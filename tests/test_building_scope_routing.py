# -*- coding: utf-8 -*-
"""A question about this building must never be answered open-domain (BUG-123).

The open-domain answerer has no sensors and no way to know it lacks any, so when a
building question reaches it the plausible completion is an invented reading.
Observed live: "Is it stuffy in RM157?" came back as "humidity around 45% and CO2
near 800 ppm" for a room that has neither sensor.

Lay-term resolution is the signal that separates the two cases — "stuffy" is not a
measurement word, so no keyword list can tell the reading question from the
vocabulary one. The detector therefore requires BOTH a resolved measurand and a
reference to this building, which is what keeps genuine general knowledge working.

Nothing here may name a building: the same rules route every building.
"""

import pytest

from orchestrator.services.grounding_guard import has_measurand_concept, is_building_specific
from orchestrator.services.routing_contract import apply_contract

pytestmark = pytest.mark.unit

# An HBCO match whose concept maps to a measurable point.
SENSOR_CONCEPT = [{"concept_id": "stuffiness", "brick_classes": ["brick:CO2_Level_Sensor"]}]
# A concept that resolves but measures nothing (e.g. a policy topic).
NON_SENSOR_CONCEPT = [{"concept_id": "policy", "brick_classes": []}]


# ── the detector ─────────────────────────────────────────────────────────────


@pytest.mark.parametrize(
    "query",
    [
        "Is it stuffy in RM157?",
        "is it too warm in room 5.01?",
        "how is the air in zone 3?",
        "is it stuffy in this building?",
        "does it feel cold in here?",
        "is it too humid on floor 2?",
        "Is it too warm?",
    ],
)
def test_a_measurand_plus_this_building_is_building_specific(query):
    assert is_building_specific(query, SENSOR_CONCEPT) is True


@pytest.mark.parametrize(
    "query",
    [
        "what is stuffiness?",
        "what does CO2 measure?",
        "why does poor ventilation cause drowsiness?",
        "what is a VAV box?",
        "explain thermal comfort",
    ],
)
def test_a_definition_question_stays_general(query):
    assert is_building_specific(query, SENSOR_CONCEPT) is False


def test_no_measurand_means_not_a_reading_question():
    """A place alone is not enough — "where is room 5.01" is navigation."""
    assert is_building_specific("where is room 5.01?", NON_SENSOR_CONCEPT) is False
    assert is_building_specific("where is room 5.01?", []) is False
    assert is_building_specific("where is room 5.01?", None) is False


@pytest.mark.parametrize("blank", ["", "   ", None])
def test_blank_query_is_not_building_specific(blank):
    assert is_building_specific(blank, SENSOR_CONCEPT) is False


def test_measurand_detection_accepts_dicts_and_objects():
    class _C:
        brick_classes = ["brick:Air_Temperature_Sensor"]

    assert has_measurand_concept([_C()]) is True
    assert has_measurand_concept(SENSOR_CONCEPT) is True
    assert has_measurand_concept(NON_SENSOR_CONCEPT) is False
    assert has_measurand_concept([]) is False


# ── the routing rule ─────────────────────────────────────────────────────────


def _route(query, intent, concepts):
    state = {"intent": intent, "concepts": concepts, "entities": []}
    applied = apply_contract(query, state, stage="concept")
    return state["intent"], applied


@pytest.mark.parametrize("intent", ["general", "general_knowledge", "clarification", "greeting"])
def test_building_question_is_pulled_out_of_the_open_domain_answerer(intent):
    got, applied = _route("Is it stuffy in RM157?", intent, SENSOR_CONCEPT)
    assert got == "analytics"
    assert "building_question_not_general" in applied


def test_the_rule_sets_analytics_so_the_data_path_actually_runs():
    state = {"intent": "general", "concepts": SENSOR_CONCEPT, "entities": []}
    apply_contract("Is it stuffy in RM157?", state, stage="concept")
    assert state["analytics"] is True
    assert state["general"] is False


def test_a_genuine_general_question_is_left_alone():
    got, applied = _route("What is a VAV box?", "general", SENSOR_CONCEPT)
    assert got == "general"
    assert applied == []


@pytest.mark.parametrize("intent", ["sensor_data", "analytics", "metadata", "floor_plan"])
def test_a_confident_data_classification_is_never_stomped(intent):
    got, applied = _route("Is it stuffy in RM157?", intent, SENSOR_CONCEPT)
    assert got == intent
    assert applied == []


def test_rule_is_inert_without_lay_term_resolution():
    """With the concept ontology unloaded there is no measurand, so nothing fires —
    the rule degrades to the previous behaviour rather than mis-routing."""
    got, applied = _route("Is it stuffy in RM157?", "general", [])
    assert got == "general"
    assert applied == []


def test_no_building_literals_in_the_contract():
    import inspect

    import orchestrator.services.routing_contract as rc

    src = inspect.getsource(rc).lower()
    for literal in ("bldg1", "bldg2", "bldg3", "abacws", "buildsys"):
        assert literal not in src, f"routing contract must not name a building: {literal}"
