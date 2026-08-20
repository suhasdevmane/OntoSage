"""
tests/test_multi_intent_aggregation.py
=======================================
Tests for Task 4: sensor_data section included in multi-intent aggregated response.

Bug: _build_from_multi_intent skips sensor_data sub-intents in group_a filter,
so the SQL time-series result is never surfaced in the final response.

Fix: _execute_multi_intent injects the SQL result as a sensor_data section
after the data pipeline completes and before the parallel phase.
"""

from datetime import datetime
from unittest.mock import AsyncMock, MagicMock, patch

import pytest


@pytest.mark.asyncio
@pytest.mark.unit
async def test_sensor_data_section_included_in_multi_intent_result():
    """sensor_data sub-intent result must appear in the aggregated response."""
    from orchestrator.agents.planner_agent import PlannerAgent
    from shared.models import ConversationState, Message

    state = ConversationState(
        conversation_id="test-agg-conv",
        user_message="Show CO2 on floor 2 and show me the floor 2 layout",
        messages=[
            Message(
                role="user",
                content="Show CO2 on floor 2 and show me the floor 2 layout",
                timestamp=datetime.now(),
            )
        ],
        building_id="bldg1",
    )
    state.intermediate_results["multi_intent_plan"] = {
        "sub_intents": [
            {"intent": "sensor_data", "sub_query": "CO2 on floor 2"},
            {"intent": "floor_plan", "sub_query": "show floor 2 layout"},
        ]
    }

    agent = PlannerAgent()

    async def fake_sparql(state, query, params):
        return {
            "results": {},
            "uuids": ["uuid-co2-001"],
            "formatted_text": "Sensor metadata found",
        }

    async def fake_sql(state, query, uuids, storage_map, params):
        return {
            "results": {"data": [{"sensor": "CO2_Sensor_2.01", "value": 450}]},
            "formatted_text": "CO2 in floor 2: 450 ppm — within normal range.",
        }

    # _run_floor_plan takes (self, state, step) — step is a PlanStep object
    # Must return a dict (matching real _run_floor_plan return shape)
    async def fake_floor_plan(state, step):
        return {
            "success": True,
            "formatted_response": "## Floor 2 Plan\nRoom A, Room B",
            "markdown": "## Floor 2 Plan\nRoom A, Room B",
        }

    with patch.object(agent, "_run_sparql", side_effect=fake_sparql), patch.object(
        agent, "_run_sql", side_effect=fake_sql
    ), patch.object(agent, "_run_floor_plan", side_effect=fake_floor_plan):
        result = await agent.plan_and_execute(state, state.messages[-1].content)

    assert result.get("success") is True, f"Plan failed: {result}"
    response = result.get("formatted_response", "")

    # Both sensor data AND floor plan content must be present
    assert any(
        term in response for term in ["CO2", "450", "co2", "Sensor"]
    ), f"Sensor data content missing from response:\n{response[:500]}"
    assert any(
        term in response for term in ["Floor 2 Plan", "Room A", "floor", "layout"]
    ), f"Floor plan content missing from response:\n{response[:500]}"


@pytest.mark.asyncio
@pytest.mark.unit
async def test_multi_intent_floor_plan_only_not_broken():
    """Pure floor_plan + spatial_query sub-intents without sensor_data must still work."""
    from orchestrator.agents.planner_agent import PlannerAgent
    from shared.models import ConversationState, Message

    state = ConversationState(
        conversation_id="test-fp-only",
        user_message="Show floor 3 and floor 5 layouts",
        messages=[
            Message(
                role="user",
                content="Show floor 3 and floor 5 layouts",
                timestamp=datetime.now(),
            )
        ],
        building_id="bldg1",
    )
    state.intermediate_results["multi_intent_plan"] = {
        "sub_intents": [
            {"intent": "floor_plan", "sub_query": "floor 3 layout"},
            {"intent": "spatial_query", "sub_query": "room count floor 3"},
        ]
    }
    agent = PlannerAgent()

    # _run_floor_plan takes (self, state, step)
    async def fake_floor_plan(state, step):
        return {
            "success": True,
            "formatted_response": "## Floor 3 Plan\nRooms listed here",
            "markdown": "## Floor 3 Plan\nRooms listed here",
        }

    # _run_spatial_query takes (self, state, step)
    async def fake_spatial_query(state, step):
        return {"formatted_text": "Floor 3 has 34 rooms.", "success": True}

    with patch.object(agent, "_run_floor_plan", side_effect=fake_floor_plan), patch.object(
        agent, "_run_spatial_query", side_effect=fake_spatial_query
    ):
        result = await agent.plan_and_execute(state, state.messages[-1].content)

    assert result.get("success") is True
    response = result.get("formatted_response", "")
    assert (
        "Floor 3" in response or "34" in response
    ), f"Expected floor plan content in response:\n{response[:300]}"


@pytest.mark.asyncio
@pytest.mark.unit
async def test_sensor_data_not_injected_when_sql_empty():
    """No sensor_data section injected when SQL returns no content."""
    from orchestrator.agents.planner_agent import PlannerAgent
    from shared.models import ConversationState, Message

    state = ConversationState(
        conversation_id="test-agg-empty-sql",
        user_message="Show CO2 on floor 2 and show me the floor 2 layout",
        messages=[
            Message(
                role="user",
                content="Show CO2 on floor 2 and show me the floor 2 layout",
                timestamp=datetime.now(),
            )
        ],
        building_id="bldg1",
    )
    state.intermediate_results["multi_intent_plan"] = {
        "sub_intents": [
            {"intent": "sensor_data", "sub_query": "CO2 on floor 2"},
            {"intent": "floor_plan", "sub_query": "show floor 2 layout"},
        ]
    }

    agent = PlannerAgent()

    async def fake_sparql(state, query, params):
        return {"results": {}, "uuids": [], "formatted_text": ""}

    # SQL returns None (no result) — simulates DB/Qdrant unavailable
    async def fake_sql(state, query, uuids, storage_map, params):
        return None

    async def fake_floor_plan(state, step):
        return {
            "success": True,
            "formatted_response": "## Floor 2 Plan\nRoom A, Room B",
            "markdown": "## Floor 2 Plan\nRoom A, Room B",
        }

    with patch.object(agent, "_run_sparql", side_effect=fake_sparql), patch.object(
        agent, "_run_sql", side_effect=fake_sql
    ), patch.object(agent, "_run_floor_plan", side_effect=fake_floor_plan):
        result = await agent.plan_and_execute(state, state.messages[-1].content)

    # Should still succeed via floor_plan section
    assert result.get("success") is True
    response = result.get("formatted_response", "")
    # Floor plan should be present
    assert (
        "Floor 2 Plan" in response or "Room A" in response
    ), f"Floor plan missing from response:\n{response[:300]}"
    # No sensor_data section injected when sql_result is None
    assert (
        "Sensor Readings" not in response
    ), f"Unexpected sensor section in response:\n{response[:300]}"
