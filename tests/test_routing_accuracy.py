"""Phase 13A — routing accuracy test harness.

The pipeline routing decision is hybrid:
  1. dialogue_agent (LLM) picks an intent label
  2. _route_from_dialogue (Python) resolves intent → graph node, applying
     contextual overrides for floor_plan, discovery+spatial, etc.

This test fires representative queries at `WorkflowOrchestrator._route_from_dialogue`
with a *fixed* intent label and asserts the resolved node is what we expect.  It
does NOT call the LLM — it exercises only the deterministic Python half.  That
keeps the test fast, deterministic, and CI-friendly, while still catching
breakage when registry overlays or contextual overrides change.

Adding a new routing rule MUST come with a new case here.
"""

from __future__ import annotations

from typing import Optional
from unittest.mock import MagicMock

import pytest

from shared.models import ConversationState, Message

# ─────────────────────────────────────────────────────────────────────────────
# Helpers
# ─────────────────────────────────────────────────────────────────────────────


def _state(message: str, intent: str, *, building_id: Optional[str] = None) -> ConversationState:
    state = ConversationState(
        conversation_id="routing-accuracy",
        user_id="tester",
        user_message=message,
        messages=[Message(role="user", content=message)],
        intermediate_results={},
    )
    state.current_intent = intent
    if building_id:
        state.building_id = building_id
    return state


@pytest.fixture
def orch():
    """A minimal WorkflowOrchestrator instance suitable for routing-only tests.

    We bypass __init__ to skip all the heavy I/O (Redis, LLM clients, agents).
    Only the routing methods are exercised.
    """
    from orchestrator.workflow import WorkflowOrchestrator

    inst = WorkflowOrchestrator.__new__(WorkflowOrchestrator)
    inst._user_wants_visualization = MagicMock(return_value=False)
    return inst


# ─────────────────────────────────────────────────────────────────────────────
# Canonical cases — one per intent, plus the contextual override matrix.
#
# Format: (query, intent_label, expected_node, expected_overrides_applied)
# expected_overrides_applied is checked as a SUBSET of the actual list, so new
# overrides added later don't break old cases (but unexpected overrides do).
# ─────────────────────────────────────────────────────────────────────────────


REGISTRY_DEFAULT_CASES = [
    # (query, intent, expected_node)
    ("hello there", "greeting", "response"),
    # general → dedicated open-domain answering node (was "response" before the
    # general_knowledge node existed).
    ("what is HVAC?", "general", "general_knowledge"),
    ("can you clarify?", "clarification", "response"),
    ("what is the temperature in 5.28", "sensor_data", "sparql"),
    ("compare CO2 in floors 1 and 3", "compare", "sparql"),
    ("is energy use trending up?", "trend", "sparql"),
    ("recommend HVAC settings", "recommend", "sparql"),
    ("detect anomalies in temperature", "anomaly", "sparql"),
    ("generate a daily building report", "report", "planner"),
    ("export sensor data as CSV", "export", "export"),
    ("plot temperature over time", "visualization", "visualization"),
    ("show me a floor plan of floor 3", "floor_plan", "floor_plan"),
    ("how many rooms on floor 2?", "spatial_query", "spatial_query"),
    ("how do I get to room 5.01 from the main entrance", "spatial_query", "spatial_query"),
    ("directions to the server room from reception", "spatial_query", "spatial_query"),
    ("route to 3.01 from 5.20", "spatial_query", "spatial_query"),
    ("navigate to the meeting room on floor 4", "spatial_query", "spatial_query"),
    ("turn off the HVAC", "control", "control"),
    ("file a maintenance ticket", "maintenance", "maintenance"),
    ("where is the prayer room?", "capability", "capability"),
    ("orchestrate a multi-step task", "planner", "planner"),
    ("are there compliance issues?", "compliance", "sparql"),
    ("show analytics for 5.28", "analytics", "sparql"),
    ("what is the average humidity?", "metadata", "sparql"),
]


@pytest.mark.parametrize("query,intent,expected_node", REGISTRY_DEFAULT_CASES)
def test_registry_default_routing(orch, query, intent, expected_node):
    """Every registered intent must route to its declared node (or pipeline
    default) without any contextual override firing."""
    state = _state(query, intent)
    node = orch._route_from_dialogue(state)
    assert (
        node == expected_node
    ), f"Intent {intent!r} routed to {node!r}; expected {expected_node!r}"

    decision = state.intermediate_results.get("route_decision")
    assert decision is not None, "route_decision must be recorded for every routing call"
    assert decision["final_node"] == expected_node
    assert decision["intent_from_dialogue"] == intent


def test_floor_plan_compare_data_keywords_override(orch):
    """Override #1: when intent==floor_plan but the query asks to compare
    sensor data across floors, route to comparison (sparql) instead."""
    state = _state("compare temperature on floor 1 vs floor 3", "floor_plan")
    node = orch._route_from_dialogue(state)
    assert node == "sparql", f"compare+data query stayed on floor_plan: {node}"

    decision = state.intermediate_results["route_decision"]
    assert "floor_plan_to_comparison_keywords" in decision["overrides_applied"]
    assert decision["decision_source"] == "override"


def test_floor_plan_keyword_detection_steals_misclassified_query(orch):
    """Override #2: even if dialogue picks 'general', a 'show me floor 3'
    query is recognised as floor_plan by keyword."""
    state = _state("show me the floor plan of floor 3", "general")
    node = orch._route_from_dialogue(state)
    assert node == "floor_plan"

    decision = state.intermediate_results["route_decision"]
    # Override fires only when the intent wasn't already floor_plan.
    assert "floor_plan_keyword_detection" in decision["overrides_applied"]


def test_floor_plan_keyword_does_NOT_steal_data_intent(orch):
    """Sensor data queries that happen to mention 'floor' must stay on
    the data pipeline — they are NOT floor-plan requests."""
    state = _state("what is the temperature on floor 3?", "sensor_data")
    node = orch._route_from_dialogue(state)
    assert node == "sparql", f"sensor_data query mentioning 'floor' got hijacked to {node!r}"


def test_discovery_with_spatial_words_routes_to_sparql(orch):
    """Override #3: discovery + spatial words → sparql (needs ontology
    lookup), not response."""
    state = _state("how many zones are on floor 1?", "discovery")
    node = orch._route_from_dialogue(state)
    assert node == "sparql"

    decision = state.intermediate_results["route_decision"]
    assert "discovery_spatial_words" in decision["overrides_applied"]


def test_discovery_without_spatial_words_routes_to_response(orch):
    """Discovery WITHOUT spatial keywords goes to response (chat-style answer)."""
    state = _state("tell me about this building", "discovery")
    node = orch._route_from_dialogue(state)
    assert node == "response"


def test_analytics_followup_with_existing_data_skips_sparql(orch):
    """Override #4: when prior data is in state, analytics-family intents
    skip the sparql fetch and run analytics directly."""
    state = _state("what's the trend on this data?", "analytics")
    state.intermediate_results["use_existing_query_results"] = True
    node = orch._route_from_dialogue(state)
    assert node == "analytics"

    decision = state.intermediate_results["route_decision"]
    assert "analytics_followup_existing_data" in decision["overrides_applied"]


def test_legacy_sparql_alias_routes_to_sparql(orch):
    """Some legacy intent labels (sparql, metadata, sensor_data) still appear
    in production; they must keep routing to sparql even if not in registry."""
    for legacy in ("sparql", "metadata", "sensor_data"):
        state = _state("test", legacy)
        assert (
            orch._route_from_dialogue(state) == "sparql"
        ), f"Legacy alias {legacy!r} must route to sparql"


def test_unknown_intent_falls_back_to_response(orch):
    """Truly unknown intents (not in registry, not in legacy list) go to
    response as a graceful fallback."""
    state = _state("???", "totally_fictional_intent_xyz")
    node = orch._route_from_dialogue(state)
    assert node == "response"

    decision = state.intermediate_results["route_decision"]
    assert decision["decision_source"] == "fallback"


def test_route_decision_audit_trail_always_emitted(orch):
    """The route_decision dict must ALWAYS be emitted, regardless of which
    code path is taken.  This is the observability contract."""
    for intent in ("greeting", "sensor_data", "floor_plan", "discovery", "weird_unknown_intent"):
        state = _state("test", intent)
        orch._route_from_dialogue(state)
        decision = state.intermediate_results.get("route_decision")
        assert decision is not None, f"No route_decision for intent={intent}"
        assert "final_node" in decision
        assert "intent_from_dialogue" in decision
        assert "overrides_applied" in decision
        assert "decision_source" in decision


# ─────────────────────────────────────────────────────────────────────────────
# T06 — Concept-layer routing cases
#
# These verify that:
#  a) Lay-language comfort/environment queries with analytics/sensor_data intent
#     flow through the SPARQL pipeline unchanged.
#  b) CLAUDE.md routing-precedence rules are preserved when concept phrasings
#     appear — comfort questions stay analytics, actuation stays control, fault
#     statements stay maintenance/complaint.
# ─────────────────────────────────────────────────────────────────────────────

CONCEPT_LAYER_ROUTING_CASES = [
    # Comfort questions → analytics pipeline (not control, not capability)
    ("Is it stuffy in room 5.01?", "analytics", "sparql"),
    ("Is it too warm in here?", "analytics", "sparql"),
    ("Is the room damp today?", "analytics", "sparql"),
    ("Is the air quality good on floor 3?", "analytics", "sparql"),
    ("Is it noisy on floor 2?", "analytics", "sparql"),
    ("Is the air stale in the library?", "analytics", "sparql"),
    # Sensor-data phrasings for same concepts
    ("What is the CO2 level in room 5.01?", "sensor_data", "sparql"),
    ("Show me the humidity in the seminar room", "sensor_data", "sparql"),
    ("What is the temperature on floor 3?", "sensor_data", "sparql"),
    # Occupancy / busyness
    ("How crowded is floor 5 right now?", "analytics", "sparql"),
    ("Is floor 3 busy this afternoon?", "analytics", "sparql"),
    # Trend phrasings for comfort concepts
    ("Has it been getting warmer in room 5.01 this week?", "trend", "sparql"),
    ("Is the CO2 level trending up today?", "trend", "sparql"),
]


@pytest.mark.parametrize("query,intent,expected_node", CONCEPT_LAYER_ROUTING_CASES)
def test_concept_layer_routing(orch, query, intent, expected_node):
    """Lay-language concept queries must route through the normal pipeline nodes."""
    state = _state(query, intent)
    node = orch._route_from_dialogue(state)
    assert node == expected_node, (
        f"Concept query {query!r} with intent {intent!r} routed to {node!r}; "
        f"expected {expected_node!r}"
    )


def test_comfort_question_stays_analytics_not_complaint(orch):
    """'Is it too warm?' is a question, NOT a complaint — must route analytics."""
    state = _state("Is it too warm in room 5.01?", "analytics")
    node = orch._route_from_dialogue(state)
    assert node == "sparql", f"Comfort question got rerouted away from SPARQL pipeline: {node!r}"


def test_actuation_concept_stays_control(orch):
    """'Open the windows' is an actuation request — must go to control (decline)."""
    state = _state("Open the windows to let in fresh air", "control")
    node = orch._route_from_dialogue(state)
    assert node == "control", f"Actuation/concept query was not routed to control: {node!r}"


def test_fault_statement_stays_maintenance(orch):
    """'The toilet is broken' is a fault statement — must route to maintenance."""
    state = _state("The toilet on floor 2 is broken", "maintenance")
    node = orch._route_from_dialogue(state)
    assert node == "maintenance", f"Fault statement routed away from maintenance: {node!r}"


def test_safety_report_intent_routes_to_own_node(orch):
    """safety_report is a standalone report-intake intent → own 'safety_report' node."""
    state = _state("There is water leaking from the ceiling", "safety_report")
    node = orch._route_from_dialogue(state)
    assert node == "safety_report", f"Safety report routed to {node!r} instead of safety_report"


def test_complaint_about_warmth_routes_to_complaint_node(orch):
    """Complaint phrasing about warmth → 'complaint' node (report-intake), not analytics."""
    state = _state("It is way too hot in my office and affecting my work", "complaint")
    node = orch._route_from_dialogue(state)
    assert node == "complaint", f"Warmth complaint routed to {node!r} instead of complaint"


# ── T21 alert management routing ──────────────────────────────────────────────


@pytest.mark.parametrize(
    "query",
    [
        "Alert me if CO2 exceeds 1000 ppm in room 5.01",
        "Notify me when temperature goes above 28 degrees on floor 3",
        "Set an alert for humidity below 30% on floor 2",
        "List my alerts",
        "Show my active alerts",
        "Delete alert abc12345",
    ],
)
def test_alert_intent_routes_to_alert_mgmt_node(orch, query):
    """All alert management phrasings must route to 'alert_mgmt' node (standalone)."""
    state = _state(query, "alert")
    node = orch._route_from_dialogue(state)
    assert node == "alert_mgmt", f"Alert query {query!r} routed to {node!r} instead of alert_mgmt"


def test_alert_node_method_exists_on_orchestrator(orch):
    """_alert_mgmt_node must be implemented on the orchestrator."""
    assert hasattr(
        orch, "_alert_mgmt_node"
    ), "_alert_mgmt_node method missing from WorkflowOrchestrator"


# ── T22 automation-capability routing ─────────────────────────────────────────


@pytest.mark.parametrize(
    "query",
    [
        "Can the building automatically alert me when CO2 gets too high?",
        "Will the system automatically notify me if temperature exceeds 28 degrees?",
        "Could the building detect a water leak by itself and send an alert?",
        "Can it automatically monitor energy use and warn me if it spikes?",
    ],
)
def test_automation_capability_routes_to_check_node(orch, query):
    """Automation-capability questions must route to 'automation_capability_check' node."""
    state = _state(query, "automation_capability")
    node = orch._route_from_dialogue(state)
    assert node == "automation_capability_check", (
        f"Automation-capability query {query!r} routed to {node!r} "
        "instead of automation_capability_check"
    )


def test_automation_capability_node_method_exists(orch):
    """_automation_capability_check_node must be implemented on the orchestrator."""
    assert hasattr(
        orch, "_automation_capability_check_node"
    ), "_automation_capability_check_node method missing from WorkflowOrchestrator"


# ── T35 preference management routing ─────────────────────────────────────────


@pytest.mark.parametrize(
    "query",
    [
        "Remember that I prefer temperatures between 22 and 24 degrees",
        "What are my personal comfort preferences?",
        "Forget my temperature preference",
        "I like it warmer — can you save my preference?",
    ],
)
def test_preference_management_routes_to_node(orch, query):
    """Preference management phrasings must route to 'preference_management' node."""
    state = _state(query, "preference_management")
    node = orch._route_from_dialogue(state)
    assert (
        node == "preference_management"
    ), f"Preference query {query!r} routed to {node!r} instead of preference_management"


def test_preference_management_node_method_exists(orch):
    """_preference_management_node must be implemented on the orchestrator."""
    assert hasattr(
        orch, "_preference_management_node"
    ), "_preference_management_node method missing from WorkflowOrchestrator"


# ── T34 what-if intent override (fix 2026-06-12) ──────────────────────────────


@pytest.mark.parametrize(
    "query,llm_intent",
    [
        ("what would happen to energy use if we lowered heating by 2 degrees?", "trend"),
        ("what if we reduced the setpoint by 1 degree?", "forecast"),
        ("if we doubled occupancy, how would CO2 change?", "sensor_data"),
        ("suppose we turned down the AHU overnight, what would we save?", "general"),
    ],
)
def test_interventional_whatif_overrides_to_analytics(query, llm_intent):
    """Interventional what-ifs must override forecast/trend classification to analytics
    so the estimate-recipe path runs (T34 WARN fix)."""
    from orchestrator.workflow._orchestrator import whatif_intent_override

    assert (
        whatif_intent_override(query.lower(), llm_intent) == "analytics"
    ), f"{query!r} with intent {llm_intent!r} should override to analytics"


@pytest.mark.parametrize(
    "query,llm_intent",
    [
        # Plain forecasts (no intervention clause) must NOT be hijacked.
        ("what will the temperature be tomorrow?", "forecast"),
        ("is energy use trending up this week?", "trend"),
        # Routing-precedence: control / alert / report-intake are never overridden.
        ("what if we lower the setpoint — actually just set it to 21", "control"),
        ("alert me if we increase past 1000 ppm", "alert"),
        ("if we lowered the lift speed it groans — the lift is broken", "maintenance"),
    ],
)
def test_whatif_override_does_not_hijack(query, llm_intent):
    """Non-interventional or precedence-protected intents keep their routing."""
    from orchestrator.workflow._orchestrator import whatif_intent_override

    assert (
        whatif_intent_override(query.lower(), llm_intent) is None
    ), f"{query!r} with intent {llm_intent!r} must not be overridden"


# ═══════════════════════════════════════════════════════════════════════════════
# Tail N, 2026-09-30 — the six wrong lanes out of sixty real survey questions.
#
# Every string below is the EXACT text a survey participant typed
# (`paper/Survey analysis and results/corpus/classified_corpus.csv`), re-asked live on
# 2026-09-30 and hand-read in `docs/phase0/tail_N_2026-09-30_read.md`. They are kept
# verbatim — including the missing question mark on #5, which is half of why it failed.
#
# The contract half of these lives in `tests/test_routing_contract.py`; what is asserted
# here is the half this file owns — `_route_from_dialogue` and its inline overrides.
# ═══════════════════════════════════════════════════════════════════════════════

TAIL_N_QUESTIONS = {
    "safety_route": "if the main exit is blocked by smoke, what is the alternative route",
    "repairman": "can you call for a repairman?",
    "cool_down": "This room is far too hot. Where is a nearby area that I can go to cool down?",
    "overcrowded": "Can you tell me which areas are currently overcrowded?",
    "energy_alerts": "are there alerts for unusual energy patterns or wastage?",
    "remind_lighting": "Can the building remind me to adjust lighting?",
}


# ── BUG-1241 (SAFETY): a question must not become an urgent incident report ───


@pytest.mark.parametrize(
    "start",
    ["general", "capability", "metadata", "clarification", "recommend", "safety_report"],
)
def test_tail_n_safety_question_does_not_reach_the_intake_node(orch, start):
    """Live 2026-09-30 it answered: "your safety report has been logged as REP-F9828F ...
    Priority: URGENT". Someone asking where to evacuate got a ticket number.

    Routed here through the CONTRACT first, because that is where the misroute happened:
    `report_intake_intent` read the question as a statement (no "?", opening "if", the word
    "smoke") and `report_intake_statement` forced `safety_report` from seven intents.
    """
    from orchestrator.services.routing_contract import apply_contract

    q = TAIL_N_QUESTIONS["safety_route"]
    norm = {"intent": start, "analytics": False, "general": False}
    apply_contract(q, norm, stage="parse")
    state = _state(q, norm["intent"])
    node = orch._route_from_dialogue(state)
    assert node not in (
        "safety_report",
        "maintenance",
        "complaint",
    ), f"from {start!r} the evacuation question reached the intake node {node!r}"
    assert node == "capability", f"from {start!r} it routed to {node!r}"


# ── BUG-1242: a report-ID lookup needs something that looks like an ID ────────


@pytest.mark.parametrize(
    "message,expected",
    [
        ("can you call for a repairman?", None),
        # The same over-capture, three other ways, all found in the survey corpus.
        ("are all the smoke detectors reporting as online right now?", None),
        ("Can it detect leaks and alert a repairman?", None),
        ("Which BMS points are physically verified against the assets they represent?", None),
        # Real identifiers, in every spelling `_normalise_id` supports.
        ("what is the status of REP-F9828F?", "REP-F9828F"),
        ("status of rep f9828f", "REP-F9828F"),
        ("REPF9828F please", "REP-F9828F"),
    ],
)
def test_tail_n_report_id_is_not_any_word_starting_with_rep(message, expected):
    """Live: "can you call for a repairman?" gave "I couldn't find a report with ID
    **REP-AIRMAN**. Double-check the ID (format REP-XXXXXX)." The old pattern took six
    LETTERS after "rep", so "repairman", "reporting" and "represent" were identifiers."""
    from orchestrator.services.report_intake_service import ReportIntakeService

    svc = ReportIntakeService()
    assert svc.extract_report_id(message) == expected
    if expected is None:
        assert svc.classify_action(message) != "status"


# ── BUG-1243: a composed clarification is not a floor-plan request ────────────


def test_tail_n_a_composed_clarification_survives_the_floor_plan_keyword_override(orch):
    """Live route: intent_from_dialogue=clarification, overrides_applied=
    ["floor_plan_keyword_detection"], answered in 1.2 s with "Ground Floor - Floor 1 ... Which
    floor would you like to see?".

    The deictic guard had already decided "this room" names no room and composed the question
    to ask back (BUG-719). Then `is_floor_plan_query` matched the two words "where is".
    """
    state = _state(TAIL_N_QUESTIONS["cool_down"], "clarification")
    state.clarification_question = (
        "Which room do you mean? Answering about a different one would look right and be wrong."
    )
    node = orch._route_from_dialogue(state)
    assert node != "floor_plan", "a composed clarification was replaced by the floor picker"
    decision = state.intermediate_results["route_decision"]
    assert "floor_plan_keyword_detection" not in decision["overrides_applied"]


def test_a_bare_clarification_label_still_falls_through_to_the_floor_picker(orch):
    """The guard is narrowed to a clarification that actually composed a question: with none,
    the alternative is "Could you please provide more details about your question?"."""
    state = _state("where is the nearest exit?", "clarification")
    state.clarification_question = ""
    node = orch._route_from_dialogue(state)
    assert node == "floor_plan"


def test_the_floor_plan_override_still_claims_a_misclassified_floor_plan_query(orch):
    state = _state("show me the floor plan of floor 3", "general")
    assert orch._route_from_dialogue(state) == "floor_plan"


# ── BUG-1245 / BUG-1246: alert existence, and an automation question ──────────


def test_tail_n_alert_existence_question_reaches_the_automation_lane(orch):
    """Live: "I haven't created an alert yet. I need the value that should trigger it..." --
    a configuration form, to someone asking whether alerting exists at all."""
    from orchestrator.services.routing_contract import apply_contract

    q = TAIL_N_QUESTIONS["energy_alerts"]
    norm = {"intent": "alert", "analytics": False, "general": False}
    apply_contract(q, norm, stage="parse")
    assert norm["intent"] == "automation_capability"
    state = _state(q, norm["intent"])
    assert orch._route_from_dialogue(state) == "automation_capability_check"


def test_a_standing_alert_request_still_reaches_the_alert_lane(orch):
    from orchestrator.services.routing_contract import apply_contract

    q = "Alert me if CO2 exceeds 1000 ppm in room 5.01"
    norm = {"intent": "alert", "analytics": False, "general": False}
    apply_contract(q, norm, stage="parse")
    assert norm["intent"] == "alert"
    assert orch._route_from_dialogue(_state(q, "alert")) == "alert_mgmt"


@pytest.mark.parametrize(
    "start", ["general", "capability", "metadata", "clarification", "automation_capability"]
)
def test_tail_n_a_reminder_question_is_not_an_actuation_command(orch, start):
    """Live: "to request a change I need which setpoint and the value to set" -- a setpoint
    form, in answer to a question about whether the building can remind anyone of anything.
    `is_control_command` was True because the verb-target layer saw "adjust lighting"."""
    from orchestrator.services.routing_contract import apply_contract

    q = TAIL_N_QUESTIONS["remind_lighting"]
    norm = {"intent": start, "analytics": False, "general": False}
    apply_contract(q, norm, stage="parse")
    assert norm["intent"] == "automation_capability", norm["intent"]
    state = _state(q, norm["intent"])
    assert orch._route_from_dialogue(state) == "automation_capability_check"


@pytest.mark.parametrize(
    "command",
    [
        "open the windows on floor 3",
        "can you please unlock the door",
        "adjust the lighting in room 5.01",
        "dim the lights in the atrium",
        "keep the doors unlocked",
    ],
)
def test_a_real_actuation_command_still_reaches_control(command):
    """The reminder guard keys on the SUBJECT ("the building"), so a command to the assistant
    is untouched. Measured: 2 of 7,196 questions move, both of the intended shape."""
    from orchestrator.services.semantic_router import SemanticRouter

    assert SemanticRouter.is_control_command(command) is True


# ── #30 "which areas are currently overcrowded?" — NOT fixed, and why ─────────


def test_tail_n_overcrowded_is_recorded_as_open_not_silently_routed():
    """BUG-1244 is deliberately NOT fixed, and this test pins the reason so a later session
    does not "fix" it by pointing it at a ranking lane.

    Answering it needs occupancy against CAPACITY. The building holds 62 capacity figures,
    every one carrying `ontosage:capacityBasis` "estimated ... Not certified", over hundreds of
    occupancy series -- and BUG-954 (P1, open) has the occupancy count itself wrong by ~190x.
    A ranking built on that would be a safety-adjacent claim nobody made. The live failure is
    visible (a decline or a wrong lane); a confident "Room X is overcrowded" would not be.
    """
    from pathlib import Path

    ttl = Path(__file__).resolve().parent.parent / "input" / "bldg1_occupancy_capacity.ttl"
    if not ttl.is_file():  # parked building: the claim above is about data, not code
        pytest.skip("no active building; the capacity file lives under input/")
    text = ttl.read_text(encoding="utf-8", errors="replace")
    assert "capacityBasis" in text and "Not certified" in text
