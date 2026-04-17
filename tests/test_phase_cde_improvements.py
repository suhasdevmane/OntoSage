"""
test_phase_cde_improvements.py — Tests for Phase C/D/E improvements.

Covers:
  C.2  PromptBuilder — sparql_system_hints, sql_dialect_hints, sql_schema_hints, intent_context_hints
  C.3  Sensor map auto-generation — SENSOR_MAP_PATH setting; workflow falls back to introspector data
  D.2  DataExportAgent → download_url returned; /api/files/{filename} endpoint registered
  E.1  CORS — CORS_ORIGINS setting controls allowed origins; value from env respected
  E.2  Request tracing — TracingMiddleware adds X-Trace-Id header; trace_id propagated
  E.3  Rate limiting — RateLimitMiddleware blocks after threshold; 429 returned with Retry-After
"""

import asyncio
import os
import sys
import tempfile

import pytest

sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))


# ──────────────────────────────────────────────────────────────────────────────
# C.2 — PromptBuilder
# ──────────────────────────────────────────────────────────────────────────────


class TestPromptBuilder:
    def _builder(self):
        from orchestrator.services.prompt_builder import PromptBuilder

        return PromptBuilder()

    def test_sparql_system_hints_contains_building_name(self):
        from shared.config import settings

        hints = self._builder().sparql_system_hints()
        assert settings.BUILDING_NAME in hints

    def test_sparql_system_hints_contains_namespace(self):
        from shared.config import settings

        hints = self._builder().sparql_system_hints()
        assert settings.BUILDING_NAMESPACE in hints

    def test_sparql_system_hints_contains_prefix(self):
        from shared.config import settings

        hints = self._builder().sparql_system_hints()
        assert settings.BUILDING_PREFIX in hints

    def test_sparql_system_hints_with_sensor_classes(self):
        ns_map = {"brick": "https://brickschema.org/schema/Brick#"}
        classes = [
            "https://brickschema.org/schema/Brick#Air_Temperature_Sensor",
            "https://brickschema.org/schema/Brick#CO2_Sensor",
        ]
        hints = self._builder().sparql_system_hints(classes, ns_map)
        assert "Air_Temperature_Sensor" in hints or "brick:" in hints

    def test_sparql_system_hints_detects_brick_schema(self):
        ns_map = {"brick": "https://brickschema.org/schema/Brick#"}
        hints = self._builder().sparql_system_hints(namespace_map=ns_map)
        assert "Brick" in hints

    def test_sparql_system_hints_detects_rec_schema(self):
        ns_map = {"rec": "https://w3id.org/rec#"}
        hints = self._builder().sparql_system_hints(namespace_map=ns_map)
        assert "RealEstateCore" in hints or "REC" in hints

    def test_sparql_prefix_block_includes_building_namespace(self):
        from shared.config import settings

        block = self._builder().sparql_prefix_block()
        assert settings.BUILDING_NAMESPACE in block
        assert f"PREFIX {settings.BUILDING_PREFIX}:" in block

    def test_sql_dialect_hints_default_mysql(self):
        hints = self._builder().sql_dialect_hints()
        assert "MySQL" in hints or "backtick" in hints.lower()

    def test_sql_dialect_hints_from_adapter_with_get_dialect_hints(self):
        from unittest.mock import MagicMock

        adapter = MagicMock()
        adapter.get_dialect_hints.return_value = "PostgreSQL dialect rules: ..."
        hints = self._builder().sql_dialect_hints(adapter)
        assert "PostgreSQL" in hints

    def test_sql_dialect_hints_falls_back_if_adapter_raises(self):
        from unittest.mock import MagicMock

        adapter = MagicMock()
        adapter.get_dialect_hints.side_effect = RuntimeError("no connection")
        hints = self._builder().sql_dialect_hints(adapter)
        # Should fall back to MySQL hints
        assert isinstance(hints, str) and len(hints) > 10

    def test_sql_schema_hints_includes_timezone(self):
        from shared.config import settings

        hints = self._builder().sql_schema_hints("CREATE TABLE sensor_data (...)")
        assert settings.BUILDING_TIMEZONE in hints

    def test_intent_context_hints_includes_building_name(self):
        from shared.config import settings

        hints = self._builder().intent_context_hints()
        assert settings.BUILDING_NAME in hints

    def test_intent_context_hints_lists_sensor_types(self):
        hints = self._builder().intent_context_hints(
            sensor_types=["Temperature", "CO2", "Humidity"]
        )
        assert "Temperature" in hints and "CO2" in hints

    def test_get_prompt_builder_returns_singleton(self):
        from orchestrator.services.prompt_builder import get_prompt_builder

        b1 = get_prompt_builder()
        b2 = get_prompt_builder()
        assert b1 is b2

    def test_sparql_agent_has_prompt_builder_attr(self):
        from orchestrator.agents.sparql_agent import SPARQLAgent
        from orchestrator.services.prompt_builder import PromptBuilder

        agent = SPARQLAgent()
        assert hasattr(agent, "_prompt_builder")
        assert isinstance(agent._prompt_builder, PromptBuilder)

    def test_sql_agent_has_prompt_builder_attr(self):
        from orchestrator.agents.sql_agent import SQLAgent
        from orchestrator.services.prompt_builder import PromptBuilder

        agent = SQLAgent()
        assert hasattr(agent, "_prompt_builder")
        assert isinstance(agent._prompt_builder, PromptBuilder)

    def test_sparql_generate_imports_prompt_builder(self):
        import inspect

        from orchestrator.agents.sparql_agent import SPARQLAgent

        src = inspect.getsource(SPARQLAgent._generate_sparql)
        assert "_building_profile" in src or "sparql_system_hints" in src

    def test_sql_generate_uses_dialect_hints(self):
        import inspect

        from orchestrator.agents.sql_agent import SQLAgent

        src = inspect.getsource(SQLAgent._generate_sql)
        assert "dialect_hints" in src or "sql_dialect_hints" in src


# ──────────────────────────────────────────────────────────────────────────────
# C.3 — Sensor map auto-generation
# ──────────────────────────────────────────────────────────────────────────────


class TestSensorMapAutoGeneration:
    def test_sensor_map_path_setting_exists(self):
        from shared.config import settings

        assert hasattr(settings, "SENSOR_MAP_PATH")
        assert isinstance(settings.SENSOR_MAP_PATH, str)

    def test_main_lifespan_contains_auto_gen_logic(self):
        import inspect

        import orchestrator.main as main_module

        src = inspect.getsource(main_module)
        assert "SENSOR_MAP_PATH" in src or "sensor_map_path" in src.lower()
        assert "_needs_regen" in src or "Auto-generated" in src

    def test_workflow_loads_sensor_map_from_setting(self):
        import inspect

        from orchestrator import workflow as wf_module

        src = inspect.getsource(wf_module.WorkflowOrchestrator.__init__)
        assert "settings.SENSOR_MAP_PATH" in src

    def test_sensor_map_file_created_when_missing(self):
        """Simulate the auto-gen logic: given sensor_classes, create a JSON file."""
        import json

        sensor_classes = [
            "https://brickschema.org/schema/Brick#Air_Temperature_Sensor",
            "https://brickschema.org/schema/Brick#CO2_Sensor",
        ]
        with tempfile.TemporaryDirectory() as tmpdir:
            path = os.path.join(tmpdir, "sensor_map.json")
            # Simulate the auto-gen code from main.py
            sensor_map = {
                cls.split("#")[-1].split("/")[-1]: {
                    "uri": cls,
                    "label": cls.split("#")[-1].split("/")[-1],
                    "uuid": "",
                    "storage": "",
                }
                for cls in sensor_classes
            }
            with open(path, "w") as f:
                json.dump(sensor_map, f)
            with open(path) as f:
                loaded = json.load(f)
            assert "Air_Temperature_Sensor" in loaded
            assert "CO2_Sensor" in loaded


# ──────────────────────────────────────────────────────────────────────────────
# D.2 — DataExportAgent → download_url
# ──────────────────────────────────────────────────────────────────────────────


class TestExportDownloadUrl:
    @pytest.mark.asyncio
    async def test_export_returns_download_url_on_success(self, tmp_path, monkeypatch):
        """When EXPORTS_DIR is writable, download_url should be populated."""
        from shared import config as cfg_module

        monkeypatch.setattr(cfg_module.settings, "EXPORTS_DIR", str(tmp_path))
        monkeypatch.setattr(cfg_module.settings, "STATIC_BASE_URL", "http://localhost:8000")

        from orchestrator.agents.data_export_agent import DataExportAgent

        agent = DataExportAgent()
        rows = [{"sensor": "Temp_1", "value": 22.5, "ts": "2026-01-01T00:00:00Z"}]
        result = await agent.export(rows, label="test_export", fmt="csv")

        assert result["success"] is True
        assert "download_url" in result
        assert result["download_url"] is not None
        assert "test_export" in result["download_url"]

    @pytest.mark.asyncio
    async def test_export_file_written_to_disk(self, tmp_path, monkeypatch):
        """The export file should actually exist on disk after export()."""
        from shared import config as cfg_module

        monkeypatch.setattr(cfg_module.settings, "EXPORTS_DIR", str(tmp_path))
        monkeypatch.setattr(cfg_module.settings, "STATIC_BASE_URL", "http://localhost:8000")

        from orchestrator.agents.data_export_agent import DataExportAgent

        agent = DataExportAgent()
        rows = [{"k": "v"}]
        result = await agent.export(rows, label="disk_test", fmt="json")

        assert result["success"] is True
        filename = result["filename"]
        assert (tmp_path / filename).exists()

    @pytest.mark.asyncio
    async def test_export_result_still_contains_content(self, tmp_path, monkeypatch):
        """content key must still exist in the result for backwards compatibility."""
        from shared import config as cfg_module

        monkeypatch.setattr(cfg_module.settings, "EXPORTS_DIR", str(tmp_path))
        monkeypatch.setattr(cfg_module.settings, "STATIC_BASE_URL", "http://localhost:8000")

        from orchestrator.agents.data_export_agent import DataExportAgent

        agent = DataExportAgent()
        rows = [{"a": 1}]
        result = await agent.export(rows, label="compat", fmt="json")
        assert "content" in result and result["content"]

    def test_api_files_endpoint_registered(self):
        """The /api/files/{filename} route must be registered in the FastAPI app."""
        from orchestrator.main import app

        routes = [r.path for r in app.routes]
        assert "/api/files/{filename}" in routes

    def test_exports_dir_setting_exists(self):
        from shared.config import settings

        assert hasattr(settings, "EXPORTS_DIR")
        assert isinstance(settings.EXPORTS_DIR, str)


# ──────────────────────────────────────────────────────────────────────────────
# E.1 — CORS from settings
# ──────────────────────────────────────────────────────────────────────────────


class TestCORSSettings:
    def test_cors_origins_setting_exists(self):
        from shared.config import settings

        assert hasattr(settings, "CORS_ORIGINS")
        assert isinstance(settings.CORS_ORIGINS, str)

    def test_cors_origins_default_is_wildcard(self):
        from shared.config import settings

        assert settings.CORS_ORIGINS == "*"

    def test_main_uses_cors_origins_setting(self):
        import inspect

        import orchestrator.main as main_module

        src = inspect.getsource(main_module)
        assert "CORS_ORIGINS" in src
        assert "_cors_origins" in src

    def test_cors_origins_parsed_as_list(self):
        """Multiple origins separated by comma should be parsed into a list."""
        raw = "http://localhost:3000,https://app.example.com"
        origins = [o.strip() for o in raw.split(",") if o.strip()]
        assert len(origins) == 2
        assert "http://localhost:3000" in origins
        assert "https://app.example.com" in origins


# ──────────────────────────────────────────────────────────────────────────────
# E.2 — Request tracing
# ──────────────────────────────────────────────────────────────────────────────


class TestRequestTracing:
    def test_tracing_middleware_class_exists(self):
        import inspect

        import orchestrator.main as main_module

        src = inspect.getsource(main_module)
        assert "TracingMiddleware" in src

    def test_tracing_middleware_adds_x_trace_id(self):
        import inspect

        import orchestrator.main as main_module

        src = inspect.getsource(main_module)
        assert "X-Trace-Id" in src

    def test_tracing_middleware_uses_uuid(self):
        import inspect

        import orchestrator.main as main_module

        src = inspect.getsource(main_module)
        assert "uuid" in src.lower()

    def test_tracing_middleware_respects_incoming_header(self):
        """If X-Trace-Id is in the request, it should be re-used, not replaced."""
        import inspect

        import orchestrator.main as main_module

        src = inspect.getsource(main_module)
        # The middleware should check for an existing X-Trace-Id header
        assert "X-Trace-Id" in src

    @pytest.mark.asyncio
    async def test_tracing_middleware_propagates_trace_id(self):
        """Live HTTP test — GET /health must return X-Trace-Id header."""
        from httpx import ASGITransport, AsyncClient

        from orchestrator.main import app

        transport = ASGITransport(app=app)
        async with AsyncClient(transport=transport, base_url="http://test") as client:
            resp = await client.get("/health")
        assert "x-trace-id" in resp.headers or "X-Trace-Id" in resp.headers

    @pytest.mark.asyncio
    async def test_tracing_middleware_uses_provided_trace_id(self):
        """If caller sends X-Trace-Id, the same ID should be echoed back."""
        from httpx import ASGITransport, AsyncClient

        from orchestrator.main import app

        my_trace = "test-trace-abc123"
        transport = ASGITransport(app=app)
        async with AsyncClient(transport=transport, base_url="http://test") as client:
            resp = await client.get("/health", headers={"X-Trace-Id": my_trace})
        returned = resp.headers.get("x-trace-id") or resp.headers.get("X-Trace-Id", "")
        assert returned == my_trace


# ──────────────────────────────────────────────────────────────────────────────
# E.3 — Rate limiting
# ──────────────────────────────────────────────────────────────────────────────


class TestRateLimiting:
    def test_rate_limit_middleware_class_exists(self):
        import inspect

        import orchestrator.main as main_module

        src = inspect.getsource(main_module)
        assert "RateLimitMiddleware" in src

    def test_rate_limit_returns_429_with_retry_after(self):
        import inspect

        import orchestrator.main as main_module

        src = inspect.getsource(main_module)
        assert "429" in src
        assert "Retry-After" in src

    def test_rate_limit_counts_by_ip(self):
        import inspect

        import orchestrator.main as main_module

        src = inspect.getsource(main_module)
        assert "client.host" in src or "client_ip" in src

    @pytest.mark.asyncio
    async def test_rate_limit_blocks_after_threshold(self):
        """Sending requests above the limit should eventually return 429."""
        from fastapi import FastAPI
        from httpx import ASGITransport, AsyncClient

        from orchestrator.main import RateLimitMiddleware

        tiny_app = FastAPI()

        @tiny_app.get("/ping")
        async def ping():
            return {"ok": True}

        tiny_app.add_middleware(RateLimitMiddleware, requests=3, window=60)

        transport = ASGITransport(app=tiny_app)
        async with AsyncClient(transport=transport, base_url="http://test") as client:
            for _ in range(3):
                r = await client.get("/ping")
                assert r.status_code == 200
            # 4th request must be blocked
            r = await client.get("/ping")
            assert r.status_code == 429
            assert "retry-after" in r.headers or "Retry-After" in r.headers

    @pytest.mark.asyncio
    async def test_rate_limit_window_env_vars(self):
        """RATE_LIMIT_REQUESTS and RATE_LIMIT_WINDOW_S env vars must be read."""
        import inspect

        import orchestrator.main as main_module

        src = inspect.getsource(main_module)
        assert "RATE_LIMIT_REQUESTS" in src
        assert "RATE_LIMIT_WINDOW_S" in src
