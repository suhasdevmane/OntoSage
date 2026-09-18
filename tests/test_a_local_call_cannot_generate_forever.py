# -*- coding: utf-8 -*-
"""A local model call has a generation ceiling (CAVEAT-727), and the template sets each key once (CAVEAT-728).

Measured 2026-09-17 in the host Ollama log: a 136-token intent prompt generated 16,248 tokens
in 161 s, filled the 16,384-token context (`truncated = 1`) and returned EMPTY content. The
runner serves one request at a time, so the next request waited 2m46s behind it. Nothing
capped generation on the local client, while every hosted client already carried max_tokens.

The template half: `.env.example` assigned OLLAMA_NUM_CTX twice, the second time to 8192 — the
value BUG-188 was fixed to remove — and a dotenv loader keeps the last assignment.
"""

from __future__ import annotations

import collections
import importlib
from pathlib import Path

import pytest

# `from orchestrator import llm_manager` is the singleton INSTANCE the package re-exports, not
# the module; the helper lives on the module.
llm_manager = importlib.import_module("orchestrator.llm_manager")

pytestmark = pytest.mark.unit

REPO = Path(__file__).resolve().parent.parent


def test_the_local_client_is_capped_by_default(monkeypatch):
    monkeypatch.delenv("OLLAMA_NUM_PREDICT", raising=False)
    cap = llm_manager._ollama_generation_cap()
    assert cap == {"num_predict": 8192}
    # Below the context the runaway filled, or the cap would change nothing.
    assert cap["num_predict"] < 16248


def test_the_cap_is_configurable(monkeypatch):
    monkeypatch.setenv("OLLAMA_NUM_PREDICT", "4096")
    assert llm_manager._ollama_generation_cap() == {"num_predict": 4096}


@pytest.mark.parametrize("value", ["0", "-1"])
def test_zero_or_negative_means_unlimited(monkeypatch, value):
    monkeypatch.setenv("OLLAMA_NUM_PREDICT", value)
    assert llm_manager._ollama_generation_cap() == {}


def test_a_malformed_value_keeps_the_cap(monkeypatch):
    """A typo must not silently remove the ceiling."""
    monkeypatch.setenv("OLLAMA_NUM_PREDICT", "eight thousand")
    assert llm_manager._ollama_generation_cap() == {"num_predict": 8192}


def test_the_client_is_built_with_the_cap():
    """The capability with no invoker is this codebase's recurring defect."""
    import inspect

    src = inspect.getsource(llm_manager.LLMManager._initialize_ollama)
    assert "**_ollama_generation_cap()" in src


def test_the_env_template_assigns_each_key_once():
    keys = []
    for line in (REPO / ".env.example").read_text(encoding="utf-8").splitlines():
        s = line.strip()
        if s and not s.startswith("#") and "=" in s:
            keys.append(s.split("=", 1)[0].strip())
    dupes = sorted(k for k, n in collections.Counter(keys).items() if n > 1)
    assert not dupes, f"assigned more than once (the last one silently wins): {dupes}"


def test_the_template_documents_the_cap_and_the_fixed_context():
    text = (REPO / ".env.example").read_text(encoding="utf-8")
    assert "\nOLLAMA_NUM_PREDICT=8192" in text
    assert "\nOLLAMA_NUM_CTX=16384" in text
    assert "\nOLLAMA_NUM_CTX=8192" not in text
