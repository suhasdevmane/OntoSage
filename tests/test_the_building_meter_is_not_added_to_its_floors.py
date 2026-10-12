"""A whole-building question reads the building's own meter, never it plus its floor meters.

2026-10-11: "How much water did the building use yesterday?" bound the main water meter AND the
18 floor water points -- the same water counted twice -- and the floors' hot and chilled circuits
split the measurand vote, so no lane claimed the turn.
"""

from __future__ import annotations

import asyncio

import pytest

from orchestrator.agents import sparql_agent as sa

pytestmark = pytest.mark.unit

NS = "http://example.org/b#"


def _agent(meter_rows, floor_rows):
    agent = sa.SPARQLAgent.__new__(sa.SPARQLAgent)
    seen = []

    async def _execute_query(q):
        seen.append(q)
        rows = meter_rows if "brick:Building_Meter" in q else floor_rows
        return {"results": {"bindings": rows}}

    agent._execute_query = _execute_query
    agent._prefix_block = lambda building_id=None: "PREFIX brick: <x>"
    return agent, seen


def _run(agent):
    return asyncio.run(
        agent._resolve_building_structurally(
            NS, 50, class_hints=["brick:Building_Water_Meter", "brick:Water_Meter"]
        )
    )


def test_the_building_meter_alone_answers_for_the_building(monkeypatch):
    monkeypatch.setattr(sa, "_active_prefix", lambda: "bldg")
    agent, seen = _agent(
        [{"s": {"value": NS + "Building_Water_Meter"}}],
        [{"s": {"value": NS + "Floor0_water"}}, {"s": {"value": NS + "Floor1_water"}}],
    )
    assert _run(agent) == ["bldg:Building_Water_Meter"]
    assert len(seen) == 1  # the floors are never asked for


def test_without_a_building_meter_the_floors_answer(monkeypatch):
    monkeypatch.setattr(sa, "_active_prefix", lambda: "bldg")
    agent, _ = _agent(
        [], [{"s": {"value": NS + "Floor0_water"}}, {"s": {"value": NS + "Floor1_water"}}]
    )
    assert _run(agent) == ["bldg:Floor0_water", "bldg:Floor1_water"]
