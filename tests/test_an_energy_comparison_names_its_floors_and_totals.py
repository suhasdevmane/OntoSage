"""An interval-energy comparison names each floor and compares totals, not per-reading means.

2026-10-11 battery (energy, turn 2): the week-on-week answer listed "**0 mean**: 3.8 kWh in both
periods" and "**1 figure**: 2,409 kWh ..." -- bare floor numbers, and the mean of 15-minute
readings beside each floor's total. Figures here are synthetic.
"""

import pytest

from orchestrator.services.comparison_lane import _additive_view, _named

pytestmark = pytest.mark.unit

FIGS = {
    "total": 15148.0,
    "0 mean": 3.8,
    "0 figure": 2434.0,
    "0 peak": 6.3,
    "1 mean": 3.8,
    "1 figure": 2409.0,
    "1 lowest": 1.5,
}


def test_bare_floor_keys_of_a_building_total_are_named():
    named = _named(FIGS, "building")
    assert "Floor 0 figure" in named and "0 figure" not in named


def test_an_additive_unit_keeps_totals_and_drops_reading_means():
    view = _additive_view(_named(FIGS, "building"), "kWh")
    assert view == {"total": 15148.0, "Floor 0 total": 2434.0, "Floor 1 total": 2409.0}


def test_a_level_unit_is_left_alone():
    figs = {"0 mean": 21.5, "0 figure": 21.5}
    assert _additive_view(_named(figs, "floor"), "°C") == {
        "Floor 0 mean": 21.5,
        "Floor 0 figure": 21.5,
    }
