"""
AlertMonitor — background service that polls sensor data and fires threshold alerts.

Started as an asyncio task in main.py:lifespan. Runs every ALERT_POLL_INTERVAL_SECS.
Uses Redis deduplication to prevent alert storms (10-minute TTL per sensor+threshold).
"""

import asyncio
from pathlib import Path
from typing import Any, Dict, List, Optional

from shared.config import settings
from shared.utils import get_logger

logger = get_logger(__name__)


def _eval_threshold(value: float, comparator: str, threshold: float) -> bool:
    """Return True when value breaches the threshold."""
    if comparator == ">":
        return value > threshold
    if comparator == "<":
        return value < threshold
    if comparator == ">=":
        return value >= threshold
    if comparator == "<=":
        return value <= threshold
    return False


def _load_thresholds(path: str) -> List[Dict[str, Any]]:
    """Load threshold rules from YAML. Returns empty list on any error."""
    try:
        import yaml

        with open(path) as f:
            data = yaml.safe_load(f)
        return data.get("thresholds", [])
    except Exception as e:
        logger.warning(f"[AlertMonitor] Could not load thresholds from {path}: {e}")
        return []


class AlertMonitor:
    """Poll sensor readings and broadcast alerts when thresholds are breached."""

    def __init__(self, sql_agent, connection_manager, redis_client) -> None:
        self.sql_agent = sql_agent
        self.conn_mgr = connection_manager
        self.redis = redis_client
        self.interval = settings.ALERT_POLL_INTERVAL_SECS
        self._thresholds_path = settings.ALERT_THRESHOLDS_PATH

    async def run_forever(self) -> None:
        """Main loop — runs until the process exits."""
        logger.info(f"[AlertMonitor] Starting — poll every {self.interval}s")
        while True:
            try:
                await self.poll()
            except Exception as e:
                logger.error(f"[AlertMonitor] Poll error: {e}", exc_info=True)
            await asyncio.sleep(self.interval)

    async def poll(self) -> None:
        """Single poll cycle — load thresholds, fetch latest readings, fire alerts."""
        rules = _load_thresholds(self._thresholds_path)
        if not rules:
            return
        for rule in rules:
            try:
                readings = await self._fetch_latest(rule["sensor_type"])
                for sensor_id, value, zone in readings:
                    if _eval_threshold(float(value), rule["comparator"], float(rule["threshold"])):
                        await self._maybe_fire(sensor_id, value, zone, rule)
            except Exception as e:
                logger.warning(f"[AlertMonitor] Rule {rule.get('sensor_type')} failed: {e}")

    async def _fetch_latest(self, sensor_type: str) -> List[Any]:
        """Fetch latest readings from sql_agent. Returns list of (sensor_id, value, zone)."""
        try:
            result = await self.sql_agent.fetch_latest_by_type(sensor_type)
            return result if result else []
        except Exception as e:
            logger.debug(f"[AlertMonitor] fetch_latest({sensor_type}) failed: {e}")
            return []

    async def _maybe_fire(
        self, sensor_id: str, value: Any, zone: str, rule: Dict[str, Any]
    ) -> None:
        """Fire alert unless dedup key exists in Redis."""
        key = f"alert:{sensor_id}:{rule['threshold']}"
        if await self.redis.get(key):
            return
        await self.redis.setex(key, 600, "1")
        message = rule["message"].format(zone=zone, value=value)
        await self.conn_mgr.broadcast_alert(severity=rule["severity"], message=message)
        logger.info(f"[AlertMonitor] Fired alert: sensor={sensor_id} zone={zone} value={value}")
