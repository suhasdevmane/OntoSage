# -*- coding: utf-8 -*-
"""Resolving a point named in prose down to the one that was asked about.

The dialogue agent names points the way a person does ("AHU01N", "Server Room
R101 Air Temperature"). Those names are not IRIs, and discarding them left the
query to a generic template that returned nothing — so the answer never reached
the timeseries.

Resolving by name brings back every point sharing that name, which for a unit
means all of its points. Answering "what is the supply air temperature" by
averaging a unit's valve outputs and setpoints together is wrong, so the
candidates are narrowed by the words of the question itself.

The two naming conventions used below come from different buildings on purpose:
nothing in the ranking may depend on either one.
"""

import pytest

from orchestrator.agents.sparql_agent import SPARQLAgent

pytestmark = pytest.mark.unit

narrow = SPARQLAgent._narrow_to_best_match

# Dotted BACnet-style names, abbreviated ("Temp").
AHU_POINTS = [
    "bldg:bldg3.AHU.AHU01N.CCV",
    "bldg:bldg3.AHU.AHU01N.Cooling_Valve_Output",
    "bldg:bldg3.AHU.AHU01N.Heating_Valve_Output",
    "bldg:bldg3.AHU.AHU01N.Outside_Air_Temp",
    "bldg:bldg3.AHU.AHU01N.Return_Air_Temp",
    "bldg:bldg3.AHU.AHU01N.Supply_Air_Temp",
    "bldg:bldg3.AHU.AHU01N.Supply_Air_Temp_Setpoint",
]

# Brick-class-style names, spelled out ("Temperature", "Sensor").
ROOM_POINTS = [
    "bldg:Air_Temperature_Sensor_R101",
    "bldg:CO2_Level_Sensor_R101",
    "bldg:Relative_Humidity_Sensor_R101",
    "bldg:Electrical_Power_Sensor_R101",
]


@pytest.mark.parametrize(
    "query,expected",
    [
        ("What is the supply air temperature of AHU01N?", "bldg:bldg3.AHU.AHU01N.Supply_Air_Temp"),
        ("What is the return air temperature of AHU01N?", "bldg:bldg3.AHU.AHU01N.Return_Air_Temp"),
        ("What is the outside air temp at AHU01N?", "bldg:bldg3.AHU.AHU01N.Outside_Air_Temp"),
    ],
)
def test_abbreviated_names_resolve_to_the_measurement_asked_for(query, expected):
    assert narrow(AHU_POINTS, query) == [expected]


@pytest.mark.parametrize(
    "query,expected",
    [
        ("What is the current air temperature in R101?", "bldg:Air_Temperature_Sensor_R101"),
        ("What is the CO2 level in R101?", "bldg:CO2_Level_Sensor_R101"),
        ("How humid is R101?", "bldg:Relative_Humidity_Sensor_R101"),
    ],
)
def test_spelled_out_names_resolve_to_the_measurement_asked_for(query, expected):
    assert narrow(ROOM_POINTS, query) == [expected]


def test_a_setpoint_does_not_displace_the_reading():
    got = narrow(AHU_POINTS, "What is the supply air temperature of AHU01N?")
    assert "bldg:bldg3.AHU.AHU01N.Supply_Air_Temp_Setpoint" not in got


@pytest.mark.parametrize(
    "query",
    [
        "Show me everything about AHU01N",
        "What points does AHU01N have?",
        "AHU01N",
    ],
)
def test_a_question_naming_no_measurement_keeps_every_point(query):
    assert narrow(AHU_POINTS, query) == AHU_POINTS


def test_unrelated_question_keeps_every_candidate():
    assert narrow(AHU_POINTS, "how is the weather today") == AHU_POINTS


@pytest.mark.parametrize("degenerate", [[], ["bldg:Only_One"]])
def test_degenerate_candidate_lists_pass_through(degenerate):
    assert narrow(degenerate, "supply air temperature") == degenerate


def test_missing_query_is_not_treated_as_a_filter():
    assert narrow(AHU_POINTS, "") == AHU_POINTS


# ── "is this a point?" comes from the graph, not from the name ───────────────


def _template(query, entities, ts_entities=None):
    return SPARQLAgent._template_sparql(
        SPARQLAgent.__new__(SPARQLAgent), query, entities, ts_entities
    )


def test_point_named_without_the_word_sensor_still_gets_its_timeseries():
    """A BACnet-style name carries no "Sensor"/"Point" token.

    Judging by the name sent these entities to the class-level template, which
    answers about every sensor of that class — so "the supply air temperature of
    AHU01N" came back as the mean of dozens of unrelated sensors.
    """
    ent = "bldg:bldg3.AHU.AHU01N.Supply_Air_Temp"
    sql = _template("what is the supply air temperature of AHU01N?", [ent], {ent})

    assert sql is not None
    assert ent in sql, "the query must be scoped to the resolved point"
    assert "ref:hasTimeseriesId ?uuid" in sql, "it must select the timeseries id"
    assert "rdf:type brick:" not in sql, "it must not fall back to a whole-class query"


def test_name_containing_sensor_still_works_without_graph_confirmation():
    ent = "bldg:Air_Temperature_Sensor_R101"
    sql = _template("what is the current air temperature in R101?", [ent], set())
    assert sql is not None and ent in sql
    assert "ref:hasTimeseriesId ?uuid" in sql


# ── a number is the whole of what distinguishes one floor from another ──────

FLOORS = ["bldg:floor0", "bldg:floor1", "bldg:floor2", "bldg:floor3"]
FLOORS_SEPARATED = ["bldg:Floor_0", "bldg:Floor_1", "bldg:Floor_2", "bldg:Floor_3"]


@pytest.mark.parametrize("floors", [FLOORS, FLOORS_SEPARATED])
@pytest.mark.parametrize("n", [0, 1, 2, 3])
def test_a_floor_reference_resolves_to_that_floor_alone(floors, n):
    """Written without a separator ("floor2") the name is one opaque token, so
    every floor used to score identically and a question about one floor
    matched all of them — the count came back building-wide or empty."""
    got = narrow(floors, f"how many rooms are on floor {n}?")
    assert len(got) == 1 and got[0].lower().endswith(str(n))


def test_a_question_naming_no_floor_keeps_every_floor():
    assert narrow(FLOORS, "list the floors in this building") == FLOORS


def test_tokens_split_letter_and_digit_runs():
    assert SPARQLAgent._name_tokens("floor2") == ["floor", "2"]
    assert SPARQLAgent._name_tokens("AHU01N") == ["ahu", "01"]
    assert SPARQLAgent._name_tokens("Supply_Air_Temp") == ["supply", "air", "temp"]
