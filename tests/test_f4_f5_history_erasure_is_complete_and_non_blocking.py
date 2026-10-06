# -*- coding: utf-8 -*-
"""F4 + F5 (QA-trial plan, 2026-10-04).

F4: `DELETE /history/{username}` deleted Redis conversations and the Postgres
`conversations` table, but never `turn_memory` -- a user told "History cleared
successfully" could still have every per-turn row sitting in `turn_memory`, which is
worse than no erasure at all because the user is told it worked.
`turn_memory.TurnMemoryService.delete_user_turns`/`.delete_conversation` already existed
with no caller anywhere in the codebase; this wires both in.

F5: the same endpoint's Redis cleanup used `.keys(pattern)`, which blocks the whole Redis
event loop for every other connection while it scans -- on an endpoint any authenticated
user can call on demand. `auth_manager.py`'s account-deletion path already moved to
`scan_iter` for exactly this reason; this endpoint gets the same treatment.
"""
import inspect

import pytest

from orchestrator import main

pytestmark = pytest.mark.unit


def _src(fn) -> str:
    return inspect.getsource(fn)


class TestF5NoBlockingKeysScan:
    def test_clear_user_history_uses_scan_iter_not_keys(self):
        src = _src(main.clear_user_history)
        assert ".keys(" not in src
        assert src.count("scan_iter(") == 2

    def test_both_scan_iter_calls_cover_the_right_patterns(self):
        src = _src(main.clear_user_history)
        assert "match=pattern" in src
        assert "match=msg_pattern" in src


class TestF4TurnMemoryIsAlsoErased:
    def test_clear_user_history_calls_delete_user_turns(self):
        src = _src(main.clear_user_history)
        assert "_turn_memory_service().delete_user_turns(username)" in src

    def test_the_deleted_turn_count_reaches_the_response(self):
        src = _src(main.clear_user_history)
        assert "turns_deleted" in src
        assert '"deleted_turn_records": turns_deleted' in src

    def test_delete_conversation_endpoint_calls_turn_memory_delete_conversation(self):
        src = _src(main.delete_conversation)
        assert "_turn_memory_service().delete_conversation(conversation_id)" in src

    def test_the_turn_memory_call_runs_for_both_endpoints_not_just_one(self):
        """Regression guard: a fix landing in only one of the two erasure surfaces is
        half the fix, same shape as the original defect."""
        assert "_turn_memory_service()" in _src(main.clear_user_history)
        assert "_turn_memory_service()" in _src(main.delete_conversation)


# ---- Behaviour: both stores are erased, and the reply names what was removed --------------


class _FakeRedisClient:
    """The Redis commands the erasure path issues, with a real SCAN-style iterator."""

    def __init__(self, keys):
        self.store = set(keys)
        self.deleted = []
        self.keys_called = False

    def keys(self, *args, **kwargs):  # pragma: no cover - must never be called
        self.keys_called = True
        raise AssertionError("KEYS must not be used on an endpoint any user can call")

    async def scan_iter(self, match=None, count=None):
        import fnmatch

        for k in sorted(self.store):
            if match is None or fnmatch.fnmatchcase(k, match):
                yield k

    async def delete(self, key):
        self.deleted.append(key)
        self.store.discard(key)
        return 1


class _FakeRedisManager:
    def __init__(self, client):
        self.client = client


class _FakePostgres:
    def __init__(self, pool=object(), conversations_deleted=2):
        self.pool = pool
        self.conversations_deleted = conversations_deleted
        self.cleared_for = []

    async def clear_user_history(self, username):
        self.cleared_for.append(username)
        return self.conversations_deleted


class _FakeTurnMemory:
    def __init__(self, turns_deleted=5):
        self.turns_deleted = turns_deleted
        self.user_calls = []
        self.conversation_calls = []

    async def delete_user_turns(self, user_id):
        self.user_calls.append(user_id)
        return self.turns_deleted

    async def delete_conversation(self, conversation_id):
        self.conversation_calls.append(conversation_id)
        return 3


class TestClearHistoryErasesBothStores:
    @pytest.mark.asyncio
    async def test_clear_removes_redis_keys_postgres_conversations_and_turn_rows(self, monkeypatch):
        client = _FakeRedisClient(
            [
                "conversation:owui_a:alice",
                "conversation:owui_b:alice",
                "messages:owui_a:alice",
                "conversation:owui_c:bob",
            ]
        )
        pg = _FakePostgres(conversations_deleted=2)
        tm = _FakeTurnMemory(turns_deleted=7)
        monkeypatch.setattr(main, "redis_manager", _FakeRedisManager(client))
        monkeypatch.setattr(main, "postgres_manager", pg)
        monkeypatch.setattr(main, "_turn_memory_service", lambda: tm)

        resp = await main.clear_user_history("alice", "alice")

        assert resp.success is True
        assert client.deleted.count("conversation:owui_a:alice") == 1
        assert "conversation:owui_c:bob" in client.store  # another user's keys are untouched
        assert pg.cleared_for == ["alice"]
        assert tm.user_calls == ["alice"]

    @pytest.mark.asyncio
    async def test_the_reply_reports_what_was_deleted_in_each_store(self, monkeypatch):
        client = _FakeRedisClient(["conversation:owui_a:alice", "messages:owui_a:alice"])
        monkeypatch.setattr(main, "redis_manager", _FakeRedisManager(client))
        monkeypatch.setattr(main, "postgres_manager", _FakePostgres(conversations_deleted=4))
        monkeypatch.setattr(main, "_turn_memory_service", lambda: _FakeTurnMemory(turns_deleted=9))

        resp = await main.clear_user_history("alice", "alice")

        assert resp.data["deleted_conversations"] == 1  # Redis conversation keys
        assert resp.data["deleted_postgres_conversations"] == 4
        assert resp.data["deleted_turn_records"] == 9

    @pytest.mark.asyncio
    async def test_another_users_history_cannot_be_cleared(self, monkeypatch):
        tm = _FakeTurnMemory()
        monkeypatch.setattr(main, "_turn_memory_service", lambda: tm)
        resp = await main.clear_user_history("bob", "alice")
        assert resp.success is False
        assert tm.user_calls == []

    @pytest.mark.asyncio
    async def test_delete_conversation_removes_its_turn_rows(self, monkeypatch):
        import types

        client = _FakeRedisClient([])
        tm = _FakeTurnMemory()
        monkeypatch.setattr(main, "redis_manager", _FakeRedisManager(client))
        monkeypatch.setattr(main, "_turn_memory_service", lambda: tm)
        user = types.SimpleNamespace(username="alice", has_permission=lambda perm: False)

        resp = await main.delete_conversation("owui_a:alice", user)

        assert resp.success is True
        assert tm.conversation_calls == ["owui_a:alice"]
        assert resp.data["deleted_turn_records"] == 3
        assert "conversation:owui_a:alice" in client.deleted
        assert "messages:owui_a:alice" in client.deleted
