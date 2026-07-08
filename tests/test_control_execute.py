"""
T25 — Tests for the config-gated control execution path.

Two paths:
  A) Building has sim driver + user has control:write → queue pending approval
  B) Building has no driver OR user lacks permission → decline with explanation
"""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock, patch, patch

import pytest

from orchestrator.agents.control_agent import ControlAgent
from shared.models import ConversationState


def _make_state(
    intent: str = "control",
    role: str = "admin",
    user_id: str = "alice",
    building_id: str = "bldg1",
    query: str = "set room 5.01 setpoint to 22",
    entities: list = None,
) -> ConversationState:
    state = ConversationState(conversation_id="test-conv", user_message=query)
    state.current_intent = intent
    state.intermediate_results.update(
        {
            "intent": intent,
            "user_role": role,
            "user_id": user_id,
            "building_id": building_id,
            "user_query": query,
            "entities": entities
            or [
                {"type": "device", "value": "room 5.01 setpoint"},
                {"type": "action", "value": "set"},
                {"type": "target_value", "value": "22"},
            ],
        }
    )
    return state


# ── Path A: driver present + user has control:write → pending approval ────────


class TestControlWithDriver:
    @pytest.mark.asyncio
    async def test_admin_with_driver_queues_approval(self):
        agent = ControlAgent()
        state = _make_state(role="admin")

        mock_driver = AsyncMock()
        mock_driver.capabilities = AsyncMock(return_value=["urn:bldg1:VAV-501-SP"])

        mock_registry = MagicMock()
        mock_registry.driver_for = MagicMock(return_value=mock_driver)

        mock_approval_store = AsyncMock()
        mock_approval_store.create_pending = AsyncMock(return_value="abc12345")

        with patch(
            "orchestrator.agents.control_agent.get_actuation_registry",
            return_value=mock_registry,
        ), patch(
            "orchestrator.agents.control_agent.get_approval_store",
            return_value=mock_approval_store,
        ):
            result = await agent.execute_command(state)

        assert result["status"] == "pending_approval"
        assert "abc12345" in result["message"]
        assert "approve" in result["message"]
        assert result["approval_id"] == "abc12345"

    @pytest.mark.asyncio
    async def test_facility_manager_with_driver_queues_approval(self):
        agent = ControlAgent()
        state = _make_state(role="facility_manager")

        mock_driver = AsyncMock()
        mock_driver.capabilities = AsyncMock(return_value=["urn:bldg1:LIGHTING-3F-SP"])

        mock_registry = MagicMock()
        mock_registry.driver_for = MagicMock(return_value=mock_driver)

        mock_approval_store = AsyncMock()
        mock_approval_store.create_pending = AsyncMock(return_value="def67890")

        with patch(
            "orchestrator.agents.control_agent.get_actuation_registry",
            return_value=mock_registry,
        ), patch(
            "orchestrator.agents.control_agent.get_approval_store",
            return_value=mock_approval_store,
        ):
            result = await agent.execute_command(state)

        assert result["status"] == "pending_approval"

    @pytest.mark.asyncio
    async def test_approval_message_contains_point_uri_and_value(self):
        agent = ControlAgent()
        state = _make_state(
            role="admin",
            query="set VAV-501 setpoint to 22",
            entities=[
                {"type": "device", "value": "VAV-501"},
                {"type": "target_value", "value": "22"},
            ],
        )

        mock_driver = AsyncMock()
        mock_driver.capabilities = AsyncMock(return_value=["urn:bldg1:VAV-501-SP"])
        mock_registry = MagicMock()
        mock_registry.driver_for = MagicMock(return_value=mock_driver)
        mock_approval_store = AsyncMock()
        mock_approval_store.create_pending = AsyncMock(return_value="abc00001")

        with patch(
            "orchestrator.agents.control_agent.get_actuation_registry",
            return_value=mock_registry,
        ), patch(
            "orchestrator.agents.control_agent.get_approval_store",
            return_value=mock_approval_store,
        ):
            result = await agent.execute_command(state)

        assert "VAV-501-SP" in result["message"]
        assert "22" in result["message"]

    @pytest.mark.asyncio
    async def test_log_entry_status_pending_approval(self):
        agent = ControlAgent()
        state = _make_state(role="admin")

        mock_driver = AsyncMock()
        mock_driver.capabilities = AsyncMock(return_value=["urn:bldg1:VAV-501-SP"])
        mock_registry = MagicMock()
        mock_registry.driver_for = MagicMock(return_value=mock_driver)
        mock_approval_store = AsyncMock()
        mock_approval_store.create_pending = AsyncMock(return_value="aaa11111")

        with patch(
            "orchestrator.agents.control_agent.get_actuation_registry",
            return_value=mock_registry,
        ), patch(
            "orchestrator.agents.control_agent.get_approval_store",
            return_value=mock_approval_store,
        ):
            result = await agent.execute_command(state)

        assert result["log_entry"]["status"] == "pending_approval"


# ── Path B: no driver → honest decline ───────────────────────────────────────


class TestControlWithoutDriver:
    @pytest.mark.asyncio
    async def test_null_driver_declines_with_explanation(self):
        agent = ControlAgent()
        state = _make_state(role="admin")

        mock_driver = AsyncMock()
        mock_driver.capabilities = AsyncMock(return_value=[])  # no writable points
        mock_registry = MagicMock()
        mock_registry.driver_for = MagicMock(return_value=mock_driver)

        with patch(
            "orchestrator.agents.control_agent.get_actuation_registry",
            return_value=mock_registry,
        ):
            result = await agent.execute_command(state)

        assert result["status"] == "denied"
        assert "not enabled" in result["message"].lower() or "alert" in result["message"].lower()

    @pytest.mark.asyncio
    async def test_readonly_user_declines_with_permission_message(self):
        agent = ControlAgent()
        state = _make_state(role="readonly")

        mock_driver = AsyncMock()
        mock_driver.capabilities = AsyncMock(return_value=["urn:bldg1:VAV-501-SP"])
        mock_registry = MagicMock()
        mock_registry.driver_for = MagicMock(return_value=mock_driver)

        with patch(
            "orchestrator.agents.control_agent.get_actuation_registry",
            return_value=mock_registry,
        ):
            result = await agent.execute_command(state)

        assert result["status"] == "denied"
        assert "permission" in result["message"].lower()

    @pytest.mark.asyncio
    async def test_occupant_role_declines(self):
        agent = ControlAgent()
        state = _make_state(role="occupant")

        mock_driver = AsyncMock()
        mock_driver.capabilities = AsyncMock(return_value=["urn:bldg1:VAV-501-SP"])
        mock_registry = MagicMock()
        mock_registry.driver_for = MagicMock(return_value=mock_driver)

        with patch(
            "orchestrator.agents.control_agent.get_actuation_registry",
            return_value=mock_registry,
        ):
            result = await agent.execute_command(state)

        assert result["status"] == "denied"


# ── Approval execution path ───────────────────────────────────────────────────


class TestApprovalExecution:
    @pytest.mark.asyncio
    async def test_approve_command_executes_sim_driver(self):
        agent = ControlAgent()
        state = _make_state(
            role="facility_manager",
            query="approve abc12345",
        )

        from orchestrator.services.actuation.base import ActuationResult

        mock_driver = AsyncMock()
        mock_driver.set_point = AsyncMock(
            return_value=ActuationResult(
                success=True,
                point_uri="urn:bldg1:VAV-501-SP",
                value="22",
                audit_id="audit-xyz",
                message="[SIM] Would set urn:bldg1:VAV-501-SP = 22. Audit id: audit-xyz",
            )
        )
        mock_registry = MagicMock()
        mock_registry.driver_for = MagicMock(return_value=mock_driver)

        mock_approval_store = AsyncMock()
        mock_approval_store.get_pending = AsyncMock(
            return_value={
                "approval_id": "abc12345",
                "building_id": "bldg1",
                "user_id": "alice",
                "point_uri": "urn:bldg1:VAV-501-SP",
                "value": "22",
                "status": "pending",
            }
        )
        mock_approval_store.approve = AsyncMock(return_value=True)

        with patch(
            "orchestrator.agents.control_agent.get_actuation_registry",
            return_value=mock_registry,
        ), patch(
            "orchestrator.agents.control_agent.get_approval_store",
            return_value=mock_approval_store,
        ):
            result = await agent.execute_command(state)

        assert result["status"] == "approved"
        assert "audit-xyz" in result["message"]
        mock_driver.set_point.assert_called_once()

    @pytest.mark.asyncio
    async def test_approve_not_found_returns_error(self):
        agent = ControlAgent()
        # "deadbeef" is valid hex (8 chars) so the regex matches, but the store returns None
        state = _make_state(role="facility_manager", query="approve deadbeef")

        mock_driver = AsyncMock()
        mock_registry = MagicMock()
        mock_registry.driver_for = MagicMock(return_value=mock_driver)

        mock_approval_store = AsyncMock()
        mock_approval_store.get_pending = AsyncMock(return_value=None)

        with patch(
            "orchestrator.agents.control_agent.get_actuation_registry",
            return_value=mock_registry,
        ), patch(
            "orchestrator.agents.control_agent.get_approval_store",
            return_value=mock_approval_store,
        ):
            result = await agent.execute_command(state)

        assert result["status"] == "error"
        assert "expired" in result["message"].lower() or "no pending" in result["message"].lower()

    @pytest.mark.asyncio
    async def test_operator_cannot_approve(self):
        agent = ControlAgent()
        state = _make_state(role="operator", query="approve abc12345")

        mock_driver = AsyncMock()
        mock_registry = MagicMock()
        mock_registry.driver_for = MagicMock(return_value=mock_driver)

        with patch(
            "orchestrator.agents.control_agent.get_actuation_registry",
            return_value=mock_registry,
        ):
            result = await agent.execute_command(state)

        assert result["status"] == "denied"
        assert "facility manager" in result["message"].lower()


# ── Entity-shape tolerance (crash fix 2026-06-12) ─────────────────────────────
# The dialogue LLM emits entities as EITHER dicts ({"type": ..., "value": ...})
# OR plain strings ("room 5.01"). String entities crashed execute_command with
# AttributeError ("str object has no attribute get") on every live control
# command, collapsing the whole T25 path into the generic failure response.


class TestStringEntityShapes:
    @pytest.mark.asyncio
    async def test_decline_path_with_string_entities(self):
        """Occupant decline must work when entities are plain strings."""
        agent = ControlAgent()
        state = _make_state(
            role="occupant",
            entities=["room 5.01", "22 degrees"],
        )

        mock_driver = AsyncMock()
        mock_driver.capabilities = AsyncMock(return_value=["urn:bldg1:VAV-501-SP"])
        mock_registry = MagicMock()
        mock_registry.driver_for = MagicMock(return_value=mock_driver)

        with patch(
            "orchestrator.agents.control_agent.get_actuation_registry",
            return_value=mock_registry,
        ):
            result = await agent.execute_command(state)

        assert result["status"] == "denied"
        assert "permission" in result["message"].lower()

    @pytest.mark.asyncio
    async def test_approval_path_with_string_entities(self):
        """Approval queueing must work when entities are plain strings."""
        agent = ControlAgent()
        state = _make_state(role="admin", entities=["room 5.01", "22"])

        mock_driver = AsyncMock()
        mock_driver.capabilities = AsyncMock(return_value=["urn:bldg1:VAV-501-SP"])
        mock_registry = MagicMock()
        mock_registry.driver_for = MagicMock(return_value=mock_driver)
        mock_approval_store = AsyncMock()
        mock_approval_store.create_pending = AsyncMock(return_value="aa11bb22")

        with patch(
            "orchestrator.agents.control_agent.get_actuation_registry",
            return_value=mock_registry,
        ), patch(
            "orchestrator.agents.control_agent.get_approval_store",
            return_value=mock_approval_store,
        ):
            result = await agent.execute_command(state)

        assert result["status"] == "pending_approval"

    @pytest.mark.asyncio
    async def test_maintenance_agent_with_string_entities(self):
        """MaintenanceAgent CREATE must tolerate string entities too."""
        from orchestrator.agents.maintenance_agent import MaintenanceAgent

        state = _make_state(
            intent="maintenance",
            role="facility_manager",
            query="the radiator in room 3.01 is broken",
            entities=["radiator", "room 3.01"],
        )
        result = await MaintenanceAgent().handle(state)
        assert result["status"] == "created"
        assert result["location"] == "Unknown"
        assert "radiator" in result["description"]


class TestApproveFromMessages:
    @pytest.mark.asyncio
    async def test_approve_id_detected_from_messages(self):
        """'approve <id>' must be detected from state.messages — the
        intermediate_results['user_query'] key is never populated by any
        endpoint, so the approval round-trip was unreachable (fix 2026-06-12)."""
        from shared.models import Message

        agent = ControlAgent()
        state = _make_state(role="facility_manager", query="approve abc12345")
        # Simulate the real pipeline: user_query key absent, message present
        state.intermediate_results.pop("user_query", None)
        state.messages = [Message(role="user", content="approve abc12345")]

        mock_store = AsyncMock()
        mock_store.get_pending = AsyncMock(return_value=None)  # expired/unknown id

        with patch(
            "orchestrator.agents.control_agent.get_approval_store",
            return_value=mock_store,
        ):
            result = await agent.execute_command(state)

        # Reaching the approval handler (instead of falling through to the
        # decline/queue path) proves the id was extracted from messages.
        mock_store.get_pending.assert_awaited_once_with("bldg1", "abc12345")
        assert result["status"] in ("denied", "error", "not_found", "expired")


class TestApproveRegexToleratesCorefRewrite:
    def test_plain_approve(self):
        from orchestrator.agents.control_agent import _APPROVE_RE

        assert _APPROVE_RE.search("approve 606ba770").group(1) == "606ba770"

    def test_coref_rewritten_approve(self):
        """The co-reference rewriter expands 'approve 606ba770' into prose with
        the id up to ~40 chars later (fix 2026-06-12)."""
        from orchestrator.agents.control_agent import _APPROVE_RE

        msg = "Can you please approve the command with ID 606ba770 to set the setpoint"
        m = _APPROVE_RE.search(msg)
        assert m and m.group(1) == "606ba770"

    def test_no_false_match_without_id(self):
        from orchestrator.agents.control_agent import _APPROVE_RE

        assert _APPROVE_RE.search("do you approve of this building design?") is None
