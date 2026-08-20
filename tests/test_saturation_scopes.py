# -*- coding: utf-8 -*-
"""V5-T09: scoped saturation (floor/building) + new signal kinds."""

from datetime import datetime

import pytest

from orchestrator.services.deliberation.coverage_audit import (
    ModalitySpec,
    SpaceCoverage,
)
from orchestrator.services.deliberation.saturation import plan_saturation
from orchestrator.services.deliberation.synthetic_signals import (
    STEP_MINUTES,
    generate_room_day,
    occupancy_series,
)

pytestmark = pytest.mark.unit

NS = "http://example.org/tb#"


def _spaces():
    out = []
    for floor, rooms in (("Floor0", ["R001", "R002"]), ("Floor1", ["R101"])):
        for r in rooms:
            sc = SpaceCoverage(space_iri=f"{NS}{r}")
            sc.label = r
            sc.floor = floor
            sc.modalities = {"pm25": {"status": "missing"}}  # audited room-scope gap
            out.append(sc)
    return out


def _specs():
    return [
        ModalitySpec(
            "pm25",
            ["PM2.5_Level_Sensor"],
            sat={"brick_class": "PM2.5_Level_Sensor", "table": "pm25_data", "unit": "ug/m3"},
        ),
        ModalitySpec(
            "energy_submeter",
            ["Electrical_Meter"],
            sat={
                "brick_class": "Electrical_Meter",
                "table": "submeter_data",
                "unit": "kWh",
                "scope": "floor",
            },
        ),
        ModalitySpec(
            "parking_free",
            ["Occupancy_Count_Sensor"],
            sat={
                "brick_class": "Occupancy_Count_Sensor",
                "table": "parking_data",
                "unit": "bays",
                "scope": "building",
            },
        ),
    ]


def test_room_scope_provisions_per_gap_floor_scope_per_floor_building_once():
    spaces = _spaces()
    plan = plan_saturation("tb", NS, spaces, _specs(), building_iri=f"{NS}TheBuilding")
    assert len(plan["pm25"]) == 3  # per room (all gaps)
    assert len(plan["energy_submeter"]) == 2  # one per distinct floor
    assert len(plan["parking_free"]) == 1  # one per building
    floors = {i.space_iri for i in plan["energy_submeter"]}
    assert floors == {f"{NS}Floor0", f"{NS}Floor1"}
    assert plan["parking_free"][0].space_iri == f"{NS}TheBuilding"
    assert plan["parking_free"][0].sensor_iri.endswith("building_sat_parking_free")


def test_building_scope_falls_back_to_namespace_when_no_entity():
    plan = plan_saturation("tb", NS, _spaces(), _specs(), building_iri=None)
    assert plan["parking_free"][0].space_iri == f"{NS}Building"


def test_scoped_modalities_deterministic_uuids():
    p1 = plan_saturation("tb", NS, _spaces(), _specs(), building_iri=f"{NS}B")
    p2 = plan_saturation("tb", NS, _spaces(), _specs(), building_iri=f"{NS}B")
    assert [i.uuid for i in p1["energy_submeter"]] == [i.uuid for i in p2["energy_submeter"]]


def test_new_signal_kinds_bounded_and_deterministic():
    day = datetime(2026, 8, 12)
    kinds = ["pm25", "energy_submeter", "water_flow", "parking_free"]
    a = generate_room_day("tb", "Floor0", kinds, day)
    b = generate_room_day("tb", "Floor0", kinds, day)
    assert a == b
    steps = (24 * 60) // STEP_MINUTES
    for k in kinds:
        assert len(a[k]) == steps
    assert all(v >= 2.0 for v in a["pm25"])
    assert all(v >= 0.5 for v in a["energy_submeter"])
    assert all(v >= 0.0 for v in a["water_flow"])
    assert all(0.0 <= v <= 62.0 for v in a["parking_free"])


def test_occupied_hours_raise_pm25():
    day = datetime(2026, 8, 12)  # a Wednesday
    steps = (24 * 60) // STEP_MINUTES
    occ = occupancy_series("tb", "R001", day, steps)
    vals = generate_room_day("tb", "R001", ["pm25"], day)["pm25"]
    busy = [v for v, o in zip(vals, occ) if o >= 2]
    empty = [v for v, o in zip(vals, occ) if o == 0]
    assert busy and empty
    assert sum(busy) / len(busy) > sum(empty) / len(empty)
