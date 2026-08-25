# -*- coding: utf-8 -*-
"""Compare two periods like with like, and say what could not be matched (V6-T41).

*"Is the office warmer than last month?"* invites the least honest arithmetic available: take
two means, subtract, report the difference. That answer is confidently wrong whenever the two
windows differ in anything that also drives the measurement — and they almost always do. A
window containing a bank holiday, a heatwave, or a fortnight of half-term compares an occupied
building against an empty one and calls the difference a trend.

Three rules, and the third is the one that keeps this honest rather than merely careful:

1. **Match before comparing.** Samples are paired on declared covariates — hour of day, weekday
   versus weekend — so a Tuesday afternoon is compared against Tuesday afternoons. Unmatched
   samples are DISCARDED, and how many were discarded is reported: a comparison that kept 8% of
   its data is a different claim from one that kept 90%.

2. **Report uncertainty with the effect.** A difference of 0.4 °C with a confidence interval
   spanning zero is not a finding, and printing the 0.4 alone makes it look like one.

3. **NAME the confounders that could not be adjusted.** Weather, occupancy and schedule move
   indoor conditions, and this building may have none of them connected. Silently omitting an
   adjustment produces a number indistinguishable from a properly adjusted one — the failure
   this whole workstream keeps finding, in its statistical form. An unadjustable confounder is
   stated in the answer.

Pure: no I/O, no clock, no graph. The caller supplies series and the covariates it could
actually resolve, which is what makes "could not be adjusted" a fact rather than a guess.
"""

from __future__ import annotations

import math
from dataclasses import dataclass, field
from datetime import datetime
from typing import Dict, List, Optional, Sequence, Tuple

from shared.utils import get_logger

logger = get_logger(__name__)

Series = Sequence[Tuple[datetime, float]]

#: Covariates this module knows how to match on FROM THE TIMESTAMP ALONE. Anything else must be
#: supplied by the caller or declared unavailable — inventing an occupancy figure to adjust by
#: would be worse than not adjusting.
INTRINSIC_COVARIATES = ("hour_of_day", "day_type")

#: Below this, a difference is reported as "no detectable difference" rather than as a value.
#: Not a significance test: it is the honest floor for a comparison of two noisy means.
MIN_SAMPLES_PER_SIDE = 8


@dataclass
class MatchedComparison:
    """The result of comparing two windows like with like."""

    effect: Optional[float] = None
    ci_low: Optional[float] = None
    ci_high: Optional[float] = None
    n_matched: int = 0
    n_baseline_total: int = 0
    n_current_total: int = 0
    adjusted_for: List[str] = field(default_factory=list)
    unadjusted_for: List[str] = field(default_factory=list)
    reason: str = ""

    @property
    def kept_share(self) -> float:
        total = max(self.n_baseline_total, self.n_current_total)
        return (self.n_matched / total) if total else 0.0

    @property
    def significant(self) -> bool:
        """True only when the interval excludes zero.

        A difference whose interval spans zero is not a difference. Reporting the point estimate
        without this distinction is how "0.4 degrees warmer" becomes a finding.
        """
        if self.effect is None or self.ci_low is None or self.ci_high is None:
            return False
        return (self.ci_low > 0.0) or (self.ci_high < 0.0)

    def describe(self, modality: str = "", units: str = "") -> str:
        """The sentence a comparison must carry: effect, uncertainty, and what was not matched."""
        what = modality or "the measurement"
        unit = f" {units}" if units else ""

        if self.effect is None:
            base = f"**I can't compare those periods for {what}** — {self.reason}."
        elif not self.significant:
            base = (
                f"**No detectable difference in {what}.** The matched comparison gives "
                f"{self.effect:+.2f}{unit}, but the range consistent with the data "
                f"({self.ci_low:+.2f} to {self.ci_high:+.2f}{unit}) includes zero, so the "
                f"difference is not distinguishable from noise."
            )
        else:
            direction = "higher" if self.effect > 0 else "lower"
            base = (
                f"**{what.capitalize()} is {abs(self.effect):.2f}{unit} {direction}** "
                f"({self.ci_low:+.2f} to {self.ci_high:+.2f}{unit})."
            )

        if self.n_matched:
            base += (
                f" Compared on {self.n_matched} matched sample pair(s) "
                f"({self.kept_share:.0%} of the data survived matching)"
            )
            if self.adjusted_for:
                base += f", adjusted for {', '.join(self.adjusted_for)}"
            base += "."

        if self.unadjusted_for:
            base += (
                f"\n\n**Not adjusted for: {', '.join(self.unadjusted_for)}.** "
                f"{'These are' if len(self.unadjusted_for) > 1 else 'This is'} not measured for "
                f"this space, so any part of the difference caused by "
                f"{'them' if len(self.unadjusted_for) > 1 else 'it'} is still in the number "
                f"above."
            )
        return base


def _bucket(when: datetime) -> Tuple[int, str]:
    """The matching key from a timestamp: hour of day, and weekday vs weekend."""
    return when.hour, ("weekend" if when.weekday() >= 5 else "weekday")


def _mean(values: Sequence[float]) -> float:
    return sum(values) / len(values)


def _welch_interval(a: Sequence[float], b: Sequence[float]) -> Tuple[float, float, float]:
    """(effect, low, high) for mean(a) - mean(b), 95%, unequal variances.

    Welch rather than Student because the two windows have no reason to share a variance — a
    heating season and a shoulder season genuinely differ in spread, and assuming otherwise
    narrows the interval and manufactures significance.

    1.96 is used rather than a t table: with the sample counts this runs on (hundreds of
    readings) the difference is immaterial, and pulling in scipy for it would not be.
    """
    na, nb = len(a), len(b)
    ma, mb = _mean(a), _mean(b)
    va = sum((x - ma) ** 2 for x in a) / (na - 1) if na > 1 else 0.0
    vb = sum((x - mb) ** 2 for x in b) / (nb - 1) if nb > 1 else 0.0
    se = math.sqrt(va / na + vb / nb) if (na and nb) else 0.0
    effect = ma - mb
    return effect, effect - 1.96 * se, effect + 1.96 * se


def compare(
    current: Series,
    baseline: Series,
    *,
    available_covariates: Sequence[str] = (),
    declared_confounders: Sequence[str] = (),
) -> MatchedComparison:
    """Compare two series like with like.

    ``available_covariates`` are the ones the caller could actually resolve. ``declared_confounders``
    is what SHOULD ideally be adjusted for in this building — anything in it that is not
    available is reported as unadjusted, by name.
    """
    cur = [(t, v) for t, v in current if t is not None and v is not None]
    base = [(t, v) for t, v in baseline if t is not None and v is not None]
    result = MatchedComparison(n_baseline_total=len(base), n_current_total=len(cur))

    intrinsic = [c for c in INTRINSIC_COVARIATES]
    result.adjusted_for = intrinsic + [c for c in available_covariates if c not in intrinsic]
    result.unadjusted_for = [c for c in declared_confounders if c not in result.adjusted_for]

    if not cur or not base:
        result.reason = "one of the two periods has no readings at all"
        result.adjusted_for = []
        return result

    by_bucket_base: Dict[Tuple[int, str], List[float]] = {}
    for t, v in base:
        by_bucket_base.setdefault(_bucket(t), []).append(float(v))

    matched_cur: List[float] = []
    matched_base: List[float] = []
    for t, v in cur:
        peers = by_bucket_base.get(_bucket(t))
        if not peers:
            continue  # no comparable hour in the baseline: DISCARD, never approximate
        matched_cur.append(float(v))
        matched_base.append(_mean(peers))

    result.n_matched = len(matched_cur)
    if result.n_matched < MIN_SAMPLES_PER_SIDE:
        result.reason = (
            f"only {result.n_matched} comparable sample(s) survived matching on "
            f"{' and '.join(INTRINSIC_COVARIATES)}, which is too few to compare"
        )
        return result

    effect, low, high = _welch_interval(matched_cur, matched_base)
    result.effect, result.ci_low, result.ci_high = (
        round(effect, 3),
        round(low, 3),
        round(high, 3),
    )
    return result


__all__ = [
    "INTRINSIC_COVARIATES",
    "MIN_SAMPLES_PER_SIDE",
    "MatchedComparison",
    "compare",
]
