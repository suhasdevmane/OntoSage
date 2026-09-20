# -*- coding: utf-8 -*-
"""A question naming a quantity and no place gets a summary, not the breadth refusal (wave 4).

On a hand read of 62 unseen stakeholder questions, five of the 24 unacceptable answers were this
lane's refusal firing on a question that named a measurand and no place:

    "how does the building prevent overheating in sun exposed areas?"
        -> "That covers all 288 temperature sensors at once..."
    "Last week's class felt hot and stuffy. What did the measurements show...?"
        -> the same, 288 sensors
    "Which commissioned CO2-monitored zones show sustained elevated CO2 during an approved
     occupied period?"  -> the same, 280 sensors

None of those needed every reading. The store computes a per-floor summary in one pass, and that
is nearer the question than a refusal. The last one was refused for a second reason worth naming:
it parses as an exceedance question but names no PERIOD, so the window resolved to None.

THE BOUNDARY, which is the whole risk of this change. Claiming too much is worse than refusing,
because three kinds of question must still reach other lanes:

* a question naming a SPECIFIC place ("in the atrium") — a building-wide summary answers a
  different question, and the place not resolving is the thing to fix;
* a request for the readings SENSOR BY SENSOR — the one shape the refusal is still right for;
* a question about what the building PROVIDES, or how a technique works in general — the
  well-being break and the background-hum question, which belong to capability and knowledge.
"""

from __future__ import annotations

import re
from datetime import datetime
from typing import Any, Callable, Dict, List

import pytest

from orchestrator.services import aggregate_lane as al
from orchestrator.services.aggregate_support import (
    asks_for_per_sensor_detail,
    is_readings_question,
    names_a_place,
)
from orchestrator.services.database_adapter import AdapterType, QueryResult

pytestmark = pytest.mark.unit

NOW = datetime(2026, 9, 18, 12, 0, 0)
TZ = "Europe/London"
STORE = "http://example.org/bldg#co2_data"

# the five live questions, verbatim
Q_ZONES = (
    "Which commissioned CO2-monitored zones show sustained elevated CO2 during an approved "
    "occupied period?"
)
Q_OVERHEAT = "how does the building prevent overheating in sun exposed areas?"
Q_CLASS = (
    "Last week's class felt hot and stuffy. What did the measurements show, and which "
    "contributing factors are best supported by the evidence?"
)
Q_WELLBEING = (
    "I may need medication or a private well-being break. What official support or suitable "
    "visitor space is available?"
)
Q_HUM = "How can a system distinguish between constant background hum and sudden Noise Events?"


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


META = {
    f"sensor-t{i:02d}-aaaa": {
        "label": f"Air Temperature Sensor {i % 6}.0{i}",
        "unit": "°C",
        "floor": str(i % 6),
    }
    for i in range(12)
}
SMAP = {u: STORE for u in META}


def handler(sql: str):
    if "MIN(`datetime`) AS ts" in sql:
        return [{"ts": "2026-09-16 09:15:00"}]
    if "AS ts" in sql and "JOIN" in sql:  # the latest-reading read
        return [
            {"uuid": u, "value": 20.0 + i, "ts": "2026-09-18 11:58:00"}
            for i, u in enumerate(_uuids_in(sql))
        ]
    return [
        {
            "uuid": u,
            "n": 100,
            "mn": 18.0 + i,
            "mx": 24.0 + i,
            "sm": 2100.0 + i * 100,
            "ex": 0,
            "bad": 0,
            "t0": "2026-09-14 00:00:00",
            "t1": "2026-09-18 11:55:00",
        }
        for i, u in enumerate(_uuids_in(sql))
    ]


def sparql_exec_factory(floors=("0", "1", "2", "3", "4", "5")):
    async def run(query: str) -> Dict[str, Any]:
        if "VALUES ?seed" in query:
            return {"results": {"bindings": []}}
        if "SELECT DISTINCT ?floorNum" in query and "VALUES" not in query:
            return {"results": {"bindings": [{"floorNum": {"value": f}} for f in floors]}}
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

    return run


async def ask(question: str, **kw):
    args = dict(
        question=question,
        uuids=list(META),
        storage_map=SMAP,
        metadata=META,
        start_date=None,
        end_date=None,
        budget_hit=True,
        tz_name=TZ,
        adapter_for=lambda uri: FAKE,
        store_key=lambda uri: "co2_data",
        sparql_exec=sparql_exec_factory(),
        now=NOW,
        bands={},
    )
    args.update(kw)
    return await al.try_answer(**args)


FAKE = FakeAdapter(handler)


# ── the boundary, stated as three predicates ─────────────────────────────────────────────────


@pytest.mark.parametrize(
    "question, place, per_sensor, readings",
    [
        (Q_ZONES, False, False, True),
        (Q_OVERHEAT, False, False, True),
        (Q_CLASS, False, False, True),
        (Q_WELLBEING, False, False, False),  # asks what is provided
        (Q_HUM, False, False, False),  # asks how a technique works
        ("Show me CO2 for every sensor this week.", False, True, True),
        ("Plot CO2 for the last 24 hours in the atrium.", True, False, True),
        ("What is the temperature in room 5.01?", True, False, True),
        ("list every temperature reading yesterday", False, True, True),
        ("Is there a quiet room available?", False, False, False),
        ("What is the policy on opening windows?", False, False, False),
        ("sensor by sensor, what is the CO2?", False, True, True),
    ],
)
def test_the_boundary_predicates_agree_with_the_hand_read(question, place, per_sensor, readings):
    assert names_a_place(question) is place
    assert asks_for_per_sensor_detail(question) is per_sensor
    assert is_readings_question(question) is readings


def test_a_grouping_word_is_not_a_named_place():
    """ "Which zones show elevated CO2" groups by zone; it does not name one."""
    assert names_a_place("Which zones show elevated CO2?") is False
    assert names_a_place("Which floor is warmest?") is False
    assert names_a_place("what is the CO2 in zone 5.01") is True


def test_the_generic_method_rule_does_not_catch_a_question_about_this_building():
    """ "How does the building prevent overheating" is about this building, so its data counts."""
    assert is_readings_question("how does the building prevent overheating?") is True
    assert is_readings_question("How can a sensor tell one from the other?") is False


# ── what the lane now does with them ─────────────────────────────────────────────────────────


CO2_META = {
    u: {"label": m["label"].replace("Air Temperature", "CO2 Level"), "unit": "ppm", "floor": m["floor"]}
    for u, m in META.items()
}


@pytest.mark.parametrize("question", [Q_OVERHEAT, Q_CLASS])
async def test_the_temperature_refusals_now_get_a_summary(question):
    res = await ask(question)
    assert res is not None, "this question was answered with the breadth refusal live"
    text = res["formatted_response"]
    assert "Across the building" in text and "| Floor 0 |" in text
    assert "too wide to answer directly" not in text
    assert "Based on 12 temperature sensors on 6 floors" in text


async def test_the_co2_refusal_now_gets_a_summary():
    res = await ask(Q_ZONES, metadata=CO2_META)
    assert res is not None and "Based on 12 CO2 sensors on 6 floors" in res["formatted_response"]


async def test_a_question_about_one_quantity_is_never_answered_with_another():
    """The sensors bound are whatever retrieval found; the quantity is the question's own."""
    assert await ask(Q_ZONES) is None  # asks about CO2; the bound sensors are temperature


@pytest.mark.parametrize("question", [Q_WELLBEING, Q_HUM])
async def test_a_question_that_is_not_about_readings_is_left_for_another_lane(question):
    assert await ask(question) is None


@pytest.mark.parametrize(
    "question",
    [
        "Show me CO2 for every sensor this week.",
        "list every temperature reading yesterday",
        "What is the temperature in room 5.01?",
        "Plot CO2 for the last 24 hours in the atrium.",
    ],
)
async def test_the_per_sensor_refusal_and_the_named_place_survive(question):
    assert await ask(question) is None


async def test_the_summary_states_its_boundary_and_claims_no_verdict():
    text = (await ask(Q_OVERHEAT))["formatted_response"]
    assert "each sensor's newest reading" in text
    for verdict in ("too high", "exceeds", "compliant", "unsafe", "acceptable"):
        assert verdict not in text.lower()


async def test_a_question_naming_a_period_is_summarised_over_that_period():
    """ "Last week's class" must select last week, not the default window."""
    text = (await ask(Q_CLASS))["formatted_response"]
    assert "Mon 07 Sep 00:00 to Sun 13 Sep 23:59 (building time)" in text
    assert "averaged" in text  # a window, not a live reading


async def test_a_question_naming_no_period_is_summarised_as_now():
    text = (await ask(Q_ZONES, metadata=CO2_META))["formatted_response"]
    assert "the newest reading from each sensor" in text
    assert "is averaging" in text


async def test_the_summary_never_reads_rows_one_by_one():
    FAKE.sql.clear()
    await ask(Q_OVERHEAT)
    assert FAKE.sql
    for sql in FAKE.sql:
        assert "GROUP BY" in sql or "JOIN" in sql or "MIN(`datetime`) AS ts" in sql


async def test_a_question_with_no_measurand_at_all_is_not_claimed():
    """Nothing to summarise: the lane must not invent a quantity from an unrelated question."""
    meta = {u: {**m, "label": "Unlabelled series", "unit": ""} for u, m in META.items()}
    assert await ask("Where is the nearest lift?", metadata=meta) is None


async def test_the_summary_is_marked_so_no_later_lane_rewrites_it():
    res = await ask(Q_OVERHEAT)
    assert res["aggregate_lane"] is True and res["analytics_required"] is False
    assert res["aggregate"]["stat"] == "summary"


# ── the lead figure and the range must describe ONE population ────────────────────────────────
#
# Live on the held-out run: "**Across the building air quality averaged 39.4 level**, ranging from
# 45 to 105 level." A mean below its own minimum is checked by eye in a second, and it discredits
# every other number in the answer. Two causes, both fixed: the building figure was an UNWEIGHTED
# mean of the floor means (one floor here carries 341 sensors, another 20) while the range came
# from the readings; and nothing checked the two against each other before printing.


def _sum_count_rows(spec):
    """A store that answers with a sum and a count, as MySQL and Postgres both do."""

    def handle(sql: str):
        if "MIN(`datetime`) AS ts" in sql:
            return [{"ts": "2026-09-16 09:15:00"}]
        out = []
        for u in _uuids_in(sql):
            n, total, mn, mx = spec[u]
            out.append(
                {
                    "uuid": u,
                    "n": n,
                    "sm": total,
                    "mn": mn,
                    "mx": mx,
                    "ex": 0,
                    "bad": 0,
                    "t0": "2026-09-19 00:00:00",
                    "t1": "2026-09-19 23:59:00",
                }
            )
        return out

    return handle


async def test_the_building_mean_is_weighted_by_readings_and_sits_inside_the_range():
    """The shape that produced 39.4 against a floor minimum of 45."""
    meta = {
        "sensor-b0-aaaa": {"label": "Air Quality 0.01", "unit": "level", "floor": "0"},
        "sensor-b5-aaaa": {"label": "Air Quality 5.01", "unit": "level", "floor": "5"},
    }
    # floor 0: 10 readings averaging 100; floor 5: 1,000 readings averaging 50
    spec = {
        "sensor-b0-aaaa": (10, 1000.0, 95.0, 105.0),
        "sensor-b5-aaaa": (1000, 50000.0, 45.0, 60.0),
    }
    adapter = FakeAdapter(_sum_count_rows(spec))
    res = await ask(
        "Is the air quality good today?",
        metadata=meta,
        uuids=list(meta),
        storage_map={u: STORE for u in meta},
        adapter_for=lambda uri: adapter,
    )
    text = res["formatted_response"]
    mean = float(re.search(r"averaged ([\d.,]+)", text).group(1).replace(",", ""))
    low, high = (
        float(x.replace(",", ""))
        for x in re.search(r"ranging from ([\d.,]+) to ([\d.,]+)", text).groups()
    )
    assert low <= mean <= high, f"{mean} is outside {low}..{high}"
    # 51,000 over 1,010 readings = 50.5, not the unweighted mean of 100 and 50
    assert abs(mean - 50.5) < 0.1, text


async def test_a_figure_outside_its_own_range_is_never_printed():
    """The invariant, driven by a store that reports a sum inconsistent with its own extremes."""
    meta = {"sensor-b5-aaaa": {"label": "Air Quality 5.01", "unit": "level", "floor": "5"}}
    impossible = {"sensor-b5-aaaa": (100, 3940.0, 45.0, 105.0)}  # mean 39.4, min 45
    adapter = FakeAdapter(_sum_count_rows(impossible))
    res = await ask(
        "Is the air quality good today?",
        metadata=meta,
        uuids=list(meta),
        storage_map={u: STORE for u in meta},
        adapter_for=lambda uri: adapter,
    )
    assert res is None, "a mean below its own minimum must never reach a reader"


def test_the_renderer_itself_withholds_rather_than_prints():
    bad = al.GroupStat(
        "5", sensors=1, readings=100, value=39.4, low=45.0, high=105.0, mean=39.4, total=3940.0
    )
    out = al.render_summary(
        [bad],
        measurand="air quality",
        unit="level",
        window=al.Window("2026-09-19 00:00:00", "2026-09-19 23:59:59", "today"),
        sensors_used=1,
        sensors_requested=1,
        floors_seen=1,
        excluded=0,
        excluded_sensors=0,
        no_reading=0,
        unplaced=0,
        bands_checked=True,
    )
    assert out == ""
    good = al.GroupStat(
        "5", sensors=1, readings=100, value=60.0, low=45.0, high=105.0, mean=60.0, total=6000.0
    )
    assert "averaged 60" in al.render_summary(
        [good],
        measurand="air quality",
        unit="level",
        window=al.Window("2026-09-19 00:00:00", "2026-09-19 23:59:59", "today"),
        sensors_used=1,
        sensors_requested=1,
        floors_seen=1,
        excluded=0,
        excluded_sensors=0,
        no_reading=0,
        unplaced=0,
        bands_checked=True,
    )


async def test_one_instrumented_floor_reads_as_a_fact_about_the_building():
    """ "No figure for Floor 0, 1, 2, 3 and 4" is true and reads like a fault."""
    meta = {"sensor-b5-aaaa": {"label": "Air Quality 5.01", "unit": "level", "floor": "5"}}
    spec = {"sensor-b5-aaaa": (100, 6000.0, 45.0, 105.0)}
    adapter = FakeAdapter(_sum_count_rows(spec))
    res = await ask(
        "Is the air quality good today?",
        metadata=meta,
        uuids=list(meta),
        storage_map={u: STORE for u in meta},
        adapter_for=lambda uri: adapter,
    )
    text = res["formatted_response"]
    assert "records air quality on one floor only (Floor 5)" in text
    assert "the other 5 floors have no sensor of this kind" in text
    assert "No figure for Floor 0" not in text
