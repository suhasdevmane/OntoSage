"""
test_phase_bc_services.py — Tests for Phase B (remaining) and Phase C implementations.

Covers:
  B.3  AgentMemoryService — embedding_dimension used for vector size; fallback store; retrieve/store round-trip
  B.5  SelfCorrectionEngine wired into SPARQLAgent — correction engine attribute exists; strategies fire
  B.6  MultiBuildingManager — list_buildings callable; /buildings endpoint importable; get_building_manager singleton
  C.1  Hardcoded paths replaced with settings — SENSOR_MAP_PATH, OUTPUT_DATA_DIR, QUERY_RESULTS_DIR, PLANNER_MAX_STEPS
  C.4  validate_config / validate_config_async — namespace check, RBAC+secret check, async returns dict
"""

import asyncio
import os
import sys

import pytest

sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))


# ──────────────────────────────────────────────────────────────────────────────
# B.3 — Agent Memory
# ──────────────────────────────────────────────────────────────────────────────


class TestAgentMemoryVectorSize:
    """Verify the hardcoded 1536 vector size has been replaced with settings.embedding_dimension."""

    def test_initialise_uses_settings_dimension(self):
        import inspect

        from orchestrator.services import agent_memory as am_module

        src = inspect.getsource(am_module.AgentMemoryService.initialise)
        # 1536 is permitted as the OpenAI-specific branch; the important check is that
        # settings.embedding_dimension is also used (for local/non-OpenAI models)
        assert (
            "embedding_dimension" in src
        ), "initialise() must reference settings.embedding_dimension for non-OpenAI models"

    def test_fallback_embed_uses_settings_dimension(self):
        import inspect

        from orchestrator.services import agent_memory as am_module

        src = inspect.getsource(am_module.AgentMemoryService._embed)
        # The fallback loop must NOT use 1536 literal
        assert (
            "range(1536)" not in src
        ), "Hardcoded range(1536) in _embed fallback — should use settings.embedding_dimension"
        assert "embedding_dimension" in src

    def test_settings_imported_in_agent_memory(self):
        import inspect

        from orchestrator.services.agent_memory import AgentMemoryService

        src = inspect.getsource(inspect.getmodule(AgentMemoryService))
        assert "from shared.config import settings" in src


class TestAgentMemoryFallbackStore:
    """Verify in-memory fallback store works without Qdrant."""

    @pytest.mark.asyncio
    async def test_store_and_retrieve_fallback(self):
        from orchestrator.services.agent_memory import AgentMemoryService

        svc = AgentMemoryService(qdrant_url="http://localhost:6666", enabled=True)
        # Qdrant is unreachable so _ready stays False; fallback store is used
        await svc.store_success(
            user_id="testuser",
            query="What is the temperature?",
            intent="analytics",
            entities=["Temp_Sensor_1"],
            answer_summary="22°C",
        )
        ctx = await svc.retrieve_context("testuser", "temperature")
        # Fallback returns recent memories; should include the entry we just stored
        assert "testuser" in svc._fallback_store
        assert len(svc._fallback_store["testuser"]) == 1

    @pytest.mark.asyncio
    async def test_forget_user_clears_fallback(self):
        from orchestrator.services.agent_memory import AgentMemoryService

        svc = AgentMemoryService(qdrant_url="http://localhost:6666", enabled=True)
        await svc.store_success("bob", "Q?", "general", [], "A.")
        await svc.forget_user("bob")
        assert "bob" not in svc._fallback_store

    @pytest.mark.asyncio
    async def test_disabled_service_returns_empty_string(self):
        from orchestrator.services.agent_memory import AgentMemoryService

        svc = AgentMemoryService(enabled=False)
        result = await svc.retrieve_context("alice", "anything")
        assert result == ""

    @pytest.mark.asyncio
    async def test_max_memories_enforced(self):
        from orchestrator.services.agent_memory import MAX_MEMORIES, AgentMemoryService

        svc = AgentMemoryService(qdrant_url="http://localhost:6666", enabled=True)
        for i in range(MAX_MEMORIES + 5):
            await svc.store_success("user1", f"Q{i}", "general", [], "A.")
        assert len(svc._fallback_store["user1"]) <= MAX_MEMORIES


# ──────────────────────────────────────────────────────────────────────────────
# B.5 — Self-Correction Engine wired into SPARQLAgent
# ──────────────────────────────────────────────────────────────────────────────


class TestSPARQLAgentSelfCorrection:
    def test_correction_engine_attribute_exists(self):
        from orchestrator.agents.sparql_agent import SPARQLAgent

        agent = SPARQLAgent()
        assert hasattr(
            agent, "_correction_engine"
        ), "SPARQLAgent must have a _correction_engine attribute (SelfCorrectionEngine)"

    def test_correction_engine_is_right_type(self):
        from orchestrator.agents.sparql_agent import SPARQLAgent
        from orchestrator.services.self_correction_engine import SelfCorrectionEngine

        agent = SPARQLAgent()
        assert isinstance(agent._correction_engine, SelfCorrectionEngine)

    def test_generate_query_uses_correction_engine(self):
        import inspect

        from orchestrator.agents.sparql_agent import SPARQLAgent

        src = inspect.getsource(SPARQLAgent.generate_query)
        assert (
            "execute_with_correction" in src
        ), "generate_query() must call self._correction_engine.execute_with_correction"

    @pytest.mark.asyncio
    async def test_correction_engine_handles_failed_execute_fn(self):
        """Verify that a failing execute_fn triggers correction strategies."""
        from orchestrator.services.self_correction_engine import SelfCorrectionEngine

        engine = SelfCorrectionEngine(max_attempts=2)

        call_count = {"n": 0}

        async def bad_execute(query: str):
            call_count["n"] += 1
            return {"success": False, "results": {}, "error": "SyntaxError near '}'"}

        result = await engine.execute_with_correction(
            initial_query="SELECT * WHERE { ?s ?p ?o }",
            execute_fn=bad_execute,
            context={
                "building_namespace": "http://example.com/b#",
                "building_prefix": "bldg",
                "user_query": "test",
            },
        )
        # Engine should have tried multiple times
        assert call_count["n"] > 1
        assert "correction_log" in result
        assert result["correction_log"]["total_attempts"] >= 1

    @pytest.mark.asyncio
    async def test_correction_engine_returns_on_success(self):
        """Verify that a succeeding execute_fn returns immediately."""
        from orchestrator.services.self_correction_engine import SelfCorrectionEngine

        engine = SelfCorrectionEngine(max_attempts=3)

        async def good_execute(query: str):
            return {
                "success": True,
                "results": {"results": {"bindings": [{"s": {"value": "x"}}]}},
                "error": None,
            }

        result = await engine.execute_with_correction(
            initial_query="SELECT ?s WHERE { ?s a brick:Sensor }",
            execute_fn=good_execute,
            context={"building_namespace": "http://example.com/b#", "building_prefix": "bldg"},
        )
        assert result["success"] is True
        assert result["correction_log"]["total_attempts"] == 1


# ──────────────────────────────────────────────────────────────────────────────
# B.6 — Multi-Building Manager
# ──────────────────────────────────────────────────────────────────────────────


class TestMultiBuildingManager:
    def test_get_building_manager_returns_singleton(self):
        from orchestrator.services.multi_building_manager import (
            get_building_manager,
            reset_building_manager,
        )

        reset_building_manager()
        mgr1 = get_building_manager()
        mgr2 = get_building_manager()
        assert mgr1 is mgr2, "get_building_manager() must return the same singleton instance"

    def test_list_buildings_returns_list(self):
        from orchestrator.services.multi_building_manager import get_building_manager

        mgr = get_building_manager()
        buildings = mgr.list_buildings()
        assert isinstance(buildings, list)

    def test_manager_importable_from_main_module(self):
        """B.6: main.py must import get_building_manager without error."""
        import inspect

        import orchestrator.main as main_module

        src = inspect.getsource(main_module)
        assert "get_building_manager" in src

    def test_buildings_endpoint_registered(self):
        """Verify /buildings route is registered in the FastAPI app."""
        from orchestrator.main import app

        routes = [r.path for r in app.routes]
        assert "/buildings" in routes, "/buildings endpoint not registered in FastAPI app"

    def test_summary_non_empty_string(self):
        from orchestrator.services.multi_building_manager import get_building_manager

        mgr = get_building_manager()
        summary = mgr.summary()
        assert isinstance(summary, str) and len(summary) > 0

    def test_detect_from_namespace_returns_none_for_unknown(self):
        from orchestrator.services.multi_building_manager import get_building_manager

        mgr = get_building_manager()
        result = mgr.detect_from_namespace("http://totally.unknown.namespace/foo#")
        assert result is None


# ──────────────────────────────────────────────────────────────────────────────
# C.1 — Hardcoded paths replaced with settings
# ──────────────────────────────────────────────────────────────────────────────


class TestExternalizedPaths:
    def test_sensor_map_path_in_settings(self):
        from shared.config import settings

        assert hasattr(settings, "SENSOR_MAP_PATH")
        assert isinstance(settings.SENSOR_MAP_PATH, str)
        assert settings.SENSOR_MAP_PATH  # not empty

    def test_output_data_dir_in_settings(self):
        from shared.config import settings

        assert hasattr(settings, "OUTPUT_DATA_DIR")
        assert isinstance(settings.OUTPUT_DATA_DIR, str)

    def test_query_results_dir_in_settings(self):
        from shared.config import settings

        assert hasattr(settings, "QUERY_RESULTS_DIR")
        assert isinstance(settings.QUERY_RESULTS_DIR, str)

    def test_planner_max_steps_in_settings(self):
        from shared.config import settings

        assert hasattr(settings, "PLANNER_MAX_STEPS")
        assert isinstance(settings.PLANNER_MAX_STEPS, int)
        assert settings.PLANNER_MAX_STEPS > 0

    def test_workflow_uses_sensor_map_path_setting(self):
        import inspect

        from orchestrator import workflow as wf_module

        src = inspect.getsource(wf_module.WorkflowOrchestrator.__init__)
        assert (
            "settings.SENSOR_MAP_PATH" in src
        ), "WorkflowOrchestrator.__init__ must use settings.SENSOR_MAP_PATH"
        assert '"data/sensor_map.json"' not in src

    def test_workflow_uses_output_data_dir_setting(self):
        import inspect

        from orchestrator import workflow as wf_module

        src = inspect.getsource(wf_module.WorkflowOrchestrator._analytics_node)
        assert "settings.OUTPUT_DATA_DIR" in src
        assert '"outputs/data"' not in src

    def test_workflow_uses_query_results_dir_setting(self):
        import inspect

        from orchestrator import workflow as wf_module

        # Read the full source of the module to find the hardcoded path
        full_src = inspect.getsource(wf_module)
        assert (
            '"/app/outputs/query_results"' not in full_src
        ), 'Hardcoded "/app/outputs/query_results" found — should use settings.QUERY_RESULTS_DIR'

    def test_planner_max_steps_uses_settings(self):
        import inspect

        from orchestrator.agents.planner_agent import PlannerAgent

        src = inspect.getsource(PlannerAgent)
        assert (
            "settings.PLANNER_MAX_STEPS" in src
        ), "PlannerAgent.MAX_STEPS must use settings.PLANNER_MAX_STEPS"
        assert "MAX_STEPS = 6" not in src


# ──────────────────────────────────────────────────────────────────────────────
# C.4 — validate_config / validate_config_async
# ──────────────────────────────────────────────────────────────────────────────


class TestValidateConfig:
    def test_valid_default_config_passes(self):
        """Default config should pass all synchronous checks."""
        from shared import config as cfg_module

        # RBAC defaults to True now, which requires non-default SECRET_KEY.
        # Disable RBAC for this unit test to isolate config validation logic.
        original_rbac = cfg_module.settings.RBAC_ENABLED
        try:
            cfg_module.settings.RBAC_ENABLED = False
            result = cfg_module.validate_config()
            assert result is True
        finally:
            cfg_module.settings.RBAC_ENABLED = original_rbac

    def test_bad_namespace_raises(self):
        """BUILDING_NAMESPACE without trailing '#' or '/' must raise ValueError."""
        import importlib

        from shared import config as cfg_module

        original_ns = cfg_module.settings.BUILDING_NAMESPACE
        try:
            cfg_module.settings.BUILDING_NAMESPACE = "http://bad.namespace"
            with pytest.raises(ValueError, match="BUILDING_NAMESPACE"):
                cfg_module.validate_config()
        finally:
            cfg_module.settings.BUILDING_NAMESPACE = original_ns

    def test_namespace_with_hash_passes(self):
        from shared import config as cfg_module

        original = cfg_module.settings.BUILDING_NAMESPACE
        original_rbac = cfg_module.settings.RBAC_ENABLED
        try:
            cfg_module.settings.BUILDING_NAMESPACE = "http://example.com/building#"
            cfg_module.settings.RBAC_ENABLED = False
            assert cfg_module.validate_config() is True
        finally:
            cfg_module.settings.BUILDING_NAMESPACE = original
            cfg_module.settings.RBAC_ENABLED = original_rbac

    def test_namespace_with_slash_passes(self):
        from shared import config as cfg_module

        original = cfg_module.settings.BUILDING_NAMESPACE
        original_rbac = cfg_module.settings.RBAC_ENABLED
        try:
            cfg_module.settings.BUILDING_NAMESPACE = "http://example.com/building/"
            cfg_module.settings.RBAC_ENABLED = False
            assert cfg_module.validate_config() is True
        finally:
            cfg_module.settings.BUILDING_NAMESPACE = original
            cfg_module.settings.RBAC_ENABLED = original_rbac

    def test_default_secret_with_rbac_raises(self):
        """Enabling RBAC with default SECRET_KEY must raise ValueError."""
        from shared import config as cfg_module

        original_rbac = cfg_module.settings.RBAC_ENABLED
        original_key = cfg_module.settings.SECRET_KEY
        try:
            cfg_module.settings.RBAC_ENABLED = True
            cfg_module.settings.SECRET_KEY = "change-me-in-production-use-32-random-bytes"
            with pytest.raises(ValueError, match="SECRET_KEY"):
                cfg_module.validate_config()
        finally:
            cfg_module.settings.RBAC_ENABLED = original_rbac
            cfg_module.settings.SECRET_KEY = original_key

    def test_strong_secret_with_rbac_passes(self):
        from shared import config as cfg_module

        original_rbac = cfg_module.settings.RBAC_ENABLED
        original_key = cfg_module.settings.SECRET_KEY
        original_ns = cfg_module.settings.BUILDING_NAMESPACE
        try:
            cfg_module.settings.RBAC_ENABLED = True
            cfg_module.settings.SECRET_KEY = "a" * 32  # Not the placeholder
            cfg_module.settings.BUILDING_NAMESPACE = "http://example.com/b#"
            assert cfg_module.validate_config() is True
        finally:
            cfg_module.settings.RBAC_ENABLED = original_rbac
            cfg_module.settings.SECRET_KEY = original_key
            cfg_module.settings.BUILDING_NAMESPACE = original_ns

    @pytest.mark.asyncio
    async def test_validate_config_async_returns_dict(self):
        from shared.config import validate_config_async

        result = await validate_config_async()
        assert isinstance(result, dict)
        assert "ok" in result
        assert "errors" in result
        assert "warnings" in result

    @pytest.mark.asyncio
    async def test_validate_config_async_ok_with_defaults(self):
        """Default settings (RBAC disabled for test, valid namespace) should return ok=True."""
        from shared import config as cfg_module

        original_rbac = cfg_module.settings.RBAC_ENABLED
        try:
            cfg_module.settings.RBAC_ENABLED = False
            result = await cfg_module.validate_config_async()
            # Connectivity checks may warn but shouldn't cause errors for valid config
            assert result["ok"] is True
        finally:
            cfg_module.settings.RBAC_ENABLED = original_rbac

    @pytest.mark.asyncio
    async def test_validate_config_async_errors_on_bad_namespace(self):
        from shared import config as cfg_module

        original = cfg_module.settings.BUILDING_NAMESPACE
        try:
            cfg_module.settings.BUILDING_NAMESPACE = "http://no-trailing-separator"
            result = await cfg_module.validate_config_async()
            assert result["ok"] is False
            assert any("BUILDING_NAMESPACE" in e for e in result["errors"])
        finally:
            cfg_module.settings.BUILDING_NAMESPACE = original
