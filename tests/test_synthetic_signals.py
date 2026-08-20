"""
V4-T10 tests — correlated physics-lite signal model.

The properties that matter: determinism (exact ground truth for the L7 grader),
cross-modal correlation through the shared occupancy driver, plausible ranges,
weekday/weekend structure, binary domains for contacts.
"""

from __future__ import annotations

from datetime import datetime

import pytest

from orchestrator.services.deliberation.synthetic_signals import (
    STEP_MINUTES,
    day_timestamps,
    generate_room_day,
    modality_series,
    occupancy_series,
)

pytestmark = pytest.mark.unit

BID = "anybldg"
ROOM = "RoomA"
WEDNESDAY = datetime(2026, 8, 12)
SATURDAY = datetime(2026, 8, 15)
STEPS = (24 * 60) // STEP_MINUTES
ALL = [
    "temperature",
    "humidity",
    "co2",
    "occupancy",
    "noise",
    "illuminance",
    "door_contact",
    "window_contact",
]


def test_deterministic_reruns_are_identical():
    a = generate_room_day(BID, ROOM, ALL, WEDNESDAY)
    b = generate_room_day(BID, ROOM, ALL, WEDNESDAY)
    assert a == b


def test_different_rooms_and_days_differ():
    a = generate_room_day(BID, ROOM, ["co2"], WEDNESDAY)
    assert a != generate_room_day(BID, "RoomB", ["co2"], WEDNESDAY)
    assert a != generate_room_day(BID, ROOM, ["co2"], datetime(2026, 8, 13))


def test_weekday_occupied_weekend_empty():
    weekday = occupancy_series(BID, ROOM, WEDNESDAY, STEPS)
    weekend = occupancy_series(BID, ROOM, SATURDAY, STEPS)
    assert sum(weekday) > 20  # meaningful daytime occupancy
    assert sum(weekend) <= sum(weekday) * 0.1  # weekends near-empty
    assert max(weekday[: 6 * 6]) <= 1  # pre-06:00 essentially empty


def test_co2_lags_and_follows_occupancy():
    day = generate_room_day(BID, ROOM, ["occupancy", "co2"], WEDNESDAY)
    occ, co2 = day["occupancy"], day["co2"]
    night = co2[: 5 * 6]  # 00:00-05:00
    busy_idx = max(range(STEPS), key=lambda i: occ[i])
    assert max(night) < 520  # near baseline overnight
    assert co2[busy_idx] > 600  # elevated when occupied
    assert all(v >= 400 for v in co2)


def test_noise_day_vs_night_and_floor():
    day = generate_room_day(BID, ROOM, ["noise"], WEDNESDAY)["noise"]
    night_avg = sum(day[: 5 * 6]) / (5 * 6)
    work_avg = sum(day[10 * 6 : 16 * 6]) / (6 * 6)
    assert work_avg > night_avg + 3  # audible working day
    assert min(day) >= 28.0


def test_temperature_and_humidity_plausible():
    day = generate_room_day(BID, ROOM, ["temperature", "humidity"], WEDNESDAY)
    assert all(17.5 <= v <= 27.0 for v in day["temperature"])
    assert all(28.0 <= v <= 70.0 for v in day["humidity"])


def test_contacts_are_binary_and_sparse():
    day = generate_room_day(BID, ROOM, ["door_contact", "window_contact"], WEDNESDAY)
    for m in ("door_contact", "window_contact"):
        assert set(day[m]) <= {0.0, 1.0}
    assert 0 < sum(day["door_contact"]) < 25  # a handful of events, not noise


def test_illuminance_lights_track_occupancy():
    day = generate_room_day(BID, ROOM, ["occupancy", "illuminance"], WEDNESDAY)
    occ, lux = day["occupancy"], day["illuminance"]
    occupied = [lux[i] for i in range(STEPS) if occ[i] > 0]
    empty_night = [lux[i] for i in range(5 * 6) if occ[i] == 0]
    assert min(occupied) > 250  # lights on when someone is in
    assert max(empty_night) < 60  # dark at night


def test_unknown_modality_yields_zeros_not_invented_physics():
    occ = occupancy_series(BID, ROOM, WEDNESDAY, STEPS)
    assert modality_series("radiation", BID, ROOM, WEDNESDAY, occ) == [0.0] * STEPS


def test_day_timestamps_grid():
    stamps = day_timestamps(WEDNESDAY)
    assert len(stamps) == STEPS
    assert stamps[0].hour == 0 and stamps[0].minute == 0
    assert (stamps[1] - stamps[0]).total_seconds() == STEP_MINUTES * 60
