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
