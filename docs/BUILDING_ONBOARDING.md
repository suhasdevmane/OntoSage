# Building Onboarding Guide

This guide walks you through connecting a new building to OntoSage — from preparing your ontology files to running your first natural language query. The entire process takes 30–90 minutes depending on the size of your building's knowledge graph.

---

## Overview

OntoSage is designed to adapt to *your* building — not the other way around. You do not need to rewrite your databases or migrate your sensor data into a new schema. There are **three independent knowledge domains** — any subset works; failures in one domain never block the others:

| Domain | Files | What it enables |
|---|---|---|
| **Sensor data** | `.ttl` ontology + time-series database | "What's the CO₂ in zone 3.01 right now?", trends, anomalies, reports |
| **Floor plans** | `.pdf` and/or `.dwg` drawings | "Show me floor 3", room areas, adjacency, block/MEP locations |
| **Capability KB** *(v3.1)* | `capability.yaml` per building | "Fire procedures?", "Bike parking?", "Power outage behaviour?" — off-ontology questions |

The full process has four parts:

1. **Prepare your ontology** — the Turtle (`.ttl`) file that describes your building's structure
2. **Configure OntoSage** — point the system at your existing time-series database
3. **Load and index** — import the ontology into GraphDB and create the similarity search index
4. **(Optional) Author capability KB and floor plans** — drop YAML / PDF / DWG into `input/<bldg>/`

After these steps, users can ask natural language questions and receive answers drawn directly from your building's real data.

---

## What You Need Before You Start

| Item | Required | Notes |
|------|----------|-------|
| Building ontology file (`.ttl` or `.rdf`) | Yes (for sensor data) | ABox — building instances |
| Brick Schema or vocabulary file | Recommended | TBox — schema definitions |
| Time-series database connection details | Yes (for sensor data) | Host, port, credentials, table names |
| `capability.yaml` for the building | Optional (recommended) | Enables off-ontology Q&A — see Part 10 |
| Floor plans (`.pdf` / `.dwg`) | Optional | Enables spatial geometry queries |
| Docker stack running | Yes | `docker compose up -d` |
| GraphDB accessible | Yes | `http://localhost:7200` |
| Qdrant accessible | Yes (for capability KB) | `http://localhost:6333` |

---

## Part 1: Prepare Your Building Ontology

### Supported Ontology Schemas

OntoSage supports all major smart building ontology schemas out of the box:

| Schema | Description | Prefix |
|--------|-------------|--------|
| **Brick Schema** | BAS/HVAC-centric, sensor-to-space relationships | `brick:` |
| **RealEstateCore (REC)** | Commercial real estate, W3C-aligned | `rec:` |
| **ASHRAE 223P** | Mechanical systems, HVAC equipment | `s223:` |
| **Project Haystack (RDF)** | Tag-based, widely used in BMS | `ph:` |
| **Custom / Proprietary** | Any RDF vocabulary | Configurable |

If your building already has a Turtle file, you can use it directly. OntoSage reads your existing class names and relationships without requiring any changes.

### Minimum Ontology Requirements

Your ABox (building instance file) should contain:

1. **Sensor declarations** — each sensor as an RDF resource with a type:
   ```turtle
   @prefix bldg: <http://example.com/mybuilding#> .
   @prefix brick: <https://brickschema.org/schema/Brick#> .

   bldg:sensor_001 a brick:Temperature_Sensor ;
       rdfs:label "Zone 5 Temperature Sensor" .
   ```

2. **Time-series linkage** — a reference connecting each sensor to its UUID or identifier in your time-series database:
   ```turtle
   @prefix ref: <https://brickschema.org/schema/Brick/ref#> .

   bldg:sensor_001 brick:hasExternalReference _:ref_001 .
   _:ref_001 ref:hasTimeseriesId "a8df8757-009a-4c3b-b1f2-ec59f8ce3e21" ;
              ref:storedAt bldg:database1 .
   ```
   The `storedAt` value maps to a key in `config/database_registry.yaml` — this is how OntoSage knows *which database* to query for each sensor.

3. **Spatial relationships** (optional but recommended):
   ```turtle
   bldg:sensor_001 brick:isPartOf bldg:zone_501 .
   bldg:zone_501 a brick:HVAC_Zone ;
       rdfs:label "Zone 5.01" ;
       brick:isPartOf bldg:floor_5 .
   bldg:floor_5 a brick:Floor ;
       brick:isPartOf bldg:building_main .
   ```

### Linking Sensors to Your Database

The `ref:storedAt` predicate is the key mechanism for multi-building database routing. It maps each sensor to a named database entry:

```turtle
# In your TTL file:
_:ref_001 ref:storedAt bldg:database1 .   # routes to MySQL "database1" in registry
_:ref_002 ref:storedAt bldg:database2 .   # routes to PostgreSQL "database2" in registry
```

The registry key (e.g., `database1`) is resolved by stripping the namespace — `bldg:database1`, `<http://example.com/bldg#database1>`, and `<http://example.com/bldg/database1>` all resolve to key `database1`.

---

## Part 2: Run the Onboarding CLI

OntoSage includes an interactive CLI that walks you through configuration and generates a ready-to-use `building_config.yaml`.

### Interactive Mode

```bash
python scripts/onboard_building.py
```

The CLI will guide you through six steps:

```
────────────────────────────────────────────────────────────
  OntoSage Building Onboarding CLI
────────────────────────────────────────────────────────────

Step 1/6: Building Identity
  Building ID (e.g. bldg1, science_tower) [bldg1]:  bldg2
  Building name [My Smart Building]:  Science Tower
  Ontology namespace URI (must end with '#') [http://example.com/bldg2#]:
  SPARQL prefix (short, e.g. bldg) [bldg]:
  IANA timezone [Europe/London]:  Europe/Berlin

Step 2/6: Ontology Files
  Path to ABox TTL file [data/bldg2_abox.ttl]:  ./science_tower.ttl
  Path to TBox TTL file [data/Brick.ttl]:
  Ontology schema type [brick]:

Step 3/6: Validating Ontology Files
  ✅ ABox parsed: 12,847 triples (./science_tower.ttl)
  Detected 8 sensor class types:
     • Temperature_Sensor: 47 instances
     • CO2_Sensor: 23 instances
     • Humidity_Sensor: 23 instances
     ...

Step 4/6: Time-Series Storage
  DB backend [mysql]:  postgresql
  Database name [bldg2]:
  Sensor data table [sensor_data]:
  UUID column name [uuid]:
  Value column name [value]:
  Timestamp column name [time]:

Step 5/6: GraphDB Connection (optional)
  Test GraphDB connection? (y/n) [n]:  y
  ✅ GraphDB connected! Repository size: 0 triples.

Step 6/6: Generating Config
  Output config file path [config/bldg2_building_config.yaml]:
  ✅ Config written to: config/bldg2_building_config.yaml
```

### Non-Interactive Mode (CI/CD)

For automated deployment pipelines:

```bash
python scripts/onboard_building.py \
  --non-interactive \
  --id bldg2 \
  --name "Science Tower" \
  --namespace "http://example.com/bldg2#" \
  --prefix bldg2 \
  --timezone "Europe/Berlin" \
  --abox ./science_tower.ttl \
  --tbox ./data/Brick.ttl \
  --schema brick \
  --backend postgresql \
  --output config/bldg2_building_config.yaml
```

Output (JSON for CI consumption):
```json
{"status": "ok", "config": "config/bldg2_building_config.yaml", "building_id": "bldg2"}
```

---

## Part 3: Review the Generated Config

The CLI generates a `building_config.yaml` file. Review and adjust it as needed:

```yaml
building:
  id: "bldg2"
  name: "Science Tower"
  namespace: "http://example.com/bldg2#"
  prefix: "bldg2"
  timezone: "Europe/Berlin"
  abox_file: "./science_tower.ttl"
  tbox_file: "./data/Brick.ttl"

ontology:
  schema: "brick"
  schema_uri: "https://brickschema.org/schema/Brick#"
  extra_prefixes: []

storage:
  backend: "postgresql"
  database: "bldg2"
  table: "sensor_data"
  columns:
    uuid: "uuid"
    value: "value"
    timestamp: "time"
    sensor_name: "sensor_name"
```

---

## Part 4: Configure the Database Registry

Open `config/database_registry.yaml` and add or activate an entry for your building's database. This file maps the `ref:storedAt` keys in your TTL to actual database connections.

### Adding a New PostgreSQL Building

Uncomment and fill in the `database2` block (or copy it and create a new entry):

```yaml
databases:
  # Primary PostgreSQL instance (Building 2)
  database2:
    type: postgresql
    host: "${PG_HOST:-postgres}"
    port: "${PG_PORT:-5432}"
    user: "${PG_USER:-ontosage}"
    password: "${PG_PASSWORD:-ontosage}"
    database: "${PG_DATABASE:-bldg2}"
```

Then add the corresponding env vars to your `.env` file:

```bash
PG_HOST=your-postgres-host
PG_PORT=5432
PG_USER=ontosage
PG_PASSWORD=yourpassword
PG_DATABASE=bldg2
```

### Adding a New MySQL Building

```yaml
databases:
  database1:                      # key referenced in TTL: ref:storedAt bldg:database1
    type: mysql
    host: "${MYSQL_HOST:-mysql}"
    port: "${MYSQL_PORT:-3306}"
    user: "${MYSQL_USER:-root}"
    password: "${MYSQL_PASSWORD:-}"
    database: "${MYSQL_DATABASE:-sensordb}"
```

### Supported Database Types

| Type Key | Technology | Python Driver | Notes |
|----------|-----------|---------------|-------|
| `mysql` | MySQL, MariaDB, TiDB, TDengine | `aiomysql` | Also works with MySQL-compatible cloud services |
| `postgresql` | PostgreSQL, Aurora, Neon, Supabase | `asyncpg` | Also works with CockroachDB, YugabyteDB, QuestDB |
| `timescaledb` | TimescaleDB hypertables | `asyncpg` | Uses time-series optimised queries |
| `mongodb` | MongoDB, Atlas, DocumentDB | `motor` | Document store with sensor_data collection |
| `influxdb` | InfluxDB 2.x | `influxdb-client` | Flux query language |
| `sqlite` | SQLite, DuckDB | `aiosqlite` | Local file or in-memory |
| `cassandra` | Cassandra, ScyllaDB, AstraDB | `cassandra-driver` | CQL wide-column store |
| `redis_timeseries` | Redis + RedisTimeSeries module | `redis.asyncio` | Key-prefix based routing |

---

## Part 5: Set the Building Config Environment Variable

Tell OntoSage where to find your building's config file:

```bash
# Add to .env
BUILDING_CONFIG_FILE=config/bldg2_building_config.yaml
BUILDING_ID=bldg2
BUILDING_NAME=Science Tower
```

Or pass it at container start time:

```bash
docker compose up -d -e BUILDING_CONFIG_FILE=config/bldg2_building_config.yaml orchestrator
```

---

## Part 6: Create the GraphDB Repository

Before loading your ontology, create a dedicated GraphDB repository for this building.

### Via the GraphDB Web UI

1. Open `http://localhost:7200`
2. Navigate to **Setup → Repositories → Create new repository**
3. Select **GraphDB Repository**
4. Set **Repository ID** to your building ID (e.g., `bldg2`)
5. Click **Create**

### Via the REST API

```bash
curl -X POST http://localhost:7200/rest/repositories \
  -H "Content-Type: application/json" \
  -d '{
    "id": "bldg2",
    "type": "graphdb",
    "title": "Science Tower Ontology",
    "params": {
      "ruleset": { "name": "ruleset", "value": "rdfsplus-optimized" },
      "storage-memory": { "name": "storage-memory", "value": "false" }
    }
  }'
```

---

## Part 7: Load Your Ontology into GraphDB

### Via the GraphDB Workbench

1. In GraphDB, select your repository from the dropdown (top right)
2. Navigate to **Import → RDF**
3. Click **Upload RDF files**
4. Select your `.ttl` file
5. Click **Import** → Keep defaults → **Import**

For large files (> 100 MB), use server-side import:

1. Copy the TTL file into the GraphDB import folder:
   ```bash
   docker cp science_tower.ttl graphdb:/opt/graphdb/home/userdata/imports/
   ```
2. In the Workbench: **Import → Server files** → select the file → **Import**

### Via the REST API (recommended for automation)

```bash
# Load ABox
curl -X POST \
  "http://localhost:7200/repositories/bldg2/statements" \
  -H "Content-Type: text/turtle" \
  --data-binary @science_tower.ttl

# Load TBox (optional — adds Brick Schema vocabulary)
curl -X POST \
  "http://localhost:7200/repositories/bldg2/statements" \
  -H "Content-Type: text/turtle" \
  --data-binary @data/Brick.ttl
```

### Verify the Load

```bash
# Count total triples
curl -s -X POST \
  "http://localhost:7200/repositories/bldg2/sparql" \
  -H "Content-Type: application/sparql-query" \
  -H "Accept: application/sparql-results+json" \
  -d "SELECT (COUNT(*) AS ?count) WHERE { ?s ?p ?o }"
```

Expected output:
```json
{"results": {"bindings": [{"count": {"value": "12847"}}]}}
```

---

## Part 8: Create the Similarity Index

The similarity index enables semantic search — it allows OntoSage to find sensors by natural language descriptions without exact keyword matches.

### Via GraphDB Workbench

1. Navigate to **Explore → Similarity → Create similarity index**
2. Click **Create text similarity index**
3. Set **Index Name**: `bldg2_index` (or your building's index name)
4. Paste the Data Query:

```sparql
PREFIX rdfs: <http://www.w3.org/2000/01/rdf-schema#>
PREFIX rdf:  <http://www.w3.org/1999/02/22-rdf-syntax-ns#>
PREFIX brick: <https://brickschema.org/schema/Brick#>

SELECT ?documentID ?documentText {
    ?documentID rdf:type ?type .
    FILTER(ISIRI(?documentID))
    OPTIONAL { ?documentID rdfs:label ?label }
    BIND(REPLACE(STR(?type), "^.*[#/]([^#/]+)$", "$1") as ?typeName)
    BIND(REPLACE(STR(?documentID), "^.*[#/]([^#/]+)$", "$1") as ?entityName)
    BIND(CONCAT(
        COALESCE(?label, ""), " ",
        COALESCE(?typeName, ""), " ",
        COALESCE(?entityName, "")
    ) as ?documentText)
}
```

5. Click **More options** and set:
   - **Analyzer Class**: `org.apache.lucene.analysis.en.EnglishAnalyzer`
   - **Semantic Vectors create index parameters**: `-termweight idf -dimension 300 -minfrequency 2`

6. Click **Create** and wait for indexing to complete (2–10 minutes depending on ontology size)

### Update the .env to Reference Your Index

```bash
GRAPHDB_REPOSITORY=bldg2
GRAPHDB_SIMILARITY_INDEX=bldg2_index
```

See the [GraphDB Setup Guide](GRAPHDB_SETUP.md) for more detail on index configuration and testing.

---

## Part 9: Restart and Verify

Restart the orchestrator to pick up the new configuration:

```bash
docker compose restart orchestrator
```

Wait 30 seconds, then verify:

```bash
# Check health
curl -s http://localhost:8000/health | python -m json.tool

# Test a discovery query
curl -s -X POST http://localhost:8000/v1/chat/completions \
  -H "Content-Type: application/json" \
  -d '{
    "model": "ontosage",
    "messages": [{"role": "user", "content": "What sensors are available in this building?"}]
  }' | python -m json.tool
```

---

## Part 10: (Optional) Author the Capability KB

**Why:** Roughly **50% of real-world building queries are off-ontology** — fire procedures, amenities, IT, accessibility, policies. SPARQL can't answer them and pure LLMs hallucinate. The capability KB solves both: a structured per-building YAML file is embedded into Qdrant at startup; semantic vector search at query time bypasses the LLM when confidence is high (sub-50 ms grounded answers with explicit provenance).

### 10.1 Author `input/<building_id>/capability.yaml`

```yaml
building_info:
  id: my_bldg
  name: Acme HQ
  institution: Acme Corp
  location: 100 Main Street, Springfield
  floors: 8
  smart_building: true
  sensor_count: ~450

capabilities:
  - id: fire_safety
    category: FIRE_SAFETY
    keywords: [fire, fire alarm, evacuation, emergency exit, sprinkler,
               assembly point, fire warden, fire drill]
    content: >
      Fire safety features: automatic smoke detectors on every floor;
      manual call points at all stairwells; wet pipe sprinkler system
      throughout; emergency lighting with battery backup. Assembly point:
      car park on south side. Do not use lifts during evacuation.
    source: fire_safety_management_plan

  - id: bike_parking
    category: AMENITIES
    keywords: [bike, bicycle, cycle, bike rack, cycling]
    content: >
      Covered bike racks for ~30 bicycles outside the main entrance.
      Showers and changing rooms on the ground floor (level 0).
    source: building_facilities
```

**Recommended categories** (used by persona system and report templates): `FIRE_SAFETY`, `SECURITY`, `HVAC`, `POWER`, `LIGHTING`, `IT_INFRASTRUCTURE`, `ACCESSIBILITY`, `AMENITIES`, `POLICY`, `SUSTAINABILITY`, `EMERGENCY`, `SMART_BUILDING`, `BUILDING_OVERVIEW`. Custom categories are allowed.

### 10.2 (Optional) Tune routing in `input/<building_id>/building.yaml`

```yaml
capability_routing:
  enabled: true
  embedding_model: auto       # follows EMBEDDING_PROVIDER
  threshold: 0.56             # MiniLM-calibrated default
  override_min: 0.60          # hard skip-LLM threshold
  top_k: 5
  fallback_on_qdrant_failure: skip
```

> **Defaults are fine for most buildings.** Only tune if you observe false positives (data queries routing to capability) or false negatives (KB queries missed). See [Capability Routing § Threshold calibration](CAPABILITY_ROUTING.md#threshold-calibration).

### 10.3 Restart and verify

```bash
docker compose restart orchestrator

# Check the indexer status
docker logs ontosage-orchestrator 2>&1 | grep capability_indexer
# Expected: status=indexed entries=N points=M sha=<8-hex>

# Confirm the Qdrant collection was created
curl -s http://localhost:6333/collections \
  | jq '.result.collections[].name' | grep capability_my_bldg

# Smoke test (replace <session-token> with your auth token)
curl -X POST http://localhost:8000/chat \
  -H "Authorization: <session-token>" \
  -H "Content-Type: application/json" \
  -d '{"message":"What are the fire procedures?","session_id":"smoke","building_id":"my_bldg"}'
```

**Zero Python edits required.** No agent code, workflow, or routing logic changes per building. See [Capability Routing](CAPABILITY_ROUTING.md) for the full pipeline, observability endpoints, multi-intent extension, and failure-mode matrix.

---

## Verifying the Complete Pipeline

Use these test queries in the Open WebUI chat (`http://localhost:3000`) to validate each layer:

### 1. Ontology Layer (SPARQL)

> "What type of sensors does this building have?"

Expected: A list of sensor classes discovered from your ontology (e.g., Temperature Sensors, CO₂ Sensors, Humidity Sensors). If this fails, check that your TTL was loaded correctly into GraphDB.

### 2. Semantic Search (RAG)

> "Where are the temperature sensors located?"

Expected: Zone and floor information derived from your ontology relationships. If this fails, check that the similarity index was created and `GRAPHDB_SIMILARITY_INDEX` is set correctly.

### 3. Time-Series Layer (SQL)

> "What is the current temperature in Zone 5?"

Expected: A live sensor reading. If this fails, check:
- The database registry entry has correct credentials
- The `ref:hasTimeseriesId` in your TTL matches actual UUIDs in your database
- The `ref:storedAt` value matches the registry key exactly

### 4. Analytics Layer

> "What was the average CO₂ level yesterday?"

Expected: A computed statistic. If this fails while step 3 works, check the code executor is running: `curl http://localhost:8002/health`

---

## Multiple Buildings

OntoSage can serve multiple buildings simultaneously. Each building:
- Has its own GraphDB repository
- Has its own database entry in `database_registry.yaml`
- Can use a different database backend

### Per-Building GraphDB Repositories

The RAG service connects to a single GraphDB repository at a time (set by `GRAPHDB_REPOSITORY`). For multi-building support with separate repositories, run multiple RAG service instances with different repository settings, or load all buildings into a single repository with distinct named graphs.

### Routing by Building ID

When a user query includes a building context (e.g., "in Building 2"), the dialogue agent extracts the `building_id` entity and the SQL agent uses it to look up the correct adapter from the registry.

### Example: Two-Building Setup

```yaml
# config/database_registry.yaml
databases:
  # Building 1 — MySQL
  database1:
    type: mysql
    host: "${MYSQL_HOST:-mysql}"
    database: "${MYSQL_DATABASE:-bldg1_sensors}"

  # Building 2 — PostgreSQL
  database2:
    type: postgresql
    host: "${PG_HOST:-postgres}"
    database: "${PG_DATABASE:-bldg2_sensors}"
```

```turtle
# Building 1 TTL
bldg1:sensor_a brick:hasExternalReference _:r1 .
_:r1 ref:hasTimeseriesId "uuid-001" ;
     ref:storedAt bldg1:database1 .

# Building 2 TTL
bldg2:sensor_x brick:hasExternalReference _:r2 .
_:r2 ref:hasTimeseriesId "uuid-999" ;
     ref:storedAt bldg2:database2 .
```

---

## Onboarding Checklist

Before declaring a building fully onboarded, verify each item:

- [ ] ABox TTL file validated (no parse errors)
- [ ] All sensors have `ref:hasTimeseriesId` linking to database UUIDs
- [ ] All `ref:storedAt` values match entries in `database_registry.yaml`
- [ ] Spatial relationships present (zone → floor → building hierarchy)
- [ ] GraphDB repository created and TTL loaded
- [ ] Triple count matches expected (no silent load failures)
- [ ] Similarity index created and rebuilt successfully
- [ ] `GRAPHDB_REPOSITORY` and `GRAPHDB_SIMILARITY_INDEX` set in `.env`
- [ ] Database credentials in `.env` tested and working
- [ ] `BUILDING_CONFIG_FILE` set and pointing to correct YAML
- [ ] Orchestrator restarted after configuration changes
- [ ] Discovery query returns expected sensor classes
- [ ] Sensor data query returns live readings
- [ ] Analytics query returns computed results

---

## Troubleshooting

### "No sensors found" on a discovery query

1. Check the ontology was loaded: `curl http://localhost:7200/repositories/bldg2/size`
2. Verify your sensor resources have `rdf:type` assertions
3. Ensure the `GRAPHDB_REPOSITORY` env var matches your repository ID exactly

### SPARQL returns results but SQL returns empty

1. Verify the UUIDs in `ref:hasTimeseriesId` match the actual identifiers in your database
2. Check the `ref:storedAt` value matches a key in `database_registry.yaml`
3. Test the database connection directly:
   ```bash
   docker exec -it ontosage-orchestrator python -c "
   from orchestrator.services.adapters.registry import AdapterRegistry
   import asyncio
   async def test():
       r = AdapterRegistry()
       await r.initialize()
       adapter = await r.get_adapter('database2')
       print(await adapter.health_check())
   asyncio.run(test())
   "
   ```

### "Similarity index not found"

Rebuild the index from SPARQL:
```sparql
PREFIX similarity-index: <http://www.ontotext.com/graphdb/similarity/instance/>
PREFIX similarity: <http://www.ontotext.com/graphdb/similarity/>

INSERT DATA {
    similarity-index:bldg2_index similarity:rebuildIndex "" .
}
```

### TTL parse errors

Use rdflib to validate locally before loading:
```bash
pip install rdflib
python -c "from rdflib import Graph; g = Graph(); g.parse('science_tower.ttl', format='turtle'); print(len(g), 'triples')"
```

Common issues:
- Missing `@prefix` declarations
- Trailing commas in Turtle lists
- Non-ASCII characters in labels without proper encoding declaration (`@charset "utf-8"`)
- Malformed URI references (spaces in URIs, unescaped special characters)
