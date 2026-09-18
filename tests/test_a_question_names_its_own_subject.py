# -*- coding: utf-8 -*-
"""A question must be answered about the subject the asker chose — or not at all.

Hand-read of 147 live answers (docs/phase0/phase0_rerun_read.md, classes C6b, C19,
C20). Eleven answers were about something the question was not about, in three ways:

* **C6b — a deictic nobody bound.** "I've developed a headache in this room" names no
  room. Four answers, four different wrong moves: one declined outright, one bound
  "here" to whichever sound sensor a search returned first, one read "this room" as the
  whole building and refused the fetch as too large, and one declined a question about
  meeting rooms the building instruments. None asked which room. Asking is the only
  move that is neither a guess nor a refusal.

* **C19 — a lane claimed a question because a word appeared in it.** "who **operates**"
  reached the building's own operator record; "which endpoints have lost connectivity"
  reached a census of sensor classes; "collaboration **areas**" reached the floor-plan
  geometry lane; "ready for the next confirmed collection" reached the teaching-room
  readiness lane; a policy-implementation audit reached the compliance template. In
  every one the matched word is present and the question is about something else.

* **C20 — the referent gate read an adjective as a place.** "a brief CORRIDOR-RELATED
  peak" was refused with "'brief corridor' does not exist in this building": a true
  sentence about a subject nobody named, from the gate built to prevent exactly that.

The tests below use the live questions verbatim, so a regression reads as the defect
rather than as an abstraction of it.
"""

from unittest.mock import AsyncMock, patch

import pytest

from orchestrator.agents.dialogue_agent import (
    DialogueAgent,
    _conversation_named_a_space,
    _is_followup_query,
)
from orchestrator.services import routing_contract as rc
from orchestrator.services.referent_resolver import (
    detect_space_deixis,
    detect_typed_referent,
    names_a_specific_space,
)
from orchestrator.services.semantic_router import SemanticRouter
from shared.models import ConversationState, Message

pytestmark = pytest.mark.unit


# The live questions, by their row number in docs/phase0/phase0_rerun_read.jsonl.
Q74 = (
    "I've developed a headache in this room. What are the current measured conditions, "
    "and is anything clearly unusual compared with this room's reliable baseline?"
)
Q100 = (
    "Should I stay here, or are noise, crowding or CO2 likely to get noticeably worse "
    "during the next hour?"
)
Q101 = (
    "The previous class has just ended. Are CO2 and temperature back near this room's "
    "usual pre-class levels?"
)
Q137 = "What systems are specific for the meeting room?"
Q14 = (
    "For each local, shared or inherited control, who operates, monitors and evidences "
    "each component, and what must be tested within this unit?"
)
# PARAPHRASED, not the live wording: the question this row came from is also in the SEALED
# Gate A set, and a sealed question written into a test is a question the system has been
# tuned on (tests/test_the_sealed_set_is_not_in_any_fixture.py). This keeps the shape the rule
# is about — an interrogative naming equipment kinds, asking about their STATE, not what exists.
Q46 = (
    "Which approved plant, sensor and door-controller endpoints have dropped off the "
    "network, and is the fault local, segment-wide or upstream?"
)
Q71 = (
    "Do Abacws local procedures and work instructions implement the current institutional "
    "policies without omissions, contradictions or unauthorised local variation?"
)
Q89 = (
    "What mix of desks, focus rooms, collaboration areas, meeting rooms, storage and "
    "support space is justified by approved operating assumptions and consultation?"
)
Q110 = (
    "Is the loading or exchange area clear, booked and operationally ready for the next "
    "confirmed collection?"
)
Q2 = (
    "Is today's noise a brief corridor-related peak or a sustained room-level problem "
    "likely to continue?"
)


def _state(*contents: str) -> ConversationState:
    """A conversation whose turns alternate user/assistant, current message last."""
    msgs = [
        Message(role="user" if i % 2 == 0 else "assistant", content=c)
        for i, c in enumerate(contents)
    ]
    return ConversationState(
        conversation_id="conv-deixis",
        user_id="tester",
        user_message=contents[-1] if contents else "",
        building_id="bldg1",
        messages=msgs,
    )


# ── C6b: an unbound deictic asks which room ──────────────────────────────────


@pytest.mark.parametrize(
    "query,expected",
    [
        (Q74, "this room"),
        (Q100, "here"),
        (Q101, "this room"),
        (Q137, "the meeting room"),
    ],
)
def test_the_four_live_questions_carry_an_unbound_deictic(query, expected):
    assert detect_space_deixis(query) == expected
    assert names_a_specific_space(query) is False


# ── BUG-719: the deictics the first pass missed ──────────────────────────────
#
# Verified by hand 2026-09-18 across the four phrasings the fix claims to cover. Three of
# them held. The fourth did not: "here" was only a room when a first-person presence verb
# ("stay", "sitting", "I'm") sat beside it, so "is it stuffy in here?", "how warm is it
# here?" and "what is the air quality here?" — the three most natural ways to ask — fell
# straight through and were answered about whichever space a search returned first.
#
# A CONDITION settles it. "Is there a café here?" can mean the campus; a reading of
# warmth, noise, light or air can only be a reading of the room the asker is standing in.


@pytest.mark.parametrize(
    "query",
    [
        "Is it stuffy in here?",
        "How warm is it here?",
        "What is the air quality here?",
        "Is it warm here?",
        "Is the CO2 high in here?",
        "How noisy is it in here right now?",
    ],
)
def test_a_condition_asked_about_here_is_asked_about_this_room(query):
    assert detect_space_deixis(query) == "here"
    assert names_a_specific_space(query) is False


@pytest.mark.parametrize(
    "query",
    [
        "How noisy is this space?",
        "Is this space too warm?",
        "What systems are specific for the meeting room?",
        "Is the meeting room free?",
        "Can I work in this area?",
        "Is it too warm in the current room?",
    ],
)
def test_the_other_deictic_phrasings_are_covered_too(query):
    assert detect_space_deixis(query) is not None
    assert names_a_specific_space(query) is False


@pytest.mark.parametrize(
    "query",
    [
        # "here" meaning the SITE, with nothing an instrument reads in the question.
        "Is there a café here?",
        "Where is the nearest toilet from here?",
        "Do you have parking here?",
    ],
)
def test_here_without_a_condition_is_still_the_site(query):
    assert detect_space_deixis(query) is None


def test_a_presence_verb_still_binds_here_even_where_the_site_was_meant():
    """Pinned as it stands, not as it should be. "How many people work here?" most likely
    means the building, but "work ... here" is the presence-verb shape that predates this
    change, and narrowing it is a separate decision with its own evidence. Recorded so the
    next reader knows it was looked at rather than missed."""
    assert detect_space_deixis("How many people work here?") == "here"


@pytest.mark.parametrize(
    "query",
    [
        "What is the temperature in room 5.01?",
        "Is this room 5.01 too warm?",  # deictic AND an id — the id wins
        "How warm is zone 5.28 right now?",
        "What is the air quality on floor 3?",
        "What's the temperature in the atrium?",
    ],
)
def test_a_question_that_names_its_room_is_never_asked_which_room(query):
    assert names_a_specific_space(query) is True


@pytest.mark.parametrize(
    "query",
    [
        "How many sensors are there in this building?",
        "Which rooms are on floor 2?",
        "how many parking bays are free?",
        "What is the average CO2 across the building today?",
    ],
)
def test_a_whole_site_question_is_not_a_deictic_one(query):
    """ "Here" meaning the site is answerable; only a room-scale deixis is asked about."""
    assert detect_space_deixis(query) is None


@pytest.mark.asyncio
@pytest.mark.parametrize("query", [Q74, Q100, Q101, Q137])
async def test_an_unbound_deictic_asks_which_room_before_any_lane_claims_it(query):
    """The ask must beat the probes that answer before classification.

    Two of these four were answered in under 1.5 s by a short-circuit that decides
    before the classifier runs, so a routing rule could not have reached them however
    it was ordered. This test calls the real entry point with no conversation history
    and asserts it returns without ever reaching the LLM.
    """
    result = await DialogueAgent().detect_intent(_state(query))
    assert result["intent"] == "clarification"
    assert "unbound_spatial_deixis" in result.get("routing_rules_applied", [])
    question = result["clarification_question"]
    assert question and "?" in question
    # The dialogue node discards a clarification that reads as a question about
    # WHERE THE USER IS in the world; this one is about which room in this building.
    for spurious in ("location", "city", "region", "where are you"):
        assert spurious not in question.lower()


@pytest.mark.asyncio
async def test_a_room_named_in_an_earlier_turn_is_not_asked_for_again():
    """The conversation already said which room — that binding must hold."""
    state = _state(
        "What is the CO2 in room 5.01 right now?",
        "CO2 in room 5.01 is 620 ppm.",
        Q101,
    )
    assert _conversation_named_a_space(state.messages) is True
    # And with the room bound, the rewrite — not a clarification — owns the turn.
    with patch(
        "orchestrator.agents.dialogue_agent.llm_manager.generate",
        new=AsyncMock(
            return_value="Are CO2 and temperature in room 5.01 back near "
            "that room's usual pre-class levels?"
        ),
    ):
        rewritten = await DialogueAgent().rewrite_to_standalone(state)
    assert rewritten and "5.01" in rewritten


def test_only_the_users_own_turns_can_bind_the_deictic():
    """An assistant reply listing rooms is not the user choosing one."""
    state = _state(
        "What rooms does this building have?",
        "It holds room 2.44, room 2.53 and room 2.01, among others.",
        Q74,
    )
    assert _conversation_named_a_space(state.messages) is False


@pytest.mark.parametrize("query", [Q74, Q100, Q101, Q137])
def test_a_deictic_question_is_offered_to_the_rewrite(query):
    """`_is_followup_query` gates the rewrite, and these carry none of its markers.

    Q101 is fourteen words with no "there"/"that"/"the same" in it, so no rewrite was
    even attempted in a conversation whose previous turn had named the room.
    """
    assert _is_followup_query(query) is True


@pytest.mark.parametrize("query", [Q74, Q100, Q101, Q137])
def test_the_concept_stage_does_not_convert_the_ask_into_a_reading(query):
    """The rule that rescues open-domain clarifications must leave this one alone.

    `building_question_not_general` takes a `clarification` naming a measurand and makes
    it `analytics` — correct when the classifier asked "which city?", and the exact
    defect here: Q101 names CO2 and temperature, and the data lane answered it with
    "that question reaches 296 sensors" for a question about one room.
    """
    normalized = {
        "intent": "clarification",
        "concepts": [
            {"concept_id": "co2", "brick_classes": ["CO2_Level_Sensor"]},
            {"concept_id": "temperature", "brick_classes": ["Air_Temperature_Sensor"]},
        ],
        "entities": [],
    }
    rc.apply_contract(query, normalized, stage="concept")
    assert normalized["intent"] == "clarification"


# ── C19: a lane may not claim a question for containing one of its words ─────


def _route(query: str, intent: str) -> tuple:
    normalized = {"intent": intent, "general": intent == "general", "analytics": False}
    applied = list(rc.apply_contract(query, normalized, stage="parse"))
    applied += list(rc.apply_contract(query, normalized, stage="post"))
    return normalized["intent"], applied


@pytest.mark.parametrize("start", ["general", "capability", "metadata", "sensor_data"])
@pytest.mark.parametrize("query", [Q14, Q46])
def test_a_state_or_accountability_question_is_not_a_census(query, start):
    """ "Which endpoints have LOST connectivity" is not "which endpoints are there"."""
    intent, applied = _route(query, start)
    assert "inventory_to_discovery" not in applied
    assert intent != "discovery"


@pytest.mark.parametrize(
    "query,start",
    [
        ("What equipment is installed in this building?", "capability"),
        ("what sensors are there?", "sensor_data"),
        ("What sensor types are available in this building?", "sensor_data"),
        ("which meters do we have?", "general"),
        ("list the chillers", "metadata"),
        ("what kinds of sensors does the building have?", "general"),
    ],
)
def test_real_census_questions_still_reach_the_one_census_handler(query, start):
    intent, applied = _route(query, start)
    assert intent == "discovery"
    assert "inventory_to_discovery" in applied


@pytest.mark.parametrize("start", ["general", "capability", "metadata", "discovery"])
def test_a_space_mix_question_is_not_a_room_measurement(start):
    """ "collaboration areas" names kinds of place; it does not ask how big one is."""
    intent, applied = _route(Q89, start)
    assert "room_geometry_spatial" not in applied
    assert intent != "spatial_query"
    assert SemanticRouter.is_space_geometry_question(Q89) is False


@pytest.mark.parametrize(
    "query",
    [
        "What is the area of room 0.34?",
        "what is the total area of this lab?",
        "what is the area in m2 of the office?",
        "How big is room 0.34?",
        "what are the dimensions of room 0.10",
    ],
)
def test_real_geometry_questions_still_reach_the_geometry_lane(query):
    assert SemanticRouter.is_space_geometry_question(query) is True


@pytest.mark.parametrize("start", ["general", "capability", "metadata", "sensor_data"])
def test_a_waste_collection_is_not_a_teaching_readiness_check(start):
    intent, applied = _route(Q110, start)
    assert "readiness_check" not in applied
    assert intent != "readiness_check"


@pytest.mark.parametrize(
    "query",
    [
        "Is room 1.06 ready for my class?",
        "Is 3.13 ready for the seminar at 2pm?",
        "what should I know before teaching in 0.34?",
        "run a readiness check on room 2.01",
    ],
)
def test_real_readiness_questions_still_reach_the_readiness_lane(query):
    intent, applied = _route(query, "capability")
    assert intent == "readiness_check"


def test_a_policy_audit_does_not_get_the_zone_required_template():
    """Nothing in it is measurable, so the compliance lane has nothing to check."""
    intent, applied = _route(Q71, "compliance")
    assert intent == "capability"
    assert "compliance_without_a_measurable_check" in applied


@pytest.mark.parametrize(
    "query",
    [
        "Is the temperature in Zone 5.28 within ASHRAE 55 comfort limits?",
        "Check ASHRAE 62.1 compliance for Zone 5.28",
        "Are we compliant with ASHRAE 55?",
        "Is room 3.13 within the CO2 limit?",
    ],
)
def test_a_checkable_compliance_question_keeps_its_lane(query):
    intent, applied = _route(query, "compliance")
    assert "compliance_without_a_measurable_check" not in applied


# ── C20: a hyphenated space word is an adjective, not a place ────────────────


def test_a_hyphenated_space_word_names_no_space():
    """ "corridor-related" modifies "peak"; the head noun of the phrase is "peak"."""
    assert detect_typed_referent(Q2) is None


@pytest.mark.parametrize(
    "query,phrase",
    [
        ("Is the public corridor on floor 1 busy?", "public corridor"),
        ("what's the temperature in the atrium?", "atrium"),
        ("how warm is the rooftop garden?", "rooftop garden"),
    ],
)
def test_a_genuinely_named_space_is_still_gated(query, phrase):
    typed = detect_typed_referent(query)
    assert typed is not None and typed.phrase == phrase
