# Project Structure

This page documents the OntoSage repository layout, explains the role of every important file and directory, and establishes the conventions that govern the codebase.

---

## Repository Root

```
OntoSage/
├── orchestrator/           # FastAPI app + LangGraph pipeline (the core)
├── rag-service/            # RAG retrieval service (GraphDB similarity + graph traversal)
├── code-executor/          # Sandboxed Python analytics execution service
├── shared/                 # Config, models, utilities shared across services
├── tests/                  # All test files (unit, integration, performance)
├── scripts/                # CLI tools (onboarding, benchmarking, sensor cache)
├── config/                 # Building config YAML + database registry
├── data/                   # Building ontology files (TTL), test datasets
├── docs/                   # Documentation (this site)
├── .github/                # GitHub Actions CI/CD workflows
├── docker-compose.yml      # Complete service stack definition
├── mkdocs.yml              # MkDocs Material documentation site config
├── .env.example            # Documented environment variable template
├── pytest.ini              # Pytest configuration (markers, asyncio mode)
└── CLAUDE.md               # AI assistant instructions for this repo
```

---

## `orchestrator/` — The Core

The orchestrator is a **FastAPI + LangGraph** application that handles all user requests.

```
orchestrator/
├── main.py                 # FastAPI app entry point; all endpoint registrations; startup lifecycle
├── workflow.py             # LangGraph state machine; ALL routing logic; _safe_node wrapper
├── llm_manager.py          # LLM provider abstraction (OpenAI / Ollama); model switching
├── auth_manager.py         # User authentication; Argon2id hashing; session tokens
├── redis_manager.py        # Redis connection pool; conversation state persistence; caching
├── postgres_manager.py     # PostgreSQL connection for user accounts (RBAC data)
├── Dockerfile              # Production container image
├── requirements.txt        # Python dependencies
│
├── agents/
│   ├── dialogue_agent.py   # Intent classification (22+ types), entity extraction, time-range parsing,
│   │                       #   SemanticRouter probe + follow-up co-reference rewrite (Phase 22)
│   ├── capability_agent.py # v3.1 — answers off-ontology questions from per-building KB
│   ├── sparql_agent.py     # SPARQL generation + execution + RAG fallback + UUID extraction
│   ├── sql_agent.py        # Time-series data fetching via storage adapters
│   ├── analytics_agent.py  # LLM-generated Python code; calls code-executor; interprets results
│   ├── forecast_agent.py   # Phase 20 — multi-model time-series forecasting (ARIMA/ETS/linear)
│   ├── visualization_agent.py # Chart generation (matplotlib/plotly); calls code-executor
│   ├── report_agent.py     # Structured building reports (multi-section formatted output)
│   ├── anomaly_agent.py    # Threshold breach detection and anomaly summarisation
│   ├── planner_agent.py    # Multi-step task orchestration (planner intent)
│   ├── data_export_agent.py # Data export to CSV/JSON/HTML
│   ├── document_agent.py   # Building document generation
│   ├── floor_plan_agent.py # Floor plan rendering + manifest lookup
│   ├── spatial_agent.py    # Spatial geometry queries from DWG manifests (no LLM)
│   └── semantic_ontology_agent.py # Semantic ontology search and grounding
│
├── services/
│   ├── adapters/           # Database storage adapters (see below)
│   ├── analytics_engine.py # Deterministic analytics without LLM (mean, std, trend)
│   ├── capability_indexer.py # NEW v3.1 — startup pipeline: capability.yaml → Qdrant (SHA-256 idempotent)
│   ├── circuit_breaker.py  # Circuit breaker pattern for external service calls
│   ├── context_manager.py  # Conversation context windowing and summarisation
│   ├── database_adapter.py # Abstract base class (ABC) for all storage adapters
│   ├── disambiguation_service.py # Resolve ambiguous entity mentions (multiple zones match)
│   ├── document_builder.py # Structured document assembly for report/export agents
│   ├── embedding_service.py # v3.1 — provider-agnostic embeddings (OpenAI 1536-d / local 384-d) with Redis cache
│   ├── turn_memory.py       # Phase 21 — TurnMemoryService: Postgres per-turn summaries + carry-forward
│   ├── forecasting/         # Phase 20 — preprocessor, horizon_parser, model_selector, metrics, models/
│   ├── job_queue.py         # Redis-backed async job queue (long-running tasks → GET /jobs/{id})
│   ├── report_intake_service.py # Phase 19 — fault/complaint/safety/feedback intake → user_reports table
│   ├── floor_plan_pipeline.py # PDF + DWG ingestion → manifest → Qdrant
│   ├── floor_plan_registry.py # Merge orchestrator for PDF + DWG floor plan data
│   ├── floor_plan_watcher.py  # File-watcher (watchfiles) for live ingest on file drop
│   ├── hybrid_retrieval.py # Hybrid RAG retrieval (GraphDB similarity + SPARQL context)
│   ├── i18n_service.py     # Language detection + translation (30+ languages)
│   ├── multi_building_manager.py # Multi-building context switching
│   ├── ontology_detector.py # Detect ontology schema from TTL (Brick/REC/S223)
│   ├── ontology_introspector.py # Live GraphDB introspection (class counts, available sensors)
│   ├── ontology_validator.py # Validate ontology completeness for onboarding
│   ├── persona_adapter.py  # Tailor responses to user role (facility manager vs occupant)
│   ├── prompt_builder.py   # System prompt construction for each agent
│   ├── reasoning_engine.py # Chain-of-thought reasoning for complex multi-step queries
│   ├── response_cache.py   # Redis-backed response caching (SPARQL + SQL results)
│   ├── self_correction_engine.py # Auto-repair SPARQL/code errors and retry
│   ├── semantic_router.py  # NEW v3.1 — query-time classifier (three-band threshold logic)
│   ├── smart_cache.py      # Intelligent cache key generation (semantic deduplication)
│   ├── sparql_validator.py # SPARQL syntax validation before execution
│   └── standards_engine.py # ASHRAE/comfort/air quality standards evaluation
│
├── middleware/
│   └── rbac.py             # RBAC middleware: 6 roles, 20 permissions, FastAPI dependency
│
└── data/                   # Runtime data files (sensor label maps, etc.)
```

### Key Files in Detail

#### `orchestrator/workflow/` (package)

The heart of OntoSage — the LangGraph state machine. The former single `workflow.py` was split into a package (zero external-import change — `from orchestrator.workflow import WorkflowOrchestrator` still works):

| Module | What it does |
|--------|--------------|
| `__init__.py` | Re-exports `WorkflowOrchestrator` |
| `_orchestrator.py` | All node implementations + `_route_from_dialogue()` (registry-driven routing across the 22+ intents, incl. `capability` v3.1, the co-reference rewrite, and forecasting dispatch) |
| `_graph.py` | `WorkflowGraphMixin._build_graph()` — auto-registers nodes from the YAML intent registry + `_safe_node()` wrapper |
| `_routing.py` | `WorkflowRoutingMixin` — the downstream routing methods |

Nodes auto-register from `orchestrator/intents/intent_definitions.yaml`, so adding an intent needs no graph edits (see the [Developer Guide](DEVELOPER_GUIDE.md#adding-a-new-intent-type)).

#### `orchestrator/main.py`

FastAPI application lifecycle and all HTTP/WebSocket endpoints:

| Line range | What it does |
|-----------|--------------|
| 1–100 | App initialization, middleware registration, startup/shutdown lifecycle |
| 100–400 | All route registrations (`/health`, `/chat`, `/v1/chat/completions`, RBAC-protected data endpoints) |

#### `orchestrator/llm_manager.py`

Single point of entry for all LLM calls. Reads `MODEL_PROVIDER` and delegates to OpenAI or Ollama. All agents import and use `llm_manager.generate(prompt)`.

---

### `orchestrator/services/adapters/`

Storage adapters for all supported database backends:

```
adapters/
├── __init__.py             # Guarded imports (try/except) for optional dependencies
├── registry.py             # AdapterRegistry: maps building_id → adapter instance
├── mysql_adapter.py        # MySQL / MariaDB / TiDB adapter (aiomysql)
├── postgresql_adapter.py   # PostgreSQL adapter (asyncpg)
├── timescaledb_adapter.py  # TimescaleDB adapter (asyncpg + hypertable queries)
├── mongodb_adapter.py      # MongoDB adapter (motor async driver)
├── influxdb_adapter.py     # InfluxDB 2.x adapter (influxdb-client, Flux)
├── sqlite_adapter.py       # SQLite / DuckDB adapter (aiosqlite)
├── cassandra_adapter.py    # Cassandra / ScyllaDB adapter (cassandra-driver)
└── redis_timeseries_adapter.py  # Redis TimeSeries adapter (redis.asyncio)
```

All adapters implement the `DatabaseAdapter` ABC from `services/database_adapter.py`. The registry reads `config/database_registry.yaml` at startup and instantiates the correct adapter for each entry.

---

## `shared/` — Common Models and Config

```
shared/
├── config.py       # All env vars; single source of truth for service URLs and feature flags
├── models.py       # ConversationState and all Pydantic request/response models
├── utils.py        # get_logger(), hash utilities, common helpers
├── constants.py    # Application-wide constants
└── structured_logger.py  # Structured JSON logging with trace ID injection
```

#### `shared/config.py`

Read by every service. Exposes a `settings` object populated from environment variables. No service should hard-code URLs — always read from `settings`.

#### `shared/models.py`

Contains `ConversationState` — the single object passed between all LangGraph nodes:

```python
class ConversationState(BaseModel):
    session_id: str
    user_id: str
    intent: Optional[str] = None
    building_id: str = "bldg1"
    messages: List[Dict[str, Any]] = []
    intermediate_results: Dict[str, Any] = {}  # the main data bus
```

The `intermediate_results` dict has many reserved keys (see [Architecture](ARCHITECTURE.md#conversation-state)).

---

## `rag-service/` — Retrieval-Augmented Generation

```
rag-service/
└── graphdbRAG/
    ├── app.py              # FastAPI app; /graphdb/retrieve and /health endpoints
    ├── retriever.py        # GraphDB similarity search + graph traversal logic
    └── requirements.txt    # Service-specific dependencies
```

The RAG service connects to GraphDB's similarity plugin, performs semantic entity search, traverses RDF triples up to N hops, and returns a structured context block for use in SPARQL generation prompts.

---

## `code-executor/` — Analytics Sandbox

```
code-executor/
├── app.py          # FastAPI app; /execute endpoint
├── sandbox.py      # RestrictedPython-based execution; SafeModule whitelist
├── Dockerfile      # Non-root user, no network access, resource limits
└── requirements.txt
```

Executes Python code submitted by the analytics and visualization agents. The sandbox blocks all filesystem, network, and process access. Only pre-approved scientific libraries (pandas, numpy, matplotlib, plotly) are importable.

---

## `tests/` — Test Suite

```
tests/
├── conftest.py                      # Fixtures, mock setup, pytest configuration
├── fixtures/
│   ├── ontology_fixtures.py         # TTL snippets, SPARQL response mocks
│   └── __init__.py
├── test_workflow_wiring.py          # Structural: verify all nodes/edges/routes are registered
├── test_routing_and_contracts.py    # HTTP: verify all endpoints return correct envelopes
├── test_integration_mock_building.py # E2E: full pipeline with mocked LLM
├── test_orchestrator.py             # Unit: orchestrator logic
├── test_phase_a_fixes.py            # Regression: Phase A bug fixes
├── test_phase_bc_services.py        # RBAC, response cache, analytics services
├── test_phase3_4_services.py        # Ontology detection, similarity services
├── test_phase_b_activations.py      # Phase B feature activations
├── test_phase_cde_improvements.py   # Phase C/D/E improvements
├── test_code_executor.py            # Sandbox security and execution tests
├── test_rag_service.py              # RAG retrieval quality
├── performance_benchmark.py         # Latency benchmarks (not run in CI)
├── rag_benchmark.py                 # RAG quality benchmarks
└── example_queries.py               # 100+ example queries for testing
```

Run with:
```bash
pytest tests/ -v                    # all tests
pytest -m unit                      # fast unit tests only
pytest -m integration               # requires Docker services
```

---

## `scripts/` — CLI and Automation Tools

```
scripts/
├── onboard_building.py     # Interactive CLI to register a new building (6-step wizard)
├── evaluate_survey_questions.py  # Evaluate OntoSage against survey question dataset
└── switch-model.ps1        # PowerShell script to switch Ollama models
```

---

## `config/` — YAML Configuration Files

```
config/
├── building_config.yaml    # Building metadata (namespace, timezone, abox/tbox files, DB backend)
└── database_registry.yaml  # All 30+ database entries; maps TTL storedAt keys → adapters
```

These files are read at orchestrator startup. Changes take effect after `docker compose restart orchestrator`.

---

## `data/` — Ontology and Dataset Files

```
data/
├── Brick.ttl               # Brick Schema vocabulary (TBox)
├── bldg1_protege.ttl       # Building 1 ABox (Cardiff Abacws Building)
└── ...                     # Additional building TTL files
```

TTL files in `data/` are the authoritative source for building ontologies. Load them into GraphDB via the REST API or the Workbench.

---

## `docs/` — Documentation Site

```
docs/
├── index.md                # Home page — overview, quick start, capability table
├── ARCHITECTURE.md         # Component design, data flow, design decisions
├── WORKFLOW.md             # Step-by-step request lifecycle with example traces
├── SERVICES.md             # Every service: ports, health, env vars, API
├── DEPLOYMENT.md           # Docker Compose deployment guide
├── BUILDING_ONBOARDING.md  # Connecting a new building ontology and database
├── CONFIGURATION.md        # Complete environment variable reference
├── GRAPHDB_SETUP.md        # Similarity index creation guide
├── USER_GUIDE.md           # End-user guide with examples for all 22+ intent types
├── CAPABILITY_ROUTING.md   # NEW v3.1 — semantic vector routing for off-ontology queries
├── DEVELOPER_GUIDE.md      # Dev setup, adding agents, testing, CI
├── SECURITY.md             # Auth, RBAC, sandbox, secrets management
├── RUNBOOK.md              # Operations: start/stop, backups, troubleshooting
├── PROJECT_STRUCTURE.md    # This file
└── superpowers/            # Internal design specs and planning documents
```

The documentation site is built with MkDocs Material and deployed to GitHub Pages at:
`https://suhasdevmane.github.io/OntoSage/`

---

## `.github/` — CI/CD

```
.github/
└── workflows/
    ├── ci.yml              # 9-job CI pipeline: lint → tests → security → docker build
    └── mkdocs.yml          # Documentation deployment to GitHub Pages
```

The CI pipeline runs on every push to `main`, `develop`, and `feature/**` branches.

---

## `docker-compose.yml`

Defines the entire OntoSage service stack. Key sections:

| Lines | Content |
|-------|---------|
| 1–50 | Shared networks (`ontobot-agentic`, `ontobot-network`) and volume definitions |
| Orchestrator service | FastAPI app container; env vars; depends_on with health checks |
| RAG service | GraphDB RAG retrieval; depends on graphdb |
| Code Executor | Analytics sandbox; network isolation |
| GraphDB | RDF store; JVM heap settings; volume for data persistence |
| MySQL | Building 1 sensor data; volume |
| PostgreSQL | User accounts and RBAC data |
| Redis | Conversation state; caching |
| MongoDB | Chat history |
| Qdrant | Vector database for agent memory |
| Open WebUI | Chat interface; points to orchestrator's OpenAI-compatible endpoint |
| Ollama | Local LLM (only in `local-gpu` profile) |

---

## `outputs/` — Runtime Outputs

```
outputs/
├── static/                 # Generated charts (PNG/SVG) served by orchestrator
└── data/                   # Per-session analytics data files (JSON)
```

The analytics and visualization agents write to `outputs/` inside the orchestrator container. Charts are referenced as `/static/<filename>` in chat responses and served by FastAPI's `StaticFiles` mount.

---

## Coding Conventions

### File Naming

- Agent files: `<name>_agent.py` (e.g., `sparql_agent.py`)
- Service files: `<name>_service.py` or descriptive noun (`circuit_breaker.py`)
- Test files: `test_<module>.py`
- Config files: `<building_id>_building_config.yaml`

### Import Order (enforced by isort)

1. Standard library
2. Third-party packages
3. `shared/` modules
4. `orchestrator/` modules

### What Goes Where

| Type of code | Location |
|---|---|
| LangGraph nodes and routing | `orchestrator/workflow.py` |
| Agent logic (LLM calls, result parsing) | `orchestrator/agents/<name>_agent.py` |
| Reusable business logic | `orchestrator/services/<name>.py` |
| Database I/O | `orchestrator/services/adapters/<backend>_adapter.py` |
| Shared data models | `shared/models.py` |
| All configuration variables | `shared/config.py` |
| FastAPI endpoints | `orchestrator/main.py` |
| RBAC rules | `orchestrator/middleware/rbac.py` |

Never add new top-level fields to `ConversationState` without updating `shared/models.py`. Never hardcode service URLs — always use `shared/config.settings`.
