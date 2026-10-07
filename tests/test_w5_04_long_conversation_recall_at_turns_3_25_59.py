# -*- coding: utf-8 -*-
"""TODO-1026 / W5-04 — the long-conversation acceptance that was never actually run.

WHY THIS FILE EXISTS INSTEAD OF A RECOVERED ORIGINAL
------------------------------------------------------
TODO-1026 (`tasks/FIX_TRACKER.csv`) reads: *"W5-04's long-conversation test still FAILS,
and now fails worse than it did."* The row's own evidence pointed at ``python
memory_probe.py`` and ``scratchpad/waveG_probe_before.txt``. Neither file exists in this
tree, and an exhaustive search found neither in ANY commit on ANY ref this repository
holds: ``git log --all -- "*memory_probe*" "*waveG*" "*w5_04*"`` is empty across all 417
commits reachable from every local and remote branch. They were never committed — the
tracker row's own wording ("Re-run 2026-09-30 after flushing resp_cache: python
memory_probe.py v1 6, ...") describes a hand-run live script against a running stack
(8 turns at 40-86 s each), the kind of thing `.gitignore`'s "Session scratch from live
verification runs" comment exists for. There is nothing to restore.

The row's own stated, unattempted acceptance is precise enough to rebuild faithfully,
though: *"the row's full acceptance (60 turns, recall at 3, 25 and 59) is still not
attempted: the probe holds 8 turns because each costs 40-86 s live, so 60 turns is
roughly an hour of stack time."* That cost is specific to the LIVE harness — it drove the
whole LangGraph pipeline (classification, SPARQL, an LLM call) for every one of the 60
turns just to produce filler answers. The mechanism TODO-1026 was actually worried about,
session_recall (BUG-1020/BUG-941), never calls an LLM at all: its own docstring says "it
quotes; it does not interpret". The two pieces that matter — ``TurnMemoryService``
(Postgres I/O) and ``session_recall.answer`` (pure text) — can be driven directly, so the
60-turn-scale acceptance can be run in milliseconds offline instead of an hour live.

WHAT THIS PROVES THAT THE EXISTING TESTS DO NOT
-------------------------------------------------
``tests/test_a_question_about_the_conversation_is_not_about_the_building.py`` already
pins ``session_recall.answer()`` thoroughly, but every fixture it uses is a hand-built
``List[TurnNote]`` of 7 or up to 40 synthetic rows handed straight to ``answer()`` — it
never drives ``TurnMemoryService.save_turn`` / ``get_session_context`` across a real,
growing conversation, so it cannot show whether the Postgres retention cap
(``_MAX_OLDER_SCAN`` / ``_MAX_TURNS_PER_CONVERSATION`` = 500) or the ``ORDER BY
turn_index DESC LIMIT`` / reverse-to-oldest-first plumbing could silently drop the turn
that named the subject once the conversation runs long. This file drives the real
service, with an in-memory Postgres stand-in that actually accumulates rows turn by
turn, and checks recall at the row's own three checkpoints.

Refs: TODO-1026; BUG-1020; BUG-941; W5-01; W5-02; W5-03; W5-04.
"""

from __future__ import annotations

import pytest

from orchestrator.services.session_recall import VALUES_CAVEAT, answer
from orchestrator.services.turn_memory import TurnMemoryService
from shared.models import ConversationState, Message

pytestmark = pytest.mark.unit

RECALL_Q = "Remind me which room I said I was looking into, and why."

#: What BUG-1020 fabricated live, and what must never reappear at any conversation length.
FABRICATED_ROOM = "0.01"


class _FakeConn:
    """A minimal, STATEFUL stand-in for the one asyncpg connection ``turn_memory.py`` uses.

    Backed by a real list of row-dicts shared with the pool, so a simulated multi-turn
    conversation behaves the way Postgres would: ``turn_index`` increments off the actual
    MAX() of what is stored, the retention DELETE prunes against the actual row set, and
    ``get_session_context``'s ``ORDER BY turn_index DESC LIMIT`` runs against real
    accumulated state rather than a canned fixture.
    """

    def __init__(self, rows: list):
        self.rows = rows

    async def fetchval(self, sql: str, conversation_id: str):
        mine = [r for r in self.rows if r["conversation_id"] == conversation_id]
        return max((r["turn_index"] for r in mine), default=0) + 1

    async def execute(self, sql: str, *args):
        if "INSERT INTO turn_memory" in sql:
            (
                conversation_id,
                user_id,
                turn_index,
                user_query,
                intent,
                entities,
                result_summary,
                carry_forward,
                evidence,
            ) = args
            self.rows.append(
                {
                    "conversation_id": conversation_id,
                    "user_id": user_id,
                    "turn_index": turn_index,
                    "user_query": user_query,
                    "intent": intent,
                    "entities": entities,
                    "result_summary": result_summary,
                    "carry_forward": carry_forward,
                    "evidence": evidence,
                }
            )
        elif "DELETE FROM turn_memory" in sql:
            conversation_id, keep_n = args
            mine = [r for r in self.rows if r["conversation_id"] == conversation_id]
            if mine:
                threshold = max(r["turn_index"] for r in mine) - keep_n
                self.rows[:] = [
                    r
                    for r in self.rows
                    if not (
                        r["conversation_id"] == conversation_id and r["turn_index"] <= threshold
                    )
                ]
        return "OK"

    async def fetch(self, sql: str, conversation_id: str, limit: int):
        mine = [r for r in self.rows if r["conversation_id"] == conversation_id]
        mine.sort(key=lambda r: r["turn_index"], reverse=True)
        return [dict(r) for r in mine[:limit]]


class _FakeAcquire:
    def __init__(self, conn: _FakeConn):
        self._conn = conn

    async def __aenter__(self):
        return self._conn

    async def __aexit__(self, exc_type, exc, tb):
        return False


class _FakePool:
    """One shared row table; every ``acquire()`` sees the same accumulated state, as a
    real pool would across sequential calls for one conversation."""

    def __init__(self):
        self.rows: list = []
        self._conn = _FakeConn(self.rows)

    def acquire(self):
        return _FakeAcquire(self._conn)


def _state(conversation_id: str, user_text: str) -> ConversationState:
    return ConversationState(
        conversation_id=conversation_id,
        user_id="tester",
        user_message=user_text,
        building_id="bldg1",
        messages=[
            Message(role="user", content=user_text),
            Message(role="assistant", content="Answered from the building's records."),
        ],
        intermediate_results={"intent": "sensor_data"},
    )


@pytest.mark.asyncio
async def test_a_subject_named_at_turn_1_is_still_recalled_at_turns_3_25_and_59():
    """The row's own unattempted acceptance, run offline: 60 turns, recall at 3, 25, 59."""
    pool = _FakePool()
    svc = TurnMemoryService(pool=pool)
    conv = "conv-w5-04-long"

    async def _save(text: str) -> None:
        await svc.save_turn(_state(conv, text))

    async def _recall_now() -> str:
        _summary, notes = await svc.get_session_context(conv)
        return answer(RECALL_Q, notes)

    # Turn 1: the subject, worded exactly as the live BUG-941/BUG-1020 probe stated it.
    await _save("I am looking into air quality in room 5.01 specifically.")
    # Turn 2: filler that names no room.
    await _save("What is the temperature on floor 1?")

    # Checkpoint "at turn 3": two turns saved, the recall question would be the third.
    out = await _recall_now()
    assert "5.01" in out
    assert "air quality" in out
    assert FABRICATED_ROOM not in out

    # Turns 3-24: 22 more filler turns, none mentioning a room.
    for i in range(22):
        await _save(f"What is the temperature on floor {i % 5}?")

    # Checkpoint "at turn 25".
    out = await _recall_now()
    assert "5.01" in out
    assert "air quality" in out
    assert FABRICATED_ROOM not in out

    # Turns 25-58: 34 more filler turns.
    for i in range(34):
        await _save(f"What is the humidity on floor {i % 5}?")

    # Checkpoint "at turn 59" — the row's own number, and further than the live probe
    # ever reached (its longest recorded run was 8 turns).
    out = await _recall_now()
    assert "5.01" in out
    assert "air quality" in out
    assert FABRICATED_ROOM not in out
    assert VALUES_CAVEAT in out

    # The plumbing half (W5-01/W5-02), checked at THIS scale rather than assumed from the
    # 1-2 turn fixtures the existing wiring tests use: the retention cap (500) must not
    # have fired, or the turn naming the subject would already be gone by turn 59.
    assert len(pool.rows) == 58
    assert any(r["turn_index"] == 1 and "5.01" in r["user_query"] for r in pool.rows)


@pytest.mark.asyncio
async def test_a_conversation_with_no_subject_still_declines_honestly_at_turn_59():
    """The negative case at the same scale: nothing to recall must stay nothing to recall,
    not a guess, however many filler turns pile up in between."""
    pool = _FakePool()
    svc = TurnMemoryService(pool=pool)
    conv = "conv-w5-04-long-no-subject"

    for i in range(59):
        await svc.save_turn(_state(conv, f"What is the temperature on floor {i % 5}?"))

    _summary, notes = await svc.get_session_context(conv)
    out = answer(RECALL_Q, notes)

    assert "no record of you mentioning" in out
    assert "5.01" not in out
    assert FABRICATED_ROOM not in out
