# -*- coding: utf-8 -*-
"""BUG-731: a question classified into an intake intent must never be filed as a report.

"For each defect, what remedial scope and acceptance evidence were required, what was
completed, and has the corrected condition remained stable?" was classified as
`maintenance` and filed as REP-7420E1. The BUG-548 guard in `_report_intake_node` asks
`SemanticRouter.is_information_question`, which only recognised a wh-word at the very start
of the message, so a question opening with a scoping phrase ("For each defect, what ...")
fell through to `create`.
"""

import asyncio
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from orchestrator.services.semantic_router import SemanticRouter

pytestmark = pytest.mark.unit

ROW_49 = (
    "What temporary exposure is created by active construction, refurbishment, "
    "commissioning, relocation or intrusive maintenance, and during which zones and "
    "time windows?"
)
FILED_AS_REP_7420E1 = (
    "For each defect, what remedial scope and acceptance evidence were required, what was "
    "completed, and has the corrected condition remained stable?"
)

QUESTIONS = [
    ROW_49,
    FILED_AS_REP_7420E1,
    "In the last month, which rooms had faults reported?",
    "During refurbishment, what maintenance work is planned on floor 2?",
    "For the lifts, how often have they been out of order this year?",
    "Across all floors, are there any leaking pipes recorded?",
    "As a facility manager, which zones are affected by intrusive maintenance?",
    "In room 2.01, is the light broken?",
    "Can we see the maintenance history of the chillers?",
    "Tell me which lights were reported broken last week",
    "Which drains have needed jetting more than twice this year?",
    "Is the lift broken?",
    "When was the boiler last repaired after the leak?",
]

STATEMENTS = [
    "the toilet is leaking",
    "The toilet on floor 2 is leaking.",
    "Suggestion: add more bike racks near the entrance",
    "there's a broken light in room 2.01",
    "report a broken light",
    "I want to report a leaking tap in the kitchen",
    "Please fix the flickering light on floor 3",
    "In room 2.01 the light is flickering",
    "On floor 3, the fire exit is blocked",
    # Requests addressed to someone, and a fault stated before a question, still file.
    "Can you fix the leaking tap?",
    "Could someone look at the broken light in room 2.01?",
    "Since the lift is broken, when will it be fixed?",
    "The lift is broken. When will it be fixed?",
]


@pytest.mark.parametrize("question", QUESTIONS)
def test_questions_are_information_questions_and_not_reports(question):
    assert SemanticRouter.is_information_question(question) is True
    assert SemanticRouter.report_intake_intent(question) is None


@pytest.mark.parametrize("statement", STATEMENTS)
def test_statements_and_requests_are_not_information_questions(statement):
    assert SemanticRouter.is_information_question(statement) is False


@pytest.mark.parametrize(
    "statement,intent",
    [
        ("the toilet is leaking", "maintenance"),
        ("Suggestion: add more bike racks near the entrance", "suggestion"),
        ("there's a broken light in room 2.01", "maintenance"),
        ("report a broken light", "maintenance"),
        ("I want to report a leaking tap in the kitchen", "maintenance"),
        ("On floor 3, the fire exit is blocked", "safety_report"),
    ],
)
def test_statements_still_classify_as_reports(statement, intent):
    assert SemanticRouter.report_intake_intent(statement) == intent


def test_the_control_gate_is_not_widened():
    """The widening lives in the method; `is_control_command` keeps its own narrower rule."""
    assert SemanticRouter.is_control_command("please close the blinds") is True
    assert SemanticRouter.is_control_command("can you unlock the main door") is True


# ── the intake node itself: nothing is written for a question ─────────────────────────────


def _intake(message, intent="maintenance"):
    from orchestrator.workflow._orchestrator import WorkflowOrchestrator

    orch = WorkflowOrchestrator.__new__(WorkflowOrchestrator)
    orch.postgres_manager = None
    orch._sparql_node = AsyncMock(side_effect=lambda s: s)
    service = MagicMock()
    service.category_for_intent.return_value = intent
    service.classify_action.return_value = "create"
    service.create_report = AsyncMock(return_value={"success": True, "message": "filed"})
    state = SimpleNamespace(
        current_intent=intent,
        messages=[SimpleNamespace(content=message)],
        user_message=message,
        intermediate_results={"entities": []},
        user_id="u",
        building_id="b",
        personas=[],
        persona="general",
        conversation_id="c",
    )
    with patch(
        "orchestrator.services.report_intake_service.get_report_intake_service",
        return_value=service,
    ):
        try:
            asyncio.run(orch._report_intake_node(state))
        except Exception:
            pass  # the create path touches more of the state than this stub carries
    return orch, service, state


@pytest.mark.parametrize("intent", ["maintenance", "complaint", "safety_report"])
@pytest.mark.parametrize("question", [ROW_49, FILED_AS_REP_7420E1])
def test_the_live_questions_file_nothing(question, intent):
    orch, service, state = _intake(question, intent)
    service.create_report.assert_not_called()
    orch._sparql_node.assert_awaited_once()
    assert state.intermediate_results["report_intake_skipped"] == "information_question"


@pytest.mark.parametrize(
    "statement",
    [
        "The toilet on floor 1 is leaking",
        "report a broken light",
        "I want to report a leaking tap in the kitchen",
        "Could someone look at the broken light in room 2.01?",
    ],
)
def test_statements_are_still_filed(statement):
    orch, service, state = _intake(statement)
    orch._sparql_node.assert_not_called()
    assert "report_intake_skipped" not in state.intermediate_results
    service.create_report.assert_called_once()
