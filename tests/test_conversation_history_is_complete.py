# -*- coding: utf-8 -*-
"""Conversation history is complete: the Redis copy is a bounded cache, Postgres is the record.

Owner decision (2026-10-06, ChatGPT-style): every conversation keeps its full history until the
user deletes it. Nothing here windows STORED history. What is bounded is the Redis working copy
(CONVERSATION_MAX_MESSAGES) and the per-turn request cap (MAX_CONVERSATION_HISTORY); both are
refilled from the Postgres `messages` transcript whenever they are shorter than the record.

Cross-session: this does NOT inject other conversations into a new one. Per-user preferences
are the only cross-session memory, and they are a separate store.

Offline: every store is a fake. Nothing reaches Redis, Postgres or a model.
"""

from datetime import datetime, timedelta
from pathlib import Path

import pytest

import orchestrator.main as main
from orchestrator.redis_manager import RedisManager
from shared.config import Settings
from shared.models import ConversationState, Message

pytestmark = pytest.mark.unit

REPO = Path(__file__).resolve().parents[1]


def _transcript(turns: int):
    """A realistic transcript: `turns` user/assistant pairs, oldest first."""
    t0 = datetime(2026, 10, 1, 9, 0, 0)
    out = []
    for i in range(turns):
        out.append(Message(role="user", content=f"q{i}", timestamp=t0 + timedelta(minutes=2 * i)))
        out.append(
            Message(
                role="assistant",
                content=f"a{i}",
                timestamp=t0 + timedelta(minutes=2 * i + 1),
            )
        )
    return out


class _FakePG:
    """The `messages` table for one conversation, with the two readers the helper uses."""

    def __init__(self, rows, available=True):
        self.pool = object() if available else None
        self._rows = rows
        self.tail_calls = []

    async def count_conversation_messages(self, conversation_id):
        return len(self._rows)

    async def load_conversation_tail(self, conversation_id, limit):
        self.tail_calls.append(limit)
        return [
            {"role": m.role, "content": m.content, "timestamp": m.timestamp}
            for m in self._rows[-limit:]
        ]


class _FakeRedisState:
    def __init__(self, messages):
        self._messages = messages

    async def load_state(self, conversation_id):
        return ConversationState(
            conversation_id=conversation_id,
            user_message="current",
            messages=list(self._messages),
        )


def _contents(msgs):
    return [m.content for m in msgs]


# ---- A 30-turn conversation rehydrates to its full length ---------------------------------


@pytest.mark.asyncio
async def test_thirty_turn_conversation_rehydrates_to_full_length(monkeypatch):
    """Redis holds only the newest 20 messages (10 turns); the store holds all 60."""
    full = _transcript(30)
    monkeypatch.setattr(main, "redis_manager", _FakeRedisState(full[-20:]))
    monkeypatch.setattr(main, "postgres_manager", _FakePG(full))

    out = await main._rehydrate_prior_messages("c1", [], 400)

    assert len(out) == 60
    assert _contents(out) == _contents(full)  # full, in order, nothing dropped


@pytest.mark.asyncio
async def test_short_client_history_is_refilled_from_the_store(monkeypatch):
    """A client that echoes only its last 20 messages does not truncate a 60-message record."""
    full = _transcript(30)
    monkeypatch.setattr(main, "postgres_manager", _FakePG(full))

    out = await main._rehydrate_prior_messages("c1", full[-20:], 400)

    assert len(out) == 60
    assert _contents(out) == _contents(full)


@pytest.mark.asyncio
async def test_fuller_client_history_is_kept_as_is(monkeypatch):
    """When the client sent everything the store holds, the client's list is returned unchanged."""
    full = _transcript(10)
    monkeypatch.setattr(main, "postgres_manager", _FakePG(full))

    out = await main._rehydrate_prior_messages("c1", full, 400)

    assert out is full


@pytest.mark.asyncio
async def test_store_unavailable_degrades_to_the_in_memory_copy(monkeypatch):
    """No Postgres pool: behaviour is exactly what it was before the store existed."""
    part = _transcript(10)
    monkeypatch.setattr(main, "postgres_manager", _FakePG(_transcript(30), available=False))

    out = await main._fill_history_gap("c1", part)

    assert out is part


@pytest.mark.asyncio
async def test_refill_reads_no_more_than_the_cap(monkeypatch):
    """The refill never pulls more rows than CONVERSATION_MAX_MESSAGES allows."""
    store = _FakePG(_transcript(300))  # 600 messages stored
    monkeypatch.setattr(main, "postgres_manager", store)

    out = await main._fill_history_gap("c1", _transcript(2), cap=400)

    assert len(out) == 400
    assert store.tail_calls == [400]
    assert _contents(out)[-1] == "a299"  # the newest message is always the last one kept


# ---- Redis eviction does not drop a conversation: the store is the fallback ---------------


class _FakeRedisClient:
    """Just the commands save_state issues, recording what the Redis copy ends up holding."""

    def __init__(self):
        self.blobs = {}
        self.trims = []

    async def set(self, key, value):
        self.blobs[key] = value

    async def ltrim(self, key, start, stop):
        self.trims.append((key, start, stop))
        return True


@pytest.mark.asyncio
async def test_redis_eviction_falls_back_to_the_store(monkeypatch):
    """Redis trims to its cap; the stored transcript still refills the full conversation."""
    full = _transcript(30)  # 60 messages
    rm = RedisManager()
    rm.client = _FakeRedisClient()
    rm.conversation_ttl = 0
    rm.max_messages = 20

    state = ConversationState(conversation_id="c1", user_message="now", messages=list(full))
    assert await rm.save_state(state) is True

    import json

    evicted = json.loads(rm.client.blobs["conversation:c1"])["messages"]
    assert len(evicted) == 20  # the working copy really was cut to its cap
    assert [m["content"] for m in evicted] == _contents(full[-20:])

    # ...and the conversation is not lost: the store restores the 60 the cap evicted.
    monkeypatch.setattr(main, "postgres_manager", _FakePG(full))
    restored = await main._fill_history_gap("c1", [Message(**m) for m in evicted])

    assert len(restored) == 60
    assert _contents(restored) == _contents(full)


# ---- Configuration: no short window by default, no expiry -------------------------------


def _field_default(name):
    fields = getattr(Settings, "model_fields", None) or Settings.__fields__
    return fields[name].default


def test_conversation_defaults_keep_a_long_chat_whole():
    assert _field_default("CONVERSATION_MAX_MESSAGES") == 400  # 200 turns
    assert _field_default("MAX_CONVERSATION_HISTORY") == 400
    assert _field_default("CONVERSATION_TTL") == 0  # no expiry while the conversation exists


def test_env_example_documents_no_expiry():
    text = (REPO / ".env.example").read_text(encoding="utf-8")
    assert "\nCONVERSATION_TTL=0\n" in text
    assert "\nCONVERSATION_MAX_MESSAGES=400\n" in text


# ---- Long conversations do not send the whole transcript to the summariser ---------------


def test_summary_is_built_from_a_bounded_window():
    """dialogue_agent folds only the last _SUMMARY_SOURCE_WINDOW messages into the summary."""
    import orchestrator.agents.dialogue_agent as da

    assert da._SUMMARY_SOURCE_WINDOW == 20
    src = Path(da.__file__).read_text(encoding="utf-8")
    assert "state.messages[-_SUMMARY_SOURCE_WINDOW:]" in src
