# OntoSage Full-System Verification & Hardening — 2026-06-12

Tester/developer session against `tasks/IMPLEMENTATION_PLAN_V3.md` (T01–T37 all
tracked done) and `tasks/SYSTEM_REVIEW_2026_06_12.md` (P0 security batch).
Goal: prove the "new building = input files only" promise, multi-persona access,
all intent families answering, honest missing-capability answers — and fix what
is broken. Everything below was verified against the **live stack**
(127.0.0.1:8000) plus the offline suites.

---

## 1. What was verified GREEN (no action needed)

| Check | Result |
|---|---|
| Unit suite (`pytest -m unit`) | 132 passed / 2 skipped (was 130 — 2 new bypass tests added) |
| Blocking lint gate (flake8 F821/F823) | clean |
| bandit `-ll` | 0 HIGH / 10 MEDIUM (the 10 = previously triaged parameterized B608) |
| `/health` | all services ok, circuit breakers closed |
| Auth: anon `/chat`, `/chat/stream`, `/conversations/*` | all 401 |
| Auth: `/v1` missing/wrong bearer key | 401 |
| Register → login → authed `/chat` | 200 with live sensor data (fresh timestamps) |
| Password policy (short password) | 422 via Pydantic |
| Role self-assignment on register | ignored — role stays `facility_manager` |
| readonly role on `/chat` | 403 naming the missing `sensor:read` permission |
| Port hardening | only 8000 (orchestrator) + 3000 (OpenWebUI) public; every datastore + code-executor bound to 127.0.0.1 |
| CI gates | bandit HIGH-blocking JSON gate + pip-audit job present as documented |
| Feed framework | polling runs as a lifespan asyncio task on per-feed intervals; the review's "write_records during read queries" observation is benign scheduler coincidence, not request-path work |
| Missing-modality honesty | "gas consumption this week" → honest answer grounded in what the ontology actually has (MQ-series gas sensors), no hallucinated data |

## 2. Bugs found and FIXED this session

### 2.1 CRITICAL — registry intents dead in live routing (alert / preferences / automation-capability)
**Symptom (live-reproduced):** "list my alerts" ran the **SPARQL data pipeline**
and answered with a list of power sensors. T21 (conversational alerts), T35
(preferences) and T22 (automation-capability) never executed on the live paths.
**Root cause:** the dialogue node's legacy dispatch chain switches on a local
`intent` variable and sets `state.current_intent` (which `_route_from_dialogue`
reads). The chain has no branches for YAML-registered intents like `alert`,
so its `else` forced `current_intent = "sparql"`. Additionally, the T22/T34/
benchmark deterministic overrides wrote `intermediate_results["intent"]` only —
routing never saw them.
**Fix:** (a) re-sync local intent from `intermediate_results["intent"]` after
the override block; (b) registry fallthrough in the chain's `else` — if the
intent registry knows the label, preserve it as `current_intent`.
**Tests:** `tests/test_workflow_wiring.py::test_dialogue_chain_preserves_registry_intents`
and `::test_registry_standalone_intents_route_to_registered_nodes`.
Files: `orchestrator/workflow/_orchestrator.py`.

### 2.2 CRITICAL — user_role never injected into workflow state
**Symptom (live-reproduced):** a `facility_manager` issuing "Set the setpoint of
room 5.01 to 22 degrees" was declined with "(role: readonly)".
**Root cause:** `control_agent` / alert node / preference node read
`intermediate_results["user_role"]` (default "readonly"/"guest"), but **no
endpoint ever wrote it**. Every authenticated user was treated as guest →
actuation approval (T25), alert creation (T21) and preference storage (T35)
were unconditionally declined on every endpoint.
**Fix:** inject `user_id` + `user_role` from the authenticated `UserContext`
into state on `/chat` and `/chat/stream`; pin `/v1` to `readonly` (matches the
P0.7 external-identity least-privilege decision — alerts/preferences work,
control stays declined for OpenWebUI users).
Files: `orchestrator/main.py` (3 sites).

### 2.3 HIGH — control agent crashed on string-shaped entities
**Symptom (live-reproduced):** every control command answered "I processed your
request, but couldn't generate a response." Logs: `'str' object has no
attribute 'get'` at `control_agent.py:102`.
**Root cause:** the dialogue LLM emits entities as either dicts or plain
strings; `control_agent` (2 sites) and `maintenance_agent` (7 sites) assumed
dicts.
**Fix:** tolerant `_entity_value()` helper in both agents.
**Tests:** `tests/test_control_execute.py::TestStringEntityShapes` (3 tests).

### 2.4 HIGH — capability KB hijacks live data questions (embedding-provider drift)
**Symptom (live-reproduced):** "What is the latest CO2 in room 5.01?" answered
with generic building info (score 0.684 high-confidence override, LLM skipped).
**Root cause:** semantic-router thresholds (0.56/0.60) in
`input/bldg1/building.yaml` were calibrated for **local MiniLM** embeddings, but
the stack now runs **OpenAI** embeddings (the building.yaml RE-CALIBRATION
CONTRACT is being violated; OpenAI scores run higher). The data-query bypass
only knew formal sensor IDs, "zone N.NN" and a fixed phrase list.
**Fix (defence in depth):** generic bypass rule — room/floor locator
(`room 5.01`, `floor 3`) + measurement keyword → data pipeline, never KB.
**Tests:** 2 new unit tests in `tests/test_maintenance_routing.py`.
**Still open:** thresholds themselves need re-calibration for OpenAI embeddings
(see §4).

### 2.5 MEDIUM — automation-capability questions declined as control commands
**Symptom (live-reproduced):** "Can the building automatically close the blinds
when it gets sunny?" → control decline instead of the T22 honest capability
answer. `is_control_command()` matched "close the blinds" with no question
awareness, beating the T22 detector (routing-precedence inversion).
**Fix:** `_AUTOMATION_CAPABILITY_Q_RE` guard in `is_control_command()` — modal +
building/system subject + autonomy cue is a question, never a command.
("Can **you** open the door" keeps subject *you* and remains a command.)

### 2.6 MEDIUM — T34 what-if estimates never ran (known WARN, now fixed)
Interventional what-ifs ("what would happen if we lowered heating 2 °C?") were
classified trend → forecast pipeline; the estimate-recipe path never executed.
**Fix:** `whatif_intent_override()` (module-level, testable) — overrides to
analytics ONLY for hypothetical-intervention phrasing on data-pipeline intents;
control/alert/report-intake are never hijacked.
**Tests:** 9 parametrized cases in `tests/test_routing_accuracy.py`.

### 2.7 MEDIUM — T37 validator passed vacuously on a missing building
`validate_building_input("ghost")` returned PASS with every file "absent —
skipped" — exactly the silent failure T37 exists to prevent.
**Fix:** missing `input/<id>/` directory now FAILS with an actionable message
naming the scaffold command. Test added (33 validator tests pass).

### 2.8 MEDIUM — T29 portability artifact (input/bldg2/) was lost
`input/bldg2/` (the files-only onboarding proof) was never committed and no
longer existed on disk; the old `bldg2-example` is deleted in the working tree.
**Fix:** recreated the full bldg2 set per the T29 tracker spec: `building.yaml`
(namespace `http://innovationhub.example.org/hub#`, `actuation.driver: none`),
`bldg2_core.ttl` (1 floor, 5 sensors incl. `Water_Level_Sensor` — a modality
bldg1 lacks), `capability.yaml` (5 entries), `feeds.yaml` (rainwater_tank
csv_drop + 336-row synthetic CSV), `rules.yaml` (tank <20% rule),
`channels.yaml`, `benchmarks.csv`, `documents/governance.md`, `concepts.ttl`
("the hub" → Room_101). **Verified:** all T37 validators PASS;
`swap_building.py --to bldg2 --dry-run` PASSES (namespace ↔ TTL prefix check
included). Zero code changes were needed — the files-only contract holds.

### 2.9 LOW — stale capability content contradicted T10
`input/bldg1/capability.yaml` still said "live data currently Floor 5 ONLY /
Floors 1-4 not yet connected" (false since T10) — and this stale text was being
served in live answers. Updated (2 places) to reflect floors 0–5 streaming
(floor 5 hardware, 0–4 simulated) + feed-framework modalities.

### 2.10 LOW — unstable /v1 conversation-id fallback (P1.10)
`owui_{abs(hash(...))}` is salted per process → memory severed on every
restart. Replaced with SHA-256 digest (live handler).

### 2.11 HIGH — "approve <id>" flow was unreachable
`control_agent` read `intermediate_results["user_query"]` to detect the
"approve <id>" phrase — but **no code anywhere writes that key**, so
`raw_query` was always empty and the second half of the T25 approval
round-trip (queue → approve → execute) could never trigger.
**Fix:** fall back to `state.messages[-1].content` / `state.user_message`.
**Test:** `tests/test_control_execute.py::TestApproveFromMessages`.

### 2.12 MEDIUM — building_id read from a never-populated key
`control_agent` and `maintenance_agent` read
`intermediate_results["building_id"]` (never written anywhere) and defaulted to
`"bldg1"` / `"unknown"` — after a building swap, control would have consulted
**bldg1's** actuation config (driver `sim`!) while serving bldg2, and
maintenance tickets were filed against building "unknown".
**Fix:** prefer `state.building_id` (the populated model field) in both agents.

### 2.13 MEDIUM — two more producer-less state reads (systematic scan)
A repo-wide scan for `intermediate_results` keys that are read but never
written found two more (beyond user_role/user_query/building_id):
- `time_range` — a **documented reserved key** that the dialogue node never
  stored; `analytics_agent` and `verifier_agent` always saw `{}` and lost all
  time-range context. Now stored in `_dialogue_node`.
- `dialogue_result` — the recommend node read
  `get("dialogue_result", {}).get("recommendation_domain")`, which always fell
  back to "general", so domain-specific recommendation prompts never fired.
  Now reads the actually-stored `recommendation_domain` key.
(`answer_length`, `user_permissions`, `degraded_services`, `document_type`
were also flagged and triaged as intentional optionals / setdefault-written.)

### 2.14 CI gap — validator tests never ran in CI
`tests/test_input_validators.py` (34 tests guarding the portability contract)
was missing from the CI file list. Added to `.github/workflows/ci.yml`.

### 2.15 HIGH — registry intent nodes had no outgoing graph edge
Once routing was fixed (2.1), the alert / preference / automation-capability
nodes RAN — but their replies were still dropped: `_build_graph` hand-enumerates
`add_edge(node, "response")` and auto-registered registry nodes got **no
outgoing edge**, dangling to END. The response node never composed their
`dialogue_response`, so the user got an echo of their own question.
**Fix:** every registry-registered intent node without an explicit edge is now
auto-wired → `response` (makes the "edges are auto-generated" CLAUDE.md claim
true). **Test:** `test_registry_intent_nodes_have_response_edge` (behavioral,
inspects the compiled graph).

### 2.16 HIGH — three Redis-backed stores used non-existent accessors
- `actuation/approval_store.py` called `redis_manager.get_client()` (5 sites) —
  **method does not exist**. Every approval write/read failed and the warning
  swallowed it: approvals were never persisted, so `approve <id>` always
  answered "No pending request found". **Broken since T24.**
- `user_alert_store.py` called `redis_manager._ensure_client()` — also did not
  exist → alert list/delete silently returned empty.
- `user_preference_store.py` used `redis_manager.redis` — also non-existent →
  preference list/forget broken.
The unit tests passed because their mocks exposed the same phantom interfaces.
**Fix:** one canonical `RedisManager._ensure_client()` (connect-lazily helper),
all three stores routed through it, test mocks corrected to the real interface.

### 2.17 MEDIUM — alert node crashed on empty list + "approve" lost to co-reference rewrite
- `_alert_mgmt_node` list branch: `"\n".join(lines)` sat outside the else —
  `UnboundLocalError` whenever the user had zero alerts (i.e. always, on first
  use).
- The co-reference rewriter expands "approve 606ba770" into "Can you please
  approve the command with ID 606ba770 …", and `_APPROVE_RE` required the hex
  id immediately after "approve" — approval requests were re-classified as new
  control commands. Regex now tolerates up to 40 chars between verb and id.
- Cosmetic: alert list rendered "co2_level > 1000.0 > 1000.0" (condition
  duplicated into the auto-generated name).

### 2.18 QA-suite fixes (test harness, not system)
- The multi-turn conversation runner sent no `/v1` bearer key (predates P0.1) —
  all 47 conversation turns failed with 401. Now sends `PIPELINE_API_KEY`.
- `should_decline` grading updated for T25: a guarded approval queue satisfies
  the "never executes directly" safety expectation alongside a polite decline
  (including persona-formatter rephrasings).

## 3. Live QA battery

Full `scripts/ontosage_qa_suite.py` run (286 graded items = 236 single
questions + 15 multi-turn conversations) against the **pre-fix** container
(baseline, `scripts/outputs/qa_run_20260612_150417.{json,md}`, 80 min):

| Tier | Count | Reading |
|---|---|---|
| PASS | 231 | |
| FAIL | 51 | **47 were the QA suite's own bug** — its conversation runner never sent the `/v1` bearer key required since P0.1 (fixed this session); 4 real |
| WARN | 4 | |

The 4 real FAILs and 4 WARNs, re-tested on the **fixed** container:

| Case | Baseline | After fixes | What changed |
|---|---|---|---|
| CT01/CT03 (control commands) | FAIL — entity crash → generic dead-end | **PASS** — guarded approval queue (QA expectation updated: decline OR approval gate both satisfy "never executes directly") |
| WF04 ("Should I open the windows…?") | FAIL — misrouted to control + crash | **PASS** — advice-question guard → analytics with window-opening guidance |
| WI01 (interventional what-if) | WARN — routed to forecast | **PASS** — estimate-recipe path runs |
| MX03 (equipment attention) | WARN | **PASS** |
| RP02 (weekly summary report) | FAIL — pipeline timeout | still slow — pre-existing report-pipeline latency (see §4) |
| OC02 ("How crowded is the building?") | WARN | still WARN — building-wide occupancy aggregation + threshold recalibration needed (§4.1) |
| IQ05 (water flow / leak) | WARN | still WARN — anomaly pipeline does not select the water_main feed sensor |
| CONV14 (3-turn occupant journey) | FAIL ×3 (suite auth bug) | **PASS 3/3** — incl. live reading with memory follow-up |

Post-fix targeted verification: `python scripts/verify_fixes_live.py` → **7/7**,
including the full T25 loop live: setpoint command → pending approval →
`approve <id>` → SimDriver executes → audit ID returned. Alert
create→list→delete round-trip verified live (T21).

## 4. Recommendations (not done this session — priority order)

1. **Re-calibrate semantic-router thresholds for OpenAI embeddings** (or pin
   `EMBEDDING_PROVIDER=local`). The building.yaml contract says score
   distributions shift per provider; 0.684 on a data question proves the local
   thresholds are too low for OpenAI vectors. Use the 11-query calibration
   batch documented in `input/bldg1/building.yaml`.
2. **Set a real `PIPELINE_API_KEY`** in `.env` — the compose default
   `sk-ontobot-pipeline` is in effect (acceptable for dev; STRICT_SECRETS
   refuses it in production, test exists).
3. **bldg1 `building.yaml` lacks `ontology_namespace`** — swapping *back* to
   bldg1 after a bldg2 swap will fail validation. Add the key.
4. **Unify the 3 chat front doors** (`run_turn()`, review A3) — the user_role
   injection had to be triplicated; that's the structural smell.
5. **Live-swap rehearsal to bldg2 and back** — dry-run passes; the actual swap
   (with GraphDB re-upload + QA) should be rehearsed before any demo that
   depends on it.
6. The dialogue dispatch chain (947–1042 in `_orchestrator.py`) should be
   replaced by pure registry dispatch — the legacy chain caused 2.1 and will
   cause it again for the next YAML intent that nobody adds to the chain.
7. **RP02 — report-pipeline latency**: "weekly building performance summary"
   exceeds the request timeout and returns the apology fallback. Needs the P2.4
   latency treatment (or routing report-family questions to the async job path
   that already exists for long reports).
8. **OC02 — building-wide occupancy**: "How crowded is the building today?"
   has no room/floor locator, so it reaches the capability KB / general path
   instead of aggregating the six occupancy_floor* feeds. Needs a
   building-level occupancy aggregation recipe + (again) threshold
   recalibration.
9. **IQ05 — water-leak heuristic**: the anomaly pipeline does not select the
   `water_main` feed sensor; the T18 night-flow leak recipe never gets data.
10. The dialogue LLM should be constrained to emit dict-shaped entities
    (schema in the intent prompt) — the string/dict ambiguity caused 2.3 and
    will keep producing latent crashes in agents that forget `_entity_value`.

## 5. Files changed this session

| File | Change |
|---|---|
| `orchestrator/workflow/_orchestrator.py` | registry fallthrough + override re-sync + `whatif_intent_override()` + alert-node UnboundLocalError + time_range stored + recommendation_domain read + alert-list label |
| `orchestrator/workflow/_graph.py` | auto-wire registry intent nodes → response |
| `orchestrator/main.py` | user_role/user_id injection (3 endpoints), SHA-256 conv-id |
| `orchestrator/redis_manager.py` | canonical `_ensure_client()` helper |
| `orchestrator/agents/control_agent.py` | `_entity_value()` crash fix; messages fallback for approve; coref-tolerant `_APPROVE_RE`; `state.building_id` |
| `orchestrator/agents/maintenance_agent.py` | `_entity_value()` crash fix (7 sites); `state.building_id` |
| `orchestrator/services/semantic_router.py` | room/floor+measurement data bypass; automation-question + advice-question guards in `is_control_command` |
| `orchestrator/services/input_validators.py` | missing-building-dir hard fail |
| `orchestrator/services/actuation/approval_store.py` | real Redis accessor (5 sites) |
| `orchestrator/services/user_preference_store.py` | real Redis accessor (scan/get/delete) |
| `input/bldg1/capability.yaml` | stale floor-5-only content corrected |
| `input/bldg2/**` (NEW, 10 files) | T29 portability artifact recreated |
| `.github/workflows/ci.yml` | + `tests/test_input_validators.py` |
| `scripts/ontosage_qa_suite.py` | conversation auth header; guarded-control grading |
| `scripts/verify_fixes_live.py` (NEW) | 7-check post-fix live verification, repeatable |
| `tests/test_routing_accuracy.py` | +9 what-if override tests (77 total) |
| `tests/test_control_execute.py` | +3 entity-shape, +1 approve-from-messages, +3 approve-regex tests (17 total) |
| `tests/test_maintenance_routing.py` | +2 data-bypass, +2 control-guard tests (9 total) |
| `tests/test_workflow_wiring.py` | +3 wiring invariants incl. compiled-graph edge check (6 total) |
| `tests/test_input_validators.py` | +1 missing-dir test (33 total) |
| `tests/test_actuation_approval.py` / `tests/test_user_preference_store.py` | mocks corrected to the REAL Redis interface (phantom mocks had masked 2.16) |

Final state: **134 unit pass / 0 fail**, flake8 F821/F823 clean, bandit 0 HIGH,
black applied to all touched files, `orchestrator.main` imports, live stack
healthy, `scripts/verify_fixes_live.py` **7/7**, control QA CT01–CT03 **3/3**.

**Not committed** — per project rule, awaiting user review.

---

## 6. Follow-up (2026-06-13): the namespace contract standardized

User decision: standardize on a fixed `bldg:` prefix **label** for every
building with a **unique namespace URI per building**, declared once in
`building.yaml: ontology_namespace`. Implemented and verified:

1. **bldg1 `building.yaml` now declares `ontology_namespace`** (closes §4.3 —
   the namespace previously came only from the hardcoded default in
   `shared/config.py`; swapping back to bldg1 would have failed validation).
   Verified: all 6 bldg1 TTLs validate clean against the declared URI.
2. **`@base` consistency check** added to `ttl_validator.py` (WARN tier — a
   foreign `@base` makes relative IRIs resolve into another namespace and
   vanish from SPARQL; absent `@base` stays fine). Detects both `@base` and
   SPARQL-style `BASE` forms. +4 tests (14 total in the suite).
3. **Namespace contract documented** in `input/README.md` (fixed label /
   unique URI / declared-once / curies-only-in-YAML / URI-choosing rule:
   institution domain, else `http://ontosage.org/buildings/<id>#`).
4. **`input/_templates/building.yaml` created** — scaffolded buildings now get
   a swap-ready identity file with the namespace rule inline and the
   ontosage.org fallback URI pre-filled with their id.
5. **Bug found by the scaffold round-trip:** the shipped `rules.yaml` template
   still used pre-T29 field names (`value`/`point_uuid` vs
   `threshold`/`sensor_uuid`) — every freshly scaffolded building failed
   validation on first contact. Template fixed; regression test added that
   scaffolds from the REAL templates and asserts the result validates clean.
6. **Bug: `input_validators.py` opened files with the platform encoding** —
   any non-ASCII config (em-dashes, accented names) crashed validation on
   Windows instead of being read. All 5 opens now `encoding="utf-8"`.
7. **Lineage clarification for §2.8:** `archive/input2/bldg2/` exists but is
   the *older replacement-set* bldg2 (namespace `http://buildsys.org/...`),
   not the lost T29 artifact (tracker records `innovationhub.example.org`,
   matching the recreation at `input/bldg2/`).

Verified end-to-end: 54 validator/swap tests pass, 134 unit pass, gate clean,
`swap_building.py --to bldg2 --dry-run` passes, scaffold→validate round-trip
on a temp building passes out of the box.

---

## 7. Follow-up (2026-06-13, part 2): input/ restructured to the replacement-set model

User decision: `input/` holds the **active building only** (root shared files +
ONE `input/<id>/` folder); parked buildings live as complete `input/`
replacement sets in `archive/input2/` (bldg2), `archive/input3/` (bldg3) —
activation = copy the set's contents over `input/`, then swap.

**Restructure performed (live-verified):**
1. The 4 root-level bldg1 TTLs (`bldg1_abacws_metadata`, `bldg1_enhancements`,
   `bldg1_expanded_protege_clean`, `bldg1_floors_0_4_sensors`) moved into
   `input/bldg1/` (tracked files via `git mv`). The uploader supports both
   layouts; named graphs are keyed by filename, so the moved files re-uploaded
   idempotently into their existing graphs: **uploaded=4 skipped=4 failed=0**,
   validator reports 6/6 bldg1 TTLs OK, health green, data questions answer
   with live values post-restart. `input/` root now holds only shared files
   (Brick schemas, database_registry, _templates, personas, floor-plan PDFs).
2. **§2.8 correction:** the original T29 synthetic bldg2 was never lost — it
   had been parked in `archive/deprecated-buildings/bldg2/` (the archive
   README already said so). The 2026-06-12 recreation at `input/bldg2/` was a
   redundant duplicate; deleted. The original keeps a provenance README.
3. `scripts/generate_floors_0_4_sensors.py` paths updated to the new layout.
4. **archive/input2 (the REAL bldg2) validated as swap-ready:** complete set
   (Brick schemas, database_registry, _templates, personas, mysql-init,
   bldg2/ with building.yaml declaring `building_id` + `ontology_namespace`);
   TTL validation 2/2 clean; optional-file validators PASS. The new `@base`
   check caught a Protégé export artifact (`@base <https://w3id.org/rec>`) in
   the 11 MB `bldg2_expanded_protege.ttl` — verified zero actual relative
   IRIs in the file (the `<device>` hits are inside documentation string
   literals), then aligned `@base` to the building namespace. 0 warnings now.
5. `swap_building.py --to bldg2` with no staged folder now fails loudly with
   the actionable drop-files-first message (the §2.7 validator fix doing its
   job under the replacement model).
6. `input/README.md` documents the replacement-set activation step.

Verified: 134 unit pass, 73 uploader/validator/swap/input tests pass, gate
clean, stack healthy on the new layout.
