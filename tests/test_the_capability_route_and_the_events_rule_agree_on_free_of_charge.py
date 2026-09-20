# -*- coding: utf-8 -*-
"""One definition of "a booking question", used by every consumer (BUG-549, second half).

The events rule and the event service exclude "free" in the sense of NO COST ("Is tap water free
somewhere, or do I have to buy bottles?"). The capability route's veto imported the raw EVENTS_RE and
did not, so that sentence — a demo-script question — was vetoed as a booking question and never
reached the deterministic amenity route, while "Can I get free water in this building?" resolved in a
second. Found 2026-09-18 by reading which of nineteen vetoes fired.
"""

from __future__ import annotations

import inspect

import pytest

from orchestrator.services import routing_contract as rc

pytestmark = pytest.mark.unit


@pytest.mark.parametrize(
    "question",
    [
        "Is tap water free somewhere, or do I have to buy bottles?",
        "Is the water free of charge here?",
        "Is drinking water free or do I have to pay?",
        "Is parking free, or does it cost anything?",
    ],
)
def test_free_meaning_no_cost_is_not_a_booking_question(question):
    assert rc.events_question(question) is False, question


@pytest.mark.parametrize(
    "question",
    [
        "Is Room 1.06 free for the next two hours?",
        "Is the seminar room booked this afternoon?",
        "Is room 5.01 free at 3pm?",
        "Which rooms are free right now?",
        "Any rooms available tomorrow?",
        "Is there a booking for Room 2.13 on Friday?",
    ],
)
def test_a_booking_question_is_still_one(question):
    assert rc.events_question(question) is True, question


def test_booking_vocabulary_overrides_the_cost_sense():
    """'free' plus a money word is still a booking question when a booking is named."""
    assert rc.events_question("Is the room booked, or is it free of charge to reserve?") is True


def test_the_rule_and_the_capability_veto_use_the_same_predicate():
    from orchestrator.agents import dialogue_agent

    rule = inspect.getsource(rc._r_event_store_query)
    assert "events_question(c.query)" in rule
    assert "EVENTS_RE.search" not in rule, "the rule must go through the shared predicate, not the raw regex"
    agent = inspect.getsource(dialogue_agent)
    assert "events_question as _events_question" in agent
    assert "and not _events_question(user_query)" in agent
    assert "EVENTS_RE as _EVENTS_RE" not in agent, "the raw regex must not come back into the veto"
