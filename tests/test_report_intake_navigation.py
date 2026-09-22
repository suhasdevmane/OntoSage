"""A request to be guided to a safety place is navigation, not a safety report."""

import pytest

from orchestrator.services.semantic_router import SemanticRouter

pytestmark = pytest.mark.unit


@pytest.mark.parametrize(
    "q",
    [
        "Take me to the nearest fire exit.",
        "Guide me to the assembly point",
        "Show me the way out",
        "Please lead me to the nearest first aid point",
    ],
)
def test_navigation_request_is_not_filed(q):
    assert SemanticRouter.report_intake_intent(q) is None


def test_a_blocked_exit_statement_is_still_a_safety_report():
    assert SemanticRouter.report_intake_intent("The fire exit on floor 2 is blocked") == "safety_report"


@pytest.mark.parametrize(
    "q",
    [
        "Before I start a long acquisition, are the approved power, network and ventilation services "
        "currently available, and what verified interruption risks remain?",
        "When the plant is shut down, which floors lose ventilation?",
    ],
)
def test_a_question_after_a_subordinate_clause_is_not_a_command(q):
    assert SemanticRouter.is_control_command(q) is False


def test_a_conditional_command_is_still_a_command():
    assert SemanticRouter.is_control_command("If it gets hot, turn off the AHU") is True
