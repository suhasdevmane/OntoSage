# -*- coding: utf-8 -*-
"""Comparing two periods like with like, and naming what could not be matched (V6-T41).

"Is the office warmer than last month?" invites the least honest arithmetic available: two
means, subtracted. That answer is confidently wrong whenever the windows differ in anything that
also drives the measurement — a bank holiday, a heatwave, half-term — and it compares an
occupied building against an empty one while calling the difference a trend.

The three properties asserted here, in order of how easily they are lost:

1. **An unadjustable confounder is NAMED.** Silently omitting an adjustment yields a number
   indistinguishable from a properly adjusted one. This is the statistical form of the failure
   this workstream keeps finding.
2. **Uncertainty travels with the effect.** A difference whose interval spans zero is not a
   difference, and the point estimate alone makes it look like one.
3. **Unmatched samples are discarded, and the loss is reported.** A comparison that kept 8% of
   its data is a different claim from one that kept 90%.
"""

from datetime import datetime, timedelta

import pytest

from orchestrator.services.evidence.matched_comparison import (
    INTRINSIC_COVARIATES,
    MIN_SAMPLES_PER_SIDE,
    MatchedComparison,
    compare,
)

pytestmark = pytest.mark.unit

MONDAY = datetime(2026, 8, 3, 0, 0)  # a Monday, so weekday/weekend buckets are predictable


def _series(start, hours, value_fn):
    return [(start + timedelta(hours=i), float(value_fn(i))) for i in range(hours)]


# ── naming what could not be adjusted ────────────────────────────────────────


class TestUnadjustableConfoundersAreNamed:
    def test_a_declared_confounder_that_is_unavailable_is_reported(self):
        got = compare(
            _series(MONDAY, 48, lambda i: 22.0),
            _series(MONDAY - timedelta(days=7), 48, lambda i: 21.0),
            available_covariates=[],
            declared_confounders=["weather", "occupancy"],
        )
        assert set(got.unadjusted_for) == {"weather", "occupancy"}
        assert "Not adjusted for" in got.describe("temperature", "°C")
        assert "weather" in got.describe("temperature", "°C")

    def test_an_available_covariate_is_not_listed_as_unadjusted(self):
        got = compare(
            _series(MONDAY, 48, lambda i: 22.0),
            _series(MONDAY - timedelta(days=7), 48, lambda i: 21.0),
            available_covariates=["occupancy"],
            declared_confounders=["weather", "occupancy"],
        )
        assert got.unadjusted_for == ["weather"]
        assert "occupancy" in got.adjusted_for

    def test_the_intrinsic_covariates_are_always_adjusted_for(self):
        """Hour-of-day and weekday/weekend come from the timestamp alone, so there is never an
        excuse not to match on them."""
        got = compare(
            _series(MONDAY, 48, lambda i: 22.0),
            _series(MONDAY - timedelta(days=7), 48, lambda i: 21.0),
        )
        for c in INTRINSIC_COVARIATES:
            assert c in got.adjusted_for

    def test_no_declared_confounders_means_no_caveat_paragraph(self):
        """A caveat on every comparison is furniture."""
        got = compare(
            _series(MONDAY, 48, lambda i: 22.0),
            _series(MONDAY - timedelta(days=7), 48, lambda i: 21.0),
        )
        assert "Not adjusted for" not in got.describe("temperature")


# ── uncertainty travels with the effect ──────────────────────────────────────


class TestUncertainty:
    def test_a_real_shift_is_reported_with_an_interval_excluding_zero(self):
        got = compare(
            _series(MONDAY, 72, lambda i: 25.0),
            _series(MONDAY - timedelta(days=7), 72, lambda i: 21.0),
        )
        assert got.effect == pytest.approx(4.0, abs=0.01)
        assert got.significant
        assert got.ci_low > 0

    def test_noise_around_zero_is_reported_as_no_detectable_difference(self):
        """The property that stops a 0.4-degree wobble becoming a headline."""
        got = compare(
            _series(MONDAY, 72, lambda i: 22.0 + (1.0 if i % 2 else -1.0)),
            _series(MONDAY - timedelta(days=7), 72, lambda i: 22.0 + (1.0 if i % 2 else -1.0)),
        )
        assert not got.significant
        text = got.describe("temperature", "°C")
        assert "No detectable difference" in text
        assert "includes zero" in text

    def test_the_point_estimate_is_never_printed_without_its_interval(self):
        got = compare(
            _series(MONDAY, 72, lambda i: 25.0),
            _series(MONDAY - timedelta(days=7), 72, lambda i: 21.0),
        )
        text = got.describe("temperature", "°C")
        assert "4.00" in text
        assert "to" in text and ("+" in text or "-" in text), "no interval accompanies the effect"

    def test_unequal_variance_is_assumed(self):
        """Welch, not Student. Two windows have no reason to share a variance, and assuming
        they do narrows the interval and manufactures significance."""
        from pathlib import Path

        src = Path("orchestrator/services/evidence/matched_comparison.py").read_text(
            encoding="utf-8"
        )
        assert "va / na + vb / nb" in src, "the interval assumes a pooled variance"


# ── matching, and reporting what it cost ─────────────────────────────────────


class TestMatching:
    def test_samples_with_no_comparable_hour_are_discarded(self):
        """Approximating a missing hour would compare 3am against 3pm and call it a trend."""
        current = _series(MONDAY, 24, lambda i: 22.0)
        baseline = [(MONDAY - timedelta(days=7) + timedelta(hours=i), 21.0) for i in range(12)]
        got = compare(current, baseline)
        assert got.n_matched == 12, f"matched {got.n_matched}; unmatched hours were not dropped"

    def test_the_share_that_survived_matching_is_reported(self):
        current = _series(MONDAY, 24, lambda i: 22.0)
        baseline = [(MONDAY - timedelta(days=7) + timedelta(hours=i), 21.0) for i in range(12)]
        got = compare(current, baseline)
        assert 0.4 < got.kept_share < 0.6
        assert "survived matching" in got.describe("temperature")

    def test_weekday_and_weekend_are_not_pooled(self):
        """A Tuesday afternoon compared against a Sunday afternoon is not a comparison."""
        saturday = datetime(2026, 8, 8, 0, 0)
        got = compare(_series(saturday, 24, lambda i: 22.0), _series(MONDAY, 24, lambda i: 21.0))
        assert got.effect is None
        assert "too few" in got.reason

    def test_too_few_matched_samples_declines_rather_than_reporting(self):
        got = compare(
            _series(MONDAY, 3, lambda i: 22.0),
            _series(MONDAY - timedelta(days=7), 3, lambda i: 21.0),
        )
        assert got.effect is None
        assert str(MIN_SAMPLES_PER_SIDE) not in got.reason or "too few" in got.reason
        assert "can't compare" in got.describe("temperature")

    def test_an_empty_period_declines_and_says_which_problem_it_hit(self):
        got = compare([], _series(MONDAY, 48, lambda i: 21.0))
        assert got.effect is None
        assert "no readings" in got.reason


# ── the sentence a comparison must carry ─────────────────────────────────────


def test_a_declined_comparison_still_explains_itself():
    text = MatchedComparison(reason="one of the two periods has no readings at all").describe(
        "temperature"
    )
    assert "can't compare" in text and "no readings" in text


def test_direction_is_stated_in_words_not_only_in_a_sign():
    got = compare(
        _series(MONDAY, 72, lambda i: 19.0),
        _series(MONDAY - timedelta(days=7), 72, lambda i: 23.0),
    )
    assert "lower" in got.describe("temperature", "°C")


# ── reachability ─────────────────────────────────────────────────────────────


class TestWiring:
    """A comparison module nothing calls is a comparison nobody gets. The diagnosis lane's
    week-on-week line was two means subtracted — reporting a 0.3-degree wobble in exactly the
    same words as a real shift — which is the naive arithmetic this module exists to replace."""

    def test_the_diagnosis_lane_uses_the_matched_comparison(self):
        from pathlib import Path

        src = Path("orchestrator/services/anomaly/diagnosis.py").read_text(encoding="utf-8")
        # Matched on the MODULE PATH, not on a formatted import line: black rewrapped the
        # import across lines and broke a substring assertion that was testing layout
        # rather than behaviour.
        assert "evidence.matched_comparison import" in src
        assert "week-on-week, matched" in src

    def test_the_confounders_this_estate_cannot_adjust_for_are_declared(self):
        """Weather and occupancy both move indoor conditions and neither is connected here.
        Declaring them is what turns "not adjusted" into a statement instead of an omission."""
        from pathlib import Path

        src = Path("orchestrator/services/anomaly/diagnosis.py").read_text(encoding="utf-8")
        assert "outdoor weather" in src and "declared_confounders" in src

    def test_the_matched_figures_reach_the_payload(self):
        """The narration prints an interval; the numeric guard checks every number against the
        payload, and an unbacked one suppresses the whole answer (V6-T26)."""
        from pathlib import Path

        src = Path("orchestrator/services/anomaly/diagnosis.py").read_text(encoding="utf-8")
        assert '"matched_comparison"' in src

    def test_a_failed_comparison_never_costs_the_answer(self):
        from pathlib import Path

        src = Path("orchestrator/services/anomaly/diagnosis.py").read_text(encoding="utf-8")
        block = src[src.index("evidence.matched_comparison import") :][:2200]
        assert "except Exception" in block


def test_the_raw_week_earlier_line_does_not_assert_a_direction():
    """It used to read "(higher now)" immediately above a matched comparison saying the
    difference was indistinguishable from noise. Two lines contradicting each other, the
    confident one first — and a reader takes the headline. The adjudication belongs to the
    matched line, which carries the interval."""
    from pathlib import Path

    src = Path("orchestrator/services/anomaly/diagnosis.py").read_text(encoding="utf-8")
    assert 'direction_word = "lower" if window_mean < prior_mean' not in src
    assert 'same window a week earlier: {prior_mean:.1f}"' in src
