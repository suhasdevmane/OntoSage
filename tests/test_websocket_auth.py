"""Unit tests for the security hardening on main.py:

  - _authenticate_websocket()  /stream handshake auth (proxy key vs session)
  - _oai_auth()                constant-time pipeline-key check on /v1

Offline: monkeypatches main.auth_manager and never touches Redis/Postgres.
These cover the previously-unauthenticated WebSocket (IDOR + full-pipeline
exposure) and the constant-time key-compare hardening.
"""

import pytest

import orchestrator.main as main
from orchestrator.main import _authenticate_websocket, _oai_auth

pytestmark = pytest.mark.unit


class _StubAuth:
    """Minimal AuthManager stand-in with a fixed token→context map."""

    def __init__(self, token_to_ctx):
        self._map = token_to_ctx

    async def validate_session_context(self, token):
        return self._map.get(token)


class _FakeWS:
    """Just enough of starlette.WebSocket for _authenticate_websocket()."""

    def __init__(self, headers=None, query=None):
        self.headers = headers or {}
        self.query_params = query or {}


def _any_pipeline_key() -> str:
    # Avoid hardcoding the env-dependent default; read what the app accepts.
    assert main._OAI_AUTH_KEYS, "expected at least one configured pipeline key"
    return next(iter(main._OAI_AUTH_KEYS))


# ── _authenticate_websocket ──────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_ws_auth_rejects_no_token(monkeypatch):
    monkeypatch.setattr(main, "auth_manager", _StubAuth({}))
    assert await _authenticate_websocket(_FakeWS()) is None


@pytest.mark.asyncio
async def test_ws_auth_rejects_bad_token(monkeypatch):
    monkeypatch.setattr(main, "auth_manager", _StubAuth({}))
    assert await _authenticate_websocket(_FakeWS(query={"token": "WRONGKEY"})) is None


@pytest.mark.asyncio
async def test_ws_auth_pipeline_key_via_query_is_proxy(monkeypatch):
    monkeypatch.setattr(main, "auth_manager", _StubAuth({}))
    auth = await _authenticate_websocket(_FakeWS(query={"token": _any_pipeline_key()}))
    assert auth is not None
    assert auth["mode"] == "proxy"
    # Untrusted forwarded identity must not be privileged.
    assert auth["role"] == "readonly"
    assert auth["is_admin"] is False


@pytest.mark.asyncio
async def test_ws_auth_pipeline_key_via_bearer_header_is_proxy(monkeypatch):
    monkeypatch.setattr(main, "auth_manager", _StubAuth({}))
    hdr = {"authorization": f"Bearer {_any_pipeline_key()}"}
    auth = await _authenticate_websocket(_FakeWS(headers=hdr))
    assert auth is not None and auth["mode"] == "proxy"


@pytest.mark.asyncio
async def test_ws_auth_session_token_resolves_user(monkeypatch):
    monkeypatch.setattr(
        main, "auth_manager", _StubAuth({"sess": {"username": "alice", "role": "facility_manager"}})
    )
    auth = await _authenticate_websocket(_FakeWS(query={"token": "sess"}))
    assert auth is not None
    assert auth["mode"] == "session"
    assert auth["username"] == "alice"
    assert auth["role"] == "facility_manager"
    # facility_manager is not an admin (no user:read) → cannot read others' convos.
    assert auth["is_admin"] is False


@pytest.mark.asyncio
async def test_ws_auth_admin_session_is_admin(monkeypatch):
    monkeypatch.setattr(
        main, "auth_manager", _StubAuth({"sess": {"username": "root", "role": "admin"}})
    )
    auth = await _authenticate_websocket(_FakeWS(query={"token": "sess"}))
    assert auth is not None and auth["mode"] == "session"
    assert auth["is_admin"] is True


# ── _oai_auth (constant-time key check) ──────────────────────────────────────


def test_oai_auth_accepts_valid_key():
    # Should not raise.
    _oai_auth(authorization=f"Bearer {_any_pipeline_key()}")


def test_oai_auth_rejects_missing_header():
    with pytest.raises(Exception) as exc:
        _oai_auth(authorization=None)
    assert getattr(exc.value, "status_code", None) == 401


def test_oai_auth_rejects_wrong_key():
    with pytest.raises(Exception) as exc:
        _oai_auth(authorization="Bearer not-the-key")
    assert getattr(exc.value, "status_code", None) == 401


def test_oai_auth_rejects_empty_token():
    with pytest.raises(Exception) as exc:
        _oai_auth(authorization="Bearer    ")
    assert getattr(exc.value, "status_code", None) == 401
