# Implementation Plan — Toggleable Data Sources, Synthetic Data & Answer Provenance

**Status:** Phases 0–5 IMPLEMENTED & TESTED (64 dedicated unit tests green; `docker compose config` validates the panel service, 2026-07-01) · Phase 6 pending (after live test) · **Owner:** OntoSage · **Created:** 2026-07-01

> **Progress (2026-07-01):**
> - **Phase 0 ✅** — `shared/models.py` (`DataSourceSpec`/`DataSourcePoint`/`DataSourceGenerator`/`ProvenanceTag`), `orchestrator/services/datasource_registry.py`, validator `validate_datasources_yaml` wired into `input_validators.py`, seed `input/datasources.yaml` (7 timeseries + 1 text_reports, all disabled), flag `DATASOURCE_TOGGLES_ENABLED`. Tests: `tests/test_datasource_registry.py`.
> - **Phase 1 ✅** — `orchestrator/services/datasource_manager.py` (named-graph PUT/CLEAR = on/off switch; canonical dual-ref TTL; JSON state store; injectable HTTP client). Admin API in `main.py`: `GET /api/v1/datasources`, `POST .../{id}/enable|disable` (RBAC `config:write`), lifespan wiring. Tests: `tests/test_datasource_manager.py`, `tests/test_datasource_api.py`.
> - **Phase 2 ✅** — `orchestrator/services/synthetic/` (deterministic diurnal/weekly generator, 7 kinds, labeled anomalies; pure `generate_rows` + live `load_to_db`). Manager `preview`/`regenerate`; API `GET .../{id}/preview`, `POST .../{id}/regenerate`. Tests: `tests/test_synthetic_generator.py`.
> - **Phase 3 ✅** — `orchestrator/services/provenance.py` (record/build_tags/render_chips/tags_to_dicts). Nodes instrumented in `_orchestrator.py`: sparql→`ontology`, sql→`store:<table>` via `storage_map` (or `live_sensors`), analytics→`analytics`, capability→`capability_kb`. Response node appends chip footer + stashes structured `sources` (flag-gated). API surfaces `sources` on REST `/chat` + WebSocket; OpenWebUI `/v1` path shows chips inline in the message text. Orchestrator gets `datasource_registry` in lifespan. Tests: `tests/test_provenance.py`.
> - **Phase 4 ✅** — locked-capability gate at the top of `_route_from_dialogue` (`_check_locked_capability`): flag-gated + conservative — fires only when a curated `match_keywords` phrase for a *disabled* source appears (new `match_keywords` field on `DataSourceSpec`, seeded per source). New `_locked_capability_node` builds an "enable **X** to unlock: …" decline; registered in `_graph.py` (node + dialogue target + edge→response). Orchestrator gets `datasource_manager` in lifespan. Confirmed no routing regression (flag off = no-op). Tests: `tests/test_locked_capability.py`.
> - **Phase 5 ✅** — `config-panel/` static SPA (HTML/CSS/vanilla JS) served by nginx that reverse-proxies `/api`+`/auth` to the orchestrator (same-origin, no CORS, no build step). Dashboard cards with enable/disable toggle, colour swatch, `simulated` badge, unlocks list, Preview (sparkline) + Regenerate; sign-in modal (`/auth/login` → Bearer); provenance legend. Compose service `config-panel` on `127.0.0.1:3001` (`docker compose config` validates). Docs `config-panel/README.md`. Guard tests: `tests/test_config_panel_assets.py`.
> - **Deferred to live verify:** GraphDB PUT/CLEAR + MySQL load + end-to-end chip rendering + the GUI are unit-tested with fakes/pure logic + asset guards; the live smoke (enable in panel → SPARQL count>0 → occupancy question answers with an "Occupancy Sensing System · simulated" chip) needs the stack up with `DATASOURCE_TOGGLES_ENABLED=true`.
> - **GUI create flow ✅ (added 2026-07-01)** — `DataSourceRegistry.add_source()` persists new sources to `input/datasources.custom.yaml` (curated seed untouched; `load()` merges both, curated wins on clash), `DataSourceManager.create()`, `POST /api/v1/datasources` (`config:write`), and an "Add source" modal in the panel (points rows, generator kind, unlocks/keywords). Tests: `tests/test_datasource_create.py`.
> - **Verification pass ✅ (2026-07-01)** — full offline suite **281 unit + 2 skipped, 0 fail**; flake8 clean; `docker compose config` valid. Fixed two real bugs: (1) `./input` was mounted **`:ro`** → GUI create would fail → made it rw + mounted `./volumes/artifacts` (toggle-state/ttl cache persist) + `add_source` raises an actionable error on read-only FS; (2) live GraphDB introspection showed `iaq`(CO2 212/AirQuality 521) and `light`(Illuminance 35) **overlap** base data → emptied their `match_keywords` so they never false-lock. Locking now: occupancy/energy/noise/equipment/water/complaints YES; iaq/light NO. Sound_Level & Electrical_Power are **0** in base (cleanly missing); occupancy/energy/water have ~6/6/2 base instances (documented in the seed).
> - **Phase 6 (pending)** — `scripts/capability_envelope.py` (corpus_replay across source-sets) + paper section. Deferred until the live test confirms the pipeline.

**Feature flag:** `DATASOURCE_TOGGLES_ENABLED` (default `false` until Phase 5 lands)
**Branch (suggested):** `feature/datasource-toggles`

> **One-line goal.** Add a config GUI that lets an operator switch synthetic data
> sources (occupancy, energy, noise, IAQ, light, equipment, student-complaints, …)
> on and off. Switching one **on** injects deterministic Brick triples (each
> sensor/device gets a stable UUID) into a **dedicated GraphDB named graph** and
> loads synthetic readings into the **narrow per-modality MySQL tables** — which
> together **unlock** the classes of questions that need that data. Every chat
> answer carries **color-coded provenance tags** naming which source system(s)
> produced it, making the real-vs-synthetic boundary visible and auditable.

---

## 0. Why this is mostly *wiring*, not a greenfield build

A survey of the codebase (2026-07-01) shows ~70% of the machinery already exists
as **disconnected primitives**. This plan's job is to bind them into one
toggleable unit and expose them, **not** to reinvent them.

| Capability you asked for | Already exists | File |
|---|---|---|
| Add Brick triples to GraphDB with a UUID per sensor, cleanly removable | ✅ `FeedRegistry.register_in_graphdb()` PUTs point triples with `_derive_uuid(bldg, id)` into a per-building **named graph** (idempotent replace) | `orchestrator/services/feeds/registry.py:240-364` |
| Per-file **named graph** isolation (atomic PUT / clean drop) | ✅ TTL uploader keys each file to `urn:ontosage:ttl:<name>` | `orchestrator/services/ttl_uploader.py:192-250` |
| Narrow per-modality timeseries `(uuid, datetime, value)` | ✅ `occupancy_data`, `energy_data`, `noise_data`, `iaq_data`, `light_data`, `equipment_data`, `water_data` declared as `mysql_narrow`, addressable via `ref:storedAt bldg:<table>` | `input/database_registry.yaml:80-135` |
| Deterministic synthetic-sensor TTL + UUID map generator | ✅ `uuid5`-based, idempotent, already covers these modalities | `scripts/generate_timeseries_extension.py`, `scripts/load_timeseries_to_db.py` |
| Adapter that routes a UUID → correct DB by `ref:storedAt` | ✅ | `orchestrator/services/adapters/registry.py` |
| Config-driven per-building optional files + validators | ✅ `feeds.yaml`, `rules.yaml`, `input_validators.py` | `orchestrator/services/input_validators.py` |
| Answer **provenance tags** | ❌ **does not exist** — no `sources_used` concept in the response node | — |
| A **data source** as one on/off unit (graph + table + generator + flag) | ❌ the four pieces are unrelated today | — |
| Config **GUI** | ❌ only a commented-out `frontend` slot in compose | `docker-compose.yml:819-826` |
| **Locked-capability** UX ("enable Occupancy to answer this") | ❌ | — |

**Design keystone — the named graph *is* the on/off switch.** Enabling a source
= PUT its triples into `urn:ontosage:ds:<id>`; disabling = `CLEAR GRAPH <that uri>`.
When the graph is absent, SPARQL cannot resolve the source's UUIDs, so the SQL
step never runs — the capability is genuinely gated with zero special-casing in
the query path. Synthetic readings can safely persist in MySQL while a source is
off; they are simply unreachable.

---

## 1. Scope

### In scope (this cycle)
1. A **DataSource manifest** binding {named graph, narrow table, generator config, enabled flag, provenance label + color, `unlocks` capability tags}.
2. **Enable/disable engine** — load/clear named graphs; persist activation state.
3. **Synthetic data generator service** — realistic diurnal/weekly profiles with **optionally embedded, labeled anomalies** (ground truth for anomaly questions and the paper).
4. **Answer provenance tagging** — end-to-end, per source system, color-coded, with an explicit `synthetic: true/false` marker.
5. **Locked-capability UX** — question-type → required-source map; graceful "enable X to unlock this" decline.
6. **Standalone admin GUI** (new docker-compose service) to drive all of the above; screenshot-friendly for the paper.
7. **Paper artifacts** — capability-envelope table (questions answerable per source-set) + a synthetic-data disclosure section.

### Explicitly out of scope (deferred to a separate plan — Phase 7 stub only)
- The general **intention-fusion / pattern-of-life** engine ("quiet desk *now* but noisy in 2h, and people complained about sunlight there"). This composes on top of the infra shipped here and must not contaminate it. It gets ONE stub scenario at most (see Phase 7) and its own plan.
- Real BMS live integration of these modalities (they remain synthetic + clearly labeled).
- `bldg1` hand-authored TTLs are **never modified**. Synthetic sources live in their own files (`input/datasources/<id>.ttl`) and their own named graphs.

---

## 2. Scientific framing (for the paper)

The provenance system is the **honesty mechanism**, not decoration. Reviewers will
attack undisclosed synthetic data; per-answer, color-coded, real-vs-synthetic tags
turn that liability into the contribution:

> *"OntoSage answers over a real-time building ontology and real sensor streams.
> To characterize the system's **capability envelope** — the questions it could
> answer given richer instrumentation that current BMS access does not expose —
> we add clearly-labeled synthetic data sources that are injected via the same
> ontology-first pipeline as real data (UUID-keyed Brick points → named graph →
> UUID-addressed time-series). Every answer is annotated with per-source
> provenance, so the real/synthetic boundary is auditable at the level of the
> individual response."*

This lets the paper claim: (a) a working real-time architecture, (b) a principled,
transparent method for demonstrating unmet-but-answerable question classes, and
(c) a provenance mechanism generalizable beyond the synthetic case.

**Deliverable:** `paper/` section + a table: *rows = question clusters from the
6,117-question survey; columns = data-source sets; cells = answerable? (with
provenance).* Reuses `corpus_replay.py` and `T5_new_capability_gaps.csv`.

---

## 3. Data model

### 3.1 DataSource manifest — `input/datasources.yaml` (flat canonical; `input/<id>/datasources.yaml` fallback via `shared/building_paths.py`)

```yaml
version: 1
datasources:
  - id: occupancy                       # stable key; used in URIs, table names, UUID derivation
    label: "Occupancy Sensing"
    modality: occupancy
    kind: timeseries                    # timeseries | text_reports
    enabled: false
    synthetic: true                     # rendered on the provenance tag
    provenance_system: "Occupancy Sensing System"
    color: "#3B82F6"                    # provenance chip color
    ts_table: occupancy_data            # narrow MySQL table == ref:storedAt bldg:<table>
    named_graph: "urn:ontosage:ds:occupancy"
    unlocks:                            # capability tags this source enables
      - desk_availability
      - occupancy_peak_hours
      - space_utilisation
    points:                             # devices to synthesize (UUIDs auto-derived, deterministic)
      - local: Occupancy_Sensor_Room_5_01
        brick_class: brick:Occupancy_Sensor
        location: bldg:Room_5.01
        unit: unit:PERCENT
        label: "Occupancy — Room 5.01"
    generator:
      kind: occupancy_profile           # generator plugin key
      window_days: 30
      interval_minutes: 15
      params:
        weekday_peak: 0.85
        weekend_peak: 0.15
        opening_hour: 8
        closing_hour: 20
      anomalies:                        # optional, labeled → ground truth
        - type: spike
          at: "2026-06-15T14:00:00"
          magnitude: 1.4
```

`kind: text_reports` sources (e.g. **Student Complaint System**) declare a synthetic
complaint corpus loaded into the report/document store instead of `ts_table`
(see Phase 2.4). Reasoning *over* them is Phase 7; here they only register + tag.

### 3.2 Activation state — Postgres table `datasource_state`
`(building_id, datasource_id, enabled, last_generated_at, last_enabled_at, triple_count, row_count)` — single source of truth for "what is currently on". Redis mirror `ds:enabled:<bldg>` for hot-path reads by the router.

### 3.3 Provenance tag (bus + API)
```python
# shared/models.py — new dataclass
class ProvenanceTag(BaseModel):
    source_id: str          # "occupancy" | "ontology" | "analytics" | ...
    label: str              # "Occupancy Sensing System"
    color: str              # "#3B82F6"
    synthetic: bool         # True → rendered as "simulated"
    store: str              # "graphdb" | "mysql:occupancy_data" | "qdrant:documents" | "compute"
```
New **reserved** `intermediate_results` key: `sources_used: List[ProvenanceTag]`
(append-only; documented in CLAUDE.md "Reserved keys").

---

## 4. Architecture — request flow changes

```
POST /chat
  → dialogue (intent + entities)
  → [NEW] capability-gate: does intent/probe require a capability tag whose
          datasource is disabled?  yes → locked_capability node (decline+unlock hint)
  → sparql   → append ProvenanceTag(ontology)         ← named graphs resolved
  → sql      → append ProvenanceTag(<datasource>)      ← from ref:storedAt key
  → analytics→ append ProvenanceTag(analytics, synthetic=inherited)
  → capability/document → append ProvenanceTag(Capability KB / Complaint System)
  → response → render answer + provenance chips; API returns `sources: [...]`
```

Admin (out-of-band, not in the chat graph):
```
Config GUI ──HTTP──> orchestrator /api/v1/datasources/*  (RBAC config:write)
   enable  → generator (if stale) → load named graph (ttl_uploader PUT) → activate
   disable → CLEAR GRAPH <uri> → deactivate
```

---

## 5. Phased delivery

Each phase is independently shippable, gated behind the flag, and ends with a
green test + QA gate. Do **not** start a phase before the prior phase's gate is green.

### Phase 0 — Manifest, schema, config plumbing
**Goal:** the data model exists and validates; nothing behaves differently yet.
- `shared/models.py`: `DataSourceSpec`, `ProvenanceTag`; add `sources_used` reserved key.
- `orchestrator/services/datasource_registry.py`: load `datasources.yaml` via `resolve_building_file`; expose `list()`, `get(id)`, `enabled_ids()`.
- Extend `services/input_validators.py` + `scripts/swap_building.py::_check_optional_configs` to validate `datasources.yaml` (unique ids, table exists in `database_registry.yaml`, valid color hex, `unlocks` are known tags, points have brick_class+location).
- Seed `input/datasources.yaml` for bldg1 with all 7 timeseries modalities (all `enabled: false`) + one `text_reports` complaint source.
- `shared/config.py`: `DATASOURCE_TOGGLES_ENABLED = False`.
- **Tests:** manifest loads; validator catches 5 bad-config cases. **Gate:** existing 251 CI tests still green.

### Phase 1 — Enable/disable engine + admin API (no GUI)
**Goal:** toggle a source via `curl`; verify triples appear/vanish in GraphDB.
- `datasource_registry.enable(id)`:
  1. ensure TTL exists (`input/datasources/<id>.ttl`); if stale, call generator (Phase 2 — until then use a committed static TTL).
  2. PUT TTL into `named_graph` (reuse `ttl_uploader.upload_to_graphdb`, param the graph URI).
  3. upsert `datasource_state.enabled=true`; refresh Redis mirror; flush `resp_cache:*`.
- `datasource_registry.disable(id)`: `CLEAR GRAPH <named_graph>` via SPARQL update; `enabled=false`; flush cache.
- `orchestrator/routers/datasources.py` (RBAC per `api-contracts.md`):
  - `GET /api/v1/datasources` (`config:read`) — list + state + `unlocks`.
  - `POST /api/v1/datasources/{id}/enable` · `/disable` (`config:write`).
- **Tests:** enable → SPARQL `SELECT (COUNT(*)) FROM <graph>` > 0; disable → 0; adapter routing intact. **Gate:** live smoke — enable `occupancy`, ask an occupancy question, get non-empty; disable, get gated/empty.

### Phase 2 — Synthetic data generator service
**Goal:** realistic readings on demand; anomaly ground truth.
- `orchestrator/services/synthetic/` — `base.py` (`Generator` ABC: `generate(spec, window) -> List[(uuid, dt, value)]`) + plugins: `occupancy_profile.py`, `energy_load.py`, `noise_profile.py`, `iaq_profile.py`, `light_profile.py`, `equipment_profile.py`. Diurnal + weekly seasonality + configurable noise + injectable labeled anomalies.
- Refactor `scripts/generate_timeseries_extension.py` core into `services/synthetic/ttl_builder.py` (deterministic `uuid5`) so both CLI and API share it. Loader reuses `scripts/load_timeseries_to_db.py` logic → narrow tables.
- API: `POST /api/v1/datasources/{id}/regenerate` (body: window/params), `GET .../preview` (sample series + triple count, no DB write).
- Store anomaly ground-truth manifest → `volumes/artifacts/anomalies_<bldg>.json`.
- **Tests:** generated series length/shape; anomaly present at declared timestamp; UUIDs deterministic across runs. **Gate:** `corpus_replay.py --sample 60` shows lift on occupancy/energy strata when enabled.

### Phase 3 — Answer provenance tagging (end-to-end)
**Goal:** every answer names its sources; API returns structured `sources`.
- Instrument nodes to append `ProvenanceTag` to `sources_used`:
  - sparql → `ontology` (label "Building Ontology", synthetic=false).
  - sql → look up `ref:storedAt` key used → map to datasource label/color/synthetic via registry.
  - analytics → `Analytics Engine` (inherits synthetic if any input source synthetic).
  - capability/document/report_intake → their labels (Complaint System = synthetic).
- `_response_node`: dedupe `sources_used`, render chips after the answer text; add `sources: [ProvenanceTag]` to the API envelope.
- Built-in always-on labels for real stores in `datasource_registry` (ontology, live MySQL, analytics) so tags work even with all synthetic sources off.
- **Tests:** occupancy query returns a tag with `source_id=occupancy, synthetic=true`; pure-metadata query returns only `ontology`. **Gate:** QA suite output includes `sources` for every turn.

### Phase 4 — Locked-capability UX
**Goal:** questions needing a disabled source decline gracefully with an unlock hint.
- Build `capability_tag → datasource` reverse index from all manifests' `unlocks`.
- Map intents/question-types → required capability tags. Start **coarse + conservative**: extend `services/semantic_router.py` capability probe to emit a `required_capability` when confident; only lock when the mapped source is known-and-disabled. If unsure → fall through to the normal pipeline (respects existing routing-precedence rules — no regressions).
- New node `_locked_capability_node` + intent wiring via `intent_definitions.yaml` (2-step autowire): returns a decline naming the source, what it `unlocks`, and (paper narrative) "this would be answerable as: …".
- **Tests:** `tests/test_routing_accuracy.py` — occupancy question with source OFF → `locked_capability`; same question with source ON → `sparql`. No regression on the existing precedence cases. **Gate:** routing accuracy suite green.

### Phase 5 — Standalone config GUI
**Goal:** operator-facing panel; screenshots for the paper.
- New `config-panel/` (Vite + React + Tailwind) → docker-compose service `config-panel` on **`3001`** (3000=OpenWebUI, 8000=orchestrator). Auth via existing session token; all calls hit `/api/v1/datasources/*`.
- Screens: (1) **Data Sources dashboard** — card per source: toggle, modality icon, color swatch, "unlocks N capabilities", synthetic badge, last-generated, sample sparkline. (2) **Source detail** — generator params, point/UUID list, triple-count + preview, Regenerate. (3) **Create source** wizard. (4) **Provenance legend** (color per system).
- Flip `DATASOURCE_TOGGLES_ENABLED=true` by default once green.
- **Tests:** component/API contract tests; manual demo script in `docs/`. **Gate:** end-to-end demo — toggle occupancy in GUI → ask desk question in chat → answer with occupancy provenance chip.

### Phase 6 — Paper artifacts
- `scripts/capability_envelope.py`: run `corpus_replay.py` across source-sets (none / +occupancy / +energy / all) → answerable-share matrix by L1–L6 and by survey cluster.
- Provenance-annotated QA export.
- `paper/` synthetic-data disclosure + capability-envelope section (use `paper-section` skill).
- **Gate:** matrix reproduces and shows monotonic lift as sources enable.

### Phase 7 — (DEFERRED, separate plan) Intention-fusion stub
- Write `tasks/IMPLEMENTATION_PLAN_INTENTION_FUSION.md` only.
- Optionally ONE proof-of-concept scenario (quiet-desk-now-vs-2h) composing occupancy+noise+`forecast_agent`+complaint source — behind its own flag, not required to ship Phases 0–6.

---

## 6. Reserved-key / contract updates (must land in Phase 0/3)
- CLAUDE.md "Reserved keys" + `.claude/rules/agent-patterns.md`: add `sources_used` (append-only; never overwrite).
- `.claude/rules/api-contracts.md`: document the `sources: [ProvenanceTag]` envelope field.

## 7. Risks & mitigations
| Risk | Mitigation |
|---|---|
| Locked-capability over-triggers → regresses good answers | Conservative: lock only on high-confidence tag match to a *disabled* source; else fall through. Guard with routing-accuracy tests before/after. |
| Synthetic data mistaken for real | `synthetic:true` on every tag + distinct chip style; paper disclosure; GUI "simulated" badge. |
| Wide-table MySQL blow-up (past InnoDB 1017-col bug) | Narrow tables only — already the design; generator writes `(uuid, dt, value)`. |
| bldg1 hand-authored TTL corrupted | Synthetic TTLs isolated to `input/datasources/*.ttl` + own named graphs; never touch base graphs. Disable = `CLEAR GRAPH` only the ds graph. |
| Stale answers after toggle | `enable/disable` flush `resp_cache:*` (container `redis-memory-store`). |
| Scope creep into fusion | Hard phase boundary; Phase 7 is a separate document. |

## 8. Test & QA gates (every phase)
- `pytest -m unit` green; `flake8 --select=F821,F823` clean; `black`/`isort`.
- `tests/test_intent_graph_autowire.py` for the new node.
- `tests/test_routing_accuracy.py` for locked-capability + no regressions.
- `python scripts/ontosage_qa_suite.py --quick` and, on data-affecting phases, `corpus_replay.py --sample 60`.

## 9. Open questions (resolve during Phase 0)
1. Complaint/text source store: reuse `user_reports` (Postgres) vs a dedicated Qdrant `complaints_<bldg>`? (Lean: reuse `report_intake` + `documents_<bldg>`.)
2. Should disabling a source **purge** MySQL rows or leave them (default: leave — cheap, and re-enable is instant)?
3. Provenance chips in OpenWebUI: does the chat frontend render our `sources` array, or do we inject a markdown chip line in the response text as a fallback? (Fallback markdown is the safe default.)

## 10. Decisions locked (2026-07-01)
- GUI = **standalone admin service** (`config-panel`, port 3001).
- Reasoning scope = **infra first; fusion deferred** to Phase 7 / separate plan.
- Off-source behavior = **explicit locked-capability** decline with unlock hint.
