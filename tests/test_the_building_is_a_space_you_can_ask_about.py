# -*- coding: utf-8 -*-
"""The most natural opening question was answered with a clarify loop (BUG-486).

MEASURED live, 2026-09-08:

    Q: "What is measured in this building?"
    A: **Which space did you mean?** I can say what is measured in a particular room,
       floor or zone, but I need to know which one before I can answer whether it is
       instrumented.

    Q: "What is monitored across the whole building?"
    A: (the same clarify)

    Q: "What can you measure in this building?"
    A: **No — in this building is not measured in this building.** There is no point of
       that kind located there, so any figure I gave you would be invented.

The third is the serious one. `NAMED_QUANTITY_RE` captured the words "in this building" as
the QUANTITY — the group is non-greedy and the `\\s*\\?` lookahead accepted the preposition
phrase — so the lane produced a garbled sentence AND a confident negative about a referent
that does not exist. A verb followed straight by a preposition names no quantity at all.

WHY THE CLARIFY WAS WRONG
-------------------------
`_observability_space` recognised rooms and floors. The building — the outermost space,
and the one the question named — was the single space it could not resolve. So the scope
was never missing; the resolver could not see it, and the lane asked the reader for
something they had already given. That is the BUG-472 shape: offering someone the answer
they just supplied.

An OPEN question wants the menu, and the menu is exactly what this lane can produce
without a room: the modalities the building declares. The fix is narrowed to open
questions, because a SPECIFIC question about an unnamed room should still clarify — there
the answer genuinely varies space by space, and asking is correct.

Live after the change, all three return "**Across Abacws Building I can measure:** air
quality, co2, … " and room-scoped questions are untouched.
"""

from __future__ import annotations

import inspect

import pytest

pytestmark = pytest.mark.unit

from orchestrator.services.observability import (  # noqa: E402
    is_open_question,
    named_quantity,
)


# ── a scope is not a quantity ───────────────────────────────────────────────


@pytest.mark.parametrize(
    "q",
    [
        "What can you measure in this building?",
        "What can you monitor across the site?",
        "What do you track throughout the building?",
        "What can you detect around here?",
        "What can you measure here?",
    ],
)
def test_a_preposition_after_the_verb_names_no_quantity(q):
    """ "in this building" as a quantity produced a confident negative about nothing."""
    assert named_quantity(q) == "", (
        f"{q!r} yields a quantity of {named_quantity(q)!r}, which the lane will then "
        f"report as not measured"
    )


@pytest.mark.parametrize(
    "q, expected",
    [
        ("Can you measure noise in this building?", "noise"),
        ("Can you measure formaldehyde?", "formaldehyde"),
        ("Can you measure radon in room 5.01?", "radon"),
        ("Do you track humidity here?", "humidity"),
        ("Do you monitor carbon monoxide in the plant room?", "carbon monoxide"),
    ],
)
def test_a_real_quantity_is_still_named(q, expected):
    """The exclusion must not cost the verdicts this function exists for."""
    assert named_quantity(q) == expected


@pytest.mark.parametrize(
    "q",
    [
        "What can you measure in this building?",
        "What is measured in this building?",
        "What is monitored across the whole building?",
        "What can you measure?",
    ],
)
def test_a_building_scoped_question_wants_the_menu(q):
    assert is_open_question(q) is True


# ── the lane answers it instead of asking ───────────────────────────────────


def _lane_source() -> str:
    from orchestrator.workflow import _orchestrator

    for name in dir(_orchestrator.WorkflowOrchestrator):
        if "observability" in name and name.startswith("_") and "node" in name:
            return inspect.getsource(getattr(_orchestrator.WorkflowOrchestrator, name))
    raise AssertionError("observability node not found")


def test_an_open_question_with_no_space_is_answered_not_clarified():
    src = _lane_source()
    open_branch = src.index("is_open_question(question)")
    clarify = src.index("Which space did you mean?")
    assert open_branch < clarify, (
        "the clarify branch still fires first, so a question about the whole building is "
        "answered by asking which space it meant"
    )


def test_a_specific_question_with_no_space_still_clarifies():
    """Narrow on purpose: there the answer really does vary room by room."""
    src = _lane_source()
    assert "Which space did you mean?" in src, (
        "the clarify was removed entirely; a specific question about an unnamed room now "
        "gets a building-wide answer that is not about the room asked for"
    )


def test_the_building_menu_lists_what_the_building_declares():
    src = _lane_source()
    assert "load_modalities(settings.BUILDING_ID)" in src


def test_the_building_is_named_from_context_not_a_literal():
    src = _lane_source()
    assert "resolve_building_context" in src, (
        "the building's name is not resolved, so the answer either names a literal or "
        "shows an id"
    )
    for literal in ("abacws", "bldg1", "bldg2"):
        assert literal not in src.lower().replace("building_id", "")


def test_an_empty_building_says_so_rather_than_listing_nothing():
    src = _lane_source()
    assert "Nothing is currently readable in this building" in src
