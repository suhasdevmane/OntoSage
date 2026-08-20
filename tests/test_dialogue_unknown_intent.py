# -*- coding: utf-8 -*-
"""An intent name no registry defines must not survive as a classification.

Observed live: the model answered with the literal intent "failure". It parses
cleanly, so nothing downstream treats it as an error -- but it matches no route,
and it is not in the WEAK set the routing contract is permitted to override. The
question therefore skipped every deterministic rule and fell through to the
default data lane, so "what is the area of room 3.50" was answered out of sensor
counts while the floor plan held that room's measured 8.87 m2.

Demoting an undefined intent to "general" restores the ordinary unclassified
path: the contract gets its chance, and the result is marked classification_failed
so one bad completion cannot pin a wrong route to the question for a whole hour.
"""

import json

import pytest

from orchestrator.agents.dialogue_agent import DialogueAgent
from orchestrator.intents.registry import get_intent_registry

pytestmark = pytest.mark.unit


def _parse(intent_name, query="What is the area of room 3.50?"):
    agent = DialogueAgent.__new__(DialogueAgent)
    payload = json.dumps(
        {
            "intent": intent_name,
            "entities": [],
            "required_analytics": [],
            "explanation": "test",
        }
    )
    return agent._parse_llm_response(payload, query, None)


def test_the_observed_failure_intent_is_demoted():
    out = _parse("failure")

    assert out["intent"] != "failure"
    assert out.get("classification_failed") is True


def test_a_demoted_intent_still_reaches_the_routing_contract():
    """The whole point: the deterministic rules must get their chance."""
    out = _parse("failure", "What is the area of room 3.50?")

    # room_geometry_spatial claims weak intents, so the demotion hands this
    # question to the agent that actually holds the geometry.
    assert out["intent"] == "spatial_query"


@pytest.mark.parametrize("bogus", ["failure", "unknown", "n/a", "SomeMadeUpIntent", "error"])
def test_any_undefined_intent_is_rejected(bogus):
    out = _parse(bogus, "tell me about the building")

    assert get_intent_registry(None).resolve_name(out["intent"]) is not None


def test_a_real_intent_is_left_alone():
    """Validation must not disturb a correct classification."""
    out = _parse("sensor_data", "what is the temperature in room 3.50")

    assert out["intent"] == "sensor_data"
    assert not out.get("classification_failed")


def test_a_demoted_result_is_not_cacheable():
    """classification_failed is what stops a bad completion being pinned for the TTL."""
    assert _parse("failure").get("classification_failed") is True
    assert not _parse("sensor_data", "temperature now").get("classification_failed")
