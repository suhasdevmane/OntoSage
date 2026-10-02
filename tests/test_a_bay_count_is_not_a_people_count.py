# -*- coding: utf-8 -*-
"""The most specific matching modality names a sensor's unit (CAVEAT-1412).

Live 2026-10-02: "1 free parking spot (reported by the sensor building parking_free [bays],
unit people) ... the average number of free spots was 2.78 people". The parking modality
declares "bays"; `unit_for_sensor` took the FIRST spec that matched, and the generic occupancy
entry ("persons"), listed earlier, shares Occupancy_Count_Sensor with it. Synthetic specs below:
no building's config is read.
"""

import pytest

from orchestrator.services import modality_units as mu
from orchestrator.services.deliberation.coverage_audit import ModalitySpec

pytestmark = pytest.mark.unit

SPECS = [
    ModalitySpec(
        name="occupancy", brick_classes=["Occupancy_Count_Sensor"], sat={"unit": "persons"}
    ),
    ModalitySpec(
        name="parking_free",
        brick_classes=["Parking_Occupancy_Sensor", "Occupancy_Count_Sensor"],
        label_contains=["parking"],
        sat={"unit": "bays"},
    ),
    ModalitySpec(name="temperature", brick_classes=["Temperature_Sensor"], sat={"unit": "degC"}),
]


@pytest.fixture(autouse=True)
def _specs(monkeypatch):
    import orchestrator.services.deliberation.coverage_audit as ca

    monkeypatch.setattr(ca, "load_modalities", lambda building_id=None, config_path=None: SPECS)


def test_a_parking_point_is_counted_in_bays():
    assert (
        mu.unit_for_sensor("brick:Occupancy_Count_Sensor", "building parking_free [bays]") == "bays"
    )


def test_a_room_counter_is_still_people():
    unit = mu.unit_for_sensor("brick:Occupancy_Count_Sensor", "Room 1.06 occupancy")
    assert unit in ("persons", "people")


def test_an_unrelated_class_is_unchanged():
    assert mu.unit_for_sensor("brick:Temperature_Sensor", "Room 1.06 temperature") in ("degC", "°C")
