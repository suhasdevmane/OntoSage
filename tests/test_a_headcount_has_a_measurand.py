"""BUG-1508: a class two modalities share is split by the point's label, so a headcount is one.

"How many people are in the building right now?" bound six floor counters typed
Occupancy_Count_Sensor. That class is declared by people counts AND parking bays, so it voted for
neither, the aggregate lane had no measurand (`not claimed: measurand=None`), and the analytics
narration answered with the highest and lowest counter instead of a total. The label now splits a
shared class, by the rule `modality_units.unit_for_sensor` already applies (CAVEAT-1412).
"""

from __future__ import annotations

import pytest

from orchestrator.services.aggregate_lane import measurand_from_classes

pytestmark = pytest.mark.unit

B = "https://brickschema.org/schema/Brick#"


def test_floor_counters_are_people():
    labels = [f"Entry Count Sensor - Floor {n}" for n in range(1, 6)]
    assert measurand_from_classes([B + "Occupancy_Count_Sensor"] * 5, labels=labels) == "occupancy"


def test_a_parking_label_is_parking_not_people():
    got = measurand_from_classes(
        [B + "Occupancy_Count_Sensor"], labels=["Free parking bays - car park"]
    )
    assert got and "parking" in got


def test_without_labels_a_shared_class_still_votes_for_neither():
    assert measurand_from_classes([B + "Occupancy_Count_Sensor"]) is None


def test_an_unshared_class_is_unchanged():
    assert measurand_from_classes([B + "CO2_Level_Sensor"], labels=["anything"]) == "co2"
