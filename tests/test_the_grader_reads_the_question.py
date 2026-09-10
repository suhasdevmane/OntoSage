# -*- coding: utf-8 -*-
"""A number is not an answer to every question (V10 W4-3).

WHAT WENT WRONG
---------------
`corpus_replay._heuristic_grade` said so itself:

    "the question is currently unused by the heuristic but kept for parity with the LLM
     judge"

Every test in it examines the shape of the RESPONSE -- does it contain digits, does it
mention a room -- so an answer containing a number was credited `answered-with-data`
whatever the number was ABOUT. "When was the fume cupboard last tested?" answered with a
table of sensor counts scored the same as a date.

MEASURED BEFORE FIXING, AND AGAIN AFTER
---------------------------------------
Against the 2,960-row capture already on disk -- no re-capture, no model, the answers were
recorded on 2026-09-03 and are unchanged; only the verdict over them moves:

    answered-with-data   1311 -> 1297   (-14, 0.5% of the corpus)
    deflected             257 ->  271   (+14)

The withdrawn rows are answers like *"That question reaches 288 sensors -- more than I can
read and summarise in one request"* and *"I can't complete that request as asked"*, both
previously credited as answered-with-data.

THE FIRST VERSION WITHDREW TWICE AS MUCH, AND HALF OF IT WRONGLY
----------------------------------------------------------------
It matched a bare `when` and a bare `who`. In this corpus most of both are not question
words:

    "...are overdue WHEN approved regimes and actual runtime diverge"     (conjunction)
    "is heat recovery effective WHEN conditions permit"                   (conjunction)
    "a staff member WHO is officially available to visitors"              (relative)
    "conditions constrain WHO may work on this asset"                     (relative)

53 rows matched; 28 changed grade. Demoting those would have withdrawn credit from answers
that were correct -- a grader that under-credits is exactly as wrong as one that
over-credits, and harder to notice because the number moves the flattering way.
"""

from __future__ import annotations

import importlib.util
import sys
from pathlib import Path

import pytest

pytestmark = pytest.mark.unit

REPO = Path(__file__).resolve().parent.parent


def _replay():
    spec = importlib.util.spec_from_file_location(
        "_cr_test", REPO / "scripts" / "corpus_replay.py"
    )
    mod = importlib.util.module_from_spec(spec)
    sys.modules["_cr_test"] = mod
    spec.loader.exec_module(mod)
    return mod


# ── the shape check itself ───────────────────────────────────────────────────


@pytest.mark.parametrize(
    "question, answer, expected",
    [
        # Asked for a date, given none.
        ("When was the fume cupboard last tested?", "There are 14 sensors in that room.", "date"),
        # Asked for a date, given one.
        ("When was the fume cupboard last tested?", "It was tested on 2026-03-14.", None),
        ("When did it begin?", "About 3 days ago.", None),
        # An honest "no date" is an answer to a date question, not an omission.
        ("When was it last serviced?", "There is no record of a service date.", None),
        # Asked for a role, given none.
        ("Who owns this job on site?", "There are 4 open work orders.", "role"),
        # Asked for a role, given one.
        ("Who owns this job on site?", "The Estates helpdesk, ext 1234.", None),
        ("Who is accountable?", "The Accessibility and Inclusion Team.", None),
    ],
)
def test_the_shape_check_asks_for_the_kind_of_thing_wanted(question, answer, expected):
    cr = _replay()
    assert cr._answer_omits_what_was_asked(question, answer) == expected


# ── the false positives that cost twice as much as the defect ────────────────


@pytest.mark.parametrize(
    "question",
    [
        # `when` as a SUBORDINATING CONJUNCTION -- verbatim from the capture.
        "Which M&E assets are due or overdue for maintenance when approved regimes and "
        "actual runtime diverge?",
        "Is heat recovery available and effective when conditions permit?",
        "For a sustainability project, when students are allowed to open windows, what "
        "usually happens to the temperature?",
        "Which automated checks must stop the pipeline when data or mappings violate a rule?",
        # Leading position is NOT the discriminator: this begins with the word and asks
        # about capacity.
        "When a lift, powered door or principal route is unavailable, how much usable "
        "capacity is actually left?",
        # `who` as a RELATIVE pronoun.
        "Where can I speak to a staff member who is officially available to visitors?",
        "Do warranty conditions constrain who may work on this asset?",
    ],
)
def test_a_conjunction_or_a_relative_pronoun_is_not_a_question_word(question):
    """Every one of these is answerable without a date or a role."""
    cr = _replay()
    assert cr._answer_omits_what_was_asked(question, "There are 12 such assets.") is None, (
        "credit would be withdrawn from an answer that is correct"
    )


@pytest.mark.parametrize(
    "question",
    [
        "When should I leave to arrive on time?",
        "When can I collect room-level environmental data?",
        "When is daylight likely to be sufficient for desk work?",
        "During our three-hour class, when are CO2 levels most likely to worsen?",
        "Is drift changing the signal, when did it begin?",
        "Who owns this job on site, who is the technical contact?",
        "Which building services are mission-critical, and who owns each dependency?",
        "For each obligation, who is accountable?",
    ],
)
def test_a_genuine_question_word_is_still_recognised(question):
    """Tightening must not silence the check -- 34 rows still match after it."""
    cr = _replay()
    assert cr._answer_omits_what_was_asked(question, "There are 12 such assets.") is not None


# ── the grade it produces ────────────────────────────────────────────────────


def test_a_credit_becomes_a_deflection_not_a_failure():
    """`deflected` is the honest verdict: the response is not FALSE, it does not answer.

    Grading it `wrong` would say the system stated something untrue, which it did not.
    """
    cr = _replay()
    g = cr._heuristic_grade(
        "When was the fume cupboard last tested?",
        "That question reaches 288 sensors - more than I can read and summarise in one "
        "request without either timing out or dropping most of them.",
    )
    assert g == "deflected"


def test_an_answer_that_matches_its_question_is_still_credited():
    cr = _replay()
    g = cr._heuristic_grade(
        "When was the fume cupboard last tested?",
        "The Level 3 fume cupboard FC-301 was last tested on 2026-03-14 by the LEV "
        "contractor, and is due again in March 2027.",
    )
    assert g == "answered-with-data"


def test_the_docstring_no_longer_claims_the_question_is_unused():
    cr = _replay()
    doc = cr._heuristic_grade.__doc__ or ""
    assert "currently unused" not in doc, (
        "the docstring still says the question is unused; it was the only thing that "
        "documented the defect and it must not outlive it"
    )
    assert "THE QUESTION IS READ" in doc


def test_the_check_runs_where_a_credit_is_given():
    """Built, correct, no invoker -- every test above would pass with it called nowhere."""
    import inspect

    cr = _replay()
    src = inspect.getsource(cr._heuristic_grade)
    assert "_answer_omits_what_was_asked(question, answer)" in src
    assert src.index("_answer_omits_what_was_asked") < src.index('return "answered-with-data"')
