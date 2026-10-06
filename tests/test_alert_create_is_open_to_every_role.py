# -*- coding: utf-8 -*-
"""B4: every authenticated role may create a personal alert rule.

Before this change the node refused only ``guest``/``anonymous`` by name, and nothing
named ``alert:create`` existed in the permission catalogue. The permission now exists,
every built-in role holds it, and the node checks it.
"""

import asyncio
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

import pytest

from orchestrator.middleware.rbac import ROLE_PERMISSIONS

pytestmark = pytest.mark.unit

_MESSAGE = "alert me when co2 goes above 1000 for 10 minutes"


def _run(role, user_id="someone"):
    from orchestrator.workflow._orchestrator import WorkflowOrchestrator

    orch = WorkflowOrchestrator.__new__(WorkflowOrchestrator)
    store = SimpleNamespace(
        create_alert=AsyncMock(return_value="abcd1234"),
        list_alerts=AsyncMock(return_value=[]),
        delete_alert=AsyncMock(return_value=True),
    )
    state = SimpleNamespace(
        messages=[SimpleNamespace(content=_MESSAGE)],
        building_id="b",
        current_intent="alert",
        intermediate_results={
            "user_id": user_id,
            "user_role": role,
            "entities": [],
            "concepts": [],
            "intent": "alert",
        },
    )
    with patch("orchestrator.services.user_alert_store.get_user_alert_store", return_value=store):
        asyncio.run(orch._alert_mgmt_node(state))
    return store, state.intermediate_results.get("dialogue_response", "")


@pytest.mark.parametrize(
    "role", ["admin", "facility_manager", "analyst", "operator", "occupant", "readonly"]
)
def test_every_built_in_role_creates_an_alert(role):
    store, reply = _run(role)
    store.create_alert.assert_awaited_once()
    assert "Alert created" in reply


def test_every_built_in_role_holds_the_permission():
    for role, perms in ROLE_PERMISSIONS.items():
        assert "alert:create" in perms, role


@pytest.mark.parametrize("role", ["guest", "anonymous", "not_a_role"])
def test_callers_without_a_role_are_still_refused(role):
    store, reply = _run(role)
    store.create_alert.assert_not_called()
    assert "logged in" in reply


def test_no_user_id_is_refused_even_with_a_role():
    store, _ = _run("admin", user_id="")
    store.create_alert.assert_not_called()
