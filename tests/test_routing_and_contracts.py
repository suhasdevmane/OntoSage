"""
test_routing_and_contracts.py — E.6 + E.7
==========================================
E.6: Routing tests for all 14+ intents in _route_from_dialogue
E.7: Agent contract tests — each agent instantiates and exposes expected interface

Run from project root:
    pytest tests/test_routing_and_contracts.py -v
"""

import asyncio
import os
import sys
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))


# ─────────────────────────────────────────────────────────────────────────────
# E.6 — Intent routing tests
# ─────────────────────────────────────────────────────────────────────────────


class TestIntentRouting:
    """
    Validates _route_from_dialogue returns the correct next node for every
    intent the dialogue agent can classify.
    """

    def _make_state(self, intent: str):
        from shared.models import ConversationState

        state = ConversationState(
            conversation_id="test-conv-id",
            user_message="test query",
        )
        state.current_intent = intent
        return state

    def _make_orchestrator(self):
        from orchestrator.workflow import WorkflowOrchestrator

        orc = object.__new__(WorkflowOrchestrator)
        # Minimal init needed for routing
        orc.agent_memory = None
        orc.response_cache = None
        return orc

    def _route(self, intent: str) -> str:
        orc = self._make_orchestrator()
        state = self._make_state(intent)
        return orc._route_from_dialogue(state)

    # Direct-to-response intents
    def test_greeting_routes_to_response(self):
        assert self._route("greeting") == "response"

    def test_clarification_routes_to_response(self):
        assert self._route("clarification") == "response"

    def test_discovery_routes_to_response(self):
        assert self._route("discovery") == "response"

    def test_unknown_routes_to_response(self):
        assert self._route("unknown") == "response"

    def test_general_knowledge_routes_to_response(self):
        assert self._route("general_knowledge") == "response"

    def test_control_routes_to_response(self):
        assert self._route("control") == "response"

    # SPARQL-bound intents
    def test_sparql_routes_to_sparql(self):
        assert self._route("sparql") == "sparql"

    def test_metadata_routes_to_sparql(self):
        assert self._route("metadata") == "sparql"

    def test_analytics_routes_to_sparql(self):
        assert self._route("analytics") == "sparql"

    def test_compare_routes_to_sparql(self):
        assert self._route("compare") == "sparql"

    def test_trend_routes_to_sparql(self):
        assert self._route("trend") == "sparql"

    def test_recommend_routes_to_sparql(self):
        assert self._route("recommend") == "sparql"

    def test_compliance_routes_to_sparql(self):
        assert self._route("compliance") == "sparql"

    def test_anomaly_routes_to_sparql(self):
        # anomaly → sparql (needs UUIDs first)
        assert self._route("anomaly") == "sparql"

    # Planner-bound intents
    def test_planner_routes_to_planner(self):
        assert self._route("planner") == "planner"

    def test_report_routes_to_planner(self):
        assert self._route("report") == "planner"

    # SQL direct
    def test_sql_routes_to_sql(self):
        assert self._route("sql") == "sql"

    # Export
    def test_export_routes_to_export(self):
        assert self._route("export") == "export"

    # Visualization
    def test_visualization_routes_to_visualization(self):
        assert self._route("visualization") == "visualization"

    # Fallback
    def test_unrecognized_intent_routes_to_response(self):
        assert self._route("completely_unknown_xyz") == "response"

    # Control and maintenance intents (Sprint 2)
    def test_control_routes_to_control(self):
        assert self._route("control") == "control"

    def test_maintenance_routes_to_maintenance(self):
        assert self._route("maintenance") == "maintenance"


# ─────────────────────────────────────────────────────────────────────────────
# E.6 cont. — SPARQL template coverage for the 5 new patterns (E.5)
# ─────────────────────────────────────────────────────────────────────────────


class TestSPARQLTemplateCoverage:
    """Verify new template patterns return non-None SPARQL for key queries."""

    def _agent(self):
        from orchestrator.agents.sparql_agent import SPARQLAgent

        return SPARQLAgent()

    def test_template_floor_listing(self):
        agent = self._agent()
        result = agent._template_sparql("list all floors", [])
        assert result is not None
        assert "Floor" in result or "Level" in result

    def test_template_floor_count(self):
        agent = self._agent()
        result = agent._template_sparql("how many floors does the building have?", [])
        assert result is not None
        assert "COUNT" in result

    def test_template_zone_listing(self):
        agent = self._agent()
        result = agent._template_sparql("list all zones in the building", [])
        assert result is not None
        assert "Zone" in result or "Room" in result or "Space" in result

    def test_template_zone_count(self):
        agent = self._agent()
        result = agent._template_sparql("how many rooms are there?", [])
        assert result is not None
        assert "COUNT" in result

    def test_template_ahu_listing(self):
        agent = self._agent()
        result = agent._template_sparql("list all air handling units", [])
        assert result is not None
        assert "Air_Handler" in result or "AHU" in result or "air handler" in result.lower()

    def test_template_hvac_listing(self):
        agent = self._agent()
        result = agent._template_sparql("show me all HVAC equipment", [])
        assert result is not None
        assert "HVAC" in result

    def test_template_vav_listing(self):
        agent = self._agent()
        result = agent._template_sparql("show VAV boxes", [])
        assert result is not None
        assert "VAV" in result

    def test_template_hierarchy(self):
        agent = self._agent()
        result = agent._template_sparql("show building hierarchy", [])
        assert result is not None
        assert "hasPart" in result or "hasLocation" in result or "parent" in result.lower()

    def test_template_sensors_in_location_entity(self):
        agent = self._agent()
        # bldg: entity means "in this location" pattern
        result = agent._template_sparql("what sensors are in bldg:Zone_5?", ["bldg:Zone_5"])
        assert result is not None
        assert "bldg:Zone_5" in result

    def test_template_building_name(self):
        agent = self._agent()
        result = agent._template_sparql("what is the name of this building?", [])
        assert result is not None
        assert "Building" in result


# ─────────────────────────────────────────────────────────────────────────────
# E.7 — Agent contract tests
# ─────────────────────────────────────────────────────────────────────────────


class TestDialogueAgentContract:
    def test_instantiates(self):
        from orchestrator.agents.dialogue_agent import DialogueAgent

        agent = DialogueAgent()
        assert agent is not None

    def test_has_detect_intent(self):
        from orchestrator.agents.dialogue_agent import DialogueAgent

        agent = DialogueAgent()
        assert hasattr(agent, "detect_intent") or hasattr(agent, "process")

    def test_has_process_or_detect(self):
        from orchestrator.agents.dialogue_agent import DialogueAgent

        agent = DialogueAgent()
        assert hasattr(agent, "detect_intent") or hasattr(agent, "analyze")


class TestSPARQLAgentContract:
    def test_instantiates(self):
        from orchestrator.agents.sparql_agent import SPARQLAgent

        agent = SPARQLAgent()
        assert agent is not None

    def test_has_generate_sparql(self):
        from orchestrator.agents.sparql_agent import SPARQLAgent

        agent = SPARQLAgent()
        assert hasattr(agent, "_generate_sparql")

    def test_has_template_sparql(self):
        from orchestrator.agents.sparql_agent import SPARQLAgent

        agent = SPARQLAgent()
        assert hasattr(agent, "_template_sparql")
        assert callable(agent._template_sparql)

    def test_has_prompt_builder(self):
        from orchestrator.agents.sparql_agent import SPARQLAgent
        from orchestrator.services.prompt_builder import PromptBuilder

        agent = SPARQLAgent()
        assert hasattr(agent, "_prompt_builder")
        assert isinstance(agent._prompt_builder, PromptBuilder)

    def test_has_correction_engine(self):
        from orchestrator.agents.sparql_agent import SPARQLAgent
        from orchestrator.services.self_correction_engine import SelfCorrectionEngine

        agent = SPARQLAgent()
        assert hasattr(agent, "_correction_engine")
        assert isinstance(agent._correction_engine, SelfCorrectionEngine)

    def test_has_prefix_block(self):
        from orchestrator.agents.sparql_agent import SPARQLAgent

        agent = SPARQLAgent()
        block = agent._prefix_block()
        assert "PREFIX" in block
        assert "brick" in block


class TestSQLAgentContract:
    def test_instantiates(self):
        from orchestrator.agents.sql_agent import SQLAgent

        agent = SQLAgent()
        assert agent is not None

    def test_has_generate_sql(self):
        from orchestrator.agents.sql_agent import SQLAgent

        agent = SQLAgent()
        assert hasattr(agent, "_generate_sql")

    def test_has_prompt_builder(self):
        from orchestrator.agents.sql_agent import SQLAgent
        from orchestrator.services.prompt_builder import PromptBuilder

        agent = SQLAgent()
        assert hasattr(agent, "_prompt_builder")
        assert isinstance(agent._prompt_builder, PromptBuilder)


class TestAnalyticsAgentContract:
    def test_instantiates(self):
        from orchestrator.agents.analytics_agent import AnalyticsAgent

        agent = AnalyticsAgent()
        assert agent is not None

    def test_has_analyze_method(self):
        from orchestrator.agents.analytics_agent import AnalyticsAgent

        agent = AnalyticsAgent()
        assert hasattr(agent, "analyze") or hasattr(agent, "run")


class TestAnomalyAgentContract:
    def test_instantiates(self):
        from orchestrator.agents.anomaly_agent import AnomalyDetectionAgent

        agent = AnomalyDetectionAgent()
        assert agent is not None

    def test_has_detect(self):
        from orchestrator.agents.anomaly_agent import AnomalyDetectionAgent

        agent = AnomalyDetectionAgent()
        assert hasattr(agent, "detect")
        assert asyncio.iscoroutinefunction(agent.detect)

    def test_has_threshold_detection(self):
        from orchestrator.agents.anomaly_agent import AnomalyDetectionAgent

        agent = AnomalyDetectionAgent()
        assert hasattr(agent, "_threshold_detection")

    def test_has_zscore_detection(self):
        from orchestrator.agents.anomaly_agent import AnomalyDetectionAgent

        agent = AnomalyDetectionAgent()
        assert hasattr(agent, "_zscore_detection")

    def test_has_spike_detection(self):
        from orchestrator.agents.anomaly_agent import AnomalyDetectionAgent

        agent = AnomalyDetectionAgent()
        assert hasattr(agent, "_spike_detection")

    def test_has_merge_anomalies(self):
        from orchestrator.agents.anomaly_agent import AnomalyDetectionAgent

        agent = AnomalyDetectionAgent()
        assert hasattr(agent, "_merge_anomalies")


class TestReportAgentContract:
    def test_instantiates(self):
        from orchestrator.agents.report_agent import ReportAgent

        agent = ReportAgent()
        assert agent is not None

    def test_has_generate(self):
        from orchestrator.agents.report_agent import ReportAgent

        agent = ReportAgent()
        assert hasattr(agent, "generate")
        assert asyncio.iscoroutinefunction(agent.generate)

    def test_has_summarize_readings(self):
        from orchestrator.agents.report_agent import ReportAgent

        agent = ReportAgent()
        assert hasattr(agent, "_summarize_readings")

    def test_has_detect_anomalies(self):
        from orchestrator.agents.report_agent import ReportAgent

        agent = ReportAgent()
        assert hasattr(agent, "_detect_anomalies")


class TestDataExportAgentContract:
    def test_instantiates(self):
        from orchestrator.agents.data_export_agent import DataExportAgent

        agent = DataExportAgent()
        assert agent is not None

    def test_has_export(self):
        from orchestrator.agents.data_export_agent import DataExportAgent

        agent = DataExportAgent()
        assert hasattr(agent, "export")
        assert asyncio.iscoroutinefunction(agent.export)

    def test_export_result_has_required_keys(self):
        import asyncio as _asyncio

        from orchestrator.agents.data_export_agent import DataExportAgent

        agent = DataExportAgent()
        result = _asyncio.get_event_loop().run_until_complete(
            agent.export([{"sensor": "s1", "value": 1.0}], label="contract_test", fmt="json")
        )
        for key in ("success", "format", "filename", "content", "size_bytes"):
            assert key in result, f"Missing key: {key}"


class TestPlannerAgentContract:
    def test_instantiates(self):
        from orchestrator.agents.planner_agent import PlannerAgent

        agent = PlannerAgent()
        assert agent is not None

    def test_has_plan_and_execute(self):
        from orchestrator.agents.planner_agent import PlannerAgent

        agent = PlannerAgent()
        assert hasattr(agent, "plan_and_execute")
        assert asyncio.iscoroutinefunction(agent.plan_and_execute)


class TestMySQLAdapterContract:
    def test_instantiates(self):
        from orchestrator.services.adapters.mysql_adapter import MySQLAdapter

        adapter = MySQLAdapter()
        assert adapter is not None

    def test_has_pool_attribute(self):
        from orchestrator.services.adapters.mysql_adapter import MySQLAdapter

        adapter = MySQLAdapter()
        assert hasattr(adapter, "_pool")
        assert adapter._pool is None  # not connected yet

    def test_has_ensure_pool(self):
        from orchestrator.services.adapters.mysql_adapter import MySQLAdapter

        adapter = MySQLAdapter()
        assert hasattr(adapter, "_ensure_pool")
        assert asyncio.iscoroutinefunction(adapter._ensure_pool)

    def test_has_close(self):
        from orchestrator.services.adapters.mysql_adapter import MySQLAdapter

        adapter = MySQLAdapter()
        assert hasattr(adapter, "close")
        assert asyncio.iscoroutinefunction(adapter.close)

    def test_has_execute_query(self):
        from orchestrator.services.adapters.mysql_adapter import MySQLAdapter

        adapter = MySQLAdapter()
        assert hasattr(adapter, "execute_query")

    def test_validate_query_allows_select(self):
        from orchestrator.services.adapters.mysql_adapter import MySQLAdapter

        adapter = MySQLAdapter()
        assert adapter.validate_query("SELECT * FROM sensor_data LIMIT 10") is True

    def test_validate_query_rejects_drop(self):
        from orchestrator.services.adapters.mysql_adapter import MySQLAdapter

        adapter = MySQLAdapter()
        with pytest.raises(ValueError):
            adapter.validate_query("DROP TABLE sensor_data")

    def test_get_dialect_hints_returns_mysql_info(self):
        from orchestrator.services.adapters.mysql_adapter import MySQLAdapter

        adapter = MySQLAdapter()
        hints = adapter.get_dialect_hints()
        assert "MySQL" in hints
        assert "backtick" in hints.lower() or "`" in hints


class TestPromptBuilderContract:
    def test_singleton_factory(self):
        from orchestrator.services.prompt_builder import get_prompt_builder

        b1 = get_prompt_builder()
        b2 = get_prompt_builder()
        assert b1 is b2

    def test_sparql_hints_non_empty(self):
        from orchestrator.services.prompt_builder import PromptBuilder

        hints = PromptBuilder().sparql_system_hints()
        assert isinstance(hints, str) and len(hints) > 50

    def test_sql_dialect_hints_non_empty(self):
        from orchestrator.services.prompt_builder import PromptBuilder

        hints = PromptBuilder().sql_dialect_hints()
        assert isinstance(hints, str) and len(hints) > 10

    def test_intent_context_hints_non_empty(self):
        from orchestrator.services.prompt_builder import PromptBuilder

        hints = PromptBuilder().intent_context_hints()
        assert isinstance(hints, str) and len(hints) > 10

    def test_sparql_prefix_block_has_prefix_keyword(self):
        from orchestrator.services.prompt_builder import PromptBuilder

        block = PromptBuilder().sparql_prefix_block()
        assert "PREFIX" in block


class TestPrometheusMetrics:
    """E.9: /metrics endpoint is registered and returns valid content."""

    def test_metrics_endpoint_registered(self):
        from orchestrator.main import app

        routes = [r.path for r in app.routes]
        assert "/metrics" in routes

    @pytest.mark.asyncio
    async def test_metrics_returns_200_or_503(self):
        from httpx import ASGITransport, AsyncClient

        from orchestrator.main import app

        transport = ASGITransport(app=app)
        async with AsyncClient(transport=transport, base_url="http://test") as client:
            resp = await client.get("/metrics")
        assert resp.status_code in (200, 503)

    @pytest.mark.asyncio
    async def test_metrics_content_type_is_text(self):
        from httpx import ASGITransport, AsyncClient

        from orchestrator.main import app

        transport = ASGITransport(app=app)
        async with AsyncClient(transport=transport, base_url="http://test") as client:
            resp = await client.get("/metrics")
        assert "text/" in resp.headers.get("content-type", "")


class TestSPARQLValidatorContract:
    def test_instantiates(self):
        from orchestrator.services.sparql_validator import SPARQLValidator

        v = SPARQLValidator()
        assert v is not None

    def test_validate_syntax_returns_tuple(self):
        from orchestrator.services.sparql_validator import SPARQLValidator

        v = SPARQLValidator()
        result = v.validate_syntax("SELECT ?s WHERE { ?s a <https://example.org/Foo> }")
        assert isinstance(result, tuple) and len(result) == 2

    def test_empty_query_returns_false(self):
        from orchestrator.services.sparql_validator import SPARQLValidator

        v = SPARQLValidator()
        ok, err = v.validate_syntax("")
        assert ok is False
        assert err is not None

    def test_forbidden_update_returns_false(self):
        from orchestrator.services.sparql_validator import SPARQLValidator

        v = SPARQLValidator()
        ok, _ = v.validate_syntax("DELETE { ?s ?p ?o } WHERE { ?s ?p ?o }")
        assert ok is False
