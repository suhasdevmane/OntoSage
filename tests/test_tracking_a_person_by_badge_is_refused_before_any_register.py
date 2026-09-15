# -*- coding: utf-8 -*-
"""BUG-553: badge and access-history tracking of a person is refused, before any register."""

import inspect

import pytest

from orchestrator.services.privacy.inference_classes import classify_inference

pytestmark = pytest.mark.unit


@pytest.mark.parametrize(
    "question",
    [
        "Can my manager see when I badge in and out?",
        "Who badged into room 2.01 last night?",
        "Can security see my access history?",
        "Show me her door access logs",
        "when did staff swipe out yesterday",
    ],
)
def test_tracking_a_person_through_access_control_is_an_individual_pattern(question):
    assert classify_inference(question) == "individual_pattern"


@pytest.mark.parametrize(
    "question",
    [
        "how many people entered through the main entrance today?",
        "how many badge readers are there?",
        "Which access groups control the main entrance?",
        "who can badge into the lab?",
        "Is the badge reader on floor 2 working?",
        "Which permission groups are orphaned because no current owner can be evidenced?",
    ],
)
def test_entitlement_inventory_and_aggregates_are_not_refused(question):
    assert classify_inference(question) is None


def test_the_register_short_circuit_yields_to_the_privacy_rule():
    from orchestrator.agents import dialogue_agent

    src = inspect.getsource(dialogue_agent)
    block = src[src.index("_held_record = held_record_class"):src.index("[ttl-route] metadata via held record class")]
    assert "not classify_inference(user_query" in block


# BUG-557 — a ranking by a measured condition goes to deliberation, not a register.


@pytest.mark.parametrize(
    "question, hands_over",
    [
        ("I'm pregnant and overheating - where's the coolest place to work today?", True),
        ("which room is warmest?", True),
        ("Where can I sit with the freshest air this afternoon?", True),
        ("Where can I work for three hours with power, good Wi-Fi and a low risk of noise?", False),
        ("where is the quietest room right now?", False),
        ("Which bookable rooms are suitable for a confidential call?", False),
    ],
)
def test_only_measured_conditions_hand_a_ranking_to_deliberation(question, hands_over):
    from orchestrator.agents.dialogue_agent import _MEASURED_CONDITION_RE
    from orchestrator.services.routing_contract import DELIBERATE_RE

    got = bool(DELIBERATE_RE.search(question) and _MEASURED_CONDITION_RE.search(question))
    assert got is hands_over


def test_the_register_short_circuit_yields_to_a_measured_ranking():
    from orchestrator.agents import dialogue_agent

    src = inspect.getsource(dialogue_agent)
    block = src[src.index("_held_record = held_record_class"):src.index("[ttl-route] metadata via held record class")]
    assert "and not _ranks_by_measurement" in block
