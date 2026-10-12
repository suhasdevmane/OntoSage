"""BUG-1506: the generated people counts, floor counters and presence flags agree with each other.

Measured 2026-10-10: every room's count was an independent 0-30 walk peaking near 30, so the
deliberation lane summed Floor 4 to 947 people while the floor's own counter read about 23, and a
presence flag could say a room was empty while its count said 12. The publisher now derives a
floor counter as the SUM of its spaces' counts and a presence flag as "count >= 1"; and occupancy
is low at weekends. No database is touched.
"""

from __future__ import annotations

import sys
from datetime import datetime, timedelta
from pathlib import Path

import pytest

pytestmark = pytest.mark.unit

_PUB_DIR = Path(__file__).resolve().parents[1] / "mysql-dummy-publish-dev"
pytest.importorskip("pymysql", reason="the publisher imports pymysql at module scope")
if str(_PUB_DIR) not in sys.path:
    sys.path.insert(0, str(_PUB_DIR))

import mysql_dummy_publisher as pub  # noqa: E402
import sensor_signal  # noqa: E402

TUE_1PM = datetime(2026, 10, 6, 13, 0)


@pytest.fixture()
def floor(monkeypatch):
    sensor_signal.reset_state()
    pub._NARROW_LAST.clear()
    rooms = [
        {
            "uuid": f"r{i}",
            "table": "occupancy_data",
            "value_col": "occupancy",
            "lo": 0,
            "hi": 10,
            "dec": 0,
            "derive": None,
        }
        for i in range(4)
    ]
    counter = {
        "uuid": "f1",
        "table": "occupancy_data",
        "value_col": "occupancy",
        "lo": 0,
        "hi": 40,
        "dec": 0,
        "derive": {"op": "sum", "of": ["r0", "r1", "r2", "r3"]},
    }
    flag = {
        "uuid": "p0",
        "table": "occupancy_data",
        "value_col": "occupancy",
        "lo": 0,
        "hi": 1,
        "dec": 0,
        "derive": {"op": "present", "of": ["r0"]},
    }
    monkeypatch.setattr(pub, "NARROW_SENSORS", rooms + [counter, flag])
    yield
    sensor_signal.reset_state()
    pub._NARROW_LAST.clear()


def _tick(at):
    sink = {}
    pub.publish_narrow(None, at=at, sink=sink)
    return {u: v for u, _t, v in sink.get("occupancy_data", [])}


def test_a_floor_counter_is_the_sum_of_its_rooms_on_every_tick(floor):
    t = TUE_1PM
    for _ in range(30):
        vals = _tick(t)
        assert vals["f1"] == sum(vals[f"r{i}"] for i in range(4))
        t += timedelta(minutes=1)


def test_a_presence_flag_follows_its_rooms_count(floor):
    t = TUE_1PM
    for _ in range(30):
        vals = _tick(t)
        assert vals["p0"] == (1 if vals["r0"] >= 1 else 0)
        t += timedelta(minutes=1)


def test_a_derived_point_is_never_invented_without_members(monkeypatch):
    pub._NARROW_LAST.clear()
    sensor_signal.reset_state()
    monkeypatch.setattr(
        pub,
        "NARROW_SENSORS",
        [
            {
                "uuid": "f9",
                "table": "occupancy_data",
                "value_col": "occupancy",
                "lo": 0,
                "hi": 9,
                "dec": 0,
                "derive": {"op": "sum", "of": ["missing"]},
            }
        ],
    )
    assert _tick(TUE_1PM) == {}


def test_a_weekend_afternoon_is_quieter_than_a_weekday_one():
    sat = datetime(2026, 10, 10, 13, 0)
    wk = sensor_signal.centre("occupancy", 0, 10, TUE_1PM, 0.0)
    we = sensor_signal.centre("occupancy", 0, 10, sat, 0.0)
    assert we < 0.25 * wk
    # other modalities keep their weekday shape
    assert sensor_signal.centre("temp_c", 18, 26, sat, 0.0) == sensor_signal.centre(
        "temp_c", 18, 26, TUE_1PM, 0.0
    )
