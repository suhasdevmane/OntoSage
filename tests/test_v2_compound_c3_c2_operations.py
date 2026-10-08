# -*- coding: utf-8 -*-
"""v2, shapes C3 and C2 — operations that are not a ranking of spaces.

C3 (group -> aggregate -> rank): "which floor has the fewest people right now?", "which floor has
the largest gap between its warmest and coolest room?", "how evenly is CO2 spread across the
floors?", "which floor has the most bookable seats?". The answer ranks FLOORS by a figure each
floor is reduced to from its spaces, with the n behind every figure.

C2 (compare two facets of the same spaces): "what is the occupancy versus the capacity in each
room?", "is the building over its design occupancy right now?". The answer puts both figures side
by side per space, names the spaces missing either one (never imputed) and adds a building total
only when both figures ADD UP -- which code decides from their units, not the question's words.

Everything here runs OFFLINE: a stub LLM, and an rdflib graph served the way GraphDB serves the
live stack. No real building's namespace appears: the rules must hold for buildings never seen.
"""

from __future__ import annotations

import ast
import asyncio
import inspect
import json
import textwrap
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from typing import Any, Dict, List, Optional

import pytest
import rdflib

from orchestrator.services.deliberation import capability_schema as cs
from orchestrator.services.deliberation import clarify_policy as cp
from orchestrator.services.deliberation import compiler as C
from orchestrator.services.deliberation import facets
from orchestrator.services.deliberation import operations as ops
from orchestrator.services.deliberation.coverage_audit import CoverageAuditor, ModalitySpec
from orchestrator.services.deliberation.cqir import (
    CQIR,
    AggregateSpec,
    CompareRelation,
    CompareSpec,
    Constraint,
    DecisionKind,
    Direction,
    EventCriterion,
    FacetCriterion,
    FacetOperator,
    GroupBy,
    Hardness,
    SortOrder,
    SpatialQualifier,
    SpatialRelation,
    Statistic,
    ThresholdSource,
    TimeBasis,
    TimeSpec,
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
NS = "http://example.org/towerC#"
BID = "towerC"


def _run(coro):
    return asyncio.run(coro)


def _settings():
    """The CURRENT settings object (another test reloads shared.config, CAVEAT-1060)."""
    import shared.config

    return shared.config.settings


@pytest.fixture(autouse=True)
def _isolated(monkeypatch):
    facets.clear_cache()
    monkeypatch.setattr(_settings(), "ARBITER_FACETS_ENABLED", True, raising=False)
    monkeypatch.setenv("CQIR_COMPILE_CACHE", "false")
    yield
    facets.clear_cache()


# ── 1. the IR: back-compat and the fingerprint ───────────────────────────────────────────

#: Computed on 9fd0831 BEFORE any v2 edit -- the same values test_v2_compound_c1_facets pins.
V1_FINGERPRINT_FULL = "caf3d578953c18a2"
V1_FINGERPRINT_MINIMAL = "317d11553fdc878e"


def _v1_full() -> CQIR:
    return CQIR(
        decision=DecisionKind.SELECT_ONE,
        constraints=[
            Constraint(modality="noise", direction=Direction.MINIMIZE, source_phrase="quiet"),
            Constraint(
                modality="co2",
                direction=Direction.BELOW,
                hardness=Hardness.HARD,
                threshold=800.0,
                threshold_source=ThresholdSource.USER,
                weight=2.0,
                source_phrase="below 800 ppm",
            ),
        ],
        spatial=[SpatialQualifier(relation=SpatialRelation.ON_FLOOR, anchor="2")],
        time=TimeSpec(
            basis=TimeBasis.WINDOW,
            window_hours=24.0,
            resolved_start="2026-10-06 00:00:00",
            resolved_end="2026-10-06 23:59:59",
        ),
        event_criteria=[EventCriterion(kind="free_window", hours=2.0)],
        raw_query="a quiet room on floor 2 below 800 ppm free for 2 hours",
    )


def test_a_plan_without_an_operation_fingerprints_exactly_as_v1_did():
    assert _v1_full().plan_fingerprint() == V1_FINGERPRINT_FULL
    explicit = _v1_full().model_copy(update={"aggregate": None, "compare": None})
    assert explicit.plan_fingerprint() == V1_FINGERPRINT_FULL
    minimal = CQIR(
        decision=DecisionKind.SUPERLATIVE,
        constraints=[Constraint(modality="temperature", direction=Direction.MINIMIZE)],
        raw_query="coolest room",
    )
    assert minimal.plan_fingerprint() == V1_FINGERPRINT_MINIMAL
    assert minimal.operation is None


def _agg(**kw) -> AggregateSpec:
    base = dict(
        facet="sensor:occupancy",
        group_by=GroupBy.FLOOR,
        statistic=Statistic.SUM,
        order=SortOrder.ASC,
    )
    base.update(kw)
    return AggregateSpec(**base)


def test_an_operation_enters_the_fingerprint_by_behaviour_only():
    base = CQIR(decision=DecisionKind.AGGREGATE_RANK, aggregate=_agg(), raw_query="q")
    assert base.is_executable() and base.operation == "aggregate_rank"
    assert base.plan_fingerprint() != CQIR(decision=DecisionKind.AGGREGATE_RANK).plan_fingerprint()
    # presentation (how many rows, the phrase, the decision label) is not behaviour
    shown = base.model_copy(
        update={"aggregate": _agg(top_k=3, source_phrase="fewest people"), "raw_query": "other"}
    )
    assert shown.plan_fingerprint() == base.plan_fingerprint()
    # the statistic, the order and the grouping are
    for change in ({"order": SortOrder.DESC}, {"statistic": Statistic.MEAN}):
        other = base.model_copy(update={"aggregate": _agg(**change)})
        assert other.plan_fingerprint() != base.plan_fingerprint()
    # which facet is a and which is b is behaviour: a ratio inverts
    ab = CQIR(
        decision=DecisionKind.COMPARE_FACETS,
        compare=CompareSpec(facet_a="sensor:occupancy", facet_b="ttl:capacity"),
    )
    ba = CQIR(
        decision=DecisionKind.COMPARE_FACETS,
        compare=CompareSpec(facet_a="ttl:capacity", facet_b="sensor:occupancy"),
    )
    assert ab.operation == "compare_facets" and ab.is_executable()
    assert ab.plan_fingerprint() != ba.plan_fingerprint()


def test_the_v1_compile_vocabulary_and_parse_are_untouched():
    assert C._DECISIONS == {"select_one", "rank_all", "superlative", "list_matching"}
    assert set(C._cqir_schema()["properties"]["decision"]["enum"]) == C._DECISIONS
    assert "aggregate" not in C._cqir_schema()["properties"]
    raw = json.dumps(
        {
            "decision": "aggregate_rank",
            "constraints": [{"phrase": "people", "modality": "occupancy", "direction": "minimize"}],
            "aggregate": {"facet": "occupancy", "group_by": "floor", "statistic": "sum"},
        }
    )
    plan = C._parse_compiled(raw, "Which floor has the fewest people?", {"occupancy"})
    assert plan.decision == DecisionKind.SELECT_ONE, "an unknown decision to v1, as it always was"
    assert plan.aggregate is None and plan.operation is None


# ── 2. the compiler ─────────────────────────────────────────────────────────────────────

MODS = [
    ModalitySpec("occupancy", ["Occupancy_Count_Sensor"], sat={"unit": "persons"}),
    ModalitySpec("temperature", ["Air_Temperature_Sensor"], sat={"unit": "degC"}),
    ModalitySpec("co2", ["CO2_Sensor"], sat={"unit": "ppm"}),
    ModalitySpec("noise", ["Sound_Level_Sensor"], sat={"unit": "dB"}),
]
LOCATED = ONTO + "locatedInSpace"


def _facet(key, label, value_type, *, source="record", cls=None, pred=None, join=None, **kw):
    return facets.Facet(
        key=key,
        entity_type=kw.pop("entity_type", "space"),
        source_kind=source,
        label=label,
        value_type=value_type,
        record_class=cls,
        predicate=pred,
        join_predicate=join,
        status=kw.pop("status", "suitable"),
        coverage=kw.pop("coverage", 5),
        **kw,
    )


def _sensor(name, unit, terms=()):
    return _facet(
        f"sensor:{name}",
        name,
        "number",
        source="sensor",
        modality=name,
        unit=unit,
        lay_terms=tuple(terms),
    )


def _catalogue(extra=()) -> facets.FacetCatalogue:
    return facets.FacetCatalogue(
        [
            _sensor("occupancy", "persons", ("people", "crowded", "busy")),
            _sensor("temperature", "degC", ("warm", "cool")),
            _sensor("co2", "ppm", ("stuffy", "air")),
            _sensor("noise", "dB", ("quiet", "loud")),
            _facet(
                "record:WorkspaceProfile.seatCount",
                "seat count",
                "integer",
                cls="WorkspaceProfile",
                pred=ONTO + "seatCount",
                join=LOCATED,
                examples=("6", "12", "16"),
                lay_terms=("seats",),
            ),
            _facet(
                "record:WorkspaceProfile.isBookable",
                "is bookable",
                "boolean",
                cls="WorkspaceProfile",
                pred=ONTO + "isBookable",
                join=LOCATED,
                examples=("false", "true"),
                lay_terms=("bookable",),
            ),
            _facet(
                "record:WorkspaceProfile.floorNumber",
                "floor number",
                "integer",
                cls="WorkspaceProfile",
                pred=ONTO + "floorNumber",
                join=LOCATED,
            ),
            _facet(
                "ttl:capacity",
                "room capacity (design occupancy)",
                "integer",
                source="ttl",
                unit="persons",
                lay_terms=("capacity", "design occupancy"),
            ),
            _facet(
                "event:free_window",
                "free for a time window (no booking overlaps it)",
                "boolean",
                source="event",
                resolver="plan_executor._event_availability",
            ),
            _facet(
                "spatial:floor",
                "floor the space is on",
                "enum",
                source="spatial",
                examples=("Level 1", "Level 2"),
            ),
            _facet(
                "spatial:AccessibleRoute.allowMinutes",
                "allow minutes (route to the space)",
                "number",
                source="spatial",
                cls="AccessibleRoute",
                pred=ONTO + "allowMinutes",
                join=ONTO + "routeToSpace",
                unit="minutes",
            ),
            *extra,
        ]
    )


def _payload(decision, aggregate=None, compare=None, criteria=(), constraints=(), **extra):
    body = {
        "decision": decision,
        "constraints": list(constraints),
        "facet_criteria": list(criteria),
        "aggregate": aggregate,
        "compare": compare,
        "spatial": [],
        "time": {"basis": "now"},
        "unmapped": [],
        "inspect": [],
    }
    body.update(extra)
    return json.dumps(body)


def _recording_llm(*responses: str):
    prompts: List[str] = []
    queue = list(responses)

    async def call(prompt: str) -> str:
        prompts.append(prompt)
        return queue.pop(0) if len(queue) > 1 else queue[0]

    return call, prompts


def _compile(question, *responses, catalogue=None):
    llm, prompts = _recording_llm(*responses)
    out = _run(
        C.compile_query(question, MODS, llm, use_cache=False, catalogue=catalogue or _catalogue())
    )
    return out, prompts


FEWEST = "Which floor has the fewest people right now?"


def test_fewest_people_per_floor_compiles_to_a_sum_ranked_ascending():
    out, prompts = _compile(
        FEWEST,
        _payload(
            "aggregate_rank",
            aggregate={
                "phrase": "fewest people",
                "facet": "occupancy",
                "group_by": "floor",
                "statistic": "sum",
                "order": "asc",
            },
            # the model restating the operation as a preference -- dropped, not double-counted
            constraints=[
                {"phrase": "fewest people", "modality": "occupancy", "direction": "minimize"}
            ],
        ),
    )
    assert out.signals == [] and out.is_executable(), out.signals
    assert out.decision == DecisionKind.AGGREGATE_RANK and out.operation == "aggregate_rank"
    assert (out.aggregate.facet, out.aggregate.group_by, out.aggregate.statistic) == (
        "sensor:occupancy",
        GroupBy.FLOOR,
        Statistic.SUM,
    )
    assert out.aggregate.order == SortOrder.ASC
    assert out.constraints == [], "a preference restating the operation is not a second criterion"
    assert "aggregate_rank" in prompts[0] and '"aggregate": null' in prompts[0]


def test_the_largest_gap_and_how_evenly_compile_to_range_and_stdev():
    gap, _ = _compile(
        "Which floor has the largest gap between its warmest and coolest room?",
        _payload(
            "aggregate_rank",
            aggregate={
                "facet": "temperature",
                "group_by": "floors",
                "statistic": "spread",
                "order": "descending",
            },
        ),
    )
    assert (gap.aggregate.facet, gap.aggregate.statistic, gap.aggregate.order) == (
        "sensor:temperature",
        Statistic.RANGE,
        SortOrder.DESC,
    )
    evenly, _ = _compile(
        "How evenly is CO2 distributed across the floors?",
        _payload(
            "aggregate_rank",
            aggregate={"facet": "sensor:co2", "group_by": "floor", "statistic": "stdev"},
        ),
    )
    assert evenly.signals == []
    assert (evenly.aggregate.statistic, evenly.aggregate.order) == (Statistic.STDEV, SortOrder.DESC)


def test_most_bookable_seats_reads_a_record_facet_and_its_filter_is_hard():
    out, prompts = _compile(
        "Which floor has the most bookable seats?",
        _payload(
            "aggregate_rank",
            aggregate={
                "facet": "record:WorkspaceProfile.seatCount",
                "group_by": "floor",
                "statistic": "sum",
                "order": "desc",
            },
            criteria=[
                {
                    "phrase": "bookable",
                    "facet": "record:WorkspaceProfile.isBookable",
                    "operator": "is_true",
                    "hardness": "soft",
                }
            ],
        ),
    )
    assert out.signals == [], out.signals
    assert out.aggregate.facet == "record:WorkspaceProfile.seatCount"
    (bookable,) = out.facet_criteria
    assert bookable.hardness == Hardness.HARD, "a filter narrows which spaces count; never soft"
    assert bookable.record_group == "WorkspaceProfile"
    assert "record:WorkspaceProfile.seatCount | seat count | integer |" in prompts[0]


def test_a_missing_order_comes_from_the_question_and_a_contradicted_one_is_a_signal():
    no_order = {"facet": "occupancy", "group_by": "floor", "statistic": "sum"}
    out, _ = _compile(FEWEST, _payload("aggregate_rank", aggregate=no_order))
    assert out.aggregate.order == SortOrder.ASC, "'fewest' says which end"
    wrong = dict(no_order, order="desc")
    out, _ = _compile(FEWEST, _payload("aggregate_rank", aggregate=wrong))
    assert out.aggregate is None and not out.is_executable()
    assert any(s.kind == "invalid_operation" and "smallest" in s.note for s in out.signals)
    # "most even" is the SMALLEST deviation: the words are not read for a spread
    even, _ = _compile(
        "Which floor is the most evenly heated?",
        _payload(
            "aggregate_rank",
            aggregate={
                "facet": "temperature",
                "group_by": "floor",
                "statistic": "stdev",
                "order": "asc",
            },
        ),
    )
    assert even.signals == [] and even.aggregate.order == SortOrder.ASC


@pytest.mark.parametrize(
    "question,aggregate,kind,needle",
    [
        (
            "Which floor has the highest total temperature?",
            {"facet": "temperature", "group_by": "floor", "statistic": "sum", "order": "desc"},
            "invalid_operation",
            "level measured in",
        ),
        (
            "Which floor has the most rooms that are too warm?",
            {
                "facet": "temperature",
                "group_by": "floor",
                "statistic": "count_above",
                "threshold": 26,
                "order": "desc",
            },
            "invalid_operation",
            "needs the limit as a number",
        ),
        (
            "Which floor has the most lockers?",
            {"facet": "record:Locker.count", "group_by": "floor", "statistic": "sum"},
            "unmapped_term",
            "not a facet this building holds",
        ),
        (
            "Which floor is most often free?",
            {"facet": "event:free_window", "group_by": "floor", "statistic": "count"},
            "invalid_operation",
            "check over a time window",
        ),
        (
            "Which floor has the most floors?",
            {"facet": "spatial:floor", "group_by": "floor", "statistic": "count"},
            "invalid_operation",
            "how spaces are grouped",
        ),
        (
            "Which floor has the shortest walk?",
            {
                "facet": "spatial:AccessibleRoute.allowMinutes",
                "group_by": "floor",
                "statistic": "min",
            },
            "invalid_operation",
            "where the route starts",
        ),
        (
            "Which is the busiest?",
            {"facet": "occupancy", "statistic": "sum", "order": "desc"},
            "invalid_operation",
            "what to group the spaces by",
        ),
        (
            "Which floor has the highest average?",
            {"group_by": "floor", "statistic": "mean"},
            "invalid_operation",
            "the mean of what",
        ),
        (
            "Which floor adds up the most floor numbers?",
            {
                "facet": "record:WorkspaceProfile.floorNumber",
                "group_by": "floor",
                "statistic": "sum",
            },
            "invalid_operation",
            "no recorded unit",
        ),
    ],
)
def test_an_invalid_aggregate_is_a_signal_never_a_guess(question, aggregate, kind, needle):
    out, _ = _compile(question, _payload("aggregate_rank", aggregate=aggregate))
    assert out.aggregate is None and not out.is_executable()
    assert any(s.kind == kind and needle in s.note for s in out.signals), out.signals


def test_a_stated_limit_counts_and_a_missing_grouping_is_read_from_the_question():
    out, _ = _compile(
        "How many rooms on each floor are above 1000 ppm of CO2?",
        _payload(
            "aggregate_rank",
            aggregate={"facet": "co2", "statistic": "count_above", "threshold": "1000 ppm"},
        ),
    )
    assert out.signals == []
    assert (out.aggregate.statistic, out.aggregate.threshold, out.aggregate.group_by) == (
        Statistic.COUNT_ABOVE,
        1000.0,
        GroupBy.FLOOR,
    )


def test_an_operation_cannot_be_forecast_and_cannot_be_two_operations():
    forecast = json.loads(
        _payload(
            "aggregate_rank",
            aggregate={"facet": "occupancy", "group_by": "floor", "statistic": "sum"},
        )
    )
    forecast["time"] = {"basis": "forecast", "horizon_hours": 24, "phrase": "tomorrow"}
    out, _ = _compile("Which floor will be busiest tomorrow?", json.dumps(forecast))
    assert not out.is_executable()
    assert any("forecast of a figure per group" in s.note for s in out.signals)
    both, _ = _compile(
        "Which floor is fullest, and occupancy versus capacity?",
        _payload(
            "aggregate_rank",
            aggregate={"facet": "occupancy", "group_by": "floor", "statistic": "sum"},
            compare={"facet_a": "occupancy", "facet_b": "ttl:capacity", "relation": "ratio"},
        ),
    )
    assert both.aggregate is None and both.compare is None and not both.is_executable()


def test_occupancy_versus_capacity_compiles_to_a_ratio_of_one_unit():
    out, _ = _compile(
        "What is the current occupancy versus the capacity in each room?",
        _payload(
            "compare_facets",
            compare={"facet_a": "occupancy", "facet_b": "ttl:capacity", "relation": "ratio"},
        ),
    )
    assert out.signals == [] and out.decision == DecisionKind.COMPARE_FACETS
    assert (out.compare.facet_a, out.compare.facet_b, out.compare.relation) == (
        "sensor:occupancy",
        "ttl:capacity",
        CompareRelation.RATIO,
    )
    assert out.compare.requested_relation is None and out.compare.total is False


def test_is_the_building_over_its_design_occupancy_compiles_to_exceeds_with_a_total():
    out, _ = _compile(
        "Is the building over its design occupancy right now?",
        _payload(
            "compare_facets",
            compare={
                "facet_a": "people",
                "facet_b": "ttl:capacity",
                "relation": "exceeds",
                "total": True,
            },
        ),
    )
    assert out.signals == []
    assert out.compare.facet_a == "sensor:occupancy", "a lay word resolves to the modality"
    assert (out.compare.relation, out.compare.total) == (CompareRelation.EXCEEDS, True)


def test_counts_of_different_things_are_shown_as_a_difference_and_levels_are_refused():
    seats, _ = _compile(
        "Are there more people than seats in each room?",
        _payload(
            "compare_facets",
            compare={
                "facet_a": "occupancy",
                "facet_b": "record:WorkspaceProfile.seatCount",
                "relation": "exceeds",
            },
        ),
    )
    assert seats.signals == []
    assert seats.compare.relation == CompareRelation.DIFFERENCE
    assert seats.compare.requested_relation == CompareRelation.EXCEEDS
    mixed, _ = _compile(
        "Compare temperature with CO2 in each room",
        _payload(
            "compare_facets",
            compare={"facet_a": "temperature", "facet_b": "co2", "relation": "ratio"},
        ),
    )
    assert mixed.compare is None and not mixed.is_executable()
    assert any("different quantities" in s.note for s in mixed.signals)
    itself, _ = _compile(
        "occupancy versus occupancy",
        _payload("compare_facets", compare={"facet_a": "occupancy", "facet_b": "occupancy"}),
    )
    assert itself.compare is None and any("compared with itself" in s.note for s in itself.signals)


def test_warmer_than_setpoint_needs_a_setpoint_facet_and_this_catalogue_has_none():
    """The example question, against a catalogue holding no setpoint: a signal, never a guess."""
    payload = _payload(
        "compare_facets",
        compare={"facet_a": "temperature", "facet_b": "setpoint", "relation": "exceeds"},
    )
    out, _ = _compile("Which rooms are warmer than their setpoint?", payload, payload)
    assert out.compare is None and not out.is_executable()
    assert any(s.kind == "unmapped_term" and "setpoint" in s.note for s in out.signals)
    verdict = cs.validate(out, _ad_schema(), catalogue=_catalogue())
    assert verdict.verdict == cs.CLARIFY


def test_a_hypothetical_setpoint_in_the_same_unit_is_compared_by_exceeds():
    """Only IF a building recorded one: same unit, so 'exceeds' means something."""
    setpoint = _facet(
        "ttl:temperatureSetpoint",
        "temperature setpoint",
        "number",
        source="ttl",
        pred=NS + "temperatureSetpoint",
        unit="degC",
    )
    out, _ = _compile(
        "Which rooms are warmer than their setpoint?",
        _payload(
            "compare_facets",
            compare={
                "facet_a": "temperature",
                "facet_b": "ttl:temperatureSetpoint",
                "relation": "exceeds",
            },
        ),
        catalogue=_catalogue(extra=[setpoint]),
    )
    assert out.signals == [] and out.compare.relation == CompareRelation.EXCEEDS


def test_the_v2_schema_covers_every_field_the_operation_parsers_read():
    """Derived like the v1 schema: from the parser, never from the prompt prose."""

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
    assert reads(C._parse_operation, "data") <= set(props)
    agg_keys = reads(C._aggregate_item, "raw")
    assert agg_keys and agg_keys <= set(props["aggregate"]["properties"])
    cmp_keys = reads(C._compare_item, "raw")
    assert cmp_keys and cmp_keys <= set(props["compare"]["properties"])
    assert set(props["decision"]["enum"]) == {d.value for d in DecisionKind}
    assert set(props["aggregate"]["properties"]["statistic"]["enum"]) == {
        s.value for s in Statistic
    }
    assert set(props["compare"]["properties"]["relation"]["enum"]) == {
        r.value for r in CompareRelation
    }
    assert "enum" not in props["aggregate"]["properties"]["facet"], "facet keys stay open"


# ── 3. the arithmetic, pure ─────────────────────────────────────────────────────────────


def _sv(iri, group, value, present=True, reason="", flag=None):
    return ops.SpaceValue(
        space_iri=NS + iri,
        label=f"Room {iri}",
        groups=[group] if group else [],
        value=value,
        flag=flag,
        present=present,
        reason=reason,
    )


#: Three floors; F2 has one space with no reading; one space is on no floor at all.
VALUES = [
    _sv("a1", "F1", 20.0),
    _sv("a2", "F1", 24.0),
    _sv("a3", "F1", 22.0),
    _sv("b1", "F2", 21.0),
    _sv("b2", "F2", None, present=False, reason="no reading"),
    _sv("c1", "F3", 23.0),
    _sv("c2", "F3", 23.0),
    _sv("c3", "F3", 26.0),
    _sv("z9", "", 30.0),
]
LABELS = {"F1": "Floor 1", "F2": "Floor 2", "F3": "Floor 3"}


def _aggregate(statistic, order=SortOrder.DESC, threshold=None, values=VALUES, **kw):
    spec = AggregateSpec(
        facet="sensor:temperature",
        group_by=GroupBy.FLOOR,
        statistic=statistic,
        order=order,
        threshold=threshold,
    )
    return ops.aggregate(spec, values, label="temperature", unit="°C", group_labels=LABELS, **kw)


def test_each_statistic_per_group_with_its_n():
    by = {g.key: g for g in _aggregate(Statistic.MEAN).groups}
    assert (by["F1"].value, by["F1"].n, by["F2"].n, by["F2"].n_missing) == (22.0, 3, 1, 1)
    assert by["F2"].missing == ["Room b2 (no reading)"]
    assert by["F3"].value == 24.0
    ranges = {g.key: g for g in _aggregate(Statistic.RANGE).groups}
    assert (ranges["F1"].value, ranges["F1"].low_space, ranges["F1"].high_space) == (
        4.0,
        "Room a1",
        "Room a2",
    )
    assert ranges["F2"].value is None and "only one space" in ranges["F2"].note
    stdev = {g.key: g.value for g in _aggregate(Statistic.STDEV).groups}
    assert stdev["F1"] == 1.63 and stdev["F3"] == 1.41 and stdev["F2"] is None
    mins = {g.key: (g.value, g.low_space) for g in _aggregate(Statistic.MIN).groups}
    assert mins["F3"] == (23.0, "Room c1"), "a tie on the extreme goes to the first name"
    above = {g.key: g.value for g in _aggregate(Statistic.COUNT_ABOVE, threshold=22.5).groups}
    assert above == {"F1": 1.0, "F2": 0.0, "F3": 3.0}
    below = {g.key: g.value for g in _aggregate(Statistic.COUNT_BELOW, threshold=22.5).groups}
    assert below == {"F1": 2.0, "F2": 1.0, "F3": 0.0}
    counted = {g.key: g.value for g in _aggregate(Statistic.COUNT).groups}
    assert counted == {"F1": 3.0, "F2": 1.0, "F3": 3.0}


def test_groups_rank_by_figure_ties_break_on_the_floor_number_and_the_tie_is_reported():
    result = _aggregate(Statistic.COUNT, order=SortOrder.DESC)
    assert [g.key for g in result.groups] == ["F1", "F3", "F2"], "3, 3 by floor number, then 1"
    assert result.tied_top == ["Floor 1", "Floor 3"]
    assert [g.rank for g in result.groups] == [1, 2, 3]
    asc = _aggregate(Statistic.MEAN, order=SortOrder.ASC)
    assert [g.key for g in asc.groups] == ["F2", "F1", "F3"] and asc.tied_top == ["Floor 2"]
    assert result.unplaced == ["Room z9"] and result.n_unplaced == 1
    assert result.n_spaces == 7, "the unplaced space and the space with no reading are not counted"


def test_dispersion_is_stated_across_groups_and_across_spaces():
    d = _aggregate(Statistic.STDEV).dispersion
    assert (d.groups_n, d.groups_low, d.groups_low_label, d.groups_high) == (
        3,
        21.0,
        "Floor 2",
        24.0,
    )
    assert d.groups_stdev == 1.25
    assert (d.spaces_n, d.spaces_low, d.spaces_low_label, d.spaces_high_label) == (
        7,
        20.0,
        "Room a1",
        "Room c3",
    )
    assert d.spaces_stdev == 1.83
    assert _aggregate(Statistic.MEAN).dispersion is None, "dispersion is for a spread question"


def test_what_adds_up_is_decided_by_the_unit_not_the_question():
    cat = _catalogue()
    for key in ("sensor:occupancy", "ttl:capacity", "record:WorkspaceProfile.seatCount"):
        assert ops.additive(cat.get(key))[0], key
    for key in ("sensor:temperature", "sensor:co2", "record:WorkspaceProfile.floorNumber"):
        adds_up, why = ops.additive(cat.get(key))
        assert not adds_up and why, key
    assert not ops.additive(cat.get("record:WorkspaceProfile.isBookable"))[0]


def test_compare_fit_follows_the_units():
    cat = _catalogue()
    occupancy, capacity = cat.get("sensor:occupancy"), cat.get("ttl:capacity")
    seats, temp, co2 = (
        cat.get("record:WorkspaceProfile.seatCount"),
        cat.get("sensor:temperature"),
        cat.get("sensor:co2"),
    )
    assert ops.compare_fit(occupancy, capacity, CompareRelation.RATIO).relation == (
        CompareRelation.RATIO
    )
    downgraded = ops.compare_fit(occupancy, seats, CompareRelation.RATIO)
    assert downgraded.relation == CompareRelation.DIFFERENCE and "difference" in downgraded.note
    assert ops.compare_fit(temp, co2, CompareRelation.DIFFERENCE).refusal
    kelvin = _facet("ttl:k", "setpoint", "number", source="ttl", pred=NS + "k", unit="K")
    converted = ops.compare_fit(temp, kelvin, CompareRelation.EXCEEDS)
    assert converted.relation == CompareRelation.EXCEEDS
    mul, add = converted.convert_b
    assert round(300.0 * mul + add, 2) == 26.85, "b is converted into a's unit"


def _row(iri, a, b, reason=""):
    return ops.ComparisonRow(space_iri=NS + iri, label=f"Room {iri}", a=a, b=b, reason=reason)


def test_a_space_missing_one_side_is_listed_not_imputed_and_the_total_covers_only_both():
    rows = [
        _row("r1", 5.0, 12.0),
        _row("r2", 9.0, 6.0),
        _row("r3", 2.0, None, reason="room capacity: no design occupancy recorded"),
        _row("r4", None, 20.0),
    ]
    spec = CompareSpec(
        facet_a="sensor:occupancy",
        facet_b="ttl:capacity",
        relation=CompareRelation.EXCEEDS,
        total=True,
    )
    out = ops.compare(spec, rows, label_a="occupancy", label_b="capacity", adds_up=True)
    assert [r.label for r in out.rows] == ["Room r2", "Room r1"], "the exceeding space first"
    assert out.rows[0].exceeds and out.rows[0].percent == 150.0
    assert (out.n_comparable, out.n_exceeding) == (2, 1)
    apart = {r.label: r for r in out.not_comparable}
    assert set(apart) == {"Room r3", "Room r4"}
    assert apart["Room r3"].b is None and apart["Room r3"].ratio is None, "never filled in"
    assert "no occupancy recorded" in apart["Room r4"].reason
    t = out.total
    assert (t.n, t.a, t.b, t.percent, t.exceeds) == (2, 14.0, 18.0, 77.78, False)
    assert (t.a_only_n, t.a_only_sum, t.b_only_n, t.b_only_sum) == (1, 2.0, 1, 20.0)
    no_total = ops.compare(spec, rows, label_a="occupancy", label_b="capacity", adds_up=False)
    assert no_total.total is None, "a total only when both figures add up"


# ── 4. a synthetic three-floor building, served the way the live stack serves it ─────────


def _sparql_json(g: rdflib.Graph, log: Optional[List[str]] = None):
    async def sparql_exec(query: str) -> Dict[str, Any]:
        if log is not None:
            log.append(query)
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
@prefix xsd: <http://www.w3.org/2001/XMLSchema#> .
@prefix o: <http://ontosage.org/capabilities#> .
@prefix hbco: <http://ontosage.org/hbco#> .
@prefix x: <http://example.org/towerC#> .

brick:Space rdfs:subClassOf brick:Location .
brick:Room rdfs:subClassOf brick:Space .
brick:Floor rdfs:subClassOf brick:Location .
o:Record a owl:Class .
o:WorkspaceProfile rdfs:subClassOf o:Record ; rdfs:label "Workspace profile" .
hbco:roomCapacity a owl:DatatypeProperty ; rdfs:label "room capacity"@en .

x:L1 a brick:Floor ; rdfs:label "Level 1" .
x:L2 a brick:Floor ; rdfs:label "Level 2" .
x:L3 a brick:Floor ; rdfs:label "Level 3" .
"""

#: (room, floor, occupancy or None = no sensor, temperature, (seats or None, bookable) or None =
#: no workspace profile, design capacity or None)
ROOMS = [
    ("R11", "L1", 5.0, 21.0, (10, True), 12),
    ("R12", "L1", 3.0, 23.5, (6, False), 8),
    ("R13", "L1", None, 22.0, None, 20),
    ("R21", "L2", 2.0, 22.0, (12, True), 10),
    ("R22", "L2", 1.0, 21.8, (8, True), None),
    ("R31", "L3", 4.0, 20.0, (16, True), 4),
    ("R32", "L3", 9.0, 25.0, (None, True), 6),
    ("R33", "L3", 0.0, 21.5, None, 30),
]


def _building() -> rdflib.Graph:
    lines = [_TBOX]
    for room, floor, occupancy, temperature, profile, capacity in ROOMS:
        lines.append(
            f'x:{room} a brick:Room ; rdfs:label "Room {room[1:]}" ; brick:isPartOf x:{floor} .\n'
            f"x:T{room} a brick:Air_Temperature_Sensor ; brick:hasLocation x:{room} ;\n"
            f'  ref:hasExternalReference [ ref:hasTimeseriesId "t-{room}" ; '
            "ref:storedAt x:temperature_data ] .\n"
        )
        if occupancy is not None:
            lines.append(
                f"x:O{room} a brick:Occupancy_Count_Sensor ; brick:hasLocation x:{room} ;\n"
                f'  ref:hasExternalReference [ ref:hasTimeseriesId "o-{room}" ; '
                "ref:storedAt x:occupancy_data ] .\n"
            )
        if profile is not None:
            seats, bookable = profile
            seat_text = f"o:seatCount {seats} ; " if seats is not None else ""
            lines.append(
                f'x:ws{room} a o:WorkspaceProfile ; o:recordId "WS-{room}" ; {seat_text}'
                f"o:isBookable {str(bookable).lower()} ; o:locatedInSpace x:{room} .\n"
            )
        if capacity is not None:
            lines.append(f"x:{room} hbco:roomCapacity {capacity} .\n")
    g = rdflib.Graph()
    g.parse(data="\n".join(lines), format="turtle")
    return g


OCCUPANCY = ModalitySpec(
    "occupancy", ["Occupancy_Count_Sensor"], sat={"unit": "persons", "scope": "room"}
)
TEMPERATURE = ModalitySpec(
    "temperature", ["Air_Temperature_Sensor"], sat={"unit": "degC", "scope": "room"}
)
LIVE_MODS = [OCCUPANCY, TEMPERATURE]


@dataclass
class _Result:
    success: bool = True
    data: List[Dict[str, Any]] = field(default_factory=list)
    error: str = ""


class _Series:
    """Twelve constant readings per uuid, for exactly the uuids a query asks for."""

    def __init__(self):
        self.values: Dict[str, float] = {}
        for room, _floor, occupancy, temperature, _p, _c in ROOMS:
            self.values[f"t-{room}"] = temperature
            if occupancy is not None:
                self.values[f"o-{room}"] = occupancy

    def build_timeseries_query(self, uuids, ts_col, start, end, limit=1000):
        return "UUIDS " + ",".join(uuids)

    async def execute_query(self, sql):
        now = datetime.utcnow()
        rows = []
        for uuid in sql.split(" ", 1)[1].split(","):
            for i in range(12):
                rows.append(
                    {
                        "timestamp": (now - timedelta(minutes=12 - i)).strftime(
                            "%Y-%m-%d %H:%M:%S"
                        ),
                        "uuid": uuid,
                        "value": self.values[uuid],
                    }
                )
        return _Result(data=rows)


def _adapters():
    series = _Series()
    return lambda key: series


def _schema(g):
    spaces = _run(CoverageAuditor(_sparql_json(g), LIVE_MODS).audit(NS))
    return cs.BuildingCapabilitySchema(building_id=BID, namespace=NS, spaces=spaces, amenities=[])


def _ad_schema():
    from orchestrator.services.deliberation.coverage_audit import SpaceCoverage

    spaces = []
    for room in ("R1", "R2"):
        sc = SpaceCoverage(space_iri=NS + room, label=room, floor="L1")
        sc.modalities = {
            "occupancy": {"status": "present", "uuid": f"o-{room}", "stored_at": "t"},
            "temperature": {"status": "present", "uuid": f"t-{room}", "stored_at": "t"},
        }
        spaces.append(sc)
    return cs.BuildingCapabilitySchema(building_id=BID, namespace=NS, spaces=spaces, amenities=[])


def _real_catalogue(g):
    return _run(
        facets.build_facet_catalogue(
            _sparql_json(g), BID, NS, LIVE_MODS, modality_config={}, events_store=False
        )
    )


def _end_to_end(ir: CQIR, g=None):
    g = g or _building()
    cat = _real_catalogue(g)
    schema = _schema(g)
    admission = cs.validate(ir, schema, catalogue=cat)
    assert admission.verdict == cs.ADMIT, admission.reason
    outcome = _run(
        execute(
            ir,
            admission,
            schema,
            adapter_getter=_adapters(),
            catalogue=cat,
            sparql_exec=_sparql_json(g),
        )
    )
    decision = cp.decide(ir, admission)
    dossier = build_dossier(ir, decision, outcome, BID)
    text = render_answer(dossier) + "\n" + render_dossier_details(dossier)
    return outcome, dossier, text


def _aggregate_plan(raw, **spec):
    return CQIR(
        decision=DecisionKind.AGGREGATE_RANK,
        aggregate=AggregateSpec(**spec),
        raw_query=raw,
    )


def test_the_catalogue_of_the_synthetic_building_carries_the_facets_the_operations_read():
    cat = _real_catalogue(_building())
    for key in (
        "sensor:occupancy",
        "sensor:temperature",
        "ttl:capacity",
        "record:WorkspaceProfile.seatCount",
        "record:WorkspaceProfile.isBookable",
    ):
        assert cat.get(key) is not None and cat.get(key).at_least("populated"), key
    assert ops.facet_unit(cat.get("sensor:occupancy")) == ops.facet_unit(cat.get("ttl:capacity"))


def test_which_floor_has_the_fewest_people_end_to_end():
    ir = _aggregate_plan(
        FEWEST,
        facet="sensor:occupancy",
        group_by=GroupBy.FLOOR,
        statistic=Statistic.SUM,
        order=SortOrder.ASC,
    )
    outcome, dossier, text = _end_to_end(ir)
    agg = outcome.aggregate
    by = {g.label: g for g in agg.groups}
    assert [g.label for g in agg.groups] == ["Level 2", "Level 1", "Level 3"]
    assert (by["Level 2"].value, by["Level 2"].n) == (3.0, 2)
    assert (by["Level 1"].value, by["Level 1"].n, by["Level 1"].n_missing) == (8.0, 2, 1)
    assert by["Level 1"].missing == ["Room 13 (no occupancy sensor)"], "named, not imputed"
    assert (by["Level 3"].value, by["Level 3"].n) == (13.0, 3)
    assert "**Level 2 has the lowest total occupancy: 3 people**, over 2 spaces with a value." in (
        text
    )
    assert "| Level 1 | 8 people | 2 | 1 |" in text
    assert "**Without a value, so not counted:** Level 1 — Room 13 (no occupancy sensor)." in text
    assert outcome.evidence and all(e.modality == "occupancy" for e in outcome.evidence)
    assert outcome.score.ranked == [], "floors are ranked, not spaces"
    assert "weighted equally" not in text, "an operation weighs no preferences"
    assert numeric_guard(text, dossier) == [], "every number in the answer is in the dossier"


def test_the_largest_gap_between_warmest_and_coolest_room_end_to_end():
    ir = _aggregate_plan(
        "Which floor has the largest gap between its warmest and coolest room?",
        facet="sensor:temperature",
        group_by=GroupBy.FLOOR,
        statistic=Statistic.RANGE,
        order=SortOrder.DESC,
    )
    outcome, dossier, text = _end_to_end(ir)
    top = outcome.aggregate.groups[0]
    assert (top.label, top.value, top.high_space, top.low_space, top.n) == (
        "Level 3",
        5.0,
        "Room 32",
        "Room 31",
        3,
    )
    assert [g.value for g in outcome.aggregate.groups] == [5.0, 2.5, 0.2]
    assert (
        "**Level 3 has the largest spread in temperature: 5 °C** — from 20 °C (Room 31) to "
        "25 °C (Room 32), over 3 spaces with a value." in text
    )
    assert "**Across 8 individual spaces:** from 20 °C (Room 31) to 25 °C (Room 32)" in text
    assert numeric_guard(text, dossier) == []


def test_how_evenly_a_reading_is_spread_states_both_dispersions_with_their_n():
    ir = _aggregate_plan(
        "How evenly is the temperature spread across the floors?",
        facet="sensor:temperature",
        group_by=GroupBy.FLOOR,
        statistic=Statistic.STDEV,
        order=SortOrder.DESC,
    )
    outcome, dossier, text = _end_to_end(ir)
    d = outcome.aggregate.dispersion
    assert (d.groups_n, d.spaces_n) == (3, 8)
    assert (d.spaces_low, d.spaces_high) == (20.0, 25.0)
    assert [g.label for g in outcome.aggregate.groups][0] == "Level 3", "least even first"
    assert "**How evenly temperature is spread across the floors:**" in text
    assert "**Across 3 floors:** averages run from" in text
    assert "**Across 8 individual spaces:**" in text
    assert "Level 3 is the least even: standard deviation 2.09 °C, over 3 spaces" in text
    assert numeric_guard(text, dossier) == []


def test_counting_spaces_above_a_stated_limit_ties_break_on_the_floor_number():
    ir = _aggregate_plan(
        "How many rooms on each floor are above 21.9 degrees?",
        facet="sensor:temperature",
        group_by=GroupBy.FLOOR,
        statistic=Statistic.COUNT_ABOVE,
        threshold=21.9,
        order=SortOrder.DESC,
    )
    outcome, dossier, text = _end_to_end(ir)
    assert [(g.label, g.value, g.n) for g in outcome.aggregate.groups] == [
        ("Level 1", 2.0, 3),
        ("Level 2", 1.0, 2),
        ("Level 3", 1.0, 3),
    ]
    assert (
        "**Level 1 has the most spaces with temperature above 21.9 °C: 2** (of 3 spaces with a "
        "value)." in text
    )
    assert numeric_guard(text, dossier) == []


def test_the_most_bookable_seats_sums_only_bookable_records_and_names_what_it_could_not_count():
    ir = CQIR(
        decision=DecisionKind.AGGREGATE_RANK,
        facet_criteria=[
            FacetCriterion(
                facet="record:WorkspaceProfile.isBookable",
                operator=FacetOperator.IS_TRUE,
                hardness=Hardness.HARD,
                record_group="WorkspaceProfile",
                source_phrase="bookable",
            )
        ],
        aggregate=AggregateSpec(
            facet="record:WorkspaceProfile.seatCount",
            group_by=GroupBy.FLOOR,
            statistic=Statistic.SUM,
            order=SortOrder.DESC,
        ),
        raw_query="Which floor has the most bookable seats?",
    )
    outcome, dossier, text = _end_to_end(ir)
    by = {g.label: g for g in outcome.aggregate.groups}
    assert [g.label for g in outcome.aggregate.groups] == ["Level 2", "Level 3", "Level 1"]
    assert (by["Level 2"].value, by["Level 2"].n) == (20.0, 2)
    assert (by["Level 1"].value, by["Level 1"].n) == (10.0, 1), "Room 12 is not bookable"
    assert by["Level 1"].unverified == ["Room 13 (is bookable (workspace profile))"]
    assert (by["Level 3"].value, by["Level 3"].n, by["Level 3"].n_missing) == (16.0, 1, 1)
    assert by["Level 3"].missing == ["Room 32 (not recorded)"], "bookable, no seat count"
    assert by["Level 3"].unverified == ["Room 33 (is bookable (workspace profile))"]
    excluded = {e.label: e.reason for e in outcome.ledger.excluded}
    assert "Room 12" in excluded and "WS-R12" in excluded["Room 12"]
    assert "**Level 2 has the highest total seat count (workspace profile): 20**" in text
    assert "**Counted only where:** is bookable (workspace profile): yes." in text
    assert "**Could not be verified on what you asked for, so not counted:**" in text
    assert "Level 1 — Room 13 (is bookable (workspace profile))" in text
    assert numeric_guard(text, dossier) == []


def test_occupancy_versus_capacity_per_room_names_the_rooms_it_cannot_compare():
    ir = CQIR(
        decision=DecisionKind.COMPARE_FACETS,
        compare=CompareSpec(
            facet_a="sensor:occupancy", facet_b="ttl:capacity", relation=CompareRelation.RATIO
        ),
        raw_query="What is the current occupancy versus the capacity in each room?",
    )
    outcome, dossier, text = _end_to_end(ir)
    cmp = outcome.comparison
    assert [(r.label, r.percent) for r in cmp.rows] == [
        ("Room 32", 150.0),
        ("Room 31", 100.0),
        ("Room 11", 41.67),
        ("Room 12", 37.5),
        ("Room 21", 20.0),
        ("Room 33", 0.0),
    ]
    apart = {r.label: r.reason for r in cmp.not_comparable}
    assert set(apart) == {"Room 13", "Room 22"}
    assert "no occupancy sensor" in apart["Room 13"]
    assert "no design occupancy recorded" in apart["Room 22"]
    assert all(r.a is None or r.b is None for r in cmp.not_comparable), "nothing imputed"
    assert cmp.total is None, "per room was asked; no total"
    assert (
        "**Occupancy as a share of room capacity (design occupancy), for the 6 spaces with both "
        "figures** — highest: Room 32 at 150%." in text
    )
    assert "| Room 32 | 9 people | 6 people | 150% |" in text
    assert "**Not comparable (2):**" in text
    assert numeric_guard(text, dossier) == []


def test_is_the_building_over_its_design_occupancy_totals_only_the_rooms_with_both():
    ir = CQIR(
        decision=DecisionKind.COMPARE_FACETS,
        compare=CompareSpec(
            facet_a="sensor:occupancy",
            facet_b="ttl:capacity",
            relation=CompareRelation.EXCEEDS,
            total=True,
        ),
        raw_query="Is the building over its design occupancy right now?",
    )
    outcome, dossier, text = _end_to_end(ir)
    cmp = outcome.comparison
    assert (cmp.n_comparable, cmp.n_exceeding) == (6, 1)
    t = cmp.total
    assert (t.n, t.a, t.b, t.percent, t.exceeds) == (6, 23.0, 70.0, 32.86, False)
    assert (t.a_only_n, t.a_only_sum, t.b_only_n, t.b_only_sum) == (1, 1.0, 1, 20.0)
    assert (
        "**Over the 6 spaces with both figures: occupancy totals 23 people against room "
        "capacity (design occupancy) 70 people (32.86%) — occupancy is not above room capacity "
        "(design occupancy).**" in text
    )
    assert "**Left out of the total:** 1 space with occupancy but no room capacity" in text
    assert "| Room 32 | 9 people | 6 people | 150% | yes |" in text
    assert numeric_guard(text, dossier) == []


def test_a_total_of_a_level_is_not_formed_and_the_answer_says_why():
    setpoint_graph = _building()
    setpoint_graph.parse(
        data=(
            "@prefix x: <http://example.org/towerC#> .\n"
            "x:R11 x:temperatureSetpoint 22.0 . x:R12 x:temperatureSetpoint 22.0 .\n"
        ),
        format="turtle",
    )
    cat = _real_catalogue(setpoint_graph)
    assert cat.get("ttl:temperatureSetpoint") is not None
    ir = CQIR(
        decision=DecisionKind.COMPARE_FACETS,
        compare=CompareSpec(
            facet_a="sensor:temperature",
            facet_b="ttl:temperatureSetpoint",
            relation=CompareRelation.DIFFERENCE,
            total=True,
        ),
        raw_query="Is the building warmer than its setpoints?",
    )
    outcome, dossier, text = _end_to_end(ir, setpoint_graph)
    cmp = outcome.comparison
    assert cmp.total is None
    assert any("no building total is formed" in n for n in cmp.notes)
    assert [(r.label, r.difference) for r in cmp.rows] == [("Room 12", 1.5), ("Room 11", -1.0)]
    assert numeric_guard(text, dossier) == []


def test_an_operation_on_a_facet_nobody_records_is_declined_naming_it():
    g = _building()
    g.parse(
        data=(
            "@prefix o: <http://ontosage.org/capabilities#> .\n"
            "@prefix owl: <http://www.w3.org/2002/07/owl#> .\n"
            "@prefix rdfs: <http://www.w3.org/2000/01/rdf-schema#> .\n"
            "o:deskCount a owl:DatatypeProperty ; rdfs:domain o:WorkspaceProfile .\n"
        ),
        format="turtle",
    )
    cat = _real_catalogue(g)
    assert cat.get("record:WorkspaceProfile.deskCount").status == "linked", "no value anywhere"
    ir = _aggregate_plan(
        "Which floor has the most desks?",
        facet="record:WorkspaceProfile.deskCount",
        group_by=GroupBy.FLOOR,
        statistic=Statistic.SUM,
    )
    verdict = cs.validate(ir, _schema(g), catalogue=cat)
    assert verdict.verdict == cs.DECLINE
    assert "I can't compute that" in verdict.explanation
    assert (
        "Desk count (workspace profile) cannot be read: it is linked to spaces but no value is "
        "recorded." in verdict.explanation
    )
    assert "record:" not in verdict.explanation


def test_an_operation_on_an_unbacked_modality_is_declined():
    schema = _ad_schema()
    for space in schema.spaces:
        space.modalities["occupancy"]["status"] = "unbacked"
    ir = _aggregate_plan(
        FEWEST, facet="sensor:occupancy", group_by=GroupBy.FLOOR, statistic=Statistic.SUM
    )
    verdict = cs.validate(ir, schema, catalogue=_catalogue())
    assert verdict.verdict == cs.DECLINE
    assert "no occupancy sensor in this building has readings" in verdict.explanation


def test_a_preference_inside_an_operation_is_named_as_not_applied():
    ir = CQIR(
        decision=DecisionKind.AGGREGATE_RANK,
        constraints=[
            Constraint(modality="temperature", direction=Direction.MINIMIZE, source_phrase="cool")
        ],
        aggregate=AggregateSpec(
            facet="sensor:occupancy",
            group_by=GroupBy.FLOOR,
            statistic=Statistic.SUM,
            order=SortOrder.DESC,
        ),
        raw_query="Which floor has the most people in cool rooms?",
    )
    outcome, dossier, text = _end_to_end(ir)
    assert any("'cool' was not applied" in n for n in outcome.aggregate.notes)
    assert "'cool' was not applied: a preference cannot decide which spaces are counted." in text
    assert numeric_guard(text, dossier) == []


def test_a_stated_reading_limit_filters_the_spaces_an_operation_counts():
    ir = CQIR(
        decision=DecisionKind.AGGREGATE_RANK,
        constraints=[
            Constraint(
                modality="temperature",
                direction=Direction.ABOVE,
                threshold=21.9,
                threshold_source=ThresholdSource.USER,
                source_phrase="warmer than 21.9",
            )
        ],
        aggregate=AggregateSpec(
            facet="sensor:occupancy",
            group_by=GroupBy.FLOOR,
            statistic=Statistic.SUM,
            order=SortOrder.DESC,
        ),
        raw_query="Which floor has the most people in rooms warmer than 21.9 degrees?",
    )
    outcome, dossier, text = _end_to_end(ir)
    by = {g.label: g for g in outcome.aggregate.groups}
    # L1: R12 (3) passes, R11 (21.0) fails, R13 (22.0) passes but has no occupancy sensor
    assert (by["Level 1"].value, by["Level 1"].n, by["Level 1"].n_missing) == (3.0, 1, 1)
    # L3: R32 (25.0, 9 people) passes
    assert (by["Level 3"].value, by["Level 3"].n) == (9.0, 1)
    excluded = {e.label for e in outcome.ledger.excluded}
    assert {"Room 11", "Room 31", "Room 33", "Room 22"} <= excluded
    assert "**Counted only where:** temperature above 21.9." in text
    assert numeric_guard(text, dossier) == []


def test_the_operation_figures_are_recorded_for_the_claim_binder():
    from orchestrator.services.evidence import computed

    computed.reset()
    ir = _aggregate_plan(
        FEWEST,
        facet="sensor:occupancy",
        group_by=GroupBy.FLOOR,
        statistic=Statistic.SUM,
        order=SortOrder.ASC,
    )
    _end_to_end(ir)
    figures = computed.recorded().get("deliberate_operation") or {}
    assert figures.get("L2 sum") == 3.0 and figures.get("L1 n") == 2.0
    computed.reset()


def test_the_plan_hash_and_fingerprint_include_the_operation():
    asc = _aggregate_plan(
        FEWEST,
        facet="sensor:occupancy",
        group_by=GroupBy.FLOOR,
        statistic=Statistic.SUM,
        order=SortOrder.ASC,
    )
    desc = asc.model_copy(
        update={"aggregate": asc.aggregate.model_copy(update={"order": SortOrder.DESC})}
    )
    a, _, _ = _end_to_end(asc)
    b, _, _ = _end_to_end(desc)
    assert a.plan_fingerprint == asc.plan_fingerprint() != desc.plan_fingerprint()
    assert a.plan_hash != b.plan_hash


# ── 5. the policy layer around an operation ─────────────────────────────────────────────


def test_absorb_unmapped_counts_an_operation_as_something_mapped():
    from orchestrator.services.deliberation.cqir import AmbiguitySignal

    ir = _aggregate_plan(
        FEWEST, facet="sensor:occupancy", group_by=GroupBy.FLOOR, statistic=Statistic.SUM
    ).model_copy(update={"signals": [AmbiguitySignal(kind="unmapped_term", phrase="disco")]})
    _, dropped, decline = cp.absorb_unmapped(ir)
    assert (dropped, decline) == (["disco"], True), "v1: no constraint means decline"
    kept, dropped, decline = cp.absorb_unmapped(ir, facets=True)
    assert (dropped, decline, kept.signals) == (["disco"], False, [])


def test_an_operation_declares_no_scoring_band_and_no_weighting():
    ir = CQIR(
        decision=DecisionKind.AGGREGATE_RANK,
        constraints=[Constraint(modality="temperature", direction=Direction.MINIMIZE)],
        aggregate=_agg(),
        raw_query="q",
    )
    texts = [a.text for a in cp.build_assumptions(ir)]
    assert not any("band" in t or "weighted" in t for t in texts), texts
    v1 = [a.text for a in cp.build_assumptions(ir.model_copy(update={"aggregate": None}))]
    assert any("weighted equally" in t for t in v1), "a v1 plan is unchanged"


def test_a_lay_word_inside_an_operation_is_not_mistaken_for_a_kind_of_room():
    """ "the gap between the warmest and coolest room": "coolest" is the temperature being
    reduced, not a room type the answer failed to narrow to. A real room type still is."""
    raw = "Which floor has the largest gap between its warmest and coolest room?"
    gap = _aggregate_plan(raw, facet="sensor:temperature", statistic=Statistic.RANGE)
    assert cp.unbound_space_type(gap) is None
    meeting = _aggregate_plan(
        "Which floor has the most meeting rooms?", statistic=Statistic.COUNT, facet=None
    )
    assert cp.unbound_space_type(meeting) == "meeting room"
    v1 = CQIR(decision=DecisionKind.SUPERLATIVE, raw_query=raw)
    assert cp.unbound_space_type(v1) == "coolest room", "a v1 plan is exactly as it was"


def test_a_question_too_broad_to_read_declines_in_the_operations_words(monkeypatch):
    from orchestrator.services.deliberation import plan_executor

    monkeypatch.setattr(plan_executor, "MAX_FETCH_ROWS", 10)
    ir = _aggregate_plan(
        FEWEST,
        facet="sensor:occupancy",
        group_by=GroupBy.FLOOR,
        statistic=Statistic.SUM,
        order=SortOrder.ASC,
    )
    outcome, dossier, text = _end_to_end(ir)
    assert outcome.aggregate is None and dossier.operation == "aggregate_rank"
    assert text.startswith("I couldn't work out those figures for this request.")
    assert "fetch budget" in text and "Narrow it to a floor" in text
    assert "rank any spaces" not in text
    assert numeric_guard(text, dossier) == []


def test_one_person_is_one_person():
    assert ops.with_unit(1.0, "people") == "1 person"
    assert ops.with_unit(2.0, "people") == "2 people"
    assert ops.with_unit(21.456, "°C") == "21.46 °C"
    assert ops.with_unit(None, "people") == ""


def test_a_refused_operation_says_why_in_the_clarify_question():
    out, _ = _compile(
        "Which floor has the highest total temperature?",
        _payload(
            "aggregate_rank",
            aggregate={"facet": "temperature", "group_by": "floor", "statistic": "sum"},
        ),
    )
    verdict = cs.validate(out, _ad_schema(), catalogue=_catalogue())
    assert verdict.verdict == cs.CLARIFY
    assert "level measured in" in verdict.question.question


# ── repairs found live, 2026-10-08 ──────────────────────────────────────────────────────


def test_a_facet_named_by_its_field_alone_resolves_when_exactly_one_matches():
    """Live: occupancy versus 'seatCount' was thrown away as 'not a facet this building holds'."""
    out, _ = _compile(
        "Are any meeting rooms over their seating capacity right now?",
        _payload(
            "compare_facets",
            compare={"facet_a": "occupancy", "facet_b": "seatCount", "relation": "exceeds"},
        ),
    )
    assert out.signals == [] and out.decision == DecisionKind.COMPARE_FACETS, out.signals
    assert (out.compare.facet_a, out.compare.facet_b) == (
        "sensor:occupancy",
        "record:WorkspaceProfile.seatCount",
    )


def test_a_field_name_two_facets_share_is_refused_not_guessed():
    twin = _facet(
        "record:BookingProfile.seatCount",
        "seat count",
        "integer",
        cls="BookingProfile",
        pred=ONTO + "bookingSeats",
        join=LOCATED,
    )
    out, _ = _compile(
        "Are any meeting rooms over their seating capacity right now?",
        _payload(
            "compare_facets",
            compare={"facet_a": "occupancy", "facet_b": "seatCount", "relation": "exceeds"},
        ),
        catalogue=_catalogue(extra=(twin,)),
    )
    assert out.compare is None
    assert any("not a facet this building holds" in s.note for s in out.signals)


def test_an_amount_that_adds_up_is_ranked_by_its_total_even_when_the_model_says_max():
    """Live: 'which floor has the most people' compiled to max -- the busiest single room."""
    out, _ = _compile(
        "Which floor has the most people in it right now?",
        _payload(
            "aggregate_rank",
            aggregate={
                "facet": "occupancy",
                "group_by": "floor",
                "statistic": "max",
                "order": "desc",
            },
        ),
    )
    assert out.signals == [], out.signals
    assert (out.aggregate.statistic, out.aggregate.order) == (Statistic.SUM, SortOrder.DESC)


def test_a_question_about_one_space_per_group_keeps_its_max_and_a_level_is_never_summed():
    busiest, _ = _compile(
        "Which floor has the busiest room right now?",
        _payload(
            "aggregate_rank",
            aggregate={"facet": "occupancy", "group_by": "floor", "statistic": "max"},
        ),
    )
    assert busiest.aggregate.statistic == Statistic.MAX
    warmest, _ = _compile(
        "Which floor has the warmest room?",
        _payload(
            "aggregate_rank",
            aggregate={"facet": "temperature", "group_by": "floor", "statistic": "max"},
        ),
    )
    assert warmest.aggregate.statistic == Statistic.MAX  # a level: never turned into a sum


def test_a_count_of_an_amount_that_adds_up_is_its_total_unless_spaces_are_counted():
    """Live (low-effort compile): 'most people' compiled to a COUNT of the spaces reporting it."""
    people, _ = _compile(
        "Which floor has the most people in it right now?",
        _payload(
            "aggregate_rank",
            aggregate={"facet": "occupancy", "group_by": "floor", "statistic": "count"},
        ),
    )
    assert people.aggregate.statistic == Statistic.SUM
    rooms, _ = _compile(
        "Which floor has the most occupied rooms?",
        _payload(
            "aggregate_rank",
            aggregate={"facet": "occupancy", "group_by": "floor", "statistic": "count"},
        ),
    )
    assert rooms.aggregate.statistic == Statistic.COUNT


def test_the_count_of_unnamed_spaces_a_comparison_prints_is_backed_for_the_guard():
    """Live, 2026-10-08: "how does the number of people on each floor compare with its capacity"
    computed a comparison over 195 spaces, 154 of them without a capacity figure. The answer
    named 8 and said "and 146 more" -- and the numeric guard, which held 154 but not 146, replaced
    the whole answer with the suppression text."""
    from orchestrator.services.deliberation import dossier as D

    rows = [_row(f"r{i}", 1.0, None, reason="no design occupancy recorded") for i in range(154)]
    rows += [_row("ok1", 5.0, 12.0), _row("ok2", 9.0, 6.0)]
    spec = CompareSpec(
        facet_a="sensor:occupancy", facet_b="ttl:capacity", relation=CompareRelation.RATIO
    )
    cmp = ops.compare(spec, rows, label_a="occupancy", label_b="capacity", adds_up=True)
    dossier = D.EvidenceDossier(
        building_id=BID, raw_query="occupancy versus capacity", decision="compare_facets"
    )
    dossier.comparison = cmp
    prose = "**Not comparable (154):** Room r0 (no design occupancy recorded); and 146 more."
    assert D.numeric_guard(prose, dossier) == []
    assert D.numeric_guard("and 999 more", dossier) == ["999"], "an unbacked figure still trips"


def test_a_constraint_that_states_a_comparison_is_compiled_as_that_comparison():
    """Live, 3 compiles of 3 (2026-10-08): 'over their seating capacity' came back as a list with
    the constraint 'occupancy above', phrase 'occupancy > seatCount'."""
    out, _ = _compile(
        "Are any meeting rooms over their seating capacity right now?",
        _payload(
            "list_matching",
            constraints=[
                {"phrase": "occupancy > seatCount", "modality": "occupancy", "direction": "above"}
            ],
        ),
    )
    assert out.decision == DecisionKind.COMPARE_FACETS, (out.decision, out.signals)
    assert (out.compare.facet_a, out.compare.facet_b) == (
        "sensor:occupancy",
        "record:WorkspaceProfile.seatCount",
    )
    assert out.constraints == [], "the comparison is not also a preference"


def test_a_plain_preference_is_not_lifted_into_a_comparison():
    out, _ = _compile(
        "Find a quiet room",
        _payload(
            "select_one",
            constraints=[{"phrase": "quiet", "modality": "noise", "direction": "minimize"}],
        ),
    )
    assert out.compare is None and [c.modality for c in out.constraints] == ["noise"]


def test_a_count_whose_figure_is_a_kind_counts_spaces_of_that_kind():
    kind = _facet(
        "spatial:space_kind",
        "kind of space",
        "enum",
        source="spatial",
        examples=("Meeting Room", "Office"),
    )
    cat = _catalogue(extra=(kind,))
    counted, _ = _compile(
        "Which floor has the most meeting rooms?",
        _payload(
            "aggregate_rank",
            aggregate={"facet": "spatial:space_kind", "group_by": "floor", "statistic": "count"},
            criteria=[
                {"phrase": "meeting rooms", "facet": "spatial:space_kind", "operator": "equals",
                 "value": "Meeting Room"}
            ],
        ),
        catalogue=cat,
    )
    assert counted.signals == [], counted.signals
    assert counted.aggregate.facet is None and counted.aggregate.statistic == Statistic.COUNT
    unsaid, _ = _compile(
        "Which floor has the most meeting rooms?",
        _payload(
            "aggregate_rank",
            aggregate={"facet": "spatial:space_kind", "group_by": "floor", "statistic": "count"},
        ),
        catalogue=cat,
    )
    assert unsaid.aggregate is None and any("which kind of space" in s.note for s in unsaid.signals)
