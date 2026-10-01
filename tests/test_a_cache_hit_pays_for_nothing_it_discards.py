# -*- coding: utf-8 -*-
"""BUG-921 — the classifier cache lookup must sit where its KEY is complete.

BUG-889 fixed a cache that hit 0 times in 38 calls, by keying it on the decision's real
inputs — the question, the building, the persona — instead of on a hash of the whole prompt.
It did not change WHERE the lookup sits, and W6-02 then measured what that costs.

`detect_intent` ran, in order: a GraphDB RAG fetch, a conversation-summarisation LLM call,
message pruning, an 18k-character prompt build — and only then computed a key that depends on
NONE of them. Measured 2026-09-29 on "Which teaching sessions are scheduled in Room 1.06?",
which hit the cache in all four rounds:

    dialogue stage   9.5 / 10.4 / 8.8 / 10.6 s   against an 11.16 s wall median
    of which the RAG fetch alone                 4.27 s  (862 triples retrieved, 30 kept)

Every hit paid full price for work it discarded. Making the cache WORK is what made this
visible: the metric that improved ("hit rate") is not the one anyone cares about ("time").

THE ONE SIDE EFFECT. The skipped block also assigns `state.summary`, which
`_orchestrator.py` reads for its own history block — so this was not a free move, and the
tests below pin both that the move happened and that the consequence was faced rather than
discovered later.
"""

from __future__ import annotations

import inspect

import pytest

from orchestrator.agents.dialogue_agent import DialogueAgent, decision_cache_key

pytestmark = pytest.mark.unit


def _src() -> str:
    return inspect.getsource(DialogueAgent.detect_intent)


def _at(needle: str) -> int:
    return _src().index(needle)


# ── the ordering, which is the whole fix ─────────────────────────────────────────────


def test_the_lookup_returns_before_the_rag_fetch():
    assert _at("return cached_result") < _at("_retrieve_ontology_context(user_query")


def test_the_lookup_returns_before_the_summarisation_llm_call():
    """A second LLM call on a turn whose answer is already known."""
    assert _at("return cached_result") < _at("self.context_manager.summarize_history")


def test_the_lookup_returns_before_the_prompt_is_built():
    """The prompt measured 18,609 characters. On a hit it is built and dropped."""
    assert _at("return cached_result") < _at("prompt = self._build_intent_detection_prompt")


def test_the_persona_label_is_computed_before_the_key_that_needs_it():
    """The key's last input. The lookup can move no earlier than this and no later."""
    assert _at("_personas_list = list(getattr(state") < _at("cache_key = decision_cache_key(")


def test_there_is_exactly_one_lookup():
    """A move that leaves the old one behind is two lookups and a confusing log."""
    assert _src().count("get_cache(cache_key)") == 1


def test_the_prompt_still_receives_the_persona_label():
    """Moving the computation up must not detach it from its other consumer."""
    assert "persona=_persona_label," in _src()


# ── the key still depends only on cheap things ───────────────────────────────────────


def test_the_key_depends_on_nothing_that_was_moved_below_it():
    """If a future change makes the key depend on the RAG context or the history, the lookup
    cannot stay here — and this test is where that should be noticed."""
    sig = inspect.signature(decision_cache_key)
    assert list(sig.parameters) == ["query", "building_id", "persona"]


def test_the_key_is_stable_for_the_same_three_inputs():
    a = decision_cache_key("What is the CO2 in room 5.01?", "bldg1", "facility_manager")
    b = decision_cache_key("what is the   CO2 in Room 5.01? ", "bldg1", "facility_manager")
    assert a == b, "normalisation is what makes the hit rate real (BUG-889)"


def test_a_different_persona_is_a_different_decision():
    a = decision_cache_key("Is it too warm?", "bldg1", "facility_manager")
    b = decision_cache_key("Is it too warm?", "bldg1", "occupant")
    assert a != b


# ── the side effect that was skipped, faced explicitly ───────────────────────────────


def test_the_skipped_summary_assignment_is_documented_where_it_is_skipped():
    """`state.summary` is no longer refreshed on a cache hit. A reader of this function must
    find that out here, not by debugging a stale history block in another module."""
    src = _src()
    assert "BUG-921" in src
    assert "state.summary" in src[: _at("return cached_result")]


def test_the_other_reader_of_state_summary_still_exists():
    """The justification above names `_orchestrator.py` as the affected reader. If that
    reader ever goes away the reasoning is stale; if it gains company, the trade-off needs
    re-checking. Either way this test is the trigger to re-read it."""
    from pathlib import Path

    text = Path("orchestrator/workflow/_orchestrator.py").read_text(encoding="utf-8")
    assert "if state.summary:" in text


def test_the_summary_is_still_refreshed_on_a_miss():
    """The block was moved below the lookup, not deleted. A miss must behave exactly as before."""
    src = _src()
    assert "state.summary = await self.context_manager.summarize_history(" in src
    assert _at("state.summary = await self.context_manager.summarize_history(") > _at(
        "return cached_result"
    )
