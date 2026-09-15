# -*- coding: utf-8 -*-
"""BUG-562: a room's modality comes from the room, never from the plant that feeds it."""

import asyncio

import pytest

from orchestrator.services.deliberation.coverage_audit import (
    CoverageAuditor,
    ModalitySpec,
    SpaceCoverage,
)

pytestmark = pytest.mark.unit

TEMP = ModalitySpec(name="temperature", brick_classes=["Temperature_Sensor",
                    "Air_Temperature_Sensor", "Return_Air_Temperature_Sensor",
                    "Zone_Air_Temperature_Sensor"])


def _auditor(points):
    a = CoverageAuditor(sparql_exec=None, modalities=[TEMP], fresh_uuids=None)

    async def _spaces(ns):
        return [SpaceCoverage(space_iri="x#Room5.01", label="Room 5.01", floor="Floor5")]

    async def _points(ns):
        return points

    a.discover_spaces = _spaces
    a.discover_points = _points
    return a


def _p(sensor, cls, via, uuid):
    return {"sensor": sensor, "class_local": cls, "space": "x#Room5.01", "text": sensor,
            "uuid": uuid, "stored_at": "t", "simulated": "", "via": via}


def test_an_air_handlers_return_temperature_never_stands_for_the_room():
    ahu = _p("x#AHU_F5_Return_Air_Temperature", "Return_Air_Temperature_Sensor", "feeds", "ahu")
    [space] = asyncio.run(_auditor([ahu]).audit("x#"))
    assert space.modalities["temperature"]["uuid"] == ""


def test_the_rooms_own_sensor_wins_over_equipment_even_if_listed_later():
    ahu = _p("x#AHU_F5_Return_Air_Temperature", "Air_Temperature_Sensor", "equipment", "ahu")
    room = _p("x#Air_Temperature_Sensor_5.01", "Air_Temperature_Sensor", "direct", "room")
    [space] = asyncio.run(_auditor([ahu, room]).audit("x#"))
    assert space.modalities["temperature"]["uuid"] == "room"


def test_a_zone_sensor_on_a_feeding_vav_still_counts():
    vav = _p("x#VAV_501_Zone_Air_Temp", "Zone_Air_Temperature_Sensor", "feeds", "vav")
    [space] = asyncio.run(_auditor([vav]).audit("x#"))
    assert space.modalities["temperature"]["uuid"] == "vav"
