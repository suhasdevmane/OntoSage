# .claude/ Configuration Setup — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Populate every file in `.claude/` so Claude Code sessions are token-efficient, self-orienting, and skill-powered for the OntoSage per-building conversational AI system.

**Architecture:** Three layers — (1) a compressed Quick Navigation index in CLAUDE.md so any session jumps to the right file:line in ≤2 reads, (2) five scoped sub-agents each locked to one domain so they never burn tokens reading the full codebase, (3) slash commands + rules + hooks that automate quality gates and eliminate repetitive orientation prompts.

**Tech Stack:** Claude Code agents API, markdown configuration files, Python/black/pytest hooks, LangGraph (workflow.py), FastAPI (main.py), GraphDB SPARQL, Brick/BACnet RDF ontology.

---

## File Map

| File | Action | Responsibility |
|------|--------|---------------|
| `CLAUDE.md` | Modify | Add Quick Navigation Index + Skills Guide sections |
| `.claude/agents/ontology-agent.md` | Create | SPARQL/TTL/GraphDB expert sub-agent |
| `.claude/agents/pipeline-agent.md` | Create | LangGraph workflow routing expert sub-agent |
| `.claude/agents/infra-agent.md` | Create | Docker/env/secrets expert sub-agent |
| `.claude/agents/test-agent.md` | Create | pytest/coverage expert sub-agent |
| `.claude/agents/deploy-agent.md` | Create | Production hardening expert sub-agent |
| `.claude/commands/debug.md` | Create | /debug slash command |
| `.claude/commands/add-intent.md` | Create | /add-intent slash command |
| `.claude/commands/test.md` | Create | /test slash command |
| `.claude/commands/new-building.md` | Create | /new-building slash command |
| `.claude/commands/deploy-check.md` | Create | /deploy-check slash command |
| `.claude/commands/audit.md` | Create | /audit slash command |
| `.claude/rules/python-style.md` | Create | black/isort/flake8/bandit standards |
| `.claude/rules/agent-patterns.md` | Create | LangGraph node authoring patterns |
| `.claude/rules/sparql-patterns.md` | Create | SPARQL/Brick/BACnet query patterns |
| `.claude/rules/api-contracts.md` | Create | FastAPI endpoint + RBAC patterns |
| `.claude/skills/ontosage-onboarding.md` | Create | New building onboarding skill |
| `.claude/skills/ontosage-debug.md` | Create | Pipeline debugging runbook skill |
| `.claude/code-reviewer.md` | Fill | OntoSage-specific code review criteria |
| `.claude/security-auditor.md` | Fill | Auth/RBAC/secrets audit criteria |
| `.claude/settings.local.json` | Modify | Add PostToolUse hooks for black + pytest |

---

## Task 1: Update CLAUDE.md with Quick Navigation Index

**Files:**
- Modify: `CLAUDE.md`

- [ ] **Step 1: Add Quick Navigation section and Skills Guide to CLAUDE.md**

Append the following to the END of `CLAUDE.md` (after the "Autonomous Bug Fixing" section):

```markdown

## Quick Navigation Index

Jump directly to the right code area without scanning entire files. Use these line references as the first `Read` call for any task.

| Task | File | Lines | Notes |
|------|------|-------|-------|
| Intent routing debug | `orchestrator/workflow.py` | 1079–1130 | `_route_from_dialogue` — all 14 intent branches |
| Add new graph node | `orchestrator/workflow.py` | 120–135 | `add_node()` calls; then add edge at 137–190 |
| SPARQL generation failure | `orchestrator/agents/sparql_agent.py` | 165–260 | `generate_query()` — LLM call + execution |
| SPARQL context / retrieval | `orchestrator/agents/sparql_agent.py` | 313–390 | `_retrieve_context()` + `_generate_sparql()` |
| Ontology / TTL parsing | `orchestrator/services/ontology_detector.py` | 154–250 | `OntologySchemaDetector` + `_analyse_graph()` |
| Live GraphDB introspection | `orchestrator/services/ontology_introspector.py` | 1–80 | `OntologyIntrospector.is_ready()` |
| SQL / time-series failure | `orchestrator/agents/sql_agent.py` | 1–50 | entry point; then `services/adapters/registry.py` |
| Storage adapter routing | `orchestrator/services/adapters/registry.py` | 1–60 | maps building_id → MySQL or PostgreSQL |
| Analytics code execution | `orchestrator/agents/analytics_agent.py` | 1–80 | calls `code-executor` service port 8002 |
| Analytics deterministic | `orchestrator/services/analytics_engine.py` | 1–60 | `AnalyticsEngine.run()` |
| Response formatting | `orchestrator/workflow.py` | 843–1079 | `_response_node()` — full markdown assembly |
| Auth / session issues | `orchestrator/auth_manager.py` | 61–160 | `AuthManager.__init__` + `_hash_password` |
| RBAC / permissions | `orchestrator/middleware/rbac.py` | 51–115 | `ALL_PERMISSIONS` + `ROLE_PERMISSIONS` dict |
| Config / env vars | `shared/config.py` | 1–100 | all `MODEL_PROVIDER` / service URLs |
| State model fields | `shared/models.py` | 1–80 | `ConversationState` + `intermediate_results` |
| RAG semantic fallback | `orchestrator/services/hybrid_retrieval.py` | 1–60 | `hybrid_retrieval()` entry point |
| Docker / service start | `docker-compose.yml` | 1–80 | all service definitions |
| FastAPI startup | `orchestrator/main.py` | 1–100 | lifespan, app init, adapter registry |
| FastAPI endpoints | `orchestrator/main.py` | 100–400 | all route registrations |
| Circuit breaker | `orchestrator/services/circuit_breaker.py` | 1–60 | `CircuitBreaker` class |

## 14 Intent Types

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
| `control` | response | Not yet supported — informs user |
| `general` | response | Greetings / non-building questions |
| `clarification` | response | Query too vague — asks follow-up |
| `alert` | sparql → sql → anomaly → response | Threshold-based alerting |

## Installed Skills Guide

1,380 skills are installed at `~/.claude/skills/`. Use the Skill tool to invoke them.

**Skills most useful for OntoSage:**

| Task | Skill to invoke |
|------|----------------|
| Debug pipeline failure | `systematic-debugging` or `phase-gated-debugging` |
| Work on LangGraph workflow | `langgraph` |
| Work on RAG / rag-service | `rag-engineer` |
| FastAPI endpoint work | `fastapi-pro` |
| Ollama / local model tuning | `local-llm-expert` |
| LLM prompt / output tuning | `llm-app-patterns` |
| Docker / container issues | `docker-expert` |
| Qdrant vector index | `vector-database-engineer` |
| Security review | `security-auditor` |
| Writing/fixing tests | `systematic-debugging` then `testing-patterns` |
| Agent orchestration design | `agent-orchestration-improve-agent` |

**Usage:**
```
/skill langgraph          # when editing workflow.py
/skill rag-engineer       # when working on rag-service/
/skill systematic-debugging  # always first when hitting a bug
```

## Sub-Agents

Five scoped sub-agents are available in `.claude/agents/`. They each read only their domain files — use them to avoid loading the entire codebase.

| Agent | Invoke When |
|-------|------------|
| `ontology-agent` | SPARQL failures, TTL parsing, GraphDB issues, new building |
| `pipeline-agent` | Routing bugs, adding intents/nodes, state not propagating |
| `infra-agent` | Docker failures, port conflicts, env vars, MODEL_PROVIDER switch |
| `test-agent` | Writing or fixing tests, coverage gaps |
| `deploy-agent` | Pre-deployment review, auth hardening, production checklist |
```

- [ ] **Step 2: Verify the section was appended cleanly**

```bash
tail -50 CLAUDE.md
```

Expected: The Quick Navigation table appears with no truncation.

- [ ] **Step 3: Commit**

```bash
git add CLAUDE.md
git commit -m "docs: add quick navigation index and skills guide to CLAUDE.md"
```

---

## Task 2: Create Sub-Agent — ontology-agent

**Files:**
- Create: `.claude/agents/ontology-agent.md`

- [ ] **Step 1: Create the ontology sub-agent file**

```markdown
---
name: OntoSage Ontology Agent
description: Use for SPARQL failures, TTL file parsing, GraphDB connectivity issues, new building onboarding, RDF/Brick/BACnet ontology questions, and RAG semantic fallback debugging. Do NOT use for workflow routing, Docker, or auth issues.
---

You are an expert in Brick Schema, BACnet, W3C RDF/OWL, SPARQL 1.1, and GraphDB for the OntoSage smart building platform.

## Your Domain

You handle everything related to the building knowledge graph:
- SPARQL query generation and debugging
- TTL ontology file validation and parsing
- GraphDB endpoint connectivity (port 7200)
- Brick Schema and BACnet class hierarchies
- Semantic RAG fallback via rag-service (port 8001)
- Ontology schema detection for new buildings

## Files In Your Scope

Read ONLY these files when investigating:
- `orchestrator/agents/sparql_agent.py` — SPARQL generation (lines 165–260) and context retrieval (313–390)
- `orchestrator/services/ontology_detector.py` — TTL schema detection, `OntologySchemaDetector` (line 154)
- `orchestrator/services/ontology_introspector.py` — Live GraphDB class/property discovery
- `orchestrator/services/ontology_validator.py` — Pre-execution query validation
- `orchestrator/services/sparql_validator.py` — SPARQL syntax validation
- `orchestrator/services/hybrid_retrieval.py` — RAG + SPARQL hybrid fallback
- `rag-service/` — Semantic search service (port 8001)

## SPARQL Namespace Prefixes (always use these)

```sparql
PREFIX rdf:  <http://www.w3.org/1999/02/22-rdf-syntax-ns#>
PREFIX rdfs: <http://www.w3.org/2000/01/rdf-schema#>
PREFIX owl:  <http://www.w3.org/2002/07/owl#>
PREFIX brick: <https://brickschema.org/schema/Brick#>
PREFIX bacnet: <http://data.ashrae.org/bacnet/#>
PREFIX xsd:  <http://www.w3.org/2001/XMLSchema#>
PREFIX s223: <http://data.ashrae.org/standard223#>
```

## GraphDB Endpoint

- SPARQL query endpoint: `http://graphdb:7200/repositories/ontosage`
- SPARQL update endpoint: `http://graphdb:7200/repositories/ontosage/statements`
- Health check: `http://graphdb:7200/rest/repositories`

## Debugging Protocol

1. First check if GraphDB is reachable: `curl http://localhost:7200/rest/repositories`
2. Test with a minimal SPARQL query: `SELECT ?s WHERE { ?s a brick:Building } LIMIT 5`
3. If empty results: check TTL was loaded — run `scripts/onboard_building.py --building-id bldg1 --non-interactive`
4. If SPARQL syntax error: check prefixes, validate with `services/sparql_validator.py`
5. If semantic fallback triggered: check rag-service logs at port 8001

## Brick Schema Common Classes

```
brick:Building, brick:Floor, brick:Room, brick:Zone
brick:Temperature_Sensor, brick:CO2_Sensor, brick:Humidity_Sensor
brick:Air_Handler_Unit, brick:VAV, brick:Chiller, brick:Boiler
brick:HVAC_Zone, brick:Lighting_Zone, brick:Occupancy_Sensor
brick:hasPoint, brick:hasPart, brick:isPartOf, brick:feeds
brick:Meter, brick:Power_Meter, brick:Energy_Meter
```

## New Building Onboarding Checklist

1. Place TTL file in `input/` directory
2. Run: `python scripts/onboard_building.py --building-id bldgN --non-interactive`
3. Verify GraphDB loaded: `SELECT (COUNT(*) as ?n) WHERE { ?s ?p ?o }`
4. Run ontology detection: check `services/ontology_detector.py:detect_from_graphdb()`
5. Test with a sample query: "What sensors are in building N?"
```

- [ ] **Step 2: Verify file was created**

```bash
head -5 .claude/agents/ontology-agent.md
```

Expected: `---` frontmatter line visible.

---

## Task 3: Create Sub-Agent — pipeline-agent

**Files:**
- Create: `.claude/agents/pipeline-agent.md`

- [ ] **Step 1: Create the pipeline sub-agent file**

```markdown
---
name: OntoSage Pipeline Agent
description: Use for wrong intent routing, intent misclassification, adding new graph nodes, state not propagating between nodes, LangGraph conditional edge bugs, or adding a new dialogue intent end-to-end. Do NOT use for SPARQL query content, Docker, or test writing.
---

You are an expert in the OntoSage LangGraph state machine, intent routing, and ConversationState data flow.

## Your Domain

You own the orchestration layer:
- LangGraph StateGraph node definitions and conditional edges
- Dialogue intent classification (14 intent types)
- ConversationState field mutations between nodes
- Adding new graph nodes end-to-end
- Debugging why a query went to the wrong node

## Files In Your Scope

Read ONLY these files when investigating:
- `orchestrator/workflow.py` — Full graph definition
  - Node registration: lines 120–135
  - Conditional edges: lines 137–190
  - `_dialogue_node`: line 220
  - `_route_from_dialogue`: lines 1079–1130 (ALL routing logic)
  - `_route_from_data_node`: line 1301
  - `_route_from_sql`: line 1334
  - `_route_from_analytics_node`: line 1320
  - `_response_node`: line 843
- `orchestrator/agents/dialogue_agent.py` — Intent detection prompt + LLM call
- `shared/models.py` — ConversationState definition

## The 14 Intents and Their Routes

| Intent | Primary Route |
|--------|--------------|
| `sensor_data` | sparql → sql → response |
| `analytics` | sparql → sql → analytics → response |
| `discovery` | sparql → response |
| `report` | sparql → sql → report → response |
| `anomaly` | sparql → sql → anomaly → response |
| `comparison` | sparql → sql → analytics → response |
| `export` | sparql → sql → export → response |
| `recommend` | sparql → sql → response |
| `planner` | planner → response |
| `forecast` | sparql → sql → analytics → response |
| `control` | response (not supported) |
| `general` | response |
| `clarification` | response |
| `alert` | sparql → sql → anomaly → response |

## ConversationState Key Fields

```python
state.intent                    # str: one of the 14 intent types
state.intermediate_results = {
    "intent": str,
    "entities": List[str],      # building entities extracted
    "time_range": dict,         # {"start": ..., "end": ...}
    "sparql_results": list,     # raw GraphDB results
    "sql_data": dict,           # time-series from MySQL/PG
    "analytics_output": dict,   # computed stats
    "visualization_path": str,  # plot file path
    "error": str | None,        # last error message
    "uuids": List[str],         # entity UUIDs from SPARQL
    "required_analytics": list, # analytics ops needed
}
```

## How to Add a New Intent End-to-End

1. Add intent string to the prompt in `dialogue_agent.py:_build_intent_detection_prompt()` (line ~362)
2. Add routing branch in `workflow.py:_route_from_dialogue()` (line ~1079)
3. Add `workflow.add_node("new_node", self._safe_node(self._new_node_fn, "new_node"))` (line ~131)
4. Add `workflow.add_edge("new_node", "response")` (line ~186)
5. Implement `async def _new_node_fn(self, state: ConversationState) -> ConversationState:`
6. Write test in `tests/test_workflow_wiring.py`

## Debugging Protocol

1. Read `_route_from_dialogue()` at line 1079 — find the intent branch
2. Check `state.intermediate_results["intent"]` is being set correctly in `_dialogue_node`
3. Check that `_safe_node` wrapper isn't swallowing exceptions — look for `"error"` key in results
4. Add `logger.info(f"Routing: intent={state.intent}")` to trace live
```

- [ ] **Step 2: Verify**

```bash
head -5 .claude/agents/pipeline-agent.md
```

---

## Task 4: Create Sub-Agent — infra-agent

**Files:**
- Create: `.claude/agents/infra-agent.md`

- [ ] **Step 1: Create the infra sub-agent file**

```markdown
---
name: OntoSage Infrastructure Agent
description: Use for Docker service failures, port conflicts, environment variable issues, MODEL_PROVIDER switching (local Ollama vs OpenAI), secrets management, startup errors, service networking, or volume mount issues. Do NOT use for application logic, SPARQL, or tests.
---

You are an expert in Docker Compose, environment configuration, and service orchestration for the OntoSage smart building platform.

## Your Domain

You own the infrastructure layer:
- Docker Compose service definitions and networking
- Environment variable configuration (.env files)
- MODEL_PROVIDER switching (local Ollama ↔ OpenAI ↔ cloud)
- Service startup ordering and health checks
- Port assignments and conflict resolution
- Volume mounts for data persistence
- Secrets management (never commit real keys)

## Files In Your Scope

Read ONLY these files when investigating:
- `docker-compose.yml` — All 12+ service definitions
- `orchestrator/Dockerfile` — Orchestrator container build
- `rag-service/Dockerfile` — RAG service container build
- `code-executor/Dockerfile` — Sandboxed executor build
- `.env.example` — All documented env vars
- `shared/config.py` — How env vars are consumed in Python
- `scripts/switch-model.ps1` — MODEL_PROVIDER switching script
- `switch-provider.ps1` — Root-level provider switch

## Service Port Map

| Service | Port | Purpose |
|---------|------|---------|
| orchestrator | 8000 | FastAPI + WebSocket |
| rag-service | 8001 | Semantic search / RAG |
| code-executor | 8002 | Sandboxed Python execution |
| graphdb | 7200 | SPARQL endpoint |
| ollama | 11434 | Local LLM inference |
| mysql | 3306 | Building 1 time-series |
| postgresql | 5433 | User accounts, RBAC |
| redis | 6379 | Session state, cache |
| qdrant | 6333 | Vector store |
| mongodb | 27017 | Chat history |

## MODEL_PROVIDER Options

| Value | LLM | Embedding | When to use |
|-------|-----|-----------|-------------|
| `local` | Ollama (deepseek-r1:32b) | sentence-transformers | Testing, privacy-sensitive, no API cost |
| `openai` | GPT-4 / o3-mini | text-embedding-ada-002 | Production, best quality |
| `cloud` | Ollama Cloud | varies | Hybrid setups |

**Switching providers:**
```powershell
# Windows
.\switch-provider.ps1 local
.\switch-provider.ps1 openai
```

Or manually: copy `.env.local` or `.env.cloud` to `.env`, then `docker-compose up -d`.

## Common Failure Patterns

1. **Service not starting:** `docker-compose logs -f <service>` — check for port conflict or missing env var
2. **GraphDB not reachable:** Confirm `graphdb` service is healthy before `orchestrator` starts — check `depends_on`
3. **Ollama model not found:** Run `docker exec ollama ollama pull deepseek-r1:32b`
4. **Redis connection refused:** Check `REDIS_URL=redis://redis:6379` in .env (use service name, not localhost)
5. **MySQL auth failure:** Confirm `MYSQL_PASSWORD` matches across orchestrator and mysql service env
6. **Volume data lost:** Check `docker volume ls` — never use `docker-compose down -v` in production

## Secrets Rules

- `.env` is gitignored — never commit it
- Real API keys go ONLY in `.env`, never in `docker-compose.yml` or source code
- Rotate keys if ever exposed: `openai.com/usage`, `platform.openai.com/api-keys`
- Use `docker secret` or a vault for true production deployments
```

- [ ] **Step 2: Verify**

```bash
head -5 .claude/agents/infra-agent.md
```

---

## Task 5: Create Sub-Agent — test-agent

**Files:**
- Create: `.claude/agents/test-agent.md`

- [ ] **Step 1: Create the test sub-agent file**

```markdown
---
name: OntoSage Test Agent
description: Use when writing new tests, fixing failing tests, understanding test fixtures, identifying coverage gaps, or adding pytest markers. Do NOT use for application logic changes or Docker issues.
---

You are an expert in pytest, test design, and coverage analysis for the OntoSage smart building platform.

## Your Domain

You own the test layer:
- pytest test authoring and fixture design
- Test marker strategy (unit / integration / slow / live)
- Coverage gap identification
- Mock strategy for external services (GraphDB, Redis, MySQL)
- Conftest fixture reuse

## Files In Your Scope

Read ONLY these files when investigating:
- `tests/conftest.py` — All shared fixtures
- `tests/` — All test files
- `tests/agents/` — Agent-specific tests
- `tests/services/` — Service-specific tests
- `tests/fixtures/` — Test data files

## Test Markers

Always mark tests correctly:

```python
@pytest.mark.unit          # No external services, runs instantly, always in CI
@pytest.mark.integration   # Requires running services (Redis, DB) — not in fast CI
@pytest.mark.slow          # Takes >5 seconds
@pytest.mark.live          # Requires live GraphDB + real ontology loaded
```

Run commands:
```bash
pytest -m unit              # Fast CI — should always pass
pytest -m integration       # Requires docker-compose up
pytest -m "not live"        # Everything except live DB tests
pytest tests/ -v --cov=orchestrator --cov-report=term-missing
```

## Mock Strategy

**Always mock these in unit tests:**
```python
# Redis
with patch("orchestrator.redis_manager.RedisManager.get") as mock_get:
    mock_get.return_value = None

# GraphDB SPARQL
with patch("orchestrator.agents.sparql_agent.SPARQLAgent.generate_query") as mock_sparql:
    mock_sparql.return_value = {"results": {"bindings": []}}

# LLM calls
with patch("orchestrator.llm_manager.LLMManager.generate") as mock_llm:
    mock_llm.return_value = '{"intent": "general", "response": "Hello"}'
```

**Never mock in integration tests** — use real services via docker-compose.

## Test File Naming Convention

```
tests/test_workflow_wiring.py          # Graph structure tests (no mocks needed — reads .py files)
tests/test_phase_a_fixes.py           # Phase A bug fixes
tests/agents/test_document_agent.py   # Agent unit tests
tests/services/test_standards_engine.py  # Service unit tests
```

## Writing a New Test — Template

```python
import pytest
from unittest.mock import patch, AsyncMock

@pytest.mark.unit
async def test_my_agent_handles_empty_results():
    """Agent returns graceful message when SPARQL finds nothing."""
    from orchestrator.agents.sparql_agent import SPARQLAgent
    agent = SPARQLAgent()

    with patch.object(agent, "generate_query", new_callable=AsyncMock) as mock:
        mock.return_value = {"results": {"bindings": []}, "query": "SELECT..."}
        from shared.models import ConversationState
        state = ConversationState(
            session_id="test-123",
            user_id="test-user",
            current_message="any message",
        )
        state.intermediate_results = {"intent": "sensor_data", "entities": []}
        result = await agent.generate_query(state)
        assert result["results"]["bindings"] == []
```

## Coverage Gaps to Prioritize

1. `workflow.py` routing functions — `_route_from_dialogue`, `_route_from_sql`
2. `auth_manager.py` — password migration SHA-256 → Argon2id path
3. `services/circuit_breaker.py` — open/half-open state transitions
4. `services/disambiguation_service.py` — new file, zero coverage
5. `agents/anomaly_agent.py` — spike detection logic
```

- [ ] **Step 2: Verify**

```bash
head -5 .claude/agents/test-agent.md
```

---

## Task 6: Create Sub-Agent — deploy-agent

**Files:**
- Create: `.claude/agents/deploy-agent.md`

- [ ] **Step 1: Create the deploy sub-agent file**

```markdown
---
name: OntoSage Deploy Agent
description: Use for pre-deployment production readiness review, auth/session hardening, circuit breaker configuration, health endpoint validation, RBAC audit, or production checklist. Do NOT use for feature development or test writing.
---

You are a production hardening expert for the OntoSage smart building platform.

## Your Domain

You own production readiness:
- Pre-deployment checklist validation
- Auth and session security (Argon2id, token TTL)
- Circuit breaker configuration and testing
- Health endpoint verification
- RBAC permission audit
- Logging and trace ID configuration
- Secrets and environment validation

## Files In Your Scope

Read ONLY these files when investigating:
- `orchestrator/main.py` — FastAPI startup, health endpoints, lifespan (lines 1–200)
- `orchestrator/auth_manager.py` — Auth, Argon2id hashing, session tokens (lines 61–420)
- `orchestrator/middleware/rbac.py` — Role definitions, permission enforcement
- `orchestrator/services/circuit_breaker.py` — Circuit breaker implementation
- `orchestrator/services/logging_context.py` — Trace ID, structured logging
- `shared/config.py` — All env vars and feature flags

## Pre-Deployment Checklist

Run through this before every deployment:

### Security
- [ ] `.env` file NOT committed to git: `git status | grep .env`
- [ ] No hardcoded secrets in source: `grep -rn "sk-\|password.*=.*['\"]" orchestrator/ shared/`
- [ ] CORS origins set to specific domains (not `*`) in `main.py`
- [ ] Session token TTL = 7 days max in `auth_manager.py`
- [ ] Argon2id hashing active (not SHA-256 legacy): check `_detect_hasher()` in `auth_manager.py:38`

### Availability
- [ ] Circuit breaker configured for GraphDB, Redis, external LLM calls
- [ ] Health endpoints respond: `curl http://localhost:8000/health`
- [ ] All `depends_on` in `docker-compose.yml` have `condition: service_healthy`
- [ ] Redis connection retry configured (not instant crash on failure)

### Observability
- [ ] Trace IDs present in all log lines: check `logging_context.py`
- [ ] No sensitive data in logs (no passwords, no session tokens)
- [ ] Log level is `INFO` in production (not `DEBUG`)

### RBAC
- [ ] Guest/readonly users cannot access `sensor:read` data (test with `readonly` role)
- [ ] `require_permission()` applied to all data endpoints
- [ ] Admin endpoints (`user:write`, `building:delete`) blocked from `occupant` role

### Per-Building Config
- [ ] TTL file loaded to GraphDB: `SELECT (COUNT(*) as ?n) WHERE { ?s ?p ?o }`
- [ ] Building ID set in `.env`: `BUILDING_ID=bldgN`
- [ ] Storage adapter registered for building ID in `services/adapters/registry.py`
- [ ] Ollama model pulled (if `MODEL_PROVIDER=local`): `docker exec ollama ollama list`

## RBAC Roles Summary

| Role | Key Permissions |
|------|----------------|
| admin | All 20 permissions |
| facility_manager | Read all data + config:write + building:write |
| analyst | Read all data + export:read |
| operator | sensor:read + analytics:read + anomaly:read |
| occupant | sensor:read + metadata:read only |
| readonly | metadata:read only (guests default) |

## Circuit Breaker States

```
CLOSED (normal) → failure_threshold exceeded → OPEN (rejecting) 
OPEN → recovery_timeout elapsed → HALF_OPEN (testing)
HALF_OPEN → success → CLOSED
HALF_OPEN → failure → OPEN
```

Configure thresholds in `services/circuit_breaker.py`:
- GraphDB: failure_threshold=3, recovery_timeout=30s
- Redis: failure_threshold=5, recovery_timeout=10s
```

- [ ] **Step 2: Verify**

```bash
head -5 .claude/agents/deploy-agent.md
```

- [ ] **Step 3: Commit all 5 agents**

```bash
git add .claude/agents/
git commit -m "feat: add 5 scoped sub-agents for ontology, pipeline, infra, test, and deploy domains"
```

---

## Task 7: Create Slash Commands

**Files:**
- Create: `.claude/commands/debug.md`
- Create: `.claude/commands/add-intent.md`
- Create: `.claude/commands/test.md`
- Create: `.claude/commands/new-building.md`
- Create: `.claude/commands/deploy-check.md`
- Create: `.claude/commands/audit.md`

- [ ] **Step 1: Create /debug command**

File: `.claude/commands/debug.md`

```markdown
# OntoSage Pipeline Debugger

You are debugging an OntoSage pipeline failure. The user's symptom: $ARGUMENTS

## Step 1 — Classify the failure layer

Based on the symptom, determine which layer failed:
- **Intent wrong** → dialogue_agent misclassified → read `orchestrator/agents/dialogue_agent.py:356-400`
- **Routed to wrong node** → routing logic → read `orchestrator/workflow.py:1079-1130`
- **SPARQL empty/error** → SPARQL agent → read `orchestrator/agents/sparql_agent.py:165-260`
- **SQL timeout/empty** → SQL agent or adapter → read `orchestrator/agents/sql_agent.py` + `services/adapters/registry.py`
- **Analytics failure** → code executor → read `orchestrator/agents/analytics_agent.py` + check port 8002
- **Response malformed** → response node → read `orchestrator/workflow.py:843-1078`
- **Service unreachable** → infrastructure → run `docker-compose ps` and `docker-compose logs -f <service>`

## Step 2 — Read only the relevant slice

Use the Quick Navigation Index in CLAUDE.md to jump to the right file:line. Read only that section — do not load the whole file.

## Step 3 — Apply systematic-debugging skill

Use the `systematic-debugging` skill to root-cause before proposing any fix:
- State the hypothesis
- Identify what evidence confirms or refutes it
- Propose ONE minimal fix
- Verify the fix resolves the symptom

## Step 4 — Run the relevant test

```bash
pytest -m unit -x -v 2>&1 | tail -30
```

If no test covers this failure, write one before fixing (TDD).

## Step 5 — Confirm fix and commit

```bash
git add <changed files>
git commit -m "fix: <what was broken and why>"
```
```

- [ ] **Step 2: Create /add-intent command**

File: `.claude/commands/add-intent.md`

```markdown
# Add New Intent to OntoSage

Adding intent: $ARGUMENTS

Follow these steps exactly. Do NOT skip any — they are all required for a complete, testable intent.

## Step 1 — Define the intent

Answer these before touching code:
- Intent name (snake_case, e.g. `maintenance_request`)
- What user phrases trigger it? (e.g. "book room", "report broken light")
- Which graph nodes does it need? (sparql? sql? new node?)
- What does the response look like?

## Step 2 — Add to dialogue agent prompt

File: `orchestrator/agents/dialogue_agent.py`
Line: ~362 (the 14-intent list in `_build_intent_detection_prompt`)

Add one line to the intent list:
```
   - "maintenance_request": User reports a broken item or requests maintenance.
```

## Step 3 — Add routing branch

File: `orchestrator/workflow.py`
Function: `_route_from_dialogue()` at line 1079

Add an elif branch:
```python
elif intent == "maintenance_request":
    return "response"   # or "sparql" if data needed
```

## Step 4 — Register node (if new node needed)

File: `orchestrator/workflow.py` at line ~131

```python
workflow.add_node("maintenance", self._safe_node(self._maintenance_node, "maintenance"))
workflow.add_edge("maintenance", "response")
```

## Step 5 — Implement node function

```python
async def _maintenance_node(self, state: ConversationState) -> ConversationState:
    """Handle maintenance request intent."""
    state.intermediate_results["maintenance_result"] = {
        "acknowledged": True,
        "message": "Maintenance request logged."
    }
    return state
```

## Step 6 — Write the test first (TDD)

File: `tests/test_workflow_wiring.py`

```python
def test_workflow_routes_maintenance_request():
    content = Path("orchestrator/workflow.py").read_text(encoding="utf-8")
    assert 'elif intent == "maintenance_request"' in content
```

Run: `pytest tests/test_workflow_wiring.py -v` — confirm FAIL first, then PASS after Step 4.

## Step 7 — Commit

```bash
git add orchestrator/agents/dialogue_agent.py orchestrator/workflow.py tests/
git commit -m "feat: add maintenance_request intent end-to-end"
```
```

- [ ] **Step 3: Create /test command**

File: `.claude/commands/test.md`

```markdown
# OntoSage Test Runner

Running tests for: $ARGUMENTS

## Quick Unit Tests (always run first)

```bash
pytest -m unit -x -v 2>&1 | tail -40
```

If any fail — stop and fix before proceeding. Unit tests must always be green.

## Coverage Report

```bash
pytest -m unit --cov=orchestrator --cov-report=term-missing 2>&1 | grep -E "FAIL|ERROR|PASS|orchestrator" | tail -50
```

Look for lines with low coverage (< 70%). Priority gaps:
- `orchestrator/workflow.py` — routing functions
- `orchestrator/services/disambiguation_service.py` — new, zero coverage
- `orchestrator/services/circuit_breaker.py` — state transitions
- `orchestrator/auth_manager.py` — SHA-256→Argon2id migration path

## Integration Tests (requires running services)

```bash
docker-compose ps    # confirm all services healthy first
pytest -m integration -v 2>&1 | tail -40
```

## Specific Test File

```bash
pytest tests/$ARGUMENTS -v 2>&1 | tail -40
```

## Fix Failing Tests Protocol

1. Read the full error traceback — identify the exact assertion that failed
2. Check if it's a stale mock (mock returns wrong type/value)
3. Check if a model field was renamed in `shared/models.py`
4. Fix the test OR the implementation — never comment out a failing test
5. Re-run to confirm green
```

- [ ] **Step 4: Create /new-building command**

File: `.claude/commands/new-building.md`

```markdown
# Onboard New Building to OntoSage

Building: $ARGUMENTS

Follow every step. Each has a verification gate — do not proceed past a failing gate.

## Step 1 — Validate TTL file

```bash
python -c "
import rdflib
g = rdflib.Graph()
g.parse('input/$ARGUMENTS.ttl', format='turtle')
print(f'Triples: {len(g)}, Valid: OK')
"
```

Expected: `Triples: NNNN, Valid: OK`. If error: fix TTL syntax before continuing.

## Step 2 — Run onboarding script

```bash
python scripts/onboard_building.py --building-id $ARGUMENTS --non-interactive
```

Expected: `Onboarding complete` with no errors.

## Step 3 — Verify GraphDB loaded

```bash
curl -s -X POST http://localhost:7200/repositories/ontosage/sparql \
  -H "Content-Type: application/sparql-query" \
  -d "SELECT (COUNT(*) as ?n) WHERE { ?s ?p ?o }" | python -m json.tool
```

Expected: `?n` > 0.

## Step 4 — Run ontology detection

```bash
python -c "
import asyncio
from orchestrator.services.ontology_detector import OntologySchemaDetector
d = OntologySchemaDetector()
r = asyncio.run(d.detect_from_graphdb('http://localhost:7200', 'ontosage'))
print(r.to_dict())
"
```

Expected: `class_count > 0`, `schema` identified as `brick` or `bacnet`.

## Step 5 — Test with sample queries

Start the stack: `docker-compose up -d`

Test via curl or the WebSocket:
```bash
curl -s -X POST http://localhost:8000/chat \
  -H "Content-Type: application/json" \
  -d '{"message": "What sensors are available?", "session_id": "test-onboard"}'
```

Expected: Response lists sensor types found in the TTL.

## Step 6 — Register in adapter registry (if new DB backend)

File: `orchestrator/services/adapters/registry.py`

Add building ID → adapter mapping if the building uses a different database than the default.

## Step 7 — Set building env var

In `.env`:
```
BUILDING_ID=$ARGUMENTS
```

Restart: `docker-compose up -d orchestrator`
```

- [ ] **Step 5: Create /deploy-check command**

File: `.claude/commands/deploy-check.md`

```markdown
# OntoSage Pre-Deployment Checklist

Running production readiness check for: $ARGUMENTS

Work through every item. Do not mark the deployment ready until ALL pass.

## Security Gates

```bash
# 1. Confirm .env not in git
git status | grep -E "\.env$" && echo "FAIL: .env is tracked" || echo "PASS: .env not tracked"

# 2. No hardcoded secrets
grep -rn --include="*.py" "sk-\|api_key.*=.*['\"][a-zA-Z0-9]" orchestrator/ shared/ && echo "FAIL" || echo "PASS: no hardcoded secrets"

# 3. CORS not wildcard
grep -n "allow_origins" orchestrator/main.py
# Should NOT be: allow_origins=["*"]

# 4. Session TTL check
grep -n "7.*day\|604800\|TTL" orchestrator/auth_manager.py | head -5
```

## Service Health Gates

```bash
# All services running
docker-compose ps

# Health endpoints
curl -sf http://localhost:8000/health && echo "PASS: orchestrator" || echo "FAIL: orchestrator"
curl -sf http://localhost:8001/health && echo "PASS: rag-service" || echo "FAIL: rag-service"
curl -sf http://localhost:8002/health && echo "PASS: code-executor" || echo "FAIL: code-executor"
```

## Data Gates

```bash
# GraphDB has triples
curl -s -X POST http://localhost:7200/repositories/ontosage/sparql \
  -H "Content-Type: application/sparql-query" \
  -d "SELECT (COUNT(*) as ?n) WHERE { ?s ?p ?o }" | python -m json.tool

# Redis reachable
docker exec redis redis-cli ping
```

## Test Gate

```bash
pytest -m unit -x -q 2>&1 | tail -10
# Must show: N passed, 0 failed
```

## Final Checklist (manual)

- [ ] `.env` has correct `BUILDING_ID`
- [ ] `MODEL_PROVIDER` is set correctly (`local` or `openai`)
- [ ] OpenAI key set if `MODEL_PROVIDER=openai`
- [ ] Ollama model pulled if `MODEL_PROVIDER=local`: `docker exec ollama ollama list`
- [ ] Log level = INFO (not DEBUG) in production
- [ ] Backup of GraphDB data taken before deploy
- [ ] Stakeholders notified of maintenance window

**If all gates pass:** Deployment is approved. Run `docker-compose up -d` on target server.
```

- [ ] **Step 6: Create /audit command**

File: `.claude/commands/audit.md`

```markdown
# OntoSage Security + Code Quality Audit

Auditing: $ARGUMENTS

## Phase 1 — Automated Scans

```bash
# Security scan
bandit -r orchestrator/ shared/ -ll --exclude orchestrator/tests 2>&1 | tail -30

# Dependency vulnerabilities
pip-audit --requirement orchestrator/requirements.txt 2>&1 | tail -20

# Format compliance
black --check --line-length 100 orchestrator/ shared/ 2>&1 | tail -20

# Import order
isort --check-only --profile black orchestrator/ tests/ 2>&1 | tail -10

# Static analysis
flake8 orchestrator/ shared/ --max-line-length 110 --extend-ignore=E203,E501,W503 2>&1 | tail -20
```

## Phase 2 — Auth & Session Audit

Review these manually:
- `orchestrator/auth_manager.py:38` — Is Argon2id the active hasher?
- `orchestrator/auth_manager.py:151` — Does `register_user` validate password strength?
- `orchestrator/auth_manager.py:373` — Does `validate_session` check token expiry?
- `orchestrator/middleware/rbac.py:302` — Is `require_permission()` used on ALL data endpoints?

## Phase 3 — Input Validation Audit

```bash
# Find endpoints without input validation
grep -n "def .*endpoint\|@app\.\(get\|post\|put\|delete\)" orchestrator/main.py | head -30
```

For each endpoint: confirm Pydantic model validates input. No raw `request.json()` without schema.

## Phase 4 — Invoke Security Auditor Skill

Use the `security-auditor` skill for a comprehensive DevSecOps review covering:
- OWASP Top 10 for the API surface
- Secrets management
- Dependency chain risks
- WebSocket security

## Phase 5 — Code Quality Review

Use the `superpowers:requesting-code-review` skill for a final code review against:
- State immutability in LangGraph nodes
- `_safe_node` wrapper usage
- Error isolation (no bare `except:`)
- Test coverage for changed files
```

- [ ] **Step 7: Commit all commands**

```bash
git add .claude/commands/
git commit -m "feat: add 6 slash commands (debug, add-intent, test, new-building, deploy-check, audit)"
```

---

## Task 8: Create Rules Files

**Files:**
- Create: `.claude/rules/python-style.md`
- Create: `.claude/rules/agent-patterns.md`
- Create: `.claude/rules/sparql-patterns.md`
- Create: `.claude/rules/api-contracts.md`

- [ ] **Step 1: Create python-style.md**

File: `.claude/rules/python-style.md`

```markdown
# Python Style Rules — OntoSage

These rules apply to ALL Python files in `orchestrator/`, `shared/`, `scripts/`, and `tests/`.

## Formatting

- Line length: **100 characters** (black default override)
- Formatter: `black --line-length 100`
- Import sorting: `isort --profile black`
- Run before every commit: `black --line-length 100 <file> && isort --profile black <file>`

## Static Analysis

- `flake8 --max-line-length 110 --extend-ignore=E203,E501,W503`
- `bandit -ll` — no high/medium severity issues
- `__init__.py` may have unused imports (F401 ignored by convention)

## Type Hints

- All new functions must have type hints on parameters and return values
- Use `Optional[X]` not `X | None` (Python 3.9 compatibility)
- Use `Dict`, `List`, `Tuple` from `typing` (not built-in generics)

## Async

- All agent node functions are `async def`
- Never block the event loop: no `time.sleep()`, no synchronous DB calls inside async functions
- Use `await asyncio.sleep()` for delays
- Wrap blocking I/O in `asyncio.get_event_loop().run_in_executor()`

## Logging

- Use `from shared.utils import get_logger; logger = get_logger(__name__)`
- Never use `print()` in production code
- Log levels: `DEBUG` for trace, `INFO` for state changes, `WARNING` for recoverable errors, `ERROR` for failures
- Never log passwords, session tokens, or API keys

## Error Handling

- No bare `except:` — always `except SpecificException as e:`
- Log the exception with `logger.error(..., exc_info=True)` before re-raising or returning error state
- Return error state rather than raising inside LangGraph nodes (the `_safe_node` wrapper handles exceptions)
```

- [ ] **Step 2: Create agent-patterns.md**

File: `.claude/rules/agent-patterns.md`

```markdown
# LangGraph Agent Node Patterns — OntoSage

These patterns MUST be followed for every new agent node.

## 1. Always Use the _safe_node Wrapper

NEVER register a node function directly:
```python
# WRONG
workflow.add_node("my_node", self._my_node_fn)

# CORRECT
workflow.add_node("my_node", self._safe_node(self._my_node_fn, "my_node"))
```

The `_safe_node` wrapper at `workflow.py:191` catches exceptions, logs them, and returns the state with an error key so the pipeline continues gracefully instead of crashing.

## 2. Node Function Signature

```python
async def _my_node_fn(self, state: ConversationState) -> ConversationState:
    """One-line description of what this node does."""
    logger.info(f"[my_node] intent={state.intent}")
    # ... do work ...
    state.intermediate_results["my_result"] = result
    return state
```

- Always `async def`
- Always returns `ConversationState` (the same object, mutated)
- Always log entry with intent for debuggability

## 3. State Mutation Rules

- Write results to `state.intermediate_results["your_key"]` — never overwrite other agents' keys
- Read previous results from `state.intermediate_results.get("sparql_results", [])` with a default
- Never store sensitive data (passwords, tokens) in state — it persists in Redis

## 4. Error Handling Inside Nodes

```python
async def _my_node_fn(self, state: ConversationState) -> ConversationState:
    try:
        result = await some_service_call()
        state.intermediate_results["my_result"] = result
    except TimeoutError:
        logger.warning("[my_node] Timed out — returning empty result")
        state.intermediate_results["my_result"] = {}
        state.intermediate_results["error"] = "my_node: timeout"
    return state
```

Do not raise from inside a node — set the error key and return. The `_safe_node` wrapper is the last line of defense but should not be relied upon as primary error handling.

## 5. Adding a New Node — Required Steps

1. Implement `async def _my_node_fn(self, state) -> ConversationState` in `WorkflowOrchestrator`
2. Register: `workflow.add_node("my_node", self._safe_node(self._my_node_fn, "my_node"))` at line ~131
3. Add edge: `workflow.add_edge("my_node", "response")` at line ~186
4. Add routing branch in `_route_from_dialogue()` at line ~1079
5. Write a test in `tests/test_workflow_wiring.py` that checks the routing exists

## 6. Routing Functions

```python
def _route_from_dialogue(self, state: ConversationState) -> str:
    intent = state.intermediate_results.get("intent", "general")
    if intent == "my_intent":
        return "my_node"   # must match the add_node() name exactly
    # ... other branches ...
    return "response"  # default fallback
```

Return values MUST exactly match registered node names — a typo silently routes to a non-existent node.
```

- [ ] **Step 3: Create sparql-patterns.md**

File: `.claude/rules/sparql-patterns.md`

```markdown
# SPARQL Query Patterns — OntoSage

These patterns apply when writing or reviewing SPARQL queries for the OntoSage building knowledge graph.

## Always Include These Prefixes

```sparql
PREFIX rdf:   <http://www.w3.org/1999/02/22-rdf-syntax-ns#>
PREFIX rdfs:  <http://www.w3.org/2000/01/rdf-schema#>
PREFIX brick: <https://brickschema.org/schema/Brick#>
PREFIX bacnet: <http://data.ashrae.org/bacnet/#>
PREFIX xsd:   <http://www.w3.org/2001/XMLSchema#>
```

## Pattern: Discover Sensors of a Type

```sparql
SELECT ?sensor ?label WHERE {
    ?sensor a brick:Temperature_Sensor .
    OPTIONAL { ?sensor rdfs:label ?label }
} LIMIT 50
```

## Pattern: Find Sensors in a Zone/Room

```sparql
SELECT ?sensor ?zone WHERE {
    ?sensor a brick:Temperature_Sensor .
    ?sensor brick:isPartOf ?zone .
    ?zone a brick:HVAC_Zone .
} LIMIT 50
```

## Pattern: Get UUID/ID for Time-Series Lookup

```sparql
SELECT ?uuid WHERE {
    ?sensor rdfs:label "Zone 3 Temperature" .
    ?sensor brick:hasExternalReference ?ref .
    ?ref brick:hasTimeseriesId ?uuid .
} LIMIT 1
```

## Pattern: Discover All Available Classes

```sparql
SELECT DISTINCT ?class (COUNT(?inst) as ?count) WHERE {
    ?inst a ?class .
    FILTER(STRSTARTS(STR(?class), "https://brickschema.org/"))
} GROUP BY ?class ORDER BY DESC(?count) LIMIT 30
```

## Rules

- Always use `LIMIT` — never unbounded queries against a large graph
- Use `OPTIONAL` for properties that may not exist on all instances
- Prefer `rdfs:label` over URI parsing for human-readable names
- Fall back to semantic RAG (`services/hybrid_retrieval.py`) when SPARQL returns empty results
- Validate syntax with `services/sparql_validator.py` before executing

## GraphDB Endpoint

```
SPARQL Query: POST http://graphdb:7200/repositories/ontosage/sparql
Content-Type: application/sparql-query
Accept: application/sparql-results+json
```
```

- [ ] **Step 4: Create api-contracts.md**

File: `.claude/rules/api-contracts.md`

```markdown
# FastAPI Endpoint Patterns — OntoSage

These patterns MUST be followed for all new endpoints in `orchestrator/main.py`.

## Response Format

All endpoints return this envelope:

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
    "message": "Human-readable error",
    "trace_id": request.state.trace_id,
}, status_code=400)
```

## RBAC Protection

Every data endpoint MUST use `require_permission()`:

```python
from orchestrator.middleware.rbac import create_rbac_dependency

# In endpoint definition
@app.get("/api/v1/sensors")
async def get_sensors(
    user: UserContext = Depends(create_rbac_dependency(token_manager, "sensor:read"))
):
    ...
```

Available permissions: `sensor:read`, `analytics:read`, `metadata:read`, `report:read`,
`export:read`, `anomaly:read`, `trend:read`, `compliance:read`, `comparison:read`,
`config:read`, `config:write`, `user:read`, `user:write`, `user:delete`,
`building:read`, `building:write`, `building:delete`, `system:admin`, `system:health`

## Input Validation

Always use a Pydantic model for request bodies — never accept raw dict:

```python
from pydantic import BaseModel, Field

class ChatRequest(BaseModel):
    message: str = Field(..., min_length=1, max_length=2000)
    session_id: str = Field(..., min_length=1)
    building_id: Optional[str] = None

@app.post("/chat")
async def chat(req: ChatRequest, ...):
    ...
```

## WebSocket Pattern

```python
@app.websocket("/ws/{session_id}")
async def websocket_endpoint(websocket: WebSocket, session_id: str):
    await websocket.accept()
    try:
        while True:
            data = await websocket.receive_json()
            # validate, process, send
            await websocket.send_json({"type": "response", "data": ...})
    except WebSocketDisconnect:
        logger.info(f"WebSocket disconnected: {session_id}")
    except Exception as e:
        logger.error(f"WebSocket error: {e}", exc_info=True)
        await websocket.close(code=1011)
```

## Trace ID

All endpoints have `request.state.trace_id` injected by middleware. Always include it in responses and logs:

```python
logger.info(f"[{request.state.trace_id}] Processing chat: session={session_id}")
```
```

- [ ] **Step 5: Commit all rules**

```bash
git add .claude/rules/
git commit -m "feat: add 4 rules files (python-style, agent-patterns, sparql-patterns, api-contracts)"
```

---

## Task 9: Create Project Skills

**Files:**
- Create: `.claude/skills/ontosage-onboarding.md`
- Create: `.claude/skills/ontosage-debug.md`

- [ ] **Step 1: Create ontosage-onboarding skill**

File: `.claude/skills/ontosage-onboarding.md`

```markdown
---
name: ontosage-onboarding
description: Use when configuring a new building instance of OntoSage — covers TTL validation, GraphDB loading, ontology detection, and end-to-end query verification.
---

# OntoSage New Building Onboarding

You are configuring OntoSage for a new building. This is a complete, ordered process — every step has a verification gate.

## Pre-conditions

- Docker stack is running: `docker-compose ps`
- TTL file for the building is available in `input/`
- Building ID decided (e.g. `bldg2`, `office_a`)

## Step 1: Validate the TTL File

```bash
python -c "
import rdflib, sys
g = rdflib.Graph()
try:
    g.parse(sys.argv[1], format='turtle')
    print(f'Valid TTL: {len(g)} triples')
except Exception as e:
    print(f'INVALID: {e}')
    sys.exit(1)
" input/<BUILDING_ID>.ttl
```

**Gate:** Must print `Valid TTL: NNNN triples`. Fix TTL syntax errors before proceeding.

## Step 2: Run Onboarding Script

```bash
python scripts/onboard_building.py --building-id <BUILDING_ID> --non-interactive
```

**Gate:** Script exits 0 with `Onboarding complete` message.

## Step 3: Verify GraphDB

```bash
curl -s -X POST http://localhost:7200/repositories/ontosage/sparql \
  -H "Content-Type: application/sparql-query" \
  -d "SELECT (COUNT(*) as ?n) WHERE { ?s ?p ?o }" \
  -H "Accept: application/sparql-results+json" | python -m json.tool
```

**Gate:** `?n` value > 0.

## Step 4: Discover Schema

```bash
python -c "
import asyncio
from orchestrator.services.ontology_detector import OntologySchemaDetector
d = OntologySchemaDetector()
r = asyncio.run(d.detect_from_graphdb('http://localhost:7200', 'ontosage'))
import json; print(json.dumps(r.to_dict(), indent=2))
"
```

**Gate:** `class_count > 0` and schema identified.

## Step 5: Set Building Configuration

In `.env`:
```
BUILDING_ID=<BUILDING_ID>
```

Restart orchestrator: `docker-compose up -d orchestrator`

## Step 6: Register Storage Adapter (if new DB)

File: `orchestrator/services/adapters/registry.py`

Add the building → adapter mapping for time-series data. If reusing MySQL: no change needed.

## Step 7: End-to-End Query Test

```bash
curl -s -X POST http://localhost:8000/chat \
  -H "Content-Type: application/json" \
  -d '{"message": "What sensors are available?", "session_id": "onboard-test"}' \
  | python -m json.tool
```

**Gate:** Response contains sensor types found in the TTL. If empty: check GraphDB has data (Step 3) and rag-service is running (`curl http://localhost:8001/health`).

## Common Issues

| Symptom | Fix |
|---------|-----|
| TTL parse error | Run `rapper -i turtle input/building.ttl` for detailed error |
| GraphDB empty after script | Check script logs for upload errors; try manual upload via GraphDB web UI at `http://localhost:7200` |
| Schema `unknown` | TTL may not use Brick prefixes — check with `ontology-agent` |
| Response empty/error | Check `docker-compose logs -f orchestrator` |
```

- [ ] **Step 2: Create ontosage-debug skill**

File: `.claude/skills/ontosage-debug.md`

```markdown
---
name: ontosage-debug
description: Use when an OntoSage pipeline query returns wrong or empty results — systematic root-cause methodology for the LangGraph multi-agent pipeline.
---

# OntoSage Pipeline Debug Runbook

Every pipeline failure has a layer. Find the layer first, then fix.

## The Pipeline Layers

```
User query
    ↓
[Layer 1] dialogue_agent — intent classification + entity extraction
    ↓
[Layer 2] workflow.py routing — _route_from_dialogue() conditional edges
    ↓
[Layer 3a] sparql_agent — SPARQL generation + GraphDB execution
[Layer 3b] sql_agent — time-series fetch via storage adapter
[Layer 3c] analytics_agent — code generation + code-executor (port 8002)
    ↓
[Layer 4] response node — markdown assembly
    ↓
User response
```

## Layer 1 Diagnosis: Intent Wrong

**Symptom:** Response answers a different question / routes to wrong path.

```bash
# Check dialogue agent logs
docker-compose logs orchestrator | grep "Intent:\|intent=" | tail -20
```

**Fix:** Edit `orchestrator/agents/dialogue_agent.py:_build_intent_detection_prompt()` at line ~362. Add clearer examples or adjust the intent description.

## Layer 2 Diagnosis: Wrong Node

**Symptom:** Correct intent detected but wrong data returned (e.g. SPARQL results but no time-series).

Read: `orchestrator/workflow.py:1079` — `_route_from_dialogue()`

Check: Does the routing branch for this intent send to the right next node?

## Layer 3a Diagnosis: SPARQL Empty

**Symptom:** "I don't have information about..." — but the data IS in the ontology.

```bash
# Test SPARQL directly
curl -s -X POST http://localhost:7200/repositories/ontosage/sparql \
  -H "Content-Type: application/sparql-query" \
  -d "SELECT ?s WHERE { ?s a brick:Temperature_Sensor } LIMIT 5" \
  -H "Accept: application/sparql-results+json"
```

If empty: data not loaded. Run `python scripts/onboard_building.py`.
If error: SPARQL syntax issue — check prefixes in `sparql_agent.py:_generate_sparql()`.

## Layer 3b Diagnosis: SQL Empty

**Symptom:** SPARQL found UUIDs but no time-series data returned.

```bash
docker-compose logs orchestrator | grep "sql_agent\|UUID\|adapter" | tail -20
```

Check: `orchestrator/services/adapters/registry.py` — is the building ID registered?

## Layer 3c Diagnosis: Analytics Failure

**Symptom:** Analytics returns error or empty.

```bash
curl http://localhost:8002/health
docker-compose logs code-executor | tail -20
```

The code-executor sandbox (port 8002) must be running. Check it's healthy.

## Layer 4 Diagnosis: Response Malformed

**Symptom:** Raw JSON / code in response instead of natural language.

Read: `orchestrator/workflow.py:843` — `_response_node()`

Check: Is `intermediate_results` populated with the right keys before response node runs?

## Universal First Steps

1. `docker-compose ps` — all services running?
2. `docker-compose logs -f orchestrator 2>&1 | grep ERROR | tail -20`
3. `curl http://localhost:8000/health` — orchestrator healthy?
4. Invoke `systematic-debugging` skill for structured root-cause analysis
```

- [ ] **Step 3: Commit skills**

```bash
git add .claude/skills/
git commit -m "feat: add 2 project skills (ontosage-onboarding, ontosage-debug)"
```

---

## Task 10: Fill code-reviewer.md and security-auditor.md

**Files:**
- Fill: `.claude/code-reviewer.md`
- Fill: `.claude/security-auditor.md`

- [ ] **Step 1: Write code-reviewer.md**

```markdown
# OntoSage Code Reviewer

You are reviewing code changes in the OntoSage smart building platform. Apply these criteria for every review.

## Use This Agent When

- A major feature or bug fix is complete and ready for review
- Before merging any PR that touches `workflow.py`, `main.py`, or `auth_manager.py`
- When the user says "review this", "code review", or "check my changes"

## Review Criteria

### 1. LangGraph Node Safety
- [ ] New nodes use `_safe_node` wrapper — never bare function registration
- [ ] Node functions are `async def` and return `ConversationState`
- [ ] State mutations only write to `intermediate_results` — no new top-level state fields added without updating `shared/models.py`
- [ ] No exceptions raised from inside node functions — errors set `intermediate_results["error"]`

### 2. Routing Integrity
- [ ] Every new intent has a branch in `_route_from_dialogue()`
- [ ] Return values from routing functions exactly match registered `add_node()` names
- [ ] `test_workflow_wiring.py` has a test for any new routing branch

### 3. Test Coverage
- [ ] Changed functions have corresponding unit tests
- [ ] New agent nodes have at minimum one `@pytest.mark.unit` test
- [ ] No test was commented out or deleted to make CI pass

### 4. Code Style
- [ ] `black --line-length 100` passes with no changes
- [ ] `isort --profile black` passes
- [ ] No bare `except:` clauses
- [ ] No `print()` statements — only `logger.*`

### 5. Security
- [ ] No hardcoded secrets, passwords, or API keys
- [ ] New endpoints use `require_permission()` from `middleware/rbac.py`
- [ ] New endpoints have Pydantic input validation (no raw dict parsing)

### 6. Per-Building Compatibility
- [ ] No assumption of a specific building ID hardcoded
- [ ] TTL-specific logic uses `OntologySchemaDetector` — not hardcoded class names
- [ ] Building ID always read from `settings.BUILDING_ID` or request context

## Review Output Format

```
## Code Review: <feature>

### Passed ✓
- <item>

### Issues Found ✗
- **[BLOCKING]** <description> — <file>:<line>
- **[SUGGESTION]** <description> — <file>:<line>

### Verdict
APPROVE / REQUEST CHANGES
```
```

- [ ] **Step 2: Write security-auditor.md**

```markdown
# OntoSage Security Auditor

You are a security auditor specializing in the OntoSage smart building platform. Apply the following framework.

## Use This Agent When

- Running a pre-deployment security review
- Reviewing auth, session, or RBAC changes
- Investigating a potential vulnerability report
- When the user invokes `/audit`

## Do NOT Use When

- You lack explicit scope/authorization from the building owner
- The request is to test live production systems without consent

## Audit Framework

### Authentication (auth_manager.py)

- [ ] Password hashing: Argon2id is active — check `_detect_hasher()` at line 38
- [ ] No SHA-256 hashes remain without migration path on login
- [ ] Session tokens: 32-byte random (`secrets.token_hex(32)`) — not UUIDs
- [ ] Session TTL: 7 days max in Redis (`ex=604800`)
- [ ] `validate_session()` checks token expiry — not just existence
- [ ] Password reset tokens are single-use and time-limited

### Authorization (middleware/rbac.py)

- [ ] Every data endpoint protected by `require_permission()`
- [ ] Guest/readonly users map to `readonly` role (not `occupant`)
- [ ] `system:admin` permission checked before any admin action
- [ ] Building ID in `UserContext.allowed_buildings` is enforced — users cannot access other buildings
- [ ] JWT claims validated: signature, expiry, issuer

### Input Validation (main.py endpoints)

- [ ] All POST bodies use Pydantic models with `Field(min_length=1, max_length=N)`
- [ ] Path parameters sanitized (no path traversal: `../`)
- [ ] WebSocket messages validated before processing
- [ ] SPARQL injection: user input never interpolated directly into SPARQL strings — LLM generates the query, user provides only natural language

### Secrets Management

- [ ] `.env` in `.gitignore` — `git ls-files .env` returns empty
- [ ] No secrets in `docker-compose.yml` hardcoded values
- [ ] API keys loaded via `os.environ` or `shared/config.py` — never literals
- [ ] Logs do not contain: passwords, session tokens, API keys

### Network / Infrastructure

- [ ] GraphDB (7200), Redis (6379), MySQL (3306) NOT exposed to public internet — internal Docker network only
- [ ] Orchestrator (8000) is the only public-facing port
- [ ] CORS: `allow_origins` is a specific list, not `["*"]`
- [ ] HTTPS enforced in production (reverse proxy / TLS termination)

### Code Execution Sandbox (code-executor port 8002)

- [ ] Analytics code runs in isolated Docker container — not in orchestrator process
- [ ] No file system access to host from sandbox
- [ ] Timeout enforced on code execution
- [ ] No ability to import `os`, `subprocess`, `socket` from analytics code

## Audit Report Format

```
## Security Audit: OntoSage — <date>

### Critical (must fix before deploy)
- <finding> — <file>:<line> — <remediation>

### High
- <finding> — <remediation>

### Medium / Low
- <finding> — <remediation>

### Passed
- <item>

### Overall Risk: LOW / MEDIUM / HIGH / CRITICAL
```
```

- [ ] **Step 3: Commit**

```bash
git add .claude/code-reviewer.md .claude/security-auditor.md
git commit -m "feat: fill code-reviewer and security-auditor with OntoSage-specific criteria"
```

---

## Task 11: Update settings.local.json with Hooks

**Files:**
- Modify: `.claude/settings.local.json`

- [ ] **Step 1: Update settings with PostToolUse hooks**

Replace the contents of `.claude/settings.local.json` with:

```json
{
  "permissions": {
    "allow": [
      "Read",
      "Write",
      "Edit",
      "MultiEdit",
      "Bash(*)",
      "Grep",
      "Glob",
      "WebFetch",
      "WebSearch",
      "NotebookRead",
      "NotebookEdit",
      "TodoRead",
      "TodoWrite"
    ]
  },
  "hooks": {
    "PostToolUse": [
      {
        "matcher": "Edit|Write|MultiEdit",
        "hooks": [
          {
            "type": "command",
            "command": "bash -c 'FILE=$(echo $CLAUDE_TOOL_INPUT | python -c \"import sys,json; d=json.load(sys.stdin); print(d.get(\\\"file_path\\\", d.get(\\\"path\\\", \\\"\\\")))\" 2>/dev/null); [[ \"$FILE\" == *.py ]] && cd /c/Users/suhas/Documents/GitHub/OntoSage && python -m black --check --line-length 100 \"$FILE\" 2>&1 | head -5 || true'"
          }
        ]
      }
    ],
    "PreToolUse": [
      {
        "matcher": "Bash",
        "hooks": [
          {
            "type": "command",
            "command": "bash -c 'CMD=$(echo $CLAUDE_TOOL_INPUT | python -c \"import sys,json; print(json.load(sys.stdin).get(\\\"command\\\", \\\"\\\"))\" 2>/dev/null); [[ \"$CMD\" == *\"rm -rf\"* || \"$CMD\" == *\"drop table\"* || \"$CMD\" == *\"--force\"* ]] && echo \"WARNING: Destructive command detected: $CMD\" || true'"
          }
        ]
      }
    ]
  },
  "model": "claude-sonnet-4-6",
  "env": {
    "PROJECT_ROOT": "/c/Users/suhas/Documents/GitHub/OntoSage"
  }
}
```

- [ ] **Step 2: Verify JSON is valid**

```bash
python -m json.tool .claude/settings.local.json > /dev/null && echo "Valid JSON" || echo "INVALID JSON"
```

Expected: `Valid JSON`

- [ ] **Step 3: Commit**

```bash
git add .claude/settings.local.json
git commit -m "feat: add PostToolUse black check and PreToolUse destructive command warning hooks"
```

---

## Task 12: Final Verification

- [ ] **Step 1: Verify all files exist**

```bash
echo "=== Agents ===" && ls .claude/agents/
echo "=== Commands ===" && ls .claude/commands/
echo "=== Rules ===" && ls .claude/rules/
echo "=== Skills ===" && ls .claude/skills/
echo "=== Root ===" && ls .claude/code-reviewer.md .claude/security-auditor.md .claude/settings.local.json
```

Expected output:
```
=== Agents ===
deploy-agent.md  infra-agent.md  ontology-agent.md  pipeline-agent.md  test-agent.md
=== Commands ===
add-intent.md  audit.md  debug.md  deploy-check.md  new-building.md  test.md
=== Rules ===
agent-patterns.md  api-contracts.md  python-style.md  sparql-patterns.md
=== Skills ===
ontosage-debug.md  ontosage-onboarding.md
=== Root ===
.claude/code-reviewer.md  .claude/security-auditor.md  .claude/settings.local.json
```

- [ ] **Step 2: Verify CLAUDE.md updated**

```bash
grep -c "Quick Navigation" CLAUDE.md && grep -c "Skills Guide\|Installed Skills" CLAUDE.md
```

Expected: Both print `1`.

- [ ] **Step 3: Run unit tests to confirm nothing broken**

```bash
pytest -m unit -x -q 2>&1 | tail -10
```

Expected: All pass, 0 failed.

- [ ] **Step 4: Final commit**

```bash
git add .
git commit -m "chore: complete .claude/ configuration — agents, commands, rules, skills, hooks"
```
