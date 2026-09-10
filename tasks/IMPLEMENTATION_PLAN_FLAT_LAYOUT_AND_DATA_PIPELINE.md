# Implementation Plan — Flat Input Layout + Standardized Sensor-Data Pipeline

**Created:** 2026-06-20 · **Owner:** Suhas Devmane · **Status:** APPROVED, not yet started
(executes after the in-flight QA suite run completes).

This is the authoritative, follow-along plan. It supersedes the earlier sketch
(`FLAT_LAYOUT_AND_DATA_STANDARDIZATION_PLAN.md`). Work it **top-down**; update the
Progress Tracker (bottom) as each task lands.

---

## 0. Why this plan exists

Two structural problems surfaced during the 2026-06 hardening/review:

1. **Layout drift.** The intended, canonical input layout is **FLAT** — one building's
   metadata/config sits directly under `input/` (`input/building.yaml`,
   `input/capability.yaml`, `input/documents/`, `input/*.ttl`). But a number of startup
   loaders only look in the **nested** `input/<building_id>/` form, so on the flat layout
   they silently skip — and on a building swap they break. Four loaders were already fixed
   this session; the rest must follow.

2. **Non-standard sensor data.** Several modalities (energy, occupancy, water, noise, IAQ,
   light, equipment) currently live as **raw CSV files in `input/data/`** read by a
   `csv_drop` feed adapter. This is not the standard model: the building's other sensors
   (temperature, CO₂, humidity) are proper Brick points in the ontology whose readings live
   in MySQL and are reached through the SPARQL→SQL→analytics pipeline. We will bring **every**
   modality onto that one standard path and stop treating `input/` as a data store.

**The canonical rule we are committing to:** *`input/` holds metadata and configuration
only. Time-series sensor data lives in a database and is referenced from the ontology via
`ref:hasExternalReference → ref:TimeseriesReference (ref:hasTimeseriesId + ref:storedAt)`.*

---

## 1. Locked decisions (do not re-litigate)

- **Layout:** FLAT `input/` is canonical. Nested `input/<id>/` stays supported as a *fallback*
  (so a future multi-building / staging layout still works).
- **MySQL schema for new modalities:** **narrow, long, per-modality tables** with shape
  `(uuid CHAR(36), datetime DATETIME, value DOUBLE, PRIMARY KEY (uuid, datetime))`. One table
  per modality (`energy_data`, `occupancy_data`, `water_data`, `noise_data`, `iaq_data`,
  `light_data`, `equipment_data`, …). All sensors of a modality share the table; the UUID
  distinguishes them. Rationale: avoids the InnoDB ~1017-column limit the wide `sensor_data`
  table already hit; gives clean `storedAt`→table routing; scales with sensor count.
- **No real other-building data.** bldg1 + synthetic only.
- **CSVs are migrated, not deleted prematurely.** Archive only after the DB+TTL path is
  verified end-to-end.

### Still-open (sensible default chosen; change if desired)
- **`csv_drop` adapter:** keep it in the feed framework (it is a generic, legitimate
  *live*-drop mechanism) but stop using it for bldg1's standard/historical data. A single
  demo drop may be retained to exercise the live path; default is to remove all bldg1
  `csv_drop` feeds once migrated.

---

## 2. The canonical pipeline (target end-state)

```
                       ┌─────────────────────────── input/ (metadata + config ONLY)
                       │  building.yaml · capability.yaml · *.ttl · documents/ · feeds.yaml(live only)
                       │
  TTL sensor points ───┘   bldg:energy_meter_floor5 a brick:Electrical_Energy_Sensor ;
   (UUID + refs)              rdfs:label "…Floor 5" ; brick:hasUnit unit:KiloW-HR ;
                              brick:hasLocation bldg:Floor5 ;
                              ref:hasExternalReference [ a ref:TimeseriesReference ;
                                  ref:hasTimeseriesId "<uuid>" ; ref:storedAt "mysql:energy_data" ] .
        │ upload (ttl_uploader, idempotent named graphs)
        ▼
   GraphDB (SPARQL resolves point → UUID + storedAt)
        │
   user question → dialogue → sparql (UUID + storedAt) → sql (narrow table fetch by UUID)
        │                                                        │
        ▼                                                        ▼
   analytics / compare / anomaly / trend           MySQL: energy_data(uuid, datetime, value)
```

Every modality follows this single path. Adding a new data source = generate its TTL point(s)
+ load its readings into the right DB table (one script, §B5).

---

## Workstream A — Flat layout in every loader

Small, mechanical, high value. Unblocks clean building swaps. Do this first (after QA).

### FA1 — Shared path-resolution helper
**New** `shared/building_paths.py`:
- `resolve_building_file(building_id, filename, input_root=None) -> Optional[Path]` — return the
  first existing of `input_root/<building_id>/<filename>` (nested) then `input_root/<filename>`
  (flat). Default `input_root` search = `/app/input` then `input` (container vs dev).
- `resolve_building_dir(building_id, dirname) -> Optional[Path]` — same precedence for
  directories (`documents/`, `data/`).
- Pure, no side effects, never raises. Fully unit-tested.

### FA2 — Refactor the nested-only loaders onto the helper
Confirmed nested-only (audit 2026-06-20). Change each to nested-first, flat-fallback via FA1:
- `services/capability_indexer.py` (capability.yaml, building.yaml) — **highest impact**: today
  it skips on flat, so the capability Qdrant index is not (re)built. After this, edits to
  `input/capability.yaml` re-index at startup.
- `services/document_indexer.py` (`documents/`) — index `input/documents/` on flat.
- `services/building_context.py` (building.yaml) — load building facts/persona context from flat.
- `services/adapters/registry.py` `_get_active_keys_for_current_building` (building.yaml) — so the
  storage filter activates and we stop probing all ~20 adapters (faster startup).
- `services/semantic_router.py` `_get_config_for_intent`/`_get_routing_config` (building.yaml) —
  per-building routing thresholds honored on flat.
- `services/floor_plan_pipeline.py`, `services/dwg_pipeline.py`, `building_registry.py:~215` —
  verify and fix if nested-only (floor plans currently work, so lower risk).
- (Optional) migrate the 4 already-fixed loaders onto FA1 for consistency.

### FA3 — input_validators accepts the flat layout
`services/input_validators.py` currently requires `input/<id>/` and hard-fails otherwise, so
`swap_building.py --dry-run` rejects a flat building. Change: if `input/<id>/` is absent but
`input/building.yaml` declares this `building_id`, validate the flat `input/` set; only hard-fail
when neither exists.

### FA4 — Tests
- `tests/test_building_paths.py` — helper: flat-only, nested-only, both (nested wins), missing.
- Extend/add per-loader flat tests, mirroring `test_capability_flat_layout.py` /
  `test_semantic_router_kb_flat_layout.py`.

### FA5 — Live verification (flat bldg1)
Clean `docker compose up -d`, then confirm in logs/behavior:
- `capability_indexer` logs `indexed entries=…` (from `input/capability.yaml`).
- `document_indexer` indexes `input/documents/`.
- `AdapterRegistry` logs the storage filter **active** → fewer adapters probed → faster start.
- `python scripts/swap_building.py --dry-run --to bldg1` passes on the flat layout.
- Capability + governance answers still ground (no regression).

### FA6 — Docs
CLAUDE.md + relevant docs: state FLAT is canonical, nested is a fallback; one line in the swap
section. (The deeper data rule lands in §B5.)

**Acceptance (A):** on a clean flat-bldg1 boot, all per-building config is found, the
capability/document Qdrant indexes are (re)built from `input/`, the storage filter is active,
`--dry-run` validation passes, and the full unit suite is green.

---

## Workstream B — Standardize sensor data (input/data CSV → TTL + GraphDB + DB)

Larger, phased. Test at every phase. Do not delete CSVs until B1–B3 are verified.

### B0 — Inventory & design (no code; review with user)
- **B0.1 Inventory** `input/data/*.csv`: for each file record parameter type, floor/zone, the
  value column(s), the current MySQL column/table, the current `feeds.yaml` entry, and its UUID.
  Cover: `energy_meter_floor0-5`, `occupancy_floor0-5`, `water_main`, `noise_floor5`,
  `iaq_pm25_floor3`, `iaq_voc_floor3`, `light_floor5`, `lift_vibration_floor0`,
  `ahu_runtime_floor5`, `energy_tariff`, plus any weather/other.
- **B0.2 Class + unit map** per type → Brick class + QUDT unit (Electrical_Energy_Sensor/KiloW-HR,
  Occupancy_Sensor/count, Water_Flow_Sensor/L-PER-MIN, Noise_Level_Sensor/DeciB-A,
  PM2.5_Level_Sensor/MicroGM-PER-M3, Illuminance_Sensor/LUX, …). **Verify each class exists** in
  the loaded Brick ontology (GraphDB `ASK { brick:X a owl:Class }`); note gaps to add.
- **B0.3 Location:** each point links `brick:hasLocation` to its `brick:Floor` (or zone) so
  floor-scoped + spatial + the new `_floor_scoped_sparql` work across modalities.
- **B0.4 UUID scheme:** keep deterministic `md5(building:param)` (already used by feeds) so
  re-runs are idempotent and existing UUIDs are preserved.
- **B0.5 Table layout (LOCKED narrow):** one narrow table per modality,
  `CREATE TABLE energy_data (uuid CHAR(36), datetime DATETIME, value DOUBLE, PRIMARY KEY (uuid, datetime))`.
  Decide the modality→table list and the `storedAt` token format (e.g. `mysql:energy_data` or a
  `database_registry.yaml` key like `energy`).
- **B0.6 Routing:** confirm how `storedAt` → MySQL adapter + table flows through
  `services/adapters/registry.py` + `config/database_registry.yaml`, and what `sql_agent` must
  change to fetch from a **narrow** table (`SELECT datetime, value WHERE uuid=? AND datetime BETWEEN…`)
  instead of the wide-column `sensor_data` pattern. Capture the concrete code changes for B3.

### B1 — TTL generation tooling
- **B1.1 New** `scripts/data_source_to_ttl.py`: input = a CSV + a small metadata spec
  (brick_class, unit, floor/location, storedAt/table, value column). Output = Brick point TTL
  (UUID + label + `hasLocation` + `hasUnit` + a `TimeseriesReference` with `hasTimeseriesId` +
  `storedAt`). Deterministic UUIDs (B0.4).
- **B1.2** Generate `input/feed_points.ttl` (single file is simplest) covering all current
  `input/data` sources. Run `ttl_validator` — must pass (`@prefix bldg:` matches
  `ontology_namespace`, parses cleanly).
- **B1.3** Upload via `ttl_uploader` (idempotent named graph). Spot-check GraphDB:
  `SELECT ?s ?u WHERE { ?s a brick:Occupancy_Sensor ; ref:hasExternalReference/ref:hasTimeseriesId ?u }`
  returns points with UUIDs; repeat for energy/water/etc.

### B2 — Load readings into the narrow DB tables
- **B2.1 New** `scripts/load_timeseries.py`: read each CSV, write to its modality table as
  `(uuid, datetime, value)` with an idempotent upsert on `(uuid, datetime)`. Tag provenance =
  synthetic in a note/log.
- **B2.2** Create the narrow tables: add `data/mysql-init/*.sql` (auto-runs only on a fresh
  volume — per the V3 audit memory) **and** apply them to the live MySQL manually.
- **B2.3** Verify: row counts per UUID; a direct `SELECT … WHERE uuid=<known occupancy/energy uuid>`.

### B3 — Wire the standard pipeline & retire the CSV feed path
- **B3.1** `sql_agent` / adapter: support fetching from a **narrow** modality table by UUID
  (the B0.6 change). The wide `sensor_data` path stays for the existing temp/CO₂ sensors until/if
  they're migrated too.
- **B3.2** SPARQL→SQL resolves the new points end-to-end (they now carry `hasTimeseriesId` +
  `storedAt`). Confirm `storedAt`→table routing returns rows.
- **B3.3** Remove the migrated modalities' `csv_drop` entries from `input/feeds.yaml`; keep
  `feeds.yaml` only for genuinely live external feeds (e.g. Open-Meteo weather poll).
- **B3.4** Verify `concept_resolver` + recipe hints still map (busyness→Occupancy_Sensor,
  energy_cost recipe, pm25 threshold, …) now that data comes from the standard points.

### B4 — Retire the CSVs
- **B4.1** After B1–B3 verified, move `input/data/*.csv` to `input/_archive/` (or out of `input/`).
- **B4.2** Confirm a clean `docker compose up -d` builds the ontology and serves every modality
  with **no** CSV-as-data dependency.

### B5 — Canonical tooling + documentation
- **B5.1 New** `scripts/onboard_data_source.py` — one repeatable command wrapping B1+B2
  (CSV-or-DB + metadata → TTL point(s) + DB table load + GraphDB upload). This is the *only*
  supported way to add a data source going forward.
- **B5.2** Rewrite `docs/ADDING_A_DATA_SOURCE.md`: the standard is point-in-TTL + data-in-DB
  (`ref:storedAt` + `hasTimeseriesId`); **CSV-in-`input/` is deprecated**. Decision tree:
  telemetry → TTL point + DB table; events → events table; documents → `input/documents/`.
- **B5.3** CLAUDE.md + ONTOSAGE.md: add the canonical rule (data in a DB, referenced from the
  ontology; `input/` = metadata/config only), the recommended pattern (local MySQL is fine), and
  the `TimeseriesReference`/`storedAt` shape. Recommend users keep their data in a database and
  register it in the ontology.
- **B5.4** Memory: record the standardized pipeline + the narrow-table decision.

### B6 — End-to-end verification (closes deflection/WARN gaps)
- **B6.1** Live curl each modality through the STANDARD pipeline (no feed path): occupancy
  ("how busy is floor 5?"), energy ("energy on floor 5 yesterday?"), water ("water flow / leak?"),
  noise, IAQ, light, equipment health.
- **B6.2** Floor-scoped + compare across modalities ("compare occupancy floor 1 vs floor 5") via
  `_floor_scoped_sparql` — now possible because the points carry `hasLocation → Floor`.
- **B6.3** Re-run `scripts/ontosage_qa_suite.py` — the occupancy/energy/IAQ WARN cluster
  (OC01-06, EN*, IQ*) should flip to PASS; no regressions.
- **B6.4** `python scripts/corpus_replay.py --sample 240` — answerable share holds/improves vs
  the 63.8% baseline.

**Acceptance (B):** `input/data/` no longer holds sensor-reading CSVs; every modality resolves
through SPARQL→SQL with UUIDs + `storedAt`; floor-scoped/compare works across modalities; docs +
CLAUDE.md state the canonical DB-backed approach; full unit suite + QA + replay green.

---

## 3. Sequencing & milestones
1. **M0** — QA suite finishes (in progress) → report deltas. *(blocks nothing structural)*
2. **M1 — Workstream A** (FA1–FA6): flat layout everywhere. Ship as one reviewable change set.
3. **M2 — B0** design confirmed (narrow tables locked; modality→class/unit/table map reviewed).
4. **M3 — B1+B2**: TTL points in GraphDB + readings in narrow DB tables (CSVs still present).
5. **M4 — B3**: standard pipeline serves the migrated modalities; feed path removed.
6. **M5 — B4+B5**: CSVs archived; canonical tool + docs in place.
7. **M6 — B6**: full e2e + QA + replay; deflection/WARN gaps closed.

## 4. Testing strategy (cross-cutting)
- **Unit** at every step: path helper, TTL generator (UUID determinism, triple shape), table
  loader (idempotent upsert), narrow-table fetch.
- **Integration**: SPARQL resolves each modality's points; `storedAt`→adapter→table returns rows.
- **E2E**: one curl per modality + floor-scoped/compare; capability/governance no-regression.
- **Regression gates** before each milestone: `black -l100`, `flake8 --select=F821,F823`,
  `bandit -ll`, `pytest -m unit`, then restart + flush `resp_cache:*` + live curls on 127.0.0.1.
- **System-level**: `ontosage_qa_suite.py` after M1 and M6; `corpus_replay.py --sample 240` at M6.

## 5. Risks & guards
- Migrating the data path could regress working temp/CO₂ queries → keep the wide `sensor_data`
  path intact; only the *new* narrow tables use the new fetch (B3.1).
- mysql-init SQL only runs on a fresh volume → always apply table DDL to the live DB too (B2.2).
- Don't delete CSVs until B3 verified (B4 gate).
- Floor links depend on the building modeling `brick:Floor` + `hasLocation`/`isPartOf` — the
  onboarding pipeline must produce these for portability (note in B5 docs).

---

## 6. Progress tracker
Status: ☐ todo · ◐ in progress · ☑ done

| ID | Task | Status | Notes |
|----|------|--------|-------|
| QA | Final QA suite re-run + deltas | ◐ | running in background |
| FA1 | shared/building_paths.py helper + tests | ☐ | after QA |
| FA2 | refactor nested-only loaders onto helper | ☐ | capability_indexer, document_indexer, building_context, adapters storage-filter, routing-cfg, floor_plan/dwg |
| FA3 | input_validators accepts flat | ☐ | unblocks --dry-run on flat |
| FA4 | flat-layout tests | ☐ | |
| FA5 | live verify (indexes rebuilt, filter active, dry-run passes) | ☐ | |
| FA6 | docs: flat canonical | ☐ | |
| B0 | inventory + design (class/unit/table map) | ☐ | review with user |
| B1 | data_source_to_ttl.py + feed_points.ttl + upload | ☐ | |
| B2 | load_timeseries.py + narrow tables + verify | ☐ | |
| B3 | narrow-table fetch + storedAt routing + remove csv feeds | ☐ | |
| B4 | archive input/data CSVs; clean up-d | ☐ | gate on B3 |
| B5 | onboard_data_source.py + docs + CLAUDE.md/ONTOSAGE.md + memory | ☐ | canonical rule |
| B6 | e2e modalities + floor compare + QA + replay | ☐ | closes WARN cluster |
