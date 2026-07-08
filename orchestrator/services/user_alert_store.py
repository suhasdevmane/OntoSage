"""
user_alert_store.py — Per-user alert rule store (T21).

Two-tier rule system:
  Operator tier: input/<building_id>/rules.yaml (YAML, admin-managed, static)
  User tier:     Redis keys user:alert:<building_id>:<user_id>:<rule_id> (dynamic, per-user)

User-tier rules follow the same EcaRule schema as operator rules and are evaluated
by RulesEngine in the same polling loop.  Users can only see and delete their own rules.
Guest users cannot create rules (requires authenticated session).

Usage:
    store = UserAlertStore()
    rule_id = await store.create_alert("user123", "bldg1", trigger_dict, action_dict)
    rules = await store.list_alerts("user123", "bldg1")
    ok = await store.delete_alert("user123", "bldg1", rule_id)
    all_rules = await store.get_all_building_alerts("bldg1")
"""

from __future__ import annotations

import json
import uuid as _uuid_mod
from typing import Any, Dict, List, Optional

from shared.utils import get_logger

logger = get_logger(__name__)

_KEY_PREFIX = "user:alert"
_TTL_SECONDS = 60 * 60 * 24 * 90  # 90 days default


class UserAlertStore:
    """Redis-backed per-user alert rule store."""

    # ── Create ────────────────────────────────────────────────────────────────

    async def create_alert(
        self,
        user_id: str,
        building_id: str,
        trigger: Dict[str, Any],
        action: Dict[str, Any],
        name: str = "",
    ) -> str:
        """Create a user-tier alert rule. Returns the new rule_id."""
        rule_id = str(_uuid_mod.uuid4())[:8]  # short ID for conversational UX
        rule_doc: Dict[str, Any] = {
            "id": rule_id,
            "name": name or self._auto_name(trigger),
            "enabled": True,
            "trigger": trigger,
            "action": action,
            "user_id": user_id,
            "building_id": building_id,
        }
        key = self._key(building_id, user_id, rule_id)
        try:
            from orchestrator.redis_manager import redis_manager
            await redis_manager.set_cache(key, json.dumps(rule_doc), ttl=_TTL_SECONDS)
            logger.info(f"[user_alerts] created rule {rule_id} for user {user_id[:8]}...")
        except Exception as e:
            logger.warning(f"[user_alerts] Redis write failed: {e}")
        return rule_id

    # ── List ──────────────────────────────────────────────────────────────────

    async def list_alerts(self, user_id: str, building_id: str) -> List[Dict[str, Any]]:
        """Return all active alert rules for this user + building."""
        pattern = f"{_KEY_PREFIX}:{building_id}:{user_id}:*"
        rules: List[Dict[str, Any]] = []
        try:
            from orchestrator.redis_manager import redis_manager
            client = await redis_manager._ensure_client()
            if client is None:
                return rules
            keys = [k async for k in client.scan_iter(match=pattern, count=100)]
            for key in keys:
                raw = await redis_manager.get_cache(key if isinstance(key, str) else key.decode())
                if raw:
                    try:
                        rules.append(json.loads(raw))
                    except Exception:
                        pass
        except Exception as e:
            logger.debug(f"[user_alerts] list_alerts Redis error: {e}")
        return rules

    # ── Delete ────────────────────────────────────────────────────────────────

    async def delete_alert(self, user_id: str, building_id: str, rule_id: str) -> bool:
        """Delete a user alert by rule_id. Returns True if deleted."""
        key = self._key(building_id, user_id, rule_id)
        try:
            from orchestrator.redis_manager import redis_manager
            await redis_manager.delete_cache(key)
            logger.info(f"[user_alerts] deleted rule {rule_id} for user {user_id[:8]}...")
            return True
        except Exception as e:
            logger.warning(f"[user_alerts] delete failed: {e}")
            return False

    # ── Bulk (for RulesEngine) ────────────────────────────────────────────────

    async def get_all_building_alerts(self, building_id: str) -> List[Dict[str, Any]]:
        """Return all enabled user-tier alert rules for a building (across all users)."""
        pattern = f"{_KEY_PREFIX}:{building_id}:*"
        rules: List[Dict[str, Any]] = []
        try:
            from orchestrator.redis_manager import redis_manager
            client = await redis_manager._ensure_client()
            if client is None:
                return rules
            keys = [k async for k in client.scan_iter(match=pattern, count=200)]
            for key in keys:
                raw = await redis_manager.get_cache(key if isinstance(key, str) else key.decode())
                if raw:
                    try:
                        doc = json.loads(raw)
                        if doc.get("enabled", True):
                            rules.append(doc)
                    except Exception:
                        pass
        except Exception as e:
            logger.debug(f"[user_alerts] get_all_building_alerts Redis error: {e}")
        return rules

    # ── Helpers ───────────────────────────────────────────────────────────────

    @staticmethod
    def _key(building_id: str, user_id: str, rule_id: str) -> str:
        return f"{_KEY_PREFIX}:{building_id}:{user_id}:{rule_id}"

    @staticmethod
    def _auto_name(trigger: Dict[str, Any]) -> str:
        concept = trigger.get("concept") or trigger.get("sensor_uuid", "sensor")
        op = trigger.get("op", ">")
        threshold = trigger.get("threshold", 0)
        return f"{concept} {op} {threshold}"


# ── Singleton ─────────────────────────────────────────────────────────────────

_user_alert_store: Optional[UserAlertStore] = None


def get_user_alert_store() -> UserAlertStore:
    global _user_alert_store
    if _user_alert_store is None:
        _user_alert_store = UserAlertStore()
    return _user_alert_store
