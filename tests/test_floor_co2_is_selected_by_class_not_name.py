# -*- coding: utf-8 -*-
"""A floor's CO2 points are selected and measured by their BRICK CLASS, never by their names (BUG-1442).

The owner's rule: floor membership comes from the graph, and the quantity of a point comes from the
class the graph gives it. A point's label is what a building's naming convention says, and the
earlier code read the quantity from it in two places: the floor resolver's label tier, and the
aggregate lane's vote over label text. Both are pinned out here.
"""

import pytest

from orchestrator.agents.sparql_agent import SPARQLAgent
from orchestrator.services import aggregate_lane as al

pytestmark = pytest.mark.unit

_agent = SPARQLAgent()


def test_a_floor_co2_question_selects_points_by_class_and_projects_it():
    q = _agent._floor_scoped_sparql("What is the average CO2 on floor 3?", None)
    assert q is not None
    assert "BIND(brick:CO2_Sensor AS ?metricCls)" in q
    assert "SELECT DISTINCT ?sensor ?label ?floorNum ?uuid ?storage ?metricCls" in q


def test_no_label_text_selects_a_floor_point_any_more():
    # The label tier is gone: a quantity with no class gets no floor query at all.
    assert _agent._floor_scoped_sparql("What is the AHU run-time on floor 5?", None) is None
    q = _agent._floor_scoped_sparql("What is the CO2 on floor 3?", None)
    assert "CONTAINS(LCASE(STR(?label))" not in q


def test_a_co2_class_is_co2_whatever_the_point_is_called():
    # The same class under a prefixed name, an IRI and a bare local name: one quantity.
    assert al.measurand_from_classes(["brick:CO2_Sensor"]) == "co2"
    assert (
        al.measurand_from_classes(["https://brickschema.org/schema/Brick#CO2_Level_Sensor"])
        == "co2"
    )
    assert al.measurand_from_classes(["CO2_Level_Sensor"]) == "co2"


def test_a_class_declared_by_two_modalities_says_nothing_about_the_quantity():
    # Motion_Sensor is declared by occupancy AND motion: it does not name one quantity.
    assert al.measurand_from_classes(["brick:Motion_Sensor"]) is None


def test_a_mixed_or_unknown_set_has_no_single_measurand():
    assert al.measurand_from_classes(["brick:CO2_Sensor", "brick:Temperature_Sensor"]) is None
    assert al.measurand_from_classes(["brick:Not_A_Real_Class"]) is None
    assert al.measurand_from_classes([]) is None
    assert al.measurand_from_classes([""]) is None


def test_the_majority_class_wins_and_a_tie_does_not():
    two_co2 = ["brick:CO2_Sensor", "brick:CO2_Level_Sensor", "brick:Temperature_Sensor"]
    assert al.measurand_from_classes(two_co2) == "co2"
    assert al.measurand_from_classes(["brick:CO2_Sensor", "brick:Humidity_Sensor"]) is None


def test_modality_names_map_to_the_lanes_vocabulary():
    assert al.lane_measurand("noise") == "sound"
    assert al.lane_measurand("occupancy_status") == "occupancy"
    assert al.lane_measurand("air_quality") == "air quality"
    assert al.lane_measurand("co2") == "co2"
