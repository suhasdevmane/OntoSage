# -*- coding: utf-8 -*-
"""Reporting an emergency and asking what to do is usually two sentences (BUG-1393).

THE DEFECT, live, occupant01 on /v1, both caches flushed:

    Q: "The fire alarm is sounding. What should I do?"
    A: "I did not find any instructions for a sounding fire alarm in the building's fire safety
        asset records. ... The only fire-alarm asset in the building is the Fire alarm control
        panel (FSA-001) ... Its recorded status is overdue ...
        Because the register contains no guidance on what to do when the alarm sounds, you
        should follow the building's standard fire-alarm procedures (e.g., evacuate, contact
        the fire department,"

The building holds the answer: `bldg:Cap_evacuation` declares the steps (nearest marked exit, do
not use the lifts, assembly point on Senghennydd Road, report to the floor warden). The answer
above declines it and then writes its own generic advice in the same breath, and stops
mid-sentence.

`EMERGENCY_ACTION_RE` joined its two halves with `[^?.!]{0,60}`, so a full stop between them
blocked the match while a comma did not. TWO independent gates read that one predicate --
`dialogue_agent`'s metadata short-circuit and the `emergency_action_is_a_procedure` routing rule
-- so both stood down together and the asset register was left holding a procedure question.

These tests assert the PREDICATE, which is what both gates consult. They do not assert the live
route; that is verified by asking the running stack.
"""

import pytest

from orchestrator.services.emergency_procedure import is_emergency_action_question

#: THE UNIT MARKER IS NOT AUTOMATIC, and without it this file is DESELECTED by `pytest -m
#: unit` -- the suite that gates a commit. Three test files written on 2026-10-01 were
#: missing it, so 61 tests ran green when invoked by name and protected nothing in the
#: gate. The tell was the summary line: `deselected` rose by exactly the number of tests
#: added while `passed` did not move.
pytestmark = pytest.mark.unit

#: A person telling the system what is happening, then asking what to do. Two sentences.
MUST_MATCH = [
    "The fire alarm is sounding. What should I do?",
    "There is smoke in the corridor. What should I do?",
    "Someone has collapsed. Who do I call?",
    "There's a flood in the plant room. Who should I tell?",
    # the one-sentence forms that always worked -- these must not regress
    "What should I do if the fire alarm goes off?",
    "The fire alarm is sounding, what should I do?",
    "What should I do when the fire alarm sounds?",
    # the 2026-09-30 case (BUG-1241) that this regex was widened for
    "if the main exit is blocked by smoke, what is the alternative route",
]

#: Questions about the KIT, its condition or its records. The register owns these.
MUST_NOT_MATCH = [
    "Which fire doors are overdue a test?",
    "When was the fire alarm panel last tested?",
    "How many smoke detectors are in the building?",
    "Where are the fire extinguishers?",
    # no emergency at all
    "What should I do about my booking?",
    "What should I do to reserve a meeting room?",
    # TWO TOPICS, separated by a `?`. The barrier that stays a barrier is what makes
    # crossing a full stop safe: without it, any question mentioning an emergency anywhere
    # would pull any later "what should I do" into a safety match.
    "Where are the fire extinguishers? What should I do about my booking?",
    # an emergency mentioned in the past, and an equipment question after it
    "There was a fire drill last week. What should I do about the broken projector?",
]


@pytest.mark.parametrize("question", MUST_MATCH)
def test_an_action_question_about_an_emergency_is_recognised(question):
    assert is_emergency_action_question(question), (
        "a person asking what to do in an emergency was not recognised, so both the metadata "
        "short-circuit and the routing rule stand down and an asset register answers: %r" % question
    )


@pytest.mark.parametrize("question", MUST_NOT_MATCH)
def test_an_equipment_or_unrelated_question_is_not_claimed(question):
    assert not is_emergency_action_question(question), (
        "this belongs to the register or to another lane, and claiming it for the procedure "
        "lane costs the answer the reader wanted: %r" % question
    )


def test_the_question_mark_is_still_a_barrier():
    """The counterfactual for the whole change.

    Crossing a full stop is only safe because `?` and `!` still are not crossed. If this ever
    passes with a `?` in the gap, the rule has become 'any emergency word plus any later action
    frame', and every two-part question mentioning a fire becomes a safety question.
    """
    assert not is_emergency_action_question(
        "Where are the fire extinguishers? What should I do about my booking?"
    )
    assert not is_emergency_action_question(
        "Is there a fire drill this week? What should I do to book a room?"
    )


def test_both_halves_are_still_required():
    """A guard on the guard: neither an emergency alone nor an action frame alone may match."""
    assert not is_emergency_action_question("Is there a fire alarm in the building?")
    assert not is_emergency_action_question("What should I do?")
    assert not is_emergency_action_question("")
