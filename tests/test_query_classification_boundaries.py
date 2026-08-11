# -*- coding: utf-8 -*-
"""Query keyword matching must respect word boundaries.

Substring matching made ordinary questions classify wrongly, because the
keywords hide inside common words and inside buildings' own identifiers:

    "id"    inside "humidity"
    "meter" inside "parameter"
    "ahu"   inside "AHU01N"

The last one is the portability failure: asking for a reading from a named air
handler was read as a question *about equipment*, so the query returned
relationship triples with no timeseries id and the answer stopped at metadata.
"""

import pytest

from orchestrator.agents.sparql_agent import SPARQLAgent

pytestmark = pytest.mark.unit


def _classify(query: str) -> dict:
    return SPARQLAgent._classify_query(SPARQLAgent.__new__(SPARQLAgent), query.lower())


@pytest.mark.parametrize(
    "query",
    [
        "what is the supply air temperature of AHU01N?",
        "what is the return air temp for AHU02S right now?",
        "what is the diameter of the duct?",
    ],
)
def test_identifier_does_not_imply_an_equipment_question(query):
    assert _classify(query)["wants_equipment"] is False


@pytest.mark.parametrize(
    "query",
    [
        "which AHU serves room 157?",
        "list all equipment on floor 2",
        "is the chiller running?",
        "show me the air handling units",
    ],
)
def test_explicit_equipment_questions_still_match(query):
    assert _classify(query)["wants_equipment"] is True


@pytest.mark.parametrize(
    "query",
    [
        "what is the humidity in room 103?",
        "is the relative humidity too high?",
    ],
)
def test_humidity_is_not_a_request_for_an_id(query):
    assert _classify(query)["wants_uuid"] is False


@pytest.mark.parametrize(
    "query", ["what is the uuid of that sensor?", "show the sensor id", "give me the identifier"]
)
def test_explicit_id_questions_still_match(query):
    assert _classify(query)["wants_uuid"] is True


def test_matching_is_case_insensitive():
    assert _classify("Which AHU serves RM157?")["wants_equipment"] is True
