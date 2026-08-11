# -*- coding: utf-8 -*-
"""A reading question must bypass the capability probe — vocabulary gaps break that.

TODO-133. The capability probe is deliberately bypassed for data questions via
``is_data_query``, whose measurand vocabulary is generic domain English. "air
quality" was missing from it, so "What is the air quality on floor 1?" failed the
bypass, lay-term-matched a capability topic, and a plainly answerable data question
was routed to capability and honestly declined — on a building whose LARGEST sensor
class is Air_Quality_Sensor (523 instances).

The words added are measurand vocabulary (what buildings measure), never a
building's own naming — the same list serves every building.
"""

from __future__ import annotations

import pytest

from orchestrator.services.plausibility import measurand_of
from orchestrator.services.semantic_router import SemanticRouter

pytestmark = pytest.mark.unit


@pytest.mark.parametrize(
    "query",
    [
        "What is the air quality on floor 1?",
        "what is the AQI in room 3.02?",
        "show me the IAQ on floor 2",
        "What is the temperature on floor 3?",
        "co2 in room 5.01",
    ],
)
def test_a_place_plus_measurand_is_a_data_query(query):
    assert SemanticRouter.is_data_query(query) is True


@pytest.mark.parametrize(
    "query",
    [
        "Is there a cafe in this building?",
        "Where is the prayer room?",
        "What is the wifi policy?",
        "How do I book a room?",
    ],
)
def test_capability_questions_are_not_hijacked_by_the_bypass(query):
    """The bypass must stay precise — widening it to swallow amenity questions
    would just move the misrouting to the other side."""
    assert SemanticRouter.is_data_query(query) is False


def test_air_quality_is_recognised_as_a_measurand():
    """This is what lets the capability door treat an air-quality question about a
    named place as a READING request and run the referent gate on it."""
    assert measurand_of("what is the air quality in the swimming pool?") == "air quality"
    assert measurand_of("what is the AQI here?") == "air quality"


def test_the_vocabulary_names_no_building():
    import inspect

    from orchestrator.services import semantic_router as sr

    src = inspect.getsource(sr).lower()
    for literal in ("bldg1", "bldg2", "bldg3", "abacws", "buildsys", "cardiff"):
        assert literal not in src, f"semantic router must not name a building: {literal}"
