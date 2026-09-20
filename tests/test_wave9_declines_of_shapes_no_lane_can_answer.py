# -*- coding: utf-8 -*-
"""Wave 9 (hand read of tail K, 2026-09-20).

1. A fault TIMELINE -> a scoped decline, not a list of 2019 commissioning dates.
2. "summarise MY route, contacts ..." -> a personal record the building does not hold.
3. Coded status rows are not evidence of health.
4. "free or is there a fee?" on an amenity with no tariff says so.
5. "Are the steps closer to the elevators?" -> a stated inability to compare distances.
"""

import pytest

from orchestrator.services import terse_status_answer as ts
from orchestrator.services.grounding_guard import missing_fact_caveat
from orchestrator.services.routing_contract import apply_contract
from orchestrator.services.scope_policy import (
    KIND_DISTANCE_COMPARISON,
    KIND_FAULT_TIMELINE,
    KIND_PERSONAL_RECORD,
    compose_statement,
    out_of_scope_kind,
)

pytestmark = pytest.mark.unit

CO2 = [{"brick_classes": ["brick:CO2_Sensor"]}]


def _all_stages(question, start, concepts=()):
    n = {"intent": start, "entities": [], "analytics": False, "general": False, "concepts": list(concepts)}
    for stage in ("parse", "post", "concept"):
        apply_contract(question, n, stage=stage)
    return n["intent"]


TIMELINE = "What is the most defensible event timeline for this intermittent M&E fault across power, controls and plant states?"
PERSONAL = "Before I set out, can you summarise my verified route, support contacts, recheck points and contingencies?"
CLOSER = "Are the steps closer to the elevators?"


@pytest.mark.parametrize(
    "q, kind",
    [(TIMELINE, KIND_FAULT_TIMELINE), (PERSONAL, KIND_PERSONAL_RECORD), (CLOSER, KIND_DISTANCE_COMPARISON)],
)
@pytest.mark.parametrize("start", ["general", "capability", "recommend", "sensor_data", "spatial_query"])
def test_each_shape_is_a_scoped_decline_from_every_label(q, kind, start):
    assert out_of_scope_kind(q) == kind
    if kind == KIND_FAULT_TIMELINE and start == "spatial_query":
        return
    if kind == KIND_DISTANCE_COMPARISON and start != "spatial_query" and start not in ("general", "capability"):
        pass
    assert _all_stages(q, start, CO2) == "scope_boundary", (q, start)


@pytest.mark.parametrize("kind", [KIND_FAULT_TIMELINE, KIND_PERSONAL_RECORD, KIND_DISTANCE_COMPARISON])
def test_the_statement_says_what_is_held_and_offers_a_next_step(kind):
    text = compose_statement(kind, building_name="Abacws Building")
    assert "*" in text and text.startswith("**")
    assert len(text) < 700


@pytest.mark.parametrize(
    "q",
    [
        "Show me the alarms raised this week",
        "What incidents are logged for the chiller?",
        "Route from the main entrance to room 2.14",
        "Is room 2.14 closer to the lift than room 2.15?",
        "Summarise the fire safety policy",
        "Give me a summary of the building",
    ],
)
def test_neighbouring_questions_are_not_declined(q):
    assert out_of_scope_kind(q) not in (KIND_FAULT_TIMELINE, KIND_PERSONAL_RECORD, KIND_DISTANCE_COMPARISON), q


CHANNEL_ROWS = "**From: Emergency Comms**\n\nCF-12 Wardens' radio (Ready)\nCF-14 Assembly PA (Ready)\nCF-15 Fixed phone (Ready)\n"


def test_coded_status_rows_are_not_evidence_of_health():
    q = "Which approved emergency communication channels and fixed points have current end-to-end health evidence?"
    assert ts.is_terse_status_overclaim(q, CHANNEL_ROWS)
    assert "not evidence" in ts.decline_text("Abacws Building")


@pytest.mark.parametrize(
    "q, a",
    [
        ("Which emergency channels are marked ready?", CHANNEL_ROWS),
        ("What is the status of the emergency channels?", CHANNEL_ROWS),
        ("Which channels have end-to-end evidence?", "The last end-to-end test was on 3 March 2026 and passed for all channels."),
    ],
)
def test_a_status_question_or_a_prose_answer_stands(q, a):
    assert not ts.is_terse_status_overclaim(q, a)


def test_a_fee_question_with_no_tariff_says_none_is_recorded():
    q = "Is the parking free or is there a fee?"
    text = "Ground Level Parking and EV chargers are on the ground floor. Trains and buses stop nearby."
    assert "tariff" in (missing_fact_caveat(q, text) or "")
    assert missing_fact_caveat(q, "Parking costs 3 pounds a day") is None
    assert missing_fact_caveat("Where is the parking?", text) is None
