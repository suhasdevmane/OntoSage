# -*- coding: utf-8 -*-
"""Wave 6 lane misfires (hand read of tail G, 2026-09-20): the answer was about the wrong thing.

1. "... which key, fob ... resource is confirmed available" -> an entrance-arrivals count.
2. "Does the system do an automatic back-up of data?" -> "here is what this building can do about
   alerts".
3. A register/booking question labelled report or planner -> "no report to give" after 47-158 s.
4. Advice, physics and requirements questions reached the all-sensors fetch and were refused.
5. "Which floor has the LAST occupancy" (a slip for least) was not read as a superlative.
"""

import pytest

from orchestrator.services.aggregate_lane import parse_intent
from orchestrator.services.routing_contract import apply_contract, events_question
from orchestrator.services.ungrounded_question import handoff

pytestmark = pytest.mark.unit

ILLUM = [{"brick_classes": ["brick:Illuminance_Sensor"]}]
SOUND = [{"brick_classes": ["brick:Sound_Level_Sensor"]}]
CO2 = [{"brick_classes": ["brick:CO2_Sensor"]}]


def _all_stages(question, start, concepts=()):
    n = {"intent": start, "entities": [], "analytics": False, "general": False, "concepts": list(concepts)}
    for stage in ("parse", "post", "concept"):
        apply_contract(question, n, stage=stage)
    return n["intent"]


ACCESS_Q = (
    "At the agreed secure entrance, which authorised key, fob or local access resource is "
    "confirmed available, and through which custodian?"
)


def test_a_participle_is_not_the_subject_of_an_availability_question():
    assert not events_question(ACCESS_Q)
    for start in ("general", "sensor_data", "analytics", "recommend", "capability"):
        assert _all_stages(ACCESS_Q, start) != "events", start


@pytest.mark.parametrize(
    "q", ["Is the seminar room free?", "is room 5.01 booked", "Is the atrium available tomorrow?", "How many bookings today?"]
)
def test_a_real_availability_question_still_reaches_events(q):
    assert events_question(q), q


BACKUP_Q = "Does the system do an automatic back-up of data in case of outages?"


@pytest.mark.parametrize("start", ["general", "capability", "automation_capability", "alert"])
def test_a_data_backup_question_is_not_an_automation_question(start):
    assert _all_stages(BACKUP_Q, start) not in ("automation_capability", "alert")


@pytest.mark.parametrize(
    "q",
    [
        "Can the system automatically turn off the lights when a room is empty?",
        "Can the building automatically adjust the heating?",
        "Does the building notify anyone by itself when CO2 is high?",
    ],
)
def test_a_control_automation_question_keeps_its_lane(q):
    assert _all_stages(q, "general") == "automation_capability", q


CATALOGUE = [
    "Which full-day cohort patterns lack an authorised usable meal or rest break after realistic transitions are removed?",
    "A lift is officially unavailable. Which bookings no longer have a verified route to their rooms?",
]


@pytest.mark.parametrize("q", CATALOGUE)
@pytest.mark.parametrize("start", ["report", "planner"])
def test_a_catalogue_question_is_not_a_report_or_planner_request(q, start):
    assert _all_stages(q, start) not in ("report", "planner"), (q, start)


@pytest.mark.parametrize(
    "q, start",
    [
        ("Give me a report on CO2 last week", "report"),
        ("Generate a summary of energy use", "report"),
        ("Analyse energy, then create a chart and export it", "planner"),
        ("Make the building more eco-friendly", "planner"),
    ],
)
def test_a_real_report_or_planner_request_keeps_its_lane(q, start):
    assert _all_stages(q, start) == start, q


ADVICE = [
    ("How can we optimize lighting usage?", ILLUM),
    ("in the windows how will the air flow", CO2),
]


@pytest.mark.parametrize("q, concepts", ADVICE)
@pytest.mark.parametrize("start", ["sensor_data", "analytics", "recommend"])
def test_advice_and_physics_never_reach_the_fetch(q, concepts, start):
    assert handoff(q) == "general_guidance"
    assert _all_stages(q, start, concepts) == "general_guidance", (q, start)


REQUIRE_Q = "What containment and monitoring are required for noise, dust, debris, vibration or odour from this job?"


@pytest.mark.parametrize("start", ["sensor_data", "analytics", "recommend"])
def test_a_requirements_question_goes_to_the_documents(start):
    assert handoff(REQUIRE_Q) == "capability"
    assert _all_stages(REQUIRE_Q, start, SOUND) == "capability"


@pytest.mark.parametrize(
    "q",
    [
        "How can we see the CO2 in room 5.01 today?",
        "How can I book a room?",
        "What is the CO2 in room 5.01 now?",
        "What monitoring is installed on floor 2?",
    ],
)
def test_grounded_or_data_questions_are_not_taken(q):
    assert handoff(q) is None, q


def test_last_for_least_is_read_as_a_minimum():
    a = parse_intent("Which floor has the last occupancy at the moment?")
    assert a is not None and a.stat == "min" and a.group == "floor" and a.now
    assert parse_intent("When was the last occupancy reading?") is None
