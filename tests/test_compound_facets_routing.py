# -*- coding: utf-8 -*-
"""v2 P6: a question choosing spaces on several facets at once escalates to deliberation.

The rule (`routing_contract._r_compound_facets_to_deliberate`) decides from the building's facet
catalogue (`facet_routing.compound_signal`), never builds one on a turn, and runs in three modes:
`off` (inert), `shadow` (logs, changes nothing -- the default) and `live` (routes).

Every test runs OFFLINE against a synthetic catalogue whose registers are invented ("KitList",
"DeskCard"): the rule must hold for buildings it has never seen. The decision's measurement on
the parked buildings' real catalogues is in `facet_routing`'s docstring and the P6 report.
"""

from __future__ import annotations

import logging
import re
from pathlib import Path
from typing import Any, Dict, List, Optional

import pytest

from orchestrator.services import routing_contract as rc
from orchestrator.services.deliberation import facet_routing as fr
from orchestrator.services.deliberation import facets
from shared import config as shared_config

pytestmark = pytest.mark.unit

REPO = Path(__file__).resolve().parent.parent
RULE = "compound_facets_to_deliberate"
SHADOW_LINE = "compound_facets_to_deliberate (shadow) would route"


def _facet(
    key: str,
    kind: str,
    label: str,
    *lay: str,
    value_type: str = "number",
    unit: Optional[str] = None,
    examples: tuple = (),
    record_class: Optional[str] = None,
    class_terms: tuple = (),
    entity: str = "space",
) -> facets.Facet:
    return facets.Facet(
        key=key,
        entity_type=entity,
        source_kind=kind,
        label=label,
        value_type=value_type,
        unit=unit,
        lay_terms=tuple(lay),
        record_class=record_class,
        examples=tuple(examples),
        status="suitable",
        coverage=1,
        class_terms=tuple(class_terms),
    )


_KIT = ("projector", "kit list", "presentation kit")
_DESK = ("desk card", "bookable room", "seat")

#: Sensed facets and an in-use flag, a kit register, a desk register with three columns, a
#: capacity, an availability check, a route's length to the space and the floor -- the kinds a
#: compound question combines.
CATALOGUE = facets.FacetCatalogue(
    [
        _facet("sensor:noise", "sensor", "noise", "quiet", "loud", "sound level", unit="dB"),
        _facet("sensor:co2", "sensor", "co2", "stuffy", "air quality", unit="ppm"),
        _facet("sensor:temperature", "sensor", "temperature", "warm", "cold", unit="degC"),
        _facet(
            "sensor:occupancy_status", "sensor", "occupancy status", "in use", value_type="boolean"
        ),
        _facet(
            "record:KitList.kitKind",
            "record",
            "kit kind",
            value_type="enum",
            examples=("Projector", "Hearing loop", "Display"),
            record_class="KitList",
            class_terms=_KIT,
        ),
        _facet(
            "record:KitList.lastChecked",
            "record",
            "last checked",
            value_type="datetime",
            record_class="KitList",
            class_terms=_KIT,
        ),
        _facet(
            "record:DeskCard.seatCount",
            "record",
            "seat count",
            "seats",
            value_type="integer",
            record_class="DeskCard",
            class_terms=_DESK,
        ),
        _facet(
            "record:DeskCard.noiseRating",
            "record",
            "noise rating",
            value_type="enum",
            examples=("quiet", "lively"),
            record_class="DeskCard",
            class_terms=_DESK,
        ),
        _facet(
            "record:DeskCard.powerSockets",
            "record",
            "power sockets",
            value_type="integer",
            record_class="DeskCard",
            class_terms=_DESK,
        ),
        _facet(
            "ttl:capacity",
            "ttl",
            "room capacity (design occupancy)",
            "capacity",
            value_type="integer",
            unit="persons",
        ),
        _facet(
            "event:free_window",
            "event",
            "free for a time window",
            "free",
            "available",
            value_type="boolean",
        ),
        _facet(
            "spatial:floor", "spatial", "floor the space is on", "floor", "level", value_type="enum"
        ),
        _facet(
            "spatial:WalkingRoute.allowMinutes",
            "spatial",
            "allow minutes (route to the space)",
            "allow minutes",
            "route",
            "journey",
            value_type="integer",
            unit="minutes",
            record_class="WalkingRoute",
        ),
    ]
)

COMPOUND = "Find me a quiet room with a projector"


def _route(query: str, intent: Optional[str] = "metadata") -> Dict[str, Any]:
    """Run the concept stage as `_dialogue_node` does (mode and catalogue set by the fixtures)."""
    state: Dict[str, Any] = {"intent": intent, "concepts": [], "entities": []}
    rc.apply_contract(query, state, stage="concept")
    return state


@pytest.fixture
def mode(monkeypatch):
    """Set ARBITER_V2_ROUTING on the settings object the config module holds NOW."""

    def _set(value: str) -> None:
        monkeypatch.setattr(shared_config.settings, "ARBITER_V2_ROUTING", value)

    return _set


@pytest.fixture
def catalogue(monkeypatch):
    """Make `active_catalogue()` return the given catalogue (or None) without any graph."""

    def _set(value: Optional[facets.FacetCatalogue]) -> None:
        monkeypatch.setattr(fr, "active_catalogue", lambda: value)

    return _set


# ── 1. the signal: what makes a question compound ─────────────────────────────────────


def test_a_choice_of_space_on_a_reading_and_a_register_is_compound():
    sig = fr.compound_signal(COMPOUND, CATALOGUE)
    assert sig is not None
    assert sig.facet_keys == ["sensor:noise", "record:KitList.kitKind"]
    assert sig.kinds == {"sensor", "record"} and sig.reason == "kinds"


def test_two_registers_are_two_sources():
    sig = fr.compound_signal("Which bookable room seats 12 and has a projector?", CATALOGUE)
    assert sig is not None and sig.reason == "sources"
    assert sig.facet_keys == ["record:DeskCard.seatCount", "record:KitList.kitKind"]


@pytest.mark.parametrize(
    "query",
    [
        "Which room is quiet?",  # one criterion
        "What is the noise level in room 2.01 right now?",  # a lookup: chooses no space
        # floor 3 is scope and the last 24 hours a time window: one criterion remains
        "Which room on floor 3 has the best air quality over the last 24 hours?",
        "Is room 2.01 quiet and does it have a projector?",  # two criteria, no choice of space
    ],
)
def test_a_single_facet_lookup_is_not_compound(query):
    assert fr.compound_signal(query, CATALOGUE) is None


def test_two_columns_of_one_register_are_one_source():
    """The register lane answers both columns in one read; that is not a compound question."""
    assert (
        fr.compound_signal("Which bookable room has 12 seats and power sockets?", CATALOGUE) is None
    )


def test_a_word_cut_down_from_a_phrase_names_nothing_alone():
    """ "in use" became the one-word term "use"; only the phrase itself names the facet."""
    assert fr.compound_signal("Which rooms are in use and stuffy?", CATALOGUE) is not None
    assert fr.compound_signal("Which rooms are used heavily and stuffy?", CATALOGUE) is None


def test_step_free_is_not_free():
    """ "X-free" means without X: with no step-free facet, "free" must not become availability."""
    assert fr.compound_signal("Which step-free room is quiet?", CATALOGUE) is None
    sig = fr.compound_signal("Which quiet rooms are free this afternoon?", CATALOGUE)
    assert sig is not None and "event:free_window" in sig.facet_keys


def test_a_time_counts_only_as_a_limit_on_the_journey():
    """ "within five minutes" bounds how far a space may be; "for 90 minutes" is how long it lasts.

    Both were once lost or wrong together: the time unit was ALSO on the generic-word list, which
    threw away the one criterion the route-limit rule exists to keep.
    """
    sig = fr.compound_signal("Which quiet room can I reach within five minutes?", CATALOGUE)
    assert sig is not None
    assert "spatial:WalkingRoute.allowMinutes" in sig.facet_keys and sig.kinds >= {"spatial"}
    assert fr.compound_signal("Which room is quiet for 90 minutes?", CATALOGUE) is None
    # a time WINDOW is scope, never a criterion
    assert fr.compound_signal("Which room was quiet over the last 24 hours?", CATALOGUE) is None


def test_the_score_bar_is_relative_to_the_catalogue():
    """A word only one facet carries weighs log(1 + n/2): a fixed bar would bite small buildings."""
    assert CATALOGUE.unique_word_weight == pytest.approx(2.0149, abs=1e-3)
    assert fr.compound_signal(COMPOUND, CATALOGUE) is not None
    # raise the bar above the kit register's evidence and the projector stops counting
    assert fr.compound_signal(COMPOUND, CATALOGUE, min_relative_score=0.9) is None


def test_term_matches_itemise_what_retrieval_scores_and_change_no_score():
    before = CATALOGUE.scores(COMPOUND)
    matches = CATALOGUE.term_matches(COMPOUND)
    assert CATALOGUE.scores(COMPOUND) == before
    assert {m.key for m in matches if m.tier != "class"} <= set(before)
    kit = [m for m in matches if m.key == "record:KitList.kitKind"]
    assert {m.tier for m in kit} >= {"value", "class"}
    use = [m for m in CATALOGUE.term_matches("in use") if m.key == "sensor:occupancy_status"]
    assert use and use[0].words == ("use",) and use[0].phrases == ("in use",)


# ── 2. the rule: three modes ──────────────────────────────────────────────────────────


def test_shadow_mode_logs_and_changes_nothing(mode, catalogue, caplog):
    mode("shadow")
    catalogue(CATALOGUE)
    caplog.set_level(logging.INFO, logger="orchestrator.services.routing_contract")
    state = _route(COMPOUND, intent="metadata")
    assert state["intent"] == "metadata"
    assert RULE not in (state.get("routing_rules_applied") or [])
    lines = [r.getMessage() for r in caplog.records if SHADOW_LINE in r.getMessage()]
    assert len(lines) == 1, lines
    assert lines[0].startswith(
        "[routing-contract] compound_facets_to_deliberate (shadow) would route "
        "'metadata' -> 'deliberate' — facets: "
    )
    assert "sensor:noise" in lines[0] and "record:KitList.kitKind" in lines[0]


def test_live_mode_routes_to_deliberate(mode, catalogue):
    mode("live")
    catalogue(CATALOGUE)
    state = _route(COMPOUND, intent="metadata")
    assert state["intent"] == "deliberate"
    assert state["routing_rules_applied"] == [RULE]


def test_off_mode_is_inert_and_never_looks_for_a_catalogue(mode, monkeypatch, caplog):
    mode("off")

    def _must_not_be_called():
        raise AssertionError("off mode read the catalogue")

    monkeypatch.setattr(fr, "active_catalogue", _must_not_be_called)
    caplog.set_level(logging.INFO, logger="orchestrator.services.routing_contract")
    state = _route(COMPOUND, intent="metadata")
    assert state["intent"] == "metadata"
    assert not [r for r in caplog.records if RULE in r.getMessage()]


@pytest.mark.parametrize("routing", ["shadow", "live"])
def test_no_cached_catalogue_means_the_rule_does_nothing(mode, catalogue, caplog, routing):
    mode(routing)
    catalogue(None)
    caplog.set_level(logging.INFO, logger="orchestrator.services.routing_contract")
    state = _route(COMPOUND, intent="metadata")
    assert state["intent"] == "metadata"
    assert not [r for r in caplog.records if RULE in r.getMessage()]


def test_the_mode_is_read_at_call_time_and_an_unknown_one_is_off(mode):
    mode("live")
    assert fr.routing_mode() == "live"
    mode(" Shadow ")
    assert fr.routing_mode() == "shadow"
    mode("sometimes")
    assert fr.routing_mode() == "off"


def test_the_setting_is_case_blind_and_refuses_an_unknown_stage():
    assert shared_config.Settings(ARBITER_V2_ROUTING=" Live ").ARBITER_V2_ROUTING == "live"
    # The CODE default, not whatever the active .env sets (a development stack may run live).
    assert shared_config.Settings.model_fields["ARBITER_V2_ROUTING"].default == "shadow"
    with pytest.raises(Exception):
        shared_config.Settings(ARBITER_V2_ROUTING="sometimes")


# ── 3. shapes another rule owns, and lanes that are not single-facet ──────────────────


@pytest.mark.parametrize(
    "query",
    [
        # a fault STATEMENT is filed even when a choice of room rides along with it
        "The heating in my office is broken, find me a quiet room with a projector",
        # a command is declined by the control lane, never ranked
        "Find a quiet room with a projector and turn off the lights there",
        # a route is answered by the route lanes
        "Which route to a quiet room with a projector is quickest?",
        # a question about the CONVERSATION and one about the previous ANSWER
        "Remind me which room with a projector and quiet seating I mentioned earlier.",
        "How do you know which quiet room has a projector?",
        # a question about the assistant
        "What can you do? Which quiet room has a projector?",
        # "when" asks for a time, which is the series lane's
        "When is the quiet room with a projector busiest?",
        # the sensors themselves are an inventory
        "Which rooms have co-located noise and CO2 sensors?",
    ],
)
def test_a_shape_another_rule_owns_is_never_escalated(mode, catalogue, query):
    mode("live")
    catalogue(CATALOGUE)
    assert _route(query, intent="metadata")["intent"] == "metadata"


def test_the_guards_are_what_stood_down_not_the_absence_of_a_signal():
    """The owner checks above are only meaningful where the facet signal alone would fire."""
    for query in (
        "The heating in my office is broken, find me a quiet room with a projector",
        "Find a quiet room with a projector and turn off the lights there",
        "Which route to a quiet room with a projector is quickest?",
        "How do you know which quiet room has a projector?",
        "Which rooms have co-located noise and CO2 sensors?",
    ):
        assert fr.compound_signal(query, CATALOGUE) is not None, query
        ctx = rc._Ctx(query=query, ql=query.lower(), normalized={"intent": "metadata"}, sr=None)
        assert rc._compound_shape_owned_elsewhere(ctx), query


@pytest.mark.parametrize(
    "intent",
    [
        "greeting",
        "clarification",
        "deliberate",
        "trend",
        "control",
        "privacy_refusal",
        "session_recall",
        "self_description",
        "maintenance",
        "complaint",
        "observability",
        "readiness_check",
        "scope_boundary",
        "general_guidance",
    ],
)
def test_only_single_facet_lanes_are_escalated_from(mode, catalogue, intent):
    mode("live")
    catalogue(CATALOGUE)
    assert _route(COMPOUND, intent=intent)["intent"] == intent


@pytest.mark.parametrize(
    "intent", ["metadata", "register", "capability", "sensor_data", "events", "general", None]
)
def test_a_single_facet_lane_is_escalated_from(mode, catalogue, intent):
    mode("live")
    catalogue(CATALOGUE)
    assert _route(COMPOUND, intent=intent)["intent"] == "deliberate"


def test_a_greeting_is_not_escalated(mode, catalogue):
    mode("live")
    catalogue(CATALOGUE)
    assert _route("Hello there", intent="greeting")["intent"] == "greeting"
    assert _route("Hello there", intent="general")["intent"] == "general"


# ── 4. the catalogue the rule reads: cached only, never built on a turn ───────────────


def test_the_accessor_returns_only_a_cached_catalogue(monkeypatch):
    from orchestrator.services.deliberation import live

    identity = {"BUILDING_ID": "towerX", "BUILDING_NAMESPACE": "http://example.org/towerX#"}
    monkeypatch.setattr(live, "active_identity", lambda: dict(identity))
    monkeypatch.setattr(facets, "_CACHE", {})
    assert fr.active_catalogue() is None
    assert facets.cached_catalogue("towerX", "http://example.org/towerX#") is None
    facets._CACHE[("towerX", "http://example.org/towerX#")] = CATALOGUE
    assert fr.active_catalogue() is CATALOGUE
    assert facets.cached_catalogue("campusY", "http://example.org/campusY#") is None


async def test_the_boot_warm_up_retries_a_partial_build_and_keeps_a_complete_one(monkeypatch):
    from orchestrator.services.deliberation import coverage_audit, live

    monkeypatch.setattr(
        live,
        "active_identity",
        lambda: {"BUILDING_ID": "towerX", "BUILDING_NAMESPACE": "http://example.org/towerX#"},
    )
    monkeypatch.setattr(coverage_audit, "load_modalities", lambda building_id=None: [])
    partial = facets.FacetCatalogue([], errors=("record: graph unavailable",))
    builds: List[facets.FacetCatalogue] = [partial, CATALOGUE]
    calls: List[Dict[str, Any]] = []

    async def fake_build(sparql_exec, building_id, namespace, modalities, **kw):
        calls.append({"building_id": building_id, "namespace": namespace, **kw})
        return builds.pop(0)

    monkeypatch.setattr(fr, "build_facet_catalogue", fake_build)
    got = await fr.warm_facet_catalogue(first_delay_s=0, retry_delays_s=(0,))
    assert got is CATALOGUE and len(calls) == 2
    assert calls[0]["building_id"] == "towerX" and calls[0]["refresh"] is True

    builds[:] = [partial]
    assert await fr.warm_facet_catalogue(first_delay_s=0, retry_delays_s=()) is None


# ── 5. the contract: position, and no building in the code ───────────────────────────


def test_the_rule_is_last_in_the_concept_stage():
    """The only stage every question reaches, and last because it only escalates."""
    names = [r.name for r in rc.CONCEPT_STAGE_RULES]
    assert names[-1] == RULE and names.count(RULE) == 1
    assert RULE not in [r.name for r in rc.PARSE_STAGE_RULES + rc.POST_STAGE_RULES]


def test_the_routing_module_names_no_building():
    text = Path(fr.__file__).read_text(encoding="utf-8")
    banned = re.compile(r"abacws|cardiff|bldg[123]\b|buildsys\.org", re.IGNORECASE)
    assert not banned.findall(text)


def test_the_setting_is_documented_with_its_default():
    example = (REPO / ".env.example").read_text(encoding="utf-8")
    assert re.search(r"^ARBITER_V2_ROUTING=shadow$", example, re.M)


# ── 6. operations no v1 lane computes: C3 (group -> aggregate -> rank) and C2 ───────────────
#
# `operation_signal` escalates what `compound_signal` cannot see -- a ranking of FLOORS or KINDS of
# room chooses no space -- but only where v1's figure is wrong or missing (live probe, 2026-10-08,
# in facet_routing's comment block). A level ranked across floors and two named periods stay
# with v1's compare lane, which answers them well.

OPS = facets.FacetCatalogue(
    [
        *CATALOGUE,
        _facet("sensor:occupancy", "sensor", "occupancy", "people", "busy", unit="persons"),
    ]
)


@pytest.mark.parametrize(
    "query, shape, reason",
    [
        ("Which floor has the fewest people?", "C3", "additive"),
        ("How many people are on each floor?", "C3", "additive"),
        ("Which floor is the busiest right now?", "C3", "additive"),
        ("Which floor has the most seats?", "C3", "additive"),
        ("Which kind of room has the highest noise level?", "C3", "room_kind"),
        ("How evenly is the temperature spread across the floors?", "C3", "dispersion"),
        ("Is the temperature uniform across the building?", "C3", "dispersion"),
        ("Are any rooms over capacity?", "C2", "measured_vs_declared"),
        ("Which rooms have more people than their capacity?", "C2", "measured_vs_declared"),
        (
            "What is the occupancy right now versus the design capacity?",
            "C2",
            "measured_vs_declared",
        ),
    ],
)
def test_an_operation_v1_cannot_compute_is_recognised(query, shape, reason):
    sig = fr.operation_signal(query, OPS)
    assert sig is not None, query
    assert (sig.shape, sig.reason) == (shape, reason)


@pytest.mark.parametrize(
    "query",
    [
        "Which floor is the warmest?",  # a level per floor: v1's compare lane gives the mean
        "What is the temperature on each floor?",
        "Was it warmer this week than last week?",  # two periods: v1 reads both whole
        "Which floor will be busiest tomorrow?",  # a forecast is the forecast lane's
        "What is the capacity of room 1.04?",  # one declared figure, nothing against it
        "Show me the noise sensors on each floor",  # an inventory, not a figure per floor
        "How many floors does the building have?",
    ],
)
def test_what_v1_already_answers_is_left_alone(query):
    assert fr.operation_signal(query, OPS) is None, query


def test_an_operation_routes_live_and_only_logs_in_shadow(mode, catalogue, caplog):
    catalogue(OPS)
    mode("shadow")
    with caplog.at_level(logging.INFO, logger="orchestrator.services.routing_contract"):
        state = _route("Which floor has the fewest people?", intent="compare")
    assert state["intent"] == "compare"
    assert any(
        SHADOW_LINE in r.getMessage() and "C3 additive" in r.getMessage() for r in caplog.records
    )
    mode("live")
    assert _route("Which floor has the fewest people?", intent="compare")["intent"] == "deliberate"
    assert _route("Which floor is the warmest?", intent="compare")["intent"] == "compare"


# ── 7. the route record names the rule that escalated a turn ───────────────────────────


def test_the_route_record_names_a_concept_stage_escalation():
    """The evaluation attributes each v2 answer to the architecture or to a v1 lane from the
    capture record alone (tasks/V2_COMPOUND_PLAN.md section 5). A concept-stage rule decides
    before `_route_from_dialogue` builds the route record, and it was recorded nowhere."""
    from orchestrator.workflow import WorkflowOrchestrator
    from shared.models import ConversationState

    wf = WorkflowOrchestrator.__new__(WorkflowOrchestrator)
    state = ConversationState(
        conversation_id="route-record", user_message="x", current_intent="deliberate"
    )
    state.intermediate_results["concept_rules_applied"] = [RULE]
    wf._route_from_dialogue(state)
    applied = state.intermediate_results["route_decision"]["overrides_applied"]
    assert f"contract:{RULE}" in applied
