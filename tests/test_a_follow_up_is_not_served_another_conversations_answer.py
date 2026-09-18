# -*- coding: utf-8 -*-
"""A follow-up question is only served a cached answer made after the same questions (BUG-668).

Found by reading the code on 2026-09-17. `_serve_from_cache` runs before the co-reference
rewrite and keyed on the raw text of the latest message, plus building, user and role. So for
one user:

    chat A: "What is the CO2 in room 5.01?"        -> "How has that changed over the last week?"
    chat B: "What is the temperature on floor 3?"  -> "How has that changed over the last week?"

and chat B's follow-up was answered, instantly, from chat A's entry: the wrong room and the
wrong quantity. A follow-up's meaning lives in the turns before it, which the key never held.

The fix folds the PRECEDING USER QUESTIONS into the key on both get and put, for the exact and
the fuzzy lookup alike. An opening question keeps its context-free key, so a standalone
question still reuses the cache across conversations. There is deliberately no anaphora word
list: a standalone question asked second merely loses cross-conversation reuse, which costs
time and never correctness.

The same reading found a second disagreement the brief did not name: `put` stored under
`messages[-2].content`, which the dialogue node has by then REPLACED with the co-reference
rewrite (or the typography-normalised or translated text), while `get` looked up the raw
words. The key is now computed once, at lookup, and the store reuses it.
"""

from __future__ import annotations

import asyncio
import fnmatch
from typing import Dict

import pytest

from orchestrator.services import response_cache as rc
from orchestrator.services.response_cache import ResponseCacheService
from orchestrator.workflow import _orchestrator as mod
from shared.models import ConversationState, Message

pytestmark = pytest.mark.unit

OPENER_A = "What is the CO2 in room 5.01?"
OPENER_B = "What is the temperature on floor 3?"
FOLLOW_UP = "How has that changed over the last week?"


class _FakeRedis:
    """The subset of redis.asyncio the cache uses, in memory."""

    def __init__(self) -> None:
        self.kv: Dict[str, str] = {}
        self.hashes: Dict[str, Dict[str, str]] = {}

    async def get(self, key):
        return self.kv.get(key)

    async def setex(self, key, ttl, value):
        self.kv[key] = value

    async def hset(self, key, field, value):
        self.hashes.setdefault(key, {})[field] = value

    async def hgetall(self, key):
        return dict(self.hashes.get(key, {}))

    async def hincrby(self, key, field, n):
        h = self.hashes.setdefault(key, {})
        h[field] = str(int(h.get(field, 0)) + n)

    async def keys(self, pattern):
        return [k for k in list(self.kv) + list(self.hashes) if fnmatch.fnmatchcase(k, pattern)]

    async def delete(self, key):
        self.kv.pop(key, None)
        self.hashes.pop(key, None)


def _cache(fuzzy: bool = False) -> ResponseCacheService:
    c = ResponseCacheService(_FakeRedis(), ttl=3600, fuzzy=fuzzy, min_similarity=0.85)
    c._enabled = True  # independent of RESPONSE_CACHE_ENABLED in the test environment
    return c


def _run(coro):
    return asyncio.run(coro)


async def _put(cache, question, context=None, role="facility_manager", user="fm1", answer="A"):
    await cache.put(
        question=question,
        response=answer,
        intent="sensor_data",
        building_id="b",
        user_id=user,
        role=role,
        context=context,
    )


async def _get(cache, question, context=None, role="facility_manager", user="fm1"):
    return await cache.get(
        question=question, building_id="b", user_id=user, role=role, context=context
    )


# ── the key ──────────────────────────────────────────────────────────────────


class TestTheKey:
    def test_the_same_follow_up_after_different_openers_has_different_keys(self):
        assert rc.cache_hash(FOLLOW_UP, [OPENER_A]) != rc.cache_hash(FOLLOW_UP, [OPENER_B])

    def test_an_opening_question_keeps_its_context_free_key(self):
        """Entries made before this change, and every standalone opener, stay addressable."""
        assert rc.cache_hash(OPENER_A, None) == rc.query_hash(OPENER_A)
        assert rc.cache_hash(OPENER_A, []) == rc.query_hash(OPENER_A)
        assert rc.cache_hash(OPENER_A, ["", "   "]) == rc.query_hash(OPENER_A)

    def test_a_question_asked_second_is_not_keyed_as_an_opener(self):
        assert rc.cache_hash(OPENER_B, [OPENER_A]) != rc.query_hash(OPENER_B)

    def test_the_context_is_normalised_like_the_question(self):
        """Case and punctuation in an earlier question do not split the key."""
        assert rc.cache_hash(FOLLOW_UP, ["what is the co2 in room 5.01"]) == rc.cache_hash(
            FOLLOW_UP, [OPENER_A]
        )

    def test_only_the_last_context_turns_are_bound(self):
        tail = ["q one", "q two", "q three"]
        assert rc.CONTEXT_TURNS == 3
        assert rc.cache_hash(FOLLOW_UP, ["older x"] + tail) == rc.cache_hash(
            FOLLOW_UP, ["older y"] + tail
        )
        assert rc.cache_hash(FOLLOW_UP, tail) != rc.cache_hash(
            FOLLOW_UP, ["q one", "q two", "q four"]
        )

    def test_turn_order_matters(self):
        assert rc.cache_hash(FOLLOW_UP, [OPENER_A, OPENER_B]) != rc.cache_hash(
            FOLLOW_UP, [OPENER_B, OPENER_A]
        )


# ── the service ──────────────────────────────────────────────────────────────


class TestTheService:
    def test_chat_b_is_not_served_chat_as_follow_up(self):
        cache = _cache()

        async def go():
            await _put(cache, FOLLOW_UP, [OPENER_A], answer="CO2 in 5.01 rose")
            return await _get(cache, FOLLOW_UP, [OPENER_B])

        assert _run(go()) is None

    def test_a_follow_up_is_not_served_an_openers_entry_for_the_same_words(self):
        """Asked as an opener, the words meant something else."""
        cache = _cache()

        async def go():
            await _put(cache, FOLLOW_UP, None, answer="no referent")
            return await _get(cache, FOLLOW_UP, [OPENER_A])

        assert _run(go()) is None

    def test_the_same_opener_and_follow_up_in_two_conversations_may_hit(self):
        cache = _cache()

        async def go():
            await _put(cache, FOLLOW_UP, [OPENER_A], answer="CO2 in 5.01 rose")
            return await _get(cache, FOLLOW_UP, [OPENER_A])

        hit = _run(go())
        assert hit and hit["response"] == "CO2 in 5.01 rose"

    def test_an_opening_question_still_hits_across_conversations(self):
        cache = _cache()

        async def go():
            await _put(cache, OPENER_A, [], answer="812 ppm")
            return await _get(cache, OPENER_A, None)

        hit = _run(go())
        assert hit and hit["response"] == "812 ppm"

    def test_role_still_partitions_a_follow_up(self):
        cache = _cache()

        async def go():
            await _put(cache, FOLLOW_UP, [OPENER_A], role="facility_manager", user="fm1")
            other_role = await _get(cache, FOLLOW_UP, [OPENER_A], role="occupant", user="fm1")
            same_role = await _get(cache, FOLLOW_UP, [OPENER_A], role="facility_manager")
            return other_role, same_role

        other_role, same_role = _run(go())
        assert other_role is None
        assert same_role is not None

    def test_role_still_partitions_an_opener(self):
        cache = _cache()

        async def go():
            await _put(cache, OPENER_A, None, role="facility_manager", user="fm1")
            return await _get(cache, OPENER_A, None, role="occupant", user="occ1")

        assert _run(go()) is None

    def test_a_fuzzy_lookup_does_not_cross_contexts(self):
        cache = _cache(fuzzy=True)
        near = "How has that changed over the last weeks?"
        assert (
            rc.trigram_similarity(rc.normalise_query(near), rc.normalise_query(FOLLOW_UP)) >= 0.85
        )

        async def go():
            await _put(cache, FOLLOW_UP, [OPENER_A], answer="CO2 in 5.01 rose")
            crossed = await _get(cache, near, [OPENER_B])
            same = await _get(cache, near, [OPENER_A])
            return crossed, same

        crossed, same = _run(go())
        assert crossed is None
        assert same and same["cache_type"] == "fuzzy"

    def test_a_fuzzy_opener_does_not_reach_a_follow_ups_entry(self):
        cache = _cache(fuzzy=True)
        near = "How has that changed over the last weeks?"

        async def go():
            await _put(cache, FOLLOW_UP, [OPENER_A])
            return await _get(cache, near, None)

        assert _run(go()) is None

    def test_a_flush_still_reaches_contextual_entries(self):
        cache = _cache(fuzzy=True)

        async def go():
            await _put(cache, FOLLOW_UP, [OPENER_A])
            await cache.invalidate(building_id="b", flush_all=True)
            return await _get(cache, FOLLOW_UP, [OPENER_A])

        assert _run(go()) is None
        assert not [k for k in cache._redis.hashes if k.startswith(cache.PREFIX_FUZZY)]


# ── the workflow: get and put agree ──────────────────────────────────────────


def _orch(cache):
    o = mod.WorkflowOrchestrator.__new__(mod.WorkflowOrchestrator)
    o.response_cache = cache
    return o


def _conversation(*user_turns: str, role: str = "facility_manager") -> ConversationState:
    messages = []
    for i, text in enumerate(user_turns):
        messages.append(Message(role="user", content=text))
        if i < len(user_turns) - 1:
            messages.append(Message(role="assistant", content=f"answer {i}"))
    state = ConversationState(
        conversation_id="c", user_id="fm1", user_message=user_turns[-1], messages=messages
    )
    state.building_id = "b"
    state.intermediate_results["user_role"] = role
    return state


def _rewrite_latest(state: ConversationState, rewritten: str) -> None:
    """What the dialogue node does to the latest message before the response node runs."""
    orig = state.messages[-1].content
    state.messages[-1] = Message(role="user", content=rewritten, metadata={"original_query": orig})


class _Recorder:
    def __init__(self):
        self.calls = []

    async def get(self, **kw):
        self.calls.append(kw)
        return None


class TestTheWorkflow:
    def test_the_lookup_carries_the_preceding_user_questions(self):
        rec = _Recorder()
        state = _conversation(OPENER_A, FOLLOW_UP)
        assert _run(_orch(rec)._serve_from_cache(state)) is False
        (call,) = rec.calls
        assert call["question"] == FOLLOW_UP
        assert call["context"] == [OPENER_A]
        assert call["role"] == "facility_manager"

    def test_an_opening_question_is_looked_up_with_no_context(self):
        rec = _Recorder()
        _run(_orch(rec)._serve_from_cache(_conversation(OPENER_A)))
        assert rec.calls[0]["context"] == []

    def test_the_lookup_context_is_bounded(self):
        rec = _Recorder()
        state = _conversation("q1", "q2", "q3", "q4", "q5", FOLLOW_UP)
        _run(_orch(rec)._serve_from_cache(state))
        assert rec.calls[0]["context"] == ["q3", "q4", "q5"]

    def test_the_store_uses_the_key_the_lookup_used_even_after_a_rewrite(self):
        """The response node sees the REWRITTEN latest message; it must still store under the
        raw words and the same context the lookup used."""
        rec = _Recorder()
        state = _conversation(OPENER_A, FOLLOW_UP)
        _run(_orch(rec)._serve_from_cache(state))
        _rewrite_latest(state, "How has the CO2 in room 5.01 changed over the last week?")
        state.messages.append(Message(role="assistant", content="it rose"))
        question, context = mod._response_cache_request(state)
        assert question == rec.calls[0]["question"] == FOLLOW_UP
        assert context == rec.calls[0]["context"] == [OPENER_A]

    def test_without_a_recorded_lookup_the_store_recovers_the_raw_words(self):
        state = _conversation(OPENER_A, FOLLOW_UP)
        _rewrite_latest(state, "How has the CO2 in room 5.01 changed over the last week?")
        state.messages.append(Message(role="assistant", content="it rose"))
        assert mod._response_cache_request(state) == (FOLLOW_UP, [OPENER_A])

    def test_the_recorded_lookup_is_consumed_by_the_store(self):
        """A key left on the bus must not be reused by the next turn."""
        rec = _Recorder()
        state = _conversation(OPENER_A, FOLLOW_UP)
        _run(_orch(rec)._serve_from_cache(state))
        mod._response_cache_request(state)
        assert mod._CACHE_REQUEST_KEY not in state.intermediate_results

    def test_a_put_then_the_matching_get_hits_and_another_chat_misses(self):
        """End to end through the real service: chat A stores, chat A' (same opener) hits,
        chat B (different opener) does not."""
        cache = _cache()
        orch = _orch(cache)
        chat_a = _conversation(OPENER_A, FOLLOW_UP)
        assert _run(orch._serve_from_cache(chat_a)) is False
        _rewrite_latest(chat_a, "How has the CO2 in room 5.01 changed over the last week?")
        chat_a.messages.append(Message(role="assistant", content="CO2 in 5.01 rose"))
        question, context = mod._response_cache_request(chat_a)
        _run(_put(cache, question, context, answer="CO2 in 5.01 rose"))

        chat_b = _conversation(OPENER_B, FOLLOW_UP)
        assert _run(orch._serve_from_cache(chat_b)) is False

        chat_a2 = _conversation(OPENER_A, FOLLOW_UP)
        assert _run(orch._serve_from_cache(chat_a2)) is True
        assert chat_a2.messages[-1].content == "CO2 in 5.01 rose"

    def test_the_response_node_stores_with_the_shared_request(self):
        """Source guard: the store must not go back to messages[-2]."""
        from pathlib import Path

        src = Path(mod.__file__).read_text(encoding="utf-8")
        put = src[src.index("await self.response_cache.put(") - 600 :][:1500]
        assert "_response_cache_request(state)" in put
        assert "context=" in put
        assert "state.messages[-2].content" not in put
