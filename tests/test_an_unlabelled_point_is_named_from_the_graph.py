"""A data answer names its points even when the generated query returned only their ids.

Bank sample M1 (2026-10-11): ten waste-bin series narrated as "Series 1 ... Series 10" with every
unit "not recorded", while each bin's label says "(percent full)" and its class declares percent.
"""

from __future__ import annotations

import pytest

from orchestrator.workflow import _orchestrator as orch

pytestmark = pytest.mark.unit

U1 = "67d1a32f-2e7f-50f8-9baa-26ec9f028e96"
OS = "http://ontosage.org/capabilities#"
BRICK = "https://brickschema.org/schema/Brick#"


def _b(uuid, type_iri, label="Room 4.70 general waste bin fill (percent full)"):
    return {
        "uuid": {"value": uuid},
        "sensor": {"value": "http://example.org/b#Bin_Fill"},
        "label": {"value": label},
        "type": {"value": type_iri},
    }


def test_the_query_asks_for_exactly_the_ids_and_drops_anything_else():
    q = orch._point_lookup_query([U1, 'x" } DROP'])
    assert f'"{U1}"' in q and "DROP" not in q
    assert "?sensor ref:hasExternalReference/ref:hasTimeseriesId ?uuid" in q


def test_the_most_specific_class_is_kept_one_binding_per_id():
    rows = [_b(U1, BRICK + "Sensor"), _b(U1, BRICK + "Point"), _b(U1, OS + "Waste_Fill_Sensor")]
    (kept,) = orch._most_specific_bindings(rows)
    assert kept["type"]["value"].endswith("Waste_Fill_Sensor")


def test_the_builder_names_the_point_and_finds_its_unit():
    agent = orch.WorkflowOrchestrator.__new__(orch.WorkflowOrchestrator)
    meta = agent._build_sensor_metadata_from_bindings(
        orch._most_specific_bindings([_b(U1, OS + "Waste_Fill_Sensor")])
    )
    assert meta[U1]["label"].startswith("Room 4.70 general waste bin fill")
    assert meta[U1]["unit"] in ("%", "percent")
