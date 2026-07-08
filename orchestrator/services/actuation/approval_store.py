"""approval_store.py — Actuation approval workflow (T24).

Pending actuation commands require explicit approval from a user with control:write
before the SimDriver executes them.  Approvals expire after APPROVAL_TTL_SECONDS.

Flow:
  1. User sends "set room 5.01 setpoint to 22°C"
  2. _control_execute_node creates a pending entry → returns "Pending approval (ID: abc123)"
  3. Approver (facility_manager or admin) says "approve abc123"
  4. approval_store.approve() is called → SimDriver.set_point() runs → audit row written
  5. If not approved within APPROVAL_TTL_SECONDS → entry expires automatically (Redis TTL)

Redis key: actuation:pending:<building_id>:<approval_id>

Approval status values: pending | approved | expired | cancelled
"""

from __future__ import annotations

import json
import time
import uuid as _uuid_mod
from typing import Any, Dict, List, Optional

from shared.utils import get_logger

logger = get_logger(__name__)

try:
    from orchestrator.redis_manager import redis_manager
except Exception:
    redis_manager = None  # type: ignore[assignment]

_KEY_PREFIX = "actuation:pending"
APPROVAL_TTL_SECONDS = 15 * 60  # 15 minutes


class ActuationApprovalStore:
    """Redis-backed pending actuation approval store."""

    def _key(self, building_id: str, approval_id: str) -> str:
        return f"{_KEY_PREFIX}:{building_id}:{approval_id}"

    async def create_pending(
        self,
        *,
        building_id: str,
        user_id: str,
        point_uri: str,
        value: Any,
        reason: str = "",
    ) -> str:
        """Create a pending actuation request. Returns the approval_id."""
        approval_id = str(_uuid_mod.uuid4())[:8]
        doc: Dict[str, Any] = {
            "approval_id": approval_id,
            "building_id": building_id,
            "user_id": user_id,
            "point_uri": point_uri,
            "value": value,
            "reason": reason,
            "status": "pending",
            "created_at": time.time(),
            "approved_by": None,
            "approved_at": None,
            "audit_id": None,
        }
        key = self._key(building_id, approval_id)
        try:

            client = await redis_manager._ensure_client()
            if client:
                await client.setex(key, APPROVAL_TTL_SECONDS, json.dumps(doc))
        except Exception as exc:
            logger.warning(f"[ApprovalStore] Redis write failed: {exc}")
        return approval_id

    async def get_pending(self, building_id: str, approval_id: str) -> Optional[Dict]:
        """Fetch a pending request. Returns None if not found or expired."""
        key = self._key(building_id, approval_id)
        try:

            client = await redis_manager._ensure_client()
            if client:
                raw = await client.get(key)
                if raw:
                    return json.loads(raw)
        except Exception as exc:
            logger.warning(f"[ApprovalStore] Redis read failed: {exc}")
        return None

    async def approve(
        self,
        building_id: str,
        approval_id: str,
        *,
        approved_by: str,
        audit_id: Optional[str] = None,
    ) -> bool:
        """Mark a pending request as approved. Returns True if found and updated."""
        doc = await self.get_pending(building_id, approval_id)
        if doc is None:
            return False
        if doc["status"] != "pending":
            return False

        doc["status"] = "approved"
        doc["approved_by"] = approved_by
        doc["approved_at"] = time.time()
        if audit_id:
            doc["audit_id"] = audit_id

        key = self._key(building_id, approval_id)
        try:

            client = await redis_manager._ensure_client()
            if client:
                # Keep approved record for 24h audit trail
                await client.setex(key, 86400, json.dumps(doc))
        except Exception as exc:
            logger.warning(f"[ApprovalStore] Redis update failed: {exc}")

        return True

    async def cancel(self, building_id: str, approval_id: str, *, user_id: str) -> bool:
        """Cancel a pending request. Returns True if found and cancelled."""
        doc = await self.get_pending(building_id, approval_id)
        if doc is None:
            return False
        if doc["status"] != "pending":
            return False
        if doc["user_id"] != user_id:
            return False  # only the requester can cancel

        doc["status"] = "cancelled"
        key = self._key(building_id, approval_id)
        try:

            client = await redis_manager._ensure_client()
            if client:
                await client.setex(key, 3600, json.dumps(doc))
        except Exception as exc:
            logger.warning(f"[ApprovalStore] Cancel write failed: {exc}")
        return True

    async def list_pending(self, building_id: str) -> List[Dict]:
        """Return all pending approvals for a building."""
        pattern = f"{_KEY_PREFIX}:{building_id}:*"
        results: List[Dict] = []
        try:

            client = await redis_manager._ensure_client()
            if client:
                async for key in client.scan_iter(pattern):
                    raw = await client.get(key)
                    if raw:
                        doc = json.loads(raw)
                        if doc.get("status") == "pending":
                            results.append(doc)
        except Exception as exc:
            logger.warning(f"[ApprovalStore] list_pending failed: {exc}")
        return results


_store: Optional[ActuationApprovalStore] = None


def get_approval_store() -> ActuationApprovalStore:
    global _store
    if _store is None:
        _store = ActuationApprovalStore()
    return _store
