"""
T35 — Per-user comfort preference store.

Stores explicit user-stated preferences ('I prefer 22–24°C') in Redis keyed
by user_id + category. Preferences overlay comfort recipe thresholds in the
analytics node so answers reference the user's personal range, not just ASHRAE.

Key format:  user:pref:{user_id}:{category}
TTL: 365 days (refreshed on update).
Privacy: scan only matches the requesting user's own prefix.
"""

from __future__ import annotations

import json
import logging
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional

logger = logging.getLogger(__name__)

_KEY_PREFIX = "user:pref"
_TTL_SECONDS = 60 * 60 * 24 * 365  # 1 year

# Known preference categories and their canonical units
_CATEGORY_META: Dict[str, Dict[str, str]] = {
    "temperature_comfort": {"unit": "°C", "label": "Temperature comfort range"},
    "humidity_comfort": {"unit": "%RH", "label": "Humidity comfort range"},
    "co2_comfort": {"unit": "ppm", "label": "CO2 comfort threshold"},
    "noise_comfort": {"unit": "dB", "label": "Noise comfort level"},
    "illuminance_comfort": {"unit": "lux", "label": "Lighting comfort level"},
}

# Natural-language → category mapping (used for detection in dialogue node)
CATEGORY_KEYWORDS: Dict[str, str] = {
    "temperature": "temperature_comfort",
    "warm": "temperature_comfort",
    "warmer": "temperature_comfort",
    "cooler": "temperature_comfort",
    "thermal": "temperature_comfort",
    "hot": "temperature_comfort",
    "cold": "temperature_comfort",
    "humid": "humidity_comfort",
    "humidity": "humidity_comfort",
    "damp": "humidity_comfort",
    "co2": "co2_comfort",
    "air quality": "co2_comfort",
    "stuffy": "co2_comfort",
    "noise": "noise_comfort",
    "quiet": "noise_comfort",
    "loud": "noise_comfort",
    "light": "illuminance_comfort",
    "bright": "illuminance_comfort",
    "dark": "illuminance_comfort",
    "lux": "illuminance_comfort",
}


class UserPreferenceStore:
    """Redis-backed per-user comfort preference store."""

    async def set_preference(
        self,
        user_id: str,
        category: str,
        *,
        pref_min: Optional[float] = None,
        pref_max: Optional[float] = None,
        raw: str = "",
    ) -> bool:
        """Store or update a preference. Returns True on success."""
        try:
            from orchestrator.redis_manager import redis_manager

            key = f"{_KEY_PREFIX}:{user_id}:{category}"
            meta = _CATEGORY_META.get(category, {"unit": "", "label": category})
            doc = {
                "user_id": user_id,
                "category": category,
                "label": meta["label"],
                "unit": meta["unit"],
                "pref_min": pref_min,
                "pref_max": pref_max,
                "raw": raw,
                "updated_at": datetime.now(timezone.utc).isoformat(),
            }
            await redis_manager.set_cache(key, json.dumps(doc), ttl=_TTL_SECONDS)
            logger.info(
                f"[user_pref] stored: user={user_id} category={category} "
                f"min={pref_min} max={pref_max}"
            )
            return True
        except Exception as exc:
            logger.warning(f"[user_pref] set_preference failed: {exc}")
            return False

    async def get_preference(self, user_id: str, category: str) -> Optional[Dict[str, Any]]:
        """Retrieve a single preference. Returns None if not set."""
        try:
            from orchestrator.redis_manager import redis_manager

            key = f"{_KEY_PREFIX}:{user_id}:{category}"
            raw = await redis_manager.get_cache(key)
            if raw:
                return json.loads(raw)
            return None
        except Exception as exc:
            logger.warning(f"[user_pref] get_preference failed: {exc}")
            return None

    async def list_preferences(self, user_id: str) -> List[Dict[str, Any]]:
        """List all preferences for a user."""
        try:
            from orchestrator.redis_manager import redis_manager

            pattern = f"{_KEY_PREFIX}:{user_id}:*"
            results = []
            _client = await redis_manager._ensure_client()
            async for key in _client.scan_iter(match=pattern):
                raw = await _client.get(key)
                if raw:
                    try:
                        results.append(json.loads(raw))
                    except Exception:
                        pass
            return sorted(results, key=lambda d: d.get("category", ""))
        except Exception as exc:
            logger.warning(f"[user_pref] list_preferences failed: {exc}")
            return []

    async def delete_preference(self, user_id: str, category: str) -> bool:
        """Delete a specific preference. Returns True if it existed."""
        try:
            from orchestrator.redis_manager import redis_manager

            key = f"{_KEY_PREFIX}:{user_id}:{category}"
            deleted = await redis_manager.delete_cache(key)
            logger.info(
                f"[user_pref] deleted: user={user_id} category={category} existed={deleted}"
            )
            return bool(deleted)
        except Exception as exc:
            logger.warning(f"[user_pref] delete_preference failed: {exc}")
            return False

    async def delete_all_preferences(self, user_id: str) -> int:
        """Delete ALL preferences for a user. Returns count deleted."""
        try:
            from orchestrator.redis_manager import redis_manager

            pattern = f"{_KEY_PREFIX}:{user_id}:*"
            count = 0
            _client = await redis_manager._ensure_client()
            async for key in _client.scan_iter(match=pattern):
                await _client.delete(key)
                count += 1
            logger.info(f"[user_pref] deleted all: user={user_id} count={count}")
            return count
        except Exception as exc:
            logger.warning(f"[user_pref] delete_all_preferences failed: {exc}")
            return 0


# ── Module-level singleton ────────────────────────────────────────────────────

_store: Optional[UserPreferenceStore] = None


def get_user_preference_store() -> UserPreferenceStore:
    global _store
    if _store is None:
        _store = UserPreferenceStore()
    return _store
