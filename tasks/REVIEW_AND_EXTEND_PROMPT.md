# OntoSage — Review, Test & Extend Prompt (Data-Source Console feature set)

> Paste everything below into a fresh chat. It is a self-contained brief for a senior
> reviewer to (1) understand the feature, (2) review it for correctness/quality/security,
> (3) run the tests and fix any failures, and (4) ADD a new end-to-end capability test that
> proves the "add a data source → new questions become answerable" mechanism works.

---

## Your role

You are a **senior system designer + reviewer** for OntoSage (an agentic AI over a Brick/BACnet
building ontology; LangGraph orchestrator; FastAPI; GraphDB + MySQL + Postgres + Redis + Qdrant).
A large feature — the **Admin Data-Source Console** — was built across a prior session. Your job is
to review it critically, run and fix the tests, verify it live, and extend it with a new
end-to-end question-answering (QA) capability test.

**House rules (from `CLAUDE.md`, obey exactly):**
- **Do NOT commit or push** to git. Leave changes in the working tree for the human to review.
- **TTL-first:** if a building fact can be a triple, it belongs in the ontology, not a sidecar.
- Style: `black --line-length 100`, `isort --profile black`; the only BLOCKING lint gate is
  `flake8 --select=F821,F823`. Type hints use `Optional[X]` / `Dict` / `List` (py3.9-compatible).
- Don't agree by default — stress-test the design; report the weakest points first.
- Verify before claiming done: run tests, hit endpoints, prove it.

## Read these first (they already capture the full design)

1. `tasks/IMPLEMENTATION_PLAN_DATASOURCE_TOGGLES_AND_PROVENANCE.md` — the phased plan + status.
2. `ONTOSAGE.md` **§6.5** ("Admin Console — Data Sources, Synthetic Data & External Databases").
3. `config-panel/README.md` — the console's runbook.
4. `CLAUDE.md` + `.claude/rules/*.md` — conventions, routing, SPARQL patterns.

## Feature inventory (what was built) — verify each is coherent

The feature is gated by **`DATASOURCE_TOGGLES_ENABLED=true`** in `.env`. A "data source" has TWO
halves that BOTH must exist for the pipeline to answer:
`NL → SPARQL finds sensor + UUID + ref:storedAt → SQL routes to that DB by storedAt (creds from
.env) → fetch rows by UUID → answer`.

1. **Toggleable synthetic data sources** — `input/datasources.yaml` (+ `datasources.custom.yaml`
   overlay). `orchestrator/services/datasource_registry.py` (load/index/UUID derive),
   `datasource_manager.py` (enable/disable = PUT/CLEAR a GraphDB **named graph**
   `urn:ontosage:ds:<id>` — the named graph is the on/off switch; JSON state in
   `volumes/artifacts/.datasource_state.json`). Models in `shared/models.py`
   (`DataSourceSpec/Point/Generator`, `ProvenanceTag`). Validator
   `validate_datasources_yaml` in `services/input_validators.py`.
2. **Synthetic data generator** — `orchestrator/services/synthetic/generator.py` (deterministic
   diurnal/weekly profiles, 7 kinds, labeled anomalies; pure `generate_rows` + live `load_to_db`
   into narrow MySQL `(uuid, datetime, value)` in DB `sensordb` at `MYSQL_HOST`).
3. **Canonical Brick TTL builder** — `orchestrator/services/brick_ttl.py`. SINGLE source of truth
   for point triples; matches bldg1's `bldg1_expanded_protege_clean.ttl` exactly (rdf:type list
   incl. `brick:Class`/`brick:Entity`; ONE shared named blank node for both
   `ashrae:hasExternalReference` + `ref:hasExternalReference`; `ref:hasTimeseriesId` +
   `ref:storedAt bldg:<key>`). Both the synthetic path (`datasource_manager.build_point_ttl`) and
   the external-DB path (`db_ontology.build_points_ttl`) delegate here.
4. **Provenance tags** — `orchestrator/services/provenance.py`. Nodes in
   `workflow/_orchestrator.py` record store keys (`ontology`/`store:<table>`/`analytics`/…); the
   response node renders per-source chips + a structured `sources` array (flag-gated).
5. **Locked-capability gate** — in `workflow/_orchestrator.py::_check_locked_capability` (top of
   `_route_from_dialogue`) + `_locked_capability_node` (registered in `workflow/_graph.py`).
   Conservative: fires only on curated `match_keywords` of a source that is (a) DISABLED, or (b)
   not allowed for the user's role. Decline names the source + what it unlocks. Per-role access is
   `input/role_datasource_access.yaml` (admin always allowed; unlisted role = permissive).
6. **External databases** — `input/database_registry.yaml` (~53 connection templates, one per
   engine) + `database_registry.custom.yaml` overlay (merged by
   `services/adapters/registry.py`). `building.yaml` `storage.databases:` marks the ACTIVE subset
   (bldg1 = `database1` + 7 narrow tables); the rest are dormant. Sensor metadata for a connection
   goes to GraphDB named graph `urn:ontosage:db:<key>` via `db_ontology.py` (points/CSV/TTL).
7. **Admin console** — `config-panel/` (static SPA + nginx reverse-proxy of `/api`,`/auth`,
   `/health`; compose service `config-panel` on `127.0.0.1:3001`). Tabs: Data Sources / Settings
   (.env) / Databases / Users & Access / Health. `.env` round-trip editor (secret-masked) +
   database CRUD (Test/Introspect/Data-preview/Delete) + user management + per-role access +
   restart button. Backend in `orchestrator/services/admin_config.py` + endpoints in
   `orchestrator/main.py`. `.env`-driven admin bootstrap in the lifespan + `orchestrator/create_admin.py`.
8. **Capability catalogue** — `config-panel/html/capabilities.json` (per-modality capabilities +
   example questions, grouped by stakeholder) rendered by the card "Capabilities & questions"
   Details modal.

**Admin API surface (all `system:admin` unless noted), under `/api/v1`:**
```
GET  /datasources                     POST /datasources                (create; config:write)
POST /datasources/{id}/enable|disable|regenerate (config:write)   GET /datasources/{id}/preview
GET/PUT /admin/env
GET  /admin/databases                 POST /admin/databases            (add)
POST /admin/databases/test            POST /admin/databases/introspect
GET  /admin/databases/{key}/data?table=            DELETE /admin/databases/{key}
GET  /admin/databases/{key}/sensors   POST /admin/databases/{key}/sensors            (points)
POST /admin/databases/{key}/sensors/ttl            POST /admin/databases/{key}/sensors/csv
GET/POST /admin/users   PUT /admin/users/{u}/role   DELETE /admin/users/{u}
GET/PUT /admin/role-access             POST /admin/restart
```

## Task 1 — Critical review (report findings; don't just praise)

Read the modules in the inventory. For each, look for **real defects**, not style nits:
- Correctness: named-graph on/off logic; provenance store-key mapping; the locked-capability gate
  precedence (does it ever wrongly block a base-ontology-answerable question? note iaq/light
  overlap CO2/illuminance in bldg1 and are intentionally NOT gated); env round-trip preserving
  comments; `${VAR:-default}` resolver; adapter overlay merge (curated wins).
- Security: admin endpoints are `system:admin`; `.env` editor masks secrets and skips MASK on
  write; the restart endpoint self-SIGTERMs; there is **no docker-socket** exposure.
- Consistency: both TTL paths use `brick_ttl` (no divergence); reserved `intermediate_results`
  keys aren't overwritten (`sources_used`, `_prov_stores`, `locked_source`).
- Failure modes: GraphDB/MySQL/Postgres down → non-fatal, graceful.
Produce a ranked findings list (most severe first) with file:line and a concrete failure scenario.

## Task 2 — Tests + lint (run, then fix any red)

```bash
# fast offline suite (should be ~360 passed, 2 skipped, 0 failed)
python -m pytest -m unit -q -p no:cacheprovider

# the feature's own tests
python -m pytest tests/test_datasource_registry.py tests/test_datasource_manager.py \
  tests/test_datasource_api.py tests/test_synthetic_generator.py tests/test_provenance.py \
  tests/test_locked_capability.py tests/test_brick_ttl.py tests/test_db_ontology.py \
  tests/test_admin_config.py tests/test_admin_api.py tests/test_config_panel_assets.py \
  tests/test_datasource_create.py -q

# blocking lint gate + formatting
flake8 orchestrator/ shared/ --select=F821,F823
black --line-length 100 orchestrator/ shared/ tests/ && isort --profile black orchestrator/ tests/
```
Fix any failures at root cause (don't weaken assertions). Note the one pre-existing branch failure
`tests/test_routing_and_contracts.py::test_general_knowledge_routes_to_response` is UNRELATED to
this feature (confirm via `git stash` of `workflow/_routing.py`/`_orchestrator.py` if unsure).

## Task 3 — Live smoke (stack must be up)

```bash
docker compose ps                       # all healthy? config-panel present?
# .env must have DATASOURCE_TOGGLES_ENABLED=true and ADMIN_USERNAME/ADMIN_PASSWORD set.
# Current admin (dev): admin@ontosage / AdminpassOntosage2026!
TOK=$(curl -s -X POST http://127.0.0.1:3001/auth/login -H 'Content-Type: application/json' \
  -d '{"username":"admin@ontosage","password":"AdminpassOntosage2026!"}' \
  | python -c "import sys,json;print(json.load(sys.stdin)['data']['session_token'])")
curl -s http://127.0.0.1:3001/api/v1/datasources | python -m json.tool            # feature on, 8 sources
curl -s -X POST http://127.0.0.1:3001/api/v1/admin/databases/test -H "Authorization: Bearer $TOK" \
  -H 'Content-Type: application/json' -d '{"key":"database1"}'                     # ok + latency
curl -s "http://127.0.0.1:3001/api/v1/admin/databases/occupancy_data/data?table=occupancy_data" \
  -H "Authorization: Bearer $TOK"                                                  # rows + sensors
curl -s http://127.0.0.1:3001/api/v1/admin/databases -H "Authorization: Bearer $TOK" \
  | python -c "import sys,json;d=json.load(sys.stdin)['data'];print('active',sum(x['active'] for x in d['databases']),'of',len(d['databases']))"
```

## Task 4 — ADD a new end-to-end QA capability test (the main extension)

**Goal:** prove the value proposition — *connecting a data source unlocks questions that were
previously unanswerable* — as an automated, reproducible check.

Do BOTH of these:

**(A) A live end-to-end flow** (script it under `scripts/` or a `@pytest.mark.live` test):
1. Pick a genuinely-missing modality for bldg1 — **noise** (`Sound_Level_Sensor` count = 0 in
   GraphDB) is the cleanest; occupancy/energy exist in small numbers, iaq/light overlap.
   *Alternatively* create a brand-new source via `POST /api/v1/datasources` on a real building
   space (verify the `location` exists: `SELECT DISTINCT ?f WHERE { ?f a brick:Floor }`).
2. **Before** (source disabled): ask a matching question via `POST /chat` (RBAC `sensor:read`) and
   assert you get the **locked-capability decline** ("enable … to unlock").
3. `regenerate` (writes MySQL) then `enable` (writes GraphDB triples) the source.
4. **After**: ask the same question; assert (a) a substantive answer, and (b) a **provenance chip**
   naming the source (e.g. "Acoustic Sensing System · simulated") in the response / `sources` array.
5. Clean up (disable + optionally clear the named graph) so the test is idempotent.

   ⚠️ **Critical thing to verify/fix:** synthetic points must sit on `location` URIs that EXIST in
   the ontology, or SPARQL won't join and the "after" answer stays empty. Inspect
   `input/datasources.yaml` point `location`s and adjust to real spaces if needed. This is the most
   likely real bug in the enable→answer path — surface it.

**(B) A NEW curated question set** proving the capability envelope:
- Add ~10–20 questions to a small fixture (e.g. extend `scripts/ontosage_qa_suite.py` or a new
  `tests/fixtures/`), each tagged with the `datasource` it requires and the `expected` behavior
  when that source is OFF (locked decline) vs ON (answered). Cover multiple stakeholders using
  `config-panel/html/capabilities.json` as the source of realistic questions.
- If you extend the ontology to make more questions answerable, **do it TTL-first** (add triples /
  register sensors via `db_ontology`), not with hard-coded routes.

## Known limitations — do NOT "fix" these (they are deliberate)

- **`.env`/new-DB-connection changes need a container RECREATE** (`docker compose up -d
  orchestrator`), not a restart — Docker bakes env at create; 19 infra keys are literal overrides.
  Auto-recreate from inside a container was attempted and REMOVED (broke the orchestrator on
  Windows Docker Desktop / path mangling). The console shows the recreate command + a code-only
  restart button. Don't re-add an auto-recreate helper without an explicit ask.
- **iaq / light are intentionally NOT gated** (they overlap real abacws CO2/illuminance sensors).
- **Locked gate is keyword-based** (conservative by design) — only fires on curated `match_keywords`.
- **Capabilities catalogue is a static presentational JSON** served by nginx (not backend).

## Deliverables

1. A ranked review-findings list (bugs first) with file:line + failure scenarios.
2. Green offline suite + lint; note & explain any pre-existing unrelated failures.
3. Live smoke results (endpoint outputs).
4. The new end-to-end QA capability test/script (Task 4A) + the curated question set (Task 4B),
   both runnable, with results (before=locked, after=answered+provenance).
5. Any root-cause fixes (esp. the point-`location` join issue) — TTL-first, no committing.
