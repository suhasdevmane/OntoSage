# -*- coding: utf-8 -*-
"""V5-T24: event query lane — classification, windows, handlers, honesty."""

import asyncio
from datetime import datetime

import pytest

from orchestrator.services.adapters.mysql_events_adapter import MySQLEventsAdapter
from orchestrator.services.datasource_registry import derive_point_uuid
from orchestrator.services.event_query_service import (
    EventQueryService,
    classify_event_question,
    parse_window,
)

pytestmark = pytest.mark.unit

NOW = datetime(2026, 8, 12, 10, 0, 0)  # Wednesday 10:00
ROOMS = ["RM001A_room", "RM101_room", "RM125_room"]


def test_kind_classification():
    assert classify_event_question("Is RM101 free at 3pm today?") == "availability_check"
    assert classify_event_question("Which rooms are free this afternoon?") == "availability_list"
    assert classify_event_question("Show me the bookings for RM125 today") == "bookings_list"
    assert classify_event_question("How many open work orders are there?") == "workorder_summary"
    assert (
        classify_event_question("How busy was the main entrance this morning?") == "access_summary"
    )
    assert classify_event_question("What is the CO2 in RM101?") is None


def test_window_parsing():
    s, e, label = parse_window("is it free at 3pm?", NOW)
    assert (s.hour, e.hour) == (15, 16)
    s, e, label = parse_window("bookings yesterday", NOW)
    assert label == "yesterday" and (e - s).days == 1
    s, e, label = parse_window("footfall this morning", NOW)
    assert label == "this morning" and e.hour == 12
    s, e, label = parse_window("free tomorrow at 9am", NOW)
    assert s.day == 13 and s.hour == 9


class _FakeResult:
    def __init__(self, rows):
        self.rows = rows
        self.success = True


class _FakeAdapter(MySQLEventsAdapter):
    """Real SQL builders, canned execution."""

    def __init__(self, rows):
        super().__init__(host="x", port=3306, user="x", password="x", database="x")
        self._canned = rows
        self.last_sql = None

    async def execute_query(self, sql):
        self.last_sql = sql
        return _FakeResult(self._canned)


def _svc(rows):
    return EventQueryService("tb", _FakeAdapter(rows), ROOMS)


def test_availability_check_free_and_busy():
    svc = _svc([])
    r = asyncio.run(svc.answer("Is RM101 free at 3pm?", now=NOW))
    assert r["success"] and r["free"] and "RM101_room is free" in r["formatted_response"]
    busy_row = (
        "id1",
        "booking",
        derive_point_uuid("tb", "evt_subject", "RM101_room"),
        datetime(2026, 8, 12, 15, 0),
        datetime(2026, 8, 12, 16, 0),
        "done",
        None,
    )
    r = asyncio.run(_svc([busy_row]).answer("Is RM101 free at 3pm?", now=NOW))
    assert not r["free"] and "booked" in r["formatted_response"]


def test_availability_list_excludes_busy_rooms():
    busy = (
        "id1",
        "booking",
        derive_point_uuid("tb", "evt_subject", "RM001A_room"),
        datetime(2026, 8, 12, 9, 0),
        datetime(2026, 8, 12, 17, 0),
        "done",
        None,
    )
    r = asyncio.run(_svc([busy]).answer("Which rooms are free today?", now=NOW))
    assert r["free_count"] == 2 and "RM001A_room" not in r["free_rooms"]


def test_workorder_summary_counts_and_overdue():
    rows = [("open", 3), ("done", 12)]
    r = asyncio.run(_svc(rows).answer("How many work orders are there?", now=NOW))
    assert r["counts"] == {"open": 3, "done": 12} and r["total"] == 15
    svc = _svc([("open", 2)])
    r = asyncio.run(svc.answer("Any overdue tickets?", now=NOW))
    assert r["aged_filter_days"] == 7 and "more than 7 days" in r["formatted_response"]


def test_access_summary_sums_counts():
    rows = [
        (
            "a1",
            "access",
            "u",
            datetime(2026, 8, 12, 8, 0),
            datetime(2026, 8, 12, 8, 10),
            "done",
            '{"count":5}',
        ),
        (
            "a2",
            "access",
            "u",
            datetime(2026, 8, 12, 9, 0),
            datetime(2026, 8, 12, 9, 10),
            "done",
            '{"count":7}',
        ),
    ]
    r = asyncio.run(_svc(rows).answer("How busy was the entrance this morning?", now=NOW))
    assert r["arrivals"] == 12 and "12 arrivals" in r["formatted_response"]
    assert "individuals are never tracked" in r["formatted_response"]


def test_honest_decline_when_source_absent():
    svc = EventQueryService("tb", None, ROOMS)
    r = asyncio.run(svc.answer("Which rooms are free today?", now=NOW))
    assert not r["success"]
    assert "no events source registered" in r["formatted_response"]
    assert "unlocks" in r["formatted_response"]


def test_room_resolution_tolerant():
    svc = _svc([])
    assert svc.resolve_room("is rm101 free?") == "RM101_room"
    assert svc.resolve_room("bookings for RM 125 please") == "RM125_room"
    assert svc.resolve_room("bookings for the moon base") is None


def test_routing_rule_targets_and_guards():
    import orchestrator.services.routing_contract as rc

    assert rc.EVENTS_RE.search("Is RM101 free at 3pm?")
    assert rc.EVENTS_RE.search("how many open work orders?")
    assert rc.EVENTS_RE.search("How busy was the entrance this morning?")
    # combined comfort+availability must stay with the deliberate lane
    assert rc.DELIBERATE_RE.search("find me a quiet room that is free at 3pm")


# ── V5-T21: anomaly episode summaries from the store ─────────────────────────


def test_anomaly_kind_classification_beats_tickets():
    assert classify_event_question("Any anomalies this week?") == "anomaly_summary"
    assert classify_event_question("were there unusual readings yesterday?") == "anomaly_summary"
    assert classify_event_question("Any overdue tickets?") == "workorder_summary"


def test_anomaly_summary_narrates_rooms_and_counts():
    import json as _json
    from datetime import datetime as _dt

    rows = [
        (
            "a1",
            "anomaly:stuck",
            "u-pm25-119",
            _dt(2026, 8, 16, 16, 40),
            _dt(2026, 8, 17, 22, 0),
            "open",
            _json.dumps({"severity": "high", "modality": "pm25"}),
        ),
        (
            "a2",
            "anomaly:dropout",
            "u-noise-101",
            _dt(2026, 8, 17, 2, 0),
            _dt(2026, 8, 17, 15, 0),
            "done",
            _json.dumps({"severity": "medium", "modality": "noise"}),
        ),
    ]
    svc = EventQueryService(
        "tb",
        _FakeAdapter(rows),
        ROOMS,
        point_map={"u-pm25-119": ("RM119_room", "pm25"), "u-noise-101": ("RM101_room", "noise")},
    )
    r = asyncio.run(svc.answer("Any anomalies this week?", now=NOW))
    assert r["success"] and r["kind"] == "anomaly_summary" and r["count"] == 2
    assert r["by_detector"] == {"stuck": 1, "dropout": 1}
    assert "RM119_room" in r["formatted_response"]
    # the open/high episode is the highlighted bullet
    assert "- **stuck**" in r["formatted_response"]
    assert "[open/high]" in r["formatted_response"]


def test_anomaly_summary_empty_window_is_honest():
    svc = EventQueryService("tb", _FakeAdapter([]), ROOMS)
    r = asyncio.run(svc.answer("any anomalies today?", now=NOW))
    assert r["success"] and r["count"] == 0
    assert "No anomaly episodes are recorded" in r["formatted_response"]


def test_anomaly_summary_survives_numeric_guard():
    import json as _json
    from datetime import datetime as _dt

    from orchestrator.services.numeric_guard import SUPPRESSION_TEXT, guard_payload

    rows = [
        (
            "a1",
            "anomaly:spike",
            "u-x",
            _dt(2026, 8, 12, 9, 50),
            _dt(2026, 8, 12, 10, 0),
            "done",
            _json.dumps({"severity": "low", "modality": "noise"}),
        ),
    ]
    svc = EventQueryService(
        "tb", _FakeAdapter(rows), ROOMS, point_map={"u-x": ("RM125_room", "noise")}
    )
    r = asyncio.run(svc.answer("anomalies today?", now=NOW))
    assert guard_payload(r, "events")["formatted_response"] != SUPPRESSION_TEXT
