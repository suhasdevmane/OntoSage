# -*- coding: utf-8 -*-
"""BUG-189: a named space must be existence-checked even when a floor is also named.

Found live. Policy trap P001 asks "What is the average temperature in the public
corridor on floor 1 right now?". bldg2 has no corridor instance at all, yet the
system answered "**Average temperature: 21.08 °C** ... Latest reading from
*RM109_room*" — a ROOM's reading attributed to a corridor that does not exist.
The leak benchmark scored it PASS, because the trap expects an answer and numbers
were present, so the grader actively rewarded the fabrication.

Two independent causes, both pinned here:

  1. `corridor` was absent from the generic space-head vocabulary, so the phrase
     was invisible to the gate entirely.
  2. `detect_typed_referent` returns on its FIRST match and checked floors before
     spaces, so "<space> on floor N" resolved to the floor. The floor exists, the
     gate passed, and the space was never checked — even for heads the gate knows.

The rule: the MOST SPECIFIC referent governs. A question naming a space is about
that space, and the floor is only context.
"""

from __future__ import annotations

import pytest

from orchestrator.services import referent_resolver as rr

pytestmark = pytest.mark.unit


@pytest.mark.parametrize(
    "query, expected_head",
    [
        (
            "What is the average temperature in the public corridor on floor 1 right now?",
            "corridor",
        ),
        ("What is the CO2 in the atrium on floor 1?", "atrium"),
        ("How stuffy is the gym on the 2nd floor?", "gym"),
        ("Temperature in the west wing on floor 3?", "wing"),
    ],
)
def test_a_named_space_is_not_shadowed_by_a_floor(query, expected_head):
    got = rr.detect_typed_referent(query)
    assert got is not None, f"gate cannot see any referent in: {query}"
    assert got.kind == rr.KIND_SPACE, (
        f"expected the SPACE to govern, got {got.kind} ({got.phrase}) — a floor that "
        "exists lets an unverified space through the gate"
    )
    assert expected_head in got.token


def test_corridor_is_a_recognised_space_head():
    """The P001 fabrication: without this the phrase is invisible to the gate."""
    got = rr.detect_typed_referent("What is the temperature in the public corridor?")
    assert got is not None and got.kind == rr.KIND_SPACE
    assert "corridor" in got.token


@pytest.mark.parametrize(
    "query, token",
    [
        ("How many sensors are on floor 3?", "floor|3"),
        ("What is the temperature on the 2nd floor?", "floor|2"),
    ],
)
def test_a_floor_only_question_still_resolves_to_the_floor(query, token):
    """The reorder must not blind the gate to plain floor questions."""
    got = rr.detect_typed_referent(query)
    assert got is not None and got.kind == rr.KIND_FLOOR
    assert got.token == token


def test_whole_building_questions_stay_ungated():
    """Regression guard: widening the space vocabulary must not start gating these."""
    for q in ("How many sensors are there?", "What is the temperature?"):
        assert rr.detect_typed_referent(q) is None
