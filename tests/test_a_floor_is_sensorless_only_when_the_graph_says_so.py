# -*- coding: utf-8 -*-
"""A floor is said to have no sensor only when the GRAPH says so (BUG-881's shape, 2026-10-02).

MEASURED live, occupant01 on /v1: "Are the CO2 levels normal?" -> "Based on 8 CO2 sensors on
1 floor ... This building records CO2 on one floor only (Floor 5); the other 5 floors have no
sensor of this kind." The graph holds 280 CO2 points with a timeseries across the floors; the
lane had been handed eight, through a 40-candidate template fetch, and inferred the absence of
the rest from what it was handed. Absence on a floor is a fact only the graph can state.
"""

import pytest

from orchestrator.services import aggregate_support as sup

pytestmark = pytest.mark.unit

ALL = ["0", "1", "2", "3", "4", "5"]


class TestTheNote:
    def test_floors_the_graph_shows_empty_are_said_to_be_empty(self):
        note = sup.missing_floors_note(ALL, ["5"], "CO2", floors_with_sensor=["5"])
        assert "records no CO2 sensor on Floor 0, Floor 1, Floor 2, Floor 3 and Floor 4" in note
        assert "not in this read" not in note

    def test_floors_the_graph_shows_populated_are_said_to_be_unread(self):
        note = sup.missing_floors_note(ALL, ["5"], "CO2", floors_with_sensor=ALL)
        assert "also record CO2, but those sensors were not in this read" in note
        assert "no CO2 sensor" not in note

    def test_both_kinds_in_one_sentence_pair(self):
        note = sup.missing_floors_note(ALL, ["5"], "CO2", floors_with_sensor=["3", "4", "5"])
        assert "records no CO2 sensor on Floor 0, Floor 1 and Floor 2" in note
        assert "Floor 3 and Floor 4 also record CO2" in note

    def test_without_a_graph_answer_nothing_is_claimed_about_sensors(self):
        note = sup.missing_floors_note(ALL, ["5"], "CO2", floors_with_sensor=None)
        assert "sensor" not in note
        assert "No figure for" in note

    def test_every_floor_present_means_no_note(self):
        assert sup.missing_floors_note(ALL, ALL, "CO2", floors_with_sensor=ALL) == ""


class TestTheQuery:
    def test_it_asks_for_the_classes_by_local_name_along_the_stated_path(self):
        q = sup.build_floors_with_class_query(["CO2_Level_Sensor", "CO2_Sensor"])
        assert '"CO2_Level_Sensor" "CO2_Sensor"' in q
        assert "brick:hasLocation|brick:isPointOf|brick:isPartOf ?space" in q
        assert "?space brick:isPartOf* ?f" in q
        assert "?f a brick:Floor" in q

    def test_an_unsafe_class_name_is_dropped(self):
        q = sup.build_floors_with_class_query(['x" } DROP', "CO2_Sensor"])
        assert "DROP" not in q and '"CO2_Sensor"' in q


class TestTheLaneAsksFirst:
    def test_the_one_floor_claim_requires_the_graphs_agreement(self):
        import inspect

        from orchestrator.services import aggregate_lane

        src = inspect.getsource(aggregate_lane)
        i = src.index("on one floor only")
        guard = src[i - 700 : i]
        assert "floors_with is not None" in guard
        assert "set(floors_with) <= {str(ranked[0].key)}" in guard
