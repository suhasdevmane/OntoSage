# OntoSage Orchestrator Recovery & Deployment — Design Spec

**Date:** 2026-03-31
**Status:** Approved
**Approach:** A — Extract + Decompile + Write Missing + Docker Compose Rewrite

---

## 1. Problem Statement

The `orchestrator/` source files were removed from git, leaving only compiled `.pyc`
bytecode. The `ontosage-orchestrator:latest` Docker image (built 2026-03-27) contains
the complete source. Three additional files (`circuit_breaker.py`, `logging_context.py`)
exist only as Python 3.10 bytecode compiled after the image. Three more
(`document_agent.py`, `persona_adapter.py`, `standards_engine.py`) appear in the spec
but not in the image or bytecode.

The `docker-compose.yml` still references legacy Rasa-era services and does not define
the orchestrator, Redis, PostgreSQL, Qdrant, or code-executor services.

---

## 2. Source Inventory

### 2a. Extract from `ontosage-orchestrator:latest` (45 files)

All files live under `/app/` inside the image.

**orchestrator/ root (6 files):**
- `main.py` (1527 lines) — FastAPI app, 25+ endpoints, lifespan manager
- `workflow.py` (1092 lines) — LangGraph StateGraph, 11 agents, 14-intent routing
- `llm_manager.py` — Provider-agnostic LLM (Ollama / OpenAI / Cloud)
- `auth_manager.py` — User registration, login, JWT sessions
- `redis_manager.py` — Conversation state, caching, message history
- `postgres_manager.py` — Persistent user data, chat history
- `__init__.py`

**orchestrator/agents/ (10 agent files):**
- `dialogue_agent.py` (510 lines) — 14-intent detection, entity extraction, persona
- `sparql_agent.py` (1479 lines) — RAG-enhanced SPARQL + 4-strategy self-correction
- `sql_agent.py` (492 lines) — UUID-based + Text-to-SQL, SELECT-only enforcement
- `analytics_agent.py` (627 lines) — Deterministic engine + code-gen sandbox
- `visualization_agent.py` (353 lines) — Chart generation, base64 embedding
- `planner_agent.py` (329 lines) — Multi-step decomposition
- `report_agent.py` (259 lines) — Structured report generation
- `anomaly_agent.py` (258 lines) — Threshold + Z-score + spike detection
- `data_export_agent.py` (198 lines) — JSON/CSV/HTML/Markdown export
- `semantic_ontology_agent.py` (332 lines) — Semantic RAG-based ontology queries
- `__init__.py`

**orchestrator/services/ (22 service files):**
- `analytics_engine.py` (487 lines) — 5 deterministic analysers
- `self_correction_engine.py` (422 lines) — 4-strategy SPARQL repair
- `smart_cache.py` (344 lines) — 5-strategy cache invalidation
- `response_cache.py` (382 lines) — Redis-backed response deduplication
- `streaming_adapter.py` (442 lines) — MQTT/Kafka hot-path anomaly
- `ws_streaming.py` (264 lines) — WebSocket streaming
- `reasoning_engine.py` (359 lines) — Multi-hop reasoning (4-step)
- `i18n_service.py` (235 lines) — 30+ language support
- `agent_memory.py` (304 lines) — Qdrant-backed per-user memory
- `multi_building_manager.py` (321 lines) — Tenant isolation, building switching
- `hybrid_retrieval.py` (176 lines) — Combined SPARQL + vector search
- `ontology_detector.py` (358 lines) — Auto-detect schema (Brick/ASHRAE/REC)
- `ontology_introspector.py` (211 lines) — Extract topology from TTL
- `ontology_validator.py` (152 lines) — Validate TTL against SHACL shapes
- `database_adapter.py` (134 lines) — Polyglot DB discovery from `ref:storedAt`
- `database_schema_discovery.py` (101 lines) — Runtime column/table introspection
- `plugin_registry.py` (322 lines) — Plugin auto-discovery
- `prompt_builder.py` (212 lines) — Building-agnostic prompt construction
- `context_manager.py` (75 lines) — Conversation context windowing
- `sparql_validator.py` (237 lines) — Pre-execution query validation
- `adapters/mysql_adapter.py`, `adapters/postgresql_adapter.py`, `adapters/registry.py`

**orchestrator/middleware/ (1 file):**
- `rbac.py` (385 lines) — 6 roles, 19 permissions, HS256 JWT

**shared/ (5 files):**
- `config.py` — Pydantic Settings with full provider/building/security config
- `models.py` — ConversationState, Message, APIResponse, shared Pydantic models
- `utils.py` — Logger factory, ID generators
- `constants.py` — System-wide constants
- `structured_logger.py` — JSON structured logging

**Infrastructure files (also extracted):**
- `orchestrator/Dockerfile`
- `orchestrator/requirements.txt`

### 2b. Extract from `ontosage-code-executor:latest` (3 files)

- `code-executor/main.py` — FastAPI sandboxed execution service
- `code-executor/sandbox.py` — Import whitelist, resource limits, asyncio timeout
- `code-executor/__init__.py`
- `code-executor/Dockerfile` (also inside image)

### 2c. Decompile from Python 3.10 bytecode (2 files)

Both are confirmed Python 3.10 (`magic=3439`), compatible with `uncompyle6`.
Install: `pip install uncompyle6`

- `orchestrator/services/__pycache__/circuit_breaker.cpython-310.pyc` → `circuit_breaker.py`
  - 5548 bytes bytecode; compiled 2026-03-28 (newer than Docker image)
  - Implements: `CircuitBreaker` class with OPEN/HALF_OPEN/CLOSED states,
    failure threshold, reset timeout, async `call()` decorator
- `orchestrator/services/__pycache__/logging_context.cpython-310.pyc` → `logging_context.py`
  - 2047 bytes bytecode; compiled 2026-03-28
  - Implements: correlation-ID context var, `get_correlation_id()`, `set_correlation_id()`

After decompile: manually review and clean generated output (uncompyle6 sometimes
emits syntactic artifacts for 3.10).

### 2d. Write from Spec (3 files)

These are absent from both image and bytecode but are specified in SYSTEM_REPORT.md.
Write clean, minimal implementations.

**`orchestrator/agents/document_agent.py`**
- Class `DocumentAgent` with `async generate(state: ConversationState) -> ConversationState`
- Document types: `summary`, `executive_kpi`, `anomaly_digest`, `compliance_report`,
  `energy_report`, `iaq_report`, `research_export`
- Generates Markdown (always), HTML (optional), PDF/DOCX via `weasyprint`/`python-docx`
  with graceful fallback if libraries unavailable
- Triggered by intent `document` or via `DocumentAgent` call in response node
- Saves output to `settings.EXPORTS_DIR`, returns download URL in response

**`orchestrator/services/persona_adapter.py`**
- Class `PersonaAdapter` with `async adapt(response: str, persona: str, context: dict) -> str`
- 10 personas: `executive`, `researcher`, `occupant`, `sustainability_officer`,
  `facility_manager`, `student`, `visitor`, `engineer`, `auditor`, `default`
- Each persona has a system prompt fragment injected into an LLM call
- Uses `llm_manager` for the reframing call; returns original if LLM unavailable
- Called as last step before returning response in `_response_node`

**`orchestrator/services/standards_engine.py`**
- Class `StandardsEngine` with `check(readings: dict, standards: list[str]) -> dict`
- Pure deterministic logic — no LLM needed
- 6 standards: ASHRAE 55, ASHRAE 62.1, WELL v2, BREEAM Hea 02, EN 15251, ISO 50001
- Returns per-parameter PASS/FAIL with measured value, threshold, and margin
- Integrated into `_analytics_node` for `compliance` intent
- Also exposed as MCP tool `check_standards_batch`

---

## 3. docker-compose.yml Rewrite

### Services to add

| Service | Image/Build | Port | Volumes |
|---------|------------|------|---------|
| `orchestrator` | `build: ./orchestrator` | 8000 | `./data:/app/data:ro`, `./config:/app/config:ro`, `./outputs:/app/outputs` |
| `redis` | `redis:7-alpine` | 6379 | `redis-data:/data` |
| `postgres-user-data` | `postgres:15-alpine` | 5433 | `postgres-user-data:/var/lib/postgresql/data` |
| `qdrant` | `qdrant/qdrant:latest` | 6333/6334 | `qdrant-data:/qdrant/storage` |
| `code-executor` | `build: ./code-executor` | 8002 | none (stateless) |
| `graphdb` (profile: `graphdb`) | `devmanenvision/graphdb:10.4.2` | 7200 | `graphdb-data:/opt/graphdb/home` |
| `rag-service` (profile: `graphdb`) | `build: ./rag-service/graphdbRAG` | 8001 | `./bldg1/trial/dataset:/app/input:ro` |
| `ollama` (profile: `local-llm`) | existing image | 11435 | `ollama-models:/usr/share/ollama/.ollama/models` |
| `prometheus` (profile: `monitoring`) | `prom/prometheus` | 9090 | `./monitoring/prometheus.yml:/etc/prometheus/prometheus.yml:ro` |
| `grafana` (profile: `monitoring`) | `grafana/grafana` | 3002 | `grafana-data:/var/lib/grafana` |

### Services to remove

All of the following are Rasa-era services no longer needed:
`rasa`, `action_server`, `duckling_server`, `rasa-train`, `http_server`, `rasa-editor`,
`decider-service`, `microservices`

### Services to keep (unchanged)

`mysql`, `jena-fuseki`, `fuseki-db`, `rasa-frontend` (React UI), `pgadmin`

### All secrets via `.env` — no hardcoded defaults for passwords

```
MYSQL_ROOT_PASSWORD, MYSQL_APP_PASSWORD, FUSEKI_ADMIN_PASSWORD,
POSTGRES_USER_PASSWORD, SECRET_KEY, GRAPHDB_PASSWORD,
PGADMIN_DEFAULT_PASSWORD
```

---

## 4. Wiring the 3 Written Files Into workflow.py

`workflow.py` currently does NOT import `document_agent`, `persona_adapter`, or
`standards_engine`. They must be wired in as follows:

### document_agent.py
- Import: `from orchestrator.agents.document_agent import DocumentAgent`
- Add `self.document_agent = DocumentAgent()` in `__init__`
- Add `workflow.add_node("document", self._document_node)` in `_build_graph()`
- Add edge: `Dialogue → document` for intent `document`
- Add `_document_node` method that calls `self.document_agent.generate(state)`

### persona_adapter.py
- Import: `from orchestrator.services.persona_adapter import PersonaAdapter`
- Add `self.persona_adapter = PersonaAdapter()` in `__init__`
- In `_response_node`: after building the response text, call
  `state["response"] = await self.persona_adapter.adapt(state["response"], persona, context)`

### standards_engine.py
- Import: `from orchestrator.services.standards_engine import StandardsEngine`
- Add `self.standards_engine = StandardsEngine()` in `__init__`
- In `_analytics_node`: when `intent == "compliance"`, call
  `standards_result = self.standards_engine.check(sql_data, requested_standards)`
  and merge into the analytics result before passing to response

---

## 5. File Placement Map

```
OntoSage/
├── orchestrator/
│   ├── Dockerfile                     ← extracted from image
│   ├── requirements.txt               ← extracted from image
│   ├── __init__.py                    ← extracted
│   ├── main.py                        ← extracted
│   ├── workflow.py                    ← extracted + wiring additions
│   ├── llm_manager.py                 ← extracted
│   ├── auth_manager.py                ← extracted
│   ├── redis_manager.py               ← extracted
│   ├── postgres_manager.py            ← extracted
│   ├── agents/
│   │   ├── __init__.py                ← extracted
│   │   ├── dialogue_agent.py          ← extracted
│   │   ├── sparql_agent.py            ← extracted
│   │   ├── sql_agent.py               ← extracted
│   │   ├── analytics_agent.py         ← extracted
│   │   ├── visualization_agent.py     ← extracted
│   │   ├── planner_agent.py           ← extracted
│   │   ├── report_agent.py            ← extracted
│   │   ├── anomaly_agent.py           ← extracted
│   │   ├── data_export_agent.py       ← extracted
│   │   ├── semantic_ontology_agent.py ← extracted
│   │   └── document_agent.py          ← WRITTEN from spec
│   ├── services/
│   │   ├── analytics_engine.py        ← extracted
│   │   ├── self_correction_engine.py  ← extracted
│   │   ├── smart_cache.py             ← extracted
│   │   ├── response_cache.py          ← extracted
│   │   ├── streaming_adapter.py       ← extracted
│   │   ├── ws_streaming.py            ← extracted
│   │   ├── reasoning_engine.py        ← extracted
│   │   ├── i18n_service.py            ← extracted
│   │   ├── agent_memory.py            ← extracted
│   │   ├── multi_building_manager.py  ← extracted
│   │   ├── hybrid_retrieval.py        ← extracted
│   │   ├── ontology_detector.py       ← extracted
│   │   ├── ontology_introspector.py   ← extracted
│   │   ├── ontology_validator.py      ← extracted
│   │   ├── database_adapter.py        ← extracted
│   │   ├── database_schema_discovery.py ← extracted
│   │   ├── plugin_registry.py         ← extracted
│   │   ├── prompt_builder.py          ← extracted
│   │   ├── context_manager.py         ← extracted
│   │   ├── sparql_validator.py        ← extracted
│   │   ├── circuit_breaker.py         ← DECOMPILED from pyc
│   │   ├── logging_context.py         ← DECOMPILED from pyc
│   │   ├── persona_adapter.py         ← WRITTEN from spec
│   │   ├── standards_engine.py        ← WRITTEN from spec
│   │   └── adapters/
│   │       ├── __init__.py            ← extracted
│   │       ├── mysql_adapter.py       ← extracted
│   │       ├── postgresql_adapter.py  ← extracted
│   │       └── registry.py            ← extracted
│   └── middleware/
│       ├── __init__.py                ← extracted
│       └── rbac.py                    ← extracted
├── shared/
│   ├── __init__.py                    ← extracted
│   ├── config.py                      ← extracted
│   ├── models.py                      ← extracted
│   ├── utils.py                       ← extracted
│   ├── constants.py                   ← extracted
│   └── structured_logger.py           ← extracted
├── code-executor/
│   ├── Dockerfile                     ← extracted from code-executor image
│   ├── __init__.py                    ← extracted
│   ├── main.py                        ← extracted
│   └── sandbox.py                     ← extracted
└── docker-compose.yml                 ← REWRITTEN (full clean replacement)
```

---

## 6. Verification Checklist

After all files are in place:

- [ ] `docker compose build orchestrator` completes without errors
- [ ] `docker compose build code-executor` completes without errors
- [ ] `docker compose up -d` (core stack) starts all services healthy
- [ ] `GET http://localhost:8000/health` returns `{"status": "ok"}`
- [ ] `GET http://localhost:8000/health/aggregate` shows all dependencies
- [ ] `POST http://localhost:8000/chat` with `{"message": "What is HVAC?"}` returns a response
- [ ] `POST http://localhost:8000/chat` with sensor query routes through SPARQL → SQL
- [ ] `POST http://localhost:8000/chat` with compliance intent invokes StandardsEngine
- [ ] `POST http://localhost:8000/chat` with persona set applies PersonaAdapter
- [ ] Frontend at `http://localhost:3000` connects to orchestrator

---

## 7. Out of Scope

- MCP server (separate service, not blocking orchestrator deployment)
- Prometheus/Grafana dashboards (profile-based, not blocking)
- Open WebUI integration (optional, deferred)
- InfluxDB/TimescaleDB adapters (Phase 9 per roadmap)
