# `input/` — the active building's folder

**Everything that varies between buildings lives here.** OntoSage boots, discovers what's in this
folder, and adapts — **no Python edits** to onboard a building, add documents, personas, feeds, rules, or
local vocabulary.

OntoSage v1 serves **one building at a time**. `input/` holds the **ACTIVE** building (flat layout —
files sit directly here, not in an `input/<id>/` subfolder). Other buildings are parked as sibling
folders (`bldg1/`, `input2/`, …); to switch, replace `input/`'s contents with the parked set (see
[`docs/BUILDING_ONBOARDING.md`](../docs/BUILDING_ONBOARDING.md)).

---

## Which files are shared vs per-building

To onboard a **new building**, keep the 🟢 shared files and replace the 🔵 ones with yours.

### 🟢 Building-agnostic — keep these in every building's `input/`
| File / dir | Role |
|---|---|
| `ontosage_schema.ttl` | **OCBV** — the conversational vocabulary that extends Brick (roles, intents, report/provenance, competency questions). Same for all buildings. |
| `Brick_v1.4.ttl`, `Brick+extensions.ttl` | The Brick schema (TBox) your sensors are typed against. Shared. |
| `database_registry.yaml` | Storage routing: maps each `ref:storedAt` key → a DB adapter. Env-driven (`${MYSQL_DATABASE}` …), so it's reusable — a building only *uses* the keys its `building.yaml` lists. |
| `_templates/` | Starter templates (`building.yaml`, `feeds.yaml`, `rules.yaml`, `concepts_overlay.ttl`, `recipes.yaml`). |
| `personas/` | Global persona overlays (any building) — framing only, **not** RBAC. |
| `README.md` | This file. |

### 🔵 Per-building — required
| File | What to provide |
|---|---|
| `building.yaml` | Identity: `building_id`, `building_name`, **`ontology_namespace`** (must match your TTL `@prefix bldg:` exactly), `storage.databases` (registry keys you use), `actuation`. |
| `<your>.ttl` | Your Brick model — sensors typed + linked to the DB (see [the two-half rule](#the-two-half-rule)). **One canonical TTL** (don't drop multiple serializations of the same ontology). |

### 🟡 Per-building — optional (drop-in; absent = feature silently skipped)
Admins can **drop these into `input/` any time** — the loader picks them up on the next restart:

- **`*.dwg` / `*.pdf`** — floor plans → spatial/floor queries and geometry.
- **`documents/*.md` (or `.pdf` / `.txt`)** — policies, manuals, contacts → the document KB (answers
  off-ontology questions like "what's the wifi policy?").
- **`personas/*.yaml`** — per-building persona overrides.
- **`<bldg>_capabilities.ttl`** — amenities / procedures as OCBV triples (or author them in the Admin
  Console → Ontology → *Add capability*).
- **`concepts.ttl`** — HBCO lay-term overlay ("the hub" → a Brick class).
- **`feeds.yaml`** (live data sources), **`rules.yaml`** (ECA alerts), **`channels.yaml`** (notification
  dispatch), **`intents.yaml`** (per-building intent overlay), **`benchmarks.csv`** (peer percentiles).

---

## The two-half rule

A question is answerable only when **both halves** exist:

1. the sensor is a **triple** in your `.ttl` (typed + `ref:hasTimeseriesId` + `ref:storedAt`), **and**
2. its readings are **rows** in the database that `ref:storedAt` points to.

```turtle
@prefix bldg:  <http://example.org/mybldg#> .   # == ontology_namespace in building.yaml
@prefix brick: <https://brickschema.org/schema/Brick#> .
@prefix ref:   <https://brickschema.org/schema/Brick/ref#> .

bldg:my_sensor a brick:Temperature_Sensor ;
    ref:hasExternalReference [
        ref:hasTimeseriesId "a8df8757-…" ;   # a UUID that exists as data in the DB
        ref:storedAt bldg:database1 ] .        # → key "database1" in database_registry.yaml
```

Miss half (2) and OntoSage answers **"no data"** honestly — it never invents a value.

---

## The namespace contract (read before writing any TTL)

| Thing | Rule |
|---|---|
| Prefix **label** | Always `bldg:` — in every TTL and every YAML curie. Never invent building-specific labels (`abacws:`, `hub:`). |
| Namespace **URI** | Unique per building, declared **once** in `building.yaml: ontology_namespace` (end with `#` or `/`). |
| Every `*.ttl` | Must declare `@prefix bldg: <ontology_namespace>` — the startup validator and `swap_building.py` **hard-fail** on a mismatch. |

Choose the URI from the owning institution's domain, else `http://ontosage.org/buildings/<id>#`. **Never
reuse another building's URI** — two buildings sharing a namespace makes their `Room_101`s the *same* RDF
resource.

---

## How startup ingests this folder

1. `BUILDING_ID` (env) selects the active building; `building.yaml` supplies its identity.
2. **TTL validator** — every `*.ttl` must parse and its `@prefix bldg:` must match `ontology_namespace`
   (hard-fails otherwise).
3. **TTL uploader** — SHA-cached upload of each `*.ttl` into a named graph (`urn:ontosage:ttl:<file>`);
   changed files replace their graph. *(No manual GraphDB import.)*
4. **Semantic index** — builds/self-heals automatically (debounced).
5. **Adapter registry** — loads `database_registry.yaml`, filtered by `building.yaml: storage.databases`.
6. **Optional loaders** — capability/document indexers (→ Qdrant `*_<bldg>`), feeds, rules, personas,
   intents. An invalid optional file → warning + feature skipped, never a crash.

## Full procedure & the Admin Console
- Step-by-step: [`docs/BUILDING_ONBOARDING.md`](../docs/BUILDING_ONBOARDING.md) (console-first + CLI).
- The **Admin Console** (`http://localhost:3001` → **Ontology** tab) sets building identity, uploads
  TTL, authors capabilities, and shows index status — the GUI equivalent of editing these files.
