# -*- coding: utf-8 -*-
"""BUG-897 — a declared design limit is composed into the answer, never left to a hint.

Measured live 2026-09-29, both of these, and both are the class of answer this system exists
to prevent:

    "What is the maximum occupancy of room 2.15?"
    -> "**30.00 people** ... the highest value observed for that location."
       The graph declares `maxOccupancy 40`. A maximum OBSERVATION, in bold, as a design limit.

    "What is the design occupancy of room 5.01?"
    -> "The design occupancy value itself is not recorded in the data."
       The graph declares it TWICE — 25 under maxOccupancy, 20 under hbco:roomCapacity.

The declared figure was ALREADY being computed for the first: the log shows
`[analytics_node] design occupancy for 'Room 2.15 — Seminar Room'` with maxOccupancy on the
bus. It was offered to the narrator as a RECIPE HINT, and the narrator answered from the sensor
anyway. That is BUG-937's lesson in a more dangerous place — a figure a narrator can get wrong
is a figure it should not be deriving, and a capacity a fire or booking decision rests on is
not one to leave to wording.

WHY IN `_response_node`. The hook that builds the hint lives inside `_analytics_node`, so
"design occupancy of room 5.01" — which routed `sensor_data -> sparql` — never reached it at
all, which is where the false denial came from. `_response_node` is the one place every lane
passes through.

THREE THINGS THIS FILE PINS, because each was got wrong first:
  * the gate is NARROWER than `is_design_occupancy_question`, which is true of a live count;
  * a decline is REPLACED, not prepended to, or the answer states the figure and then denies it;
  * the skip is idempotent on the SENTENCE, not on a bare number — room 5.01 declares 20 and 25
    and the sensor text contained "at 25 Sep 01:22", a DATE, which the first version read as
    the capacity having been stated.
"""

from __future__ import annotations

import inspect
import re

import pytest

from orchestrator.services.design_occupancy import (
    DESIGN_OCCUPANCY_TERMS,
    is_design_occupancy_question,
)
from orchestrator.workflow._orchestrator import WorkflowOrchestrator

pytestmark = pytest.mark.unit


def _src() -> str:
    return inspect.getsource(WorkflowOrchestrator._response_node)


def _fires(question: str) -> bool:
    """The gate as the response node computes it."""
    squashed = re.sub(r"[^a-z0-9]+", "", question.lower())
    return any(t in squashed for t in DESIGN_OCCUPANCY_TERMS) and is_design_occupancy_question(
        question
    )


# ── the gate: a declared limit, not a live count ──────────────────────────────────────


@pytest.mark.parametrize(
    "question",
    [
        "What is the maximum occupancy of room 2.15?",
        "What is the design occupancy of room 5.01?",
        "What is the seating capacity of room 1.04?",
        "What's the capacity of room 3.10?",
        "How does observed occupancy compare with the design occupancy of room 1.25?",
    ],
)
def test_a_question_naming_the_declared_property_is_claimed(question):
    assert _fires(question) is True, question


@pytest.mark.parametrize(
    "question",
    [
        # THE CASE THAT FORCED THE NARROWING. `is_design_occupancy_question` is True here —
        # correctly, it exists to inject a COMPARISON hint — and leading a live count with a
        # capacity would put the wrong figure first.
        "How many people are in room 2.15 right now?",
        "Is room 2.15 busy?",
        "Which floor has the most people?",
        "What is the temperature in room 2.15?",
    ],
)
def test_a_live_count_is_not_led_by_a_capacity(question):
    assert _fires(question) is False, question


def test_the_broad_predicate_really_is_broader():
    """The premise of the narrowing. If this stops being true, the extra gate is dead weight."""
    assert is_design_occupancy_question("How many people are in room 2.15 right now?") is True


# ── how the statement is placed ───────────────────────────────────────────────────────


def test_it_lives_in_the_response_node_where_every_lane_passes():
    src = _src()
    assert "design_occupancy_for" in src
    assert "BUG-897" in src


def test_a_decline_is_replaced_rather_than_prepended_to():
    """Otherwise the answer states the capacity and then denies having answered — measured."""
    src = _src()
    assert "_was_decline" in src
    block = src[src.index("_was_decline") :]
    assert "_stmt if _was_decline" in block


def test_the_decline_leads_are_matched_as_literals_not_by_the_classifier():
    """`publication_gate.is_decline` returns False for the commonest decline this system emits
    (CAVEAT-952), so it cannot be used here. The two leads are literals in the source that
    emits them, which makes matching them a reference rather than a guess."""
    src = _src()
    assert "_decline_leads" in src
    assert "i couldn't answer that" in src
    assert "i could not find this in" in src


def test_the_skip_is_idempotent_on_the_sentence_not_on_a_bare_number():
    """A bare number matches dates, reading counts and timestamps. Room 5.01 declares 20 and 25
    and the sensor text held "at 25 Sep 01:22"."""
    src = _src()
    assert "_stmt.strip() not in final_response" in src


def test_it_never_costs_an_answer():
    src = _src()
    block = src[src.index("BUG-897") :]
    assert "except Exception" in block


def test_the_analytics_hook_caches_the_object_for_it():
    """So the response node reuses the computation instead of repeating the SPARQL round trip."""
    src = inspect.getsource(WorkflowOrchestrator)
    assert '"_design_occupancy_obj"' in src
