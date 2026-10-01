# -*- coding: utf-8 -*-
"""BUG-947 (tail M #61) — "what kind of data is collected?" must reach the reach lane.

Measured on the held-out tail M against the 2026-09-29 build:

    "what kind of data is collected?"
    -> "I don't have that specific information on record for **Abacws Building**. For
        building-specific queries please contact your building's facilities / estates
        management team. Abacws Building does keep Waste collection point records, which I
        can read for you."

It is the first question anyone asks a system like this, and it is the one the system is best
placed to answer: it holds 44 record classes with instances and 45 measured modalities, and
the reach lane answers "what can you measure in this building?" by naming every one of them —
air quality through window contact, measured live the same day.

THE GAP WAS ONE VERB. `CAN_MEASURE_RE` alternates over measure|monitor|track|sense|detect|
read|report|tell me. "Collect" is not there, and "what kind of data IS COLLECTED" is passive
and names no actor at all, so neither form could match. `capability` was already in the set of
intents the routing rule may claim, so nothing else needed to move.

WHY THE FIX IS NARROW, AND WHAT THAT PROTECTS. "Collect" is also what happens to WASTE in this
building: 24 waste collection points and a collection schedule are held as records. "When is
the recycling collected?" must stay a register question and must not be answered with a list
of measurands. So `collect` is admitted only as a verb the asker attributes to the SYSTEM
("do you collect"), and the passive only for the fixed phrase "what kind/sort/type of data".
The negative cases below are the point of this file as much as the positive ones.
"""

from __future__ import annotations

import pytest

from orchestrator.services.observability import is_observability_question

pytestmark = pytest.mark.unit


@pytest.mark.parametrize(
    "question",
    [
        "what kind of data is collected?",  # tail M #61, verbatim
        "what data do you collect?",
        "what sort of data does this building collect?",
        "what types of data are collected here?",
        "do you collect noise data?",
        "can the system gather occupancy data?",
    ],
)
def test_a_question_about_what_is_collected_is_a_reach_question(question):
    assert is_observability_question(question) is True, question


@pytest.mark.parametrize(
    "question",
    [
        # "collect" is what happens to WASTE here — 24 collection points and a schedule.
        "when is the recycling collected?",
        "when is waste collected on floor 2?",
        "which waste collection points are on floor 3?",
        "how often is rubbish collected?",
        # an instruction, not a question about reach
        "collect the work order records for me",
        # someone else collecting something
        "who collects the data protection forms?",
    ],
)
def test_collecting_something_other_than_data_is_not_a_reach_question(question):
    assert is_observability_question(question) is False, question


@pytest.mark.parametrize(
    "question",
    [
        "what is the CO2 in room 5.01?",
        "what is the temperature on floor 3?",
        "how do I report a fault?",  # PROCEDURE_ASK_RE guards this one
    ],
)
def test_the_existing_boundaries_are_unmoved(question):
    """A reading question answered with a menu of measurands withholds data the building has —
    the failure this lane's docstring opens with."""
    assert is_observability_question(question) is False, question


@pytest.mark.parametrize(
    "question",
    ["What can you measure in this building?", "what sensors do you have?"],
)
def test_what_already_worked_still_works(question):
    assert is_observability_question(question) is True, question


def test_the_reach_rule_may_already_claim_a_capability_question():
    """The other half of why this fix is one pattern and not a routing change: tail M #61
    classified as `capability`, and the observability rule's claimable set already includes
    it. If that ever narrows, this fix stops working and the test should say so here."""
    from orchestrator.services import routing_contract as rc

    assert "capability" in rc._WEAK_INTENTS


# ── the second gate, which is what actually produces the answer ──────────────────────
#
# Teaching CAN_MEASURE_RE about "collect" got the question to the lane, and the lane then
# answered "**Which space did you mean?**" — because the branch that lists the building's
# measurands is gated on OPEN_QUESTION_RE instead. Two gates; widening one gets you halfway,
# and the halfway point looks like a fix if you only check the route.

from orchestrator.services.observability import is_open_question  # noqa: E402


@pytest.mark.parametrize(
    "question",
    [
        "what kind of data is collected?",
        "what data do you collect?",
        "what sort of data does this building collect?",
    ],
)
def test_it_also_counts_as_an_open_question_so_the_menu_is_given(question):
    assert is_open_question(question) is True, question


def test_a_question_naming_a_quantity_still_gets_a_verdict_not_a_menu():
    """ "Can you measure formaldehyde in room 5.01?" deserves an answer about formaldehyde.
    Listing what IS measured and leaving the asker to notice the absence is a non-answer."""
    q = "can you measure formaldehyde in room 5.01?"
    assert is_observability_question(q) is True
    assert is_open_question(q) is False


@pytest.mark.parametrize(
    "question",
    [
        "when is the recycling collected?",
        "what is collected on Tuesdays?",
        "how often is rubbish collected?",
    ],
)
def test_the_waste_round_is_neither_reach_nor_open(question):
    """Both gates must refuse it. This building holds 24 waste collection points and a
    schedule, and "when is the recycling collected?" answers from that register with bin
    names and dates — verified live 2026-09-29. A menu of measurands would replace a good
    answer with a wrong one."""
    assert is_observability_question(question) is False, question
    assert is_open_question(question) is False, question


def test_every_added_alternative_still_requires_the_word_data():
    """The guard that keeps the waste round out. A bare "what is collected" would claim it."""
    from orchestrator.services.observability import OPEN_QUESTION_RE

    # NOT by splitting on "|": that also splits alternations INSIDE groups, so
    # `(?:is|are)\s+collected` becomes a fragment holding "collect" and no "data". Check a
    # window before each occurrence instead, which is what the rule actually means.
    pattern = OPEN_QUESTION_RE.pattern
    at = pattern.find("collect")
    assert at != -1, "the pattern no longer mentions collecting at all"
    while at != -1:
        assert "data" in pattern[max(0, at - 90) : at], pattern[max(0, at - 90) : at + 10]
        at = pattern.find("collect", at + 1)
