# -*- coding: utf-8 -*-
"""Three stakeholder questions the aggregate lane must answer the way the building would (wave 2).

Read from the wave-1 live run (docs/phase0/wave1_verification.jsonl):

* "Which floor has the most people in it right now?" answered "Floor 5 has the highest occupancy
  with 17 people ... 10 on floor 2, 9 on floor 4, 8 on floor 0, 3 on floor 3": Floor 1 missing, 47
  people in total, and three minutes earlier "how many people are in the building" had said 23
  from the six floor counters. The compare lane had summed room readings. A floor's headcount is
  the floor's own counter when one exists; the two questions must agree.
* "How much gas did we use this week?" answered "No usage data available. The sensor readings show
  the highest concentration of 205.31 ppm ..." followed by ppm statistics. The building has gas
  SENSORS reporting a concentration, not a gas meter: one honest sentence, no statistics.
* "How much water did floor 3 use yesterday?" answered "2,058,048 L" from the analytics lane
  (mean flow x 86,400 s) without saying how. The flow series is integrated and the sampling and
  the gap are stated. It reached the analytics lane because the sensor's metadata carried no unit
  while its label said [L/s]; the unit is now read from the label when nothing else declares it.
"""

from __future__ import annotations

import re
from datetime import datetime
from typing import Any, Callable, Dict, List, Optional

import pytest

from orchestrator.services import aggregate_lane as al
from orchestrator.services.database_adapter import AdapterType, QueryResult

pytestmark = pytest.mark.unit

NOW = datetime(2026, 9, 18, 12, 0, 0)
TZ = "Europe/London"
STORE = "http://example.org/bldg#occupancy_data"


class FakeAdapter:
    adapter_type = AdapterType.MYSQL

    def __init__(
        self, handler: Callable[[str], List[Dict[str, Any]]], table: str = "occupancy_data"
    ):
        self.table = table
        self.handler = handler
        self.sql: List[str] = []

    async def execute_query(self, sql: str) -> QueryResult:
        self.sql.append(sql)
        rows = self.handler(sql)
        return QueryResult(success=True, data=rows, row_count=len(rows), query=sql)


def _uuids_in(sql: str) -> List[str]:
    return re.findall(r"'(sensor-[0-9a-z-]+)'", sql)


def latest_handler(values: Dict[str, Any]):
    """values: uuid -> value, or uuid -> (value, timestamp)."""

    def handle(sql: str):
        rows = []
        for u, v in values.items():
            if f"'{u}'" in sql:
                value, ts = v if isinstance(v, tuple) else (v, "2026-09-18 11:58:00")
                rows.append({"uuid": u, "value": value, "ts": ts})
        return rows

    return handle


def sparql(
    places: Optional[Dict[str, Any]] = None,
    counters: Optional[Dict[str, Any]] = None,
    floors: Optional[List[str]] = None,
):
    async def run(query: str) -> Dict[str, Any]:
        if "VALUES ?seed" in query:
            binds = [
                {
                    "uuid": {"value": u},
                    "storage": {"value": STORE},
                    "floorNum": {"value": f},
                    "label": {"value": f"Occupancy Count Sensor - Floor {f}"},
                }
                for u, f in (counters or {}).items()
            ]
            return {"results": {"bindings": binds}}
        if "SELECT DISTINCT ?floorNum" in query and "VALUES" not in query:
            return {"results": {"bindings": [{"floorNum": {"value": f}} for f in (floors or [])]}}
        binds = []
        for u, (room, floor) in (places or {}).items():
            if f'"{u}"' in query:
                binds.append(
                    {
                        "uuid": {"value": u},
                        "locLabel": {"value": room},
                        "floorNum": {"value": floor},
                        "onFloor": {"value": "false"},
                    }
                )
        return {"results": {"bindings": binds}}

    return run


async def ask(question, adapter, meta, sparql_exec, **kw):
    args = dict(
        question=question,
        uuids=list(meta),
        storage_map={u: STORE for u in meta},
        metadata=meta,
        start_date=None,
        end_date=None,
        budget_hit=False,
        tz_name=TZ,
        adapter_for=lambda uri: adapter,
        store_key=lambda uri: "occupancy_data",
        sparql_exec=sparql_exec,
        now=NOW,
        bands={},
    )
    args.update(kw)
    return await al.try_answer(**args)


# ── who has the most people: the floor's own counter, every floor, and it agrees ─────────────

ROOMS = {f"sensor-room{f}-aaaa": (f"Room {f}.01 - Office", str(f)) for f in (0, 2, 3, 4, 5)}
ROOM_META = {
    u: {"label": f"{room} occupancy [persons]", "unit": "persons", "floor": floor}
    for u, (room, floor) in ROOMS.items()
}  # floor 1 has no room sensors in the resolved set, exactly as the live run showed
COUNTERS = {f"sensor-fl{f}-counter": str(f) for f in range(6)}
FLOOR_READINGS = {
    u: v for u, v in zip(COUNTERS, (5, 5, 4, 3, 2, 4))
}  # the 23 people of the live run


async def test_the_floor_headcount_uses_the_floor_counters_even_when_the_sensors_carry_floors():
    adapter = FakeAdapter(latest_handler({**FLOOR_READINGS, **{u: 9 for u in ROOM_META}}))
    res = await ask(
        "Which floor has the most people in it right now?",
        adapter,
        ROOM_META,
        sparql(ROOMS, COUNTERS, floors=list("012345")),
    )
    text = res["formatted_response"]
    assert "| Floor 1 | 5 | 1 |" in text  # the floor the room sensors never mentioned
    assert "| Floor 4 | 2 | 1 |" in text
    assert "the room-level counters are not added to it, so nobody is counted twice" in text
    assert not any(u in " ".join(adapter.sql) for u in ROOM_META), "the rooms were never summed"


async def test_the_floor_figures_add_up_to_the_building_total_given_a_moment_earlier():
    adapter = FakeAdapter(latest_handler({**FLOOR_READINGS, **{u: 9 for u in ROOM_META}}))
    res = await ask(
        "Which floor has the most people in it right now?",
        adapter,
        ROOM_META,
        sparql(ROOMS, COUNTERS, floors=list("012345")),
    )
    per_floor = [int(n) for n in re.findall(r"\| Floor \d \| (\d+) \|", res["formatted_response"])]
    assert len(per_floor) == 6 and sum(per_floor) == 23  # the building-total answer's 23


async def test_without_floor_counters_a_room_is_counted_once_with_its_newest_reading():
    meta = {
        "sensor-a1-aaaa": {
            "label": "Room 1.01 occupancy [persons]",
            "unit": "persons",
            "floor": "1",
        },
        "sensor-a2-aaaa": {
            "label": "Room 1.01 second sensor [persons]",
            "unit": "persons",
            "floor": "1",
        },
        "sensor-b1-aaaa": {
            "label": "Room 1.02 occupancy [persons]",
            "unit": "persons",
            "floor": "1",
        },
    }
    places = {
        "sensor-a1-aaaa": ("Room 1.01", "1"),
        "sensor-a2-aaaa": ("Room 1.01", "1"),
        "sensor-b1-aaaa": ("Room 1.02", "1"),
    }
    adapter = FakeAdapter(
        latest_handler(
            {
                "sensor-a1-aaaa": (3, "2026-09-18 11:50:00"),
                "sensor-a2-aaaa": (
                    4,
                    "2026-09-18 11:58:00",
                ),  # the newer reading of the same room wins
                "sensor-b1-aaaa": (2, "2026-09-18 11:57:00"),
            }
        )
    )
    res = await ask(
        "Which floor has the most people right now?",
        adapter,
        meta,
        sparql(places, {}),
        budget_hit=True,
    )
    text = res["formatted_response"]
    assert text.startswith("**Floor 1 has the most people in it right now: 6**")  # 4 + 2, not 3+4+2
    assert "each floor's figure is the sum of one reading per room that has a counter" in text


async def test_a_floor_that_returned_no_reading_is_named_not_dropped():
    meta = {u: m for u, m in ROOM_META.items() if m["floor"] in ("2", "3")}
    adapter = FakeAdapter(
        latest_handler(
            {
                "sensor-room2-aaaa": 4,
                "sensor-room3-aaaa": 2,
            }
        )
    )
    res = await ask(
        "Which floor has the most people right now?",
        adapter,
        meta,
        sparql(ROOMS, {}, floors=list("0123")),
        budget_hit=True,
    )
    assert "No figure for Floor 0 and Floor 1" in res["formatted_response"]


async def test_a_weeks_headcount_is_never_built_from_the_peaks_of_rooms():
    """Summing each room's PEAK counts people who were there at different times."""
    adapter = FakeAdapter(lambda sql: [])
    res = await ask(
        "Which floor had the most people this week?",
        adapter,
        ROOM_META,
        sparql(ROOMS, {}),
        budget_hit=True,
    )
    assert res is None


async def test_a_status_flag_is_not_added_up_as_people():
    meta = {
        u: {**m, "label": m["label"].replace("occupancy [persons]", "occupancy_status")}
        for u, m in ROOM_META.items()
    }
    adapter = FakeAdapter(latest_handler({u: 1 for u in meta}))
    assert (
        await ask("Which floor has the most people right now?", adapter, meta, sparql(ROOMS, {}))
        is None
    )


async def test_a_temperature_question_that_names_floors_is_still_left_to_the_row_lane():
    meta = {u: {"label": "Air Temperature 1.01", "unit": "°C", "floor": "1"} for u in ROOM_META}
    adapter = FakeAdapter(latest_handler({}))
    assert (
        await ask("Which floor is the warmest right now?", adapter, meta, sparql(ROOMS, {})) is None
    )
    assert adapter.sql == []


# ── gas: a level is not a consumption, in one sentence ───────────────────────────────────────

GAS = {
    f"sensor-gas{i}-aaaa": {"label": f"LPG Natural Gas Town MQ5 Sensor 5.{i:02d}", "unit": "ppm"}
    for i in range(1, 5)
}


async def test_a_gas_consumption_question_is_one_sentence_even_when_under_the_budget():
    adapter = FakeAdapter(latest_handler({}))
    res = await ask("How much gas did we use this week?", adapter, GAS, sparql(), budget_hit=False)
    text = res["formatted_response"]
    assert "\n" not in text and text.endswith(".")
    assert "I can't say how much gas was used" in text and "show you their readings" in text
    assert '4 sensors matched to "gas"' in text and "ppm" in text
    assert not re.search(r"\|", text) and "highest" not in text
    assert adapter.sql == [], "no store is asked: the answer does not depend on the readings"


async def test_a_gas_answer_names_no_statistics_and_no_meter_claim_it_cannot_back():
    adapter = FakeAdapter(latest_handler({}))
    text = (await ask("How much gas did we use this week?", adapter, GAS, sparql()))[
        "formatted_response"
    ]
    assert not re.search(r"\d+\.\d+", text.replace("4 sensors", ""))
    assert (
        "no gas meter" not in text.lower()
    )  # it says what the SENSORS are, not what the building lacks


async def test_a_how_much_question_about_a_level_without_a_consumption_verb_is_left_alone():
    meta = {"sensor-co2-aaaaa": {"label": "CO2 1.01", "unit": "ppm", "floor": "1"}}
    adapter = FakeAdapter(latest_handler({}))
    assert await ask("How much CO2 is on floor 1 this week?", adapter, meta, sparql()) is None


# ── water: the sensor has no unit but its label does ────────────────────────────────────────

W = "sensor-water3-flow"


def _integral(**over):
    row = dict(
        n=258,
        integral=2_051_447.0,
        max_gap=2504,
        mean_gap=336.0,
        gap_s=6974.0,
        t0="2026-09-16 23:04:16",
        t1="2026-09-17 22:56:41",
    )
    row.update(over)
    return row


def integral_handler(row):
    return lambda sql: [{"uuid": W, **row}] if f"'{W}'" in sql else []


async def test_a_flow_with_no_declared_unit_takes_its_unit_from_its_label():
    meta = {W: {"label": "Floor3 water_flow_rate [L/s]", "unit": "", "floor": "3"}}
    adapter = FakeAdapter(integral_handler(_integral()), table="waterflow_data")
    res = await ask("How much water did floor 3 use yesterday?", adapter, meta, sparql())
    text = res["formatted_response"]
    assert text.startswith("**About 2,051 m³ (2,051,447 L) of water on floor 3**")
    assert "integrating the flow readings" in text and "a gap of 42 min was bridged" in text


async def test_a_label_that_disagrees_with_the_declared_unit_is_not_turned_into_a_volume():
    meta = {W: {"label": "Floor3 water_flow_rate [L/s]", "unit": "L/min", "floor": "3"}}
    adapter = FakeAdapter(integral_handler(_integral()), table="waterflow_data")
    res = await ask("How much water did floor 3 use yesterday?", adapter, meta, sparql())
    text = res["formatted_response"]
    assert "I can't total" in text and "L/min" in text and "L/s" in text
    assert "2,051" not in text


async def test_a_series_too_holey_to_integrate_says_so_instead_of_falling_through():
    meta = {W: {"label": "Floor3 water_flow_rate [L/s]", "unit": "L/s", "floor": "3"}}
    adapter = FakeAdapter(
        integral_handler(_integral(gap_s=40_000.0, max_gap=30_000)), table="waterflow_data"
    )
    res = await ask("How much water did floor 3 use yesterday?", adapter, meta, sparql())
    assert res is not None and "I can't total" in res["formatted_response"]
    assert "too much to bridge honestly" in res["formatted_response"]


def test_a_unit_written_in_a_label_is_read_only_when_it_is_a_unit_the_contract_knows():
    from orchestrator.services.aggregate_support import unit_from_label

    assert unit_from_label("Floor3 water_flow_rate [L/s]") == "L/s"
    assert unit_from_label("Room 4.16 occupancy [persons]") == ""  # not a unit it can convert
    assert unit_from_label("Floor5 gas [ppm]") == "ppm"
    assert unit_from_label("no brackets here") == ""
    assert unit_from_label("bays [free] [bays]") == ""


def test_a_class_level_unit_of_another_kind_loses_to_the_sensors_own_label():
    from orchestrator.services.aggregate_support import resolve_unit

    # the modality entry for the water-flow class says litres; the sensor says litres per second
    assert resolve_unit("L", "Floor3 water_flow_rate [L/s]") == ("L/s", "")
    assert resolve_unit("", "Floor3 water_flow_rate [L/s]") == ("L/s", "")
    assert resolve_unit("ppm", "CO2 [ppm]") == ("ppm", "")
    assert resolve_unit("ppm", "no bracket") == ("ppm", "")


def test_two_units_of_the_same_kind_are_a_conflict_not_a_choice():
    from orchestrator.services.aggregate_support import resolve_unit

    assert resolve_unit("L/min", "Floor3 water_flow_rate [L/s]") == ("L/min", "L/s")


def test_floors_without_a_number_are_not_floors_whose_absence_needs_explaining():
    from orchestrator.services.aggregate_support import (
        missing_floors_note,
        parse_floors,
    )

    result = {
        "results": {
            "bindings": [
                {"floorNum": {"value": "1"}},
                {"floorNum": {"value": "0"}},
                {"floorNum": {"value": "http://example.org/bldg#Rooftop"}},
            ]
        }
    }
    assert parse_floors(result) == ["0", "1"]
    assert missing_floors_note(["0", "1"], ["0", "1"], "occupancy") == ""


# ── the shape the live bind actually has (wave 2, second pass) ───────────────────────────────
#
# The fix above did not take effect live: the turn still went to the compare lane, which answered
# "Floor 5 has the highest occupancy with 114 people ... floor 2's 86 ... floor 3's 27" while the
# building-total question read 29+28+29+27+28+29 = 170 from the six floor counters. Two causes,
# both reproduced here with the metadata the pipeline really builds:
#
#   * `occupancy_data` holds 256 counting series and 243 occupancy-STATUS series, and a question
#     about people binds a mixture. `is_headcount` asked whether NO label carried a status word,
#     so one status series among hundreds made the whole question "not a headcount".
#   * only the six floor counters carry a `brick:hasUnit` triple; every room series falls back to
#     the modality table, which gives "people" for a count and "" for a status.

LIVE_COUNT = "Telecommunications Room \u2014 Floor {f} (Room {f}.34) occupancy [persons]"
LIVE_STATUS = "Telecommunications Room \u2014 Floor {f} (Room {f}.34) occupancy_status"


def _live_metadata():
    """250 room series as the pipeline builds them: counts and statuses mixed, floors attached."""
    meta = {}
    for i in range(125):
        f = i % 6
        meta[f"sensor-cnt{i:03d}-aaaa"] = {
            "label": LIVE_COUNT.format(f=f),
            "unit": "people",
            "floor": str(f),
            "kind": "occupancy",
        }
        meta[f"sensor-sta{i:03d}-aaaa"] = {
            "label": LIVE_STATUS.format(f=f),
            "unit": "",
            "floor": str(f),
            "kind": "occupancy",
        }
    return meta


def test_a_mixture_of_counters_and_status_flags_is_still_a_headcount_question():
    """ANY, not ALL: one status series must not disqualify two hundred counters."""
    from orchestrator.services.aggregate_support import is_headcount

    meta = _live_metadata()
    labels = [m["label"] for m in meta.values()]
    assert is_headcount("occupancy", labels, ["count"] * 125) is True
    assert is_headcount("occupancy", [LIVE_STATUS.format(f=1)], []) is False


@pytest.mark.parametrize(
    "question",
    [
        "Which floor has the most people in it right now?",
        "Which floor has the most people?",  # no period named: for a headcount that means now
        "Which floor has the most people in it?",
    ],
)
def test_both_phrasings_reach_the_lane_on_the_live_metadata_shape(question):
    from orchestrator.services.aggregate_lane import wants_lane
    from orchestrator.services.aggregate_support import is_headcount

    meta = _live_metadata()
    labels = [m["label"] for m in meta.values()]
    head = is_headcount("occupancy", labels, ["count"] * 125)
    # budget NOT hit and the sensors DO carry floors: exactly the live conditions under which the
    # lane declined and the compare lane summed rooms instead
    intent = wants_lane(question, len(meta), False, True, ["count"] * 125, head)
    assert intent is not None and intent.group == "floor"


def test_a_headcount_over_a_named_period_is_still_left_alone():
    from orchestrator.services.aggregate_lane import wants_lane

    for q in ("Which floor had the most people this week?", "Which floor was busiest yesterday?"):
        assert wants_lane(q, 250, False, True, ["count"], True) is None


async def test_on_the_live_shape_the_floor_counters_answer_and_the_status_flags_are_named():
    meta = _live_metadata()
    counters = {f"sensor-fl{f}-counter": str(f) for f in range(6)}
    readings = {u: v for u, v in zip(counters, (29, 28, 28, 27, 28, 29))}
    places = {u: (m["label"].split(" occupancy")[0], m["floor"]) for u, m in meta.items()}
    adapter = FakeAdapter(latest_handler({**readings, **{u: 14 for u in meta}}))
    res = await ask(
        "Which floor has the most people in it right now?",
        adapter,
        meta,
        sparql(places, counters, floors=list("012345")),
    )
    text = res["formatted_response"]
    per_floor = [int(n) for n in re.findall(r"\| Floor \d \| (\d+) \|", text)]
    assert len(per_floor) == 6 and sum(per_floor) == 169  # the six counters, and nothing else
    assert "the room-level counters are not added to it" in text
    assert "125 sensors record whether a space is occupied" in text
    assert "114" not in text  # the compare lane's room-sum figure must not reappear


async def test_without_counters_the_room_sum_uses_only_the_counting_series():
    meta = _live_metadata()
    places = {u: (m["label"].split(" occupancy")[0], m["floor"]) for u, m in meta.items()}
    adapter = FakeAdapter(latest_handler({u: (1 if "sta" in u else 14) for u in meta}))
    res = await ask(
        "Which floor has the most people?", adapter, meta, sparql(places, {}, floors=list("012345"))
    )
    text = res["formatted_response"]
    # 125 counting series over 6 floors, one room each (the label repeats per floor), 14 apiece
    assert "sum of one reading per room that has a counter" in text
    assert "125 sensors record whether a space is occupied" in text
    for _f, value in re.findall(r"\| Floor (\d) \| (\d+) \|", text):
        assert int(value) == 14, "a status flag was added to a headcount"
