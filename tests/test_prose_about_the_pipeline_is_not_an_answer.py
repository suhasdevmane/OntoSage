# -*- coding: utf-8 -*-
"""Developer-facing narration must not reach a user (BUG-443).

WHAT WENT WRONG
---------------
Measured live 2026-09-06, cache flushed, "Which rooms are stuffy right now?":

    "I don't have the live CO2 or temperature readings that would let me tell you which
     rooms are currently 'stuffy.' What I can share is a quick snapshot of how many
     sensors are installed in each space...
       Floor 0 - 11 sensors, Floor 1 - 8 sensors, ...
     If you'd like to pull the current CO2 or temperature data for any of these spaces,
     just let me know."

The building has 589 air-quality sensors and a populated `co2_data` table. HBCO maps
"stuffy" to CO2 correctly. The generated SPARQL returned COUNTS per space rather than
readings, and the model narrated the shortfall -- offering, at the end, to do the very
thing it had just been asked to do.

THE DISTINCTION THIS FILE EXISTS TO PROTECT
-------------------------------------------
An HONEST DECLINE is a statement about the BUILDING: *"I don't have a floor plan for
Floor 7. Available floors: 0-5"*, *"this building has no lifts recorded in its model"*.
It is produced deterministically by a lane that looked and found nothing, it says what
would change the answer, and it is one of this system's best behaviours.

A META-ANSWER is a statement about the PIPELINE: what the model was handed, what it would
need, what the reader should go and do. The reader cannot act on it and cannot tell whether
the building has the data.

A bare "I don't have X" CANNOT be the marker -- this system says it legitimately in at
least three places. What made the stuffy-rooms answer a meta-answer was the second move:
having said it lacked the readings, it offered a substitute it had just labelled as not the
thing asked for, and handed the task back. That pivot is the marker.
"""

from __future__ import annotations

import inspect

import pytest

pytestmark = pytest.mark.unit

from orchestrator.services.grounding_guard import (  # noqa: E402
    is_meta_answer,
    meta_answer_reason,
)

# ── caught ───────────────────────────────────────────────────────────────────

THE_LIVE_FAILURE = (
    "I don't have the live CO2 or temperature readings that would let me tell you which "
    "rooms are currently 'stuffy.'\n"
    "What I can share is a quick snapshot of how many sensors are installed in each "
    "space.\n\nFloor 0 - 11 sensors\nFloor 1 - 8 sensors\n\n"
    "If you'd like to pull the current CO2 or temperature data for any of these spaces, "
    "just let me know."
)


def test_the_answer_that_started_this_is_caught():
    assert is_meta_answer(THE_LIVE_FAILURE)


@pytest.mark.parametrize(
    "prose",
    [
        # The reviewer's own transcript of the same failure.
        "The data you've provided only tells us how many sensors are in each space. "
        "If you can run a query against the readings table I can help further.",
        "Based on the information provided, I cannot determine the current CO2 level.",
        "Please provide the readings and I will summarise them.",
        "I do not have access to the live telemetry for these rooms.",
        "The results you gave do not contain any actual readings.",
        "I couldn't find humidity. However, I can show you the temperature instead.",
    ],
)
def test_prose_about_the_exchange_is_caught(prose):
    assert is_meta_answer(prose), f"not caught: {prose!r}"


def test_the_reason_names_the_phrase_that_fired():
    """A guard that reports only "blocked" cannot be tuned, and an untunable guard gets
    switched off the first time it is wrong."""
    reason = meta_answer_reason(THE_LIVE_FAILURE)
    assert reason and reason.lower().startswith("what i can share")


# ── NOT caught: the system's own honest declines ─────────────────────────────


@pytest.mark.parametrize(
    "prose",
    [
        # Real strings from floor_plan_agent and capability_agent.
        "I don't have floor plans loaded yet for the Abacws Building. Please check that "
        "PDF files are placed in the `/app/input/` folder.",
        "I don't have a floor plan for Floor 7 of the Abacws Building. "
        "Available floors: 0, 1, 2, 3, 4, 5.",
        "I don't have that specific information on record for **Abacws Building**. For "
        "building-specific queries please contact your building's facilities team. "
        "You can add it - no code changes needed.",
        # Deterministic lane declines.
        "This building has no lifts recorded in its model, so I can't tell you its state.",
        "No room called 3.99 exists in this building.",
        # Ordinary answers.
        "**Room 5.01 CO2 is 812 ppm**, measured 4 minutes ago by CO2 Level Sensor 5.01.",
        "Floor 1's average CO2 (612 ppm) is higher than Floor 3's (540 ppm).",
        "Room 2.01, Room 2.03 and Room 2.05 are on floor 2. Let me know if you want the "
        "sensors in each.",
        # The fallback the guard itself routes to. Catching this would loop.
        "I understood the question but could not put an answer together for it. "
        "Sparql ran, but returned nothing to report.",
    ],
)
def test_an_honest_decline_or_a_real_answer_survives(prose):
    assert not is_meta_answer(prose), (
        f"FALSE POSITIVE -- this is a true statement about the building and the guard "
        f"suppressed it: {meta_answer_reason(prose)!r} in {prose[:70]!r}"
    )


def test_empty_and_whitespace_are_not_meta_answers():
    assert not is_meta_answer("")
    assert not is_meta_answer("   \n  ")


# ── wired ────────────────────────────────────────────────────────────────────


def test_the_response_node_runs_the_guard():
    """Built, correct, no invoker -- the failure this codebase repeats.

    Every test above would pass with the guard called from nowhere.
    """
    from orchestrator.workflow import _orchestrator

    src = inspect.getsource(_orchestrator)
    assert "meta_answer_reason(final_response)" in src, (
        "the meta-answer guard is defined and never applied to the final response"
    )
    assert "final_response = _unanswered_response(state, ctx)" in src


def test_the_guard_runs_after_the_whole_dispatch_not_inside_one_lane():
    """Any lane's prose can drift this way; a guard inside one lane protects one lane."""
    from orchestrator.workflow import _orchestrator

    src = inspect.getsource(_orchestrator)
    guard = src.index("meta_answer_reason(final_response)")
    # Every lane's assignment to final_response happens before the guard.
    last_assignment = src.rindex("final_response = sparql_result[")
    assert last_assignment < guard, (
        "the guard now runs before some lane can set the final response, so that lane's "
        "narration would reach the user unchecked"
    )

# ── what the LIVE probe found the guard missing (2026-09-07) ─────────────────
#
# The guard shipped, the offline tests passed, and the first live re-ask returned the
# exact prose it exists to suppress. Two gaps, and the second is a class:
#
#   1. "What I can give you is ..." -- the pivot list held share/tell you/offer. Three
#      synonyms is not a vocabulary.
#
#   2. "If you'd like to check ... just let me know" never matched, because the model
#      wrote a RIGHT SINGLE QUOTATION MARK and the pattern expects an apostrophe. Every
#      pattern matching a contraction or a dash in MODEL OUTPUT had the same hole.
#
# Both are fixtures now, taken verbatim from the live answer.

THE_LIVE_MISS = (
    "I don’t have the current CO₂ readings, so I can’t tell you which rooms "
    "are actually “stuffy” at the moment. "
    "What I can give you is a quick snapshot of the rooms that are equipped with "
    "sensors (so you know where you can pull real-time data from): "
    "Room 0.01 - 8 sensors. Room 0.04 - 8 sensors. "
    "If you’d like to check the current CO₂ levels (or any other metric) for a "
    "specific room, just let me know which one and I can pull the latest sensor data."
)


def test_the_answer_the_guard_shipped_and_still_missed_is_caught():
    reason = meta_answer_reason(THE_LIVE_MISS)
    assert reason, "the guard still lets its own motivating example through"


def test_a_curly_apostrophe_does_not_defeat_a_pattern():
    """The class, not the instance.

    A model writes curly quotes and typographic dashes wherever prose calls for them, so a
    pattern written in ASCII silently stops matching. Normalising once covers every
    pattern rather than adding an alternative to each.
    """
    from orchestrator.services.grounding_guard import normalise_typography

    curly = "If you’d like me to check the data, just let me know."
    straight = "If you'd like me to check the data, just let me know."
    assert normalise_typography(curly) == straight
    assert bool(meta_answer_reason(curly)) == bool(meta_answer_reason(straight))


@pytest.mark.parametrize(
    "verb",
    ["share", "tell you", "offer", "give you", "provide", "show you"],
)
def test_every_hand_over_verb_is_a_pivot(verb):
    prose = f"I cannot answer that. What I can {verb} is a list of sensor counts instead."
    assert is_meta_answer(prose), f"'what I can {verb} is' is not recognised as a pivot"


def test_normalising_does_not_break_the_honest_declines():
    """The exemptions must survive the same normalisation."""
    for honest in (
        "This building has no lifts recorded in its model.",
        "I don’t have a floor plan for Floor 7. Available floors: 0, 1, 2, 3, 4, 5.",
        "I don’t have that specific information on record. You can add it - no code changes needed.",
    ):
        assert not is_meta_answer(honest), f"false positive after normalisation: {honest[:60]}"
