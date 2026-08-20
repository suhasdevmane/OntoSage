# -*- coding: utf-8 -*-
"""KNOWN-008: a fault report with no location must be clarified, not silently filed.

"report broken light" used to file REP-C9228F with no location and no device —
a ticket nobody can action, because whoever picks it up cannot find the light.
Asking once is better. Asking TWICE is worse than filing, so the prompt must be
self-limiting: if the previous assistant turn was already this question, file
with whatever we have.
"""

from __future__ import annotations

import pytest

from orchestrator.workflow._orchestrator import WorkflowOrchestrator

pytestmark = pytest.mark.unit


class _Msg:
    def __init__(self, role, content):
        self.role = role
        self.content = content


class _State:
    def __init__(self, messages=None):
        self.messages = messages or []


def test_no_prior_assistant_turn_means_not_yet_asked():
    assert WorkflowOrchestrator._already_asked_where(_State()) is False


def test_a_normal_previous_answer_does_not_count_as_asking():
    st = _State(
        [
            _Msg("user", "report broken light"),
            _Msg("assistant", "Your report has been logged as REP-123456."),
        ]
    )
    assert WorkflowOrchestrator._already_asked_where(st) is False


def test_the_clarification_is_recognised_on_the_next_turn():
    st = _State(
        [
            _Msg("user", "report broken light"),
            _Msg("assistant", WorkflowOrchestrator._WHERE_PROMPT_TEXT + "\n\nTell me the room"),
        ]
    )
    assert WorkflowOrchestrator._already_asked_where(st) is True


def test_only_the_MOST_RECENT_assistant_turn_decides():
    """An old clarification must not suppress a fresh report later in the chat."""
    st = _State(
        [
            _Msg("assistant", WorkflowOrchestrator._WHERE_PROMPT_TEXT),
            _Msg("user", "RM101"),
            _Msg("assistant", "Logged as REP-000001."),
            _Msg("user", "report broken light"),
        ]
    )
    assert WorkflowOrchestrator._already_asked_where(st) is False


def test_the_prompt_names_what_is_missing():
    p = WorkflowOrchestrator._WHERE_PROMPT_TEXT
    assert "room" in p.lower() and "equipment" in p.lower()


# ── the message itself may name the place, even when entity extraction misses ──


@pytest.mark.parametrize(
    "text",
    [
        "The light in RM101 is broken",
        "the light in rm 101 is broken",
        "The toilet on floor 2 is leaking",
        "Broken socket in room 3.15",
        "The heater in the gym is dead",
        "office 204 has a flickering light",
    ],
)
def test_a_message_that_names_a_place_is_not_asked_where(text):
    """The first cut asked 'which room?' for these — worse than the bug it fixed."""
    assert WorkflowOrchestrator._message_names_a_place(text) is True


@pytest.mark.parametrize(
    "text",
    [
        "report broken light",
        "there is a leak",
        "the lights keep flickering",
        "something smells burnt",
        "",
    ],
)
def test_a_message_naming_nowhere_is_asked(text):
    assert WorkflowOrchestrator._message_names_a_place(text) is False
