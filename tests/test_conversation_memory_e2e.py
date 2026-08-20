"""End-to-end flow tests for turn memory wiring.

Tests exercise TurnMemoryService at the boundary — no live Postgres/Redis.
"""

import json
from unittest.mock import AsyncMock, MagicMock

import pytest

from shared.models import ConversationState, Message

_FORECAST_CF = {
    "forecast_result": {
        "success": True,
        "sensor_label": "Zone 5.02 Temperature",
        "model": "ARIMA",
        "horizon": "next 24 hours",
        "metrics": {"rmse": 0.82, "mae": 0.61, "mape": 3.1},
        "forecast": [21.1, 21.3],
        "lower_80": [20.5, 20.7],
        "upper_80": [21.7, 21.9],
        "lower_95": [20.0, 20.2],
        "upper_95": [22.2, 22.4],
        "formatted_response": "24h forecast: 21-23 deg C",
    }
}


def test_carry_forward_survives_json_round_trip():
    """carry_forward JSON stored in Postgres must deserialise back identically."""
    import importlib.util
    import pathlib

    spec = importlib.util.spec_from_file_location(
        "turn_memory",
        str(pathlib.Path("orchestrator/services/turn_memory.py").resolve()),
    )
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    TurnMemoryService = mod.TurnMemoryService

    svc = TurnMemoryService(pool=None)
    state = ConversationState(
        conversation_id="conv-rt",
        user_id="alice",
        user_message="forecast",
        building_id="bldg1",
        messages=[Message(role="user", content="forecast")],
        intermediate_results=_FORECAST_CF,
    )
    cf = svc._extract_carry_forward(state)
    restored = json.loads(json.dumps(cf))
    assert restored["forecast_result"]["success"] is True
    assert restored["forecast_result"]["sensor_label"] == "Zone 5.02 Temperature"


@pytest.mark.asyncio
async def test_carry_forward_injected_into_new_state():
    """get_carry_forward result appears in new state's intermediate_results."""
    import importlib.util
    import pathlib

    spec = importlib.util.spec_from_file_location(
        "turn_memory",
        str(pathlib.Path("orchestrator/services/turn_memory.py").resolve()),
    )
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    TurnMemoryService = mod.TurnMemoryService

    mock_conn = AsyncMock()
    mock_conn.fetchrow = AsyncMock(return_value={"carry_forward": json.dumps(_FORECAST_CF)})
    mock_pool = MagicMock()
    mock_pool.acquire = MagicMock(
        return_value=AsyncMock(
            __aenter__=AsyncMock(return_value=mock_conn),
            __aexit__=AsyncMock(return_value=False),
        )
    )

    svc = TurnMemoryService(pool=mock_pool)
    cf = await svc.get_carry_forward("conv-fc")

    new_state = ConversationState(
        conversation_id="conv-fc",
        user_id="alice",
        user_message="show graph",
        building_id="bldg1",
        messages=[Message(role="user", content="show graph")],
        intermediate_results=cf,
    )
    assert new_state.intermediate_results.get("forecast_result", {}).get("success") is True


@pytest.mark.asyncio
async def test_older_context_text_format():
    """Older turn summaries are formatted as readable text."""
    import importlib.util
    import pathlib

    spec = importlib.util.spec_from_file_location(
        "turn_memory",
        str(pathlib.Path("orchestrator/services/turn_memory.py").resolve()),
    )
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    TurnMemoryService = mod.TurnMemoryService

    mock_conn = AsyncMock()
    mock_conn.fetch = AsyncMock(
        return_value=[
            {
                "turn_index": 1,
                "user_query": "what is the temperature in room 5.02",
                "intent": "sensor_data",
                "result_summary": "Room 5.02: 22.3 deg C current reading",
            }
        ]
    )
    mock_pool = MagicMock()
    mock_pool.acquire = MagicMock(
        return_value=AsyncMock(
            __aenter__=AsyncMock(return_value=mock_conn),
            __aexit__=AsyncMock(return_value=False),
        )
    )

    svc = TurnMemoryService(pool=mock_pool)
    ctx = await svc.get_older_context("conv-fc", skip_recent=20)

    assert "Earlier conversation context" in ctx
    assert "22.3" in ctx
    assert "sensor_data" in ctx


@pytest.mark.asyncio
async def test_save_turn_does_not_store_raw_sensor_arrays():
    """Raw SQL/SPARQL data must never reach the turn_memory table."""
    import importlib.util
    import pathlib

    spec = importlib.util.spec_from_file_location(
        "turn_memory",
        str(pathlib.Path("orchestrator/services/turn_memory.py").resolve()),
    )
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    TurnMemoryService = mod.TurnMemoryService

    executed_args = []

    mock_conn = AsyncMock()
    mock_conn.fetchval = AsyncMock(return_value=1)

    async def capture_execute(sql, *args):
        executed_args.append(args)

    mock_conn.execute = AsyncMock(side_effect=capture_execute)
    mock_pool = MagicMock()
    mock_pool.acquire = MagicMock(
        return_value=AsyncMock(
            __aenter__=AsyncMock(return_value=mock_conn),
            __aexit__=AsyncMock(return_value=False),
        )
    )

    svc = TurnMemoryService(pool=mock_pool)
    state = ConversationState(
        conversation_id="conv-sql",
        user_id="bob",
        user_message="temperature last hour",
        building_id="bldg1",
        messages=[
            Message(role="user", content="temperature last hour"),
            Message(role="assistant", content="Average: 22.1 deg C"),
        ],
        intermediate_results={
            "intent": "sensor_data",
            "sql_data": [{"ts": "2026-06-01T10:00", "value": 22.1}] * 500,
            "sparql_results": [{"uuid": "abc123"}] * 100,
        },
    )
    await svc.save_turn(state)

    assert executed_args, "No INSERT executed"
    cf_arg = executed_args[0][7]  # 8th positional arg = carry_forward JSON
    cf = json.loads(cf_arg)
    assert "sql_data" not in cf
    assert "sparql_results" not in cf
