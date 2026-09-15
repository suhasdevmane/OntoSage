# -*- coding: utf-8 -*-
"""BUG-543: a chart is drawn only when one was asked for, and only over data.

Two faults compounded on one stakeholder question — "Which permission groups or zones are
orphaned because no current owner, purpose or mapped opening can be evidenced?":

1. the visualisation trigger matched keywords INSIDE words, so "mapped" asked for a map;
2. with nothing to plot, the viz agent still drew a chart, and the narration read an empty
   bar chart as a finding.
"""

import asyncio
from types import SimpleNamespace

import pytest

from orchestrator.workflow._orchestrator import WorkflowOrchestrator

pytestmark = pytest.mark.unit

wants = WorkflowOrchestrator._user_wants_visualization


@pytest.mark.parametrize(
    "question",
    [
        "Which permission groups or zones are orphaned because no current owner, purpose or "
        "mapped opening can be evidenced?",
        "Are any lighting circuits drawing more power than their design load?",
        "Which spaces should reconfigure, how quickly, and what acoustic changes follow?",
        "Are the solar panels working?",
        "Can I get the sensor-to-room mapping as a file?",
        "Which permissioned logs, telemetry or photographs may be lost under retention?",
    ],
)
def test_a_keyword_inside_another_word_is_not_a_chart_request(question):
    assert wants(question) is False


@pytest.mark.parametrize(
    "question",
    [
        "plot the CO2 in room 5.01 today",
        "show me a bar chart of temperature by floor",
        "Graph humidity for the last week",
        "can you visualise occupancy on floor 2",
        "draw the trend",
        "show the trend of energy use",
        "give me a heat map of CO2",
        "plots of every floor please",
    ],
)
def test_a_real_chart_request_still_is_one(question):
    assert wants(question) is True


def test_a_negated_request_still_wins():
    assert wants("compute the average, no chart") is False


def _orchestrator(fetched):
    orch = WorkflowOrchestrator.__new__(WorkflowOrchestrator)
    calls = []

    async def _sparql(state):
        return state

    async def _sql(state):
        state.query_results = fetched
        return state

    async def _viz(state, message, data):
        calls.append(data)
        return {"formatted_response": "chart", "media": [{"type": "image"}]}

    orch._sparql_node = _sparql
    orch._sql_node = _sql
    orch.viz_agent = SimpleNamespace(create_visualization=_viz)
    return orch, calls


def _state():
    return SimpleNamespace(
        messages=[SimpleNamespace(content="show me a chart of orphaned permission groups")],
        query_results=None,
        intermediate_results={},
    )


def test_no_data_after_the_fetch_draws_no_chart():
    orch, calls = _orchestrator(fetched={"data": []})
    state = asyncio.run(orch._visualization_node(_state()))
    assert calls == []
    viz = state.intermediate_results["viz_result"]
    assert viz["skipped"] == "no_data" and "media" not in viz


def test_data_after_the_fetch_is_charted():
    rows = {"data": [{"timestamp": "2026-09-15 00:00:00", "uuid": "u", "value": 1.0}]}
    orch, calls = _orchestrator(fetched=rows)
    state = asyncio.run(orch._visualization_node(_state()))
    assert calls == [rows] and state.intermediate_results["viz_result"]["media"]
