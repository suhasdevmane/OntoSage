# -*- coding: utf-8 -*-
"""Offering the reader the floor they just named (V10 W2-6, regression probe 2026-09-07).

WHAT WENT WRONG
---------------
    Q: "Which space on Floor 3 has the best conditions for focused work this afternoon?"
    A: "Which floor did you mean? I know: Floor0, Floor1, Floor2, Floor3, Floor4, Floor5"

The question names its floor. The deliberate lane had ranked this exact question correctly
in an earlier session (BUG-435's verification). It regressed to a clarify loop, and the
option list it offered contained the floor the reader had already given.

WHY IT MOVED WITHOUT ANY CODE CHANGING
--------------------------------------
`_norm_floor` matched `Floor 3`, `3` and `floor3` -- and nothing else. The anchor it is
given comes from an LLM CQ-IR compile, so the SPELLING varies between runs of the same
question: `Level 3`, `3rd floor`, `third floor` all fail. That is the BUG-184 finding in a
new place -- the provider returns different text at temperature 0 and the parser absorbs
most but not all of it.

**An unstable input is not a reason to ask the user. It is a reason to normalise harder.**

Both sides are now reduced to a STOREY NUMBER and compared, so nothing here assumes what
this building calls a floor -- only how the same floor might be written.

AND THE LOG COULD NOT HAVE TOLD ANYONE
--------------------------------------
It said `asking ONE question (slot=floor); plan parked` and dropped the `reason`, which
carries the value that failed to resolve. The slot alone cannot distinguish "the reader
gave no floor" from "the compiler wrote a spelling we do not accept" -- the same "a guard
that reports only 'blocked' cannot be tuned" lesson, one lane over.
"""

from __future__ import annotations

import inspect

import pytest

pytestmark = pytest.mark.unit

from orchestrator.services.deliberation.capability_schema import _norm_floor  # noqa: E402

FLOORS = ["Floor0", "Floor1", "Floor2", "Floor3", "Floor4", "Floor5"]


@pytest.mark.parametrize(
    "anchor",
    [
        # What it always accepted.
        "Floor 3",
        "3",
        "floor3",
        "Floor3",
        "floor 3",
        # What an LLM compile also produces, and what it used to reject.
        "third",
        "third floor",
        "3rd",
        "3rd floor",
        "Level 3",
        "level 3",
        "L3",
        "FL-3",
        "storey 3",
    ],
)
def test_every_spelling_of_a_storey_resolves(anchor):
    assert _norm_floor(anchor, FLOORS) == "Floor3", (
        f"{anchor!r} does not resolve, so a question naming this floor is answered with "
        f"'which floor did you mean?' offering that same floor"
    )


@pytest.mark.parametrize("anchor", ["ground", "ground floor", "0", "zeroth"])
def test_the_ground_floor_resolves_by_name_or_number(anchor):
    assert _norm_floor(anchor, FLOORS) == "Floor0"


@pytest.mark.parametrize(
    "anchor", ["the roof", "somewhere", "", "the basement", "Floor 9", "12th"]
)
def test_a_floor_this_building_does_not_have_still_returns_none(anchor):
    """Normalising harder must not start inventing matches.

    Asking which floor is CORRECT when the building has no such floor -- that is the case
    the clarify question exists for, and widening the matcher must not swallow it.
    """
    assert _norm_floor(anchor, FLOORS) is None


def test_nothing_assumes_what_a_floor_is_called():
    """Both sides reduce to a storey number, so a building naming floors its own way works."""
    exotic = ["Niveau-0", "Niveau-1", "Niveau-2", "Niveau-3"]
    assert _norm_floor("3", exotic) == "Niveau-3"
    assert _norm_floor("third", exotic) == "Niveau-3"
    assert _norm_floor("Niveau-3", exotic) == "Niveau-3"


def test_the_clarify_log_carries_the_value_that_failed():
    """`slot=floor` cannot distinguish "no floor given" from "a spelling we reject"."""
    from orchestrator.workflow import _orchestrator

    src = inspect.getsource(_orchestrator)
    assert "asking ONE question (slot=" in src
    assert "getattr(decision, 'reason'" in src, (
        "the clarify log dropped the reason again; the anchor that failed to resolve is "
        "the only thing that makes a clarify loop diagnosable"
    )

# ── what the log actually said, once it carried the reason ──────────────────
#
#     [deliberate] asking ONE question (slot=floor); plan parked - unknown floor 'None'
#
# The anchor was the literal string "None". The CQ-IR compile had recognised that the
# question named a floor -- it emitted an ON_FLOOR qualifier -- and then failed to say
# WHICH, and the gate turned that into "which floor did you mean?" offering the reader
# Floor3 among the options for a question that says "Floor 3".
#
# Normalising spellings, above, was a real robustness gain and NOT the fix for this: no
# amount of normalising resolves "None". The compiler is one source; the question is the
# authoritative one.


@pytest.mark.parametrize(
    "question, expected",
    [
        ("Which space on Floor 3 has the best conditions for focused work?", "Floor3"),
        ("best space on level 3 this afternoon", "Floor3"),
        ("quietest room on the 3rd floor", "Floor3"),
        ("which space on floor 0 is warmest", "Floor0"),
        # No floor named: nothing to recover, and inventing one would be worse than asking.
        ("Which space has the best conditions for focused work this afternoon?", None),
        # A ROOM number is not a floor reference. `3.10` must not read as floor 3, or the
        # gate would silently scope a room question to a whole floor.
        ("what is the CO2 in room 3.10", None),
        # A floor this building does not have still asks -- which is what the question is for.
        ("show me the 9th floor", None),
    ],
)
def test_the_floor_is_recovered_from_the_question_when_the_compiler_leaves_it_blank(
    question, expected
):
    from orchestrator.services.deliberation.capability_schema import floor_from_text

    assert floor_from_text(question, FLOORS) == expected


def test_recovery_only_runs_when_the_anchor_is_nullish():
    """A WRONG anchor must still clarify.

    If the compiler confidently says "Floor 9" for a six-storey building, asking is
    correct. Recovery is for the case where it said nothing at all -- otherwise the raw
    text would silently override a compile that disagreed with it, and the disagreement
    is worth surfacing.
    """
    import inspect

    from orchestrator.services.deliberation import capability_schema as cs

    src = inspect.getsource(cs.validate)
    assert "_NULLISH" in src, (
        "the text recovery no longer checks that the anchor was blank, so it would "
        "override a compiled anchor that merely disagrees with the question"
    )
    assert "floor_from_text(cqir.raw_query" in src


@pytest.mark.parametrize("blank", ["None", "null", "", "  ", "n/a", "unspecified", "any"])
def test_every_way_a_model_writes_nothing_counts_as_blank(blank):
    from orchestrator.services.deliberation.capability_schema import _NULLISH

    assert blank.strip().lower() in _NULLISH
