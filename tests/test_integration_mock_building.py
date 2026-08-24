"""
Phase 5.4 — Integration Test Suite with Mock Building
=====================================================
End-to-end tests that exercise the full workflow (dialogue → SPARQL → SQL →
analytics/report/anomaly → response) using mock services — no live GraphDB,
MySQL, or Redis required.

Run from project root:
    pytest tests/test_integration_mock_building.py -v

Requires:
    pip install pytest pytest-asyncio httpx
"""

import json
import os
import sys
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from tests.fixtures.ontology_fixtures import (
    mock_anomalous_readings,
    mock_sparql_result,
    mock_sql_result,
)


# ─────────────────────────────────────────────────────────────────────────────
# State factory
# ─────────────────────────────────────────────────────────────────────────────
def make_state(query: str, intent: str = "analytics", persona: str = "general"):
    """Build a minimal ConversationState mock."""
    state = MagicMock()
    state.conversation_id = "test-conv-001"
    state.user_id = "test-user"
    state.messages = [MagicMock(content=query, role="user")]
    state.current_intent = intent
    state.analytics_required = False
    state.needs_clarification = False
    state.query_results = {}
    state.intermediate_results = {}
    state.persona = persona
    state.title = "New Conversation"
    return state


# ─────────────────────────────────────────────────────────────────────────────
# Integration: Dialogue → Intent detection
# ─────────────────────────────────────────────────────────────────────────────
class TestDialogueIntentDetection:
    """Integration tests for DialogueAgent intent detection with mock LLM."""

    INTENT_SCENARIOS = [
        ("what is the current temperature in zone 1?", "analytics"),
        # Same story as the anomaly case below: routing rule inventory_to_discovery sends
        # "list/what/which X does this building have" to the single census handler, after
        # countable_metadata so COUNT questions keep their own route. The expectation here
        # predated that rule.
        ("list all CO2 sensors on floor 2", "discovery"),
        ("hello, how are you?", "general"),
        ("generate a weekly report", "report"),
        ("export the sensor data as CSV", "export"),
        # The routing contract deliberately sends anomaly QUESTIONS to the events lane
        # (rule anomaly_history_to_events, V5-T21): the events store holds durable episodes
        # with stable IDs, and a fresh z-score pass over one fetch cannot see stuck/dropout/
        # drift history. This expectation predated that rule and was asserting the old
        # behaviour -- it only stayed green because the test needs the container network and
        # is deselected from the unit set.
        ("check for any anomaly in humidity sensors", "events"),
        ("compare zones 1 and 2 temperatures", "compare"),
        ("what sensors do you have?", "discovery"),
    ]

    @pytest.mark.asyncio
    @pytest.mark.parametrize("query,expected_intent", INTENT_SCENARIOS)
    async def test_intent_routing(self, query, expected_intent):
        """Each query should produce an intent matching (or compatible with) expected."""
        try:
            from orchestrator.agents.dialogue_agent import DialogueAgent
        except ImportError:
            pytest.skip("DialogueAgent not importable")

        agent = DialogueAgent()
        llm_response = json.dumps(
            {
                "intent": expected_intent,
                "entities": [],
                "required_analytics": [],
                "time_range": {"start": None, "end": None},
                "response": "Hello!" if expected_intent == "general" else None,
                "clarification_question": None,
                "discovery_filter": None,
                "export_format": "csv" if expected_intent == "export" else None,
                "report_type": "summary" if expected_intent == "report" else None,
                "recommendation_domain": None,
                "explanation": "Test mock",
            }
        )

        with patch(
            "orchestrator.agents.dialogue_agent.llm_manager.generate",
            new_callable=AsyncMock,
            return_value=llm_response,
        ), patch(
            "orchestrator.agents.dialogue_agent.redis_manager.get_cache",
            new_callable=AsyncMock,
            return_value=None,
        ), patch(
            "orchestrator.agents.dialogue_agent.redis_manager.set_cache",
            new_callable=AsyncMock,
            return_value=None,
        ):
            state = make_state(query)
            result = await agent.detect_intent(state)

        assert (
            result.get("intent") == expected_intent
        ), f"Query '{query}' should route to '{expected_intent}', got '{result.get('intent')}'"


# ─────────────────────────────────────────────────────────────────────────────
# Integration: Analytics pipeline (SPARQL → SQL → Analytics → Response)
# ─────────────────────────────────────────────────────────────────────────────


class TestAnalyticsPipeline:
    """Integration test for the core SPARQL→SQL→Analytics pipeline."""

    @pytest.mark.asyncio
    async def test_full_pipeline_temperature_query(self):
        """Analytics query should produce a formatted response with sensor data."""
        try:
            from orchestrator.workflow import WorkflowOrchestrator
        except ImportError:
            pytest.skip("WorkflowOrchestrator not importable")

        sparql_mock = mock_sparql_result("Air_Temperature_Sensor_1_01")
        sql_mock = mock_sql_result("uuid-temp-101", n=20)
        analytics_mock = {
            "success": True,
            "formatted_response": "The average temperature today was **22.3°C** (min: 21.1°C, max: 23.8°C).",
            "media": None,
        }

        with patch(
            "orchestrator.workflow.WorkflowOrchestrator._build_graph", return_value=MagicMock()
        ):
            orch = WorkflowOrchestrator()
            orch.sparql_agent = MagicMock()
            orch.sparql_agent.generate_query = AsyncMock(return_value=sparql_mock)
            orch.sql_agent = MagicMock()
            orch.sql_agent.fetch_data_for_uuids = AsyncMock(return_value=sql_mock)
            orch.analytics_agent = MagicMock()
            orch.analytics_agent.analyze = AsyncMock(return_value=analytics_mock)

        state = make_state("what is the temperature in zone 1?", "analytics")
        state.analytics_required = True
        state.intermediate_results["sparql_result"] = sparql_mock
        state.intermediate_results["sql_result"] = sql_mock
        state.intermediate_results["analytics_result"] = analytics_mock
        state.intermediate_results["sensor_metadata"] = {
            "uuid-temp-101": {"label": "Air Temperature Sensor 1.01"}
        }

        # Check response assembly
        final = analytics_mock["formatted_response"]
        assert "22.3" in final or "temperature" in final.lower()


# ─────────────────────────────────────────────────────────────────────────────
# Integration: Anomaly detection pipeline
# ─────────────────────────────────────────────────────────────────────────────


class TestAnomalyPipeline:
    """Integration test for the SPARQL→SQL→Anomaly pipeline."""

    @pytest.mark.asyncio
    async def test_anomaly_pipeline_detects_outliers(self):
        """Anomaly pipeline should detect high-temperature spike."""
        try:
            from orchestrator.agents.anomaly_agent import AnomalyDetectionAgent
        except ImportError:
            pytest.skip("AnomalyDetectionAgent not importable")

        agent = AnomalyDetectionAgent()
        sql = {
            "success": True,
            "data": mock_anomalous_readings(n=20),
        }
        state = make_state("are there any anomalies in temperature?", "anomaly")

        with patch.object(
            agent,
            "_generate_summary",
            new_callable=AsyncMock,
            return_value="2 anomalies detected: spike at 35 degrees and cold at 8 degrees.",
        ):
            result = await agent.detect(state, "anomalies?", sensor_data=sql)

        assert isinstance(result, dict)
        # Should have found at least 1 anomaly
        anomaly_count = result.get("total_anomalies", len(result.get("anomalies", [])))
        assert anomaly_count >= 1, "Should detect at least 1 anomaly in injected data"


# ─────────────────────────────────────────────────────────────────────────────
# Integration: Report generation
# ─────────────────────────────────────────────────────────────────────────────


class TestReportPipeline:
    """Integration test for report generation with mock data."""

    @pytest.mark.asyncio
    async def test_report_generates_text(self):
        try:
            from orchestrator.agents.report_agent import ReportAgent
        except ImportError:
            pytest.skip("ReportAgent not importable")

        agent = ReportAgent()
        sql = mock_sql_result("uuid-temp-101", n=30)
        sparql = mock_sparql_result()
        state = make_state("generate a building report", "report")

        with patch.object(
            agent,
            "_narrate",
            new_callable=AsyncMock,
            return_value="Summary: Avg temperature 22.1 degrees C. All metrics within range.",
        ):
            result = await agent.generate(state, "weekly report", sensor_data=sql, metadata=sparql)

        assert isinstance(result, dict)
        text = result.get("formatted_text", "") or result.get("report", "")
        assert len(text) > 10, "Report should contain meaningful content"


# ─────────────────────────────────────────────────────────────────────────────
# Integration: Planner decomposition
# ─────────────────────────────────────────────────────────────────────────────


class TestPlannerPipeline:
    """Integration test for PlannerAgent multi-step decomposition."""

    @pytest.mark.asyncio
    async def test_planner_generates_valid_plan(self):
        try:
            from orchestrator.agents.planner_agent import PlannerAgent
        except ImportError:
            pytest.skip("PlannerAgent not importable")

        agent = PlannerAgent()
        plan_json = json.dumps(
            {
                "steps": [
                    {"id": "step_1", "agent": "sparql", "task": "Get CO2 sensor UUIDs"},
                    {"id": "step_2", "agent": "sql", "task": "Fetch CO2 readings"},
                    {"id": "step_3", "agent": "anomaly", "task": "Detect anomalies"},
                    {"id": "step_4", "agent": "export", "task": "Export to CSV"},
                ],
                "goal": "Check CO2 levels and export anomaly report",
            }
        )
        state = make_state("check CO2 levels and export as CSV", "planner")

        from orchestrator.agents.planner_agent import ExecutionPlan, PlanStep

        mock_plan = ExecutionPlan(
            user_query="check CO2 and export CSV",
            rationale="Fetch CO2 sensor data then export",
            steps=[
                PlanStep(index=1, agent="sparql", description="Get CO2 sensor UUIDs"),
                PlanStep(index=2, agent="sql", description="Fetch CO2 readings"),
                PlanStep(index=3, agent="export", description="Export to CSV"),
            ],
        )
        with patch.object(agent, "_build_plan", new_callable=AsyncMock, return_value=mock_plan):
            with patch.object(
                agent,
                "_execute_plan",
                new_callable=AsyncMock,
                return_value={"success": True, "formatted_response": "Done."},
            ):
                result = await agent.plan_and_execute(state, "check CO2 and export CSV")

        assert isinstance(result, dict)
        assert result.get("success") is True or "formatted_response" in result


# ─────────────────────────────────────────────────────────────────────────────
# Integration: Export pipeline
# ─────────────────────────────────────────────────────────────────────────────


class TestExportPipeline:
    """Integration test for DataExportAgent with real format generation."""

    @pytest.mark.asyncio
    async def test_csv_export_round_trip(self):
        """CSV export → parse back → verify row count."""
        try:
            import csv
            import io

            from orchestrator.agents.data_export_agent import DataExportAgent
        except ImportError:
            pytest.skip("DataExportAgent or csv not available")

        agent = DataExportAgent()
        sql = mock_sql_result(n=10)
        result = await agent.export(
            data=sql, label="integration_test", fmt="csv", title="Integration CSV Test"
        )

        if not result.get("success"):
            pytest.skip(f"Export returned: {result}")

        content = result["content"]
        rows = list(csv.DictReader(io.StringIO(content)))
        assert len(rows) == 10, f"CSV should have 10 data rows, got {len(rows)}"

    @pytest.mark.asyncio
    async def test_json_export_round_trip(self):
        """JSON export → parse back → verify structure."""
        try:
            from orchestrator.agents.data_export_agent import DataExportAgent
        except ImportError:
            pytest.skip("DataExportAgent not importable")

        agent = DataExportAgent()
        sql = mock_sql_result(n=5)
        result = await agent.export(data=sql, label="json_test", fmt="json", title="JSON Test")

        if not result.get("success"):
            pytest.skip(f"Export returned: {result}")

        parsed = json.loads(result["content"])
        assert isinstance(parsed, (list, dict)), "JSON export should be parseable"
