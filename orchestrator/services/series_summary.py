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
