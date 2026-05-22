# Capability Semantic Routing — Implementation Plan

> Derived from: [`docs/superpowers/specs/2026-05-21-capability-semantic-routing-design.md`](../specs/2026-05-21-capability-semantic-routing-design.md)
>
> **Goal:** Replace hardcoded keyword routing for the capability intent with semantic (embedding-based) routing using Qdrant. Net result: a new building is onboarded by dropping one YAML file — no Python edits.
>
> **Tech Stack:** Python 3.11, FastAPI, LangGraph, Qdrant, Redis, OpenAI text-embedding-3-small (cloud) / nomic-embed-text (local), Pydantic v1.

**Branch:** `feature/capability-semantic-routing`
**Migration phases:** Phase 1 (code lands behind flag) → Phase 2 (enable + validate) → Phase 3 (delete legacy).

---

## Task 1: EmbeddingService (provider-agnostic wrapper)

**Files:**
- Create: `orchestrator/services/embedding_service.py`
- Test: `tests/test_embedding_service.py`
- Modify: `shared/config.py` (add constants `EMBEDDING_DIM_OPENAI=1536`, `EMBEDDING_DIM_LOCAL=768`, `EMBEDDING_CACHE_TTL_SECONDS=86400`)

**Behaviour:**
- Routes to OpenAI `text-embedding-3-small` or local Ollama `nomic-embed-text` based on `settings.MODEL_PROVIDER`.
- Redis-caches by `sha256(text + ":" + provider)` → key `cache:embed:<hash>`, TTL 24h.
- Retries 3× with exponential backoff on transient failures.
- Truncates input to model max tokens (8191 for OpenAI; ~2048 for local) — does not raise on long input.
- Raises `EmbeddingServiceError` on persistent failure.

**Tests (≥ 12, from §16.1):** dimension correctness per provider, cache hit/miss, retry, batch order, empty/long/unicode input, dimension property, provider switch invalidates cache, persistent failure raises.

**Done when:** all 12 tests pass; module is import-clean.

---

## Task 2: CapabilityRoutingConfig (Pydantic config model)

**Files:**
- Modify: `shared/capability_schema.py` (add `CapabilityRoutingConfig` model)
- Create or modify: `shared/building_config.py` (load capability_routing from `input/<bldg>/building.yaml`)
- Test: `tests/test_capability_routing_config.py`

**Schema:**
```python
class CapabilityRoutingConfig(BaseModel):
    enabled: bool = True
    embedding_model: Literal["auto", "openai", "local"] = "auto"
    threshold: float = Field(0.65, ge=0.0, le=1.0)
    override_min: float = Field(0.85, ge=0.0, le=1.0)
    top_k: int = Field(5, ge=1, le=50)
    fallback_on_qdrant_failure: Literal["skip", "keyword"] = "skip"

    @validator("override_min")
    def override_above_threshold(cls, v, values):
        if "threshold" in values and v < values["threshold"]:
            raise ValueError("override_min must be >= threshold")
        return v
```

**Tests (≥ 8):** defaults applied when block absent; invalid threshold rejected; threshold > override_min rejected; negative top_k rejected; embedding_model auto resolves at runtime; existing 32-entry YAML still validates; no `search()` method on CapabilityKB after Phase 3; building without `capability_routing` block loads.

**Done when:** all 8 tests pass; existing `input/bldg1/capability.yaml` validates with new schema; no breaking change to `CapabilityKB` or `CapabilityEntry`.

---

## Task 3: CapabilityIndexer (startup-time embedding pipeline)

**Files:**
- Create: `orchestrator/services/capability_indexer.py`
- Test: `tests/test_capability_indexer.py`

**Behaviour:**
- `index_all_buildings()` iterates `/app/input/*/capability.yaml`.
- Per building: computes SHA-256 of YAML file content. If Qdrant collection `capability_<bldg>` exists with any point whose `payload.yaml_sha` matches → SKIP. Otherwise: DELETE collection if dim mismatch, CREATE if missing, batch-embed all keywords + content, upsert with UUID v5 IDs.
- Point ID: `uuid5(NAMESPACE_OID, f"{building_id}:{entry_id}:{vector_source}:{text_hash}")`.
- Returns `IndexResult(building_id, status, entries, points, duration_ms, reason)` per building.
- Status: `indexed | skipped | degraded | disabled`.
- On Qdrant or embedding failure: `degraded` — does NOT raise (orchestrator must start).

**Tests (≥ 14, from §16.1):** first index creates collection; unchanged YAML skips; changed YAML rebuilds; point count = sum(keywords)+1; yaml_sha in payload; UUID v5 deterministic; missing YAML graceful; malformed YAML graceful; Qdrant down graceful; embedding down graceful; dim mismatch rebuilds; multi-building isolation; batch upsert used; disabled config skipped.

**Done when:** all 14 tests pass; manual run against real bldg1 produces ~480 points in `capability_bldg1` collection; second run with unchanged YAML logs `status=skipped` with 0 embedding API calls.

---

## Task 4: SemanticRouter (query-time classifier)

**Files:**
- Create: `orchestrator/services/semantic_router.py`
- Test: `tests/test_semantic_router.py`

**API:**
```python
@dataclass
class CapabilityMatch:
    entry_id: str
    score: float
    entry: CapabilityEntry

@dataclass
class SemanticRouteResult:
    intent: Optional[str]
    score: float
    matches: List[CapabilityMatch]
    source: Literal["semantic", "fallback", "disabled"]

class SemanticRouter:
    def register_intent(self, intent: str, collection_prefix: str) -> None
    async def classify(self, query: str, building_id: str) -> SemanticRouteResult
```

**Behaviour:**
- Embeds query once (via `EmbeddingService` — Redis-cached).
- For each registered intent: `qdrant.search(collection, query_vec, top_k)`.
- Groups raw points by `payload.entry_id`; max-pool scores within each group.
- Loads `CapabilityKB` for `entry` field population (KB still serves content lookup).
- Decision rule:
  - `score >= override_min` → `intent=capability`, `source=semantic` (caller skips LLM)
  - `threshold <= score < override_min` → `intent=None`, but matches populated (caller decides based on LLM)
  - `score < threshold` → `intent=None`, matches empty
- Qdrant unreachable → `source=fallback`, score=0.0, matches=[].
- Disabled per-building → `source=disabled`, score=0.0, matches=[].

**Tests (≥ 16, from §16.1):** high/medium/low score routing; group-by-entry_id with max-pool; disabled returns disabled; Qdrant down returns fallback; per-building threshold; top_k respected; register_intent stores binding; embedding failure → fallback; empty/punctuation/unicode queries; concurrent safety.

**Done when:** all 16 tests pass; against real `capability_bldg1`, the query "What are the lift dimensions and weight limit?" returns `score > 0.65` with `lift_accessibility_detail` as top match.

---

## Task 5: Feature flag in shared/config.py

**Files:**
- Modify: `shared/config.py`
- Modify: `.env.example`

**Change:**
```python
CAPABILITY_SEMANTIC_ROUTING_ENABLED: bool = Field(
    default=False,
    description="Enable Qdrant-based semantic routing for capability intent. "
                "Phase 2 of capability-semantic-routing migration. "
                "When False, falls back to keyword-based routing (legacy).",
)
```

**Done when:** flag is `False` by default; reads from `CAPABILITY_SEMANTIC_ROUTING_ENABLED` env var; documented in `.env.example`.

---

## Task 6: Wire CapabilityIndexer into FastAPI lifespan (flag-gated)

**Files:**
- Modify: `orchestrator/main.py` (lifespan block, around line 278)

**Behaviour:**
- After existing floor-plan registry init, add:
  ```python
  capability_indexer = CapabilityIndexer(
      qdrant_client=qdrant_client,
      embedding_service=embedding_service,
      input_root=settings.INPUT_ROOT,
  )
  index_results = await capability_indexer.index_all_buildings()
  for bldg, result in index_results.items():
      logger.info(f"[capability_indexer] {bldg}: {result.status} "
                  f"entries={result.entries} points={result.points}")
  app.state.capability_indexer = capability_indexer
  app.state.semantic_router = SemanticRouter(
      qdrant_client=qdrant_client,
      embedding_service=embedding_service,
  )
  app.state.semantic_router.register_intent("capability", "capability_")
  ```
- Indexing failure: logged, NOT re-raised. Orchestrator boots.
- Always runs (regardless of flag) — so when flag flips to True, the data is ready. The flag only gates whether `dialogue_agent` *uses* the router.

**Done when:** orchestrator startup logs `[capability_indexer] bldg1: indexed entries=32 points=~480` on first run, `skipped` on second; orchestrator boots even if Qdrant is unreachable.

---

## Task 7: Wire SemanticRouter into dialogue_agent.py (flag-gated)

**Files:**
- Modify: `orchestrator/agents/dialogue_agent.py`

**Behaviour:**
- Add `semantic_router: Optional[SemanticRouter] = None` to `DialogueAgent.__init__`.
- In `classify_intent()`, before LLM call:
  ```python
  if settings.CAPABILITY_SEMANTIC_ROUTING_ENABLED and self.semantic_router is not None:
      semantic = await self.semantic_router.classify(user_query, building_id)
      if semantic.score >= cfg.override_min:
          state.intermediate_results["capability_matches"] = semantic.matches
          state.intermediate_results["semantic_route_score"] = semantic.score
          # skip LLM call entirely
          return {"intent": "capability", "analytics": False, "general": False}
  ```
- After LLM call, soft override:
  ```python
  if (settings.CAPABILITY_SEMANTIC_ROUTING_ENABLED
          and 'semantic' in locals()
          and cfg.threshold <= semantic.score < cfg.override_min
          and normalized.get("intent") in NON_DATA_INTENTS):
      state.intermediate_results["capability_matches"] = semantic.matches
      normalized["intent"] = "capability"
  ```
- Cache-hit path: same logic — semantic router runs after cache read, before returning.
- **No deletion** of `_CAPABILITY_KW` / `_STRONG_FACILITY_KW` in this task. They stay as the keyword-fallback path when flag is OFF or when `fallback_on_qdrant_failure: keyword`.

**Done when:** flag OFF → behaviour byte-identical to current; flag ON → semantic router runs, but legacy keyword override is bypassed when router returns capability_matches (avoid double-routing).

---

## Task 8: Update capability_agent.py to use pre-fetched matches

**Files:**
- Modify: `orchestrator/agents/capability_agent.py`

**Behaviour:**
- In `handle()`:
  ```python
  matches = state.intermediate_results.get("capability_matches")
  if matches:
      # Use pre-fetched semantic matches
      kb = _load_kb(building_id)  # still needed for entry content lookup
      response_entries = [m.entry for m in matches]
  else:
      # Fallback to legacy keyword search (when flag off OR Qdrant fallback)
      kb = _load_kb(building_id)
      response_entries = kb.search(user_query) if kb else []
  ```
- Response formatting unchanged.

**Done when:** with `capability_matches` populated, agent does ZERO calls to `kb.search()`; without it, behaves identically to current code.

---

## Task 9: Phase 1 Gate Validation

**Tests to run (from §17.2):**

```bash
# A. New unit tests pass
pytest tests/test_embedding_service.py tests/test_capability_indexer.py \
       tests/test_semantic_router.py tests/test_capability_routing_config.py -v

# B. Full pytest suite (with flag OFF)
CAPABILITY_SEMANTIC_ROUTING_ENABLED=false pytest tests/ -v

# C. Survey test with flag OFF
CAPABILITY_SEMANTIC_ROUTING_ENABLED=false python scripts/survey_live_test.py
```

**Pass criteria:** A all pass; B no new regressions vs baseline; C ≥ 70/70.

**Done when:** all three gates pass.

---

## Task 10: Phase 2 — Enable flag, run regression battery

**Steps:**
1. Set `CAPABILITY_SEMANTIC_ROUTING_ENABLED=true` in `.env`.
2. Restart orchestrator. Verify `[capability_indexer] bldg1: indexed entries=32` in startup logs.
3. Run regression battery (§16):
   - `pytest tests/test_capability_e2e.py -v` (integration)
   - `pytest tests/test_non_regression_intents.py -v` (16 intents)
   - `pytest tests/test_floor_n_protection.py -v` (4 cases)
   - `pytest tests/test_capability_edge_cases.py -v` (edge cases)
   - `pytest tests/test_capability_semantic_quality.py -v` (recall delta report)
4. Re-run `scripts/survey_live_test.py` — must hit ≥ 70/70.
5. If threshold needs tuning (false positives in survey): adjust `input/bldg1/building.yaml:capability_routing.threshold`, re-run.
6. If recall is below target on synonyms: increase `top_k` or tune `embed_text` strategy.

**Done when:** all regression tests pass; survey ≥ 70/70; recall report shows ≥ 8/10 new synonym hits.

**This is a checkpoint.** Stop here and review with the user before proceeding to Phase 3.

---

## Task 11: Phase 3 — Cleanup (only after Phase 2 passes)

**Files to modify:**
- `orchestrator/agents/dialogue_agent.py` — delete `_CAPABILITY_KW`, `_STRONG_FACILITY_KW`, both override blocks (hot-path + cache-hit).
- `shared/capability_schema.py` — delete `CapabilityKB.search()` method.
- `orchestrator/agents/capability_agent.py` — delete the `else` fallback in Task 8 (the one that calls `kb.search()`); replace with a defensive error log if matches are missing.
- `shared/capability_schema.py` — remove `keyword` from `fallback_on_qdrant_failure` `Literal`; keep only `skip`.
- `shared/config.py` — delete `CAPABILITY_SEMANTIC_ROUTING_ENABLED` flag.
- `orchestrator/agents/dialogue_agent.py` — remove the `if settings.CAPABILITY_SEMANTIC_ROUTING_ENABLED` conditionals (semantic routing becomes unconditional).

**Verification:**
```bash
! grep -rn "_CAPABILITY_KW\|_STRONG_FACILITY_KW" orchestrator/ shared/
! grep -n "def search" shared/capability_schema.py
! grep -rn "CAPABILITY_SEMANTIC_ROUTING_ENABLED" orchestrator/ shared/
pytest tests/ -v
python scripts/survey_live_test.py
```

**Done when:** all three greps return non-zero (no matches); pytest all pass; survey ≥ 70/70.

---

## Out-of-band: Regression battery test files

The spec (§16) defines 130+ tests. Since per-task scoping keeps tasks small, the regression test files are written incrementally as part of Tasks 9, 10, 11. Specifically:

- `tests/test_capability_e2e.py` — created in Task 10 (12 integration tests)
- `tests/test_non_regression_intents.py` — created in Task 10 (16 intents × 1 test each)
- `tests/test_floor_n_protection.py` — created in Task 10 (4 edge cases)
- `tests/test_capability_edge_cases.py` — created in Task 10 (14 adversarial)
- `tests/test_capability_semantic_quality.py` — created in Task 10 (10 semantic recall + delta report)
- `tests/test_ontology_integrity.py` — created in Task 10 (8 semantic web)
- `tests/perf/test_capability_performance.py` — created in Task 10 (7 perf targets)

Total tests added by the end of Task 10: **~130 tests** (matches §16 spec).

---

## Risk register (live during implementation)

| Risk | Status | Mitigation |
|---|---|---|
| Threshold 0.65 / 0.85 untuned | Open | Tune in Task 10 based on survey result |
| Embedding API latency on every query | Open | Redis cache + Task 9 perf gate |
| Existing 32 KB entries fail semantic recall | Open | Recall report in Task 10; fall back to top_k bump or content-only embedding |
| Floor-N protection regresses | Mitigated | §15.2 + Task 10 4-case test |
| Qdrant collection name collision with future intents | Mitigated | Per-building suffix in collection name |

---

## Definition of Done (overall)

1. All 11 tasks above completed and verified.
2. All 7 acceptance criteria from spec §14 met.
3. Spec §15 non-regression contract holds (verified by §17 validation protocol).
4. No commit pushed to remote without explicit user approval.
