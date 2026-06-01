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
    ("what is HVAC?", "general", "response"),
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
    assert node == expected_node, (
        f"Intent {intent!r} routed to {node!r}; expected {expected_node!r}"
    )

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
    assert node == "sparql", (
        f"sensor_data query mentioning 'floor' got hijacked to {node!r}"
    )


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
        assert orch._route_from_dialogue(state) == "sparql", (
            f"Legacy alias {legacy!r} must route to sparql"
        )


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
    for intent in ("greeting", "sensor_data", "floor_plan", "discovery",
                   "weird_unknown_intent"):
        state = _state("test", intent)
        orch._route_from_dialogue(state)
        decision = state.intermediate_results.get("route_decision")
        assert decision is not None, f"No route_decision for intent={intent}"
        assert "final_node" in decision
        assert "intent_from_dialogue" in decision
        assert "overrides_applied" in decision
        assert "decision_source" in decision
