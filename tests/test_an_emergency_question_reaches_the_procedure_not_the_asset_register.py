# -*- coding: utf-8 -*-
"""SAFETY (live hand read, 2026-09-19): "what should I do if the fire alarm goes off?" was answered

    **1 of the 30 records in the Fire safety asset register matches** (fire asset kind: alarm):
    **FSA-001** - Fire alarm control panel

to a person asking what to do while an alarm sounds. The building's own evacuation text answers it
("leave by the nearest marked fire exit; do not use the lifts; assemble on the road; report to the
floor warden") and is given perfectly to "What is the evacuation procedure?".

The register was not wrong to match — it holds fire alarms — it just has no actions in it. These
tests pin the shape (an action frame + an emergency), the routing over ALL THREE stages, and the
two things that must not move: a question about the EQUIPMENT, and a fault being reported.
"""

import pytest

from orchestrator.services.emergency_procedure import is_emergency_action_question
from orchestrator.services.routing_contract import apply_contract

pytestmark = pytest.mark.unit

ASKS_WHAT_TO_DO = [
    "what should I do if the fire alarm goes off?",  # the failing question
    "What should I do in an emergency?",
    "What do I do if there's a fire?",
    "Where do I go if the fire alarm sounds?",
    "Who do I call if someone is injured?",
    "How do I get out if there is smoke?",
    "What is the procedure if the building floods?",
    "What happens if there is a lockdown?",
    "What should staff do during an evacuation?",
    "What should I do if I am trapped in the lift?",
]

ABOUT_THE_EQUIPMENT_OR_A_REPORT = [
    "Which fire doors are overdue a test?",
    "How many fire extinguishers are there?",
    "When was the fire alarm last tested?",
    "Where is the fire alarm panel?",
    "Which fire safety assets are defective?",
    "The fire door on floor 2 is broken",  # a report, not a question
    "What is the evacuation procedure?",  # already reaches the topic; no action frame needed
    "What should I do about my booking?",  # no emergency
    "What should I do to reduce CO2?",
]


@pytest.mark.parametrize("question", ASKS_WHAT_TO_DO)
def test_an_action_question_about_an_emergency_is_recognised(question):
    assert is_emergency_action_question(question), question


@pytest.mark.parametrize("question", ABOUT_THE_EQUIPMENT_OR_A_REPORT)
def test_equipment_questions_and_reports_are_not(question):
    assert not is_emergency_action_question(question), question


def _all_stages(question, start, concepts=()):
    n = {"intent": start, "entities": [], "analytics": False, "general": False, "concepts": list(concepts)}
    for stage in ("parse", "post", "concept"):
        apply_contract(question, n, stage=stage)
    return n["intent"]


# "alarm" and "smoke" resolve to measurands, so the concept stage would otherwise convert the
# question into a reading -- the trap that cost the lux and quiet-pause answers.
SOUND = [{"brick_classes": ["brick:Sound_Level_Sensor"]}]


@pytest.mark.parametrize(
    "start", ["metadata", "register", "capability", "general", "sensor_data", "clarification"]
)
def test_the_fire_alarm_question_reaches_the_procedure_from_every_label(start):
    assert _all_stages("what should I do if the fire alarm goes off?", start, SOUND) == "capability"


@pytest.mark.parametrize(
    "question, start, expected",
    [
        ("Which fire safety assets are defective?", "metadata", "metadata"),
        ("The fire door on floor 2 is broken", "maintenance", "maintenance"),
        ("There is a fire in the kitchen", "safety_report", "safety_report"),  # reporting one
    ],
)
def test_the_register_and_the_intake_keep_what_they_own(question, start, expected):
    assert _all_stages(question, start, SOUND) == expected


def test_the_dialogue_agents_register_short_circuit_yields_to_it():
    """That return runs BEFORE the contract, and it is the path that produced FSA-001."""
    import inspect

    from orchestrator.agents.dialogue_agent import DialogueAgent

    src = inspect.getsource(DialogueAgent.detect_intent)
    held = src.split("metadata via held record class")[0]
    assert "_is_emergency_action(user_query)" in held
