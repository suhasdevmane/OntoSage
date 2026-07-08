"""Tests for T35 — UserPreferenceStore (Redis-backed per-user comfort preferences)."""

import json
import pytest
from unittest.mock import AsyncMock, MagicMock, patch


@pytest.fixture()
def mock_redis():
    """Patch redis_manager with an in-memory dict backend."""
    store: dict = {}

    async def _set(key, value, ttl=None):
        store[key] = value

    async def _get(key):
        return store.get(key)

    async def _delete(key):
        existed = key in store
        store.pop(key, None)
        return existed

    async def _scan_iter(match="*"):
        import fnmatch

        for k in list(store.keys()):
            if fnmatch.fnmatch(k, match):
                yield k

    redis_mock = MagicMock()
    redis_mock.scan_iter = _scan_iter
    redis_mock.get = AsyncMock(side_effect=lambda k: store.get(k))
    redis_mock.delete = AsyncMock(side_effect=lambda k: store.pop(k, None))

    manager_mock = MagicMock()
    manager_mock.set_cache = AsyncMock(side_effect=_set)
    manager_mock.get_cache = AsyncMock(side_effect=_get)
    manager_mock.delete_cache = AsyncMock(side_effect=_delete)
    # The store accesses Redis via the canonical _ensure_client() helper
    # (fix 2026-06-12 — the old mock exposed a `.redis` attribute that the
    # real RedisManager never had, so the mock made broken code pass).
    manager_mock._ensure_client = AsyncMock(return_value=redis_mock)
    manager_mock.redis = redis_mock

    with patch("orchestrator.services.user_preference_store.get_user_preference_store") as _:
        with patch("orchestrator.redis_manager.redis_manager", manager_mock):
            yield manager_mock, store


@pytest.fixture()
def pref_store(mock_redis):
    from orchestrator.services.user_preference_store import UserPreferenceStore

    return UserPreferenceStore()


@pytest.mark.unit
@pytest.mark.asyncio
async def test_set_and_get_temperature_preference(pref_store):
    ok = await pref_store.set_preference(
        "user1", "temperature_comfort", pref_min=22.0, pref_max=24.0, raw="I prefer 22 to 24"
    )
    assert ok is True
    pref = await pref_store.get_preference("user1", "temperature_comfort")
    assert pref is not None
    assert pref["pref_min"] == 22.0
    assert pref["pref_max"] == 24.0
    assert pref["unit"] == "°C"
    assert pref["label"] == "Temperature comfort range"


@pytest.mark.unit
@pytest.mark.asyncio
async def test_get_nonexistent_preference_returns_none(pref_store):
    result = await pref_store.get_preference("user_nobody", "temperature_comfort")
    assert result is None


@pytest.mark.unit
@pytest.mark.asyncio
async def test_list_preferences_empty(pref_store):
    prefs = await pref_store.list_preferences("user_no_prefs")
    assert prefs == []


@pytest.mark.unit
@pytest.mark.asyncio
async def test_list_preferences_returns_stored(pref_store):
    await pref_store.set_preference("user2", "temperature_comfort", pref_min=20.0, pref_max=23.0)
    await pref_store.set_preference("user2", "noise_comfort", pref_max=45.0)
    prefs = await pref_store.list_preferences("user2")
    assert len(prefs) == 2
    cats = {p["category"] for p in prefs}
    assert "temperature_comfort" in cats
    assert "noise_comfort" in cats


@pytest.mark.unit
@pytest.mark.asyncio
async def test_delete_specific_preference(pref_store):
    await pref_store.set_preference("user3", "humidity_comfort", pref_min=40.0, pref_max=60.0)
    deleted = await pref_store.delete_preference("user3", "humidity_comfort")
    assert deleted is True
    pref = await pref_store.get_preference("user3", "humidity_comfort")
    assert pref is None


@pytest.mark.unit
@pytest.mark.asyncio
async def test_delete_nonexistent_preference_returns_false(pref_store):
    result = await pref_store.delete_preference("user4", "noise_comfort")
    assert result is False


@pytest.mark.unit
@pytest.mark.asyncio
async def test_delete_all_preferences(pref_store):
    await pref_store.set_preference("user5", "temperature_comfort", pref_min=22.0)
    await pref_store.set_preference("user5", "humidity_comfort", pref_min=40.0)
    count = await pref_store.delete_all_preferences("user5")
    assert count == 2
    prefs = await pref_store.list_preferences("user5")
    assert prefs == []


@pytest.mark.unit
@pytest.mark.asyncio
async def test_preferences_are_user_isolated(pref_store):
    await pref_store.set_preference("alice", "temperature_comfort", pref_min=22.0, pref_max=24.0)
    await pref_store.set_preference("bob", "temperature_comfort", pref_min=18.0, pref_max=20.0)
    alice_pref = await pref_store.get_preference("alice", "temperature_comfort")
    bob_pref = await pref_store.get_preference("bob", "temperature_comfort")
    assert alice_pref["pref_min"] == 22.0
    assert bob_pref["pref_min"] == 18.0


@pytest.mark.unit
@pytest.mark.asyncio
async def test_update_preference_overwrites(pref_store):
    await pref_store.set_preference("user6", "temperature_comfort", pref_min=20.0, pref_max=22.0)
    await pref_store.set_preference("user6", "temperature_comfort", pref_min=23.0, pref_max=25.0)
    pref = await pref_store.get_preference("user6", "temperature_comfort")
    assert pref["pref_min"] == 23.0
    assert pref["pref_max"] == 25.0


@pytest.mark.unit
def test_category_keywords_cover_temperature():
    from orchestrator.services.user_preference_store import CATEGORY_KEYWORDS

    assert CATEGORY_KEYWORDS.get("temperature") == "temperature_comfort"
    assert CATEGORY_KEYWORDS.get("warm") == "temperature_comfort"
    assert CATEGORY_KEYWORDS.get("humidity") == "humidity_comfort"
    assert CATEGORY_KEYWORDS.get("noise") == "noise_comfort"


@pytest.mark.unit
def test_preference_management_node_exists_on_orchestrator():
    from orchestrator.workflow._orchestrator import WorkflowOrchestrator

    assert hasattr(
        WorkflowOrchestrator, "_preference_management_node"
    ), "_preference_management_node missing from WorkflowOrchestrator"
