"""
ControlAgent — RBAC-gated building device control.

Reads intent entities from state.intermediate_results, checks user role,
dispatches to BMSAdapter, and returns a structured result dict.
Does NOT write to the database — that is done by the workflow node.
"""
from datetime import datetime, timezone
from typing import Any, Dict

from orchestrator.services.bms_adapter import BMSAdapter
from shared.models import ConversationState
from shared.utils import get_logger

logger = get_logger(__name__)

_CONTROL_ROLES = {"admin", "facility_manager", "operator"}


class ControlAgent:
    """Execute device commands with RBAC permission check."""

    def __init__(self) -> None:
        self.bms = BMSAdapter()

    async def execute_command(self, state: ConversationState) -> Dict[str, Any]:
        """Check RBAC permission and dispatch device command via BMSAdapter."""
        role = state.intermediate_results.get("user_role", "readonly")
        user_id = state.intermediate_results.get("user_id", "unknown")
        building_id = state.intermediate_results.get("building_id", "unknown")

        if role not in _CONTROL_ROLES:
            logger.warning(f"[ControlAgent] Permission denied: role={role} user={user_id}")
            return {
                "status": "denied",
                "message": (
                    f"🔒 You don't have permission to control building systems.\n"
                    f"Your current role ({role}) does not include device control.\n"
                    "Contact your facility manager if you need this access."
                ),
            }

        entities = state.intermediate_results.get("entities", [])
        device = next((e["value"] for e in entities if e.get("type") == "device"), "unknown device")
        action = next((e["value"] for e in entities if e.get("type") == "action"), "set")
        target_value = next((e["value"] for e in entities if e.get("type") == "target_value"), "")

        bms_result = await self.bms.send_command(device, action, target_value, building_id)
        log_entry = {
            "building_id": building_id,
            "device": device,
            "action": action,
            "target_value": target_value,
            "status": bms_result["status"],
            "user_id": user_id,
            "user_role": role,
            "session_id": state.conversation_id,
            "timestamp": datetime.now(timezone.utc).isoformat(),
        }
        mode_note = (
            " (simulation mode — no real BMS configured)" if bms_result.get("mode") == "simulation" else ""
        )
        message = (
            f"✅ Command acknowledged{mode_note}: {device} → {action}"
            + (f"({target_value})" if target_value else "")
            + f"\nLogged at: {log_entry['timestamp']}"
        )
        return {**bms_result, "log_entry": log_entry, "message": message}
