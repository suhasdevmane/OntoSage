# -*- coding: utf-8 -*-
"""One LLM call ran 3,239 s inside a 180 s `asyncio.wait_for` (BUG-1191).

`LLM_TIMEOUT_S=180` was present in the container environment and resolved to 180.0 in the
running process; `llm_manager.generate` wrapped the call in `asyncio.wait_for`; and no
TimeoutError, retry or degraded marker was ever logged. The 420 s `WORKFLOW_TIMEOUT_S`
wrapped around the same turn was equally silent. Two independent deadlines written in the
same idiom do not both have the same bug -- the loop was not running its timer callbacks,
on a process later measured at 40 GiB (BUG-1194).

What is asserted here is the SECOND deadline, set somewhere else: the HTTP client's own.
MEASURED on the installed packages, because the reason it was missing is that nobody had
looked -- `ollama` 0.6.3 defaults `timeout` to **None** and hands it straight to httpx, so
out of the box an Ollama request has no transport deadline at all.

It is not claimed to be a complete fix. httpx implements its timeouts with anyio, which on
the asyncio backend is still a loop timer. This layer catches a silent provider on a
healthy loop -- the shape actually observed, where the connection was open and nothing
arrived for 54 minutes -- and does not survive a fully starved loop. The container memory
ceiling is what covers that.
"""

from __future__ import annotations

import importlib

import pytest

pytestmark = pytest.mark.unit


def _llm_manager(monkeypatch, **overrides):
    """The llm_manager MODULE with its module-level constants patched in place.

    Two traps avoided on purpose:

    * `import orchestrator.llm_manager as lm` does NOT give the module — the
      `orchestrator` package binds the name `llm_manager` to an LLMManager INSTANCE, so
      the plain import silently hands back an object with no module attributes at all.
      `importlib.import_module` returns the module regardless.
    * No `importlib.reload`. CAVEAT-1060: a reload builds a NEW module object while every
      importer keeps the old one, so a test that reloads and patches is patching something
      the product no longer reads. `LLM_TIMEOUT_S` is read from the environment ONCE at
      import, so patching the constant is both simpler and the thing the code actually
      uses.
    """
    lm = importlib.import_module("orchestrator.llm_manager")
    for key, value in overrides.items():
        monkeypatch.setattr(lm, key, value, raising=True)
    monkeypatch.delenv("LLM_TRANSPORT_TIMEOUT_S", raising=False)
    return lm


def test_the_transport_deadline_outlasts_the_asyncio_one(monkeypatch):
    """Under a healthy loop `wait_for` must still win, so no existing path changes."""
    lm = _llm_manager(monkeypatch, LLM_TIMEOUT_S=180.0)
    assert lm._transport_timeout_s() > lm.LLM_TIMEOUT_S
    assert lm._transport_timeout_s() == pytest.approx(285.0)


def test_the_transport_deadline_is_derived_from_llm_timeout(monkeypatch):
    lm = _llm_manager(monkeypatch, LLM_TIMEOUT_S=60.0)
    assert lm._transport_timeout_s() == pytest.approx(105.0)


def test_an_explicit_override_is_honoured(monkeypatch):
    lm = _llm_manager(monkeypatch, LLM_TIMEOUT_S=180.0)
    monkeypatch.setenv("LLM_TRANSPORT_TIMEOUT_S", "42")
    assert lm._transport_timeout_s() == pytest.approx(42.0)


def test_a_nonsense_override_falls_back_rather_than_raising(monkeypatch, caplog):
    lm = _llm_manager(monkeypatch, LLM_TIMEOUT_S=180.0)
    monkeypatch.setenv("LLM_TRANSPORT_TIMEOUT_S", "soon")
    with caplog.at_level("WARNING"):
        assert lm._transport_timeout_s() == pytest.approx(285.0)
    assert "not a number" in caplog.text


def test_the_client_kwargs_carry_a_short_connect_and_a_long_read(monkeypatch):
    """A refused model server must fail fast; the long budget belongs to the read."""
    lm = _llm_manager(monkeypatch, LLM_TIMEOUT_S=180.0)
    kwargs = lm._ollama_client_kwargs()
    assert set(kwargs) == {"timeout"}
    timeout = kwargs["timeout"]
    assert getattr(timeout, "read", None) == pytest.approx(285.0)
    assert getattr(timeout, "connect", None) == pytest.approx(10.0)


def test_the_installed_ollama_client_really_defaults_to_no_timeout():
    """The premise of the whole fix, checked rather than believed.

    If a future `ollama` release starts defaulting to a finite timeout this test fails and
    the comment above it should be corrected. That is the point of asserting it.
    """
    import inspect

    mod = importlib.import_module("ollama._client")
    sig = inspect.signature(mod.BaseClient.__init__)
    assert sig.parameters["timeout"].default is None, (
        "ollama's BaseClient no longer defaults timeout to None — re-read the "
        "BUG-1191 reasoning before trusting it"
    )


def test_langchain_ollama_still_exposes_client_kwargs():
    """The route by which the timeout reaches httpx. Losing it silently is the risk."""
    from langchain_ollama import OllamaLLM

    assert "client_kwargs" in OllamaLLM.model_fields, (
        "OllamaLLM has no client_kwargs field, so the local client is running with NO "
        "transport timeout — BUG-1191 is unprotected"
    )


@pytest.mark.parametrize(
    "name", ["TimeoutException", "ConnectTimeout", "ReadTimeout", "WriteTimeout", "PoolTimeout"]
)
def test_a_transport_timeout_with_an_empty_message_is_still_a_timeout(name):
    """`str(httpx.ReadTimeout())` is frequently the EMPTY STRING.

    Every classifier in llm_manager works on `str(error).lower()`, so before this a
    transport timeout would have been bucketed as "other" and treated as non-retryable --
    the failure mode the transport deadline exists to fix, mislabelled by the code that
    handles it.
    """
    import httpx

    from orchestrator.llm_manager import LLMManager, classify_llm_error

    err = getattr(httpx, name)("")
    assert str(err) == ""
    assert classify_llm_error(err) == "timeout"
    assert LLMManager._is_retryable(object.__new__(LLMManager), err) is True


def test_a_slow_call_threshold_exists_and_is_below_the_timeout(monkeypatch):
    """A call that overruns the bound must be visible before it overruns it."""
    lm = _llm_manager(monkeypatch, LLM_TIMEOUT_S=180.0)
    assert 0 < lm.LLM_SLOW_CALL_WARN_S < lm.LLM_TIMEOUT_S


def test_generate_logs_the_elapsed_time_of_a_slow_call(monkeypatch, caplog):
    """The number that had to be recovered by subtracting two log timestamps by hand."""
    import asyncio

    lm = _llm_manager(monkeypatch, LLM_TIMEOUT_S=180.0, LLM_SLOW_CALL_WARN_S=0.0)
    mgr = object.__new__(lm.LLMManager)
    mgr.provider = "ollama"
    mgr.client = object()
    mgr.client_fast = mgr.client
    mgr.last_request_time = 0.0
    mgr.last_request_time_fast = 0.0
    mgr._breaker = lm.circuit_breaker_for("llm-test-elapsed", failure_threshold=5)

    async def fake_once(*_a, **_k):
        return "an answer"

    monkeypatch.setattr(mgr, "_generate_once", fake_once)
    with caplog.at_level("WARNING"):
        out = asyncio.run(mgr.generate("how warm is it?"))
    assert out == "an answer"
    assert "slow call" in caplog.text, caplog.text
    assert "completion 9 chars" in caplog.text
