"""CAVEAT-1629, second half: the building's only atrium is BOUND, not merely not refused.

Stepping aside alone let the lane read "glass atrium" as nothing and answer with the whole
building's CO2 (live, 2026-10-11). The one candidate now travels with the step-aside, the question
is rewritten to it for the turn, and the answer says so in a footnote.
"""

from __future__ import annotations

import inspect

import pytest

from orchestrator.workflow import _orchestrator as orch

pytestmark = pytest.mark.unit


@pytest.mark.parametrize(
    "question, phrase, local, want",
    [
        (
            "What is the CO2 in the glass atrium?",
            "glass atrium",
            "Room1.04",
            "What is the CO2 in Room 1.04?",
        ),
        (
            "How noisy is the Glass Atrium now?",
            "glass atrium",
            "Room1.04",
            "How noisy is Room 1.04 now?",
        ),
        ("Is the main lobby warm?", "main lobby", "Lobby_Ground", "Is Lobby Ground warm?"),
    ],
)
def test_the_phrase_becomes_the_one_place_it_can_mean(question, phrase, local, want):
    assert orch._bind_sole_candidate(question, phrase, local) == want


def test_nothing_to_bind_leaves_the_question_alone():
    assert orch._bind_sole_candidate("What is the CO2?", "", "Room1.04") == "What is the CO2?"


def test_the_binding_is_disclosed_and_never_outlives_its_turn():
    src = inspect.getsource(orch.WorkflowOrchestrator._response_node)
    assert 'pop("referent_bound"' in src
    assert "the only one of its kind" in src
