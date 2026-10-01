# -*- coding: utf-8 -*-
"""W6-01 / BUG-889 — the intent cache is keyed on the DECISION's inputs, not on the prompt.

Measured over a full 51-question gate run on 2026-09-29: the intent cache hit **0 times against
38 classification calls**. The key was `hash(prompt)`, and the prompt is built from the question
PLUS the retrieved ontology context, the conversation history and the memory context. All three
vary per conversation, so the same question in a new chat produced a different prompt, a
different hash, a miss, and a fresh LLM call free to classify differently.

That is why W6-01 exists: *"Six of fifty answers differed between two identical runs. Until this
closes, no single-run pass rate is trustworthy to better than about ten points."*

Keying on the question alone is only sound because `rewrite_to_standalone` runs FIRST and
replaces `messages[-1].content` with a self-contained query (`_orchestrator.py` :1951, then
`detect_intent` at :1996). These tests pin that reasoning, because if the rewrite ever moved
after classification the cache would start serving one conversation's answer to another's
follow-up.
"""

from __future__ import annotations

import pytest

from orchestrator.agents.dialogue_agent import decision_cache_key as key

pytestmark = pytest.mark.unit

Q = "What is the CO2 level in room 5.01 right now?"


# ── the same question must reach the same decision ───────────────────────────────────


@pytest.mark.parametrize(
    "variant",
    [
        Q,
        Q.lower(),
        Q.upper(),
        "  What is the CO2 level in room 5.01 right now?  ",
        "What  is   the CO2 level in room 5.01 right now?",
    ],
)
def test_case_and_whitespace_do_not_split_the_cache(variant):
    assert key(variant, "bldg1", "general") == key(Q, "bldg1", "general")


@pytest.mark.parametrize(
    "pair",
    [
        ("what's the CO2 in 5.01?", "what’s the CO2 in 5.01?"),  # curly apostrophe
        ("the air-pressure sensor", "the air‑pressure sensor"),  # non-breaking hyphen
        ("room 5.01 now", "room 5.01 now"),  # non-breaking space
    ],
)
def test_typographic_forms_fold_to_one_key(pair):
    """A browser sends a curly apostrophe where a CLI sends a straight one.

    BUG-864 was that difference alone changing a routing decision, and lesson #130 is that it
    bit twice. Folding here means both spellings reach ONE cached decision rather than two LLM
    calls free to disagree.
    """
    a, b = pair
    assert key(a, "bldg1", "general") == key(b, "bldg1", "general")


# ── and the things that legitimately change a decision must split it ─────────────────


def test_a_different_building_is_a_different_decision():
    """Intents are per-building — bldg1 carries a `lab_booking` overlay another building lacks."""
    assert key(Q, "bldg1", "general") != key(Q, "bldg2", "general")


def test_a_different_persona_is_a_different_decision():
    """Core contract #5: personas bias classification and framing by design."""
    assert key(Q, "bldg1", "general") != key(Q, "bldg1", "facility_manager")


def test_a_different_question_is_a_different_decision():
    assert key(Q, "bldg1", "general") != key(
        "Which floor is the warmest right now?", "bldg1", "general"
    )


def test_changing_the_routing_contract_retires_every_cached_decision(monkeypatch):
    """A cached value is stored AFTER apply_contract has run over it.

    So a cached decision embeds the contract that produced it. Without the contract in the key,
    changing a rule leaves every cached decision stale for the whole TTL — silently.
    """
    import orchestrator.agents.dialogue_agent as da

    before = key(Q, "bldg1", "general")
    monkeypatch.setattr(da, "_CONTRACT_FP", "deadbeef00")
    after = key(Q, "bldg1", "general")
    assert before != after


# ── what must NOT be in the key, which is the entire point ───────────────────────────


def test_the_key_does_not_depend_on_conversation_state():
    """The three fields that varied are gone: ontology context, history, memory.

    This is asserted on the SIGNATURE rather than by constructing prompts, because the defect
    was that those values reached the key at all.
    """
    import inspect

    sig = inspect.signature(key)
    assert list(sig.parameters) == ["query", "building_id", "persona"]
    for forbidden in ("history", "memory", "context", "prompt"):
        assert forbidden not in sig.parameters, forbidden


def test_the_cache_read_uses_this_key_and_not_the_prompt_hash():
    """Guard against the old key creeping back in a merge."""
    import inspect

    import orchestrator.agents.dialogue_agent as da

    src = inspect.getsource(da.DialogueAgent.detect_intent)
    assert "decision_cache_key(" in src
    assert 'f"cache:intent:{prompt_hash}"' not in src


def test_the_rewrite_still_runs_before_classification():
    """The load-bearing assumption. If this ordering flips, keying on the question is unsafe.

    `rewrite_to_standalone` must replace `messages[-1].content` BEFORE `detect_intent` reads it,
    or a follow-up like "and humidity there?" would be cached as itself and served to every
    other conversation that ever asks those three words.
    """
    from pathlib import Path

    src = Path("orchestrator/workflow/_orchestrator.py").read_text(encoding="utf-8")
    rewrite_at = src.index("rewrite_to_standalone(state)")
    classify_at = src.index("dialogue_agent.detect_intent(state)")
    assert rewrite_at < classify_at, "the co-reference rewrite must precede classification"
