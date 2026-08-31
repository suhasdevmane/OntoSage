# -*- coding: utf-8 -*-
"""A quoted passage is not a computed answer (BUG-370).

The replay grader tested the SHAPE of a response — does it contain digits, does it
mention a room — and never whether it responded to the question. So the document lane
handing back a passage scored identically to a calculation over live sensor data.

Measured on a 111-question stakeholder probe: 56 responses graded `answered-with-data`,
of which only 18 computed anything. "Which valves have accumulated questionable
behaviour" returned the helpdesk phone number; "which cleaning defects keep recurring"
returned the cleaning schedule. The reported 55.4% coverage was really 17.8%.

A quote is not a failure — for a genuinely prose question, a passage with its source is
the right answer. It is a THIRD outcome, reported beside the other two and never summed
with computed answers.
"""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))

from corpus_replay import (  # noqa: E402
    COMPUTED_GRADES,
    PASS_GRADES,
    VALID_GRADES,
    _heuristic_grade,
)

pytestmark = pytest.mark.unit


def test_a_pasted_document_is_not_a_computed_answer():
    answer = (
        "Here is what I found in **Abacws Building** documentation:\n\n"
        "**From: Asbestos Register**\n\n"
        "| location | material | condition |\n|---|---|---|\n"
        "| Level 2 riser | AIB panel | Good, 2024-09-14 |"
    )
    assert _heuristic_grade("Which plant can be replaced?", answer) == "document-quoted"


def test_a_paste_full_of_digits_is_still_a_quote():
    """The digit test is exactly what mis-scored these, so a table must not defeat it."""
    answer = (
        "Here is what I found for **Abacws Building**:  **Service Schedules**. "
        "Office cleaning daily, last completed 2026-08-28, next due 2026-08-30; "
        "carpet deep clean 6 monthly, 12 areas, 450 m2."
    )
    assert _heuristic_grade("Which defects recur?", answer) == "document-quoted"


def test_a_computed_answer_is_still_a_computed_answer():
    answer = "The average temperature in room 5.04 was 22.5 °C over the last hour, from 3 sensors."
    assert _heuristic_grade("Temperature in 5.04?", answer) == "answered-with-data"


def test_citing_a_document_later_does_not_make_an_answer_a_quote():
    """Only a response that OPENS as a paste is a quote.

    A computed answer should cite its sources, and penalising it for doing so would
    push the system away from the provenance the whole project is built on.
    """
    answer = (
        "3 permits are open in the basement. Source: the Permit to Work Register, "
        "version 4.1, effective 2026-01-01."
    )
    assert _heuristic_grade("How many permits are open?", answer) == "answered-with-data"


def test_the_two_are_never_summed_into_coverage():
    """COMPUTED_GRADES is the coverage figure; PASS_GRADES is not."""
    assert "document-quoted" in PASS_GRADES, "a sourced quote is a truthful response"
    assert "document-quoted" not in COMPUTED_GRADES, "but it computed nothing"
    assert COMPUTED_GRADES < PASS_GRADES


def test_document_quoted_is_a_declared_grade():
    assert "document-quoted" in VALID_GRADES
