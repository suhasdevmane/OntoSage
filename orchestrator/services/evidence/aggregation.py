# -*- coding: utf-8 -*-
"""Aggregation that treats absent samples as absent TIME (V6-T19).

Acceptance test 2, and the failure it describes: *"hours above 1000 ppm" computed over a
series with a six-hour hole understates the answer and looks authoritative doing it.*

Two aggregates carry almost every question a stakeholder actually asks -- an average over a
window, and how long something stayed past a threshold -- and both are wrong in a specific,
invisible way when the series has holes.

**Why the arithmetic mean is wrong here.** It weights every sample equally, so a stream that
reported every minute for two hours and then once an hour for the rest of the day is dominated
by those two hours. Nothing in the output says so.

**Why naive time-weighting is worse.** The obvious repair -- weight each sample by the interval
until the next one -- hands the entire six-hour hole to the last sample before it, as though
that one reading described the whole morning. That converts an under-statement into a
fabrication, which is the trade this project never makes. So each sample's weight is CAPPED at
the declared cadence (times a tolerance): a sample speaks for its own interval and no further,
and the time nothing spoke for is reported as missing rather than silently attributed.

**Why the cadence must be declared, never inferred.** Inferring it from the data infers it from
a series that already contains the hole -- the inferred cadence stretches to fit, and the
stream scores itself complete. The same reasoning is why
:mod:`orchestrator.services.evidence.completeness` takes cadence as an argument, and this
module reuses that decision rather than relitigating it.

**A low-completeness window returns no number at all.** Not a number with a warning attached: a
figure printed with a caveat beside it gets read as a figure, and the caveat gets skimmed. The
whole point of V6 is that "not assessable, and here is why" is a first-class answer.

Pure, no I/O, building-agnostic -- the cadence, the floor and the samples all arrive from the
caller.
"""

from __future__ import annotations

from datetime import datetime, timedelta
from typing import Dict, List, Optional, Sequence, Tuple

from orchestrator.services.evidence.completeness import GAP_TOLERANCE, assess
from shared.utils import get_logger

logger = get_logger(__name__)

Sample = Tuple[datetime, float]

# GAP_TOLERANCE is IMPORTED, not redeclared: one sample may speak for exactly as long as
# completeness.find_gaps() is willing to call silence. Two copies of the number would drift,
# and the symptom would be a mean that counted an interval the same answer reported as a gap.

#: Below this share of expected observations, no aggregate is returned. Overridable per call
#: from EvidencePolicy.min_completeness(), which is where the building-specific figure lives.
DEFAULT_MIN_COMPLETENESS = 0.9


def time_weighted_mean(
    samples: Sequence[Sample],
    start: datetime,
    end: datetime,
    cadence_seconds: Optional[int],
    *,
    min_completeness: float = DEFAULT_MIN_COMPLETENESS,
    unit: str = "",
) -> Dict[str, object]:
    """Mean over a window, weighting each sample by the time it genuinely speaks for.

    Returns the recipe dict shape used across ``recipes_compute`` -- value / unit / method /
    citation, or ``error`` -- extended with ``completeness`` and ``covered_minutes`` so the
    caller can state its basis without recomputing it.

    Each sample's weight is the time until the next sample, **capped** at
    ``cadence x GAP_TOLERANCE``. The cap is the whole design: without it the last reading
    before a six-hour hole would be weighted as though it had been true all morning.
    """
    report = assess([t for t, _ in samples], start, end, cadence_seconds)
    inside = _inside(samples, start, end)

    if not inside:
        return _error(
            "no observations in the requested window, so no average can be computed",
            method="time-weighted mean",
        )
    if cadence_seconds is None or cadence_seconds <= 0:
        return _error(
            "the stream's cadence is not declared, so the share of the window that was "
            "actually observed is unknown and an average would overstate its basis",
            method="time-weighted mean",
        )

    coverage = report.coverage
    if coverage is not None and coverage < min_completeness:
        return _error(
            f"only {coverage:.0%} of the expected observations are present "
            f"(floor {min_completeness:.0%}), so an average over this window would be "
            "reported as though it described time it never observed",
            method="time-weighted mean",
            completeness=coverage,
            gaps=_describe_gaps(report.gaps),
        )

    cap = timedelta(seconds=cadence_seconds * GAP_TOLERANCE)
    weights = _weights(inside, end, cap)
    total = sum(weights)
    if total <= 0:
        return _error("no time is covered by the observations", method="time-weighted mean")

    value = sum(v * w for (_, v), w in zip(inside, weights)) / total
    covered = total / 60.0
    span = max((end - start).total_seconds() / 60.0, 0.0)
    return {
        "value": value,
        "unit": unit,
        "completeness": coverage,
        "covered_minutes": round(covered, 1),
        "window_minutes": round(span, 1),
        "gaps": _describe_gaps(report.gaps),
        "method": (
            f"time-weighted mean of {len(inside)} observation(s); each weighted by the time "
            f"until the next, capped at {cadence_seconds * GAP_TOLERANCE / 60:.0f} minutes so "
            "no reading speaks for a period it did not observe"
        ),
        "citation": (
            "unobserved intervals are excluded from the weighting rather than attributed to "
            "the preceding reading"
        ),
    }


def exceedance_duration(
    samples: Sequence[Sample],
    threshold: float,
    start: datetime,
    end: datetime,
    cadence_seconds: Optional[int],
    *,
    above: bool = True,
    min_completeness: float = DEFAULT_MIN_COMPLETENESS,
) -> Dict[str, object]:
    """How long the series stayed past a threshold, counting only observed time.

    The acceptance-test case. Two figures are returned rather than one, because they answer
    different questions and conflating them is the defect:

    * ``value`` -- minutes OBSERVED past the threshold;
    * ``unobserved_minutes`` -- minutes for which there is no observation either way.

    A caller that prints only the first is still honest; a caller that prints "3 hours" when
    six hours went unobserved is not, and now has the number it needs to say so.

    `above=False` measures time below the threshold, for the questions phrased that way
    ("how long was it below 18 C") -- the same arithmetic with the comparison inverted, so it
    lives here rather than being reimplemented by a caller.
    """
    report = assess([t for t, _ in samples], start, end, cadence_seconds)
    inside = _inside(samples, start, end)
    direction = "above" if above else "below"

    if cadence_seconds is None or cadence_seconds <= 0:
        return _error(
            "the stream's cadence is not declared, so an exceedance duration cannot be "
            "distinguished from a sparse sample",
            method=f"time {direction} threshold",
        )
    if not inside:
        return _error(
            "no observations in the requested window, so time past the threshold is unknown "
            "-- which is not the same as zero",
            method=f"time {direction} threshold",
        )

    coverage = report.coverage
    if coverage is not None and coverage < min_completeness:
        return _error(
            f"only {coverage:.0%} of the expected observations are present "
            f"(floor {min_completeness:.0%}); the time past the threshold would be a "
            "lower bound presented as a total",
            method=f"time {direction} threshold",
            completeness=coverage,
            gaps=_describe_gaps(report.gaps),
        )

    cap = timedelta(seconds=cadence_seconds * GAP_TOLERANCE)
    weights = _weights(inside, end, cap)
    past = sum(
        w for (_, v), w in zip(inside, weights) if (v > threshold if above else v < threshold)
    )
    covered = sum(weights)
    span = max((end - start).total_seconds(), 0.0)

    return {
        "value": round(past / 60.0, 1),
        "unit": "minutes",
        "threshold": threshold,
        "direction": direction,
        "completeness": coverage,
        "covered_minutes": round(covered / 60.0, 1),
        "unobserved_minutes": round(max(span - covered, 0.0) / 60.0, 1),
        "gaps": _describe_gaps(report.gaps),
        "method": (
            f"observed time {direction} {threshold:g}, summed over {len(inside)} observation(s) "
            f"each counted for at most {cadence_seconds * GAP_TOLERANCE / 60:.0f} minutes"
        ),
        "citation": (
            "unobserved intervals are reported separately rather than counted as time "
            f"not {direction} the threshold"
        ),
    }


def describe_basis(result: Dict[str, object]) -> str:
    """One sentence a lane can put in an answer, stating what the figure rests on.

    Empty for a failed aggregate: the error text already says what happened, and appending a
    basis to a refusal would read as though a number had been produced.
    """
    if not result or result.get("error"):
        return ""
    parts: List[str] = []
    completeness = result.get("completeness")
    if isinstance(completeness, float):
        parts.append(f"based on {completeness:.0%} of the expected observations")
    unobserved = result.get("unobserved_minutes")
    if isinstance(unobserved, (int, float)) and unobserved > 0:
        parts.append(f"{unobserved:g} minutes of the window were not observed at all")
    gaps = result.get("gaps") or []
    if isinstance(gaps, list) and gaps:
        parts.append(f"{len(gaps)} gap(s) in the record")
    return ("; ".join(parts) + ".").capitalize() if parts else ""


# -- internals ---------------------------------------------------------------


def _describe_gaps(gaps: Sequence[object]) -> List[str]:
    """Each gap as a readable span.

    Rendered here rather than in the answer template so every caller says the same thing about
    the same hole -- two lanes wording a gap differently is how a reader concludes there were
    two of them.
    """
    out: List[str] = []
    for g in gaps:
        start = getattr(g, "start", None)
        end = getattr(g, "end", None)
        minutes = getattr(g, "minutes", None)
        if start is None or end is None or minutes is None:
            continue
        out.append(
            f"{start.strftime('%Y-%m-%d %H:%M')} to {end.strftime('%H:%M')} ({minutes:.0f} min)"
        )
    return out


def _inside(samples: Sequence[Sample], start: datetime, end: datetime) -> List[Sample]:
    return sorted((t, v) for t, v in samples if start <= t <= end)


def _weights(inside: Sequence[Sample], end: datetime, cap: timedelta) -> List[float]:
    """Seconds each sample speaks for: to the next sample, or the cap, whichever is smaller.

    The final sample is treated identically -- it speaks until the window ends or its cap
    expires, never automatically to the end of the window. A window that closes long after the
    last reading is a window whose tail was not observed, and saying otherwise would extend one
    reading across a silence, which is the same error the cap exists to prevent.
    """
    out: List[float] = []
    for i, (t, _) in enumerate(inside):
        nxt = inside[i + 1][0] if i + 1 < len(inside) else end
        span = min(max((nxt - t).total_seconds(), 0.0), cap.total_seconds())
        out.append(span)
    return out


def _error(message: str, *, method: str, **extra: object) -> Dict[str, object]:
    """A refusal in the recipe dict shape. Never carries a `value`.

    Deliberately no partial figure: a number printed beside a caveat is read as a number, and
    the caveat is skimmed.
    """
    return {"error": message, "method": method, **extra}
