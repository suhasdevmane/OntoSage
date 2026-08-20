"""
PipelineContext — Phase 7A typed view over `state.intermediate_results`.

The orchestrator state currently holds inter-agent data in a single
`Dict[str, Any]` (`ConversationState.intermediate_results`) with 49 distinct
keys.  This file gives that dict a typed shape so:

  * IDE autocomplete works — typing `ctx.sparql_result.` shows the fields
  * mypy / pyright catch typos at edit time
  * a key's purpose, owner, and reader are documented in one place

Phase 7A is purely ADDITIVE: every existing caller continues to use
`state.intermediate_results["key"]` and nothing breaks.  Callers that want
typed access can call `PipelineContext.from_state(state)` (read-only snapshot)
or use the cached property `state.pipeline_ctx`.

Phase 7B/7C (future sessions) will migrate callers incrementally.  After
enough have moved, the raw dict can be deprecated.

Design notes
------------
* Each field is `Optional[X]` with a default — every key in the original
  dict is implicitly optional because the agent that produces it might not
  have run yet.
* Complex nested results stay as `Dict[str, Any]` for now; future sessions
  can subdivide into typed result models if there's appetite.
* Internal keys (prefix `_`) are kept verbatim to match what existing code
  writes; they're documented as PRIVATE so callers know not to depend on
  them across versions.
"""

from __future__ import annotations

from typing import Any, Dict, List, Optional

from pydantic import BaseModel, Field


class PipelineContext(BaseModel):
    """Typed view of `ConversationState.intermediate_results`.

    Field naming preserves the existing dict keys exactly so a one-line
    `model_dump(exclude_none=True)` round-trips into the dict that downstream
    code expects.

    See `from_state` and `apply_to_state` for bidirectional sync helpers.
    """

    # ─── Intent classification (set by dialogue agent) ────────────────────
    # NOTE: types are intentionally permissive here.  The PipelineContext is
    # a typed VIEW for IDE autocomplete + read-time documentation; runtime
    # writers store whatever shape they want.  Pydantic validation must not
    # block legitimate-but-unconventional payloads.
    intent: Optional[Any] = Field(
        default=None, description="LLM-classified intent string (typically str)"
    )
    llm_intent: Optional[Any] = Field(
        default=None,
        description="Raw LLM intent response (typically dict with intent/entities/analytics)",
    )
    entities: Optional[Any] = Field(
        default_factory=list, description="Entities extracted by the LLM (typically List[str])"
    )
    explanation: Optional[Any] = Field(
        default=None, description="LLM explanation of the classification (typically str)"
    )
    required_analytics: Optional[Any] = Field(
        default_factory=list,
        description="Analytics ops the LLM said are needed (avg, min, max, count, ...) - typically List[str]",
    )
    analytics_required: Optional[Any] = Field(
        default=None,
        description="Boolean flag: does this query require running analytics?",
    )

    # ─── Time range hints (set by dialogue agent) ─────────────────────────
    start_date: Optional[str] = None
    end_date: Optional[str] = None

    # ─── Pipeline-stage results ───────────────────────────────────────────
    sparql_result: Optional[Any] = Field(default=None, description="SPARQL agent output")
    sql_result: Optional[Any] = Field(default=None, description="SQL agent output")
    analytics_result: Optional[Any] = Field(default=None, description="Analytics agent output")
    anomaly_result: Optional[Any] = Field(default=None, description="Anomaly agent output")
    capability_result: Optional[Any] = Field(default=None, description="Capability KB answer")
    control_result: Optional[Any] = Field(default=None, description="Control agent ack")
    floor_plan_result: Optional[Any] = Field(
        default=None, description="Floor plan response (typically markdown str)"
    )
    floor_plan_structured: Optional[Any] = Field(
        default=None, description="Structured FloorPlanResult dict"
    )
    maintenance_result: Optional[Any] = Field(default=None, description="Maintenance ticket result")
    planner_result: Optional[Any] = Field(
        default=None, description="Planner agent output (multi-step)"
    )
    report_result: Optional[Any] = Field(default=None, description="Report agent output")
    viz_result: Optional[Any] = Field(default=None, description="Visualization agent output")
    document_result: Optional[Any] = Field(default=None, description="Document agent output")
    export_result: Optional[Any] = Field(default=None, description="Data export agent output")

    # ─── Multi-intent (Phase 6) ──────────────────────────────────────────
    multi_intent_plan: Optional[Any] = Field(
        default=None,
        description="Sub-intent decomposition + execution plan (typically Dict[str, Any])",
    )
    capability_matches: Optional[Any] = Field(
        default_factory=list,
        description="Pre-fetched capability KB matches from the semantic router (List[CapabilityMatch])",
    )

    # ─── Semantic routing (Phase 1 capability + Phase 4 floor_plan bypasses) ──
    semantic_route_intent: Optional[str] = Field(default=None)
    semantic_route_score: Optional[float] = Field(default=None)

    # ─── Contextual hints ─────────────────────────────────────────────────
    floor_context_hint: Optional[Any] = Field(default=None)
    sensor_metadata: Optional[Any] = Field(default_factory=dict)
    dialogue_response: Optional[Any] = Field(default=None)
    persona_domain_hint: Optional[Any] = Field(default=None)
    pending_clarification_type: Optional[Any] = Field(default=None)

    # ─── Compliance / recommendation ──────────────────────────────────────
    compliance_context: Optional[Any] = Field(default=None)
    recommendation_domain: Optional[Any] = Field(default=None)
    report_type: Optional[Any] = Field(default=None)
    export_format: Optional[Any] = Field(default=None)

    # ─── Memory / grounding / verification ────────────────────────────────
    memory_context: Optional[Any] = Field(default=None)
    user_context: Optional[Any] = Field(default=None)
    g1_taxonomy: Optional[Any] = Field(default=None)
    verification: Optional[Any] = Field(default=None)

    # ─── Self-correction trail ────────────────────────────────────────────
    # Note: correction_log is written as dict (log.to_dict()) by self-correction
    # engine; correction_trace is a List.  Both permissive.
    correction_log: Optional[Any] = Field(default=None)
    correction_trace: Optional[Any] = Field(default_factory=list)

    # ─── Cache / session ──────────────────────────────────────────────────
    cache_hit: Optional[Any] = Field(default=False)
    fresh_session: Optional[Any] = Field(default=None)

    # ─── Error reporting ──────────────────────────────────────────────────
    error: Optional[str] = Field(default=None)

    # ─── Internal: prefix with underscore.  These are agent-private state ──
    # PRIVATE keys — names preserved to match existing writers.  Avoid using
    # in new code; future cleanup may rename or remove these.
    saved_query_results: Optional[Dict[str, Any]] = Field(
        default=None, alias="_saved_query_results"
    )
    semantic_route: Optional[Dict[str, Any]] = Field(default=None, alias="_semantic_route")
    user_lang: Optional[str] = Field(default=None, alias="_user_lang")
    llm_sparql_query: Optional[str] = Field(default=None)
    use_existing_query_results: Optional[bool] = Field(default=None)

    # ─── Pydantic config: allow extra fields so unknown keys round-trip ──
    model_config = {
        "populate_by_name": True,
        "extra": "allow",  # forward-compat: new keys from older callers don't break
    }

    # ─────────────────────────────────────────────────────────────────────
    # Bidirectional sync with the legacy dict
    # ─────────────────────────────────────────────────────────────────────

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "PipelineContext":
        """Snapshot a dict into a typed PipelineContext.

        Unknown keys are preserved on the model (Pydantic `extra='allow'`).
        The original dict is NOT mutated.
        """
        # Normalise underscore-prefixed aliases — Pydantic accepts both the
        # alias and the field name when `populate_by_name=True`.
        return cls.model_validate(dict(data))

    @classmethod
    def from_state(cls, state: Any) -> "PipelineContext":
        """Snapshot a ConversationState into a typed PipelineContext."""
        return cls.from_dict(getattr(state, "intermediate_results", {}) or {})

    def to_dict(self) -> Dict[str, Any]:
        """Serialize to the legacy dict shape, including underscore aliases."""
        return self.model_dump(by_alias=True, exclude_none=False)

    def apply_to_state(self, state: Any) -> None:
        """Write this context BACK onto a ConversationState's intermediate_results.

        Existing keys are overwritten; unknown keys present on the state but
        absent here are LEFT IN PLACE so callers that still use the dict
        don't lose data.
        """
        if not hasattr(state, "intermediate_results") or state.intermediate_results is None:
            state.intermediate_results = {}
        for k, v in self.to_dict().items():
            if v is not None or k in state.intermediate_results:
                # Always write non-None values; for None, only overwrite if the
                # key already existed (so we don't pollute the dict with None
                # entries for keys nobody set).
                state.intermediate_results[k] = v
