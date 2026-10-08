# -*- coding: utf-8 -*-
"""v2, shape C4 — one reading over two periods.

"Was it warmer this week than last week?", "today versus yesterday", "is CO2 higher on weekdays
than at weekends?". The two periods are resolved by requested_interval from the question's own
words -- never a second date parser, never a date the model wrote -- and each period is reduced IN
THE STORE (aggregate_lane.run_aggregates), so a week is read whole rather than cut to its newest
rows. Only spaces with readings in BOTH periods are compared: like against like.

Peak against off-peak needs peak hours, and those belong to a tariff: with none in the catalogue
the question is a clarify signal, never a guess at clock hours.

Everything here runs OFFLINE: a stub LLM, an rdflib graph and a fake narrow store that answers
the aggregate lane's own GROUP BY statements from in-memory readings.
"""

from __future__ import annotations

import ast
import asyncio
import inspect
import json
import re
import textwrap
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from typing import Any, Dict, List, Optional, Tuple

import pytest
import rdflib

from orchestrator.services import requested_interval as ri
from orchestrator.services.deliberation import capability_schema as cs
from orchestrator.services.deliberation import clarify_policy as cp
from orchestrator.services.deliberation import compiler as C
from orchestrator.services.deliberation import facets
from orchestrator.services.deliberation import operations as ops
from orchestrator.services.deliberation.coverage_audit import CoverageAuditor, ModalitySpec
from orchestrator.services.deliberation.cqir import (
    CQIR,
    DecisionKind,
    GroupBy,
    PeriodRef,
    PeriodSpec,
    Statistic,
)
from orchestrator.services.deliberation.dossier import (
    build_dossier,
    numeric_guard,
    render_answer,
    render_dossier_details,
)
from orchestrator.services.deliberation.plan_executor import execute

pytestmark = pytest.mark.unit

ONTO = "http://ontosage.org/capabilities#"
NS = "http://example.org/campusD#"
BID = "campusD"

#: A Wednesday, building-local, so "this week" is in progress and "last week" is whole.
FROZEN = datetime(2026, 10, 7, 15, 30, 0)


def _run(coro):
    return asyncio.run(coro)


def _settings():
    import shared.config

    return shared.config.settings


@pytest.fixture(autouse=True)
def _isolated(monkeypatch):
    facets.clear_cache()
    monkeypatch.setattr(_settings(), "ARBITER_FACETS_ENABLED", True, raising=False)
    monkeypatch.setenv("CQIR_COMPILE_CACHE", "false")
    yield
    facets.clear_cache()


# ── 1. the periods, resolved once, by the one resolver ──────────────────────────────────


def test_this_week_against_last_week_is_two_whole_iso_weeks_earlier_first():
    periods, why = ri.compared_periods("Was it warmer this week than last week?", None, FROZEN)
    assert why == "" and [p["label"] for p in periods] == ["last week", "this week"]
    last, this = periods
    assert (last["start"], last["end"]) == ("2026-09-28 00:00:00", "2026-10-04 23:59:59")
    assert (this["start"], this["end"]) == ("2026-10-05 00:00:00", "2026-10-11 23:59:59")
    assert this["partial"] and not last["partial"], "the week in progress is said to be"
    # one period on its own is exactly what the single-period resolver gives it
    assert (last["start"], last["end"]) == ri.calendar_period_bounds("last week", None, FROZEN)


def test_two_named_days_and_the_day_before_yesterday_is_never_read_as_yesterday():
    periods, _ = ri.compared_periods("CO2 today versus yesterday", None, FROZEN)
    assert [p["label"] for p in periods] == ["yesterday", "today"]
    assert periods[0]["start"] == "2026-10-06 00:00:00" and periods[1]["partial"]
    older, _ = ri.compared_periods("Compare yesterday with the day before yesterday", None, FROZEN)
    assert [p["label"] for p in older] == ["the day before yesterday", "yesterday"]
    assert ri.named_days("the day before yesterday") == ["the day before yesterday"]


def test_weekdays_against_weekends_split_one_window_by_the_local_calendar():
    periods, _ = ri.compared_periods("Is CO2 higher on weekdays than weekends?", None, FROZEN)
    weekdays, weekends = periods
    assert (weekdays["day_type"], weekends["day_type"]) == ("weekday", "weekend")
    assert weekdays["start"] == weekends["start"] == "2026-09-24 00:00:00", "14 local days"
    assert weekdays["label"] == "weekdays (the last 14 days)"
    month, _ = ri.compared_periods("weekdays against weekends this month", None, FROZEN)
    assert (month[0]["start"], month[0]["end"]) == ri.period_bounds("month", 0, None, FROZEN)
    days = ri.local_day_windows("2026-10-02 12:00:00", "2026-10-05 08:00:00", None)
    assert [d[2] for d in days] == [5, 6, 7, 1], "Fri, Sat, Sun, Mon"
    assert days[0][0] == "2026-10-02 12:00:00" and days[-1][1] == "2026-10-05 08:00:00"


def test_a_local_day_is_converted_to_the_stores_clock_across_a_clock_change():
    """25 October 2026 is 25 hours long in the UK; its bounds are still one local day."""
    days = ri.local_day_windows("2026-10-24 23:00:00", "2026-10-25 23:59:59", "Europe/London")
    assert days == [("2026-10-24 23:00:00", "2026-10-25 23:59:59", 7)]


def test_periods_that_cannot_be_read_exactly_are_a_reason_not_a_guess():
    for question in (
        "Was it warmer recently than before?",
        "Compare this week with last month",
        "weekdays against weekends yesterday",
    ):
        periods, why = ri.compared_periods(question, None, FROZEN)
        assert periods == [] and why, question


# ── 2. the compiler ─────────────────────────────────────────────────────────────────────

MODS = [
    ModalitySpec("temperature", ["Air_Temperature_Sensor"], sat={"unit": "degC"}),
    ModalitySpec("occupancy", ["Occupancy_Count_Sensor"], sat={"unit": "persons"}),
]


def _facet(key, label, value_type, *, source="record", **kw):
    return facets.Facet(
        key=key,
        entity_type=kw.pop("entity_type", "space"),
        source_kind=source,
        label=label,
        value_type=value_type,
        status=kw.pop("status", "suitable"),
        coverage=kw.pop("coverage", 5),
        **kw,
    )


def _catalogue(extra=()) -> facets.FacetCatalogue:
    return facets.FacetCatalogue(
        [
            _facet(
                "sensor:temperature",
                "temperature",
                "number",
                source="sensor",
                modality="temperature",
                unit="degC",
            ),
            _facet(
                "sensor:occupancy",
                "occupancy",
                "number",
                source="sensor",
                modality="occupancy",
                unit="persons",
            ),
            _facet(
                "ttl:capacity",
                "room capacity (design occupancy)",
                "integer",
                source="ttl",
                unit="persons",
            ),
            *extra,
        ]
    )


def _payload(period, decision="period_compare"):
    return json.dumps(
        {
            "decision": decision,
            "constraints": [],
            "facet_criteria": [],
            "period": period,
            "spatial": [],
            "time": {"basis": "now"},
            "unmapped": [],
            "inspect": [],
        }
    )


def _compile(question, *responses, catalogue=None):
    prompts: List[str] = []
    queue = list(responses)

    async def llm(prompt: str) -> str:
        prompts.append(prompt)
        return queue.pop(0) if len(queue) > 1 else queue[0]

    out = _run(
        C.compile_query(question, MODS, llm, use_cache=False, catalogue=catalogue or _catalogue())
    )
    return out, prompts


WARMER = "Was it warmer this week than last week, by floor?"


def test_a_period_comparison_compiles_with_periods_read_from_the_question():
    out, prompts = _compile(
        WARMER,
        _payload({"facet": "temperature", "statistic": "average", "group_by": "floor"}),
    )
    assert out.signals == [] and out.is_executable(), out.signals
    assert out.decision == DecisionKind.PERIOD_COMPARE and out.operation == "period_compare"
    spec = out.period
    assert (spec.facet, spec.statistic, spec.group_by) == (
        "sensor:temperature",
        Statistic.MEAN,
        GroupBy.FLOOR,
    )
    expected, _ = ri.compared_periods(WARMER, ri.building_tz())
    assert [(p.label, p.start, p.end) for p in spec.periods] == [
        (p["label"], p["start"], p["end"]) for p in expected
    ]
    assert "period_compare" in prompts[0] and "Never write dates" in prompts[0]


def test_dates_the_model_writes_are_never_read():
    out, _ = _compile(
        WARMER,
        _payload(
            {
                "facet": "temperature",
                "periods": ["1999-01-01", "1999-01-08"],
                "start": "1999-01-01 00:00:00",
            }
        ),
    )
    assert out.period is not None
    assert all(not p.start.startswith("1999") for p in out.period.periods)


@pytest.mark.parametrize(
    "question,period,needle",
    [
        (WARMER, {"facet": "ttl:capacity"}, "not measured over time"),
        (WARMER, {"facet": "temperature", "statistic": "sum"}, "level measured in"),
        (WARMER, {"facet": "temperature", "statistic": "stdev"}, "not a way to compare"),
        (WARMER, {"facet": "temperature", "group_by": "wing"}, "not a way to group"),
        (
            "Was it warmer recently than before?",
            {"facet": "temperature"},
            "does not name two periods",
        ),
        (
            "Is energy use higher at peak than off-peak?",
            {"facet": "temperature"},
            "define no peak hours",
        ),
    ],
)
def test_an_invalid_period_comparison_is_a_signal_never_a_guess(question, period, needle):
    out, _ = _compile(question, _payload(period), _payload(period))
    assert out.period is None and not out.is_executable()
    assert any(needle in s.note for s in out.signals), out.signals


def test_peak_hours_are_looked_for_in_the_catalogue_not_assumed():
    peak = _facet(
        "record:Tariff.peakStart",
        "peak start",
        "text",
        entity_type="building",
        record_class="Tariff",
        predicate=ONTO + "peakStart",
    )
    out, _ = _compile(
        "Is occupancy higher at peak than off-peak?",
        _payload({"facet": "occupancy"}),
        catalogue=_catalogue(extra=[peak]),
    )
    assert out.period is None
    assert any("records peak hours (peak start)" in s.note for s in out.signals)


def test_the_v2_schema_covers_the_period_parser_and_carries_no_date_field():
    def reads(fn, receiver):
        keys = set()
        for node in ast.walk(ast.parse(textwrap.dedent(inspect.getsource(fn)))):
            if (
                isinstance(node, ast.Call)
                and isinstance(node.func, ast.Attribute)
                and node.func.attr == "get"
                and isinstance(node.func.value, ast.Name)
                and node.func.value.id == receiver
                and node.args
                and isinstance(node.args[0], ast.Constant)
            ):
                keys.add(node.args[0].value)
        return keys

    props = C._cqir_schema(facets=True)["properties"]
    period_keys = reads(C._period_item, "raw")
    assert period_keys and period_keys <= set(props["period"]["properties"])
    assert not {"start", "end", "periods", "dates"} & set(props["period"]["properties"])
    assert "period_compare" in props["decision"]["enum"]
    assert "period_compare" not in C._DECISIONS, "never in the v1 vocabulary"


def test_the_fingerprint_holds_the_resolved_bounds_and_not_the_labels():
    def plan(label_a, start_a):
        return CQIR(
            decision=DecisionKind.PERIOD_COMPARE,
            period=PeriodSpec(
                facet="sensor:temperature",
                periods=[
                    PeriodRef(label=label_a, start=start_a, end="2026-10-04 23:59:59"),
                    PeriodRef(label="b", start="2026-10-05 00:00:00", end="2026-10-11 23:59:59"),
                ],
            ),
        )

    base = plan("last week", "2026-09-28 00:00:00")
    assert base.is_executable() and base.operation == "period_compare"
    assert plan("the week before", "2026-09-28 00:00:00").plan_fingerprint() == (
        base.plan_fingerprint()
    )
    assert plan("last week", "2026-09-21 00:00:00").plan_fingerprint() != base.plan_fingerprint()
    assert base.operation_facets() == ["sensor:temperature"]


# ── 3. the arithmetic, pure ─────────────────────────────────────────────────────────────


def _ps(name, group, a=None, b=None, a_lo=None, a_hi=None, b_lo=None, b_hi=None):
    return ops.PeriodSpace(
        space_iri=NS + name,
        label=f"Room {name}",
        groups=[group],
        a_mean=a,
        a_low=a_lo if a_lo is not None else a,
        a_high=a_hi if a_hi is not None else a,
        a_n=10 if a is not None else 0,
        b_mean=b,
        b_low=b_lo if b_lo is not None else b,
        b_high=b_hi if b_hi is not None else b,
        b_n=12 if b is not None else 0,
        reason="" if a is not None and b is not None else "no readings in one period",
    )


SPACES = [
    _ps("a1", "F1", 20.0, 21.0, a_lo=19.0, b_hi=23.0),
    _ps("a2", "F1", 22.0, 22.0),
    _ps("b1", "F2", 21.0, 24.0, b_hi=26.0),
    _ps("b2", "F2", None, 30.0),
]
WINDOWS = [
    ops.PeriodWindow(label="last week", start="s1", end="e1"),
    ops.PeriodWindow(label="this week", start="s2", end="e2"),
]


def _compare(statistic, group_by="floor"):
    return ops.compare_periods(
        statistic,
        SPACES,
        WINDOWS,
        facet="sensor:temperature",
        label="temperature",
        unit="°C",
        group_by=group_by,
        group_labels={"F1": "Floor 1", "F2": "Floor 2"},
    )


def test_only_spaces_with_readings_in_both_periods_are_compared():
    result = _compare(Statistic.MEAN)
    overall = result.overall
    assert (overall.n, overall.a, overall.b) == (3, 21.0, 22.33)
    assert (overall.change, overall.percent, overall.direction) == (1.33, 6.33, "higher")
    assert (overall.readings_a, overall.readings_b) == (30, 36)
    assert result.not_compared == ["Room b2 (no readings in one period)"]
    by = {g.label: g for g in result.groups}
    assert (by["Floor 1"].a, by["Floor 1"].b, by["Floor 1"].n) == (21.0, 21.5, 2)
    assert (by["Floor 2"].a, by["Floor 2"].b, by["Floor 2"].n) == (21.0, 24.0, 1)


def test_each_reduction_of_the_spaces():
    assert (_compare(Statistic.SUM).overall.a, _compare(Statistic.SUM).overall.b) == (63.0, 67.0)
    low = _compare(Statistic.MIN).overall
    assert (low.a, low.a_space, low.b, low.b_space) == (19.0, "Room a1", 21.0, "Room a1")
    high = _compare(Statistic.MAX).overall
    assert (high.a, high.a_space, high.b, high.b_space) == (22.0, "Room a2", 26.0, "Room b1")
    assert _compare(Statistic.MEAN, group_by="").groups == []


# ── 4. a synthetic building and a store that reduces in SQL ─────────────────────────────


def _sparql_json(g: rdflib.Graph):
    async def sparql_exec(query: str) -> Dict[str, Any]:
        res = g.query(query)
        bindings = []
        for row in res:
            binding = {}
            for var in res.vars:
                val = row[var]
                if val is not None:
                    kind = "uri" if isinstance(val, rdflib.URIRef) else "literal"
                    binding[str(var)] = {"type": kind, "value": str(val)}
            bindings.append(binding)
        return {"head": {"vars": [str(v) for v in res.vars]}, "results": {"bindings": bindings}}

    return sparql_exec


_TBOX = """
@prefix brick: <https://brickschema.org/schema/Brick#> .
@prefix ref: <https://brickschema.org/schema/Brick/ref#> .
@prefix rdfs: <http://www.w3.org/2000/01/rdf-schema#> .
@prefix owl: <http://www.w3.org/2002/07/owl#> .
@prefix o: <http://ontosage.org/capabilities#> .
@prefix x: <http://example.org/campusD#> .

brick:Space rdfs:subClassOf brick:Location .
brick:Room rdfs:subClassOf brick:Space .
brick:Floor rdfs:subClassOf brick:Location .
o:Record a owl:Class .
x:G a brick:Floor ; rdfs:label "Ground" .
x:U a brick:Floor ; rdfs:label "Upper" .
"""

LAST = ("2026-09-28 00:00:00", "2026-10-04 23:59:59")
THIS = ("2026-10-05 00:00:00", "2026-10-11 23:59:59")

#: (room, floor, has a sensor, temperature last week, temperature this week). None = no
#: readings in that period.
ROOMS = [
    ("G1", "G", True, 20.0, 21.0),
    ("G2", "G", True, 22.0, 22.0),
    ("U1", "U", True, 21.0, 24.0),
    ("U2", "U", True, None, 30.0),
    ("U3", "U", False, None, None),
]


def _uuid(room: str) -> str:
    return f"tmp-{room}-0000"


def _building() -> rdflib.Graph:
    lines = [_TBOX]
    for room, floor, sensed, _a, _b in ROOMS:
        lines.append(
            f'x:{room} a brick:Room ; rdfs:label "Room {room}" ; brick:isPartOf x:{floor} .\n'
        )
        if sensed:
            lines.append(
                f"x:T{room} a brick:Air_Temperature_Sensor ; brick:hasLocation x:{room} ;\n"
                f'  ref:hasExternalReference [ ref:hasTimeseriesId "{_uuid(room)}" ; '
                "ref:storedAt x:temperature_data ] .\n"
            )
    g = rdflib.Graph()
    g.parse(data="\n".join(lines), format="turtle")
    return g


def _series() -> Dict[str, List[Tuple[datetime, float]]]:
    """Hourly readings. A weekday reads the period's value, a weekend day reads it plus 5."""
    out: Dict[str, List[Tuple[datetime, float]]] = {}
    for room, _floor, sensed, a, b in ROOMS:
        if not sensed:
            continue
        rows: List[Tuple[datetime, float]] = []
        for (start, end), value in ((LAST, a), (THIS, b)):
            if value is None:
                continue
            t = datetime.strptime(start, "%Y-%m-%d %H:%M:%S")
            stop = datetime.strptime(end, "%Y-%m-%d %H:%M:%S")
            while t <= stop:
                bump = 5.0 if t.isoweekday() >= 6 else 0.0
                rows.append((t, value + bump))
                t += timedelta(hours=1)
        out[_uuid(room)] = rows
    return out


@dataclass
class _Result:
    success: bool = True
    data: List[Dict[str, Any]] = field(default_factory=list)
    error: str = ""


class _Kind:
    value = "mysql"


class _NarrowStore:
    """Answers the aggregate lane's narrow GROUP BY statement from in-memory readings."""

    adapter_type = _Kind()
    table = "temperature_data"

    def __init__(self):
        self.series = _series()
        self.statements: List[str] = []

    async def execute_query(self, sql: str):
        self.statements.append(sql)
        uuids = re.findall(r"'([0-9A-Za-z-]{8,64})'", sql.split("IN (", 1)[1].split(")", 1)[0])
        start = re.search(r">= '([^']+)'", sql).group(1)
        end = re.search(r"<= '([^']+)'", sql).group(1)
        lo = datetime.strptime(start, "%Y-%m-%d %H:%M:%S")
        hi = datetime.strptime(end, "%Y-%m-%d %H:%M:%S")
        rows = []
        for uuid in uuids:
            values = [v for t, v in self.series.get(uuid, []) if lo <= t <= hi]
            if values:
                rows.append(
                    {
                        "uuid": uuid,
                        "n": len(values),
                        "mn": min(values),
                        "mx": max(values),
                        "sm": sum(values),
                        "t0": start,
                        "t1": end,
                        "ex": 0,
                        "bad": 0,
                    }
                )
        return _Result(data=rows)


TEMPERATURE = ModalitySpec(
    "temperature", ["Air_Temperature_Sensor"], sat={"unit": "degC", "scope": "room"}
)


def _schema(g):
    spaces = _run(CoverageAuditor(_sparql_json(g), [TEMPERATURE]).audit(NS))
    return cs.BuildingCapabilitySchema(building_id=BID, namespace=NS, spaces=spaces, amenities=[])


def _period_plan(periods, statistic=Statistic.MEAN, group_by=GroupBy.FLOOR, raw="q"):
    return CQIR(
        decision=DecisionKind.PERIOD_COMPARE,
        period=PeriodSpec(
            facet="sensor:temperature",
            statistic=statistic,
            group_by=group_by,
            periods=[PeriodRef(**p) for p in periods],
        ),
        raw_query=raw,
    )


WEEKS = [
    {"label": "last week", "start": LAST[0], "end": LAST[1]},
    {"label": "this week", "start": THIS[0], "end": THIS[1], "partial": True},
]


def _end_to_end(ir, monkeypatch):
    # the day-type split reads the building's zone; this synthetic building declares none
    monkeypatch.setattr(ri, "building_tz", lambda *_a, **_k: None)
    g = _building()
    cat = _run(
        facets.build_facet_catalogue(
            _sparql_json(g), BID, NS, [TEMPERATURE], modality_config={}, events_store=False
        )
    )
    schema = _schema(g)
    admission = cs.validate(ir, schema, catalogue=cat)
    assert admission.verdict == cs.ADMIT, admission.reason
    store = _NarrowStore()
    outcome = _run(
        execute(
            ir,
            admission,
            schema,
            adapter_getter=lambda key: store,
            catalogue=cat,
            sparql_exec=_sparql_json(g),
        )
    )
    dossier = build_dossier(ir, cp.decide(ir, admission), outcome, BID)
    text = render_answer(dossier) + "\n" + render_dossier_details(dossier)
    return outcome, dossier, text, store


def test_this_week_against_last_week_reads_each_period_whole_in_the_store(monkeypatch):
    ir = _period_plan(WEEKS, raw="Was it warmer this week than last week, by floor?")
    outcome, dossier, text, store = _end_to_end(ir, monkeypatch)
    result = outcome.periods
    overall = result.overall
    # weekday 20 x 120 h + weekend 25 x 48 h over 168 h: the store's mean of EVERY reading
    g1_last = round((20.0 * 120 + 25.0 * 48) / 168, 2)
    assert result.spaces[0].a_mean == g1_last and result.spaces[0].a_n == 168
    assert overall.n == 3, "U2 has no readings last week and U3 has no sensor"
    by = {g.label: g for g in result.groups}
    assert set(by) == {"Ground", "Upper"} and by["Upper"].n == 1
    assert result.n_not_compared == 2
    assert any("Room U2 (no readings last week)" == s for s in result.not_compared)
    assert any("Room U3 (no temperature sensor)" == s for s in result.not_compared)
    assert len(store.statements) == 2, "one GROUP BY per period, never a row fetch"
    assert all("GROUP BY" in s and "COUNT(" in s for s in store.statements)
    assert outcome.evidence == [] and outcome.score.ranked == []
    assert text.startswith("**Temperature, averaged across spaces: this week")
    assert "over 3 spaces with readings in both periods." in text
    assert "| Ground |" in text and "| Upper |" in text
    assert "this week is not over: its figure covers its readings so far" in text.replace(
        "This week", "this week"
    )
    assert "**Periods (building time):** last week — Mon 28 Sep 00:00 to Sun 04 Oct 23:59" in text
    assert "interpreted as current conditions" not in text
    assert numeric_guard(text, dossier) == [], "every number in the answer is in the dossier"


def test_weekdays_against_weekends_reduce_only_their_own_local_days(monkeypatch):
    window = (LAST[0], THIS[1])
    ir = _period_plan(
        [
            {"label": "weekdays", "start": window[0], "end": window[1], "day_type": "weekday"},
            {"label": "weekends", "start": window[0], "end": window[1], "day_type": "weekend"},
        ],
        group_by=None,
        raw="Is it warmer on weekdays than weekends?",
    )
    outcome, dossier, text, store = _end_to_end(ir, monkeypatch)
    result = outcome.periods
    g1 = next(s for s in result.spaces if s.label == "Room G1")
    # weekdays: 5 days at 20 and 5 at 21; weekends: 2 days at 25 and 2 at 26 (hourly)
    assert (g1.a_mean, g1.a_n) == (20.5, 240)
    assert (g1.b_mean, g1.b_n) == (25.5, 96)
    assert [w.days for w in result.periods] == [10, 4]
    assert len(store.statements) == 14, "one GROUP BY per local day of the window"
    assert result.groups == [] and result.overall.direction == "higher"
    assert "weekdays — " in text and "(10 days)" in text and "(4 days)" in text
    assert numeric_guard(text, dossier) == []


def test_the_highest_reading_names_the_space_that_holds_it(monkeypatch):
    ir = _period_plan(WEEKS, statistic=Statistic.MAX, group_by=None)
    outcome, dossier, text, _ = _end_to_end(ir, monkeypatch)
    overall = outcome.periods.overall
    assert (overall.a, overall.a_space) == (27.0, "Room G2")
    assert (overall.b, overall.b_space) == (29.0, "Room U1")
    assert "this week 29 °C (Room U1) against last week 27 °C (Room G2)" in text
    assert numeric_guard(text, dossier) == []


def test_a_reading_limit_is_named_as_not_applied_and_never_listed_as_applied(monkeypatch):
    """A limit on a reading does not say which period it is a limit in."""
    from orchestrator.services.deliberation.cqir import Constraint, Direction, ThresholdSource

    ir = _period_plan(WEEKS, group_by=None).model_copy(
        update={
            "constraints": [
                Constraint(
                    modality="temperature",
                    direction=Direction.ABOVE,
                    threshold=21.0,
                    threshold_source=ThresholdSource.USER,
                    source_phrase="rooms above 21 degrees",
                )
            ]
        }
    )
    outcome, dossier, text, _ = _end_to_end(ir, monkeypatch)
    assert outcome.periods.overall.n == 3, "no space was filtered by the limit"
    assert "'rooms above 21 degrees' was not applied" in text
    assert "Counted only where" not in text
    assert numeric_guard(text, dossier) == []


def test_a_period_comparison_on_an_unbacked_reading_is_declined():
    from orchestrator.services.deliberation.coverage_audit import SpaceCoverage

    sc = SpaceCoverage(space_iri=NS + "G1", label="G1", floor="G")
    sc.modalities = {"temperature": {"status": "unbacked", "uuid": "", "stored_at": ""}}
    schema = cs.BuildingCapabilitySchema(building_id=BID, namespace=NS, spaces=[sc], amenities=[])
    verdict = cs.validate(_period_plan(WEEKS), schema, catalogue=_catalogue())
    assert verdict.verdict == cs.DECLINE
    assert "no temperature sensor in this building has readings" in verdict.explanation


def test_a_period_plan_declares_no_current_conditions_assumption():
    texts = [a.text for a in cp.build_assumptions(_period_plan(WEEKS))]
    assert "interpreted as current conditions" not in texts
