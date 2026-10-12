"""CAVEAT-1630: a plan's SQL rows that hold identifiers, not readings, are not passed on as data.

Bank sample v3: the planner answered "Each record has a timestamp of None and a value that is a
UUID: 13dd8500-..." -- rows with no measured value narrated as if they were readings.
"""

from __future__ import annotations

import asyncio
from types import SimpleNamespace

import pytest

from orchestrator.agents import planner_agent as pa

pytestmark = pytest.mark.unit

ID_ROWS = {
    "success": True,
    "results": {"data": [{"timestamp": None, "value": "13dd8500-5723-5015-8816-ef273f5795c6"}]},
}
READINGS = {
    "success": True,
    "results": {"data": [{"timestamp": "2026-10-10T10:00:00", "value": 21.4, "uuid": "u1"}]},
}


def test_identifier_rows_become_a_refusal():
    out = pa._readings_or_refusal(ID_ROWS)
    assert out["success"] is False
    assert out["rows_without_readings"] == 1
    assert "13dd8500" not in out["error"]


@pytest.mark.parametrize(
    "result",
    [READINGS, {"success": True, "results": {"data": []}}, {"success": False, "error": "x"}, None],
)
def test_readings_empty_and_failed_results_pass_through_unchanged(result):
    assert pa._readings_or_refusal(result) is result


def test_no_later_step_analyses_or_exports_identifier_rows():
    agent = pa.PlannerAgent.__new__(pa.PlannerAgent)
    ctx = {"sql_result": pa._readings_or_refusal(ID_ROWS)}
    state = SimpleNamespace(intermediate_results={})
    analysed = asyncio.run(agent._run_analytics(state, "q", ctx))
    exported = asyncio.run(agent._run_export(ctx, {"format": "csv"}))
    assert analysed["success"] is False and exported["success"] is False


def test_the_reader_is_told_what_happened_not_that_the_plan_was_empty():
    agent = pa.PlannerAgent.__new__(pa.PlannerAgent)
    plan = SimpleNamespace(rationale="")
    out = agent._assemble_result(plan, {"sql_result": pa._readings_or_refusal(ID_ROWS)}, [])
    assert out["formatted_response"] == pa._NO_READINGS_TEXT
    assert "UUID" not in out["formatted_response"] and "None" not in out["formatted_response"]
