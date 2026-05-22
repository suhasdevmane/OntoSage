# Multi-Intent Semantic Routing — Mini-Spec

**Date:** 2026-05-22
**Status:** In progress (extension of the capability-semantic-routing migration)
**Branch:** `feature/capability-semantic-routing`

## Goal

Make `SemanticRouter` genuinely intent-agnostic so the `register_intent()` extension hook described in the original spec (§7.2) is functional. Demonstrate by adding optional `floor_plan` semantic routing.

## Non-goal

This does NOT replace the existing `floor_plan_service.is_floor_plan_query()` heuristic — that still runs in `workflow.py:_route_from_dialogue()` as today. Multi-intent semantic routing is purely ADDITIVE and opt-in via per-building YAML. Default behavior is unchanged.

## Schema extension (`input/<bldg>/building.yaml`)

```yaml
# Existing block (unchanged)
capability_routing:
  enabled: true
  threshold: 0.56
  override_min: 0.60
  top_k: 5
  fallback_on_qdrant_failure: skip

# New optional block — opt-in by default missing
intent_routing:
  floor_plan:
    enabled: false  # SAFE DEFAULT: opt-in only
    descriptors:
      - "show me the floor plan"
      - "what is the layout of the building"
      - "where is the meeting room"
      - "building map"
    threshold: 0.60
    override_min: 0.70
  spatial_query:
    enabled: false
    descriptors:
      - "how many rooms are on this floor"
      - "what is the total area of this floor"
      - "which rooms are adjacent to room X"
    threshold: 0.60
    override_min: 0.70
```

## Indexer changes

Extend `CapabilityIndexer` to also index `intent_routing.<intent>.descriptors` into per-intent Qdrant collections named `intent_<intent_name>_<building_id>`.

- Same SHA-256 idempotency contract
- Each descriptor → one Qdrant point with payload `{intent_name, descriptor_idx, text, yaml_sha}`
- Skipped entirely when `intent_routing` block absent or `enabled: false`

## Router changes — make classify() intent-agnostic

Current `classify()` hardcodes capability lookup. Refactor:

```python
async def classify(self, query, building_id) -> SemanticRouteResult:
    # Embed once
    query_vec = await self._embedder.embed(query)

    # For each registered intent, search its collection
    results = []
    for intent_name, binding in self._intents.items():
        cfg = self._get_intent_config(building_id, intent_name)
        if not cfg.enabled:
            continue
        matches = await self._search(query_vec, binding.collection(building_id), cfg)
        if matches:
            results.append((intent_name, cfg, matches))

    # Pick highest-scoring intent
    if not results:
        return SemanticRouteResult(intent=None, score=0.0, source="semantic")

    best_intent, best_cfg, best_matches = max(
        results, key=lambda r: r[2][0].score
    )
    top_score = best_matches[0].score

    # Decision based on the WINNING intent's thresholds
    if top_score >= best_cfg.override_min:
        return SemanticRouteResult(
            intent=best_intent, score=top_score,
            matches=best_matches, source="semantic",
        )
    elif top_score >= best_cfg.threshold:
        return SemanticRouteResult(
            intent=None, score=top_score,
            matches=best_matches, source="semantic",
        )
    else:
        return SemanticRouteResult(
            intent=None, score=top_score, matches=[], source="semantic",
        )
```

## Dialogue agent change

The existing dialogue_agent code already treats `semantic_result.intent` as agnostic — it just checks `if semantic_result.intent == "capability"`. To extend, the check becomes:

```python
if semantic_result.intent:  # any intent (capability, floor_plan, ...)
    if semantic_result.intent == "capability":
        state.intermediate_results["capability_matches"] = semantic_result.matches
    # For other intents, just set the intent — no pre-fetched data
    return {
        "intent": semantic_result.intent,
        "general": False,
        "analytics": False,
        "sparql_query": "",
        "response": "",
    }
```

## Non-regression contract

1. **No building.yaml change → byte-identical behavior to current state.** Building.yaml without `intent_routing:` block → no extra intents registered → SemanticRouter behaves as today (capability-only).
2. **Floor-N protection holds.** Even if `floor_plan` semantic routing is enabled, the floor-N hijack guard in `workflow.py:_route_from_dialogue` still runs. Capability intent stays in `_data_intents` per §6.4.
3. **Backward-compat.** All existing tests continue to pass without modification.

## Test plan

1. **Unit tests** (extending `test_semantic_router.py`):
   - `test_classify_intent_agnostic_picks_highest_score`
   - `test_disabled_intent_skipped`
   - `test_no_registered_intents_returns_disabled`
2. **Integration tests** (extending `test_capability_e2e.py`):
   - `test_floor_plan_descriptors_off_by_default` — confirm opt-in
3. **Live opt-in smoke test** — enable floor_plan descriptors in bldg1, send sample floor_plan queries, verify routing.
4. **Survey regression** — full 70-query survey with floor_plan descriptors ENABLED. Must still hit 70/70.

## Phased rollout

- **Phase A (this session):** Code + schema + unit tests. floor_plan descriptors STAY OFF in bldg1.
- **Phase B (future):** Enable floor_plan descriptors in bldg1, validate, tune thresholds. Separate PR.
- **Phase C (future):** Replace `floor_plan_service.is_floor_plan_query()` heuristic entirely. Even more careful PR with full regression.

This minimizes risk: Phase A is a pure architecture change with no behavioral impact.
