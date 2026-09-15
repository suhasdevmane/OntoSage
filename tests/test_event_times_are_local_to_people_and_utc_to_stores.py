# -*- coding: utf-8 -*-
"""BUG-539 / BUG-540: the events store is UTC; the people asking are not.

A question names building-local time ("at 3pm", "today", "the next two hours") and an
answer is read in building-local time ("booked 09:20-19:00"). The store is compared in UTC.
The zone converts at those two edges and nowhere else; with no zone configured the
behaviour is exactly what it was.
"""

import asyncio
from datetime import datetime

import pytest

from orchestrator.services.adapters.mysql_events_adapter import MySQLEventsAdapter
from orchestrator.services.datasource_registry import derive_point_uuid
from orchestrator.services.event_query_service import EventQueryService, parse_window

pytestmark = pytest.mark.unit

TZ = "Europe/London"
# 2026-09-15 00:20 UTC is 01:20 BST — the live question that exposed BUG-539.
STORE_NOW = datetime(2026, 9, 15, 0, 20, 0)
ROOMS = ["Room1.06"]


class _Result:
    def __init__(self, rows):
        self.rows, self.success = rows, True


class _Adapter(MySQLEventsAdapter):
    def __init__(self, rows):
        super().__init__(host="x", port=3306, user="x", password="x", database="x")
        self._canned, self.sql = rows, []

    async def execute_query(self, sql):
        self.sql.append(sql)
        return _Result(self._canned)


def _booking(start, end):
    return ("e1", "booking", derive_point_uuid("tb", "evt_subject", "Room1.06"), start, end,
            "booked", None)


@pytest.mark.parametrize(
    "q, minutes, label",
    [
        ("Is Room 1.06 free for the next two hours?", 120, "for the next 2 hours"),
        ("is it free for the next 3 hours", 180, "for the next 3 hours"),
        ("free for the next hour?", 60, "for the next 1 hour"),
        ("any bookings in the next 30 minutes", 30, "for the next 30 minutes"),
    ],
)
def test_next_n_hours_is_a_window_starting_now(q, minutes, label):
    s, e, got = parse_window(q, STORE_NOW)
    assert s == STORE_NOW and (e - s).total_seconds() == minutes * 60 and got == label


def test_the_next_two_hours_are_free_even_when_the_day_is_booked():
    """The live answer was '**Room1.06 is booked today**: 08:20-18:00' at 01:20."""
    adapter = _Adapter([])
    svc = EventQueryService("tb", adapter, ROOMS, tz_name=TZ)
    r = asyncio.run(svc.answer("Is Room1.06 free for the next two hours?", now=STORE_NOW))
    assert r["free"] and "for the next 2 hours" in r["formatted_response"]
    assert "2026-09-15 00:20:00" in adapter.sql[0] and "2026-09-15 02:20:00" in adapter.sql[0]


def test_at_3pm_means_3pm_in_the_building_and_is_queried_in_utc():
    adapter = _Adapter([])
    svc = EventQueryService("tb", adapter, ROOMS, tz_name=TZ)
    asyncio.run(svc.answer("Is Room1.06 free at 3pm?", now=STORE_NOW))
    assert "2026-09-15 14:00:00" in adapter.sql[0] and "2026-09-15 15:00:00" in adapter.sql[0]


def test_today_is_the_buildings_day_not_the_utc_day():
    # 23:30 UTC on the 14th is already 00:30 on the 15th in London.
    adapter = _Adapter([])
    svc = EventQueryService("tb", adapter, ROOMS, tz_name=TZ)
    asyncio.run(svc.answer("show me the bookings for Room1.06 today",
                           now=datetime(2026, 9, 14, 23, 30)))
    assert "2026-09-14 23:00:00" in adapter.sql[0] and "2026-09-15 23:00:00" in adapter.sql[0]


def test_stored_booking_times_are_shown_on_the_buildings_clock():
    booked = _booking(datetime(2026, 9, 15, 7, 20), datetime(2026, 9, 15, 17, 0))
    svc = EventQueryService("tb", _Adapter([booked]), ROOMS, tz_name=TZ)
    r = asyncio.run(svc.answer("Is Room1.06 free today?", now=STORE_NOW))
    assert r["clashes"] == ["08:20–18:00"]


def test_string_timestamps_are_converted_too():
    booked = _booking("2026-09-15 07:20:00", "2026-09-15 17:00:00")
    svc = EventQueryService("tb", _Adapter([booked]), ROOMS, tz_name=TZ)
    r = asyncio.run(svc.answer("show me the bookings for Room1.06 today", now=STORE_NOW))
    assert r["bookings"] == ["- 08:20–18:00"]


def test_no_zone_leaves_behaviour_unchanged():
    booked = _booking(datetime(2026, 9, 15, 7, 20), datetime(2026, 9, 15, 17, 0))
    adapter = _Adapter([booked])
    r = asyncio.run(EventQueryService("tb", adapter, ROOMS).answer(
        "Is Room1.06 free at 3pm?", now=STORE_NOW))
    assert "2026-09-15 15:00:00" in adapter.sql[0]
    assert r["clashes"] == ["07:20–17:00"]


def test_the_orchestrator_hands_the_service_the_buildings_zone():
    import ast
    from pathlib import Path

    tree = ast.parse(Path("orchestrator/workflow/_orchestrator.py").read_text(encoding="utf-8"))
    calls = [n for n in ast.walk(tree) if isinstance(n, ast.Call)
             and getattr(n.func, "id", "") == "EventQueryService"]
    assert calls and all(any(k.arg == "tz_name" for k in c.keywords) for c in calls)


def test_the_recheck_line_shows_local_clock_times_and_a_utc_age():
    from orchestrator.services.evidence.recheck import RecheckAdvice

    advice = RecheckAdvice(
        evidence_time=datetime(2026, 9, 15, 0, 20), recheck_at=datetime(2026, 9, 15, 0, 50),
        horizon_minutes=30, switch_condition="x", modality="co2",
    )
    line = advice.describe(now=datetime(2026, 9, 15, 0, 25), tz_name=TZ)
    assert "01:20 on 15 Sep, 5 minutes ago" in line and "Recheck by **01:50**" in line
    assert "00:20" in advice.describe(now=datetime(2026, 9, 15, 0, 25))  # no zone: unchanged


# BUG-549 — "free" meaning no cost is not a booking question.


@pytest.mark.parametrize(
    "question",
    [
        "Is tap water free somewhere, or do I have to buy bottles?",
        "Is parking free for visitors or do I pay?",
        "is the wifi free to use?",
    ],
)
def test_free_meaning_no_cost_is_not_an_event_question(question):
    from orchestrator.services.event_query_service import classify_event_question
    from orchestrator.services.routing_contract import COST_SENSE_OF_FREE_RE

    assert classify_event_question(question) is None
    assert COST_SENSE_OF_FREE_RE.search(question)  # the guard the contract rule applies


@pytest.mark.parametrize(
    "question", ["Is Room1.06 free at 3pm?", "Is the seminar room booked tomorrow?"]
)
def test_room_availability_is_still_an_event_question(question):
    from orchestrator.services.event_query_service import classify_event_question

    assert classify_event_question(question) in ("availability_check", "bookings_list")


# BUG-558 — reading narration shows the building's clock.


def test_reading_timestamps_reach_the_narration_in_building_time():
    from unittest.mock import AsyncMock, patch

    from orchestrator.agents.sql_agent import SQLAgent

    agent = SQLAgent.__new__(SQLAgent)
    agent._sensor_context = lambda meta: ""
    captured = {}

    async def _gen(prompt, task_type=None):
        captured["prompt"] = prompt
        return "ok"

    rows = [{"timestamp": "2026-09-15T02:20:00", "uuid": "u", "value": 509.0}]
    with patch("orchestrator.agents.sql_agent.llm_manager.generate", new=AsyncMock(side_effect=_gen)), \
         patch("orchestrator.services.requested_interval.building_tz", return_value=TZ):
        asyncio.run(agent._format_results(rows, "co2 now?", "SELECT 1"))
    prompt = captured["prompt"]
    assert "timestamp: 2026-09-15 03:20:00" in prompt and "building local time" in prompt
    assert "never label them UTC" in prompt
