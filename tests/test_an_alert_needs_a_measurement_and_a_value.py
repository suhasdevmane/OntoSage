# -*- coding: utf-8 -*-
"""BUG-552: an alert with no value or no measurement is not created (it fired every cycle)."""

import asyncio
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

import pytest

pytestmark = pytest.mark.unit


def _run(message, concepts=None):
    from orchestrator.workflow._orchestrator import WorkflowOrchestrator

    orch = WorkflowOrchestrator.__new__(WorkflowOrchestrator)
    store = SimpleNamespace(create_alert=AsyncMock(return_value="abcd1234"),
                            list_alerts=AsyncMock(return_value=[]),
                            delete_alert=AsyncMock(return_value=True))
    state = SimpleNamespace(
        messages=[SimpleNamespace(content=message)], building_id="b", current_intent="alert",
        intermediate_results={"user_id": "u", "user_role": "analyst", "entities": [], "concepts": concepts or [],
                              "intent": "alert"},
    )
    with patch("orchestrator.services.user_alert_store.get_user_alert_store", return_value=store):
        asyncio.run(orch._alert_mgmt_node(state))
    return store, state.intermediate_results.get("dialogue_response", "")


def test_no_value_creates_nothing_and_asks():
    store, reply = _run("alert me when it gets crowded", concepts=[{"concept_id": "crowded"}])
    store.create_alert.assert_not_called()
    assert "haven't created an alert" in reply and "the value that should trigger it" in reply


def test_no_measurement_creates_nothing_and_asks():
    store, reply = _run("alert me when it goes above 50")
    store.create_alert.assert_not_called()
    assert "what to measure" in reply


def test_a_measurement_and_a_value_create_the_alert():
    store, reply = _run("alert me when co2 goes above 1000 for 10 minutes")
    store.create_alert.assert_awaited_once()
    trigger = store.create_alert.call_args.args[2]
    assert trigger["threshold"] == 1000.0 and trigger["op"] == ">" and trigger["duration_min"] == 10
    assert "Alert created" in reply
