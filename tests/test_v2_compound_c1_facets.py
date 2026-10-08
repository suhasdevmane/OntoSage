# -*- coding: utf-8 -*-
"""v2, shape C1 — multi-criteria selection over facets of the graph (P3 + P4).

ARBITER v1 compiled a question to SENSED modalities only, so "a quiet room with at least 12
seats and a ready projector" lost everything but "quiet" to an unmapped term. v2 compiles to
the facet catalogue (records, TTL properties, capacity, bookings), admits each criterion on
its own, reads facet values in code, and explains every value with the record it came from.

Everything here runs OFFLINE: a stub LLM, and an rdflib graph served the way GraphDB serves
the live stack. Several tests pin v1 BYTE FOR BYTE against values computed on the unmodified
9fd0831 code before any v2 edit -- the flag-off arm of the thesis ablation must be v1.
"""

from __future__ import annotations

import asyncio
import hashlib
import json
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from typing import Any, Dict, List

import pytest
import rdflib

from orchestrator.services.datasource_registry import derive_point_uuid
from orchestrator.services.deliberation import capability_schema as cs
from orchestrator.services.deliberation import clarify_policy as cp
from orchestrator.services.deliberation import compiler as C
from orchestrator.services.deliberation import facet_resolvers as fr
from orchestrator.services.deliberation import facets
from orchestrator.services.deliberation.coverage_audit import CoverageAuditor, ModalitySpec
from orchestrator.services.deliberation.cqir import (
    CQIR,
    AmbiguitySignal,
    Constraint,
    DecisionKind,
    Direction,
    EventCriterion,
    FacetCriterion,
    FacetOperator,
    Hardness,
    SpatialQualifier,
    SpatialRelation,
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
#: No real building's namespace: the rules must hold for buildings never seen.
NS = "http://example.org/towerZ#"
BID = "towerZ"


def _run(coro):
    return asyncio.run(coro)


def _settings():
    """The CURRENT settings object. Another test reloads shared.config (CAVEAT-1060), so a
    module-level import here could patch an object the code under test no longer reads."""
    import shared.config

    return shared.config.settings


@pytest.fixture(autouse=True)
def _isolated(monkeypatch):
    facets.clear_cache()
    monkeypatch.setattr(_settings(), "ARBITER_FACETS_ENABLED", True, raising=False)
    monkeypatch.setenv("CQIR_COMPILE_CACHE", "false")
    yield
    facets.clear_cache()


# ── 1. back-compat, pinned against the unmodified v1 code ────────────────────────────────

#: Computed on 9fd0831 BEFORE any v2 edit (scratchpad baseline script), then hardcoded.
V1_FINGERPRINT_FULL = "caf3d578953c18a2"
V1_FINGERPRINT_MINIMAL = "317d11553fdc878e"
V1_PROMPT_SHA256 = "a8ff2d020f7790cf0b771eed87d1ef1b27cdbd9e321be96afca18eecd4c3ed57"
V1_SCHEMA_SHA256 = "dd512906a2878c4feeccab23c4e6a76cb1d23d542d5b7569c72504ada8dd9ca8"
V1_CACHE_KEY = "cqir_compile:5de6a2d0c0394595c5fbcc6b9e17e6e87d6b5d83ded1bc7e49a9f37adb13dceb"
V1_RENDER_SHA256 = "37c1f785edeeef6416f89647cf451608715b2aafb67428c0f34cb1615d47ad09"


def _v1_full() -> CQIR:
    return CQIR(
        decision=DecisionKind.SELECT_ONE,
        constraints=[
            Constraint(
                modality="noise",
                direction=Direction.MINIMIZE,
                hardness=Hardness.SOFT,
                weight=1.0,
                source_phrase="quiet",
            ),
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


def test_a_facet_free_plan_fingerprints_exactly_as_v1_did():
    assert _v1_full().plan_fingerprint() == V1_FINGERPRINT_FULL
    minimal = CQIR(
        decision=DecisionKind.SUPERLATIVE,
        constraints=[Constraint(modality="temperature", direction=Direction.MINIMIZE)],
        raw_query="coolest room",
    )
    assert minimal.plan_fingerprint() == V1_FINGERPRINT_MINIMAL
    explicit = _v1_full().model_copy(update={"facet_criteria": []})
    assert explicit.plan_fingerprint() == V1_FINGERPRINT_FULL


def test_facet_criteria_enter_the_fingerprint_by_behaviour_not_by_label():
    def plan(group_a, group_b, value):
        return _v1_full().model_copy(
            update={
                "facet_criteria": [
                    FacetCriterion(
                        facet="record:AVReadiness.avComponentKind",
                        operator=FacetOperator.EQUALS,
                        value=value,
                        hardness=Hardness.HARD,
                        record_group=group_a,
                    ),
                    FacetCriterion(
                        facet="record:AVReadiness.recordStatus",
                        operator=FacetOperator.EQUALS,
                        value="ready",
                        hardness=Hardness.HARD,
                        record_group=group_b,
                    ),
                ]
            }
        )

    one = plan("AVReadiness:g1", "AVReadiness:g1", "Projector")
    renamed = plan("AVReadiness:projector", "AVReadiness:projector", "projector")
    split = plan("AVReadiness:a", "AVReadiness:b", "Projector")
    assert one.plan_fingerprint() != V1_FINGERPRINT_FULL
    assert one.plan_fingerprint() == renamed.plan_fingerprint()
    assert one.plan_fingerprint() != split.plan_fingerprint(), "one record vs two records"


MODS = [
    ModalitySpec(name="noise", brick_classes=["Sound_Pressure_Level_Sensor"]),
    ModalitySpec(name="co2", brick_classes=["CO2_Sensor"]),
    ModalitySpec(name="temperature", brick_classes=["Air_Temperature_Sensor"]),
    ModalitySpec(name="occupancy", brick_classes=["Occupancy_Count_Sensor"]),
]
SAMPLE = "Find a quiet room with at least 12 seats and a ready projector"


def _recording_llm(*responses: str):
    prompts: List[str] = []
    queue = list(responses)

    async def call(prompt: str) -> str:
        prompts.append(prompt)
        return queue.pop(0) if len(queue) > 1 else queue[0]

    return call, prompts


def test_flag_off_sends_the_v1_prompt_byte_for_byte_even_given_a_catalogue(monkeypatch):
    monkeypatch.setattr(_settings(), "ARBITER_FACETS_ENABLED", False, raising=False)
    llm, prompts = _recording_llm('{"decision": "select_one", "constraints": [], "unmapped": []}')
    out = _run(C.compile_query(SAMPLE, MODS, llm, use_cache=False, catalogue=_manual_catalogue()))
    assert hashlib.sha256(prompts[0].encode("utf-8")).hexdigest() == V1_PROMPT_SHA256
    assert out.facet_criteria == []


def test_no_catalogue_is_the_v1_compile_whatever_the_flag():
    llm, prompts = _recording_llm('{"decision": "select_one", "constraints": [], "unmapped": []}')
    _run(C.compile_query(SAMPLE, MODS, llm, use_cache=False))
    assert hashlib.sha256(prompts[0].encode("utf-8")).hexdigest() == V1_PROMPT_SHA256


def test_the_v1_schema_and_cache_key_are_untouched(monkeypatch):
    schema = json.dumps(C._cqir_schema(), sort_keys=True).encode("utf-8")
    assert hashlib.sha256(schema).hexdigest() == V1_SCHEMA_SHA256
    monkeypatch.setattr(_settings(), "MODEL_PROVIDER", "local", raising=False)
    monkeypatch.setattr(_settings(), "OLLAMA_MODEL", "gpt-oss:20b", raising=False)
    monkeypatch.setattr(_settings(), "STRUCTURED_PLAN_ENABLED", False, raising=False)
    key = C._compile_cache_key("Find a quiet room with a projector", MODS[:2])
    assert key == V1_CACHE_KEY


def test_the_cache_key_carries_the_catalogue_fingerprint():
    cat = _manual_catalogue()
    v1 = C._compile_cache_key(SAMPLE, MODS)
    v2 = C._compile_cache_key(SAMPLE, MODS, catalogue=cat)
    assert v1 != v2
    regraded = facets.FacetCatalogue(
        [
            f if f.key != "record:WorkspaceProfile.seatCount" else _replace(f, status="populated")
            for f in cat
        ]
    )
    assert C._compile_cache_key(SAMPLE, MODS, catalogue=regraded) != v2


def _replace(facet, **changes):
    from dataclasses import replace

    return replace(facet, **changes)


# ── 2. the compiler ─────────────────────────────────────────────────────────────────────


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


LOCATED = ONTO + "locatedInSpace"


def _manual_catalogue(extra=()) -> facets.FacetCatalogue:
    return facets.FacetCatalogue(
        [
            _facet(
                "sensor:noise",
                "noise",
                "number",
                source="sensor",
                modality="noise",
                lay_terms=("quiet", "noisy", "loud"),
                unit="dB",
            ),
            _facet(
                "record:WorkspaceProfile.seatCount",
                "seat count",
                "integer",
                cls="WorkspaceProfile",
                pred=ONTO + "seatCount",
                join=LOCATED,
                examples=("6", "12", "16", "30"),
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
            ),
            _facet(
                "record:AVReadiness.avComponentKind",
                "av component kind",
                "enum",
                cls="AVReadiness",
                pred=ONTO + "avComponentKind",
                join=LOCATED,
                examples=("Display", "Microphone", "Projector"),
                class_terms=("projector", "display"),
            ),
            _facet(
                "record:AVReadiness.recordStatus",
                "record status",
                "enum",
                cls="AVReadiness",
                pred=ONTO + "recordStatus",
                join=LOCATED,
                examples=("degraded", "failed", "ready"),
                class_terms=("projector", "display"),
            ),
            _facet(
                "record:WorkspaceProfile.daylightAspect",
                "daylight aspect",
                "text",
                cls="WorkspaceProfile",
                pred=ONTO + "daylightAspect",
                join=LOCATED,
                examples=("East-facing", "Internal"),
                lay_terms=("daylight",),
            ),
            _facet(
                "ttl:capacity",
                "room capacity (design occupancy)",
                "integer",
                source="ttl",
                unit="persons",
                lay_terms=("capacity",),
                examples=("12", "30"),
            ),
            _facet(
                "event:free_window",
                "free for a time window (no booking overlaps it)",
                "boolean",
                source="event",
                lay_terms=("free", "available"),
                resolver="plan_executor._event_availability",
                status="linked",
                coverage=0,
            ),
            _facet(
                "spatial:floor",
                "floor the space is on",
                "enum",
                source="spatial",
                examples=("Level 1", "Level 2"),
                lay_terms=("floor", "level"),
            ),
            *extra,
        ]
    )


def _payload(criteria=(), constraints=(), unmapped=(), inspect=(), decision="select_one"):
    return json.dumps(
        {
            "decision": decision,
            "constraints": list(constraints),
            "facet_criteria": list(criteria),
            "spatial": [],
            "time": {"basis": "now"},
            "unmapped": list(unmapped),
            "inspect": list(inspect),
        }
    )


QUIET = {"phrase": "quiet", "modality": "noise", "direction": "minimize", "hardness": "soft"}
SEATS = {
    "phrase": "at least 12 seats",
    "facet": "record:WorkspaceProfile.seatCount",
    "operator": "at_least",
    "value": 12,
    "hardness": "hard",
}
PROJECTOR = {
    "phrase": "a ready projector",
    "facet": "record:AVReadiness.avComponentKind",
    "operator": "equals",
    "value": "projector",
    "hardness": "hard",
    "record_group": "g1",
}
READY = {
    "phrase": "a ready projector",
    "facet": "record:AVReadiness.recordStatus",
    "operator": "equals",
    "value": "Ready",
    "hardness": "hard",
    "record_group": "g1",
}


def _compile(question, *responses, catalogue=None, value_reader=None):
    llm, prompts = _recording_llm(*responses)
    out = _run(
        C.compile_query(
            question,
            MODS,
            llm,
            use_cache=False,
            catalogue=catalogue or _manual_catalogue(),
            value_reader=value_reader,
        )
    )
    return out, prompts


def test_the_facet_prompt_lists_recorded_facets_and_keeps_the_modality_list():
    _, prompts = _compile(SAMPLE, _payload())
    prompt = prompts[0]
    assert (
        C._modality_lines(MODS) in prompt
    ), "sensor modalities are listed exactly as v1 lists them"
    assert "record:WorkspaceProfile.seatCount | seat count | integer | - |" in prompt
    assert '"Display", "Microphone", "Projector"' in prompt, "an enum shows its whole value set"
    assert "| sensor:noise |" not in prompt, "sensors stay in the modality list only"


def test_facet_criteria_are_validated_normalised_and_grouped():
    out, _ = _compile(
        SAMPLE + ", free for two hours, on Level 1",
        _payload(
            criteria=[
                SEATS,
                PROJECTOR,
                READY,
                {
                    "phrase": "free for two hours",
                    "facet": "event:free_window",
                    "operator": "free_for",
                    "value": 2,
                    "hardness": "hard",
                },
                {
                    "phrase": "on Level 1",
                    "facet": "spatial:floor",
                    "operator": "equals",
                    "value": "level 1",
                    "hardness": "hard",
                },
                {
                    "phrase": "quiet",
                    "facet": "sensor:noise",
                    "operator": "minimize",
                    "hardness": "soft",
                },
            ]
        ),
    )
    assert out.signals == [] and out.is_executable()
    by = {(c.facet, c.operator): c for c in out.facet_criteria}
    seats = by[("record:WorkspaceProfile.seatCount", FacetOperator.AT_LEAST)]
    assert (seats.value, seats.hardness, seats.threshold_source) == (
        12.0,
        Hardness.HARD,
        ThresholdSource.USER,
    )
    kind = by[("record:AVReadiness.avComponentKind", FacetOperator.EQUALS)]
    status = by[("record:AVReadiness.recordStatus", FacetOperator.EQUALS)]
    assert (kind.value, status.value) == ("Projector", "ready"), "the building's own spelling"
    assert kind.record_group == status.record_group == "AVReadiness:g1"
    assert seats.record_group == "WorkspaceProfile"
    free = by[("event:free_window", FacetOperator.FREE_FOR)]
    assert (free.value, free.threshold_source) == (2.0, ThresholdSource.USER)
    # a sensor facet becomes the legacy Constraint; a single hard floor the v1 floor scope
    assert [(c.modality, c.direction) for c in out.constraints] == [("noise", Direction.MINIMIZE)]
    assert [(q.relation, q.anchor) for q in out.spatial] == [(SpatialRelation.ON_FLOOR, "level 1")]


def test_criteria_on_one_record_class_share_a_group_when_the_model_names_none():
    unnamed = [dict(PROJECTOR, record_group=""), dict(READY, record_group=None), SEATS]
    out, _ = _compile(SAMPLE, _payload(criteria=unnamed))
    groups = {c.facet: c.record_group for c in out.facet_criteria}
    assert groups["record:AVReadiness.avComponentKind"] == "AVReadiness"
    assert groups["record:AVReadiness.recordStatus"] == "AVReadiness"
    assert groups["record:WorkspaceProfile.seatCount"] == "WorkspaceProfile"


@pytest.mark.parametrize(
    "item,kind,needle",
    [
        (dict(SEATS, facet="record:Room.hasProjector"), "unmapped_term", "not a facet"),
        (dict(SEATS, operator="equals"), "invalid_facet", "does not apply"),
        (dict(READY, value="working"), "invalid_facet", "recorded: degraded, failed, ready"),
        (dict(SEATS, operator="teleport"), "invalid_facet", "not an operator"),
        (
            {
                "phrase": "east",
                "facet": "record:WorkspaceProfile.daylightAspect",
                "operator": "contains",
                "value": "",
            },
            "invalid_facet",
            "needs the text",
        ),
    ],
)
def test_an_invalid_facet_criterion_is_a_signal_never_a_guess(item, kind, needle):
    out, _ = _compile(SAMPLE, _payload(criteria=[item]), _payload(criteria=[item]))
    assert not out.facet_criteria
    assert any(s.kind == kind and needle in s.note for s in out.signals), out.signals
    assert not out.is_executable()


def test_a_number_the_question_does_not_state_is_never_used():
    big = {
        "phrase": "a big room",
        "facet": "ttl:capacity",
        "operator": "at_least",
        "value": 20,
        "hardness": "soft",
    }
    out, _ = _compile("Which is the biggest room with a projector?", _payload(criteria=[big]))
    (criterion,) = out.facet_criteria
    assert (criterion.operator, criterion.value, criterion.threshold_source) == (
        FacetOperator.MAXIMIZE,
        None,
        ThresholdSource.DEFAULT,
    )
    stated, _ = _compile("A room for twelve people", _payload(criteria=[dict(big, value=12)]))
    assert stated.facet_criteria[0].value == 12.0, "a number word the question states counts"


def test_an_availability_check_the_fold_already_made_is_kept_once():
    free = {
        "phrase": "free for 2 hours",
        "facet": "event:free_window",
        "operator": "free_for",
        "value": 2,
        "hardness": "hard",
    }
    out, _ = _compile(
        "a quiet room free for 2 hours", _payload(criteria=[free], constraints=[QUIET])
    )
    assert [e.kind for e in out.event_criteria] == ["free_window"]
    assert out.facet_criteria == [], "the deterministic fold owns this phrase, as in v1"


def test_the_v2_schema_covers_every_field_the_facet_parser_reads():
    """Derived like the v1 schema: from the parser, never from the prompt prose."""
    import ast
    import inspect
    import textwrap

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

    schema = C._cqir_schema(facets=True)
    props = schema["properties"]
    top = reads(C._apply_facets, "data")
    assert top and not top - set(props)
    item_keys = reads(C._facet_item, "item")
    assert item_keys and not item_keys - set(props["facet_criteria"]["items"]["properties"])
    assert set(props["facet_criteria"]["items"]["properties"]["operator"]["enum"]) == {
        o.value for o in FacetOperator
    }
    assert "enum" not in props["facet_criteria"]["items"]["properties"]["facet"]


# ── 3. bounded inspection ────────────────────────────────────────────────────────────────


def test_inspection_adds_a_facet_and_recompiles_exactly_once(monkeypatch):
    monkeypatch.setattr(C, "FACET_SHORTLIST_K", 0)  # the first prompt shows no facet at all
    first = _payload(constraints=[QUIET], unmapped=["a ready projector"])
    second = _payload(constraints=[QUIET], criteria=[PROJECTOR, READY])
    out, prompts = _compile(SAMPLE, first, second)
    assert len(prompts) == 2, "one recompile"
    assert "record:AVReadiness.avComponentKind" not in prompts[0]
    assert "record:AVReadiness.avComponentKind" in prompts[1]
    assert {c.facet for c in out.facet_criteria} == {
        "record:AVReadiness.avComponentKind",
        "record:AVReadiness.recordStatus",
    }
    assert out.signals == []


def test_a_slow_compile_keeps_its_plan_instead_of_spending_a_second_call(monkeypatch):
    """Measured 2026-10-08: under four concurrent questions two escalated turns spent their 300 s
    deadline queueing for compile and recompile. Past the budget, the first plan is kept and the
    unmapped words stay signals (dropped and declared downstream)."""
    monkeypatch.setattr(C, "FACET_SHORTLIST_K", 0)
    monkeypatch.setattr(C, "INSPECTION_BUDGET_S", -1.0)  # every compile is "already too slow"
    first = _payload(constraints=[QUIET], unmapped=["a ready projector"])
    second = _payload(constraints=[QUIET], criteria=[PROJECTOR, READY])
    out, prompts = _compile(SAMPLE, first, second)
    assert len(prompts) == 1, "no recompile past the budget"
    assert [s.phrase for s in out.signals] == ["a ready projector"]


def test_inspection_that_finds_nothing_new_does_not_recompile():
    out, prompts = _compile(
        "a quiet room near a coffee machine", _payload(constraints=[QUIET], unmapped=["coffee"])
    )
    assert len(prompts) == 1
    assert [s.phrase for s in out.signals] == ["coffee"]


def test_an_inspected_facet_shows_its_recorded_values_from_the_graph():
    reads: List[str] = []

    async def reader(facet):
        reads.append(facet.key)
        return ["East-facing", "Internal", "North-facing", "West-facing"]

    first = _payload(inspect=["record:WorkspaceProfile.daylightAspect"])
    second = _payload(
        criteria=[
            {
                "phrase": "north light",
                "facet": "record:WorkspaceProfile.daylightAspect",
                "operator": "contains",
                "value": "North",
            }
        ]
    )
    out, prompts = _compile("a room with north light", first, second, value_reader=reader)
    assert reads == ["record:WorkspaceProfile.daylightAspect"]
    assert len(prompts) == 2 and '"North-facing"' in prompts[1]
    assert out.facet_criteria[0].value == "North"


def test_recompiles_are_capped_at_two(monkeypatch):
    monkeypatch.setattr(C, "FACET_SHORTLIST_K", 0)
    responses = [
        _payload(unmapped=["seats"]),
        _payload(unmapped=["projector"]),
        _payload(unmapped=["bookable"]),
        _payload(unmapped=["daylight"]),
    ]
    out, prompts = _compile("seats projector bookable daylight", *responses)
    assert len(prompts) == 1 + C.MAX_RECOMPILES == 3
    assert out.signals and out.signals[0].phrase == "bookable"


# ── 4. a synthetic building, served the way the live stack serves it ─────────────────────


def _sparql_json(g: rdflib.Graph, log: List[str] = None):
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


_TTL = """
@prefix brick: <https://brickschema.org/schema/Brick#> .
@prefix ref: <https://brickschema.org/schema/Brick/ref#> .
@prefix rdfs: <http://www.w3.org/2000/01/rdf-schema#> .
@prefix owl: <http://www.w3.org/2002/07/owl#> .
@prefix xsd: <http://www.w3.org/2001/XMLSchema#> .
@prefix o: <http://ontosage.org/capabilities#> .
@prefix x: <http://example.org/towerZ#> .

brick:Space rdfs:subClassOf brick:Location .
brick:Room rdfs:subClassOf brick:Space .
brick:Floor rdfs:subClassOf brick:Location .
o:Record a owl:Class .

x:L1 a brick:Floor ; rdfs:label "Level 1" .

o:WorkspaceProfile rdfs:subClassOf o:Record ; rdfs:label "Workspace profile" .
o:AVReadiness rdfs:subClassOf o:Record ; rdfs:label "AV readiness" ;
    o:layTerms "projector", "display" .
"""

#: (room, noise dB, seats or None, [(AV id, kind, status)])
ROOMS = [
    ("R1", 35.0, 16, [("AV-01", "Projector", "ready")]),
    ("R2", 30.0, 8, [("AV-02", "Projector", "degraded")]),
    ("R3", 33.0, 20, [("AV-03A", "Display", "ready"), ("AV-03B", "Projector", "failed")]),
    ("R4", 45.0, 30, [("AV-04", "Projector", "ready")]),
    ("R5", 38.0, None, [("AV-05", "Projector", "ready")]),
    ("R6", 32.0, 24, [("AV-06", "Projector", "ready")]),
]
BOOKED = "R6"


def _building() -> rdflib.Graph:
    lines = [_TTL]
    for room, _noise, seats, avs in ROOMS:
        lines.append(
            f'x:{room} a brick:Room ; rdfs:label "Room {room[1:]}" ; brick:isPartOf x:L1 .\n'
            f"x:N{room} a o:Sound_Level_Sensor ; brick:hasLocation x:{room} ;\n"
            f'  ref:hasExternalReference [ ref:hasTimeseriesId "u-{room}" ; '
            "ref:storedAt x:noise_data ] .\n"
        )
        if seats is not None:
            lines.append(
                f'x:ws{room} a o:WorkspaceProfile ; o:recordId "WS-{room}" ; '
                f"o:seatCount {seats} ; o:isBookable true ; o:locatedInSpace x:{room} .\n"
            )
        for rid, kind, status in avs:
            lines.append(
                f'x:{rid.replace("-", "_")} a o:AVReadiness ; o:recordId "{rid}" ; '
                f'o:avComponentKind "{kind}" ; o:recordStatus "{status}" ; '
                f"o:locatedInSpace x:{room} .\n"
            )
    g = rdflib.Graph()
    g.parse(data="\n".join(lines), format="turtle")
    return g


NOISE = ModalitySpec("noise", ["Sound_Level_Sensor"], sat={"unit": "dB", "scope": "room"})


def _real_catalogue(g):
    return _run(
        facets.build_facet_catalogue(
            _sparql_json(g), BID, NS, [NOISE], modality_config={}, events_store=True
        )
    )


@dataclass
class _Result:
    success: bool = True
    data: List[Dict[str, Any]] = field(default_factory=list)
    error: str = ""


class _Series:
    def build_timeseries_query(self, uuids, ts_col, start, end, limit=1000):
        return "SELECT ..."

    async def execute_query(self, sql):
        now = datetime.utcnow()
        rows = []
        for room, noise, _seats, _avs in ROOMS:
            for i in range(12):
                rows.append(
                    {
                        "timestamp": (now - timedelta(minutes=12 - i)).strftime(
                            "%Y-%m-%d %H:%M:%S"
                        ),
                        "uuid": f"u-{room}",
                        "value": noise,
                    }
                )
        return _Result(data=rows)


class _Events:
    def __init__(self, busy_label: str):
        self.busy = derive_point_uuid(BID, "evt_subject", busy_label)

    def build_overlap_window(self, event_type, start, end, subject_uuids=None, limit=1000):
        return "SELECT ..."

    async def execute_query(self, sql):
        s = datetime.utcnow()
        return _Result(
            data=[
                {
                    "subject_uuid": self.busy,
                    "start_dt": s,
                    "end_dt": s + timedelta(hours=3),
                }
            ]
        )


def _adapters():
    events, series = _Events(f"Room {BOOKED[1:]}"), _Series()
    return lambda key: events if key == "bldg:events_data" else series


def _schema(g):
    spaces = _run(CoverageAuditor(_sparql_json(g), [NOISE]).audit(NS))
    return cs.BuildingCapabilitySchema(building_id=BID, namespace=NS, spaces=spaces, amenities=[])


def _ir(*criteria, constraints=(), raw="a quiet room with at least 12 seats and a ready projector"):
    return CQIR(
        decision=DecisionKind.SELECT_ONE,
        constraints=list(constraints),
        facet_criteria=list(criteria),
        raw_query=raw,
    )


def _crit(facet, op, value=None, hard=True, group=None, phrase=""):
    return FacetCriterion(
        facet=facet,
        operator=op,
        value=value,
        hardness=Hardness.HARD if hard else Hardness.SOFT,
        record_group=group,
        source_phrase=phrase,
    )


KIND = "record:AVReadiness.avComponentKind"
STATUS = "record:AVReadiness.recordStatus"
SEAT = "record:WorkspaceProfile.seatCount"


def _checks(criteria, iris, g, cat=None):
    cat = cat or _real_catalogue(g)
    return _run(fr.resolve_facets(criteria, cat, iris, _sparql_json(g)))


def test_one_record_must_meet_the_whole_group():
    """Room 3 has a READY display and a FAILED projector: no 'projector that is ready'."""
    g = _building()
    iris = [NS + r for r in ("R1", "R3", "R5")]
    group = [
        _crit(KIND, FacetOperator.EQUALS, "Projector", group="AVReadiness:g"),
        _crit(STATUS, FacetOperator.EQUALS, "ready", group="AVReadiness:g"),
    ]
    status = {(c.space_iri[-2:], c.criterion.facet): c for c in _checks(group, iris, g)}
    assert status[("R1", KIND)].status == status[("R1", STATUS)].status == fr.MET
    assert status[("R1", STATUS)].provenance == ["AVReadiness AV-01"]
    assert status[("R3", KIND)].status == status[("R3", STATUS)].status == fr.UNMET
    # the same two facts asked of DIFFERENT records would wrongly pass room 3
    apart = [
        _crit(KIND, FacetOperator.EQUALS, "Projector", group="AVReadiness:a"),
        _crit(STATUS, FacetOperator.EQUALS, "ready", group="AVReadiness:b"),
    ]
    separately = {(c.space_iri[-2:], c.criterion.facet): c for c in _checks(apart, iris, g)}
    assert separately[("R3", KIND)].status == separately[("R3", STATUS)].status == fr.MET

    soft = [c.model_copy(update={"hardness": Hardness.SOFT}) for c in group]
    soft_checks = {(c.space_iri[-2:], c.criterion.facet): c for c in _checks(soft, iris, g)}
    assert soft_checks[("R3", STATUS)].status == fr.UNMET, "soft does not loosen the group"

    mixed = [group[0], group[1].model_copy(update={"hardness": Hardness.SOFT})]
    mixed_checks = {(c.space_iri[-2:], c.criterion.facet): c for c in _checks(mixed, iris, g)}
    assert mixed_checks[("R3", KIND)].status == fr.MET, "room 3 HAS a projector"
    assert mixed_checks[("R3", STATUS)].status == fr.UNMET, "...which is not ready"


def test_a_space_with_no_record_is_unknown_not_unmet():
    g = _building()
    (check,) = _checks([_crit(SEAT, FacetOperator.AT_LEAST, 12.0)], [NS + "R5"], g)
    assert check.status == fr.UNKNOWN
    assert "no workspace profile record" in check.display


def test_a_record_without_the_value_is_unknown_never_met():
    """A projector whose state was never recorded is not 'a ready projector' -- nor a failed one."""
    g = _building()
    g.parse(
        data=(
            "@prefix o: <http://ontosage.org/capabilities#> .\n"
            "@prefix x: <http://example.org/towerZ#> .\n"
            "@prefix brick: <https://brickschema.org/schema/Brick#> .\n"
            "@prefix rdfs: <http://www.w3.org/2000/01/rdf-schema#> .\n"
            'x:R7 a brick:Room ; rdfs:label "Room 7" ; brick:isPartOf x:L1 .\n'
            'x:AV_07 a o:AVReadiness ; o:recordId "AV-07" ; o:avComponentKind "Projector" ;\n'
            "    o:locatedInSpace x:R7 .\n"
        ),
        format="turtle",
    )
    group = [
        _crit(KIND, FacetOperator.EQUALS, "Projector", group="AVReadiness:g"),
        _crit(STATUS, FacetOperator.EQUALS, "ready", group="AVReadiness:g"),
    ]
    checks = {c.criterion.facet: c for c in _checks(group, [NS + "R7"], g)}
    assert checks[STATUS].status == fr.UNKNOWN
    assert checks[KIND].status == fr.UNKNOWN, "the group, not the field, is what is unknown"
    assert "record status: not recorded" in checks[STATUS].display
    assert checks[STATUS].provenance == ["AVReadiness AV-07"]


def test_a_route_fact_names_the_route_it_came_from_and_where_that_route_starts():
    g = _building()
    g.parse(
        data=(
            "@prefix o: <http://ontosage.org/capabilities#> .\n"
            "@prefix x: <http://example.org/towerZ#> .\n"
            "@prefix rdfs: <http://www.w3.org/2000/01/rdf-schema#> .\n"
            'o:AccessibleRoute rdfs:subClassOf o:Record ; rdfs:label "Accessible route" .\n'
            'x:ar1 a o:AccessibleRoute ; o:recordId "AR-01" ; o:isStepFree true ;\n'
            "    o:allowMinutes 4 ; o:routeToSpace x:R1 ; o:routeFromSpace x:R2 .\n"
            'x:ar2 a o:AccessibleRoute ; o:recordId "AR-02" ; o:isStepFree false ;\n'
            "    o:allowMinutes 9 ; o:routeToSpace x:R4 ; o:routeFromSpace x:R2 .\n"
        ),
        format="turtle",
    )
    cat = _real_catalogue(g)
    step_free = "spatial:AccessibleRoute.isStepFree"
    assert cat.get(step_free) is not None
    checks = {
        c.space_iri[-2:]: c
        for c in _checks(
            [_crit(step_free, FacetOperator.IS_TRUE, group="AccessibleRoute")],
            [NS + "R1", NS + "R4", NS + "R5"],
            g,
            cat,
        )
    }
    assert checks["R1"].status == fr.MET
    assert checks["R1"].provenance == ["AccessibleRoute AR-01, from Room 2"]
    assert checks["R4"].status == fr.UNMET
    assert checks["R5"].status == fr.UNKNOWN


def test_the_resolver_sparql_is_built_by_code_batched_and_bounded():
    g = _building()
    cat = _real_catalogue(g)
    criteria = [
        _crit(SEAT, FacetOperator.AT_LEAST, 12.0),
        _crit(KIND, FacetOperator.EQUALS, "Projector", group="AVReadiness:g"),
        _crit(STATUS, FacetOperator.EQUALS, "ready", group="AVReadiness:g"),
    ]

    def queries(iris):
        log: List[str] = []
        _run(fr.resolve_facets(criteria, cat, iris, _sparql_json(g, log)))
        return log

    few = queries([NS + "R1", NS + "R2"])
    many = queries([NS + r for r, *_ in ROOMS])
    assert len(few) == len(many) == 2, "one query per record class, never one per candidate"
    for q in many:
        assert "LIMIT" in q and q.count("VALUES") == 1
        assert (
            "Projector" not in q and "ready" not in q and "12" not in q
        ), "no user value in SPARQL"
    av = next(q for q in many if "AVReadiness" in q)
    assert f"<{ONTO}avComponentKind>" in av and f"<{ONTO}recordStatus>" in av
    assert f"<{ONTO}locatedInSpace>" in av and f"<{ONTO}recordId>" in av
    with pytest.raises(ValueError):
        fr.record_query(ONTO + "X", "not an iri", [ONTO + "p"], [NS + "R1"])


def test_capacity_is_read_through_its_authority_order_and_a_conflict_is_unknown():
    g = _building()
    g.parse(
        data=(
            "@prefix x: <http://example.org/towerZ#> .\n"
            "@prefix hbco: <http://ontosage.org/hbco#> .\n"
            "@prefix b: <http://example.org/towerZ#> .\n"
            "x:R1 hbco:roomCapacity 20 .\n"
            "x:R4 hbco:roomCapacity 25 . x:R4 b:maxOccupancy 50 .\n"
        ),
        format="turtle",
    )
    cat = _real_catalogue(g)
    assert cat.get("ttl:capacity") is not None
    checks = _run(
        fr.resolve_facets(
            [_crit("ttl:capacity", FacetOperator.AT_LEAST, 20.0)],
            cat,
            [NS + "R1", NS + "R4", NS + "R2"],
            _sparql_json(g),
        )
    )
    by = {c.space_iri[-2:]: c for c in checks}
    assert by["R1"].status == fr.MET and by["R1"].number == 20.0
    assert by["R4"].status == fr.UNKNOWN and "disagreeing" in by["R4"].display
    assert by["R2"].status == fr.UNKNOWN


# ── 5. admission per criterion ───────────────────────────────────────────────────────────


def _ad_schema():
    from orchestrator.services.deliberation.coverage_audit import SpaceCoverage

    spaces = []
    for room in ("R1", "R2"):
        sc = SpaceCoverage(space_iri=NS + room, label=room, floor="L1")
        sc.modalities = {"noise": {"status": "present", "uuid": f"u-{room}", "stored_at": "t"}}
        spaces.append(sc)
    return cs.BuildingCapabilitySchema(building_id=BID, namespace=NS, spaces=spaces, amenities=[])


def test_a_hard_criterion_that_cannot_be_assessed_proceeds_as_an_honest_partial():
    cat = _manual_catalogue(
        extra=[
            _facet(
                "spatial:AccessibleRoute.isStepFree",
                "is step free (route to the space)",
                "boolean",
                source="spatial",
                cls="AccessibleRoute",
                pred=ONTO + "isStepFree",
                join=ONTO + "routeToSpace",
                status="linked",
                coverage=0,
            )
        ]
    )
    ir = _ir(
        _crit(SEAT, FacetOperator.AT_LEAST, 12.0),
        _crit("spatial:AccessibleRoute.isStepFree", FacetOperator.IS_TRUE, phrase="step-free"),
    )
    verdict = cs.validate(ir, _ad_schema(), catalogue=cat)
    assert verdict.verdict == cs.ADMIT
    assert verdict.not_assessable == ["spatial:AccessibleRoute.isStepFree"]
    assert verdict.facet_admission[SEAT] in (cs.FACET_EXECUTABLE, cs.FACET_PARTIAL)
    assert "'step-free' could not be checked" in verdict.not_assessable_notes[0]


def test_only_when_nothing_is_assessable_is_the_question_declined_in_facet_labels():
    cat = _manual_catalogue(
        extra=[
            _facet(
                "record:Locker.lockerCount",
                "locker count",
                "integer",
                cls="Locker",
                pred=ONTO + "lockerCount",
                join=LOCATED,
                status="declared",
                coverage=0,
            )
        ]
    )
    ir = _ir(_crit("record:Locker.lockerCount", FacetOperator.AT_LEAST, 2.0, phrase="lockers"))
    verdict = cs.validate(ir, _ad_schema(), catalogue=cat)
    assert verdict.verdict == cs.DECLINE
    assert "Nothing you asked for can be checked" in verdict.explanation
    assert "seat count (workspace profile)" in verdict.explanation, "what it DOES hold, as labels"
    assert "sensor:" not in verdict.explanation and "record:" not in verdict.explanation


def test_absorb_unmapped_is_v1_with_the_flag_off_and_counts_facets_with_it_on():
    ir = _ir(_crit(SEAT, FacetOperator.AT_LEAST, 12.0)).model_copy(
        update={"signals": [AmbiguitySignal(kind="unmapped_term", phrase="disco lights")]}
    )
    _, dropped, decline = cp.absorb_unmapped(ir)
    assert (dropped, decline) == (["disco lights"], True), "v1: no constraint means decline"
    kept, dropped, decline = cp.absorb_unmapped(ir, facets=True)
    assert (dropped, decline, kept.signals) == (["disco lights"], False, [])


# ── 6. execution and the answer, end to end ─────────────────────────────────────────────


def _end_to_end(ir, g=None):
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


C1_QUESTION = "a quiet room with at least 12 seats and a ready projector, free for two hours"


def _c1_plan():
    return _ir(
        _crit(SEAT, FacetOperator.AT_LEAST, 12.0, phrase="at least 12 seats"),
        _crit(KIND, FacetOperator.EQUALS, "Projector", group="AVReadiness:g", phrase="projector"),
        _crit(STATUS, FacetOperator.EQUALS, "ready", group="AVReadiness:g", phrase="ready"),
        _crit("event:free_window", FacetOperator.FREE_FOR, 2.0, phrase="free for two hours"),
        constraints=[
            Constraint(modality="noise", direction=Direction.MINIMIZE, source_phrase="quiet")
        ],
        raw=C1_QUESTION,
    )


def test_the_c1_question_excludes_ranks_and_flags_correctly():
    outcome, dossier, text = _end_to_end(_c1_plan())
    excluded = {e.label: e.reason for e in outcome.ledger.excluded}
    assert set(excluded) == {"Room 2", "Room 3", "Room 6"}
    assert "seat count: 8" in excluded["Room 2"] and "WorkspaceProfile WS-R2" in excluded["Room 2"]
    assert "no single record meets" in excluded["Room 3"] and "AV-03B" in excluded["Room 3"]
    assert "booked" in excluded["Room 6"]

    ranked = [s.label for s in outcome.score.ranked]
    assert ranked == ["Room 1", "Room 4", "Room 5"], "quietest verified first; unverified last"
    room5 = outcome.score.ranked[2]
    assert room5.unverified_hard == ["seat count (workspace profile)"]

    first = dossier.ranked[0]
    shown = {f.facet: f for f in first.facets}
    assert (
        shown[SEAT].display == "seat count: 16"
        and shown[SEAT].provenance == "WorkspaceProfile WS-R1"
    )
    assert shown[KIND].provenance == "AVReadiness AV-01"
    assert first.criteria == {"noise": 35.0}

    assert "**Best match: Room 1**" in text
    assert "seat count: 16 (WorkspaceProfile WS-R1)" in text
    assert "av component kind: Projector, record status: ready (AVReadiness AV-01)" in text
    assert "**Not verified for Room 5:** seat count (workspace profile)" in text
    assert "**Where each criterion came from:** sensors — noise; records —" in text
    assert "bookings — free for a time window" in text
    assert "3. **Room 5** — score 0.95 on what could be checked" in text
    assert (
        "**Coverage:** 3 of 6 spaces considered; noise: 3/3 instrumented" in text
    ), "the ledger counts the spaces still considered, not the ones enumerated"
    assert numeric_guard(text, dossier) == [], "no number in the prose that is not in the evidence"


def test_a_hard_criterion_nobody_records_is_named_and_the_rest_is_still_answered():
    g = _building()
    g.parse(
        data=(
            "@prefix o: <http://ontosage.org/capabilities#> .\n"
            "@prefix owl: <http://www.w3.org/2002/07/owl#> .\n"
            "@prefix rdfs: <http://www.w3.org/2000/01/rdf-schema#> .\n"
            "o:acousticRating a owl:DatatypeProperty ; rdfs:domain o:WorkspaceProfile .\n"
        ),
        format="turtle",
    )
    rating = "record:WorkspaceProfile.acousticRating"
    ir = _ir(
        _crit(SEAT, FacetOperator.AT_LEAST, 12.0, phrase="at least 12 seats"),
        _crit(rating, FacetOperator.AT_LEAST, 3.0, phrase="an acoustic rating of 3"),
        raw="a room with at least 12 seats and an acoustic rating of 3",
    )
    outcome, dossier, text = _end_to_end(ir, g)
    assert [s.label for s in outcome.score.ranked][:3] == ["Room 1", "Room 3", "Room 4"]
    assert "**Not checked:** 'an acoustic rating of 3' could not be checked" in text
    # four rooms meet every checked requirement: none of them is "the best match"
    assert "Best match" not in text
    assert "each meet everything you asked for that could be checked" in text
    assert "stable under" not in text
    assert "acoustic rating (workspace profile)" in text
    assert "record:" not in text.split("<details>")[0], "a facet key never reaches the reader"
    sources = next(line for line in text.splitlines() if line.startswith("**Where each"))
    assert "acoustic" not in sources, "an unchecked criterion is never listed as a source"
    assert numeric_guard(text, dossier) == []


def test_a_question_with_only_facet_criteria_executes_without_a_fetch():
    ir = _ir(
        _crit(SEAT, FacetOperator.AT_LEAST, 12.0, phrase="at least 12 seats"),
        _crit(KIND, FacetOperator.EQUALS, "Projector", group="AVReadiness:g"),
        _crit(STATUS, FacetOperator.EQUALS, "ready", group="AVReadiness:g"),
        raw="which rooms have at least 12 seats and a ready projector?",
    )
    assert ir.is_executable()
    outcome, dossier, text = _end_to_end(ir)
    assert outcome.evidence == [] and "fetch_ms" in outcome.timings_ms
    assert {s.label for s in outcome.score.ranked} == {"Room 1", "Room 4", "Room 6", "Room 5"}
    assert outcome.score.ranked[-1].label == "Room 5", "an unverified space never outranks"
    assert numeric_guard(text, dossier) == []


def test_a_soft_numeric_facet_is_scored_relative_to_the_candidates_and_says_so():
    ir = _ir(
        _crit(SEAT, FacetOperator.MAXIMIZE, hard=False, phrase="the most seats"),
        raw="which room has the most seats?",
    )
    outcome, dossier, text = _end_to_end(ir)
    order = [s.label for s in outcome.score.ranked]
    assert order[:5] == ["Room 4", "Room 6", "Room 3", "Room 1", "Room 2"]
    assert order[-1] == "Room 5", "a soft unknown is a gap, ranked after the measured"
    assert any("scored relative to the 5 space(s)" in n for n in dossier.facet_notes)
    assert "1. **Room 4** — score 1 · seat count: 30 (WorkspaceProfile WS-R4)" in text
    assert numeric_guard(text, dossier) == []


def test_the_plan_hash_and_fingerprint_include_the_facet_criteria():
    plain = _c1_plan()
    looser = plain.model_copy(
        update={
            "facet_criteria": [
                c if c.facet != SEAT else c.model_copy(update={"value": 10.0})
                for c in plain.facet_criteria
            ]
        }
    )
    a, _, _ = _end_to_end(plain)
    b, _, _ = _end_to_end(looser)
    assert a.plan_fingerprint == plain.plan_fingerprint() != looser.plan_fingerprint()
    assert a.plan_hash != b.plan_hash


def test_v1_rendering_is_byte_identical_without_facet_criteria():
    """The fixed v1 dossier from the baseline script, rendered on 9fd0831 before any edit."""
    from orchestrator.services.deliberation.candidates import Candidate, CoverageLedger, LedgerEntry
    from orchestrator.services.deliberation.clarify_policy import Assumption, ClarifyDecision
    from orchestrator.services.deliberation.plan_executor import (
        EventCheck,
        EvidenceCell,
        ExecutionOutcome,
    )
    from orchestrator.services.deliberation.scorer import (
        CriterionScore,
        ScoredCandidate,
        ScoreResult,
    )

    ns = "http://example.org/towerX#"
    cqir = CQIR(
        decision=DecisionKind.SELECT_ONE,
        constraints=[
            Constraint(modality="noise", direction=Direction.MINIMIZE, source_phrase="quiet"),
            Constraint(
                modality="co2", direction=Direction.MINIMIZE, hardness=Hardness.SOFT, weight=1.0
            ),
        ],
        raw_query="Where can I find a quiet room with fresh air free for 2 hours?",
    )
    cands = [
        Candidate(space_iri=ns + "R1", label="Room 1.01", floor="floor1"),
        Candidate(space_iri=ns + "R2", label="Room 1.02", floor="floor1"),
        Candidate(space_iri=ns + "R3", label="Room 2.01", floor="floor2", kinds=("Office",)),
    ]
    ledger = CoverageLedger(
        in_scope=4,
        considered=3,
        excluded=[
            LedgerEntry(
                ns + "R4",
                "Room 2.02",
                "booked 14:00–16:00 — not free for the requested 2h window",
            )
        ],
        instrumented={"noise": 3, "co2": 3},
    )
    who = "WHO guideline band 30-70 dB(A) indoor"
    ashrae = "ASHRAE 62.1 comfort band 420-1500 ppm"
    ranked = [
        ScoredCandidate(
            space_iri=ns + "R1",
            label="Room 1.01",
            floor="floor1",
            criteria=[
                CriterionScore("noise", 38.5, 0.7875, 1.0, who),
                CriterionScore("co2", 520.0, 0.9074, 1.0, ashrae),
            ],
            total=0.8475,
            rank=1,
        ),
        ScoredCandidate(
            space_iri=ns + "R3",
            label="Room 2.01",
            floor="floor2",
            criteria=[
                CriterionScore("noise", 45.0, 0.625, 1.0, who),
                CriterionScore("co2", 700.0, 0.7407, 1.0, ashrae),
            ],
            total=0.6829,
            rank=2,
        ),
        ScoredCandidate(
            space_iri=ns + "R2",
            label="Room 1.02",
            floor="floor1",
            criteria=[
                CriterionScore("noise", 41.0, 0.725, 1.0, who),
                CriterionScore(
                    "co2",
                    None,
                    None,
                    1.0,
                    ashrae,
                    "no data — criterion skipped, weights renormalized",
                ),
            ],
            total=0.725,
            rank=3,
            data_gaps=["co2"],
        ),
    ]
    stamp = "2026-10-07 10:00:00"
    basis = "recent mean (last readings)"
    outcome = ExecutionOutcome(
        score=ScoreResult(ranked=ranked, excluded=[], top1_stable_under_weight_perturbation=True),
        ledger=ledger,
        candidates=cands,
        evidence=[
            EvidenceCell(ns + "R1", "noise", 38.5, basis, 3.0, 15, "u1", "noise_data", stamp),
            EvidenceCell(ns + "R1", "co2", 520.0, basis, 3.0, 15, "u2", "co2_data", stamp),
            EvidenceCell(ns + "R3", "noise", 45.0, basis, 3.0, 15, "u3", "noise_data", stamp),
        ],
        event_checks=[
            EventCheck(ns + r, "free_window", True, "no booking in the next 2h", 2.0)
            for r in ("R1", "R2", "R3")
        ],
        event_notes=[],
        plan_hash="abcd1234abcd1234",
        plan_fingerprint="feedbeeffeedbeef",
    )
    decision = ClarifyDecision(
        action="proceed",
        assumptions=[
            Assumption("'quiet' scored as minimize noise against the 30-70 band", who),
            Assumption("all stated preferences weighted equally", "default"),
        ],
    )
    dossier = build_dossier(cqir, decision, outcome, "towerX")
    text = render_answer(dossier) + "\n" + render_dossier_details(dossier)
    assert hashlib.sha256(text.encode("utf-8")).hexdigest() == V1_RENDER_SHA256


# ── 7. the node: the flag decides which compiler, admission and executor run ─────────────


def _node_harness(monkeypatch, catalogue):
    """The deliberation node with every live dependency replaced; records what it was given."""
    from orchestrator.services.deliberation import compiler, coverage_audit, live
    from orchestrator.workflow._orchestrator import WorkflowOrchestrator
    from shared.models import ConversationState, Message

    seen: Dict[str, Any] = {}
    monkeypatch.setattr(
        live, "active_identity", lambda: {"BUILDING_ID": BID, "BUILDING_NAMESPACE": NS}
    )
    monkeypatch.setattr(coverage_audit, "load_modalities", lambda _b=None: [NOISE])

    async def _catalogue(*_a, **_k):
        seen["catalogue_built"] = True
        return catalogue

    monkeypatch.setattr(facets, "build_facet_catalogue", _catalogue)

    async def _compile(query, modalities, *a, **kw):
        seen["compile_kwargs"] = sorted(kw)
        return _ir(_crit(SEAT, FacetOperator.AT_LEAST, 12.0), raw=query)

    async def _schema(*_a, **_k):
        return _ad_schema()

    def _validate(cqir, schema, *a, **kw):
        seen["validate_kwargs"] = sorted(kw)
        return cs.AdmissionResult(verdict=cs.DECLINE, reason="stop here")

    monkeypatch.setattr(compiler, "compile_query", _compile)
    monkeypatch.setattr(cs, "build_schema", _schema)
    monkeypatch.setattr(cs, "validate", _validate)

    question = "a room with at least 12 seats"
    orch = WorkflowOrchestrator.__new__(WorkflowOrchestrator)
    state = ConversationState(
        conversation_id="c",
        user_id="u",
        user_message=question,
        messages=[Message(role="user", content=question)],
    )
    return orch, state, seen


def test_the_node_passes_the_catalogue_when_the_flag_is_on(monkeypatch):
    orch, state, seen = _node_harness(monkeypatch, _manual_catalogue())
    _run(orch._deliberate_node(state))
    assert seen["catalogue_built"]
    assert seen["compile_kwargs"] == ["catalogue", "value_reader"]
    assert seen["validate_kwargs"] == ["catalogue"]


def test_the_node_is_v1_when_the_flag_is_off(monkeypatch):
    monkeypatch.setattr(_settings(), "ARBITER_FACETS_ENABLED", False, raising=False)
    orch, state, seen = _node_harness(monkeypatch, _manual_catalogue())
    _run(orch._deliberate_node(state))
    assert "catalogue_built" not in seen
    assert seen["compile_kwargs"] == [] and seen["validate_kwargs"] == []


def test_a_partial_catalogue_is_not_trusted(monkeypatch):
    partial = facets.FacetCatalogue(list(_manual_catalogue()), errors=["record: unreachable"])
    orch, state, seen = _node_harness(monkeypatch, partial)
    _run(orch._deliberate_node(state))
    assert seen["catalogue_built"] and seen["compile_kwargs"] == []
