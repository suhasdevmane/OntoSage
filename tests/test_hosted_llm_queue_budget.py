# -*- coding: utf-8 -*-
"""The hosted COMAT gateway: queue-aware deadline, a process-wide gate, and a token floor.

The gateway generates a few requests at once and QUEUES the rest, so a request can wait
minutes before its first token. Three things in the client were sized for a local model that
answers at once, and each one abandoned or starved a request that was merely waiting:

1. The client deadline was `LLM_TIMEOUT_S * 1.5 + 15` (105 s at the default) -- shorter than
   a queued request. Now `HOSTED_LLM_TIMEOUT_S` (660 s), with the outer `wait_for` 30 s longer.
2. Requests were stacked on the gateway without limit. Now a process-wide gate of
   `HOSTED_LLM_MAX_CONCURRENCY` (4), and the wait for a slot is logged.
3. A reasoning model can spend its whole `max_tokens` on hidden reasoning and return an empty
   answer with `finish_reason=length`. Now every hosted call carries a floor
   (`HOSTED_LLM_MAX_TOKENS`, 4096), and a budget shortfall is retried once at double.

The fakes below stand in for the gateway client. Nothing here opens a socket.
"""

from __future__ import annotations

import asyncio
import importlib
import logging
from types import SimpleNamespace

import pytest


@pytest.fixture(autouse=True)
def _no_live_probe(monkeypatch):
    # These tests exercise the queue and the budget, not the reachability check.
    from orchestrator.llm_manager import LLMManager

    async def _up(self):
        return None

    monkeypatch.setattr(LLMManager, "_probe_hosted_gateway", _up)

pytestmark = pytest.mark.unit


def _lm():
    """The llm_manager MODULE. The package re-exports the singleton under the same name."""
    return importlib.import_module("orchestrator.llm_manager")


class _Breaker:
    def allow_request(self):
        return True

    def record_success(self):
        pass

    def record_failure(self):
        pass


def _hosted_manager(lm, monkeypatch, **module_overrides):
    """A hosted-provider LLMManager without the import-time constructor, with fast pacing."""
    for key, value in {
        "OPENAI_RATE_LIMIT_DELAY": 0.0,
        "OPENAI_RETRY_DELAY_S": 0.0,
        "LLM_BACKOFF_BASE_S": 0.0,
        **module_overrides,
    }.items():
        monkeypatch.setattr(lm, key, value, raising=True)
    mgr = lm.LLMManager.__new__(lm.LLMManager)
    mgr.provider = "hosted"
    mgr.config = {"base_url": "http://gateway.invalid/v1", "model": "gpt-oss:20b"}
    mgr.client = mgr.client_fast = object()  # replaced per test where a call is made
    mgr.last_request_time = mgr.last_request_time_fast = 0.0
    mgr._breaker = _Breaker()
    return mgr


class _Gateway:
    """A chat client whose `agenerate` answers from a script of (content, finish_reason)."""

    def __init__(self, script):
        self.script = list(script)
        self.calls = []

    async def agenerate(self, messages, **kwargs):
        self.calls.append(dict(kwargs))
        content, finish = self.script[min(len(self.calls) - 1, len(self.script) - 1)]
        message = SimpleNamespace(content=content)
        generation = SimpleNamespace(message=message, generation_info={"finish_reason": finish})
        return SimpleNamespace(generations=[[generation]])


# ── 1. Deadlines ─────────────────────────────────────────────────────────────


def test_the_hosted_deadline_defaults_to_660_seconds():
    """Pinned on the field default, so the number cannot drift unnoticed."""
    from shared.config import Settings

    assert Settings.model_fields["HOSTED_LLM_TIMEOUT_S"].default == 660.0


def test_the_hosted_attempt_outlasts_the_client_deadline(monkeypatch):
    lm = _lm()
    mgr = _hosted_manager(lm, monkeypatch)
    monkeypatch.setattr(lm.settings, "HOSTED_LLM_TIMEOUT_S", 660.0)
    assert mgr._attempt_timeout_s() == pytest.approx(690.0)


def test_a_local_attempt_keeps_the_local_deadline(monkeypatch):
    """The hosted change must not move any existing provider's bound."""
    lm = _lm()
    mgr = _hosted_manager(lm, monkeypatch)
    mgr.provider = "ollama"
    monkeypatch.setattr(lm, "LLM_TIMEOUT_S", 180.0, raising=True)
    assert mgr._attempt_timeout_s() == pytest.approx(180.0)


def test_the_hosted_client_gets_the_long_deadline_and_no_sdk_retries(monkeypatch):
    """The SDK must not re-send a timed-out request into the same gateway queue."""
    lm = _lm()
    mgr = _hosted_manager(lm, monkeypatch)
    mgr.config.update({"api_key": "test-key", "temperature": 0.0})
    monkeypatch.setattr(lm.settings, "HOSTED_LLM_TIMEOUT_S", 660.0)
    monkeypatch.setattr(lm.settings, "HOSTED_LLM_MAX_TOKENS", 4096)
    mgr._initialize_hosted()
    assert mgr.client.max_retries == 0
    assert mgr.client.request_timeout.read == pytest.approx(660.0)
    assert mgr.client.request_timeout.connect == pytest.approx(10.0)
    assert mgr.client_fast is mgr.client


def test_the_workflow_deadline_is_derived_from_the_hosted_call_not_the_local_one(monkeypatch):
    """Derived from LLM_TIMEOUT_S this would be 180 s, and a queued call would be killed."""
    import shared.config as cfg

    monkeypatch.delenv("LLM_TIMEOUT_S", raising=False)
    s = cfg.Settings(MODEL_PROVIDER="hosted", WORKFLOW_TIMEOUT_S=0, HOSTED_LLM_TIMEOUT_S=660.0)
    # 2 x (660 + 30) + 60
    assert s.WORKFLOW_TIMEOUT_S == 1440


# ── 2. Concurrency gate ──────────────────────────────────────────────────────


def test_at_most_the_cap_run_at_once_and_all_five_complete(monkeypatch):
    lm = _lm()
    mgr = _hosted_manager(lm, monkeypatch)
    monkeypatch.setattr(lm.settings, "HOSTED_LLM_MAX_CONCURRENCY", 2)
    in_flight = {"now": 0, "peak": 0}

    async def fake_once(*_a, **_k):
        in_flight["now"] += 1
        in_flight["peak"] = max(in_flight["peak"], in_flight["now"])
        await asyncio.sleep(0.05)
        in_flight["now"] -= 1
        return "an answer"

    monkeypatch.setattr(mgr, "_generate_once", fake_once)

    async def run_all():
        return await asyncio.gather(*(mgr.generate(f"question {i}") for i in range(5)))

    results = asyncio.run(run_all())
    assert results == ["an answer"] * 5
    assert in_flight["peak"] == 2


def test_a_request_queued_behind_the_gate_is_logged(monkeypatch, caplog):
    lm = _lm()
    mgr = _hosted_manager(lm, monkeypatch)
    monkeypatch.setattr(lm.settings, "HOSTED_LLM_MAX_CONCURRENCY", 1)

    async def fake_once(*_a, **_k):
        await asyncio.sleep(0.05)
        return "ok"

    monkeypatch.setattr(mgr, "_generate_once", fake_once)

    async def run_all():
        return await asyncio.gather(mgr.generate("a"), mgr.generate("b"))

    with caplog.at_level(logging.INFO):
        asyncio.run(run_all())
    assert "slots busy" in caplog.text


def test_the_gate_is_not_taken_by_a_local_provider(monkeypatch):
    lm = _lm()
    mgr = _hosted_manager(lm, monkeypatch)
    mgr.provider = "ollama"
    monkeypatch.setattr(lm.settings, "HOSTED_LLM_MAX_CONCURRENCY", 1)

    async def probe():
        async with mgr._hosted_slot("fast"):
            pass
        return mgr._hosted_sem

    assert asyncio.run(probe()) is None


# ── 3. Token floor and the budget retry ──────────────────────────────────────


def test_a_small_requested_budget_is_raised_to_the_floor(monkeypatch):
    lm = _lm()
    mgr = _hosted_manager(lm, monkeypatch)
    monkeypatch.setattr(lm.settings, "HOSTED_LLM_MAX_TOKENS", 4096)
    gateway = _Gateway([("answer", "stop")])

    out = asyncio.run(
        mgr._generate_once("p", None, None, gateway, provider_kwargs={"max_tokens": 8})
    )
    assert out == "answer"
    assert gateway.calls[0]["max_tokens"] == 4096


def test_an_empty_length_answer_is_retried_once_at_double_the_budget(monkeypatch, caplog):
    lm = _lm()
    mgr = _hosted_manager(lm, monkeypatch)
    monkeypatch.setattr(lm.settings, "HOSTED_LLM_MAX_TOKENS", 4096)
    gateway = _Gateway([("", "length"), ("a real answer", "stop")])
    mgr.client = mgr.client_fast = gateway

    with caplog.at_level(logging.WARNING):
        out = asyncio.run(mgr.generate("how warm is it?"))

    assert out == "a real answer"
    assert [c["max_tokens"] for c in gateway.calls] == [4096, 8192]
    assert "max_tokens=4096" in caplog.text and "Retrying" in caplog.text


def test_a_budget_shortfall_that_persists_gives_up_and_names_the_budget(monkeypatch):
    lm = _lm()
    mgr = _hosted_manager(lm, monkeypatch, LLM_MAX_RETRIES=2)
    monkeypatch.setattr(lm.settings, "HOSTED_LLM_MAX_TOKENS", 4096)
    gateway = _Gateway([("", "length")])
    mgr.client = mgr.client_fast = gateway

    with pytest.raises(lm.EmptyCompletionError) as info:
        asyncio.run(mgr.generate("how warm is it?"))

    # Two attempts, each trying 4096 then 8192 -- four calls, and the error names the budget.
    assert [c["max_tokens"] for c in gateway.calls] == [4096, 8192, 4096, 8192]
    assert "budget of 8192" in str(info.value)


def test_an_empty_stop_is_not_mistaken_for_a_budget_shortfall(monkeypatch):
    """Only finish_reason=length means the budget was spent; any other empty answer is a
    plain empty completion and does not double the budget."""
    lm = _lm()
    mgr = _hosted_manager(lm, monkeypatch, LLM_MAX_RETRIES=1)
    monkeypatch.setattr(lm.settings, "HOSTED_LLM_MAX_TOKENS", 4096)
    gateway = _Gateway([("", "stop")])
    mgr.client = mgr.client_fast = gateway

    with pytest.raises(lm.EmptyCompletionError):
        asyncio.run(mgr.generate("x"))
    # Two attempts at the same budget (hosted cap), never a doubled one.
    assert {c["max_tokens"] for c in gateway.calls} == {4096}
