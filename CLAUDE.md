# CLAUDE.md

Guidance for Claude Code working in this repo. Keep it lean — deep detail lives in
[ONTOSAGE.md](./ONTOSAGE.md) and [docs/](./docs/). **Read the [Notes](#notes) at the bottom first — they govern how to work here.**

---

## New session orientation (read this first)

**Current branch:** `main` — all P0 + multi-building work committed and pushed (through
`1f263a4`, 2026-07-29). **Never commit or push without the user's explicit approval.**

**Three files every session must read** (in order):
1. `CLAUDE.md` (this file) — navigation index, debugging, workflow rules
2. `README.md` — architecture overview, stakeholder guide, data setup
3. `ONTOSAGE.md` — complete technical reference (source layout, all phases, config)

> **STALE BELOW — see [`tasks/V6_HANDOFF.md`](./tasks/V6_HANDOFF.md) first (2026-08-23).**
> The snapshot in this section predates the V6 audit and Waves A+B. Current truth lives in
> `tasks/V6_HANDOFF.md`, `tasks/V6_AUDIT_2026_08_23.md` and the two trackers. Headline: V6 is
> 31 done / 28 todo, suite 2,655 pass, every evidence gate wired ADVISORY and live-verified,
> 1,994 measured cadences loaded as TTL with zero code change, nothing committed.

**Current state snapshot (2026-08-22):**
- Test suite: **2488 passing, 2 skipped** (`pytest -m unit -q`). Nothing since the last commit
  is committed — the whole V4+V5+V6 body of work is uncommitted and awaiting the user's review.
- **Sensor connectivity is now complete on bldg1** (TODO-224): every one of the 2,688 timeseries
  UUIDs resolves to rows in a registered database (was 2,597/2,598), and the 90 points that were
  described in the ontology but connected to nothing are linked. The 23 points still without a
  UUID are the correct ones — cameras, setpoints, commands. Full audit, including how the
  GraphDB deletion was verified:
  [`scripts/outputs/SENSOR_CONNECTIVITY_AUDIT.md`](./scripts/outputs/SENSOR_CONNECTIVITY_AUDIT.md).
- **CAVEAT-039 was a live wrong-answer defect, not the P2 it was labelled.** Blank-node
  duplication from a pre-b4c7381 context-less POST had grown sensor reference fan-out to 68.9
  (expected 1-2), and the class-listing query's `LIMIT 50` with no `DISTINCT` was exhausted by a
  single subject: `brick:CO2_Sensor` returned **1 distinct sensor against a true 280**. Cleaned
  (1,211,551 triples, backed up first, rescue gate 0) and the query rewritten to `GROUP BY` +
  `SAMPLE`. Now returns 280 of 280. **Both fixes were needed; neither sufficed alone.**
- **`--resume` on the capture harness was inert** (BUG-219): it counted quarantined rows as
  captured, so the remedy its own output recommends did nothing. Fourth measurement-apparatus
  bug in this project's history — see `tasks/lessons.md`.
- **BUG-188's context-window fix never reached bldg1** (BUG-221): `.env` sat at
  `OLLAMA_NUM_CTX=8192` while `.env2`/`.env3` had 16384, so the entire 1,580-question golden
  baseline ran on the configuration BUG-188 identified as faulty. Now 16384, verified live.
- Corpus coverage: **63.8%** (bldg1, 2026-06-18) / **70.4%** (bldg2, 2026-07-30) on the
  240-question stratified replay — both above the ≥60% target. A 2026-08-18 replay on
  bldg2 under the hosted model scored **78.8% combined / 25.0% data-backed** with zero
  transport errors (`scripts/outputs/replay/cloud_240_r1.md`).
- **Grading a run is only valid if the stack was healthy for all of it.** Two separate
  incidents produced fictitious numbers: a mid-run container recreate (CAVEAT-173, and a
  9.2%-coverage artifact, BUG-176) and an LLM outage whose fallback text reads like an
  answer (BUG-177 — one such fallback was a 1000-row dump that would have graded as a
  PASS). Both harnesses now quarantine those rows instead of scoring them; the API
  declares `llm_degraded` per turn. Never publish a number from a run that reports
  invalid rows.
- **Three buildings, all tracked in git, swap-by-rename, ONE active at a time:**
  the active building's files are `input/` + `.env` + `docker-compose.yml`; parked
  buildings live as `bldgN/` + `.envN` (gitignored — identity delta tracked as
  `<folder>/env.building`) + `docker-compose.bldgN.yml`. Per-building state:
  `./volumes/<BUILDING_ID>/*` (guarded — compose refuses to start if `BUILDING_ID`
  unset). **Committed state = NO building active** (Workflow rule 8): a fresh clone has
  `input/`, `.env` and `docker-compose.yml` ABSENT. Activate one by rename before
  `docker compose up -d` — see "Run building N" below. Tests and code must never
  require an active building (`pytest -m unit -q` passes in the parked state).
- **Swap procedure:** `docker compose down` the OLD building FIRST (its project name,
  e.g. `docker compose -p ontosage_bldg2 down`), then rename `input/`↔`bldgN/`,
  `.env`↔`.envN`, `docker-compose.yml`↔`docker-compose.bldgN.yml`, then `up -d`.
  Cold boots self-heal: ontology init retries after TTL ingestion + a ~7-min
  background backstop for slow GraphDB warm-up (BUG-100, fixed 2026-07-30).
- Admin portal (`/admin`, 8 endpoints), narrow MySQL tables + adapter, TTL
  extensions, RBAC (`require_permission()` on all data endpoints),
  `STRICT_SECRETS` boot guard, P0 hardening rounds 1+2 — all **committed on main**.

**To verify current state before starting work:**
```bash
pytest -m unit -q                                  # should show 1590 pass, 4 skip, 0 fail
git status                                         # shows what's modified vs committed
git diff --stat HEAD                               # shows scope of uncommitted changes
docker-compose logs --tail=20 orchestrator         # live system health
```

**Open issues / pending decisions:**
- **ACTIVE WORKSTREAM (2026-08-15): Improvement Plan V5 — Universal Coverage.** V4 is
  DELIVERED (36/36, see `tasks/V4_TRACKER.csv` + `scripts/outputs/V4_RESULTS.md`; nothing
  committed). V5 design: [`tasks/IMPROVEMENT_PLAN_V5_UNIVERSAL_COVERAGE.md`](./tasks/IMPROVEMENT_PLAN_V5_UNIVERSAL_COVERAGE.md)
  (v3: OCBV-2 + Event Framework + PREDICT + DETECT + PROTECT pillars). Execution:
  [`tasks/V5_TRACKER.csv`](./tasks/V5_TRACKER.csv), 45 tasks, MVP-ordered. **Cold-start /
  model-handoff pack: [`tasks/V5_HANDOFF.md`](./tasks/V5_HANDOFF.md) — read it FIRST when
  resuming V5 work.** Session protocol: take the first `todo` row whose deps are done
  (respecting the MVP order in the handoff doc), work it, flip status + notes with
  evidence. User decisions already made are logged in the handoff doc — do not re-ask.
  **Status 2026-08-19: 39/45 done, T02 skipped.** T33 (bldg2 pillar scorecard) and T43
  (policy editor, live-probed 3/3) are DONE. Left: T34/T35 (bldg3/bldg1 legs — HELD, the
  user asked to keep bldg2 live), T36 (certification ×3 + DELIVERED), T44 (multi-model
  benchmark — needs the hosted quota window to reset), T45 (results tables).
- **Certified bldg2 scorecard (2026-08-19):** COVERAGE 26.2% data-backed / **80.6%
  combined** (237 graded, +3 quarantined) · PROTECT **0.0% leak** over 37 applicable
  traps with the PDP **enforced** · DETECT **96.9% recall** (31/32) · PREDICT **CI95
  0.92**. Artifact: `scripts/outputs/V5_SCORECARD_bldg2_*.md`. All on the LOCAL
  `gpt-oss:20b`, which BEAT the hosted 120B on coverage (80.6% vs 78.8%) — the quota
  exhaustion costs nothing scientifically.
- **The LLM provider is `local` (`gpt-oss:20b`) as of 2026-08-18.** The hosted trial ran on
  Ollama Cloud `gpt-oss:120b`, but its rolling ~5-hour call budget was **exhausted** during
  the T44 benchmark and every cloud call now returns HTTP 429 — so no real work can be done
  on cloud until the window resets. Embeddings were already `local`, so nothing needed
  reindexing. Switch with `MODEL_PROVIDER=` in `.env` **plus `docker compose up -d`** —
  `restart` silently keeps the old environment (CAVEAT-178). Only 7 of the 19 hosted models
  are reachable on this key at all: `gpt-oss:120b/20b`, `gemma4:31b`, `minimax-m3`,
  `nemotron-3-nano:30b/-super/-ultra`. deepseek-v4-*/qwen3.5/glm-5.x/kimi-*/mistral-large-3
  all return HTTP 403 "requires a subscription" — a **paid plan** is needed to benchmark
  those, which is the one open item that needs the user.
- **Live fix/caveat log + backlog: [`tasks/FIX_TRACKER.csv`](./tasks/FIX_TRACKER.csv)** — read it at session start to see what's OPEN vs fixed; keep it updated (Workflow rule 7). FIX-001/002/003 done (verified live). **TODO-010→011→012 DONE (2026-07-28):** `capability.yaml` is **removed** — capabilities are now `ontosage:Amenity` / `ontosage:KnowledgeTopic` **triples** (authored via the admin Capabilities GUI `POST /api/v1/admin/capabilities` or the OCBV TBox `input/ontosage_schema.ttl`), answered by the `CapabilityGraphResolver`. Routing is a single TTL-first path (the Qdrant capability-KB probe is gone). Migration: `scripts/migrate_capability_yaml_to_ttl.py`. **Remaining: `TODO-081`** — excise the now-dead capability-KB infra (`capability_indexer`, `semantic_router.classify`, `shared/capability_schema.py`); it no-ops harmlessly today. Design/why in [`tasks/TODO_012_CAPABILITY_YAML_REMOVAL_STEP.md`](./tasks/TODO_012_CAPABILITY_YAML_REMOVAL_STEP.md) + [`tasks/TTL_NATIVE_CAPABILITIES_PLAN.md`](./tasks/TTL_NATIVE_CAPABILITIES_PLAN.md).
- ALL changes need user review and explicit commit approval before any `git commit` or `git push`
- **Tracker: 223 rows as of 2026-08-22** (7 not closed). **Tracker: 193 rows as of 2026-08-19.** Fixed this session, in the order the evidence
  arrived: **BUG-189** (P1 FABRICATION — a room's reading attributed to a "public corridor"
  bldg2 does not have, because the referent gate matched FLOORS BEFORE SPACES so an existing
  floor let an unverified space through); **BUG-191** (P1 — the leak grader counted the "2"
  inside `bldg2` as a sensor reading, so refusals scored PASS and a run reported a spurious
  39/39); **BUG-188** (2.7% of local turns returned empty completions from a 29,705-char
  prompt against an 8192 context — `OLLAMA_NUM_CTX` now 16384, costing +200 MiB with the
  model still 100% on GPU); **BUG-194** (P1 — a GUI policy edit was SHADOWED by a stale copy
  in the default graph: file and named graph correct, API and enforcement using the OLD
  value, editor reporting success); **BUG-195** (P1 — the sparql lane could answer a reading
  question with NO PDP chokepoint, and "how many people" was not recognised as
  presence-adjacent so the k-check was skipped even when the PDP ran); plus BUG-186,
  CAVEAT-182/190/193.
- **The measurement apparatus was wrong more often than the system.** Four of the five P1s
  above were in graders/harnesses, and the same weak heuristic ("any digit means it
  answered") hid a fabrication one day and manufactured a perfect score the next. When a
  number looks perfect, read the rows behind it — see `tasks/lessons.md` #20-22.
- Still OPEN and worth doing next: **BUG-192** (the model claims a sensor class is absent
  reasoning from its RAG window rather than a graph COUNT), **CAVEAT-193** (trap P005
  expects an answer the certified policy is designed to restrict), **CAVEAT-190** (two
  answer-traps name spaces bldg2 lacks — now auto-marked N/A, but the bank should be fixed
  for T34/T35), **TODO-181** (retype 56 legacy instances carrying undefined brick: classes).
- **BUG-184 — root cause found, fix landed, re-measure owed.** `plan_hash` is
  `sha256(plan_fingerprint | sorted candidate IRIs | fetch_window | time basis)`, and the
  candidate set excludes *currently-busy rooms* — so on a live building it MUST differ
  between runs by construction. It identifies what was computed, not how the system
  reasoned, and the T44 invariance probe was comparing it. A layered probe (host Ollama,
  temp 0, identical prompt, 6 repeats) showed the provider does return different text at
  temp 0, but the parser absorbs nearly all of it: CQ-IR fingerprints came out 1/6, 1/6,
  2/6 distinct. `cqir.plan_fingerprint()` — documented as "the determinism anchor" — was
  never surfaced; it is now published in the dossier and `plan_trace` alongside
  `plan_hash`, and the benchmark compares it. **Compare `plan_fingerprint` across runs;
  `plan_hash` is provenance.** Residual: one query still compiles two ways — shrink via the
  deterministic folds or a compile cache.
- Remaining P1s: **BUG-147** (`FIXED_UNVERIFIED` — code landed in V4-T13, the live
  join-rate assertion is still owed), **TODO-143** (paper claims TimescaleDB + Cassandra
  backends no shipped fixture supports — deferred by the user), **TODO-072** (GUI-only
  onboarding). Lower: KNOWN-153, CAVEAT-148/154, hygiene (CAVEAT-094, TODO-081, TODO-181).
- **Routing overrides live in ONE contract**: `orchestrator/services/routing_contract.py`
  (17 parse-stage + 1 post-stage + 1 concept-stage ordered rules as of 2026-08-13, order
  pinned by `tests/test_routing_contract.py::test_precedence_order_is_pinned` — update that
  test in the SAME commit as any rule change). Add/change a routing rule THERE — never as a
  new inline override in `dialogue_agent`.
- `data/mysql-init/init.sql` creates `abacws` DB (legacy); live system uses `sensordb` — mismatch is inert (MySQL container is disabled; host MySQL used directly)
- Maintenance agent "report broken light" → generic fallback (tracked as KNOWN-008)
- **bldg1 `sensor_data` (wide) = REAL snapshot + INTENTIONAL dev-mode top-up — user-confirmed
  2026-08-13, BUG-144 resolved as by-design. Do not "fix", purge, or relabel.** The physical
  abacws sensors feed a separate real DB (3 years of readings, still collecting) that this
  dev machine does NOT receive; the user manually loaded a real snapshot (2025-01-01→
  2025-03-09) into local `sensor_data`, and `data-publisher` deliberately extends it with
  generated "latest" rows (`PUBLISH_WIDE=true` in compose) so real-time questions are
  testable during development. Everything else (all other modalities/buildings) is synthetic
  and live-generated, labeled as such. **End of development (user will do):** disable the
  generator (`PUBLISH_WIDE=false` / remove service) and repoint `database_registry.yaml`
  `database1` at the real/cloud DB. `nature: real` stays as-is throughout.

---

## Core design contract — what OntoSage IS (check every solution against this)

OntoSage is an **agentic conversational layer over one smart building's own data** — *"connect a
building's data, then ask it anything in plain English."* The points below are **non-negotiables**.
When you propose or write a solution, verify it honors every one — a solution that violates any of
these is wrong for this project even if it "works." Depth lives in `ONTOSAGE.md`.

1. **One building at a time.** v1 serves a single active building (`BUILDING_ID`). Multi-building is
   *forward-compat only* (registries keyed by `building_id`, per-building Qdrant collections + persona
   overlays) — never assume multiple live buildings, and never break the single-building path.

2. **TTL-first — the ontology is the source of truth.** If a fact can be an RDF triple, it belongs in
   the Brick/BACnet TTL, not a sidecar YAML or a code constant. Answer via SPARQL on GraphDB first;
   fall back to SQL / analytics / capability KB only for live time-series or computation RDF can't
   express. To add a capability, **extend the TTL before adding code.** Depth: the *TTL-first design
   principle* section below.

3. **No hardcoding → building-agnostic.** Core code and `shared/` carry **zero** building literals
   (namespaces, zone ids, sensor counts, areas, floor lists). Resolve everything from the active
   building: `_active_namespace()` / `bctx`, `input/database_registry.yaml`, floor-plan manifests. Any
   number in an answer is **computed live** (SPARQL `COUNT` / DWG geometry), never a frozen literal.
   Litmus test: *would this run unchanged for `bldg2`?* If not, it's wrong.

4. **Honest, grounded answers — never fabricate.** Every figure traces to live data (graph / DB / floor
   plan). If a referent doesn't exist or the data isn't loaded, **say so** (referent-existence gate,
   honest "no data") — never surface a plausible-but-wrong value. Grounding beats fluency.

5. **Any stakeholder, any purpose.** One NL interface serves facility managers, occupants, researchers,
   sustainability / safety officers, executives, visitors, students, admins. Personas bias
   *classification + response framing* only (**not** permissions). Build intent-routed, persona-framed
   features — never single-persona ones.

6. **Zero-knowledge → expert coverage.** Users need no SQL / SPARQL / schema knowledge — lay terms
   resolve via the HBCO concept resolver ("stuffy" → CO₂). The same system also serves experts (Brick
   classes, RDF types, the admin SPARQL browser). A solution must span that range and degrade gracefully.

7. **Admin-controlled access (RBAC).** Every data / config endpoint is gated by `require_permission()`;
   ontology CRUD and reindex require `system:admin`. Personas ≠ RBAC roles. **Never** add an
   unauthenticated data endpoint.

8. **Connect-data → get-answers.** A question is answerable when (a) the sensor is a triple in GraphDB
   **and** (b) its readings are rows in a registered DB, linked via `ref:hasTimeseriesId` +
   `ref:storedAt`. Both halves are required. Onboarding a source = drop TTL + register the DB + load
   rows — **no code change.**

9. **Multiple datasources, pluggable.** Time-series routes by `ref:storedAt` → adapter registry → the
   right backend. MySQL (wide/narrow), PostgreSQL, **TimescaleDB 2.11 and Cassandra 4.1 are live and
   test-covered** (TODO-143 — start them with `docker compose -f docker-compose.timeseries-backends.yml
   up -d`, seed with `scripts/seed_timeseries_backends.py`); Influx / Mongo / SQLite / Redis-TS adapters
   exist but are not yet exercised by a fixture. A new backend is **a new adapter**, never edits to the
   agents.

10. **Local or API models, independently.** `MODEL_PROVIDER` = `openai` / `local` (Ollama) / `cloud`;
    `EMBEDDING_PROVIDER` is independent. Never hardcode a provider or model — go through `llm_manager`
    + `shared/config.py`. Solutions must work under both local and API providers.

11. **`docker-compose up -d` is all you need.** The whole stack boots with one command; config lives in
    `.env` + `input/`. Don't add setup steps outside compose / `.env`, and don't assume host-installed
    tools.

---

## Commands

```bash
# Stack
docker-compose up -d                                   # start all services
docker-compose build orchestrator && docker-compose up -d orchestrator   # rebuild one
docker-compose logs -f orchestrator                    # live logs

# Health
curl http://localhost:8000/health   # orchestrator (8001 rag, 8002 code-executor)

# Tests
pytest tests/ -v                                       # all (live e2e need the stack up)
pytest -m unit            # fast / offline      pytest -m integration   # needs services
pytest tests/test_routing_accuracy.py -v               # single file
# CI deterministic suite = 423 tests (2 skipped) on 3.10/3.11/3.12 (see .github/workflows/ci.yml)

# Lint (run before commit)
black --line-length 100 orchestrator/ shared/ scripts/ tests/
isort --profile black orchestrator/ tests/
flake8 orchestrator/ shared/ scripts/ --select=F821,F823   # the only BLOCKING gate
bandit -r orchestrator/ shared/ -ll --exclude orchestrator/tests

# QA — the canonical end-to-end check (every persona × intent × flow)
python scripts/ontosage_qa_suite.py            # full battery → scripts/outputs/qa_run_<ts>.{json,md}
python scripts/ontosage_qa_suite.py --quick    # fast sample
python scripts/ontosage_qa_suite.py --ids RI05,VZ01 --convos CONV5   # targeted re-test
```

### Onboard / swap a building
```bash
python scripts/onboard_building.py --building-id bldg2 --non-interactive   # generate config
# Swap the ACTIVE building (v1 serves one at a time):
python scripts/swap_building.py --to bldg2 --dry-run    # validate (TTL @prefix bldg: ↔ ontology_namespace)
python scripts/swap_building.py --to bldg2 --archive    # apply: update .env, archive old, flush resp_cache
docker-compose restart orchestrator                     # TTL validator runs first; hard-fails on mismatch
```

### "Run building N" — the swap-by-rename procedure Claude executes on request

When the user says **"run building 1" / "run bldg2" / "switch to bldg3"** (any phrasing),
perform this EXACT sequence — never skip the down step, never guess identities:

1. **Identify the current active building** (if any): `grep BUILDING_ID input/env.building`.
   If `input/` doesn't exist, all buildings are parked — skip to step 3.
2. **Down the running stack FIRST** — renaming while up breaks the bind mounts
   (`/app/input` goes empty, CAVEAT-088/verified 2026-07-30):
   `docker compose -p ontosage_<oldN> down`. If the canonical `.env` is already gone,
   the BUILDING_ID guard blocks interpolation — pass the env explicitly:
   `docker compose --env-file .env<oldN> -p ontosage_<oldN> -f docker-compose.bldg<oldN>.yml down`
3. **Park the old active set** (names must match its OWN identity, read from
   `input/env.building` — never assume): `input/`→`bldg<oldN>/`, `.env`→`.env<oldN>`,
   `docker-compose.yml`→`docker-compose.bldg<oldN>.yml`
4. **Activate the target**: `bldg<N>/`→`input/`, `.env<N>`→`.env`,
   `docker-compose.bldg<N>.yml`→`docker-compose.yml`
5. **Sanity before boot** (all three must agree on bldg<N>): `.env BUILDING_ID` ==
   `input/building.yaml building_id` == `input/env.building BUILDING_ID`, and
   `.env COMPOSE_PROJECT_NAME` == `ontosage_bldg<N>`.
6. `docker compose up -d`, then poll `http://127.0.0.1:8000/health` until 200.
   Cold GraphDB warm-up can take minutes — ontology init self-heals (retry after TTL
   ingestion + ~7-min backstop, BUG-100). Then verify isolation: GraphDB triple count
   in the building's own namespace > 0 and other buildings' namespaces == 0;
   `data-publisher` env `MYSQL_DATABASE` matches the building's DB.
7. **Flush the response cache** before any testing:
   `docker exec redis-memory-store sh -c 'redis-cli --scan --pattern "resp_cache:*" | xargs -r redis-cli DEL'`

**Input layout — FLAT is canonical.** The active building's files sit directly under
`input/`: `input/building.yaml` + `input/*.ttl` (required — incl. `<id>_capabilities.ttl`
for `ontosage:Amenity`/`KnowledgeTopic` triples); `*.dwg`, `*.pdf`,
`intents.yaml`, `documents/` (uploaded manuals), `personas/` (optional). The nested form
`input/<id>/…` is still supported as a *fallback* (staging / future multi-building). All
per-building loaders resolve paths via `shared/building_paths.py`
(`resolve_building_file`/`resolve_building_dir` — nested first, then flat), so don't hardcode
either form. Swap exits non-zero if neither layout exists, `building.yaml` lacks required keys
/ `building_id` ≠ declared id, or a TTL prefix disagrees with `ontology_namespace`.

> **Sensor data belongs in a database, not in `input/`.** `input/` holds metadata/config only.
> Time-series readings live in a DB (MySQL/Postgres) and are referenced from the ontology via
> `ref:hasExternalReference → ref:TimeseriesReference (ref:hasTimeseriesId + ref:storedAt)`.
> Raw CSV sensor files in `input/` are deprecated — see
> `tasks/IMPLEMENTATION_PLAN_FLAT_LAYOUT_AND_DATA_PIPELINE.md` (Workstream B).

**V3 per-building optional files** (validators in `services/input_validators.py`):
`feeds.yaml` (live data sources), `recipes.yaml` (override/extend), `rules.yaml` (ECA alerts),
`channels.yaml` (notification dispatch), `benchmarks.csv`, `concepts.ttl` (lay-term overlay),
`documents/` (policy/manual KB). All optional — absent = feature silently skipped.

```bash
# Corpus replay — measure answerable share (requires live stack)
python scripts/corpus_replay.py                    # 240q stratified (40 per L1-L6)
python scripts/corpus_replay.py --sample 60        # quick smoke test
python scripts/corpus_replay.py --out-prefix <ts>  # resume a previous run
```

---

## Architecture

`orchestrator/workflow/` is a **LangGraph** state machine (package: `_orchestrator.py` = nodes
+ `_route_from_dialogue`; `_graph.py` = `_build_graph`/`_safe_node`; `_routing.py` = downstream
routes). Per request:

```
POST /chat (or /v1/chat/completions)
  → [co-reference rewrite]  → dialogue (intent + entities)  → route
  → sparql → sql → analytics/forecast → visualization        (data flows)
  → capability / floor_plan / spatial / report_intake / control / planner  (standalone)
  → response → [persist memory]
```

- **Nodes auto-register** from `orchestrator/intents/intent_definitions.yaml` (no graph edits to add an intent).
- **dialogue** (`agents/dialogue_agent.py`): LLM classifies intent + extracts entities; runs the
  co-reference rewrite and the capability semantic-router probe first.
- **sparql** (`agents/sparql_agent.py`): SPARQL gen+exec on GraphDB (7200), RAG fallback (8001); returns UUIDs.
- **sql** (`agents/sql_agent.py`): time-series by UUID via storage adapters (MySQL bldg1).
- **analytics** (`agents/analytics_agent.py`): LLM Python → sandboxed `code-executor` (8002).
- **forecast** (`agents/forecast_agent.py` + `services/forecasting/`): multi-model (ARIMA/ETS/linear), runs inside the `trend` pipeline.
- **floor_plan / spatial** (`agents/floor_plan_agent.py`, `spatial_agent.py`): PDF/DWG manifests; no LLM for spatial.
- **capability** (`agents/capability_agent.py`): single TTL-first chain — live metrics → ontology capability **triples** (`ontosage:Amenity`/`KnowledgeTopic` via `CapabilityGraphResolver`) → uploaded documents (Qdrant `documents_<bldg>`) → honest "no info". No `capability.yaml` / Qdrant capability-KB (removed, TODO-012).
- **report_intake** (`services/report_intake_service.py`): fault/complaint/safety/feedback/suggestion → `user_reports`.
- **sql adapters** (`services/adapters/`): `registry.py` routes by `ref:storedAt` key → `mysql_adapter.py` (wide `sensor_data` table) or `mysql_narrow_adapter.py` (narrow `(uuid, datetime, value)` per-modality tables — P0 addition).

**P0 additions** (all behind `system:admin` RBAC):
- **Admin endpoints** (`main.py` — 8 new routes under `/api/v1/admin/`): ontology CRUD + Qdrant reindex job queue.
- **Ontology manager** (`services/ontology_manager.py`): async GraphDB admin via httpx — list/validate/upload/drop named graphs + SELECT browser.
- **Reindex service** (`services/reindex_service.py`): background job queue for re-embedding capability/documents/floor_plans into Qdrant. Singleton `_reindex_service_instance` in `main.py`.
- **RBAC** (`middleware/rbac.py`): `require_permission(perm)` → `get_user_context` dependency chain; all data endpoints now return 401 without valid session.
- **Admin React portal** (`frontend/src/pages/AdminPortal.js`): 11-tab UI at `/admin` (Policies added by
  V5-T43; **Onboarding** added by TODO-072 and now the default tab); backed by the admin endpoints above.
- **GUI-only onboarding** (`services/onboarding_status.py`, `GET /api/v1/admin/onboarding/status`,
  `components/admin/OnboardingTab.js`): a building is onboarded end-to-end through the console —
  identity → TTL → datasource → documents → floor plans — with per-step readiness read from the LIVE
  system (spaces in the graph; declared sensors vs UUIDs that actually have rows; share of floor-plan
  spaces linked to an IRI), never from a checklist. `identity` and `ontology` are blocking; the rest
  narrow what can be answered rather than breaking it.

**V3 additions** (all config-driven, zero code for new buildings):
- **HBCO concept resolver** (`services/concept_resolver.py`): lay-term → Brick class + recipe via `ontology/hbco_core.ttl` + `hbco_mappings.ttl`; per-building overlay `input/<id>/concepts.ttl`. Injected into dialogue + SPARQL + analytics.
- **Feed framework** (`services/feeds/`): config-driven live data — `rest_poll`, `csv_drop` adapters; point auto-registration in GraphDB; `input/<id>/feeds.yaml`.
- **ECA rules engine** (`services/rules_engine.py`): standing event-condition-action rules evaluated against telemetry; `input/<id>/rules.yaml`; notification dispatch via `services/notification_service.py` + `input/<id>/channels.yaml`.
- **Actuation gateway** (`services/actuation/`): `ActuationDriver` ABC → `SimDriver` (log-only, Postgres `actuation_log`) → `ActuationRegistry`; `input/<id>/building.yaml` `actuation:` block.
- **Goal planner** (`services/goal_planner.py`): mandate decomposition ('make eco-friendly') → KPI sub-queries; `config/goals.yaml`; `GOAL_PLANNER_ENABLED` flag (default false).
- **Notification service** (`services/notification_service.py`): routes rule alerts and user requests to log/webhook/smtp channels from `input/<id>/channels.yaml`.
- **Recipe registry** (`services/recipe_registry.py`): threshold/range/aggregate/benchmark/estimate recipes; `config/recipes.yaml` + per-building overlay.
- **Document indexer** (`services/document_indexer.py`): SHA-idempotent ingestion of `input/<id>/documents/` into Qdrant `documents_<bldg>`.

Full design, all phases, and the floor-plan PDF+DWG pipeline: **[ONTOSAGE.md](./ONTOSAGE.md)**.

### Conversation memory & co-reference
- **Memory** (`services/turn_memory.py`): Redis `conversation:<id>` holds recent state, **count-bounded**
  to `CONVERSATION_MAX_MESSAGES` with **no time-expiry by default** (`CONVERSATION_TTL=0`). Postgres
  `turn_memory` keeps per-turn summaries + **carry-forward** of `forecast_result`/`analytics_result`
  (so "now plot that" works). Long-term context injected on `/v1/chat/completions`.
- **Co-reference**: `dialogue_agent.rewrite_to_standalone()` rewrites follow-ups
  ("…humidity *there*?") to self-contained queries before classification (`COREFERENCE_REWRITE_ENABLED`).

### Shared state
All nodes read/write one `ConversationState` (`shared/models.py`); `intermediate_results: Dict` is the
data bus. **Reserved keys — never overwrite another node's key:**
`intent`, `entities`, `time_range` (dialogue) · `sparql_result` (sparql) · `sql_result`, `sensor_metadata` (sql; **not** `uuids` — that name is a local, never a bus key)
· `analytics_output` (analytics) · `visualization_path` (visualization) · `concepts` (concept_resolver)
· `recipe_hints` (concept_resolver → analytics) · `control_result` (control) · `goal_plan` (planner)
· `error` (_safe_node on failure).

### Storage
| Store | Port | Purpose |
|---|---|---|
| GraphDB | 7200 | Brick/BACnet RDF ontology (SPARQL) |
| MySQL | 3306 | Sensor time-series (UUID-keyed) |
| PostgreSQL | 5433 | Users + RBAC + `turn_memory` + `user_reports` |
| Redis | 6379 | Conversation state (count-bounded) + `resp_cache:*` (1h) + `cache:embed:*` (24h) + async job queue |
| Qdrant | 6333 | `floor_plans`, `capability_<bldg>`, `user_memory` |
| MongoDB | 27017 | Full chat transcripts (OpenWebUI) |

### Providers & auth
- `shared/config.py` is the single source of truth. `MODEL_PROVIDER` = `openai` / `local` (Ollama) / `cloud`;
  `EMBEDDING_PROVIDER` = `openai` (1536-d) / `local` (MiniLM 384-d) — independent.
- `STRICT_SECRETS=true` refuses startup on default passwords; secrets masked in `Settings` repr.
- `auth_manager.py`: Argon2id + Redis sessions (7-day). RBAC (`middleware/rbac.py`): 6 roles × 20 perms;
  protect endpoints with `require_permission()`.

---

## Quick Navigation Index

First `Read` target for a task — go straight to the symbol (line numbers drift; search the symbol).

| Task | File · symbol |
|---|---|
| Intent routing (all branches + overrides) | `workflow/_orchestrator.py` · `_route_from_dialogue` |
| Register node / graph wiring | `workflow/_graph.py` · `_build_graph` |
| Intent classification + entity extraction + overrides | `agents/dialogue_agent.py` · `detect_intent`, `_parse_llm_response` |
| Co-reference rewrite | `agents/dialogue_agent.py` · `rewrite_to_standalone` |
| Capability / control / report-intake detection | `services/semantic_router.py` · `is_*`, `report_intake_intent` |
| SPARQL gen/exec + RAG fallback | `agents/sparql_agent.py` · `generate_query`, `_retrieve_context` |
| SQL time-series | `agents/sql_agent.py`; adapter routing `services/adapters/registry.py` |
| Analytics / forecast | `agents/analytics_agent.py`; `agents/forecast_agent.py` + `services/forecasting/` |
| Visualization | `workflow/_orchestrator.py` · `_visualization_node` |
| Floor plan / spatial | `services/floor_plan_registry.py`, `floor_plan_pipeline.py`, `dwg_pipeline.py`; `agents/spatial_agent.py` |
| Conversation memory | `services/turn_memory.py`; `redis_manager.py` · `save_state`/`load_state` |
| Capability triples (Amenity/KnowledgeTopic) | `services/capability_graph_resolver.py`; `agents/capability_agent.py`; author via `services/capability_admin.py` (`POST /api/v1/admin/capabilities`) / OCBV `input/ontosage_schema.ttl` |
| Document KB (policy/manual) | `services/document_indexer.py`; `agents/capability_agent.py` · `_search_documents` |
| Grounding guard (no unrelated content as answers) | `services/grounding_guard.py` · `is_on_topic`, `filter_on_topic`, `enablement_hint` |
| Referent existence gate (zones/floors/spaces/equipment/measurands) | `services/referent_resolver.py` · `detect_typed_referent`, `ReferentResolver.resolve` |
| Report intake | `services/report_intake_service.py` |
| Response formatting | `workflow/_orchestrator.py` · `_response_node` |
| Config / env vars | `shared/config.py` · `Settings` |
| State / models | `shared/models.py` · `ConversationState`, `FloorPlanManifest`, `Space`, `Block` |
| FastAPI app / endpoints / lifespan | `orchestrator/main.py` |
| Services / ports | `docker-compose.yml` |
| HBCO concept resolution | `services/concept_resolver.py` · `resolve`; `ontology/hbco_core.ttl`, `hbco_mappings.ttl` |
| Feed framework (live data) | `services/feeds/registry.py` · `FeedRegistry`; `input/<id>/feeds.yaml` |
| ECA rules engine | `services/rules_engine.py` · `RulesEngine`; `input/<id>/rules.yaml` |
| Notification dispatch | `services/notification_service.py`; `input/<id>/channels.yaml` |
| Actuation gateway | `services/actuation/registry.py` · `ActuationRegistry`; `sim_driver.py`; `approval_store.py` |
| Recipe registry | `services/recipe_registry.py` · `RecipeRegistry`; `config/recipes.yaml` |
| Goal planner | `services/goal_planner.py` · `GoalPlanner`; `config/goals.yaml` |
| Input validators | `services/input_validators.py` · `validate_building_input` |
| Per-building config validators | `scripts/swap_building.py` · `_check_optional_configs` |
| **P0 — Admin portal endpoints** | `orchestrator/main.py` · `list_named_graphs`, `validate_ttl_endpoint`, `upload_ttl_endpoint`, `drop_named_graph_endpoint`, `sparql_browser`, `trigger_reindex`, `list_reindex_jobs`, `get_reindex_job` |
| **P0 — GraphDB admin CRUD** | `services/ontology_manager.py` · `list_named_graphs`, `validate_ttl_text`, `upload_ttl`, `drop_named_graph`, `run_sparql_select` |
| **P0 — Qdrant reindex jobs** | `services/reindex_service.py` · `ReindexService`, `start`, `status`, `list_jobs`, `_run` |
| **P0 — Narrow MySQL adapter** | `services/adapters/mysql_narrow_adapter.py` · `MySQLNarrowAdapter`, `build_timeseries_query`, `get_columns` |
| **P0 — Sensor TTL generator** | `services/sensor_ttl_generator.py` · `generate_timeseries_ttl`, `parse_sensor_csv` |
| **P0 — RBAC auth dependency** | **`main.py`** · `get_user_context`, `require_permission` (the LIVE session→permission gate); `middleware/rbac.py` provides `UserContext` + `ROLE_PERMISSIONS` only — the rest of that module (`TokenManager`/`create_rbac_dependency`/`RBACMiddleware`) is unwired legacy, do not use |
| **P0 — Admin React portal** | `frontend/src/pages/AdminPortal.js` (11 tabs: Onboarding, Ontology, Capabilities, Policies, …) |
| **Onboarding readiness (GUI-only build)** | `services/onboarding_status.py` · `collect_status`; `main.py` · `onboarding_status`; `components/admin/OnboardingTab.js` |
| **P0 — Narrow table DDL** | `data/mysql-init/create_narrow_timeseries_tables.sql` (7 tables in `sensordb`) |
| **P0 — TTL extensions** | `input/bldg1_timeseries_extension.ttl` (19 sensors) · `input/bldg1_security_lighting_extension.ttl` (293 triples) |

---

## Intents & routing

Canonical list: `orchestrator/intents/intent_definitions.yaml` (per-building overlays:
`input/<id>/intents.yaml`). 29+ intents grouped `data` (sparql→sql→…), `standalone`, `meta`.
Families: sensor_data, analytics, metadata, discovery, report, anomaly, compare, export, recommend,
trend/forecast, compliance, floor_plan, spatial_query, capability, control, alert, planner,
report-intake (maintenance/complaint/safety_report/feedback/suggestion), general/greeting/clarification,
automation_capability, preference_management, lab_booking (bldg1 overlay).

**Routing precedence rules to preserve** (deterministic overrides in `dialogue_agent._parse_llm_response`
+ `_route_from_dialogue`):
- Fault/suggestion/safety **statements** ("the toilet is leaking", "Suggestion: …") → report-intake, **beating** the capability KB router. Questions ("is the lift broken?") are NOT reports.
- Comfort **questions** ("is it too warm?") → analytics, **not** complaint.
- Actuation/external-action ("open the windows", "email it") → `control` → **decline**; never floor_plan/maintenance.
- "show me floor N / where is room X" → floor_plan; "how many / area / adjacent" → spatial_query; data + floor N → data wins.

### Add an intent (2 steps, no graph edits)
1. Append to `orchestrator/intents/intent_definitions.yaml` (`pipeline_group`, optional `route_target`, `node_method`).
2. Implement `async def _my_node(self, state) -> ConversationState` on `WorkflowOrchestrator` in `workflow/_orchestrator.py`.

Restart — edges + routing auto-wire. A YAML intent with no `node_method` safely falls through to
`response`. Patterns to follow: `.claude/rules/agent-patterns.md`. SPARQL: `.claude/rules/sparql-patterns.md`.

---

## TTL-first design principle

**Goal:** answer the 6,117 questions in `paper/Survey analysis and results/` using OntoSage with minimum additional files. The Brick/BACnet `.ttl` files are the **primary source of truth** for everything a building knows about itself.

Rules to follow in every development decision:

1. **TTL before YAML.** If a fact about the building can be expressed as an RDF triple in the ontology, put it there — not in a sidecar file. Sidecar YAML is for *operational config* (thresholds, auth, routing overrides) that doesn't belong in the ontology. (Capabilities followed this to completion: `capability.yaml` was removed (TODO-012) and replaced by `ontosage:Amenity`/`KnowledgeTopic` triples authored via the admin Capabilities GUI or the OCBV TBox.)
2. **Extend the TTL, don't bypass it.** When OntoSage can't answer a survey question, the first fix is to add the missing triples (sensors, equipment, relationships, metadata) to the `.ttl` — not to add a hard-coded capability entry or a special-case code path.
3. **SPARQL is the query path.** New question types should be answerable via SPARQL against GraphDB. Only fall back to the capability KB (Qdrant), SQL adapters, or analytics when the question requires live time-series data or computation that RDF cannot express.
4. **Minimum additional files.** Each new capability should add at most one file: the enriched `.ttl`. New `feeds.yaml`, `rules.yaml`, `channels.yaml` entries are for live-data and alerting — not for answering static/structural questions.
5. **`T5_new_capability_gaps.csv`** (`paper/Survey analysis and results/outputs/master table analysis/`) is the engineering backlog. Each row that says `requires_extension` maps to a missing TTL property or an unmapped sensor. Fix it there before adding code.

This principle is grounded in the pre-design survey corpus (6,117 questions, 96 participants). The architecture coverage crosswalk (`tasks/architecture_coverage_crosswalk.csv`) shows which question clusters are already served by the existing TTL and which gaps remain.

---

## Workflow rules
1. **Plan first** for non-trivial work (3+ steps / architectural). Re-plan if it goes sideways.
2. **Subagents** only when the user asks; one focused task each.
3. **Self-improvement**: after any correction, capture the pattern in `tasks/lessons.md`.
4. **Verify before done**: run tests/QA, check logs, prove it. "Would a staff engineer approve?"
5. **Elegance, balanced**: ask for the cleaner way on non-trivial changes; don't over-engineer simple fixes.
6. **Autonomous bug-fixing**: given a bug/log/failing test, fix it directly.
7. **Fix tracker — always keep current**: [`tasks/FIX_TRACKER.csv`](./tasks/FIX_TRACKER.csv) is the
   living log of every bug/caveat/fix over time. **Whenever you fix a bug or resolve a caveat**,
   update its row (`Status` → `FIXED`/`DEPLOYED`/`VERIFIED_LIVE`, fill `Date_Resolved` +
   `Verification`). **Whenever you find a new bug/caveat**, add a row (next `FIX-`/`CAVEAT-` id,
   `Status: OPEN`). Non-optional — it is the single source of truth for what has been fixed.
   Design/why-notes for open items live in the matching plan (e.g.
   [`tasks/GROUNDING_AND_HONESTY_FIXES_PLAN.md`](./tasks/GROUNDING_AND_HONESTY_FIXES_PLAN.md)).
8. **PARK ALL BUILDINGS BEFORE EVERY COMMIT/PUSH** (non-negotiable). The repo's canonical
   committed state has **NO active building**: `input/`, `.env` and `docker-compose.yml` must
   NOT exist — only `bldg1|bldg2|bldg3/` + `.env1|.env2|.env3` (gitignored) +
   `docker-compose.bldg{1,2,3}.yml`. When the user says *"commit"* / *"push"*, do this FIRST:
   1. `docker compose ls` — if a stack runs, `docker compose -p ontosage_<N> down`
      (never rename while up: bind mounts break, CAVEAT-088).
   2. Read the active id from `input/env.building`, then park it by ITS OWN identity:
      `input/`→`bldg<N>/`, `.env`→`.env<N>`, `docker-compose.yml`→`docker-compose.bldg<N>.yml`.
   3. Verify: `ls -d input .env docker-compose.yml` all absent; all three parked sets present.
   4. Run `pytest -m unit -q` **in the parked state** (it must pass there — that is what a
      fresh clone and CI see), then commit + push.
   5. Tell the user which building was parked, so they can say *"run bldg\<N\>"* to resume.
   Rationale: the committed tree is then identical no matter who was testing what, a fresh
   clone has all three buildings intact and none half-active, and no `.env` (secrets) can
   ever ride along. Tests and code must therefore never require an active building.

---

## Debugging (common)
- **Orchestrator won't start** → `docker-compose logs --tail=50 orchestrator`; usually an ImportError (a
  module imported before it's defined, or a symbol missing from a package `__init__`).
- **Wrong intent/node** → check the routing-precedence rules above; inspect `intermediate_results["route_decision"]`; run `tests/test_routing_accuracy.py`.
- **SPARQL empty** → test GraphDB directly (`.claude/rules/sparql-patterns.md`); empty = ontology not loaded; results-but-empty = `sparql_agent._retrieve_context`.
- **Floor plan empty / `area_m2=null`** → DWG pipeline off (`dwg2dxf`/libredwg missing → PDF-only); manifest `schema_version` should be "2.0"; reingest `POST /api/v1/floor-plans/reingest`.
- **Capability not answering** → capabilities are triples now. SPARQL GraphDB: `SELECT ?a ?lay WHERE { { ?a a ontosage:Amenity } UNION { ?a a ontosage:KnowledgeTopic } ; ontosage:layTerms ?lay }` — empty = `<id>_capabilities.ttl` not loaded (check `ttl_uploader`). Match miss = the query's lay-term isn't in any `ontosage:layTerms`; add it via the admin Capabilities GUI. Prose manual not surfacing = document score below the 0.50 (local) honesty floor in `capability_agent._search_documents`.
- **Stale answers after a code fix** → flush `resp_cache:*` in Redis (`redis-cli --scan --pattern "resp_cache:*" | xargs redis-cli del`) before re-testing. Real container name: `redis-memory-store` (not `ontosage-redis`).
- **Feed not updating** → check `docker logs … | grep FeedRegistry` for `loaded=N`; missing feed = feeds.yaml absent or disabled flag.
- **ECA rule not firing** → check Redis keys `rules:breach_start:*` and `rules:fired:*`; verify `sensor_uuid` matches a UUID in MySQL `sensor_data`.
- **Concept not resolving** → SPARQL `SELECT ?c WHERE { ?c a hbco:Concept; hbco:layTerm "stuffy" }` against GraphDB; empty = hbco_mappings.ttl not uploaded.
- **Actuation decline unexpected** → check `building.yaml` `actuation.driver` value and `points_writable` list; user must have `control:write` permission (admin/facility_manager only).
- **Input validator fails on swap** → `python -c "from orchestrator.services.input_validators import validate_building_input, format_validation_report; from pathlib import Path; ok, r = validate_building_input('bldg2', Path('input')); print(format_validation_report(r))"` for full report.
- **Admin endpoint returns 401** → the endpoint uses `require_permission()` which chains through `get_user_context`. In tests: override `get_user_context` (not `get_current_user`). In live: ensure the `Authorization` header contains a valid Redis session token from `/auth/login`. Check `docker logs … | grep "401"` to see which endpoint is rejecting.
- **Admin portal upload TTL returns 500** → `services/ontology_manager.py` makes HTTP calls to GraphDB (port 7200). Verify GraphDB is healthy: `curl http://localhost:7200/rest/repositories`. Check `docker-compose logs --tail=30 orchestrator | grep ontology_manager`.
- **Reindex job stuck in `pending`** → `_reindex_service_instance` singleton in `main.py` must be initialized. Check `docker logs … | grep ReindexService` for `started`. If `None`, the lifespan didn't call `reindex_service.start()`.
- **Narrow table returns empty** → two-step check: (1) verify the sensor UUID exists in the TTL via SPARQL: `SELECT ?uuid WHERE { bldg:MySensor ref:hasTimeseriesId ?uuid }` — if empty, TTL not loaded; (2) verify rows exist in MySQL: `SELECT COUNT(*) FROM energy_data WHERE uuid='<uuid>'` in `sensordb`. If both exist but still empty, check `ref:storedAt` key in TTL matches the key in `database_registry.yaml`.
- **TTL auto-upload not loading a new TTL** → `ttl_uploader.py` discovers files matching `bldg1_*.ttl` in `input/`. File must be named `bldg1_<anything>.ttl`. Check `docker logs … | grep ttl_uploader` for `Uploading` or `Already up to date (SHA match)`. If the SHA matches, delete the named graph via Admin portal first then restart.
- **STRICT_SECRETS startup failure** → orchestrator refuses to boot if any password equals its default. Set real passwords in `.env`: `POSTGRES_USER_PASSWORD`, `MYSQL_PASSWORD`, `SECRET_KEY`, `GRAPHDB_PASSWORD`. Or set `STRICT_SECRETS=false` for local dev.

---

## Skills (`Skill` tool) & Sub-agents (`.claude/agents/`, only when asked)

| Task | Skill |  | Agent | When |
|---|---|---|---|---|
| Debug pipeline | `systematic-debugging` / `phase-gated-debugging` | | `ontology-agent` | SPARQL/TTL/GraphDB |
| LangGraph changes | `langgraph` | | `pipeline-agent` | routing / intents / state |
| RAG work | `rag-engineer` | | `infra-agent` | Docker / env / providers |
| FastAPI endpoints | `fastapi-pro` | | `test-agent` | tests / coverage |
| Docker | `docker-expert` | | `deploy-agent` | pre-deploy / auth hardening |
| Qdrant | `vector-database-engineer` | | | |
| Security review | `security-auditor` | | | |

---

## Notes:

Never agree with me by default. Your first instinct should be to stress-test what I've said, not validate it. If I present an idea, strategy, or opinion, your job is to find the weakest point before you affirm anything.
No glazing. Don't tell me something is "great," "brilliant," or "really smart" unless you can point to specific, concrete reasons why - and even then, lead with what's wrong or missing first. Compliments without substance are noise.
Don't echo my framing back to me. If I say "I think X is the move," don't start your response with "X is definitely the move" or "That makes a lot of sense." Instead, start by asking yourself: what am I not seeing? What's the counter-argument? What would someone who disagrees say, and are they right?
When you do agree, earn it. Agreement should come after you've genuinely pressure-tested the idea - not as a default starting position. If you agree, say why in a way that adds something I didn't already say.

Be direct and concise. Skip the warm-up sentences.
Don't pad responses with filler affirmations. Get to the point. If the answer is "no" or "this won't work," say that in the first sentence.
Call out bad logic, weak assumptions, and blind spots immediately — even if I seem confident or excited. Especially then. The more certain I sound, the more I need pushback.
If you catch yourself about to start a response with "That's a great point" or "You're absolutely right" - stop and rewrite. Start with the most useful thing you can say instead.

**DO NOT PUSH OR COMMIT TO GIT UNTIL I SAY SO EXPLICITLY.** Always wait for my approval before making any commits or pushing to the repository. I want to review and understand the changes before they are added to the codebase.
