# -*- coding: utf-8 -*-
"""Pinning the compile so a repeat of a question replays its own plan (CAVEAT-327).

V6-T49's acceptance criterion was "deliberative fingerprints identical across models".
Measured on three local arms: 2/8 identical across models -- against a NOISE FLOOR, the
same model run twice, of 3/8. Cross-model agreement sat at or below run-to-run variance,
so none of the observed differences could be attributed to the model at all. The claim
was not so much false as unmeasurable.

BUG-184 had already established that ``plan_fingerprint`` is the right anchor and that
the harness compares it; the wobble is UPSTREAM, in what the LLM emits for one question
at temperature 0. Batched GPU inference returns different text for a byte-identical
prompt, and while the closed-vocabulary parser absorbs most of that, it does not absorb
all of it.

So the compile is cached, and the RAW TEXT is what is stored: everything after the LLM
call is deterministic validation against a closed vocabulary, so replaying the text
reproduces the plan exactly, and a stored plan can never drift out of step with the
parser that produced it.

**The key includes the provider and the model, and that is the whole point.** Keyed on
the question alone, this cache would hand model B the plan model A compiled, and the
multi-model invariance benchmark would report a perfect score for the very property it
exists to measure. A cache that fabricates the result is worse than the wobble it fixes.
"""

import asyncio

import pytest

from orchestrator.services.deliberation import compiler as C
from orchestrator.services.deliberation.coverage_audit import ModalitySpec

pytestmark = pytest.mark.unit


def _mods(*names):
    return [ModalitySpec(name=n, brick_classes=[]) for n in names]


class _Redis:
    """An in-memory stand-in with the two methods the compiler uses."""

    def __init__(self):
        self.store = {}

    async def get_cache(self, key):
        return self.store.get(key)

    async def set_cache(self, key, value, ttl=0):
        self.store[key] = value
        return True


_RAW = (
    '{"decision": "superlative", "constraints": [{"phrase": "quietest", '
    '"modality": "noise", "direction": "minimize", "hardness": "soft", '
    '"threshold": null}], "spatial": [], "time": {"basis": "now", '
    '"horizon_hours": null, "window_hours": null, "phrase": ""}, '
    '"time_phrase_unclear": "", "unmapped": []}'
)


# -- the key covers everything that can change a plan ------------------------
def test_the_same_question_hits_the_same_key():
    m = _mods("noise", "temperature")
    q = "Which room is quietest?"
    assert C._compile_cache_key(q, m) == C._compile_cache_key(q, m)


@pytest.mark.parametrize(
    "a,b",
    [
        ("Which room is quietest?", "which room is quietest"),
        ("Which  room   is quietest?", "Which room is quietest?"),
        ("Which room is quietest!", "Which room is quietest"),
    ],
)
def test_incidental_differences_in_asking_share_a_key(a, b):
    """Whitespace, case and trailing punctuation are not different questions."""
    m = _mods("noise")
    assert C._compile_cache_key(a, m) == C._compile_cache_key(b, m)


def test_a_different_question_gets_a_different_key():
    m = _mods("noise")
    assert C._compile_cache_key("Which room is quietest?", m) != C._compile_cache_key(
        "Which room is warmest?", m
    )


def test_a_building_with_different_modalities_gets_a_different_key():
    """A building that gains a modality can legitimately compile the same words
    differently, so it must not inherit another building's plan."""
    q = "Which room is most comfortable?"
    assert C._compile_cache_key(q, _mods("noise")) != C._compile_cache_key(q, _mods("noise", "co2"))


def test_the_modality_order_does_not_change_the_key():
    q = "Which room is most comfortable?"
    assert C._compile_cache_key(q, _mods("noise", "co2")) == C._compile_cache_key(
        q, _mods("co2", "noise")
    )


def test_editing_the_prompt_invalidates_every_entry():
    """Editing the prompt is editing the compiler; stale plans must not survive it."""
    m = _mods("noise")
    q = "Which room is quietest?"
    before = C._compile_cache_key(q, m)
    original = C._PROMPT
    try:
        C._PROMPT = original + "\nAn extra instruction.\n"
        after = C._compile_cache_key(q, m)
    finally:
        C._PROMPT = original
    assert before != after


def test_the_model_is_in_the_key(monkeypatch):
    """THE trap. Keyed on the question alone, the multi-model benchmark would compare
    one model's cached plan against itself and report perfect invariance -- a fabricated
    answer to the exact question it was built to ask."""
    from shared.config import settings

    m = _mods("noise")
    q = "Which room is quietest?"
    monkeypatch.setattr(settings, "MODEL_PROVIDER", "local", raising=False)
    monkeypatch.setattr(settings, "OLLAMA_MODEL", "gpt-oss:20b", raising=False)
    a = C._compile_cache_key(q, m)
    monkeypatch.setattr(settings, "OLLAMA_MODEL", "gemma4:31b", raising=False)
    b = C._compile_cache_key(q, m)
    assert a != b, "two models share a compile cache entry"


def test_the_provider_is_in_the_key(monkeypatch):
    from shared.config import settings

    m = _mods("noise")
    q = "Which room is quietest?"
    monkeypatch.setattr(settings, "MODEL_PROVIDER", "local", raising=False)
    a = C._compile_cache_key(q, m)
    monkeypatch.setattr(settings, "MODEL_PROVIDER", "openai", raising=False)
    b = C._compile_cache_key(q, m)
    assert a != b


# -- replaying a cached compile reproduces the plan exactly ------------------
def test_a_replayed_compile_gives_the_identical_fingerprint():
    """The property CAVEAT-327 needs: a repeat of a question yields the same plan."""
    a = C._parse_compiled(_RAW, "Which room is quietest?", {"noise"})
    b = C._parse_compiled(_RAW, "Which room is quietest?", {"noise"})
    assert a.plan_fingerprint() == b.plan_fingerprint()


def test_the_second_ask_replays_instead_of_recompiling(monkeypatch):
    m = _mods("noise")
    calls = []

    async def _llm(prompt):
        calls.append(prompt)
        return _RAW

    import orchestrator.redis_manager as rm

    monkeypatch.setattr(rm, "redis_manager", _Redis(), raising=False)

    first = asyncio.run(C.compile_query("Which room is quietest?", m, _llm))
    second = asyncio.run(C.compile_query("Which room is quietest?", m, _llm))

    assert len(calls) == 1, "the second compile called the LLM again"
    assert first.plan_fingerprint() == second.plan_fingerprint()


def test_use_cache_false_forces_a_fresh_compile(monkeypatch):
    """The benchmark MUST be able to bypass it, or it measures this cache."""
    m = _mods("noise")
    calls = []

    async def _llm(prompt):
        calls.append(prompt)
        return _RAW

    import orchestrator.redis_manager as rm

    monkeypatch.setattr(rm, "redis_manager", _Redis(), raising=False)

    asyncio.run(C.compile_query("Which room is quietest?", m, _llm, use_cache=False))
    asyncio.run(C.compile_query("Which room is quietest?", m, _llm, use_cache=False))
    assert len(calls) == 2


def test_a_dead_redis_does_not_break_compilation(monkeypatch):
    """The cache is an optimisation. If it fails, the building must still answer."""
    m = _mods("noise")

    async def _llm(prompt):
        return _RAW

    class _Broken:
        async def get_cache(self, key):
            raise RuntimeError("redis down")

        async def set_cache(self, key, value, ttl=0):
            raise RuntimeError("redis down")

    import orchestrator.redis_manager as rm

    monkeypatch.setattr(rm, "redis_manager", _Broken(), raising=False)
    out = asyncio.run(C.compile_query("Which room is quietest?", m, _llm))
    assert out.plan_fingerprint()


def test_a_failed_compile_is_not_cached(monkeypatch):
    """Caching an LLM error would make one transient failure permanent for a day."""
    m = _mods("noise")

    async def _boom(prompt):
        raise RuntimeError("provider down")

    fake = _Redis()
    import orchestrator.redis_manager as rm

    monkeypatch.setattr(rm, "redis_manager", fake, raising=False)

    out = asyncio.run(C.compile_query("Which room is quietest?", m, _boom))
    assert out.signals, "an LLM failure should surface as a signal"
    assert not fake.store, "a failed compile was written to the cache"
