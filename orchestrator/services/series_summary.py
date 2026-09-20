# -*- coding: utf-8 -*-
"""A compact, per-series statistical summary of fetched readings, for a narration prompt.

BUG-554. The recommendation lane put `rows[-5:]` in front of the model: the LAST FIVE rows of
6,000, all of them from one of six floor energy meters. Asked "can you provide energy saving
suggestions?", it duly reported that "the building's data only shows values for the sensor on
Floor 4 (UUID f72eafc6-…)" and advised collecting readings from the other floors — which had
been fetched. The same lane decided whether energy data was present by looking for "energy"
in the COLUMN NAMES, and narrow rows are `timestamp, uuid, value`, so it also told the model
the data "contains no energy or power readings".

One line per series, built only from the rows and the sensor metadata already on the bus:
what it is, how much was read and over what span, its range and mean, its latest value in the
building's local time, and — where the timestamps allow — night against working-day means,
which is the single most useful contrast for an energy or comfort recommendation. No building
literal, no sensor uuid in the text.
"""

from __future__ import annotations

import re
from datetime import datetime
from statistics import mean
from typing import Any, Dict, Iterable, List, Optional, Tuple

#: Metadata words that mark a series as energy or power. Units first: they are asserted.
_ENERGY_UNITS = frozenset({"kwh", "wh", "mwh", "w", "kw", "mw", "kvah", "kvarh"})
_ENERGY_WORDS = ("energy", "power", "electric", "kwh", "gas consumption")


def _parse_ts(value: Any) -> Optional[datetime]:
    if isinstance(value, datetime):
        return value.replace(tzinfo=None)
    text = str(value or "").strip().replace("T", " ")[:19]
    for fmt in ("%Y-%m-%d %H:%M:%S", "%Y-%m-%d %H:%M", "%Y-%m-%d"):
        try:
            return datetime.strptime(text, fmt)
        except ValueError:
            continue
    return None


def _is_energy(meta: Dict[str, Any]) -> bool:
    unit = str(meta.get("unit") or "").strip().lower()
    if unit in _ENERGY_UNITS:
        return True
    text = " ".join(str(meta.get(k) or "") for k in ("kind", "label", "sensor_uri")).lower()
    return any(word in text for word in _ENERGY_WORDS)


def _fmt(x: float) -> str:
    return f"{x:.3g}" if abs(x) < 1000 else f"{x:,.0f}"


def summarise_groups(
    rows: Iterable[Any],
    metadata: Optional[Dict[str, Dict[str, Any]]] = None,
    key: str = "floor",
) -> Optional[str]:
    """Per-group aggregates (e.g. per floor), computed here rather than by the narrator.

    BUG-537. "Compare the average CO2 on floor 1 versus floor 3" gave the narrator 64 per-sensor
    lines and let it average them into two numbers — arithmetic by language model on the most
    quotable figure in the answer, and 210 s of it. Returns None unless the series span at
    least two groups whose readings may be aggregated (units.aggregation_decision); an energy
    unit is SUMMED (readings are interval energy) as well as averaged, anything else averaged.
    """
    from orchestrator.services.units import _KIND, aggregation_decision, normalise

    metadata = metadata or {}
    per_group: Dict[str, Dict[str, List[float]]] = {}
    for row in rows or []:
        if not isinstance(row, dict):
            continue
        uid = str(row.get("uuid") or row.get("sensor") or "")
        group = str((metadata.get(uid) or {}).get(key) or "")
        if not group:
            continue
        try:
            value = float(row.get("value"))
        except (TypeError, ValueError):
            continue
        per_group.setdefault(group, {}).setdefault(uid, []).append(value)
    if len(per_group) < 2:
        return None

    units = {str((metadata.get(u) or {}).get("unit") or "") for g in per_group.values() for u in g}
    decision = aggregation_decision(units)
    if not decision.ok:
        return f"Per-{key} aggregates were NOT computed: {decision.reason}."
    unit = decision.target
    is_energy = _KIND.get(normalise(unit)) == "energy"

    def _order(g: str) -> Tuple[int, str]:
        return (int(g), g) if g.lstrip("-").isdigit() else (10**9, g)

    lines = [
        f"Per-{key} aggregates, computed from the readings fetched (quote these; do not "
        "recompute them):"
    ]
    for group in sorted(per_group, key=_order):
        series = per_group[group]
        values = [v for vs in series.values() for v in vs]
        parts = [f"{len(series)} sensor(s), {len(values)} readings"]
        if is_energy:
            parts.append(f"total {_fmt(sum(values))} {unit}")
        parts.append(f"mean {_fmt(mean(values))} {unit}")
        parts.append(f"range {_fmt(min(values))} to {_fmt(max(values))} {unit}")
        lines.append(f"- {key.capitalize()} {group}: " + "; ".join(parts))
    if is_energy:
        lines.append(
            "Totals are sums of the readings, which are the energy of each reading interval; "
            "a floor with more readings in the window has more interval energy counted."
        )
    return "\n".join(lines)


def summarise_series(
    rows: Iterable[Any],
    metadata: Optional[Dict[str, Dict[str, Any]]] = None,
    tz_name: Optional[str] = None,
    max_series: int = 20,
) -> Tuple[str, bool]:
    """(one line per series, whether any series is energy/power)."""
    from orchestrator.services.requested_interval import to_local

    metadata = metadata or {}
    groups: Dict[str, List[Tuple[Optional[datetime], float]]] = {}
    for row in rows or []:
        if not isinstance(row, dict):
            continue
        key = str(row.get("uuid") or row.get("sensor") or row.get("sensor_uuid") or "")
        try:
            value = float(row.get("value"))
        except (TypeError, ValueError):
            continue
        ts = _parse_ts(row.get("timestamp") or row.get("datetime") or row.get("time"))
        groups.setdefault(key, []).append((ts, value))

    has_energy = any(_is_energy(metadata.get(k) or {}) for k in groups)
    ordered = sorted(groups, key=lambda k: str((metadata.get(k) or {}).get("label") or k))
    lines: List[str] = []
    for key in ordered[:max_series]:
        meta = metadata.get(key) or {}
        label = str(meta.get("label") or "unlabelled series")
        unit = str(meta.get("unit") or "")
        points = groups[key]
        values = [v for _, v in points]
        timed = sorted((t, v) for t, v in points if t is not None)
        line = (
            f"- {label}: {len(values)} readings; min {_fmt(min(values))}, mean "
            f"{_fmt(mean(values))}, max {_fmt(max(values))}{(' ' + unit) if unit else ''}"
        )
        if timed:
            first = to_local(timed[0][0], tz_name)
            last_t, last_v = timed[-1]
            last = to_local(last_t, tz_name)
            line += (
                f"; from {first:%d %b %H:%M} to {last:%d %b %H:%M} (building time); latest "
                f"{_fmt(last_v)}"
            )
            # WHEN the extremes happened (BUG-592): without it a narration shown only the newest
            # rows placed the day's minimum in the last hour ("lowest 842 ppm at 17:23" against a
            # stored 704 ppm at 04:08).
            lo_t, lo_v = min(timed, key=lambda p: p[1])
            hi_t, hi_v = max(timed, key=lambda p: p[1])
            line += (
                f"; minimum {_fmt(lo_v)} at {to_local(lo_t, tz_name):%d %b %H:%M}, maximum "
                f"{_fmt(hi_v)} at {to_local(hi_t, tz_name):%d %b %H:%M}"
            )
            night = [v for t, v in timed if to_local(t, tz_name).hour < 6]
            day = [v for t, v in timed if 8 <= to_local(t, tz_name).hour < 18]
            if night and day:
                line += f"; night (00-06) mean {_fmt(mean(night))} vs day (08-18) mean {_fmt(mean(day))}"
        lines.append(line)
    if len(ordered) > max_series:
        lines.append(f"- …and {len(ordered) - max_series} more series not shown")
    return "\n".join(lines), has_energy


#: A question that asks for a TOTAL over a period ("how much electricity did we use yesterday",
#: "the total energy use last month"). Matched on the question, never on the data.
_TOTAL_RE = re.compile(
    r"\b(?:how\s+much|total|in\s+total|altogether|consum\w*|"
    r"(?:did|do|does|have|has)\s+(?:we|you|it|the\s+building)\s+us(?:e|ed))\b",
    re.IGNORECASE,
)
#: Words that make it a different question: those have their own templates and lanes.
_NOT_A_TOTAL_RE = re.compile(
    r"\b(?:average|mean|avg|highest|lowest|peak|maximum|minimum|max|min|current|latest|now|"
    r"recent|compare[ds]?|versus|vs|trend|forecast|predict\w*)\b",
    re.IGNORECASE,
)


def asks_for_a_total(question: str) -> bool:
    """True when the answer is a SUM over the period, not a latest, average or extreme."""
    q = question or ""
    return bool(_TOTAL_RE.search(q)) and not _NOT_A_TOTAL_RE.search(q)


def summarise_energy_totals(
    rows: Iterable[Any],
    metadata: Optional[Dict[str, Dict[str, Any]]] = None,
    max_series: int = 8,
) -> Optional[str]:
    """The TOTAL of energy series over the fetched window, computed here, not narrated.

    2026-09-18, unscripted: *"How much electricity did the building use yesterday?"* fetched the
    right six meters and the right local day (144 readings), then took the analytics lane's default
    stats template — there is no total template; the keywords "current/latest/now" pick one and this
    question has none — which prints the latest reading per series. The narrator then reported the
    sum of the six LATEST readings as "17.08 kWh yesterday". A wrong figure, stated with confidence,
    which is worse than the "no data" it replaced.

    An energy reading is the energy of its own interval, so a total is the SUM of readings and the
    latest reading is not a total. Returns None unless every series is an energy series in units
    that may be summed together (`units.aggregation_decision`), so a power (kW) series or a mixed
    set is never added up.
    """
    from orchestrator.services.units import _KIND, aggregation_decision, normalise

    metadata = metadata or {}
    per: Dict[str, List[Tuple[Optional[datetime], float]]] = {}
    for row in rows or []:
        if not isinstance(row, dict):
            continue
        key = str(row.get("uuid") or row.get("sensor") or row.get("sensor_uuid") or "")
        if not key:
            continue
        try:
            value = float(row.get("value"))
        except (TypeError, ValueError):
            continue
        ts = _parse_ts(row.get("timestamp") or row.get("datetime") or row.get("time"))
        per.setdefault(key, []).append((ts, value))
    if not per:
        return None
    if not all(_is_energy(metadata.get(k) or {}) for k in per):
        return None
    decision = aggregation_decision({str((metadata.get(k) or {}).get("unit") or "") for k in per})
    if not decision.ok or _KIND.get(normalise(decision.target)) != "energy":
        return None
    unit = decision.target

    def _label(k: str) -> str:
        return str((metadata.get(k) or {}).get("label") or "unlabelled series")

    values = [v for pts in per.values() for _, v in pts]
    stamps = sorted(t for pts in per.values() for t, _ in pts if t is not None)
    span = f", {stamps[0]:%d %b %H:%M} to {stamps[-1]:%d %b %H:%M} store time" if stamps else ""
    lines = [
        f"Total over the period, computed from the readings fetched (quote it; do not recompute it "
        f"and never use a latest reading as a total): {_fmt(sum(values))} {unit} across "
        f"{len(per)} series ({len(values)} readings{span}).",
    ]
    for key in sorted(per, key=_label)[:max_series]:
        vals = [v for _, v in per[key]]
        lines.append(f"- {_label(key)}: {_fmt(sum(vals))} {unit} ({len(vals)} readings)")
    if len(per) > max_series:
        lines.append(f"- …and {len(per) - max_series} more series not shown")
    lines.append(
        "Each reading is the energy of its own interval, so a total is the SUM of the readings."
    )
    if stamps:
        # "What was the total energy use last month?" was answered "5,531 kWh for the period" from
        # about eleven days of readings, and the reader took it for a month. A total means nothing
        # without the span it covers, and a span shorter than the one asked about must be said.
        lines.append(
            "State in your answer the period these readings actually cover (the dates above). If "
            "it is shorter than the period the question asked about, say so plainly, and do not "
            "describe the total as covering more than it does."
        )
    return "\n".join(lines)


def summarise_latest_overview(
    rows: Iterable[Any],
    metadata: Optional[Dict[str, Dict[str, Any]]] = None,
    top_n: int = 5,
) -> Optional[str]:
    """An overview of the LATEST reading from each of many series, computed here, not narrated.

    2026-09-18, unscripted: *"How busy is the building right now?"* fetched 250 occupancy streams
    and built a 64,436-character narration prompt for a model with a 16,384-token context. Ollama
    drops from the FRONT when a prompt overflows, so the model saw only the tail — the last two
    rules and "Response:" — and answered with the ticket id in rule 9 (`**BUG-606**`), then, with
    that stripped, "I'm ready to help". The data was fine and the analytics had run; the question
    never reached the model. `summarise_groups` (BUG-537) solves the same size problem for series
    that span floors and declines when they carry no floor, which is exactly this case.

    Returns None for fewer than two series. Never sums: a room sensor and a floor sensor can
    both be in the set, so a total would count the same people twice; the overview reports the
    spread and names the extremes, which is what "how busy" needs.
    """
    metadata = metadata or {}
    latest: Dict[str, Tuple[Optional[datetime], float]] = {}
    for row in rows or []:
        if not isinstance(row, dict):
            continue
        key = str(row.get("uuid") or row.get("sensor") or row.get("sensor_uuid") or "")
        if not key:
            continue
        try:
            value = float(row.get("value"))
        except (TypeError, ValueError):
            continue
        ts = _parse_ts(row.get("timestamp") or row.get("datetime") or row.get("time"))
        held = latest.get(key)
        # A newer timestamp wins; a row with no timestamp cannot be ordered, so the last one seen
        # stands rather than being dropped.
        if held is None:
            latest[key] = (ts, value)
        elif ts is None:
            latest[key] = (held[0], value)
        elif held[0] is None or ts >= held[0]:
            latest[key] = (ts, value)
    if len(latest) < 2:
        return None

    def _label(k: str) -> str:
        return str((metadata.get(k) or {}).get("label") or "unlabelled series")

    units = {str((metadata.get(k) or {}).get("unit") or "") for k in latest} - {""}
    unit = f" {next(iter(units))}" if len(units) == 1 else ""
    values = [v for _, v in latest.values()]
    ranked = sorted(latest, key=lambda k: latest[k][1], reverse=True)
    zero = sum(1 for v in values if v == 0)
    lines = [
        f"Overview of the latest reading from each of {len(latest)} series, computed from the "
        "readings fetched (quote these; do not recompute them):",
        f"- mean {_fmt(mean(values))}{unit}; range {_fmt(min(values))} to {_fmt(max(values))}{unit}; "
        f"{zero} of {len(latest)} series read zero.",
        "- Highest: " + "; ".join(f"{_label(k)} {_fmt(latest[k][1])}{unit}" for k in ranked[:top_n]),
        "- Lowest: "
        + "; ".join(f"{_label(k)} {_fmt(latest[k][1])}{unit}" for k in ranked[::-1][:top_n]),
        "Each series is one sensor. Do not add readings from different sensors into a total: "
        "a room and the floor it is on may both be in this set.",
    ]
    return "\n".join(lines)


#: A question about how something CHANGED, or about one period against another. Matched on the
#: question, never on the data: the same rows answer "what is the CO2 now" and "how has the CO2
#: changed this week", and only the question says which.
_TEMPORAL_RE = None  # built lazily below, so the module keeps importing with no regex cost


def asks_how_it_changed(question: str) -> bool:
    """True when the answer has to be a shape over time, not a single figure.

    "How has the temperature on floor 3 changed over the last week?" was answered *"No change
    data available for floor 3 over the last week"* from a week of readings that had been
    fetched, clamped and handed over — as per-floor means, because a per-FLOOR summary is the
    only one that existed (BUG-626). A mean over a week cannot show a change within it.
    """
    global _TEMPORAL_RE
    if _TEMPORAL_RE is None:
        import re as _re

        _TEMPORAL_RE = _re.compile(
            r"\b(?:how\s+(?:has|have|did|is|are)\b[^?]*\bchang|chang(?:e|ed|ing)\s+over"
            r"|trend|trending|over\s+(?:the\s+)?(?:last|past|previous)\s+\w+"
            r"|compared?\s+(?:with|to)\s+(?:last|previous|the\s+(?:previous|preceding))"
            # "Compare this week's electricity use with last week" — the comparison word and
            # the period it names are six words apart, so an adjacency pattern misses it.
            r"|\bthis\s+(?:week|month|year|quarter)\b[^?]{0,60}?\b(?:last|previous|prior)\s+"
            r"(?:week|month|year|quarter)\b"
            r"|\b(?:last|previous|prior)\s+(?:week|month|year|quarter)\b[^?]{0,60}?\bthis\s+"
            r"(?:week|month|year|quarter)\b"
            r"|week\s+on\s+week|day\s+on\s+day|month\s+on\s+month"
            r"|rise|risen|rising|fall|fallen|falling|increase[sd]?|decrease[sd]?"
            r"|busiest|quietest|peak\s+(?:time|hour)|what\s+time\b)",
            _re.IGNORECASE,
        )
    return bool(_TEMPORAL_RE.search(question or ""))


def _bucket_of(when: datetime, size: str) -> str:
    if size == "hour":
        return when.strftime("%Y-%m-%d %H:00")
    if size == "week":
        iso = when.isocalendar()
        return f"{iso[0]}-W{iso[1]:02d}"
    return when.strftime("%Y-%m-%d")


def _bucket_size(span_hours: float, question: str = "") -> str:
    """Chosen from the period the QUESTION names, else from the span.

    "Compare this week's electricity use with last week" bucketed by day answered with the
    first day against the last day — two PARTIAL days, one of them today — and reported a
    291.7% rise that no week had. A question that names weeks is answered in weeks.

    No calendar literal about this building: a span is a span wherever it was measured.
    """
    import re as _re

    asked = (question or "").lower()
    for word, hours in (("year", 24 * 365), ("quarter", 24 * 90), ("month", 24 * 28), ("week", 24 * 7)):
        if _re.search(rf"\b(?:this|last|previous|prior|past|each|per)\s+{word}\b", asked):
            # Only if the window actually holds more than one of them; otherwise one bucket
            # is the whole answer and says nothing.
            if span_hours >= hours * 1.5:
                return word
    if span_hours <= 72:
        return "hour"
    if span_hours <= 24 * 70:
        return "day"
    return "week"


#: Hours in a whole bucket, and the smaller unit a partial one is compared in.
_NOMINAL_HOURS = {"hour": 1.0, "day": 24.0, "week": 168.0}
_RATE_UNIT = {"hour": ("hour", 1.0), "day": ("hour", 1.0), "week": ("day", 24.0)}
#: A bucket whose readings span less than this share of it is still filling (or began mid-way).
_WHOLE_COVERAGE = 0.9


def _covered_hours(stamps: List[datetime]) -> Optional[float]:
    """Hours of the bucket its readings actually span; None when three readings cannot say."""
    distinct = sorted(set(stamps))
    if len(distinct) < 3:
        return None
    span = (distinct[-1] - distinct[0]).total_seconds() / 3600.0
    return span + span / (len(distinct) - 1)


def _complete_buckets(ordered: List[str], per_bucket: Dict[str, List[float]]) -> List[str]:
    """Drop an edge bucket that is materially shorter than the rest — it is partial.

    The window almost always starts mid-bucket and ends NOW, so the first and last buckets
    hold a fraction of the readings the others do. Comparing them states a change in the
    measurement window as though it were a change in the building.
    """
    if len(ordered) < 3:
        return ordered
    counts = sorted(len(per_bucket[b]) for b in ordered)
    typical = counts[len(counts) // 2]
    if typical <= 0:
        return ordered
    keep = list(ordered)
    for edge in (0, -1):
        if len(keep) > 2 and len(per_bucket[keep[edge]]) < typical * 0.6:
            keep.pop(edge)
    return keep


def summarise_periods(
    rows: Iterable[Any],
    metadata: Optional[Dict[str, Dict[str, Any]]] = None,
    question: str = "",
    bucket: str = "",
) -> Optional[str]:
    """Per-period aggregates and the change across them, computed here not by the narrator.

    The counterpart of :func:`summarise_groups`: that one answers "which floor", this one
    answers "when" and "how did it change". Energy is summed per period and everything else
    averaged, by the same unit decision, so a period total never silently averages kWh.
    """
    from orchestrator.services.units import _KIND, aggregation_decision, normalise

    metadata = metadata or {}
    stamped: List[Tuple[datetime, str, float]] = []
    for row in rows or []:
        if not isinstance(row, dict):
            continue
        when = _parse_ts(
            row.get("datetime") or row.get("timestamp") or row.get("time") or row.get("Datetime")
        )
        if when is None:
            continue
        try:
            value = float(row.get("value"))
        except (TypeError, ValueError):
            continue
        stamped.append((when, str(row.get("uuid") or row.get("sensor") or ""), value))
    if len(stamped) < 4:
        return None

    span_hours = (max(s[0] for s in stamped) - min(s[0] for s in stamped)).total_seconds() / 3600.0
    if span_hours < 1:
        return None
    size = bucket or _bucket_size(span_hours, question)

    units = {str((metadata.get(u) or {}).get("unit") or "") for _, u, _ in stamped}
    decision = aggregation_decision(units)
    if not decision.ok:
        return f"Per-period aggregates were NOT computed: {decision.reason}."
    unit = decision.target
    is_energy = _KIND.get(normalise(unit)) == "energy"

    per_bucket: Dict[str, List[float]] = {}
    stamps_by: Dict[str, List[datetime]] = {}
    for when, _uid, value in stamped:
        key = _bucket_of(when, size)
        per_bucket.setdefault(key, []).append(value)
        stamps_by.setdefault(key, []).append(when)
    if len(per_bucket) < 2:
        return None

    ordered = sorted(per_bucket)
    nominal = _NOMINAL_HOURS.get(size, 0.0)
    covered = {b: _covered_hours(stamps_by[b]) for b in ordered} if nominal else {}
    # A long window is reported at its ends and its extremes, not as two hundred lines.
    shown = ordered if len(ordered) <= 14 else ordered[:6] + ordered[-6:]
    lines = [
        f"Per-{size} figures, computed from the readings fetched (quote these; do not "
        f"recompute them, and do not say the data holds only latest values):"
    ]
    for key in shown:
        values = per_bucket[key]
        stat = sum(values) if is_energy else mean(values)
        word = "total" if is_energy else "mean"
        span = ""
        if is_energy and covered.get(key) is not None and covered[key] < nominal * _WHOLE_COVERAGE:
            span = f"; covers {covered[key]:.0f} of {nominal:.0f} hours, not a whole {size}"
        lines.append(
            f"- {key}: {word} {_fmt(stat)} {unit} "
            f"({len(values)} readings, {_fmt(min(values))} to {_fmt(max(values))}{span})"
        )
    if len(ordered) > len(shown):
        lines.append(f"- … {len(ordered) - len(shown)} further {size}(s) omitted from this list")

    def _stat(key: str) -> float:
        return sum(per_bucket[key]) if is_energy else mean(per_bucket[key])

    # The change is measured between COMPLETE periods. A window that begins mid-period and
    # ends now makes its two edge buckets partial, and comparing those reports a change in
    # the measurement window as a change in the building (BUG-627).
    whole = _complete_buckets(ordered, per_bucket)
    partial = [b for b in ordered if b not in whole]
    # "This week against last week" on a Friday compares five days with seven: the newest
    # bucket passes the count test above (5/7 of the readings) yet is still filling, and its
    # total is smaller because it is shorter, not because the building used less. A SUM over
    # an unfinished bucket is compared as a rate per smaller unit, and the narrator is told
    # the bucket is in progress. A mean needs none of this: it is per reading already.
    in_progress = [
        b
        for b in dict.fromkeys((whole[0], whole[-1]))
        if covered.get(b) is not None and covered[b] < nominal * _WHOLE_COVERAGE
    ]
    by_rate = is_energy and bool(in_progress)
    if by_rate:
        rate_word, rate_hours = _RATE_UNIT[size]
        cmp_unit = f"{unit} per {rate_word}"

        def _cmp(key: str) -> float:
            return sum(per_bucket[key]) / ((covered.get(key) or nominal) / rate_hours)

    else:
        cmp_unit = unit
        _cmp = _stat
    first, last = _cmp(whole[0]), _cmp(whole[-1])
    change = last - first
    direction = "up" if change > 0 else ("down" if change < 0 else "unchanged")
    pct = f" ({change / first * 100:+.1f}%)" if first else ""
    lines.append(
        f"CHANGE ACROSS THE WINDOW: {_fmt(first)} {cmp_unit} in {whole[0]} to "
        f"{_fmt(last)} {cmp_unit} in {whole[-1]} — {direction} by "
        f"{_fmt(abs(change))} {cmp_unit}{pct}. This is the answer to how it changed; state it."
    )
    if by_rate:
        for b in in_progress:
            lines.append(
                f"IN PROGRESS: {b} covers only {covered[b]:.0f} of {nominal:.0f} hours, so its "
                f"total is not a {size}'s worth. The change above is a rate per {rate_word}; do "
                f"not compare the totals, and say that {b} is still in progress."
            )
    if partial:
        lines.append(
            f"PARTIAL {size}(s) EXCLUDED from that comparison: {', '.join(partial)} — each holds "
            f"far fewer readings than a whole {size} because the window starts or ends inside "
            f"it. Do not compare them with a whole {size}, and do not present their figure as a "
            f"{size}'s worth."
        )
    hi = max(whole, key=_cmp)
    lo = min(whole, key=_cmp)
    lines.append(
        f"HIGHEST {size}: {hi} at {_fmt(_cmp(hi))} {cmp_unit}. LOWEST: {lo} at "
        f"{_fmt(_cmp(lo))} {cmp_unit}."
    )
    return "\n".join(lines)
