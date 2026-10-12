"""Routing defects found by the 2026-10-10 Open WebUI probe rounds, each pinned at its rule.

BUG-1515 a room id read as a numbered list split one question into three sub-tasks;
BUG-1518 the post stage promoted a register decision back to a reading lookup;
BUG-1519 "which sensors have stopped reporting?" classified analytics never reached the freshness lane;
BUG-1520 "what maintenance was done last month?" / "who maintains the lifts?" reached the intake lane;
BUG-1521 an incident-LOG question went to the events lane;
BUG-1524 "what does the building measure?" was answered with cost lines.
"""

import pytest

from orchestrator.services import routing_contract as rc
from orchestrator.services.multi_intent_detector import MultiIntentDetector
from orchestrator.services.observability import is_observability_question, is_open_question

pytestmark = pytest.mark.unit


def _ctx(query: str, intent: str) -> "rc._Ctx":
    return rc._Ctx(query=query, ql=query.lower(), normalized={"intent": intent}, sr=None)


def test_a_dotted_room_id_is_not_a_numbered_list():
    gate = MultiIntentDetector()._passes_heuristic
    assert not gate("Compare CO2 in room 1.06 this morning with yesterday morning.")
    # a real enumeration still opens the gate
    assert gate("1. what is the temperature in room 1.06 and 2. compare it with last week")


@pytest.mark.parametrize(
    "question",
    [
        "What maintenance was done last month?",
        "Who maintains the lifts?",
        "Who services the chillers?",
    ],
)
def test_a_maintenance_question_is_a_register_question(question):
    assert rc.maintenance_record_question(question)
    assert (
        rc._r_maintenance_record_is_a_register_question(_ctx(question, "maintenance")) == "metadata"
    )


def test_a_fault_statement_still_files_a_ticket():
    assert not rc.maintenance_record_question("The lift on floor 2 is broken.")


@pytest.mark.parametrize(
    "question, owned",
    [
        ("What incidents or near misses were logged in September?", True),
        ("How many incidents happened last month?", True),
        ("How should incidents be handled?", False),
        ("What is the incident procedure?", False),
    ],
)
def test_only_the_incident_log_shape_is_claimed_for_the_register(question, owned):
    assert rc.register_owns_the_record(question) is owned


def test_the_post_stage_keeps_a_register_decision():
    q = "What timetabled sessions are in room 1.06 today?"
    assert rc.register_owns_the_record(q)
    assert rc._r_data_query_promotion(_ctx(q, "metadata")) is None


def test_a_silence_question_classified_analytics_reaches_the_freshness_lane():
    q = "Which sensors have stopped reporting?"
    assert is_observability_question(q)
    assert rc._r_observability_query(_ctx(q, "analytics")) == "observability"


@pytest.mark.parametrize(
    "question", ["What does the building measure?", "What sensors does the building have?"]
)
def test_what_the_building_measures_is_the_menu(question):
    assert is_observability_question(question)
    assert is_open_question(question)


def test_a_reading_question_is_not_a_reach_question():
    assert not is_observability_question("What is the CO2 in room 5.01?")
    assert not is_observability_question("What does the building do?")


# ── round 2 (2026-10-10) ─────────────────────────────────────────────────────────────────────


def _route(question: str, intent: str) -> str:
    out = intent
    for rule in rc.PARSE_STAGE_RULES:
        try:
            got = rule.fn(_ctx(question, out))
        except Exception:  # a rule that cannot run on a bare context passes, as live
            got = None
        if got:
            out = got
    return out


@pytest.mark.parametrize(
    "question",
    [
        "Make room 2.03 warmer please.",
        "Please make it a bit cooler in here",
        "Turn up the heating on floor 2",
    ],
)
def test_an_imperative_comfort_change_is_a_control_request(question):
    assert _route(question, "sensor_data") == "control"


def test_a_comfort_question_is_not_a_control_request():
    assert _route("Is it warmer than yesterday in room 2.03?", "sensor_data") != "control"


@pytest.mark.parametrize(
    "question",
    ["Which staff member badged in first today?", "Who was the first person to arrive today?"],
)
def test_isolating_one_person_s_arrival_is_refused(question):
    from orchestrator.services.privacy.inference_classes import classify_inference

    assert classify_inference(question) == "individual_pattern"


@pytest.mark.parametrize(
    "question", ["How many people came in today?", "Which rooms were entered after hours?"]
)
def test_aggregate_arrival_questions_are_not_refused(question):
    from orchestrator.services.privacy.inference_classes import classify_inference

    assert classify_inference(question) is None


def test_a_room_s_sensor_inventory_is_the_room_s_reach_menu():
    assert _route("What sensors are in room 2.03?", "sensor_data") == "observability"
    assert _route("How many sensors are in room 2.03?", "metadata") == "metadata"


def test_whats_on_in_a_room_is_a_booking_question():
    from orchestrator.services.event_query_service import classify_event_question

    assert classify_event_question("What's on in room 1.25 tomorrow?") == "bookings_list"
    assert classify_event_question("What is on floor 3?") is None


def test_people_through_the_entrance_is_an_events_question():
    assert rc.events_question("How many people came through the main entrance last week?")
