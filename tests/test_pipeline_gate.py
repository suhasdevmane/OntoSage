"""H2 (TRIAL_TRACKER, 2026-10-06): one pipeline turn at a time per process, with the wait logged.

The helper is exercised with real concurrent coroutines (two or more asyncio tasks), each test
on a fresh lock so no state leaks between tests. The endpoint wiring is a source check: the
pipeline is only reachable through the endpoints in orchestrator/main.py.
"""

from __future__ import annotations

import asyncio
import re
from pathlib import Path

import pytest

from orchestrator.services import pipeline_gate

pytestmark = pytest.mark.unit

REPO = Path(__file__).resolve().parents[1]
MAIN = REPO / "orchestrator" / "main.py"


@pytest.fixture(autouse=True)
def fresh_gate(monkeypatch):
    from shared.config import settings

    # These tests pin the one-at-a-time rule that applies to the local model.
    monkeypatch.setattr(settings, "MODEL_PROVIDER", "local")
    monkeypatch.setattr(pipeline_gate, "_gate", None)
    monkeypatch.setattr(pipeline_gate, "_waiting", 0)


def test_the_hosted_gateway_runs_as_many_turns_as_it_has_slots(monkeypatch):
    from shared.config import settings

    monkeypatch.setattr(settings, "MODEL_PROVIDER", "hosted")
    monkeypatch.setattr(settings, "HOSTED_PIPELINE_CONCURRENCY", 4)
    assert pipeline_gate._capacity() == 4
    monkeypatch.setattr(settings, "MODEL_PROVIDER", "local")
    assert pipeline_gate._capacity() == 1


class _Log:
    def __init__(self):
        self.lines = []

    def info(self, msg, *args, **kwargs):
        self.lines.append(msg)


def test_a_second_turn_waits_while_the_first_holds_the_pipeline(monkeypatch):
    events = []

    async def turn_body(name, pause):
        events.append(f"{name} start")
        await asyncio.sleep(pause)
        events.append(f"{name} end")
        return name

    async def scenario():
        first = asyncio.create_task(pipeline_gate.run(turn_body("first", 0.05), "a"))
        await asyncio.sleep(0)  # let the first take the lock
        assert pipeline_gate.busy() is True
        second = asyncio.create_task(pipeline_gate.run(turn_body("second", 0.0), "b"))
        await asyncio.sleep(0.01)
        assert pipeline_gate.waiting() == 1  # the second is queued, not running
        results = await asyncio.gather(first, second)
        return results

    assert asyncio.run(scenario()) == ["first", "second"]
    assert events == ["first start", "first end", "second start", "second end"]
    assert pipeline_gate.busy() is False
    assert pipeline_gate.waiting() == 0


def test_the_queue_wait_is_logged_with_its_duration(monkeypatch):
    log = _Log()
    monkeypatch.setattr(pipeline_gate, "logger", log)

    async def scenario():
        async def slow():
            await asyncio.sleep(0.05)

        a = asyncio.create_task(pipeline_gate.run(slow(), "first"))
        await asyncio.sleep(0)
        b = asyncio.create_task(pipeline_gate.run(asyncio.sleep(0), "second"))
        await asyncio.gather(a, b)

    asyncio.run(scenario())
    assert any("second: another question is being answered; queued" in m for m in log.lines)
    assert any("second: started after" in m and "in the queue" in m for m in log.lines)


def test_the_timeout_does_not_count_the_time_spent_queued():
    """A question that queued longer than its own budget must still get the full budget."""

    async def scenario():
        async def hold():
            await asyncio.sleep(0.3)

        async def quick():
            await asyncio.sleep(0.01)
            return "answered"

        first = asyncio.create_task(pipeline_gate.run(hold(), "holder"))
        await asyncio.sleep(0)
        # Queued for ~0.3 s, budget 0.2 s: it must answer, because only the run is timed.
        return await pipeline_gate.run(quick(), "queued", timeout=0.2), await first

    assert asyncio.run(scenario()) == ("answered", None)


def test_a_run_that_exceeds_its_own_timeout_raises_and_releases_the_gate():
    async def scenario():
        async def never():
            await asyncio.sleep(10)

        with pytest.raises(asyncio.TimeoutError):
            await pipeline_gate.run(never(), "slow", timeout=0.05)
        # The gate must be free again, or every later question queues forever.
        assert pipeline_gate.busy() is False
        return await pipeline_gate.run(asyncio.sleep(0, result="next"), "next")

    assert asyncio.run(scenario()) == "next"


def test_an_error_inside_a_turn_releases_the_gate():
    async def scenario():
        async def boom():
            raise RuntimeError("pipeline failed")

        with pytest.raises(RuntimeError):
            await pipeline_gate.run(boom(), "boom")
        return pipeline_gate.busy()

    assert asyncio.run(scenario()) is False


def test_two_streams_are_serialised_and_the_gate_frees_on_close():
    order = []

    async def stream_of(name):
        order.append(f"{name} open")
        for i in range(2):
            await asyncio.sleep(0.01)
            yield f"{name}{i}"
        order.append(f"{name} done")

    async def consume(name):
        out = []
        async for item in pipeline_gate.stream(stream_of(name), name):
            out.append(item)
        return out

    async def scenario():
        return await asyncio.gather(consume("x"), consume("y"))

    results = asyncio.run(scenario())
    assert results == [["x0", "x1"], ["y0", "y1"]]
    assert order == ["x open", "x done", "y open", "y done"]
    assert pipeline_gate.busy() is False


def test_the_message_a_waiting_client_sees_says_it_is_next():
    assert "You are next" in pipeline_gate.WAITING_MESSAGE
    assert "Another question is being answered" in pipeline_gate.WAITING_MESSAGE


def test_every_request_path_goes_through_the_gate():
    """The four request paths and the websocket are gated; the only bare calls left are in
    the unused _unused_oai_chat_completions and the background report job, which are not
    request paths."""
    src = MAIN.read_text(encoding="utf-8")
    assert len(re.findall(r"pipeline_gate\.run\(\s*orchestrator\.execute\(state\)", src)) == 2
    assert (
        len(re.findall(r"pipeline_gate\.stream\(\s*orchestrator\.stream_execute\(state\)", src))
        == 3
    )

    bare = [m.start() for m in re.finditer(r"await orchestrator\.execute\(state\)", src)] + [
        m.start()
        for m in re.finditer(r"async for step in orchestrator\.stream_execute\(state\)", src)
    ]
    # Bare calls allowed: _run_workflow_as_job (background), _unused_oai_chat_completions (unused).
    owners = []
    for pos in bare:
        head = src[:pos]
        owners.append(re.findall(r"\n(?:async )?def (\w+)", head)[-1])
    assert sorted(owners) == sorted(
        ["_run_workflow_as_job", "_unused_oai_chat_completions", "_unused_oai_chat_completions"]
    ), owners
