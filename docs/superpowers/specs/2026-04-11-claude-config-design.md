# .claude/ Configuration Design — OntoSage
**Date:** 2026-04-11  
**Approach:** C — Layered Context Compression + Targeted Agents  
**Goal:** Token-efficient Claude Code sessions, specialized sub-agents, automated quality gates, and skill-powered workflows for a per-building conversational AI system.

---

## Problem Statement

OntoSage has 4,700+ lines across 5 core files, 11 agents, 20+ services, and 6 storage backends. Every Claude Code session burns tokens re-deriving architecture before doing any real work. The `.claude/` directory is empty. Users span guests → experts, and the system must be deploy-ready.

---

## Design: Three Layers

### Layer 1 — Token-Efficient CLAUDE.md (Quick Navigation Index)

Add a **compressed Quick Navigation section** to the existing CLAUDE.md so any session can jump directly to the right file:line without scanning entire files.

```
Task                          → File:Lines
Intent routing debug          → workflow.py:1079-1130 (_route_from_dialogue)
Add new graph node            → workflow.py:120-135 (add_node), 137-190 (edges)
SPARQL generation failure     → sparql_agent.py:165-260 (generate_query)
Ontology / TTL issues         → services/ontology_detector.py:154-250
SQL/time-series failures      → sql_agent.py, services/adapters/registry.py
Analytics code execution      → analytics_agent.py, services/analytics_engine.py
Auth / session issues         → auth_manager.py:61-420
RBAC / permissions            → middleware/rbac.py
Config / env vars             → shared/config.py
Response formatting           → workflow.py:843 (_response_node)
RAG / semantic fallback       → rag-service/, services/hybrid_retrieval.py
Docker / infra issues         → docker-compose.yml, orchestrator/Dockerfile
```

Also add: installed skills reference, per-task skill invocation guide.

---

### Layer 2 — Five Focused Sub-Agents

Each agent is scoped to one domain. When spawned, it only reads the files it needs — preventing full-codebase token burn.

#### `ontology-agent`
- **Trigger:** SPARQL failures, TTL parsing, GraphDB issues, new building onboarding, RDF/Brick/BACnet questions
- **Scoped files:** `sparql_agent.py`, `services/ontology_detector.py`, `services/ontology_introspector.py`, `services/ontology_validator.py`, `services/sparql_validator.py`, `services/hybrid_retrieval.py`, `rag-service/`
- **Capabilities:** Write/debug SPARQL, interpret TTL, design ontology patterns, fix GraphDB connectivity

#### `pipeline-agent`
- **Trigger:** Wrong routing, intent misclassification, state not propagating, new intent/node needed
- **Scoped files:** `workflow.py` (nodes:120-135, routing:1079-1373), `agents/dialogue_agent.py`, `shared/models.py`
- **Capabilities:** Debug LangGraph routing, add graph nodes, trace `intermediate_results` state, fix conditional edges

#### `infra-agent`
- **Trigger:** Docker service failures, port conflicts, env var issues, secrets management, startup errors
- **Scoped files:** `docker-compose.yml`, `orchestrator/Dockerfile`, `rag-service/Dockerfile`, `.env.example`, `shared/config.py`
- **Capabilities:** Fix service networking, configure MODEL_PROVIDER switching, manage volumes, diagnose startup

#### `test-agent`
- **Trigger:** Writing new tests, fixing failing tests, coverage gaps, adding fixtures
- **Scoped files:** `tests/`, `tests/conftest.py`, `tests/agents/`, `tests/services/`
- **Capabilities:** Write pytest tests with correct markers (unit/integration/slow/live), fix fixtures, identify gaps

#### `deploy-agent`
- **Trigger:** Pre-deployment review, production hardening, security audit, health check failures
- **Scoped files:** `main.py` (health:startup sections), `services/circuit_breaker.py`, `auth_manager.py`, `middleware/rbac.py`, `services/logging_context.py`
- **Capabilities:** Production checklist, harden endpoints, verify circuit breakers, audit auth flow

---

### Layer 3 — Slash Commands + Rules + Hooks

#### Commands (`.claude/commands/`)

| Command | Purpose |
|---------|---------|
| `/debug` | Systematic pipeline debug — loads symptoms → traces route → identifies node |
| `/add-intent` | End-to-end guide: dialogue → routing → agent node → test |
| `/test` | Smart test run with coverage gap report |
| `/new-building` | Onboard a new building TTL: validate → load GraphDB → verify queries |
| `/deploy-check` | Pre-deployment production readiness checklist |
| `/audit` | Security + code quality audit (invokes security-auditor skill) |

#### Rules (`.claude/rules/`)

| Rule file | Enforces |
|-----------|---------|
| `python-style.md` | black (len=100), isort (black profile), flake8 (max=110), bandit |
| `agent-patterns.md` | `_safe_node` wrapper required, state mutation via copy, error isolation |
| `sparql-patterns.md` | Brick/BACnet namespace prefixes, fallback chain, query structure |
| `api-contracts.md` | FastAPI response format, RBAC decorator, WebSocket protocol |

#### Hooks (`settings.local.json`)

- **PostToolUse (Edit/Write):** Run `black --check` on edited Python files — surfaces formatting violations immediately
- **PostToolUse (Edit to test files):** Run `pytest -m unit -x` fast feedback loop

#### Filled Agent Definition Files
- `.claude/code-reviewer.md` — OntoSage-specific review criteria (state immutability, node safety, test coverage)
- `.claude/security-auditor.md` — Auth, RBAC, session tokens, secret management, input validation

#### Project Skills (`.claude/skills/`)
- `ontosage-onboarding.md` — How to configure a new building instance (TTL → GraphDB → test)
- `ontosage-debug.md` — OntoSage-specific debugging runbook for pipeline failures

---

## File Inventory (20 files)

```
CLAUDE.md                          (update — add Quick Nav + Skills Guide)
.claude/agents/ontology-agent.md   (new)
.claude/agents/pipeline-agent.md   (new)
.claude/agents/infra-agent.md      (new)
.claude/agents/test-agent.md       (new)
.claude/agents/deploy-agent.md     (new)
.claude/commands/debug.md          (new)
.claude/commands/add-intent.md     (new)
.claude/commands/test.md           (new)
.claude/commands/new-building.md   (new)
.claude/commands/deploy-check.md   (new)
.claude/commands/audit.md          (new)
.claude/rules/python-style.md      (new)
.claude/rules/agent-patterns.md    (new)
.claude/rules/sparql-patterns.md   (new)
.claude/rules/api-contracts.md     (new)
.claude/skills/ontosage-onboarding.md (new)
.claude/skills/ontosage-debug.md   (new)
.claude/code-reviewer.md           (fill — was blank)
.claude/security-auditor.md        (fill — was blank)
.claude/settings.local.json        (update — add hooks)
```

---

## Success Criteria

- Any session can navigate to the right code area in ≤2 file reads
- Five sub-agents cover 100% of OntoSage task types without loading the full codebase
- `/debug`, `/add-intent`, `/new-building` commands reduce repetitive prompt overhead to zero
- Formatting violations surface immediately after every edit (hook)
- A guest can ask "how warm is room 3?" and get a natural answer; an engineer can run SPARQL directly — both paths work and are testable
