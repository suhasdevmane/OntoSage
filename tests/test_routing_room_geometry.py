# -*- coding: utf-8 -*-
"""A question about a room's SIZE belongs to the floor plan, not the capability KB.

The classifier reads "what is the area of room 0.34" as a capability lookup,
which answers that it has no information on record -- while the floor-plan
manifest holds that room's measured 195 m2. A false "I don't have that" is a
particularly bad failure: it tells the user to go add data the system already
has, and it buries the geometry that surveying the building's plans produced.
"""

import pytest

from orchestrator.services import routing_contract as rc
from orchestrator.services.semantic_router import SemanticRouter

pytestmark = pytest.mark.unit


def _apply(query, intent, sr=SemanticRouter):
    """Runs against the REAL SemanticRouter — the shape test is shared with the
    capability bypass, and a stub here would let the two drift apart unnoticed."""
    ctx = rc._Ctx(query=query, ql=query.lower(), normalized={"intent": intent}, sr=sr)
    return rc._r_room_geometry_spatial(ctx)


@pytest.mark.parametrize(
    "query",
    [
        "What is the area of room 0.34?",
        "How big is room 0.34?",
        "how large is the lecture theatre",
        "what are the dimensions of office 3.12",
        "what is the size of lab 2.05",
        "how much floor space does room 1.01 have",
    ],
)
def test_room_size_questions_are_claimed_from_capability(query):
    assert _apply(query, "capability") == "spatial_query"


def test_claimed_from_a_general_classification_too():
    assert _apply("how big is room 0.34", "general") == "spatial_query"


@pytest.mark.parametrize(
    "query",
    [
        "how warm is room 0.34",
        "what is the CO2 in room 0.34",
        "how many rooms are on floor 3",
        "is room 0.34 booked this afternoon",
    ],
)
def test_non_geometry_room_questions_are_left_alone(query):
    """A reading taken INSIDE a room is not a measurement OF the room."""
    assert _apply(query, "capability") is None


@pytest.mark.parametrize("query", ["what is the total area of the building", "how big is it"])
def test_measure_without_a_space_noun_is_left_alone(query):
    assert _apply(query, "capability") is None


@pytest.mark.parametrize("intent", ["sensor_data", "analytics", "floor_plan", "control"])
def test_a_confident_classification_is_never_overridden(intent):
    """Only weak intents are claimed — this rule breaks no working route."""
    assert _apply("what is the area of room 0.34", intent) is None


def test_a_control_command_is_never_claimed():
    class _Cmd(SemanticRouter):
        @staticmethod
        def is_control_command(_q):
            return True

    assert _apply("set the size of room 0.34", "capability", sr=_Cmd) is None


def test_the_capability_bypass_agrees_with_the_routing_rule():
    """One predicate, two consumers — they must never disagree again."""
    for q in [
        "What is the area of room 0.34?",
        "How big is room 0.34?",
        "what are the dimensions of office 3.12",
    ]:
        assert SemanticRouter.is_spatial_query(q), q
        assert _apply(q, "capability") == "spatial_query", q
