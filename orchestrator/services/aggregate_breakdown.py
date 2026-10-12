"""A figure PER DAY or PER HOUR, reduced in the store (BUG-1563).

"Give me the daily average temperature in room 4.18 for the last 7 days" was claimed by the
aggregate lane and answered with ONE mean for the whole week. The relevance gate objected, rightly
("does not provide daily averages, only a single period average"), and replaced it with a decline,
so the reader got nothing for a question the building answers easily. A breakdown question is a
different question from a summary: it asks for one figure per period.

The store already knows how to do this. `aggregate_lane.run_buckets` (built for v2's series
operation, C5) reduces each sensor into fixed time buckets with a GROUP BY, so a week of 5-minute
readings never comes back as rows and the 1,000-row cap that clips the row-level path does not
apply. This module chooses the bucket, aligns it to the building's calendar day or clock hour,
pools the sensors bucket by bucket (total over count, not a mean of means), and writes the table.

Deliberately narrow:
- only an INTENSIVE quantity (a reading averaged over time). A total per day of an energy meter is
  a different computation, and the `total` path keeps those questions;
- one unit family, the largest, so two quantities are never averaged together (BUG-521);
- at most 48 hourly or 62 daily rows, so the answer stays a table a person can read. A longer
  breakdown is left to the lanes that answered it before.

Building-agnostic: nothing here names a room, a sensor or a store.
"""

from __future__ import annotations

import re
from datetime import datetime, timedelta
from typing import Any, Callable, Dict, List, Optional, Sequence, Tuple

from shared.utils import get_logger

logger = get_logger(__name__)

#: "daily average", "hour by hour", "for each day", "per hour". The word must ask for a figure
#: per period. "throughout the day" and "time of day" are a daily PATTERN (one figure per hour of
#: the day, pooled over days) and belong to the hourly profile, so they are not here.
_PER_DAY_RE = re.compile(
    r"\b(?:daily|each\s+day|per\s+day|every\s+day|day[- ]by[- ]day|by\s+day|a\s+day\s+by\s+day)\b",
    re.IGNORECASE,
)
_PER_HOUR_RE = re.compile(
    r"\b(?:hourly|each\s+hour|per\s+hour|every\s+hour|hour[- ]by[- ]hour|by\s+(?:the\s+)?hour)\b",
    re.IGNORECASE,
)
#: Not a breakdown: "the daily pattern", "a typical hourly profile" ask for the profile.
_PATTERN_RE = re.compile(
    r"\b(?:pattern|profile|typical(?:ly)?|usually|normally|generally)\b", re.IGNORECASE
)

DAY = 86400
HOUR = 3600
MAX_ROWS = {DAY: 62, HOUR: 48}


def per_period_bucket(question: str) -> Optional[Tuple[int, str]]:
    """(bucket seconds, "day"|"hour") when the question asks for a figure per period, else None."""
    q = question or ""
    if _PATTERN_RE.search(q):
        return None
    if _PER_HOUR_RE.search(q):
        return HOUR, "hour"
    if _PER_DAY_RE.search(q):
        return DAY, "day"
    return None


def aligned_start(start: datetime, bucket_s: int, tz_name: Optional[str]) -> datetime:
    """The window's start moved back to the building's local midnight (day) or the hour (hour).

    Buckets are numbered from the window's start, so an unaligned start makes every "day" run
    from, say, 14:19 to 14:19 -- correct arithmetic over periods no reader means. Stores are UTC
    and the building is not, so the alignment is done on the LOCAL clock and converted back.
    A bucket is a fixed 24 hours from there, so across a clock change one day's bucket is an hour
    off its calendar day; the answer is still a mean over 24 hours of readings.
    """
    from orchestrator.services.requested_interval import to_local, to_store

    local = to_local(start, tz_name)
    if bucket_s == DAY:
        local = local.replace(hour=0, minute=0, second=0, microsecond=0)
    else:
        local = local.replace(minute=0, second=0, microsecond=0)
    return to_store(local, tz_name)


def _label(local_start: datetime, kind: str) -> str:
    if kind == "day":
        return local_start.strftime("%a %d %b")
    return local_start.strftime("%a %d %b %H:00")


def render(
    *,
    kind: str,
    quantity: str,
    unit: str,
    place: str,
    window_label: str,
    rows: Sequence[Tuple[str, float, int, int]],
    sensors: int,
    partial_first: bool,
    partial_last: bool,
) -> str:
    """The table: one row per period with its mean, the readings behind it and the sensors."""
    u = f" {unit}" if unit else ""
    per = "Daily" if kind == "day" else "Hourly"
    where = f" in {place}" if place else ""
    means = [m for _l, m, _n, _s in rows]
    hi = max(range(len(rows)), key=lambda i: means[i])
    lo = min(range(len(rows)), key=lambda i: means[i])
    lead = (
        f"**{per} average {quantity}{where}, {window_label}:** from {means[lo]:.1f}{u} "
        f"({rows[lo][0]}) to {means[hi]:.1f}{u} ({rows[hi][0]}) across {len(rows)} "
        f"{'days' if kind == 'day' else 'hours'}."
    )
    head = f"| {kind} | average{u and f' ({unit})'} | readings | sensors |"
    table = [head, "|---|---|---|---|"]
    for label, mean, n, s in rows:
        table.append(f"| {label} | {mean:.1f} | {n} | {s} |")
    notes = []
    if partial_first:
        # The window was moved back to the building's midnight (or the hour), so the first row is
        # a WHOLE period that starts before the moment the question's window did.
        notes.append(
            f"Each {kind} runs {'midnight to midnight' if kind == 'day' else 'on the hour'} in "
            f"building time, so the first {kind} is shown whole."
        )
    if partial_last:
        notes.append(f"The last {kind} is still in progress, so its average covers fewer readings.")
    basis = (
        f"Each {kind}'s figure is the mean of every reading from the "
        f"{sensors} sensor{'s' if sensors != 1 else ''} in that {kind} (total over count, reduced "
        "in the store, so no reading was left out by a row limit)."
    )
    return "\n".join([lead, "", *table, "", basis, *notes])


async def answer_breakdown(
    *,
    question: str,
    bucket: Tuple[int, str],
    uuids: Sequence[str],
    facts: Dict[str, Any],
    storage_map: Dict[str, str],
    window: Any,
    tz_name: Optional[str],
    adapter_for: Callable[[str], Any],
    store_key: Callable[[str], str],
    bands: Optional[Dict[str, Tuple[float, float]]],
    quantity: str,
    place: str,
) -> Optional[Dict[str, Any]]:
    """The per-period table, or None to leave the question to the lane's other paths."""
    from orchestrator.services import aggregate_lane as al
    from orchestrator.services.requested_interval import to_local
    from orchestrator.services.units import normalise

    bucket_s, kind = bucket
    start = al._stamp(window.start)
    end = al._stamp(window.end)
    if start is None or end is None or end <= start:
        return None
    a_start = aligned_start(start, bucket_s, tz_name)
    n_buckets = int(((end - a_start).total_seconds() + bucket_s - 1) // bucket_s)
    if n_buckets < 2 or n_buckets > MAX_ROWS[bucket_s]:
        logger.info(f"[aggregate] breakdown left alone: {n_buckets} {kind}s is not a table")
        return None
    families: Dict[str, List[str]] = {}
    for u in uuids:
        f = facts.get(u)
        families.setdefault(normalise(getattr(f, "unit", "") or ""), []).append(u)
    unit_key, members = max(families.items(), key=lambda kv: len(kv[1]))
    unit = next((getattr(facts.get(u), "unit", "") for u in members if facts.get(u)), "") or ""
    aligned = al.Window(
        a_start.strftime(al.STAMP), end.strftime(al.STAMP), window.label, latest=False
    )
    ready, _unsupported = await al._stores_ready(members, storage_map, adapter_for, store_key)
    pooled: Dict[int, List[float]] = {}
    contributors: Dict[int, set] = {}
    for _key, (adapter, group) in ready.items():
        got, _bad = await al.run_buckets(adapter, group, aligned, bucket_s, bands)
        for b in got:
            cell = pooled.setdefault(b.index, [0.0, 0])
            cell[0] += b.total
            cell[1] += b.n
            contributors.setdefault(b.index, set()).add(b.uuid)
    if len(pooled) < 2:
        return None
    rows: List[Tuple[str, float, int, int]] = []
    for idx in sorted(pooled):
        total, n = pooled[idx]
        if not n:
            continue
        local = to_local(a_start + timedelta(seconds=idx * bucket_s), tz_name)
        rows.append((_label(local, kind), total / n, int(n), len(contributors[idx])))
    if len(rows) < 2:
        return None
    used = len(set().union(*contributors.values()))
    text = render(
        kind=kind,
        quantity=quantity,
        unit=unit,
        place=place,
        window_label=window.label,
        rows=rows,
        sensors=used,
        partial_first=a_start < start,
        # A closed window ends one second before a boundary ("yesterday" ends 23:59:59), which is
        # a whole last period, not a cut one.
        partial_last=((end - a_start).total_seconds() + 1) % bucket_s > 1,
    )
    figures = {f"{label} mean": round(mean, 4) for label, mean, _n, _s in rows}
    logger.info(
        f"[aggregate] breakdown: {len(rows)} {kind}s over {used} sensor(s), unit={unit_key}"
    )
    return al._result(text, al.AggregateIntent("mean", "time"), window, used, figures)
