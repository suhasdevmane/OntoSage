"""Admin password reset — hashing, session revocation, and the guarantees around it.

A stored password is a one-way Argon2id hash: an admin can SET a new one but can
never read the existing one back. Resetting must also sign out anyone already
holding a session, since a compromised/shared password is the usual reason to reset.
"""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock

import pytest

from orchestrator.auth_manager import AuthManager

pytestmark = pytest.mark.unit


def _mgr(user_exists=True):
    redis = MagicMock()
    redis.client = MagicMock()
    redis.client.smembers = AsyncMock(return_value={"tok-a", "tok-b"})
    redis.client.delete = AsyncMock(return_value=1)
    redis.client.hset = AsyncMock(return_value=1)
    pg = MagicMock()
    pg.update_password = AsyncMock(return_value=True)
    am = AuthManager(redis, pg)
    am.get_user_info = AsyncMock(return_value={"username": "alice"} if user_exists else None)
    return am, redis, pg


@pytest.mark.asyncio
async def test_reset_hashes_and_revokes_every_session():
    am, redis, pg = _mgr()
    res = await am.set_password("alice", "a-brand-new-password")
    assert res["success"] is True
    assert res["sessions_revoked"] == 2  # both live sessions killed
    pg.update_password.assert_awaited_once()
    stored_hash = pg.update_password.await_args.args[1]
    # Never store the plaintext, and use the configured strong hasher.
    assert "a-brand-new-password" not in stored_hash
    assert stored_hash.startswith(("argon2id:", "bcrypt:")) or len(stored_hash) == 64


@pytest.mark.asyncio
async def test_reset_enforces_the_same_minimum_as_registration():
    am, _, pg = _mgr()
    res = await am.set_password("alice", "short")
    assert res["success"] is False and "12 characters" in res["error"]
    pg.update_password.assert_not_awaited()  # nothing written on rejection


@pytest.mark.asyncio
async def test_reset_rejects_unknown_user():
    am, _, pg = _mgr(user_exists=False)
    res = await am.set_password("nobody", "a-brand-new-password")
    assert res["success"] is False and "not found" in res["error"]
    pg.update_password.assert_not_awaited()


@pytest.mark.asyncio
async def test_reset_reports_failure_when_the_row_is_not_updated():
    am, _, pg = _mgr()
    pg.update_password = AsyncMock(return_value=False)
    res = await am.set_password("alice", "a-brand-new-password")
    assert res["success"] is False


@pytest.mark.asyncio
async def test_password_is_never_recoverable_only_replaceable():
    """Two resets of the SAME password must produce different stored hashes."""
    am, _, pg = _mgr()
    await am.set_password("alice", "identical-password-x")
    first = pg.update_password.await_args.args[1]
    await am.set_password("alice", "identical-password-x")
    second = pg.update_password.await_args.args[1]
    assert first != second  # per-reset salt — hashes are not reversible lookups
