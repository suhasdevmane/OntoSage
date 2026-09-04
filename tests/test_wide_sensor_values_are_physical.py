# -*- coding: utf-8 -*-
"""Every wide-table sensor must produce a value it could physically produce (CAVEAT-410).

`get_realistic_value` was an if-chain of nine name rules and returned None for anything it
did not name, falling through to `gen_value`'s TYPE fallback — where `tinyint` becomes
`rand_int(0, 1)`. Measured on bldg1: **450 of 1,218 wide sensor names (37%)** reached that
fallback, so twelve whole sensor classes across 34 rooms reported numbers with no physical
meaning.

The visible failure: "what is the PM2.5 level in Room 5.04" answered **1**. Grounded in a
real, live column — and nonsense as a reading. That is worse than declining, and it is the
failure contract 4 exists to prevent. PM2.5, CO, NO2 and formaldehyde are all named
directly by the stakeholder catalogues.

Two traps these tests exist to hold:

* **Substring order.** "pm10" contains "pm1", so a table checked in the wrong order types
  every PM10 sensor as PM1 and nothing complains.
* **Column type.** A range with decimals written into an integer column is truncated
  silently — 0.25 into a `tinyint` stores 0 — so a correct range still yields an
  implausible reading.
"""

import json
import re
import sys
from pathlib import Path

import pytest

pytestmark = pytest.mark.unit

_PUBLISHER_DIR = Path(__file__).resolve().parent.parent / "mysql-dummy-publish-dev"
sys.path.insert(0, str(_PUBLISHER_DIR))

pub = pytest.importorskip("mysql_dummy_publisher")
sensor_signal = pytest.importorskip("sensor_signal")

_ENUM = ["FreshAir", "high", "medium", "low"]


@pytest.fixture(autouse=True)
def _clean_state():
    sensor_signal.reset_state()
    yield
    sensor_signal.reset_state()


def _names():
    path = _PUBLISHER_DIR / "sensor_uuids.json"
    return list(json.loads(path.read_text(encoding="utf-8")).keys())


# ── the reported failure ───────────────────────────────────────────────────────────────


def test_every_declared_wide_sensor_gets_a_physical_range():
    """The measured defect: 450 of 1,218 names fell through to the type fallback."""
    unmatched = [n for n in _names() if pub.get_realistic_value(n, n, enum_opts=_ENUM) is None]
    assert not unmatched, (
        f"{len(unmatched)} sensor name(s) have no physical range and will be generated from "
        f"their COLUMN TYPE instead — a tinyint becomes 0 or 1. First few: {unmatched[:5]}"
    )


def test_a_pm25_reading_is_not_a_coin_flip():
    value = pub.get_realistic_value("PM2.5_Level_Sensor_Atmospheric_5.04", "u-pm25")
    assert 5 <= value <= 35, f"PM2.5 came back as {value}"


# ── substring ordering ─────────────────────────────────────────────────────────────────


def test_pm10_is_not_typed_as_pm1():
    """ "pm10" contains "pm1". Wrong order types every PM10 sensor as PM1, silently."""
    pm10 = pub.get_realistic_value("PM10_Level_Sensor_Atmospheric_5.01", "u-a")
    assert 10 <= pm10 <= 50, f"PM10 came back as {pm10}, which is the PM1 range"


def test_the_particulate_sizes_keep_their_physical_ordering():
    """PM1 <= PM2.5 <= PM10 by construction: the finer fraction is part of the coarser."""
    lows = {}
    for sub, _key, lo, hi, _dec in pub._WIDE_RANGES:
        if sub in ("pm1", "pm2.5", "pm10"):
            lows[sub] = (lo, hi)
    assert lows["pm1"][1] <= lows["pm2.5"][1] <= lows["pm10"][1], lows


def test_the_air_quality_level_enum_is_not_swallowed_by_the_index_rule():
    level = pub.get_realistic_value("Air_Quality_Level_Sensor_5.01", "u-b", enum_opts=_ENUM)
    assert level in _ENUM
    index = pub.get_realistic_value("Air_Quality_Sensor_5.01", "u-c")
    assert isinstance(index, (int, float)) and 0 <= index <= 150


# ── column type wins over the table's fallback decimals ────────────────────────────────


def test_an_integer_column_gets_an_integer():
    pub.SCHEMA_MAP["u-int"] = {"data_type": "tinyint", "scale": 0}
    value = pub.get_realistic_value("Formaldehyde_Level_Sensor_5.01", "u-int")
    assert value == int(value), f"{value} would be truncated by a tinyint column"


def test_a_decimal_column_keeps_its_declared_scale():
    pub.SCHEMA_MAP["u-dec"] = {"data_type": "decimal", "scale": 4}
    value = pub.get_realistic_value("Electrical_Price_Sensor_Exterior", "u-dec")
    assert 0.12 <= value <= 0.45
    assert len(str(value).split(".")[-1]) <= 4


def test_an_unknown_schema_still_produces_a_value():
    """SCHEMA_MAP comes from a per-building CSV; a missing entry must not return None."""
    pub.SCHEMA_MAP.pop("u-none", None)
    assert pub.get_realistic_value("CO_Level_Sensor_Atmospheric_5.01", "u-none") is not None


# ── plausibility of the specific classes the catalogues name ───────────────────────────


@pytest.mark.parametrize(
    "name, lo, hi",
    [
        ("CO_Level_Sensor_Atmospheric_5.01", 0, 5),
        ("NO2_Level_Sensor_Atmospheric_5.01", 5, 40),
        ("Formaldehyde_Level_Sensor_5.01", 5, 50),
        ("Oxygen_O2_Percentage_Gas_Sensor_5.01", 20.5, 21.0),
        ("Wind_Speed_Sensor_Exterior", 0, 12),
        ("PM1_Level_Sensor_Atmospheric_5.01", 2, 15),
    ],
)
def test_a_named_class_reads_inside_its_physical_band(name, lo, hi):
    for _ in range(20):
        value = pub.get_realistic_value(name, f"u-{name}")
        assert lo <= value <= hi, f"{name} produced {value}, outside [{lo}, {hi}]"


def test_oxygen_does_not_wander_into_an_emergency():
    """Ambient is 20.95%. A room at 15% is not a reading, it is an evacuation."""
    values = [
        pub.get_realistic_value("Oxygen_O2_Percentage_Gas_Sensor_5.01", "u-o2") for _ in range(50)
    ]
    assert min(values) > 20.0, f"oxygen fell to {min(values)}%"


# ── shaping reaches the wide table too ─────────────────────────────────────────────────


def test_wide_values_persist_rather_than_jumping(monkeypatch):
    """The wide table had the same white-noise problem as the narrow ones (CAVEAT-405)."""
    pub.SCHEMA_MAP.pop("u-walk", None)
    series = [pub.get_realistic_value("CO2_Sensor_5.01", "u-walk") for _ in range(60)]
    span = 1200.0 - 400.0
    jumps = [abs(series[i] - series[i - 1]) for i in range(1, len(series))]
    assert max(jumps) < span * 0.15, f"largest step {max(jumps):.1f} of a {span} range"


def test_two_sensors_of_the_same_class_differ():
    a = [pub.get_realistic_value("PM2.5_Level_Sensor_Atmospheric_5.01", "u-1") for _ in range(30)]
    b = [pub.get_realistic_value("PM2.5_Level_Sensor_Atmospheric_5.02", "u-2") for _ in range(30)]
    assert a != b, "every room would report an identical particulate level"


def test_the_range_table_is_ordered_specific_before_general():
    """A regression guard on the table itself, not on one sampled value."""
    subs = [r[0] for r in pub._WIDE_RANGES]
    for general, specific in (("pm1", "pm10"),):
        assert subs.index(specific) < subs.index(
            general
        ), f"{specific!r} must be checked before {general!r} or it can never match"
