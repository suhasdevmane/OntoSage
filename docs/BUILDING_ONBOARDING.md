# Building Onboarding Guide

This guide takes a **new building admin** from zero to *asking your building questions in plain English*.
It reflects the current system: a **flat `input/` folder**, **auto-upload** of your ontology on boot, a
**GUI admin console**, and RBAC-gated auth. You can do the whole thing from the console (no code) or with
the CLI — both are covered.

> **Two ways to onboard:**
> **Path A — Admin Console** (`http://localhost:3001`) — recommended, no code, no Turtle by hand.
> **Path B — Files + CLI** — scriptable / CI. Both write the same `input/` files.

---

## 1. The mental model (read this first)

OntoSage answers from **your building's own data**. A question is answerable when **both halves** exist:

```
(a) the sensor is a triple in the ontology (GraphDB)      — "there IS a CO₂ sensor in room 3.04"
        AND
(b) its readings are rows in a registered database         — linked by ref:hasTimeseriesId + ref:storedAt
```

- A DB full of rows with **no ontology** is invisible. An ontology with **no rows** has nothing to read.
- If a half is missing, OntoSage says **"no data"** honestly — it never invents a number. (You'll verify
  exactly this in [§9](#9-verify--the-two-half-test).)

Two facts that make everything else simpler:

- **Building identity = the namespace.** The `bldg:` prefix in your TTL is just a *label*; the
  **namespace** it binds to is what makes triples belong to *this* building. It lives in
  **`input/building.yaml`** (`ontology_namespace`) and is the single most important setting.
- **Everything for the active building lives under `input/` (flat layout).** Drop files there; the stack
  loads them on boot. There is no per-building GraphDB repository to create and no manual RDF import.

---

## 2. Before you start

| Need | Notes |
|---|---|
| Docker stack running | `docker compose up -d` (see the [Quick start](../README.md)) |
| Real secrets in `.env` | `STRICT_SECRETS=true` refuses to boot on defaults — set `SECRET_KEY`, `GRAPHDB_PASSWORD`, `MYSQL_PASSWORD`, `POSTGRES_USER_PASSWORD` |
| An **admin account** | Set `ADMIN_USERNAME` / `ADMIN_PASSWORD` (12+ chars) in `.env`, or create one via `POST /api/v1/admin/users`. Needed for the console and admin APIs. |
| Your building's **ontology** | A Turtle (`.ttl`) Brick/BACnet (or REC/223/Haystack/custom) model — see [§4](#4-prepare-your-ontology-ttl) |
| Your **time-series DB** details | Host, port, credentials, table — for *live* readings (optional if you only want structural Q&A) |
| Floor plans (optional) | `.pdf` and/or `.dwg` for spatial questions |

---

## 3. The `input/` folder — file by file (flat layout is canonical)

The active building's files sit **directly** under `input/`. Absent optional files just disable that
feature — nothing breaks.

| File | Required | Purpose |
|---|---|---|
| `building.yaml` | ✅ | Building id, name, **ontology namespace + prefix**, actuation block |
| `*.ttl` (e.g. `<bldg>_model.ttl`) | ✅ | Your Brick/BACnet model + sensor `ref:` links — **auto-uploaded on boot** |
| `database_registry.yaml` | ✅ for live data | Maps each `ref:storedAt` key → a real DB connection + adapter |
| `ontosage_schema.ttl` | ✅ (shipped) | The **OCBV** conversational vocabulary — keep it |
| `<bldg>_capabilities.ttl` | optional | Amenities / knowledge topics (or author them in the console) |
| `documents/*.md` | optional | Policy / manual / contact prose → document KB (answers off-ontology questions) |
| `*.dwg` / `*.pdf` | optional | Floor-plan geometry + text → spatial queries |
| `concepts.ttl` | optional | Per-building lay-term overlay (e.g. your local word for "stuffy") |
| `feeds.yaml`, `rules.yaml`, `channels.yaml` | optional | Live external feeds, ECA alert rules, notification channels |
| `intents.yaml`, `personas/*.yaml` | optional | Per-building intent overlay / persona priors |

> **Sensor readings never go in `input/`.** `input/` is metadata/config only. Readings live in a
> database and are referenced from the ontology via `ref:hasTimeseriesId` + `ref:storedAt`.
>
> The nested form `input/<building_id>/…` is still supported as a fallback (staging / future
> multi-building), but **flat is the canonical layout** — put files directly in `input/`.

---

## 4. Prepare your ontology (TTL)

OntoSage reads your existing classes and relationships as-is — Brick, RealEstateCore (`rec:`),
ASHRAE 223P (`s223:`), Project Haystack (RDF), or any custom RDF vocabulary.

**Minimum your model needs:**

1. **Typed sensor declarations** — the `@prefix` must equal your `ontology_namespace` exactly:
   ```turtle
   @prefix bldg:  <http://example.com/mybuilding#> .          # == ontology_namespace in building.yaml
   @prefix brick: <https://brickschema.org/schema/Brick#> .
   @prefix rdfs:  <http://www.w3.org/2000/01/rdf-schema#> .

   bldg:sensor_001 a brick:Temperature_Sensor ;
       rdfs:label "Zone 5 Temperature Sensor" .
   ```

2. **Time-series linkage** — connects each sensor to its DB identifier. This is **half (b)**:
   ```turtle
   @prefix ref: <https://brickschema.org/schema/Brick/ref#> .

   bldg:sensor_001 ref:hasExternalReference _:ref_001 .
   _:ref_001 ref:hasTimeseriesId "a8df8757-009a-4c3b-b1f2-ec59f8ce3e21" ;   # UUID in your DB
             ref:storedAt bldg:database1 .                                  # → registry key "database1"
   ```
   The `ref:storedAt` value maps to a key in `input/database_registry.yaml`; the namespace is stripped,
   so `bldg:database1` resolves to the key **`database1`**.

3. **Spatial hierarchy** (optional, enables zone/floor answers):
   ```turtle
   bldg:sensor_001 brick:isPartOf bldg:zone_501 .
   bldg:zone_501 a brick:HVAC_Zone ; brick:isPartOf bldg:floor_5 .
   bldg:floor_5  a brick:Floor      ; brick:isPartOf bldg:building_main .
   ```

**Validate locally before you load** (catches parse errors early):
```bash
python -c "from rdflib import Graph; g=Graph(); g.parse('mybuilding.ttl', format='turtle'); print(len(g),'triples')"
```

> ⚠️ The startup **TTL validator hard-fails the boot** if a TTL's `@prefix bldg:` disagrees with
> `ontology_namespace`. That's a feature — you can never get a silently-empty graph — but it means the
> two must match exactly.

---

## Path A — Admin Console (recommended, no code)

The console at **`http://localhost:3001`** does the whole onboarding in a GUI. Sign in with your admin
account first (read-only tabs work without it; anything that writes needs `system:admin`).

### 5A. Set the building identity
**Ontology tab → Building identity** — set the **namespace**, **prefix**, and **name**. This writes
`input/building.yaml`. Do it **first**, before loading triples. Applies after an orchestrator restart.

### 6A. Load your ontology
**Ontology tab → Upload TTL** — paste your Turtle, **Validate**, then **Upload**. It's stored to
`input/<file>` (survives restart) and loaded into a named graph. *(Alternatively, drop the `.ttl` into
`input/` and restart — it auto-uploads; see [§6](#6-load--index-happens-automatically).)*

### 7A. Connect the database + register sensors
**Databases tab → Guided setup** — a 3-step wizard: connect a database → describe its sensors (points
form, CSV, or Brick TTL) → verify. Each sensor gets a `ref:storedAt bldg:<key>` triple so its queries
route to that DB. Credentials are stored in `.env`.

### 8A. (Optional) Author capabilities & watch indexing
- **Ontology tab → + Add capability** — a schema-driven form (from the [OCBV schema](../input/ontosage_schema.ttl))
  for amenities / procedures ("prayer room", "how to report a fault"). Saved to
  `input/<bldg>_capabilities.ttl`, answerable immediately.
- **Ontology tab → Semantic search index** — shows when newly-added data has finished indexing. It
  **rebuilds automatically** (debounced) after edits; exact name/type questions work instantly.

### 9A. (Optional) Add documents & floor plans — no host-side file drop
The **Ontology tab** now uploads these directly from the browser (each writes into the active
building's `input/` and re-indexes automatically — no restart, no editing files on the host):
- **Documents** — a `.md` / `.txt` / `.pdf` policy, manual, or contact sheet → the document KB
  (Qdrant `documents_<bldg>`), answering off-ontology questions ("what's the wifi policy?"). Saved to
  `input/documents/`. `POST /api/v1/admin/documents/upload`.
- **Floor plans** — a PDF or DWG per floor → spatial / floor queries and geometry. Stored as
  `<label> floor <N>.<ext>` (label defaults to the active building id) and ingested into the manifest
  registry. `POST /api/v1/admin/floor-plans/upload`.

This closes the last host-side gap: **the entire onboarding — identity, TTL, sensors/DB, documents,
floor plans — is now doable from the Admin Console for any building.**

Then jump to [§9 Verify](#9-verify--the-two-half-test).

---

## Path B — Files + CLI (scriptable / CI)

### 5B. Generate the building config
```bash
python scripts/onboard_building.py --building-id bldg2 --non-interactive
# writes an input/building.yaml skeleton — then set ontology_namespace / ontology_prefix in it
```

`input/building.yaml` (the source of truth for identity):
```yaml
building_id:        bldg2
building_name:      Science Tower
ontology_namespace: "http://example.com/bldg2#"   # must end with '#' or '/', match your TTL @prefix
ontology_prefix:    bldg                            # the SPARQL prefix label
```

### 6B. Drop your files into `input/`
- Your model → `input/<anything>.ttl` (auto-loaded on boot).
- Register the DB → add an entry to `input/database_registry.yaml` (see [§7](#7-connect-the-time-series-database)).
- Optional: `input/documents/*.md`, `*.pdf`/`*.dwg`, `input/<bldg>_capabilities.ttl`.

### 7B–8B. Swap to the new building and restart
```bash
python scripts/swap_building.py --to bldg2 --dry-run    # validates TTL @prefix ↔ ontology_namespace; writes nothing
python scripts/swap_building.py --to bldg2 --archive    # updates .env (BUILDING_ID), archives old input, flushes cache
docker compose restart orchestrator                     # TTL validator runs first; auto-upload loads your TTLs
docker compose logs -f orchestrator | grep -Ei "ttl_validator|ttl_uploader"
```
The swap exits non-zero if `building.yaml` lacks required keys, `building_id` ≠ the declared id, or any
TTL prefix disagrees with `ontology_namespace`.

---

## 6. Load & index — happens automatically

You do **not** create a GraphDB repository or import RDF by hand. On boot:

- **Auto-upload:** the `ttl_uploader` discovers your `input/*.ttl` (any filename that isn't a shared
  schema) and loads each into a named graph inside the single repository (`GRAPHDB_REPOSITORY`, default
  `bldg`). Re-uploads only when a file's content changes (SHA-based).
- **Semantic index:** the similarity index that powers meaning-based sensor search **builds and
  self-heals automatically** (debounced) whenever you add sensors or upload TTL. Exact name/type
  questions work immediately; semantic ones become available once indexing finishes (watch the console's
  *Semantic search index* panel).

**If you ever need to rebuild the index manually,** use the console's **Ontology → Semantic search index
→ Rebuild now**. ⚠️ **Do not** run the old `similarity:rebuildIndex` SPARQL — it stalls the index. The
supported rebuild is delete-and-recreate, which the console button does for you.

---

## 7. Connect the time-series database

Add an entry to **`input/database_registry.yaml`** mapping the `ref:storedAt` key from your TTL to a real
connection. Credentials come from `.env`.

```yaml
databases:
  database1:                              # key referenced in TTL: ref:storedAt bldg:database1
    type: mysql                           # mysql | postgresql | timescaledb | mongodb | influxdb | sqlite | cassandra | redis_timeseries
    host: "${MYSQL_HOST:-host.docker.internal}"
    port: "${MYSQL_PORT:-3306}"
    user: "${MYSQL_USER:-root}"
    password: "${MYSQL_PASSWORD:-}"
    database: "${MYSQL_DATABASE:-sensordb}"
```

| Type key | Technology | Driver |
|---|---|---|
| `mysql` | MySQL, MariaDB, TiDB | `aiomysql` |
| `postgresql` | PostgreSQL, Aurora, Neon, Supabase, CockroachDB | `asyncpg` |
| `timescaledb` | TimescaleDB hypertables | `asyncpg` |
| `mongodb` | MongoDB, Atlas, DocumentDB | `motor` |
| `influxdb` | InfluxDB 2.x | `influxdb-client` |
| `sqlite` | SQLite, DuckDB | `aiosqlite` |
| `cassandra` | Cassandra, ScyllaDB, AstraDB | `cassandra-driver` |
| `redis_timeseries` | Redis + RedisTimeSeries | `redis.asyncio` |

A new backend is **a new adapter**, never an edit to the agents.

---

## 8. Authenticate

Every data endpoint is RBAC-gated — there is no unauthenticated data path.

- **Chat UI:** open OpenWebUI at `http://localhost:3000` and sign in.
- **API (session token):**
  ```bash
  TOKEN=$(curl -s -X POST http://localhost:8000/auth/login \
    -H "Content-Type: application/json" \
    -d '{"username":"admin@yourorg.com","password":"<password>"}' \
    | python -c "import sys,json;print(json.load(sys.stdin)['data']['session_token'])")
  curl -s -X POST http://localhost:8000/chat -H "Authorization: Bearer $TOKEN" \
    -H "Content-Type: application/json" \
    -d '{"message":"how many temperature sensors are there?","session_id":"probe"}'
  ```
- **OpenAI-compatible endpoint** (`/v1/chat/completions`) authenticates with the pipeline key
  (`PIPELINE_API_KEY` in `.env`) via `Authorization: Bearer <key>`.

---

## 9. Verify — the two-half test

Run these in order. Together they prove building-agnosticism *and* the honest "no data" behavior.

**A. Structural (ontology only — works even with no database):**
> "What sensor types does this building have?" · "How many temperature sensors are there?"

Expected: a list / count computed from *your* graph. If empty → the TTL didn't load (check
`ttl_uploader` logs and that `@prefix` matches `ontology_namespace`).

**B. Live reading (needs both halves):**
> "What is the temperature right now?"

Expected: a live value **if** the database is registered and has rows; otherwise an honest **"no data /
not loaded."** *This is the grounding gate — a sensor in the graph with no rows should say so, not
guess.*

**C. Analytics:** "What was the average CO₂ yesterday?" → a computed statistic (needs half (b) + the
code-executor at `:8002`).

**D. Capability / spatial (if provided):** "Where's the nearest quiet room?" · "Show me floor 3."

---

## 10. Onboarding checklist

- [ ] `input/building.yaml` present; `ontology_namespace` set and matching every TTL `@prefix`
- [ ] Model `.ttl` in `input/`; auto-uploaded on boot (triple count > 0)
- [ ] Every sensor has `ref:hasTimeseriesId` + `ref:storedAt`
- [ ] Each `ref:storedAt` key exists in `input/database_registry.yaml` with working credentials
- [ ] Admin account works; you can get a session token
- [ ] **Structural** query returns your sensor classes (Test A)
- [ ] **Live** query returns a reading *or* an honest "no data" (Test B)
- [ ] (Optional) capabilities authored; floor plans ingested; semantic index shows *built*

---

## 11. Switching the active building

OntoSage v1 serves **one active building at a time** (`BUILDING_ID`). To switch safely:

```bash
python scripts/swap_building.py --to <id> --dry-run   # validate prefix ↔ namespace, write nothing
python scripts/swap_building.py --to <id> --archive   # apply: update .env, archive old input, flush cache
docker compose restart orchestrator
```

Per-building overlays (`intents.yaml`, `personas/*.yaml`, `concepts.ttl`, `feeds.yaml`, …) are picked up
at startup — no code changes.

---

## Troubleshooting

**"No sensors found" / empty structural answer**
- Check the model loaded: `docker compose logs orchestrator | grep -i ttl_uploader` (look for *Uploading*
  / *Already up to date*). If nothing, the file may be named/placed wrong — put it directly in `input/`.
- Confirm the TTL validator passed (no boot hard-fail): `... | grep -i ttl_validator`.
- Verify `@prefix bldg:` equals `ontology_namespace` in `building.yaml` **exactly**.

**SPARQL answers but live readings are empty (half (b) missing)**
- The `ref:hasTimeseriesId` UUIDs must match the identifiers in your database.
- The `ref:storedAt` key must match a key in `input/database_registry.yaml` exactly.
- Test the DB from inside the stack:
  ```bash
  docker exec -it ontosage-orchestrator python -c "
  import asyncio; from orchestrator.services.adapters.registry import AdapterRegistry
  async def t():
      r=AdapterRegistry(); await r.initialize()
      print(await (await r.get_adapter('database1')).health_check())
  asyncio.run(t())"
  ```

**Semantic search seems stale / "index not found"**
- Use **Ontology → Semantic search index → Rebuild now** in the console. **Never** run the
  `similarity:rebuildIndex` SPARQL — it hangs the index. The index also self-heals on boot.

**Boot hard-fails**
- Prefix/namespace mismatch (see above), or a default secret with `STRICT_SECRETS=true` — set real
  secrets in `.env`.

**401 on a query**
- You're unauthenticated. Get a session token (`/auth/login`) or use `PIPELINE_API_KEY` on
  `/v1/chat/completions`. New accounts default to `occupant` (can chat); admin actions need `system:admin`.

**TTL parse errors** — validate with rdflib (see [§4](#4-prepare-your-ontology-ttl)); common causes:
missing `@prefix`, trailing commas, unescaped characters or spaces in URIs.

---

## See also
- [Configuration](CONFIGURATION.md) · [Adding a data source](ADDING_A_DATA_SOURCE.md) ·
  [Capability routing](CAPABILITY_ROUTING.md) · [GraphDB setup](GRAPHDB_SETUP.md)
- Published docs: the [Onboard a building](https://suhasdevmane.github.io/docs/onboarding-building/) and
  [Admin console](https://suhasdevmane.github.io/docs/admin-console/) pages mirror this guide.
