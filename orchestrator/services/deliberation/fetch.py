"""
fetch.py — per-candidate history fetch for the deliberation path (V4-T18).

Fixes the starvation caveat (CAVEAT-148) for fan-out: instead of the sql_agent's
30-UUID cap + one global LIMIT (≈33 rows/sensor across 30 zones — below every
forecast model's eligibility gate), this path issues ONE query per storage table
with a PER-UUID row limit (MySQLNarrowAdapter's ROW_NUMBER partitioning), so
every candidate keeps its full window of history no matter how many neighbours
are being compared.

The adapter accessor is injectable for offline tests; live wiring uses the
process-wide adapter_registry (ref:storedAt key → adapter).
"""

from __future__ import annotations

from datetime import datetime, timedelta
from typing import Any, Callable, Dict, List, Optional, Tuple

from orchestrator.services.deliberation.candidates import Candidate
from orchestrator.services.requested_interval import STAMP, store_now
from shared.utils import get_logger

logger = get_logger(__name__)

Series = List[Tuple[str, float]]  # [(timestamp_iso, value), ...] newest-last


async def fetch_series(
    candidates: List[Candidate],
    modalities: List[str],
    window_hours: float = 24.0,
    per_uuid_limit: int = 500,
    adapter_getter: Optional[Callable[[str], Any]] = None,
    *,
    start: Optional[str] = None,
    end: Optional[str] = None,
    now: Optional[datetime] = None,
) -> Dict[str, Series]:
    """{uuid: series} for every requested modality of every candidate.

    One query per storage table (all uuids in one IN-list, per-uuid limited);
    a failed table logs and yields no rows for its uuids — the scorer records
    those candidates as insufficient-data rather than this layer inventing rows.

    `start`/`end` are an ALREADY-RESOLVED interval and are used verbatim (V12-08). This
    function used to derive its own window from `datetime.utcnow()` and pass no upper
    bound at all, so a question about a named day was answered over "the last N hours
    ending now" — and the caller that had resolved the day correctly had no way to say so.
    Falling back to a duration is kept for the phrases that genuinely are durations, on the
    STORES' clock (UTC — see requested_interval). From 2026-09-12 to 2026-09-15 this read
    the building's local clock on a false premise and started every window an hour late.
    """
    if adapter_getter is None:  # pragma: no cover - live wiring
        from orchestrator.services.adapters.registry import adapter_registry

        adapter_getter = adapter_registry.get

    by_table: Dict[str, List[str]] = {}
    for cand in candidates:
        for modality in modalities:
            handle = cand.sensors.get(modality)
            if handle and handle.get("uuid") and handle.get("stored_at"):
                by_table.setdefault(handle["stored_at"], []).append(handle["uuid"])

    if not start:
        base = now or store_now()
        start = (base - timedelta(hours=window_hours)).strftime(STAMP)
        end = None
    out: Dict[str, Series] = {}
    for table, uuids in sorted(by_table.items()):
        adapter = adapter_getter(table)
        if adapter is None:
            logger.warning(
                f"[fetch] no adapter for storedAt '{table}' — {len(uuids)} uuids skipped"
            )
            continue
        builder = getattr(adapter, "build_timeseries_query", None)
        if builder is None:
            logger.warning(f"[fetch] adapter for '{table}' has no timeseries builder — skipped")
            continue
        sql = builder(sorted(set(uuids)), "datetime", start, end, limit=per_uuid_limit)
        if not sql:
            continue
        result = await adapter.execute_query(sql)
        if not getattr(result, "success", False):
            logger.warning(f"[fetch] query failed for '{table}': {getattr(result, 'error', '?')}")
            continue
        for row in result.data or []:
            uuid_ = str(row.get("uuid", ""))
            value = row.get("value")
            ts = str(row.get("timestamp", ""))
            if not uuid_ or value is None:
                continue
            try:
                out.setdefault(uuid_, []).append((ts, float(value)))
            except (TypeError, ValueError):
                continue
    # newest-last ordering per series (queries return DESC)
    for series in out.values():
        series.sort(key=lambda p: p[0])
    logger.info(
        f"[fetch] {len(out)} series from {len(by_table)} tables "
        f"(interval={start} .. {end or 'now'}, per-uuid limit={per_uuid_limit})"
    )
    return out
