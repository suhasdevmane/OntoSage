# -*- coding: utf-8 -*-
"""BUG-941 — a question about the CONVERSATION must not be answered from the building.

THE TWO LIVE OBSERVATIONS THIS FILE IS BUILT FROM
--------------------------------------------------
One conversation, eight turns on ``/v1/chat/completions``, one chat id, unique filler so
nothing was served from ``resp_cache``. Turn 1: *"I am looking into air quality in room 5.01
specifically."* Turns 2-7: floor temperatures. Turn 8: *"Remind me which room I said I was
looking into, and why."*

**2026-09-29** — an honest decline about the wrong thing:

    the building's records do not record the room you were interested in or why you were
    looking into it

**2026-09-30**, after the four waves of that day — the same question, and now a
FABRICATION of the user's own words:

    You mentioned you were looking into **Room0.01**.

The user said room 5.01 and never said Room0.01. That is not a wrong reading; it is a false
claim about what the USER said, asserted in bold and decorated with sensor counts, in the
one place a fabrication is least visible — there is no live value for the reader to check it
against. The session summary naming room 5.01 was on the bus of that very turn (measured:
``session summary injected (516 chars, 7 turns)``), unread.

WHAT THESE TESTS PIN
--------------------
* the detector fires on the measured question and does NOT fire on questions about the
  building, measured over every question this project holds;
* the lane QUOTES and never interprets, so Room0.01 cannot be produced from a transcript
  that does not contain it;
* it recalls subjects and not values, and SAYS so;
* an empty record declines honestly instead of guessing.
"""

from __future__ import annotations

import csv
import re
from pathlib import Path

import pytest

from orchestrator.services.session_recall import (
    MAX_QUOTED,
    NOTES_KEY,
    VALUES_CAVEAT,
    answer,
    focus_terms,
    is_recall_question,
    session_recall_node,
)
from orchestrator.services.session_summary import TurnNote

REPO = Path(__file__).resolve().parents[1]

#: The probe's transcript, as the store would hold it after seven saved turns.
PROBE_NOTES = [
    TurnNote(
        1, "I am looking into air quality in room 5.01 specifically.", "sensor_data", "answered"
    ),
    TurnNote(2, "What is the temperature on floor 1?", "sensor_data", "answered"),
    TurnNote(3, "What is the temperature on floor 2?", "sensor_data", "answered"),
    TurnNote(4, "What is the temperature on floor 3?", "sensor_data", "answered"),
    TurnNote(5, "What is the temperature on floor 4?", "sensor_data", "answered"),
    TurnNote(6, "What is the temperature on floor 0?", "sensor_data", "answered"),
    TurnNote(7, "What is the temperature on floor 1?", "sensor_data", "answered"),
]

RECALL_Q = "Remind me which room I said I was looking into, and why."


# ── the detector ────────────────────────────────────────────────────────────────────────


def test_the_measured_question_is_recognised_as_being_about_the_conversation():
    assert is_recall_question(RECALL_Q)


@pytest.mark.parametrize(
    "query",
    [
        "What did I ask about earlier?",
        "What have we discussed so far?",
        "Which floor did I mention before?",
        "Remind me what I asked you about.",
        "Did I say which room I was interested in?",
        "Which rooms have we talked about?",
        "Can you recap what I have asked so far?",
        "What did we discuss about ventilation?",
        "Remind me which floor I said I liked working on last month.",
    ],
)
def test_questions_about_what_was_said_are_recognised(query):
    assert is_recall_question(query), query


@pytest.mark.parametrize(
    "query",
    [
        # Turn 1 of the probe itself. A pattern that took "looking into" as a speech act
        # would classify the DECLARATION as a question about itself.
        "I am looking into air quality in room 5.01 specifically.",
        # A relative clause on a thing the question is really about.
        "What is the CO2 in the room I mentioned earlier?",
        "Show me the temperature in the zone I asked about.",
        "How much energy did the building use in the week I mentioned?",
        "What was the average temperature in the room we discussed on Tuesday?",
        # Forward-looking, not retrospective.
        "Can I ask about the humidity on floor 3?",
        "May I ask what the CO2 level is?",
        "Let me ask about energy use last week.",
        "I want to ask about the lift.",
        # A statement, not a request to recall.
        "I told you about room 5.01.",
        # Plain data questions.
        "What is the temperature in room 5.01?",
        "Which rooms did the cleaners cover yesterday?",
        "How many sensors are there on floor 2?",
        "",
    ],
)
def test_questions_about_the_building_are_not_taken(query):
    assert not is_recall_question(query), query


def test_the_one_sentence_that_put_the_relative_clause_guard_here():
    """A real catalogue question, and the single false positive before the guard existed.

    ``docs/smart_building_questions.csv``. It is about a maintenance ticket, not about the
    conversation, and it contains "I raised".
    """
    assert not is_recall_question(
        "What happened to the ticket I raised about the draught last week?"
    )


def test_the_phrasing_the_guard_costs_is_recorded_rather_than_forgotten():
    """The trade is deliberate, and this test exists so it is not silently reversed.

    ``"What was the room I mentioned?"`` is grammatically the same sentence as the ticket
    question above — ``the <noun> I <speech verb>`` — so no determiner rule can keep one and
    drop the other. Over-capture is the worse direction: a working data question answered
    from the conversation is a new defect, while this is BUG-941's existing behaviour left
    in place for one wording.

    If a later change makes this fire, re-run ``measure_recall_detector`` over all 4,287
    questions before believing it is an improvement.
    """
    assert not is_recall_question("What was the room I mentioned?")


def test_the_detector_does_not_fire_on_the_catalogue():
    """Measured, not asserted: 4,060 stakeholder-catalogue questions, one hit.

    The one hit is *"Remind me which floor I said I liked working on last month."*, which is
    a recall question and is pinned as a TRUE positive above. Everything else in the
    catalogue is about the building and must stay there.
    """
    corpus = REPO / "docs" / "smart_building_questions.csv"
    if not corpus.exists():  # pragma: no cover - the file is tracked
        pytest.skip("catalogue corpus not present")
    questions = []
    with corpus.open(encoding="utf-8-sig", newline="") as fh:
        for row in csv.DictReader(fh):
            for key in ("question", "Question", "text", "Query"):
                if row.get(key):
                    questions.append(row[key].strip())
                    break
    assert len(questions) > 3000, "corpus looks truncated; the measurement would be hollow"
    fired = [q for q in questions if is_recall_question(q)]
    assert fired == ["Remind me which floor I said I liked working on last month."], fired


# ── what the lane says ──────────────────────────────────────────────────────────────────


def test_the_probe_question_recalls_the_room_the_user_actually_named():
    """The acceptance BUG-941 records: PASS is naming room 5.01."""
    out = answer(RECALL_Q, PROBE_NOTES)
    assert "5.01" in out
    assert "air quality" in out


def test_the_room_the_system_invented_cannot_appear():
    """Room0.01 is in no turn of this transcript, so no code path can emit it.

    This is the structural half of the fix: the lane quotes the user's words, so the only
    place names it can produce are place names the user typed. An extractor deciding which
    room was 'meant' would be a second place a referent can be invented (BUG-940).
    """
    out = answer(RECALL_Q, PROBE_NOTES)
    assert "Room0.01" not in out
    assert "0.01" not in out


def test_every_quoted_word_came_from_the_user():
    """No noun in the answer may be one this module chose.

    Everything that is not fixed prose from the module must be a substring of some turn the
    user typed. Checked on the identifiers, which are what a fabricated referent looks like.
    """
    out = answer(RECALL_Q, PROBE_NOTES)
    typed = " ".join(n.question for n in PROBE_NOTES).lower()
    found = re.findall(r"\b\d+\.\d+\b|\bfloor\s+\d\b|\broom\s+[\d.]+\b", out.lower())
    for token in found:
        assert token in typed, f"{token!r} is in the answer and in no turn the user typed"
    # An answer carrying NO identifier satisfies "every quoted word came from the user" while
    # quoting nothing, so the fabrication guard and a lane that had stopped recalling the room
    # render identically (lessons #20, CAVEAT-1115). RECALL_Q asks which room the user named
    # and the transcript names 5.01, so at least one identifier must be quoted back.
    assert found, (
        f"the recall answer quotes no identifier at all, so nothing was checked against the "
        f"transcript: {out[:200]!r}"
    )


def test_it_says_that_it_recalls_subjects_and_not_values():
    """W5-01 keeps figures out of the record by construction; the ANSWER must say so.

    Quietly omitting the values would leave the reader unable to tell a recall that has no
    measurement from one whose measurement happened to be absent (design contract #4).
    """
    assert VALUES_CAVEAT in answer(RECALL_Q, PROBE_NOTES)
    assert "asked" in VALUES_CAVEAT and "re-query" in VALUES_CAVEAT


def test_asking_why_gets_a_statement_that_no_reason_was_inferred():
    out = answer(RECALL_Q, PROBE_NOTES)
    assert "not inferred one" in out


def test_an_empty_record_declines_instead_of_guessing():
    out = answer(RECALL_Q, [])
    assert "Nothing has been asked in this conversation yet" in out
    assert "5.01" not in out


def test_a_subject_the_user_never_raised_is_named_back_as_absent():
    """The tracker's wording: *you have not mentioned a room in this conversation*."""
    floors_only = [n for n in PROBE_NOTES if "room" not in n.question.lower()]
    out = answer("Remind me which room I said I was looking into.", floors_only)
    assert "no record of you mentioning" in out
    assert '"room"' in out
    # and it still shows what they DID ask, because a decline is more useful with the
    # record attached.
    assert "floor 1" in out


def test_the_answer_is_bounded():
    many = [TurnNote(i, f"what about subject{i}?", "sensor_data", "answered") for i in range(1, 41)]
    out = answer("What have we discussed so far?", many)
    assert out.count("- Turn ") <= MAX_QUOTED
    assert "more matching turn(s) not shown" in out


def test_a_filtered_record_is_not_reported_as_a_truncated_one():
    """Two different facts, and the reader needs to be able to tell them apart.

    Six turns did not mention a room; none of them was CUT for length. Reporting that as
    *"…and 6 more turn(s) not shown"* tells the reader their record was truncated, and the
    next thing they do is ask for the rest of a list that is already complete.
    """
    out = answer(RECALL_Q, PROBE_NOTES)
    assert "more matching turn(s) not shown" not in out
    assert 'did not mention "room"' in out


def test_focus_terms_keep_the_users_subject_and_drop_the_recall_words():
    assert focus_terms(RECALL_Q) == ["room"]
    assert focus_terms("What have we discussed so far?") == []


# ── the lane, end to end ────────────────────────────────────────────────────────────────


class _State:
    def __init__(self, message, notes):
        self.user_message = message
        self.intermediate_results = {NOTES_KEY: notes} if notes is not None else {}
        self.current_intent = None


@pytest.mark.asyncio
async def test_the_node_writes_the_key_the_response_node_collects():
    """`agent-patterns.md` step 3: a lane that answers into a key nobody reads is invisible.

    ``dialogue_response`` is the branch ``_response_node`` already dispatches for standalone
    lanes with no other key. Pinned here so a future rename of this lane's output cannot
    quietly make it produce *"I processed your request, but couldn't generate a response."*
    """
    state = await session_recall_node(_State(RECALL_Q, PROBE_NOTES))
    assert "5.01" in state.intermediate_results["dialogue_response"]
    assert state.current_intent == "session_recall"


@pytest.mark.asyncio
async def test_the_node_still_answers_when_the_store_gave_nothing():
    """Postgres down, or a route that did not inject: an honest decline, never an exception."""
    state = await session_recall_node(_State(RECALL_Q, None))
    assert "Nothing has been asked" in state.intermediate_results["dialogue_response"]


def test_the_response_node_really_does_collect_that_key():
    """The premise of the test above, read from the source rather than believed."""
    body = (REPO / "orchestrator" / "workflow" / "_orchestrator.py").read_text(
        encoding="utf-8", errors="replace"
    )
    assert "elif dialogue_response:" in body
    assert "final_response = dialogue_response" in body


# ── building-agnostic ───────────────────────────────────────────────────────────────────


def test_the_module_names_no_building():
    """Design contract #3. The only nouns this lane can emit are the user's own."""
    src = (REPO / "orchestrator" / "services" / "session_recall.py").read_text(
        encoding="utf-8", errors="replace"
    )
    body = src.split('"""', 2)[-1]  # the module docstring quotes the live transcript
    for literal in ("bldg1", "bldg2", "abacws", "brick:", "Temperature_Sensor"):
        assert literal.lower() not in body.lower(), literal


# ── the intent is declared the way the graph expects ────────────────────────────────────


def test_the_intent_is_declared_as_a_lane_the_classifier_is_not_asked_to_pick():
    """Deterministic rule only: the whole defect is that this question LOOKS like data."""
    import yaml

    spec = yaml.safe_load(
        (REPO / "orchestrator" / "intents" / "intent_definitions.yaml").read_text(encoding="utf-8")
    )
    row = next(i for i in spec["intents"] if i["name"] == "session_recall")
    assert row["route_target"] == "session_recall"
    assert row["node_method"] == "_session_recall_node"
    assert row["cacheable"] is False
    assert "do not classify into this" in row["description"]
