"""
ControlAgent — RBAC-gated building device control (T25).

T25 upgrade: routes through ActuationRegistry when a driver is configured.
  - driver present + user has control:write  → create pending approval
  - driver absent  OR  user lacks permission  → decline with honest explanation
  - "approve <id>" pattern in query          → approve pending actuation

Legacy BMSAdapter path is preserved as the fallback when ActuationRegistry
is not available (import guard).
"""

from __future__ import annotations

import re
from datetime import datetime, timezone
from typing import Any, Dict

from shared.models import ConversationState
from shared.utils import get_logger

logger = get_logger(__name__)

_CONTROL_ROLES = {"admin", "facility_manager", "operator"}
# Tolerate co-reference rewriting: "approve 606ba770" gets expanded by the
# rewriter to "approve the command with ID 606ba770 ..." — allow up to 40
# chars between the verb and the hex id (fix 2026-06-12).
_APPROVE_RE = re.compile(r"\bapprove\b.{0,40}?\b([a-f0-9]{6,8})\b", re.IGNORECASE | re.DOTALL)


def _entity_value(entities: Any, etype: str, default: str = "") -> str:
    """Extract an entity value by type, tolerating both dict and plain-string
    entity shapes (the dialogue LLM emits either; crash fix 2026-06-12)."""
    for e in entities or []:
        if isinstance(e, dict) and e.get("type") == etype:
            return str(e.get("value", default))
    return default


try:
    from orchestrator.services.actuation.registry import get_actuation_registry
    from orchestrator.services.actuation.approval_store import get_approval_store

    _ACTUATION_AVAILABLE = True
except Exception:
    _ACTUATION_AVAILABLE = False


class ControlAgent:
    """Execute device commands with RBAC permission check."""

    def __init__(self) -> None:
        from orchestrator.services.bms_adapter import BMSAdapter

        self.bms = BMSAdapter()

    async def execute_command(self, state: ConversationState) -> Dict[str, Any]:
        """Check RBAC permission and dispatch device command.

        T25 routing logic:
        1. If query matches "approve <id>" → run approval flow.
        2. If building has a sim driver AND user has control:write → queue pending approval.
        3. Otherwise → decline with honest T22-style explanation.
        """
        role = state.intermediate_results.get("user_role", "readonly")
        user_id = state.intermediate_results.get("user_id", "unknown")
        # building_id lives on the state model; the intermediate_results key is
        # never populated (fix 2026-06-12 — the old "bldg1" default would have
        # consulted the wrong building's actuation config after a swap).
        building_id = (
            getattr(state, "building_id", None)
            or state.intermediate_results.get("building_id")
            or "bldg1"
        )
        # "user_query" is not a populated key — fall back to the actual message
        # (fix 2026-06-12: raw_query was always "", so "approve <id>" never matched
        # and the T25 approval round-trip was unreachable).
        raw_query = (
            state.intermediate_results.get("user_query", "")
            or (state.messages[-1].content if state.messages else "")
            or (state.user_message or "")
        )

        # ── Check for "approve <id>" pattern ──────────────────────────────────
        approve_match = _APPROVE_RE.search(raw_query)
        if approve_match and _ACTUATION_AVAILABLE:
            approval_id = approve_match.group(1)
            return await self._handle_approval(building_id, approval_id, user_id, role)

        # ── Check actuation registry ──────────────────────────────────────────
        if _ACTUATION_AVAILABLE:
            try:
                registry = get_actuation_registry()
                driver = registry.driver_for(building_id)
                caps = await driver.capabilities()
            except Exception as exc:
                logger.warning(f"[ControlAgent] ActuationRegistry error: {exc}")
                caps = []
        else:
            caps = []

        has_driver = len(caps) > 0
        has_permission = "control:write" in (
            state.intermediate_results.get("user_permissions", set()) or set()
        ) or role in {"admin", "facility_manager"}

        if has_driver and has_permission:
            return await self._queue_pending_approval(state, building_id, user_id, caps)

        # ── Decline path — build honest explanation ───────────────────────────
        if not has_permission:
            message = (
                f"You don't have permission to control building systems "
                f"(role: {role}). Facility managers and administrators can "
                f"make configuration changes. Contact your facility manager "
                f"if you need this access."
            )
        elif not has_driver:
            message = (
                "Physical actuation is not enabled for this building. "
                "The system can monitor conditions and send alerts (via ECA rules) "
                "but cannot directly adjust setpoints without a configured actuation driver. "
                "If you'd like to set up an alert instead, just ask."
            )
        else:
            message = (
                "This control action cannot be completed. "
                "Check the building configuration and your user permissions."
            )

        entities = state.intermediate_results.get("entities", [])
        device = _entity_value(entities, "device", "device")
        action = _entity_value(entities, "action", "action")

        log_entry = {
            "building_id": building_id,
            "device": device,
            "action": action,
            "target_value": "",
            "status": "denied",
            "user_id": user_id,
            "user_role": role,
            "session_id": state.conversation_id,
            "timestamp": datetime.now(timezone.utc).isoformat(),
        }
        return {"status": "denied", "message": message, "log_entry": log_entry}

    async def _queue_pending_approval(
        self, state: ConversationState, building_id: str, user_id: str, writable_caps: list
    ) -> Dict[str, Any]:
        """Create a pending actuation approval and return a confirmation message."""
        entities = state.intermediate_results.get("entities", [])
        device = _entity_value(entities, "device")
        target_value = _entity_value(entities, "target_value")

        # Best-effort point URI matching: pick the first writable point whose URI
        # contains any token from the device entity.  Fall back to first point.
        point_uri = writable_caps[0]
        if device:
            tokens = device.lower().split()
            for cap in writable_caps:
                if any(t in cap.lower() for t in tokens if len(t) > 2):
                    point_uri = cap
                    break

        approval_store = get_approval_store()
        approval_id = await approval_store.create_pending(
            building_id=building_id,
            user_id=user_id,
            point_uri=point_uri,
            value=target_value or "as specified",
            reason=(
                "User request: "
                + (
                    state.intermediate_results.get("user_query", "")
                    or (state.messages[-1].content if state.messages else "")
                    or (state.user_message or "")
                )
            ),
        )

        log_entry = {
            "building_id": building_id,
            "device": device,
            "action": "set_point",
            "target_value": str(target_value),
            "status": "pending_approval",
            "user_id": user_id,
            "user_role": state.intermediate_results.get("user_role", ""),
            "session_id": state.conversation_id,
            "timestamp": datetime.now(timezone.utc).isoformat(),
        }
        message = (
            f"Command queued for approval (ID: **{approval_id}**).\n"
            f"Target: `{point_uri}` → `{target_value}`\n\n"
            "A facility manager or administrator can approve this by typing:\n"
            f"> `approve {approval_id}`\n\n"
            "The request expires in 15 minutes if not approved."
        )
        return {
            "status": "pending_approval",
            "approval_id": approval_id,
            "message": message,
            "log_entry": log_entry,
        }

    async def _handle_approval(
        self, building_id: str, approval_id: str, user_id: str, role: str
    ) -> Dict[str, Any]:
        """Approve a pending actuation and execute via sim driver."""
        if role not in {"admin", "facility_manager"}:
            return {
                "status": "denied",
                "message": (
                    "Only facility managers and administrators can approve " "actuation commands."
                ),
            }

        approval_store = get_approval_store()
        pending = await approval_store.get_pending(building_id, approval_id)

        if pending is None:
            return {
                "status": "error",
                "message": (
                    f"No pending request found with ID `{approval_id}`. "
                    "It may have expired (15-minute limit) or already been approved."
                ),
            }

        # Execute via sim driver
        registry = get_actuation_registry()
        driver = registry.driver_for(building_id)
        result = await driver.set_point(
            pending["point_uri"],
            pending["value"],
            user_id=user_id,
            reason=f"Approved by {user_id}",
        )

        await approval_store.approve(
            building_id, approval_id, approved_by=user_id, audit_id=result.audit_id
        )

        if result.success:
            return {
                "status": "approved",
                "audit_id": result.audit_id,
                "message": (
                    f"Command approved and executed.\n"
                    f"{result.message}\n"
                    f"Audit ID: `{result.audit_id}`"
                ),
            }
        else:
            return {
                "status": "error",
                "message": f"Approval granted but execution failed: {result.error}",
            }
