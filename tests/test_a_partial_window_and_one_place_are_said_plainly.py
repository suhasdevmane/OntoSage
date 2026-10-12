"""BUG-1491: a figure over a window its readings only partly cover says so; one place is not ranked.

Measured on the Paper 3 development forms (2026-10-10): "the average temperature in room 5.23 in
March 2025" came back "HVAC Zone 5.23 had the highest average temperature in the period: 33.2",
no unit, over 1-31 March, when the stored readings stop on 9 March. The figure was the right mean
of nine days; the sentence claimed a month and a comparison.
"""

from datetime import datetime

import pytest

from orchestrator.services.aggregate_lane import (
    AggregateIntent,
    GroupStat,
    SensorAgg,
    Window,
    coverage_note,
    render_extreme,
)

pytestmark = pytest.mark.unit

MARCH = Window(
    start="2025-03-01 00:00:00", end="2025-03-31 23:59:59", label="Sat 01 Mar to Mon 31 Mar"
)


def _agg(first, last, n=100):
    return SensorAgg(
        uuid="u1", n=n, first=first, last=last, total=33.0 * n, minimum=31.0, maximum=35.0
    )


def test_readings_that_stop_early_are_stated_with_their_span():
    note = coverage_note(
        [_agg(datetime(2025, 3, 1, 0, 0, 15), datetime(2025, 3, 9, 23, 59, 55))], MARCH, None
    )
    assert "run only from" in note and "09 Mar" in note and "not the whole period" in note
    assert "29%" in note or "30%" in note


def test_a_window_the_readings_cover_needs_no_note():
    day = Window(start="2025-01-31 10:00:00", end="2025-01-31 15:59:59", label="x")
    assert (
        coverage_note(
            [_agg(datetime(2025, 1, 31, 10, 0, 5), datetime(2025, 1, 31, 15, 59, 55))], day, None
        )
        == ""
    )


def test_no_readings_means_no_claim_about_coverage():
    assert coverage_note([SensorAgg(uuid="u1", n=0)], MARCH, None) == ""


def test_one_place_is_reported_not_ranked():
    text = render_extreme(
        AggregateIntent("mean", "room"),
        [GroupStat(key="HVAC Zone 5.23", sensors=1, readings=100, value=33.18)],
        measurand="temperature",
        unit="°C",
        window=MARCH,
        sensors_used=1,
        sensors_requested=1,
        floors_seen=1,
        peak_at=None,
        excluded=0,
        excluded_sensors=0,
        no_reading=0,
        unplaced=0,
        bands_checked=True,
    )
    first = text.splitlines()[0]
    assert "highest" not in first and "average" in first and "33.2 °C" in first


def test_two_places_are_still_ranked():
    text = render_extreme(
        AggregateIntent("mean", "room"),
        [
            GroupStat(key="Room 5.05", sensors=1, value=30.1),
            GroupStat(key="Room 5.31", sensors=1, value=28.3),
        ],
        measurand="temperature",
        unit="°C",
        window=MARCH,
        sensors_used=2,
        sensors_requested=2,
        floors_seen=1,
        peak_at=None,
        excluded=0,
        excluded_sensors=0,
        no_reading=0,
        unplaced=0,
        bands_checked=True,
    )
    assert "highest average" in text.splitlines()[0]
