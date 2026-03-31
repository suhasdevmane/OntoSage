# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Commands

### Running the full stack
```bash
# Start all services (requires Docker)
docker-compose up -d

# Rebuild a specific service after code changes
docker-compose build orchestrator
docker-compose up -d orchestrator

# View logs
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
# Run all tests
pytest tests/ -v

# Run a single test file
pytest tests/test_phase3_4_services.py -v

# Run a single test by name
pytest tests/test_phase3_4_services.py::test_ontology_validator -v

# Run with coverage
pytest tests/ --cov=orchestrator --cov-report=html

# Run by marker (unit / integration / slow / live)
pytest -m unit
pytest -m integration
```

### Linting
```bash
# Format check
black --check --line-length 100 orchestrator/ shared/ scripts/ tests/

# Auto-fix formatting
black --line-length 100 orchestrator/ shared/ scripts/ tests/

# Import sorting
isort --check-only --profile black orchestrator/ tests/
isort --profile black orchestrator/ tests/

# Static analysis
flake8 orchestrator/ shared/ scripts/ \
  --max-line-length 110 \
  --extend-ignore=E203,E501,W503 \
  --per-file-ignores="__init__.py:F401"

# Security scan
bandit -r orchestrator/ shared/ -ll --exclude orchestrator/tests
```

### Building onboarding CLI
```bash
python scripts/onboard_building.py --building-id bldg2 --non-interactive
```

## Architecture

OntoSage is an **agentic AI framework** for smart buildings. Users ask natural language questions; the system retrieves answers from a knowledge graph (ontology) and/or a time-series database, then synthesizes responses.

### Hub-and-spoke agent orchestration

`orchestrator/workflow.py` defines a **LangGraph state machine** that is the central orchestrator. Every request flows through these nodes:

```
WebSocket → dialogue → [routing] → sparql / sql / analytics / planner / report / anomaly / export
                                  ↓
                               visualization → response → end
```

1. **dialogue** (`agents/dialogue_agent.py`): LLM classifies intent into one of 14 types and extracts entities/time ranges. Result is stored in `state.intermediate_results`.
2. **sparql** (`agents/sparql_agent.py`): Generates and executes SPARQL against GraphDB (port 7200). Falls back to semantic RAG via `rag-service` (port 8001) on failure. Returns UUIDs for downstream SQL.
3. **sql** (`agents/sql_agent.py`): Fetches time-series data by UUID via storage adapters (MySQL for Building 1, PostgreSQL for others).
4. **analytics** (`agents/analytics_agent.py`): LLM-generates Python code; remotely executes it via the sandboxed `code-executor` service (port 8002).
5. **visualization** (`agents/visualization_agent.py`): Generates matplotlib/plotly plots; saves to `/app/outputs/static/`.
6. **response** node: Formats final markdown response.

Routing decisions are all conditional edges in `workflow.py` based on `state.intent` and the content of `state.intermediate_results`.

### Shared state: ConversationState

All agents read and write a single `ConversationState` object (defined in `shared/models.py`). The key field is `intermediate_results: Dict[str, Any]` — a 16-field dict that passes data between nodes (intent, entities, SPARQL results, SQL data, analytics output, etc.). Conversation state is persisted in Redis with a 1-hour TTL.

### Storage layer

| Store | Purpose | Port |
|-------|---------|------|
| GraphDB | RDF ontology / SPARQL | 7200 |
| MySQL | Building 1 time-series sensor data | 3306 (host) |
| PostgreSQL | User accounts, RBAC | 5433 |
| Redis | Conversation state, session tokens | 6379 |
| Qdrant | Agent memory (vector search) | 6333 |
| MongoDB | Chat history | 27017 |

Storage adapter routing (`orchestrator/services/adapters/`) maps building IDs to the correct database backend; this registry is initialized at startup in `main.py`.

### LLM / embedding provider switching

`shared/config.py` is the single source of truth for all service URLs and feature flags. The model provider is selected via `MODEL_PROVIDER` env var:
- `local` → Ollama at `http://ollama:11434` (default model: `deepseek-r1:32b`)
- `openai` → OpenAI API (`o3-mini`)
- `cloud` → Ollama Cloud

Copy `.env.local` (local GPU) or `.env.cloud` (OpenAI) to `.env` before starting.

### Authentication

`orchestrator/auth_manager.py` uses Argon2id password hashing (with transparent migration from legacy SHA-256 on login). Sessions are 32-byte random tokens stored in Redis with a 7-day TTL.

RBAC middleware (`orchestrator/middleware/rbac.py`) enforces 6 roles (admin, facility_manager, analyst, operator, occupant, readonly) with 20 granular permissions. Use the `require_permission()` FastAPI dependency to protect endpoints.

### Key files

| File | Role |
|------|------|
| `orchestrator/main.py` | FastAPI app, startup lifecycle, all endpoint registration |
| `orchestrator/workflow.py` | LangGraph graph definition; all routing logic lives here |
| `shared/config.py` | All env vars and service URLs; read by every component |
| `shared/models.py` | `ConversationState` and all Pydantic models |
| `orchestrator/auth_manager.py` | Auth, session management, password hashing |
| `orchestrator/middleware/rbac.py` | Role definitions and permission enforcement |
| `orchestrator/services/adapters/` | MySQL / PostgreSQL storage adapters and routing registry |
| `docker-compose.yml` | All 12+ service definitions, networks, volumes |
| `.env.example` | Documented template for all configuration variables |

## Workflow Orchestration

### 1. Plan Mode Default
- Enter plan mode for ANY non-trivial task (3+ steps or architectural decisions)
- If something goes sideways, STOP and re-plan immediately - don't keep pushing
- Use plan mode for verification steps, not just building
- Write detailed specs upfront to reduce ambiguity

### 2. Subagent Strategy
- Use subagents liberally to keep main context window clean
- Offload research, exploration, and parallel analysis to subagents
- For complex problems, throw more compute at it via subagents
- One task per subagent for focused execution

### 3. Self-Improvement Loop
- After ANY correction from the user: update `tasks/lessons.md` with the pattern
- Write rules for yourself that prevent the same mistake
- Ruthlessly iterate on these lessons until mistake rate drops
- Review lessons at session start for relevant project

### 4. Verification Before Done
- Never mark a task complete without proving it works
- Diff behavior between main and your changes when relevant
- Ask yourself: "Would a staff engineer approve this?"
- Run tests, check logs, demonstrate correctness

### 5. Demand Elegance (Balanced)
- For non-trivial changes: pause and ask "is there a more elegant way?"
- If a fix feels hacky: "Knowing everything I know now, implement the elegant solution"
- Skip this for simple, obvious fixes - don't over-engineer
- Challenge your own work before presenting it

### 6. Autonomous Bug Fixing
- When given a bug report: just fix it. Don't ask for hand-holding
- Point at logs, errors, failing tests - then resolve them
- Zero context switching required from the user
- Go fix failing CI tests without being told how