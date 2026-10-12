"""The main water meter's interval volume follows a working week (2026-10-11).

"How much water did the building use yesterday?" had no series to sum: the graph declared a
``brick:Building_Water_Meter`` with no readings. It now has litres per 15-minute interval, drawn
by the publisher's ``water_l`` shape, and the same shape writes its history.
"""

from __future__ import annotations

import sys
from datetime import datetime, timedelta
from pathlib import Path

import pytest

pytestmark = pytest.mark.unit

REPO = Path(__file__).resolve().parents[1]


def _signal():
    d = str(REPO / "mysql-dummy-publish-dev")
    if d not in sys.path:
        sys.path.insert(0, d)
    return pytest.importorskip("sensor_signal")


def _scripts():
    d = str(REPO / "scripts")
    if d not in sys.path:
        sys.path.insert(0, d)


def _day_litres(s, day: datetime, hi: float = 600.0) -> float:
    t, total = day, 0.0
    while t < day + timedelta(days=1):
        total += hi * s.water_fraction(t)
        t += timedelta(minutes=15)
    return total


def test_a_weekday_uses_several_times_a_weekend_day():
    s = _signal()
    wednesday = _day_litres(s, datetime(2026, 10, 7))
    sunday = _day_litres(s, datetime(2026, 10, 11))
    assert 10_000 < wednesday < 15_000
    assert 2_000 < sunday < 4_000
    assert wednesday > 3 * sunday


def test_midday_draws_more_than_the_small_hours():
    s = _signal()
    assert s.water_fraction(datetime(2026, 10, 7, 11, 0)) > 5 * s.water_fraction(
        datetime(2026, 10, 7, 2, 0)
    )


def test_a_reading_is_never_negative_nor_above_the_declared_maximum():
    s = _signal()
    s.reset_state()
    for hour in range(24):
        v, _ = s.next_value("water-test", "water_l", 0.0, 600.0, 1, datetime(2026, 10, 7, hour))
        assert 0.0 <= v <= 600.0


def test_the_map_gives_the_meter_its_shape_and_range_and_nothing_else():
    _scripts()
    from derive_generation_shapes import WATER_SHAPE, mark_water_shapes

    points = {"m": {"value_col": "value", "lo": 0, "hi": 5, "dec": 2}, "x": {"value_col": "kwh"}}
    assert mark_water_shapes(points, ["m", "absent"]) == 1
    assert points["m"] == {"value_col": WATER_SHAPE, "lo": 0.0, "hi": 600.0, "dec": 1}
    assert points["x"] == {"value_col": "kwh"}
    assert mark_water_shapes(points, ["m"]) == 0


def test_the_meter_series_id_is_stable_per_building():
    _scripts()
    pytest.importorskip("yaml")
    from provision_building_water_meter import meter_uuid, ttl_text

    a = meter_uuid("http://example.org/a#")
    assert a == meter_uuid("http://example.org/a#")
    assert a != meter_uuid("http://example.org/b#")
    ttl = ttl_text("http://example.org/a#", a)
    assert f'ref:hasTimeseriesId "{a}"' in ttl
    assert "ref:storedAt bldg:water_data" in ttl
    assert "unit/L>" in ttl
