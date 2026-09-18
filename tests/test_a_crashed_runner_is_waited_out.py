"""A crashed local model runner is waited out, not raced (CAVEAT-619).

The local runner died with a CUDA fault on a 155-token prompt, Ollama respawned a fresh
llama-server on a new port, and every one of the three retries fired inside the 5-14s reload
window — so a register answer that the model CAN write came back as "I found 12 records but
couldn't summarise them". The backoff now recognises a dead runner and waits for it.
"""

import pytest

from orchestrator.llm_manager import (
    LLM_RUNNER_RESTART_WAIT_S,
    _looks_like_a_dead_local_runner,
)

pytestmark = pytest.mark.unit


@pytest.mark.parametrize(
    "message",
    [
        # The exact text the provider returned when the runner died, port and all.
        'health resp: Get "http://127.0.0.1:53122/health": dial tcp 127.0.0.1:53122: '
        "connect: connection refused",
        "Error: llama runner process has terminated: exit status 0xc0000409",
        "model runner has unexpectedly stopped",
        # Windows words the same refusal differently, and the string must still match.
        "No connection could be made because the target machine actively refused it",
    ],
)
def test_a_refused_loopback_port_is_read_as_a_dead_runner(message):
    assert _looks_like_a_dead_local_runner(RuntimeError(message)) is True


@pytest.mark.parametrize(
    "message",
    [
        "Read timed out after 60s",
        "rate limit exceeded (429)",
        "the model returned an empty completion",
        "503 service unavailable",
    ],
)
def test_a_slow_or_busy_provider_is_not_a_dead_runner(message):
    """A live-but-unhappy server must keep the short backoff: waiting 10s helps nothing."""
    assert _looks_like_a_dead_local_runner(RuntimeError(message)) is False


def test_no_error_is_not_a_dead_runner():
    assert _looks_like_a_dead_local_runner(None) is False


def test_the_wait_outlasts_a_measured_runner_reload():
    """The reload took 5.0-14.0s here; a wait shorter than that retries into the gap."""
    assert LLM_RUNNER_RESTART_WAIT_S >= 5.0


def test_the_backoff_actually_consults_the_predicate():
    """The predicate is worthless if the retry loop never calls it — that was BUG-618's shape."""
    import inspect

    from orchestrator.llm_manager import LLMManager

    source = inspect.getsource(LLMManager.generate)
    assert "_looks_like_a_dead_local_runner" in source
    assert "LLM_RUNNER_RESTART_WAIT_S" in source


def _llm_module():
    """Import the MODULE, not the class the package re-exports under the same name."""
    import importlib.util
    import sys

    spec = importlib.util.spec_from_file_location("_lm_mod", "orchestrator/llm_manager.py")
    mod = importlib.util.module_from_spec(spec)
    sys.modules["_lm_mod"] = mod
    spec.loader.exec_module(mod)
    return mod


@pytest.mark.parametrize(
    "prompt",
    [
        "Analyse this.\nUser Query:\n\nData: ...",
        "Analyse this.\nUser Query:   \nData: ...",
        "Question:\n\nRows: ...",
    ],
)
def test_a_prompt_that_lost_its_question_is_flagged(prompt):
    """"Is it too warm anywhere right now?" came back as "No question was provided." after 116
    seconds — the model's own words, because its prompt carried an empty question slot. The
    lane logs the query it RECEIVED, not the one it rendered, so nothing in any log said so
    (BUG-630)."""
    assert _llm_module()._EMPTY_QUESTION_SLOT_RE.search(prompt)


@pytest.mark.parametrize(
    "prompt",
    [
        "Analyse this.\nUser Query: what is the CO2 in room 5.01?\n\nData: ...",
        "Summarise.\nQuestion: which floor is warmest?\n",
        "No question label here at all, just instructions.",
    ],
)
def test_a_prompt_that_carries_its_question_is_left_alone(prompt):
    assert not _llm_module()._EMPTY_QUESTION_SLOT_RE.search(prompt)


def test_the_check_runs_on_every_generate_call():
    """One place, because seven builders render a question and any of them can drop it."""
    import inspect

    mod = _llm_module()
    source = inspect.getsource(mod.LLMManager.generate)
    assert "_EMPTY_QUESTION_SLOT_RE" in source


def test_the_check_only_warns():
    """A caller with a genuine reason to ask without a question must keep working."""
    import inspect

    mod = _llm_module()
    source = inspect.getsource(mod.LLMManager.generate)
    block = source[source.index("_EMPTY_QUESTION_SLOT_RE") : source.index("_EMPTY_QUESTION_SLOT_RE") + 600]
    assert "logger.warning" in block
    assert "raise" not in block
