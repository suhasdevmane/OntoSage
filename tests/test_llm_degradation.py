# -*- coding: utf-8 -*-
"""V5-BUG-177: an LLM outage must be declared, never graded as behaviour.

A quota refusal (429), a timeout or an open circuit makes every agent fall back
to generic text.  That text reads like an ordinary answer, so an offline grader
scores it — and the run then reports a coverage/leak number that measures the
outage instead of the system.  These tests pin the declaration path.
"""

from __future__ import annotations

import asyncio

import pytest

from orchestrator.llm_manager import (
    EmptyCompletionError,
    begin_llm_trace,
    classify_llm_error,
    llm_degradation,
    record_llm_failure,
)

pytestmark = pytest.mark.unit


# ── cause classification ─────────────────────────────────────────────────────


@pytest.mark.parametrize(
    "error, expected",
    [
        (RuntimeError("Error code: 429 - rate limit reached"), "rate_limit"),
        (RuntimeError("this model requires a subscription, upgrade for access"), "rate_limit"),
        (RuntimeError("You exceeded your current quota"), "rate_limit"),
        (RuntimeError("Too Many Requests"), "rate_limit"),
        (EmptyCompletionError("LLM [fast] returned an empty completion"), "empty_completion"),
        (TimeoutError("LLM [complex] timed out after 60.0s"), "timeout"),
        (RuntimeError("LLM circuit breaker is OPEN — the ollama_cloud provider"), "circuit_open"),
        (RuntimeError("Connection aborted"), "connection"),
        (ValueError("something else entirely"), "other"),
    ],
)
def test_failure_causes_are_classified(error, expected):
    assert classify_llm_error(error) == expected


def test_asyncio_timeout_is_a_timeout():
    assert classify_llm_error(asyncio.TimeoutError()) == "timeout"


# ── per-request trace ────────────────────────────────────────────────────────


def test_untraced_caller_is_a_noop():
    """Scripts and tests call the LLM outside a request — recording must not blow up."""
    record_llm_failure(RuntimeError("429 rate limit"))  # no begin_llm_trace()
    assert llm_degradation() is None


def test_clean_turn_declares_nothing():
    begin_llm_trace()
    assert llm_degradation() is None


def test_rate_limit_is_named_so_the_operator_can_act():
    begin_llm_trace()
    record_llm_failure(RuntimeError("Error code: 429 - rate limit reached"), "fast")
    d = llm_degradation()
    assert d["rate_limited"] is True
    assert d["causes"] == ["rate_limit"]
    assert d["failed_calls"] == 1


def test_multiple_failures_are_summarised_without_duplicates():
    begin_llm_trace()
    record_llm_failure(TimeoutError("timed out after 60.0s"), "complex")
    record_llm_failure(TimeoutError("timed out after 60.0s"), "fast")
    record_llm_failure(EmptyCompletionError("empty"), "fast")
    d = llm_degradation()
    assert d["failed_calls"] == 3
    assert d["causes"] == ["empty_completion", "timeout"]
    assert d["rate_limited"] is False


def test_a_new_turn_does_not_inherit_the_previous_turn_s_failures():
    begin_llm_trace()
    record_llm_failure(RuntimeError("429 rate limit"))
    assert llm_degradation() is not None
    begin_llm_trace()  # next request
    assert llm_degradation() is None


def test_detail_is_truncated_so_a_provider_dump_cannot_bloat_the_reply():
    begin_llm_trace()
    record_llm_failure(RuntimeError("x" * 5000))
    assert len(llm_degradation()["detail"]) <= 200


def test_nested_tasks_report_into_the_request_that_spawned_them():
    """Pipeline nodes run as child tasks; their failures must reach the reply."""

    async def scenario():
        begin_llm_trace()

        async def node():
            record_llm_failure(RuntimeError("429 rate limit"), "fast")

        await asyncio.gather(node(), node())
        return llm_degradation()

    d = asyncio.run(scenario())
    assert d is not None and d["failed_calls"] == 2


def test_concurrent_requests_do_not_cross_contaminate():
    """Two in-flight turns must not see each other's faults."""

    async def turn(fail: bool):
        begin_llm_trace()
        await asyncio.sleep(0)  # yield, interleaving the two turns
        if fail:
            record_llm_failure(RuntimeError("429 rate limit"))
        await asyncio.sleep(0)
        return llm_degradation()

    async def both():
        return await asyncio.gather(turn(True), turn(False))

    failed, clean = asyncio.run(both())
    assert failed is not None and failed["rate_limited"] is True
    assert clean is None
