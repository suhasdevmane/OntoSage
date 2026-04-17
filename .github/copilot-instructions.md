# OntoSage — GitHub Copilot Instructions

> This file is read automatically by GitHub Copilot Chat for every session.
> It is the Copilot equivalent of `CLAUDE.md`. Keep it as the single source of truth
> for project context, coding rules, and architecture.

---

## Project Overview

OntoSage is an **agentic AI framework for smart buildings**. Users ask natural language
questions; the system retrieves answers from a Brick Schema knowledge graph (SPARQL) and a
time-series database (SQL), then synthesises responses via specialised agents orchestrated by
LangGraph.

**Stack:** FastAPI · LangGraph · GraphDB (SPARQL) · MySQL/PostgreSQL/Cassandra · Redis ·
Qdrant · MongoDB · Docker Compose · Open WebUI

---

## Architecture: Hub-and-Spoke Agent Orchestration

`orchestrator/workflow.py` is the LangGraph state machine. Every request flows:

```
WebSocket → dialogue → [routing] → sparql / sql / analytics / planner / report / anomaly / export
                                  ↓
                               visualization → response → end
```

1. **dialogue** (`agents/dialogue_agent.py`) — classifies intent (14 types), extracts entities/time ranges
2. **sparql** (`agents/sparql_agent.py`) — SPARQL against GraphDB; falls back to RAG on failure
3. **sql** (`agents/sql_agent.py`) — time-series retrieval by UUID via storage adapters
4. **analytics** (`agents/analytics_agent.py`) — LLM-generates Python; executed in sandboxed Code Executor (port 8002)
5. **visualization** (`agents/visualization_agent.py`) — matplotlib/plotly charts

All agents share `ConversationState` (defined in `shared/models.py`), a single Pydantic object
with `intermediate_results: Dict[str, Any]` passing data between nodes.

---

## Key File Navigation Index

| Task | File | Lines |
|------|------|-------|
| Intent routing | `orchestrator/workflow.py` | 1079–1130 |
| Add new graph node | `orchestrator/workflow.py` | 120–135 |
| SPARQL generation | `orchestrator/agents/sparql_agent.py` | 165–260 |
| SPARQL context/retrieval | `orchestrator/agents/sparql_agent.py` | 313–390 |
| SQL / time-series | `orchestrator/agents/sql_agent.py` | 1–50 |
| Storage adapter routing | `orchestrator/services/adapters/registry.py` | 1–60 |
| Analytics code execution | `orchestrator/agents/analytics_agent.py` | 1–80 |
| Response formatting | `orchestrator/workflow.py` | 843–1079 |
| Auth / session | `orchestrator/auth_manager.py` | 61–160 |
| RBAC / permissions | `orchestrator/middleware/rbac.py` | 51–115 |
| Config / env vars | `shared/config.py` | 1–100 |
| State model fields | `shared/models.py` | 1–80 |
| RAG semantic fallback | `orchestrator/services/hybrid_retrieval.py` | 1–60 |
| FastAPI startup | `orchestrator/main.py` | 1–100 |
| FastAPI endpoints | `orchestrator/main.py` | 100–400 |
| Circuit breaker | `orchestrator/services/circuit_breaker.py` | 1–60 |

---

## 14 Intent Types

| Intent | Route | Description |
|--------|-------|-------------|
| `sensor_data` | sparql → sql → response | Current/historical sensor readings |
| `analytics` | sparql → sql → analytics → response | Statistical analysis, trends |
| `discovery` | sparql → response | Explore sensors/zones/devices |
| `report` | sparql → sql → report → response | Structured building report |
| `anomaly` | sparql → sql → anomaly → response | Out-of-range / spike detection |
| `comparison` | sparql → sql → analytics → response | Compare zones/devices/times |
| `export` | sparql → sql → export → response | Download CSV/JSON/HTML |
| `recommend` | sparql → sql → response | HVAC/energy/comfort recommendations |
| `planner` | planner → response | Multi-step orchestrated tasks |
| `forecast` | sparql → sql → analytics → response | Future predictions |
| `control` | response | Not supported — informs user |
| `general` | response | Greetings / non-building questions |
| `clarification` | response | Query too vague |
| `alert` | sparql → sql → anomaly → response | Threshold-based alerting |

---

## Storage Layer

| Store | Purpose | Port |
|-------|---------|------|
| GraphDB | RDF ontology / SPARQL | 7200 |
| MySQL | Building 1 time-series | 3306 (host) |
| PostgreSQL | User accounts, RBAC | 5433 |
| Redis | Conversation state (1-hr TTL) | 6379 |
| Qdrant | Agent memory (vector search) | 6333 |
| MongoDB | Chat history | 27017 |

Model provider: `MODEL_PROVIDER=local` → Ollama `deepseek-r1:32b` | `MODEL_PROVIDER=openai` → `o3-mini`

---

## Python Style Rules (apply to ALL files in orchestrator/ shared/ scripts/ tests/)

- **Line length:** 100 chars — run `black --line-length 100` + `isort --profile black`
- **Type hints:** required on all new functions; use `Optional[X]`, `Dict`, `List` from `typing`
- **Async:** all LangGraph node functions must be `async def`; never block with `time.sleep()`
- **Logging:** use `from shared.utils import get_logger` — never `print()`
- **Error handling:** always catch specific exceptions; set `state.intermediate_results["error"]` and return state — never raise from inside a node
- **Imports order:** stdlib → third-party → `shared/` → `orchestrator/`
- **Static analysis:** `flake8 --max-line-length 110 --extend-ignore=E203,E501,W503` + `bandit -ll`

---

## LangGraph Node Pattern (MUST follow for every new node)

```python
# 1. Always wrap with _safe_node
workflow.add_node("my_node", self._safe_node(self._my_node_fn, "my_node"))

# 2. Node signature
async def _my_node_fn(self, state: ConversationState) -> ConversationState:
    """One-line description."""
    logger.info(f"[my_node] intent={state.intent}")
    try:
        result = await some_service_call()
        state.intermediate_results["my_node_result"] = result
    except Exception as e:
        logger.error(f"[my_node] Failed: {e}", exc_info=True)
        state.intermediate_results["error"] = f"my_node: {str(e)}"
    return state

# 3. Add edge
workflow.add_edge("my_node", "response")

# 4. Add routing branch in _route_from_dialogue() at line ~1079
elif intent == "my_intent":
    return "my_node"  # must exactly match add_node() name
```

**Reserved `intermediate_results` keys** — never overwrite:
`intent`, `entities`, `time_range`, `sparql_results`, `uuids`, `sql_data`, `analytics_output`,
`visualization_path`, `error`

---

## FastAPI Endpoint Pattern

```python
# All endpoints return this envelope:
return JSONResponse({
    "status": "success",   # or "error"
    "data": {...},
    "trace_id": request.state.trace_id,
})

# RBAC on every data endpoint:
@app.get("/api/v1/sensors")
async def get_sensors(
    request: Request,
    user: UserContext = Depends(create_rbac_dependency(token_manager, "sensor:read")),
):
    ...

# Input: always typed Pydantic models — never raw await request.json()
# Health endpoint: no auth required — used by Docker health checks
```

---

## SPARQL Patterns

Always include these prefixes:
```sparql
PREFIX brick:  <https://brickschema.org/schema/Brick#>
PREFIX rdfs:   <http://www.w3.org/2000/01/rdf-schema#>
PREFIX bacnet: <http://data.ashrae.org/bacnet/#>
```

Rules: always use `LIMIT`; use `OPTIONAL` for optional props; prefer `rdfs:label`; never
interpolate user input directly into SPARQL; fall back to RAG when results empty.

---

## Common Commands

```bash
# Start stack
docker-compose up -d

# Rebuild one service
docker-compose build orchestrator && docker-compose up -d orchestrator

# Health checks
curl http://localhost:8000/health   # orchestrator
curl http://localhost:8001/health   # rag-service
curl http://localhost:8002/health   # code-executor

# Tests
pytest -m unit -x -v               # fast unit tests (always first)
pytest -m integration -v            # requires docker-compose up
pytest tests/ --cov=orchestrator --cov-report=html

# Linting
black --line-length 100 orchestrator/ shared/ scripts/ tests/
isort --profile black orchestrator/ tests/
flake8 orchestrator/ --max-line-length 110 --extend-ignore=E203,E501,W503
bandit -r orchestrator/ shared/ -ll

# Onboard new building
python scripts/onboard_building.py --building-id bldg2 --non-interactive
```

---

## Scoped Sub-Agents Reference (use `#file` to include their instructions)

| Domain | File | Use when |
|--------|------|----------|
| SPARQL / ontology / GraphDB | `.claude/agents/ontology-agent.md` | SPARQL failures, TTL parsing |
| Intent routing / LangGraph nodes | `.claude/agents/pipeline-agent.md` | Routing bugs, adding intents |
| Docker / env vars / ports | `.claude/agents/infra-agent.md` | Service failures, port conflicts |
| Writing or fixing tests | `.claude/agents/test-agent.md` | Coverage gaps, fixture questions |
| Pre-deployment review | `.claude/agents/deploy-agent.md` | Auth hardening, production checklist |

To include an agent's instructions in Copilot Chat:
```
#file:.claude/agents/ontology-agent.md  ← drag into chat or type #file:
```

---

## Workflow Principles

1. **Read before editing** — understand existing code before suggesting modifications
2. **No speculative abstractions** — don't add helpers for one-time operations
3. **Verify before marking done** — run tests, check logs, demonstrate correctness
4. **No security vulnerabilities** — no command injection, SQL injection, XSS
5. **No backwards-compat hacks** — delete unused code; don't rename to `_unused_`
