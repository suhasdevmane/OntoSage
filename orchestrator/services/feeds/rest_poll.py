"""
feeds/rest_poll.py — HTTP REST polling adapter.

Polls a JSON endpoint at spec.url on each poll() call.
Authentication via Bearer token from spec.auth_env (env-var name, never literal).
JSON extraction via spec.field_map: {json_key_path -> metric_name}.

field_map examples:
  {"temperature": "value"}           # top-level key
  {"data.sensors.0.temp": "value"}   # dot-path into nested structure
  {"readings.temp": "temp_c", "readings.humidity": "humidity_pct"}  # multi-metric
"""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any, Dict, List, Optional

from shared.utils import get_logger

from orchestrator.services.feeds.base import FeedAdapter, FeedRecord, FeedSpec

try:
    import httpx as _httpx
except ImportError:
    _httpx = None  # type: ignore[assignment]

logger = get_logger(__name__)

_DEFAULT_TIMEOUT = 15.0


def _extract_by_dotpath(data: Any, path: str) -> Optional[float]:
    """Traverse a nested JSON structure using dot-separated key path.

    Supports dict keys and list indices.  Returns None when path not found.
    """
    for part in path.split("."):
        if data is None:
            return None
        if isinstance(data, dict):
            data = data.get(part)
        elif isinstance(data, list):
            try:
                data = data[int(part)]
            except (ValueError, IndexError):
                return None
        else:
            return None
    try:
        return float(data)
    except (TypeError, ValueError):
        return None


class RestPollAdapter(FeedAdapter):
    """Poll a JSON REST endpoint and extract one or more numeric values."""

    def __init__(self, spec: FeedSpec, *, timeout: float = _DEFAULT_TIMEOUT) -> None:
        super().__init__(spec)
        self._timeout = timeout

    async def poll(self) -> List[FeedRecord]:
        if not self.spec.url:
            logger.warning(f"[feeds] {self.spec.id}: rest_poll requires url")
            return []

        if _httpx is None:
            logger.error("[feeds] httpx not installed — rest_poll unavailable")
            return []

        headers: Dict[str, str] = {}
        token = self.spec.auth_header()
        if token:
            headers["Authorization"] = f"Bearer {token}"

        try:
            async with _httpx.AsyncClient(timeout=self._timeout) as client:
                resp = await client.get(self.spec.url, headers=headers)
                resp.raise_for_status()
                payload = resp.json()
        except _httpx.HTTPStatusError as e:
            logger.warning(f"[feeds] {self.spec.id} HTTP {e.response.status_code}: {self.spec.url}")
            return []
        except _httpx.RequestError as e:
            # str(e) is empty for some httpx errors — repr always identifies the cause
            logger.warning(f"[feeds] {self.spec.id} request error: {e!r}")
            return []
        except Exception as e:
            logger.error(f"[feeds] {self.spec.id} unexpected error: {e}", exc_info=True)
            return []

        ts = datetime.now(tz=timezone.utc)
        records: List[FeedRecord] = []

        if not self.spec.field_map:
            # No mapping: try to read a single numeric value from top-level "value" key
            val = _extract_by_dotpath(payload, "value")
            if val is not None:
                records.append(self._make_record(val, "value", ts))
        else:
            for source_path, metric_name in self.spec.field_map.items():
                val = _extract_by_dotpath(payload, source_path)
                if val is not None:
                    records.append(self._make_record(val, metric_name, ts))
                else:
                    logger.debug(f"[feeds] {self.spec.id} field '{source_path}' not found in response")

        return records
