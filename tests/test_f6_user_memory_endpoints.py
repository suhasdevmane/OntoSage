# -*- coding: utf-8 -*-
"""F6: GET and DELETE /api/v1/me/memory.

The identity is the one the chat turn uses (resolve_forwarded_user), never a session. The
shared fallback identity is refused with a reason, because it is not a person. The route is
gated by the pipeline key, the same gate /v1 uses; that is what the forwarded header rests on.

Every store is a fake: preferences, turn memory and the identity resolver.
"""

from typing import Any, Dict, List
from unittest.mock import AsyncMock, patch

import pytest

pytestmark = pytest.mark.unit


class _FakePrefStore:
    def __init__(self, prefs: Dict[str, List[Dict[str, Any]]]):
        self._prefs = prefs
        self.deleted_for: List[str] = []

    async def list_preferences(self, user_id: str):
        return list(self._prefs.get(user_id, []))

    async def delete_all_preferences(self, user_id: str) -> int:
        self.deleted_for.append(user_id)
        return len(self._prefs.pop(user_id, []))


class _FakeTurnMemory:
    def __init__(self, turns: Dict[str, int]):
        self._turns = turns
        self.deleted_for: List[str] = []

    async def count_user_turns(self, user_id: str) -> int:
        return self._turns.get(user_id, 0)

    async def delete_user_turns(self, user_id: str) -> int:
        self.deleted_for.append(user_id)
        return self._turns.pop(user_id, 0)


ALICE_PREFS = [
    {"category": "comfort", "value": "22-24 C", "user_id": "alice"},
    {"category": "lighting", "value": "warm", "user_id": "alice"},
]


@pytest.fixture
def app_client(monkeypatch):
    """The real app with the pipeline-key gate overridden; stores and identity are fakes."""
    from httpx import ASGITransport, AsyncClient

    import orchestrator.main as main
    import orchestrator.services.user_preference_store as ups

    prefs = _FakePrefStore({"alice": list(ALICE_PREFS), "bob": [{"category": "x"}]})
    turns = _FakeTurnMemory({"alice": 12, "bob": 3})
    monkeypatch.setattr(ups, "_store", prefs)
    monkeypatch.setattr(main, "_turn_memory_service", lambda: turns)

    app = main.app
    app.dependency_overrides[main._oai_auth] = lambda: None
    state = {"prefs": prefs, "turns": turns}

    def _client(identity):
        resolver = AsyncMock(return_value=identity)
        ctx = patch.object(main, "resolve_forwarded_user", resolver)
        return ctx, AsyncClient(transport=ASGITransport(app=app), base_url="http://test"), resolver

    try:
        yield _client, state
    finally:
        app.dependency_overrides.pop(main._oai_auth, None)


@pytest.mark.asyncio
async def test_get_lists_the_identified_users_preferences_and_turn_count(app_client):
    make, _state = app_client
    ctx, client, resolver = make(("alice", "analyst"))
    with ctx:
        async with client as c:
            r = await c.get("/api/v1/me/memory")

    assert r.status_code == 200
    body = r.json()["data"]
    assert body["user"] == "alice"
    assert body["turn_count"] == 12
    assert [p["category"] for p in body["preferences"]] == ["comfort", "lighting"]
    resolver.assert_awaited_once()  # identity came from the forwarded-user path


@pytest.mark.asyncio
async def test_delete_erases_only_the_identified_users_memory_and_reports_counts(app_client):
    make, state = app_client
    ctx, client, _ = make(("alice", "analyst"))
    with ctx:
        async with client as c:
            r = await c.delete("/api/v1/me/memory")

    assert r.status_code == 200
    data = r.json()["data"]
    assert data == {
        "user": "alice",
        "preferences_deleted": 2,
        "turn_records_deleted": 12,
    }
    assert state["prefs"].deleted_for == ["alice"]
    assert state["turns"].deleted_for == ["alice"]
    # bob's memory is untouched: a request for alice never names bob's partition.
    assert state["turns"]._turns == {"bob": 3}
    assert "bob" in state["prefs"]._prefs


@pytest.mark.asyncio
@pytest.mark.parametrize("method", ["get", "delete"])
async def test_shared_fallback_identity_is_refused_with_a_reason(app_client, method):
    make, state = app_client
    ctx, client, _ = make(("openwebui_user", "readonly"))
    with ctx:
        async with client as c:
            r = await getattr(c, method)("/api/v1/me/memory")

    assert r.status_code == 403
    detail = r.json()["detail"]
    assert "openwebui_user" in detail
    assert "shared fallback" in detail
    # Nothing was listed or erased on the shared partition.
    assert state["turns"].deleted_for == []
    assert state["prefs"].deleted_for == []


@pytest.mark.asyncio
async def test_no_pipeline_key_is_rejected_before_any_store_is_read(monkeypatch):
    """The gate is the pipeline key, the same as /v1: no key, no memory."""
    from httpx import ASGITransport, AsyncClient

    import orchestrator.main as main

    called = AsyncMock(return_value=("alice", "analyst"))
    with patch.object(main, "resolve_forwarded_user", called):
        async with AsyncClient(transport=ASGITransport(app=main.app), base_url="http://t") as c:
            r = await c.get("/api/v1/me/memory")

    assert r.status_code == 401
    called.assert_not_awaited()


def test_routes_are_registered_with_the_expected_methods():
    import orchestrator.main as main

    routes = {
        (method, route.path)
        for route in main.app.routes
        for method in getattr(route, "methods", set()) or set()
    }
    assert ("GET", "/api/v1/me/memory") in routes
    assert ("DELETE", "/api/v1/me/memory") in routes
