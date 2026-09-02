# -*- coding: utf-8 -*-
"""A lane's answer must not outlive the turn that produced it (BUG-392).

Measured live on bldg1, one session, two turns:

    turn 1  "Which public space on floor 2 is quietest right now?"
            -> deliberate lane: "Best match: Room 2.44 — Server Room ... (noise: 36.175)"
    turn 2  "What is the temperature in Room 5.04 right now?"
            -> classified correctly as sensor_data, and returned TURN 1'S ANSWER VERBATIM

A confident, specific reading about the wrong room, the wrong floor and the wrong modality.
The response cache then stored it under turn 2's key, so the wrong answer outlived the
session and was served to a fresh one — which is how it was first noticed.

CAUSE: a resumed conversation is loaded from Redis with its whole `intermediate_results`
intact and only `user_message` replaced, so every lane result from the previous turn was
still on the bus. `_response_node` collects the first lane it recognises and checks
`deliberate_result` long before `sql_result`.

The completeness test at the bottom is the one that matters most. The FIRST attempt at this
fix derived the key list from `_LANE_KEYS_FOR_DIAGNOSIS`, a list written for a different
purpose that does not contain `deliberate_result` — so the fix deployed, ran, cleared nine
keys, and changed nothing at all. Only an explicit check against what `_response_node`
actually reads can catch that.
"""

import re
from pathlib import Path

import pytest

from orchestrator.workflow._orchestrator import (
    _CARRIED_FORWARD_ON_PURPOSE,
    _PER_TURN_LANE_KEYS,
    _clear_stale_lane_results,
)

pytestmark = pytest.mark.unit

_SRC = Path(__file__).resolve().parent.parent / "orchestrator" / "workflow" / "_orchestrator.py"


class _State:
    def __init__(self, **results):
        self.intermediate_results = results


def test_the_key_that_caused_the_bug_is_cleared():
    assert "deliberate_result" in _PER_TURN_LANE_KEYS


def test_a_previous_turns_deliberate_answer_does_not_survive():
    state = _State(deliberate_result={"formatted_response": "Best match: Room 2.44"})
    _clear_stale_lane_results(state)
    assert "deliberate_result" not in state.intermediate_results


@pytest.mark.parametrize("key", _PER_TURN_LANE_KEYS)
def test_every_per_turn_key_is_actually_cleared(key):
    state = _State(**{key: {"formatted_response": "stale"}})
    _clear_stale_lane_results(state)
    assert key not in state.intermediate_results


@pytest.mark.parametrize("key", _CARRIED_FORWARD_ON_PURPOSE)
def test_deliberately_carried_keys_survive(key):
    """turn_memory carries these so "now plot that" can still find its referent."""
    state = _State(**{key: {"series": [1, 2, 3]}})
    _clear_stale_lane_results(state)
    assert key in state.intermediate_results


def test_the_carried_and_cleared_lists_do_not_overlap():
    assert not set(_PER_TURN_LANE_KEYS) & set(_CARRIED_FORWARD_ON_PURPOSE)


def test_user_context_is_not_wiped():
    """Clearing must not take the identity the PDP needs with it."""
    state = _State(user_id="alice", user_role="occupant", sql_result={"x": 1})
    _clear_stale_lane_results(state)
    assert state.intermediate_results["user_id"] == "alice"
    assert state.intermediate_results["user_role"] == "occupant"


def test_a_state_with_no_results_is_survivable():
    class _Bare:
        pass

    _clear_stale_lane_results(_Bare())  # must not raise


def test_every_lane_result_the_response_node_reads_is_cleared():
    """The guard that would have caught the first, inert version of this fix.

    Any `*_result` key `_response_node` collects must expire with its turn. One missing entry
    means that lane's answer stays pinned for the rest of the session — which is precisely
    what `deliberate_result` did.
    """
    src = _SRC.read_text(encoding="utf-8")
    read_keys = set(re.findall(r'intermediate_results\.get\("([a-z_]+_result)"', src))
    assert read_keys, "found no lane result reads — the pattern needs updating"
    allowed = set(_PER_TURN_LANE_KEYS) | set(_CARRIED_FORWARD_ON_PURPOSE)
    missing = sorted(read_keys - allowed)
    assert (
        not missing
    ), f"these lane results are read but never cleared, so they outlive their turn: {missing}"
