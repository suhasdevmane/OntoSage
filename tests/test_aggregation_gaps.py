# -*- coding: utf-8 -*-
"""Missing-interval-aware aggregation (V6-T19).

Acceptance test 2: *"hours above 1000 ppm" computed over a series with a six-hour hole
understates the answer and looks authoritative doing it.*

The tests are organised around the three ways this can be got wrong, and the third is the one
that matters most:

1. **Under-statement** -- unobserved time counted as time below the threshold. The stated bug.
2. **Over-statement** -- the naive repair. Weighting each sample by the interval until the next
   hands a six-hour hole to the last reading before it, which turns an understatement into a
   fabrication. Guarded by the weight cap and asserted in its own section below.
3. **Confident output on thin evidence** -- returning a figure with a caveat beside it. A
   number printed next to a warning is read as a number; the warning is skimmed. So a
   low-completeness window returns no value at all.

Synthetic series throughout: this is arithmetic over time, and a test that only held for one
building's sampling regime would prove nothing about the arithmetic.
"""

from datetime import datetime, timedelta

import pytest

from orchestrator.services.evidence.aggregation import (
    DEFAULT_MIN_COMPLETENESS,
    GAP_TOLERANCE,
    describe_basis,
    exceedance_duration,
    time_weighted_mean,
)

pytestmark = pytest.mark.unit

START = datetime(2026, 8, 21, 0, 0)
END = START + timedelta(hours=12)
CADENCE = 60  # one sample a minute, declared


def series(minutes=720, high_until=360, high=1200.0, low=800.0):
    """A 12-hour minute-resolution series: `high_until` minutes high, then low."""
    return [(START + timedelta(minutes=i), high if i < high_until else low) for i in range(minutes)]


def punch(samples, from_hour, to_hour):
    """Remove a stretch, leaving a hole exactly where the caller wants one."""
    lo, hi = START + timedelta(hours=from_hour), START + timedelta(hours=to_hour)
    return [(t, v) for t, v in samples if not (lo <= t < hi)]


# -- the complete case must still be right -----------------------------------


def test_a_complete_series_reports_the_true_duration():
    """If this drifts, nothing else here is meaningful."""
    r = exceedance_duration(series(), 1000.0, START, END, CADENCE)
    assert r["value"] == pytest.approx(360.0, abs=1.0)
    assert r["completeness"] == pytest.approx(1.0, abs=0.01)
    assert r["unobserved_minutes"] == pytest.approx(0.0, abs=1.0)


def test_a_complete_series_reports_the_true_mean():
    r = time_weighted_mean(series(), START, END, CADENCE, unit="ppm")
    assert r["value"] == pytest.approx(1000.0, abs=1.0)
    assert r["unit"] == "ppm"


# -- 1. unobserved time is never counted as time below the threshold ---------


def test_unobserved_time_is_reported_separately_from_time_below():
    """The acceptance test.

    Six hours of the exceedance are missing. The answer must not imply the level was below the
    threshold then -- it must say those minutes were not observed at all.
    """
    holed = punch(series(), 1, 7)
    r = exceedance_duration(holed, 1000.0, START, END, CADENCE, min_completeness=0.4)
    assert r["unobserved_minutes"] > 300
    assert r["value"] < 120  # only the observed exceedance is claimed


def test_the_observed_and_unobserved_figures_do_not_overlap():
    holed = punch(series(), 1, 7)
    r = exceedance_duration(holed, 1000.0, START, END, CADENCE, min_completeness=0.4)
    window = (END - START).total_seconds() / 60.0
    assert r["covered_minutes"] + r["unobserved_minutes"] == pytest.approx(window, abs=2.0)


def test_the_gap_is_named_with_its_span():
    """ "Some data is missing" is not actionable; a named window is."""
    holed = punch(series(), 1, 7)
    r = exceedance_duration(holed, 1000.0, START, END, CADENCE, min_completeness=0.4)
    assert len(r["gaps"]) == 1
    assert "min)" in r["gaps"][0]


def test_time_below_a_threshold_is_the_same_arithmetic_inverted():
    """Asked the other way round ("how long below 18C"), the same guarantees must hold."""
    r = exceedance_duration(series(), 1000.0, START, END, CADENCE, above=False)
    assert r["direction"] == "below"
    assert r["value"] == pytest.approx(360.0, abs=1.0)


# -- 2. the naive repair must not be what we shipped -------------------------


def test_one_reading_does_not_speak_for_a_six_hour_hole():
    """The over-statement guard.

    Two samples twelve hours apart cover two capped intervals, not twelve hours. Naive
    time-weighting would report full coverage of a window it barely observed.
    """
    sparse = [(START, 1200.0), (START + timedelta(hours=6), 800.0)]
    r = time_weighted_mean(sparse, START, END, CADENCE, min_completeness=0.0)
    assert r["covered_minutes"] < 10
    assert r["window_minutes"] == pytest.approx(720.0, abs=1.0)


def test_a_sample_speaks_for_at_most_the_cadence_tolerance():
    cap_minutes = CADENCE * GAP_TOLERANCE / 60.0
    sparse = [(START, 1200.0), (START + timedelta(hours=6), 1200.0)]
    r = exceedance_duration(sparse, 1000.0, START, END, CADENCE, min_completeness=0.0)
    assert r["value"] <= 2 * cap_minutes + 0.1


def test_the_cap_and_the_gap_tolerance_are_one_constant():
    """Not "they happen to be equal" -- they are the SAME object.

    Two independent copies of this number would drift, and the symptom would be a mean that
    counted an interval as covered while the completeness report attached to the very same
    answer reported it as a gap. Importing it makes that state unrepresentable.
    """
    from orchestrator.services.evidence import aggregation, completeness

    assert aggregation.GAP_TOLERANCE is completeness.GAP_TOLERANCE


def test_find_gaps_defaults_to_that_same_constant():
    import inspect

    from orchestrator.services.evidence import completeness

    default = inspect.signature(completeness.find_gaps).parameters["tolerance"].default
    assert default is completeness.GAP_TOLERANCE


def test_a_dense_burst_does_not_dominate_the_mean():
    """The reason a plain arithmetic mean is wrong.

    Ten minutes reported every second, then eleven hours at one a minute: an arithmetic mean is
    dominated by the burst. Time-weighting is not.
    """
    burst = [(START + timedelta(seconds=s), 2000.0) for s in range(0, 600, 1)]
    rest = [(START + timedelta(minutes=10 + i), 1000.0) for i in range(700)]
    r = time_weighted_mean(burst + rest, START, END, CADENCE, min_completeness=0.0)
    arithmetic = (2000.0 * len(burst) + 1000.0 * len(rest)) / (len(burst) + len(rest))
    assert r["value"] < arithmetic


# -- 3. thin evidence yields no number ---------------------------------------


def test_a_half_empty_window_returns_no_figure_at_all():
    """Not a figure with a caveat. The caveat is what gets skimmed."""
    holed = punch(series(), 1, 7)
    r = exceedance_duration(holed, 1000.0, START, END, CADENCE)
    assert "value" not in r
    assert r["error"]


def test_the_refusal_states_the_shortfall_and_the_floor():
    holed = punch(series(), 1, 7)
    r = exceedance_duration(holed, 1000.0, START, END, CADENCE)
    assert "50%" in r["error"]
    assert "90%" in r["error"]


def test_the_floor_is_overridable_because_it_is_a_building_figure():
    """A building sampling on change is permanently 'incomplete' against a fixed count."""
    holed = punch(series(), 1, 7)
    assert "error" in exceedance_duration(holed, 1000.0, START, END, CADENCE)
    assert "value" in exceedance_duration(holed, 1000.0, START, END, CADENCE, min_completeness=0.4)


def test_the_default_floor_is_the_policy_default():
    assert DEFAULT_MIN_COMPLETENESS == pytest.approx(0.9)


def test_no_observations_is_distinguished_from_zero():
    """ "It was never above 1000" and "nobody looked" are different answers."""
    r = exceedance_duration([], 1000.0, START, END, CADENCE)
    assert "value" not in r
    assert "not the same as zero" in r["error"]


def test_an_undeclared_cadence_refuses_rather_than_guessing():
    """Inferring cadence from a holed series infers it from the hole."""
    r = exceedance_duration(series(), 1000.0, START, END, None)
    assert "value" not in r
    assert "cadence" in r["error"]
    m = time_weighted_mean(series(), START, END, None)
    assert "value" not in m


def test_samples_outside_the_window_are_ignored():
    outside = [(START - timedelta(hours=2), 5000.0)] + series()
    r = exceedance_duration(outside, 1000.0, START, END, CADENCE)
    assert r["value"] == pytest.approx(360.0, abs=1.0)


# -- what a lane prints ------------------------------------------------------


def test_the_basis_sentence_states_coverage_and_unobserved_time():
    holed = punch(series(), 1, 7)
    r = exceedance_duration(holed, 1000.0, START, END, CADENCE, min_completeness=0.4)
    basis = describe_basis(r)
    assert "50%" in basis
    assert "not observed" in basis


def test_a_refusal_has_no_basis_sentence():
    """Appending a basis to a refusal reads as though a number had been produced."""
    holed = punch(series(), 1, 7)
    assert describe_basis(exceedance_duration(holed, 1000.0, START, END, CADENCE)) == ""


def test_every_result_states_its_method():
    """Rule R-2: the answer must be able to say HOW the number was produced."""
    for r in (
        exceedance_duration(series(), 1000.0, START, END, CADENCE),
        time_weighted_mean(series(), START, END, CADENCE),
        exceedance_duration([], 1000.0, START, END, CADENCE),
    ):
        assert r.get("method")


# -- building agnosticism ----------------------------------------------------


def test_the_module_carries_no_building_literal():
    from pathlib import Path

    from scripts.check_building_literals import _prose_lines

    path = (
        Path(__file__).resolve().parent.parent
        / "orchestrator"
        / "services"
        / "evidence"
        / "aggregation.py"
    )
    src = path.read_text(encoding="utf-8")
    prose = _prose_lines(src)
    code = "\n".join(l for n, l in enumerate(src.splitlines(), 1) if n not in prose).lower()
    for literal in ("abacws", "bldg1", "bldg2", "bldg3", "cardiff"):
        assert literal not in code
