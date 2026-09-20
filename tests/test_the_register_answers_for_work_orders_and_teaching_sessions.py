# -*- coding: utf-8 -*-
"""Work-order and timetable questions are answered from the register, not the events store.

Two probe cases regressed together on 2026-09-19. "How many work orders are open?" came back
"**Work orders: 402 done, 65 open, 50 assigned** (517 total)" from the events store, while the
register it is pinned against holds 24 rows of which three are open (WO-008, WO-013, WO-015).
"Which teaching sessions are scheduled in Room 1.06?" came back "**This building doesn't keep a
record of that**" — the events lane has no timetable kind at all, so its vocabulary claims a
question it cannot serve, while 675 session rows sit in the register.

Neither had changed in the events lane: the LLM classifier simply chose `events` that day, having
chosen `metadata` the day before. Which lane answers must not depend on that, so the contract
claims both shapes before the events rule sees them.
"""

from __future__ import annotations

import pytest

from orchestrator.services import routing_contract as rc

pytestmark = pytest.mark.unit


@pytest.mark.parametrize(
    "question",
    [
        "How many work orders are open?",
        "How many open work orders are there, and which are overdue?",
        "Which work orders are overdue?",
        "Which teaching sessions are scheduled in Room 1.06?",
        "Which rooms have teaching sessions this week?",
        "How many timetabled sessions are there in Room 2.07?",
    ],
)
def test_a_register_shaped_question_is_claimed_for_the_register(question):
    assert rc.register_owns_the_record(question) is True, question


@pytest.mark.parametrize(
    "statement",
    [
        "The projector in Room 1.06 is broken",
        "Raise a work order for the leaking tap",
        "The lift is out of service again",
    ],
)
def test_a_statement_still_files_a_ticket(statement):
    assert rc.register_owns_the_record(statement) is False, statement


@pytest.mark.parametrize(
    "question",
    [
        "Is Room 1.06 free for the next two hours?",
        "Which meeting rooms are booked this afternoon?",
        "How busy was the building yesterday?",
        "Any anomalies this week?",
        # Ticket AGING is the events store's: the work-order register records no due date, so it
        # cannot say what is overdue.
        "Any overdue tickets?",
        "Are there any outstanding tickets?",
    ],
)
def test_the_events_store_keeps_its_own_questions(question):
    """Bookings, availability, footfall, anomalies and ticket aging are the events lane's own."""
    assert rc.register_owns_the_record(question) is False, question


def test_the_rule_claims_the_question_even_when_the_classifier_said_events():
    """The regression's own shape: no later rule can correct the classifier, so this one must
    fire from `events` itself."""
    from orchestrator.services.semantic_router import SemanticRouter

    for intent in ("events", "general", "metadata", "sensor_data"):
        ctx = rc._Ctx(
            query="How many work orders are open?",
            ql="how many work orders are open?",
            normalized={"intent": intent},
            sr=SemanticRouter,
        )
        assert rc._r_register_owns_work_orders_and_timetable(ctx) == "metadata", intent


def test_the_rule_runs_after_the_events_rule_and_has_the_last_word():
    """Every rule in a stage runs and each SETS the intent, so the later rule wins. Placed before
    `event_store_query` this fix changed nothing at all live."""
    names = [r.name for r in rc.PARSE_STAGE_RULES]
    assert names.index("register_owns_work_orders_and_timetable") > names.index("event_store_query")


@pytest.mark.parametrize(
    "question",
    ["How many work orders are open?", "Which teaching sessions are scheduled in Room 1.06?"],
)
def test_the_contract_leaves_the_question_with_the_register(question):
    normalized = {"intent": "events"}
    rc.apply_contract(question, normalized)
    assert normalized["intent"] == "metadata", question


def test_a_booking_question_still_ends_with_the_events_lane():
    normalized = {"intent": "general"}
    rc.apply_contract("Is Room 1.06 free for the next two hours?", normalized)
    assert normalized["intent"] == "events"
