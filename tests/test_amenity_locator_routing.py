# -*- coding: utf-8 -*-
"""Asking WHERE something can be done is not asking what a sensor reads (BUG-337).

Measured live: *"Where can I fill my water bottle on floor 3?"* returned the FLOOR 3
PLAN and a room list. ``is_data_query`` treats "a floor is named AND a measurement
word appears" as a reading request; the sentence names floor 3 and contains
"water", so it was promoted to ``sensor_data`` while the building's twelve
bottle-refill points sat in a lane the question never reached.

The distinguishing signal is the SHAPE, not the noun. "Where can I <verb>" and
"where is the nearest <thing>" ask for a facility to use; no amount of water being
metered turns them into a request for a reading.

Deliberately narrow. An extremum word hands the question straight back — "where is
the water usage highest on floor 3?" asks which place holds an extreme of a
measured value, and that is exactly the analytic question this must not steal.

The predicate lives in the routing contract, next to ``metered_quantity_question``,
because one decision with two owners is the drift this contract exists to prevent
(BUG-266).
"""

import pytest

from orchestrator.services.routing_contract import amenity_seeking_question
from orchestrator.services.semantic_router import SemanticRouter

pytestmark = pytest.mark.unit


# ── the live defect ──────────────────────────────────────────────────────────
@pytest.mark.parametrize(
    "question",
    [
        "Where can I fill my water bottle on floor 3?",
        "Where can I get a coffee on floor 1?",
        "Where can I charge my laptop on floor 2?",
        "Where is the nearest toilet to room 3.01?",
        "How do I get to room 5.01?",
    ],
)
def test_a_locator_question_is_not_a_data_query(question):
    assert SemanticRouter.is_data_query(question) is False, question


# ── and the reading questions it must not steal ──────────────────────────────
@pytest.mark.parametrize(
    "question",
    [
        "What is the water usage on floor 3?",
        "Latest CO2 in room 5.01",
        "Show me the temperature on floor 5",
        "How much electricity did floor 2 use yesterday?",
    ],
)
def test_reading_questions_are_still_data_queries(question):
    assert SemanticRouter.is_data_query(question) is True, question


@pytest.mark.parametrize(
    "question",
    [
        "Where is the water usage highest on floor 3?",
        "Where can I find the room with the highest CO2 on floor 5?",
    ],
)
def test_an_extremum_hands_a_where_question_back_to_analytics(question):
    """ "Where" plus a superlative asks which place holds an extreme of a measured
    value. Stealing that for the amenity lane would trade one wrong lane for
    another."""
    assert SemanticRouter.is_data_query(question) is True, question


def test_the_guard_is_not_blamed_for_a_gap_it_did_not_cause():
    """ "Where are the coldest rooms on floor 4?" is NOT recognised as a data query —
    and was not before this change either, because "coldest" appears in no analytic
    word list. A first draft of this file asserted otherwise and failed, which would
    have read as a regression in the new guard.

    The guard is exonerated explicitly rather than by deleting the case: the
    underlying gap is real and belongs to _DATA_ANALYTIC_WORDS, not here.
    """
    q = "Where are the coldest rooms on floor 4?"
    assert amenity_seeking_question(q) is False, "the new guard must not be firing here"
    assert SemanticRouter.is_data_query(q) is False


# ── the predicate itself ─────────────────────────────────────────────────────
@pytest.mark.parametrize(
    "question,expected",
    [
        ("Where can I fill my bottle?", True),
        ("Where could we park?", True),
        ("Where is the nearest lift?", True),
        ("How can I get to the lab?", True),
        ("What is the temperature?", False),
        ("Where is room 5.01?", False),  # a plain room lookup, not a facility ask
        ("Where can I see the highest readings?", False),  # extremum wins
    ],
)
def test_amenity_seeking_shapes(question, expected):
    assert amenity_seeking_question(question) is expected, question


def test_the_predicate_reads_shape_not_this_estate():
    """A list of Abacws amenities here would make the rule building-specific, which
    the design contract forbids for core code."""
    import inspect

    from orchestrator.services import routing_contract

    src = inspect.getsource(routing_contract.amenity_seeking_question)
    for literal in ("abacws", "bldg1", "5.01", "cardiff"):
        assert literal not in src.lower(), literal


def test_the_rule_has_one_owner():
    """is_data_query imports the predicate rather than restating it."""
    import inspect

    from orchestrator.services import semantic_router

    src = inspect.getsource(semantic_router.SemanticRouter.is_data_query)
    assert "amenity_seeking_question" in src
