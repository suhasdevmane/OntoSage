# -*- coding: utf-8 -*-
"""BUG-555: 'you mentioned X earlier' with no earlier reply is not answered as if it were true."""

import asyncio
import inspect
from types import SimpleNamespace

import pytest

from orchestrator.services.semantic_router import SemanticRouter

pytestmark = pytest.mark.unit


@pytest.mark.parametrize(
    "text",
    [
        "You mentioned a sensor fault earlier - has it been fixed yet?",
        "you said the lift was broken, is it working now?",
        "Earlier you recommended room 5.03 — is it still quiet?",
        "the AHU you flagged, what happened to it?",
        "As you said, CO2 was high. What now?",
    ],
)
def test_references_to_the_assistant_are_detected(text):
    assert SemanticRouter.refers_to_earlier_reply(text) is True


@pytest.mark.parametrize(
    "text",
    [
        "Has the sensor fault on floor 2 been fixed yet?",
        "Did anyone mention a leak in 3.02?",
        "What did the facilities team say about the lift?",
        "show me what you have on energy",
    ],
)
def test_ordinary_questions_are_not(text):
    assert SemanticRouter.refers_to_earlier_reply(text) is False


def _dialogue(messages):
    from orchestrator.workflow._orchestrator import WorkflowOrchestrator

    orch = WorkflowOrchestrator.__new__(WorkflowOrchestrator)
    called = []

    async def _detect(state):
        called.append(True)
        return {"intent": "general"}

    orch.dialogue_agent = SimpleNamespace(detect_intent=_detect)
    return orch, called


def test_the_guard_sits_before_intent_detection_and_checks_for_earlier_replies():
    from orchestrator.workflow._orchestrator import WorkflowOrchestrator

    src = inspect.getsource(WorkflowOrchestrator._dialogue_node)
    guard = src.index("refers_to_earlier_reply(_latest)")
    assert guard < src.index("await self.dialogue_agent.detect_intent(state)")
    assert '"assistant"' in src[guard - 400 : guard]
