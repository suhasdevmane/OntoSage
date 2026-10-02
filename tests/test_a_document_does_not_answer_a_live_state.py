# -*- coding: utf-8 -*-
"""A document never answers whether something is so RIGHT NOW (BUG-1407 residual, BUG-836).

MEASURED 2026-10-01, occupant01 on /v1, tail O #21:

    Q 'Are the doors locked'
    A 'Yes, the door was secured; access log reviewed.
       *From the building's documents: Accessible Route Register, Incident And Near Miss Log.*'

A past event about ONE door, lifted from an incident log, read back as the present state of
all of them -- a definite yes a reader would act on. A document records procedures and past
events; no passage can say what is so now, so the composer is not asked. The detector was
measured over the 4,060-question bank before landing: 2 matches, both live-state asks.
"""

import pytest

from orchestrator.services.passage_relevance import is_live_state_question

pytestmark = pytest.mark.unit


@pytest.mark.parametrize(
    "q",
    [
        "Are the doors locked",
        "Are the doors locked?",
        "Is the lift working?",
        "Is the heating on today?",
        "Are the solar panels working?",
        "Is the fire alarm armed?",
        "Is the main entrance locked right now?",
        "Are the lights on at the moment?",
        "Is the cafe open right now?",
    ],
)
def test_a_present_state_yes_no_question(q):
    assert is_live_state_question(q), q


@pytest.mark.parametrize(
    "q",
    [
        "Is the building open today?",  # opening hours: a document DOES answer this
        "Is the cafe open on weekends?",
        "Are there showers?",
        "Are the lights on in room 2.01 right now?",  # names a place: the data lane's shape
        "What is the procedure if the doors are locked?",
        "Is the door locking policy documented?",
        "How do I report a broken door?",
        "",
    ],
)
def test_not_a_present_state_question(q):
    assert not is_live_state_question(q), q


def test_the_capability_lane_checks_before_composing():
    import inspect

    from orchestrator.agents import capability_agent

    src = inspect.getsource(capability_agent)
    i_guard = src.index("is_live_state_question(state.user_message")
    i_compose = src.index("composed, _decided = await self._answer_from_passages(")
    assert i_guard < i_compose, "the live-state check must run BEFORE the passage composer"
    assert "document_cannot_answer_live_state" in src
