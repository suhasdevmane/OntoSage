# -*- coding: utf-8 -*-
"""An empty completion is a failure, not an answer.

A local model that spends its budget on reasoning, or whose prompt crowds out
the context window, returns "" with HTTP 200. Treating that as success meant the
retry loop never engaged and the caller fell through to a generic answer — which,
for a question about a building, is a fabricated one.
"""

import importlib

import pytest

from orchestrator.llm_manager import EmptyCompletionError, LLMManager

# The package re-exports the singleton as `orchestrator.llm_manager`, shadowing
# the module of the same name — so reach the module explicitly to patch it.
_llm_mod = importlib.import_module("orchestrator.llm_manager")

pytestmark = pytest.mark.unit


def _manager(monkeypatch, responses):
    """An LLMManager whose single generation call yields `responses` in order."""
    mgr = LLMManager.__new__(LLMManager)
    mgr.provider = "ollama"
    mgr.client = mgr.client_fast = object()
    mgr.last_request_time = mgr.last_request_time_fast = 0.0

    class _Breaker:
        successes = 0
        failures = 0

        def allow_request(self):
            return True

        def record_success(self):
            _Breaker.successes += 1

        def record_failure(self):
            _Breaker.failures += 1

    mgr._breaker = _Breaker()
    calls = {"n": 0}

    async def _once(*_a, **_kw):
        i = calls["n"]
        calls["n"] += 1
        return responses[min(i, len(responses) - 1)]

    monkeypatch.setattr(mgr, "_generate_once", _once)
    return mgr, calls, _Breaker


def test_empty_completion_is_retryable():
    assert LLMManager._is_retryable(None, EmptyCompletionError("empty")) is True


@pytest.mark.parametrize("blank", ["", "   ", "\n\t "])
async def test_blank_completion_retries_then_succeeds(monkeypatch, blank):
    mgr, calls, breaker = _manager(monkeypatch, [blank, '{"intent":"sensor_data"}'])
    monkeypatch.setattr(_llm_mod, "LLM_BACKOFF_BASE_S", 0.0)

    out = await mgr.generate("classify this")

    assert out == '{"intent":"sensor_data"}'
    assert calls["n"] == 2, "a blank completion must trigger another attempt"


async def test_persistently_empty_raises_rather_than_returning_blank(monkeypatch):
    mgr, calls, _ = _manager(monkeypatch, [""])
    monkeypatch.setattr(_llm_mod, "LLM_BACKOFF_BASE_S", 0.0)

    with pytest.raises(EmptyCompletionError):
        await mgr.generate("classify this")

    assert calls["n"] > 1, "should exhaust retries before giving up"


async def test_normal_completion_does_not_retry(monkeypatch):
    mgr, calls, _ = _manager(monkeypatch, ["a real answer"])
    assert await mgr.generate("hello") == "a real answer"
    assert calls["n"] == 1
