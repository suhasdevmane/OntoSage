# -*- coding: utf-8 -*-
"""BUG-548: a question about how devices behave was routed to control and queued a command."""

import pytest

from orchestrator.services.semantic_router import SemanticRouter

pytestmark = pytest.mark.unit


@pytest.mark.parametrize(
    "question",
    [
        "Which shutters or doors fail open versus fail locked on power loss?",
        "What happens if we turn off the AHU at 6pm?",
        "does the door fail locked?",
        "Is the fire door fail-safe?",
        "Which lights can be switched off at night?",
        "How do I open the bike store?",
        "Why does the heating turn on at 5am?",
        "the fire doors fail-safe on alarm, right?",
    ],
)
def test_information_questions_are_not_commands(question):
    assert SemanticRouter.is_control_command(question) is False


@pytest.mark.parametrize(
    "command",
    [
        "open the door",
        "turn off the lights on floor 2",
        "can you unlock the main door",
        "please close the blinds",
        "Do something about the temperature in here",
        "Switch off the lights in 5.01",
        "unlock the doors that fail locked",
    ],
)
def test_commands_are_still_commands(command):
    assert SemanticRouter.is_control_command(command) is True


# ── …and never a filed report (BUG-548, the write-side twin) ────────────────────────────

import asyncio  # noqa: E402
from types import SimpleNamespace  # noqa: E402
from unittest.mock import AsyncMock, MagicMock, patch  # noqa: E402


def _intake(message):
    from orchestrator.workflow._orchestrator import WorkflowOrchestrator

    orch = WorkflowOrchestrator.__new__(WorkflowOrchestrator)
    orch.postgres_manager = None
    orch._sparql_node = AsyncMock(side_effect=lambda s: s)
    service = MagicMock()
    service.category_for_intent.return_value = "maintenance"
    service.classify_action.return_value = "create"
    service.create_report = AsyncMock(return_value={"success": True, "message": "filed"})
    state = SimpleNamespace(
        current_intent="maintenance", messages=[SimpleNamespace(content=message)],
        user_message=message, intermediate_results={"entities": []}, user_id="u",
        building_id="b", personas=[], persona="general", conversation_id="c",
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


def test_a_question_classified_as_maintenance_files_nothing():
    orch, service, state = _intake("Which drains have needed jetting more than twice this year?")
    service.create_report.assert_not_called()
    orch._sparql_node.assert_awaited_once()
    assert state.intermediate_results["report_intake_skipped"] == "information_question"


def test_a_fault_statement_is_still_filed():
    orch, service, state = _intake("The toilet on floor 1 is leaking")
    orch._sparql_node.assert_not_called()
    assert "report_intake_skipped" not in state.intermediate_results
    service.create_report.assert_called_once()
