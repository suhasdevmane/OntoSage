# -*- coding: utf-8 -*-
"""A class the building HOLDS outranks a lay-term match (V7-T21).

Lifting the permit register into 15 queryable instances changed nothing on its own,
because the capability short-circuit fired first: "how many permits are open?" matched
*open* against the Working Hours topic's lay terms and returned the building's opening
times, never reaching classification. Every lifted register would have been swallowed
the same way.

And the mirror case matters just as much. A question about a class the ontology defines
but the building does NOT hold reached the document lane, which handed back the nearest
passage — measured: a contracts question returned the PERMIT register. Naming the absent
system is both true and actionable.
"""

from __future__ import annotations

import pytest

from orchestrator.services.record_registry import (
    RecordClass,
    _terms_for,
    absent_record_class,
    held_record_class,
)

pytestmark = pytest.mark.unit


def _held(*names: str) -> list:
    return [RecordClass(n, n, 5, _terms_for(n, n.replace("Record", " record"))) for n in names]


def test_terms_come_from_the_ontology_label_not_a_keyword_list():
    """A hand-written keyword list is a building literal by another route."""
    terms = _terms_for("Permit", "Permit to work")
    assert "permit" in terms
    assert "permits" in terms, "a counting question is almost always plural"
    assert "permit to work" in terms


def test_camel_case_class_names_become_words():
    """A CamelCase class name becomes its phrase — and only its phrase.

    "condition" alone is NOT derived: the short form is declared as a lay term instead,
    because deriving head words from phrases caused three separate misroutes.
    """
    terms = _terms_for("ConditionSurvey", "Condition survey")
    assert "condition survey" in terms
    assert "condition surveys" in terms
    assert "condition" not in terms


def test_a_held_class_is_matched():
    held = _held("Permit")
    hit = held_record_class("How many permits are currently open?", held)
    assert hit is not None and hit.local_name == "Permit"


def test_an_unrelated_question_matches_nothing():
    """Opening hours must still reach the capability lane."""
    held = _held("Permit")
    assert held_record_class("When does the building open?", held) is None
    assert held_record_class("What is the temperature in room 5.04?", held) is None


def test_a_defined_but_unheld_class_is_named():
    """This is what turns one generic decline into a useful one."""
    assert absent_record_class("Which contracts expire this year?", _held("Permit")) == "Contract"
    assert absent_record_class("Is the AHU under warranty?", _held("Permit")) == "Warranty"


def test_a_class_the_building_holds_is_never_reported_absent():
    assert absent_record_class("How many permits are open?", _held("Permit")) is None


def test_a_question_about_no_record_class_is_left_alone():
    """Nothing here may interfere with ordinary routing."""
    held = _held("Permit")
    assert absent_record_class("What is the CO2 level on floor 5?", held) is None
    assert absent_record_class("Where is the nearest toilet?", held) is None


def test_matching_is_word_bounded():
    """A substring must not claim a question — 'permitted' is not 'permit'."""
    held = _held("Permit")
    assert held_record_class("Is smoking permitted in the atrium?", held) is None


def test_a_lay_term_phrase_is_never_reduced_to_its_head_word():
    """ "roof access permit" must not contribute a bare "roof".

    Measured: it did, and "what competency is required for the roof?" was answered from
    the PERMIT register instead of the competency one. The head word of a phrase is a
    different concept, not a shorter name for the same one.
    """
    terms = _terms_for("Permit", "Permit to work", "roof access permit|hot works permit")
    assert "roof access permit" in terms
    assert "roof" not in terms
    # "permit" survives because the CLASS NAME is the single word Permit — not because
    # anything was derived from the label "Permit to work".
    assert "permit" in terms


def test_declared_lay_terms_are_matched_whole():
    held = _held("ConditionSurvey")
    held[0] = RecordClass(
        "ConditionSurvey",
        "Condition survey",
        10,
        _terms_for("ConditionSurvey", "Condition survey", "expected life|remaining life"),
    )
    hit = held_record_class("Which assets are beyond their expected life?", held)
    assert hit is not None and hit.local_name == "ConditionSurvey"


def test_matching_is_now_uniform_and_no_head_word_survives_anywhere():
    """The held/absent asymmetry is gone, because the looser side was the defect.

    It was introduced when WorkOrder's bare "work" made the system decline a question the
    permit document answers. The same class of bug then appeared on the HELD side — a
    bare "room" from "Room booking" pulled two wayfinding questions into the register lane
    — so the phrase rule is now uniform rather than asymmetric.
    """
    strict = _terms_for("WorkOrder", "Work Order", include_head_words=False)
    loose = _terms_for("WorkOrder", "Work Order")
    assert "work" not in strict and "work" not in loose
    assert "work order" in strict and "work order" in loose


def test_a_generic_head_word_no_longer_triggers_a_decline():
    import orchestrator.services.record_registry as rr

    assert rr.absent_record_class("What is the procedure for hot works?", _held("Permit")) is None


def test_a_full_class_name_still_names_an_absent_system():
    import orchestrator.services.record_registry as rr

    assert rr.absent_record_class("Show me the work order backlog", _held("Permit")) == "WorkOrder"


def test_no_term_is_ever_derived_from_part_of_a_phrase():
    """Three separate defects came from this, so it is pinned uniformly.

    ontosage:Booking is labelled "Room booking". Deriving its head word gave a bare
    "room", which claimed every question naming a room — including two wayfinding
    questions that had been routing correctly. In English a compound noun's head is its
    LAST word, so the first word of a phrase names a different concept nearly every time.
    """
    booking = _terms_for("Booking", "Room booking", "booking|bookings|room booking")
    assert "room" not in booking
    assert "room booking" in booking
    assert "booking" in booking, "the short form is DECLARED, not derived"

    assert "roof" not in _terms_for("Permit", "Permit to work", "roof access permit")
    assert "work" not in _terms_for("WorkOrder", "Work Order")
    assert "condition" not in _terms_for("ConditionSurvey", "Condition survey")


def test_the_plural_of_a_whole_phrase_is_kept():
    """ "work orders" and "work order" name one thing — that much is safe."""
    terms = _terms_for("WorkOrder", "Work Order")
    assert "work order" in terms and "work orders" in terms


def test_wayfinding_questions_are_not_claimed_by_a_register():
    held = [
        RecordClass(
            "Booking",
            "Room booking",
            16,
            _terms_for("Booking", "Room booking", "booking|bookings|room booking"),
        )
    ]
    for query in (
        "Where's the nearest water refill station to Room 3.18?",
        "I've just arrived at reception - how do I get to the seminar room on level 3?",
        "Which rooms are we heating that nobody uses?",
    ):
        assert held_record_class(query, held) is None, query


def test_a_real_booking_question_is_still_claimed():
    """The TBox declares "booked", and that is what carries this question.

    Worth stating: with head-word derivation gone, a class is only as findable as its
    declared lay terms. That is the intended trade — the ontology says what a thing is
    called — but it means an incomplete layTerms list now shows up as a miss rather than
    being papered over by a guessed short form.
    """
    held = [
        RecordClass(
            "Booking",
            "Room booking",
            16,
            _terms_for("Booking", "Room booking", "booking|bookings|room booking|booked"),
        )
    ]
    assert held_record_class("Which rooms are booked tomorrow?", held) is not None


def test_plurals_of_class_names_are_english():
    """ "survey" -> "surveys", not "surveies" — the y/ies rule needs a consonant."""
    assert "condition surveys" in _terms_for("ConditionSurvey", "Condition survey")
    assert "warranties" in _terms_for("Warranty", "Warranty")
