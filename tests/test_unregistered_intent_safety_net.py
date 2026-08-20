"""Phase 10G — safety net for YAML-added intents pointing to missing nodes.

When a building's `input/<bldg>/intents.yaml` adds a new intent like
`lab_booking` but doesn't ship a `lab_booking` workflow node, the routing
function must NOT return "lab_booking" because LangGraph would crash with
"branch returned unknown node".  Instead it must:

  1. Detect that "lab_booking" is not in the registered node set
  2. Fall back to "response"
  3. Set a polite `dialogue_response` so the user sees a clear message
"""

from __future__ import annotations

from unittest.mock import MagicMock, patch

import pytest

from shared.models import ConversationState, Message


def _make_state(intent: str) -> ConversationState:
    state = ConversationState(
        conversation_id="phase10g-test",
        user_id="tester",
        user_message="hi",
        messages=[Message(role="user", content="hi")],
        intermediate_results={},
    )
    state.current_intent = intent
    return state


def _make_orchestrator_stub():
    from orchestrator.workflow import WorkflowOrchestrator

    inst = WorkflowOrchestrator.__new__(WorkflowOrchestrator)
    inst._user_wants_visualization = MagicMock(return_value=False)
    return inst


def test_unknown_route_target_falls_back_to_response():
    """An intent whose route_target points to a node that doesn't exist
    must NOT be returned verbatim — fall back to 'response'."""
    from orchestrator.intents import IntentDefinition, IntentRegistry

    orch = _make_orchestrator_stub()
    state = _make_state("totally_made_up_intent")

    fake_reg = IntentRegistry(
        intents=[
            IntentDefinition(
                name="totally_made_up_intent",
                description="...",
                pipeline_group="standalone",
                route_target="nonexistent_node_name",
            ),
        ]
    )
    with patch(
        "orchestrator.intents.get_intent_registry",
        return_value=fake_reg,
    ):
        target = orch._route_from_dialogue(state)

    assert target == "response", f"Expected fallback to 'response', got {target!r}"


def test_fallback_sets_polite_dialogue_response():
    """When falling back, the routing should set a `dialogue_response`
    so the response node has something user-facing to say."""
    from orchestrator.intents import IntentDefinition, IntentRegistry

    orch = _make_orchestrator_stub()
    state = _make_state("lab_booking")

    fake_reg = IntentRegistry(
        intents=[
            IntentDefinition(
                name="lab_booking",
                description="...",
                pipeline_group="standalone",
                # default route_target falls back to intent name → "lab_booking"
            ),
        ]
    )
    with patch(
        "orchestrator.intents.get_intent_registry",
        return_value=fake_reg,
    ):
        orch._route_from_dialogue(state)

    msg = state.intermediate_results.get("dialogue_response", "")
    assert (
        "lab_booking" in msg or "lab" in msg
    ), f"Expected user-facing message mentioning the intent, got: {msg!r}"


def test_registered_node_routes_through_normally():
    """A KNOWN node like 'floor_plan' must not trigger the fallback."""
    from orchestrator.intents import IntentDefinition, IntentRegistry

    orch = _make_orchestrator_stub()
    state = _make_state("floor_plan")

    fake_reg = IntentRegistry(
        intents=[
            IntentDefinition(
                name="floor_plan",
                description="...",
                pipeline_group="standalone",
            ),
        ]
    )
    with patch(
        "orchestrator.intents.get_intent_registry",
        return_value=fake_reg,
    ):
        target = orch._route_from_dialogue(state)

    # floor_plan IS a registered node — should route there directly
    # (not "response").
    assert target == "floor_plan"
