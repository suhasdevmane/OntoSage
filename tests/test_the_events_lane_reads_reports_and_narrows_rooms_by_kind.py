# -*- coding: utf-8 -*-
"""BUG-828 through the events lane itself (B11 and B23), with a fake booking store and a fake report
store, so the wiring is proven and not only the pieces.

* "Has anything been reported broken this week?" is a kind of its own (`report_activity`), needs no
  booking store, and is answered for a role that may see reports and declined for one that may not.
* "Which meeting rooms are booked this afternoon?" lists only the rooms the graph types as meeting
  rooms; a kind the building does not record is stated, never turned into "nothing is booked"; and
  a question that names no kind is answered exactly as before.
"""

from datetime import datetime, timezone
from types import SimpleNamespace

import pytest

from orchestrator.services import report_activity as ra
from orchestrator.services.adapters.mysql_events_adapter import MySQLEventsAdapter
from orchestrator.services.datasource_registry import derive_point_uuid
from orchestrator.services.event_query_service import EventQueryService, classify_event_question

pytestmark = pytest.mark.unit

NOW = datetime(2026, 9, 18, 13, 0)  # a Friday, 13:00 on the store clock
ROOMS = ["Room1.25", "Room1.26", "Room1.06", "Room2.01"]
KINDS = {
    "Room1.25": {"Room", "Conference_Room"},
    "Room1.26": {"Room", "Conference_Room"},
    "Room1.06": {"Room", "Laboratory"},
    "Room2.01": {"Room", "Office"},
}


class _FakeResult:
    def __init__(self, rows):
        self.rows = rows
        self.success = True


class _FakeAdapter(MySQLEventsAdapter):
    def __init__(self, rows):
        super().__init__(host="x", port=3306, user="x", password="x", database="x")
        self._canned = rows

    async def execute_query(self, sql):
        return _FakeResult(self._canned)


def _booking(room, hour):
    return (
        f"id-{room}-{hour}",
        "booking",
        derive_point_uuid("tb", "evt_subject", room),
        datetime(2026, 9, 18, hour, 0),
        datetime(2026, 9, 18, hour + 1, 0),
        "confirmed",
        None,
    )


def _svc(rows, kinds=KINDS):
    return EventQueryService("tb", _FakeAdapter(rows), ROOMS, room_kinds=kinds)


# ── which meeting rooms are booked ──────────────────────────────────────────

ROWS = [
    _booking("Room1.25", 14),
    _booking("Room1.25", 16),
    _booking("Room1.06", 14),  # a laboratory
    _booking("Room2.01", 15),  # an office
]


async def test_which_meeting_rooms_are_booked_lists_only_meeting_rooms():
    out = await _svc(ROWS).answer("Which meeting rooms are booked this afternoon?", now=NOW)
    text = out["formatted_response"]
    assert out["kind"] == "bookings_by_room"
    assert text.startswith("**1 meeting room with bookings this afternoon**")
    assert "Room 1.25: 2 session(s)" in text
    assert "Room 1.06" not in text and "Room 2.01" not in text
    assert out["count"] == 2 and out["rooms"] == [{"room": "Room1.25", "sessions": 2}]


async def test_a_kind_with_no_bookings_says_so_and_is_not_a_list_of_other_rooms():
    only_others = [_booking("Room1.06", 14), _booking("Room2.01", 15)]
    out = await _svc(only_others).answer("Which meeting rooms are booked this afternoon?", now=NOW)
    assert out["formatted_response"].startswith("**No meeting rooms have a booking this afternoon**")
    assert out["count"] == 0


async def test_a_kind_the_building_does_not_record_is_stated_not_read_as_nothing_booked():
    out = await _svc(ROWS, kinds={}).answer("Which meeting rooms are booked this afternoon?", now=NOW)
    text = out["formatted_response"]
    assert "3 room(s) with bookings" in text  # every room, because none can be told apart
    assert "does not record which rooms are meeting rooms" in text


async def test_a_question_that_names_no_kind_is_answered_exactly_as_before():
    out = await _svc(ROWS).answer("Which rooms are booked this afternoon?", now=NOW)
    assert out["formatted_response"].startswith("**3 room(s) with bookings this afternoon**")
    assert "does not record" not in out["formatted_response"]


async def test_which_meeting_rooms_are_free_is_narrowed_the_same_way():
    out = await _svc(ROWS).answer("Which meeting rooms are free this afternoon?", now=NOW)
    assert out["kind"] == "availability_list"
    assert out["total_rooms"] == 2 and out["free_rooms"] == ["Room1.26"]
    assert "1 of 2 meeting rooms have no booking" in out["formatted_response"]


# ── what has been reported ──────────────────────────────────────────────────


def test_a_reports_question_has_its_own_kind_and_leaves_its_neighbours_alone():
    assert classify_event_question("Has anything been reported broken this week?") == "report_activity"
    assert classify_event_question("Which faults keep being reported in the same place?") == "recurrence"
    assert classify_event_question("How many open work orders are there?") == "workorder_summary"
    assert classify_event_question("Which rooms are booked today?") == "bookings_list"


class _Conn:
    def __init__(self, rows):
        self.rows, self.calls = rows, []

    async def fetch(self, sql, *args):
        self.calls.append((sql, args))
        return self.rows


class _Acquire:
    def __init__(self, conn):
        self.conn = conn

    async def __aenter__(self):
        return self.conn

    async def __aexit__(self, *exc):
        return False


def _postgres(rows):
    conn = _Conn(rows)
    return SimpleNamespace(pool=SimpleNamespace(acquire=lambda: _Acquire(conn)), conn=conn)


def _report_row():
    return {
        "category": "maintenance",
        "status": "OPEN",
        "priority": "HIGH",
        "place": "Room 2.01",
        "device": "projector",
        "created_at": datetime(2026, 9, 17, 9, 0, tzinfo=timezone.utc),
    }


@pytest.fixture
def report_store(monkeypatch):
    pg = _postgres([_report_row()])
    monkeypatch.setattr(
        "orchestrator.services.report_intake_service.get_report_intake_service",
        lambda *a, **k: SimpleNamespace(postgres=pg),
    )
    return pg


async def test_a_facility_manager_gets_the_report_breakdown_with_no_booking_store_at_all(report_store):
    svc = EventQueryService("tb", None, ROOMS)  # no events adapter: reports do not need one
    out = await svc.answer(
            "Has anything been reported broken this week?", now=NOW, reader_role="facility_manager"
        )
    assert out["kind"] == "report_activity" and out["count"] == 1
    assert "Room 2.01" in out["formatted_response"] and "projector" in out["formatted_response"]
    assert "documents" not in out["formatted_response"].lower()


async def test_an_occupant_asking_the_same_question_is_declined_and_the_store_is_not_read(report_store):
    svc = EventQueryService("tb", None, ROOMS)
    out = await svc.answer("Has anything been reported broken this week?", now=NOW, reader_role="occupant")
    assert out["kind"] == "report_activity_not_permitted"
    assert report_store.conn.calls == []


async def test_an_unknown_role_fails_closed(report_store):
    svc = EventQueryService("tb", None, ROOMS)
    out = await svc.answer("Has anything been reported broken this week?", now=NOW)
    assert out["kind"] == "report_activity_not_permitted"


async def test_the_report_numbers_pass_the_events_lanes_own_numeric_guard(report_store):
    from orchestrator.services.numeric_guard import SUPPRESSION_TEXT, guard_payload

    svc = EventQueryService("tb", None, ROOMS)
    out = await svc.answer("What has been reported this week?", now=NOW, reader_role="admin")
    assert guard_payload(out, "events")["formatted_response"] != SUPPRESSION_TEXT
    assert ra.REPORT_PERMISSION == "report:read"
