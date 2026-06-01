# OntoSage — Agentic AI for Smart Buildings

**Ask your building anything in plain English. Get sensor-grounded, persona-aware, multi-intent answers.**

[![Python](https://img.shields.io/badge/python-3.10%20|%203.11%20|%203.12-blue.svg)](https://www.python.org/)
[![FastAPI](https://img.shields.io/badge/FastAPI-0.115-009688.svg)](https://fastapi.tiangolo.com/)
[![LangGraph](https://img.shields.io/badge/LangGraph-0.2-7C3AED.svg)](https://langchain-ai.github.io/langgraph/)
[![Brick Schema](https://img.shields.io/badge/Brick_Schema-1.3-orange.svg)](https://brickschema.org/)
[![License: MIT](https://img.shields.io/badge/License-MIT-yellow.svg)](https://opensource.org/licenses/MIT)
[![CI](https://github.com/suhasdevmane/OntoSage/actions/workflows/ci.yml/badge.svg)](https://github.com/suhasdevmane/OntoSage/actions/workflows/ci.yml)
[![Tests](https://img.shields.io/badge/tests-225%20passing-brightgreen.svg)](#run-the-tests)

---

A facility manager opens the chat and asks: *"Show me floor 3 layout and also tell me how many rooms are there."*

OntoSage decomposes it into two sub-intents (`floor_plan` + `spatial_query`), routes each to the right agent, and returns both the floor map PDF and the room count in one response. Behind the scenes, it ran two LLM calls, validated the user's session, blended their stacked personas (`facility_manager` + `sustainability_officer`), consulted the building's Brick ontology + MySQL time-series + DWG geometry, and wrote a complete routing audit trail to Redis.

No SQL, no SPARQL, no schema knowledge required from the user.

> **Full technical reference:** see [ONTOSAGE.md](./ONTOSAGE.md) — architecture, all 22 intents, multi-tenant / multi-persona / multi-intent model, the Phase 11-18 changelog, test coverage, and known issues.

---

## Latest live-survey baseline (Phase 18 + libredwg, 2026-05-30)

```
RESULTS: 94/95 PASS  ·  1 WARN  ·  0 FAIL  (99% clean pass)
Latency: avg 16.7s · median 9.2s · max 71.2s
```

Floor Plan/Spatial category is now 4/4 (was 3/4 in every prior baseline) thanks to the libredwg source build delivering real DWG geometry — the orchestrator now answers *"What is the total area of floor 1?"* with a full markdown table covering all 6 floors and a **20,370.2 m²** building total. Deterministic unit suite: **225 tests pass / 3 skip / 0 fail** on Python 3.12.

---

## What's new (Phase 11-19)

| Capability | What it does | Phase |
|---|---|---|
| **Unified user-report intake** | Any persona reports a fault, complaint, safety hazard, feedback, or suggestion in plain English. Auto-classified + prioritised (gas/fire → URGENT, broken → HIGH), persona-stamped, stored in the `user_reports` Postgres table, acknowledged with a tracking ID. Admins triage in pgAdmin via auto-created views (`v_urgent_reports`, `v_reports_by_persona`, …) | **19** |

### Earlier (Phase 11-18)

| Capability | What it does | Phase |
|---|---|---|
| **DWG geometry pipeline live** | `libredwg 0.13.3` built from source in a multi-stage Dockerfile. The orchestrator now ingests all `.dwg` files at startup and the `spatial_query` agent returns room areas, polygons, floor totals from real CAD data | **18 (libredwg)** |
| **PDF backend swapped to weasyprint** | `wkhtmltopdf` was removed from Debian trixie (dead upstream, unfixed CVEs); switched to Python-native weasyprint as primary, pdfkit as legacy fallback | 18 |
| **Base image CVE remediation** | All 7 Dockerfiles moved from `python:3.11-slim-bookworm` to `python:3.12-slim-trixie`. Python 3.11 itself had unfixed CVEs after Oct 2024 maintenance end; the bump to 3.12 + Debian 13 clears the IDE-flagged critical+13 high vulns | 18 |
| **Auth fails closed honestly** | When Postgres is unreachable mid-request, `/auth/login` now returns *"Authentication service is temporarily unavailable"* instead of misleading *"Invalid password"* | 18 |
| **Postgres connect retry on startup** | `lifespan` retries 5 times with 2→4→8→16→30s backoff — survives the well-known orchestrator-boots-before-Postgres race | 18 |
| **Building-swap CLI** | `python scripts/swap_building.py --to bldg2` validates TTL ↔ namespace consistency, archives the old dir, flushes the response cache, updates `.env` | 12C |
| **TTL startup validator** | Orchestrator refuses to boot if any TTL's `@prefix bldg:` doesn't match `building.yaml`'s `ontology_namespace` — no more silently-empty SPARQL | 12B |
| **Routing audit trail** | Every turn writes `state.intermediate_results["route_decision"]` with `{intent, overrides_applied, final_node, decision_source}` | 13A |
| **Auto-wired graph** | Adding a new intent is 2 steps: YAML entry + `_my_node_fn`. The graph builds itself | 13B |
| **Multi-persona blending** | Pass `personas: ["facility_manager", "researcher"]` and the registry rank-vote-merges `top_domains`, takes `max(complexity)`, `min(threshold)` | 14A |
| **Multi-intent decomposition** | "show me X and tell me Y" → planner fans out 2-5 sub-intents | 14B |
| **Multi-tenant SPARQL** | `ContextVar` threads per-request building namespace through every SPARQL helper (forward-compat for Onto-community) | 15A |
| **Persona-aware intent prompt** | LLM dialogue agent sees the blended persona's domains, complexity, clarification threshold for better classification | 16B |
| **Multi-intent threshold tuning** | Lowered from 80→50 chars; catches "show me floor 3 layout and tell me how many rooms" (55 chars) | 16A |
| **`workflow.py` package split** | 3,220-line monolith → `workflow/__init__.py` + `_orchestrator.py` + `_graph.py` + `_routing.py` via mixins; zero behavior change | 17 |

---

## Quick start

### 1. Bring the stack up

```bash
cp .env.example .env             # set OPENAI_API_KEY (or MODEL_PROVIDER=local)
docker-compose up -d              # 12 services start; wait ~90s for first boot
curl http://localhost:8000/health # should report all services healthy
```

### 2. Register a user

```bash
curl -X POST http://localhost:8000/auth/register \
  -H "Content-Type: application/json" \
  -d '{"username":"you","password":"pickone","email":"you@example.com"}'
```

### 3. Ask a question

```bash
TOKEN=$(curl -s -X POST http://localhost:8000/auth/login \
  -H "Content-Type: application/json" \
  -d '{"username":"you","password":"pickone"}' \
  | python -c "import sys,json; print(json.load(sys.stdin)['data']['session_token'])")

curl -X POST http://localhost:8000/chat \
  -H "Content-Type: application/json" -H "Authorization: $TOKEN" \
  -d '{"message":"What is the current temperature in zone 5.28?","session_id":"demo"}'
```

### 4. Try the new capabilities

**Multi-persona (blends two role priors):**
```bash
curl -X POST http://localhost:8000/chat \
  -H "Content-Type: application/json" -H "Authorization: $TOKEN" \
  -d '{
    "message": "what should I look at this week?",
    "session_id": "demo2",
    "personas": ["facility_manager", "sustainability_officer"]
  }'
```

**Multi-intent (one turn, two sub-tasks):**
```bash
curl -X POST http://localhost:8000/chat \
  -H "Content-Type: application/json" -H "Authorization: $TOKEN" \
  -d '{
    "message": "show me floor 3 layout and also tell me how many rooms are there",
    "session_id": "demo3"
  }'
```

Or use the [OpenWebUI](http://localhost:3000) chat interface that ships with the stack.

---

## Architecture at a glance

```
                       POST /chat
                            │
                            ▼
                    ┌───────────────┐
                    │   dialogue    │ ← LLM classifies intent + extracts entities
                    └───────┬───────┘     (persona priors surfaced into prompt — Phase 16B)
                            │
                            │ _route_from_dialogue (Python, audit-logged — Phase 13A)
                            ▼
   ┌───────┬────────────┬─────────┬─────────────┬───────────┬───────┬──────┐
   ▼       ▼            ▼         ▼             ▼           ▼       ▼      ▼
 sparql  capability  floor_plan spatial_q   control   maintenance export planner
   │      │           │          │           │           │           │     │
   ▼      └───────────┴──────────┴───────────┴───────────┴───────────┘     │
  sql                                                                       │
   │                                                                        │
   ▼                                                                        │
analytics ───► visualization                                                │
   │                                                                        │
   └────────────────────────────────────► response ◄────────────────────────┘
                                              │
                                              ▼
                                            client
```

Underneath:

- **GraphDB** (port 7200) — Brick/BACnet RDF (the ontology)
- **MySQL** (3306) — Time-series sensor readings
- **PostgreSQL** (5433) — User accounts + RBAC
- **Redis** (6379) — Conversation state + response cache + sessions
- **Qdrant** (6333) — Capability KB embeddings + floor-plan room vectors
- **rag-service** (8001) — Semantic fallback when SPARQL returns empty
- **code-executor** (8002) — Sandboxed Python for analytics

Full source layout and per-component detail in [ONTOSAGE.md §2](./ONTOSAGE.md#2-architecture).

---

## Add stuff via YAML — no code changes

### A new intent

Drop into `orchestrator/intents/intent_definitions.yaml`:

```yaml
- name: my_intent
  description: |-
    What this intent handles. Include trigger phrases.
  examples:
    - '"trigger query 1"'
  pipeline_group: standalone
  node_method: _my_node_fn
```

Add `_my_node_fn(self, state)` to `orchestrator/workflow/_orchestrator.py`. Restart. Done. [Details](./ONTOSAGE.md#61-add-a-new-intent).

### A new persona

```yaml
# input/<bldg>/personas/safety_officer.yaml
name: safety_officer
top_domains: [FIRE_SAFETY, OCCUPANCY, THERMAL]
default_complexity: MODERATE
clarification_threshold: 0.40
borda_topics: [Fire Safety, Occupancy, Air Quality]
aliases: [fire_officer, safety]
```

No code changes. [Details](./ONTOSAGE.md#62-add-a-new-persona).

### A new building

```bash
# 1. Drop files under input/<new>/ (building.yaml + TTLs + optional DWG/PDF/capability/personas)
# 2. Validate
python scripts/swap_building.py --to <new> --dry-run
# 3. Apply (updates .env, archives old, flushes resp_cache)
python scripts/swap_building.py --to <new> --archive
# 4. Restart
docker-compose restart orchestrator
```

The TTL validator hard-fails on `@prefix bldg:` ↔ `ontology_namespace` mismatch. [Details](./ONTOSAGE.md#63-swap-to-a-new-building).

---

## Run the tests

The CI suite (`.github/workflows/ci.yml`) runs **225 deterministic tests** across 13 files in ~20s:

```bash
pytest tests/test_phase3_4_services.py tests/test_blended_persona.py \
       tests/test_compound_query_e2e.py tests/test_intent_graph_autowire.py \
       tests/test_multi_tenant_fixture.py tests/test_routing_accuracy.py \
       tests/test_state_persistence.py tests/test_swap_building.py \
       tests/test_unregistered_intent_safety_net.py tests/test_workflow_wiring.py \
       tests/test_survey_aligned_phases.py tests/test_phase_a_fixes.py \
       tests/services/test_ttl_validator.py
```

For a live regression battery (needs the stack running):

```bash
python scripts/survey_live_test.py
# Phase 18 + libredwg baseline: 94/95 PASS · 1 WARN · 0 FAIL  (99% clean pass)
```

[Full test inventory](./ONTOSAGE.md#9-test-coverage).

---

## What this is NOT

To set expectations honestly:

- **Not multi-tenant in v1.** One building at a time. The code is forward-compatible (per-building registry caches, ContextVar-scoped SPARQL bctx, per-building Qdrant collections) for the upcoming Onto-community release, but `BUILDING_ID` selects exactly one active building today.
- **Not a building automation system.** OntoSage observes and reports. It doesn't actuate HVAC, lock doors, or override setpoints (the `control` intent politely declines and logs the attempt).
- **Not a substitute for SCADA / BMS.** It's a question-answering layer on top of your existing data. Real-time control still belongs in your BMS.
- **Not magic.** The LLM occasionally misclassifies intents (the survey hits ~92/95). The routing audit trail (Phase 13A) lets you see exactly why every query went where it did.

---

## Known issues

| Issue | Status | Workaround / fix |
|---|---|---|
| ~~Argon2 salt stored in Redis only~~ | **FIXED in Phase 18** | Audit found salt was already in Postgres; the user-visible symptom was the silent Redis fallback path which now fails closed with an honest "service unavailable" error |
| ~~Postgres connect race after Docker restart~~ | **FIXED in Phase 18** | `lifespan` retries 5 times with exponential backoff (2→4→8→16→30s) |
| ~~`dwg2dxf` missing — no DWG geometry~~ | **FIXED in Phase 18 libredwg build** | `libredwg 0.13.3` built from source in a multi-stage Dockerfile; the orchestrator now parses 6 floors at startup and the `spatial_query` agent answers area/polygon/floor-totals questions from real CAD data |
| Maintenance ticket via "report broken light" | Open (T15-S5 WARN in survey) | The maintenance agent returns "I processed your request, but couldn't generate a response" — needs a better default for the maintenance intent's nominal-create path |

[Details + proper fixes](./ONTOSAGE.md#10-known-issues).

---

## Documentation map

| Doc | Audience | Scope |
|---|---|---|
| **[README.md](./README.md)** | New users | This file — what it is, how to start, what's new |
| **[ONTOSAGE.md](./ONTOSAGE.md)** | Operators + contributors | Complete system reference — architecture, all phases, configuration, tests, known issues |
| **[CLAUDE.md](./CLAUDE.md)** | Future AI assistants | Operational rules, navigation index, debugging patterns, workflow conventions |
| **[.claude/rules/](./. claude/rules/)** | Contributors | Style + agent + API + SPARQL patterns |

---

## License

MIT. See [LICENSE](./LICENSE).

The Phase 11-17 work was developed against Cardiff University's Abacws building (`bldg1`) with `bldg2` as a multi-tenant fixture. Brick Schema is BSD-licensed.
