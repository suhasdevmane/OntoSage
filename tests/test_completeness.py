# -*- coding: utf-8 -*-
"""Completeness accounting (V6-T17, acceptance scenario 2).

Master 14.1 scenario 2: introduce missing intervals and the duration/average calculations
must change appropriately. The failure this prevents is quiet: an average over 40% of a
window looks exactly like an average over all of it.

Two design choices are pinned here because each had a tempting alternative that fails
subtly:

* expected count comes from the DECLARED cadence, never inferred from the data -- a series
  with a six-hour hole has a median gap that already reflects the hole, so it would score
  itself complete;
* unknown coverage FAILS a floor rather than passing it. A stream whose cadence nobody
  declared has not thereby been fully observed.
"""

from datetime import datetime, timedelta

import pytest

from orchestrator.services.evidence.completeness import (
    assess,
    duration_above,
    expected_samples,
    find_gaps,
)

pytestmark = pytest.mark.unit

START = datetime(2026, 8, 1, 0, 0, 0)
END = START + timedelta(hours=24)
MINUTE = 60


def _series(n: int, step_min: int = 1, begin: datetime = START):
    return [begin + timedelta(minutes=i * step_min) for i in range(n)]


# ── expected counts ──────────────────────────────────────────────────────────


def test_expected_comes_from_declared_cadence():
    assert expected_samples(START, END, MINUTE) == 1440


def test_expected_is_none_without_a_declared_cadence():
    """Unknown, not assumed. The gate must refuse rather than guess."""
    assert expected_samples(START, END, None) is None
    assert expected_samples(START, END, 0) is None


# ── coverage ─────────────────────────────────────────────────────────────────


def test_full_window_is_full_coverage():
    r = assess(_series(1440), START, END, MINUTE)
    assert r.coverage == pytest.approx(1.0)
    assert r.passes(0.90)


def test_partial_window_reports_its_real_coverage():
    r = assess(_series(720), START, START + timedelta(hours=24), MINUTE)
    assert r.coverage == pytest.approx(0.5, abs=0.01)
    assert not r.passes(0.90)


def test_unknown_coverage_fails_the_floor():
    """The safe direction: unestablished completeness must not read as checked."""
    r = assess(_series(100), START, END, None)
    assert r.coverage is None
    assert r.is_known is False
    assert r.passes(0.90) is False


def test_coverage_is_capped_at_one():
    """A stream reporting faster than declared must not produce 150% coverage."""
    r = assess(_series(2880, step_min=1), START, END, 2 * MINUTE)
    assert r.coverage == pytest.approx(1.0)


# ── gaps ─────────────────────────────────────────────────────────────────────


def test_a_hole_is_detected_and_measured():
    ts = _series(120) + _series(120, begin=START + timedelta(hours=8))
    gaps = find_gaps(ts, START, START + timedelta(hours=10), MINUTE)
    assert gaps
    assert max(g.minutes for g in gaps) > 300


def test_ordinary_jitter_is_not_a_gap():
    """A 61-second interval on a 60-second stream is normal.

    Flagging it would make every window look broken, and a field that is always red gets
    ignored -- which costs more than not having it.
    """
    ts = [START + timedelta(seconds=i * 61) for i in range(200)]
    assert find_gaps(ts, ts[0], ts[-1], MINUTE) == []


def test_an_empty_window_is_one_whole_gap():
    gaps = find_gaps([], START, END, MINUTE)
    assert len(gaps) == 1
    assert gaps[0].minutes == pytest.approx(1440)


def test_gaps_at_the_edges_are_found():
    """A stream that started late or stopped early is incomplete at the edge."""
    ts = _series(60, begin=START + timedelta(hours=2))
    gaps = find_gaps(ts, START, START + timedelta(hours=5), MINUTE)
    assert len(gaps) == 2  # before the first sample and after the last


def test_no_gaps_without_a_cadence():
    """Nothing to measure against; report unknown rather than inventing gaps."""
    assert find_gaps(_series(10), START, END, None) == []


# ── narration ────────────────────────────────────────────────────────────────


def test_description_states_coverage_and_the_longest_gap():
    ts = _series(120) + _series(120, begin=START + timedelta(hours=8))
    text = assess(ts, START, START + timedelta(hours=10), MINUTE).describe()
    assert "%" in text and "gap" in text


def test_unknown_coverage_says_why():
    text = assess(_series(10), START, END, None).describe()
    assert "unknown" in text and "archival interval" in text


def test_reporting_happens_even_when_coverage_passes():
    """Master 10.1 wants missingness stated in EVERY analysis, not only failures."""
    text = assess(_series(1440), START, END, MINUTE).describe()
    assert "100%" in text


# ── exceedance duration (acceptance scenario 2) ──────────────────────────────


def test_duration_above_counts_only_observed_intervals():
    """Absent samples are absent TIME, not time below the threshold."""
    samples = [(START + timedelta(minutes=i), 1200.0) for i in range(60)]
    minutes, basis = duration_above(samples, 1000.0, MINUTE)
    assert minutes == pytest.approx(60.0)
    assert "unobserved intervals are excluded" in basis


def test_removing_intervals_changes_the_duration():
    """Acceptance scenario 2, stated as an assertion.

    If punching a hole in the series leaves the answer unchanged, the calculation is
    treating missing data as data.
    """
    full = [(START + timedelta(minutes=i), 1200.0) for i in range(120)]
    holed = full[:60] + full[90:]
    a, _ = duration_above(full, 1000.0, MINUTE)
    b, _ = duration_above(holed, 1000.0, MINUTE)
    assert b < a
    assert a - b == pytest.approx(30.0)


def test_duration_declines_without_a_cadence():
    samples = [(START, 1200.0)]
    minutes, basis = duration_above(samples, 1000.0, None)
    assert minutes is None
    assert "cannot be computed" in basis


def test_no_observations_is_not_zero_minutes():
    """'Never exceeded' and 'never observed' are different answers."""
    minutes, basis = duration_above([], 1000.0, MINUTE)
    assert minutes is None
    assert "no observations" in basis
