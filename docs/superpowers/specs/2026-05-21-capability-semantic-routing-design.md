# Capability Semantic Routing — Design

**Date:** 2026-05-21
**Author:** OntoSage core
**Status:** Draft — pending user review

---

## 1. Goal

Replace the hardcoded keyword routing for the capability intent with semantic (embedding-based) routing so that adding a new building requires editing one YAML file and nothing else.

## 2. Problem

The current capability routing fails the developer-experience test for multi-building deployment:

1. **Two synchronized sources.** Adding a new capability entry today requires editing `input/<bldg>/capability.yaml` AND `orchestrator/agents/dialogue_agent.py` (the `_STRONG_FACILITY_KW` / `_CAPABILITY_KW` frozensets). A YAML-only change is invisible to the router.
2. **Substring matching, no semantics.** `kw.lower() in query.lower()` misses synonyms: "elevator capacity" cannot match `lift_accessibility_detail` no matter what.
3. **Tiered keyword gates are fragile.** `_STRONG_FACILITY_KW` overrides unconditionally, `_CAPABILITY_KW` overrides only when LLM picks a non-data intent, and a separate floor-plan hijack guard had to be added in `workflow.py:_data_intents`. The interactions compound.
4. **The codebase already has the infrastructure** (Qdrant, OpenAI/Ollama embeddings, per-building YAML configs) but capabilities don't use any of it.

## 3. Decision Summary

Six core decisions, each chosen from explicit options:

| Decision | Choice | Reason |
|---|---|---|
| Re-embed trigger | Startup-only with SHA-256 fingerprint | Matches floor-plan pipeline; predictable; idempotent |
| Routing architecture | Semantic-first, skip LLM if confident | Best latency (~500ms saved per high-confidence query) |
| Embed strategy | Multi-vector per entry (per-keyword + per-content) | Best recall for terse/synonym queries |
| Scope | Capability-only this iteration | Smaller PR; floor_plan/spatial deferred to later spec |
| Configuration location | `input/<bldg>/building.yaml` | Per-building tunable; matches existing config pattern |
| Migration | Behind feature flag, then cleanup | Keyword-based routing is battle-tested; remove only after parity |

## 4. Architecture

```
┌──────────────────────────────────────────────────────────────────┐
│  STARTUP (per building)                                          │
│                                                                  │
│  input/<bldg>/capability.yaml ──┐                                │
│                                 ├──> CapabilityIndexer           │
│  input/<bldg>/building.yaml  ───┘    (SHA-256 fingerprint check) │
│         (capability_routing:)                                    │
│                                          │                       │
│                            ┌─────────────┴──────────────┐        │
│                            ↓                            ↓        │
│                    embed each entry           Per-bldg config:   │
│                    keywords + content         threshold,         │
│                    (multi-vector)             top_k,             │
│                            │                  override_min       │
│                            ↓                                     │
│                  Qdrant: capability_<bldg>                       │
└──────────────────────────────────────────────────────────────────┘

┌──────────────────────────────────────────────────────────────────┐
│  QUERY-TIME                                                      │
│                                                                  │
│  user_query ──> SemanticRouter.classify(query, bldg_id)          │
│                       │                                          │
│                       ↓ embed query                              │
│                  Qdrant.search("capability_<bldg>", top_k)       │
│                       │                                          │
│                       ↓ group by entry_id, max(score)            │
│                       │                                          │
│           ┌───────────┴───────────┐                              │
│           ↓                       ↓                              │
│   score >= override_min       score >= threshold                 │
│   (e.g. 0.85)                 (e.g. 0.65)                        │
│   intent = capability         intent = capability                │
│   skip LLM intent call        but only if LLM would have         │
│                               picked non-data intent             │
│           ↓                       ↓                              │
│           └─────────┬─────────────┘                              │
│                     ↓                                            │
│      state.intermediate_results["capability_matches"]            │
│              (pre-populated entries, no second search)           │
│                     ↓                                            │
│             CapabilityAgent.handle()                             │
│             formats response from pre-fetched matches            │
└──────────────────────────────────────────────────────────────────┘
```

### 4.1 Key design properties

- **One source of truth:** `input/<bldg>/capability.yaml`. Edit YAML → restart → done.
- **Zero hardcoded keywords:** `_CAPABILITY_KW`, `_STRONG_FACILITY_KW` are deleted entirely.
- **Per-building isolation:** Each building gets its own Qdrant collection. No cross-building leakage.
- **Two-tier routing:** A high score (`override_min`) overrides even LLM data-intent classifications. A medium score (`threshold`) is a softer override that yields to LLM data intents. Both numbers are per-building configurable.
- **Extension hook:** `SemanticRouter` class is intent-agnostic — `register_intent("floor_plan", "spatial_")` works the same way when we extend to other intents later.

## 5. Schema

### 5.1 `input/<bldg>/capability.yaml`

Unchanged. Existing schema (`shared/capability_schema.py:CapabilityEntry`) stays as-is. The `keywords` field is now used for multi-vector embedding rather than substring matching, but the YAML structure does not change. Backwards compatible with every existing building config.

### 5.2 `input/<bldg>/building.yaml` — new optional block

```yaml
capability_routing:
  enabled: true                    # default true; false → falls back to LLM-only intent
  embedding_model: auto            # auto | openai | local; "auto" follows MODEL_PROVIDER
  threshold: 0.65                  # min score to set intent=capability when LLM picked non-data
  override_min: 0.85               # min score to override even LLM data-intent classifications
  top_k: 5                         # how many points to fetch from Qdrant; grouped by entry_id
  fallback_on_qdrant_failure: skip # skip | keyword
                                   # skip → SemanticRouter returns source="fallback", score=0.0;
                                   #        dialogue_agent reverts to LLM-only intent (current
                                   #        behaviour for capability queries — they were not
                                   #        being captured before this refactor anyway).
                                   # keyword → use legacy `_CAPABILITY_KW` substring matcher.
                                   #        Only valid during Phase 1 of migration (see §11),
                                   #        when the keyword code still exists. After Phase 3
                                   #        cleanup, this option is removed; default "skip"
                                   #        is the only option going forward.
```

If `capability_routing:` block is absent, defaults are applied — existing buildings need no edits.

### 5.3 Qdrant collection layout: `capability_<bldg_id>`

One collection per building. Vector dim auto-detected at startup (1536 for OpenAI `text-embedding-3-small`, 768 for `nomic-embed-text`). Multi-vector layout — one point per `(entry, vector_source)` tuple:

```json
{
  "id": "<uuid v5 from entry_id + vector_source + text_hash>",
  "vector": [...],
  "payload": {
    "entry_id": "lift_accessibility_detail",
    "category": "ACCESSIBILITY",
    "source": "cardiff_university_accessibility_page",
    "vector_source": "keyword",
    "text": "lift dimensions",
    "yaml_sha": "a4f2b9..."
  }
}
```

For an entry with 17 keywords + 1 content block = **18 points** in Qdrant. With 32 entries × ~15 vectors each ≈ **~480 points per building**. Trivial for Qdrant.

## 6. Data Flow

### 6.1 Startup (per building)

```
For each building_id in /app/input/*/:
  1. Load capability.yaml + building.yaml
  2. Compute sha256(capability.yaml content) → yaml_sha
  3. Query Qdrant: does collection capability_<bldg> exist?
     a. Yes + any point's payload.yaml_sha matches → SKIP (no changes)
     b. Yes + sha mismatch → DELETE collection, rebuild
     c. No → CREATE collection
  4. For each entry in capabilities:
     a. For each keyword: embed("<keyword>") → upsert point (vector_source=keyword)
     b. Embed content[:500] → upsert point (vector_source=content)
  5. Log: "[capability_indexer] bldg=bldg1, entries=32, points=480, sha=a4f2b9..."
```

Idempotent. Unchanged YAML on restart → zero embedding API calls.

### 6.2 Query-time

```python
# In dialogue_agent (before LLM intent call):

semantic = await semantic_router.classify(
    query=user_query, building_id=state.building_id
)
# Returns: SemanticRouteResult(intent, score, matches, source)

if semantic.score >= cfg.override_min:
    intent = "capability"
    state.intermediate_results["capability_matches"] = semantic.matches
    return intent  # skip LLM intent call

llm_intent = await self._classify_intent_llm(...)

if (cfg.threshold <= semantic.score < cfg.override_min
        and llm_intent in NON_DATA_INTENTS):
    intent = "capability"
    state.intermediate_results["capability_matches"] = semantic.matches
else:
    intent = llm_intent
```

`CapabilityAgent.handle()` reads `capability_matches` from state and formats — it does no second search.

### 6.3 Code deletions

| File | What is removed |
|---|---|
| `dialogue_agent.py` | `_CAPABILITY_KW` (108 keywords), `_STRONG_FACILITY_KW` (36 keywords), both override blocks (hot-path + cache-hit) |
| `shared/capability_schema.py` | `CapabilityKB.search()` substring method |
| `capability_agent.py` | The `_load_kb()` lookup + `kb.search(query)` call inside `handle()` (replaced by reading `state.intermediate_results["capability_matches"]`) |

Net code reduction: roughly **−200 lines** of keyword sync logic.

### 6.4 Code that explicitly stays (non-deletions)

These are common review traps — list them so the implementer doesn't "clean them up":

| File | What stays and why |
|---|---|
| `workflow.py` | The `"capability"` entry in `_data_intents` **stays**. It is the floor-plan hijack guard for queries like "Which floors have accessible toilets?". Removing it would regress the fix shipped 2026-05-20. |
| `workflow.py` | `_route_from_dialogue()` capability → `capability` node mapping stays unchanged. |
| `workflow.py` | The floor-plan heuristic (`floor_plan_service.is_floor_plan_query()` + `_data_intents` check) stays — it protects all data intents, not just capability. |
| `capability_agent.py` | `_load_kb()` and `_KB_CACHE` stay — used as defensive fallback when `state.intermediate_results["capability_matches"]` is missing (e.g., when feature flag is off, or when fallback path triggers). |
| `shared/capability_schema.py` | `CapabilityKB`, `CapabilityEntry`, `BuildingInfo` Pydantic models — KB still needs to be loaded for content lookup by `entry_id`. Only the `search()` method goes. |
| `dialogue_agent.py` | LLM intent classification, persona detection, time-range extraction, G1 taxonomy emission, entity extraction — all unchanged. |
| `dialogue_agent.py` | The intent cache (`cache:intent:<hash>`) and response cache (`resp_cache:exact:<bldg>:*`) stay unchanged. |

## 7. New Files

### 7.1 `orchestrator/services/capability_indexer.py`

Startup-time indexer. Owns SHA-256 fingerprint logic and Qdrant writes.

```python
class CapabilityIndexer:
    def __init__(self, qdrant_client, embedding_service, input_root="/app/input"):
        ...

    async def index_all_buildings(self) -> Dict[str, IndexResult]:
        """Called once during FastAPI lifespan. Iterates every input/<bldg>/."""

    async def index_building(self, building_id: str) -> IndexResult:
        """Index one building. Idempotent — skips if YAML sha matches existing collection."""

    async def _embed_entry(self, entry: CapabilityEntry, yaml_sha: str) -> List[PointStruct]:
        """Return one point per keyword + one for content. UUID v5 for deterministic IDs."""

    async def _upsert_points(self, collection: str, points: List[PointStruct]) -> None:
        """Batch upsert. Retries on Qdrant 503."""
```

**Failure mode:** If embedding API is down or Qdrant unreachable at startup, log error and set `IndexResult(status="degraded", reason=...)`. The orchestrator still starts — `SemanticRouter` uses `fallback_on_qdrant_failure` config at query time.

### 7.2 `orchestrator/services/semantic_router.py`

Query-time semantic classifier. Intent-agnostic by design.

```python
@dataclass
class SemanticRouteResult:
    intent: Optional[str]               # None if no match above threshold
    score: float                        # max similarity (0.0 if no match)
    matches: List[CapabilityMatch]      # grouped by entry_id, top-3
    source: Literal["semantic", "fallback", "disabled"]

class SemanticRouter:
    def __init__(self, qdrant_client, embedding_service, building_config_loader):
        self._intents: Dict[str, IntentBinding] = {}

    def register_intent(self, intent: str, collection_prefix: str) -> None:
        """Extension hook: future floor_plan/spatial bindings register here."""

    async def classify(
        self, query: str, building_id: str
    ) -> SemanticRouteResult:
        """Embed query, search registered collections, return best match."""

    async def _search_capability(
        self, query_vec, building_id: str, cfg: CapabilityRoutingConfig
    ) -> List[CapabilityMatch]:
        """Capability-specific search: group by entry_id, max-pool keyword+content scores."""
```

The `register_intent()` API is the extension hook for future floor_plan/spatial refactors.

### 7.3 `orchestrator/services/embedding_service.py`

Provider-agnostic embedding wrapper. Routes to OpenAI or Ollama based on `MODEL_PROVIDER`. Caches results in Redis (`cache:embed:<sha256>`) with 24h TTL.

```python
class EmbeddingService:
    async def embed(self, text: str) -> List[float]: ...
    async def embed_batch(self, texts: List[str]) -> List[List[float]]: ...
    @property
    def dimension(self) -> int: ...
```

Used by `CapabilityIndexer` (batch, startup) and `SemanticRouter` (single, per-query, Redis-cached).

## 8. Modified Files

| File | Change |
|---|---|
| `shared/capability_schema.py` | Delete `CapabilityKB.search()`. Add `CapabilityRoutingConfig` Pydantic model. |
| `shared/floor_plan_config.py` (or new `shared/building_config.py`) | Add `capability_routing` field to `BuildingConfig` |
| `orchestrator/agents/dialogue_agent.py` | Delete `_CAPABILITY_KW`, `_STRONG_FACILITY_KW`, both override blocks. Inject `SemanticRouter`. Call `semantic_router.classify()` before LLM intent call. |
| `orchestrator/agents/capability_agent.py` | `handle()` reads `state.intermediate_results["capability_matches"]` directly. Falls back to `_load_kb()` only if matches missing (defensive). |
| `orchestrator/workflow.py` | Inject `SemanticRouter` into `dialogue_agent` via constructor. **No change to `_data_intents` or `_route_from_dialogue` routing logic** — capability routing is set BEFORE this function runs, by the semantic router inside dialogue_agent. |
| `orchestrator/main.py` | In `lifespan`: instantiate `CapabilityIndexer`, call `index_all_buildings()`, instantiate `SemanticRouter`, pass to `WorkflowOrchestrator`. |
| `shared/config.py` | Add `EMBEDDING_MODEL_AUTO`, `EMBEDDING_DIM_OPENAI=1536`, `EMBEDDING_DIM_LOCAL=768` constants. |

## 9. Developer Workflow (the user-facing outcome)

Onboarding `bldg2`:

```bash
# 1. Drop YAML
cp input/bldg1/capability.yaml input/bldg2/capability.yaml
# (edit for bldg2-specific content)

# 2. (Optional) Tune thresholds in input/bldg2/building.yaml
echo "capability_routing:
  threshold: 0.60
  override_min: 0.80" >> input/bldg2/building.yaml

# 3. Restart
docker-compose restart orchestrator
```

Three steps. Zero Python edits. This is the entire developer flow.

## 10. Testing

### 10.1 Unit tests

| File | Tests |
|---|---|
| `tests/test_capability_indexer.py` | SHA-256 fingerprint skips unchanged YAML; rebuilds on change; missing YAML graceful; multi-vector point count = sum(keywords)+1 per entry |
| `tests/test_semantic_router.py` | High-confidence match returns intent without LLM call; low-confidence falls through; matches grouped by `entry_id` with max-pool; disabled config returns `source="disabled"`; Qdrant down → `source="fallback"` |
| `tests/test_embedding_service.py` | OpenAI/Ollama auto-switch via `MODEL_PROVIDER`; Redis cache hit avoids API call; dimension matches provider |
| `tests/test_capability_schema.py` | `CapabilityRoutingConfig` defaults applied when YAML block absent; invalid thresholds rejected |

### 10.2 Integration tests (`tests/integration/test_capability_e2e.py`)

| Test | Verifies |
|---|---|
| `test_lift_dimensions_routes_to_capability` | The exact query that failed today returns `lift_accessibility_detail` |
| `test_synonym_query_matches` | "How big is the elevator?" matches `lift_accessibility_detail` (semantic) |
| `test_floor_word_does_not_steal_capability` | "Which floors have accessible toilets" routes to capability, not floor_plan |
| `test_sensor_query_not_hijacked` | "What is the CO2 level on floor 3?" still routes to sensor_data |
| `test_unchanged_yaml_skips_reindex` | Restart with unchanged YAML → zero embedding API calls |
| `test_yaml_edit_triggers_reindex` | YAML SHA change → collection rebuilt → new entries searchable |
| `test_multi_building_isolation` | bldg2 query never matches bldg1 entries |

### 10.3 Survey-test integration

- Re-run `scripts/survey_live_test.py` after migration. Must hit ≥ 70/70 (current baseline).
- Add 5 new survey tests with synonym phrasings (e.g., "elevator capacity", "where can I shower?", "wheelchair access lift").

## 11. Migration

Three-phase rollout behind a feature flag:

**Phase 1 — Land code behind flag (Sprint A):**
- `CAPABILITY_SEMANTIC_ROUTING_ENABLED=false` env var, default off
- `CapabilityIndexer` runs at startup; `SemanticRouter` instantiated but `dialogue_agent` only calls it when flag enabled
- Keyword-based routing remains in place but unused when flag enabled
- Allows A/B comparison via survey test

**Phase 2 — Validate (1 week):**
- Toggle flag on for bldg1. Run survey test on both flag states. Compare:
  - Pass rate (must be ≥ current 70/70)
  - Latency p50, p95 (semantic-first should *improve* latency for high-confidence matches)
  - Cost per query (one extra embedding call vs. one fewer LLM call — net negative cost)

**Phase 3 — Cleanup (Sprint B):**
- Default flag to `true`
- Delete `_CAPABILITY_KW`, `_STRONG_FACILITY_KW`, override blocks, `CapabilityKB.search()`
- Remove `keyword` option from `fallback_on_qdrant_failure` config; default becomes `skip` only
- Delete the feature flag itself

The staging is essential because the keyword approach has 32 entries that are battle-tested. We don't rip it out until semantic routing has proven equal-or-better against the survey baseline.

## 12. Risks & Mitigations

| Risk | Probability | Mitigation |
|---|---|---|
| Embedding API latency adds to every query | High (certain) | Redis-cache embeddings by `sha256(query)` with 24h TTL. Cold queries pay ~80ms (OpenAI) or ~30ms (Ollama) once. Net p50 latency *decreases* because semantic-first skips LLM intent call. |
| OpenAI embedding API down | Low | `EmbeddingService` retries 3x with exponential backoff. Full failure → `SemanticRouter` returns `source="fallback"`. `dialogue_agent` reverts to LLM-only intent (current behaviour). Graceful degradation. |
| Qdrant collection corrupt / missing | Low | `CapabilityIndexer` rebuilds from YAML on every startup if SHA mismatch. Missing collection → rebuild from scratch. Self-healing. |
| Threshold miscalibration → false positives | Medium | Conservative defaults (`threshold=0.65`, `override_min=0.85`). Per-building tunable. Survey test catches regressions before merge. |
| Embedding model swap (OpenAI ↔ Ollama) requires reindex | Certain | `EmbeddingService.dimension` exposed; `CapabilityIndexer` reads it. On dim mismatch with existing collection: rebuild. Logged with `[indexer] embedding model changed, rebuilding capability_<bldg>`. |
| Multi-vector retrieval returns dupes from same entry | Certain (by design) | Group-by `entry_id` with max-pool in `_search_capability`. Top-k returned distinct entries, not points. |
| Synonym recall not as good as expected | Medium | `embed_text` strategy is a Phase 1 lever — per-keyword vs combined can be tuned in YAML without code changes. |
| Embedding cost in production | Low | text-embedding-3-small is $0.02/1M tokens. 32 entries × 15 vecs × ~10 tokens = ~5K tokens per building per restart. Per-query: 1 embedding × ~10 tokens × $0.02/1M = $2e-7. Negligible. |

## 13. Out of Scope

Explicit non-goals for this iteration:

- **Other intents** (floor_plan, spatial, anomaly, etc.) — extension hook `SemanticRouter.register_intent()` is included so future refactors do not need a new design doc.
- **Cross-language semantic search** — English-first. OpenAI multilingual works out of the box; local `nomic-embed-text` is English-primary. Multi-language KB content (translated YAMLs) is a separate problem.
- **Disambiguation between similar capability entries** — if two entries score 0.84 and 0.83, we pick the higher; we do not ask the user. Multi-match disambiguation UX is a separate design.
- **Query rewriting / query expansion (HyDE, etc.)** — we embed the raw query.
- **Persona-aware capability ranking** — facility_manager and occupant get the same matches today.

## 14. Acceptance Criteria

This design is implemented and shipped when:

1. New `bldg2` with only a `capability.yaml` file (no Python edits) can answer capability queries correctly.
2. All 70 existing survey tests still pass (no regressions).
3. At least 5 new survey tests with synonym phrasings pass (e.g., "elevator capacity" → `lift_accessibility_detail`).
4. Feature flag toggled off → exact current behaviour (rollback path validated).
5. Latency p50 for capability queries does not regress (target: improves by 100–400ms via skipped LLM call).
6. Unit + integration test coverage ≥ 80% for new files (`capability_indexer.py`, `semantic_router.py`, `embedding_service.py`).
7. Cleanup phase complete: `_CAPABILITY_KW`, `_STRONG_FACILITY_KW`, `CapabilityKB.search()` deleted from codebase.
8. Full regression test battery (§16) passes at every phase gate (§17).

## 15. Non-Regression Contract

This section lists every behaviour from the current pipeline that MUST continue to work unchanged. Implementation that violates any item here is a P0 bug and blocks merge.

### 15.1 Intent classification — all 16 intents preserved

These intents are NOT touched by this refactor. Their dialogue-agent classification, LLM prompts, few-shot examples, persona handling, entity extraction, and time-range parsing all remain bit-identical when the feature flag is off, and remain semantically identical when the flag is on (the only addition is a pre-LLM semantic check, which returns no-match for non-capability queries).

| Intent | Existing route | Must continue to work |
|---|---|---|
| `sensor_data` | sparql → sql → response | Current temperature/CO2/humidity readings |
| `analytics` | sparql → sql → analytics → response | Statistical analysis, trends, averages |
| `discovery` | sparql → response (or → sparql when spatial words) | Sensor type listings, zone/floor counts |
| `report` | planner → report → response | Structured building reports |
| `anomaly` | sparql → sql → anomaly → response | Out-of-range / spike detection |
| `comparison` | sparql → sql → analytics → response | Zone/period comparisons |
| `export` | sparql → sql → export → response | CSV/JSON/HTML exports |
| `recommend` | sparql → sql → analytics → response | HVAC/energy/comfort recommendations |
| `planner` | planner → response | Multi-step orchestrated tasks |
| `forecast` | sparql → sql → analytics → response | Future predictions |
| `floor_plan` | floor_plan → response | Floor map display, room location |
| `spatial_query` | spatial_query → response | Area, adjacency, room counts |
| `control` | response (informs unsupported) | Unsupported-action message |
| `general` | response | Greetings, non-building questions |
| `clarification` | response | Vague-query follow-ups |
| `alert` | sparql → sql → anomaly → response | Threshold-based alerting |

### 15.2 Routing edge cases — all 4 floor-N protections preserved

These were fixed in commits `4995a7f` and `a432d57` (2026-05-20). The semantic router must NOT regress them.

| Query | Must route to | Must NOT route to |
|---|---|---|
| "What is the temperature on floor 3?" | sensor_data → sparql | floor_plan |
| "Show me analytics for floor 2 sensors" | analytics | floor_plan |
| "How many CO2 sensors are on floor 1?" | discovery → sparql | floor_plan |
| "Compare energy usage on floor 1 vs floor 3" | comparison → sparql/analytics | floor_plan |

### 15.3 SPARQL / RAG pipeline — semantic web layer preserved

The ontology subsystem is **entirely untouched**. This refactor does not modify:

- The Brick Schema TTL files in `input/<bldg>/`
- GraphDB endpoint `http://graphdb:7200/repositories/ontosage/sparql`
- `orchestrator/agents/sparql_agent.py` — query generation, context retrieval, RAG fallback via `rag-service:8001`
- The Qdrant `floor_plans` collection (DWG-derived geometry + room descriptions for semantic floor search)
- The Qdrant `user_memory` collection (cross-session agent memory)
- The hybrid retrieval flow (`services/hybrid_retrieval.py`)
- SPARQL prefixes, query templates, or LIMIT enforcement

The new Qdrant collections (`capability_<bldg>`) live alongside existing collections — they do not share names, schemas, or vectors with `floor_plans` or `user_memory`.

### 15.4 Storage layer — untouched

| Store | Status |
|---|---|
| GraphDB (port 7200) | No reads modified, no writes added |
| MySQL (port 3306) | Untouched |
| PostgreSQL (port 5433) | Untouched (auth/RBAC) |
| Redis (port 6379) | NEW keys added: `cache:embed:<sha256>` with 24h TTL. Existing keys (`cache:intent:*`, `resp_cache:exact:*`, `conv_*`, etc.) are unchanged in schema and behaviour. |
| Qdrant (port 6333) | NEW collections added: `capability_<bldg>`. Existing collections (`floor_plans`, `user_memory`) are unchanged. |
| MongoDB (port 27017) | Untouched |

### 15.5 API contract — untouched

| Endpoint | Status |
|---|---|
| `POST /chat` | Request/response shape unchanged. New optional debug field `semantic_route_score` may appear in `meta` but is non-breaking. |
| `GET /health` | New optional service block `capability_router` added. Existing services unchanged. |
| `POST /v1/chat/completions` (OpenAI-compat) | Untouched |
| `GET /floor-plans/*` | Untouched |
| `GET /api/v1/floor-plans/search` | Untouched |
| `POST /auth/login`, `/auth/logout`, `/auth/register` | Untouched |
| WebSocket `/ws/{session_id}` | Untouched |
| RBAC permissions (20 perms × 6 roles) | Untouched |

### 15.6 Per-building startup — additive only

The existing startup lifecycle in `main.py:lifespan` MUST continue to work. The new `CapabilityIndexer.index_all_buildings()` call is added as a step but:

- Runs AFTER GraphDB, Redis, Qdrant, and floor-plan registry initialisation
- Failure of capability indexing does NOT abort startup — it logs `IndexResult(status="degraded")` and the orchestrator boots normally
- Buildings with no `capability.yaml` (or no `capability_routing:` block) get a degraded `IndexResult` and the semantic router returns `source="disabled"` for that building — current behaviour preserved

## 16. Regression Test Battery

A multi-layered test suite written from four professional perspectives. Each layer is gated: failure of an earlier layer blocks the next.

### 16.1 Layer 1 — Software Developer: Unit tests for new code

Goal: every new function has tests that verify correctness in isolation.

**`tests/unit/test_embedding_service.py`** (≥ 12 tests)

| # | Test | Asserts |
|---|---|---|
| 1 | `test_embed_returns_correct_dimension_openai` | `len(embed("hello")) == 1536` when MODEL_PROVIDER=openai |
| 2 | `test_embed_returns_correct_dimension_local` | `len(embed("hello")) == 768` when MODEL_PROVIDER=local |
| 3 | `test_embed_batch_preserves_order` | `embed_batch(["a","b","c"])[i]` corresponds to input `i` |
| 4 | `test_embed_caches_in_redis` | Second call to `embed("x")` makes 0 API calls |
| 5 | `test_embed_cache_ttl_24h` | Redis TTL on `cache:embed:*` is between 86000 and 86500 seconds |
| 6 | `test_embed_retries_on_transient_failure` | 503 then 200 → returns vector after 1 retry |
| 7 | `test_embed_raises_after_3_retries` | 503 × 4 → raises `EmbeddingServiceError` |
| 8 | `test_dimension_property_matches_provider` | `.dimension == 1536` for openai, `768` for local |
| 9 | `test_embed_empty_string_raises` | `embed("")` raises ValueError |
| 10 | `test_embed_very_long_text_truncated` | `embed("a" * 100000)` does not raise; truncated to model's max tokens |
| 11 | `test_embed_unicode_handled` | `embed("室温")` succeeds without UnicodeError |
| 12 | `test_provider_switch_clears_cache` | Switching MODEL_PROVIDER invalidates cached embeddings |

**`tests/unit/test_capability_indexer.py`** (≥ 14 tests)

| # | Test | Asserts |
|---|---|---|
| 1 | `test_first_index_creates_collection` | `capability_bldg1` collection created in Qdrant |
| 2 | `test_unchanged_yaml_skips_reindex` | Restart → 0 embedding calls when YAML SHA matches |
| 3 | `test_changed_yaml_rebuilds_collection` | New SHA → old collection deleted, new one created |
| 4 | `test_point_count_matches_keyword_sum` | For each entry: `points = len(keywords) + 1` |
| 5 | `test_yaml_sha_recorded_in_payload` | Every point's `payload.yaml_sha` matches the file's SHA |
| 6 | `test_uuid_v5_deterministic` | Reindexing same entry produces same point IDs |
| 7 | `test_missing_yaml_returns_degraded` | Building without `capability.yaml` → `IndexResult(status="degraded")` |
| 8 | `test_malformed_yaml_returns_degraded` | Invalid YAML → no crash, degraded result, helpful error message |
| 9 | `test_qdrant_unreachable_returns_degraded` | Qdrant down → degraded result; startup still succeeds |
| 10 | `test_embedding_api_down_returns_degraded` | OpenAI 503 × 4 → degraded; orchestrator boots |
| 11 | `test_dim_mismatch_rebuilds` | Existing collection has dim=1536, current provider gives dim=768 → rebuild |
| 12 | `test_multiple_buildings_isolated` | Indexing bldg1 does not affect bldg2's points |
| 13 | `test_batch_upsert_used_for_efficiency` | `embed_batch` called once per entry, not once per keyword |
| 14 | `test_index_skips_disabled_buildings` | `capability_routing.enabled: false` → no collection created |

**`tests/unit/test_semantic_router.py`** (≥ 16 tests)

| # | Test | Asserts |
|---|---|---|
| 1 | `test_high_score_returns_capability_intent` | score=0.90 → `intent="capability"`, source=semantic |
| 2 | `test_medium_score_returns_no_intent` | 0.65 < score < 0.85 → `intent=None`, caller decides |
| 3 | `test_low_score_returns_no_intent` | score=0.40 → `intent=None` |
| 4 | `test_matches_grouped_by_entry_id` | Multi-vector hits collapsed to distinct entries |
| 5 | `test_max_pool_score_per_entry` | Entry with hits [0.7, 0.8, 0.9] → group_score=0.9 |
| 6 | `test_disabled_returns_source_disabled` | Config `enabled: false` → `source="disabled"`, score=0.0 |
| 7 | `test_qdrant_down_returns_source_fallback` | Qdrant 500 → `source="fallback"`, score=0.0 |
| 8 | `test_collection_missing_returns_source_disabled` | No `capability_bldg2` → `source="disabled"` for bldg2 |
| 9 | `test_per_building_threshold_honored` | bldg1.threshold=0.65, bldg2.threshold=0.80 — same query different intent decision |
| 10 | `test_top_k_respected` | `top_k=3` → returns at most 3 entries |
| 11 | `test_register_intent_extension_hook` | `router.register_intent("test", "test_")` stored in `_intents` |
| 12 | `test_embedding_failure_returns_fallback` | EmbeddingService raises → `source="fallback"` |
| 13 | `test_empty_query_returns_no_intent` | `classify("")` → `score=0.0`, `intent=None` (no crash) |
| 14 | `test_query_with_only_punctuation` | `classify("???")` → no crash, low score |
| 15 | `test_unicode_query_works` | Non-ASCII query routes correctly when matching content exists |
| 16 | `test_concurrent_classify_safe` | 100 concurrent `classify()` calls all return correct results (no shared-state bug) |

**`tests/unit/test_capability_schema.py`** (≥ 8 tests, augmenting existing)

| # | Test | Asserts |
|---|---|---|
| 1 | `test_capability_routing_config_defaults` | Missing block → `threshold=0.65`, `override_min=0.85`, `top_k=5`, `enabled=true` |
| 2 | `test_invalid_threshold_rejected` | `threshold: 1.5` → ValidationError |
| 3 | `test_threshold_above_override_min_rejected` | `threshold: 0.9, override_min: 0.8` → ValidationError (logically invalid) |
| 4 | `test_negative_top_k_rejected` | `top_k: -1` → ValidationError |
| 5 | `test_embedding_model_auto_resolves_to_provider` | `embedding_model: auto` → resolved at runtime via MODEL_PROVIDER |
| 6 | `test_existing_capability_yaml_unchanged` | All 32 entries in bldg1 still validate with the existing schema |
| 7 | `test_search_method_removed` | `hasattr(CapabilityKB, "search") == False` after Phase 3 |
| 8 | `test_load_yaml_with_no_routing_block` | Existing buildings without `capability_routing:` load successfully |

### 16.2 Layer 2 — System Designer: Integration tests

Goal: components work correctly together. State propagation, service boundaries, lifecycle.

**`tests/integration/test_capability_e2e.py`** (≥ 12 tests)

| # | Test | Asserts |
|---|---|---|
| 1 | `test_lift_dimensions_routes_to_capability` | The exact query that failed today returns `lift_accessibility_detail` content |
| 2 | `test_synonym_query_matches` | "How big is the elevator?" → `lift_accessibility_detail` (no keyword would have matched) |
| 3 | `test_floor_word_does_not_steal_capability` | "Which floors have accessible toilets?" → capability, not floor_plan |
| 4 | `test_sensor_query_not_hijacked_by_capability` | "What is the CO2 level on floor 3?" → sensor_data, NOT capability |
| 5 | `test_capability_match_propagated_to_state` | `state.intermediate_results["capability_matches"]` populated when score ≥ threshold |
| 6 | `test_capability_agent_uses_pre_fetched_matches` | `CapabilityAgent.handle()` does 0 KB searches when matches are pre-populated |
| 7 | `test_capability_agent_fallback_when_no_matches` | If `capability_matches` missing (e.g. flag off), agent falls back to `_load_kb()` + legacy lookup |
| 8 | `test_feature_flag_off_is_byte_identical` | With flag off, all 70 survey responses byte-equal pre-refactor responses |
| 9 | `test_startup_no_capability_yaml_for_one_building` | bldg with no YAML → `IndexResult(status="degraded")`, but bldg1 still indexes |
| 10 | `test_multi_building_isolation` | bldg2 query never returns bldg1 entries (collection-scoped) |
| 11 | `test_unchanged_yaml_startup_idempotent` | Two consecutive restarts → exactly the same points in Qdrant, 0 embedding calls on 2nd |
| 12 | `test_yaml_edit_triggers_rebuild` | Modify YAML → restart → new entries searchable, old removed entries 404 |

**`tests/integration/test_non_regression_intents.py`** — one test per intent (16 tests minimum)

For each of the 16 intents listed in §15.1, send one canonical query and assert:
- Correct intent classification
- Correct routing through the workflow
- Response contains expected markers (e.g., temperature reading, KB content, floor plan image URL)
- Latency within 2× current baseline

**`tests/integration/test_floor_n_protection.py`** — one test per case in §15.2 (4 tests)

| Test | Query | Asserts |
|---|---|---|
| 1 | "What is the temperature on floor 3?" | Routes to sparql, response contains a temperature reading |
| 2 | "Show me analytics for floor 2 sensors" | Routes to analytics, response contains a numeric summary |
| 3 | "How many CO2 sensors are on floor 1?" | Routes to sparql, response contains a count |
| 4 | "Compare energy usage on floor 1 vs floor 3" | Routes to comparison, response contains a comparison structure |

### 16.3 Layer 3 — Professional Tester: Edge case & adversarial tests

Goal: prove the system survives weird inputs, race conditions, and intentional abuse.

**`tests/edge/test_capability_edge_cases.py`** (≥ 14 tests)

| # | Test | Input | Asserts |
|---|---|---|---|
| 1 | Empty query | `""` | HTTP 422 (Pydantic validation), no crash |
| 2 | Whitespace-only query | `"   "` | Clarification response, no crash |
| 3 | Single-char query | `"?"` | Clarification or general, no crash |
| 4 | 2000-char query | `"a" * 2000` | Handled (Pydantic max_length); not 500 |
| 5 | SQL injection attempt | `"'; DROP TABLE sensors; --"` | Treated as natural language; no DB error; response is grounded English |
| 6 | XSS attempt | `"<script>alert(1)</script>"` | Treated as text; response escapes any echo |
| 7 | Non-English query | `"Quelle est la dimension de l'ascenseur?"` | Either responds in English or detects clarification — no crash |
| 8 | Unicode emoji query | `"🚪 lift 🛗"` | No UnicodeError; semantic router handles |
| 9 | Score exactly at threshold | Score = 0.65 (mock) | Inclusive: counts as match |
| 10 | Score exactly at override_min | Score = 0.85 (mock) | Inclusive: overrides LLM |
| 11 | Score just below threshold | Score = 0.649 | NO match; falls through to LLM |
| 12 | Concurrent identical queries | 100 × same query in parallel | All 100 get correct response; Redis embed cache prevents stampede |
| 13 | Concurrent different queries | 100 × different queries | All routed correctly; no shared state corruption |
| 14 | Qdrant connection drops mid-query | Force Qdrant disconnect | Single query: `source="fallback"`, response still returned (LLM-only intent) |

**`tests/edge/test_idempotency.py`** (≥ 5 tests)

| # | Test | Asserts |
|---|---|---|
| 1 | `test_5_consecutive_restarts_no_reembed` | 5 × `docker-compose restart` → 1st triggers indexing, 2nd–5th call 0 embedding APIs |
| 2 | `test_uuid_v5_collision_safe` | 1000 entries with same keywords across different buildings → no UUID collisions |
| 3 | `test_partial_index_failure_recoverable` | Kill orchestrator mid-indexing → next restart completes indexing |
| 4 | `test_concurrent_indexer_safe` | Spawn 2 indexers on same building → idempotent, no duplicate points |
| 5 | `test_yaml_save_during_indexing` | Edit YAML while indexer running → next restart picks up the edit |

**`tests/edge/test_threshold_sensitivity.py`** (≥ 6 tests)

Run the same set of 20 ambiguous queries against thresholds [0.50, 0.60, 0.65, 0.70, 0.75, 0.80]. Record:
- False positives (non-capability query → capability route)
- False negatives (capability query → other route)
- Confusion matrix for each threshold

Asserts: chosen default (0.65) sits at the F1-score maximum across the test corpus.

### 16.4 Layer 4 — Semantic Web Engineer: Ontology & RAG integrity

Goal: prove the semantic web layer (Brick Schema, GraphDB, RAG service) is unaffected.

**`tests/semantic/test_ontology_integrity.py`** (≥ 8 tests)

| # | Test | Asserts |
|---|---|---|
| 1 | `test_sparql_endpoint_unchanged` | `POST graphdb:7200/repositories/ontosage/sparql` with canonical query returns same result before/after refactor |
| 2 | `test_brick_schema_classes_unchanged` | Sensor type count from `SELECT DISTINCT ?class WHERE { ?inst a ?class }` matches baseline |
| 3 | `test_sensor_uuid_lookup_unchanged` | `SELECT ?uuid WHERE { ?s rdfs:label "..." ; brick:hasExternalReference/brick:hasTimeseriesId ?uuid }` returns same UUIDs |
| 4 | `test_zone_hierarchy_traversal` | `hasPart` traversal from building → floors → rooms → sensors returns same shape |
| 5 | `test_discovery_intent_still_uses_graphdb` | "What sensor types exist?" → SPARQL agent reads GraphDB (not capability KB) |
| 6 | `test_rag_fallback_still_triggers` | SPARQL empty result → `hybrid_retrieval.py` runs against rag-service (not capability collection) |
| 7 | `test_floor_plans_qdrant_collection_untouched` | `floor_plans` collection point count unchanged before/after refactor |
| 8 | `test_user_memory_qdrant_collection_untouched` | `user_memory` collection point count unchanged |

**`tests/semantic/test_capability_semantic_quality.py`** (≥ 10 tests)

Goal: validate that semantic recall is genuinely better than substring recall.

| # | Test | Query (synonym/paraphrase) | Expected entry | Old (keyword) result | New (semantic) result |
|---|---|---|---|---|---|
| 1 | Synonym | "elevator capacity" | `lift_accessibility_detail` | MISS | HIT |
| 2 | Synonym | "wheelchair access to floors" | `lift_accessibility_detail` | MISS | HIT |
| 3 | Paraphrase | "where can I shower in this building?" | `shower_facilities_detail` | MISS | HIT |
| 4 | Paraphrase | "is there a changing table for infants?" | `toilet_facilities_by_floor` | MISS | HIT |
| 5 | Paraphrase | "do you offer secure cycle storage?" | `bicycle_parking_detail` | MISS | HIT |
| 6 | Paraphrase | "what time can I sign in at the front desk?" | `reception_and_hours` | MISS | HIT |
| 7 | Question form | "is location data being collected on me?" | `data_privacy_gdpr` | HIT (existing) | HIT (must not regress) |
| 8 | Question form | "what happens if the power goes out?" | `power_resilience` | HIT (existing) | HIT (must not regress) |
| 9 | Off-domain | "what is the airspeed of an unladen swallow?" | (no entry) | MISS | MISS (low score, fall through to general) |
| 10 | Adversarial | "fire alarm temperature sensor" (mixed-topic) | Should route to highest-score entry, NOT trigger BOTH capability+sensor_data | One route only | One route only |

A passing run produces a markdown report `tests/semantic/recall_report.md` showing the recall delta — this is the artefact that proves the refactor was worth doing.

### 16.5 Layer 5 — Performance & resilience

| # | Test | Target |
|---|---|---|
| 1 | `test_cold_query_latency` | p50 cold query: ≤ current p50 + 80ms (one embedding API call) |
| 2 | `test_warm_query_latency` | p50 warm query (embed cached): ≤ current p50 − 200ms (skipped LLM call) |
| 3 | `test_high_confidence_skips_llm_call` | LLM call count = 0 for high-confidence capability queries |
| 4 | `test_qdrant_query_p99_under_50ms` | Qdrant search latency p99 ≤ 50ms |
| 5 | `test_no_memory_leak_over_1000_queries` | RSS growth ≤ 100MB over 1000 queries |
| 6 | `test_redis_embed_cache_hit_rate` | After warm-up, embed cache hit rate ≥ 80% |
| 7 | `test_circuit_breaker_protects_embedding_api` | OpenAI 503 × N → circuit opens; semantic router returns fallback without further API attempts |

## 17. Validation Protocol

Exact commands and gates the implementer runs at each phase. No phase advances until its gate passes.

### 17.1 Pre-flight baseline (run BEFORE any code change)

Capture the current behaviour as the ground-truth baseline. All subsequent comparisons go against this.

```bash
# 1. Capture current survey baseline
python scripts/survey_live_test.py > tests/baselines/survey_pre_refactor.txt
# Required: 70/70 PASS

# 2. Capture current test suite state
pytest tests/ -v --tb=short -q > tests/baselines/pytest_pre_refactor.txt
# Required: no new failures vs. last green main

# 3. Capture latency baseline (200 queries, mixed intents)
python scripts/latency_baseline.py --queries 200 > tests/baselines/latency_pre_refactor.json

# 4. Snapshot Qdrant collection sizes
curl -s http://localhost:6333/collections | python -m json.tool > tests/baselines/qdrant_pre_refactor.json

# 5. Snapshot GraphDB repository state
curl -s http://localhost:7200/rest/repositories > tests/baselines/graphdb_pre_refactor.json
```

Gate: all 5 baselines captured. Survey baseline = 70/70. No green-main pytest regressions.

### 17.2 Phase 1 gate — Code lands behind disabled flag

After implementing all new code with `CAPABILITY_SEMANTIC_ROUTING_ENABLED=false`:

```bash
# A. Run full unit-test layer (§16.1)
pytest tests/unit/ -v -k "embedding_service or capability_indexer or semantic_router or capability_schema" -q

# B. Run integration tests with flag OFF
CAPABILITY_SEMANTIC_ROUTING_ENABLED=false pytest tests/integration/ -v -q

# C. Re-run survey test with flag OFF
CAPABILITY_SEMANTIC_ROUTING_ENABLED=false python scripts/survey_live_test.py > tests/results/survey_phase1_flag_off.txt

# D. Diff against pre-flight baseline
diff tests/baselines/survey_pre_refactor.txt tests/results/survey_phase1_flag_off.txt
# Required: byte-identical (proves flag-off is non-disruptive)
```

Gate: A & B all pass. C = 70/70. D = empty diff.

### 17.3 Phase 2 gate — Flag enabled, survey + regression

Toggle `CAPABILITY_SEMANTIC_ROUTING_ENABLED=true`:

```bash
# A. Re-run survey test with flag ON
CAPABILITY_SEMANTIC_ROUTING_ENABLED=true python scripts/survey_live_test.py > tests/results/survey_phase2_flag_on.txt
# Required: ≥ 70/70

# B. Run synonym/paraphrase recall tests (§16.4)
pytest tests/semantic/test_capability_semantic_quality.py -v
# Required: ≥ 8/10 new HIT cases (synonyms that previously MISS)

# C. Run non-regression intent tests (§16.2)
pytest tests/integration/test_non_regression_intents.py -v
# Required: 16/16

# D. Run floor-N protection tests (§16.2)
pytest tests/integration/test_floor_n_protection.py -v
# Required: 4/4

# E. Run edge case suite (§16.3)
pytest tests/edge/ -v
# Required: all PASS

# F. Run semantic web integrity tests (§16.4)
pytest tests/semantic/test_ontology_integrity.py -v
# Required: 8/8

# G. Run performance suite (§16.5)
pytest tests/perf/ -v
# Required: all latency targets met
```

Gate: A ≥ 70/70. B ≥ 8/10. C = 16/16. D = 4/4. E all pass. F = 8/8. G all targets met.

### 17.4 Phase 3 gate — Cleanup deletes legacy code

After deleting `_CAPABILITY_KW`, `_STRONG_FACILITY_KW`, `CapabilityKB.search()`, override blocks, and the feature flag:

```bash
# A. grep proves keyword frozensets are gone
! grep -rn "_CAPABILITY_KW\|_STRONG_FACILITY_KW" orchestrator/ shared/
# Required: no matches

# B. grep proves search() method is gone
! grep -n "def search" shared/capability_schema.py
# Required: no matches

# C. grep proves feature flag is gone
! grep -rn "CAPABILITY_SEMANTIC_ROUTING_ENABLED" orchestrator/ shared/
# Required: no matches

# D. Full test suite still passes
pytest tests/ -v -q

# E. Final survey baseline
python scripts/survey_live_test.py > tests/results/survey_phase3_final.txt
# Required: ≥ 70/70
```

Gate: A, B, C all return non-zero exit (grep finds nothing). D = all pass. E ≥ 70/70.

### 17.5 Continuous monitoring (post-merge)

For 7 days after Phase 3 merge:

- Dashboard panel: capability intent classification distribution (semantic vs LLM-fallback vs other)
- Dashboard panel: embedding API latency p50 / p95 / p99
- Dashboard panel: Qdrant search latency p50 / p95 / p99
- Alert: capability intent fallback rate > 5% → page on-call
- Alert: embedding API error rate > 1% → page on-call
- Alert: capability collection point count drops > 10% unexpectedly → page on-call

If any alert fires within the 7-day window: investigate, fix, or roll back via the feature flag (which still exists in Phase 2; if already Phase 3, revert the PR).
