"""BUG-585: Open WebUI streams by default, and the streamed path skipped three things execute() does.

`stream_execute` went straight to `graph.astream(state)`, so a streamed turn:
  * kept the previous turn's lane results on the bus — the defect `_clear_stale_lane_results`
    was written for, where turn 2 returned turn 1's answer verbatim about the wrong room;
  * never consulted the response cache, so the demo runbook's warm-up did nothing in the UI;
  * had no workflow deadline and no honest "took too long" reply.
Every rehearsal used stream:false, so none of this was ever exercised.
"""

import asyncio

import pytest

from orchestrator.workflow import _orchestrator as mod
from shared.models import ConversationState, Message

pytestmark = pytest.mark.unit


class _Graph:
    def __init__(self, delay=0.0):
        self.seen = None
        self.delay = delay

    async def astream(self, state):
        self.seen = dict(state.intermediate_results)
        if self.delay:
            await asyncio.sleep(self.delay)
        state.messages.append(Message(role="assistant", content="fresh"))
        yield {"response": state}


class _Cache:
    def __init__(self, hit):
        self.hit = hit

    async def get(self, **kw):
        return self.hit


def _orch(graph, cache=None):
    o = mod.WorkflowOrchestrator.__new__(mod.WorkflowOrchestrator)
    o.graph = graph
    o.response_cache = cache
    return o


def _state():
    s = ConversationState(
        conversation_id="c", user_id="u", user_message="q2", messages=[Message(role="user", content="q2")]
    )
    s.intermediate_results["deliberate_result"] = {"formatted_response": "turn 1 answer"}
    return s


async def _drain(agen):
    return [step async for step in agen]


def test_a_streamed_turn_clears_the_previous_turns_lane_results():
    graph = _Graph()
    asyncio.run(_drain(_orch(graph).stream_execute(_state())))
    assert "deliberate_result" not in graph.seen


def test_a_streamed_turn_is_served_from_the_response_cache():
    graph = _Graph()
    hit = {"response": "cached answer", "intent": "metadata", "cache_type": "exact"}
    steps = asyncio.run(_drain(_orch(graph, _Cache(hit)).stream_execute(_state())))
    assert graph.seen is None  # the graph never ran
    final = list(steps[-1].values())[0]
    assert final.messages[-1].content == "cached answer"


def test_a_streamed_turn_past_the_deadline_says_so(monkeypatch):
    monkeypatch.setattr(mod.settings, "WORKFLOW_TIMEOUT_S", 0.05, raising=False)
    steps = asyncio.run(_drain(_orch(_Graph(delay=1.0)).stream_execute(_state())))
    final = list(steps[-1].values())[0]
    assert "took too long" in final.messages[-1].content
