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
    return [
        RecordClass(n, n, 5, _terms_for(n, n.replace("Record", " record")))
        for n in names
    ]


def test_terms_come_from_the_ontology_label_not_a_keyword_list():
    """A hand-written keyword list is a building literal by another route."""
    terms = _terms_for("Permit", "Permit to work")
    assert "permit" in terms
    assert "permits" in terms, "a counting question is almost always plural"
    assert "permit to work" in terms


def test_camel_case_class_names_become_words():
    terms = _terms_for("ConditionSurvey", "Condition survey")
    assert "condition survey" in terms
    assert "condition" in terms


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
