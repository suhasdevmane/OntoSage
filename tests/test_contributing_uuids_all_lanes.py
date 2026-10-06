"""D12 — contributing_uuids is the one reader of the timeseries ids behind an answer.

A turn whose SQL lane put sensor_metadata on the bus must yield those ids, a deliberation turn
must yield the dossier's sensor_uuid rows, and a turn with neither must yield []. Nothing here
promotes a gate: the spatial grader still only reads through this function.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from orchestrator.services.evidence.assemble import contributing_uuids

pytestmark = pytest.mark.unit

UUID_A = "11111111-aaaa-0000-0000-000000000001"
UUID_B = "11111111-aaaa-0000-0000-000000000002"
UUID_C = "11111111-bbbb-0000-0000-000000000003"


def test_sql_lane_sensor_metadata_yields_its_uuids():
    results = {
        "sql_result": {"success": True, "results": {"data": []}},
        "sensor_metadata": {
            UUID_A: {"label": "Room 1.04 CO2", "kind": "co2"},
            UUID_B: {"label": "Room 1.04 temperature", "kind": "temperature"},
        },
    }
    assert contributing_uuids(results) == [UUID_A, UUID_B]


def test_a_turn_with_no_sensor_binding_yields_an_empty_list():
    assert contributing_uuids({}) == []
    assert contributing_uuids({"sql_result": {"success": False}}) == []
    assert contributing_uuids({"evidence_dossier": {"evidence": []}}) == []


def test_deliberation_dossier_uuids_are_read_without_sensor_metadata():
    """The deliberation lane never writes sensor_metadata. Its dossier rows carry the uuids."""
    results = {
        "evidence_dossier": {
            "evidence": [
                {"sensor_uuid": UUID_A, "stored_at": "sensordb.sensor_data"},
                {"sensor_uuid": UUID_C},
                {"sensor_uuid": None},
                "not-a-row",
            ]
        }
    }
    assert contributing_uuids(results) == [UUID_A, UUID_C]


def test_the_same_uuid_from_two_lanes_is_listed_once_in_order():
    results = {
        "sensor_metadata": {UUID_A: {}},
        "evidence_dossier": {"evidence": [{"sensor_uuid": UUID_A}, {"sensor_uuid": UUID_B}]},
    }
    assert contributing_uuids(results) == [UUID_A, UUID_B]


def test_spatial_grader_reads_through_the_single_reader():
    """_grade_spatial_adequacy must not carry its own copy of the uuid lookup."""
    src = Path("orchestrator/workflow/_orchestrator.py").read_text(encoding="utf-8")
    start = src.index("async def _grade_spatial_adequacy")
    body = src[start : start + 2000]
    assert "contributing_uuids(results)" in body
