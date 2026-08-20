# -*- coding: utf-8 -*-
"""V5-T08: synthetic event generators — determinism, lifecycles, consistency."""

from datetime import datetime, timedelta

import pytest

from orchestrator.services.deliberation.synthetic_events import (
    access_events_for_day,
    bookings_for_room_day,
    event_id,
    generate_building_day,
    to_row,
    workorders_for_day,
)
from orchestrator.services.deliberation.synthetic_signals import (
    STEP_MINUTES,
    occupancy_series,
)

pytestmark = pytest.mark.unit

BID = "tb"
DAY = datetime(2026, 8, 12)  # Wednesday
NOW = datetime(2026, 8, 15, 12, 0, 0)
ROOMS = [f"R{n:03d}" for n in range(1, 21)]


def test_deterministic_across_runs():
    a = generate_building_day(BID, ROOMS, DAY, NOW)
    b = generate_building_day(BID, ROOMS, DAY, NOW)
    assert [to_row(e) for e in a] == [to_row(e) for e in b]


def test_event_ids_stable_and_unique():
    events = generate_building_day(BID, ROOMS, DAY, NOW)
    ids = [e["event_id"] for e in events]
    assert len(ids) == len(set(ids))
    # identity: same (building, type, subject, start) -> same id, regardless of path
    bookings = bookings_for_room_day(BID, "R001", DAY)
    for b in bookings:
        assert b["event_id"] == event_id(BID, "booking", "R001", b["start_dt"])


def test_real_bookings_overlap_occupancy_and_ghosts_do_not():
    steps = (24 * 60) // STEP_MINUTES
    for room in ROOMS:
        occ = occupancy_series(BID, room, DAY, steps)
        day0 = DAY.replace(hour=0, minute=0, second=0, microsecond=0)
        for b in bookings_for_room_day(BID, room, DAY):
            s = int((b["start_dt"] - day0).total_seconds() // 60 // STEP_MINUTES)
            t = int((b["end_dt"] - day0).total_seconds() // 60 // STEP_MINUTES)
            window = occ[s:t]
            if b["attrs"]["ghost"]:
                assert all(v == 0 for v in window), f"ghost booking overlaps occupancy in {room}"
            else:
                assert any(v > 0 for v in window), f"real booking in empty window in {room}"


def test_workorder_lifecycle_consistency():
    events = []
    day = DAY - timedelta(days=20)
    while day <= NOW:
        events += workorders_for_day(BID, ROOMS, day, NOW)
        day += timedelta(days=1)
    assert events, "expected some work orders over 3+ weeks"
    for e in events:
        if e["status"] == "done":
            assert e["end_dt"] is not None and e["end_dt"] <= NOW
        else:
            assert e["end_dt"] is None
    statuses = {e["status"] for e in events}
    assert "done" in statuses  # lifecycle actually progresses


def test_access_events_are_aggregate_only():
    events = access_events_for_day(BID, ROOMS, DAY)
    assert events
    for e in events:
        assert e["attrs"]["count"] >= 1
        assert "person" not in str(e["attrs"]).lower()
        assert e["event_type"] == "access"


def test_weekend_quieter_than_weekday():
    saturday = datetime(2026, 8, 15)
    wk = generate_building_day(BID, ROOMS, DAY, NOW)
    we = generate_building_day(BID, ROOMS, saturday, NOW)
    assert len([e for e in we if e["event_type"] == "booking"]) < len(
        [e for e in wk if e["event_type"] == "booking"]
    )


def test_to_row_shapes():
    e = generate_building_day(BID, ROOMS, DAY, NOW)[0]
    row = to_row(e)
    assert len(row) == 7 and isinstance(row[6], str) and row[6].startswith("{")
