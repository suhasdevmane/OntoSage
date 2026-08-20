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
    @pytest.mark.asyncio
    async def test_operator_can_execute(self):
        agent = ControlAgent()
        state = _make_state("Set HVAC Zone 3 to 21°C", role="operator")
        with patch.object(
            agent.bms,
            "send_command",
            new=AsyncMock(
                return_value={
                    "status": "simulated",
                    "device": "HVAC Zone 3",
                    "action": "set",
                    "value": "21°C",
                    "mode": "simulation",
                }
            ),
        ):
            result = await agent.execute_command(state)
        assert result["status"] == "simulated"
        assert result["device"] == "HVAC Zone 3"

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
    async def test_facility_manager_can_execute(self):
        agent = ControlAgent()
        state = _make_state("Turn off the lights in room 2.04", role="facility_manager")
        with patch.object(
            agent.bms,
            "send_command",
            new=AsyncMock(
                return_value={
                    "status": "simulated",
                    "device": "lights room 2.04",
                    "action": "off",
                    "value": "",
                    "mode": "simulation",
                }
            ),
        ):
            result = await agent.execute_command(state)
        assert result["status"] == "simulated"


class TestControlAgentLogging:
    @pytest.mark.asyncio
    async def test_log_entry_written(self):
        agent = ControlAgent()
        state = _make_state("Set HVAC Zone 3 to 21°C", role="operator")
        with patch.object(
            agent.bms,
            "send_command",
            new=AsyncMock(
                return_value={
                    "status": "simulated",
                    "device": "HVAC Zone 3",
                    "action": "set",
                    "value": "21°C",
                    "mode": "simulation",
                }
            ),
        ):
            result = await agent.execute_command(state)
        assert "log_entry" in result
        log = result["log_entry"]
        assert log["user_role"] == "operator"
        assert log["device"] == "HVAC Zone 3"
        assert log["action"] == "set"
