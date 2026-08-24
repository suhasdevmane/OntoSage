# -*- coding: utf-8 -*-
"""How much of the window did we actually observe? (V6-T17)

An average over 40% of a window is a different number from an average over all of it, and
today the two are presented identically. Stakeholder catalogue 05 states the requirement per
record -- *"historical windows at least 90% complete"* -- and Master 10.1 additionally
requires explicit missingness reporting in **every** analysis, which is why coverage is
attached even when it passes.

Two decisions worth stating, because both had a tempting alternative:

**Expected count comes from the stream's DECLARED cadence, never from the data.** Inferring
the interval from the rows themselves is circular: a series with a six-hour hole has a median
gap that already reflects the hole, so it would score itself complete. The cadence comes from
``ontosage:archivalIntervalS`` (Master Table 12's third clock), and where a building has not
declared one the answer is *unknown coverage* -- which is honest, and refuses at the gate
rather than guessing.

**Gaps are reported, never filled.** Interpolating across a hole invents data, and it invents
it in exactly the place where the building was not looking.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timedelta
from typing import List, Optional, Sequence, Tuple

from shared.utils import get_logger

logger = get_logger(__name__)


#: How many cadence intervals of silence before a stretch counts as a gap.
#:
#: Real streams jitter -- a sensor reporting every 60 s routinely delivers at 61 s -- and
#: flagging that would make every window look broken and train people to ignore the field.
#: Three intervals is the smallest multiple that clears ordinary jitter while still catching a
#: genuine dropout.
#:
#: Exported because the aggregation module caps each sample's weight at the SAME multiple. Two
#: independent copies of this number would let a mean call an interval covered while the
#: completeness report attached to the same answer called it a gap.
GAP_TOLERANCE = 3.0


@dataclass
class Gap:
    """One stretch of the window with no observations."""

    start: datetime
    end: datetime

    @property
    def minutes(self) -> float:
        return (self.end - self.start).total_seconds() / 60.0


@dataclass
class CompletenessReport:
    """Coverage of one window, and what was missing from it."""

    expected: Optional[int]
    observed: int
    gaps: List[Gap] = field(default_factory=list)
    cadence_seconds: Optional[int] = None

    @property
    def coverage(self) -> Optional[float]:
        """Observed share of expected, or None when the cadence is undeclared.

        None is a real answer meaning *unknown*, and callers must not read it as 1.0. A
        stream whose cadence nobody declared has not thereby been fully observed.
        """
        if not self.expected:
            return None
        return min(1.0, self.observed / self.expected)

    @property
    def is_known(self) -> bool:
        return self.coverage is not None

    def passes(self, floor: float) -> bool:
        """Unknown coverage FAILS a floor.

        The safe direction: an aggregate whose completeness cannot be established must not
        be presented as though it had been checked.
        """
        cov = self.coverage
        return cov is not None and cov >= floor

    def describe(self) -> str:
        """One sentence for an answer footer or a refusal."""
        if not self.is_known:
            return (
                "coverage unknown - this stream declares no archival interval, so the share "
                "of the window actually observed cannot be established"
            )
        pct = (self.coverage or 0) * 100
        if not self.gaps:
            return f"{pct:.0f}% of the requested window was observed"
        longest = max(self.gaps, key=lambda g: g.minutes)
        return (
            f"{pct:.0f}% of the requested window was observed; "
            f"{len(self.gaps)} gap(s), the longest {longest.minutes:.0f} minutes "
            f"from {longest.start:%Y-%m-%d %H:%M}"
        )


def expected_samples(
    start: datetime, end: datetime, cadence_seconds: Optional[int]
) -> Optional[int]:
    """How many observations the window SHOULD contain, from the declared cadence."""
    if not cadence_seconds or cadence_seconds <= 0:
        return None
    span = (end - start).total_seconds()
    if span <= 0:
        return None
    return max(1, int(span // cadence_seconds))


def find_gaps(
    timestamps: Sequence[datetime],
    start: datetime,
    end: datetime,
    cadence_seconds: Optional[int],
    tolerance: float = GAP_TOLERANCE,
) -> List[Gap]:
    """Stretches with no observation, longer than `tolerance` x the declared cadence.

    A tolerance is necessary because real streams jitter: a sensor reporting every 60 s will
    routinely deliver at 61 s, and flagging that as a gap would make every window look
    broken and train people to ignore the field. Three intervals is the smallest multiple
    that clears ordinary jitter while still catching a genuine dropout.
    """
    if not cadence_seconds or cadence_seconds <= 0:
        return []
    limit = timedelta(seconds=cadence_seconds * tolerance)
    gaps: List[Gap] = []
    ordered = sorted(timestamps)

    if not ordered:
        return [Gap(start, end)]
    if ordered[0] - start > limit:
        gaps.append(Gap(start, ordered[0]))
    for a, b in zip(ordered, ordered[1:]):
        if b - a > limit:
            gaps.append(Gap(a, b))
    if end - ordered[-1] > limit:
        gaps.append(Gap(ordered[-1], end))
    return gaps


def assess(
    timestamps: Sequence[datetime],
    start: datetime,
    end: datetime,
    cadence_seconds: Optional[int],
) -> CompletenessReport:
    """Coverage of one window for one stream."""
    inside = [t for t in timestamps if start <= t <= end]
    return CompletenessReport(
        expected=expected_samples(start, end, cadence_seconds),
        observed=len(inside),
        gaps=find_gaps(inside, start, end, cadence_seconds),
        cadence_seconds=cadence_seconds,
    )


def duration_above(
    samples: Sequence[Tuple[datetime, float]],
    threshold: float,
    cadence_seconds: Optional[int],
) -> Tuple[Optional[float], str]:
    """Minutes spent above a threshold, and an honest caveat (V6-T19 groundwork).

    Returns (minutes, basis). Absent samples are absent TIME, not time below the threshold:
    "hours above 1000 ppm" computed over a series with a six-hour hole understates the answer
    and looks authoritative doing it. So each sample accounts for at most one cadence
    interval, and the basis names what was actually counted -- which lets a caller
    distinguish *not exceeded* from *not observed*.
    """
    if not cadence_seconds or cadence_seconds <= 0:
        return None, "no declared cadence, so exceedance duration cannot be computed"
    inside = sorted(samples, key=lambda s: s[0])
    if not inside:
        return None, "no observations in the requested window"
    step = cadence_seconds / 60.0
    minutes = sum(step for _, v in inside if v > threshold)
    return minutes, (
        f"counted over {len(inside)} observation(s) at {step:.1f}-minute resolution; "
        "unobserved intervals are excluded rather than counted as below threshold"
    )
