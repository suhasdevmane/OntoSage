"""Tests for MaintenanceAgent — work-order CRUD and state machine."""
import re
import pytest
from unittest.mock import AsyncMock, MagicMock, patch

from orchestrator.agents.maintenance_agent import MaintenanceAgent, _detect_operation
from shared.models import ConversationState, Message


def _make_state(query: str, role: str = "occupant") -> ConversationState:
    state = ConversationState(
        conversation_id="maint-test",
        user_id="u1",
        user_message=query,
        messages=[Message(role="user", content=query)],
    )
    state.intermediate_results["intent"] = "maintenance"
    state.intermediate_results["user_role"] = role
    state.intermediate_results["user_id"] = "u1"
    state.intermediate_results["building_id"] = "bldg1"
    state.intermediate_results["entities"] = [
        {"type": "location", "value": "Room 4.02"},
        {"type": "fault_description", "value": "heating not working"},
    ]
    return state


class TestOperationDetection:
    def test_create_from_broken(self):
        assert _detect_operation("The heating in 4.02 is broken") == "CREATE"

    def test_create_from_not_working(self):
        assert _detect_operation("The lift is not working") == "CREATE"

    def test_status_from_check_ticket(self):
        assert _detect_operation("Check ticket MT-0042") == "STATUS"

    def test_status_from_mt_id(self):
        assert _detect_operation("What is the status of MT-0001?") == "STATUS"

    def test_list_from_open_tickets(self):
        assert _detect_operation("What open tickets exist?") == "LIST"

    def test_assign(self):
        assert _detect_operation("Assign MT-0042 to John") == "ASSIGN"

    def test_resolve(self):
        assert _detect_operation("Mark MT-0042 as resolved") == "RESOLVE"

    def test_close(self):
        assert _detect_operation("Close ticket MT-0042") == "CLOSE"


class TestTicketIdFormat:
    def test_id_matches_pattern(self):
        agent = MaintenanceAgent()
        ticket_id = agent._generate_ticket_id(42)
        assert re.match(r"^MT-\d{4}$", ticket_id), f"Bad format: {ticket_id}"
        assert ticket_id == "MT-0042"


class TestPermissions:
    @pytest.mark.asyncio
    async def test_occupant_can_create(self):
        agent = MaintenanceAgent()
        state = _make_state("The heating in room 4.02 is broken", role="occupant")
        with patch.object(agent, "_create_ticket", new=AsyncMock(return_value={
            "status": "created", "ticket_id": "MT-0001",
            "message": "🔧 Maintenance ticket created: MT-0001\nLocation: Room 4.02",
        })):
            result = await agent.handle(state)
        assert result["status"] == "created"

    @pytest.mark.asyncio
    async def test_occupant_cannot_assign(self):
        agent = MaintenanceAgent()
        state = _make_state("Assign MT-0042 to John", role="occupant")
        state.intermediate_results["entities"] = [{"type": "ticket_id", "value": "MT-0042"}]
        result = await agent.handle(state)
        assert result["status"] == "denied"
        assert "occupant" in result["message"].lower()

    @pytest.mark.asyncio
    async def test_facility_manager_can_assign(self):
        agent = MaintenanceAgent()
        state = _make_state("Assign MT-0042 to John", role="facility_manager")
        state.intermediate_results["entities"] = [
            {"type": "ticket_id", "value": "MT-0042"},
            {"type": "assignee", "value": "John"},
        ]
        with patch.object(agent, "_assign_ticket", new=AsyncMock(return_value={
            "status": "assigned", "ticket_id": "MT-0042",
            "message": "📋 MT-0042 assigned to John",
        })):
            result = await agent.handle(state)
        assert result["status"] == "assigned"
