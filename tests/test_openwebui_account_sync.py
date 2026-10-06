"""One set of accounts for OntoSage and Open WebUI.

(a) An admin-created OntoSage account is mirrored into Open WebUI.
(b) A first sign-in through Open WebUI creates a readonly OntoSage account.
All Open WebUI HTTP is mocked with httpx.MockTransport; no network is used.
"""

from __future__ import annotations

import asyncio
import json
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

import httpx
import pytest

from orchestrator.services import openwebui_sync as sync

pytestmark = pytest.mark.unit

ADMIN_EMAIL = "owui-admin@example.com"
ADMIN_PASSWORD = "admin-pass-for-tests-123"


def _configured(**overrides):
    values = {
        "OPENWEBUI_ADMIN_EMAIL": ADMIN_EMAIL,
        "OPENWEBUI_ADMIN_PASSWORD": ADMIN_PASSWORD,
        "OPENWEBUI_URL": "http://owui.test",
    }
    values.update(overrides)
    return patch.multiple(sync.settings, **values)


def _transport(handler):
    return httpx.MockTransport(handler)


def _signin_ok(request: httpx.Request):
    body = json.loads(request.content)
    if body == {"email": ADMIN_EMAIL, "password": ADMIN_PASSWORD}:
        return httpx.Response(200, json={"token": "tok-123", "role": "admin"})
    return httpx.Response(400, json={"detail": "Incorrect password"})


def _no_call(request: httpx.Request):
    raise AssertionError(f"unexpected HTTP call: {request.method} {request.url}")


# ---------------------------------------------------------------- ensure_openwebui_user


@pytest.mark.asyncio
async def test_unset_admin_email_is_a_silent_skip_with_no_http():
    with patch.multiple(sync.settings, OPENWEBUI_ADMIN_EMAIL="", OPENWEBUI_ADMIN_PASSWORD="x"):
        res = await sync.ensure_openwebui_user(
            "a@example.com", "a", "pw-123456789012", transport=_transport(_no_call)
        )
    assert res.status == "skipped"
    assert "OPENWEBUI_ADMIN_EMAIL" in res.reason


@pytest.mark.asyncio
async def test_unset_admin_password_is_a_skip_with_no_http():
    with patch.multiple(
        sync.settings, OPENWEBUI_ADMIN_EMAIL=ADMIN_EMAIL, OPENWEBUI_ADMIN_PASSWORD=""
    ):
        res = await sync.ensure_openwebui_user(
            "a@example.com", "a", "pw-123456789012", transport=_transport(_no_call)
        )
    assert res.status == "skipped"
    assert "OPENWEBUI_ADMIN_PASSWORD" in res.reason


@pytest.mark.asyncio
async def test_missing_email_is_skipped_not_sent_to_open_webui():
    with _configured():
        res = await sync.ensure_openwebui_user(
            "", "a", "pw-123456789012", transport=_transport(_no_call)
        )
    assert res.status == "skipped"


@pytest.mark.asyncio
async def test_existing_account_is_reported_and_not_recreated():
    seen_add = []

    def handler(request):
        if request.url.path == "/api/v1/auths/signin":
            return _signin_ok(request)
        if request.url.path == "/api/v1/users/":
            assert request.headers["authorization"] == "Bearer tok-123"
            return httpx.Response(
                200, json={"users": [{"email": "Analyst01@Example.com", "name": "a"}], "total": 1}
            )
        seen_add.append(request)
        return httpx.Response(200, json={})

    with _configured():
        res = await sync.ensure_openwebui_user(
            "analyst01@example.com", "analyst01", "pw-123456789012", transport=_transport(handler)
        )
    assert res.status == "exists"
    assert seen_add == []


@pytest.mark.asyncio
async def test_missing_account_is_created_with_the_supplied_password():
    added = {}

    def handler(request):
        if request.url.path == "/api/v1/auths/signin":
            return _signin_ok(request)
        if request.url.path == "/api/v1/users/":
            return httpx.Response(200, json={"users": [], "total": 0})
        if request.url.path == "/api/v1/auths/add":
            added.update(json.loads(request.content))
            added["auth"] = request.headers["authorization"]
            return httpx.Response(200, json={"id": "u1", "token": "x"})
        raise AssertionError(request.url.path)

    with _configured():
        res = await sync.ensure_openwebui_user(
            "New.User@example.com", "new_user", "pw-123456789012", transport=_transport(handler)
        )
    assert res.status == "created"
    assert added["email"] == "new.user@example.com"
    assert added["password"] == "pw-123456789012"
    assert added["name"] == "new_user"
    assert added["role"] == "user"
    assert added["auth"] == "Bearer tok-123"


@pytest.mark.asyncio
async def test_listing_pages_until_the_account_is_found():
    def handler(request):
        if request.url.path == "/api/v1/auths/signin":
            return _signin_ok(request)
        if request.url.path == "/api/v1/users/":
            page = int(request.url.params["page"])
            users = [{"email": f"other{page}@example.com"}]
            if page == 2:
                users.append({"email": "target@example.com"})
            return httpx.Response(200, json=users)  # bare-list shape
        raise AssertionError("should not add when the account exists")

    with _configured():
        res = await sync.ensure_openwebui_user(
            "target@example.com", "t", "pw-123456789012", transport=_transport(handler)
        )
    assert res.status == "exists"


@pytest.mark.asyncio
async def test_add_refused_as_already_taken_is_exists_not_failure():
    def handler(request):
        if request.url.path == "/api/v1/auths/signin":
            return _signin_ok(request)
        if request.url.path == "/api/v1/users/":
            return httpx.Response(200, json={"users": []})
        return httpx.Response(400, json={"detail": "The email is already taken"})

    with _configured():
        res = await sync.ensure_openwebui_user(
            "race@example.com", "r", "pw-123456789012", transport=_transport(handler)
        )
    assert res.status == "exists"


@pytest.mark.asyncio
async def test_wrong_admin_password_is_failed_with_reason_and_never_raises():
    def handler(request):
        return httpx.Response(400, json={"detail": "Incorrect password"})

    with _configured():
        res = await sync.ensure_openwebui_user(
            "a@example.com", "a", "pw-123456789012", transport=_transport(handler)
        )
    assert res.status == "failed"
    assert "400" in res.reason


@pytest.mark.asyncio
async def test_unreachable_open_webui_is_failed_not_raised():
    def handler(request):
        raise httpx.ConnectError("no route to host", request=request)

    with _configured():
        res = await sync.ensure_openwebui_user(
            "a@example.com", "a", "pw-123456789012", transport=_transport(handler)
        )
    assert res.status == "failed"
    assert "ConnectError" in res.reason


@pytest.mark.asyncio
async def test_add_server_error_is_failed():
    def handler(request):
        if request.url.path == "/api/v1/auths/signin":
            return _signin_ok(request)
        if request.url.path == "/api/v1/users/":
            return httpx.Response(200, json={"users": []})
        return httpx.Response(500, text="boom")

    with _configured():
        res = await sync.ensure_openwebui_user(
            "a@example.com", "a", "pw-123456789012", transport=_transport(handler)
        )
    assert res.status == "failed" and "500" in res.reason


def test_result_never_carries_the_password():
    res = sync.OpenWebUISyncResult("failed", "reason", "a@example.com")
    assert "pw-" not in json.dumps(res.as_dict())


# ---------------------------------------------------------------- (a) create_user_account hook


class _Auth:
    def __init__(self, success=True):
        self.success = success
        self.calls = []

    async def register_user(self, username, password, email=None, role="occupant", **_):
        self.calls.append((username, password, email, role))
        return {"success": self.success, "error": None if self.success else "taken"}


def _body(**kw):
    import orchestrator.main as m

    data = {
        "username": "newuser1",
        "password": "pw-123456789012",
        "role": "analyst",
        "email": "newuser1@example.com",
    }
    data.update(kw)
    return m.UserCreate(**data)


@pytest.mark.asyncio
async def test_admin_create_also_creates_the_open_webui_account():
    import orchestrator.main as m

    auth = _Auth(success=True)
    mirror = AsyncMock(
        return_value=sync.OpenWebUISyncResult("created", "ok", "newuser1@example.com")
    )
    with patch.object(m, "auth_manager", auth), patch.object(sync, "ensure_openwebui_user", mirror):
        resp = await m.create_user_account(body=_body(), user=None)
    assert resp.success is True
    mirror.assert_awaited_once_with("newuser1@example.com", "newuser1", "pw-123456789012")
    assert resp.data["openwebui_sync"] == {
        "status": "created",
        "reason": "ok",
        "email": "newuser1@example.com",
    }
    assert "warning" not in resp.data


@pytest.mark.asyncio
async def test_open_webui_failure_keeps_the_ontosage_account_and_says_so():
    import orchestrator.main as m

    auth = _Auth(success=True)
    failed = sync.OpenWebUISyncResult("failed", "HTTP 400", "newuser1@example.com")
    with patch.object(m, "auth_manager", auth), patch.object(
        sync, "ensure_openwebui_user", AsyncMock(return_value=failed)
    ):
        resp = await m.create_user_account(body=_body(), user=None)
    assert resp.success is True
    assert resp.data["openwebui_sync"]["status"] == "failed"
    assert "unaffected" in resp.data["warning"]


@pytest.mark.asyncio
async def test_no_sync_is_attempted_when_the_ontosage_create_fails():
    import orchestrator.main as m

    mirror = AsyncMock()
    with patch.object(m, "auth_manager", _Auth(success=False)), patch.object(
        sync, "ensure_openwebui_user", mirror
    ):
        resp = await m.create_user_account(body=_body(), user=None)
    assert resp.success is False
    mirror.assert_not_awaited()


@pytest.mark.asyncio
async def test_a_skipped_sync_is_reported_without_a_warning():
    import orchestrator.main as m

    skipped = sync.OpenWebUISyncResult("skipped", "OPENWEBUI_ADMIN_EMAIL is not set", "")
    with patch.object(m, "auth_manager", _Auth(success=True)), patch.object(
        sync, "ensure_openwebui_user", AsyncMock(return_value=skipped)
    ):
        resp = await m.create_user_account(body=_body(email=None), user=None)
    assert resp.success is True
    assert resp.data["openwebui_sync"]["status"] == "skipped"
    assert "warning" not in resp.data


# ---------------------------------------------------------------- (b) forwarded-identity hook


class _FakePG:
    """Minimal Postgres stand-in with create_user's duplicate semantics."""

    def __init__(self, rows=None, create_result=True, create_error=None):
        self.rows = dict(rows or {})
        self.create_result = create_result
        self.create_error = create_error
        self.created = []

    async def get_user(self, name):
        return self.rows.get(name)

    async def get_users_by_email(self, email):
        return []

    async def create_user(
        self, username, password_hash, salt, email=None, metadata=None, role="facility_manager"
    ):
        self.created.append(
            {
                "username": username,
                "hash": password_hash,
                "email": email,
                "metadata": metadata,
                "role": role,
            }
        )
        if self.create_error:
            raise self.create_error
        if self.create_result:
            self.rows[username] = {"username": username, "role": role, "metadata": metadata}
        return self.create_result


def _req(headers):
    return SimpleNamespace(headers=headers)


async def _resolve_with(pg, headers, trust=True):
    import orchestrator.main as m

    with patch.object(m.settings, "TRUST_FORWARDED_USER", trust), patch.object(
        m, "postgres_manager", pg
    ):
        return await m.resolve_forwarded_user(_req(headers))


@pytest.mark.asyncio
async def test_first_open_webui_sign_in_creates_a_readonly_account():
    pg = _FakePG()
    got = await _resolve_with(pg, {"X-OpenWebUI-User-Email": "Visitor@Example.com"})
    assert got == ("Visitor@Example.com", "readonly")
    assert len(pg.created) == 1
    row = pg.created[0]
    assert row["role"] == "readonly"
    assert row["email"] == "Visitor@Example.com"
    assert row["hash"] == "placeholder_hash"
    # Not the conversation-stub marker, which the resolver ignores, so a later admin
    # role change would never take effect on this row.
    assert row["metadata"] == {"source": "openwebui_signup"}


@pytest.mark.asyncio
async def test_second_request_finds_the_row_and_does_not_create_again():
    pg = _FakePG()
    await _resolve_with(pg, {"X-OpenWebUI-User-Email": "visitor@example.com"})
    got = await _resolve_with(pg, {"X-OpenWebUI-User-Email": "visitor@example.com"})
    assert got == ("visitor@example.com", "readonly")
    assert len(pg.created) == 1


@pytest.mark.asyncio
async def test_concurrent_first_requests_both_resolve_and_one_row_results():
    class _RacingPG(_FakePG):
        async def create_user(self, *a, **k):
            # Both callers passed the lookup; the second insert loses the unique race.
            await asyncio.sleep(0)
            if self.rows:
                self.created.append({"lost": True})
                return False
            return await super().create_user(*a, **k)

    pg = _RacingPG()
    headers = {"X-OpenWebUI-User-Email": "race@example.com"}
    results = await asyncio.gather(_resolve_with(pg, headers), _resolve_with(pg, headers))
    assert results == [("race@example.com", "readonly")] * 2
    assert sum(1 for c in pg.created if "lost" not in c) == 1


@pytest.mark.asyncio
async def test_duplicate_reports_the_role_of_the_row_that_won():
    pg = _FakePG(create_result=False)
    pg.rows["boss@example.com"] = {"username": "boss@example.com", "role": "admin", "metadata": {}}

    async def _get_user(name):
        # First lookup misses (before the race), the re-read after the lost insert finds it.
        return pg.rows.get(name) if pg.created else None

    pg.get_user = _get_user
    got = await _resolve_with(pg, {"X-OpenWebUI-User-Email": "boss@example.com"})
    assert got == ("boss@example.com", "admin")


@pytest.mark.asyncio
async def test_duplicate_that_is_only_a_placeholder_stays_readonly():
    pg = _FakePG(
        create_result=False,
        rows={
            "stub@example.com": {
                "username": "stub@example.com",
                "role": "readonly",
                "metadata": {"source": "open_webui"},
            }
        },
    )
    got = await _resolve_with(pg, {"X-OpenWebUI-User-Email": "stub@example.com"})
    assert got == ("stub@example.com", "readonly")


@pytest.mark.asyncio
async def test_create_exception_falls_back_to_readonly_without_raising():
    pg = _FakePG(create_error=RuntimeError("pool exhausted"))
    got = await _resolve_with(pg, {"X-OpenWebUI-User-Email": "x@example.com"})
    assert got == ("x@example.com", "readonly")


@pytest.mark.asyncio
async def test_shared_fallback_identity_never_creates_an_account():
    pg = _FakePG()
    got = await _resolve_with(pg, {})
    assert got == ("openwebui_user", "readonly")
    assert pg.created == []


@pytest.mark.asyncio
async def test_untrusted_header_never_creates_an_account():
    pg = _FakePG()
    got = await _resolve_with(pg, {"X-OpenWebUI-User-Email": "a@example.com"}, trust=False)
    assert got == ("openwebui_user", "readonly")
    assert pg.created == []


@pytest.mark.asyncio
async def test_a_non_email_identity_is_not_turned_into_an_account():
    pg = _FakePG()
    got = await _resolve_with(pg, {"X-OpenWebUI-User-Email": "alice"})
    assert got == ("alice", "readonly")
    assert pg.created == []
