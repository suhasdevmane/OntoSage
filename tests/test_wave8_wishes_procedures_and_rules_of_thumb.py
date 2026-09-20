# -*- coding: utf-8 -*-
"""Wave 8 (hand read of tail J, 2026-09-20): six routing shapes.

1. "What can people do if they don't like the AI temperature settings?" -> a procedure question.
2. "What kind of tasks can I automate?" -> the automation-capability lane.
3. A technique or rule-of-thumb question -> labelled general guidance.
4. Proactive-notice -> capability; a polite request to change the environment -> control; "is there a
   way to notify the lighting system" -> a suggestion.
5. "Is MY office warmer than comparable offices?" names no office -> ask which.
"""

import pytest

from orchestrator.services.guidance_shape import is_general_guidance_question
from orchestrator.services.routing_contract import apply_contract

pytestmark = pytest.mark.unit

TEMP = [{"brick_classes": ["brick:Air_Temperature_Sensor"]}]
OCC = [{"brick_classes": ["brick:Occupancy_Sensor"]}]


def _all_stages(question, start, concepts=()):
    n = {"intent": start, "entities": [], "analytics": False, "general": False, "concepts": list(concepts)}
    for stage in ("parse", "post", "concept"):
        apply_contract(question, n, stage=stage)
    return n["intent"]


@pytest.mark.parametrize("start", ["general", "recommend", "sensor_data", "analytics", "capability"])
def test_a_what_can_people_do_question_is_a_procedure(start):
    q = "What can people do if they don't like the AI temperature settings?"
    assert _all_stages(q, start, TEMP) == "capability", start


@pytest.mark.parametrize("start", ["general", "recommend", "sensor_data", "capability", "automation_capability"])
def test_what_can_i_automate_reaches_the_automation_lane(start):
    assert _all_stages("What kind of tasks can I automate?", start, TEMP) == "automation_capability", start


@pytest.mark.parametrize(
    "q",
    [
        "can predictive analytics help reduce future resource consumption?",
        "How many people is enough for a meeting?",
    ],
)
@pytest.mark.parametrize("start", ["general", "recommend", "sensor_data", "analytics", "capability"])
def test_a_technique_or_rule_of_thumb_is_general_guidance(q, start):
    assert is_general_guidance_question(q)
    assert _all_stages(q, start, OCC) == "general_guidance", (q, start)


@pytest.mark.parametrize(
    "q",
    [
        "How many people are in room 5.01 right now?",
        "How many people are in the building today?",
        "Can predictive analytics help reduce energy in our building?",
        "How much energy is typical for this building?",
    ],
)
def test_a_grounded_question_is_not_taken_as_guidance(q):
    assert not is_general_guidance_question(q), q


PROACTIVE = "could the building proactively notice when harmful materials may be used and offer a safer option that is already available?"


@pytest.mark.parametrize("start", ["general", "recommend", "sensor_data", "analytics"])
def test_a_proactive_notice_question_is_capability(start):
    assert _all_stages(PROACTIVE, start, TEMP) == "capability", start


@pytest.mark.parametrize("start", ["general", "recommend", "sensor_data", "analytics", "automation_capability"])
def test_a_polite_request_to_change_the_environment_is_control(start):
    assert _all_stages("Can you reduce noise in this workpace?", start) == "control", start


@pytest.mark.parametrize("start", ["general", "sensor_data", "automation_capability", "control"])
def test_a_way_to_tell_a_system_is_a_suggestion(start):
    q = "With a presentation on the screen, is there a way to notify the lighting system that this is occurring?"
    assert _all_stages(q, start) == "suggestion", start


@pytest.mark.parametrize("start", ["general", "sensor_data", "analytics", "compare", "clarification", "deliberate"])
def test_my_office_versus_comparable_offices_asks_which_office(start):
    q = "Is my office significantly warmer than comparable offices today once sunlight, occupancy and outdoor conditions are considered?"
    assert _all_stages(q, start, OCC) == "clarification", start


@pytest.mark.parametrize(
    "q, start, expected",
    [
        ("Is room 2.14 warmer than comparable rooms today?", "compare", "compare"),
        ("Can the building automatically turn off the lights when a room is empty?", "general", "automation_capability"),
        ("Turn off the lights in room 5.01", "general", "control"),
        ("How do I book a room?", "general", "general"),
    ],
)
def test_the_neighbouring_shapes_keep_their_lanes(q, start, expected):
    assert _all_stages(q, start) == expected, q
