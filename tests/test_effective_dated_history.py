# -*- coding: utf-8 -*-
"""Effective-dated configuration history (V6-T07, acceptance scenario 3).

*"Move a sensor in metadata -> historical observations remain linked to the correct prior
location."*

The failure prevented here is unusually convincing: relocating or recalibrating a sensor puts
a **step change** in its series, and a step change is precisely what a real building event
looks like. Reported as a trend, the answer is confident, specific, and about nothing that
happened.

The second rule matters as much as the first: a window crossing a change is **flagged, not
refused**. Refusing every trend that spans a recalibration would discard most long-horizon
questions on a well-maintained building -- exactly the ones the PhD and Research Staff
catalogues care about.
"""

from datetime import datetime, timedelta

import pytest

from orchestrator.services.evidence.history import (
    MIN_SEGMENT_HOURS,
    ConfigurationPeriod,
    attribute_readings,
    check_window,
    location_as_of,
)

pytestmark = pytest.mark.unit

JAN = datetime(2026, 1, 1)
MAR = datetime(2026, 3, 1)
JUN = datetime(2026, 6, 1)
ROOM_A = "http://x/Room2.15"
ROOM_B = "http://x/Room3.20"

MOVED = [
    ConfigurationPeriod(JAN, MAR, ROOM_A, "commissioning"),
    ConfigurationPeriod(MAR, None, ROOM_B, "relocation"),
]


# ── as-of resolution ─────────────────────────────────────────────────────────


def test_a_reading_resolves_to_the_room_the_sensor_was_in_then():
    """The literal acceptance scenario."""
    assert location_as_of(MOVED, datetime(2026, 2, 1)) == ROOM_A
    assert location_as_of(MOVED, datetime(2026, 4, 1)) == ROOM_B


def test_an_open_interval_still_applies_today():
    """Absent effectiveTo means in force - not expired."""
    assert location_as_of(MOVED, datetime(2027, 1, 1)) == ROOM_B


def test_before_any_declared_period_is_unknown_not_current():
    """A reading predating the record cannot borrow today's location."""
    assert location_as_of(MOVED, datetime(2025, 6, 1)) is None


def test_no_periods_at_all_is_unknown():
    assert location_as_of([], MAR) is None


def test_readings_are_tagged_with_their_own_era():
    readings = [(datetime(2026, 2, 1), 21.0), (datetime(2026, 4, 1), 23.0)]
    out = attribute_readings(readings, MOVED)
    assert [loc for _, _, loc in out] == [ROOM_A, ROOM_B]


# ── window integrity ─────────────────────────────────────────────────────────


def test_a_window_inside_one_period_is_continuous():
    w = check_window(MOVED, datetime(2026, 1, 10), datetime(2026, 2, 10))
    assert w.is_continuous
    assert w.caveat() == ""


def test_a_window_spanning_a_relocation_is_flagged():
    w = check_window(MOVED, datetime(2026, 2, 1), datetime(2026, 4, 1))
    assert not w.is_continuous
    assert "relocation" in w.caveat()
    assert "indistinguishable from a real change" in w.caveat()


def test_a_flagged_window_is_not_refused():
    """Refusing every trend across a recalibration discards the long-horizon questions."""
    w = check_window(MOVED, datetime(2026, 2, 1), datetime(2026, 4, 1))
    assert w.segments, "the window must still be usable, split around the change"


def test_a_period_starting_exactly_at_the_window_start_is_not_a_boundary():
    """That is the window's own configuration, not a discontinuity inside it."""
    w = check_window(MOVED, MAR, JUN)
    assert w.is_continuous


def test_segments_split_around_each_change():
    w = check_window(MOVED, datetime(2026, 2, 1), datetime(2026, 4, 1))
    assert len(w.segments) == 2
    assert w.segments[0][2] == ROOM_A
    assert w.segments[1][2] == ROOM_B


def test_short_segments_are_not_offered_as_comparable():
    """A fragment either side of a change cannot characterise a trend."""
    w = check_window(MOVED, MAR - timedelta(hours=6), MAR + timedelta(hours=6))
    assert not w.is_continuous
    assert w.comparable_segments == []
    assert "no segment either side is long enough" in w.caveat()


def test_long_segments_are_offered_as_comparable():
    w = check_window(MOVED, MAR - timedelta(days=30), MAR + timedelta(days=30))
    assert len(w.comparable_segments) == 2
    assert "segments either side" in w.caveat()


def test_multiple_changes_are_all_named():
    periods = [
        ConfigurationPeriod(JAN, MAR, ROOM_A, "commissioning"),
        ConfigurationPeriod(MAR, JUN, ROOM_A, "recalibration"),
        ConfigurationPeriod(JUN, None, ROOM_B, "relocation"),
    ]
    w = check_window(periods, datetime(2026, 2, 1), datetime(2026, 7, 1))
    assert len(w.boundaries) == 2
    caveat = w.caveat()
    assert "recalibration" in caveat and "relocation" in caveat


def test_an_inverted_window_yields_nothing():
    assert check_window(MOVED, JUN, JAN).segments == []


def test_min_segment_threshold_is_declared_not_magic():
    """It is a judgement about daily cycles, so it should be visible and adjustable."""
    assert MIN_SEGMENT_HOURS >= 24
