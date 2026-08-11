# OntoSage — Agentic AI for Smart Buildings

**Ask your building anything in plain English. Get sensor-grounded, persona-aware, multi-intent answers.**

[![Python](https://img.shields.io/badge/python-3.10%20|%203.11%20|%203.12-blue.svg)](https://www.python.org/)
[![FastAPI](https://img.shields.io/badge/FastAPI-0.115-009688.svg)](https://fastapi.tiangolo.com/)
[![LangGraph](https://img.shields.io/badge/LangGraph-0.2-7C3AED.svg)](https://langchain-ai.github.io/langgraph/)
[![Brick Schema](https://img.shields.io/badge/Brick_Schema-1.3-orange.svg)](https://brickschema.org/)
[![License: MIT](https://img.shields.io/badge/License-MIT-yellow.svg)](https://opensource.org/licenses/MIT)
[![CI](https://github.com/suhasdevmane/OntoSage/actions/workflows/ci.yml/badge.svg)](https://github.com/suhasdevmane/OntoSage/actions/workflows/ci.yml)
[![Tests](https://img.shields.io/badge/tests-981%20passing-brightgreen.svg)](#tests)

---

A facility manager opens the chat and asks: *"Show me floor 3 layout and also tell me how many rooms are there."*

OntoSage decomposes it into two sub-intents (`floor_plan` + `spatial_query`), routes each to the right agent, and returns both the floor map PDF and the room count in one response. Behind the scenes: two LLM calls, session validation, persona blending, Brick ontology + MySQL time-series + DWG geometry, and a complete routing audit trail written to Redis.

No SQL, no SPARQL, no schema knowledge required from the user.

Ask a follow-up — *"and what about humidity there?"* — and it remembers you meant floor 3.

> **Full technical reference:** [ONTOSAGE.md](./ONTOSAGE.md) — complete architecture, phase-by-phase changelog, all intents, multi-tenant/multi-persona model, conversation memory, forecasting pipeline, admin console, test coverage, known issues.

---

## Measured coverage

```
Corpus replay, 240 stratified questions
    bldg1 (Abacws, real building)         63.8% pass   (vs 16.2% baseline before V3)
    bldg2 (portability building)          70.4% pass   — same code, zero changes
Live survey (95 questions, Phase 18):     94/95 PASS · 1 WARN · 0 FAIL  (99%)
Deterministic unit suite:                 981 pass / 0 fail, 8 skipped (Python 3.10/3.11/3.12)
```

Validates against the 5,604-question survey in `paper/Survey analysis and results/` — corroborates
paper §6.5. The bldg2 run is the portability evidence: a second building with a different namespace,
size and sensor mix scored **above** the first with no code changes — only its own data and config.

---

## Design principles

OntoSage is **an agentic conversational layer over one smart building's own data** — *connect a
building's data, then ask it anything in plain English.* Everything below is a deliberate design
commitment, not an accident of implementation:

1. **One building at a time.** A deployment serves a single active building. Several buildings can
   live side by side in the repo, each with its own data folder, env file and compose file; exactly
   one is *activated* at a time by renaming its trio to `input/`, `.env` and `docker-compose.yml`,
   and each keeps isolated state under `volumes/<building_id>/`.
2. **TTL-first — the ontology is the source of truth.** If a fact can be an RDF triple, it lives in
   the Brick/BACnet ontology, not a sidecar file or a code constant. Questions are answered via SPARQL
   first; SQL, analytics, and the knowledge base handle only live time-series and things RDF can't express.
3. **No hardcoding — building-agnostic core.** Core code carries no building-specific literals
   (namespaces, zone ids, sensor counts, areas). Every figure in an answer is computed live from the
   graph or the floor plans, so it can never drift stale — and the same code runs unchanged for any building.
4. **Honest, grounded answers — never fabricate.** Every number traces to live data. Ask about a floor,
   wing, amenity, asset or measurement this building does not have and OntoSage says so plainly — it will
   not quietly answer with another sensor's readings, and it will not present an unrelated document as
   the answer. Each refusal also tells you **what to add** to make the question answerable.
5. **Any stakeholder, any purpose.** One interface serves facility managers, occupants, researchers,
   sustainability and safety officers, executives, visitors, students, and admins. Personas shape how an
   answer is framed; they don't gate access.
6. **Zero-knowledge to expert.** No SQL, SPARQL, or schema knowledge is required — lay terms resolve to
   the right sensors — yet experts still get Brick classes, RDF types, and a live SPARQL browser.
7. **Admin-controlled access (RBAC).** Every data and configuration endpoint is permission-gated;
   ontology management is admin-only. Roles are separate from personas.
8. **Connect data, get answers.** A question becomes answerable when the sensor is described in the
   ontology *and* its readings are in a registered database. Onboarding a source is drop-in: add the
   triples, register the database, load the rows — no code.
9. **Multiple datasources, pluggable — even within one building.** Each sensor's `ref:storedAt`
   routes its readings to the right backend, so different sensors in the *same* building can live in
   different databases: one active building runs MySQL and PostgreSQL side by side, some sensors read
   from each. A new backend technology is a new adapter, nothing more; the registry ships connection
   templates for ~50 stores (MySQL, PostgreSQL, TimescaleDB, MongoDB, InfluxDB, Cassandra, Redis, …).
10. **Local or API models, independently.** Language and embedding models are each switchable between
    OpenAI and local Ollama, so you can run fully offline for privacy or on the API for capability.
    The local embedding model (`bge-large-en-v1.5`) is baked into the image and runs offline; its
    vector width and retrieval threshold are read from the model itself, and a boot-time sweep repairs
    any vector store left at a mismatched width — so the model can never silently drift.
11. **One command to run it.** Activate a building once (a couple of renames — no build steps, no
    generators) and the entire stack boots with `docker compose up -d`; all configuration lives in
    `.env` and the `input/` folder.

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

### Flow — onboard a building end-to-end from the browser

**Fresh clone → pure-GUI onboarding. No host-side file editing, no code.** Every step is a tab in
the Admin Console (`http://localhost:3001`); each one writes into the **active building's `input/`
folder**, which OntoSage re-reads live.

```
  git clone …  →  activate a building (rename bldg1/ → input/)  →  docker compose up -d
        │
        ▼
  open  http://localhost:3001   (Admin Console — sign in as admin)
        │
        ▼
  ┌──────────────────────────────────────────────────────────────────────┐
  │ 1  Ontology ▸ Building identity   namespace / prefix / building name  │
  │ 2  Ontology ▸ Upload TTL          Brick model — sensors + links       │
  │ 3  Databases ▸ Register sensors   ref:hasTimeseriesId + ref:storedAt   │
  │ 4  Ontology ▸ Documents           policies / manuals (.md/.txt/.pdf)   │
  │ 4  Ontology ▸ Floor plans         PDF / DWG per floor                  │
  └──────────────────────────────────────────────────────────────────────┘
        │
        ▼
  5  Ask ▸ type a question   →   grounded answers, forever

  Every step writes into the ACTIVE building's  input/  folder (live reload).
  One building at a time — input/ is always the active building.
```

| Step | Admin Console tab | What it writes | Backing endpoint |
|---|---|---|---|
| 1. Building identity | **Ontology ▸ Building** | `input/building.yaml` (namespace, prefix, storage keys) | `PUT /api/v1/admin/building/config` |
| 2. Upload TTL | **Ontology ▸ Upload TTL** | `input/<file>.ttl` + GraphDB named graph | `POST /api/v1/admin/ontology/upload` |
| 3. Register sensors / DB | **Databases** | Brick + `ref:storedAt` triples; DB connection | `POST /api/v1/admin/databases/*` |
| 4. Documents | **Ontology ▸ Documents** | `input/documents/*` → document KB (Qdrant `documents_<bldg>`) | `POST /api/v1/admin/documents/upload` |
| 4. Floor plans | **Ontology ▸ Floor plans** | `input/<label> floor <N>.<ext>` → spatial manifests | `POST /api/v1/admin/floor-plans/upload` |
| 5. Ask | **Ask** | — (queries all of the above) | `POST /chat` |

> **Switching vs building.** `input/` is always the *active* building. To **build a new** building,
> do steps 1–5 in the browser. To **switch to a pre-built** building, swap `input/`'s contents (and
> `.env` / `docker-compose.yml`) — see [BUILDING_ONBOARDING.md](docs/BUILDING_ONBOARDING.md).

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

### Questions answered from capability triples (no time-series needed)

Capabilities are **`ontosage:Amenity` / `ontosage:KnowledgeTopic` triples** in the building's
ontology (authored via the admin Capabilities GUI or the OCBV TBox — see
[ONTOSAGE.md §8.5](./ONTOSAGE.md)). Genuinely-uploaded manuals stay in the document KB.

| Question | Intent | Answered from |
|---|---|---|
| "Where is the lift?" | `capability` | `ontosage:Amenity` triple (`<id>_capabilities.ttl`) |
| "Is there a prayer room?" | `capability` | `ontosage:Amenity` triple |
| "What is the wifi / GDPR policy?" | `capability` | `ontosage:Policy` / `ontosage:KnowledgeTopic` triple (`answerText`), with the full text drawn from the document the topic names via `ontosage:documentRef` |
| "Is the building wheelchair accessible?" | `capability` | `ontosage:Amenity` triple |
| "What are the fire evacuation procedures?" | `capability` | the `ontosage:Policy` topic points at `documents/fire_safety.md`; retrieval is scoped to that file, not chosen by similarity across the whole corpus |

A `KnowledgeTopic` carries the short authoritative answer; when it also declares
`ontosage:documentRef`, the long form is read from *that named document* rather than whichever
chunk a vector search scores highest — so a policy question is answered deterministically from the
document the ontology says governs it.

### Asking about OntoSage itself (no building data needed)

| Question | Intent | Answered from |
|---|---|---|
| "What is OntoSage?" | `self_description` | Live configuration — described as a building-agnostic framework, not one site's product |
| "What can you do?" | `self_description` | The active building's own intent registry (so a per-building intent shows up automatically) |
| "How do you work?" | `self_description` | The schema's grounding-source types + the connected building's live figures |
| "What kind of questions can I ask?" | `self_description` | The capability groups, composed from configuration — never a written-out blurb |

These are answered before any other path can claim them, so OntoSage never mistakes a question
*about itself* for one about the building, never answers it from an unrelated document, and never
falls through to a generic assistant that would claim to be "a large language model."

![OntoSage describing itself](docs/screenshots/answer-self-description.png)
*Asked "What can you do?", OntoSage answers as the framework it is. The capability groups are read
from the active building's own intent registry and the figures from its live data — connect a
different building and the capabilities stay the same while "Currently connected to" changes.*


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
| "What's the temperature in Zone 99.99?" | The zone is not in this building's model | Names real zones instead — never another zone's reading |
| "How many sensors are on floor 42?" | The floor does not exist | Lists the floors that do exist |
| "Show me the swimming pool temperature" | No such space or sensor | Says so, and explains how to add it |
| "Plot the methane concentration" | Nothing measures methane here | Refuses rather than substituting another metric |

**Refusals are actionable.** Every "I don't have that" ends with the concrete next step —
upload a TTL describing the entity, give its sensors `ref:hasTimeseriesId` + `ref:storedAt`,
register the database, or add an `ontosage:Amenity` — all config and data, never code.
This is the honesty guarantee in practice: a plausible-sounding wrong number is worse than
no number, because you cannot tell it apart from a right one.

![An honest decline with the steps that would make it answerable](docs/screenshots/answer-honest-decline.png)
*The building has no swimming pool. Rather than return its real whole-building sensor count — every
figure true, none of them an answer — OntoSage says it cannot find the referent and lists exactly what
to add.*

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

### 1. Activate a building

*Takes about a minute — do this before anything else.*

OntoSage runs **one building at a time**, and "activating" one is simply *naming*: the active
building is whichever folder is called `input/`, with `.env` and `docker-compose.yml` beside it.
A fresh clone ships all three demo buildings **parked**, so you pick one — nothing is generated,
nothing is built, you are just renaming files:

```
  A FRESH CLONE HAS                          YOU MAKE IT LOOK LIKE
  ─────────────────────────                  ──────────────────────────────
  bldg1/                     ──rename──►     input/               ← active building's data
  docker-compose.bldg1.yml   ──rename──►     docker-compose.yml   ← its services
  .env1.example              ──copy────►     .env                 ← its settings + secrets

  bldg2/ , bldg3/ and their files stay parked, untouched.
```

**Linux / macOS**

```bash
mv bldg1 input                                  # 1. building data (TTLs, floor plans, docs)
mv docker-compose.bldg1.yml docker-compose.yml  # 2. its compose file
cp .env1.example .env                           # 3. its settings — already has bldg1's identity
```

**Windows (PowerShell)**

```powershell
Move-Item bldg1 input
Move-Item docker-compose.bldg1.yml docker-compose.yml
Copy-Item .env1.example .env
```

Each building ships a matching template — `.env1.example`, `.env2.example`, `.env3.example` —
already carrying that building's identity (`BUILDING_ID`, namespace, database, compose project),
so activating `bldg2` is the same three lines with `2` substituted.

**Now open `.env` and replace every `CHANGE-ME` value.** They are placeholders, and
`STRICT_SECRETS=true` deliberately refuses to boot while any of them remains:

```bash
SECRET_KEY=CHANGE-ME-random-64-hex-chars     →  a real random string
GRAPHDB_PASSWORD=CHANGE-ME-…                 →  your GraphDB password
MYSQL_PASSWORD=CHANGE-ME-…                   →  your MySQL password
POSTGRES_USER_PASSWORD=CHANGE-ME-…           →  your Postgres password
ADMIN_PASSWORD=CHANGE-ME-…                   →  12+ characters
OPENAI_API_KEY=                              →  your key, or leave blank for local Ollama
```

The real `.env` you create is gitignored and never committed — only the `*.example`
templates ship.

> **`bldg1`, `bldg2`, `bldg3` are demo fixtures** so you can see a working system in minutes.
> Running *your own* building works the same way — activate a slot, then replace its contents:
> see [Use OntoSage with YOUR building](#use-ontosage-with-your-building).

### 2. Start the stack

```bash
docker compose up -d                          # all services start; wait ~90s
curl http://localhost:8000/health             # should show all services healthy
```

First boot warms GraphDB, which can take a few minutes on a large ontology; ontology
initialisation retries itself, so no manual restart is needed.

### 3. Register and authenticate

```bash
curl -X POST http://localhost:8000/auth/register \
  -H "Content-Type: application/json" \
  -d '{"username":"you","password":"pick-a-strong-one","email":"you@example.com"}'

TOKEN=$(curl -s -X POST http://localhost:8000/auth/login \
  -H "Content-Type: application/json" \
  -d '{"username":"you","password":"pick-a-strong-one"}' \
  | python -c "import sys,json; print(json.load(sys.stdin)['data']['session_token'])")
```

### 4. Ask questions

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

### 5. Open the web interfaces

- **Chat UI**: `http://localhost:3000` (OpenWebUI — full conversation, multi-turn)
- **Admin Console**: `http://localhost:3001` (config-panel — building identity, capabilities, sensors, ontology, reindex, health; requires admin role)
- **GraphDB SPARQL**: `http://localhost:7200`
- **Qdrant dashboard**: `http://localhost:6333/dashboard`

---

## Use OntoSage with YOUR building

> **`bldg1`, `bldg2` and `bldg3` are test fixtures, not the product.** They exist so you can see a
> working system immediately and so portability is provable. Your building goes in exactly the same
> three slots — same folder, same env file, same compose file, **no code changes**.

### The idea in one line

Activate a slot, replace its contents with your building's ontology and config, point the sensors at
your database, restart. That's the whole process.

### Step 1 — Activate a slot and give it your identity

Activate any building (`bldg1` is the conventional choice) so the slots exist, then **change the
identity to your own**. Use a **new `BUILDING_ID`** — this is the single most important choice on
this page:

```bash
mv bldg1 input                                  # take over the slot
mv docker-compose.bldg1.yml docker-compose.yml
cp .env1.example .env                           # then change the identity block below
```

Per-building state lives in `volumes/<BUILDING_ID>/`. A **new id gets a brand-new, empty GraphDB,
Qdrant, Redis and Postgres automatically** — a genuinely fresh start. Keep the id `bldg1` and you
inherit Abacws's 320k triples, and your building's entities will be *added alongside* them, mixing
two buildings in one graph. If you must reuse an id, delete its state first:
`docker compose down && rm -rf volumes/bldg1`.

Set the identity block in **`.env`** (and mirror it in `input/env.building`, which travels with the
folder):

```bash
BUILDING_ID=riverside_hq                              # your id — drives volumes/<id>/ and log lines
BUILDING_NAME=Riverside HQ                            # shown in answers
BUILDING_NAMESPACE=http://example.org/riverside#      # MUST equal @prefix bldg: in your TTL
BUILDING_PREFIX=bldg
BUILDING_TIMEZONE=Europe/London                       # used for "today" / "yesterday"
MYSQL_DATABASE=riverside_sensordb                     # your time-series database
COMPOSE_PROJECT_NAME=ontosage_riverside               # keeps containers/volumes namespaced
```

Also set real secrets — `STRICT_SECRETS=true` refuses to boot while any password is still a default:
`MYSQL_PASSWORD`, `POSTGRES_USER_PASSWORD`, `GRAPHDB_PASSWORD`, `SECRET_KEY`, `PIPELINE_API_KEY`,
plus `OPENAI_API_KEY` (or `MODEL_PROVIDER=local` with `OLLAMA_MODEL`).

### Step 2 — Replace the building data in `input/`

Delete the fixture's building files and drop in yours. **Keep the three shared schema files** —
they are OntoSage's vocabulary, not building data:

| Keep as-is (shared schema) | Replace with yours (building data) |
|---|---|
| `Brick_v1.4.ttl` — Brick ontology | `<your_id>.ttl` — your Brick model (sensors, spaces, equipment) |
| `Brick+extensions.ttl` — Brick extensions | `building.yaml` — `building_id`, `building_name`, `ontology_namespace` |
| `ontosage_schema.ttl` — OCBV vocabulary | `env.building` — identity mirror of the block above |
| | `database_registry.yaml` — your database connections |
| | `<your_id>_capabilities.ttl` — amenities / knowledge topics *(optional)* |
| | `<label> floor <N>.pdf` / `.dwg` — floor plans *(optional)* |
| | `documents/` — manuals, policies *(optional)* · `personas/` *(optional)* |

Your TTL must satisfy three rules — each one caused a real onboarding failure here:

```turtle
@prefix bldg: <http://example.org/riverside#> .   # 1. MUST equal ontology_namespace
@base        <http://example.org/riverside#> .   # 2. REQUIRED — without it GraphDB
                                                 #    rejects the whole file if any
                                                 #    IRI is relative
bldg:Room_204_Temp a brick:Air_Temperature_Sensor ;
    rdfs:label "Room 204 Temperature" ;
    brick:hasExternalReference [
        a ref:TimeseriesReference ;
        ref:hasTimeseriesId "8f3c…-uuid" ;       # 3. the column/uuid in YOUR database
        ref:storedAt        bldg:database1 ] .   #    an IRI, NOT a string — a quoted
                                                 #    literal silently breaks the join
```

### Step 3 — Connect your data source

The **two-halves rule** governs everything: a question is answerable when the sensor is a **triple in
the graph** *and* its readings are **rows in a registered database**. One half alone answers nothing.

Register the database under the key your TTL's `ref:storedAt` points to, in
`input/database_registry.yaml`:

```yaml
databases:
  database1:                                    # ← matches ref:storedAt bldg:database1
    type: mysql                                 # mysql | mysql_narrow | postgresql |
                                                # timescaledb | influxdb | mongodb | sqlite | …
    host: "${MYSQL_HOST:-host.docker.internal}"
    port: "${MYSQL_PORT:-3306}"
    user: "${MYSQL_USER}"
    password: "${MYSQL_PASSWORD}"
    database: "${MYSQL_DATABASE}"
    nature: real                                # real | synthetic — shown as provenance
    note: "Riverside BMS historian"
```

Two supported table shapes: **wide** (`type: mysql`, one column per sensor uuid — note MySQL's
~1017-column limit) and **narrow** (`type: mysql_narrow` / `postgresql` with `table:`, rows of
`(uuid, datetime, value)` — preferred for large estates).

**One building, several databases.** Add as many backends as you like; each `ref:storedAt` key
routes to its own. Point some sensors at a second key and register it — no code:

```yaml
  database_pg:                                  # ← a subset of sensors: ref:storedAt bldg:database_pg
    type: postgresql
    host: "${POSTGRES_HOST:-postgres}"
    database: "${POSTGRES_DB:-readings}"
    table: sensor_timeseries                    # narrow (uuid, datetime, value); layout auto-detected
    nature: synthetic
    note: "Second backend technology for this building"
```

A working example ships in the repo: one building answers `AHU01N` readings from **MySQL** and
`Server Room R101` readings from **PostgreSQL** in the same conversation — the adapter layer picks
the backend per sensor from `ref:storedAt`. Adding a third technology (TimescaleDB, MongoDB, …) is
the same three edits: point sensors at a new key, register it, supply its credentials in `.env`.

![A reading served from MySQL](docs/screenshots/answer-mysql-reading.png)
![The same building, a reading served from PostgreSQL](docs/screenshots/answer-postgres-reading.png)
*Two questions, one building, two database technologies. Nothing in the question says which backend to
use — the sensor's `ref:storedAt` decides, and the user never sees the difference.*

### Step 4 — Build and start

```bash
docker compose down                       # if anything is running
docker compose build orchestrator         # only needed after a code change or first build
docker compose up -d
curl http://localhost:8000/health         # wait for "healthy"
```

Your TTLs are ingested automatically on boot (re-uploaded only when their content changes), the
sensor map is built from the live graph, and the floor-plan pipeline indexes any PDFs/DWGs. Cold
GraphDB warm-up can take minutes on a large ontology; ontology initialisation retries on its own.

### Step 5 — Verify both halves

```bash
# Half 1 — ontology loaded? (structural; answered by SPARQL alone)
"How many temperature sensors are in this building?"

# Half 2 — readings connected? (needs the timeseries link + rows)
"What is the current temperature in Room 204?"
```

The count answer also reports **declared vs reporting** sensors — "1,318 declared, 683 reported in
the last 24 h" — which is the fastest way to see how much of your model is actually wired to data.
If a sensor exists in the graph but returns nothing, its `ref:hasTimeseriesId` or `ref:storedAt` is
wrong, or the rows aren't there.

### Onboarding pitfalls we hit for real

| Symptom | Cause | Fix |
|---|---|---|
| Orchestrator refuses to boot, complains about namespace | `@prefix bldg:` ≠ `ontology_namespace` | Make them byte-identical (trailing `#` included) |
| GraphDB rejects the whole TTL ("malformed") | Relative IRIs with no `@base` | Add `@base` matching your namespace |
| Structural questions work, live values never do | `ref:hasTimeseriesId` present but `ref:storedAt` missing, or refs written as **strings** instead of IRIs | Both required; `ref:storedAt` must be an IRI matching a registry key |
| Answers mention a building you didn't load | Reused a `BUILDING_ID` whose `volumes/<id>/` still holds the old graph | Use a new id, or delete that state directory |
| "UUIDs missing / no readings" right after seeding | Adapter caches table columns for 5 minutes | Seed before boot, or restart the orchestrator |
| Wide table refuses more sensors | MySQL's ~1017-column limit | Switch those sensors to a narrow `(uuid, datetime, value)` table |

> **Prefer clicking to editing?** Everything above can be done from the Admin Console at
> `http://localhost:3001` — building identity, TTL upload, database registration, sensor mapping,
> documents and floor plans — with no host-side file editing. See [Admin Portal](#admin-portal).

---

## Adding data to your building

> **No-code path (recommended):** you never have to write code — only add **data** and
> **triples** through the admin console (`http://localhost:3001`). The whole flow is:
> **(1)** *Databases* tab → **+ Add connection** (your DB, hosted anywhere) → **(2)** that
> datasource → **Register sensors** (a guided form with Brick-class / location / UUID
> suggestions, or bulk **CSV**/**TTL**) — this writes the Brick + `ref:storedAt` triples that
> say *"I have this sensor, at this location, and its data is in this datasource"* →
> **(3)** ask questions and get grounded answers, forever. New backend = new registry entry,
> not code. Full walkthrough: **[ONTOSAGE.md §6.9](ONTOSAGE.md)**. The file-based steps below
> are the equivalent if you prefer editing TTL by hand.

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

**Rule**: If a fact can be expressed as an RDF triple, it goes in the TTL — not in a sidecar file. Sidecar YAML is for operational config only. (Capabilities followed this to completion: the old `capability.yaml` was removed and its content lives as `ontosage:Amenity` / `ontosage:KnowledgeTopic` triples.)

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
├── *.ttl                   # REQUIRED — Brick Schema ontology files; auto-uploaded at startup
├── ontosage_schema.ttl     # The OCBV vocabulary — the "talk to the building" layer over Brick
├── db_<key>_sensors.ttl    # Auto-written when you register a DB's sensors in the admin console
├── *.dwg, *.pdf            # Optional — floor plans (DWG for geometry, PDF for display)
├── <id>_capabilities.ttl   # Capability TRIPLES — ontosage:Amenity / KnowledgeTopic
│                           #   (amenities, policies, how-tos, faults). GUI- or TBox-authored.
├── documents/              # Optional — uploaded long-form manuals (semantic doc KB)
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
ontology_namespace: "http://abacwsbuilding.cardiff.ac.uk/abacws#"   # the URI the bldg: prefix binds to
ontology_prefix: bldg                                               # SPARQL prefix label
storage:
  databases:
    - database1       # the main MySQL adapter for original sensor_data table
    - energy_narrow   # narrow modality tables
    - occupancy_narrow
```

> **`ontology_namespace` is the key per-building setting** — the `bldg:` prefix in every TTL is only a
> label; the *namespace* it binds to is what makes triples belong to *this* building. Set it before
> loading triples, and make sure every TTL's `@prefix bldg:` matches it (the startup validator hard-fails
> on a mismatch). You can set/view it in the admin console (**Ontology → Building identity**) instead of
> editing the file. It's read at boot, so a change applies after an orchestrator restart.

---

## Talking to the building — the OCBV vocabulary

Brick describes a building's *technical fabric* (points, sensors, equipment, locations) for machines.
It does **not** model what a human actually asks — *"where's the prayer room?", "is it stuffy on floor
5?", "the toilet is leaking, who do I tell?"*. The **OntoSage Conversational Building Vocabulary
(OCBV)** — `input/ontosage_schema.ttl`, CC-BY-4.0 — adds exactly that layer, and is what makes a
building *talkable-to*.

It **extends Brick without contradicting it** (own `ontosage:`/`hbco:` namespaces; references Brick
classes as ranges; aligns to Brick/REC/BOT/SOSA with SKOS mappings only). Loading it alongside a Brick
model adds conversational triples and invalidates nothing. Modules:

| Module | What it models |
|---|---|
| **Capabilities** | Amenities (prayer room, café, lift…) + knowledge topics (info / how-to / maintenance route) |
| **Conversation concepts** (HBCO) | Lay word → Brick sensor ("stuffy" → CO₂), so plain language resolves to live data |
| **Stakeholder roles** | Who is asking (occupant, FM, researcher…) — frames the answer, **not** RBAC |
| **Question-intent grammar** | The *kinds* of question (locate, quantify, trend, compare, anomaly, forecast, report) |
| **Report intake + provenance** | Fault/complaint/safety/feedback records, and how an answer is grounded (SPARQL/DB/floor-plan) |
| **Competency questions + example SPARQL** | Per-class annotations — for both the paper and LLM-assisted query generation |

**The schema is the single source of truth for authoring *and* answering:**

- **It drives the authoring UI.** The admin console's "Add capability" **Type** dropdown *and* its form
  fields are generated live from the OCBV classes and datatype-property domains — add a class or
  property to `ontosage_schema.ttl` and it appears in the form, no code change.
- **It feeds the RAG/LLM.** The schema's natural-language text (comments, definitions, examples,
  lay-terms, competency questions) is indexed into the semantic index, so a plain-English question
  matches the right OCBV term — and the retriever then hands the term's **example SPARQL** to the LLM
  as a copy-adaptable template.

Stakeholders add instances via the guided form (or by dropping a `<bldg>_capabilities.ttl` file); no
Turtle required. Full technical detail: [ONTOSAGE.md § 6.10](./ONTOSAGE.md).

---

## Admin Portal

The running admin console is the **config-panel at `http://localhost:3001`** (localhost-only, served
by nginx and proxying `/api` + `/auth` to the orchestrator over the internal network). All admin
actions call FastAPI endpoints under `/api/v1/admin/` and require the `system:admin` role. *(A React
admin portal also exists under `frontend/src/` for development, but its Docker service is off by
default — the config-panel is the console to use.)*

### Ontology & schema

| Action | What it does |
|---|---|
| **Building identity** | View/edit `ontology_namespace` + prefix + name (written to `building.yaml`); restart to apply |
| **Add capability** | Guided form whose **Type dropdown + fields are generated from the OCBV schema**; writes a dual-typed instance to `input/<bldg>_capabilities.ttl` |
| **Browse / drop graphs** | List named graphs with triple counts; drop a graph (file-backed graphs are trashed so the drop survives a restart) |
| **Validate / Upload TTL** | Parse Turtle (rdflib); upload into a named graph — a `urn:ontosage:ttl:<file>` graph also persists to `input/<file>` so it survives a restart |
| **SPARQL browser** | Run read-only SELECT/ASK against the live ontology |

### Databases & sensors

| Action | What it does |
|---|---|
| **Register sensors** | Points form / CSV / TTL → **written TTL-first to `input/db_<key>_sensors.ttl`** (source of truth) and synced to GraphDB, so they survive a restart and get reindexed. Re-registering upserts (no duplicates). |
| **Test / introspect** | Probe an external DB connection and list its tables/columns |

### Indexing

| Action | What it does |
|---|---|
| **Semantic index (auto)** | Adding sensors or uploading TTL automatically triggers a **debounced** rebuild of the GraphDB similarity index (it self-heals/creates on a fresh volume). |
| **Semantic-index status** | The console shows *rebuilding → up-to-date* so you know when new data is searchable; a **Rebuild now** button forces it. |
| **KB reindex (Qdrant)** | Background job to re-embed `capability` / `documents` / `floor_plans` into Qdrant. |

### Backend endpoints (selected)

```
GET  /api/v1/admin/building/config              — read ontology namespace/prefix/name
PUT  /api/v1/admin/building/config              — write them to building.yaml (restart to apply)
GET  /api/v1/admin/capabilities                 — list capabilities + schema-derived types & form fields
POST /api/v1/admin/capabilities                 — create a capability (guided, schema-validated)
POST /api/v1/admin/databases/{key}/sensors[/csv|/ttl]  — register sensors (persist to input/ + reindex)
GET  /api/v1/admin/ontology/graphs              — list named graphs
POST /api/v1/admin/ontology/validate|upload     — validate / upload TTL (file graphs persist to input/)
DEL  /api/v1/admin/ontology/graphs/{id}         — drop a named graph
POST /api/v1/admin/ontology/sparql              — run a SELECT/ASK query
POST /api/v1/admin/reindex                      — trigger reindex (capability|documents|floor_plans|ontology_similarity)
GET  /api/v1/admin/reindex/similarity-status    — semantic-index state (rebuilding | ready)
GET  /api/v1/admin/reindex[/{job_id}]           — list / poll Qdrant reindex jobs
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

### Users and roles in practice

Accounts are created in the **Admin Console → Users & Access**: pick a username, a
password (12+ characters, with a show/hide toggle so you can confirm what you typed), and
a role. Each row also has a **Password** button to set a new one — stored passwords are
one-way Argon2id hashes, so an existing password can never be displayed, only replaced.
A reset signs out that user's active sessions, and both creating a user and changing a
role take effect on the next request: **no restart, no re-login, no cache flush**.

The **Role → Data-source access** matrix on the same tab controls which data sources each
role may draw on when answering. A role left fully unticked is unrestricted (access
control is opt-in), and changes apply immediately.

### Role-aware answers in the chat UI

Open WebUI authenticates to OntoSage with a single shared `PIPELINE_API_KEY`, so on its own
every chat request would arrive as the same least-privilege identity. Setting
`ENABLE_FORWARD_USER_INFO_HEADERS=true` on Open WebUI makes it forward who is signed in, and
`TRUST_FORWARDED_USER=true` on the orchestrator resolves that identity to the matching
OntoSage account so **its** role drives the answer:

```
"Set the temperature setpoint in zone 5.28 to 21 degrees"

  readonly          → "You don't have permission to control building systems…"
  facility_manager  → "Command queued for approval (ID: b2160acc)…"
```

Identical request, identical API key, different answers.

Someone who signs into the chat UI without an OntoSage account is served at **readonly** —
enough to explore the building, nothing more. Give them a role by creating an account whose
username matches their sign-in email (or its local part, e.g. `alice@example.com` →
`alice`); the next question they ask uses it.

> **Trust boundary.** A forwarded header is only as trustworthy as whoever can set it —
> anyone holding `PIPELINE_API_KEY` could claim to be any user. `TRUST_FORWARDED_USER` is
> therefore **off by default** and safe to enable only where the proxy is the sole key
> holder on a trusted network (the default Docker setup). With it off the header is ignored
> entirely.

### Required env flags

```bash
STRICT_SECRETS=true          # refuse startup if any password still equals its default
SECRET_KEY=<random-64-char>  # JWT signing key
TRUST_FORWARDED_USER=true    # apply each chat user's own role (see trust boundary above)
```

---

## Tests

**981 deterministic tests pass, 8 skipped**, run in CI on Python 3.10/3.11/3.12.
Skips are optional dependencies and fixtures that need an *active* building.
The suite runs from a clean checkout with **no active building and no `.env`** — that is exactly what CI sees:

```bash
pytest tests/ -m unit -q                       # fast offline suite (~60s)
pytest tests/ -m integration -q                # needs running stack
pytest tests/test_routing_accuracy.py -v       # 29 canonical routing cases
pytest tests/test_admin_ontology_endpoints.py  # 13 admin endpoint tests
```

Key test files:

| File | Tests | What it covers |
|---|---|---|
| `test_routing_accuracy.py` | 29 | All 20+ intents + 5 override scenarios + 4 audit invariants |
| `test_routing_contract.py` | 51 | Every question-shape → intent rule, its precedence order, and a scan proving no building literals |
| `test_survey_aligned_phases.py` | 64 | Capability KB + persona + workflow wiring |
| `test_compound_query_e2e.py` | 17 | Multi-intent heuristic + decomposition |
| `test_coreference_rewrite.py` | 16 | Follow-up query rewrite gate + LLM mock |
| `test_grounding_guard.py` | 47 | Refusing unrelated passages; floor/space/equipment/measurand existence gate; verb-inflection matching; the "I don't hold that fact" caveat |
| `test_referent_resolver.py` | 12 | Named zone/room existence gate + fail-open behaviour |
| `test_absent_referent_metrics.py` | 18 | A count/reading question about a place the building lacks is declined, not answered with whole-building figures — even when the existence check itself times out |
| `test_plausibility.py` | 11 | No confident verdict ("very strong") over a value outside every plausible range for its measurand |
| `test_self_description.py` | 16 | "What is OntoSage / what can you do / how do you work" answered from live configuration as a building-agnostic framework — never invented, never claiming to be a bare LLM |
| `test_ontology_inventory.py` | 18 | "What equipment / sensors does this building have" answered from the graph's own Brick classes |
| `test_entity_label_resolution.py` | 12 | A sensor named in prose resolves to the one asked about, across two different naming conventions |
| `test_data_query_bypass.py` | 4 | A reading question reaches the data path regardless of the measurand's wording |
| `test_agents_building_agnostic.py` | 2 | A source scan proving no agent names a building in code |
| `test_embedding_standardisation.py` | 14 | Retrieval floor and vector width derive from the loaded model, not a hardcoded constant |
| `test_embedding_consistency.py` | 9 | Boot-time sweep drops any Qdrant collection built at a different width, for any building |
| `test_document_indexer_hygiene.py` | 7 | Documents in any editor encoding are indexed; deleted-document folders are never treated as a building |
| `test_admin_ontology_endpoints.py` | 13 | Admin portal endpoints, auth enforcement |
| `test_forwarded_user_rbac.py` | 8 | Per-user RBAC through the shared-key proxy; header ignored when untrusted; placeholder stubs never shadow real accounts |
| `test_admin_password_reset.py` | 5 | Argon2id reset, session revocation, minimum length, non-recoverability |
| `test_ttl_validator.py` | 10 | TTL parse, prefix/namespace, SHACL gating |

**Cross-building regression harness** — one command proves a change didn't break any building:

```bash
python scripts/regression_harness.py --record   # capture a behavioural baseline for the active building
python scripts/regression_harness.py            # compare against it; non-zero exit on any regression
```

It fills 14 fixed checks from the *active* building's own graph (a real room, floor and measurand,
discovered by SPARQL), so the same set runs on any building — including one onboarded tomorrow.
It compares behaviour (route taken, whether live data was reached, answered-vs-declined), not
answer text, and flags an honest decline that turns into an answer as a fabrication risk. A baseline
is recorded per building under `tasks/regression_baselines/`.

**Live tests (needs running stack):**
```bash
python scripts/corpus_replay.py --sample 240   # stratified 240-question replay (~63.8% pass)
python scripts/ontosage_qa_suite.py --quick    # persona × intent QA battery
```

---

## What's new

### Conversational vocabulary + schema-driven console (2026-07-17)

| Change | Detail |
|---|---|
| **OCBV 2.0 schema** | `input/ontosage_schema.ttl` — the single, publication-ready (CC-BY-4.0) *Conversational Building Vocabulary* over Brick: capabilities, HBCO conversation concepts (folded in), stakeholder roles, question-intent grammar, report-intake, answer-provenance, competency questions + example SPARQL, Brick/REC/BOT/SOSA alignment, SHACL shapes |
| **Schema-driven authoring** | The "Add capability" Type dropdown **and** form fields are generated live from the OCBV classes + datatype-property domains (`/api/v1/admin/capabilities` → `types`/`form_fields`), falling back to a built-in list if GraphDB is down |
| **Schema indexed for RAG** | The similarity index's `documentText` now includes each term's comment/definition/example/lay-terms/competency-question, so a plain-English question matches the right OCBV term and the retriever hands its example SPARQL to the LLM |
| **Sensors persist TTL-first** | GUI-registered sensors are written to `input/db_<key>_sensors.ttl` (source of truth) and synced to GraphDB — they survive a restart/volume reset. Re-registering upserts (no duplicate triples) |
| **Automatic semantic reindex** | Adding sensors / uploading TTL / startup triggers a **debounced** similarity-index rebuild that **self-creates** on a fresh volume (delete+create; the in-place trigger hangs on GraphDB 10.7.4). A `similarity-status` endpoint + console banner show when new data is searchable |
| **Building-identity GUI** | Set/view `ontology_namespace` + prefix in the console (written to `building.yaml`) instead of hand-editing — the per-building onboarding prerequisite |
| **Building-agnostic retrieval fix** | `graphdb_retriever` + the SPARQL-agent prompts now resolve the `bldg:` namespace from `settings.BUILDING_NAMESPACE`/`BUILDING_PREFIX` (was a hardcoded abacws literal) — semantic retrieval now works for any building |
| **Build provenance** | Each built image bakes `GIT_SHA`/`BUILD_TIME`; `/health` reports `build.sha`/`build.time` so an operator knows exactly which commit is running |

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
| **Self-registration default role** | `/auth/register` grants `occupant` (was `readonly`, which couldn't call `/chat`) |
| **Export download auth** | `/api/files/{filename}` now requires `export:read` (was unauthenticated) |
| **Per-account login lockout** | `LOGIN_MAX_ATTEMPTS` failed logins locks a username for `LOGIN_LOCKOUT_SECONDS`, independent of the per-IP rate limiter |
| **Proxy-aware, replica-safe rate limiting** | `RateLimitMiddleware` only trusts `X-Forwarded-For` from `TRUSTED_PROXY_CIDRS`; counts via Redis when connected (falls back to in-process otherwise) |
| **delete_user Redis cleanup** | Uses the tracked per-user conversation index + a targeted `SCAN` instead of a blocking `KEYS conversation:*` scan; the admin delete-user endpoint now revokes sessions too (previously left them valid up to 7 days) |
| **Password minimum length** | Raised from 6 to 12 characters |
| **Legacy RBAC stack removed** | `middleware/rbac.py` now exports only `UserContext` + `ROLE_PERMISSIONS`; the unwired, defective JWT/in-memory stack (`TokenManager`, `RBACMiddleware`, `UserStore`, `create_rbac_dependency`) is gone |

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

## Switching buildings

Each building is a trio of files: a data folder, an env file, and a compose file. Exactly one
building is *active* at a time, and activation is just naming: the active trio is `input/`,
`.env` and `docker-compose.yml`. Everything else stays parked.

```
bldg1/  .env1  docker-compose.bldg1.yml     ← parked
bldg2/  .env2  docker-compose.bldg2.yml     ← parked
input/  .env   docker-compose.yml           ← ACTIVE (this was bldg3/, .env3, …)
```

The folders and compose files are in git; the `.env*` files are **not** — they hold secrets, so
each machine keeps its own. On a fresh clone you create `.env` from `.env.example` plus the
building's `env.building` block (see [Quick start](#1-activate-a-building));
after that first setup, parking a building keeps its `.envN` around for next time.

To switch, **stop the running stack first** — renaming underneath a live container breaks its
mounts — then swap the names:

```bash
docker compose down                                    # stop the current building
mv input bldg3 && mv .env .env3                        # park it under its OWN id
mv docker-compose.yml docker-compose.bldg3.yml
mv bldg1 input && mv .env1 .env                        # activate the next one
mv docker-compose.bldg1.yml docker-compose.yml
docker compose up -d
```

Before booting, the three identity sources must agree: `BUILDING_ID` in `.env`, `building_id`
in `input/building.yaml`, and the `@prefix bldg:` in the TTL matching `ontology_namespace`.
Each building's copy is recorded in `<folder>/env.building`, and the orchestrator hard-fails
on a mismatch rather than answering from the wrong graph.

**State stays isolated per building** under `volumes/<building_id>/` — GraphDB, Qdrant, Redis,
Postgres and Mongo each get their own directory, so switching back finds everything intact.
Compose refuses to start if `BUILDING_ID` is unset, so a missing env can never mount one
building's data into another's stack.

`scripts/swap_building.py --to <id> --dry-run` performs the same identity validation
non-destructively (exit code 2 on a mismatch) if you prefer a scripted check.

---

## Documentation map

| Doc | Audience | Scope |
|---|---|---|
| **[CLAUDE.md](./CLAUDE.md)** | AI assistants / contributors | **Read first.** Navigation index (file:symbol), current branch state, debugging patterns, workflow rules, open issues |
| **README.md** (this file) | New users | Quickstart, stakeholder question guide, data setup, admin portal, RBAC |
| **[ONTOSAGE.md](./ONTOSAGE.md)** | Operators + contributors | Complete technical reference — all architecture, phases, config surface, tests, known issues |
| **[docs/CAPABILITY_ROUTING.md](./docs/CAPABILITY_ROUTING.md)** | Contributors | Capability routing (TTL-first single path) + document-KB thresholds |
| **[docs/RUNBOOK.md](./docs/RUNBOOK.md)** | Operators | Incident runbook — what to do when things break |
| **[.claude/rules/](./.claude/rules/)** | Contributors | Style + agent + API + SPARQL patterns |

**For AI-assisted code review or bug fixing:** read all three core files (`CLAUDE.md` → `README.md` → `ONTOSAGE.md`) before touching code. `CLAUDE.md`'s Navigation Index tells you exactly which file and symbol to open for any task — without it you'll spend tool calls searching.

---

## Known issues

| Issue | Status |
|---|---|
| Maintenance agent "report broken light" | Open — returns generic fallback; workaround: be specific ("report broken light in room 3.01") |
| Service-history questions | Open — "when was X last serviced?" may file a maintenance ticket instead of answering |
| Related-but-partial answers | Open — a topical document may be returned without stating which specific fact (a date, a reading) is not held |
| MySQL host mode | MySQL runs on the Docker host (`host.docker.internal:3306`, database `sensordb`); the Docker MySQL service in `docker-compose.yml` is commented out |
| FLUSHDB wipes sessions | `redis-cli FLUSHDB` removes session tokens; users must log in again. Safe flush: target only `resp_cache:*` keys |

---

## License

MIT. Developed against Cardiff University's Abacws building (`bldg1`), with `bldg2` and `bldg3` as portability fixtures. Brick Schema is BSD-licensed.
