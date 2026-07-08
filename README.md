# OntoSage — Agentic AI for Smart Buildings

**Ask your building anything in plain English. Get sensor-grounded, persona-aware, multi-intent answers.**

[![Python](https://img.shields.io/badge/python-3.10%20|%203.11%20|%203.12-blue.svg)](https://www.python.org/)
[![FastAPI](https://img.shields.io/badge/FastAPI-0.115-009688.svg)](https://fastapi.tiangolo.com/)
[![LangGraph](https://img.shields.io/badge/LangGraph-0.2-7C3AED.svg)](https://langchain-ai.github.io/langgraph/)
[![Brick Schema](https://img.shields.io/badge/Brick_Schema-1.3-orange.svg)](https://brickschema.org/)
[![License: MIT](https://img.shields.io/badge/License-MIT-yellow.svg)](https://opensource.org/licenses/MIT)
[![CI](https://github.com/suhasdevmane/OntoSage/actions/workflows/ci.yml/badge.svg)](https://github.com/suhasdevmane/OntoSage/actions/workflows/ci.yml)
[![Tests](https://img.shields.io/badge/tests-416%20passing-brightgreen.svg)](#tests)

---

A facility manager opens the chat and asks: *"Show me floor 3 layout and also tell me how many rooms are there."*

OntoSage decomposes it into two sub-intents (`floor_plan` + `spatial_query`), routes each to the right agent, and returns both the floor map PDF and the room count in one response. Behind the scenes: two LLM calls, session validation, persona blending, Brick ontology + MySQL time-series + DWG geometry, and a complete routing audit trail written to Redis.

No SQL, no SPARQL, no schema knowledge required from the user.

Ask a follow-up — *"and what about humidity there?"* — and it remembers you meant floor 3.

> **Full technical reference:** [ONTOSAGE.md](./ONTOSAGE.md) — complete architecture, phase-by-phase changelog, all intents, multi-tenant/multi-persona model, conversation memory, forecasting pipeline, admin console, test coverage, known issues.

---

## Corpus coverage (2026-06-18, live measurement)

```
Corpus replay (240 stratified questions):   63.8% pass  (vs 16.2% baseline before V3)
Live survey (95 questions, Phase 18):       94/95 PASS  ·  1 WARN  ·  0 FAIL  (99%)
Deterministic unit suite:                   416 tests pass / 0 fail (Python 3.10/3.11/3.12)
```

Validates against the 5,604-question survey in `paper/Survey analysis and results/` — corroborates paper §6.5.

---

## How the system works

```
User question (natural language)
        │
        ▼
[Co-reference rewrite] — "and humidity there?" → "average humidity on floor 3"
        │
        ▼
Dialogue agent — LLM classifies intent + extracts entities (persona priors injected)
        │
        ▼
Python router — deterministic, audit-logged
        │
   ┌────┴────────────────────────────────────────────────────────────┐
   ▼         ▼           ▼           ▼          ▼          ▼         ▼
sparql   capability  floor_plan  spatial_q  control  maintenance  planner
   │         │                                                        │
   ▼         └──────────────────────────────────────────────┐        │
  sql                                                        │        │
   │                                                         │        │
   ▼                                                         ▼        ▼
analytics ──► visualization                              response ◄───┘
                                                              │
                                          [conversation memory saved]
                                                              ▼
                                                           client
```

Every turn: co-reference rewrite before classification; conversation persisted to Redis + Postgres after response. The routing decision (`intent, overrides_applied, final_node, decision_source`) is logged per-request.

---

## Which questions can be answered — Stakeholder Guide

The core principle: **a question is answerable when the Brick TTL describes the sensor AND the time-series data is in the database.** Without triples in GraphDB, SPARQL finds nothing. Without rows in MySQL, analytics returns empty.

### Questions answerable from Brick TTL alone (no time-series needed)

| Question | Intent | Required |
|---|---|---|
| "How many sensors are on floor 3?" | `metadata` | Brick TTL in GraphDB |
| "What types of equipment does the building have?" | `discovery` | Brick TTL |
| "What is the total floor area?" | `spatial_query` | DWG/PDF floor plans |
| "Show me floor 3 layout" | `floor_plan` | PDF/DWG file in `input/` |
| "How many rooms are adjacent to room 3.01?" | `spatial_query` | DWG geometry |
| "What zones does floor 2 have?" | `metadata` | Brick TTL |

### Questions that need time-series data in MySQL

| Question | Intent | TTL required | MySQL table |
|---|---|---|---|
| "What is the temperature in zone 5.28 right now?" | `sensor_data` | `bldg1_*.ttl` with `ref:hasTimeseriesId` | `sensor_data` (wide) |
| "What was average humidity on floor 4 last week?" | `analytics` | same | same |
| "Show CO2 trends for the past month" | `trend` | Brick TTL with UUID | `sensor_data` or `iaq_data` |
| "Predict energy consumption next week" | `trend` + forecast | Brick TTL | `energy_data` |
| "Are there unusual temperature readings today?" | `anomaly` | Brick TTL | `sensor_data` |
| "Compare floor 3 vs floor 4 energy" | `compare` | Both floor sensors in TTL | `energy_data` |
| "Plot occupancy over the last 30 days" | `visualization` | Occupancy TTL | `occupancy_data` |
| "Export IAQ data as CSV" | `export` | IAQ TTL | `iaq_data` |
| "How many people are on floor 3 right now?" | `sensor_data` | Occupancy TTL | `occupancy_data` |
| "What is the energy consumption today?" | `analytics` | Energy meter TTL | `energy_data` |
| "Is the CO2 in meeting rooms within limits?" | `compliance` | IAQ TTL + `rules.yaml` | `iaq_data` |
| "What should I check this week?" | `recommend` | Multiple sensor TTLs | multiple tables |

### Questions answered from the capability KB (no time-series needed)

| Question | Intent | Required |
|---|---|---|
| "Where is the lift?" | `capability` | `capability.yaml` or Brick TTL |
| "Is there a prayer room?" | `capability` | `capability.yaml` |
| "What are the fire evacuation procedures?" | `capability` | `documents/fire_safety.md` in document KB |
| "Is the building wheelchair accessible?" | `capability` | `capability.yaml` or `documents/` |
| "How do I book a meeting room?" | `capability` | `documents/` |

### Questions that store a report (no data needed — just saves to Postgres)

| Question | Intent | What happens |
|---|---|---|
| "The toilet is broken on floor 2" | `maintenance` | Stored in `user_reports`, tracking ID returned |
| "There is a gas smell near the lab" | `safety_report` | Prioritised URGENT, stored, triage views in pgAdmin |
| "The canteen was too cold yesterday" | `complaint` | Stored as NORMAL priority |
| "Suggestion: add more recycling bins" | `suggestion` | Stored with persona stamp |
| "The lift is making a noise" | `maintenance` | Stored as HIGH priority |

### Questions answered from external feeds (needs `feeds.yaml`)

| Question | Required feed |
|---|---|
| "What is the outside air temperature?" | `outside_weather_temp` in `feeds.yaml` |
| "Is there a meeting room available now?" | calendar feed |
| "What is the current electricity tariff?" | tariff feed |

### What OntoSage will not do

| Request | Why | Response |
|---|---|---|
| "Turn off the lights on floor 3" | `control` intent always declines in v1 (SimDriver only) | Polite decline, logs attempt |
| "Email the report to the team" | External action, not modelled | Declined |
| "What is the capital of France?" | Out of scope | Scope redirect |

---

## By stakeholder

| Stakeholder | Key question types | Minimum data needed |
|---|---|---|
| **Facility Manager** | sensor_data, analytics, trend, anomaly, maintenance, floor_plan, recommend | Brick TTL + time-series MySQL + DWG files |
| **Sustainability Officer** | energy analytics, compare, trend, compliance, recommend | Energy/IAQ Brick TTL + `energy_data` + `iaq_data` tables |
| **Researcher** | metadata, discovery, analytics, export, trend | Brick TTL + relevant narrow tables |
| **Safety Officer** | anomaly, compliance, capability (fire safety), report_intake | Brick TTL + `documents/fire_safety.md` + `rules.yaml` |
| **General User / Student** | discovery, capability, floor_plan, spatial_query | Brick TTL + DWG/PDF files |
| **Admin** | All of the above + Admin portal | Everything above + `system:admin` role |

---

## Quick start

### 1. Configure and start

```bash
cp .env.example .env                          # set OPENAI_API_KEY (or MODEL_PROVIDER=local)
docker-compose up -d                          # all services start; wait ~90s
curl http://localhost:8000/health             # should show all services healthy
```

### 2. Register and authenticate

```bash
curl -X POST http://localhost:8000/auth/register \
  -H "Content-Type: application/json" \
  -d '{"username":"you","password":"pick-a-strong-one","email":"you@example.com"}'

TOKEN=$(curl -s -X POST http://localhost:8000/auth/login \
  -H "Content-Type: application/json" \
  -d '{"username":"you","password":"pick-a-strong-one"}' \
  | python -c "import sys,json; print(json.load(sys.stdin)['data']['session_token'])")
```

### 3. Ask questions

```bash
# Structural query — answered from Brick TTL alone
curl -X POST http://localhost:8000/chat \
  -H "Content-Type: application/json" -H "Authorization: $TOKEN" \
  -d '{"message":"How many sensors are on floor 3?","session_id":"demo"}'

# Live sensor reading — needs Brick TTL + time-series MySQL
curl -X POST http://localhost:8000/chat \
  -H "Content-Type: application/json" -H "Authorization: $TOKEN" \
  -d '{"message":"What is the current temperature in zone 5.28?","session_id":"demo"}'

# Multi-persona blending
curl -X POST http://localhost:8000/chat \
  -H "Content-Type: application/json" -H "Authorization: $TOKEN" \
  -d '{"message":"what should I look at this week?","session_id":"demo2",
       "personas":["facility_manager","sustainability_officer"]}'

# Multi-intent in one turn
curl -X POST http://localhost:8000/chat \
  -H "Content-Type: application/json" -H "Authorization: $TOKEN" \
  -d '{"message":"show me floor 3 layout and also tell me how many rooms are there",
       "session_id":"demo3"}'
```

### 4. Open the web interfaces

- **Chat UI**: `http://localhost:3000` (OpenWebUI — full conversation, multi-turn)
- **Admin Portal**: `http://localhost:3000/admin` (ontology management, reindex, health — requires admin role)
- **GraphDB SPARQL**: `http://localhost:7200`
- **Qdrant dashboard**: `http://localhost:6333/dashboard`

---

## Adding data to your building

### Step 1 — Add Brick triples (metadata, sensors, spaces)

This is the primary path. Everything OntoSage knows about a building's structure comes from `.ttl` files.

**File placement**: Drop any `bldg1_*.ttl` file into `input/` — the startup loader (`services/ttl_uploader.py`) ingests it idempotently into a named graph in GraphDB. No restart required if you use the Admin Portal upload; restart if dropping the file manually.

**Sensor registration shape** (canonical pattern):

```turtle
@prefix bldg:  <http://abacwsbuilding.cardiff.ac.uk/abacws#> .
@prefix brick: <https://brickschema.org/schema/Brick#> .
@prefix ref:   <https://brickschema.org/schema/Brick/ref#> .
@prefix rdf:   <http://www.w3.org/1999/02/22-rdf-syntax-ns#> .
@prefix rdfs:  <http://www.w3.org/2000/01/rdf-schema#> .

# 1. Declare the sensor and its location
bldg:EnergyMeter_Floor3 a brick:Electrical_Meter ;
    rdfs:label "Floor 3 Energy Meter"@en ;
    brick:isPartOf bldg:Floor3 .

# 2. Link to the time-series DB via a TimeseriesReference
bldg:EnergyMeter_Floor3 ref:hasExternalReference [
    a ref:TimeseriesReference ;
    ref:hasTimeseriesId "550e8400-e29b-41d4-a716-446655440003" ;
    ref:storedAt bldg:energy_narrow   # key in input/database_registry.yaml
] .
```

**Spaces and zones:**
```turtle
bldg:Room301 a brick:Room ;
    rdfs:label "Room 3.01"@en ;
    brick:isPartOf bldg:Floor3 ;
    brick:area "45.2"^^xsd:double .
```

**Rule**: If a fact can be expressed as an RDF triple, it goes in the TTL — not in `capability.yaml` or any sidecar file. Sidecar YAML is for operational config only.

### Step 2 — Connect time-series data (narrow MySQL tables)

OntoSage uses narrow `(uuid, datetime, value)` tables — one per sensor modality. The 7 tables are in `data/mysql-init/create_narrow_timeseries_tables.sql`:

| Table | Content | Unit |
|---|---|---|
| `energy_data` | Electrical energy per floor | kWh |
| `occupancy_data` | Occupancy count per zone | persons |
| `water_data` | Water flow | L/min |
| `noise_data` | Ambient noise | dB |
| `iaq_data` | PM2.5 and TVOC | µg/m³, ppb |
| `light_data` | Illuminance | lux |
| `equipment_data` | Vibration, AHU runtime | mm/s, h |

**Load the tables:**
```bash
mysql -u root -p sensordb < data/mysql-init/create_narrow_timeseries_tables.sql
```

**Insert sensor readings** (match the UUID from the TTL):
```sql
INSERT INTO energy_data (uuid, datetime, value)
VALUES ('550e8400-e29b-41d4-a716-446655440003', '2026-07-07 14:00:00', 12.4);
```

**Register the connection** in `input/database_registry.yaml`:
```yaml
energy_narrow:
  type: mysql_narrow
  table: energy_data
  host: "${MYSQL_HOST}"
  port: 3306
  database: sensordb
  user: "${MYSQL_USER}"
  password: "${MYSQL_PASSWORD}"
```

**Activate** by adding the key to `input/building.yaml` under `storage.databases`.

### Step 3 — Add documents to the knowledge base

Drop Markdown, PDF, or TXT files into `input/documents/`:

```
input/documents/
├── fire_safety.md          # "What are the fire procedures?"
├── governance.md           # "Who is responsible for HVAC?"
├── hvac_operation.md       # "How do I adjust the temperature setpoint?"
└── maintenance_log.md      # "When was the last HVAC service?"
```

The document indexer (`services/document_indexer.py`) runs at startup and indexes them into the Qdrant `documents_bldg1` collection. Cited in capability answers with the source filename.

### Step 4 — Configure live feeds (optional)

Add `input/feeds.yaml` for real-time data from REST APIs or CSV drops:

```yaml
feeds:
  - id: outside_weather_temp
    type: rest_poll
    url: https://api.open-meteo.com/v1/forecast?latitude=51.48&longitude=-3.18&current_weather=true
    interval_s: 300
    brick_class: brick:Outside_Air_Temperature_Sensor
    storage: mysql
    field_map:
      current_weather.temperature: value
```

Absence of `feeds.yaml` = feed framework idle (no error).

---

## The `input/` folder

All per-building files live in `input/`. The active building's files sit directly at root level — `input/building.yaml`, `input/*.ttl`, etc. A nested `input/<id>/` layout is supported as a fallback for staging.

```
input/
├── building.yaml           # REQUIRED — building_id, ontology_namespace, storage.databases
├── database_registry.yaml  # REQUIRED — connection templates for all data stores
├── bldg1_*.ttl             # REQUIRED — Brick Schema ontology files; auto-uploaded at startup
├── *.dwg, *.pdf            # Optional — floor plans (DWG for geometry, PDF for display)
├── capability.yaml         # Optional — off-ontology KB (lifts, prayer room, contacts)
├── intents.yaml            # Optional — per-building intent overlay
├── personas/               # Optional — per-building persona YAML files
│   └── facility_manager.yaml
├── feeds.yaml              # Optional — live feed specs (rest_poll / csv_drop)
├── rules.yaml              # Optional — ECA alert rules (CO2 high → notify)
├── channels.yaml           # Optional — notification dispatch (log / webhook / smtp)
├── benchmarks.csv          # Optional — peer benchmark percentiles
├── concepts.ttl            # Optional — HBCO local vocab ("the fishbowl" → Room)
└── documents/              # Optional — policy/manual KB (indexed into Qdrant)
    ├── fire_safety.md
    └── hvac_operation.md
```

**`building.yaml` required keys:**
```yaml
building_id: bldg1
building_name: Abacws Building
ontology_namespace: "http://abacwsbuilding.cardiff.ac.uk/abacws#"
building_prefix: bldg
storage:
  databases:
    - database1       # the main MySQL adapter for original sensor_data table
    - energy_narrow   # narrow modality tables
    - occupancy_narrow
```

---

## Admin Portal

The Admin Portal is a tab in the React frontend at **`http://localhost:3000/admin`**, backed by 8 FastAPI endpoints under `/api/v1/admin/`. All require `system:admin` role.

### Ontology Management

| Action | What it does |
|---|---|
| **Browse graphs** | List all named graphs in GraphDB with triple counts |
| **Validate TTL** | Parse Turtle text with rdflib; reports triple count or parse error |
| **Upload TTL** | POST valid Turtle into a named graph — live, no restart needed |
| **Drop graph** | Remove a named graph and all its triples from GraphDB |
| **SPARQL Browser** | Run SELECT queries against the live ontology |

### Knowledge Base Reindexing

| Action | What it does |
|---|---|
| **Trigger reindex** | Queues a background job to re-embed `capability`, `documents`, or `floor_plans` into Qdrant |
| **List jobs** | See all reindex jobs with status (`pending`, `running`, `done`, `error`) |
| **Job status** | Poll individual job by ID |

### Backend endpoints

```
GET  /api/v1/admin/ontology/graphs              — list named graphs
POST /api/v1/admin/ontology/validate            — validate TTL text
POST /api/v1/admin/ontology/upload              — upload TTL to GraphDB
DEL  /api/v1/admin/ontology/graphs/{id}         — drop a named graph
POST /api/v1/admin/ontology/sparql              — run a SELECT query
POST /api/v1/admin/reindex                      — trigger reindex job
GET  /api/v1/admin/reindex                      — list all jobs
GET  /api/v1/admin/reindex/{job_id}             — get job status
```

### Admin bootstrap

No default admin account exists. Set in `.env` before first start:
```bash
ADMIN_USERNAME=admin@yourorg.com
ADMIN_PASSWORD=<strong-password>
STRICT_SECRETS=true
```

The orchestrator creates that admin-role account on startup if it doesn't exist. Or create manually:
```bash
docker exec ontosage-orchestrator python /app/orchestrator/create_admin.py <user> <pass>
```

---

## Security & RBAC

### Authentication

- Argon2id password hashing
- Redis session tokens (7-day TTL)
- Session probes Postgres before lookup; fails closed with honest "service unavailable" on DB outage

### RBAC — 6 roles × 21 permissions

Roles and their grants are defined in `ROLE_PERMISSIONS` (`orchestrator/middleware/rbac.py`).
These are **RBAC roles**, distinct from *personas* (e.g. `sustainability_officer`,
`researcher`) which only bias intent classification and carry no permissions.

| Role | Key permissions |
|---|---|
| `admin` | `system:admin` + every read/write permission |
| `facility_manager` | All data reads + `config:read/write` + `building:read/write` + `device:control` + `control:write` |
| `analyst` | All data reads (sensor/analytics/metadata/report/export/anomaly/trend/compliance/comparison) + `building:read` |
| `operator` | `sensor/analytics/metadata/anomaly/trend:read` + `building:read` + `device:control` |
| `occupant` | `sensor:read`, `metadata:read`, `system:health` |
| `readonly` | `metadata:read`, `system:health` only |

### Required env flags

```bash
STRICT_SECRETS=true         # refuse startup if any password still equals its default
SECRET_KEY=<random-64-char> # JWT signing key
```

---

## Tests

**416 deterministic tests** across 17 files, run in CI on Python 3.10/3.11/3.12:

```bash
pytest tests/ -m unit -q                       # fast offline suite (~20s)
pytest tests/ -m integration -q                # needs running stack
pytest tests/test_routing_accuracy.py -v       # 29 canonical routing cases
pytest tests/test_admin_ontology_endpoints.py  # 13 admin endpoint tests
```

Key test files:

| File | Tests | What it covers |
|---|---|---|
| `test_routing_accuracy.py` | 29 | All 20+ intents + 5 override scenarios + 4 audit invariants |
| `test_survey_aligned_phases.py` | 64 | Capability KB + persona + workflow wiring |
| `test_phase_a_fixes.py` | 44 | Persona + routing (Phase 14A updates) |
| `test_blended_persona.py` | 14 | Persona blending semantics |
| `test_compound_query_e2e.py` | 17 | Multi-intent heuristic + decomposition |
| `test_coreference_rewrite.py` | 16 | Follow-up query rewrite gate + LLM mock |
| `test_turn_memory.py` | 10 | Redis count-eviction, Postgres `turn_memory` schema |
| `test_admin_ontology_endpoints.py` | 13 | Admin portal endpoints, auth enforcement |
| `test_intent_graph_autowire.py` | 5 | Every `node_method` resolves + is registered |
| `test_ttl_validator.py` | 10 | TTL parse, prefix/namespace, SHACL gating |

**Live tests (needs running stack):**
```bash
python scripts/corpus_replay.py --sample 240   # stratified 240-question replay (~63.8% pass)
python scripts/survey_live_test.py             # 95-question regression (94/95 last baseline)
python scripts/ontosage_qa_suite.py --quick    # persona × intent QA battery
```

---

## What's new

### P0 — Security Hardening (current branch: `security/p0-hardening`)

| Change | Detail |
|---|---|
| **RBAC enforced on all endpoints** | `require_permission()` → `get_user_context` dependency; all data endpoints return 401 on missing/invalid token |
| **Admin portal (8 new endpoints)** | Ontology management (list/validate/upload/drop graphs, SPARQL browser) + reindex job queue; all `system:admin` gated |
| **React admin tab** | `/admin` route in the frontend; service health check updated to GraphDB |
| **Narrow MySQL tables** | 7 per-modality `(uuid, datetime, value)` tables in `sensordb` — DDL in `data/mysql-init/create_narrow_timeseries_tables.sql` |
| **mysql_narrow adapter** | `MySQLNarrowAdapter` scopes to one table, builds `WHERE uuid IN (...)` queries |
| **TTL extensions** | `bldg1_timeseries_extension.ttl` (19 sensors, 7 modalities) + `bldg1_security_lighting_extension.ttl` (lighting systems, CCTV, alarm zones across 6 floors) |
| **STRICT_SECRETS** | `STRICT_SECRETS=true` refuses orchestrator startup when any password still equals its default value |

### V3 — Corpus-Driven Capability Completion (2026-06-11)

| Capability | Detail |
|---|---|
| **HBCO concept resolver** | 69 lay terms → Brick class + recipe; *"stuffy"* → `CO2_Sensor` + threshold recipe |
| **Recipe registry** | 38 analytic recipes (threshold, range, aggregate, benchmark, estimate) |
| **Live feed framework** | `csv_drop` + `rest_poll` adapters; weather, calendar, tariff feeds for bldg1 |
| **ECA rules engine** | Standing event-condition-action rules with Redis duration windows |
| **Actuation gateway** | SimDriver (log-only) + approval workflow; `control:write` RBAC gate |
| **Goal planner** | Mandate decomposition ("make this eco-friendly") → KPI sub-queries |
| **Document KB** | Policy/manual files indexed into Qdrant; cited in answers |
| **Corpus replay harness** | 240-question stratified replay; LLM-graded pass rate |
| **bldg2 portability proof** | Full V3 config validated against a second building fixture |

### Phase 22 — Follow-up co-reference (2026-05-xx)

*"and humidity there?"* is rewritten to *"average humidity on floor 3"* before classification. Gated (zero-LLM heuristic first); no-ops self-contained queries.

### Phase 21 — Conversation memory + secret hardening

Two-tier: Redis (count-bounded, no time-expiry) + Postgres `turn_memory` per-turn summaries. `STRICT_SECRETS` boot guard. Secrets masked in config repr.

### Phase 20 — PhD-grade forecasting

Multi-model time-series forecast (ARIMA / exp-smoothing / linear) inside the `trend` pipeline. Auto model selection, horizon parsing, RMSE/R² metrics.

### Phase 18 — Production hardening

libredwg 0.13.3 source build (6-floor DWG geometry, 20,370.2 m² total area); weasyprint PDF backend; Python 3.12 + Debian trixie base image (CVE remediation); Postgres connect retry with exponential backoff.

---

## Add a new intent (2 steps, no graph edits)

```yaml
# orchestrator/intents/intent_definitions.yaml
- name: my_intent
  description: |-
    What this intent handles. Include trigger phrases.
  examples:
    - '"trigger query 1"'
  pipeline_group: standalone
  node_method: _my_node_fn
```

```python
# orchestrator/workflow/_orchestrator.py
async def _my_node_fn(self, state: ConversationState) -> ConversationState:
    """One-line description."""
    state.intermediate_results["my_result"] = ...
    return state
```

Restart. Routing, graph wiring, and conditional edges auto-wire.

---

## Swap to a different building

```bash
# 1. Drop files under input/<new_id>/ (building.yaml + *.ttl required)
python scripts/swap_building.py --to bldg2 --dry-run    # validate
python scripts/swap_building.py --to bldg2 --archive    # apply
docker-compose restart orchestrator                       # TTL validator runs first
```

Exit code 2 on: missing building dir, missing/invalid `building.yaml`, or `@prefix bldg:` ≠ `ontology_namespace`.

---

## Documentation map

| Doc | Audience | Scope |
|---|---|---|
| **[CLAUDE.md](./CLAUDE.md)** | AI assistants / contributors | **Read first.** Navigation index (file:symbol), current branch state, debugging patterns, workflow rules, open issues |
| **README.md** (this file) | New users | Quickstart, stakeholder question guide, data setup, admin portal, RBAC |
| **[ONTOSAGE.md](./ONTOSAGE.md)** | Operators + contributors | Complete technical reference — all architecture, phases, config surface, tests, known issues |
| **[docs/CAPABILITY_ROUTING.md](./docs/CAPABILITY_ROUTING.md)** | Contributors | Semantic router threshold tuning + capability KB design |
| **[docs/RUNBOOK.md](./docs/RUNBOOK.md)** | Operators | Incident runbook — what to do when things break |
| **[.claude/rules/](./.claude/rules/)** | Contributors | Style + agent + API + SPARQL patterns |

**For AI-assisted code review or bug fixing:** read all three core files (`CLAUDE.md` → `README.md` → `ONTOSAGE.md`) before touching code. `CLAUDE.md`'s Navigation Index tells you exactly which file and symbol to open for any task — without it you'll spend tool calls searching.

---

## Known issues

| Issue | Status |
|---|---|
| Maintenance agent "report broken light" | Open — returns generic fallback; workaround: be specific ("report broken light in room 3.01") |
| MySQL host mode | MySQL runs on the Docker host (`host.docker.internal:3306`, database `sensordb`); the Docker MySQL service in `docker-compose.yml` is commented out |
| FLUSHDB wipes sessions | `redis-cli FLUSHDB` removes session tokens; users must log in again. Safe flush: target only `resp_cache:*` keys |

---

## License

MIT. Developed against Cardiff University's Abacws building (`bldg1`), with `bldg2` as a multi-tenant fixture. Brick Schema is BSD-licensed.
