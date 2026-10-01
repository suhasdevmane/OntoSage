# -*- coding: utf-8 -*-
"""Two forecasts, and whether either may be called the higher one (W2-03, BUG-946/885).

WHY THIS IS A MODULE AND NOT A SENTENCE IN A PROMPT
---------------------------------------------------
BUG-885 was a single instant: *"Floor 3 is warmer than Floor 4"* asserted twice in bold from a
**0.06 °C** gap between two means whose readings spanned **3.9 °C**. The verdict half of that
was fixed by computing the comparison rather than narrating it. A forecast makes the same
mistake cost more, because a prediction carries an interval that a reader is entitled to see
BEFORE a winner is named — and W2-03's acceptance is exactly that: *"the answer names BOTH
forecasts and declines to pick a winner when the intervals overlap."*

So the rule is arithmetic, here, once, rather than a hope about how the narration will phrase
two numbers.

THE RULE
--------
Two forecasts are compared over the steps they SHARE. If their 95% intervals overlap at the
aggregate being compared, no winner may be named and the answer says the two are
indistinguishable at this horizon. If they do not overlap, the higher one is named WITH both
intervals, so the reader can see the separation rather than take it on trust.

A separation smaller than the reported precision is also no separation: two forecasts differing
by 0.004 °C are equal to anyone reading "23.0 °C", and naming a winner there is BUG-885 again
one decimal place down.

WHAT THIS DOES NOT DO
---------------------
It does not bind the sensors for the two sides, and that is deliberate rather than unfinished:
**a side may not be assigned by parsing a sensor's label.** BUG-884 was a floor question bound
to the sensors NAMED for the floor instead of the sensors ON it, and `data_coverage_audit.py`
files roughly 4,000 of 5,874 sensors under "F?" for the same reason. Each side has to be bound
through the graph — floor to spaces to points, filtered by the resolved Brick class — which is
the caller's job. This function takes two already-bound, already-aggregated forecasts and says
what may honestly be said about the pair.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import List, Optional, Sequence, Tuple

from shared.utils import get_logger

logger = get_logger(__name__)

#: A difference at or below the precision the answer is written to is not a difference. Two
#: digits is what every forecast figure in this system is rendered with, so a gap that rounds
#: away is a gap the reader cannot see.
_REPORTED_PRECISION = 0.01


@dataclass(frozen=True)
class SideForecast:
    """One side of the comparison: a named place and its predicted series with 95% bands."""

    name: str
    forecast: Sequence[float]
    lower_95: Sequence[float]
    upper_95: Sequence[float]
    n_sensors: int = 0
    how: str = "mean"  # "mean" or "total" — from the QUANTITY, never the wording (lesson #139)


@dataclass(frozen=True)
class Verdict:
    """What may be said about the pair, and the figures it was said from."""

    comparable: bool  # were there shared steps to compare at all?
    separated: bool  # do the 95% intervals fail to overlap?
    winner: Optional[str]  # None whenever `separated` is False
    figures: Tuple[float, float]  # (first side's aggregate, second side's)
    intervals: Tuple[Tuple[float, float], Tuple[float, float]]
    n_steps: int
    reason: str


def _reduce(values: Sequence[float], how: str) -> float:
    return sum(values) if how == "total" else sum(values) / len(values)


def compare(
    a: SideForecast,
    b: SideForecast,
    steps: Optional[Sequence[int]] = None,
) -> Optional[Verdict]:
    """Compare two forecasts over the steps they share, or None when they share none.

    `steps` restricts the comparison to a sub-window of the horizon (the indices
    `window_aggregate` selects for "tomorrow afternoon", say). None compares the whole of the
    shared horizon.
    """
    shared = min(len(a.forecast), len(b.forecast))
    if shared == 0:
        return None
    picked: List[int] = (
        [i for i in steps if 0 <= i < shared] if steps is not None else list(range(shared))
    )
    if not picked:
        return None

    how = a.how if a.how == b.how else "mean"
    fa = _reduce([float(a.forecast[i]) for i in picked], how)
    fb = _reduce([float(b.forecast[i]) for i in picked], how)

    def _band(side: SideForecast) -> Tuple[float, float]:
        lows = [float(side.lower_95[i]) for i in picked if i < len(side.lower_95)]
        highs = [float(side.upper_95[i]) for i in picked if i < len(side.upper_95)]
        if not lows or not highs:
            # No band is not a narrow band: a missing interval must not read as certainty, so
            # the side is given an unbounded one and the pair can never be called separated.
            return (float("-inf"), float("inf"))
        return (_reduce(lows, how), _reduce(highs, how))

    lo_a, hi_a = _band(a)
    lo_b, hi_b = _band(b)
    overlap = lo_a <= hi_b and lo_b <= hi_a
    gap = abs(fa - fb)
    separated = (not overlap) and gap > _REPORTED_PRECISION

    if overlap:
        reason = "the 95% intervals overlap"
    elif gap <= _REPORTED_PRECISION:
        reason = "the two forecasts differ by less than the precision they are reported to"
    else:
        reason = "the 95% intervals do not overlap"

    winner = None
    if separated:
        winner = a.name if fa > fb else b.name

    return Verdict(
        comparable=True,
        separated=separated,
        winner=winner,
        figures=(fa, fb),
        intervals=((lo_a, hi_a), (lo_b, hi_b)),
        n_steps=len(picked),
        reason=reason,
    )


def render(
    a: SideForecast,
    b: SideForecast,
    verdict: Optional[Verdict],
    unit: str = "",
    window_label: str = "",
) -> str:
    """The sentence W2-03 asks for: both forecasts, and a winner only when there is one."""
    where = f" over {window_label}" if window_label else ""
    if verdict is None or not verdict.comparable:
        return (
            f"**No comparison is stated{where}: the two forecasts share no predicted step, "
            f"so there is nothing to compare like with like.**"
        )
    fa, fb = verdict.figures
    (lo_a, hi_a), (lo_b, hi_b) = verdict.intervals

    def _one(side: SideForecast, value: float, lo: float, hi: float) -> str:
        word = "total" if side.how == "total" else "mean"
        band = (
            f" (95% {lo:.2f} to {hi:.2f}{unit})"
            if lo not in (float("-inf"),) and hi not in (float("inf"),)
            else " (no interval available)"
        )
        over = f", over {side.n_sensors} sensor(s)" if side.n_sensors else ""
        return f"{side.name} {word} {value:.2f}{unit}{band}{over}"

    both = f"{_one(a, fa, lo_a, hi_a)}; {_one(b, fb, lo_b, hi_b)}"
    if verdict.separated and verdict.winner:
        return (
            f"**{verdict.winner} is forecast higher{where}.** {both}. "
            f"Compared over {verdict.n_steps} predicted step(s); {verdict.reason}."
        )
    return (
        f"**Neither is forecast higher{where} — the two cannot be told apart at this "
        f"horizon.** {both}. Compared over {verdict.n_steps} predicted step(s); "
        f"{verdict.reason}, so naming a winner would assert more than the forecasts support."
    )
