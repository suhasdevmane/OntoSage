# -*- coding: utf-8 -*-
"""The usual daily pattern of a quantity: "when are CO2 or temperature most likely to worsen?".

A time-of-day question names a measurand and no place, and asks WHEN. It is neither a per-floor
summary (that answers "how is it now") nor a forecast (nothing here predicts). What answers it is
the hourly profile: the store groups each sensor's readings by hour of the day over a window long
enough to hold several of them, and the answer says at which hours the building's readings run
highest and lowest, with the boundary stated. It is computed by the store in one GROUP BY, never by
reading rows.

WHAT IT DELIBERATELY DOES NOT CLAIM
-----------------------------------
* No prediction. "Usually highest around 15:00 over the last seven days" describes the past; it
  does not say what will happen in tomorrow's class, and the answer says so.
* No verdict. Hours are ranked, not called high or low, because nothing here compares them with a
  cited limit.
* No occupancy. A headcount is additive across sensors and a mean of counters is not a headcount;
  those questions belong to the headcount path.

THE INVARIANT
-------------
Every printed hourly mean is checked against the extremes of the readings it is the mean of. A mean
outside its own range is an arithmetic error in the pipeline, not a finding, so the family it
belongs to is not printed and the disagreement is logged (the wave-4 rule, applied here from the
start: a wrong number must never reach a reader).
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import timedelta
from typing import Any, Dict, List, Optional, Sequence, Tuple

from orchestrator.services import aggregate_lane as al
from shared.utils import get_logger

logger = get_logger(__name__)

#: A profile needs several days to be a pattern rather than one day's weather.
DEFAULT_DAYS = 7

#: The most unit families answered in one reply. "CO2 or temperature" is two; a set that binds
#: more than that is a question about something other than one or two quantities.
MAX_FAMILIES = 2

#: A family needs at least this many sensors to be described as the building's pattern.
MIN_SERIES_FOR_A_PATTERN = 3

#: Hours of the day are grouped in bands this wide for the table; the peak is still an exact hour.
BAND_HOURS = 3

#: An hour counts as one the building is "in use" when its typical headcount reaches this share of
#: the building's own typical peak.
IN_USE_SHARE = 0.25


@dataclass
class HourRow:
    """One sensor's readings within one hour of the day, reduced by the store."""

    uuid: str
    hour: int  # the store's hour (UTC)
    n: int
    total: float
    low: float
    high: float


def hourly_statements(
    layout: str,
    adapter: Any,
    uuids: Sequence[str],
    window: al.Window,
    bands: Optional[Dict[str, Tuple[float, float]]] = None,
) -> List[al.Statement]:
    """GROUP BY hour-of-day statements: (count, sum, min, max) per sensor per hour."""
    start, end = al._clean_stamp(window.start), al._clean_stamp(window.end)
    bands = bands or {}
    safe = [u for u in dict.fromkeys(uuids) if al._SAFE_ID.match(str(u))]
    out: List[al.Statement] = []
    if not safe:
        return out
    if layout == "mysql_narrow":
        table = al._ident(getattr(adapter, "table", ""))
        for band, group in al._by_band(safe, bands):
            x = al._banded("`value`", band)
            for part in al._chunks(group, al.NARROW_CHUNK):
                inl = ", ".join(f"'{u}'" for u in part)
                out.append(
                    al.Statement(
                        f"SELECT `uuid`, HOUR(`datetime`) AS h, COUNT({x}) AS n, SUM({x}) AS sm, "
                        f"MIN({x}) AS mn, MAX({x}) AS mx FROM `{table}` WHERE `uuid` IN ({inl}) "
                        f"AND `datetime` >= '{start}' AND `datetime` <= '{end}' "
                        f"GROUP BY `uuid`, HOUR(`datetime`)",
                        "hourly",
                        tuple(part),
                    )
                )
    elif layout == "mysql_wide":
        table = al._wide_table_of(adapter)
        ts = al._wide_ts_of(adapter)
        known = getattr(adapter, "_columns_cache", None)
        cols = [u for u in safe if not known or u in known]
        for part in al._chunks(cols, al.WIDE_CHUNK):
            picks = ", ".join(
                f"COUNT({al._banded(f'`{u}`', bands.get(u))}) AS n{i}, "
                f"SUM({al._banded(f'`{u}`', bands.get(u))}) AS sm{i}, "
                f"MIN({al._banded(f'`{u}`', bands.get(u))}) AS mn{i}, "
                f"MAX({al._banded(f'`{u}`', bands.get(u))}) AS mx{i}"
                for i, u in enumerate(part)
            )
            out.append(
                al.Statement(
                    f"SELECT HOUR(`{ts}`) AS h, {picks} FROM `{table}` "
                    f"WHERE `{ts}` >= '{start}' AND `{ts}` <= '{end}' GROUP BY HOUR(`{ts}`)",
                    "hourly_wide",
                    tuple(part),
                )
            )
    elif layout == "pg_narrow":
        nb = getattr(adapter, "_narrow") or {}
        t, u_, ts, v = (al._ident(nb.get(k, "")) for k in ("table", "uuid", "ts", "value"))
        for band, group in al._by_band(safe, bands):
            x = al._pg_banded(f'"{v}"', band)
            for part in al._chunks(group, al.NARROW_CHUNK):
                inl = ", ".join(f"'{u}'" for u in part)
                out.append(
                    al.Statement(
                        f'SELECT "{u_}" AS uuid, EXTRACT(HOUR FROM "{ts}")::int AS h, '
                        f"COUNT({x}) AS n, SUM({x}) AS sm, MIN({x}) AS mn, MAX({x}) AS mx "
                        f'FROM "{t}" WHERE "{u_}" IN ({inl}) AND "{ts}" >= \'{start}\' '
                        f'AND "{ts}" <= \'{end}\' GROUP BY "{u_}", EXTRACT(HOUR FROM "{ts}")',
                        "hourly",
                        tuple(part),
                    )
                )
    return out


def parse_hourly(statement: al.Statement, rows: List[Dict[str, Any]]) -> List[HourRow]:
    """Per-sensor, per-hour reductions from one statement's rows."""
    out: List[HourRow] = []
    if statement.kind == "hourly_wide":
        for row in rows:
            h = al._i(row.get("h"))
            for i, u in enumerate(statement.uuids):
                n, mn, mx = (
                    al._i(row.get(f"n{i}")),
                    al._f(row.get(f"mn{i}")),
                    al._f(row.get(f"mx{i}")),
                )
                if n and mn is not None and mx is not None:
                    out.append(HourRow(u, h, n, al._f(row.get(f"sm{i}")) or 0.0, mn, mx))
    else:
        for row in rows:
            n, mn, mx = al._i(row.get("n")), al._f(row.get("mn")), al._f(row.get("mx"))
            u = str(row.get("uuid") or "")
            if u and n and mn is not None and mx is not None:
                out.append(HourRow(u, al._i(row.get("h")), n, al._f(row.get("sm")) or 0.0, mn, mx))
    return out


async def run_hourly(
    adapter: Any,
    uuids: Sequence[str],
    window: al.Window,
    bands: Optional[Dict[str, Tuple[float, float]]] = None,
) -> Tuple[List[HourRow], List[str]]:
    layout = al.layout_of(adapter)
    done, failed = await al._execute(
        adapter, hourly_statements(layout, adapter, uuids, window, bands)
    )
    out: List[HourRow] = []
    for st, rows in done:
        out.extend(parse_hourly(st, rows))
    return out, [u for st in failed for u in st.uuids]


@dataclass
class HourStat:
    """The building's readings at one local hour of the day."""

    hour: int  # building-local
    n: int = 0
    total: float = 0.0
    low: float = float("inf")
    high: float = float("-inf")

    @property
    def mean(self) -> Optional[float]:
        return self.total / self.n if self.n else None


def combine_hours(rows: Sequence[HourRow], offset_hours: int) -> Dict[int, HourStat]:
    """One figure per local hour, from every sensor's reductions: sums over counts, not means of
    means, so a sensor with more readings weighs what it should."""
    by_hour: Dict[int, HourStat] = {}
    for r in rows:
        local = (r.hour + offset_hours) % 24
        s = by_hour.setdefault(local, HourStat(local))
        s.n += r.n
        s.total += r.total
        s.low = min(s.low, r.low)
        s.high = max(s.high, r.high)
    return by_hour


def inside_range(hours: Dict[int, HourStat]) -> bool:
    """Is every hour's mean inside the extremes of its own readings? The invariant."""
    return all(h.mean is not None and h.low <= h.mean <= h.high for h in hours.values())


def _fmt_hour(h: int) -> str:
    return f"{h:02d}:00"


def render_profile(
    hours: Dict[int, HourStat],
    *,
    name: str,
    unit: str,
    window: al.Window,
    sensors: int,
    floors: int,
    excluded: int,
    band_text: str = "",
) -> str:
    """The daily pattern as words and one small table, with its boundary and its limits."""
    u = f" {unit}" if unit else ""
    ordered = sorted(hours.values(), key=lambda s: (s.mean, -s.hour))
    top, bottom = ordered[-1], ordered[0]
    peak3 = sorted(hours.values(), key=lambda s: (-s.mean, s.hour))[:3]
    lines = [
        f"**{name[:1].upper() + name[1:]} usually runs highest around {_fmt_hour(top.hour)} "
        f"({al._n(top.mean, 1)}{u} on average) and lowest around {_fmt_hour(bottom.hour)} "
        f"({al._n(bottom.mean, 1)}{u}).**",
        "",
        f"| Hours (building time) | Mean{u} | Highest reading |",
        "|---|---|---|",
    ]
    for start in range(0, 24, BAND_HOURS):
        members = [hours[h] for h in range(start, start + BAND_HOURS) if h in hours]
        if not members:
            continue
        n = sum(m.n for m in members)
        mean = sum(m.total for m in members) / n
        lines.append(
            f"| {_fmt_hour(start)}–{_fmt_hour((start + BAND_HOURS) % 24)} | "
            f"{al._n(mean, 1)} | {al._n(max(m.high for m in members), 1)} |"
        )
    lines += [
        "",
        "The hours with the highest averages were "
        + ", ".join(_fmt_hour(s.hour) for s in peak3)
        + ".",
        "",
        f"Based on {sensors} {name} sensor{'s' if sensors != 1 else ''}"
        + (f" on {floors} floor{'s' if floors != 1 else ''}" if floors else "")
        + f", {window.label}: each sensor's readings grouped by hour of the day in the store.",
        "This describes the usual pattern over that period. It does not predict a particular day, "
        "and it does not call any hour high or low against a limit.",
    ]
    if excluded:
        lines.append(
            f"{excluded:,} reading{'s' if excluded != 1 else ''} fell outside the physically "
            f"possible range for {name}{' (' + band_text + ')' if band_text else ''} and "
            f"{'is' if excluded == 1 else 'are'} not included."
        )
    return "\n".join(lines).strip()


def combine_floor_counters(
    rows: Sequence[HourRow], floors: Dict[str, str], offset_hours: int
) -> Dict[int, HourStat]:
    """The building's headcount at each local hour: the SUM over floors of each floor's own mean.

    A headcount is additive across floors and NOT across a floor's readings, so the mean over all
    readings (what `combine_hours` computes) would be the average FLOOR, six times too small. Each
    floor's mean at an hour is taken first; the building's figure is their sum. An hour at which
    any floor has no reading is dropped rather than summed over fewer floors, because a total over
    five floors beside a total over six is a comparison of different buildings.

    The range is the sum of the floors' lowest and of their highest readings at that hour. It is a
    bound, not an observation (the floors need not have peaked together), and it is what the mean
    is checked against.
    """
    per_floor: Dict[str, Dict[int, List[float]]] = {}
    for r in rows:
        floor = floors.get(r.uuid)
        if floor is None:
            continue
        local = (r.hour + offset_hours) % 24
        cell = per_floor.setdefault(floor, {}).setdefault(
            local, [0.0, 0.0, float("inf"), float("-inf")]
        )
        cell[0] += r.total
        cell[1] += r.n
        cell[2] = min(cell[2], r.low)
        cell[3] = max(cell[3], r.high)
    out: Dict[int, HourStat] = {}
    for hour in range(24):
        cells = [
            per_floor[f][hour] for f in per_floor if hour in per_floor[f] and per_floor[f][hour][1]
        ]
        if not per_floor or len(cells) != len(per_floor):
            continue
        s = HourStat(hour, n=len(cells))
        s.total = sum(c[0] / c[1] for c in cells)  # the building's mean, so mean == total / 1
        s.n = 1
        s.low = sum(c[2] for c in cells)
        s.high = sum(c[3] for c in cells)
        out[hour] = s
    return out


def render_headcount_profile(
    hours: Dict[int, HourStat],
    *,
    window: al.Window,
    counters: int,
    local_hour_now: Optional[int],
    note: str = "",
) -> str:
    """When the building is typically busiest and quietest, from its floor counters."""
    ordered = sorted(hours.values(), key=lambda s: (s.mean, -s.hour))
    top, bottom = ordered[-1], ordered[0]
    lines = [
        f"**The building is typically busiest around {_fmt_hour(top.hour)} (about "
        f"{al._n(top.mean)} people) and quietest around {_fmt_hour(bottom.hour)} (about "
        f"{al._n(bottom.mean)}).**",
        "",
        "| Hours (building time) | People (typical) |",
        "|---|---|",
    ]
    for start in range(0, 24, BAND_HOURS):
        members = [hours[h] for h in range(start, start + BAND_HOURS) if h in hours]
        if members:
            mean = sum(m.mean for m in members) / len(members)
            lines.append(
                f"| {_fmt_hour(start)}–{_fmt_hour((start + BAND_HOURS) % 24)} | {al._n(mean)} |"
            )
    lines.append("")
    if local_hour_now is not None:
        # QUIETEST AMONG THE HOURS THE BUILDING IS IN USE. Without the second condition the
        # quietest hours "later today" are the small hours of the night, which is true and answers
        # nothing anyone asking about desk work meant. "In use" is read from the data — at least a
        # quarter of the building's own typical peak — not from a working-day constant, so it holds
        # for a building that opens at another time and is stated in the reply.
        floor_level = IN_USE_SHARE * top.mean
        later = sorted(
            (s for s in hours.values() if s.hour > local_hour_now and s.mean >= floor_level),
            key=lambda s: (s.mean, s.hour),
        )[:3]
        if later:
            lines.append(
                f"Later today (after {_fmt_hour(local_hour_now)}), among the hours when the "
                f"building is typically in use (at least a quarter of its usual peak), the "
                "quietest are "
                + ", ".join(f"{_fmt_hour(s.hour)} (about {al._n(s.mean)})" for s in later)
                + "."
            )
            lines.append("")
    lines += [
        f"Based on the building's {counters} floor counters, {window.label}: each floor's average "
        "at each hour of the day, added across floors. The room-level counters are not added to it.",
        "This is typical for the recent days. It does not predict today, which may be busier or "
        "quieter than usual.",
    ]
    if note:
        lines.append(note)
    return "\n".join(lines).strip()


def default_window(now: Any, tz_name: Optional[str]) -> al.Window:
    """The last seven days: several of each hour, so the pattern is more than one day's weather."""
    start = now - timedelta(days=DEFAULT_DAYS)
    return al.Window(
        start.strftime(al.STAMP),
        now.strftime(al.STAMP),
        f"{al._show(start, tz_name)} to {al._show(now, tz_name)} (building time)",
    )


def local_offset_hours(window: al.Window, tz_name: Optional[str]) -> int:
    """Whole hours between the store's clock and building time at the END of the window."""
    from orchestrator.services.requested_interval import to_local

    end = al._stamp(window.end)
    if end is None:
        return 0
    return int(round((to_local(end, tz_name) - end).total_seconds() / 3600.0))


async def answer_profile(
    *,
    families: Dict[str, List[str]],
    facts: Dict[str, "al.Facts"],
    storage_map: Dict[str, str],
    window: al.Window,
    tz_name: Optional[str],
    adapter_for: Any,
    store_key: Any,
    measurand: Optional[str],
    bands: Dict[str, Tuple[float, float]],
    intent: "al.AggregateIntent",
) -> Optional[Dict[str, Any]]:
    """The profile of the largest unit families, or None when there is nothing honest to say."""
    offset = local_offset_hours(window, tz_name)
    blocks: List[str] = []
    figures: Dict[str, float] = {}
    used = 0
    ranked_families = sorted(families.items(), key=lambda kv: -len(kv[1]))[:MAX_FAMILIES]
    for unit, members in ranked_families:
        if len(members) < MIN_SERIES_FOR_A_PATTERN:
            continue
        ready, _unsupported = await al._stores_ready(members, storage_map, adapter_for, store_key)
        rows: List[HourRow] = []
        for _key, (adapter, group) in ready.items():
            got, _bad = await run_hourly(adapter, group, window, bands)
            rows.extend(got)
        hours = combine_hours(rows, offset)
        if not hours:
            continue
        if not inside_range(hours):
            logger.error(
                "[aggregate] hourly profile suppressed for unit %r: an hourly mean lies outside "
                "the range of its own readings",
                unit,
            )
            continue
        answered = {r.uuid for r in rows}
        family_name = al.display_name(
            al.measurand_key(facts[u].label for u in members) or measurand
        )
        excluded = 0
        blocks.append(
            render_profile(
                hours,
                name=family_name,
                unit=unit,
                window=window,
                sensors=len(answered),
                floors=len({facts[u].floor for u in answered if facts[u].floor}),
                excluded=excluded,
            )
        )
        used += len(answered)
        for h, s in hours.items():
            figures[f"{family_name} {h:02d}:00 mean"] = s.mean
            figures[f"{family_name} {h:02d}:00 highest"] = s.high
        figures[f"{family_name} sensors"] = float(len(answered))
    if not blocks:
        return None
    return al._result("\n\n".join(blocks), intent, window, used, figures)


async def answer_headcount_profile(
    *,
    counters: Dict[str, str],
    storage_map: Dict[str, str],
    window: al.Window,
    tz_name: Optional[str],
    adapter_for: Any,
    store_key: Any,
    intent: "al.AggregateIntent",
    note: str = "",
) -> Optional[Dict[str, Any]]:
    """The building's typical headcount by hour, from its floor counters (uuid -> floor).

    The floor counters are the same source the per-floor headcount uses, so the two answers cannot
    disagree about how many people are in the building.
    """
    from orchestrator.services.requested_interval import to_local

    if len(counters) < 2:
        return None
    ready, _unsupported = await al._stores_ready(
        list(counters), storage_map, adapter_for, store_key
    )
    rows: List[HourRow] = []
    for _key, (adapter, group) in ready.items():
        got, _bad = await run_hourly(adapter, group, window, None)
        rows.extend(got)
    hours = combine_floor_counters(rows, counters, local_offset_hours(window, tz_name))
    if len(hours) < 6 or not inside_range(hours):
        if hours:
            logger.error("[aggregate] hourly headcount suppressed: a mean lies outside its range")
        return None
    end = al._stamp(window.end)
    now_hour = to_local(end, tz_name).hour if end is not None else None
    text = render_headcount_profile(
        hours, window=window, counters=len(counters), local_hour_now=now_hour, note=note
    )
    figures = {f"{h:02d}:00 people": s.mean for h, s in hours.items()}
    figures["floor counters"] = float(len(counters))
    return al._result(text, intent, window, len(counters), figures)
