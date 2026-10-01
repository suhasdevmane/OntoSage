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
