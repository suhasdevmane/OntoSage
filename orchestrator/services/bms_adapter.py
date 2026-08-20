"""
BMS (Building Management System) adapter.

If settings.BMS_ENDPOINT is empty, all commands are simulated — logged but not sent.
If BMS_ENDPOINT is set, commands are POSTed as JSON to that URL.
"""

import asyncio
from typing import Any, Dict

import httpx

from shared.config import settings
from shared.utils import get_logger

logger = get_logger(__name__)


class BMSAdapter:
    """Send device control commands to a BMS or simulate them."""

    async def send_command(
        self,
        device: str,
        action: str,
        target_value: str,
        building_id: str,
    ) -> Dict[str, Any]:
        """
        Execute a device command.

        Returns a dict with keys: status, device, action, value, mode.
        status is 'simulated', 'executed', or 'failed'.
        """
        if not settings.BMS_ENDPOINT:
            logger.info(
                f"[BMS SIMULATE] building={building_id} device={device!r} "
                f"action={action!r} value={target_value!r}"
            )
            return {
                "status": "simulated",
                "device": device,
                "action": action,
                "value": target_value,
                "mode": "simulation",
            }

        payload = {
            "building_id": building_id,
            "device": device,
            "action": action,
            "value": target_value,
        }
        try:
            async with httpx.AsyncClient(timeout=10.0) as client:
                resp = await client.post(settings.BMS_ENDPOINT, json=payload)
                resp.raise_for_status()
                logger.info(
                    f"[BMS EXECUTE] {device} → {action}({target_value}) HTTP {resp.status_code}"
                )
                return {
                    "status": "executed",
                    "device": device,
                    "action": action,
                    "value": target_value,
                    "mode": "live",
                }
        except Exception as e:
            logger.error(f"[BMS FAILED] {e}", exc_info=True)
            return {
                "status": "failed",
                "device": device,
                "action": action,
                "value": target_value,
                "error": str(e),
                "mode": "live",
            }
