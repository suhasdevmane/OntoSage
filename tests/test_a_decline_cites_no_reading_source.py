# -*- coding: utf-8 -*-
"""An answer that states no figure cites no sensing system as a source (BUG-1401, Sources half).

Live 2026-10-01: "there is no air-pressure sensor recorded for Room 2.01 ... *Sources:
`Building model` `Sensor data` `Lighting Sensing System` `Acoustic Sensing System` `Occupancy
Sensing System`*" -- three sensing systems cited under a conclusion drawn from the absence of
readings. Measured over 2,554 stored answers before landing: 322 cite a sensing or metering
system, 12 state no figure, and all 12 are declines.
"""

import pytest

from orchestrator.services import provenance as prov
from shared.models import ProvenanceTag

pytestmark = pytest.mark.unit

MODEL = ProvenanceTag(source_id="ontology", label="Building model", store="graphdb")
OCC = ProvenanceTag(
    source_id="occupancy", label="Occupancy Sensing System", store="mysql:occupancy_data"
)
LIVE = ProvenanceTag(source_id="live_sensors", label="Sensor data", store="mysql")
ANALYTICS = ProvenanceTag(source_id="analytics", label="Analytics Engine", store="compute")
DOCS = ProvenanceTag(source_id="documents", label="Documents", store="qdrant")


def test_a_decline_keeps_only_the_model_and_the_documents():
    out = prov.tags_for_answer(
        [MODEL, LIVE, OCC, ANALYTICS, DOCS], "I don't have an air-pressure reading for Room 2.01."
    )
    assert [t.label for t in out] == ["Building model", "Documents"]


def test_an_answer_with_a_figure_keeps_every_source():
    out = prov.tags_for_answer(
        [MODEL, OCC, ANALYTICS], "Occupancy averaged 13 persons across 40 rooms."
    )
    assert [t.label for t in out] == [
        "Building model",
        "Occupancy Sensing System",
        "Analytics Engine",
    ]


def test_a_two_decimal_reading_is_a_figure():
    """29.81 is a flow rate, not a room number; the note and the sources stay."""
    out = prov.tags_for_answer([MODEL, OCC], "Floor 4 flow rate has the highest mean of 29.81.")
    assert len(out) == 2


def test_it_is_wired_into_the_response_node():
    import inspect

    from orchestrator.workflow import _orchestrator

    src = inspect.getsource(_orchestrator)
    assert "_prov.tags_for_answer(_tags, final_response)" in src
