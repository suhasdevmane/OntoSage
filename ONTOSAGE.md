# OntoSage — System Reference (V3 + P0 Security Hardening)

**Comprehensive technical reference for the OntoSage agentic-AI framework for smart buildings.** This document covers the full architecture, every Phase 11-22 improvement plus V3 corpus-driven extensions and P0 security hardening, the routing pipeline, the multi-tenant / multi-persona / multi-intent model, conversation memory, follow-up co-reference resolution, the forecasting pipeline, the admin portal, the operational surface (configuration, swap workflow, CI), the test coverage, and known issues — accurate as of 2026-07-09.

**Test suite**: 981 deterministic tests passing, 8 skipped (Python 3.10/3.11/3.12); the suite runs from a clean checkout with no active building and no `.env` — the skips are optional deps plus fixtures that need an activated building. **Corpus coverage**: 63.8% (bldg1) and 70.4% (bldg2) of the 240-question stratified replay drawn from the 5,604-question survey (vs. 16.2% baseline before V3) — corroborates paper §6.5, and the bldg2 figure is the portability evidence (same code, different building).

**For new AI sessions:** Read `CLAUDE.md` first (navigation index, debugging, current branch state), then this file for deep architecture. Do not commit or push without explicit user approval.

Two-line summary: A user types a question in plain English. OntoSage resolves follow-up references against conversation memory, classifies the intent, blends the user's stacked personas, routes to the right pipeline (SPARQL → SQL → analytics / forecasting, or floor-plan, or capability triples, or one of the standalone agents), and returns a structured answer with full per-request audit trail — remembering the conversation across turns.

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

**Around the graph, two cross-cutting layers run every turn (Phase 21-22):**

- **Before `dialogue`** — *co-reference resolution* (Phase 22): a context-dependent follow-up such as *"and what about humidity there?"* is rewritten into a self-contained query (*"average humidity on floor 3"*) so intent classification, entity extraction, and SPARQL all resolve the reference. See §5.4.
- **After `response`** — *conversation memory* (Phase 21): the full state is persisted to Redis (count-bounded, no time-expiry by default) and a structured one-line summary of the turn is written to the Postgres `turn_memory` table. The next turn reads back recent messages, carries forward forecast/analytics artifacts, and injects older-turn summaries as long-term context. See §5.5.

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
├── agents/                         # one file per agent (17 agents)
│   ├── dialogue_agent.py           # LLM intent classification + entity extraction + co-reference rewrite (Phase 22)
│   ├── sparql_agent.py             # SPARQL generation + execution + ContextVar bctx (Phase 15A)
│   ├── sql_agent.py                # Time-series fetch
│   ├── analytics_agent.py          # Code-executor sandboxed analysis
│   ├── forecast_agent.py           # Phase 20 — multi-model time-series forecasting
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
│   ├── ttl_uploader.py             # Phase 3 — idempotent TTL upload on startup (discovers bldg1_*.ttl glob)
│   ├── multi_intent_detector.py    # Phase 14 — compound-query decomposition
│   ├── turn_memory.py              # Phase 21 — TurnMemoryService (Postgres per-turn summaries + carry-forward)
│   ├── report_intake_service.py    # Phase 19 — fault/complaint/safety/feedback intake → user_reports table
│   ├── job_queue.py                # Async job queue (Redis-backed) for long-running tasks (GET /jobs/{id})
│   ├── semantic_router.py          # is_data_query/report/control/spatial routing helpers
│   ├── capability_graph_resolver.py # Answers capability questions from ontosage: triples
│   ├── capability_admin.py         # GUI/API authoring of capability triples (OCBV)
│   ├── floor_plan_pipeline.py      # PDF → manifest
│   ├── dwg_pipeline.py             # DWG → DXF → polygons
│   ├── floor_plan_registry.py      # Merge PDF + DWG manifests
│   ├── ontology_manager.py         # P0 — Admin CRUD for GraphDB: list/validate/upload/drop graphs, SPARQL select
│   ├── reindex_service.py          # P0 — Async Qdrant reindex job queue: start/status/list_jobs/_run
│   ├── sensor_ttl_generator.py     # P0 — Brick Turtle generator for sensor registration from CSV
│   ├── forecasting/                # Phase 20 — preprocessor, horizon_parser, model_selector,
│   │                               #   metrics, models/ (ARIMA, exp-smoothing, linear)
│   ├── adapters/                   # Storage backend abstraction
│   │   ├── registry.py             # Routes by ref:storedAt key → correct adapter
│   │   ├── mysql_adapter.py        # Wide sensor_data table (original abacws sensors)
│   │   └── mysql_narrow_adapter.py # P0 — per-modality (uuid, datetime, value) tables
│   ├── feeds/                      # V3 — FeedAdapter ABC + csv_drop + rest_poll + registry
│   ├── actuation/                  # V3 — ActuationDriver ABC + SimDriver + approval_store + registry
│   ├── rules_engine.py             # V3 — ECA rule engine (standing rules, Redis duration windows)
│   ├── concept_resolver.py         # V3 — HBCO lay-term → Brick class + recipe (Redis 24h cache)
│   ├── recipe_registry.py          # V3 — config/recipes.yaml + per-building overlay loader
│   ├── document_indexer.py         # V3 — indexes input/<bldg>/documents/ into Qdrant
│   ├── goal_planner.py             # V3 — mandate decomposition + three-tier capability report
│   ├── notification_service.py     # V3 — log/webhook/smtp dispatch from rules + conversation
│   ├── user_alert_store.py         # V3 — per-user conversational alert rules (Redis, 90-day TTL)
│   ├── user_preference_store.py    # V3 — per-user comfort preferences (Redis, 1-year TTL)
│   ├── input_validators.py         # V3 — schema validators for all per-building optional files
│   └── …
├── auth_manager.py                 # Argon2id + Redis sessions (see Known Issues §10)
├── middleware/rbac.py              # 6 roles × 20 permissions; require_permission() dependency
└── main.py                         # FastAPI app + lifespan + 70+ endpoints incl. 8 P0 admin endpoints

input/
├── building.yaml                   # REQUIRED — building_id, ontology_namespace, storage.databases
├── database_registry.yaml          # REQUIRED — all connection templates (53+ engines)
├── bldg1_abacws_metadata.ttl       # Original Abacws building metadata
├── bldg1_timeseries_extension.ttl  # P0 — 19 sensors across 7 modalities with TimeseriesReference triples
├── bldg1_security_lighting_extension.ttl  # P0 — lighting systems, CCTV, alarm zones, 293 triples
├── *.dwg, *.pdf                    # Floor plans (DWG for geometry; PDF for display)
├── <id>_capabilities.ttl           # Capability TRIPLES (ontosage:Amenity/KnowledgeTopic)
├── intents.yaml                    # Per-building intent overlay
├── personas/                       # Per-building persona YAML files
├── feeds.yaml                      # V3 — live feed specs
├── rules.yaml                      # V3 — ECA alert rules
├── channels.yaml                   # V3 — notification dispatch
├── benchmarks.csv                  # V3 — peer benchmark percentiles
├── concepts.ttl                    # V3 — HBCO local vocab overlay
└── documents/                      # V3 — policy/manual KB (indexed into Qdrant)

data/mysql-init/
├── init.sql                        # Legacy — creates abacws DB (deprecated; live system uses sensordb)
└── create_narrow_timeseries_tables.sql  # P0 — 7 narrow (uuid, datetime, value) tables in sensordb

frontend/src/
├── pages/AdminPortal.js            # P0 — React admin portal (9 tabs)
├── pages/Health.js                 # Updated — shows GraphDB, Qdrant, Ollama (removed stale entries)
└── components/TopNav.js            # Updated — /admin link

shared/
├── config.py                       # Settings (Pydantic v2); secrets masked via repr=False (Phase 21);
│                                    #   MULTI_INTENT_MIN_LENGTH=50, COREFERENCE_REWRITE_ENABLED, STRICT_SECRETS
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
│   ├── building.yaml               # building_id, name, ontology_namespace, actuation block
│   ├── <id>_capabilities.ttl       # capability TRIPLES (amenities, policies, how-tos)
│   ├── intents.yaml                # per-building intent overlay
│   ├── personas/                   # per-building persona overlay
│   ├── feeds.yaml                  # V3 — external feed specs (csv_drop / rest_poll); absence = silently skipped
│   ├── recipes.yaml                # V3 — analytic recipe overrides (optional; merged with config/recipes.yaml)
│   ├── rules.yaml                  # V3 — ECA operator rules; absence = engine idle
│   ├── channels.yaml               # V3 — notification dispatch channels (log / webhook / smtp)
│   ├── benchmarks.csv              # V3 — peer/standard percentiles for this building segment
│   ├── concepts.ttl                # V3 — per-building HBCO vocab overlay ("the fishbowl" → Room)
│   ├── documents/                  # V3 — policy/manual docs indexed into Qdrant documents_<bldg>
│   └── *.ttl, *.dwg, *.pdf
└── bldg1_*.ttl                     # legacy root-level TTL layout (still supported)

scripts/
├── swap_building.py                # Phase 12C — safe building swap CLI; V3 validates all optional configs
├── onboard_building.py             # Legacy onboarding + V3 --scaffold flag (copies input/_templates)
├── corpus_replay.py                # V3 — stratified 240q replay (40/level); LLM-graded pass rate
└── survey_live_test.py             # 95-query regression survey

tests/                              # 981 deterministic tests, 8 skipped; see §9
├── fixtures/buildings/bldg2/       # Phase 12A — fixture for multi-tenant tests
├── test_admin_ontology_endpoints.py # P0 — 13 admin endpoint tests
├── test_auth_manager.py             # P0 round 2 — 7 tests (login lockout, delete_user cleanup, default role)
└── …                               # 18 test files in CI

.github/workflows/ci.yml            # Phase 16C+ → P0 — runs full deterministic suite (3.10/3.11/3.12)
```

### 2.3 Storage layer

| Store | Port | Purpose |
|---|---|---|
| **GraphDB** | 7200 | RDF ontology (Brick/BACnet TTL). Used by SPARQL agent. |
| **MySQL** | 3306 | Time-series sensor readings, keyed by UUID. Wide `sensor_data` (UUID-per-column) for the original sensors; **narrow per-modality tables** `(uuid, datetime, value)` for energy/occupancy/water/noise/IAQ/light/equipment (`type: mysql_narrow` in `input/database_registry.yaml`). |
| **PostgreSQL** | 5433 | User accounts + Argon2id hashes + RBAC; `turn_memory` (per-turn conversation summaries, Phase 21); `user_reports` (fault/complaint intake, Phase 19). |
| **Redis** | 6379 | Conversation state (`conversation:<id>` — **no time-expiry by default**, count-bounded to `CONVERSATION_MAX_MESSAGES`; Phase 21), response cache (`resp_cache:*`), session salt (see §10). |
| **Qdrant** | 6333 | `floor_plans` (room vectors + geometry payload), `documents_<bldg>` (uploaded-manual chunks), `user_memory`. (Capabilities are ontology triples, not vectors.) |
| **MongoDB** | 27017 | Full chat-history transcripts (OpenWebUI). |
| **rag-service** | 8001 | Semantic fallback for empty SPARQL results. |
| **code-executor** | 8002 | Sandboxed Python for analytics agent. |

> **Canonical data rule.** `input/` holds metadata/config only. Sensor time-series **belong in a
> database**, referenced from the ontology via
> `ref:hasExternalReference → ref:TimeseriesReference (ref:hasTimeseriesId + ref:storedAt)`. Raw
> CSV sensor readings in `input/` are deprecated. To add a source, declare the Brick point(s) in an
> `input/*.ttl` (the startup loader ingests it idempotently into a per-file named graph), register
> the narrow table in `input/database_registry.yaml`, and load readings keyed by UUID — one command:
> `scripts/onboard_data_source.py`. Full guide: [docs/ADDING_A_DATA_SOURCE.md](docs/ADDING_A_DATA_SOURCE.md).

### 2.4 LLM / embedding provider

`shared/config.py` is the single switch via `MODEL_PROVIDER`:

- `openai` → OpenAI API (gpt-5.4 complex, gpt-4o-mini fast)
- `local` → Ollama at `http://ollama:11434` (default `deepseek-r1:32b`)
- `cloud` → Ollama Cloud

Embedding: `EMBEDDING_PROVIDER` independently selects `openai` (1536-d `text-embedding-3-small`) or
`local` (1024-d `BAAI/bge-large-en-v1.5`, baked into the image and run fully offline —
`HF_HUB_OFFLINE=1`, so it can never be silently fetched or swapped at runtime).

**The model settles its own numbers, not a config constant.** Both the vector width and the document
retrieval floor derive from the loaded model (`shared/config.py` → `dimension_for_model`,
`document_score_floor`; once resident the local model is asked directly via
`get_sentence_embedding_dimension()`). The previous code branched on *provider name* and applied a
floor calibrated for 384-d MiniLM to a 1024-d model — a floor tuned for a model that is not running
is worse than no floor. The `EMBEDDING_DIMENSION_*` settings are kept only as a fallback for an
unrecognised model, and a disagreement is logged rather than followed silently.

**Boot-time consistency sweep.** Vectors of different widths cannot be compared, and a failed
similarity search returns no rows rather than raising — so a stale collection left by an earlier
model is silent until a user gets an empty answer. `services/embedding_consistency.py` runs once in
the lifespan, *enumerating whatever Qdrant collections exist* (never a fixed name list, so a building
onboarded tomorrow is covered), drops any derived collection built at a mismatched width so its owner
rebuilds it at the right one, and *reports but never deletes* an irreplaceable store like
`user_memory`. It fails open, so Qdrant being briefly unavailable cannot block startup.

---

## 2.5 V3 — Corpus-Driven Capability Extensions (2026-06-11)

V3 was derived from a 5,604-question corpus (corpus analysis in `paper/Survey analysis and results/`). It added seven new service layers, all config-driven so adding a new building = dropping files, no code edits.

| Layer | Service | Per-building file | What it enables |
|---|---|---|---|
| **HBCO** | `concept_resolver.py` | `concepts.ttl` (overlay) | Lay terms → Brick class + recipe; 69 concepts mined from corpus |
| **Recipes** | `recipe_registry.py` | `recipes.yaml` (overlay) | 38 analytic recipes (threshold/range/aggregate/trend/benchmark/estimate) |
| **Live feeds** | `feeds/registry.py` | `feeds.yaml` | csv_drop + rest_poll adapters; auto-registers Brick points in GraphDB |
| **Document KB** | `document_indexer.py` | `documents/` | Policy/manual KB indexed into Qdrant; cited in capability answers |
| **ECA rules** | `rules_engine.py` | `rules.yaml` | Standing event-condition-action rules with Redis duration windows |
| **Actuation** | `actuation/registry.py` | `building.yaml` actuation block | SimDriver (log-only) + approval workflow; `control:write` RBAC gate |
| **Goal planner** | `goal_planner.py` | `config/goals.yaml` | Mandate decomposition → KPI questions → three-tier honest capability report |
| **Notifications** | `notification_service.py` | `channels.yaml` | Rules + conversation dispatch through log / webhook / smtp |
| **Validators** | `input_validators.py` | — | Schema-validates all optional files at swap/startup; bad optional = WARNING not crash |

**Answerability improvement** (projected from corpus master table):

| After phase | Fully answerable | % of non-GK |
|---|---|---|
| Baseline (Phase 22) | 786 | 16.2% |
| B — metadata + doc KB | 822 | 17.0% |
| C — live streams floors 0-4 | 904 | 18.7% |
| D — external feeds (weather/calendar/tariff) | 978 | 20.2% |
| E — sensor modality expansion (occupancy/energy/IAQ/noise/light/water) | 2,437 | **50.3%** |
| G — guarded actuation + goal planner | 2,930 | **60.5%** |

Run `python scripts/corpus_replay.py --sample 240` on the live stack to measure actual post-V3 numbers.

**V3 new intents** (added to `intent_definitions.yaml`):
`alert_mgmt`, `automation_capability`, `preference_management`, `wayfinding` (spatial sub-type),
`report_intake` family extended, `planner` extended with goal-mandate detection.

---

## 3. The 29+ Intents

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

**Forecasting (Phase 20):** the `trend` intent flows through `sparql → sql → analytics`. When the query also carries forecast/predict keywords (e.g. *"predict CO₂ for next week"*), the analytics stage hands the fetched series to the **`ForecastAgent`** (`agents/forecast_agent.py`), which preprocesses, auto-selects a model (ARIMA / exponential-smoothing / linear), parses the horizon, computes accuracy metrics (RMSE/R²), and writes `forecast_result` for visualization. See §5.6.

---

## 3.5 Stakeholder Question Guide — What data is needed?

Every question is answerable when the right data is attached. This guide maps question types to the required data sources.

### Questions answered from Brick TTL alone (SPARQL, no time-series)

| Question example | Intent | Required |
|---|---|---|
| "How many sensors are on floor 3?" | `metadata` | Brick TTL in GraphDB |
| "What types of equipment does the building have?" | `discovery` | Brick TTL |
| "What zones does floor 2 have?" | `metadata` | Brick TTL |
| "How many CCTV cameras are there?" | `metadata` | `bldg1_security_lighting_extension.ttl` |
| "Is there motion sensing on floor 3?" | `discovery` | `bldg1_security_lighting_extension.ttl` |

### Questions that need time-series data (TTL + MySQL)

| Question example | Intent | TTL required | MySQL table |
|---|---|---|---|
| "Current temperature in zone 5.28?" | `sensor_data` | `bldg1_abacws_metadata.ttl` | `sensor_data` (wide) |
| "Average humidity on floor 4 last week?" | `analytics` | Same | Same |
| "CO2 trend for the past month" | `trend` | Brick TTL with UUID | `sensor_data` or `iaq_data` |
| "Predict energy consumption next week" | `trend` + forecast | Timeseries TTL | `energy_data` |
| "Any unusual temperature readings?" | `anomaly` | Brick TTL | `sensor_data` |
| "Compare floor 3 vs floor 4 energy" | `compare` | Both floor sensors in TTL | `energy_data` |
| "Plot occupancy over 30 days" | `visualization` | Occupancy TTL | `occupancy_data` |
| "Export IAQ data as CSV" | `export` | IAQ TTL | `iaq_data` |
| "How many people are on floor 3?" | `sensor_data` | Occupancy TTL | `occupancy_data` |
| "Energy consumption today?" | `analytics` | Energy meter TTL | `energy_data` |
| "Is CO2 in meeting rooms compliant?" | `compliance` | IAQ TTL + `rules.yaml` | `iaq_data` |
| "Water usage this week?" | `analytics` | Water TTL | `water_data` |
| "Is it too noisy for studying?" | `analytics` | Noise TTL | `noise_data` |
| "Is the AHU operating normally?" | `analytics` | Equipment TTL | `equipment_data` |

### Questions answered from floor plans (DWG/PDF)

| Question example | Intent | Required |
|---|---|---|
| "Show me floor 3 layout" | `floor_plan` | PDF or DWG in `input/` |
| "How many rooms on floor 2?" | `spatial_query` | DWG geometry |
| "What is the total floor area?" | `spatial_query` | DWG geometry |
| "Which rooms are adjacent to room 3.01?" | `spatial_query` | DWG polygon data |
| "What is the area of floor 1?" | `spatial_query` | DWG — returns 3,008.5 m² for bldg1 |

### Questions answered from capability triples (see §8.5)

| Question example | Intent | Answered from |
|---|---|---|
| "Where is the lift?" | `capability` | `ontosage:Amenity` triple |
| "Is there a prayer room?" | `capability` | `ontosage:Amenity` triple |
| "What is the wifi / GDPR policy?" | `capability` | `ontosage:KnowledgeTopic` triple (`answerText`) |
| "Is the building wheelchair accessible?" | `capability` | `ontosage:Amenity` triple |
| "What are the fire evacuation procedures?" | `capability` | uploaded `documents/fire_safety.md` (long-form) |

### Questions that store a report (no data query — just writes to Postgres)

| Question example | Intent | What happens |
|---|---|---|
| "The toilet is broken on floor 2" | `maintenance` | Stored in `user_reports` as HIGH priority, tracking ID returned |
| "There is a gas smell near the lab" | `safety_report` | Stored as URGENT, triage views in pgAdmin |
| "The canteen was too cold yesterday" | `complaint` | Stored as NORMAL priority |
| "Suggestion: add more recycling bins" | `suggestion` | Stored with persona stamp |

### Questions requiring external feeds (`feeds.yaml`)

| Question example | Required feed |
|---|---|
| "What is the outside air temperature?" | `outside_weather_temp` (Open-Meteo rest_poll) |
| "Is there a meeting room available now?" | Calendar feed |
| "What is the current electricity tariff?" | Tariff feed |

### What OntoSage will not do

| Request | Why |
|---|---|
| "Turn off the lights on floor 3" | `control` intent declines — `actuation.driver=sim` (log-only); would require `driver=real` and `control:write` permission |
| "Email the report to the team" | External action — not modelled |
| "What is the capital of France?" | Out of scope — scope redirect returned |

### By stakeholder

| Stakeholder | Primary intents | Minimum data |
|---|---|---|
| **Facility Manager** | sensor_data, analytics, trend, anomaly, maintenance, floor_plan, recommend | Brick TTL + time-series + DWG files |
| **Sustainability Officer** | analytics (energy), compare, trend, compliance, recommend | Energy/IAQ TTL + `energy_data` + `iaq_data` |
| **Researcher** | metadata, discovery, analytics, export, trend | Brick TTL + relevant narrow tables |
| **Safety Officer** | anomaly, compliance, capability (fire safety), report_intake | Brick TTL + `documents/fire_safety.md` + `rules.yaml` |
| **General User / Student** | discovery, capability, floor_plan, spatial_query | Brick TTL + DWG/PDF files |
| **Admin** | All of the above + Admin portal | Everything + `system:admin` role |

---

## 4. The routing pipeline

### 4.0 The routing contract (TODO-050)

Deterministic intent corrections used to live as a dozen inline overrides accreted one
bug-fix at a time inside `dialogue_agent`. They now live in **one ordered, tested,
building-agnostic contract**: `orchestrator/services/routing_contract.py`.

* **13 parse-stage rules + 1 post-stage rule.** Each maps a *question shape* (count words,
  comparison words, modal-automation phrasing, report statements…) to the intent the
  pipeline can actually ground, and only overrides *from* the intents it names — a
  confident, correct classification is never stomped.
* **Order is the contract.** Earlier rules win, later rules see the rewritten intent, and
  `tests/test_routing_contract.py` pins the exact sequence so a reordering must be
  deliberate.
* **Building-agnostic by test.** The rules key on English phrasing only; a test scans the
  module source and fails if any building name, namespace or zone id ever appears.
* **Audited.** Every applied rule is logged and recorded in `routing_rules_applied`.

Add or change a routing rule **there** — never as a new inline override in the dialogue
agent.

### 4.1 Decision flow

```
LLM dialogue_agent classifies intent
            │
            ▼
routing_contract.apply_contract(stage="parse" | "post")
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

### 4.2b Grounding: what stops a fabricated answer (BUG-103)

A conversational layer over a building will always be *asked* about things the building does
not have. Two independent paths used to answer those questions with real-but-unrelated
content, phrased as if it were the answer. Both are now gated, building-agnostically.

**1. Named referents — `services/referent_resolver.py`.** Before the SPARQL→SQL→analytics
cascade can attribute some other sensor's readings to a thing the user named, the referent is
validated against the *active* building's graph:

| Referent kind | Example | How it is validated |
|---|---|---|
| zone / room / sensor id | "Zone 99.99" | dotted id or `zone\|room\|space <id>` present in the namespace |
| floor | "floor 42" | an entity matching `floor` + that number |
| named space / amenity | "the west wing", "swimming pool" | modifier + generic space head noun, both on one entity |
| equipment | "chiller 7", "EV chargers" | equipment noun (+ number) in a URI, label, or class |
| measurand | "methane concentration" | any sensor class or label measuring that quantity |

Detection uses **English structure only** — never a building's vocabulary — and validation
runs against that building's own triples, so a new building works unchanged. The gate is
precision-first (an unnamed or broad query passes straight through) and **fails open**: if
GraphDB is unreachable the query proceeds exactly as it did before the gate existed.

**2. Retrieved passages — `services/grounding_guard.py`.** Vector similarity alone is not
grounding. A cosine floor calibrated for one embedding model lets generic building prose clear
it for *any* question under another model, which is how an HVAC CO₂ table came to "answer" a
question about pH. The guard requires a retrieved passage to actually *mention* what was asked
about — matched on the passage text **or** the document name, and on **distinctive** terms
(question terms minus vocabulary every building question shares, like *temperature*, *floor*,
*water*). It is applied to both capability sources: uploaded documents and ontology
`Amenity`/`KnowledgeTopic` triples. Being lexical, it needs no per-model tuning.

**3. Refusals are actionable.** Every honest "I don't have that" ends with the concrete step
that would make the question answerable — upload a TTL describing the entity, give its sensors
`ref:hasTimeseriesId` + `ref:storedAt`, register the database, or add an `ontosage:Amenity` —
which is the connect-data → get-answers contract expressed in the answer itself.

**Measuring it.** `scripts/honesty_sweep.py` fires a battery of absent-referent questions at a
live stack and grades every answer, per building. On bldg1 it moved honest answers from 4/18 to
12/18 with **zero** fabricated measurements remaining, while wifi, lift-location, live zone
readings and building metrics all continued to answer normally.

### 4.2c Grounding, continued — the rest of the honesty subsystem

The grounding guard above stops an *unrelated passage* being dressed up as an answer. Three more
guards, each building-agnostic, close the remaining ways a plausible-but-wrong answer could slip out:

**Referent existence gate — and its deliberate asymmetry.** Before any fallback can attribute one
sensor's readings to a place the building lacks, the named referent is checked against the active
building's graph (`services/referent_resolver.py` → `detect_typed_referent` for floors, spaces,
equipment and measurands; `capability_agent._absent_referent_decline` guards the metadata/capability
door the sparql gate never sees). The gate's failure handling is intentionally **asymmetric**: a
question that names *nothing* fails **open** (there is nothing to fabricate about), but once a
referent is named and the existence check cannot complete — a timeout under load, a degraded GraphDB
— it fails **closed**, returning an honest "I couldn't verify that — ask again" rather than letting
the query proceed into the fabricating fallback. Failing open on a legitimate question loses one
answer; failing open on an existence check produces a confident fabrication, so the two are handled
differently (BUG-136).

**Plausibility guard.** A comparative verdict — "very strong", "high", "too warm" — is a claim the
value was compared against something. When a reading cannot be that quantity in *any* unit it is
normally reported in (a "wind speed" of 8308 is not m/s, km/h, mph or knots), `services/plausibility.py`
strips the verdict and reports the raw number with a note that its scaling needs checking. The
ranges are physical facts keyed on measurand words from Brick classes, so the same guard serves
every building; years and clock times are excluded so a timestamp is never mistaken for a reading.

**Missing-fact caveat.** Being *about* the subject is not the same as *answering* the question. A
service-history question can match a topic that discusses the equipment yet contains no date;
`grounding_guard.missing_fact_caveat` prefixes such an answer with "I don't hold a specific date for
this — here is the related information I do have", turning a misleading reply into an honest partial
one. It is silent when the question asks for no particular kind of fact, so it never becomes noise.

**Self-description is settled first.** "What is OntoSage / what can you do / how do you work" is
resolved at the very top of intent detection, before the capability probe and before the LLM sees
it. Left downstream, such a question matched a building document that happened to mention the name
(an answer that exists on exactly one building) or fell through to the open-domain answerer, which
claimed to be "a large language model." It is now answered from live configuration — the intent
registry, the schema's grounding-source types, the connected building's own figures — described as a
building-agnostic framework, so it is correct on every building including one with no data yet
(`services/self_description.py`, `_self_description_node`).

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
| Per-building capability triples (`ontosage:Amenity`/`KnowledgeTopic`) | `services/capability_graph_resolver.py`, `capability_admin.py` | — |
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

### 5.4 Follow-up co-reference resolution (Phase 22)

Follow-up turns that refer back with a pronoun or deictic — *"and what about humidity **there**?"*, *"the same for floor 5"*, *"how about floor 2"* — are rewritten into self-contained queries before classification. This is the industry-standard "condense question" step, **gated** so the extra LLM call only fires when it's likely worth it.

```
Turn 1: "what is the average temperature on floor 3"
Turn 2: "and what about humidity there"
                                    ▲ "there" = floor 3
        → rewritten to "what is the average humidity on floor 3"
```

| Stage | Mechanism |
|---|---|
| **Gate** (zero-LLM) | `dialogue_agent._is_followup_query()` — fires on short queries (≤4 words) OR deictic markers (`there`, `that`, `the same`, leading `and`/`what about`, …) |
| **Rewrite** | `DialogueAgent.rewrite_to_standalone()` — a fast LLM (`TaskType.REWRITE`) resolves the reference against the last 6 turns; returns the original on any failure (fully graceful); no-ops self-contained queries |
| **Apply** | `_dialogue_node` rewrites `messages[-1]` before `detect_intent`, so intent + entity extraction **and** the SPARQL node (both read `messages[-1].content`) resolve the reference. Original preserved in `metadata["original_query"]` + `intermediate_results["coref_rewrite"]` |

Feature flag: `settings.COREFERENCE_REWRITE_ENABLED` (default `True`). Tests: `tests/test_coreference_rewrite.py` (16 cases — heuristic gate + gated rewrite, LLM mocked).

### 5.5 Conversation memory (Phase 21)

Two complementary stores keep a conversation coherent across turns:

| Layer | Store | What it holds | Eviction |
|---|---|---|---|
| **Short-term** | Redis `conversation:<id>` | Full `ConversationState` blob (messages + `intermediate_results`) | **Count-based** — the stored blob is trimmed to `CONVERSATION_MAX_MESSAGES` (default 20). `CONVERSATION_TTL=0` ⇒ no time-expiry by default (set >0 to re-enable) |
| **Long-term** | Postgres `turn_memory` | One row per turn: `user_query`, `intent`, `entities`, a deterministic 1-line `result_summary` (no raw sensor arrays), and `carry_forward` (forecast/analytics artifacts) | Persistent |

On each turn (`/v1/chat/completions`): `TurnMemoryService.get_carry_forward()` re-injects the previous turn's `forecast_result` / `analytics_result` (so *"now plot that"* works), and `get_older_context()` prepends compact summaries of turns older than the recent window as a long-term-memory system prefix. Secrets are masked in the pydantic `Settings` repr (`repr=False`) so they never leak into logs. Tests: `tests/test_turn_memory.py`, `tests/test_conversation_memory_e2e.py`.

### 5.6 Forecasting pipeline (Phase 20)

`agents/forecast_agent.py` + `services/forecasting/` add PhD-grade multi-model time-series forecasting, triggered inside the `trend` pipeline when the query carries forecast/predict intent:

```
sql series ─► preprocessor ─► model_selector ─► {ARIMA | exp-smoothing | linear}
                                   │
                              horizon_parser ("next week" → N steps)
                                   │
                                   ▼
                         forecast_result {model, horizon, metrics{rmse,r2}, points}
                                   │
                                   ▼  visualization node renders the chart
```

The selector picks the best model for the series' characteristics; `metrics.py` reports RMSE / R². Tests: `tests/test_forecast_pipeline.py`, `tests/test_forecast_routing.py` (live-stack suites).

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
#    Optional: *.dwg, *.pdf, <id>_capabilities.ttl, documents/, intents.yaml, personas/

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

## 6.5 Admin Portal — Ontology Management, Reindexing & Health

The running admin console is the **config-panel at `http://localhost:3001`** (localhost-only nginx that proxies `/api` + `/auth` to the orchestrator). Admin actions call FastAPI endpoints under `/api/v1/admin/`; all require the `system:admin` role — requests without a valid admin session token return HTTP 401. (Beyond the ontology/reindex endpoints below, the console also drives building-identity, schema-driven capability authoring, sensor registration, and the semantic-index status — see §6.10/§6.11.)

The admin account is created from `.env` at startup (safe-create, never overwrites):
```bash
ADMIN_USERNAME=admin@yourorg.com
ADMIN_PASSWORD=<strong-password>
```
Or create manually: `docker exec ontosage-orchestrator python /app/orchestrator/create_admin.py <user> <pass>`.

### How a sensor question gets answered — the two-half model

Every time-series question goes through two phases:

```
NL question → SPARQL on GraphDB   (finds sensor + its UUID + which DB it's ref:storedAt)
           → SQL routes by ref:storedAt → that DB's adapter → rows by UUID → answer
```

| Half | What | Where it lives |
|---|---|---|
| **Sensor metadata** | Brick triples: sensor class + `ref:hasTimeseriesId "<uuid>"` + `ref:storedAt bldg:<key>` | **GraphDB** — a TTL file loaded at startup via named graph |
| **Time-series readings** | The numeric values, keyed by UUID | **MySQL** — narrow `(uuid, datetime, value)` table or wide `sensor_data` |

**A database with rows but no TTL triples is invisible.** SPARQL cannot find sensors that aren't in the ontology. Both halves must be in place.

### Admin Portal tabs

#### Ontology tab — GraphDB management

| Action | API endpoint | What it does |
|---|---|---|
| Browse named graphs | `GET /api/v1/admin/ontology/graphs` | Lists all named graphs + triple count each |
| Validate TTL | `POST /api/v1/admin/ontology/validate` | Parses Turtle with rdflib; returns triple count or parse error |
| Upload TTL | `POST /api/v1/admin/ontology/upload` | Pushes valid Turtle into a named graph — live, no restart |
| Drop graph | `DELETE /api/v1/admin/ontology/graphs/{id}` | Removes named graph and all its triples |
| SPARQL browser | `POST /api/v1/admin/ontology/sparql` | Runs a SELECT against the live ontology; rows returned as JSON |

#### Knowledge Base tab — Qdrant reindexing

| Action | API endpoint | What it does |
|---|---|---|
| Trigger reindex | `POST /api/v1/admin/reindex` | Queues a background job for `capability`, `documents`, or `floor_plans` |
| List jobs | `GET /api/v1/admin/reindex` | Returns all jobs with `id`, `status`, `target`, `started_at` |
| Job status | `GET /api/v1/admin/reindex/{job_id}` | Polls a specific job; `status` ∈ `{pending, running, done, error}` |

### Registering a sensor via the Admin Portal (Upload TTL path)

Paste this Brick Turtle into the Ontology tab → Upload TTL:

```turtle
@prefix bldg:  <http://abacwsbuilding.cardiff.ac.uk/abacws#> .
@prefix brick: <https://brickschema.org/schema/Brick#> .
@prefix ref:   <https://brickschema.org/schema/Brick/ref#> .
@prefix rdf:   <http://www.w3.org/1999/02/22-rdf-syntax-ns#> .
@prefix rdfs:  <http://www.w3.org/2000/01/rdf-schema#> .

bldg:EnergyMeter_Floor3 a brick:Electrical_Meter ;
    rdfs:label "Floor 3 Energy Meter"@en ;
    brick:isPartOf bldg:Floor3 ;
    ref:hasExternalReference [
        a ref:TimeseriesReference ;
        ref:hasTimeseriesId "550e8400-e29b-41d4-a716-446655440003" ;
        ref:storedAt bldg:energy_narrow
    ] .
```

The sensor is immediately queryable via SPARQL. Rows in `energy_data` with that UUID are immediately answerable.

### Alternative — TTL file at startup (how bldg1's abacws sensors are wired)

Drop a `bldg1_*.ttl` file into `input/`. `services/ttl_uploader.py` discovers all `bldg1_*.ttl` files via a glob pattern and uploads each idempotently into a named graph `urn:ontosage:ttl:<filename>` on startup. No admin portal needed; no restart needed if the file is already present before startup.

**See also:** §6.7 (Narrow MySQL tables), §6.8 (TTL extensions for bldg1).

### Connecting an external database

1. Add the connection template to `input/database_registry.yaml` (or use one of the ~53 shipped templates for MySQL/Postgres/InfluxDB/TimescaleDB/etc.):
   ```yaml
   my_db:
     type: mysql_narrow
     table: my_sensor_table
     host: "${MY_DB_HOST}"
     port: 3306
     database: sensordb
     user: "${MY_DB_USER}"
     password: "${MY_DB_PASSWORD}"
   ```
2. Add `my_db` to `input/building.yaml` → `storage.databases`.
3. Recreate the orchestrator (`docker compose up -d orchestrator`) — `.env` is baked at container-create.
4. Load rows into the table keyed by each sensor's UUID.
5. Register the sensor via TTL file or Admin Portal Upload TTL.

### When changes take effect

| Change | Takes effect |
|---|---|
| Upload/drop graph via Admin Portal | Immediately (live GraphDB write) |
| Reindex via Admin Portal | Background job; poll `/api/v1/admin/reindex/{job_id}` |
| Add `.env` variable or database connection credentials | Recreate: `docker compose up -d orchestrator` |
| Drop new TTL file into `input/` | Restart orchestrator |

---

## 6.6 P0 — Security Hardening

The P0 hardening work (merged to `main`) enforces authentication and authorization across all endpoints and adds the admin portal. Key changes:

### RBAC enforcement

Every data endpoint is protected by `require_permission(perm)`, which chains through the `get_user_context` dependency:

```python
@app.get("/api/v1/sensors")
async def get_sensors(
    request: Request,
    user: UserContext = Depends(create_rbac_dependency(token_manager, "sensor:read")),
):
    ...
```

`get_user_context()` validates the `Authorization` header against Redis sessions and returns a `UserContext` (with `role`, `permissions`, `tenant_id`, `allowed_buildings`) or raises HTTP 401. Prior to P0, many endpoints accepted requests without any token.

### STRICT_SECRETS boot guard

`STRICT_SECRETS=true` in `.env` causes the orchestrator to refuse startup if any of these passwords still equal their default value:
- `POSTGRES_USER_PASSWORD`
- `MYSQL_PASSWORD`
- `SECRET_KEY`
- `GRAPHDB_PASSWORD`

This prevents accidental production deployments with default credentials.

### Auth chain (override in tests)

The dependency chain: `require_permission(perm)` → `_dependency(user=Depends(get_user_context))` → `get_user_context()`. In tests, override `get_user_context` directly:

```python
from orchestrator.middleware.rbac import ROLE_PERMISSIONS, UserContext
from orchestrator.main import app, get_user_context

app.dependency_overrides[get_user_context] = lambda: UserContext(
    user_id="testadmin",
    username="testadmin",
    role="admin",
    tenant_id="default",
    allowed_buildings=[],
    permissions=ROLE_PERMISSIONS.get("admin", set()),
)
```

### Roles and permissions

The 6 RBAC roles are defined in `ROLE_PERMISSIONS` (`orchestrator/middleware/rbac.py`)
and validated by `_VALID_ROLES` in `main.py`. They are **distinct from personas**
(`sustainability_officer`, `researcher`, …), which bias intent classification only
and grant no permissions.

| Role | Key permissions |
|---|---|
| `admin` | `system:admin`, all data reads, `config:write`, `user:write` (all 21 permissions) |
| `facility_manager` | All data reads, `config:read/write`, `building:read/write`, `device:control`, `control:write` |
| `analyst` | All data reads (sensor/analytics/metadata/report/export/anomaly/trend/compliance/comparison), `building:read` |
| `operator` | `sensor/analytics/metadata/anomaly/trend:read`, `building:read`, `device:control` |
| `occupant` | `sensor:read`, `metadata:read`, `system:health` |
| `readonly` | `metadata:read`, `system:health` |

### Identity through a shared-key proxy

Open WebUI authenticates to OntoSage with one shared `PIPELINE_API_KEY`, so the
OpenAI-compatible endpoint cannot infer the end user from the credential alone. Left there,
every chat user is pinned to least privilege and role-aware answers are impossible.

`resolve_forwarded_user()` (`main.py`) closes that gap: when `TRUST_FORWARDED_USER` is on,
the proxy's forwarded identity header (`FORWARDED_USER_HEADER`, default
`X-OpenWebUI-User-Email`) is resolved against Postgres — full identity first, then the
email's local part, since proxies identify by email while accounts are keyed by username —
and that account's role becomes `intermediate_results["user_role"]` for the whole pipeline.
Control, alert and preference nodes read it, as does the role → data-source access matrix.

Four properties make it safe to run:

* **Opt-in.** With `TRUST_FORWARDED_USER` off the header is ignored entirely. A header is
  only as trustworthy as whoever can set it, and anyone holding the pipeline key could
  otherwise impersonate any user — so this is never inferred from traffic.
* **Least privilege on the unknown.** Someone signed into the proxy with no OntoSage
  account resolves to `readonly` rather than being refused or silently upgraded.
* **Never fatal.** A lookup failure degrades to `readonly` instead of failing the turn.
* **Stubs are not accounts.** `/v1` auto-creates a placeholder Postgres row so
  conversations have a valid owner; it is always readonly and marked
  `metadata.source = "open_webui"`. Resolution skips those rows — otherwise a stub created
  before an admin provisioned someone would permanently shadow their real role.

Roles are read per request, so creating a user or changing a role in the admin console
applies to the next question with no restart, re-login or cache flush.

---

## 6.7 Narrow MySQL Tables — Workstream B

The original `sensor_data` table has one column per sensor UUID (wide format, ~1,000+ columns, hits InnoDB 1,017-column limit on the full building). The narrow format — **one row per reading: `(uuid, datetime, value)`** — avoids this limit and makes adding new sensors trivial.

### 7 narrow tables in `sensordb`

```sql
-- data/mysql-init/create_narrow_timeseries_tables.sql
CREATE TABLE IF NOT EXISTS energy_data (
    uuid     CHAR(36)  NOT NULL,
    datetime DATETIME  NOT NULL,
    value    DOUBLE,
    PRIMARY KEY (uuid, datetime),
    INDEX idx_energy_uuid (uuid),
    INDEX idx_energy_datetime (datetime)
) ENGINE=InnoDB;
```

| Table | Content | Unit |
|---|---|---|
| `energy_data` | Electrical energy per floor | kWh |
| `occupancy_data` | Occupancy count | persons |
| `water_data` | Water flow | L/min |
| `noise_data` | Ambient noise | dB |
| `iaq_data` | PM2.5 and TVOC | µg/m³, ppb |
| `light_data` | Illuminance | lux |
| `equipment_data` | Vibration, AHU runtime | mm/s, h |

### Registering a narrow table as a data source

In `input/database_registry.yaml`:
```yaml
energy_narrow:
  type: mysql_narrow          # routes to MySQLNarrowAdapter
  table: energy_data
  host: "${MYSQL_HOST}"
  port: 3306
  database: sensordb
  user: "${MYSQL_USER}"
  password: "${MYSQL_PASSWORD}"
```

Add `energy_narrow` to `input/building.yaml` → `storage.databases`.

### MySQLNarrowAdapter

`orchestrator/services/adapters/mysql_narrow_adapter.py` — scoped to one table per adapter instance. Builds:

```sql
SELECT datetime AS timestamp, uuid AS uuid, value AS value
FROM energy_data
WHERE uuid IN (%s, %s, ...)
  AND datetime BETWEEN %s AND %s
ORDER BY datetime
```

The `ref:storedAt bldg:energy_narrow` triple in the TTL tells the adapter registry to route that sensor's UUID queries to this adapter.

### How sensor → UUID → table → answer works

```
SPARQL: ?sensor ref:hasTimeseriesId ?uuid ;
               ref:storedAt ?db .

Result: uuid="550e8400-...", db="energy_narrow"

Adapter registry: routes "energy_narrow" → MySQLNarrowAdapter(table="energy_data")

SQL: SELECT value FROM energy_data WHERE uuid="550e8400-..." AND datetime BETWEEN ...

Answer: "Floor 3 energy consumption was 47.2 kWh between 09:00 and 17:00"
```

---

## 6.8 TTL Extensions — Bldg1 Sensor Coverage

Two extension TTL files expand bldg1's sensor coverage beyond the original abacws metadata:

### `input/bldg1_timeseries_extension.ttl`

19 new sensors across 7 modalities, each wired to a narrow table via `ref:storedAt`:

| Modality | Sensor count | Table | What it enables |
|---|---|---|---|
| Energy meters | 6 (one per floor) | `energy_data` | "What is the energy consumption on floor 3?" |
| Occupancy counters | 6 (one per floor) | `occupancy_data` | "How many people are on floor 4 right now?" |
| Water meter | 1 (main supply) | `water_data` | "What is the water consumption today?" |
| Noise sensor | 1 (floor 5) | `noise_data` | "Is it too noisy for studying on floor 5?" |
| IAQ sensors | 2 (floor 3 — PM2.5 + TVOC) | `iaq_data` | "Is the air quality safe in the lab?" |
| Illuminance sensor | 1 (floor 5) | `light_data` | "What is the lighting level in the reading room?" |
| Equipment sensors | 2 (AHU-03 vibration + runtime) | `equipment_data` | "Is the AHU operating normally?" |

UUID source: `input/bldg1_timeseries_extension_uuids.json` (stable deterministic UUIDs, referenced in TTL and used in the MySQL publisher).

### `input/bldg1_security_lighting_extension.ttl`

293 triples covering lighting systems and security infrastructure:

| System | What's declared |
|---|---|
| Lighting systems | 6 `brick:Lighting_System` instances (one per floor), each with PIR detectors, luminance sensors, lighting command points, and luminaire instances |
| Outdoor | Roof daylight sensor (`bldg:DaylightSensor_Roof`) |
| CCTV | 8 cameras (`bldg:CCTV_Camera` class) with `bldg:coverageArea` triples (entrance, lobby, stairwells, roof) |
| Alarm zones | 6 alarm zones with `bldg:IntrusionDetector` instances and a main `AlarmPanel_Main` |
| Access control | `bldg:Turnstile_MainEntrance` + `bldg:Main_Entrance_Zone` |
| Security system | `bldg:SecuritySystem_Abacws` with `bldg:cameraCount 8` |

This file answers questions like: *"How many CCTV cameras does the building have?"*, *"Is there a motion sensor on floor 3?"*, *"What security zones exist?"*

Both files are auto-discovered by `ttl_uploader.py` on startup (glob `bldg1_*.ttl`). No manual onboarding step required.

---

## 6.9 No-code onboarding — connect a data source, describe it as triples, ask

**This is the core promise of OntoSage: to make a building answerable, an admin adds
*data* and *triples* through the admin console (`:3001`) — never code.** A new deployment
needs three things and nothing else: (1) a datasource holding the readings, (2) triples that
say *what* is installed *where* and *which datasource* holds its data, and (3) the datasource's
access configuration. After that, questions are answered automatically, forever.

### The contract (why two halves are required)

A question about a sensor is answerable only when **both** halves exist and are linked:

| Half | What it is | Where it lives | Added via |
|---|---|---|---|
| **A — the thing** | The sensor/device as an RDF triple: its Brick class, its location, and a **timeseries UUID + a `ref:storedAt` datasource key** | GraphDB (the ontology) | Ontology / Databases tab (form · CSV · TTL) |
| **B — the data** | The actual readings (rows keyed by that UUID) | A registered database (MySQL/Postgres/Timescale/Influx/… hosted **anywhere**) | Databases tab (connection + config) |

The link between them is a single Brick-`ref:` idiom the admin never types by hand unless they
want to — the console generates it:

```turtle
bldg:TempSensor_5_04 a brick:Air_Temperature_Sensor ;
    brick:hasLocation bldg:Room_5.04 ;
    ref:hasExternalReference [
        ref:hasTimeseriesId "a8df8757-009a-4b9c-…" ;   # matches a row key in the DB
        ref:storedAt        bldg:energy_data ] .         # key → database_registry entry
```

`ref:storedAt bldg:<key>` is the whole trick: the key (`energy_data`, `mariadb`, `database1`, …)
maps to a connection in `input/database_registry.yaml` (+ the GUI overlay
`database_registry.custom.yaml`). At query time `services/adapters/registry.py` reads that key
off the SPARQL result and routes the fetch to the right backend — automatically, with the right
adapter (`mysql` / `postgresql` / `timescaledb` / `influx` / …). **A new backend is a new
registry entry, not a code change** (contract #9).

### The end-to-end flow (all in `:3001`, zero code)

```
┌── 1. ADD THE DATASOURCE ────────────────────────────────────────────────┐
│ Databases tab → “+ Add connection”                                       │
│   type (mysql/postgres/timescale/… — 45 templates) · host · port ·       │
│   user · password · database · table                                     │
│   → written to database_registry.custom.yaml (+ .env creds).             │
│   “Test” verifies reachability; “Introspect” lists its tables/columns.   │
│   The DB can be hosted ANYWHERE reachable from the orchestrator network.  │
└──────────────────────────────────────────────────────────────────────────┘
                                   │  (key, e.g. "energy_data")
                                   ▼
┌── 2. DESCRIBE YOUR SENSORS AS TRIPLES ──────────────────────────────────┐
│ Databases tab → that datasource card → “Register sensors” (3 modes):      │
│   • Add points  — a row per sensor: Brick class · location · UUID · unit  │
│   • Import CSV  — bulk: one line per sensor (class, location, uuid, …)     │
│   • Upload TTL  — paste hand-authored Brick TTL                           │
│   Any mode → services/sensor_ttl_generator.py emits the Brick + ref:      │
│   triples above (ref:storedAt is auto-set to THIS datasource) and uploads │
│   them to GraphDB. This is the admin telling OntoSage: “I have this        │
│   sensor, at this location, and its data is in this datasource.”          │
│ (Amenities / policies / maintenance topics are added the same way on the  │
│  Ontology tab’s “Add capability” form — see §6.5 / OCBV, input/ontosage_  │
│  schema.ttl. Those need no datasource; they answer straight from triples.)│
└──────────────────────────────────────────────────────────────────────────┘
                                   │
                                   ▼
┌── 3. ASK — grounded answer, no further setup ───────────────────────────┐
│ Chat (:3000) or the Ask tab (:3001):                                      │
│   “what’s the temperature in room 5.04?”                                   │
│   dialogue → SPARQL finds the sensor by class+location → reads its UUID +  │
│   ref:storedAt → AdapterRegistry routes to the datasource → SQL fetches    │
│   the rows → analytics → a grounded, cited answer. Cached; reused forever. │
└──────────────────────────────────────────────────────────────────────────┘
```

**Onboarding a whole new building** is the same three steps at scale: drop its Brick TTL under
`input/` (or upload it on the Ontology tab), register its datasource(s), point `BUILDING_ID` /
`BUILDING_NAMESPACE` at it. No agent, adapter, or pipeline code changes — everything routes off
the active building's namespace and the `ref:storedAt` keys (contracts #1, #3, #8, #9).

### What’s guided today vs. where it can get smoother

Working today (no code): add/test/introspect a datasource; register sensors by form, CSV, or
TTL; the `ref:storedAt`→adapter routing; answer + cache. The main *friction* is that the sensor
form takes **free-text** `brick:Class` and `bldg:Location` (it assumes Brick vocabulary) and a
hand-entered UUID. Planned "right choices" to make it foolproof for a non-expert admin:

1. **Dropdown-driven sensor form** — a Brick-class picker (Temperature/CO₂/Occupancy/… from the
   loaded schema) and a location picker (existing `brick:Location`/rooms from the graph), so no
   Brick strings are typed. Mirrors the amenity/knowledge form (WS-5).
2. **Introspection-driven mapping** — use the existing `Introspect` endpoint to list the
   datasource's real columns/UUIDs and let the admin map each to a Brick class + location, so
   UUIDs are *selected from real data*, never typed.
3. **“Verify answerability” check** — one click per sensor/datasource that runs the
   resolve→fetch path and reports ✓ answerable / ✗ (declared-but-no-data), closing the loop
   between the two halves immediately.
4. **One “Connect a data source” wizard** chaining add-connection → register-sensors → verify,
   plus a top-level “Connect data” CTA on Overview so the primary workflow is discoverable.
5. **Linkage visibility** — “N sensors linked · M answerable” on each datasource card, and a
   declared-vs-populated indicator on the Ontology tab (closes FIX-004 / CAVEAT-007 honestly).

Endpoints backing the flow: `POST /api/v1/admin/databases` (+ `/test`, `/introspect`,
`/{key}/sensors`, `/{key}/sensors/csv`, `/{key}/sensors/ttl`, `/{key}/data`) and the Ontology
CRUD in §6.5. Generators: `services/sensor_ttl_generator.py`. Routing: `services/adapters/registry.py`.

---

## 6.10 OCBV — the Conversational Building Vocabulary (2026-07-17)

Brick models the building's *technical fabric* for machines; it does not model what a human asks in
plain language. **OCBV** (`input/ontosage_schema.ttl`, `owl:versionInfo "2.0.0"`, CC-BY-4.0) is the
single, self-describing vocabulary that adds that conversational layer over Brick — the schema that
makes a building *talkable-to*, and a standalone publication artifact.

### Non-contradiction contract

OCBV **extends** Brick and never redefines it. It declares only `ontosage:`
(`http://ontosage.org/capabilities#`) and `hbco:` (`http://ontosage.org/hbco#`) terms; where it
touches the physical building it references Brick classes as property ranges
(`ontosage:locatedIn → brick:Location`, `hbco:mapsToBrickClass → a Brick sensor class`); and it aligns
to Brick/REC/BOT/SOSA with SKOS mapping properties only (`skos:relatedMatch`/`closeMatch`, never
`owl:equivalent*`), so loading it can never entail a contradictory Brick fact.

### Modules (all in one file)

| Module | Terms |
|---|---|
| **A — Capabilities** | `ontosage:Capability → Amenity` (PrayerRoom, Cafe, Lift, ToiletFacility, …) `+ KnowledgeTopic` (InformationTopic, Procedure, **Policy**, MaintenanceIssue); Brick-bridge object props (`locatedIn`, `aboutEquipment`, `servesFloor`); datatype props incl. `documentRef`, `effectiveDate`, `policyOwner` |
| **B — Conversation concepts** | `hbco:Concept`, `hbco:mapsToBrickClass`, `hbco:layTerm`, `requiresRecipe`, `personaDepth` — lay word → Brick sensor ("stuffy" → CO₂). Consolidated here from the former `ontology/hbco_core.ttl` (now a stub); `hbco:` terms unchanged |
| **C — Stakeholder roles** | `ontosage:StakeholderRole` (Occupant, FacilityManager, Researcher, SustainabilityOfficer, …) + `asksAbout`/`defaultPersonaDepth` — frames answers, **explicitly not RBAC** |
| **D — Question-intent grammar** | `ontosage:QuestionIntent` (Locate, Quantify, Trend, Compare, Anomaly, Forecast, Comfort, Discover, Procedure, Report) + `intentPattern`/`answeredBy` |
| **E — Report intake** | `ontosage:Report → FaultReport/Complaint/SafetyReport/Feedback/Suggestion` + status/priority/`concernsIssue` |
| **F — Answer provenance** | `ontosage:SourceType` (GraphDB, TimeSeriesDB, Analytics, FloorPlan, **Ontology** and **Document** — an asserted triple and retrieved prose are different strengths of evidence and no longer share one chip — ReportIntake) + `groundedIn`/`isSimulated` — the vocabulary behind honest, auditable answers |
| **G — Competency Qs + example SPARQL** | `ontosage:competencyQuestion` + `ontosage:exampleSparql` annotations per class (paper + RAG) |
| **H / I / J** | Brick/REC/BOT/SOSA alignment; SHACL shapes (Capability/Concept/Report); worked examples + changelog |

Every term carries `rdfs:label` + `rdfs:comment` + `skos:definition` + `skos:example` so each is
individually retrievable when the schema is chunked into a vector store.

**`ontosage:documentRef` makes document retrieval deterministic.** A `KnowledgeTopic`/`Policy` carries
the short authoritative answer *and* names the document that sets it out in full. When a topic
matches, the long-form detail is drawn from *that named file* — retrieval is filtered to it and the
similarity floor dropped, because relevance was already settled by the triple. Without the link, a
policy question is matched to a document by cosine score against a floor tuned for one corpus and one
embedding model, so changing either silently changes which document answers. RDF holds the structure
and the short answer; the document holds the long form; `documentRef` is the join — the schema stays
TTL-first without pretending RDF is a document store. The shared OCBV schema now lives once under
`ontology/ontosage_schema.ttl` (mounted read-only, uploaded per building by the TTL uploader) rather
than a per-building copy that could drift.

### The schema is the source of truth for authoring AND answering

**It drives the console.** `capability_admin.get_capability_classes()` queries the OCBV subclasses in
GraphDB → the "Add capability" **Type** dropdown; `get_capability_form_schema()` returns the datatype
properties + their `rdfs:domain` → the form renders only the **fields whose domain applies to the
selected type** (an Amenity shows `locationText`; a Procedure shows `steps`; a MaintenanceIssue shows
`priority`). Add a class or property to `ontosage_schema.ttl` and it appears in the form after reload
— no code change (falls back to a built-in list if GraphDB is unreachable). Endpoint:
`GET /api/v1/admin/capabilities` → `{types, types_by_kind, form_fields, types_source}`.

**It feeds the RAG/LLM.** The GraphDB similarity-index data query (`ontology_manager._SIM_DATA_QUERY`)
now concatenates each term's `rdfs:comment` + `skos:definition`/`example` + `ontosage:layTerms` +
`ontosage:competencyQuestion` into the indexed `documentText`. So a plain-English question —
*"the toilet is leaking, who do I tell"* — matches `ontosage:MaintenanceIssue`, and the retriever's
bounded-context step then hands that term's `ontosage:exampleSparql` to the LLM as a copy-adaptable
query template. (Verified live: that query retrieves `ontosage:MaintenanceIssue` with its example
SPARQL in context.)

## 6.11 Sensor persistence, auto-reindex & building identity (2026-07-16/17)

- **Sensors persist TTL-first.** Registering a DB's sensors (`db_ontology.register_points/ttl`) now
  writes `input/db_<key>_sensors.ttl` (source of truth) via `input_ttl_store.persist_ttl_file` and
  syncs its named graph — they survive a restart/volume reset (`ttl_uploader` reloads the file) and are
  reindexed. Re-registering **upserts** (per-subject replace, so no duplicate triples / external-ref
  nodes). Removing a connection trashes the file so the removal persists.
- **Automatic, self-healing semantic reindex.** `services/similarity_reindex.py::SimilarityRebuildDebouncer`
  is the single similarity-rebuild gateway: a burst of registrations collapses into one rebuild, and it
  re-runs once if triples arrive mid-rebuild. Rebuild = **delete + create** (`ensure_similarity_index`
  via `POST /rest/similarity`, the correct GraphDB 10.x path) — the in-place SPARQL `rebuildIndex`
  trigger hangs the index on 10.7.4, whereas delete+create rebuilds the Lucene text index in ~10s and
  **self-creates on a fresh volume**. Register / TTL-upload / startup all route through it.
  `GET /api/v1/admin/reindex/similarity-status` (+ a console banner) reports `state`/`ready`/live
  GraphDB status so an admin knows when new data is searchable.
- **Building identity in the GUI.** `GET`/`PUT /api/v1/admin/building/config` read/write
  `ontology_namespace` + `ontology_prefix` + `building_name` into `input/building.yaml` (validated;
  comment-preserving line edit; `config.py` reads `ontology_prefix` → `BUILDING_PREFIX` at boot). The
  per-building onboarding prerequisite, settable without hand-editing — applies after a restart.
- **Building-agnostic retrieval (CAVEAT-044 fix).** `rag-service/graphdbRAG/graphdb_retriever.py` and
  the SPARQL-agent prompts now build the `bldg:` prefix from `settings.BUILDING_PREFIX` +
  `settings.BUILDING_NAMESPACE` instead of a hardcoded abacws literal — IRI shortening and generated
  `PREFIX` declarations are correct for any building.
- **Build provenance.** The orchestrator + rag Dockerfiles bake `ARG GIT_SHA`/`BUILD_TIME` →
  `ENV BUILD_SHA`/`BUILD_TIME`; both `/health` responses report `build.{sha,time}`. Build with
  `GIT_SHA=$(git rev-parse --short HEAD) BUILD_TIME=$(date -u +%FT%TZ) docker compose build`. NB use
  `docker compose up -d <svc>` (recreate) — not `restart` — to run a freshly-built image.

> **Console note.** The running admin console is the **config-panel at `http://localhost:3001`**
> (localhost-only nginx, proxying `/api`+`/auth` to the orchestrator). The React admin portal under
> `frontend/src/` is a dev alternative whose Docker service is off by default — earlier references to a
> `http://localhost:3000/admin` React tab describe that non-default component; use the config-panel.

---

## 7. Phase 11-22 + V3 + P0 changelog

This section captures every architectural change since v1.0. See `CLAUDE.md` for the operational quick-reference.

### OCBV + schema-driven console (2026-07-16/17) — see §6.10, §6.11

| Change | Detail |
|---|---|
| **OCBV 2.0 vocabulary** | `input/ontosage_schema.ttl` consolidated + expanded: HBCO folded in; new stakeholder-role, question-intent, report-intake, answer-provenance modules; competency questions + example SPARQL; Brick/REC/BOT/SOSA alignment; SHACL shapes. `ontology/hbco_core.ttl` reduced to a stub |
| **Schema-driven authoring** | `capability_admin.get_capability_classes()` + `get_capability_form_schema()` — the console's capability **Type dropdown and form fields** are derived from the OCBV subclasses + datatype-property domains |
| **Schema RAG indexing** | `_SIM_DATA_QUERY` enriches `documentText` with comment/definition/example/lay-terms/competency-question → OCBV terms + their example SPARQL become retrievable for the LLM |
| **Sensors persist TTL-first + upsert** | `db_ontology` → `input/db_<key>_sensors.ttl` + graph sync; re-register replaces (no dup ref nodes); connection removal trashes the file |
| **Debounced, self-healing reindex** | `services/similarity_reindex.py` (single gateway) + `ensure_similarity_index` (delete+create via `POST /rest/similarity`); `GET /reindex/similarity-status` + console banner |
| **Building-identity GUI** | `GET`/`PUT /api/v1/admin/building/config` write `ontology_namespace`/`ontology_prefix` to `building.yaml`; `config.py` reads `ontology_prefix` |
| **Building-agnostic retrieval** | `graphdb_retriever` + SPARQL-agent prompts resolve the `bldg:` namespace from settings (CAVEAT-044) |
| **Build provenance** | `GIT_SHA`/`BUILD_TIME` baked into images; `/health.build.{sha,time}` on orchestrator + rag |
| **Reindex gateway fix** | `_get_reindex_service` reads `app.state.doc_indexer` + refreshes indexers each call (CAVEAT-042) |

### P0 — Security Hardening (2026-07-07, branch `security/p0-hardening`)

| Sub | Change |
|---|---|
| P0-A | `require_permission()` dependency chain enforced on all data endpoints; all return 401 on missing/invalid token (was unauthenticated before P0) |
| P0-B | 8 new admin endpoints under `/api/v1/admin/`: `list_named_graphs`, `validate_ttl`, `upload_ttl`, `drop_named_graph`, `sparql_select`, `reindex_trigger`, `reindex_list`, `reindex_status` |
| P0-C | `orchestrator/services/ontology_manager.py` — admin CRUD for GraphDB (async, httpx-based) |
| P0-D | `orchestrator/services/reindex_service.py` — background job queue for Qdrant reindexing; singleton `_reindex_service_instance` in `main.py` |
| P0-E | `orchestrator/services/sensor_ttl_generator.py` — Brick Turtle generator for bulk sensor registration from CSV |
| P0-F | `orchestrator/services/adapters/mysql_narrow_adapter.py` — `MySQLNarrowAdapter` scoped to one narrow `(uuid, datetime, value)` table |
| P0-G | `data/mysql-init/create_narrow_timeseries_tables.sql` — DDL for 7 narrow modality tables in `sensordb` |
| P0-H | `input/bldg1_timeseries_extension.ttl` — 19 sensors across 7 modalities with `ref:storedAt` to narrow tables |
| P0-I | `input/bldg1_security_lighting_extension.ttl` — 293 triples: lighting systems, CCTV cameras, alarm zones |
| P0-J | `frontend/src/pages/AdminPortal.js` — React admin portal (9 tabs: Ontology, KB Reindex, Health, Users, Buildings, Settings, …) |
| P0-K | `frontend/src/components/TopNav.js` — `/admin` nav link added |
| P0-L | `frontend/src/pages/Health.js` — updated to show GraphDB endpoint (removed stale Redis/Fuseki/MySQL entries) |
| P0-M | `tests/test_admin_ontology_endpoints.py` — 13 unit tests; auth via `get_user_context` override pattern |
| P0-N | `STRICT_SECRETS` validator refuses orchestrator startup when any password equals its default |

**P0 test count:** 416 deterministic tests pass (vs. 251 pre-V3 / 121 V3 unit suite). 13 new admin endpoint tests added.

### P0 — Security Hardening, round 2 (2026-07-09)

Findings from a full auth/RBAC/session/adapter audit (`tasks/PRODUCTION_READINESS_AUDIT.md`).

| Sub | Change |
|---|---|
| P0-O | `auth_manager.register_user` default role `readonly` → `occupant` — `readonly` lacked `sensor:read` so a freshly self-registered user got 403 on `POST /chat` |
| P0-P | `/api/files/{filename}` now requires `export:read` via `require_permission()` — was resolving `get_current_user` but never checking it, so any unauthenticated caller could download export files |
| P0-Q | Per-account login lockout (`AuthManager._check_login_lockout` / `_register_failed_login`, Redis-backed) after `LOGIN_MAX_ATTEMPTS` (default 5) failures, `LOGIN_LOCKOUT_SECONDS` (default 900) window — independent of the global per-IP `RateLimitMiddleware`, which can't stop one username being brute-forced from many IPs |
| P0-R | `RateLimitMiddleware` — honors `X-Forwarded-For` only from `TRUSTED_PROXY_CIDRS` (was always keying on the direct TCP peer, so every client behind one proxy shared a bucket); counts via Redis `INCR`/`EXPIRE` when connected so the limit holds across replicas, falls back to the original in-process deque otherwise |
| P0-S | `AuthManager.delete_user` — replaced a blocking `KEYS conversation:*` + per-key `GET`/`json.loads` scan with the existing `user:{id}:conversations` tracked index plus a targeted `SCAN` on the `:{username}` suffix convention; also fixed a live `AttributeError` (`token.decode()` on an already-`str` session token). The admin `DELETE /api/v1/admin/users/{username}` endpoint now calls `auth_manager.delete_user()` instead of `postgres_manager.delete_user()` directly, so a deleted user's Redis sessions are revoked immediately instead of staying valid for up to 7 days |
| P0-T | Password minimum length 6 → 12 (`auth_manager.register_user`, `RegisterRequest`, `UserCreate`) |
| P0-U | `middleware/rbac.py` trimmed to `UserContext` + `ROLE_PERMISSIONS` only — deleted the unwired `SimpleJWT` / `TokenManager` / `UserStore` / `RBACMiddleware` / `create_rbac_dependency` stack (query-param auth instead of header, bare `Exception` → HTTP 500, unsalted SHA-256); its dedicated activation tests in `test_phase_b_activations.py` removed with it |
| P0-V | `tests/test_auth_manager.py` — 7 new unit tests locking in P0-O/Q/S; `test_phase_cde_improvements.py`'s rate-limit test fixed to use a non-exempt route (it had been asserting against `/ping`, which `RateLimitMiddleware._EXEMPT_PATHS` deliberately excludes, so the 429 branch was never exercised) |

**P0 round 2 test count:** 423 deterministic tests pass, 2 skipped (`pytest -m unit -q`), measured 2026-07-09. This round added 7 (`test_auth_manager.py`) and removed 5 (the deleted RBAC stack's activation tests in `test_phase_b_activations.py`); the gap versus round 1's stated 416 baseline wasn't independently reconciled beyond that ±2 net.

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

### Phase 19 — Unified user-report intake

| Sub | Change |
|---|---|
| 19A | `services/report_intake_service.py` — any persona reports a fault, complaint, safety hazard, feedback, or suggestion in plain English. Auto-classified + prioritised (gas/fire → URGENT, broken → HIGH), persona-stamped, stored in the Postgres `user_reports` table, acknowledged with a tracking ID |
| 19B | `maintenance` / `complaint` / `feedback` / `safety_report` / `suggestion` intents route to the `report_intake` handler; admin triage via auto-created views (`v_urgent_reports`, `v_reports_by_persona`, …). Flag: `REPORT_INTAKE_ENABLED` |

### Phase 20 — PhD-grade forecasting + async job queue

| Sub | Change |
|---|---|
| 20A | `agents/forecast_agent.py` + `services/forecasting/` (preprocessor, `horizon_parser`, `model_selector`, `metrics`, `models/` = ARIMA / exponential-smoothing / linear). Triggered inside the `trend` pipeline on forecast/predict queries; emits `forecast_result {model, horizon, metrics{rmse,r2}, points}` for the visualization node (see §5.6) |
| 20B | `services/job_queue.py` — Redis-backed async `JobQueue` for long-running tasks; status via `GET /jobs/{job_id}` (auth-enforced) |

### Phase 21 — Conversation memory + secret/config hardening

| Sub | Change |
|---|---|
| 21A | `services/turn_memory.py` — `TurnMemoryService`: per-turn structured summary into the Postgres `turn_memory` table; `get_carry_forward()` (forecast/analytics artifacts) + `get_older_context()` (long-term summaries) wired into `/v1/chat/completions` |
| 21B | Redis `save_state` now **count-bounds the stored `conversation:<id>` blob** (`state_dict["messages"][-CONVERSATION_MAX_MESSAGES:]`) — the trim acts on the blob `load_state` actually reads. `CONVERSATION_TTL` default → `0` (no time-expiry; count-eviction instead); `.env`/`.env.example` aligned |
| 21C | Secret hygiene: `repr=False` on `OPENAI_API_KEY`, `OLLAMA_CLOUD_API_KEY`, `GRAPHDB_PASSWORD`, `POSTGRES_USER_PASSWORD`, `MYSQL_PASSWORD`, `SECRET_KEY` — pydantic `Settings` repr no longer leaks secrets into logs/test output. `STRICT_SECRETS` validator refuses startup when any password equals its default |
| 21D | `tests/test_turn_memory.py` + `tests/test_conversation_memory_e2e.py` wired into CI |

### Phase 22 — Follow-up co-reference resolution

| Sub | Change |
|---|---|
| 22A | `dialogue_agent._is_followup_query()` — zero-LLM gate (short query OR deictic markers); `DialogueAgent.rewrite_to_standalone()` — gated fast-LLM "condense question" rewrite, graceful fallback, no-ops self-contained queries |
| 22B | `_dialogue_node` rewrites `messages[-1]` before `detect_intent` so intent/entity extraction **and** the SPARQL node resolve the reference; original preserved in `metadata` + `intermediate_results["coref_rewrite"]`. Flag: `COREFERENCE_REWRITE_ENABLED` |
| 22C | **Verified live:** *"avg temperature on floor 3"* → *"and humidity there"* now scopes to floor 3 (previously returned floor 5). `tests/test_coreference_rewrite.py` (16 cases) wired into CI |

**Phase 19-22 verified:** deterministic suite **251 pass / 3 skip / 0 fail** on Python 3.10/3.11/3.12; full `docker-compose up --build` boots healthy; co-reference fix confirmed end-to-end against the live stack.

### V3 — Corpus-Driven Capability Completion (2026-06-11)

Driven by 5,604-question corpus analysis. 37 implementation turns (T01–T37).

| Turn group | What shipped |
|---|---|
| T01–T06 (Phase A) | HBCO TBox/ABox (949 triples, 69 concepts); recipe registry; concept resolver wired into dialogue+SPARQL+analytics |
| T07–T09 (Phase B) | bldg1 metadata enrichment TTL (101 triples); document KB (Qdrant documents_bldg1); idempotent named-graph TTL uploader |
| T10–T11 (Phase C) | 522 new floor 0-4 sensor points; full-building SPARQL verified |
| T12–T15 (Phase D) | Feed adapter framework (csv_drop + rest_poll); auto-registration in GraphDB; weather feed (Open-Meteo); calendar/tariff |
| T16–T19 (Phase E) | 17 new synthetic feeds: occupancy / energy / IAQ / noise / light / water / maintenance / equipment; 38 recipes; long-tail onboarding playbook |
| T20–T22 (Phase F) | ECA rules engine (Redis duration windows); conversational alert creation; honest automation-capability answers |
| T23–T25 (Phase G) | Actuation gateway (SimDriver + approval store); `control:write` RBAC; control intent upgraded to config-gated execute |
| T26–T27 (Phase H) | Goal planner (4 goals, 11 KPIs); three-tier capability report |
| T28–T30 (Phase I) | Corpus replay harness (240q stratified, LLM-graded); bldg2 portability proof; docs update |
| T31–T37 (Phase J) | Wayfinding routes; benchmarking vs peers; notification service; what-if recipes; personalised preferences; maintenance/CMMS records; input validators + scaffolder |

**V3 verified:** 121 unit tests pass, 2 skipped (offline); 32 validator tests pass; 68/68 routing tests pass. Live corpus replay requires running stack: `python scripts/corpus_replay.py --sample 240`.

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
| `COREFERENCE_REWRITE_ENABLED` | `true` | Phase 22 — gated follow-up query rewrite |
| `CONVERSATION_TTL` | `0` | Phase 21 — Redis state TTL in seconds; `0` = no expiry (count-bounded) |
| `CONVERSATION_MAX_MESSAGES` | `20` | Phase 21 — max messages kept in the Redis blob |
| `REPORT_INTAKE_ENABLED` | `true` | Phase 19 — user-report intake |
| `STRICT_SECRETS` | `true` | Phase 21 — refuse boot if any password is still the default; set `false` only for local dev |
| `TTL_VALIDATION_SHACL` | `false` | Phase 12B — needs brickschema |
| `GOAL_PLANNER_ENABLED` | `false` | V3 — goal/mandate decomposition (T26-27) |
| `MULTI_INTENT_ENABLED` | `true` | Phase 14 — compound-query decomposition |
| `FEED_POLL_INTERVAL` | `60` | V3 — seconds between rest_poll feed polls |
| `TRUSTED_PROXY_CIDRS` | `""` | P0 — CIDRs of reverse proxies trusted to set `X-Forwarded-For` for per-IP rate limiting; empty = trust only the direct TCP peer |
| `LOGIN_MAX_ATTEMPTS` | `5` | P0 — failed logins allowed for one username before a temporary lockout |
| `LOGIN_LOCKOUT_SECONDS` | `900` | P0 — lockout duration after `LOGIN_MAX_ATTEMPTS` failures |

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
| `actuation.driver` | no | V3 — `sim` / `none`; controls whether control intent executes |
| `actuation.points_writable` | no | V3 — list of Brick point URIs the driver may set |

### 8.3 `input/<bldg>/intents.yaml` (per-building overlay)

Same schema as the shipped `intent_definitions.yaml`. Entries with the same `name` override; new names extend.

### 8.4 `input/<bldg>/personas/<name>.yaml`

Same schema as `PersonaPriors` dataclass. Loaded by `PersonaRegistry` at startup; `Literal[...]` constraint dropped in Phase 14A so any name resolves.

### 8.5 Capability triples — `input/<id>_capabilities.ttl` (OCBV, replaces `capability.yaml`)

`capability.yaml` was **removed** (TODO-012). Capabilities are now first-class **triples** in
the building's ontology, typed with the OCBV vocabulary (`input/ontosage_schema.ttl`):

- **`ontosage:Amenity`** (+ subclasses `PrayerRoom`, `Cafe`, `Lift`, `ShowerFacility`,
  `ToiletFacility`, `NursingRoom`, `StudyArea`, `BikeStorage`, `Facility`, `Service`) — a
  physical facility a stakeholder can locate and use.
- **`ontosage:KnowledgeTopic`** (+ subclasses `InformationTopic`, `Procedure`,
  `MaintenanceIssue`) — a non-physical fact/policy/how-to/fault route, answered from
  `ontosage:answerText` (+ `steps`, contacts).

Key datatype properties: **`ontosage:layTerms`** (comma-separated plain-language phrasings —
the field the resolver matches questions against; the single most important field),
`answerText`, `capabilityCategory`, `locationText`, `onFloor`, `note`, `steps`,
`contactEmail`/`contactPhone`, `reportTo`, `infoUrl`. Object properties bridge to Brick:
`locatedIn` (→`brick:Location`), `servesFloor` (→`brick:Floor`), `aboutEquipment`.

```turtle
bldg:Cap_lift a ontosage:Lift, ontosage:Amenity ;
    rdfs:label "Main passenger lift"@en ;
    ontosage:layTerms "lift, elevator, where is the lift, nearest lift, accessible lift" ;
    ontosage:locationText "Left of reception" ;
    ontosage:capabilityCategory "ACCESSIBILITY" .

bldg:Cap_wifi a ontosage:InformationTopic, ontosage:KnowledgeTopic ;
    rdfs:label "WiFi and network access"@en ;
    ontosage:layTerms "wifi, wi-fi, internet, eduroam, guest network, connect to wifi" ;
    ontosage:answerText "Guests use the guest SSID (captive portal); staff use eduroam." .
```

**Authoring** (no hand-written Turtle needed): the admin Capabilities tab / `POST
/api/v1/admin/capabilities` (`services/capability_admin.py`) turns guided form fields into a
dual-typed instance on the building's namespace, validated against the OCBV schema, persisted
to `input/<id>_capabilities.ttl`, and re-synced into GraphDB — the response cache is flushed so
the new capability answers on the next question. Answered live by
`services/capability_graph_resolver.py`. Migration of a legacy `capability.yaml`:
`scripts/migrate_capability_yaml_to_ttl.py` (`keywords → layTerms`, `content → answerText`).

> **Long-form manuals stay as documents.** `answerText` is a *one-line canonical answer* by
> design — genuine multi-page manuals (governance, maintenance procedures) belong in
> `input/<bldg>/documents/` (the semantic document KB), not crammed into a single triple.

### 8.6 `input/<bldg>/feeds.yaml` (V3 — external data feeds)

```yaml
feeds:
  - id: outside_weather_temp
    type: rest_poll          # or csv_drop
    url: https://api.open-meteo.com/v1/forecast?…
    interval_s: 300
    brick_class: brick:Outside_Air_Temperature_Sensor
    storage: mysql
    field_map:
      temperature_2m: value
```

All types: `rest_poll`, `csv_drop`. Absence of this file = feed framework idle. Feed points auto-register in GraphDB on boot (named graph per building). Secrets via env-var name only — never literal in YAML.

### 8.7 `input/<bldg>/rules.yaml` (V3 — ECA operator rules)

```yaml
rules:
  - id: co2_high_room501
    trigger:
      concept: co2_level       # OR sensor_uuid: <uuid>
      op: ">"
      threshold: 1000
    action:
      type: notify
      message: "CO2 high in room 5.01"
```

Evaluated by `rules_engine.py` on a polling loop. Duration windows (`duration_min`) and cooldown (`cooldown_min`) tracked in Redis. Users may also create personal alert rules via conversation (`alert_mgmt` intent); those are stored separately in Redis and merged at evaluation time.

### 8.8 `input/<bldg>/channels.yaml` (V3 — notification dispatch)

```yaml
channels:
  - type: log          # always present as default
  - type: webhook
    url: https://hooks.example.com/ontosage
    enabled: false     # set true to activate
  - type: smtp
    from: alerts@example.com
    # SMTP_PASSWORD env var — never hardcode
```

### 8.9 `input/<bldg>/benchmarks.csv` (V3 — peer benchmarks)

Columns: `metric`, `p25`, `p50`, `p75`, `unit`, `source`. Used by `energy_intensity_benchmark` and `co2_benchmark` recipes to compare this building's readings against a sector percentile.

### 8.10 `input/<bldg>/concepts.ttl` (V3 — HBCO local vocabulary)

```turtle
@prefix hbco: <http://ontosage.org/hbco#> .
@prefix brick: <https://brickschema.org/schema/Brick#> .

<http://bldg1.example.org#the_fishbowl_concept> a hbco:Concept ;
    hbco:layTerm "the fishbowl"^^xsd:string ;
    hbco:mapsToBrickClass brick:Room .
```

Loaded alongside the building-independent `hbco_mappings.ttl`. Per-building terms extend, never override, the shared vocabulary.

### 8.11 `input/<bldg>/documents/` (V3 — document KB)

Markdown, PDF, or TXT files indexed into Qdrant collection `documents_<bldg>`. Retrieved by the capability agent when KB confidence is low; document name cited in the answer. Seed files for bldg1: `governance.md`, `fire_safety.md`, `hvac_operation.md`, `maintenance_log.md`.

---

## 9. Test coverage

### 9.1 Deterministic suite (CI — Phase 16C, expanded through P0)

**Current suite: 981 pass, 8 skip, 0 fail** on the Python 3.10/3.11/3.12 matrix.

Honesty, self-description, embedding and portability guards (selected):

| File | Tests | Coverage |
|---|---|---|
| `test_routing_contract.py` | 51 | Every question-shape → intent rule + precedence + a source scan proving no building literal |
| `test_grounding_guard.py` | 47 | Unrelated-passage refusal; typed-referent existence gate; verb-inflection matching; the "I don't hold that fact" caveat |
| `test_absent_referent_metrics.py` | 18 | A named place the building lacks is declined, not answered with whole-building figures — including when the existence check times out (fail-closed on a named referent) |
| `test_plausibility.py` | 11 | No comparative verdict over a value outside every plausible unit-range for its measurand |
| `test_self_description.py` | 16 | "What is OntoSage / what can you do" composed from live config as a building-agnostic framework; never a bare-LLM claim, never a per-building literal |
| `test_ontology_inventory.py` | 18 | "What equipment/sensors does this building have" from the graph's own Brick classes |
| `test_entity_label_resolution.py` | 12 | A prose-named sensor resolves to the one asked about, across two naming conventions |
| `test_embedding_standardisation.py` | 14 | Retrieval floor + vector width derived from the loaded model |
| `test_embedding_consistency.py` | 9 | Boot sweep drops any Qdrant collection at a mismatched width, for any building |
| `test_document_indexer_hygiene.py` | 7 | Any-encoding document indexing; deleted-document folders never treated as a building |
| `test_agents_building_agnostic.py` | 2 | Source scan: no agent names a building in code |

Legacy baseline rows (still passing):

| File | Tests | Coverage |
|---|---|---|
| `test_phase3_4_services.py` | many | Phase 3/4 services (legacy baseline) |
| `test_phase_a_fixes.py` | 44 | Persona + new intents routing (updated for Phase 14A) |
| `test_survey_aligned_phases.py` | 64 | Capability KB + persona + G1 taxonomy + workflow wiring |
| `test_workflow_wiring.py` | 4 | Behavioral wiring contracts (Phase 17-updated) |
| `test_routing_accuracy.py` | 29 | All 20+ intents + 5 override scenarios + 4 audit invariants |
| `test_intent_graph_autowire.py` | 5 | Every `node_method` resolves; every registry node in graph |
| `test_unregistered_intent_safety_net.py` | 3 | YAML-added intent with no node → safe fallback |
| `test_auth_manager.py` | 7 | P0 round 2 — default registration role, per-account login lockout, delete_user Redis cleanup |
| `test_multi_tenant_fixture.py` | 5 | bldg2 fixture exercises per-building infra |
| `test_blended_persona.py` | 14 | Persona blending semantics |
| `test_compound_query_e2e.py` | 17 | Multi-intent heuristic + decomposition (incl. Phase 16A short-compound) |
| `test_state_persistence.py` | 7 | ConversationState ↔ JSON round-trip with `personas` |
| `test_swap_building.py` | 6 | swap_building CLI integration (dry-run, apply, mismatch, missing dir, no-op) |
| `services/test_ttl_validator.py` | 10 | TTL parse + prefix/namespace + SHACL gating |
| `test_turn_memory.py` | 10 | Phase 21 — Redis count-eviction, no-TTL SET, Postgres `turn_memory` schema |
| `test_conversation_memory_e2e.py` | — | Phase 21 — carry-forward round-trip, older-context format, no raw arrays stored |
| `test_coreference_rewrite.py` | 16 | Phase 22 — follow-up heuristic gate + gated LLM rewrite (mocked) |
| `test_admin_ontology_endpoints.py` | 13 | P0 — all 8 admin endpoints; auth via `get_user_context` override; mocked GraphDB/Qdrant |

**Auth pattern used in admin tests** (override `get_user_context`, not `get_current_user`):
```python
from orchestrator.middleware.rbac import ROLE_PERMISSIONS, UserContext
from orchestrator.main import app, get_user_context

app.dependency_overrides[get_user_context] = lambda: UserContext(
    user_id="testadmin", username="testadmin", role="admin",
    tenant_id="default", allowed_buildings=[],
    permissions=ROLE_PERMISSIONS.get("admin", set()),
)
```

### 9.2 Live e2e suite (NOT in CI — needs running stack)

- `test_capability_e2e.py` — capability KB → answer
- `test_floor_plan_e2e.py` — floor plan API
- `test_non_regression_intents.py` — intent routing against live LLM
- `test_ontology_integrity.py` — discovery → SPARQL → GraphDB

These exercise the full stack and have LLM nondeterminism. Run manually before deploys.

### 9.3 Live survey and corpus replay

**Corpus replay (2026-06-18):** 240 stratified questions, LLM-graded, live stack required:

```
corpus_replay pass rate: 63.8%   (vs 16.2% baseline before V3)
```

Run: `python scripts/corpus_replay.py --sample 240`

**Live survey (`scripts/survey_live_test.py`):** 95-question battery covering 16 categories. **Phase 18 + libredwg baseline (2026-05-30):**

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
| "Where is the prayer room?" | `capability` → CapabilityGraphResolver | Returned location from the `ontosage:Amenity` triple in `bldg1_capabilities.ttl` |
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
pytest tests/ -m unit -q                        # fast offline suite — 981 pass (8 skip) ~1 min
pytest tests/test_routing_accuracy.py -v        # 29 canonical routing cases
pytest tests/test_admin_ontology_endpoints.py   # 13 P0 admin endpoint tests
```

Or rely on `.github/workflows/ci.yml` — runs the full suite on Python 3.10/3.11/3.12.

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

OntoSage is MIT-licensed. The Phase 11-22 work documented here was developed against Cardiff University's Abacws building (`bldg1`) with `bldg2` as a multi-tenant fixture. The Brick Schema ontology is BSD-licensed; the orchestrator's LLM provider abstraction supports both OpenAI and local Ollama models for cost / privacy flexibility.

The single-building-at-a-time design is intentional for v1. The future Onto-community release will support multiple simultaneous buildings; the per-building infrastructure (registry caches, BuildingContext resolver, per-building Qdrant collections, persona overlays) is the forward-compatible foundation already in place.
