# -*- coding: utf-8 -*-
"""Wave 2 (2D-07): "can i get a real time map of available spaces across the building?" names no room.

The events lane classified it as a lookup of ONE room's availability and answered "I couldn't match
that room name -- try the room id as it appears on the floor plan", followed by a stray "No chart was
drawn" note. The building holds what the question wants (which rooms have no booking right now), and
says it in one sentence when asked "which rooms are free?".

These tests pin the shape (a request for the list, a whole-building scope, no room named), the
meaning of "real time" (now, not the whole day) and the honest half of "map" (there is none).
"""

import pytest

from orchestrator.services import availability_overview as ao

pytestmark = pytest.mark.unit

OVERVIEW = [
    "can i get a real time map of available spaces across the building?",  # the failing question
    "Which spaces are free right now?",
    "Which rooms are available?",
    "Are there any free rooms?",
    "Show me available study spaces",
    "What's free at the moment?",
    "Is there anywhere free?",
    "Give me an overview of free rooms in the building",
    "list the vacant spaces",
    "What rooms are available across the building?",
]

NOT_AN_OVERVIEW = [
    "Is Room 1.06 free at 3pm?",  # a named room: the availability CHECK
    "Is room 5.01 available?",
    "Is 2.14 booked?",
    "Which rooms are booked this afternoon?",  # bookings, the other list
    "Is the free-standing sculpture in the atrium open?",
    "How many free parking bays are there?",  # not a room or space
    "Where can I get free water?",
    "Which rooms have teaching sessions this week?",
]


@pytest.mark.parametrize("question", OVERVIEW)
def test_a_request_for_what_is_free_across_the_building_is_an_overview(question):
    assert ao.asks_free_overview(question), question


@pytest.mark.parametrize("question", NOT_AN_OVERVIEW)
def test_a_named_room_or_a_different_question_is_not(question):
    assert not ao.asks_free_overview(question), question


def test_the_failing_question_reads_as_a_map_request_about_now_across_the_building():
    q = "can i get a real time map of available spaces across the building?"
    assert ao.asks_for_a_map(q) and ao.asks_now(q) and ao.whole_building(q)


@pytest.mark.parametrize(
    "question", ["Which rooms are free?", "Which spaces are available on floor 3 tomorrow?"]
)
def test_no_map_and_no_now_in_a_plain_list_question(question):
    assert not ao.asks_for_a_map(question) and not ao.asks_now(question)


def test_real_time_and_live_and_right_now_all_mean_now():
    for q in ("real time", "real-time", "live view of free rooms", "free at the moment", "free right now"):
        assert ao.asks_now(q), q


def test_naming_a_room_by_any_of_its_usual_spellings_is_recognised():
    for q in ("Is Room 1.06 free?", "is rm 5.01 free", "Is 2.14 free?", "Is Room1.06 free?"):
        assert ao.names_a_room(q), q
    assert not ao.names_a_room("Which rooms are free?")


def test_the_no_map_sentence_says_what_the_building_records_instead():
    assert "no live occupancy map" in ao.NO_MAP_SENTENCE
    assert "no booking right now" in ao.NO_MAP_SENTENCE


# ── through the events lane, and the note that contradicted it ───────────────────────────────

import asyncio  # noqa: E402
from datetime import datetime  # noqa: E402

from orchestrator.services.adapters.mysql_events_adapter import MySQLEventsAdapter  # noqa: E402
from orchestrator.services.datasource_registry import derive_point_uuid  # noqa: E402
from orchestrator.services.event_query_service import (  # noqa: E402
    EventQueryService,
    classify_event_question,
    parse_window,
)
from orchestrator.services.viz_honesty import chart_note  # noqa: E402

NOW = datetime(2026, 9, 19, 13, 0)
ROOMS = ["Room1.25", "Room1.26", "Room1.06"]


class _Result:
    def __init__(self, rows):
        self.rows, self.success = rows, True


class _Adapter(MySQLEventsAdapter):
    def __init__(self, rows):
        super().__init__(host="x", port=3306, user="x", password="x", database="x")
        self._rows = rows

    async def execute_query(self, sql):
        return _Result(self._rows)


def _booking(room, hour):
    return (
        f"id-{room}",
        "booking",
        derive_point_uuid("tb", "evt_subject", room),
        datetime(2026, 9, 19, hour, 0),
        datetime(2026, 9, 19, hour + 2, 0),
        "confirmed",
        None,
    )


def test_the_failing_question_is_classified_as_the_list_not_a_room_lookup():
    q = "can i get a real time map of available spaces across the building?"
    assert classify_event_question(q) == "availability_list"


def test_real_time_means_now_not_the_whole_day():
    q = "can i get a real time map of available spaces across the building?"
    start, end, label = parse_window(q, NOW)
    assert label == "right now" and start == NOW and (end - start).seconds == 60


async def test_the_answer_lists_free_rooms_and_says_there_is_no_map():
    svc = EventQueryService("tb", _Adapter([_booking("Room1.25", 12)]), ROOMS)
    out = await svc.answer(
        "can i get a real time map of available spaces across the building?", now=NOW
    )
    text = out["formatted_response"]
    assert out["kind"] == "availability_list"
    assert text.startswith("**There is no live occupancy map.**")
    assert "2 of 3 rooms have no booking right now" in text
    assert "Room 1.26" in text and "Room 1.06" in text
    assert "couldn't match that room name" not in text  # the failing answer


async def test_a_plain_list_question_gets_no_map_sentence():
    svc = EventQueryService("tb", _Adapter([]), ROOMS)
    out = await svc.answer("Which rooms are free today?", now=NOW)
    assert "occupancy map" not in out["formatted_response"]


def test_an_answer_that_already_said_there_is_no_map_gets_no_chart_note():
    # the live answer carried "No chart was drawn: there was no data to plot", under a list of rooms
    answer = ao.NO_MAP_SENTENCE + "\n\n**2 of 3 rooms have no booking right now**: Room 1.26"
    assert chart_note(wants_chart=True, has_media=False, viz_result=None, answer=answer) == ""


def test_a_genuine_chart_request_still_gets_its_note():
    note = chart_note(
        wants_chart=True,
        has_media=False,
        viz_result={"skipped": True},
        answer="**21.4 °C** is the latest reading in Room 5.01.",
    )
    assert "No chart was drawn" in note
