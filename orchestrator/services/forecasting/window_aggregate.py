# -*- coding: utf-8 -*-
"""The one number a forecast was asked for, reduced from the series it predicts (BUG-874).

    "Based on the last two weeks, what is the expected mean humidity in room 2.01
     tomorrow afternoon?"

produced a 24-row hourly prediction table and never stated the expected mean for tomorrow
afternoon, which is the only number the question asked for. The forecast was fitted, the
sensor was right, the horizon was right; the output SHAPE is fixed — horizon, model
selection, per-step predictions with intervals — and nothing read the aggregate the question
names, or the sub-window it names, and reduced the prediction to it.

Leaving the reader to average twenty-four rows by eye is not an answer, and it is the kind
of near-miss the answer-relevance gate used to discard outright (BUG-873): its judgement
was correct, and after that fix the incomplete answer at least reaches the reader. This
closes the other half.

THREE RULES THIS FOLLOWS
------------------------
**The sub-window is the OCCUPANTS' afternoon.** `future_index` carries store (UTC) stamps,
and the hours a word like "afternoon" names are local. Each step is therefore converted with
`requested_interval.to_local` before the mask is applied — "convert only for display, and to
decide which local hours a word names". Applying a 12:00-18:00 mask to UTC stamps would
answer about 13:00-19:00 for an occupant on BST.

**A mask that selects nothing is said, not widened.** If the horizon does not reach the
window the question named, the honest answer is that it does not — silently reducing over
every step instead would put a figure about the next hour under a heading about tomorrow
afternoon.

**A total is a property of the QUANTITY, not of the wording** (lesson #139). "Total" is
offered only where adding readings is meaningful; asked of an instantaneous quantity it is
answered with the mean and the substitution is stated.
"""

from __future__ import annotations

import re
from datetime import datetime
from typing import List, Optional, Sequence, Tuple

from shared.utils import get_logger

logger = get_logger(__name__)

#: The reduction a question asks a forecast for, most specific pattern first.
#:
#: "peak" and "highest" are the same request as "maximum"; a reader asking either wants one
#: number, not a table to scan. Ordered so that "average" cannot be claimed by a looser
#: pattern later in the list.
_REDUCTIONS: Sequence[Tuple[str, str]] = (
    (r"\b(?:mean|average|avg|typical|on\s+average)\b", "mean"),
    (r"\b(?:max(?:imum)?|highest|peak|hottest|warmest|worst|busiest)\b", "max"),
    (r"\b(?:min(?:imum)?|lowest|coldest|coolest|quietest)\b", "min"),
    (r"\b(?:total|sum|altogether|in\s+all|overall\s+consumption)\b", "total"),
)

#: How each reduction reads in a sentence.
_WORD = {"mean": "mean", "max": "highest", "min": "lowest", "total": "total"}

#: Quantities for which adding readings is meaningful. Everything else is a level measured at
#: an instant, and a sum of levels is not a quantity anyone has a use for.
_SUMMABLE_UNITS = ("kwh", "wh", "mwh", "kvarh", "m3", "m³", "l", "litre", "liter", "kg")


def requested_reduction(question: str) -> Optional[str]:
    """Which single figure the question asks for, or None when it asks for the series.

    None is the ordinary case and means the table is the answer: "forecast the temperature
    for tomorrow" wants the shape, and reducing it to one number would lose the question.
    """
    q = (question or "").lower()
    for pattern, kind in _REDUCTIONS:
        if re.search(pattern, q):
            return kind
    return None


def _is_summable(unit: str) -> bool:
    u = (unit or "").strip().lower()
    return any(u == s or u.startswith(s) for s in _SUMMABLE_UNITS)


def _to_local(stamp: str, tz_name: Optional[str]) -> Optional[datetime]:
    """One future step as building-local wall time, or None when it cannot be read."""
    try:
        from orchestrator.services.requested_interval import to_local

        text = str(stamp).replace("T", " ")[:19]
        for fmt in ("%Y-%m-%d %H:%M:%S", "%Y-%m-%d %H:%M"):
            try:
                return to_local(datetime.strptime(text, fmt), tz_name)
            except ValueError:
                continue
        return None
    except Exception:  # pragma: no cover - a clock failure must not cost the forecast
        return None


def reduce_to_requested_figure(
    question: str,
    future_index: Sequence[str],
    forecast: Sequence[float],
    lower_95: Sequence[float],
    upper_95: Sequence[float],
    unit: str = "",
    horizon_label: str = "",
    tz_name: Optional[str] = None,
    occupied_hours: Tuple[Optional[int], Optional[int]] = (None, None),
) -> Optional[str]:
    """One sentence giving the figure the question asked for, or None when it asked for none.

    Returns None — leaving the table as the whole answer — when no reduction is named, when
    the forecast is empty, or when the timestamps cannot be read, because a reduction whose
    window cannot be established is a guess about which steps it covered.
    """
    kind = requested_reduction(question)
    if kind is None or not forecast:
        return None

    mask = None
    try:
        from orchestrator.services.evidence.time_windows import detect_mask

        mask = detect_mask(question, occupied_hours[0], occupied_hours[1])
    except Exception as exc:  # pragma: no cover - no mask is the whole horizon
        logger.debug(f"[forecast_window] mask detection skipped: {exc}")

    steps = list(range(len(forecast)))
    window = horizon_label or "the forecast horizon"
    if mask is not None:
        stamps = [_to_local(s, tz_name) for s in future_index]
        if any(s is None for s in stamps[: len(forecast)]):
            logger.info(
                "[forecast_window] '%s' was asked for but a predicted step carries no "
                "readable timestamp — the window cannot be established, so no figure is "
                "stated",
                mask.describe(),
            )
            return None
        steps = [i for i in steps if i < len(stamps) and mask.covers(stamps[i])]
        window = mask.describe()
        if not steps:
            return (
                f"**No {_WORD[kind]} is stated for {window}: the forecast reaches only "
                f"{horizon_label or 'the end of its horizon'}, which does not include it.** "
                f"The predictions below cover the horizon that was fitted."
            )

    values = [float(forecast[i]) for i in steps]
    lows = [float(lower_95[i]) for i in steps if i < len(lower_95)]
    highs = [float(upper_95[i]) for i in steps if i < len(upper_95)]

    note = ""
    if kind == "total" and not _is_summable(unit):
        kind = "mean"
        note = (
            " A total was asked for; adding readings of this quantity does not produce a "
            "quantity, so the mean is given instead."
        )

    if kind == "mean":
        figure = sum(values) / len(values)
    elif kind == "max":
        figure = max(values)
    elif kind == "min":
        figure = min(values)
    else:
        figure = sum(values)

    interval = ""
    if lows and highs:
        if kind == "mean":
            lo, hi = sum(lows) / len(lows), sum(highs) / len(highs)
        elif kind == "max":
            lo, hi = max(lows), max(highs)
        elif kind == "min":
            lo, hi = min(lows), min(highs)
        else:
            lo, hi = sum(lows), sum(highs)
        interval = f" (95% interval {lo:.2f} to {hi:.2f}{unit})"

    return (
        f"**The predicted {_WORD[kind]} for {window} is {figure:.2f}{unit}"
        f"{interval}.** Computed over the {len(values)} predicted step(s) that fall inside "
        f"it, out of {len(forecast)} in the horizon.{note}"
    )


#: "Will meeting room 4.11 get STUFFY this afternoon?" (BUG-1592): (pattern, measurand, which
#: end of the comfort band, how the answer names it). A forecast table with no verdict was deleted
#: by the relevance gate as not answering the question asked.
_FUTURE_ASK = re.compile(r"\b(?:will|going\s+to|likely\s+to|expected\s+to|about\s+to)\b", re.I)
_COMFORT_ASKS = (
    (re.compile(r"\bstuff(?:y|ier)\b", re.I), "co2", "upper", "stuffy"),
    (
        re.compile(
            r"\btoo\s+(?:warm|hot)\b|\boverheat\w*\b|\b(?:get|become)\s+(?:warm|hot)\b", re.I
        ),
        "temperature",
        "upper",
        "too warm",
    ),
    (
        re.compile(r"\btoo\s+(?:cold|cool|chilly)\b|\b(?:get|become)\s+(?:cold|chilly)\b", re.I),
        "temperature",
        "lower",
        "too cold",
    ),
    (re.compile(r"\b(?:too\s+)?humid\b|\bmuggy\b", re.I), "humidity", "upper", "too humid"),
    (re.compile(r"\btoo\s+dry\b", re.I), "humidity", "lower", "too dry"),
)
#: The unit a forecast must carry for its measurand, so a limit is never compared across units.
_UNIT_OF = {"co2": ("ppm",), "temperature": ("°c", "degc", "c"), "humidity": ("%", "percent")}


def comfort_verdict(
    question: str,
    future_index: Sequence[str],
    forecast: Sequence[float],
    lower_95: Sequence[float],
    upper_95: Sequence[float],
    unit: str = "",
    horizon_label: str = "",
    tz_name: Optional[str] = None,
    occupied_hours: Tuple[Optional[int], Optional[int]] = (None, None),
) -> Optional[str]:
    """'Will it get stuffy this afternoon?' answered against the standards table, or None.

    The forecast's peak (or trough, for "too cold") over the window asked about, and the edge of
    its 95% band, are compared with the band the system's standards table gives the measurand.
    Three outcomes, worded by what the band allows: above the limit (likely), the band reaches it
    (possibly), the band stays clear (unlikely). None when the question names no comfort word, the
    unit does not match the measurand, or no band is listed: then no verdict is invented.
    """
    if not forecast or not _FUTURE_ASK.search(question or ""):
        return None
    ask = next((a for a in _COMFORT_ASKS if a[0].search(question or "")), None)
    if ask is None:
        return None
    _rx, measurand, end, word = ask
    u = (unit or "").strip()
    if not any(u.lower() == x or u.lower().endswith(x) for x in _UNIT_OF[measurand]):
        return None
    try:
        import json

        from orchestrator.services import aggregate_lane as al

        table = json.loads(al._STANDARDS_FILE.read_text(encoding="utf-8"))
        entry = table.get(al._DEFAULT_STANDARD) or {}
        band = entry.get(measurand)
        lo_lim, hi_lim = float(band[0]), float(band[1])
        standard = str(entry.get("name") or al._DEFAULT_STANDARD)
    except Exception as exc:  # no listed band, no verdict
        logger.debug(f"[forecast_window] no comfort band for {measurand}: {exc}")
        return None

    steps = list(range(len(forecast)))
    window = horizon_label or "the forecast horizon"
    try:
        from orchestrator.services.evidence.time_windows import detect_mask

        mask = detect_mask(question, occupied_hours[0], occupied_hours[1])
    except Exception:  # pragma: no cover - no mask is the whole horizon
        mask = None
    passed = ""
    if mask is not None:
        stamps = [_to_local(s, tz_name) for s in future_index]
        if any(s is None for s in stamps[: len(forecast)]):
            return None
        covered = [i for i in steps if i < len(stamps) and mask.covers(stamps[i])]
        if covered:
            steps, window = covered, mask.describe()
        else:
            # THE WINDOW ASKED ABOUT IS NOT IN THE FORECAST (BUG-1611). "Will room 4.11 get stuffy
            # this afternoon?" asked at 19:03 printed a six-hour table and no verdict: the
            # afternoon had passed and no step fell in it. Say so, then judge the horizon there is.
            first, last = stamps[0], stamps[min(len(forecast), len(stamps)) - 1]
            hours = ""
            if getattr(mask, "start_hour", None) is not None and mask.start_hour != mask.end_hour:
                hours = f", {mask.start_hour:02d}:00–{mask.end_hour % 24:02d}:00"
            passed = (
                f"The time asked about ({mask.describe()}{hours}) is not in this forecast, which "
                f"runs from {first:%a %H:%M} to {last:%a %H:%M}. "
            )
    sp = " " if u and not u.startswith("°") and u != "%" else ""
    values = [float(forecast[i]) for i in steps]
    if end == "upper":
        point = max(values)
        edge = max(float(upper_95[i]) for i in steps if i < len(upper_95)) if upper_95 else point
        limit, beyond, side = hi_lim, point > hi_lim, "above"
        reaches = edge > hi_lim
        shape = "peaks at"
    else:
        point = min(values)
        edge = min(float(lower_95[i]) for i in steps if i < len(lower_95)) if lower_95 else point
        limit, beyond, side = lo_lim, point < lo_lim, "below"
        reaches = edge < lo_lim
        shape = "falls to"
    name = {"co2": "CO2"}.get(measurand, measurand)
    cite = (
        f"the {limit:g}{sp}{u} limit for {name} in the {standard} entry of this system's "
        "standards table"
    )
    if beyond:
        lead = (
            f"**Likely yes:** the forecast for {window} {shape} {point:.0f}{sp}{u}, {side} {cite}."
        )
    elif reaches:
        lead = (
            f"**Possibly:** the forecast for {window} {shape} {point:.0f}{sp}{u}, inside {cite}, "
            f"but the edge of its 95% band reaches {edge:.0f}{sp}{u}."
        )
    else:
        lead = (
            f"**Unlikely:** the forecast for {window} {shape} {point:.0f}{sp}{u}, and even the edge "
            f"of its 95% band ({edge:.0f}{sp}{u}) stays inside {cite}."
        )
    return passed + lead + f" ('{word}' is read as {name} {side} that limit.)"
