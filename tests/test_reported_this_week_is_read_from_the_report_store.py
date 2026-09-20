# -*- coding: utf-8 -*-
"""BUG-828 (tail B row B23): "Has anything been reported broken this week?" is a question about
the REPORT STORE, not about two uploaded registers.

The capability lane answered it with "the projector in Room 2.01 failed during maintenance on
2026-09-02" (not this week, and not a report) and, on the second run, "documents do not answer
this". `user_reports` holds what people filed, by category, status, priority and place.

These tests pin the four things that make the answer safe to give: the shape is recognised and
statements/procedures are not; the window is the one the reader named; the reporter's identity
is unreachable; and only a role holding ``report:read`` sees other people's reports.
"""

from datetime import datetime, timezone

import pytest

from orchestrator.services import report_activity as ra
from orchestrator.services.numeric_guard import SUPPRESSION_TEXT, guard_payload

pytestmark = pytest.mark.unit

# ── the shape ───────────────────────────────────────────────────────────────

ASKS_WHAT_WAS_REPORTED = [
    "Has anything been reported broken this week?",  # the failing question, B23
    "Have any faults been reported today?",
    "What has been reported this week?",
    "What problems have people reported recently?",
    "Any new complaints filed this week?",
    "How many faults were reported yesterday?",
    "How many reports are open?",
    "Were there any new issues reported last week?",
    "Is anything reported as broken on floor 3?",
    "What near-misses were reported this quarter, and do they cluster by location?",
]

NOT_ABOUT_REPORT_ACTIVITY = [
    "How do I report a fault?",  # a procedure
    "The toilet on floor 2 is leaking",  # somebody making a report
    "Something is broken and I already reported it",  # a statement, however it reads
    "Is the lift broken?",  # asset state
    "What is the status of REP-AB12CD?",  # one report's status, intake owns it
    "Give me a report on energy use last week",  # a document, not the store
    "Is the projector in Room 2.01 working?",
    "Which faults keep being reported in the same place?",  # recurrence, the events lane's own
    # Shapes the first draft claimed: the subject of "reported" is a roll call, a zone or a
    # barrier, not a fault, so they are not asking what people filed. Written in the test's own
    # words: a stakeholder-catalogue question must not be copied into a fixture.
    "Which assembly points have reported in so far, and which are still outstanding?",
    "Which zones report that people are sheltering, and how is each one contacted?",
    "Which barriers were noticed today, and who must respond first?",
]


@pytest.mark.parametrize("question", ASKS_WHAT_WAS_REPORTED)
def test_a_question_about_what_was_reported_is_recognised(question):
    assert ra.is_report_activity_question(question), question


@pytest.mark.parametrize("question", NOT_ABOUT_REPORT_ACTIVITY)
def test_procedures_statements_and_asset_state_are_not_report_activity(question):
    assert not ra.is_report_activity_question(question), question


def test_category_follows_the_words_the_reader_used():
    assert ra.category_asked("Has anything been reported broken this week?") == "maintenance"
    assert ra.category_asked("Any complaints filed today?") == "complaint"
    assert ra.category_asked("Were any safety hazards reported?") == "safety"
    assert ra.category_asked("What has been reported this week?") == ""


# ── the window ──────────────────────────────────────────────────────────────

FRIDAY = datetime(2026, 9, 18, 15, 0)  # week 38, Monday was 14 September


def test_this_week_starts_on_monday_and_ends_now_not_in_the_future():
    start, end, label = ra.report_window("Has anything been reported broken this week?", FRIDAY)
    assert (start.day, start.hour) == (14, 0)
    assert end == FRIDAY  # nothing can have been reported after now
    assert label == "this week"


def test_no_period_named_means_a_rolling_week_not_today_so_far():
    start, end, label = ra.report_window("What has been reported?", FRIDAY)
    assert (end - start).days == 7 and end == FRIDAY
    assert label == "in the last 7 days"


def test_months_and_past_n_days_are_understood():
    s, e, label = ra.report_window("Any faults reported last month?", FRIDAY)
    assert (s.month, s.day, e.month, e.day, label) == (8, 1, 9, 1, "last month")
    s, e, label = ra.report_window("Anything reported this month?", FRIDAY)
    assert (s.month, s.day, label) == (9, 1, "this month")
    s, e, label = ra.report_window("Anything reported in the past 14 days?", FRIDAY)
    assert (e - s).days == 14 and label == "in the past 14 days"


def test_quarters_and_years_are_understood_not_silently_read_as_a_week():
    s, e, label = ra.report_window("What near-misses were reported this quarter?", FRIDAY)
    assert (s.month, s.day, label) == (7, 1, "this quarter") and e == FRIDAY
    s, e, label = ra.report_window("Anything reported last quarter?", FRIDAY)
    assert (s.month, s.day, e.month, e.day, label) == (4, 1, 7, 1, "last quarter")
    s, e, label = ra.report_window("Anything reported last year?", FRIDAY)
    assert (s.year, s.month, e.year, e.month, label) == (2025, 1, 2026, 1, "last year")
    january = datetime(2026, 1, 20, 10, 0)
    s, e, label = ra.report_window("Anything reported last quarter?", january)
    assert (s.year, s.month, e.year, e.month) == (2025, 10, 2026, 1)


def test_yesterday_is_the_calendar_day_not_the_last_24_hours():
    s, e, label = ra.report_window("Anything reported yesterday?", FRIDAY)
    assert (s.day, s.hour, e.day, e.hour, label) == (17, 0, 18, 0, "yesterday")


# ── access ──────────────────────────────────────────────────────────────────


@pytest.mark.parametrize("role", ["facility_manager", "admin", "analyst"])
def test_roles_that_hold_report_read_may_see_the_breakdown(role):
    assert ra.may_view_reports(role)


@pytest.mark.parametrize("role", ["occupant", "readonly", "operator", "", None, "no_such_role"])
def test_every_other_role_fails_closed(role):
    assert not ra.may_view_reports(role)


# ── the store: what is read, and what can never be ──────────────────────────


class _Conn:
    def __init__(self, rows, fail=False):
        self.rows, self.fail, self.calls = rows, fail, []

    async def fetch(self, sql, *args):
        self.calls.append((sql, args))
        if self.fail:
            raise RuntimeError("connection reset")
        return self.rows


class _Acquire:
    def __init__(self, conn):
        self.conn = conn

    async def __aenter__(self):
        return self.conn

    async def __aexit__(self, *exc):
        return False


class _Pool:
    def __init__(self, conn):
        self.conn = conn

    def acquire(self):
        return _Acquire(self.conn)


class _Postgres:
    def __init__(self, rows=None, fail=False):
        self.conn = _Conn(rows or [], fail=fail)
        self.pool = _Pool(self.conn)


def _row(category="maintenance", status="OPEN", priority="HIGH", place="Room 2.01", device="projector", day=17):
    return {
        "category": category,
        "status": status,
        "priority": priority,
        "place": place,
        "device": device,
        "created_at": datetime(2026, 9, day, 9, 30, tzinfo=timezone.utc),
    }


def test_the_query_names_its_columns_so_no_identity_or_free_text_is_ever_read():
    sql = ra._SELECT_SQL.lower()
    for private in (
        "reporter_id",
        "persona",
        "session_id",
        "assignee",
        "description",
        "title",
        "admin_notes",
        "select *",
    ):
        assert private not in sql, private


async def test_a_permitted_role_gets_counts_places_and_status_from_the_store():
    pg = _Postgres(
        [
            _row(place="Room 2.01", device="projector", status="OPEN", day=17),
            _row(priority="NORMAL", place="", device="", status="RESOLVED", day=16),
            _row(place="Room 3.04", device="light", status="IN_PROGRESS", day=15),
        ]
    )
    out = await ra.answer_report_activity(
        "Has anything been reported broken this week?",
        building_id="bldgX",
        now_utc=datetime(2026, 9, 18, 14, 0),
        tz_name=None,
        reader_role="facility_manager",
        postgres=pg,
    )
    text = out["formatted_response"]
    assert out["count"] == 3 and out["open"] == 2
    assert "**3 fault reports filed this week**, 2 still open" in text
    assert "Room 2.01" in text and "projector" in text
    assert "no location given" in text
    assert "1 of these gave no location" in text
    assert out["source"] == "user_reports"
    # the store was asked for THIS building and THIS window, with the maintenance category
    sql, args = pg.conn.calls[0]
    assert args[0] == "bldgX"
    assert args[1] == datetime(2026, 9, 14, 0, 0, tzinfo=timezone.utc)
    assert args[3] == "maintenance"


async def test_the_answer_carries_its_own_numbers_so_the_numeric_guard_lets_it_through():
    pg = _Postgres([_row(day=17), _row(category="complaint", day=16, status="CLOSED")])
    out = await ra.answer_report_activity(
        "What has been reported this week?",
        building_id="bldgX",
        now_utc=datetime(2026, 9, 18, 14, 0),
        tz_name="Europe/London",
        reader_role="admin",
        postgres=pg,
    )
    assert guard_payload(out, "events")["formatted_response"] != SUPPRESSION_TEXT
    assert "By kind" in out["formatted_response"]


async def test_reporter_identity_is_not_in_the_answer_even_if_the_row_carried_it():
    row = _row()
    row["reporter_id"] = "jane.doe@example.com"
    row["description"] = "Jane Doe says the projector caught fire"
    out = await ra.answer_report_activity(
        "Has anything been reported broken this week?",
        building_id="bldgX",
        now_utc=datetime(2026, 9, 18, 14, 0),
        tz_name=None,
        reader_role="facility_manager",
        postgres=_Postgres([row]),
    )
    blob = repr(out)
    assert "jane" not in blob.lower() and "caught fire" not in blob


async def test_an_occupant_is_declined_before_the_store_is_touched():
    pg = _Postgres([_row()])
    out = await ra.answer_report_activity(
        "Has anything been reported broken this week?",
        building_id="bldgX",
        now_utc=datetime(2026, 9, 18, 14, 0),
        tz_name=None,
        reader_role="occupant",
        postgres=pg,
    )
    assert out["kind"] == "report_activity_not_permitted"
    assert "facility staff" in out["formatted_response"]
    assert pg.conn.calls == []


async def test_a_quiet_window_says_so_and_says_what_it_counts():
    out = await ra.answer_report_activity(
        "Has anything been reported broken this week?",
        building_id="bldgX",
        now_utc=datetime(2026, 9, 18, 14, 0),
        tz_name=None,
        reader_role="facility_manager",
        postgres=_Postgres([]),
    )
    assert out["count"] == 0
    assert "No fault reports were filed this week" in out["formatted_response"]
    assert "through this assistant" in out["formatted_response"]


async def test_an_unreadable_store_is_never_reported_as_a_quiet_week():
    out = await ra.answer_report_activity(
        "Has anything been reported broken this week?",
        building_id="bldgX",
        now_utc=datetime(2026, 9, 18, 14, 0),
        tz_name=None,
        reader_role="facility_manager",
        postgres=_Postgres(fail=True),
    )
    assert out["success"] is False
    assert "couldn't read" in out["formatted_response"]
    assert "No " not in out["formatted_response"].split("**")[0]
    assert out.get("count") is None


async def test_no_database_connection_is_an_unavailable_store_not_an_empty_one():
    out = await ra.answer_report_activity(
        "What has been reported this week?",
        building_id="bldgX",
        now_utc=datetime(2026, 9, 18, 14, 0),
        tz_name=None,
        reader_role="facility_manager",
        postgres=object(),  # no .pool
    )
    assert out["success"] is False


def test_a_long_free_text_device_is_shortened_and_cannot_carry_markup():
    line = ra.summarise_reports(
        [_row(device="proj|ector`" + "x" * 200)], label="this week"
    )["reports"][0]
    assert "|" not in line and "`" not in line
    assert len(line) < 200


# ── a named place narrows the answer, so the subject stays what was asked ───────────────────


def test_a_floor_or_a_room_named_in_the_question_becomes_a_place_filter():
    regex, phrase = ra.place_scope("Is anything reported as broken on floor 3?")
    assert phrase == "on floor 3"
    import re

    assert re.search(regex, "Floor 3 corridor", re.I) and re.search(regex, "Room3.04", re.I)
    assert re.search(regex, "urn:x#Room3.04", re.I) and not re.search(regex, "Room 4.04", re.I)
    assert not re.search(regex, "Floor 30", re.I)  # floor 30 is not floor 3
    regex, phrase = ra.place_scope("Has the projector in Room 2.01 been reported broken?")
    assert phrase == "in Room 2.01"
    assert re.search(regex, "Room 2.01", re.I) and not re.search(regex, "Room 12.01", re.I)
    assert ra.place_scope("Has anything been reported broken this week?") == ("", "")


async def test_the_place_filter_reaches_the_query_and_the_answer_says_it():
    pg = _Postgres([_row(place="Floor 3 corridor", device="light", day=17)])
    out = await ra.answer_report_activity(
        "Has anything been reported broken on floor 3 this week?",
        building_id="bldgX",
        now_utc=datetime(2026, 9, 18, 14, 0),
        tz_name=None,
        reader_role="facility_manager",
        postgres=pg,
    )
    sql, args = pg.conn.calls[0]
    assert "~*" in sql and "location" in sql and "space_iri" in sql
    assert args[3] == "maintenance" and "floor" in args[4]
    assert "**1 fault report filed this week on floor 3**" in out["formatted_response"]


async def test_a_quiet_floor_says_which_floor_it_was_quiet_on():
    out = await ra.answer_report_activity(
        "Has anything been reported broken on floor 3 this week?",
        building_id="bldgX",
        now_utc=datetime(2026, 9, 18, 14, 0),
        tz_name=None,
        reader_role="facility_manager",
        postgres=_Postgres([]),
    )
    assert "No fault reports were filed this week on floor 3" in out["formatted_response"]
