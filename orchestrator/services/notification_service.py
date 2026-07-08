"""
notification_service.py — Multi-channel notification dispatch (T33).

Channels are configured per-building in input/<building_id>/channels.yaml.
The default 'log' channel is always present and cannot be removed.

Supported channel types:
  log      — writes to the application logger (always enabled)
  webhook  — HTTP POST JSON payload to a URL (env-var auth header optional)
  smtp     — email via SMTP (credentials via env vars; NOT yet implemented — placeholder)

STRICT_SECRETS compliance:
  - auth_header_env names an env var; never a literal token in YAML.
  - Credentials are loaded at dispatch time; never stored in memory.

Channel YAML schema:
  channels:
    - id: my_channel
      type: log | webhook | smtp
      enabled: true
      # webhook:
      url: "https://..."
      auth_header_env: "MY_WEBHOOK_TOKEN"   # optional: env var name for Authorization header
      # smtp (future):
      smtp_host: ...
      smtp_port: 587
      from_addr_env: "SMTP_FROM"
      to_addr: "recipient@example.com"

Usage:
  from orchestrator.services.notification_service import get_notification_service
  svc = get_notification_service()
  await svc.dispatch(title="...", message="...", severity="warning", building_id="bldg1")
"""

from __future__ import annotations

import os
from pathlib import Path
from typing import Any, Dict, List, Optional

import httpx
import yaml

from shared.utils import get_logger

logger = get_logger(__name__)

_YAML_SEARCH_PATHS = [
    "/app/input/{building_id}/channels.yaml",
    "input/{building_id}/channels.yaml",
]

_DEFAULT_LOG_CHANNEL: Dict[str, Any] = {
    "id": "log",
    "type": "log",
    "enabled": True,
}


class NotificationService:
    """Dispatch notifications through configured channels.

    Args:
        building_id: Used to locate channels.yaml.
        _channels_override: Inject channel dicts directly (for testing).
    """

    def __init__(
        self,
        building_id: str,
        *,
        _channels_override: Optional[List[Dict[str, Any]]] = None,
    ) -> None:
        self._building_id = building_id
        self._channels: List[Dict[str, Any]] = []
        if _channels_override is not None:
            self._channels = _channels_override
        else:
            self._load_channels()

    # ── Loading ───────────────────────────────────────────────────────────────

    def _load_channels(self) -> None:
        """Load channels.yaml; always include the log channel."""
        self._channels = [dict(_DEFAULT_LOG_CHANNEL)]  # log always present

        yaml_path = self._find_yaml()
        if yaml_path is None:
            logger.debug(
                f"[notifications] no channels.yaml for '{self._building_id}' — log channel only"
            )
            return

        try:
            data = yaml.safe_load(yaml_path.read_text(encoding="utf-8")) or {}
        except Exception as e:
            logger.warning(f"[notifications] could not parse {yaml_path}: {e}")
            return

        for ch in data.get("channels", []):
            if ch.get("id") == "log":
                continue  # do not duplicate the built-in log channel
            if ch.get("enabled", True):
                self._channels.append(ch)
                logger.info(
                    f"[notifications] loaded channel id={ch.get('id')} type={ch.get('type')}"
                )

    @property
    def channels(self) -> List[Dict[str, Any]]:
        return list(self._channels)

    def has_channel_type(self, channel_type: str) -> bool:
        """Return True if any enabled channel of the given type is configured."""
        return any(c.get("type") == channel_type for c in self._channels if c.get("enabled", True))

    # ── Dispatch ──────────────────────────────────────────────────────────────

    async def dispatch(
        self,
        title: str,
        message: str,
        severity: str = "info",
        building_id: Optional[str] = None,
        source: str = "system",
        extra: Optional[Dict[str, Any]] = None,
    ) -> int:
        """Send notification to all enabled channels. Returns count of successful dispatches."""
        payload: Dict[str, Any] = {
            "title": title,
            "message": message,
            "severity": severity,
            "building_id": building_id or self._building_id,
            "source": source,
            **(extra or {}),
        }
        ok = 0
        for ch in self._channels:
            if not ch.get("enabled", True):
                continue
            try:
                dispatched = await self._send(ch, payload)
                if dispatched:
                    ok += 1
            except Exception as e:
                logger.error(
                    f"[notifications] channel {ch.get('id','?')} dispatch error: {e}",
                    exc_info=True,
                )
        return ok

    async def _send(self, channel: Dict[str, Any], payload: Dict[str, Any]) -> bool:
        ch_type = channel.get("type", "log")

        if ch_type == "log":
            return await self._send_log(channel, payload)
        elif ch_type == "webhook":
            return await self._send_webhook(channel, payload)
        elif ch_type == "smtp":
            return await self._send_smtp(channel, payload)
        else:
            logger.warning(
                f"[notifications] unknown channel type '{ch_type}' for channel {channel.get('id')}"
            )
            return False

    async def _send_log(self, channel: Dict[str, Any], payload: Dict[str, Any]) -> bool:
        severity = payload.get("severity", "info")
        msg = f"[NOTIFY] [{severity.upper()}] {payload.get('title')}: {payload.get('message')}"
        if severity in ("critical", "error"):
            logger.error(msg)
        elif severity == "warning":
            logger.warning(msg)
        else:
            logger.info(msg)
        return True

    async def _send_webhook(self, channel: Dict[str, Any], payload: Dict[str, Any]) -> bool:
        url = channel.get("url")
        if not url:
            logger.warning(f"[notifications] webhook channel {channel.get('id')} has no url")
            return False

        headers: Dict[str, str] = {"Content-Type": "application/json"}
        auth_env = channel.get("auth_header_env")
        if auth_env:
            token = os.environ.get(auth_env)
            if token:
                headers["Authorization"] = token

        try:
            async with httpx.AsyncClient(timeout=10.0) as client:
                resp = await client.post(url, json=payload, headers=headers)
                if resp.status_code < 300:
                    logger.info(
                        f"[notifications] webhook {channel.get('id')} -> {resp.status_code}"
                    )
                    return True
                else:
                    logger.warning(
                        f"[notifications] webhook {channel.get('id')} -> {resp.status_code}: "
                        f"{resp.text[:200]}"
                    )
                    return False
        except Exception as e:
            logger.warning(f"[notifications] webhook {channel.get('id')} failed: {e}")
            return False

    async def _send_smtp(self, channel: Dict[str, Any], payload: Dict[str, Any]) -> bool:
        # SMTP dispatch is a placeholder — requires aiosmtplib or smtplib executor.
        # Configured now so building operators can pre-configure smtp channels;
        # actual sending is a Phase H extension.
        logger.info(
            f"[notifications] smtp channel {channel.get('id')}: "
            f"SMTP dispatch not yet implemented — would send to {channel.get('to_addr')}"
        )
        return False

    # ── Helpers ───────────────────────────────────────────────────────────────

    def _find_yaml(self) -> Optional[Path]:
        for tmpl in _YAML_SEARCH_PATHS:
            p = Path(tmpl.format(building_id=self._building_id))
            if p.exists():
                return p
        return None


# ── Singleton ─────────────────────────────────────────────────────────────────

_notification_service: Optional[NotificationService] = None


def get_notification_service(building_id: Optional[str] = None) -> NotificationService:
    """Return the singleton NotificationService, initialised on first call."""
    global _notification_service
    if _notification_service is None:
        from shared.config import settings
        bid = building_id or settings.BUILDING_ID
        _notification_service = NotificationService(bid)
    return _notification_service


def reset_notification_service() -> None:
    """Reset the singleton (for testing)."""
    global _notification_service
    _notification_service = None
