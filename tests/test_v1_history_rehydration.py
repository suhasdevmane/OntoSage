"""Unit tests for /v1 server-side conversation-history rehydration.

OpenWebUI echoes the full message array each turn (co-reference works from the
client array). Minimal clients — a custom chat UI, the /stream WebSocket, or a
plain API caller — send only the current message; without rehydration their
follow-ups ("is that ok?", "humidity there?") lose all context. The helper
recovers prior turns from the persisted conversation state in that case, and is
skipped (returns the client-supplied history unchanged) otherwise.

Offline: monkeypatches main.redis_manager; never touches Redis.
"""

import pytest

import orchestrator.main as main

pytestmark = pytest.mark.unit


class _Msg:
    def __init__(self, content):
        self.content = content


class _State:
    def __init__(self, messages):
        self.messages = messages


class _FakeRedis:
    def __init__(self, result=None, raises=False):
        self._result = result
        self._raises = raises
        self.calls = 0

    async def load_state(self, conversation_id):
        self.calls += 1
        if self._raises:
            raise RuntimeError("redis down")
        return self._result


def _msgs(n):
    return [_Msg(f"m{i}") for i in range(n)]


@pytest.mark.asyncio
async def test_skips_when_client_sent_history(monkeypatch):
    fake = _FakeRedis(result=_State(_msgs(4)))
    monkeypatch.setattr(main, "redis_manager", fake)
    existing = _msgs(2)
    out = await main._rehydrate_prior_messages("c1", existing, 10)
    assert out is existing  # returned unchanged
    assert fake.calls == 0  # server never consulted


@pytest.mark.asyncio
async def test_loads_server_history_when_client_empty(monkeypatch):
    server = _msgs(6)
    monkeypatch.setattr(main, "redis_manager", _FakeRedis(result=_State(server)))
    out = await main._rehydrate_prior_messages("c1", [], 10)
    assert [m.content for m in out] == [m.content for m in server]


@pytest.mark.asyncio
async def test_trims_to_max_history_keeping_most_recent(monkeypatch):
    monkeypatch.setattr(main, "redis_manager", _FakeRedis(result=_State(_msgs(20))))
    out = await main._rehydrate_prior_messages("c1", [], 5)
    assert len(out) == 5
    assert out[-1].content == "m19"  # most recent retained
    assert out[0].content == "m15"


@pytest.mark.asyncio
async def test_empty_when_no_prior_state(monkeypatch):
    monkeypatch.setattr(main, "redis_manager", _FakeRedis(result=None))
    out = await main._rehydrate_prior_messages("c1", [], 10)
    assert out == []


@pytest.mark.asyncio
async def test_graceful_on_redis_error(monkeypatch):
    monkeypatch.setattr(main, "redis_manager", _FakeRedis(raises=True))
    out = await main._rehydrate_prior_messages("c1", [], 10)
    assert out == []  # degrades to no history, never raises
