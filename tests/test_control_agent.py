"""Tests for ControlAgent — RBAC-gated device control."""

from unittest.mock import AsyncMock, patch

import pytest

from orchestrator.agents.control_agent import ControlAgent
from shared.models import ConversationState, Message


def _make_state(query: str, role: str = "operator", user_id: str = "u1") -> ConversationState:
    state = ConversationState(
        conversation_id="ctrl-test",
        user_id=user_id,
        user_message=query,
        messages=[Message(role="user", content=query)],
    )
    state.intermediate_results["intent"] = "control"
    state.intermediate_results["entities"] = [
        {"type": "device", "value": "HVAC Zone 3"},
        {"type": "action", "value": "set"},
        {"type": "target_value", "value": "21°C"},
    ]
    state.intermediate_results["user_role"] = role
    state.intermediate_results["user_id"] = user_id
    state.intermediate_results["building_id"] = "bldg1"
    return state


class TestControlAgentPermissions:
    """These two tests pinned the LEGACY path (`agent.bms.send_command` -> "simulated"), which
    `execute_command` stopped calling when the actuation gateway landed (T25): every write now goes
    through an approval, and only a role holding `control:write` (admin and facility_manager; the
    catalogue says so in rbac.py) may request one. They failed at HEAD for that reason, not for
    anything about labels or wording, and are re-pinned to what the agent does."""

    @pytest.mark.asyncio
    async def test_operator_cannot_request_a_write(self):
        agent = ControlAgent()
        state = _make_state("Set HVAC Zone 3 to 21°C", role="operator")
        result = await agent.execute_command(state)
        assert result["status"] == "denied"
        assert "operator" in result["message"].lower()

    @pytest.mark.asyncio
    async def test_analyst_is_denied(self):
        agent = ControlAgent()
        state = _make_state("Set HVAC Zone 3 to 21°C", role="analyst")
        result = await agent.execute_command(state)
        assert result["status"] == "denied"
        assert "analyst" in result["message"].lower()

    @pytest.mark.asyncio
    async def test_occupant_is_denied(self):
        agent = ControlAgent()
        state = _make_state("Turn off the lights", role="occupant")
        result = await agent.execute_command(state)
        assert result["status"] == "denied"

    @pytest.mark.asyncio
    async def test_facility_manager_naming_no_writable_point_is_asked_for_one_and_nothing_is_queued(self):
        agent = ControlAgent()
        state = _make_state("Turn off the lights in room 2.04", role="facility_manager")
        result = await agent.execute_command(state)
        # allowed to ask (control:write), but "lights in room 2.04" is no point the building lets
        # the assistant write: the decline names it and lists the plain-label setpoints instead
        assert result["status"] == "needs_detail"
        assert "Nothing has been queued" in result["message"] or "can't control" in result["message"]
        assert "nothing has been queued" in result["message"].lower()


class TestControlAgentLogging:
    @pytest.mark.asyncio
    async def test_log_entry_written(self):
        agent = ControlAgent()
        state = _make_state("Set HVAC Zone 3 to 21°C", role="operator")
        result = await agent.execute_command(state)
        assert "log_entry" in result
        log = result["log_entry"]
        assert log["user_role"] == "operator"
        assert log["device"] == "HVAC Zone 3"
        assert log["action"] == "set"
