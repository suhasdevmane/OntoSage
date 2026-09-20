# -*- coding: utf-8 -*-
"""The SQL lane offers a question to the store's aggregates BEFORE it refuses it as too broad.

The wiring is where 2D-10 can silently fail: the lane can be correct in isolation and never
reached, or reached and then rewritten by a later lane. These tests pin the four joints.

1. the SQL lane asks the aggregate lane first, and a None answer leaves the old refusal intact;
2. the budget has ONE definition, shared by the refusal and the aggregate lane;
3. a computed answer is final: routing goes straight to the response, whatever the intent;
4. the response node collects it.
"""

from __future__ import annotations

import inspect
from types import SimpleNamespace

import pytest

from orchestrator.agents import sql_agent
from orchestrator.agents.sql_agent import SQLAgent, over_fetch_budget

pytestmark = pytest.mark.unit


def _agent() -> SQLAgent:
    return SQLAgent.__new__(SQLAgent)


@pytest.fixture
def registry(monkeypatch):
    fake = SimpleNamespace(
        is_available=True, _adapters={}, _resolve_storage_key=lambda uri: (uri or "default")
    )
    monkeypatch.setattr(sql_agent, "adapter_registry", fake)
    return fake


# ── 1. the store is asked first ────────────────────────────────────────────────


async def test_an_aggregate_answer_is_returned_instead_of_the_refusal(registry, monkeypatch):
    seen = {}

    async def fake_lane(self, uuids, question, storage_map, start, end, metadata, *limits):
        seen.update(n=len(uuids), question=question, start=start, end=end)
        return {
            "success": True,
            "formatted_response": "answered in the store",
            "aggregate_lane": True,
        }

    monkeypatch.setattr(SQLAgent, "_try_aggregate_lane", fake_lane)
    uuids = [f"sensor-{i:04d}-aaaa" for i in range(700)]  # over the 600-sensor budget
    out = await _agent().fetch_data_for_uuids(
        uuids, "Which floor had the highest CO2 this week?", {}, "2026-09-13 23:00:00", None, {}
    )
    assert out["aggregate_lane"] and out["formatted_response"] == "answered in the store"
    assert "too_broad" not in out
    assert seen["n"] == 700 and seen["start"] == "2026-09-13 23:00:00"


async def test_when_the_aggregate_lane_declines_the_old_refusal_stands(registry, monkeypatch):
    async def steps_aside(self, *args):
        return None

    monkeypatch.setattr(SQLAgent, "_try_aggregate_lane", steps_aside)
    uuids = [f"sensor-{i:04d}-aaaa" for i in range(700)]
    out = await _agent().fetch_data_for_uuids(
        uuids, "show me every sensor reading this week", {}, None, None, {}
    )
    assert out["too_broad"] is True and "700 sensors" in out["formatted_response"]


async def test_a_failure_inside_the_aggregate_lane_never_costs_the_turn(registry, monkeypatch):
    from orchestrator.services import aggregate_lane

    async def boom(**kwargs):
        raise RuntimeError("store exploded")

    monkeypatch.setattr(aggregate_lane, "try_answer", boom)
    assert await _agent()._try_aggregate_lane(["sensor-0001-aaaa"], "q", {}, None, None, {}) is None


async def test_a_store_the_registry_does_not_know_is_not_borrowed_from_the_default(
    registry, monkeypatch
):
    """The registry falls back to the default adapter for an unknown key, which reads a narrow
    store's uuid as a column name. The aggregate lane must not inherit that."""
    from orchestrator.services import aggregate_lane

    captured = {}

    async def spy(**kwargs):
        captured["adapter"] = kwargs["adapter_for"]("http://example.org/bldg#unknown_store")
        return None

    registry._adapters["default"] = object()
    monkeypatch.setattr(aggregate_lane, "try_answer", spy)
    await _agent()._try_aggregate_lane(["sensor-0001-aaaa"], "q", {}, None, None, {})
    assert captured["adapter"] is None


def test_the_hook_sits_before_the_refusal_and_after_the_availability_check():
    source = inspect.getsource(SQLAgent.fetch_data_for_uuids)
    unavailable = source.index("database_unavailable")
    hook = source.index("_try_aggregate_lane")
    refusal = source.index("over_fetch_budget(")
    assert unavailable < hook < refusal


# ── 2. one definition of "too broad" ───────────────────────────────────────────


def test_the_budget_has_one_definition():
    assert over_fetch_budget(601, 60) is True  # too many sensors
    assert over_fetch_budget(276, 1000) is True  # 276,000 rows: the week-long question
    assert over_fetch_budget(276, 60) is False  # 16,560 rows: "right now" still fits
    assert over_fetch_budget(1, 1000) is False
    source = inspect.getsource(SQLAgent.fetch_data_for_uuids)
    assert "len(uuids) > MAX_FETCH_UUIDS" not in source, "the refusal must call over_fetch_budget"


def test_the_lane_and_the_refusal_are_given_the_same_budget_question():
    lane = inspect.getsource(SQLAgent._try_aggregate_lane)
    assert "over_fetch_budget(len(uuids), rows_per_uuid_for(user_query))" in lane


# ── 3. a computed answer is final ──────────────────────────────────────────────


@pytest.mark.parametrize("intent", ["anomaly", "report", "visualization", "compare", "analytics"])
def test_an_aggregate_answer_routes_straight_to_the_response(intent):
    from orchestrator.workflow._routing import WorkflowRoutingMixin

    state = SimpleNamespace(
        current_intent=intent,
        analytics_required=True,
        messages=[],
        intermediate_results={"aggregate_result": {"formatted_response": "computed"}},
    )
    assert WorkflowRoutingMixin._route_from_sql(SimpleNamespace(), state) == "response"


def test_without_an_aggregate_answer_the_routing_is_unchanged():
    from orchestrator.workflow._routing import WorkflowRoutingMixin

    state = SimpleNamespace(
        current_intent="anomaly", analytics_required=True, messages=[], intermediate_results={}
    )
    assert WorkflowRoutingMixin._route_from_sql(SimpleNamespace(), state) == "anomaly"


async def test_the_sql_node_records_the_answer_and_stops_analytics():
    from orchestrator.workflow import _orchestrator as orch_mod

    source = inspect.getsource(orch_mod.WorkflowOrchestrator._sql_node)
    assert 'result.get("aggregate_lane")' in source
    assert "state.analytics_required = False" in source
    assert 'intermediate_results["aggregate_result"]' in source


# ── 4. the response node collects it ───────────────────────────────────────────


def test_the_response_node_collects_the_aggregate_answer_before_any_narrating_lane():
    from orchestrator.workflow import _orchestrator as orch_mod

    source = inspect.getsource(orch_mod.WorkflowOrchestrator._response_node)
    agg = source.index('"aggregate_result"')
    assert agg < source.index('elif analytics_result.get("formatted_response")')
    assert agg < source.index('elif sql_result.get("formatted_response")')


# ── 5. the verifier and the publication gate see the answer as grounded ────────


def test_an_aggregate_answer_counts_as_grounded_not_as_zero_rows():
    from orchestrator.agents.verifier_agent import _count_sql_rows

    answered = {"aggregate_lane": True, "aggregate": {"sensors": 276}, "results": {"data": []}}
    assert _count_sql_rows(answered) == 276
    assert _count_sql_rows({"results": {"data": []}}) == 0  # an ordinary empty read is unchanged


def test_a_gated_lane_does_not_withhold_an_aggregate_answer():
    """compare/analytics answers are gated on grounding; zero rows would have read as none."""
    from orchestrator.services import publication_gate as gate

    text = "**Floor 5 had the highest CO2 in the period: 1,175 ppm**."
    grounded = {"grounded": True, "confidence": 0.92, "source": "sql", "missing": []}
    assert gate.evaluate(intent="compare", final_response=text, verification=grounded).publish
    # and the failure this guards: with zero rows the verifier concluded "none", and it WITHHELD
    ungrounded = {"grounded": False, "confidence": 0.2, "source": "none", "missing": []}
    assert not gate.evaluate(intent="compare", final_response=text, verification=ungrounded).publish
