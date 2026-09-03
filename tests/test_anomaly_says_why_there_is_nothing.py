# -*- coding: utf-8 -*-
"""A refusal should describe the building, not the lane's internals (CAVEAT-396).

Measured live: "Is there a Voltage fluctuation that could put our hardware at risk?" returned

    "No sensor data available for anomaly detection."

The refusal is CORRECT — bldg1 has no voltage sensors — but that sentence describes the
detector's input, and to a reader it sounds like a temporary outage worth waiting out. The
honest version is a fact about the building, and it is also the only version that tells them
what to do about it.

The distinction that matters: NOTHING RESOLVED is a different situation from points that
resolved and returned no rows. The first means the building does not instrument that
quantity; the second means the readings are not loaded. They have different remedies, so
only the first is rewritten and the detector's own wording is left alone for the second.
"""

import pytest

from orchestrator.workflow._orchestrator import (
    _quantity_asked_about,
    _resolved_point_count,
)

pytestmark = pytest.mark.unit


class _State:
    def __init__(self, **results):
        self.intermediate_results = results


# ── what the question named ────────────────────────────────────────────────────────────


@pytest.mark.parametrize(
    "question, expected",
    [
        ("Is there a Voltage fluctuation that could put our hardware at risk?", "voltage"),
        ("are there any radon readings", "radon"),
        ("any pressure anomalies today", "pressure"),
    ],
)
def test_the_named_quantity_is_extracted(question, expected):
    assert _quantity_asked_about(question).lower() == expected


def test_an_unrecognised_shape_names_nothing_rather_than_guessing():
    """Empty is the safe answer. Matching a near modality is how "radon" gets answered
    about CO2, which is the fabrication this whole subsystem exists to prevent."""
    assert _quantity_asked_about("how is everything going") == ""


# ── nothing resolved vs nothing returned ───────────────────────────────────────────────


def test_no_points_resolved_is_zero():
    assert _resolved_point_count(_State(sparql_result={"results": {"data": []}})) == 0


def test_points_in_sensor_metadata_are_counted():
    state = _State(sensor_metadata={"uuid-a": {}, "uuid-b": {}})
    assert _resolved_point_count(state) == 2


def test_points_resolved_by_sparql_are_counted():
    state = _State(sparql_result={"results": {"data": [{"uuid": "a"}, {"uuid": "b"}]}})
    assert _resolved_point_count(state) == 2


def test_a_bare_state_counts_zero_rather_than_raising():
    class _Bare:
        pass

    assert _resolved_point_count(_Bare()) == 0


# ── the message ────────────────────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_an_uninstrumented_quantity_is_described_as_such():
    from orchestrator.workflow._orchestrator import WorkflowOrchestrator

    class _Detector:
        async def detect(self, *a, **k):
            return {"success": False, "anomalies": [], "formatted_response": "No sensor data."}

    class _Msg:
        content = "Is there a Voltage fluctuation that could put our hardware at risk?"

    class _State2:
        def __init__(self):
            self.messages = [_Msg()]
            self.intermediate_results = {"sparql_result": {"results": {"data": []}}}

    orch = WorkflowOrchestrator.__new__(WorkflowOrchestrator)
    orch.anomaly_agent = _Detector()
    state = await WorkflowOrchestrator._anomaly_node(orch, _State2())
    out = state.intermediate_results["anomaly_result"]

    assert out["declined_reason"] == "modality_not_instrumented"
    assert "voltage" in out["formatted_response"].lower()
    assert "No sensor data." not in out["formatted_response"]
    assert "not a fault" in out["formatted_response"]


@pytest.mark.asyncio
async def test_points_that_resolved_keep_the_detectors_own_wording():
    """Sensors exist and returned nothing — a different problem with a different remedy."""
    from orchestrator.workflow._orchestrator import WorkflowOrchestrator

    class _Detector:
        async def detect(self, *a, **k):
            return {"success": False, "anomalies": [], "formatted_response": "No sensor data."}

    class _Msg:
        content = "any temperature anomalies"

    class _State2:
        def __init__(self):
            self.messages = [_Msg()]
            self.intermediate_results = {"sensor_metadata": {"uuid-a": {}}}

    orch = WorkflowOrchestrator.__new__(WorkflowOrchestrator)
    orch.anomaly_agent = _Detector()
    state = await WorkflowOrchestrator._anomaly_node(orch, _State2())
    assert state.intermediate_results["anomaly_result"]["formatted_response"] == "No sensor data."
