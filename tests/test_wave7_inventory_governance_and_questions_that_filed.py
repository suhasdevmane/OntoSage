# -*- coding: utf-8 -*-
"""Wave 7 (hand read of tail H, 2026-09-20).

1. A QUESTION filed a ticket (REP-8AC1A1). An interrogative that states no fault, names no place and
   asks for no action is never filed; a real fault statement still is.
2. Inventory and discovery listings answered governance questions ("Room 234, Equipment 147 ...",
   "Found 3543 sensors").
3. Misclaims: sensing question -> alerts lane; governance judgement -> readings; wish -> control list.
4. "is there sufficient exhaust ventilation to prevent mold growth?" reached the all-sensors fetch.
"""

import inspect

import pytest

from orchestrator.services import report_statement as rs
from orchestrator.services.governance_question import is_governance_question
from orchestrator.services.ontology_inventory import is_inventory_question
from orchestrator.services.routing_contract import apply_contract
from orchestrator.services.ungrounded_question import handoff

pytestmark = pytest.mark.unit

CO2 = [{"brick_classes": ["brick:CO2_Sensor"]}]


def _all_stages(question, start, concepts=()):
    n = {"intent": start, "entities": [], "analytics": False, "general": False, "concepts": list(concepts)}
    for stage in ("parse", "post", "concept"):
        apply_contract(question, n, stage=stage)
    return n["intent"]


INSTRUMENT_Q = (
    "Is every piece of measuring equipment set to the right range and still in calibration "
    "for the reading being taken?"
)


def test_a_question_that_states_no_fault_is_recognised():
    assert rs.is_question_not_a_fault(INSTRUMENT_Q)


def test_the_intake_node_refuses_to_file_such_a_question():
    from orchestrator.workflow._orchestrator import WorkflowOrchestrator

    src = inspect.getsource(WorkflowOrchestrator._report_intake_node)
    assert "is_question_not_a_fault" in src and "question_states_no_fault" in src


@pytest.mark.parametrize(
    "q",
    [
        "The fire door on floor 2 is broken",
        "The heating is not working in room 1.06",
        "Can someone fix the projector?",
        "Could you send someone to clean the spill?",
        "There is a gas smell in the kitchen",
    ],
)
def test_a_real_fault_or_request_still_files(q):
    assert not rs.is_question_not_a_fault(q), q


GOVERNANCE = [
    "What asset and space information may be shown to this user role for this purpose without exposing restricted or personal detail?",
    "Which BMS points are physically verified against the assets and sensors they claim to represent?",
    "Can every reported value be traced back to the exact raw records, mappings, coefficients, parameters and code that produced it?",
    "Do current layouts and aggregate demand indicate that a competent assessment of occupancy control, circulation or egress capacity is now required?",
    "Before confirming the booking, which room features are currently verified against the requirements the person has chosen to state?",
]


@pytest.mark.parametrize("q", GOVERNANCE)
def test_a_governance_question_is_neither_a_census_nor_a_reading(q):
    assert is_governance_question(q)
    assert not is_inventory_question(q)
    for start in ("sensor_data", "analytics", "discovery", "events", "general", "maintenance"):
        assert _all_stages(q, start, CO2) == "capability", (q, start)


@pytest.mark.parametrize(
    "q",
    [
        "How many sensors are in the building?",
        "What kinds of equipment do we have?",
        "List the meters",
        "Which sensors are installed on floor 3?",
    ],
)
def test_a_real_inventory_question_still_gets_the_census(q):
    assert not is_governance_question(q)
    assert is_inventory_question(q), q


def test_a_bare_what_or_which_is_not_an_inventory_question():
    assert not is_inventory_question("What equipment information is restricted?")
    assert not is_inventory_question("Which assets are the most important?")


def test_how_does_it_monitor_is_not_an_alerts_question():
    from orchestrator.services.routing_contract import _acts_on_a_building_system

    q = "How does it monitor for people using temperature or co2 or motion?"
    assert not _acts_on_a_building_system(q)
    assert _all_stages(q, "automation_capability") != "automation_capability"


WISH = "if there is a certain type of monitor that causes glare, it would be nice for the system to adjust the lighting"


@pytest.mark.parametrize("start", ["control", "general", "capability", "sensor_data"])
def test_a_wish_is_a_suggestion_not_a_control_request(start):
    assert _all_stages(WISH, start) == "suggestion"


@pytest.mark.parametrize("q", ["Turn off the lights in room 5.01", "Open the windows"])
def test_a_command_is_still_a_control_request(q):
    assert _all_stages(q, "general") == "control", q


def test_a_design_adequacy_question_never_reaches_the_fetch():
    q = "is there sufficient exhaust ventilation to prevent mold growth?"
    assert handoff(q) == "capability"
    for start in ("sensor_data", "analytics", "recommend"):
        assert _all_stages(q, start, CO2) == "capability", start


@pytest.mark.parametrize(
    "q", ["Is there enough CO2 data for room 5.01 today?", "Is there sufficient data to plot the trend?"]
)
def test_a_data_sufficiency_question_is_not_taken(q):
    assert handoff(q) is None, q
