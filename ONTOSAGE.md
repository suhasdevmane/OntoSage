# OntoSage — System Reference (post-Phase-17)

**Comprehensive technical reference for the OntoSage agentic-AI framework for smart buildings.** This document covers the architecture, every Phase 11-17 improvement, the routing pipeline, the multi-tenant / multi-persona / multi-intent model, the operational surface (configuration, swap workflow, CI), the test coverage, and known issues — accurate as of 2026-05-29.

Two-line summary: A user types a question in plain English. OntoSage classifies the intent, blends the user's stacked personas, routes to the right pipeline (SPARQL → SQL → analytics, or floor-plan, or capability KB, or one of the standalone agents), and returns a structured answer with full per-request audit trail.

---

## 1. What it is

OntoSage is an open-source agentic-AI orchestration layer for one smart building at a time. It connects:

- An **ontology graph** (Brick Schema + BACnet TTL in GraphDB) — *what sensors and zones exist*
- A **time-series store** (MySQL today; pluggable to Postgres/Timescale/Influx) — *what readings they emit*
- **Floor plans** (PDF + AutoCAD DWG) — *what the building looks like and where rooms are*
- A **capability knowledge base** (YAML) — *policies, amenities, contacts that aren't in the ontology*

…and exposes a single HTTP `POST /chat` endpoint that returns natural-language answers, structured reports, exports, or visualizations.

The next major release (Onto-community) will support multiple simultaneous buildings. Today's release (v1) serves one building at a time, with the per-building infrastructure already in place as forward compatibility.

---

## 2. Architecture

### 2.1 Hub-and-spoke LangGraph

`orchestrator/workflow/` (a Python package post Phase 17) defines a LangGraph state machine. Every request flows through:

```
              POST /chat
                  │
                  ▼
          ┌───────────────┐
          │   dialogue    │  ← LLM classifies intent + extracts entities
          └───────┬───────┘
                  │  _route_from_dialogue (Python)
                  ▼
  ┌───────┬──────┬──────┬───────┬───────┬───────┬───────┬──────┐
  │       │      │      │       │       │       │       │      │
sparql  capability floor_plan spatial control maintenance export planner
  │      │       │       │       │       │       │       │
  ▼      ▼       ▼       ▼       ▼       ▼       ▼       ▼
  sql    ┕──────────────────┬───────────────────────────────┘
  │                         │
  ▼                         │
 analytics ───► visualization
  │
  ▼
 response  ← exit; formats final answer, persists conversation
```

The 17 graph nodes auto-register from `orchestrator/intents/intent_definitions.yaml` (see Phase 13B). Shared pipeline stages (`dialogue`, `sparql`, `sql`, `analytics`, `response`) and downstream-only nodes (`anomaly`, `report`, `document`) are hardcoded because they aren't 1:1 with any intent.

### 2.2 Source layout (post Phase 17)

```
orchestrator/
├── workflow/                       # Phase 17 — was a single 3,220-line file
│   ├── __init__.py                 #   25 lines — re-exports WorkflowOrchestrator
│   ├── _orchestrator.py            # 3,012 lines — node implementations + _route_from_dialogue
│   ├── _graph.py                   #  187 lines — WorkflowGraphMixin._build_graph
│   └── _routing.py                 #  115 lines — WorkflowRoutingMixin (4 downstream routes)
├── intents/                        # Phase 6+13 — intent registry & YAML
│   ├── __init__.py
│   ├── registry.py                 # IntentDefinition, IntentRegistry, route_target_for()
│   └── intent_definitions.yaml     # 22 intents — single source of truth
├── agents/                         # one file per agent (16 agents)
│   ├── dialogue_agent.py           # LLM intent classification + entity extraction
│   ├── sparql_agent.py             # SPARQL generation + execution + ContextVar bctx (Phase 15A)
│   ├── sql_agent.py                # Time-series fetch
│   ├── analytics_agent.py          # Code-executor sandboxed analysis
│   ├── floor_plan_agent.py
│   ├── spatial_agent.py
│   ├── capability_agent.py
│   ├── report_agent.py
│   ├── anomaly_agent.py
│   ├── export_agent.py
│   ├── visualization_agent.py
│   ├── planner_agent.py
│   ├── control_agent.py
│   ├── maintenance_agent.py
│   ├── document_agent.py
│   └── verifier_agent.py
├── services/
│   ├── building_context.py         # Phase 10/11A — BuildingContextResolver
│   ├── building_registry.py        # Discovers input/<bldg>/building.yaml
│   ├── ttl_validator.py            # Phase 12B — TTL prefix/namespace consistency check
│   ├── ttl_uploader.py             # Phase 3 — idempotent TTL upload on startup
│   ├── multi_intent_detector.py    # Phase 14 — compound-query decomposition
│   ├── semantic_router.py          # Capability KB semantic routing
│   ├── capability_indexer.py       # Embeds capability.yaml into Qdrant
│   ├── floor_plan_pipeline.py      # PDF → manifest
│   ├── dwg_pipeline.py             # DWG → DXF → polygons
│   ├── floor_plan_registry.py      # Merge PDF + DWG manifests
│   ├── adapters/                   # Storage backend abstraction
│   └── …
├── auth_manager.py                 # Argon2id + Redis sessions (see Known Issues §10)
├── middleware/rbac.py              # 6 roles × 20 permissions
└── main.py                         # FastAPI app + lifespan + endpoints

shared/
├── config.py                       # Settings (Pydantic v2); MULTI_INTENT_MIN_LENGTH=50 (Phase 16A)
├── models.py                       # ConversationState, ChatRequest (with personas: List[str] Phase 14A)
├── persona_registry.py             # PersonaPriors + get_blended_priors() (Phase 14A)
├── persona_loader.py               # YAML overlays from input/_defaults/personas/ + input/<bldg>/personas/
├── pipeline_context.py             # Typed view over intermediate_results
└── floor_plan_config.py            # Per-building DWG/PDF settings

input/
├── _defaults/                      # Phase 11C — operator-editable defaults
│   ├── intents.yaml                # (optional override of orchestrator/intents/intent_definitions.yaml)
│   └── personas/                   # (optional override of shipped persona priors)
├── bldg1/                          # The ACTIVE building's data (one at a time)
│   ├── building.yaml               # building_id, name, ontology_namespace, building_prefix, …
│   ├── capability.yaml             # off-ontology KB (lifts, prayer room, fire, …)
│   ├── intents.yaml                # per-building intent overlay
│   ├── personas/                   # per-building persona overlay
│   └── *.ttl, *.dwg, *.pdf
└── bldg1_*.ttl                     # legacy root-level TTL layout (still supported)

scripts/
├── swap_building.py                # Phase 12C — safe building swap CLI
├── onboard_building.py             # Legacy onboarding flow
└── survey_live_test.py             # 95-query regression survey

tests/                              # 225 deterministic tests; see §9
├── fixtures/buildings/bldg2/       # Phase 12A — fixture for multi-tenant tests
└── …                               # 13 test files in CI

.github/workflows/ci.yml            # Phase 16C — runs all 13 deterministic test files
```

### 2.3 Storage layer

| Store | Port | Purpose |
|---|---|---|
| **GraphDB** | 7200 | RDF ontology (Brick/BACnet TTL). Used by SPARQL agent. |
| **MySQL** | 3306 | Time-series sensor readings, keyed by UUID. |
| **PostgreSQL** | 5433 | User accounts, Argon2id password hashes, RBAC. |
| **Redis** | 6379 | Conversation state (1h TTL), response cache (`resp_cache:*`), session salt (see §10). |
| **Qdrant** | 6333 | `floor_plans` (room vectors + geometry payload), `capability_<bldg>` (KB embeddings), `user_memory`. |
| **MongoDB** | 27017 | Full chat-history transcripts (OpenWebUI). |
| **rag-service** | 8001 | Semantic fallback for empty SPARQL results. |
| **code-executor** | 8002 | Sandboxed Python for analytics agent. |

### 2.4 LLM / embedding provider

`shared/config.py` is the single switch via `MODEL_PROVIDER`:

- `openai` → OpenAI API (gpt-5.4 complex, gpt-4o-mini fast)
- `local` → Ollama at `http://ollama:11434` (default `deepseek-r1:32b`)
- `cloud` → Ollama Cloud

Embedding: `EMBEDDING_PROVIDER` independently selects `openai` (1536-d `text-embedding-3-small`) or `local` (384-d `sentence-transformers/all-MiniLM-L6-v2`). The capability indexer auto-rebuilds its Qdrant collection if the embedding dim changes between restarts.

---

## 3. The 22 Intents

All intents live in `orchestrator/intents/intent_definitions.yaml`. Each has `name`, `description`, `examples`, `pipeline_group` (`data` | `standalone` | `meta`), optional `route_target`, optional `node_method` (Phase 13B), optional `aliases`, optional `cacheable`.

| Intent | Pipeline group | Default route | Node method |
|---|---|---|---|
| `general` | meta | response | — (shared infra) |
| `greeting` | meta | response | — |
| `clarification` | meta | response | — |
| `planner` | meta | planner | `_planner_node` |
| `metadata` | data | sparql | — |
| `discovery` | data | sparql | — |
| `sensor_data` | data | sparql | — |
| `analytics` | data | sparql | — |
| `compare` (alias `comparison`) | data | sparql | — |
| `trend` | data | sparql | — |
| `recommend` | data | sparql | — |
| `anomaly` | data | sparql | — (downstream node: `_anomaly_node`) |
| `report` | data | **planner** (override) | — (downstream node: `_report_node`) |
| `export` | data | **export** (override) | `_export_node` |
| `compliance` | data | sparql | — |
| `visualization` | data | **visualization** (override) | `_visualization_node` |
| `floor_plan` | standalone | floor_plan | `_floor_plan_node` |
| `spatial_query` | standalone | spatial_query | `_spatial_query_node` |
| `capability` | standalone | capability | `_capability_node` |
| `control` | standalone | control | `_control_node` |
| `maintenance` | standalone | maintenance | `_maintenance_node` |
| `lab_booking` | standalone (bldg1 overlay) | (no node → safety net) | — |

The `route_target_for(intent_name)` resolver in `intents/registry.py:485` returns the explicit `route_target` if set, otherwise applies pipeline-group defaults (`data`→`sparql`, `standalone`→intent name, `meta`→`response`).

---

## 4. The routing pipeline

### 4.1 Decision flow

```
LLM dialogue_agent classifies intent
            │
            ▼
_route_from_dialogue (workflow/_orchestrator.py)
            │
   ┌────────┴────────────────────────┐
   │ Contextual overrides (4)        │
   │  1. floor_plan ↔ comparison     │
   │     (compare+data keywords)     │
   │  2. floor_plan keyword detect   │
   │     (when not in data intents)  │
   │  3. discovery + spatial words   │
   │     → sparql (not response)     │
   │  4. analytics-family +          │
   │     cached data → analytics     │
   └────────┬────────────────────────┘
            │
            ▼
   registry.route_target_for(intent)
            │
            ▼
   Phase 10G safety net:
   if target not in registered nodes →
     "response" + polite dialogue_response
            │
            ▼
   LangGraph dispatches to the node
            │
            ▼
   Per-turn state.intermediate_results["route_decision"] =
     { intent_from_dialogue, intent_after_overrides,
       overrides_applied, final_node, decision_source }
```

### 4.2 Routing diagnostics (Phase 13A)

Every routing decision writes a structured record to `state.intermediate_results["route_decision"]`:

```python
{
    "intent_from_dialogue": "floor_plan",
    "intent_after_overrides": "comparison",
    "overrides_applied": ["floor_plan_to_comparison_keywords"],
    "final_node": "sparql",
    "decision_source": "override",   # 'registry' | 'override' | 'fallback'
}
```

Inspect via the saved Redis state or via `tests/test_routing_accuracy.py` (29 canonical cases that pin the contract).

### 4.3 Smart Python ↔ Agent split

The user asked "should routing be in Python or by the agent?" The answer is **both, layered**:

- **LLM dialogue_agent** picks the *intent label* (context-aware, persona-informed via Phase 16B)
- **Python `_route_from_dialogue`** turns the label into a *graph node* (deterministic, audit-logged)
- **4 contextual overrides** catch known LLM weak spots (floor_plan/compare confusion, etc.)
- **Safety net** prevents YAML-added intents without nodes from crashing LangGraph

This gives the smartness of LLM classification with the determinism and observability of Python routing.

---

## 5. Multi-tenant / multi-persona / multi-intent

### 5.1 Multi-tenant (forward-compat for Onto-community)

v1 serves one building at a time via `BUILDING_ID`. The code is already multi-tenant ready:

| Mechanism | Where | Phase |
|---|---|---|
| `IntentRegistry` keyed by `building_id` via `lru_cache` | `intents/registry.py:509` | 11A |
| `BuildingContextResolver.resolve(building_id)` | `services/building_context.py` | 10A/11A |
| Per-building Qdrant collection (`capability_<bldg>`) | `services/capability_indexer.py` | 5/14 |
| Per-building persona overlays (`input/<bldg>/personas/`) | `shared/persona_loader.py` | 5/11C |
| Per-request SPARQL ContextVar | `agents/sparql_agent.py` | 15A |
| Storage adapter filter (`storage.databases` in `building.yaml`) | `services/adapters/registry.py` | 2 |

All run identically when only one building exists — no overhead.

### 5.2 Multi-persona blending (Phase 14A + 16B)

A single turn can stack multiple personas:

```jsonc
POST /chat
{
  "message": "what should I look at this week?",
  "session_id": "...",
  "personas": ["facility_manager", "sustainability_officer"]
}
```

The `PersonaRegistry.get_blended_priors(personas)` merges:

| Field | Blend rule |
|---|---|
| `top_domains` | Rank-vote (1st=8pts, 2nd=7pts, …); ties keep first-encountered persona's order |
| `borda_topics` | Same rank-voting |
| `lookup_share` | Arithmetic mean |
| `default_complexity` | Max of `{SIMPLE < MODERATE < COMPLEX}` |
| `clarification_threshold` | Min (more willing to clarify) |

The blended priors are surfaced to the LLM intent prompt (Phase 16B):

```
=== USER PERSONA HINTS (informs classification) ===
Active persona(s): facility_manager, researcher
Priority domains (break ties on ambiguous intent): ENERGY, THERMAL, OCCUPANCY, FIRE_SAFETY, AIR_QUALITY
Expected answer depth: COMPLEX
Clarification threshold: 0.60
```

Backward-compatible: legacy `persona: "facility_manager"` (single string) still works. When `personas` is present, it takes precedence; `state.persona` is back-filled with `personas[0]`. The `Literal[...]` constraint on `persona` was relaxed to `str` so YAML-added personas resolve without code changes.

### 5.3 Multi-intent decomposition (Phase 14B + 16A)

A single user message can mix multiple intents:

```
"show me floor 3 layout and also tell me how many rooms are there"
```

The two-stage gate:

1. **Heuristic** (`MultiIntentDetector._passes_heuristic`):
   - length ≥ `MULTI_INTENT_MIN_LENGTH` (default **50 chars**, lowered from 80 in Phase 16A)
   - contains an explicit connective from `_CONNECTIVE_PHRASES` (`"and also"`, `"tell me"`, `"1."`, `"first/then/finally"`, etc.)
   - keywords from ≥ 2 distinct `INTENT_DOMAINS` sets
2. **LLM decomposition**: returns 2–5 sub-intents validated against `VALID_INTENTS`.

When triggered, `state.current_intent` is rewritten to `"planner"` and the enhanced PlannerAgent fans out each sub-intent. The example decomposes to:

```python
[SubIntent(intent="floor_plan",    sub_query="floor 3 layout"),
 SubIntent(intent="spatial_query", sub_query="how many rooms on floor 3")]
```

Feature flag: `settings.MULTI_INTENT_ENABLED` (default `True`).

---

## 6. Adding stuff (the YAML-only path)

Phase 13B made adding intents/personas/buildings code-free:

### 6.1 Add a new intent

```yaml
# orchestrator/intents/intent_definitions.yaml  (or input/<bldg>/intents.yaml)
- name: my_intent
  description: |-
    What this intent handles. Include trigger phrases.
  examples:
    - '"trigger query 1"'
    - '"trigger query 2"'
  pipeline_group: standalone           # data | standalone | meta
  route_target: my_node                # optional override; defaults via pipeline_group
  node_method: _my_node_fn             # method on WorkflowOrchestrator
```

```python
# orchestrator/workflow/_orchestrator.py
async def _my_node_fn(self, state: ConversationState) -> ConversationState:
    """One-line description."""
    state.intermediate_results["my_result"] = ...
    return state
```

Restart. Done. Outgoing edges, conditional routing, and graph wiring auto-generated by Phase 13B.

### 6.2 Add a new persona

Drop a YAML into `input/_defaults/personas/` (operator default) or `input/<bldg>/personas/` (per-building override):

```yaml
# input/<bldg>/personas/safety_officer.yaml
name: safety_officer
description: Fire safety officer
top_domains: [FIRE_SAFETY, OCCUPANCY, THERMAL]
lookup_share: 0.70
default_complexity: MODERATE
clarification_threshold: 0.40
borda_topics: [Fire Safety, Occupancy, Air Quality, Temperature, Energy]
aliases: [fire_officer, safety]
```

No code changes needed.

### 6.3 Swap to a new building

```bash
# 1. Drop new building's files under input/<new_id>/
#    Required: building.yaml, *.ttl (@prefix bldg: must match ontology_namespace)
#    Optional: *.dwg, *.pdf, capability.yaml, intents.yaml, personas/

# 2. Dry-run the swap
python scripts/swap_building.py --to bldg2 --dry-run

# 3. Apply (updates .env, optionally archives old input dir, flushes resp_cache)
python scripts/swap_building.py --to bldg2 --archive

# 4. Restart the orchestrator. TTL validator runs first; hard-fails on mismatch.
docker-compose restart orchestrator
docker-compose logs -f orchestrator | grep ttl_validator
```

The swap CLI exits **2** on:
- `input/<new>/` missing
- `building.yaml` missing required keys or `building_id` ≠ directory name
- Any TTL declares `@prefix bldg:` ≠ `ontology_namespace`

---

## 7. Phase 11-17 changelog

This section captures every architectural change since v1.0 (Phase 11 onwards). See `CLAUDE.md` for the operational quick-reference.

### Phase 11 — Multi-tenant intent + SPARQL bctx + `input/_defaults/`

| Sub | Change |
|---|---|
| 11A-1 | `IntentRegistry` `lru_cache(maxsize=None)` keyed by `building_id`; per-building overlays from `input/<bldg>/intents.yaml` |
| 11A-2 | `_route_from_dialogue` passes `state.building_id` to `get_intent_registry()` |
| 11A-3 | `dialogue_agent._build_intent_detection_prompt` passes `building_id` so per-building intents appear in LLM prompt |
| 11B | `sparql_agent._generate_sparql` resolves `bctx` from `building_id`; replaced 5 `settings.BUILDING_*` sites with `bctx.namespace` / `bctx.prefix` |
| 11C | `input/_defaults/intents.yaml` + `input/_defaults/personas/` added to loader search paths |

### Phase 12 — Single-building convention enforcement

| Sub | Change |
|---|---|
| 12A-1 | `input/bldg2/` moved to `tests/fixtures/buildings/bldg2/` (keeps `input/` single-tenant) |
| 12A-2 | `tests/test_multi_tenant_fixture.py` — 5 tests exercise per-building infra against the fixture |
| 12B-1 | `orchestrator/services/ttl_validator.py` — rdflib-based TTL parse + prefix/namespace match + optional Brick SHACL |
| 12B-2 | Hard-fail tier (parse error, prefix mismatch) vs. warn tier (zero triples, SHACL violations) |
| 12B-3 | Wired into orchestrator lifespan BEFORE TTL uploader; halts boot on mismatch |
| 12B-4 | `tests/services/test_ttl_validator.py` — 10 tests (SHACL skipped without brickschema) |
| 12C | `scripts/swap_building.py` — `--to / --from / --dry-run / --archive / --no-cache-flush`; reuses the validator; exit 2 on inconsistency |
| 12D-1 | CLAUDE.md: "Swapping the active building" section |
| 12D-2 | `.env.example`: single-building guidance + `TTL_VALIDATION_SHACL` opt-in |
| 12E | First clean baseline: 92/95 PASS, 0 real FAIL on live survey |

### Phase 13 — Routing diagnostics + registry-driven graph auto-wire

| Sub | Change |
|---|---|
| 13A-1 | `state.intermediate_results["route_decision"]` audit trail emitted on every routing call |
| 13A-2 | `tests/test_routing_accuracy.py` — 29 canonical cases (20 intents + 5 override scenarios + 4 audit invariants) |
| 13B-1 | `IntentDefinition.node_method` field added; 8 intents populated |
| 13B-2 | `_build_graph` iterates `registry.with_node_method()` and auto-registers nodes via `getattr(self, node_method)` |
| 13B-3 | Conditional-edges target dict = `registry.route_targets() ∩ registered_nodes` (filters out YAML-added intents with no node) |
| 13C | **SKIPPED** — moving contextual overrides into the LLM prompt loses determinism without measurable gain |
| 13D | `tests/test_intent_graph_autowire.py` — 5 invariants on the auto-wire contract |
| 13E | CLAUDE.md + `.claude/rules/agent-patterns.md`: adding an intent = 2 steps (down from 5) |

### Phase 14 — Multi-persona + multi-intent

| Sub | Change |
|---|---|
| 14A-1/2 | `PersonaRegistry.get_blended_priors(personas)` with rank-vote merge; `normalize_personas` |
| 14A-3 | `ConversationState.personas: List[str]` field; `ChatRequest.personas`; `Literal[...]` constraint on `persona` dropped to `str` |
| 14A-4 | SPARQL node injects blended `persona_domain_hint` + `persona_blended` diagnostic when `personas` is non-empty |
| 14A-5 | `tests/test_blended_persona.py` — 14 tests (single, blended, conflict, alias, unknown) |
| 14B-1 | `tests/test_compound_query_e2e.py` — 14 tests for `MultiIntentDetector` heuristic + LLM decomposition |
| 14B-2 | Live verification: compound query → `[floor_plan, spatial_query]` → planner |

### Phase 15 — SPARQL ContextVar + swap cache flush + state persistence

| Sub | Change |
|---|---|
| 15A | `_REQUEST_BCTX: ContextVar` in `sparql_agent.py` + `set_request_bctx` / `reset_request_bctx` helpers; `sparql_node` wraps `generate_query` with try/finally; all 7 remaining `settings.BUILDING_*` sites use `_active_namespace()` / `_active_prefix()` |
| 15B-1 | `swap_building.py --no-cache-flush` flag; default = flush only `resp_cache:*` keys (auth sessions preserved) |
| 15B-2 | `tests/test_swap_building.py` — 6 integration tests (happy + 4 failure paths + 1 no-op) |
| 15C | `tests/test_state_persistence.py` — 7 round-trip tests for Pydantic state → JSON → state (incl. legacy state without `personas` field) |
| 15D | flake8 clean across 14 new/edited files |
| 15E | Survey: 92/95 PASS, 0 real FAIL |

### Phase 16 — Threshold tuning + persona-aware prompt + CI expansion

| Sub | Change |
|---|---|
| 16A | `MULTI_INTENT_MIN_LENGTH: 80 → 50`; catches natural compound queries like "show me floor 3 layout and tell me how many rooms" (55 chars). Connective + 2-domain gates prevent false positives |
| 16B | Dialogue agent surfaces blended priors in LLM intent prompt: `top_domains[:5]`, `default_complexity`, `clarification_threshold`. Graceful fallback if PersonaRegistry fails |
| 16C | `.github/workflows/ci.yml` unit-tests step expanded from 1 → 13 test files (timeout raised 60→120s) |
| 16D | 225 deterministic tests pass |

### Phase 17 — `workflow.py` package split

| Sub | Change |
|---|---|
| 17A | `orchestrator/workflow.py` (3,220 lines) → `orchestrator/workflow/` package; `__init__.py` re-exports `WorkflowOrchestrator`; zero external import break |
| 17B | Extracted 4 downstream routing methods (`_route_from_data_node`, `_route_from_analytics_node`, `_route_from_sql`, `_route_from_report`) into `_routing.py` as `WorkflowRoutingMixin` |
| 17C | Extracted `_build_graph` (146 lines) into `_graph.py` as `WorkflowGraphMixin` |
| 17D | MRO: `WorkflowOrchestrator → WorkflowGraphMixin → WorkflowRoutingMixin → object`. 225 tests pass |

**Not extracted (intentional):** `_route_from_dialogue` (497 lines including viz keyword sets), all node implementations, `_safe_node`. They stay in `_orchestrator.py` because pulling them out requires architectural rework that risks the test suite for marginal review benefit. Phase 13B auto-wire already eliminated the worst pain point (graph wiring scattered across the file).

### Phase 18 — Production hardening (auth + base image + PDF backend + DWG geometry)

| Sub | Change |
|---|---|
| 18A — Auth fail-closed | `auth_manager.login` now probes Postgres connectivity (`SELECT 1`) before user lookup. When Postgres is degraded, returns *"Authentication service is temporarily unavailable"* instead of the previous misleading *"Invalid password"*. Verified live by `docker stop postgres-user-data` mid-session |
| 18B — Postgres connect retry | `lifespan` retries connection 5 times with exponential backoff (2→4→8→16→30s). Survives the well-known orchestrator-boots-before-Postgres-healthy race that left `postgres: "not_configured"` in `/health` |
| 18C — Base image CVE remediation | All 7 Dockerfiles moved from `python:3.11-slim-bookworm` → `python:3.12-slim-trixie`. First attempt `3.11-slim-trixie` didn't clear the IDE-flagged 1 critical + 13 high CVEs because the vulns are in Python 3.11 itself (exited active maintenance Oct 2024). Python 3.12 + Debian 13 was the smallest bump that actually cleared the scan |
| 18D — wkhtmltopdf → weasyprint | `wkhtmltopdf` was removed from Debian trixie (dead upstream, unfixed CVEs). `document_builder._render_pdf` now uses **weasyprint** as primary backend (Python-native, in trixie), pdfkit as fallback for legacy bookworm deployments, HTML as last resort. Native deps for weasyprint (libpango / libcairo / libharfbuzz / libgdk-pixbuf / libffi-dev) added to the Dockerfile. Verified live with a 2,612-byte test PDF |
| 18E — libredwg source build | Multi-stage Dockerfile: stage 1 builds `libredwg 0.13.3` from a pinned upstream release with autotools + swig + libpcre2-dev; stage 2 copies the binaries (`dwg2dxf`, `dwg2svg`) + shared library to `/usr/local/`. The runtime image gains ~12 MB; the build cache amortizes the 3-minute compile. After this fix, all 6 Abacws floor DWGs ingest at startup: floor 0 (15 spaces, 2,765.7 m²), floor 1 (34 spaces, 3,008.5 m²), floor 2 (34, 3,617.7), floor 3 (34, 3,618.2), floor 4 (41, 3,743.8), floor 5 (34, 3,616.3). Building total: **20,370.2 m²** — answered by `spatial_query` agent on demand |

**Phase 18 verified:** 225 unit tests pass · live survey **94/95 PASS / 1 WARN / 0 FAIL (99%)** · auth fail-closed verified with `docker stop` · Postgres retry verified by log line `Postgres connected (attempt 1/5)` · weasyprint PDF verified in-container · `dwg2dxf 0.13.3` callable; the persistent **T7-SP2 (area of floor 1) WARN was upgraded to PASS** for the first time in the project's history, taking the Floor Plan/Spatial category to 4/4.

---

## 8. Configuration surface

### 8.1 `.env` (process-global)

| Key | Default | Notes |
|---|---|---|
| `BUILDING_ID` | `bldg1` | The active building. Must match an `input/<dir>/`. |
| `BUILDING_NAME` | `Abacws Building` | Display name in responses |
| `MODEL_PROVIDER` | `openai` | `openai` / `local` / `cloud` |
| `EMBEDDING_PROVIDER` | `openai` | Independent of `MODEL_PROVIDER` |
| `MULTI_INTENT_ENABLED` | `true` | Phase 14 |
| `MULTI_INTENT_MIN_LENGTH` | `50` | Phase 16A |
| `TTL_VALIDATION_SHACL` | `false` | Phase 12B — needs brickschema |

### 8.2 `input/<bldg>/building.yaml` (per-building)

| Field | Required | Notes |
|---|---|---|
| `building_id` | yes | Must match directory name |
| `building_name` | yes | Display name |
| `ontology_namespace` | yes | Must match `@prefix bldg:` in every TTL |
| `building_prefix` | yes | Short SPARQL prefix |
| `building_timezone` | no | IANA tz; defaults to `Europe/London` |
| `floor_plan_aliases` | no | Alt names for PDF/DWG slug → registry key |
| `storage.databases` | no | List of database keys from `config/database_registry.yaml` |
| `capability_routing` | no | Threshold tuning for semantic router |

### 8.3 `input/<bldg>/intents.yaml` (per-building overlay)

Same schema as the shipped `intent_definitions.yaml`. Entries with the same `name` override; new names extend.

### 8.4 `input/<bldg>/personas/<name>.yaml`

Same schema as `PersonaPriors` dataclass. Loaded by `PersonaRegistry` at startup; `Literal[...]` constraint dropped in Phase 14A so any name resolves.

### 8.5 `input/<bldg>/capability.yaml`

```yaml
building_info:
  id: bldg1
  name: Abacws Building
  …

capabilities:
  - id: lift_locations
    category: ACCESSIBILITY
    keywords: [lift, elevator, accessible]
    content: >
      Main passenger lift is located left of reception …
    source: building_management_system
```

---

## 9. Test coverage

### 9.1 Deterministic suite (CI — Phase 16C)

13 files, **225 tests pass, 3 skipped, 0 fail**:

| File | Tests | Coverage |
|---|---|---|
| `test_phase3_4_services.py` | many | Phase 3/4 services (legacy baseline) |
| `test_phase_a_fixes.py` | 44 | Persona + new intents routing (updated for Phase 14A) |
| `test_survey_aligned_phases.py` | 64 | Capability KB + persona + G1 taxonomy + workflow wiring |
| `test_workflow_wiring.py` | 4 | Behavioral wiring contracts (Phase 17-updated) |
| `test_routing_accuracy.py` | 29 | All 20 intents + 5 override scenarios + 4 audit invariants |
| `test_intent_graph_autowire.py` | 5 | Every `node_method` resolves; every registry node in graph |
| `test_unregistered_intent_safety_net.py` | 3 | YAML-added intent with no node → safe fallback |
| `test_multi_tenant_fixture.py` | 5 | bldg2 fixture exercises per-building infra |
| `test_blended_persona.py` | 14 | Persona blending semantics |
| `test_compound_query_e2e.py` | 17 | Multi-intent heuristic + decomposition (incl. Phase 16A short-compound) |
| `test_state_persistence.py` | 7 | ConversationState ↔ JSON round-trip with `personas` |
| `test_swap_building.py` | 6 | swap_building CLI integration (dry-run, apply, mismatch, missing dir, no-op) |
| `services/test_ttl_validator.py` | 10 | TTL parse + prefix/namespace + SHACL gating |

### 9.2 Live e2e suite (NOT in CI — needs running stack)

- `test_capability_e2e.py` — capability KB → answer
- `test_floor_plan_e2e.py` — floor plan API
- `test_non_regression_intents.py` — intent routing against live LLM
- `test_ontology_integrity.py` — discovery → SPARQL → GraphDB

These exercise the full stack and have LLM nondeterminism. Run manually before deploys.

### 9.3 Live survey (`scripts/survey_live_test.py`)

95-question battery covering 16 categories. **Phase 18 + libredwg baseline (2026-05-30):**

```
RESULTS: 94/95 PASS  ·  1 WARN  ·  0 FAIL  ·  (99% clean pass)
Latency: avg 16.7s · median 9.2s · max 71.2s
```

Per-category breakdown:

| Category | Result | Notes |
|---|---|---|
| Temperature (T1) | 4/4 PASS | |
| CO2 / Air Quality (T2) | 4/4 PASS | |
| Humidity (T3) | 2/2 PASS | |
| Anomaly Detection (T4) | 3/3 PASS | |
| Discovery / Ontology (T5) | 5/5 PASS | |
| Analytics (T6) | 4/4 PASS | |
| **Floor Plan / Spatial (T7)** | **4/4 PASS** | **Was 3/4 in every prior baseline; Phase 18 libredwg lifted T7-SP2 (area) and T7-SP3 (adjacency) from WARN to PASS** |
| Capability KB (T8) | 12/12 PASS | |
| Routing edge cases (T9) | 4/4 PASS | |
| Reports / Export (T10) | 4/4 PASS | |
| Persona queries (T11) | 5/5 PASS | |
| Multi-hop reasoning (T12) | 3/3 PASS | |
| Control (must decline) (T13) | 3/3 PASS | |
| Robustness (T14) | 6/6 PASS | |
| Non-tech persona (T15) | 14 PASS / 1 WARN | The 1 WARN is "report broken light" → maintenance agent improvement needed |
| Tech expert (T16) | 17/17 PASS | |

Historical comparison:

| Baseline | PASS | WARN | FAIL | Notes |
|---|---|---|---|---|
| Phase 11A | 92/95 | 2 | 1 | False-positive on legitimate report |
| Phase 13 | 93/95 | 2 | 0 | First clean session |
| Phase 15 | 92/95 | 2 | 1 | False-positive on ASHRAE report |
| Phase 18 + weasyprint | 93/95 | 2 | 0 | T16 went 17/17 |
| **Phase 18 + libredwg (current)** | **94/95** | **1** | **0** | **T7 went 4/4 — first time** |

### 9.4 Live verification (this session)

After all Phase 11-18 work completed, the system was started and exercised as a regular user. Representative queries verified:

| Query | Path exercised | Result |
|---|---|---|
| "What is the current temperature in zone 5.28?" | SPARQL + SQL via Phase 15A ContextVar | Returned the right sensor + UUID |
| "Where is the prayer room?" | Capability KB via Phase 13B auto-wire | Returned location from `bldg1/capability.yaml` |
| "show me floor 3" | Floor plan via Phase 13B auto-wire | Returned PDF link + space list |
| "tell me something" | Phase 10G safety net | Polite SCOPE redirect |
| "what is the capital of France?" | Per-building SCOPE rule | Polite SCOPE redirect |
| "show me floor 3 layout and also tell me how many rooms are there" | Phase 16A short-compound + Phase 14B planner | Decomposed to `[floor_plan, spatial_query]` |
| "what should I look at this week?" with `personas=[facility_manager, sustainability_officer]` | Phase 14A blend + Phase 16B prompt-surface | Returned sustainability-focused FM recommendations; `persona_blended` diagnostic in state |

---

## 10. Known issues

### 10.1 Argon2 salt stored only in Redis (pre-existing, surfaced during Phase verification)

**Observed:** During this session's verification, the test user `surveytest` could no longer log in. Diagnosis showed `Login attempt - hash len: 0, salt len: 0`. Root cause: `auth_manager.py` persists user accounts in **Postgres** (durable) but stores the per-user Argon2 salt in **Redis** (ephemeral, 7-day TTL on sessions, wiped on `FLUSHDB`).

**Impact:** Any operation that flushes Redis (the swap CLI's `_flush_response_cache` only targets `resp_cache:*` so this is safe; manual `FLUSHDB` is not) breaks all existing user accounts. The Postgres row prevents re-registration; the missing salt prevents login. Recovery requires manual `DELETE FROM users WHERE …` then re-register.

**Workaround (used in this session):**

```bash
docker exec postgres-user-data psql -U ontobot -d ontobot \
  -c "DELETE FROM conversations WHERE user_id='surveytest'; DELETE FROM users WHERE username='surveytest';"
```

**Diagnosis revision (Phase 18):** Detailed audit showed the salt IS already written to Postgres on register (see `postgres_manager.create_user` schema — both `password_hash` and `salt` columns). The user-visible symptom was actually the silent Redis fallback path used when Postgres was unreachable mid-session: `get_user` returned `None`, the code fell through to `redis.hgetall("user:<name>")` which returned `{}`, and the final extraction produced `hash len: 0, salt len: 0` → the user saw misleading "Invalid password".

**Fix shipped in Phase 18A:** `auth_manager.login` now probes Postgres connectivity (`SELECT 1`) before user lookup. When Postgres is degraded, returns *"Authentication service is temporarily unavailable"* instead of pretending the user doesn't exist. Redis fallback is now gated on `not self.postgres` (truly Postgres-free legacy deployments only). Verified live by `docker stop postgres-user-data` mid-session.

### 10.2 Postgres connect race on Docker restart — **FIXED in Phase 18B**

**Observed:** After restarting Docker Desktop, the orchestrator booted before `postgres-user-data` was healthy. `/health` showed `postgresql: "not_configured"` and user registration silently failed.

**Fix shipped:** `lifespan` in `orchestrator/main.py` now retries the Postgres connection up to 5 times with exponential backoff (2 → 4 → 8 → 16 → 30 s). Verified live by log line `Postgres connected (attempt N/5)` on a clean container restart.

### 10.3 `dwg2dxf` not in default Debian image — **FIXED in Phase 18E (libredwg source build)**

**Observed:** `[dwg_pipeline] DWG→DXF conversion failed for Abacws floor 2.dwg — aborting.`

**Investigation (Phase 18):** `apt-cache search libredwg` in a live trixie-sourced container returned ZERO results — the package isn't in bookworm, trixie, or sid. The CLAUDE.md note that suggested "install from sid/trixie" was outdated; the upstream Debian packaging was dropped.

**Fix shipped (Phase 18E):** Multi-stage Dockerfile builds `libredwg 0.13.3` from the pinned upstream release in a builder stage (with autotools + swig + libpcre2-dev + libxml2-dev) and copies only the resulting binaries (`dwg2dxf`, `dwg2svg`) + shared library to the runtime stage. Runtime image gains ~12 MB; first build adds ~3 minutes (cached afterwards). All 6 Abacws floor DWGs now ingest at startup with real polygons and areas; total building area: **20,370.2 m²**. T7-SP2 (survey question "What is the total area of floor 1?") went from a persistent WARN to PASS.

### 10.4 Maintenance agent's "create new ticket" path (T15-S5 WARN)

**Observed:** `"report broken light"` returns *"I processed your request, but couldn't generate a response."*

**Status:** Only remaining WARN in the 95-question survey. The maintenance agent has the ticket-lookup path working but the nominal-create path (when no entity is recognised in the query) drops to a generic fallback message instead of asking for the missing fields (location, device, fault description).

**Workaround:** Be more specific — *"file a maintenance ticket for the broken light in room 3.01"* works.

---

## 11. Quick reference — common operations

### Run the deterministic test suite

```bash
pytest tests/test_phase3_4_services.py tests/test_blended_persona.py \
       tests/test_compound_query_e2e.py tests/test_intent_graph_autowire.py \
       tests/test_multi_tenant_fixture.py tests/test_routing_accuracy.py \
       tests/test_state_persistence.py tests/test_swap_building.py \
       tests/test_unregistered_intent_safety_net.py tests/test_workflow_wiring.py \
       tests/test_survey_aligned_phases.py tests/test_phase_a_fixes.py \
       tests/services/test_ttl_validator.py
```

(Or just rely on `.github/workflows/ci.yml` which runs the exact same list.)

### Run the live survey

```bash
# WARNING: FLUSHDB wipes auth salts — see §10.1
docker exec redis-memory-store redis-cli FLUSHDB
python scripts/survey_live_test.py
```

### Live smoke (single query)

```bash
TOKEN=$(curl -s -X POST http://localhost:8000/auth/login \
  -H "Content-Type: application/json" \
  -d '{"username":"...","password":"..."}' \
  | python -c "import sys,json; print(json.load(sys.stdin)['data']['session_token'])")

curl -s -X POST http://localhost:8000/chat \
  -H "Content-Type: application/json" -H "Authorization: $TOKEN" \
  -d '{"message":"What is the current temperature in zone 5.28?","session_id":"smoke","personas":["facility_manager"]}' \
  | python -m json.tool
```

### Inspect the routing audit trail

```bash
# state.intermediate_results["route_decision"] is written on every turn
docker exec redis-memory-store redis-cli GET conversation:conv_<session_id>:<user>
```

---

## 12. License + provenance

OntoSage is MIT-licensed. The Phase 11-17 work documented here was developed against Cardiff University's Abacws building (`bldg1`) with `bldg2` as a multi-tenant fixture. The Brick Schema ontology is BSD-licensed; the orchestrator's LLM provider abstraction supports both OpenAI and local Ollama models for cost / privacy flexibility.

The single-building-at-a-time design is intentional for v1. The future Onto-community release will support multiple simultaneous buildings; the per-building infrastructure (registry caches, BuildingContext resolver, per-building Qdrant collections, persona overlays) is the forward-compatible foundation already in place.
