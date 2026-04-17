# Building Deployment Bootstrap — Design Spec

**Date:** 2026-04-14
**Status:** Approved
**Approach:** A — Docker init-container bootstrap

---

## 1. Problem Statement

OntoSage currently requires manual code changes to deploy at a new building site:
- GraphDB repository name is hardcoded
- SPARQL namespace (`http://abacwsbuilding.cardiff.ac.uk/abacws#`) is baked into query templates
- Database credentials are scattered across `.env` and agent files
- No automated first-boot sequence to ingest TTL into GraphDB and Qdrant
- The existing `onboard_building.py` is a manual interactive CLI, not integrated into Docker startup

**Goal:** A site installer drops in a TTL file + one YAML config, sets `BUILDING_ID` in `.env`, runs `docker compose up`, and the system is fully operational. Zero code changes required between buildings.

---

## 2. Deployment Model

**One Docker stack per building site.** Each building runs its own copy of all containers (orchestrator, GraphDB, Redis, Qdrant, code-executor) on local hardware. A new building = a new stack instance, not a new tenant in a shared cloud stack.

---

## 3. Operator Workflow (complete)

```bash
# 1. Drop in the TTL
cp /path/to/newbuilding.ttl input/bldg2.ttl

# 2. Create building config from template
cp config/buildings/bldg1.yaml config/buildings/bldg2.yaml
# Edit: id, name, namespace, prefix, abox_file, storage.databases entries

# 3. Set building identity + DB secrets
echo "BUILDING_ID=bldg2" >> .env
echo "DB1_HOST=192.168.1.10" >> .env
echo "DB1_PASS=secret" >> .env

# 4. Start
docker compose up -d
# bootstrap runs, orchestrator waits, system is live
```

**Moving to a new building = steps 1–4. Zero code changes for the site installer** (once this spec is implemented).

---

## 4. Architecture

### Boot sequence

```
docker compose up
     │
     ├─► graphdb   (waits for healthy)
     ├─► qdrant    (waits for healthy)
     ├─► redis     (waits for healthy)
     ├─► databases (waits for healthy)
     │
     └─► bootstrap  (runs once, exits 0 or 1)
           1.  Read BUILDING_ID → load config/buildings/{id}.yaml
           2.  Validate YAML (BuildingConfig.validate())
           3.  Validate TTL exists + parseable (rdflib)
           4.  Auto-detect ontology schema (OntologySchemaDetector)
           5.  Create GraphDB repo — idempotent
           6.  Load TTL into GraphDB — idempotent (SHA-256 of TTL file stored in Redis; skip if hash unchanged)
           7.  Extract ref:storedAt values → cross-reference YAML databases
           8.  Build UUID → database_id mapping from TTL
           9.  Vectorize ontology into Qdrant — idempotent (collection exists check)
           10. Test connectivity for every database in storage.databases
           11. Write config/resolved/{id}.json
           12. Write Redis key bootstrap:{id}:ready = "1"
           13. EXIT 0

     └─► orchestrator  (starts only after bootstrap exits 0)
           - Reads BUILDING_ID → loads config/resolved/{id}.json
           - Registers with MultiBuildingConfigManager
           - Accepts traffic
```

### How Brick TTL drives multi-database routing

The TTL ontology uses `ref:storedAt` to name which database holds each sensor's time-series data:

```turtle
:TempSensor_01  brick:hasExternalReference [
    ref:hasTimeseriesId  "uuid-aaa-111" ;
    ref:storedAt         "sensors_mysql"
] .

:EnergyMeter_01  brick:hasExternalReference [
    ref:hasTimeseriesId  "uuid-bbb-222" ;
    ref:storedAt         "energy_postgres"
] .

:CO2_Sensor_01  brick:hasExternalReference [
    ref:hasTimeseriesId  "uuid-ccc-333" ;
    ref:storedAt         "air_influx"
] .
```

Bootstrap reads all `ref:storedAt` values, cross-references them against the YAML `storage.databases` list, and fails loudly if any value has no matching entry. At query time the SQL agent uses the resolved UUID→DB mapping to route each query to the correct backend.

---

## 5. Config Schema

### `config/buildings/{building_id}.yaml`

```yaml
# ─── Identity ────────────────────────────────────────────────────────────────
building:
  id: bldg2                              # used as GraphDB repo name + Redis key prefix
  name: "Science Tower, Cardiff"
  namespace: "http://example.org/bldg2#" # must match URIs inside the TTL
  prefix: bldg2                          # SPARQL PREFIX shorthand
  timezone: "Europe/London"
  abox_file: "input/bldg2.ttl"          # path relative to project root
  tbox_file: ""                          # optional TBox / schema TTL

# ─── Ontology ────────────────────────────────────────────────────────────────
ontology:
  schema: auto           # brick | s223 | rec | custom | auto (auto = ontology_detector.py)
  graphdb_repo: bldg2    # defaults to building.id if omitted

# ─── GraphDB ─────────────────────────────────────────────────────────────────
graphdb:
  url: "${GRAPHDB_URL}"
  username: ""
  password: ""

# ─── Time-Series Databases ───────────────────────────────────────────────────
storage:
  default: sensors_mysql  # used when ref:storedAt is absent in TTL

  databases:

    - id: sensors_mysql                  # matches ref:storedAt value in TTL
      backend: mysql
      host: "${DB1_HOST}"
      port: 3306
      database: abacws_db
      username: "${DB1_USER}"
      password: "${DB1_PASS}"
      table: sensor_data
      columns:
        uuid: uuid
        value: value
        timestamp: time
        sensor_name: sensor_name

    - id: energy_postgres
      backend: postgresql
      host: "${DB2_HOST}"
      port: 5432
      database: energy_db
      username: "${DB2_USER}"
      password: "${DB2_PASS}"
      table: energy_readings
      columns:
        uuid: sensor_id
        value: reading
        timestamp: recorded_at
        sensor_name: name

    - id: air_influx
      backend: influxdb
      host: "${DB3_HOST}"
      port: 8086
      bucket: air_quality
      org: "${INFLUXDB_ORG}"
      token: "${INFLUXDB_TOKEN}"
      measurement: air_sensors
      columns:
        uuid: sensor_uuid
        value: field_value
        timestamp: _time
        sensor_name: sensor_tag

    - id: hvac_timescale
      backend: timescaledb              # PostgreSQL wire protocol
      host: "${DB4_HOST}"
      port: 5432
      database: hvac_db
      username: "${DB4_USER}"
      password: "${DB4_PASS}"
      table: hvac_hypertable
      columns:
        uuid: device_id
        value: measurement
        timestamp: ts
        sensor_name: device_name

# ─── Optional: extra SPARQL prefixes ────────────────────────────────────────
extra_prefixes:
  - prefix: brick
    uri: "https://brickschema.org/schema/Brick#"
  - prefix: ref
    uri: "https://brickschema.org/schema/BrickFrame#"
```

### Secrets model

All values that vary per site and contain credentials use `${VAR}` syntax in the YAML. The bootstrap script resolves these from environment variables at load time. Secrets never appear in the YAML file.

```bash
# .env (per-site, never committed)
BUILDING_ID=bldg2
GRAPHDB_URL=http://graphdb:7200
DB1_HOST=192.168.1.10
DB1_USER=ontosage
DB1_PASS=secret
DB2_HOST=192.168.1.11
# ...
```

---

## 6. New File: `scripts/bootstrap.py`

Replaces the manual `onboard_building.py` interactive flow. Designed to run as a Docker init container.

### Responsibilities
- Env var substitution in YAML values
- Full config + TTL validation before touching any service
- Idempotent GraphDB repo creation and TTL loading (SHA-256 hash stored in Redis; skip re-load if unchanged)
- Idempotent Qdrant vectorization (collection exists check)
- Cross-referencing TTL `ref:storedAt` values against YAML database list
- Writing `config/resolved/{id}.json` (merged, fully-resolved config + UUID→DB map)
- Writing Redis ready stamp

### Key reused services
- `orchestrator.services.ontology_detector.OntologySchemaDetector` — schema auto-detection
- `orchestrator.services.ontology_introspector.OntologyIntrospector` — UUID/namespace extraction
- `orchestrator.services.multi_building_manager.BuildingConfig.validate()` — YAML validation
- `orchestrator.services.adapters.registry` — DB adapter registration

### Error behaviour
Bootstrap exits 1 on any failure with a human-readable message. The orchestrator's
`depends_on: bootstrap: condition: service_completed_successfully` prevents it from
starting if bootstrap failed.

---

## 7. Orchestrator Changes

### `shared/config.py`
Add one new field:
```python
BUILDING_ID: str = "bldg1"    # which building config this instance serves
```

### `orchestrator/main.py` — lifespan startup
```python
# After Redis is available, before accepting HTTP traffic:
ready = await redis.wait_for_key(f"bootstrap:{settings.BUILDING_ID}:ready", timeout=120)
if not ready:
    raise RuntimeError(f"Bootstrap did not complete for {settings.BUILDING_ID}")

resolved = load_resolved_config(settings.BUILDING_ID)   # reads config/resolved/{id}.json
building_manager.register(resolved)
```

### Hardcoded string cleanup
Grep for the 3–4 occurrences of the Cardiff namespace and `"bldg1"` literals in
`sparql_agent.py` and `main.py`. Replace with:
- `building_config.namespace`
- `building_config.id`
- `building_config.sparql_prefix_block` (already implemented on BuildingConfig)

No agent logic changes — only the string sources change.

---

## 8. `docker-compose.yml` Changes

```yaml
bootstrap:
  build:
    context: .
    dockerfile: orchestrator/Dockerfile
  command: python scripts/bootstrap.py
  environment:
    - BUILDING_ID=${BUILDING_ID}
    - GRAPHDB_URL=${GRAPHDB_URL}
    - DB1_HOST=${DB1_HOST}
    - DB1_USER=${DB1_USER}
    - DB1_PASS=${DB1_PASS}
    # add remaining DB vars as needed
  volumes:
    - ./input:/app/input
    - ./config:/app/config
  depends_on:
    graphdb:    { condition: service_healthy }
    qdrant:     { condition: service_healthy }
    redis:      { condition: service_healthy }
  restart: "no"

orchestrator:
  depends_on:
    bootstrap: { condition: service_completed_successfully }
    # existing deps remain unchanged
```

---

## 9. Error Messages (fast-fail at boot)

| Mistake | Message in `docker compose logs bootstrap` |
|---|---|
| `BUILDING_ID` not set | `BUILDING_ID env var not set — cannot start` |
| YAML file missing | `Config not found: config/buildings/bldg3.yaml` |
| TTL file path wrong | `abox_file 'input/bldg3.ttl' does not exist` |
| DB unreachable | `Cannot connect to energy_postgres at 10.0.0.5:5432 — check DB2_HOST` |
| TTL references unknown DB | `TTL ref:storedAt 'air_influx' has no entry in bldg3.yaml storage.databases` |
| GraphDB not running | `GraphDB not healthy after 60s — is graphdb service running?` |
| TTL parse error | `Failed to parse input/bldg3.ttl: [rdflib error]` |

---

## 10. Files Changed / Added

### New files
```
scripts/bootstrap.py
config/buildings/bldg1.yaml    (converted from existing config/building_config.yaml)
config/buildings/bldg2.yaml    (template for new buildings)
```

### Modified files
```
docker-compose.yml             add bootstrap service + orchestrator dependency
shared/config.py               add BUILDING_ID env var
orchestrator/main.py           add bootstrap stamp wait in lifespan
.env.example                   document BUILDING_ID + per-DB vars
.gitignore                     add config/resolved/
```

### Not touched
```
orchestrator/workflow.py
orchestrator/agents/           (all 10 agent files)
orchestrator/services/         (all 23 service files — including multi_building_manager.py,
                                ontology_detector.py, ontology_introspector.py,
                                database_adapter.py — these are reused, not changed)
orchestrator/middleware/
shared/models.py
rag-service/
code-executor/
tests/                         (existing tests unaffected)
```

---

## 11. Remaining Sub-Projects (deferred)

The following were identified during scoping but are out of scope for this spec.
Each will get its own spec → plan → implementation cycle:

| # | Sub-project |
|---|---|
| 2 | MCP Server Layer (SPARQL/SQL/ontology as MCP tools) |
| 3 | LangGraph Modernization (checkpointing, streaming, interrupts, subgraphs) |
| 4 | Enhanced Retrieval (hybrid BM25+vector, reranking, query rewriting, eval harness) |
| 5 | Reliability & Observability (OpenTelemetry, Prometheus, SLO dashboards) |
| 6 | Config & Secrets Portability (Vault/Doppler integration, validated boot) |
| 7 | Custom Skills Pack (new-building onboarding, smoke testing, incident response) |
