# `input/` — the active building's mutable surface

**Everything that varies between deployments lives here.** The orchestrator
boots, discovers what's in this directory, and adapts — no Python edits needed
to onboard a building, add personas, tune intents, add data feeds, alerting
rules, documents, or local vocabulary.

OntoSage v1 serves **one building at a time**. This folder holds the ACTIVE
building (currently **bldg1**, Abacws). Complete replacement sets for other
buildings are parked in `archive/input2/` and `archive/input3/` (gitignored) —
see `archive/README.md` for the swap model.

---

## Directory layout

```
input/
├── README.md                       this file
├── Brick_v1.4.ttl                  shared Brick schema — auto-uploaded once (SHA-cached)
├── Brick+extensions.ttl            shared Brick extensions
├── database_registry.yaml          universal storage routing (storedAt key → adapter)
├── _templates/                     starter templates: building.yaml/feeds/recipes/rules/concepts
│
├── personas/                       global persona overlays (any building)
│   ├── README.md                   persona YAML schema docs
│   ├── caretaker.yaml
│   └── auditor.yaml
│
├── <BUILDING_ID>/                  the active building's directory (must match env BUILDING_ID)
│   │
│   │  ── REQUIRED ──
│   ├── building.yaml               identity, ontology_namespace, storage, actuation
│   ├── *.ttl                       Brick ontology — every TTL MUST declare
│   │                               @prefix bldg: matching ontology_namespace
│   │                               (the startup TTL validator hard-fails otherwise)
│   │
│   │  ── OPTIONAL (absent = feature silently skipped) ──
│   ├── capability.yaml             off-ontology Q&A KB → Qdrant capability_<bldg>
│   ├── intents.yaml                per-building intent overlay
│   ├── personas/<name>.yaml        per-building persona overrides
│   ├── feeds.yaml                  live data sources (csv_drop / rest_poll)
│   ├── data/*.csv                  files watched by csv_drop feeds
│   ├── recipes.yaml                analytic recipe overrides (merge over config/recipes.yaml)
│   ├── rules.yaml                  ECA alert rules (sensor_uuid must be a real MySQL column!)
│   ├── channels.yaml               notification dispatch (log / webhook / smtp)
│   ├── benchmarks.csv              peer/standard percentiles (metric,p25,p50,p75,unit,source)
│   ├── concepts.ttl                HBCO lay-term overlay ("the hub" → a Brick class)
│   └── documents/*.md|pdf|txt      policy/manual KB → Qdrant documents_<bldg>
│
├── <BuildingName> floor N.pdf      floor plans (flat layout at input/ root)
└── <BuildingName> floor N.dwg      DWG versions (optional — enables real geometry)
```

---

## The namespace contract (read this before writing any TTL)

A Turtle prefix is a **file-local abbreviation**; only full URIs reach GraphDB.
The system therefore standardizes the *label* and varies the *URI*:

| Thing | Rule |
|---|---|
| Prefix **label** | Always `bldg:` — in every TTL, every `feeds.yaml`/`rules.yaml` curie, every generated SPARQL query. Never invent building-specific labels (`abacws:`, `hub:`). |
| Namespace **URI** | Unique per building. Declared **exactly once**, in `building.yaml: ontology_namespace` (must end with `#`). Everything else derives from it at runtime via `settings.BUILDING_NAMESPACE`. |
| Every `*.ttl` in the building folder | Must declare `@prefix bldg: <ontology_namespace>` — the startup validator and `swap_building.py` **hard-fail** on a mismatch. |
| `@base` | Optional. If declared, it must equal `ontology_namespace` (validator **warns** otherwise — relative IRIs would resolve into a foreign namespace and vanish from SPARQL results). |
| YAML configs | Reference entities as `bldg:` curies only (`location: "bldg:Room_101"`, `storage: "bldg:database1"`) — never full URIs. Loaders expand them against the active building. |

**Choosing the URI for a new building:** use the owning institution's domain
when it has one (`http://abacwsbuilding.cardiff.ac.uk/abacws#`); otherwise use
`http://ontosage.org/buildings/<building_id>#`. Never reuse another building's
URI — two buildings sharing a namespace would make their `Room_101`s the *same
RDF resource*, which corrupts silently the moment both are ever co-loaded.

Why this design: fixed label keeps SPARQL templates, recipes, and the HBCO
resolver building-independent; unique URI keeps every building's triples,
named graphs, and caches collision-free.

---

## Getting started: adding a new building

### 1. Scaffold the folder

```bash
python scripts/onboard_building.py --building-id mybldg --scaffold
```

Copies `_templates/` into `input/mybldg/` with the ID substituted. Or copy the
files by hand — the only hard requirements are `building.yaml` + at least one TTL.

### 2. Fill in the required files

`building.yaml` minimum:

```yaml
building_id: mybldg                    # must equal the directory name
building_name: My Building
ontology_namespace: "http://example.org/mybldg#"
building_prefix: bldg
storage:
  databases: [database1]               # keys from database_registry.yaml
actuation:
  driver: none                         # none | sim
  points_writable: []
```

Your TTL must declare the matching prefix (and, if you use `@base`, it must be
the same URI — see [the namespace contract](#the-namespace-contract-read-this-before-writing-any-ttl)):

```turtle
@prefix bldg: <http://example.org/mybldg#> .
@base         <http://example.org/mybldg#> .   # optional, but must match if present
```

Sensors need timeseries references so SPARQL→SQL works end to end:

```turtle
bldg:my_sensor a brick:Temperature_Sensor ;
    ref:hasExternalReference [
        ref:hasTimeseriesId "<uuid>" ;        # = the MySQL column name
        ref:storedAt bldg:database1 ] .
```

### 3. Validate BEFORE booting

```bash
# All optional files (feeds/recipes/rules/channels/benchmarks/concepts/documents):
python -c "from orchestrator.services.input_validators import validate_building_input, format_validation_report; from pathlib import Path; ok, r = validate_building_input('mybldg', Path('input')); print(format_validation_report(r))"

# Full pre-flight (TTL prefix ↔ namespace, building.yaml keys, optional configs):
python scripts/swap_building.py --to mybldg --dry-run
```

### 4. Load the telemetry (MySQL on the HOST — containers don't do this)

The wide `sensor_data` table needs one column per sensor UUID, plus the data.
`data/mysql-init/*.sql` only auto-runs on a **fresh** MySQL volume — for an
existing database apply the SQL manually. See `archive/input2/mysql-init/` for
a worked example (generated CREATE TABLE + a chunked CSV loader script).

Hard limit to know: **InnoDB allows max 1,017 columns per table.**

### 5. Activate and rebuild

**Replacement-set model:** `input/` holds the ACTIVE building only (root
shared files + ONE `input/<id>/` folder). Parked buildings live as complete
`input/` replacement sets in `archive/input2/`, `archive/input3/`, … — to
activate one, copy its contents over `input/` first (see `archive/README.md`),
THEN run the swap. `swap_building.py --to <id>` fails loudly when
`input/<id>/` hasn't been staged yet — that's the reminder to copy.

```bash
# Either the swap CLI (updates .env, archives old building, flushes resp_cache):
python scripts/swap_building.py --to mybldg --archive

# …or manually: set in .env
#   BUILDING_ID=mybldg
#   BUILDING_NAME=My Building

docker compose build orchestrator && docker compose up -d
```

If a previous building's triples are in GraphDB, clear them first — named
graphs persist per-file and old sensors would keep answering:

```bash
curl -X POST http://localhost:7200/repositories/bldg/statements --data-urlencode "update=DROP ALL"
rm volumes/artifacts/.ttl_uploads.json        # SHA cache — forces TTL re-upload
docker exec redis-memory-store sh -c "redis-cli --scan --pattern 'resp_cache:*' | xargs -r redis-cli del"
```

### 6. Verify it's live

```bash
curl http://127.0.0.1:8000/health                      # → healthy (use 127.0.0.1, not localhost)
docker compose logs orchestrator | grep ttl_uploader   # uploaded=N failed=0
docker compose logs orchestrator | grep intent_registry # loaded N intents (building_id=mybldg)
# SPARQL smoke: SELECT (COUNT(?s) AS ?c) WHERE { ?s a brick:Building }  → 1
# Chat smoke: "What sensors does this building have?" via POST /chat
```

Targeted QA battery: `python scripts/ontosage_qa_suite.py --quick`

---

## Override resolution

| Concern | Resolution order (later wins) |
|---------|--------------------------------|
| Intents | `orchestrator/intents/intent_definitions.yaml` (shipped) → `input/_defaults/intents.yaml` → `input/<bldg>/intents.yaml` |
| Personas | shipped registry → `input/personas/*.yaml` → `input/<bldg>/personas/*.yaml` |
| Recipes | `config/recipes.yaml` → `input/<bldg>/recipes.yaml` |
| HBCO concepts | `ontology/hbco_mappings.ttl` (shared) → `input/<bldg>/concepts.ttl` (extends) |
| Building config | hardcoded defaults → `input/<bldg>/building.yaml` |
| Storage adapters | `input/database_registry.yaml` filtered by `building.yaml: storage.databases` |
| Floor-plan registry key | PDF filename slug → `building.yaml: floor_plan_aliases` |

## How startup ingests this directory

1. **Config** (`shared/config.py`): reads `BUILDING_ID` env var.
2. **BuildingRegistry**: scans `input/*/building.yaml`.
3. **TTL validator**: every per-building TTL must parse AND declare the
   `bldg:` prefix matching `ontology_namespace` — hard-fails startup otherwise.
4. **TTL uploader**: SHA-cached upload into per-file named graphs in GraphDB
   (`urn:ontosage:ttl:<filename>`); changed files replace their graph atomically.
5. **AdapterRegistry**: loads `database_registry.yaml`, filtered by the building.
6. **Input validators**: optional files schema-checked; invalid optional file →
   WARNING + feature skipped (never crashes boot).
7. **FeedRegistry**: loads `feeds.yaml`, auto-registers Brick points in GraphDB,
   starts the polling loop.
8. **RulesEngine**: loads `rules.yaml`, starts the evaluation loop.
9. **FloorPlanPipeline**: scans PDFs/DWGs, reconciles via aliases.
10. **Capability + Document indexers**: embed `capability.yaml` and `documents/`
    into per-building Qdrant collections (SHA-idempotent).
11. **Intent + Persona registries**: merge shipped + global + per-building.

## What's NOT config-driven (needs Python)

- A new storage adapter type — implement the `DatabaseAdapter` protocol
  (`orchestrator/services/adapters/`), including `write_records` if feeds
  should persist through it.
- A new feed adapter type (beyond csv_drop / rest_poll) — subclass `FeedAdapter`.
- A new agent/pipeline node — `workflow/_orchestrator.py` method + one YAML
  entry in `intent_definitions.yaml` (routing auto-wires; see
  `.claude/rules/agent-patterns.md`).

## Further reading

- `docs/ADDING_A_DATA_SOURCE.md` — decision tree + 30-minute playbook for any
  new data source (telemetry / events / documents / facts).
- `archive/README.md` — the parked bldg2/bldg3 replacement sets + swap model.
- `ONTOSAGE.md` — full system reference.
