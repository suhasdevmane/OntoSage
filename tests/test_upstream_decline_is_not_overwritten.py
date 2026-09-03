# -*- coding: utf-8 -*-
"""A downstream lane must not overwrite an upstream decline (BUG-395).

Measured live: "are there any energy spikes?" resolved 288 sensors, over the fetch lane's
`MAX_FETCH_UUIDS` budget, so the SQL lane declined correctly and said so — it named the
count and offered the narrowing to try. The anomaly node then handed the resulting empty
row set to the detector, which reported:

    "No sensor data available for anomaly detection."

A different claim, and an untrue one. bldg1 has 8 energy sensors and all 8 are live; the
anomaly scanner found 24,317 spike findings in the same hour. The question was too broad to
read in one request, and the user was told the building had no data.

The analytics lane already did this correctly, so the shape was established and one lane
simply did not follow it. The test is parameterised over both to keep them in step.
"""

import inspect

import pytest

pytestmark = pytest.mark.unit


def _too_broad_sql_result():
    return {
        "success": True,
        "query": "Breadth Budget (No Fetch)",
        "results": {"data": []},
        "formatted_response": "That question reaches **288 sensors** — more than I can read "
        "and summarise in one request.",
        "analytics_required": False,
        "too_broad": True,
        "uuids_requested": 288,
    }


@pytest.mark.asyncio
async def test_the_anomaly_lane_surfaces_the_upstream_decline():
    from orchestrator.workflow._orchestrator import WorkflowOrchestrator

    class _State:
        def __init__(self):
            self.messages = []
            self.intermediate_results = {"sql_result": _too_broad_sql_result()}

    orch = WorkflowOrchestrator.__new__(WorkflowOrchestrator)
    state = await WorkflowOrchestrator._anomaly_node(orch, _State())
    out = state.intermediate_results["anomaly_result"]

    assert out["declined_upstream"] == "too_broad"
    assert "288 sensors" in out["formatted_response"]
    assert "No sensor data available" not in out["formatted_response"]


@pytest.mark.asyncio
async def test_the_detector_is_not_even_called_when_upstream_declined():
    """Running it would waste the work and produce a claim about data nobody fetched."""
    from orchestrator.workflow._orchestrator import WorkflowOrchestrator

    called = {"n": 0}

    class _Detector:
        async def detect(self, *a, **k):
            called["n"] += 1
            return {"success": False, "formatted_response": "No sensor data available."}

    class _State:
        def __init__(self):
            self.messages = []
            self.intermediate_results = {"sql_result": _too_broad_sql_result()}

    orch = WorkflowOrchestrator.__new__(WorkflowOrchestrator)
    orch.anomaly_agent = _Detector()
    await WorkflowOrchestrator._anomaly_node(orch, _State())
    assert called["n"] == 0


@pytest.mark.asyncio
async def test_a_normal_empty_result_still_reaches_the_detector():
    """The safety property: only a DECLARED decline short-circuits, not any empty result."""
    from orchestrator.workflow._orchestrator import WorkflowOrchestrator

    called = {"n": 0}

    class _Detector:
        async def detect(self, *a, **k):
            called["n"] += 1
            return {"success": False, "formatted_response": "No sensor data available."}

    class _State:
        def __init__(self):
            self.messages = []
            self.intermediate_results = {"sql_result": {"success": True, "results": {"data": []}}}

    orch = WorkflowOrchestrator.__new__(WorkflowOrchestrator)
    orch.anomaly_agent = _Detector()
    await WorkflowOrchestrator._anomaly_node(orch, _State())
    assert called["n"] == 1


@pytest.mark.parametrize(
    "module_path, symbol",
    [
        ("orchestrator.agents.analytics_agent", "too_broad"),
        ("orchestrator.workflow._orchestrator", "too_broad"),
    ],
)
def test_every_consumer_of_the_fetch_lane_checks_for_the_decline(module_path, symbol):
    """Keeps the two lanes in step. A third consumer must add the same check."""
    import importlib

    mod = importlib.import_module(module_path)
    assert symbol in inspect.getsource(mod), (
        f"{module_path} consumes the fetch lane's result without checking `too_broad`, so an "
        "upstream decline will be replaced by a claim about data nobody fetched"
    )
