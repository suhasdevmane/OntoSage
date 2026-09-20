# -*- coding: utf-8 -*-
"""Wave 8: the sensor-count refusal is for ONE shape only, and a summary never answers a route.

Measured across seven unseen sets, "That covers all N <quantity> sensors at once, which is too wide
to answer directly" was still the most frequent visible failure. It reached wishes, knowledge
questions and design questions, and it reads as a limit of the system, not as an answer. The size of
the set is an honest reason in exactly one case: the reader asked for the readings sensor by sensor.

1. `too_broad_reply` keeps its sentence for a per-sensor request and gives every other question the
   plain decline: no count, no "too wide", and a way forward.
2. A question whose head is "which exit / study area / room" is not a building-wide summary, even
   when it names a quantity as a constraint ("after dark", "without worse CO2").
3. A "right now" figure is screened against the physical range, so a range printed beside it cannot
   begin at a value the air cannot hold.
"""

from __future__ import annotations

import re
from datetime import datetime
from typing import Any, Callable, Dict, List

import pytest

from orchestrator.services import aggregate_lane as al
from orchestrator.services.aggregate_support import asks_which_place
from orchestrator.services.database_adapter import AdapterType, QueryResult
from orchestrator.services.too_broad_reply import too_broad_reply

pytestmark = pytest.mark.unit

NOW = datetime(2026, 9, 18, 12, 0, 0)

NOT_A_READINGS_ASK = [
    "Can you reduce noise in this workpace?",
    "Not all eyes are the same. How does the Lux sensor find a medium?",
    "With a presentation the light needs to be off. Is there a way to notify the lighting system?",
    "Is my office significantly warmer than comparable offices today once sunlight, occupancy and "
    "outdoor conditions are considered?",
    "could the building proactively notice when harmful materials may be used?",
    "What hours are considered off-peak?",
    "Is there sufficient exhaust ventilation to prevent mold growth?",
    "How can we optimize lighting usage?",
    "show me everything this week",
]

PER_SENSOR = [
    "show me CO2 for every sensor this week",
    "list all temperature readings yesterday",
    "give me the raw data for each sensor",
]


@pytest.mark.parametrize("question", NOT_A_READINGS_ASK)
def test_a_question_that_is_not_a_per_sensor_ask_gets_a_decline_without_a_count(question):
    text = too_broad_reply(question, 233, ["Room 1.01 sound level [dB]"])
    assert "233" not in text and "too wide" not in text and "sensors at once" not in text
    assert text.startswith("I couldn't tie that question to a reading")
    assert "\n" not in text  # one paragraph, no bullets
    for jargon in ("row by row", "summarise", "summarize", "timing out", "fetch budget"):
        assert jargon not in text


@pytest.mark.parametrize("question", PER_SENSOR)
def test_the_per_sensor_refusal_is_kept_exactly(question):
    text = too_broad_reply(question, 233, ["Room 1.01 CO2 level [ppm]"])
    assert "all 233" in text and "too wide to answer directly" in text


def test_the_decline_names_the_quantity_only_when_the_question_does():
    labels = ["Room 4.16 occupancy [persons]"]
    # asked about people: the way forward is about people
    asked = too_broad_reply("is the office busy in the afternoon", 250, labels)
    assert "people" in asked and "250" not in asked
    # the sensors are occupancy sensors but the question is a wish about lighting: never said
    wish = too_broad_reply("How can we optimize lighting usage?", 250, labels)
    assert "occupancy" not in wish and "Room 4.16" not in wish


def test_the_decline_names_no_building_and_no_room_literal():
    text = too_broad_reply("What hours are considered off-peak?", 269, [])
    assert "bldg" not in text.lower() and "Abacws" not in text and "Room " not in text


# ── 2. WHICH place: a constraint is not a summary ────────────────────────────────────────────


@pytest.mark.parametrize(
    "question",
    [
        "The visit ends after dark. Which confirmed public exit and onward route should we use?",
        "I feel cold today. Which student-accessible study area is warmer without showing clearly "
        "worse CO2 or particle levels?",
        "Which room should I book for a quiet meeting?",
        "Which exit is the best lit?",
    ],
)
def test_a_which_place_head_is_recognised(question):
    assert asks_which_place(question) is True


@pytest.mark.parametrize(
    "question",
    [
        "Which floor had the highest CO2 this week?",
        "Which floors are warmest?",
        "Which rooms are hottest?",
        "Which commissioned CO2-monitored zones show sustained elevated CO2 during an approved "
        "occupied period?",
        "Is the air quality good today?",
    ],
)
def test_a_floor_ranking_and_a_plural_grouping_are_not_a_which_place_head(question):
    assert asks_which_place(question) is False


class FakeAdapter:
    adapter_type = AdapterType.MYSQL

    def __init__(self, handler: Callable[[str], List[Dict[str, Any]]]):
        self.table = "co2_data"
        self.handler = handler
        self.sql: List[str] = []

    async def execute_query(self, sql: str) -> QueryResult:
        self.sql.append(sql)
        rows = self.handler(sql)
        return QueryResult(success=True, data=rows, row_count=len(rows), query=sql)


def _uuids_in(sql: str) -> List[str]:
    return re.findall(r"'(sensor-[0-9a-z-]+)'", sql)


STORE = "http://example.org/bldg#co2_data"
META = {
    f"sensor-c{i:02d}-aaaa": {"label": f"CO2 Level Sensor {i}.01", "unit": "ppm", "floor": str(i)}
    for i in range(6)
}
#: one sensor's newest reading is 10 ppm, which no occupied room can hold
NEWEST = {u: (10.0 if i == 0 else 400.0 + 100 * i) for i, u in enumerate(META)}


def handler(sql: str):
    if "JOIN" in sql:
        return [
            {"uuid": u, "value": NEWEST[u], "ts": "2026-09-18 11:58:00"} for u in _uuids_in(sql)
        ]
    return []


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


async def ask(question: str, bands=None):
    return await al.try_answer(
        question=question,
        uuids=list(META),
        storage_map={u: STORE for u in META},
        metadata=META,
        start_date=None,
        end_date=None,
        budget_hit=True,
        tz_name="Europe/London",
        adapter_for=lambda uri: FAKE,
        store_key=lambda uri: "co2_data",
        sparql_exec=sparql_exec,
        now=NOW,
        bands=bands if bands is not None else {},
    )


async def test_a_route_question_that_names_a_quantity_is_not_summarised():
    q = "The visit ends after dark. Which confirmed public exit and onward route should we use?"
    assert await ask(q) is None
    q = "I feel cold today. Which student-accessible study area is warmer without worse CO2?"
    assert await ask(q) is None


async def test_a_plain_quantity_question_is_still_summarised():
    res = await ask("What is the CO2 level across the building right now?")
    assert res is not None and "CO2" in res["formatted_response"]


# ── 3. the physical range applies to "right now" ─────────────────────────────────────────────


def test_a_newest_reading_outside_its_range_is_dropped_and_named():
    latest = [al.SensorLatest(u, v, None) for u, v in NEWEST.items()]
    bands = {u: (350.0, 40000.0) for u in META}
    kept, dropped = al.drop_out_of_band(latest, bands)
    assert dropped == {"sensor-c00-aaaa"} and len(kept) == 5
    kept, dropped = al.drop_out_of_band(latest, {})
    assert not dropped and len(kept) == 6  # no declared band, nothing is invented


async def test_the_printed_range_never_begins_below_the_declared_band():
    bands = {u: (350.0, 40000.0) for u in META}
    res = await ask("What is the CO2 level across the building right now?", bands=bands)
    assert res is not None
    text = res["formatted_response"]
    assert "10 to" not in text and "from 10 " not in text
    assert "outside the physically possible range" in text and "350" in text
    without = await ask("What is the CO2 level across the building right now?", bands={})
    assert without is not None  # with no band declared the reading stands, as before
