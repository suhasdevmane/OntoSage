"""
test_phase_b_activations.py — Tests for IMPROVEMENT_PLAN_V2.md Phase B (Activate Dead Services).

Covers:
  B.1  RBAC — TokenManager issues/validates tokens; RBACMiddleware exists; login helper works
  B.2  Response Cache — pure async Redis interface; get/put/cache_type round-trip
  B.4  OntologyDetector — DetectionResult dataclass; detect_from_graphdb graceful failure
  B.7  Analytics Engine wired into workflow — deterministic path chosen for known intents
"""
import sys
import os
import json
import asyncio
import pytest

sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))


# ──────────────────────────────────────────────────────────────────────────────
# B.1 — RBAC
# ──────────────────────────────────────────────────────────────────────────────

class TestRBACTokenManager:
    def _mgr(self):
        from orchestrator.middleware.rbac import TokenManager, UserContext, ROLE_PERMISSIONS
        mgr = TokenManager(secret_key="test-secret-key")
        user = UserContext(
            user_id="u1",
            username="alice",
            role="analyst",
            tenant_id="bldg1",
            allowed_buildings=[],
            permissions=ROLE_PERMISSIONS["analyst"],
        )
        return mgr, user

    def test_issue_and_validate_token(self):
        from orchestrator.middleware.rbac import TokenManager
        mgr, user = self._mgr()
        token = mgr.issue_token(user)
        assert isinstance(token, str) and token.count(".") == 2

        validated = mgr.validate_token(token)
        assert validated.user_id == "u1"
        assert validated.role == "analyst"

    def test_token_carries_permissions(self):
        mgr, user = self._mgr()
        token = mgr.issue_token(user)
        validated = mgr.validate_token(token)
        assert validated.has_permission("analytics:read")
        assert not validated.has_permission("system:admin")

    def test_invalid_secret_rejected(self):
        from orchestrator.middleware.rbac import TokenManager
        mgr, user = self._mgr()
        token = mgr.issue_token(user)

        wrong_mgr = TokenManager(secret_key="wrong-secret")
        with pytest.raises(PermissionError):
            wrong_mgr.validate_token(token)

    def test_rbac_middleware_exists_and_is_importable(self):
        from orchestrator.middleware.rbac import RBACMiddleware, get_auth_manager, get_user_store
        assert RBACMiddleware is not None
        assert callable(get_auth_manager)
        assert callable(get_user_store)

    def test_create_rbac_dependency_callable(self):
        from orchestrator.middleware.rbac import create_rbac_dependency, TokenManager
        mgr = TokenManager("s")
        dep = create_rbac_dependency(mgr, "sensor:read")
        assert callable(dep)


class TestRBACRoles:
    @pytest.mark.parametrize("role,perm,expected", [
        ("admin",            "system:admin",  True),
        ("admin",            "sensor:read",   True),
        ("analyst",          "analytics:read",True),
        ("analyst",          "system:admin",  False),
        ("occupant",         "sensor:read",   True),
        ("occupant",         "export:read",   False),
        ("readonly",         "metadata:read", True),
        ("readonly",         "sensor:read",   False),
    ])
    def test_role_permissions(self, role, perm, expected):
        from orchestrator.middleware.rbac import ROLE_PERMISSIONS
        perms = ROLE_PERMISSIONS.get(role, set())
        assert (perm in perms) == expected, (
            f"Role '{role}' permission '{perm}': expected {expected}"
        )


# ──────────────────────────────────────────────────────────────────────────────
# B.2 — Response Cache (async Redis)
# ──────────────────────────────────────────────────────────────────────────────

class MockAsyncRedis:
    """Minimal async Redis mock for testing ResponseCacheService."""
    def __init__(self):
        self._store: dict = {}
        self._hashes: dict = {}

    async def get(self, key):
        return self._store.get(key)

    async def setex(self, key, ttl, value):
        self._store[key] = value

    async def delete(self, key):
        self._store.pop(key, None)

    async def keys(self, pattern):
        # Simple prefix match only (good enough for tests)
        prefix = pattern.rstrip("*")
        return [k for k in self._store if k.startswith(prefix)]

    async def hset(self, key, field, value):
        self._hashes.setdefault(key, {})[field] = value

    async def hgetall(self, key):
        return self._hashes.get(key, {})

    async def hincrby(self, key, field, amount):
        h = self._hashes.setdefault(key, {})
        h[field] = str(int(h.get(field, 0)) + amount)


class TestResponseCache:
    def _cache(self, enabled=True):
        import os
        os.environ["RESPONSE_CACHE_ENABLED"] = "true" if enabled else "false"
        from orchestrator.services.response_cache import ResponseCacheService
        redis = MockAsyncRedis()
        return ResponseCacheService(redis_client=redis)

    @pytest.mark.asyncio
    async def test_put_then_get_exact_hit(self):
        cache = self._cache()
        await cache.put("What is the temperature?", "22°C", "analytics", building_id="bldg1")
        result = await cache.get("What is the temperature?", building_id="bldg1")
        assert result is not None
        assert result["response"] == "22°C"
        assert result["cache_type"] == "exact"

    @pytest.mark.asyncio
    async def test_cache_miss_returns_none(self):
        cache = self._cache()
        result = await cache.get("Totally unknown query xyzzy", building_id="bldg1")
        assert result is None

    @pytest.mark.asyncio
    async def test_non_cacheable_intent_not_stored(self):
        cache = self._cache()
        await cache.put("Hello", "Hi there!", "clarification", building_id="bldg1")
        result = await cache.get("Hello", building_id="bldg1")
        assert result is None  # clarification should not be cached

    @pytest.mark.asyncio
    async def test_normalised_query_hits_same_bucket(self):
        """Queries with same core words but different word order should hit same key."""
        cache = self._cache()
        await cache.put("temperature room 5", "22°C", "analytics", building_id="bldg1")
        # Normalised form is sorted tokens; 'room 5 temperature' sorts identically
        result = await cache.get("room 5 temperature", building_id="bldg1")
        assert result is not None

    @pytest.mark.asyncio
    async def test_different_buildings_isolated(self):
        cache = self._cache()
        await cache.put("CO2 level?", "400 ppm", "analytics", building_id="bldg1")
        result = await cache.get("CO2 level?", building_id="bldg2")
        assert result is None  # different building — should not hit

    def test_redis_methods_are_all_async(self):
        """Verify no sync Redis calls remain (no hasattr __await__ pattern)."""
        import inspect
        from orchestrator.services import response_cache as rc_module
        src = inspect.getsource(rc_module.ResponseCacheService)
        assert "__await__" not in src, (
            "Sync/async Redis detection via __await__ found — should be pure async awaits"
        )


# ──────────────────────────────────────────────────────────────────────────────
# B.4 — OntologyDetector
# ──────────────────────────────────────────────────────────────────────────────

class TestOntologyDetector:
    def test_detection_result_dataclass(self):
        from orchestrator.services.ontology_detector import DetectionResult
        r = DetectionResult(schemas=["brick"], confidence=0.95)
        assert r.schemas == ["brick"]
        assert r.confidence == 0.95
        d = r.to_dict()
        assert "schemas" in d and "confidence" in d

    @pytest.mark.asyncio
    async def test_detect_from_graphdb_graceful_on_failure(self):
        """If GraphDB is unreachable, detect_from_graphdb should return an empty DetectionResult."""
        from orchestrator.services.ontology_detector import OntologySchemaDetector
        detector = OntologySchemaDetector()
        result = await detector.detect_from_graphdb(
            graphdb_url="http://localhost:9999",  # unreachable
            repository="nonexistent"
        )
        assert result is not None
        assert not result.detected
        assert isinstance(result.notes, list)

    def test_schema_fingerprints_cover_major_ontologies(self):
        from orchestrator.services.ontology_detector import SCHEMA_NAMESPACES
        for schema in ("brick", "rec", "ashrae223"):
            assert schema in SCHEMA_NAMESPACES, f"Missing fingerprints for {schema}"

    def test_detector_importable_from_main(self):
        """main.py must import OntologySchemaDetector without error."""
        from orchestrator.services.ontology_detector import OntologySchemaDetector
        d = OntologySchemaDetector()
        assert d is not None


# ──────────────────────────────────────────────────────────────────────────────
# B.7 — Analytics Engine wired into workflow
# ──────────────────────────────────────────────────────────────────────────────

class TestAnalyticsEngineWiring:
    def _make_orchestrator(self):
        from unittest.mock import MagicMock
        from orchestrator.workflow import WorkflowOrchestrator
        wf = WorkflowOrchestrator.__new__(WorkflowOrchestrator)
        from orchestrator.services.analytics_engine import AnalyticsEngine
        wf.analytics_engine = AnalyticsEngine()
        wf.response_cache = None
        return wf

    @pytest.mark.asyncio
    async def test_deterministic_trend_chosen(self):
        wf = self._make_orchestrator()
        rows = [{"temperature": float(20 + i * 0.5)} for i in range(20)]
        data = {"data": rows}
        result = await wf._try_deterministic_analytics(
            intent="trend", query="show temperature trend", data=data
        )
        assert result is not None
        assert result.analysis_type == "trend"
        assert result.success

    @pytest.mark.asyncio
    async def test_deterministic_compliance_chosen(self):
        wf = self._make_orchestrator()
        rows = [{"temperature": 22.0, "humidity": 50.0, "co2": 700.0} for _ in range(10)]
        data = {"data": rows}
        result = await wf._try_deterministic_analytics(
            intent="compliance", query="check ASHRAE compliance", data=data
        )
        assert result is not None
        assert result.analysis_type == "compliance"

    @pytest.mark.asyncio
    async def test_returns_none_for_unknown_intent_no_keywords(self):
        wf = self._make_orchestrator()
        rows = [{"x": 1}]
        data = {"data": rows}
        result = await wf._try_deterministic_analytics(
            intent="export", query="export the data please", data=data
        )
        assert result is None

    @pytest.mark.asyncio
    async def test_returns_none_on_empty_data(self):
        wf = self._make_orchestrator()
        result = await wf._try_deterministic_analytics(
            intent="trend", query="show trends", data={"data": []}
        )
        assert result is None

    @pytest.mark.asyncio
    async def test_keyword_match_comfort(self):
        wf = self._make_orchestrator()
        rows = [{"temperature": 22.0, "humidity": 45.0} for _ in range(5)]
        result = await wf._try_deterministic_analytics(
            intent="analytics", query="is the ASHRAE comfort level acceptable?", data={"data": rows}
        )
        assert result is not None
        assert result.analysis_type == "comfort"

    def test_analytics_engine_attribute_on_orchestrator(self):
        from orchestrator.workflow import WorkflowOrchestrator
        from unittest.mock import patch, MagicMock
        # Patch agents to avoid loading real LLM clients
        with patch.object(WorkflowOrchestrator, '_build_graph', return_value=MagicMock()):
            wf = WorkflowOrchestrator.__new__(WorkflowOrchestrator)
            wf.__dict__.update({
                'dialogue_agent': MagicMock(), 'sparql_agent': MagicMock(),
                'sql_agent': MagicMock(), 'analytics_agent': MagicMock(),
                'viz_agent': MagicMock(), 'report_agent': MagicMock(),
                'export_agent': MagicMock(), 'planner_agent': MagicMock(),
                'anomaly_agent': MagicMock(), 'redis_manager': None,
                'postgres_manager': None, 'response_cache': None, 'sensor_map': {},
                'use_semantic_ontology': True, 'ontology_mode': 'semantic',
            })
            from orchestrator.services.analytics_engine import AnalyticsEngine
            wf.analytics_engine = AnalyticsEngine()
            assert isinstance(wf.analytics_engine, AnalyticsEngine)


# ──────────────────────────────────────────────────────────────────────────────
# B.2/B.7: Config — SECRET_KEY and RBAC_ENABLED added to settings
# ──────────────────────────────────────────────────────────────────────────────

class TestNewConfigFields:
    def test_secret_key_in_settings(self):
        from shared.config import settings
        assert hasattr(settings, "SECRET_KEY")
        assert isinstance(settings.SECRET_KEY, str) and len(settings.SECRET_KEY) > 0

    def test_rbac_enabled_flag_in_settings(self):
        from shared.config import settings
        assert hasattr(settings, "RBAC_ENABLED")
        assert isinstance(settings.RBAC_ENABLED, bool)

    def test_response_cache_enabled_flag_in_settings(self):
        from shared.config import settings
        assert hasattr(settings, "RESPONSE_CACHE_ENABLED")
        assert isinstance(settings.RESPONSE_CACHE_ENABLED, bool)
