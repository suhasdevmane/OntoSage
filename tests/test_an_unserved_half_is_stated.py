# -*- coding: utf-8 -*-
"""A request's unserved half is named, not silently dropped (V12-06, T07, case B14).

    B14 — "Ask a supported observations-plus-procedure question. Both subclaims have their
           own sources, or the unsupported part is stated."

THE GAP
-------
`_promote_to_capability_from_documents` returns immediately unless the intent is weak, so

    "Which rooms were stuffy yesterday, and what does the manual say to do about it?"

classifies as data, gets the observations, and the procedure half is never attempted and
never mentioned. The reader cannot distinguish "the manual says nothing" from "nobody
looked" — and those are different facts, which is the same principle as the four kinds of
nothing one row earlier.

WHAT THESE TESTS GUARD HARDEST
------------------------------
Not that the note appears. That it appears RARELY. A rule firing on ordinary questions
would append a caveat to most answers, and a caveat on most answers is read as boilerplate
and then not read at all — which is how the dossier's "simulated" column failed (BUG-515).
So the negative cases outnumber the positive ones here too.
"""

from __future__ import annotations

import pytest

pytestmark = pytest.mark.unit

from orchestrator.services.unserved_half import (  # noqa: E402
    GUIDANCE,
    OBSERVATIONS,
    detect,
    unserved_note,
)

COMPOUND = "Which rooms were stuffy yesterday, and what does the manual say to do about it?"


# ── it fires on the case the review names ────────────────────────────────────


def test_the_reviews_own_example_is_detected():
    comp = detect(COMPOUND)
    assert comp is not None
    assert comp.parts == (OBSERVATIONS, GUIDANCE)


def test_a_data_lane_answering_it_says_the_other_half_was_not_attempted():
    note = unserved_note(COMPOUND, "analytics")
    assert note and "only the first half" in note


def test_the_note_does_not_claim_the_documents_are_silent():
    """"I did not look" and "there is nothing" are different facts. Claiming the second
    from the first is the same error as narrating an empty fetch as sensor absence."""
    note = unserved_note(COMPOUND, "analytics")
    assert "I did not look" in note
    assert "not telling you they are silent" in note


def test_the_note_quotes_the_part_it_did_not_serve():
    """A reader should not have to work out which half was dropped."""
    note = unserved_note(COMPOUND, "sensor_data")
    assert "what does the manual say" in note.lower()


def test_it_works_in_the_other_direction_too():
    note = unserved_note(COMPOUND, "capability")
    assert note and "documented half" in note


# ── and stays quiet everywhere else, which matters more ──────────────────────


@pytest.mark.parametrize(
    "q",
    [
        "Which rooms were stuffy yesterday?",
        "What does the manual say about fire drills?",
        "What is the CO2 in room 5.01 right now?",
        "Show me floor 3",
        "What should I do about the temperature in room 5.01?",
        "How many CO2 sensors are there?",
        "Who do I contact about a broken door closer, and how quickly should they respond?",
    ],
)
def test_a_single_purpose_question_is_never_annotated(q):
    """The last one is the trap: it HAS a connector and asks who to contact, but both
    halves are answered from the same register — annotating it would be noise.

    Asserted on `detect` directly rather than through `unserved_note`. The first version
    of this test was a chain of `or`s that would have passed whenever ANY branch was None,
    which is most of the time — a negative test that cannot fail is worse than none,
    and this file's whole point is that the rule stays quiet.
    """
    assert detect(q) is None, f"fired on a single-purpose question: {q!r}"
    for intent in ("analytics", "sensor_data", "capability", "register"):
        assert unserved_note(q, intent) is None, f"{q!r} annotated under intent {intent!r}"


def test_a_guidance_question_with_an_action_word_is_one_request_not_two():
    """"What should I do about the temperature" reads as guidance ABOUT a reading. It is
    one request, and splitting it would invent a half nobody asked for."""
    assert detect("What should I do about the temperature in room 5.01?") is None


def test_two_observation_halves_are_not_a_composition():
    """Both halves are servable by the same lane, so nothing went unserved."""
    q = "What is the CO2 in room 5.01, and what is the temperature on floor 3?"
    assert unserved_note(q, "sensor_data") is None


def test_an_unknown_intent_stays_quiet():
    """Guessing what an unrecognised lane served would produce a confident wrong caveat."""
    assert unserved_note(COMPOUND, "some_new_lane") is None
    assert unserved_note(COMPOUND, None) is None
    assert unserved_note(COMPOUND, "") is None


def test_empty_input_is_survivable():
    for q in ("", "   ", None):
        assert detect(q) is None
        assert unserved_note(q, "analytics") is None


# ── the step nobody remembers ────────────────────────────────────────────────


def test_it_is_called_on_the_response_path():
    """A module nothing calls is the V6-T10 failure, and this one is only useful at the
    moment an answer is assembled."""
    from pathlib import Path

    src = (
        Path(__file__).resolve().parent.parent
        / "orchestrator" / "workflow" / "_orchestrator.py"
    ).read_text(encoding="utf-8")
    assert "unserved_half" in src, "the unserved-half rule is never consulted"
    assert "unserved_note" in src

    call_at = src.index("unserved_note")
    append_at = src.index('role="assistant"')
    assert call_at < append_at, "the note must be added before the answer is transcribed"
