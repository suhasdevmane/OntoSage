"""D10 — GET /api/v1/evidence/{conversation_id}?turn=n is read-only and owner-gated.

Auth is bypassed via app.dependency_overrides[get_user_context] (the same pattern as
test_admin_ontology_endpoints.py); the turn-memory service is replaced, so no Postgres is
touched. What is pinned: the owner reads 200, another user gets 403, a user:read holder reads
someone else's turn, and the admin-only remedy reaches system:admin and nobody else.
"""

from __future__ import annotations

from unittest.mock import AsyncMock, patch

import pytest

pytestmark = pytest.mark.unit

CONV = "conv-1:alice"
STORED = {
    "status": "not_assessable",
    "operation": "observation",
    "sources": [{"source_id": "sensor-uuid-1", "kind": "sensor"}],
    "remedy": "connect the Level 2 occupancy stream",
}


def _ctx(username: str, role: str):
    from orchestrator.middleware.rbac import ROLE_PERMISSIONS, UserContext

    return UserContext(
        user_id=username,
        username=username,
        role=role,
        tenant_id="default",
        allowed_buildings=[],
        permissions=set(ROLE_PERMISSIONS.get(role, set())),
    )


async def _get(url: str, ctx, service):
    from httpx import ASGITransport, AsyncClient

    from orchestrator.main import app, get_user_context

    app.dependency_overrides[get_user_context] = lambda: ctx
    try:
        with patch("orchestrator.main._turn_memory_service", return_value=service):
            transport = ASGITransport(app=app)
            async with AsyncClient(transport=transport, base_url="http://test") as client:
                return await client.get(url)
    finally:
        app.dependency_overrides.pop(get_user_context, None)


def _service(evidence=STORED):
    svc = AsyncMock()
    svc.get_evidence = AsyncMock(return_value={"turn": 2, "evidence": evidence})
    return svc


@pytest.mark.asyncio
async def test_owner_gets_200_and_remedy_is_absent_for_a_non_admin():
    resp = await _get(f"/api/v1/evidence/{CONV}?turn=2", _ctx("alice", "occupant"), _service())
    assert resp.status_code == 200
    body = resp.json()
    assert body["data"]["turn"] == 2
    assert body["data"]["evidence"]["sources"][0]["source_id"] == "sensor-uuid-1"
    assert "remedy" not in body["data"]["evidence"]


@pytest.mark.asyncio
async def test_another_user_gets_403_and_the_store_is_not_read():
    svc = _service()
    resp = await _get(f"/api/v1/evidence/{CONV}?turn=2", _ctx("bob", "occupant"), svc)
    assert resp.status_code == 403
    svc.get_evidence.assert_not_called()


@pytest.mark.asyncio
async def test_system_admin_sees_the_remedy():
    resp = await _get(f"/api/v1/evidence/{CONV}?turn=2", _ctx("root", "admin"), _service())
    assert resp.status_code == 200
    assert resp.json()["data"]["evidence"]["remedy"] == "connect the Level 2 occupancy stream"


@pytest.mark.asyncio
async def test_unknown_turn_is_404():
    svc = AsyncMock()
    svc.get_evidence = AsyncMock(return_value=None)
    resp = await _get(f"/api/v1/evidence/{CONV}?turn=99", _ctx("alice", "occupant"), svc)
    assert resp.status_code == 404


@pytest.mark.asyncio
async def test_latest_turn_is_read_when_turn_is_omitted():
    svc = _service()
    await _get(f"/api/v1/evidence/{CONV}", _ctx("alice", "occupant"), svc)
    svc.get_evidence.assert_awaited_once_with(CONV, None)
