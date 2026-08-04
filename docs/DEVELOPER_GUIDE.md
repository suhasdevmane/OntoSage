# Developer Guide

This guide covers local development setup, codebase conventions, how to add new agents and intent types, testing strategy, CI/CD, and contribution workflow.

---

## Setting Up a Local Development Environment

### Prerequisites

- Python 3.10, 3.11, or 3.12
- Docker Desktop (for service dependencies)
- Git

### 1. Clone and Create Virtual Environment

```bash
git clone https://github.com/suhasdevmane/OntoSage.git
cd OntoSage

# Create virtual environment (Python 3.11 recommended)
python -m venv .venv

# Activate it
# Linux / macOS:
source .venv/bin/activate
# Windows:
.venv\Scripts\activate
```

### 2. Install Dependencies

```bash
# Core orchestrator dependencies
pip install -r orchestrator/requirements.txt

# Shared utilities
pip install -r shared/requirements.txt   # if present, else install from orchestrator

# Dev tools (testing, linting)
pip install pytest pytest-asyncio pytest-cov black isort flake8 bandit
```

### 3. Start Service Dependencies

You do not need to run the orchestrator itself locally — only the services it depends on:

```bash
# Start infrastructure services only (GraphDB, Redis, MySQL, PostgreSQL, Code Executor)
docker compose up -d graphdb redis mysql postgres-user-data code-executor rag-service
```

The orchestrator runs locally from your editor, connecting to these Dockerised services.

### 4. Configure Local Environment

```bash
cp .env.example .env
```

For local development, key settings:

```bash
MODEL_PROVIDER=openai         # or local if you have Ollama running
OPENAI_API_KEY=sk-...

# These point to Docker containers on localhost
MYSQL_HOST=localhost
MYSQL_PORT=3307               # host-mapped port from docker-compose.yml
REDIS_URL=redis://localhost:6379/0
RAG_SERVICE_URL=http://localhost:8001
CODE_EXECUTOR_URL=http://localhost:8002
GRAPHDB_HOST=localhost
GRAPHDB_PORT=7200
```

### 5. Run the Orchestrator Locally

```bash
# From repo root, with PYTHONPATH including orchestrator and shared
PYTHONPATH=. python -m uvicorn orchestrator.main:app --reload --host 0.0.0.0 --port 8000
```

The `--reload` flag enables hot reload on code changes.

---

## Code Style and Standards

### Formatting

All Python in `orchestrator/`, `shared/`, `scripts/`, and `tests/` must pass:

```bash
# Check formatting
black --check --line-length 100 orchestrator/ shared/ scripts/ tests/

# Auto-fix
black --line-length 100 orchestrator/ shared/ scripts/ tests/

# Import sorting
isort --check-only --profile black orchestrator/ tests/
isort --profile black orchestrator/ tests/
```

### Static Analysis

```bash
# Lint
flake8 orchestrator/ shared/ scripts/ \
  --max-line-length 110 \
  --extend-ignore=E203,E501,W503 \
  --per-file-ignores="__init__.py:F401"

# Security scan
bandit -r orchestrator/ shared/ -ll --exclude orchestrator/tests
```

### Type Hints

All new functions must have complete type hints:

```python
from typing import Dict, List, Optional, Any

async def fetch_sensor_data(
    uuid: str,
    start_time: str,
    end_time: Optional[str] = None,
) -> Dict[str, Any]:
    ...
```

Use `Optional[X]` not `X | None` (Python 3.9 compatibility). Use `Dict`, `List`, `Tuple` from `typing`, not built-in generics.

### Logging

```python
from shared.utils import get_logger
logger = get_logger(__name__)

# Entry point of every agent node
logger.info(f"[sparql_agent] intent={state.intent}, entities={entities}")

# Recoverable failures
logger.warning(f"[sparql_agent] SPARQL returned empty — falling back to RAG")

# Unexpected errors — always include exc_info
logger.error(f"[sparql_agent] Query failed: {e}", exc_info=True)
```

Never use `print()` in production code.

---

## Architecture Deep Dive

### LangGraph State Machine

The orchestrator is a LangGraph `StateGraph` defined in `orchestrator/workflow.py`. Every request flows through nodes connected by conditional edges:

```
dialogue → [routing by intent] → sparql / sql / analytics / planner / report / anomaly / export
                                          ↓
                                    visualization → response → end
```

The routing function `_route_from_dialogue()` at line ~1079 reads `state.intermediate_results["intent"]` and returns the name of the next node. All routing logic is centralised here.

### ConversationState

All agents share a single `ConversationState` object (defined in `shared/models.py`). The key communication channel is:

```python
state.intermediate_results: Dict[str, Any]
```

Reserved keys (never overwrite another agent's key):

| Key | Set by | Contains |
|-----|--------|---------|
| `intent` | dialogue | Classified intent string |
| `entities` | dialogue | Extracted entity list |
| `time_range` | dialogue | Parsed time range dict |
| `sparql_results` | sparql | SPARQL query results |
| `uuids` | sparql | Sensor UUID list for SQL |
| `sql_data` | sql | Raw time-series rows |
| `analytics_output` | analytics | Computed statistics |
| `visualization_path` | visualization | Path to saved chart |
| `error` | _safe_node | Error description if a node fails |

### The `_safe_node` Wrapper

Every node is wrapped with `_safe_node` to prevent pipeline crashes:

```python
# CORRECT
workflow.add_node("my_node", self._safe_node(self._my_node_fn, "my_node"))

# WRONG — bare registration has no error handling
workflow.add_node("my_node", self._my_node_fn)
```

The wrapper catches all exceptions, logs them with context, and returns state with an `"error"` key so the pipeline continues to the response node rather than raising an uncaught exception.

---

## Adding a New Intent Type

!!! tip "Registry-driven (2 steps) — the current path"
    Adding an intent **no longer requires editing the graph wiring**. The graph auto-registers nodes from the YAML intent registry, so the modern path is just **two steps**:

    1. Append an entry to `orchestrator/intents/intent_definitions.yaml` (or a per-building `input/<bldg>/intents.yaml` overlay) with `pipeline_group`, optional `route_target`, and `node_method`.
    2. Implement that `node_method` on `WorkflowOrchestrator` in `orchestrator/workflow/_orchestrator.py`.

    Restart — outgoing edges and conditional routing are generated automatically; a YAML-added intent with no node falls through to a safe `response`. The manual steps below remain useful only for **shared pipeline stages** (sparql/sql/analytics/response) that are not 1:1 with an intent.

### Step 1: Implement the Node Function

In `orchestrator/workflow/_orchestrator.py`, add an `async def` method to `WorkflowOrchestrator`:

```python
async def _maintenance_node_fn(self, state: ConversationState) -> ConversationState:
    """Predict maintenance needs from anomaly patterns."""
    logger.info(f"[maintenance_node] intent={state.intent}")
    try:
        # Use existing sparql/sql data if available
        sensor_data = state.intermediate_results.get("sql_data", {})
        # ... your logic here ...
        state.intermediate_results["maintenance_output"] = {"recommendations": [...]}
    except Exception as e:
        logger.error(f"[maintenance_node] Failed: {e}", exc_info=True)
        state.intermediate_results["error"] = f"maintenance_node: {str(e)}"
    return state
```

Rules:
- Always `async def`
- Always returns the same `ConversationState` (mutated in place)
- Always logs entry with `intent`
- Never raises — catch and set `error` key

### Step 2: Register the Node

In `_build_graph()` at line ~131:

```python
workflow.add_node("maintenance", self._safe_node(self._maintenance_node_fn, "maintenance"))
```

### Step 3: Add Outgoing Edge

At line ~186:

```python
workflow.add_edge("maintenance", "response")
```

Or if it needs visualization:

```python
workflow.add_edge("maintenance", "visualization")
```

### Step 4: Add Routing

In `_route_from_dialogue()` at line ~1079:

```python
elif intent == "predictive_maintenance":
    return "maintenance"   # MUST match the add_node() name exactly
```

### Step 5: Write a Test

In `tests/test_workflow_wiring.py`:

```python
def test_workflow_routes_predictive_maintenance():
    content = Path("orchestrator/workflow.py").read_text(encoding="utf-8")
    assert 'elif intent == "predictive_maintenance"' in content
    assert 'workflow.add_node("maintenance"' in content
    assert 'workflow.add_edge("maintenance"' in content
```

### Step 6: Update the Dialogue Agent Prompt

In `orchestrator/agents/dialogue_agent.py`, add the new intent to the intent classification prompt:

```python
INTENT_TYPES = [
    ...
    "predictive_maintenance",  # Add here
]
```

---

## Working with the Capability Routing Pipeline *(v2.0)*

The capability semantic routing pipeline ships with four collaborating components. When extending or debugging them, follow these guidelines.

### Architecture quick reference

| Component | File | Role |
|---|---|---|
| `EmbeddingService` | `orchestrator/services/embedding_service.py` | Provider switching · Redis embed cache |
| `CapabilityIndexer` | `orchestrator/services/capability_indexer.py` | Startup pipeline · SHA-256 idempotency |
| `SemanticRouter` | `orchestrator/services/semantic_router.py` | Query-time classifier · three-band threshold |
| `CapabilityAgent` | `orchestrator/agents/capability_agent.py` | Response formatting · provenance |

### Adding a new building's capability KB (zero code changes)

```bash
# 1. Author input/<id>_capabilities.ttl (ontosage:Amenity / KnowledgeTopic triples),
#    or add them via Admin ▸ Capabilities — capability.yaml was removed (TODO-012)
# 2. (Optional) tune in input/<new_bldg>/building.yaml::capability_routing
# 3. Restart orchestrator
docker compose restart orchestrator

# 4. Verify
docker logs ontosage-orchestrator | grep capability_indexer
# Expected: status=indexed entries=N points=M sha=<8-hex>
```

No Python edits, no migrations, no docker-compose changes.

### Adding a new semantic intent (multi-intent extension)

Beyond `capability`, you can register additional intents that benefit from semantic routing (e.g. `floor_plan`, `maintenance`). Opt-in per building:

```yaml
# input/<bldg>/building.yaml
intent_routing:
  maintenance:
    enabled: true
    descriptors:
      - "create a maintenance ticket"
      - "log a fault"
      - "report a broken sensor"
    threshold: 0.60
    override_min: 0.70
    top_k: 3
```

Then in `SemanticRouter.__init__`, the new intent is auto-registered. The dialogue agent will receive `SemanticRouteResult(intent="maintenance", ...)` and apply the same band logic. See `docs/superpowers/specs/2026-05-22-multi-intent-semantic-routing.md`.

### Calibrating thresholds for a new embedding model

Default thresholds (`threshold=0.65`, `override_min=0.85`) target a generic distribution. Real models produce tighter or wider ranges. Calibrate as follows:

```bash
# 1. Capture a baseline of golden queries
python scripts/capture_baseline.py --building bldg1 \
  --output tests/baselines/your_model.json

# 2. Sweep thresholds
python scripts/calibrate_intent_routing.py \
  --building bldg1 \
  --baseline tests/baselines/your_model.json \
  --threshold-range 0.40:0.75:0.02 \
  --override-range 0.50:0.85:0.02
```

The script outputs per-band precision/recall and an F1-optimal `(threshold, override_min)` pair.

### Testing capability routing changes

```bash
# Unit (fast)
pytest tests/test_embedding_service.py \
       tests/test_capability_indexer.py \
       tests/test_semantic_router.py \
       tests/test_capability_routing_config.py -v

# Live (requires Docker stack)
pytest tests/test_capability_e2e.py \
       tests/test_capability_edge_cases.py \
       tests/test_capability_semantic_quality.py \
       tests/test_non_regression_intents.py -v

# Performance
pytest tests/perf/test_capability_performance.py -v
```

The non-regression contract test (`test_non_regression_intents.py`) verifies that adding capability routing did not break any of the other 15 intents. Always run it after any change to `dialogue_agent.py` or `semantic_router.py`.

---

## Adding a New Storage Adapter

To support a new database type (e.g., ClickHouse):

### Step 1: Create the Adapter Class

Create `orchestrator/services/adapters/clickhouse_adapter.py`:

```python
from typing import Any, Dict, List, Optional
from orchestrator.services.adapters.base import DatabaseAdapter
from shared.utils import get_logger

logger = get_logger(__name__)

class ClickHouseAdapter(DatabaseAdapter):
    """ClickHouse adapter using clickhouse-connect."""

    def __init__(self, config: Dict[str, Any]) -> None:
        self.host = config["host"]
        self.port = int(config.get("port", 8123))
        self.database = config["database"]
        self.client = None

    async def connect(self) -> None:
        import clickhouse_connect
        self.client = await clickhouse_connect.get_async_client(
            host=self.host, port=self.port
        )

    async def query_sensor_data(
        self,
        uuids: List[str],
        start_time: str,
        end_time: str,
        limit: int = 10000,
    ) -> Dict[str, Any]:
        # ... implementation ...
        pass

    async def health_check(self) -> bool:
        try:
            await self.client.ping()
            return True
        except Exception:
            return False
```

### Step 2: Add to Registry

In `orchestrator/services/adapters/registry.py`, add to the `_build_adapter()` method:

```python
elif adapter_type == "clickhouse":
    from orchestrator.services.adapters.clickhouse_adapter import ClickHouseAdapter
    return ClickHouseAdapter(config)
```

### Step 3: Guard the Import in `__init__.py`

In `orchestrator/services/adapters/__init__.py`:

```python
try:
    from orchestrator.services.adapters.clickhouse_adapter import ClickHouseAdapter
except ImportError:
    ClickHouseAdapter = None  # requires clickhouse-connect
```

### Step 4: Add to `database_registry.yaml`

```yaml
clickhouse:
  type: clickhouse
  host: "${CLICKHOUSE_HOST:-clickhouse}"
  port: "${CLICKHOUSE_PORT:-8123}"
  database: "${CLICKHOUSE_DATABASE:-default}"
```

---

## Testing

### Test Structure

```
tests/
├── conftest.py                      # Shared fixtures, mock setup
├── fixtures/
│   ├── ontology_fixtures.py         # TTL data, SPARQL response mocks
│   └── __init__.py
├── test_workflow_wiring.py          # Structural tests (node/edge/routing wiring)
├── test_routing_and_contracts.py    # HTTP contract tests for all API endpoints
├── test_integration_mock_building.py # End-to-end with mocked LLM + real services
├── test_orchestrator.py             # Orchestrator unit tests
├── test_phase_a_fixes.py            # Phase A regression tests
├── test_phase_bc_services.py        # RBAC, caching, analytics services
├── test_phase3_4_services.py        # Ontology detection, similarity
├── test_routing_accuracy.py         # 29 canonical routing cases + audit invariants
├── test_turn_memory.py              # Phase 21 — Redis count-eviction, no-TTL SET, turn_memory schema
├── test_conversation_memory_e2e.py  # Phase 21 — carry-forward + older-context round-trip
├── test_coreference_rewrite.py      # Phase 22 — follow-up heuristic gate + gated rewrite (mocked LLM)
├── test_forecast_pipeline.py        # Phase 20 — forecasting models + metrics (live-stack)
├── test_code_executor.py            # Code sandbox security and execution
├── test_rag_service.py              # RAG retrieval quality tests
└── performance_benchmark.py         # Latency benchmarks (not in CI)
```

The CI unit-tests job runs a curated deterministic suite (**251 tests, 3 skipped, 0 fail** on the Python 3.10/3.11/3.12 matrix) — see `.github/workflows/ci.yml` for the exact file list, which now gates the turn-memory and co-reference tests.

### Running Tests

```bash
# All tests
pytest tests/ -v

# By marker
pytest -m unit           # fast, no external services
pytest -m integration    # requires Docker services running

# Single file
pytest tests/test_workflow_wiring.py -v

# With coverage
pytest tests/ --cov=orchestrator --cov=shared --cov-report=html
# Open: htmlcov/index.html
```

### Writing Tests

Use `pytest-asyncio` for async tests:

```python
import pytest
from unittest.mock import patch, AsyncMock

@pytest.mark.asyncio
async def test_sparql_agent_returns_uuids():
    """SPARQL agent extracts UUIDs from query results."""
    from orchestrator.agents.sparql_agent import SPARQLAgent
    agent = SPARQLAgent()

    with patch("orchestrator.agents.sparql_agent.llm_manager.generate") as mock_llm:
        mock_llm.return_value = "SELECT ?uuid WHERE { ... }"
        # ... test body ...
```

**Key mock targets** (as of current codebase):
- LLM calls: `patch("orchestrator.agents.<agent_module>.llm_manager.generate")`
- Redis: `patch("orchestrator.agents.<agent_module>.redis_manager")`
- SQL adapters: `patch.object(adapter_instance, "query_sensor_data")`

### Test Markers

Add markers to `pyproject.toml` or use inline:

```python
@pytest.mark.unit          # no external services, fast (<1s)
@pytest.mark.integration   # requires Docker services
@pytest.mark.slow          # >5 second tests (not run in fast CI)
@pytest.mark.live          # hits real external APIs (never run in CI)
```

---

## CI/CD Pipeline

The GitHub Actions CI pipeline (`.github/workflows/ci.yml`) runs on every push to `main`, `develop`, and `feature/**` branches.

### Jobs

| Job | What it checks |
|-----|---------------|
| `lint` | Black, isort, flake8, bandit |
| `unit-3.10` / `unit-3.11` / `unit-3.12` | Unit tests on all supported Python versions |
| `integration` | Integration tests against mocked services |
| `onboarding-cli` | Non-interactive CLI smoke test |
| `multi-building-config` | Database registry YAML validation |
| `rag-benchmark` | RAG retrieval quality (BLEU score threshold) |
| `docker-build` | `docker compose build` succeeds |
| `security-scan` | Bandit security audit |
| `ci-summary` | Required gate — blocks merge if any job fails |

### Running CI Locally

```bash
# Simulate lint job
black --check --line-length 100 orchestrator/ shared/ scripts/ tests/
isort --check-only --profile black orchestrator/ tests/
flake8 orchestrator/ shared/ scripts/ --max-line-length 110 --extend-ignore=E203,E501,W503

# Simulate unit test job
pytest tests/ -m "not integration and not slow and not live" -v

# Simulate integration test job (requires Docker services)
pytest tests/ -m integration -v
```

---

## FastAPI Endpoint Conventions

All endpoints in `orchestrator/main.py` must follow these patterns:

### Response Envelope

```python
from fastapi.responses import JSONResponse

# Success
return JSONResponse({
    "status": "success",
    "data": {...},
    "trace_id": request.state.trace_id,
})

# Error
return JSONResponse({
    "status": "error",
    "message": "Human-readable description",
    "trace_id": request.state.trace_id,
}, status_code=400)
```

### RBAC Protection

```python
from orchestrator.middleware.rbac import create_rbac_dependency, UserContext
from fastapi import Depends

@app.get("/api/v1/sensors")
async def get_sensors(
    request: Request,
    user: UserContext = Depends(create_rbac_dependency(token_manager, "sensor:read")),
):
    ...
```

### Input Validation

Always use Pydantic models — never `await request.json()` directly:

```python
from pydantic import BaseModel, Field

class SensorQueryRequest(BaseModel):
    uuid: str = Field(..., description="Sensor UUID from ontology")
    start_time: str = Field(..., description="ISO 8601 start time")
    end_time: Optional[str] = Field(None, description="ISO 8601 end time (default: now)")
```

---

## Project Conventions

### Commit Messages

Follow Conventional Commits:

```
feat: add predictive_maintenance intent type
fix: sparql agent returns empty list instead of None on no results
docs: update building onboarding guide for TimescaleDB
test: add integration tests for analytics agent code generation
refactor: extract sensor UUID resolution into shared utility
```

### Branch Naming

```
feature/add-maintenance-intent
fix/sparql-empty-results
docs/update-onboarding
```

### Pull Requests

- All CI jobs must pass
- Self-review before requesting review
- Update `docs/` if the change affects user-facing behavior
- Update `tests/test_workflow_wiring.py` for any routing changes

---

## Frequently Used Commands

```bash
# Format all Python files
black --line-length 100 orchestrator/ shared/ scripts/ tests/
isort --profile black orchestrator/ tests/

# Quick health check after making changes
curl http://localhost:8000/health

# View orchestrator logs
docker compose logs -f orchestrator

# Rebuild orchestrator after code changes
docker compose build orchestrator
docker compose up -d orchestrator

# Access FastAPI interactive docs
open http://localhost:8000/docs

# Run SPARQL query directly against GraphDB (bypass orchestrator)
curl -X POST http://localhost:7200/repositories/ontosage/sparql \
  -H "Content-Type: application/sparql-query" \
  -H "Accept: application/sparql-results+json" \
  -d "SELECT ?s WHERE { ?s a <https://brickschema.org/schema/Brick#Temperature_Sensor> } LIMIT 5"

# Test code executor directly
curl -X POST http://localhost:8002/execute \
  -H "Content-Type: application/json" \
  -d '{"code": "import pandas as pd\nresult = {\"mean\": 22.5}", "timeout": 10}'
```
