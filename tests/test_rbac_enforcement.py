"""Unit tests for the session→RBAC bridge (P0 security hardening).

Covers the dependency layer added in orchestrator/main.py:
  - get_user_context()      session → UserContext mapping
  - require_permission()     401 (anonymous) / 403 (wrong role) / pass
  - _user_owns_conversation() ownership semantics

These are offline tests — they monkeypatch auth_manager.validate_session_context
and never touch Redis/Postgres.
"""

import pytest

import orchestrator.main as main
from orchestrator.main import (
    _user_owns_conversation,
    get_user_context,
    require_permission,
)
from orchestrator.middleware.rbac import ROLE_PERMISSIONS, UserContext

pytestmark = pytest.mark.unit


class _StubAuth:
    """Minimal stand-in for AuthManager with a single configured session."""

    def __init__(self, token_to_ctx):
        self._map = token_to_ctx

    async def validate_session_context(self, token):
        return self._map.get(token)


def _fm_ctx(username="alice"):
    return UserContext(
        user_id=username,
        username=username,
        role="facility_manager",
        tenant_id="default",
        allowed_buildings=[],
        permissions=ROLE_PERMISSIONS["facility_manager"],
    )


@pytest.mark.asyncio
async def test_get_user_context_maps_role_to_permissions(monkeypatch):
    monkeypatch.setattr(
        main, "auth_manager", _StubAuth({"tok": {"username": "alice", "role": "facility_manager"}})
    )
    ctx = await get_user_context(session_token="tok", authorization=None)
    assert ctx is not None
    assert ctx.username == "alice"
    assert ctx.role == "facility_manager"
    assert ctx.has_permission("sensor:read")
    # facility_manager is broad but is NOT a system admin
    assert not ctx.has_permission("system:admin")


@pytest.mark.asyncio
async def test_get_user_context_none_without_token(monkeypatch):
    monkeypatch.setattr(main, "auth_manager", _StubAuth({}))
    assert await get_user_context(session_token=None, authorization=None) is None


@pytest.mark.asyncio
async def test_get_user_context_unknown_role_defaults_safe(monkeypatch):
    monkeypatch.setattr(
        main, "auth_manager", _StubAuth({"tok": {"username": "bob", "role": "nonsense"}})
    )
    ctx = await get_user_context(session_token="tok", authorization=None)
    # Unknown role → readonly permission set (fail-safe), never empty/all
    assert ctx.has_permission("metadata:read")
    assert not ctx.has_permission("sensor:read")


@pytest.mark.asyncio
async def test_require_permission_401_when_anonymous():
    dep = require_permission("sensor:read")
    with pytest.raises(Exception) as exc:
        await dep(user=None)
    assert getattr(exc.value, "status_code", None) == 401


@pytest.mark.asyncio
async def test_require_permission_403_when_role_lacks_permission():
    readonly = UserContext(
        user_id="r",
        username="r",
        role="readonly",
        tenant_id="default",
        allowed_buildings=[],
        permissions=ROLE_PERMISSIONS["readonly"],
    )
    dep = require_permission("sensor:read")
    with pytest.raises(Exception) as exc:
        await dep(user=readonly)
    assert getattr(exc.value, "status_code", None) == 403


@pytest.mark.asyncio
async def test_require_permission_allows_authorized():
    dep = require_permission("sensor:read")
    ctx = _fm_ctx()
    assert await dep(user=ctx) is ctx


def test_user_owns_conversation_by_suffix():
    ctx = _fm_ctx("alice")
    assert _user_owns_conversation(ctx, "conv_123:alice")
    assert not _user_owns_conversation(ctx, "conv_123:bob")


def test_user_owns_conversation_admin_bypass():
    admin = UserContext(
        user_id="admin",
        username="admin",
        role="admin",
        tenant_id="default",
        allowed_buildings=[],
        permissions=ROLE_PERMISSIONS["admin"],
    )
    # admin has user:read → may access anyone's conversation
    assert _user_owns_conversation(admin, "conv_123:someone_else")
