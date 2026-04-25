# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with this repository.

## Commands

### Running the full stack
```bash
# Start all services (requires Docker)
docker-compose up -d

# Rebuild one service after code changes
docker-compose build orchestrator && docker-compose up -d orchestrator

# View live logs
docker-compose logs -f orchestrator
docker-compose logs -f rag-service
```

### Health checks
```bash
curl http://localhost:8000/health        # Orchestrator
curl http://localhost:8001/health        # RAG Service
curl http://localhost:8002/health        # Code Executor
```

### Testing
```bash
pytest tests/ -v                                              # all tests
pytest tests/test_phase3_4_services.py -v                    # single file
pytest tests/test_phase3_4_services.py::test_ontology_validator -v  # single test
pytest tests/ --cov=orchestrator --cov-report=html           # with coverage
pytest -m unit                                                # by marker
pytest -m integration
```

### Linting
```bash
black --line-length 100 orchestrator/ shared/ scripts/ tests/   # format
isort --profile black orchestrator/ tests/                      # imports
flake8 orchestrator/ shared/ scripts/ \
  --max-line-length 110 --extend-ignore=E203,E501,W503 \
  --per-file-ignores="__init__.py:F401"
bandit -r orchestrator/ shared/ -ll --exclude orchestrator/tests
```

### Building onboarding CLI
```bash
python scripts/onboard_building.py --building-id bldg2 --non-interactive
```

---

## Architecture

OntoSage is an **agentic AI framework** for smart buildings. Users ask natural language questions; the system retrieves answers from a knowledge graph (ontology) and/or a time-series database, then synthesizes responses.

### Hub-and-spoke agent orchestration

`orchestrator/workflow.py` defines a **LangGraph state machine**. Every request flows through:

```
WebSocket/HTTP → dialogue → [routing] → sparql / sql / analytics / planner
                                      → report / anomaly / export / floor_plan
                                      → spatial_query / document
                                      ↓
                                   visualization → response → END
```

1. **dialogue** (`agents/dialogue_agent.py`): LLM classifies intent into one of 16 types and extracts entities/time ranges → `state.intermediate_results`.
2. **sparql** (`agents/sparql_agent.py`): Generates + executes SPARQL against GraphDB (port 7200). Falls back to semantic RAG via `rag-service` (port 8001). Returns UUIDs for downstream SQL.
3. **sql** (`agents/sql_agent.py`): Fetches time-series data by UUID via storage adapters (MySQL for Building 1, PostgreSQL for others).
4. **analytics** (`agents/analytics_agent.py`): LLM-generates Python code; executes in sandboxed `code-executor` (port 8002).
5. **floor_plan** (`agents/floor_plan_agent.py`): Reads `FloorPlanManifest` JSON; returns PNG image + room list. No SPARQL/SQL.
6. **spatial_query** (`agents/spatial_agent.py`): Pure manifest analysis — area, adjacency, block counts. No LLM calls.
7. **visualization** (`agents/visualization_agent.py`): matplotlib/plotly → `/app/outputs/static/`.
8. **response** node: Formats final markdown response.

Routing is all conditional edges in `workflow.py:_build_graph` (line 132) and `_route_from_dialogue` (line 1521).

### Floor Plan Pipeline (PDF + DWG)

Two parallel pipelines auto-run on every startup and are orchestrated by `FloorPlanRegistry`:

```
/app/input/*.pdf  → FloorPlanPipeline  → text extraction, OCR fallback, zone ID regex
/app/input/*.dwg  → DWGPipeline        → dwg2dxf → ezdxf → shapely polygons, area, adjacency
                       ↓
               FloorPlanRegistry._merge()   ← DWG wins geometry; PDF wins render/image
                       ↓
          floor_plans/abacws/floor_N.manifest.json
                       ↓
               Qdrant floor_plans collection  ← all spaces re-indexed with full payload
```

- **Idempotent**: SHA-256 fingerprint per file — unchanged files skip reprocessing.
- **Graceful degradation**: if `dwg2dxf` is absent (not in Debian Bookworm repos), the DWG pipeline logs a warning and produces PDF-only `schema_version="1.0"` manifests. Install via `libredwg-utils` from sid/trixie or build from source.
- **File watcher**: `floor_plan_watcher.py` watches `/app/input/` at runtime — drop a new `.pdf` or `.dwg` and it auto-ingests within 3 seconds.
- **Building config**: per-building YAML at `/app/input/<building_id>/building.yaml` overrides zone ID patterns, layer maps, DPI, etc. See `shared/floor_plan_config.py`.

### How the system chooses TTL/SPARQL vs PDF/DWG data

| User question type | Intent classified as | Data source |
|--------------------|---------------------|-------------|
| Sensor readings, temperature, CO2 | `sensor_data`, `analytics` | GraphDB TTL (ontology) + MySQL (time-series) |
| What sensors exist, building discovery | `discovery` | GraphDB TTL only |
| Show me floor 3 / where is room 3.01 | `floor_plan` | Manifest JSON + PNG |
| Area, adjacency, room count, block query | `spatial_query` | Manifest JSON (geometry) |
| Semantic room search (RAG fallback) | any SPARQL failure | Qdrant `floor_plans` vectors |

The TTL/GraphDB knows *what sensors exist and how they relate*. The manifests know *what rooms look like and their geometry*. They are separate knowledge domains, never merged.

### Shared state: ConversationState

All agents read and write one `ConversationState` object (`shared/models.py:222`). Key field: `intermediate_results: Dict[str, Any]` — passes data between nodes (intent, entities, SPARQL results, SQL data, analytics output, etc.). Persisted in Redis with 1-hour TTL.

### Storage layer

| Store | Port | Purpose |
|-------|------|---------|
| **GraphDB** | 7200 | RDF ontology (Brick/BACnet TTL). Stores sensor types, zones, hierarchies. Used by SPARQL agent. |
| **MySQL** | 3306 | Building 1 sensor time-series (temperature, CO2, humidity). Rows keyed by UUID that links to ontology. |
| **PostgreSQL** | 5433 | User accounts, Argon2id password hashes, RBAC roles. No building data. |
| **Redis** | 6379 | Three caches: conversation state (1hr), response cache (avoid repeat OpenAI calls), floor plan manifest hot-cache. |
| **Qdrant** | 6333 | Two collections: `floor_plans` (room description vectors + DWG geometry payload for semantic search); `user_memory` (cross-session agent memory per user). |
| **MongoDB** | 27017 | Full chat history transcripts per session (used by OpenWebUI). |

### LLM / embedding provider

`shared/config.py` is the single source of truth. Switch via `MODEL_PROVIDER` env var:
- `openai` → OpenAI API (default: `gpt-4o-mini` for most; `o3-mini` for analytics)
- `local` → Ollama at `http://ollama:11434` (default model: `deepseek-r1:32b`)
- `cloud` → Ollama Cloud

Copy `.env.local` (local GPU) or `.env.cloud` (OpenAI) to `.env` before starting.

### Authentication

`orchestrator/auth_manager.py`: Argon2id password hashing with transparent migration from legacy SHA-256. Sessions are 32-byte random tokens in Redis with 7-day TTL.

RBAC (`orchestrator/middleware/rbac.py`): 6 roles (admin, facility_manager, analyst, operator, occupant, readonly) × 20 permissions. Use `require_permission()` FastAPI dependency to protect endpoints.

---

## Quick Navigation Index

Use these as the **first `Read` call** for any task — jump straight to the right function without scanning whole files.

| Task | File | Line | Symbol |
|------|------|------|--------|
| Intent routing (all 16 branches) | `orchestrator/workflow.py` | 1521 | `_route_from_dialogue` |
| Add/register a new graph node | `orchestrator/workflow.py` | 132 | `_build_graph` — `add_node()` block |
| SPARQL generation + execution | `orchestrator/agents/sparql_agent.py` | 174 | `generate_query()` |
| SPARQL context retrieval | `orchestrator/agents/sparql_agent.py` | 324 | `_retrieve_context()` |
| SPARQL query builder | `orchestrator/agents/sparql_agent.py` | 400 | `_generate_sparql()` |
| Floor plan manifest load/search | `orchestrator/services/floor_plan_pipeline.py` | 126 | `class FloorPlanPipeline` |
| Floor plan Qdrant indexing | `orchestrator/services/floor_plan_pipeline.py` | 522 | `_embed_and_index()` |
| Floor plan manifest enumeration | `orchestrator/services/floor_plan_pipeline.py` | 342 | `list_manifests()` |
| DWG+PDF merge orchestrator | `orchestrator/services/floor_plan_registry.py` | 30 | `class FloorPlanRegistry` |
| DWG+PDF merge logic | `orchestrator/services/floor_plan_registry.py` | 120 | `_merge()` |
| Qdrant re-index after merge | `orchestrator/services/floor_plan_registry.py` | 272 | `_reindex_merged_spaces()` |
| DWG ingestion pipeline | `orchestrator/services/dwg_pipeline.py` | 156 | `class DWGPipeline` |
| DWG label→space association | `orchestrator/services/dwg_pipeline.py` | 768 | `_associate_labels()` |
| DWG sensor→ontology linking | `orchestrator/services/dwg_pipeline.py` | 514 | `_link_sensor_blocks()` |
| DWG adjacency computation | `orchestrator/services/dwg_pipeline.py` | 869 | `_compute_adjacency()` |
| File watcher (PDF + DWG) | `orchestrator/services/floor_plan_watcher.py` | 26 | `watch_forever()` |
| Spatial geometry queries | `orchestrator/agents/spatial_agent.py` | 101 | `class SpatialAgent` |
| Spatial manifest loading | `orchestrator/agents/spatial_agent.py` | 440 | `_load_manifests()` |
| Response formatting | `orchestrator/workflow.py` | 1194 | `_response_node()` |
| Spatial query node | `orchestrator/workflow.py` | 2334 | `_spatial_query_node()` |
| Dialogue intent classification | `orchestrator/agents/dialogue_agent.py` | — | `classify_intent()` — search for `INTENT_DEFINITIONS` |
| SQL / time-series failure | `orchestrator/agents/sql_agent.py` | 1 | entry; then `services/adapters/registry.py` |
| Storage adapter routing | `orchestrator/services/adapters/registry.py` | 1 | maps building_id → MySQL/PostgreSQL |
| Analytics code execution | `orchestrator/agents/analytics_agent.py` | 1 | calls `code-executor` port 8002 |
| Auth / session issues | `orchestrator/auth_manager.py` | 65 | `class AuthManager` |
| RBAC role → permission map | `orchestrator/middleware/rbac.py` | 78 | `ROLE_PERMISSIONS` |
| All env vars / service URLs | `shared/config.py` | 1 | `Settings` class |
| ConversationState fields | `shared/models.py` | 222 | `class ConversationState` |
| FloorPlanManifest schema | `shared/models.py` | 449 | `class FloorPlanManifest` |
| Space / Block models | `shared/models.py` | 400 | `class Block`, `class Space` |
| Per-building floor plan config | `shared/floor_plan_config.py` | 69 | `class BuildingConfig` |
| RAG semantic fallback | `orchestrator/services/hybrid_retrieval.py` | 1 | `hybrid_retrieval()` |
| Circuit breaker | `orchestrator/services/circuit_breaker.py` | 41 | `class CircuitBreaker` |
| FastAPI startup / lifespan | `orchestrator/main.py` | 278 | `async def lifespan` |
| Floor plan registry startup | `orchestrator/main.py` | 419 | floor plan registry block |
| Health endpoint | `orchestrator/main.py` | 613 | `@app.get("/health")` |
| OpenAI-compat chat endpoint | `orchestrator/main.py` | 2112 | `@app.post("/v1/chat/completions")` |
| Floor plan REST endpoints | `orchestrator/main.py` | 2406 | `@app.get("/floor-plans/")` |
| Docker service definitions | `docker-compose.yml` | 1 | all service blocks |

---

## 16 Intent Types

The dialogue agent classifies every query into one of:

| Intent | Route | Description |
|--------|-------|-------------|
| `sensor_data` | sparql → sql → response | Current or historical sensor readings |
| `analytics` | sparql → sql → analytics → response | Statistical analysis, trends, averages |
| `discovery` | sparql → response | Explore available sensors/zones/devices |
| `report` | sparql → sql → report → response | Structured building report |
| `anomaly` | sparql → sql → anomaly → response | Out-of-range / spike detection |
| `comparison` | sparql → sql → analytics → response | Compare zones/devices/time periods |
| `export` | sparql → sql → export → response | Download data as CSV/JSON/HTML |
| `recommend` | sparql → sql → response | HVAC/energy/comfort recommendations |
| `planner` | planner → response | Multi-step orchestrated tasks |
| `forecast` | sparql → sql → analytics → response | Future predictions |
| `floor_plan` | floor_plan → response | Show floor map, locate a room, visual navigation |
| `spatial_query` | spatial_query → response | Area, adjacency, room counts, block/MEP queries |
| `control` | response | Not yet supported — informs user |
| `general` | response | Greetings / non-building questions |
| `clarification` | response | Query too vague — asks follow-up |
| `alert` | sparql → sql → anomaly → response | Threshold-based alerting |

**Disambiguation rule**: "show me / where is / find" → `floor_plan`. "how many / area / size / adjacent" → `spatial_query`.

---

## Key Files

| File | Role |
|------|------|
| `orchestrator/main.py` | FastAPI app, startup lifecycle, all endpoint registration |
| `orchestrator/workflow.py` | LangGraph graph definition; all routing logic |
| `orchestrator/agents/dialogue_agent.py` | Intent classification + entity extraction |
| `orchestrator/agents/spatial_agent.py` | Geometry queries from manifests — no LLM |
| `orchestrator/services/floor_plan_registry.py` | Merge orchestrator: DWG + PDF → merged manifest + Qdrant |
| `orchestrator/services/floor_plan_pipeline.py` | PDF → text extraction → manifest → Qdrant |
| `orchestrator/services/dwg_pipeline.py` | DWG → DXF → shapely geometry → manifest |
| `orchestrator/services/floor_plan_watcher.py` | watchfiles background task for auto-ingest |
| `shared/config.py` | All env vars and service URLs |
| `shared/models.py` | `ConversationState`, `FloorPlanManifest`, `Space`, `Block` |
| `shared/floor_plan_config.py` | Per-building YAML config, AIA/NCS layer map, zone ID patterns |
| `orchestrator/auth_manager.py` | Auth, session management, Argon2id hashing |
| `orchestrator/middleware/rbac.py` | Role definitions and permission enforcement |
| `orchestrator/services/adapters/` | MySQL / PostgreSQL adapters + routing registry |
| `orchestrator/Dockerfile` | Container build — tesseract-ocr included; libredwg-utils best-effort |
| `docker-compose.yml` | All 12+ service definitions, networks, volumes |
| `.env.example` | Documented template for all configuration variables |

---

## Workflow Orchestration Rules

### 1. Plan Mode Default
- Enter plan mode for ANY non-trivial task (3+ steps or architectural decisions)
- Stop and re-plan immediately if something goes sideways — don't keep pushing
- Write detailed specs upfront to reduce ambiguity

### 2. Subagent Strategy
- Use subagents to keep main context window clean
- Offload research, exploration, and parallel analysis to subagents
- One task per subagent for focused execution

### 3. Self-Improvement Loop
- After ANY correction: update `tasks/lessons.md` with the pattern
- Write rules to prevent the same mistake; review at session start

### 4. Verification Before Done
- Never mark a task complete without proving it works
- Ask: "Would a staff engineer approve this?"
- Run tests, check logs, demonstrate correctness

### 5. Demand Elegance (Balanced)
- For non-trivial changes: ask "is there a more elegant way?"
- Skip for simple obvious fixes — don't over-engineer

### 6. Autonomous Bug Fixing
- When given a bug report: fix it directly. No hand-holding needed.
- Point at logs, errors, failing tests — then resolve them.

---

## Common Debugging Patterns

### Orchestrator won't start
```bash
docker-compose logs --tail=50 orchestrator   # look for ImportError or missing module
# Common cause: orchestrator/__init__.py imports something not yet defined
# Fix: check llm_manager.py for missing symbols (TaskType, etc.)
```

### Intent routed to wrong node
```bash
# 1. Check dialogue agent prompt — search for INTENT_DEFINITIONS in dialogue_agent.py
# 2. Check _route_from_dialogue at workflow.py:1521 — verify elif branch exists
# 3. Verify add_node() name exactly matches return value of _route_from_dialogue
```

### Floor plan not showing / manifest empty
```bash
# 1. Check /app/input/ has matching filenames: "Abacws floor N.pdf" / "Abacws floor N.dwg"
# 2. Check SHA-256 cache: if file unchanged, manifest is reused from disk
# 3. DWG pipeline: "dwg2dxf not found" warning → libredwg-utils not installed → PDF-only mode
# 4. Reingest via API: POST /api/v1/floor-plans/reingest
```

### SPARQL returns empty
```bash
curl -s -X POST http://localhost:7200/repositories/ontosage/sparql \
  -H "Content-Type: application/sparql-query" \
  -H "Accept: application/sparql-results+json" \
  -d "SELECT ?s WHERE { ?s a <https://brickschema.org/schema/Brick#Building> } LIMIT 5"
# Empty → ontology not loaded → run onboard_building.py
# Results exist but app returns empty → check _retrieve_context() in sparql_agent.py:324
```

### Qdrant floor_plans missing geometry
```bash
# Spaces show area_m2=null → DWG pipeline not running (libredwg-utils missing)
# Check: manifest schema_version should be "2.0" for DWG-enriched floors
curl http://localhost:8000/api/v1/floor-plans/abacws/3/manifest | python -m json.tool | grep schema_version
```

---

## Installed Skills Guide

Skills at `~/.claude/skills/`. Invoke with the Skill tool.

| Task | Skill |
|------|-------|
| Debug pipeline failure | `systematic-debugging` or `phase-gated-debugging` |
| LangGraph workflow changes | `langgraph` |
| RAG / rag-service work | `rag-engineer` |
| FastAPI endpoint work | `fastapi-pro` |
| Ollama / local model tuning | `local-llm-expert` |
| LLM prompt / output tuning | `llm-app-patterns` |
| Docker / container issues | `docker-expert` |
| Qdrant vector index | `vector-database-engineer` |
| Security review | `security-auditor` |
| Writing / fixing tests | `systematic-debugging` then `testing-patterns` |
| Agent orchestration design | `agent-orchestration-improve-agent` |

---

## Sub-Agents

Scoped sub-agents in `.claude/agents/`. Each reads only its domain files.

| Agent | Invoke When |
|-------|------------|
| `ontology-agent` | SPARQL failures, TTL parsing, GraphDB issues, new building onboarding |
| `pipeline-agent` | Routing bugs, adding intents/nodes, state not propagating between nodes |
| `infra-agent` | Docker failures, port conflicts, env vars, MODEL_PROVIDER switching |
| `test-agent` | Writing or fixing tests, coverage gaps, pytest markers |
| `deploy-agent` | Pre-deployment review, auth hardening, production checklist |
