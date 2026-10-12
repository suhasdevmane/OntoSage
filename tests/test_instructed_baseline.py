"""The Paper 3 comparison assistant's tools and loops behave as specified (spec §3, §6).

Offline: SPARQL, stores and the model provider are fakes. No test asserts which building is active.
"""

import asyncio
import json
import sys
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Dict, List

import httpx
import pytest

pytestmark = pytest.mark.unit
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))

from instructed_baseline import loop, native  # noqa: E402
from instructed_baseline.tools import Toolbox, compact  # noqa: E402

NS = "http://example.org/bldg#"


def run(coro):
    return asyncio.run(coro)


def b(**kv):
    return {k: {"value": v} for k, v in kv.items()}


async def fake_sparql(q: str) -> Dict[str, Any]:
    if "LCASE(STR(?label))" in q:  # find_spaces
        if '"nowhere"' in q:
            return {"results": {"bindings": []}}
        return {
            "results": {
                "bindings": [
                    b(
                        s=NS + "Room9.99",
                        label="Room 9.99 - Lab",
                        type="https://brickschema.org/schema/Brick#Room",
                    )
                ]
            }
        }
    if f"<{NS}Room9.99> ?p ?o" in q:  # facts
        return {
            "results": {
                "bindings": [
                    b(p=NS + "roomCapacity", o="12"),
                    b(p=NS + "isPartOf", o=NS + "Floor9"),
                ]
            }
        }
    if "hasExternalReference" in q and "?label ?type" in q:  # points in place
        return {
            "results": {
                "bindings": [
                    b(
                        p=NS + "Temp_A",
                        label="Room temp (generated)",
                        type="https://brickschema.org/schema/Brick#Air_Temperature_Sensor",
                        uuid="aaaaaaaa-0000",
                        store=NS + "narrow_t",
                    ),
                    b(
                        p=NS + "Temp_B",
                        label="Zone temp (real)",
                        type="https://brickschema.org/schema/Brick#Air_Temperature_Sensor",
                        uuid="bbbbbbbb-0000",
                        store=NS + "wide_db",
                    ),
                    b(
                        p=NS + "Hum_C",
                        label="Humidity",
                        type="https://brickschema.org/schema/Brick#Humidity_Sensor",
                        uuid="cccccccc-0000",
                        store=NS + "narrow_t",
                    ),
                ]
            }
        }
    if "hasTimeseriesId" in q and '"bbbbbbbb-0000"' in q:  # store lookup by uuid
        return {"results": {"bindings": [b(store=NS + "wide_db")]}}
    if "?s ?p ?o" in q:  # register rows
        return {
            "results": {
                "bindings": [
                    b(s=NS + "SVC-1", p=NS + "task", o="Gutter clearance"),
                    b(s=NS + "SVC-1", p=NS + "nextDue", o="2028-05-17"),
                    b(s=NS + "SVC-2", p=NS + "task", o="Window cleaning"),
                ]
            }
        }
    return {"results": {"bindings": []}}


@dataclass
class Res:
    success: bool = True
    data: List[Dict[str, Any]] = field(default_factory=list)
    error: str = ""


class FakeAdapter:
    def __init__(self, table=None, rows=None):
        self.table, self.rows, self.sql = table, rows or [], []

    def build_timeseries_query(self, uuids, ts, start, end, limit=1000):
        return f"SELECT `Datetime` AS `timestamp` FROM `sensor_data` WHERE uuids={','.join(uuids)}"

    async def execute_query(self, sql):
        self.sql.append(sql)
        if "MIN(" in sql:
            return Res(
                data=[
                    {"first_ts": "2025-01-01 00:00:05", "last_ts": "2025-03-09 23:59:55", "n": 1000}
                ]
            )
        return Res(data=self.rows)


@dataclass
class Concept:
    concept_id: str
    lay_term: str
    brick_classes: List[str]

    def to_dict(self):
        return {"concept_id": self.concept_id}


@dataclass
class RecordClass:
    local_name: str
    label: str
    instances: int
    terms: tuple


def box(adapters=None):
    adapters = adapters or {}

    async def concepts(text):
        return (
            [
                Concept(
                    "air_temp",
                    "temperature",
                    ["https://brickschema.org/schema/Brick#Air_Temperature_Sensor"],
                )
            ]
            if "temp" in text
            else []
        )

    async def records():
        return [RecordClass("ServiceSchedule", "Service schedule", 2, ("service", "schedule"))]

    return Toolbox(
        sparql=fake_sparql,
        adapter_getter=adapters.get,
        concept_resolve=concepts,
        record_classes=records,
        namespace=NS,
        building_id="bx",
        tz="Europe/London",
    )


def test_compact_states_the_cut():
    text = compact({"x": "y" * 9000}, budget=100)
    assert len(text) < 200 and "TRUNCATED" in text


def test_call_returns_errors_as_data():
    t = box()
    assert "unknown tool" in run(t.call("drop_tables", {}))["error"]
    assert "bad arguments" in run(t.call("find_spaces", {"wrong": 1}))["error"]


def test_find_spaces_states_an_empty_match_and_returns_facts():
    t = box()
    assert run(t.find_spaces("nowhere"))["spaces"] == []
    sp = run(t.find_spaces("9.99"))["spaces"][0]
    assert sp["id"] == "Room9.99" and sp["properties"]["roomCapacity"] == "12"


def test_find_points_lists_every_matching_series_with_its_coverage():
    t = box({"narrow_t": FakeAdapter(table="t"), "wide_db": FakeAdapter()})
    res = run(t.find_points("9.99", "temperature"))
    names = [p["point"] for p in res["points"]]
    assert names == ["Temp_A", "Temp_B"]  # both temperature series, not the humidity point
    assert res["points"][1]["series"]["first"].startswith("2025-01-01")


def test_get_readings_summarises_rows_resolves_a_missing_store_and_reports_coverage():
    wide = FakeAdapter(
        rows=[
            {"uuid": "bbbbbbbb-0000", "timestamp": "2025-01-13 09:00:00", "value": 22.0},
            {"uuid": "bbbbbbbb-0000", "timestamp": "2025-01-13 09:30:00", "value": 23.0},
        ]
    )
    t = box({"wide_db": wide})
    res = run(
        t.get_readings(
            [{"uuid": "bbbbbbbb-0000"}, {"uuid": "dddddddd-0000", "stored_at": "wide_db"}],
            "2025-01-13T09:00",
            "2025-01-13T12:00",
        )
    )
    r = res["readings"][0]
    assert (r["n"], r["min"], r["max"], r["largest_gap_minutes"]) == (2, 22.0, 23.0, 30.0)
    assert res["points_with_data"] == 1 and res["points_asked"] == 2
    assert res["readings"][1]["n"] == 0 and "no readings" in res["readings"][1]["note"]


def test_get_readings_rejects_a_backwards_window():
    assert (
        "after start"
        in run(
            box().get_readings(
                [{"uuid": "x", "stored_at": "s"}], "2025-01-02T10:00", "2025-01-02T09:00"
            )
        )["error"]
    )


def test_query_records_lists_registers_when_nothing_matches_and_filters_rows():
    t = box()
    miss = run(t.query_records("paint log"))
    assert miss["rows"] == [] and miss["registers_held"]
    hit = run(t.query_records("service", contains="gutter"))
    assert hit["matched"] == 1 and hit["rows"][0]["nextDue"] == "2028-05-17"


class FakeProvider:
    def __init__(self, replies):
        self.replies, self.calls = list(replies), []

    async def chat(self, messages, tools, force_answer=False):
        self.calls.append(force_answer)
        r = self.replies.pop(0)
        if isinstance(r, Exception):
            raise r
        return r


def tool_call(name, args):
    return {
        "message": {
            "content": "",
            "tool_calls": [{"id": "c1", "function": {"name": name, "arguments": json.dumps(args)}}],
        },
        "finish_reason": "tool_calls",
    }


def test_native_loop_runs_a_tool_then_answers():
    p = FakeProvider(
        [
            tool_call("find_spaces", {"name_or_kind": "9.99"}),
            {"message": {"content": "Room 9.99 holds 12."}, "finish_reason": "stop"},
        ]
    )
    res = run(native.answer("How many fit in 9.99?", box(), p, "rules", "2026-10-10"))
    assert res["answer"] == "Room 9.99 holds 12." and [s["action"] for s in res["steps"]] == [
        "find_spaces"
    ]
    assert res["provider_failure"] is False


def test_native_loop_forces_an_answer_at_the_step_limit():
    p = FakeProvider(
        [tool_call("find_spaces", {"name_or_kind": "9.99"})] * 3
        + [{"message": {"content": "done"}, "finish_reason": "stop"}]
    )
    res = run(native.answer("q", box(), p, "rules", "2026-10-10", max_steps=3))
    assert p.calls[-1] is True and res["answer"] == "done" and res["hit_step_limit"]


def test_native_loop_records_a_provider_failure():
    p = FakeProvider([httpx.ConnectError("gateway unreachable")])
    res = run(native.answer("q", box(), p, "rules", "2026-10-10"))
    assert res["provider_failure"] is True and res["answer"] == ""


class FakeLLM:
    def __init__(self, steps):
        self.steps = list(steps)

    async def generate_structured(self, prompt, schema, **kw):
        return self.steps.pop(0)


def test_json_loop_runs_a_tool_then_answers():
    llm = FakeLLM(
        [
            {"action": "find_spaces", "arguments": {"name_or_kind": "9.99"}},
            {"action": "final_answer", "answer": "12 people."},
        ]
    )
    res = run(loop.answer("q", box(), llm, "rules", "2026-10-10"))
    assert res["answer"] == "12 people." and res["steps"][0]["action"] == "find_spaces"
