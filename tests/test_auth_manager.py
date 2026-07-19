"""
test_auth_manager.py — AuthManager security-behavior regression tests.

Covers three P0 fixes from tasks/PRODUCTION_READINESS_AUDIT.md:
  #1  Self-registration default role is 'occupant' (was 'readonly', which
      could not call /chat — see auth_manager.register_user).
  #3  Per-account login lockout after LOGIN_MAX_ATTEMPTS failed attempts,
      independent of the global per-IP rate limiter.
  #4  delete_user cleans up Redis session/conversation state via the tracked
      per-user conversation index + a targeted SCAN, not a blocking
      `KEYS conversation:*` + per-key GET/parse.
"""

import fnmatch

import pytest

from orchestrator.auth_manager import AuthManager

pytestmark = pytest.mark.unit


class FakeRedisClient:
    """Minimal async Redis stand-in covering the ops AuthManager needs."""

    def __init__(self):
        self._store: dict = {}
        self._hashes: dict = {}
        self._sets: dict = {}
        self._ttls: dict = {}

    async def get(self, key):
        return self._store.get(key)

    async def set(self, key, value):
        self._store[key] = value

    async def setex(self, key, ttl, value):
        self._store[key] = value
        self._ttls[key] = ttl

    async def delete(self, *keys):
        for key in keys:
            self._store.pop(key, None)
            self._hashes.pop(key, None)
            self._sets.pop(key, None)
            self._ttls.pop(key, None)

    async def exists(self, key):
        return key in self._store or key in self._hashes or key in self._sets

    async def hset(self, name, key=None, value=None, mapping=None):
        h = self._hashes.setdefault(name, {})
        if mapping:
            h.update(mapping)
        if key is not None:
            h[key] = value

    async def hgetall(self, name):
        return dict(self._hashes.get(name, {}))

    async def sadd(self, name, *members):
        self._sets.setdefault(name, set()).update(members)

    async def srem(self, name, *members):
        s = self._sets.get(name)
        if s:
            for m in members:
                s.discard(m)

    async def smembers(self, name):
        return set(self._sets.get(name, set()))

    async def incr(self, key):
        current = int(self._store.get(key) or 0) + 1
        self._store[key] = str(current)
        return current

    async def expire(self, key, seconds):
        self._ttls[key] = seconds
        return True

    async def ttl(self, key):
        return self._ttls.get(key, -1)

    async def scan_iter(self, match=None, count=None):
        pattern = match or "*"
        for key in list(self._store.keys()) + list(self._hashes.keys()) + list(self._sets.keys()):
            if fnmatch.fnmatch(key, pattern):
                yield key


class FakeRedisManager:
    def __init__(self):
        self.client = FakeRedisClient()


@pytest.fixture
def auth():
    return AuthManager(redis_manager=FakeRedisManager(), postgres_manager=None)


# ── #1: default registration role ───────────────────────────────────────────


class TestDefaultRegistrationRole:
    @pytest.mark.asyncio
    async def test_register_user_defaults_to_occupant(self, auth):
        result = await auth.register_user("alice", "correct-horse-battery")
        assert result["success"] is True
        stored = await auth.redis.client.hgetall("user:alice")
        assert stored["role"] == "occupant"

    @pytest.mark.asyncio
    async def test_occupant_can_reach_chat_permission(self):
        """occupant must carry sensor:read so POST /chat (which requires it)
        doesn't 403 a user immediately after self-registration."""
        from orchestrator.middleware.rbac import ROLE_PERMISSIONS

        assert "sensor:read" in ROLE_PERMISSIONS["occupant"]


# ── #3: per-account login lockout ───────────────────────────────────────────


class TestLoginLockout:
    async def _seed_user(self, auth, username="bob", password="s3cret-pw-long"):
        await auth.register_user(username, password)

    @pytest.mark.asyncio
    async def test_lockout_after_max_attempts(self, auth):
        await self._seed_user(auth)
        auth.login_max_attempts = 3
        for _ in range(3):
            result = await auth.login_user("bob", "wrong-password")
            assert result["success"] is False
            assert "Invalid username or password" in result["error"]

        # 4th attempt (even with the correct password) must be locked out.
        locked = await auth.login_user("bob", "s3cret-pw-long")
        assert locked["success"] is False
        assert "Too many failed login attempts" in locked["error"]

    @pytest.mark.asyncio
    async def test_successful_login_resets_counter(self, auth):
        await self._seed_user(auth)
        auth.login_max_attempts = 3
        await auth.login_user("bob", "wrong-password")
        await auth.login_user("bob", "wrong-password")

        ok = await auth.login_user("bob", "s3cret-pw-long")
        assert ok["success"] is True

        # Counter cleared — two more failures shouldn't trigger lockout yet.
        r1 = await auth.login_user("bob", "wrong-password")
        r2 = await auth.login_user("bob", "wrong-password")
        assert "Too many failed login attempts" not in r1["error"]
        assert "Too many failed login attempts" not in r2["error"]

    @pytest.mark.asyncio
    async def test_lockout_is_per_username(self, auth):
        await self._seed_user(auth, "carol", "carol-pw-12345")
        await self._seed_user(auth, "dave", "dave-pw-12345")
        auth.login_max_attempts = 2

        await auth.login_user("carol", "wrong")
        await auth.login_user("carol", "wrong")
        locked = await auth.login_user("carol", "carol-pw-12345")
        assert "Too many failed login attempts" in locked["error"]

        # dave's account is untouched by carol's lockout.
        ok = await auth.login_user("dave", "dave-pw-12345")
        assert ok["success"] is True


# ── #4: delete_user Redis cleanup without KEYS scan ─────────────────────────


class TestDeleteUserRedisCleanup:
    @pytest.mark.asyncio
    async def test_delete_user_removes_sessions_and_tracked_conversations(self, auth):
        await auth.register_user("erin", "erin-pw-123456")
        login = await auth.login_user("erin", "erin-pw-123456")
        token = login["session_token"]
        assert await auth.redis.client.exists(f"session:{token}")

        # A conversation tracked via the per-user index (the normal /chat path).
        await auth.redis.client.set("conversation:conv1:erin", "{}")
        await auth.redis.client.set("conversation:conv1:erin:meta", "{}")
        await auth.redis.client.set("messages:conv1:erin", "[]")
        await auth.redis.client.sadd("user:erin:conversations", "conv1:erin")

        # A conversation NOT in the tracked index but matching the
        # `:{username}` suffix convention — must still be caught by the SCAN.
        await auth.redis.client.set("conversation:conv2:erin", "{}")

        result = await auth.delete_user("erin")
        assert result["success"] is True

        assert not await auth.redis.client.exists(f"session:{token}")
        assert not await auth.redis.client.exists("conversation:conv1:erin")
        assert not await auth.redis.client.exists("conversation:conv1:erin:meta")
        assert not await auth.redis.client.exists("messages:conv1:erin")
        assert not await auth.redis.client.exists("conversation:conv2:erin")
        assert not await auth.redis.client.exists("user:erin:conversations")
        assert not await auth.redis.client.exists("user:erin")

    @pytest.mark.asyncio
    async def test_delete_user_does_not_touch_other_users_conversations(self, auth):
        await auth.register_user("frank", "frank-pw-123456")
        await auth.register_user("grace", "grace-pw-123456")
        await auth.redis.client.set("conversation:convX:grace", "{}")
        await auth.redis.client.sadd("user:grace:conversations", "convX:grace")

        await auth.delete_user("frank")

        assert await auth.redis.client.exists("conversation:convX:grace")
