# -*- coding: utf-8 -*-
"""A 'nearest' answer computed from an ASSUMED starting point says so in its first line (BUG-1419).

Tail Q, 2026-10-02 (occupant01, /v1): "where's the nearest bathroom?" -> "**The bathroom
nearest Room 0.01 is on the same floor:** Male washroom - Floor 0." The asker never said where
they were; the spatial lane measured from the building's entrance (the right default for a
visitor) and nothing in the answer said so. The clarification lane refuses "here" and "this
room" for exactly this reason. The default is kept; the guess is now stated, and only when the
default was actually used.
"""

from types import SimpleNamespace

import pytest

from orchestrator.agents.spatial_agent import SpatialAgent

pytestmark = pytest.mark.unit


def _agent(inner_text, assumed=None):
    agent = SpatialAgent.__new__(SpatialAgent)

    async def _inner(*a, **k):
        agent._assumed_start_label = assumed
        return inner_text

    agent._answer_nearest_inner = _inner
    return agent


async def test_an_assumed_start_is_stated_first():
    agent = _agent(
        "**The bathroom nearest Room 0.01 is on the same floor:** Male washroom", "Room 0.01"
    )
    out = await agent._answer_nearest("where's the nearest bathroom?", [], {})
    assert out.startswith("_You did not say where you are, so this is measured from **Room 0.01**")
    assert "Male washroom" in out


async def test_a_named_start_is_not_prefixed():
    agent = _agent("**The toilet nearest Room 3.01 is on the same floor:** ...", None)
    out = await agent._answer_nearest("nearest toilet to room 3.01", [], {})
    assert not out.startswith("_You did not say")


async def test_a_decline_for_want_of_a_start_is_not_prefixed():
    agent = _agent("I can look up the nearest toilet, but I need a starting point", "Reception")
    out = await agent._answer_nearest("nearest toilet?", [], {})
    assert out.startswith("I can look up")


async def test_the_flag_is_cleared_between_calls():
    agent = _agent("x", "Reception")
    await agent._answer_nearest("nearest lift?", [], {})
    assert agent._assumed_start_label is None


def test_the_inner_sets_the_flag_only_on_the_default_branch():
    import inspect

    src = inspect.getsource(SpatialAgent._answer_nearest_inner)
    i_default = src.index("await self._default_start(manifests, zone_to_space)")
    i_flag = src.index("self._assumed_start_label = (")
    assert i_default < i_flag
