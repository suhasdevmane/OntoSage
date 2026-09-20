# -*- coding: utf-8 -*-
"""Wave 5: four shapes the bare-measurand summary still mishandled on the held-out read.

    "Rooms temperature?"                      -> refused as "all 240 temperature sensors"
    "...when are CO2 or temperature most likely to worsen enough for the lecturer to consider a
     short break?"                             -> refused as "all 296 sensors"
    "My appointment is in 30 minutes. Where can I wait nearby in a quiet, uncrowded ... area?"
                                               -> not a readings question at all
    "How many people can this building hold at one time?"
                                               -> capacity, a property of a space, not a reading

What is pinned here, in the order the risks run:

1. A plural place noun on its own is a GROUPING word, never a place.
2. A "when will it worsen" question is answered by the hourly profile: the store groups each
   sensor's readings by hour of the day; nothing is predicted and no hour is called high or low.
3. "Where can I wait / work / relax" and "how many people can it hold" and "capacity" are not
   readings questions, so the lane declines to claim them and the workspace/capability lanes can.
4. The guards from wave 4 survive: per-sensor detail still refuses, a named place stays local.
5. A stated figure outside its stated range is never printed, on every path that prints a mean.
"""

from __future__ import annotations

import re
from datetime import datetime
from typing import Any, Callable, Dict, List

import pytest

from orchestrator.services import aggregate_lane as al
from orchestrator.services import aggregate_profile as prof
from orchestrator.services.aggregate_support import (
    asks_for_per_sensor_detail,
    asks_for_time_pattern,
    is_readings_question,
    names_a_place,
)
from orchestrator.services.database_adapter import AdapterType, QueryResult

pytestmark = pytest.mark.unit

NOW = datetime(2026, 9, 18, 12, 0, 0)
TZ = "Europe/London"
STORE = "http://example.org/bldg#temperature_data"

Q_ROOMS = "Rooms temperature?"
Q_FLOORS = "floors CO2?"
Q_CLASS = (
    "During our three-hour class, when are CO2 or temperature most likely to worsen enough for the "
    "lecturer to consider a short break?"
)
Q_WAIT = (
    "My appointment is in 30 minutes. Where can I wait nearby in a quiet, uncrowded "
    "student-accessible area with reasonable measured conditions?"
)
Q_CAPACITY = "How many people can this building hold at one time?"


class FakeAdapter:
    adapter_type = AdapterType.MYSQL

    def __init__(self, handler: Callable[[str], List[Dict[str, Any]]]):
        self.table = "temperature_data"
        self.handler = handler
        self.sql: List[str] = []

    async def execute_query(self, sql: str) -> QueryResult:
        self.sql.append(sql)
        rows = self.handler(sql)
        return QueryResult(success=True, data=rows, row_count=len(rows), query=sql)


def _uuids_in(sql: str) -> List[str]:
    return re.findall(r"'(sensor-[0-9a-z-]+)'", sql)


META = {
    f"sensor-t{i:02d}-aaaa": {
        "label": f"Air Temperature Sensor {i % 6}.0{i}",
        "unit": "°C",
        "floor": str(i % 6),
    }
    for i in range(12)
}


def handler(sql: str):
    if "HOUR(`datetime`) AS h" in sql:
        rows = []
        for u in _uuids_in(sql):
            for h in range(24):  # UTC hours; warmest at 16 UTC, coolest at 04 UTC
                mean = 22.0 + 2.0 * (1 - abs(h - 16) / 12 if abs(h - 16) <= 12 else 0.0)
                rows.append(
                    {
                        "uuid": u,
                        "h": h,
                        "n": 40,
                        "sm": mean * 40,
                        "mn": mean - 1.0,
                        "mx": mean + 1.5,
                    }
                )
        return rows
    if "MIN(`datetime`) AS ts" in sql:
        return [{"ts": "2026-09-16 09:15:00"}]
    if "JOIN" in sql:
        return [{"uuid": u, "value": 21.0, "ts": "2026-09-18 11:58:00"} for u in _uuids_in(sql)]
    return [
        {
            "uuid": u,
            "n": 100,
            "mn": 18.0,
            "mx": 26.0,
            "sm": 2200.0,
            "ex": 0,
            "bad": 0,
            "t0": "2026-09-14 00:00:00",
            "t1": "2026-09-18 11:55:00",
        }
        for u in _uuids_in(sql)
    ]


FAKE = FakeAdapter(handler)


async def sparql_exec(query: str) -> Dict[str, Any]:
    if "SELECT DISTINCT ?floorNum" in query and "VALUES" not in query:
        return {"results": {"bindings": [{"floorNum": {"value": str(f)}} for f in range(6)]}}
    binds = [
        {
            "uuid": {"value": u},
            "locLabel": {"value": f"Room {m['floor']}.01"},
            "floorNum": {"value": m["floor"]},
            "onFloor": {"value": "false"},
        }
        for u, m in META.items()
        if f'"{u}"' in query
    ]
    return {"results": {"bindings": binds}}


async def ask(question: str, meta=None, **kw):
    meta = META if meta is None else meta
    args = dict(
        question=question,
        uuids=list(meta),
        storage_map={u: STORE for u in meta},
        metadata=meta,
        start_date=None,
        end_date=None,
        budget_hit=True,
        tz_name=TZ,
        adapter_for=lambda uri: FAKE,
        store_key=lambda uri: "temperature_data",
        sparql_exec=sparql_exec,
        now=NOW,
        bands={},
    )
    args.update(kw)
    return await al.try_answer(**args)


# ── 1. a plural place noun on its own is a grouping word ─────────────────────────────────────


@pytest.mark.parametrize(
    "question",
    [
        Q_ROOMS,
        Q_FLOORS,
        "zones CO2?",
        "What is the temperature in every room?",
        "What is the temperature in the rooms?",
        "temperature in each room",
        "Which rooms are hottest?",
    ],
)
def test_a_plural_or_collective_place_noun_is_not_a_named_place(question):
    assert names_a_place(question) is False


@pytest.mark.parametrize(
    "question",
    [
        "What is the temperature in room 5.01?",
        "CO2 in the atrium",
        "When is the atrium busiest?",
        "temperature on floor 3",
        "how warm is the library",
    ],
)
def test_a_specific_place_is_still_a_place(question):
    assert names_a_place(question) is True


async def test_a_bare_plural_place_and_quantity_is_summarised():
    res = await ask(Q_ROOMS)
    assert res is not None and "Across the building" in res["formatted_response"]
    co2 = {
        u: {**m, "label": m["label"].replace("Air Temperature", "CO2 Level"), "unit": "ppm"}
        for u, m in META.items()
    }
    res = await ask(Q_FLOORS, meta=co2)
    assert res is not None and "Across the building" in res["formatted_response"]


# ── 2. WHEN it worsens: the hourly profile ───────────────────────────────────────────────────


@pytest.mark.parametrize(
    "question",
    [
        Q_CLASS,
        "What time of day is it hottest?",
        "which hours is the CO2 highest?",
        "when does the temperature peak?",
    ],
)
def test_a_time_of_day_question_is_recognised(question):
    assert asks_for_time_pattern(question) is True


@pytest.mark.parametrize("question", [Q_ROOMS, "Which floor is warmest?", Q_WAIT])
def test_an_ordinary_question_is_not_a_time_of_day_question(question):
    assert asks_for_time_pattern(question) is False


async def test_the_class_question_gets_the_hourly_profile():
    res = await ask(Q_CLASS)
    text = res["formatted_response"]
    assert res["aggregate"]["stat"] == "profile"
    assert text.startswith("**Temperature usually runs highest around 17:00")  # 16 UTC = 17 BST
    assert "lowest around 05:00" in text  # 04 UTC
    assert "| Hours (building time) |" in text and "grouped by hour of the day in the store" in text


async def test_the_profile_is_computed_in_the_store_and_reads_no_rows():
    FAKE.sql.clear()
    await ask(Q_CLASS)
    assert FAKE.sql
    for sql in FAKE.sql:
        assert "GROUP BY" in sql and "HOUR(" in sql, sql


async def test_the_profile_predicts_nothing_and_calls_no_hour_high_or_low():
    text = (await ask(Q_CLASS))["formatted_response"]
    assert "does not predict a particular day" in text
    assert "does not call any hour high or low against a limit" in text
    for verdict in ("will worsen", "you should", "take a break", "unsafe", "too high"):
        assert verdict not in text.lower()


async def test_a_pattern_is_taken_over_several_days_not_the_class_afternoon():
    """A window shorter than three days would give one reading per hour: one day's weather."""
    res = await ask(Q_CLASS, start_date="2026-09-18 09:00:00", end_date="2026-09-18 12:00:00")
    assert res["aggregate"]["window"]["start"] == "2026-09-11 12:00:00"  # seven days back


async def test_the_hour_is_shown_in_building_time_not_store_time():
    text = (await ask(Q_CLASS))["formatted_response"]
    assert "17:00" in text and "16:00" not in text.split("highest around")[1][:8]


async def test_a_headcount_profile_is_never_built_from_room_counters():
    """A mean of counters is not a headcount. Since wave 7 a headcount profile IS answered, but
    only from the floor counters; with none to be found the lane says nothing rather than
    average rooms."""
    meta = {
        u: {"label": f"Room {i}.01 occupancy [persons]", "unit": "people", "floor": str(i % 6)}
        for i, u in enumerate(META)
    }

    async def no_floor_counters(query: str):
        if "VALUES ?seed" in query:
            return {"results": {"bindings": []}}
        return await sparql_exec(query)

    assert (
        await ask("when is the building busiest?", meta=meta, sparql_exec=no_floor_counters) is None
    )


# ── 3. not readings questions: decline so the register can have them ─────────────────────────


@pytest.mark.parametrize("question", [Q_WAIT, Q_CAPACITY])
def test_the_two_held_out_questions_are_not_readings_questions(question):
    assert is_readings_question(question) is False


@pytest.mark.parametrize(
    "question",
    [
        "Where can I work quietly this afternoon?",
        "where can we meet before the lecture?",
        "Where could I relax between classes?",
        "How many students can the lecture theatre seat?",
        "How many people can fit in the atrium?",
        "What is the capacity of this building?",
        "What is the maximum occupancy?",
        "I have an appointment at 3, where do I go?",
        "Is there somewhere nearby to sit?",
    ],
)
def test_capacity_and_where_can_i_questions_are_not_readings_questions(question):
    assert is_readings_question(question) is False


@pytest.mark.parametrize(
    "question",
    [
        "How many people are in the building right now?",
        "Is the building noisy?",
        "What is the temperature like?",
        "how does the building prevent overheating in sun exposed areas?",
        "Which floor has the most people?",
    ],
)
def test_a_genuine_readings_question_is_still_a_readings_question(question):
    assert is_readings_question(question) is True


@pytest.mark.parametrize("question", [Q_WAIT, Q_CAPACITY])
async def test_the_lane_declines_to_claim_them(question):
    meta = {
        u: {"label": f"Room {i}.01 occupancy [persons]", "unit": "people", "floor": str(i % 6)}
        for i, u in enumerate(META)
    }
    assert await ask(question, meta=meta) is None
    assert await ask(question) is None


# ── 4. the wave-4 guards survive ─────────────────────────────────────────────────────────────


@pytest.mark.parametrize(
    "question",
    [
        "Show me CO2 for every sensor this week.",
        "list every temperature reading yesterday",
        "sensor by sensor, what is the temperature?",
    ],
)
async def test_per_sensor_detail_still_refuses(question):
    assert asks_for_per_sensor_detail(question) is True
    assert await ask(question) is None


@pytest.mark.parametrize(
    "question",
    [
        "Plot temperature for the last 24 hours in the atrium.",
        "What is the temperature in room 5.01?",
        "When is the atrium busiest?",
        "when does the temperature peak in the library?",
    ],
)
async def test_a_named_place_stays_local(question):
    assert await ask(question) is None


# ── 5. a figure outside its own range is never printed ───────────────────────────────────────


def test_an_hourly_mean_outside_its_own_readings_is_detected():
    ok = {9: prof.HourStat(9, n=10, total=200.0, low=19.0, high=21.0)}
    bad = {9: prof.HourStat(9, n=10, total=100.0, low=19.0, high=21.0)}  # mean 10, min 19
    assert prof.inside_range(ok) is True
    assert prof.inside_range(bad) is False


async def test_a_profile_whose_hourly_mean_is_impossible_is_never_printed():
    def broken(sql: str):
        rows = handler(sql)
        for r in rows:
            if "sm" in r:
                r["sm"] = 5.0 * r["n"]  # a mean of 5 against readings that never fall below 21
        return rows

    adapter = FakeAdapter(broken)
    res = await ask(Q_CLASS, adapter_for=lambda uri: adapter)
    assert res is None


def test_a_group_mean_outside_its_own_range_is_never_accepted():
    good = al.GroupStat("1", sensors=2, readings=10, mean=20.0, low=18.0, high=22.0, total=200.0)
    bad = al.GroupStat("2", sensors=2, readings=10, mean=39.4, low=45.0, high=105.0, total=394.0)
    assert al._means_inside_ranges([good]) is True
    assert al._means_inside_ranges([good, bad]) is False


async def test_a_ranking_of_means_is_withheld_when_a_mean_disagrees_with_its_range():
    def inconsistent(sql: str):
        rows = handler(sql)
        for r in rows:
            if "sm" in r and "mn" in r:
                r["sm"] = 3940.0  # 100 readings averaging 39.4 against a minimum of 18
        return rows

    adapter = FakeAdapter(inconsistent)
    res = await ask(
        "Which floor had the highest average temperature this week?",
        adapter_for=lambda uri: adapter,
    )
    assert res is None
