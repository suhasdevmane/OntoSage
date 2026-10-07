"""C8 (trial readiness, 2026-10-07): what one turn spends on the model, in the existing trace.

Pins four things:
* an untraced caller (script, test) records nothing and reports None;
* a traced request counts LOGICAL generate() calls, not retries, and sums their wall time;
* the count survives asyncio child tasks, because the dict is shared by reference;
* `plan_trace_for_response` carries `llm` on the plan trace the /v1 bodies already return,
  and leaves the trace unchanged when there is none.
"""

from __future__ import annotations

import asyncio
import importlib
from unittest.mock import AsyncMock

import pytest

from orchestrator.workflow._orchestrator import plan_trace_for_response

# `orchestrator.llm_manager` is also an attribute of the package (the shared instance), so the
# module must be fetched by name.
lm = importlib.import_module("orchestrator.llm_manager")

pytestmark = pytest.mark.unit


@pytest.fixture(autouse=True)
def _untraced_after_each_test():
    """begin_llm_trace() sets a context variable that outlives the test; reset it for the next."""
    yield
    lm._llm_failures.set(None)
    lm._llm_usage.set(None)


def _manager_with(attempts: AsyncMock) -> lm.LLMManager:
    """An LLMManager without its provider clients; only the counting wrapper is exercised."""
    manager = lm.LLMManager.__new__(lm.LLMManager)
    manager._generate_attempts = attempts  # instance attribute shadows the method
    return manager


def test_an_untraced_caller_records_nothing_and_reports_none():
    lm._llm_usage.set(None)
    lm.record_llm_call(1.5)
    assert lm.llm_usage() is None


def test_a_traced_request_sums_calls_and_seconds():
    lm.begin_llm_trace()
    lm.record_llm_call(1.25)
    lm.record_llm_call(0.5)
    assert lm.llm_usage() == {"calls": 2, "seconds": 1.75}


def test_a_negative_duration_cannot_reduce_the_total():
    lm.begin_llm_trace()
    lm.record_llm_call(-3.0)
    assert lm.llm_usage() == {"calls": 1, "seconds": 0.0}


def test_generate_counts_one_logical_call_however_many_attempts_it_made():
    async def run():
        attempts = AsyncMock(side_effect=["retried-and-answered"])
        manager = _manager_with(attempts)
        lm.begin_llm_trace()
        out = await manager.generate("prompt")
        return out, lm.llm_usage()

    out, usage = asyncio.run(run())
    assert out == "retried-and-answered"
    assert usage["calls"] == 1
    assert usage["seconds"] >= 0.0


def test_a_failed_generation_is_still_a_call_that_was_made():
    async def run():
        attempts = AsyncMock(side_effect=RuntimeError("provider down"))
        manager = _manager_with(attempts)
        lm.begin_llm_trace()
        with pytest.raises(RuntimeError):
            await manager.generate("prompt")
        return lm.llm_usage()

    assert asyncio.run(run())["calls"] == 1


def test_child_tasks_report_into_the_request_that_spawned_them():
    async def run():
        manager = _manager_with(AsyncMock(return_value="ok"))
        lm.begin_llm_trace()
        await asyncio.gather(manager.generate("a"), manager.generate("b"), manager.generate("c"))
        return lm.llm_usage()

    assert asyncio.run(run())["calls"] == 3


def test_the_plan_trace_carries_llm_usage_when_traced():
    lm.begin_llm_trace()
    lm.record_llm_call(2.0)
    results = {"plan_trace": {"intent": "sensor_data", "steps": []}}
    refreshed = plan_trace_for_response(results)
    assert refreshed["llm"] == {"calls": 1, "seconds": 2.0}
    assert refreshed["intent"] == "sensor_data"
    assert "stage_ms" in refreshed


def test_the_plan_trace_has_no_llm_key_when_untraced():
    lm._llm_usage.set(None)
    refreshed = plan_trace_for_response({"plan_trace": {"intent": "x", "steps": []}})
    assert "llm" not in refreshed


def test_no_plan_trace_stays_none():
    lm.begin_llm_trace()
    assert plan_trace_for_response({}) is None
