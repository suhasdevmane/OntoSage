"""Phase 7A — typed PipelineContext over intermediate_results.

Verifies:
  1. Model accepts all 49 documented dict keys.
  2. Round-trip dict → PipelineContext → dict preserves data.
  3. Underscore-prefixed aliases (_semantic_route, _user_lang, _saved_query_results) work.
  4. Unknown keys round-trip (forward compatibility).
  5. ConversationState.pipeline_ctx returns a typed snapshot.
  6. apply_to_state writes back without clobbering unrelated keys.
"""

from __future__ import annotations

from typing import Any, Dict

import pytest

from shared.pipeline_context import PipelineContext


# ─────────────────────────────────────────────────────────────────────────────
# Field coverage
# ─────────────────────────────────────────────────────────────────────────────


def test_model_accepts_all_documented_keys():
    """Each of the 49 known intermediate_results keys is accepted."""
    sample = {
        # Intent
        "intent": "analytics",
        "llm_intent": "analytics",
        "entities": ["zone 5.28"],
        "explanation": "Statistical query.",
        "required_analytics": ["avg", "max"],
        "analytics_required": True,
        # Time range
        "start_date": "2026-05-01",
        "end_date": "2026-05-29",
        # Results
        "sparql_result": {"success": True},
        "sql_result": {"success": True},
        "analytics_result": {"avg": 22.5},
        "anomaly_result": {"count": 0},
        "capability_result": {"response": "..."},
        "control_result": {"ok": True},
        "floor_plan_result": "## Floor 3",
        "floor_plan_structured": {"floor": 3},
        "maintenance_result": {"ticket_id": "MT-1"},
        "planner_result": {"steps": []},
        "report_result": {"text": "..."},
        "viz_result": {"path": "/tmp/plot.png"},
        "document_result": {"url": "..."},
        "export_result": {"rows": 100},
        # Multi-intent
        "multi_intent_plan": {"sub_intents": []},
        "capability_matches": [],
        # Semantic routing
        "semantic_route_intent": "capability",
        "semantic_route_score": 0.85,
        # Hints
        "floor_context_hint": {"floor": 3},
        "sensor_metadata": {"uuid1": "label"},
        "dialogue_response": "Hello",
        "persona_domain_hint": "THERMAL",
        "pending_clarification_type": None,
        # Compliance / recommend
        "compliance_context": "ASHRAE 55",
        "recommendation_domain": "hvac",
        "report_type": "summary",
        "export_format": "csv",
        # Memory
        "memory_context": "...",
        "user_context": {"prior": "yes"},
        "g1_taxonomy": {"domain_l1": "ENERGY"},
        "verification": {"grounded": True},
        # Self-correction
        "correction_log": [],
        "correction_trace": [],
        # Cache / session
        "cache_hit": True,
        "fresh_session": False,
        # Error
        "error": None,
        # Private (underscore aliases)
        "_saved_query_results": {"data": []},
        "_semantic_route": {"score": 0.5},
        "_user_lang": "en",
        # Misc
        "llm_sparql_query": "",
        "use_existing_query_results": False,
    }
    ctx = PipelineContext.from_dict(sample)
    # Smoke-check a handful from each category
    assert ctx.intent == "analytics"
    assert ctx.entities == ["zone 5.28"]
    assert ctx.sparql_result == {"success": True}
    assert ctx.semantic_route_score == 0.85
    assert ctx.compliance_context == "ASHRAE 55"
    assert ctx.cache_hit is True
    # Underscore aliases populated the right fields
    assert ctx.saved_query_results == {"data": []}
    assert ctx.semantic_route == {"score": 0.5}
    assert ctx.user_lang == "en"


# ─────────────────────────────────────────────────────────────────────────────
# Round-trip
# ─────────────────────────────────────────────────────────────────────────────


def test_roundtrip_preserves_underscore_aliases():
    """`_semantic_route` etc. survive dict → model → dict."""
    src = {"_semantic_route": {"score": 0.7, "source": "semantic"}, "intent": "x"}
    out = PipelineContext.from_dict(src).to_dict()
    assert "_semantic_route" in out
    assert out["_semantic_route"]["score"] == 0.7
    assert out["intent"] == "x"


def test_unknown_keys_are_preserved():
    """Pydantic `extra='allow'` lets unknown keys round-trip safely."""
    src = {"intent": "analytics", "future_field_added_later": "hello"}
    ctx = PipelineContext.from_dict(src)
    out = ctx.to_dict()
    assert out["future_field_added_later"] == "hello"


def test_permissive_types_accept_unexpected_shapes():
    """Phase 7B regression: real producers write whatever shape they want.

    The PipelineContext is a READ-time view + documentation.  It must NOT
    reject legitimate payloads even if the runtime shape differs from the
    field's docstring hint.
    """
    # llm_intent is actually a dict (the full LLM response object) — must accept
    src = {
        "llm_intent": {
            "intent": "analytics",
            "entities": ["zone 5.28"],
            "complexity": "SIMPLE",
            "explanation": "...",
        },
        # correction_log can be a dict (from log.to_dict()) — must accept
        "correction_log": {"attempts": 1, "succeeded": True},
        # capability_matches is a list of CapabilityMatch objects — must accept
        "capability_matches": [object(), object()],
        # cache_hit is boolean today but could change — must accept
        "cache_hit": True,
    }
    ctx = PipelineContext.from_dict(src)
    assert isinstance(ctx.llm_intent, dict)
    assert ctx.llm_intent["intent"] == "analytics"
    assert ctx.correction_log == {"attempts": 1, "succeeded": True}
    assert len(ctx.capability_matches) == 2


# ─────────────────────────────────────────────────────────────────────────────
# from_state / apply_to_state
# ─────────────────────────────────────────────────────────────────────────────


class _FakeState:
    """Lightweight stand-in for ConversationState used only in unit tests."""

    def __init__(self, data: Dict[str, Any] | None = None):
        self.intermediate_results = data or {}


def test_from_state_reads_intermediate_results():
    state = _FakeState({"intent": "report", "report_type": "weekly"})
    ctx = PipelineContext.from_state(state)
    assert ctx.intent == "report"
    assert ctx.report_type == "weekly"


def test_apply_to_state_writes_back_known_fields():
    state = _FakeState({"intent": "analytics"})
    ctx = PipelineContext.from_state(state)
    ctx.sparql_result = {"success": True, "rows": 5}
    ctx.apply_to_state(state)
    assert state.intermediate_results["sparql_result"]["rows"] == 5
    # Original key preserved
    assert state.intermediate_results["intent"] == "analytics"


def test_apply_to_state_does_not_clobber_unrelated_keys():
    state = _FakeState({"unrelated_legacy_key": {"keep": "me"}})
    ctx = PipelineContext.from_state(state)
    ctx.intent = "discovery"
    ctx.apply_to_state(state)
    assert state.intermediate_results["intent"] == "discovery"
    # Unknown keys survive
    assert state.intermediate_results["unrelated_legacy_key"] == {"keep": "me"}


def test_conversation_state_has_pipeline_ctx_property():
    """Phase 7A integration: ConversationState exposes the typed snapshot."""
    from shared.models import ConversationState, Message

    state = ConversationState(
        conversation_id="x",
        user_id="t",
        user_message="hi",
        messages=[Message(role="user", content="hi")],
        intermediate_results={"intent": "greeting", "entities": ["bob"]},
    )
    ctx = state.pipeline_ctx
    assert isinstance(ctx, PipelineContext)
    assert ctx.intent == "greeting"
    assert ctx.entities == ["bob"]


def test_pipeline_ctx_is_a_snapshot_not_a_view():
    """Mutating the snapshot does NOT change the underlying dict directly."""
    from shared.models import ConversationState, Message

    state = ConversationState(
        conversation_id="x",
        user_id="t",
        user_message="hi",
        messages=[Message(role="user", content="hi")],
        intermediate_results={"intent": "greeting"},
    )
    ctx = state.pipeline_ctx
    ctx.intent = "MUTATED"
    # The dict is UNCHANGED until apply_to_state is called.
    assert state.intermediate_results["intent"] == "greeting"
    # Now sync.
    ctx.apply_to_state(state)
    assert state.intermediate_results["intent"] == "MUTATED"
