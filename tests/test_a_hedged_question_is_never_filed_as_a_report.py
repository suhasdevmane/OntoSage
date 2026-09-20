# -*- coding: utf-8 -*-
"""Wave 5 routing classes (hand read of tail F, 2026-09-19).

1. SERIOUS: "if the building are safe or not" was FILED as a high-priority safety ticket. A hedged or
   whole-building-verdict message that states no fault and names no place is never a report; a real
   fault statement still files.
2. An automation/alert label needs an automate/alert/notify/standing-rule shape.
3. "Can you make reservations in the cafe through AI?" asks the ASSISTANT to transact: a scope
   statement, not a bookings list.
4. "How many people can this building hold?" is a recorded CAPACITY, not a reading.
"""

import inspect

import pytest

from orchestrator.services import report_statement as rs
from orchestrator.services.building_profile import detect_facet, render, BuildingProfile
from orchestrator.services.routing_contract import apply_contract
from orchestrator.services.scope_policy import KIND_TRANSACTION, out_of_scope_kind

pytestmark = pytest.mark.unit

OCC = [{"brick_classes": ["brick:Occupancy_Sensor"]}]


def _all_stages(question, start, concepts=()):
    n = {"intent": start, "entities": [], "analytics": False, "general": False, "concepts": list(concepts)}
    for stage in ("parse", "post", "concept"):
        apply_contract(question, n, stage=stage)
    return n["intent"]


NOT_REPORTS = [
    "if the building are safe or not",
    "Is the building safe?",
    "whether the building is safe",
    "I wonder if it's safe here",
    "tell me if we are safe or not",
]

REAL_REPORTS = [
    "The fire door on floor 2 is broken",
    "The stairs are unsafe",
    "There is a gas smell in the kitchen",
    "The heating is not working in room 1.06",
    "Suggestion: add more bins in the atrium",
]


@pytest.mark.parametrize("q", NOT_REPORTS)
def test_a_hedged_or_verdict_message_is_not_a_report(q):
    assert rs.is_not_a_report(q), q
    assert rs.clarification_for(q)


@pytest.mark.parametrize("q", REAL_REPORTS)
def test_a_real_fault_statement_is_still_a_report(q):
    assert not rs.is_not_a_report(q), q
    assert rs.clarification_for(q) is None


@pytest.mark.parametrize("start", ["safety_report", "maintenance", "complaint", "general", "sensor_data", "capability"])
def test_the_verdict_message_reaches_a_clarification_from_every_label(start):
    assert _all_stages("if the building are safe or not", start, OCC) == "clarification"


@pytest.mark.parametrize(
    "q, start, expected",
    [
        ("The fire door on floor 2 is broken", "safety_report", "safety_report"),
        ("The heating is not working in room 1.06", "maintenance", "maintenance"),
        ("There is a gas smell in the kitchen", "safety_report", "safety_report"),
    ],
)
def test_real_reports_keep_their_lane(q, start, expected):
    assert _all_stages(q, start) == expected


def test_the_intake_node_refuses_to_file_a_hedged_message_even_if_routing_changes():
    from orchestrator.workflow._orchestrator import WorkflowOrchestrator

    src = inspect.getsource(WorkflowOrchestrator._report_intake_node)
    assert "clarification_for" in src and "not_a_statement" in src


def test_the_safety_reply_says_nothing_was_filed():
    assert "nothing has been filed" in rs.reply_for("is the building safe").lower()


# ── 2. automation shape ─────────────────────────────────────────────────────


@pytest.mark.parametrize("start", ["automation_capability", "alert"])
def test_an_automation_label_without_the_shape_goes_to_capability(start):
    assert _all_stages("Can a managed test client roam between access points?", start) == "capability"


@pytest.mark.parametrize(
    "q", ["Can the system automatically turn off lights?", "Notify me when CO2 exceeds 1000", "Tell me if the lift stops"]
)
def test_a_real_automation_or_alert_question_keeps_its_lane(q):
    assert _all_stages(q, "automation_capability") in ("automation_capability", "alert")


# ── 3. transaction ──────────────────────────────────────────────────────────


@pytest.mark.parametrize(
    "q",
    [
        "Can you make reservations in the cafe through AI?",
        "Book me a room",
        "Can you book a meeting room for me?",
        "Please reserve a table",
    ],
)
def test_asking_the_assistant_to_transact_is_a_scope_statement(q):
    assert out_of_scope_kind(q) == KIND_TRANSACTION, q
    for start in ("events", "control", "general"):
        assert _all_stages(q, start) == "scope_boundary", (q, start)


@pytest.mark.parametrize(
    "q", ["How do I book a room?", "Can I book a room?", "Which rooms are booked this afternoon?", "Show me the bookings"]
)
def test_a_procedure_or_a_records_question_is_not_a_transaction(q):
    assert out_of_scope_kind(q) != KIND_TRANSACTION, q


# ── 4. capacity ─────────────────────────────────────────────────────────────


@pytest.mark.parametrize(
    "q",
    [
        "How many people can this building hold at one time?",
        "What is the capacity of the building?",
        "How many people can the building accommodate?",
    ],
)
def test_a_capacity_question_is_a_building_fact_not_a_reading(q):
    assert detect_facet(q) == "capacity", q
    for start in ("sensor_data", "analytics", "capability", "general"):
        assert _all_stages(q, start, OCC) == "capability", (q, start)


@pytest.mark.parametrize("q", ["How many people are in the building right now?", "What is the occupancy today?"])
def test_a_live_head_count_is_still_a_reading(q):
    assert detect_facet(q) != "capacity"


def test_the_capacity_answer_is_labelled_a_recorded_figure():
    p = BuildingProfile(facts={"Capacity": "about 500 people"}, facets={"capacity": "about 500 people"}, resolved=True)
    text = render(p, "capacity", "Abacws")
    assert "about 500 people" in text and "not a live head-count" in text
