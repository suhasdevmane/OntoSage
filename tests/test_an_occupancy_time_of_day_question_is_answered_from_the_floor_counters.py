# -*- coding: utf-8 -*-
"""Wave 7: the occupancy time-of-day question, and the rule that stopped wrong-quantity answers.

"My shared office is usually busy after lunch. What is the best remaining time today for
uninterrupted desk work?" was refused as "That covers all 233 occupancy sensors at once". Two
things are true of it at once. It is a time-of-day question about occupancy, which the hourly
profile answers. And it must NOT be answered from a mean over room counters: a mean of counters is
not a headcount. The floor counters are (one per floor, the same source "how many people are in the
building" uses), and a building's headcount at an hour is the SUM of the floors' own averages at
that hour, never the average over all readings, which is one floor's worth and six times too small.

It also pins the second half of the wave: the question and the sensors must agree on the quantity,
and every recorded question that reached the breadth refusal is classified, so a change to the
boundary is visible as a change in a table rather than as a live surprise.
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
    names_a_possessive_place,
)
from orchestrator.services.database_adapter import AdapterType, QueryResult

pytestmark = pytest.mark.unit

NOW = datetime(2026, 9, 18, 12, 0, 0)  # 13:00 in the building (BST)
TZ = "Europe/London"
STORE = "http://example.org/bldg#occupancy_data"

Q_OFFICE = (
    "My shared office is usually busy after lunch. What is the best remaining time today for "
    "uninterrupted desk work?"
)


class FakeAdapter:
    adapter_type = AdapterType.MYSQL

    def __init__(self, handler: Callable[[str], List[Dict[str, Any]]]):
        self.table = "occupancy_data"
        self.handler = handler
        self.sql: List[str] = []

    async def execute_query(self, sql: str) -> QueryResult:
        self.sql.append(sql)
        rows = self.handler(sql)
        return QueryResult(success=True, data=rows, row_count=len(rows), query=sql)


def _uuids_in(sql: str) -> List[str]:
    return re.findall(r"'(sensor-[0-9a-z-]+)'", sql)


COUNTERS = {f"sensor-fl{f}-counter": str(f) for f in range(6)}
ROOMS = {f"sensor-rm{i:02d}-aaaa": str(i % 6) for i in range(12)}
META = {
    **{
        u: {"label": f"Room {f}.0{i} occupancy [persons]", "unit": "people", "floor": f}
        for i, (u, f) in enumerate(ROOMS.items())
    },
    # 243 of the 499 series in the real store are 0/1 status flags, bound together with the counts
    **{
        f"sensor-st{i:02d}-aaaa": {
            "label": f"Room {i % 6}.9{i} occupancy_status",
            "unit": "",
            "floor": str(i % 6),
        }
        for i in range(6)
    },
}


def _floor_mean(hour_utc: int) -> float:
    """A floor's typical headcount: quiet at night, busiest at 13 UTC (14:00 BST)."""
    return max(0.0, 5.0 - abs(hour_utc - 13) * 0.6)


def handler(sql: str):
    if "HOUR(`datetime`) AS h" in sql:
        rows = []
        for u in _uuids_in(sql):
            for h in range(24):
                m = _floor_mean(h)
                rows.append(
                    {"uuid": u, "h": h, "n": 20, "sm": m * 20, "mn": max(0.0, m - 1), "mx": m + 2}
                )
        return rows
    if "JOIN" in sql:
        return [{"uuid": u, "value": 4.0, "ts": "2026-09-18 11:58:00"} for u in _uuids_in(sql)]
    return []


FAKE = FakeAdapter(handler)


async def sparql_exec(query: str) -> Dict[str, Any]:
    if "VALUES ?seed" in query:
        return {
            "results": {
                "bindings": [
                    {
                        "uuid": {"value": u},
                        "storage": {"value": STORE},
                        "floorNum": {"value": f},
                        "label": {"value": f"Occupancy Count Sensor - Floor {f}"},
                    }
                    for u, f in COUNTERS.items()
                ]
            }
        }
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
        store_key=lambda uri: "occupancy_data",
        sparql_exec=sparql_exec,
        now=NOW,
        bands={},
    )
    args.update(kw)
    return await al.try_answer(**args)


# ── the question ─────────────────────────────────────────────────────────────────────────────


def test_the_office_question_is_a_time_of_day_question_about_the_reader_own_space():
    assert asks_for_time_pattern(Q_OFFICE) is True
    assert names_a_possessive_place(Q_OFFICE) is True
    assert names_a_place(Q_OFFICE) is False, "a possessive space is a note, not a reason to refuse"
    assert is_readings_question(Q_OFFICE) is True
    assert al.question_asks_about(Q_OFFICE, "occupancy") is True


async def test_it_is_answered_from_the_floor_counters_summed_across_floors():
    res = await ask(Q_OFFICE)
    text = res["formatted_response"]
    assert res["aggregate"]["stat"] == "profile"
    # busiest 13 UTC = 14:00 building time; six floors of 5.0 each
    assert text.startswith("**The building is typically busiest around 14:00 (about 30 people)")
    assert "Based on the building's 6 floor counters" in text
    assert "The room-level counters are not added to it" in text


async def test_the_building_figure_is_a_sum_of_floors_not_the_average_floor():
    """Averaging all readings would print about 5, one floor's worth."""
    text = (await ask(Q_OFFICE))["formatted_response"]
    peak = int(re.search(r"about (\d+) people\) and quietest", text).group(1))
    assert peak == 30


async def test_room_counters_and_status_flags_never_reach_the_store():
    FAKE.sql.clear()
    await ask(Q_OFFICE)
    joined = " ".join(FAKE.sql)
    assert FAKE.sql and not any(u in joined for u in ROOMS)
    assert not any(f"sensor-st{i:02d}" in joined for i in range(6))
    assert all(u in joined for u in COUNTERS)


async def test_it_is_a_typical_pattern_and_never_a_prediction_for_today():
    text = (await ask(Q_OFFICE))["formatted_response"]
    assert "typical for the recent days" in text
    assert "does not predict today" in text
    for promise in ("you should", "will be quiet", "guarantee"):
        assert promise not in text.lower()


async def test_the_quietest_later_today_is_among_the_hours_the_building_is_in_use():
    """Without that, "the best remaining time" is 03:00, which answers nothing."""
    text = (await ask(Q_OFFICE))["formatted_response"]
    later = re.search(
        r"Later today \(after (\d\d):00\), among the hours when the building is "
        r"typically in use \(at least a quarter of its usual peak\), the quietest are "
        r"([^.]*)\.",
        text,
    )
    assert later, text
    assert later.group(1) == "13"
    hours = [int(h) for h in re.findall(r"(\d\d):00 \(about", later.group(2))]
    assert hours and all(h > 13 for h in hours)
    assert not any(h in (0, 1, 2, 3, 4) for h in hours), "small hours are not desk-work hours"


async def test_the_whole_building_note_is_present_because_the_office_was_named():
    text = (await ask(Q_OFFICE))["formatted_response"]
    assert (
        "These figures are for the whole building; I can't tell which of its spaces is yours"
        in text
    )


async def test_without_a_possessive_space_there_is_no_such_note():
    text = (await ask("When is the building busiest?"))["formatted_response"]
    assert "whole building; I can't tell" not in text


async def test_with_fewer_than_two_floor_counters_it_says_nothing_rather_than_sum_rooms():
    async def none_found(query: str) -> Dict[str, Any]:
        if "VALUES ?seed" in query:
            return {"results": {"bindings": []}}
        return await sparql_exec(query)

    assert await ask(Q_OFFICE, sparql_exec=none_found) is None


def test_a_floor_missing_an_hour_drops_that_hour_instead_of_summing_five_floors():
    rows = []
    for f in range(6):
        for h in range(24):
            if f == 5 and h == 9:
                continue  # one floor has no reading at 09
            rows.append(prof.HourRow(f"c{f}", h, 10, 50.0, 3.0, 8.0))
    hours = prof.combine_floor_counters(rows, {f"c{f}": str(f) for f in range(6)}, 0)
    assert 9 not in hours and 10 in hours
    assert hours[10].mean == pytest.approx(30.0)


def test_the_headcount_invariant_holds_and_a_broken_one_is_detected():
    ok = prof.combine_floor_counters(
        [prof.HourRow("c0", 3, 10, 50.0, 3.0, 8.0), prof.HourRow("c1", 3, 10, 60.0, 4.0, 9.0)],
        {"c0": "0", "c1": "1"},
        0,
    )
    assert prof.inside_range(ok) is True
    broken = {3: prof.HourStat(3, n=1, total=99.0, low=1.0, high=10.0)}
    assert prof.inside_range(broken) is False


# ── the question and the sensors must agree ──────────────────────────────────────────────────


@pytest.mark.parametrize(
    "question, measurand, expected",
    [
        ("Is the building busy?", "occupancy", True),
        ("Is the building busy?", "temperature", False),  # a busy question, temperature sensors
        ("Rooms temperature?", "temperature", True),
        ("Rooms temperature?", "co2", False),
        ("Is the air quality good today?", "co2", True),  # air quality is answered by CO2 sensors
        ("Is the air quality good today?", "pm25", True),
        ("Is the air quality good today?", "temperature", False),
        ("felt hot and stuffy", "temperature", True),
        ("felt hot and stuffy", "co2", True),  # two quantities, both the question's own
        ("during an approved occupied period, is CO2 high?", "occupancy", False),
        ("during an approved occupied period, is CO2 high?", "co2", True),
        ("Is the ambient light sufficient?", "illuminance", True),
        (
            "which approved paths have abnormal latency, jitter or packet loss?",
            "temperature",
            False,
        ),
    ],
)
def test_the_sensors_quantity_must_be_one_the_question_is_about(question, measurand, expected):
    assert al.question_asks_about(question, measurand) is expected


async def test_a_busy_question_is_never_answered_with_a_temperature_summary():
    temp = {
        u: {"label": f"Air Temperature Sensor {i}.01", "unit": "°C", "floor": str(i % 6)}
        for i, u in enumerate(ROOMS)
    }
    assert await ask("Is the building busy right now?", meta=temp) is None


# ── every recorded question that reached the breadth refusal, classified ─────────────────────

#: (question, what the lane must do). Read from docs/phase0/*.jsonl: the 27 distinct questions that
#: were answered with the breadth refusal in development runs. The point of the table is that
#: moving the boundary shows up here, in one place, as a diff.
CLASSIFIED = [
    # could summarise (answered)
    (
        "Last week's class felt hot and stuffy. What did the measurements show, and which "
        "contributing factors are best supported by the evidence?",
        "summarise",
    ),
    ("how does the building prevent overheating in sun exposed areas?", "summarise"),
    (Q_OFFICE, "summarise"),
    ("Is the ambient light sufficient?", "summarise"),
    # not a readings question (declined so another lane can have it)
    (
        "How can a system distinguish between constant background hum and sudden Noise Events?",
        "not readings",
    ),
    ("How can occupancy sensors lead to more efficient use?", "not readings"),
    ("Can temperature or humidity affect the CO2 sensor?", "not readings"),
    ("what happens if temperature spikes?", "not readings"),
    ("Which floor will have the highest CO2 tomorrow?", "not readings"),
    ("What lux level is maintained for reading tasks?", "not readings"),
    (
        "What defensible aggregate occupancy range applied to each affected zone at the incident "
        "start time?",
        "not readings",
    ),
    (
        "Which remaining period today has the best supported balance of temperature, ventilation, "
        "light and quiet for c",
        "not readings",
    ),
    (
        "Which zones are recovering from setback more slowly than their own recent verified "
        "warm-up or cool-down patterns?",
        "not readings",
    ),
    (
        "Which zones have not stabilised after the approved warm-up or cool-down period should "
        "have completed?",
        "not readings",
    ),
    (
        "Will clock drift, time-zone settings or a daylight-saving transition change any active "
        "or scheduled access window?",
        "not readings",
    ),
    (
        "I may need medication or a private well-being break. What official support or suitable "
        "visitor space is available?",
        "not readings",
    ),
    (
        "Which approved nearby space is suitable for a brief quiet pause before my next "
        "appointment?",
        "not readings",
    ),
    # a place the lane cannot resolve, or per-sensor detail: the refusal survives
    ("Show me CO2 for every sensor this week.", "per sensor"),
    ("Plot CO2 for the last 24 hours in the atrium.", "place"),
    ("Is the temperature the same across the space?", "place"),
    (
        "The previous class has just ended. Are CO2 and temperature back near this room's usual "
        "pre-class levels?",
        "place",
    ),
    # names no quantity of its own
    ("Is there sufficient exhaust ventilation to prevent mold growth?", "no quantity"),
    (
        "How many free-cooling hours did we capture last month versus what was available?",
        "no quantity",
    ),
]


def _classify(q: str) -> str:
    if asks_for_per_sensor_detail(q):
        return "per sensor"
    if not is_readings_question(q):
        return "not readings"
    if names_a_place(q):
        return "place"
    if not al.question_names_a_quantity(q):
        return "no quantity"
    return "summarise"


@pytest.mark.parametrize("question, expected", CLASSIFIED)
def test_each_recorded_refusal_is_classified_as_intended(question, expected):
    assert _classify(question) == expected


def test_the_classification_counts():
    from collections import Counter

    counts = Counter(_classify(q) for q, _ in CLASSIFIED)
    assert counts["summarise"] == 4 and counts["not readings"] == 13
    assert counts["per sensor"] == 1 and counts["place"] == 3 and counts["no quantity"] == 2
