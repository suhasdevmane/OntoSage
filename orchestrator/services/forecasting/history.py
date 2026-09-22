# -*- coding: utf-8 -*-
"""Fetch the history a forecast needs, rather than reusing whatever the question happened to read.

WHY THIS EXISTS. "Will the CO2 in room 5.01 exceed 1000 ppm tomorrow afternoon?" answered
"Forecast not available -- too_sparse_after_resample". The store held 27,621 readings for that
sensor spanning 73 days; the forecast saw about thirty MINUTES of them. The reading lane fetches
what the QUESTION asks about -- "right now" means the newest rows -- and the forecast then consumed
that same fetch. Resampled to the hourly frequency a next-day forecast needs, thirty minutes of
readings collapse to a single bucket, and one bucket is not a series.

So a forecast asks for its own window. The lookback is derived from the horizon rather than fixed:
predicting the next hour needs hours of history, predicting next month needs months, and asking for
months of rows to predict an hour is a slow way to get the same answer.

BUILDING-AGNOSTIC. Nothing here names a building, a sensor or a table: uuids and their storage keys
come from the caller, and the adapter registry resolves where each one lives.

HONESTY. A failure returns no rows, never invented ones. The caller keeps whatever it already had,
so a forecast that cannot be grounded still declines instead of predicting from nothing.
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from typing import Any, Dict, List, Optional, Sequence

from shared.utils import get_logger

logger = get_logger(__name__)

#: Pandas frequency alias -> hours, for the horizons the parser produces.
_FREQ_HOURS = {"15min": 0.25, "30min": 0.5, "1h": 1.0, "3h": 3.0, "6h": 6.0, "12h": 12.0,
               "1d": 24.0, "1w": 168.0}

#: How many times the forecast span to look back. A model fitted on one span of history to predict
#: the same span forward has no seasonality to learn from; several spans is the usual minimum.
LOOKBACK_MULTIPLE = 8.0

#: Floor and ceiling on that lookback. The floor keeps a next-hour forecast from being fitted on
#: eight hours alone; the ceiling keeps a next-month forecast from reading a year of rows.
MIN_LOOKBACK_HOURS = 72.0
MAX_LOOKBACK_HOURS = 24.0 * 90

#: Rows per sensor. Sized so a long window still resamples cleanly: at one reading every few
#: minutes, 20,000 rows is several weeks.
DEFAULT_ROW_LIMIT = 20000


def _as_rows(result: Any) -> List[Dict[str, Any]]:
    """Adapters return a QueryResult, a list, or a dict wrapping one. Take the rows from any."""
    if result is None:
        return []
    for attr in ("data", "rows", "results"):
        inner = getattr(result, attr, None)
        if isinstance(inner, list):
            return [r for r in inner if isinstance(r, dict)]
    if isinstance(result, dict):
        for k in ("data", "rows", "results"):
            inner = result.get(k)
            if isinstance(inner, list):
                return [r for r in inner if isinstance(r, dict)]
    if isinstance(result, list):
        return [r for r in result if isinstance(r, dict)]
    return []


def lookback_hours(freq: str, n_steps: int) -> float:
    """How far back to read, from the horizon being predicted."""
    step = _FREQ_HOURS.get(str(freq).lower(), 1.0)
    span = max(step * max(1, int(n_steps)), step)
    return max(MIN_LOOKBACK_HOURS, min(span * LOOKBACK_MULTIPLE, MAX_LOOKBACK_HOURS))


def window(freq: str, n_steps: int, now: Optional[datetime] = None) -> tuple:
    """(start, end) as store-clock strings. The store is UTC (BUG-403)."""
    end = now or datetime.now(timezone.utc)
    if end.tzinfo is None:
        end = end.replace(tzinfo=timezone.utc)
    start = end - timedelta(hours=lookback_hours(freq, n_steps))
    fmt = "%Y-%m-%d %H:%M:%S"
    return start.strftime(fmt), end.strftime(fmt)


#: Returned for a sensor whose store is not known from the caller's map.
_UNKNOWN = "\x00unknown"


def _group_by_store(uuids: Sequence[str], storage_map: Dict[str, str], registry: Any) -> Dict[str, List[str]]:
    """{store key: uuids}. A sensor whose store is unknown is grouped under ``_UNKNOWN``.

    THERE IS NO ADAPTER CALLED "default". The registry is keyed by the stores the building
    declares -- database1, co2_data, temperature_data and so on -- so grouping unknown sensors
    under "default" and looking that up found nothing, and the forecast read zero rows about a
    sensor holding 412,227 of them. Unknown sensors are searched for instead.
    """
    grouped: Dict[str, List[str]] = {}
    known = set()
    try:
        known = set(registry._adapters.keys())
    except Exception:
        pass
    for uuid in uuids:
        storage = (storage_map or {}).get(uuid)
        key = _UNKNOWN
        if storage:
            try:
                resolved = registry._resolve_storage_key(storage)
                if resolved in known:
                    key = resolved
            except Exception:
                pass
        grouped.setdefault(key, []).append(uuid)
    return grouped


def _adapters_to_try(key: str, registry: Any) -> List[Any]:
    """The adapter for a known store, or every adapter when the store is unknown.

    Searching is bounded by the number of stores the building declares and stops at the first
    that returns rows, so the usual case is one or two queries.
    """
    try:
        adapters = registry._adapters
    except Exception:
        return []
    if key != _UNKNOWN and key in adapters:
        return [adapters[key]]
    return list(adapters.values())


async def fetch_history(
    uuids: Sequence[str],
    freq: str,
    n_steps: int,
    *,
    storage_map: Optional[Dict[str, str]] = None,
    registry: Any = None,
    row_limit: int = DEFAULT_ROW_LIMIT,
    now: Optional[datetime] = None,
) -> List[Dict[str, Any]]:
    """``[{timestamp, uuid, value}, ...]`` over the window this horizon needs. Never raises."""
    if not uuids:
        return []
    if registry is None:
        from orchestrator.services.adapters.registry import adapter_registry as registry

    start, end = window(freq, n_steps, now=now)
    out: List[Dict[str, Any]] = []
    for key, group in _group_by_store(list(uuids), storage_map or {}, registry).items():
        for adapter in _adapters_to_try(key, registry):
            builder = getattr(adapter, "build_timeseries_query", None)
            if builder is None:
                continue
            ts_col = getattr(adapter, "timestamp_column", None) or "datetime"
            try:
                sql = builder(list(group), ts_col, start, end, limit=row_limit)
                if not sql:
                    continue
                rows = await adapter.execute_query(sql)
            except Exception as exc:  # one store failing must not lose the others
                logger.debug("[forecast-history] %s read failed: %s", type(adapter).__name__, exc)
                continue
            got = []
            for r in _as_rows(rows):
                ts = r.get("timestamp") or r.get("datetime") or r.get(ts_col)
                val = r.get("value")
                uid = r.get("uuid") or r.get("sensor_uuid")
                if ts is None or val is None:
                    continue
                got.append({"timestamp": ts, "uuid": uid, "value": val})
            if got:
                out.extend(got)
                break          # this store holds them; stop searching for this group
    logger.info(
        "[forecast-history] %d rows for %d sensor(s) over %s .. %s (horizon %s x%d)",
        len(out), len(uuids), start, end, freq, n_steps,
    )
    return out
