"""
Phase 2 tests — synthetic time-series generator (pure, offline, deterministic).

See tasks/IMPLEMENTATION_PLAN_DATASOURCE_TOGGLES_AND_PROVENANCE.md.
"""

from __future__ import annotations

from datetime import datetime

import pytest

from orchestrator.services.synthetic import (
    GENERATOR_KINDS,
    SyntheticDataService,
    generate_point_series,
)
from shared.models import DataSourceGenerator, DataSourcePoint, DataSourceSpec

pytestmark = pytest.mark.unit

END = datetime(2026, 6, 30, 12, 0, 0)  # a Tuesday, noon


def _point(uuid="u-occ-1"):
    return DataSourcePoint(
        local="Occupancy_Sensor_Floor5",
        brick_class="brick:Occupancy_Sensor",
        location="bldg:Floor5",
        unit="unit:PERCENT",
        uuid=uuid,
    )


def test_all_seed_kinds_registered():
    for kind in (
        "occupancy_profile",
        "energy_load",
        "noise_profile",
        "iaq_profile",
        "light_profile",
        "equipment_profile",
        "water_profile",
    ):
        assert kind in GENERATOR_KINDS


def test_series_length_and_shape():
    rows = generate_point_series(
        _point(), "occupancy_profile", window_days=2, interval_minutes=60, end=END
    )
    # 2 days hourly + inclusive endpoint
    assert len(rows) == 2 * 24 + 1
    # narrow row shape
    u, t, v = rows[0]
    assert u == "u-occ-1" and isinstance(v, float)
    assert len(t) == 19 and t[4] == "-" and t[13] == ":"


def test_deterministic_regeneration():
    a = generate_point_series(_point(), "occupancy_profile", window_days=3, end=END)
    b = generate_point_series(_point(), "occupancy_profile", window_days=3, end=END)
    assert a == b


def test_occupancy_night_is_zero_daytime_positive():
    rows = generate_point_series(
        _point(),
        "occupancy_profile",
        window_days=1,
        interval_minutes=60,
        end=END,
        params={"opening_hour": 8, "closing_hour": 20, "weekday_peak": 0.9, "noise": 0.0},
    )
    by_hour = {int(t[11:13]): v for _u, t, v in rows}
    assert by_hour[3] == 0.0  # 3am closed
    assert by_hour[14] > 0.0  # 2pm open


def test_weekday_busier_than_weekend():
    # noon on a weekday vs the weekend, noise off for determinism
    p = {
        "opening_hour": 8,
        "closing_hour": 20,
        "weekday_peak": 0.9,
        "weekend_peak": 0.1,
        "noise": 0.0,
    }
    weekday = generate_point_series(
        _point(),
        "occupancy_profile",
        window_days=0,
        interval_minutes=60,
        end=datetime(2026, 6, 30, 12, 0),
        params=p,
    )[-1][2]
    weekend = generate_point_series(
        _point(),
        "occupancy_profile",
        window_days=0,
        interval_minutes=60,
        end=datetime(2026, 6, 28, 12, 0),
        params=p,  # Sunday
    )[-1][2]
    assert weekday > weekend


def test_unknown_kind_raises():
    with pytest.raises(ValueError):
        generate_point_series(_point(), "not_a_kind", end=END)


def test_spike_anomaly_injected():
    rows = generate_point_series(
        _point(),
        "energy_load",
        window_days=1,
        interval_minutes=60,
        end=END,
        params={"base_kwh": 4, "peak_kwh": 20, "noise": 0.0},
        anomalies=[{"type": "spike", "at": "2026-06-30T12:00:00", "magnitude": 3.0}],
    )
    # last sample is noon (the spike target); it should be markedly larger than
    # the same-hour baseline the day before
    noon_vals = [v for _u, t, v in rows if t.endswith("12:00:00")]
    assert noon_vals[-1] > noon_vals[0] * 1.5


def test_flatline_anomaly_holds_value():
    rows = generate_point_series(
        _point(),
        "energy_load",
        window_days=1,
        interval_minutes=60,
        end=END,
        params={"base_kwh": 4, "peak_kwh": 20, "noise": 0.0},
        anomalies=[{"type": "flatline", "at": "2026-06-30T08:00:00", "duration_min": 180}],
    )
    seg = [v for _u, t, v in rows if "2026-06-30 08:00" <= t <= "2026-06-30 10:00"]
    assert len(set(seg)) == 1  # held constant


# ── Service ────────────────────────────────────────────────────────────────────


def _spec():
    return DataSourceSpec(
        id="occupancy",
        label="Occupancy",
        modality="occupancy",
        kind="timeseries",
        provenance_system="Occupancy Sensing System",
        ts_table="occupancy_data",
        points=[_point("u1"), _point("u2")],
        generator=DataSourceGenerator(kind="occupancy_profile", window_days=1, interval_minutes=60),
    )


def test_service_generate_rows_per_point():
    # give the two points distinct locals/uuids
    spec = _spec()
    spec.points[1].local = "Occupancy_Sensor_Floor3"
    rows = SyntheticDataService().generate_rows(spec, end=END)
    assert set(rows.keys()) == {"Occupancy_Sensor_Floor5", "Occupancy_Sensor_Floor3"}
    assert all(len(v) == 25 for v in rows.values())


def test_service_preview():
    prev = SyntheticDataService().preview(_spec(), limit=10)
    assert prev["ts_table"] == "occupancy_data"
    assert len(prev["sample"]) == 10
    assert prev["total_rows"] > 0


def test_service_regenerate_noop_for_text_reports():
    spec = DataSourceSpec(
        id="complaints",
        label="Complaints",
        modality="complaints",
        kind="text_reports",
        provenance_system="Student Complaint System",
    )
    res = SyntheticDataService().regenerate(spec)
    assert res["ok"] and res["rows"] == 0
