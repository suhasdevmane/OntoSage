"""Sign-in must accept whichever identifier a person actually has.

The chat UI identifies people by email; OntoSage accounts are keyed by username. Without
an email fallback the same credentials work in one portal and are rejected by the other —
which is indistinguishable from a wrong password to the person typing it.
"""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock

import pytest

from orchestrator.auth_manager import AuthManager

pytestmark = pytest.mark.unit


def _mgr(by_username=None, by_email=None):
    redis = MagicMock()
    # AsyncMock so EVERY redis call used along the login path (lockout counters,
    # session write, per-user session index) is awaitable without enumerating them.
    redis.client = AsyncMock()
    redis.client.get = AsyncMock(return_value=None)

    pool_cm = MagicMock()
    pool_cm.__aenter__ = AsyncMock(return_value=MagicMock(fetchval=AsyncMock(return_value=1)))
    pool_cm.__aexit__ = AsyncMock(return_value=False)
    pg = MagicMock()
    pg.pool = MagicMock(acquire=MagicMock(return_value=pool_cm))
    pg.get_user = AsyncMock(return_value=by_username)
    pg.get_user_by_email = AsyncMock(return_value=by_email)
    pg.update_last_login = AsyncMock(return_value=None)
    return AuthManager(redis, pg), pg


def _account(am, username="admin01", role="admin", password="OntoAdmin01!abc"):
    hashed, salt = am._hash_password(password)
    return {
        "username": username,
        "password_hash": hashed,
        "salt": salt,
        "role": role,
        "email": f"{username}@example.com",
    }


@pytest.mark.asyncio
async def test_login_by_username():
    am, _ = _mgr()
    acct = _account(am)
    am.postgres.get_user = AsyncMock(return_value=acct)
    res = await am.login_user("admin01", "OntoAdmin01!abc")
    assert res["success"] is True and res["role"] == "admin"


@pytest.mark.asyncio
async def test_login_by_email_resolves_to_the_same_account():
    am, pg = _mgr()
    acct = _account(am)
    pg.get_user = AsyncMock(return_value=None)  # not found by username…
    pg.get_user_by_email = AsyncMock(return_value=acct)  # …found by email
    res = await am.login_user("admin01@example.com", "OntoAdmin01!abc")
    assert res["success"] is True
    assert res["username"] == "admin01"  # resolved back to the account name
    pg.get_user_by_email.assert_awaited_once()


@pytest.mark.asyncio
async def test_wrong_password_still_rejected_when_found_by_email():
    am, pg = _mgr()
    acct = _account(am)
    pg.get_user = AsyncMock(return_value=None)
    pg.get_user_by_email = AsyncMock(return_value=acct)
    res = await am.login_user("admin01@example.com", "not-the-password")
    assert res["success"] is False


@pytest.mark.asyncio
async def test_plain_username_never_triggers_an_email_lookup():
    am, pg = _mgr()
    pg.get_user = AsyncMock(return_value=None)
    res = await am.login_user("nosuchuser", "whatever12345")
    assert res["success"] is False
    pg.get_user_by_email.assert_not_awaited()  # no '@' → not an email
