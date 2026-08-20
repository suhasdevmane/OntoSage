"""
ConnectionManager — registry of active WebSocket connections.

AlertMonitor uses this to push system alerts to all connected clients.
The /stream WebSocket endpoint registers/unregisters itself here.
"""

import asyncio
from datetime import datetime, timezone
from typing import Set

from fastapi import WebSocket

from shared.utils import get_logger

logger = get_logger(__name__)


class ConnectionManager:
    """Thread-safe registry of active WebSocket connections."""

    def __init__(self) -> None:
        self._connections: Set[WebSocket] = set()

    def register(self, ws: WebSocket) -> None:
        """Add a WebSocket to the active connection set."""
        self._connections.add(ws)
        logger.debug(f"[ConnectionManager] registered WS — total={len(self._connections)}")

    def unregister(self, ws: WebSocket) -> None:
        """Remove a WebSocket from the active connection set."""
        self._connections.discard(ws)
        logger.debug(f"[ConnectionManager] unregistered WS — total={len(self._connections)}")

    async def broadcast_alert(self, severity: str, message: str) -> None:
        """Send a system alert to all active WebSocket connections."""
        ts = datetime.now(timezone.utc).strftime("%H:%M:%S UTC")
        severity_emoji = "🚨" if severity == "critical" else "⚠️"
        full_message = (
            f"{severity_emoji} [SYSTEM ALERT — {ts}]\n"
            f"{message}\n\n"
            "You can ask me for more details or to export data about this sensor."
        )
        payload = {"type": "system_alert", "severity": severity, "data": full_message}
        dead: Set[WebSocket] = set()
        for ws in list(self._connections):
            try:
                await ws.send_json(payload)
            except Exception:
                dead.add(ws)
        for ws in dead:
            self.unregister(ws)

    @property
    def active_count(self) -> int:
        """Return the number of currently registered connections."""
        return len(self._connections)
