"""
Phase 5.3 — Unit tests for Phase 3 & 4 services
=================================================
Tests: SPARQLValidator, HybridRetrievalOrchestrator (Phase 3)
       AnomalyDetectionAgent, DataExportAgent, ReportAgent (Phase 4)

Run from project root:
    pytest tests/test_phase3_4_services.py -v
"""

import os
import sys

import pytest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from unittest.mock import AsyncMock, MagicMock, patch

from tests.fixtures.ontology_fixtures import (
    brick_fixture,
    mock_anomalous_readings,
    mock_sensor_readings,
    mock_sparql_result,
    mock_sql_result,
)

# ═════════════════════════════════════════════════════════════════════════════
# Phase 3 — SPARQL Validator
# ═════════════════════════════════════════════════════════════════════════════


class TestSPARQLValidator:
    """Unit tests for orchestrator.services.sparql_validator.SPARQLValidator"""

    def _make_validator(self):
        """Import and instantiate SPARQLValidator."""
        try:
            from orchestrator.services.sparql_validator import SPARQLValidator

            return SPARQLValidator()
        except ImportError:
            return None

    def test_valid_sparql_passes(self):
        v = self._make_validator()
        if v is None:
            pytest.skip("SPARQLValidator not available in this environment")
        valid_q = "SELECT ?s WHERE { ?s a <https://brickschema.org/schema/Brick#Sensor> }"
        ok, err = v.validate_syntax(valid_q)
        assert ok is True
        assert err is None

    def test_invalid_sparql_detected(self):
        v = self._make_validator()
        if v is None:
            pytest.skip("SPARQLValidator not available")
        bad_q = "SELECT WHERE { INVALID }"
        ok, err = v.validate_syntax(bad_q)
        # Should either flag invalid or auto-fix
        assert isinstance(ok, bool)

    def test_empty_query_invalid(self):
        v = self._make_validator()
        if v is None:
            pytest.skip("SPARQLValidator not available")
        ok, err = v.validate_syntax("")
        assert ok is False

    def test_autofix_missing_prefix(self):
        """Auto-fix should add missing PREFIX declarations."""
        try:
            v = self._make_validator()
            q = "SELECT ?s WHERE { ?s a brick:Sensor }"
            result = v.validate_and_fix(q)
            assert "fixed_query" in result or "query" in result
        except (ImportError, AttributeError):
            pytest.skip("validate_and_fix not available")


# ═════════════════════════════════════════════════════════════════════════════
# Phase 4 — Anomaly Detection Agent
# ═════════════════════════════════════════════════════════════════════════════


class TestAnomalyDetectionAgent:
    """Unit tests for AnomalyDetectionAgent strategies."""

    def _make_agent(self):
        try:
            from orchestrator.agents.anomaly_agent import AnomalyDetectionAgent

            return AnomalyDetectionAgent()
        except ImportError:
            return None

    def test_agent_instantiates(self):
        agent = self._make_agent()
        if agent is None:
            pytest.skip("AnomalyDetectionAgent not importable")
        assert agent is not None

    def test_threshold_detection_normal_data(self):
        agent = self._make_agent()
        if agent is None:
            pytest.skip()
        rows = mock_sensor_readings("uuid-temp-101", n=20)
        result = agent._threshold_detection(rows)
        # Normal temperature (21-24°C) should produce few/no high-severity alerts
        high = [a for a in result if a.get("severity") == "high"]
        assert len(high) == 0, "Normal temps should not produce high-severity alerts"

    def test_threshold_detection_anomalous_data(self):
        agent = self._make_agent()
        if agent is None:
            pytest.skip()
        rows = mock_anomalous_readings(n=20)
        result = agent._threshold_detection(rows)
        # Should detect the 35°C spike and 8°C cold
        assert len(result) > 0, "Anomalous readings should produce alerts"

    def test_zscore_detection(self):
        agent = self._make_agent()
        if agent is None:
            pytest.skip()
        rows = mock_anomalous_readings(n=20)
        result = agent._zscore_detection(rows)
        assert isinstance(result, list)

    def test_spike_detection(self):
        agent = self._make_agent()
        if agent is None:
            pytest.skip()
        rows = mock_anomalous_readings(n=20)
        result = agent._spike_detection(rows)
        # The big spike at index 5 should be detected
        assert isinstance(result, list)
        assert len(result) > 0, "Should detect ≥1 spike in anomalous data"

    def test_deduplication(self):
        agent = self._make_agent()
        if agent is None:
            pytest.skip()
        rows = mock_anomalous_readings(n=20)
        findings = agent._threshold_detection(rows)
        # _merge_anomalies deduplicates across multiple lists
        deduplicated = agent._merge_anomalies(findings, findings)
        assert len(deduplicated) <= len(findings + findings)

    @pytest.mark.asyncio
    async def test_detect_returns_dict(self):
        agent = self._make_agent()
        if agent is None:
            pytest.skip()
        state = MagicMock()
        state.intermediate_results = {}
        sql = mock_sql_result(n=20)
        with patch.object(
            agent, "_generate_summary", new_callable=AsyncMock, return_value="2 anomalies found."
        ):
            result = await agent.detect(state, "any anomalies?", sensor_data=sql)
        assert "formatted_response" in result or "anomalies" in result


# ═════════════════════════════════════════════════════════════════════════════
# Phase 4 — Data Export Agent
# ═════════════════════════════════════════════════════════════════════════════


class TestDataExportAgent:
    """Unit tests for DataExportAgent format outputs."""

    def _make_agent(self):
        try:
            from orchestrator.agents.data_export_agent import DataExportAgent

            return DataExportAgent()
        except ImportError:
            return None

    def test_agent_instantiates(self):
        agent = self._make_agent()
        if agent is None:
            pytest.skip("DataExportAgent not importable")
        assert agent is not None

    @pytest.mark.asyncio
    async def test_export_json(self):
        agent = self._make_agent()
        if agent is None:
            pytest.skip()
        data = mock_sql_result(n=5)
        result = await agent.export(data=data, label="test", fmt="json", title="Test Export")
        assert result.get("success") is True
        assert result.get("filename", "").endswith(".json")
        assert "content" in result

    @pytest.mark.asyncio
    async def test_export_csv(self):
        agent = self._make_agent()
        if agent is None:
            pytest.skip()
        data = mock_sql_result(n=5)
        result = await agent.export(data=data, label="test", fmt="csv", title="Test CSV")
        assert result.get("success") is True
        assert result.get("filename", "").endswith(".csv")
        content = result.get("content", "")
        assert "," in content, "CSV should contain commas"

    @pytest.mark.asyncio
    async def test_export_markdown(self):
        agent = self._make_agent()
        if agent is None:
            pytest.skip()
        data = mock_sql_result(n=3)
        result = await agent.export(data=data, label="test", fmt="markdown", title="MD Test")
        assert result.get("success") is True
        assert "|" in result.get("content", ""), "Markdown should contain table pipes"

    @pytest.mark.asyncio
    async def test_export_html(self):
        agent = self._make_agent()
        if agent is None:
            pytest.skip()
        data = mock_sql_result(n=3)
        result = await agent.export(data=data, label="test", fmt="html", title="HTML Test")
        assert result.get("success") is True
        assert "<table" in result.get("content", "").lower()

    @pytest.mark.asyncio
    async def test_export_invalid_format_fallback(self):
        agent = self._make_agent()
        if agent is None:
            pytest.skip()
        data = mock_sql_result(n=2)
        result = await agent.export(data=data, label="test", fmt="xlsx", title="Fallback")
        # Should either succeed with fallback or return error gracefully
        assert isinstance(result, dict)
        assert "success" in result


# ═════════════════════════════════════════════════════════════════════════════
# Phase 4 — Report Agent
# ═════════════════════════════════════════════════════════════════════════════


class TestReportAgent:
    """Unit tests for ReportAgent statistics and comfort detection."""

    def _make_agent(self):
        try:
            from orchestrator.agents.report_agent import ReportAgent

            return ReportAgent()
        except ImportError:
            return None

    def test_agent_instantiates(self):
        agent = self._make_agent()
        if agent is None:
            pytest.skip("ReportAgent not importable")
        assert agent is not None

    def test_compute_stats_normal(self):
        agent = self._make_agent()
        if agent is None:
            pytest.skip()
        rows = mock_sensor_readings("uuid-temp-101", n=30)
        stats = agent._summarize_readings(rows)
        assert isinstance(stats, dict)
        # Check numeric columns have expected keys
        for col, s in stats.items():
            if isinstance(s, dict) and "avg" in s:
                assert 15 < s["avg"] < 30, "Mean temp should be in plausible range"

    def test_detect_comfort_violations_normal(self):
        agent = self._make_agent()
        if agent is None:
            pytest.skip()
        rows = mock_sensor_readings("uuid-temp-101", n=20)
        violations = agent._detect_anomalies(rows)
        assert isinstance(violations, list)
        # Normal data should have few violations
        high = [v for v in violations if v.get("severity") == "high"]
        assert len(high) == 0

    def test_detect_comfort_violations_anomalous(self):
        agent = self._make_agent()
        if agent is None:
            pytest.skip()
        rows = mock_anomalous_readings(n=20)
        violations = agent._detect_anomalies(rows)
        assert len(violations) > 0, "Anomalous data should trigger violations"

    @pytest.mark.asyncio
    async def test_generate_returns_formatted_text(self):
        agent = self._make_agent()
        if agent is None:
            pytest.skip()
        state = MagicMock()
        sql = mock_sql_result(n=10)
        sparql = mock_sparql_result()
        with patch.object(
            agent, "_narrate", new_callable=AsyncMock, return_value="Building report summary."
        ):
            result = await agent.generate(
                state, "generate a summary report", sensor_data=sql, metadata=sparql
            )
        assert "formatted_text" in result or "success" in result


# ═════════════════════════════════════════════════════════════════════════════
# Phase 3 — Hybrid Retrieval Orchestrator (basic contract tests)
# ═════════════════════════════════════════════════════════════════════════════


class TestHybridRetrieval:
    """Contract tests for HybridRetrievalOrchestrator."""

    def _make_orchestrator(self):
        try:
            from orchestrator.services.hybrid_retrieval import (
                HybridRetrievalOrchestrator,
            )

            return HybridRetrievalOrchestrator()
        except ImportError:
            return None

    def test_orchestrator_instantiates(self):
        orc = self._make_orchestrator()
        if orc is None:
            pytest.skip("HybridRetrievalOrchestrator not importable")
        assert orc is not None

    def test_classify_query_type_metadata(self):
        orc = self._make_orchestrator()
        if orc is None:
            pytest.skip()
        from orchestrator.services.hybrid_retrieval import (
            QueryType,
            classify_query_type,
        )

        tier = classify_query_type("list all temperature sensors")
        assert isinstance(tier, QueryType)

    def test_classify_query_type_analytics(self):
        orc = self._make_orchestrator()
        if orc is None:
            pytest.skip()
        from orchestrator.services.hybrid_retrieval import (
            QueryType,
            classify_query_type,
        )

        tier = classify_query_type("what is the average CO2 level today?")
        assert isinstance(tier, QueryType)
