"""T21 — UserAlertStore unit tests.

Covers:
  1. create_alert returns an 8-char rule_id
  2. list_alerts returns created rules
  3. delete_alert removes rule
  4. get_all_building_alerts returns rules across users
  5. Redis error during create is non-fatal (returns ID anyway)
  6. Redis error during list returns empty list
  7. EcaRule can be constructed from user alert doc (for RulesEngine integration)
  8. auto_name helper generates readable name
  9. load_user_rules() adds user rules to RulesEngine
  10. load_user_rules() skips already-loaded rules (no duplicates)
"""
from __future__ import annotations

import json
import uuid
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from orchestrator.services.user_alert_store import UserAlertStore, get_user_alert_store
from orchestrator.services.rules_engine import EcaRule, RulesEngine


# ── helpers ────────────────────────────────────────────────────────────────────

_TRIGGER = {"concept": "co2", "op": ">", "threshold": 1000.0, "duration_min": 0}
_ACTION = {"type": "notify", "message": "CO2 high", "severity": "warning"}


async def _make_store_with_rules(rules: list) -> UserAlertStore:
    """Build a UserAlertStore where Redis returns the provided list of rules."""
    store = UserAlertStore()
    docs = [
        {
            "id": r["id"],
            "name": r.get("name", ""),
            "enabled": True,
            "trigger": r["trigger"],
            "action": r["action"],
            "user_id": r["user_id"],
            "building_id": "bldg_test",
        }
        for r in rules
    ]

    # Patch Redis scan_iter + get_cache
    mock_client = AsyncMock()
    # scan_iter returns keys as async generator
    async def fake_scan_iter(match=None, count=100):
        for i, doc in enumerate(docs):
            yield f"user:alert:bldg_test:user1:{doc['id']}"

    mock_client.scan_iter = fake_scan_iter

    async def fake_get_cache(key):
        for doc in docs:
            if doc["id"] in key:
                return json.dumps(doc)
        return None

    with patch("orchestrator.redis_manager.redis_manager") as mock_rm:
        mock_rm._ensure_client = AsyncMock(return_value=mock_client)
        mock_rm.get_cache = AsyncMock(side_effect=fake_get_cache)
        result = await store.get_all_building_alerts("bldg_test")

    return store, result


# ── tests ──────────────────────────────────────────────────────────────────────


@pytest.mark.unit
@pytest.mark.asyncio
async def test_create_alert_returns_8char_id():
    store = UserAlertStore()
    with patch("orchestrator.redis_manager.redis_manager") as mock_rm:
        mock_rm.set_cache = AsyncMock()
        rule_id = await store.create_alert("user1", "bldg_test", _TRIGGER, _ACTION)
    assert len(rule_id) == 8
    assert rule_id.replace("-", "").isalnum()


@pytest.mark.unit
@pytest.mark.asyncio
async def test_list_alerts_returns_created_rules():
    store = UserAlertStore()
    stored: dict = {}

    async def fake_set(key, value, ttl=None):
        stored[key] = value

    async def fake_scan_iter(match=None, count=100):
        for k in stored:
            if match and match.rstrip("*") in k:
                yield k

    async def fake_get(key):
        return stored.get(key)

    mock_client = AsyncMock()
    mock_client.scan_iter = fake_scan_iter

    with patch("orchestrator.redis_manager.redis_manager") as mock_rm:
        mock_rm.set_cache = AsyncMock(side_effect=fake_set)
        mock_rm._ensure_client = AsyncMock(return_value=mock_client)
        mock_rm.get_cache = AsyncMock(side_effect=fake_get)

        rule_id = await store.create_alert("user1", "bldg_test", _TRIGGER, _ACTION)
        rules = await store.list_alerts("user1", "bldg_test")

    assert len(rules) == 1
    assert rules[0]["id"] == rule_id


@pytest.mark.unit
@pytest.mark.asyncio
async def test_delete_alert_removes_rule():
    store = UserAlertStore()
    deleted_keys = []

    async def fake_delete(key):
        deleted_keys.append(key)

    with patch("orchestrator.redis_manager.redis_manager") as mock_rm:
        mock_rm.delete_cache = AsyncMock(side_effect=fake_delete)
        ok = await store.delete_alert("user1", "bldg_test", "abc12345")

    assert ok is True
    assert any("abc12345" in k for k in deleted_keys)


@pytest.mark.unit
@pytest.mark.asyncio
async def test_get_all_building_alerts_returns_rules_across_users():
    docs = [
        {"id": "rule0001", "name": "CO2 rule", "trigger": _TRIGGER, "action": _ACTION, "user_id": "alice"},
        {"id": "rule0002", "name": "Temp rule", "trigger": {**_TRIGGER, "threshold": 28.0}, "action": _ACTION, "user_id": "bob"},
    ]
    _, result = await _make_store_with_rules(docs)
    assert len(result) == 2


@pytest.mark.unit
@pytest.mark.asyncio
async def test_create_alert_redis_error_returns_id():
    store = UserAlertStore()
    with patch("orchestrator.redis_manager.redis_manager") as mock_rm:
        mock_rm.set_cache = AsyncMock(side_effect=ConnectionError("Redis down"))
        rule_id = await store.create_alert("user1", "bldg_test", _TRIGGER, _ACTION)
    # Returns an ID even if Redis write fails (logged as warning)
    assert len(rule_id) == 8


@pytest.mark.unit
@pytest.mark.asyncio
async def test_list_alerts_redis_error_returns_empty():
    store = UserAlertStore()
    with patch("orchestrator.redis_manager.redis_manager") as mock_rm:
        mock_rm._ensure_client = AsyncMock(side_effect=ConnectionError("Redis down"))
        rules = await store.list_alerts("user1", "bldg_test")
    assert rules == []


@pytest.mark.unit
def test_eca_rule_from_user_alert_doc():
    doc = {
        "id": "test1234",
        "name": "CO2 test",
        "enabled": True,
        "trigger": _TRIGGER,
        "action": _ACTION,
    }
    rule = EcaRule(**doc)
    assert rule.id == "test1234"
    assert rule.trigger.threshold == 1000.0
    assert rule.trigger.op == ">"
    assert rule.trigger.concept == "co2"


@pytest.mark.unit
def test_auto_name_helper():
    name = UserAlertStore._auto_name({"concept": "stuffy", "op": ">", "threshold": 1000})
    assert "stuffy" in name
    assert "1000" in name


@pytest.mark.unit
@pytest.mark.asyncio
async def test_load_user_rules_adds_to_engine():
    docs = [
        {"id": "urule001", "name": "User CO2", "enabled": True, "trigger": _TRIGGER, "action": _ACTION, "user_id": "alice"},
    ]

    engine = RulesEngine("bldg_test", value_fetcher=AsyncMock(return_value=None), notifier=AsyncMock())
    engine._rules = []  # start empty (no operator rules)

    async def fake_get_all(building_id):
        return [{"id": d["id"], "name": d["name"], "enabled": True,
                 "trigger": d["trigger"], "action": d["action"]} for d in docs]

    mock_store = MagicMock()
    mock_store.get_all_building_alerts = AsyncMock(side_effect=fake_get_all)

    with patch("orchestrator.services.user_alert_store.get_user_alert_store", return_value=mock_store):
        added = await engine.load_user_rules()

    assert added == 1
    assert engine.rules[0].id == "urule001"


@pytest.mark.unit
@pytest.mark.asyncio
async def test_load_user_rules_no_duplicates():
    doc = {"id": "urule001", "name": "User CO2", "enabled": True, "trigger": _TRIGGER, "action": _ACTION}
    engine = RulesEngine("bldg_test", value_fetcher=AsyncMock(return_value=None), notifier=AsyncMock())
    engine._rules = [EcaRule(**doc)]  # already loaded

    async def fake_get_all(building_id):
        return [dict(doc)]  # same rule again

    mock_store = MagicMock()
    mock_store.get_all_building_alerts = AsyncMock(side_effect=fake_get_all)

    with patch("orchestrator.services.user_alert_store.get_user_alert_store", return_value=mock_store):
        added = await engine.load_user_rules()

    assert added == 0
    assert len(engine.rules) == 1  # still only one
