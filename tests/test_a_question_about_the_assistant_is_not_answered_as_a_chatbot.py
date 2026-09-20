# -*- coding: utf-8 -*-
"""Live 2026-09-19: "What kind of user friendly features do you have?" was answered

    General knowledge (not from this building's records): I'm designed to be intuitive and
    helpful... I can summarize long documents, translate text, generate ideas

— a generic chatbot's abilities, which are neither this system's nor this building's. A question
about the ASSISTANT belongs to the self-description lane, which answers from the live intent
registry and this building's own figures.

The negatives are the point of the tightening: "you" must be the subject, so a question about what
the BUILDING has keeps its data lane.
"""

import pytest

from orchestrator.services.routing_contract import apply_contract
from orchestrator.services.self_description import is_self_question

pytestmark = pytest.mark.unit

ABOUT_THE_ASSISTANT = [
    "What kind of user friendly features do you have?",  # the failing question
    "What features do you have?",
    "What sort of capabilities do you have?",
    "What are your capabilities?",
    "What can you do?",
    "What is OntoSage?",
]

ABOUT_THE_BUILDING = [
    "What kind of sensors does the building have?",
    "Do you have a CO2 sensor in the lab?",
    "What can you tell me about this building?",
    "What features does Room 1.06 have?",
    "How many meeting rooms do we have?",
]


@pytest.mark.parametrize("question", ABOUT_THE_ASSISTANT)
def test_a_question_about_the_assistant_is_recognised(question):
    assert is_self_question(question), question


@pytest.mark.parametrize("question", ABOUT_THE_BUILDING)
def test_a_question_about_the_building_is_not(question):
    assert not is_self_question(question), question


@pytest.mark.parametrize("start", ["general", "general_knowledge", "capability", "clarification"])
def test_it_reaches_the_self_description_lane_over_all_three_stages(start):
    n = {"intent": start, "entities": [], "analytics": False, "general": start == "general",
         "concepts": [{"brick_classes": ["brick:Temperature_Sensor"]}]}
    for stage in ("parse", "post", "concept"):
        apply_contract("What kind of user friendly features do you have?", n, stage=stage)
    assert n["intent"] == "self_description"


def test_the_dialogue_agent_settles_it_before_the_model_is_asked():
    """`detect_intent` short-circuits a self question, so no lane can answer it as a chatbot."""
    import inspect

    from orchestrator.agents.dialogue_agent import DialogueAgent

    src = inspect.getsource(DialogueAgent.detect_intent)
    assert "is_self_question(user_query)" in src
    assert src.index("is_self_question(user_query)") < src.index("_held_record")
