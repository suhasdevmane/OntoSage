# IMPROVEMENT PLAN V4 — ARBITER, the Deliberative Brain of OntoSage

**Date:** 2026-08-13 · **Status:** PROPOSED (awaiting user/supervisor review — no code changes yet)
**Timeline:** ~3–4 months (16 weeks) · **Decided inputs:** dossier-only synthetic disclosure;
"brain routes everything" implemented as one plan formalism with two execution regimes (see §3.1).

**How this plan was produced:** 8 parallel code-reader agents grounded every claim in the actual
codebase (file:line refs throughout); a web novelty scan surveyed the 2023–2026 literature; three
independent design agents (neuro-symbolic purist / pragmatic staff engineer / evaluation-first)
proposed architectures that **converged on the same design** — synthesized here. Raw outputs:
`%TEMP%\claude\...\tasks\wf_split\` (session-local).

---

## 0. Executive summary

Build **ARBITER** ("the LLM proposes, the symbolic layer disposes") — a deliberative planning
layer that turns vague, multi-constraint stakeholder questions ("I'm visiting tomorrow — where can
I sit that's quiet, with good air, near water?") into: a typed constraint program → admission
check against the building's live self-description → candidate-space enumeration → per-candidate
data fetch + forecast fan-out → **deterministic, standards-anchored scoring (the LLM never
produces a number)** → an answer carrying a **machine-re-executable evidence dossier**. Ask at
most ONE clarifying question, and only when interpretations materially diverge; otherwise proceed
with declared assumptions.

Prerequisite substrate: **SATURATE** — a building-agnostic coverage auditor + synthetic-sensor
provisioner (TTL named graphs + narrow MySQL tables + correlated physics-lite signals +
per-sensor `ontosage:isSimulated` labels) so every room in all 3 buildings has occupancy / CO₂ /
noise / temp / light / contact coverage, plus structured amenity individuals (water points,
seating) so "near water" resolves to a space IRI instead of prose.

Evaluation: a new in-repo **L7 deliberative benchmark** graded against **deterministic ground
truth computed independently from the same DB**, split-metric reporting (data-backed vs
honest-decline — fixes NOTE-142), fabrication-rate before/after, clarification precision/recall,
and the determinism proof (identical dossier under `MODEL_PROVIDER=local` vs `openai`).
Portability across bldg1/2/3 is the **validation method**, not a headline claim (BuildingGPT2
already publishes zero-shot cross-building Brick QA).

---

## 1. Stress-test of the original ask (read this before the supervisor meeting)

1. **"Answerable to any question" is unfalsifiable.** No examiner accepts "any question." The
   defensible form is: a defined question space (the 6,117-question survey corpus + a new L7
   deliberative tier), measured coverage, and split metrics. Related: the current headline
   (63.8% / 70.4%) is **already vulnerable** — NOTE-142 (OPEN) records that it counts honest
   declines as PASS; the 2026-07-22 bldg1 replay was 82.9% PASS but only **44.6% data-backed**.
   A system that declines everything would score 100% under current semantics. Fix the metric
   before quoting any number in the thesis.
2. **Synthetic saturation alone doesn't create answerability — and it can be turned against you.**
   The project's own non-negotiable #4 ("never fabricate") invites the viva question: *"how is a
   provenance-labeled synthetic CO₂ reading different from a well-labeled hallucination?"* The
   answer must be built in, not improvised: simulation/what-if semantics, per-sensor
   `ontosage:isSimulated`, per-row dossier provenance, real-vs-simulated rates reported
   separately, and a real-data contrast slice (bldg1 floor-5 IAQ is genuinely instrumented).
   Never claim "the building is fully queryable" as fact.
3. **An LLM agent/planner is not novel in 2026.** The lane is crowded: BuildingGPT/BuildingGPT2
   (Brick QA, zero-shot on held-out buildings), JARVIS (compiled multi-stage plans over HVAC
   SQL), CSIMQ hybrid KG+TSDB+LLM, Graph-DT-GPT. Even "portability across buildings" is no longer
   a standalone claim. What IS open: the **intersection** (§2) and the **measurements** nobody
   reports (fabrication-rate reduction, clarification precision, dossier re-executability).
4. **"Brain routes everything" as literally-LLM-planning-every-query would be a design flaw** —
   seconds of latency on "what's the temperature in zone 3," and it re-risks 523 passing tests
   for zero gain. §3.1 gives the version that survives scrutiny.
5. **The thesis delta vs your own published WWW/Springer 2026 OntoSage paper must be explicit**,
   or examiners read ARBITER as an increment on your own system. A delta table (journal =
   NL→SPARQL + analytics; thesis = constraint deliberation + clarification policy + dossier +
   saturation + L7 benchmark) is mandatory in the related-work chapter.

---

## 2. Thesis positioning — four contribution claims

Framing rule from the novelty scan: **claim the intersection and the measurements, cite the
lineage for each part.** Related-work chapter = three lanes (Brick/KG QA · agentic clarification ·
attributable answers), showing each lane is blind to the other two.

- **C1 — Neuro-symbolic deliberative QA over a building's heterogeneous knowledge.** NL compiles
  to a typed Constraint-Query IR (closed vocabulary); an admission gate validates it against a
  live graph-derived Building Capability Schema **before** execution; execution and scoring are
  deterministic. Falsifiable determinism artifact: same query, LLM swapped (gpt-oss:20b ↔
  OpenAI) → identical plan hash and evidence table. Delta vs BuildingGPT2 (static-model QA only)
  and JARVIS (single-system SQL, no ontology, no candidate ranking).
- **C2 — Ontology-grounded clarify-or-proceed policy, measured end-to-end.** Interpretation sets
  are enumerated from the graph (SPARQL referent/threshold resolution); ask exactly one targeted
  question only when interpretations change the outcome (candidate-set Jaccard / rank-flip on a
  metadata-only dry run). Claimed as the **domain instantiation with measurement** — EVPI /
  information-gain clarification papers (2025–26) are cited lineage, not competitors.
- **C3 — Proof-carrying answers with measured fabrication reduction.** The composite dossier
  (CQ-IR + coverage ledger + candidate×criterion evidence table + executed SPARQL/SQL + forecast
  backtests + score table) is **machine-re-executable**: an independent grader replays its
  queries and verifies every prose number. Cite PCN as protocol analogue; the deployed composite
  artifact + the fabrication-rate number on a survey-derived corpus is the claim.
- **C4 — Coverage auditing with simulation-backed saturation as a queryability substrate**
  (defensively framed). Auditor → provisioner → correlated publisher, building-agnostic, with
  per-sensor epistemic labels flowing to per-answer disclosure. **Portability on 3 buildings is
  the validation method certifying C1–C3**, evidenced by zero-building-literal source-scan tests
  and code-identical benchmark runs — not a standalone contribution.

---

## 3. Architecture — ARBITER

New intent `deliberate` (2-step auto-wire: `intent_definitions.yaml` entry with
`pipeline_group: standalone`, `cacheable: false`, `node_method: _deliberate_node`; **one** rule
appended at the END of `routing_contract.py` PARSE_STAGE_RULES with from-set limited to weak
intents; `test_precedence_order_is_pinned` updated in the same commit — note the real rule count
is **17 parse + 1 post + 1 concept**, CLAUDE.md's "13+1" is stale). `deliberate` joins the
referent gate's GATED_INTENTS. Six stages inside the node, all in a new package
`orchestrator/services/deliberation/`:

| # | Stage | What it does | Numbers from LLM? |
|---|-------|--------------|-------------------|
| 1 | **ConstraintCompiler** (`cqir.py`) | temp-0 LLM emits typed CQ-IR JSON: Goal{decision_kind, target_kind}, Constraint[]{modality→Brick class via `concept_resolver`, direction, hard/soft, threshold_source: recipe\|user\|default, weight}, SpatialQualifier[]{near\|on_floor\|adjacent, anchor}, TimeSpec via `horizon_parser` (extended to return UNPARSEABLE instead of silently defaulting to 24h). Unmappable terms → ambiguity signals, never guessed. | no — words→symbols only |
| 2 | **Admission gate** (`capability_schema.py`) | Validates CQ-IR against a live Building Capability Schema (subclass-closure space inventory; per-space modality→(uuid, storedAt, provenance) matrix from `ref:hasTimeseriesId`; amenity anchors; recipe thresholds). Returns ADMIT \| CLARIFY(question, options) \| DECLINE(enablement_hint). | no |
| 3 | **Clarify-or-proceed** (`clarify_policy.py`) | §6. One question max, structured options in the API payload, parked CQ-IR resumes after the reply. | no (template question) |
| 4 | **Fan-out executor** (`plan_executor.py`) | Typed DAG: enumerate candidates → per-candidate per-modality fetch (per-UUID limits) → `ForecastAgent.predict` per series for future TimeSpecs (top-K only) → centroid metric distance. Bounded `asyncio.gather`, per-step timeouts, plausibility gate on every value. | no |
| 5 | **DeterministicScorer** (`scorer.py`) | Recipe-anchored utilities normalized to [0,1] (ASHRAE/WHO/CIBSE-cited params — recipes finally EXECUTED, not prompt text), hard-filter then weighted soft aggregation, explicit missing-modality policy (coverage ledger; never impute, never silently drop), lexicographic tie-breaks. Pure Python, unit-tested. | **never** |
| 6 | **DossierBuilder + renderer** (`dossier.py`) | §7. Templated prose with programmatic number substitution; LLM may polish connective text under a numeric-consistency guard (every figure in prose must exist in the dossier). | words only |

### 3.1 "Brain routes everything" — the defensible version

One **plan formalism**, two **execution regimes**:

- **Reflex plans** (System 1): today's intent routes become pre-compiled plan templates. The
  existing `route_decision` audit trail (already written on every turn) is wrapped as a 1-step
  reflex plan trace; existing pipeline nodes are unchanged and remain the tool library. Zero
  LLM planning, zero added latency, 523 tests untouched.
- **Deliberative plans** (System 2): novel multi-constraint queries get full CQ-IR compilation +
  admission + fan-out.

By demo time, **every** answer carries a plan trace (reflex or deliberative) — the "one brain"
narrative holds architecturally and rhetorically ("a brain that re-derives reflexes from scratch
every time would be a design flaw; ARBITER has reflexes and deliberation in one formalism").
Unification is Phase 4, after the deliberative path is proven — never before.

### 3.2 What each component builds on (grounded reuse map)

| New component | Reuses (verified in code) |
|---|---|
| ConstraintCompiler | `multi_intent_detector.py` two-stage gate (heuristic + temp-0 validated JSON); `concept_resolver.resolve`; `forecasting/horizon_parser.py`; `llm_manager` |
| Capability Schema | `referent_resolver` `_exists_terms`/`_suggest_terms` + SPARQL-injection guards + asymmetric SKIPPED handling; `capability_graph_resolver` cached-SPARQL pattern; `building_profile.resolve` single-query VALUES design |
| Candidate enumerator | `generate_spatial_topology.py` space SPARQL (made subclass-closure-aware); `floor_plan_registry.load_manifest`; `FloorPlanManifest`/`Space` (models.py:487–559 — centroid, polygon, area_m2, adjacent_spaces already exist) |
| Clarify policy | `disambiguation_service` pending-state mechanism — **implements the missing `extract_clarification_answer`** (called at `_orchestrator.py:659` but never defined; error silently swallowed); `turn_memory` `_CARRY_FORWARD_KEYS` (+`pending_cqir`) |
| Executor | `planner_agent.py` ExecutionPlan/PlanStep + `_execute_multi_intent` fan-out chassis (45s timeouts, provenance strings); `sql_agent.fetch_data_for_uuids` + storage_map; `ForecastAgent.predict` (verified effectively state-free → callable per series); `MySQLNarrowAdapter.build_timeseries_query` ROW_NUMBER PARTITION BY for per-UUID limits |
| Scorer | `recipe_registry` + `config/recipes.yaml` (~35 standards-cited recipes); `plausibility._PLAUSIBLE` ranges (+binary/contact shapes) |
| Dossier | `verifier_agent` verification record (computed every turn, **never surfaced today**); the `sources` payload pipeline (`_orchestrator.py:3202–3211` → `main.py:2355`); `route_decision` audit-trail pattern; `Message.metadata` persistence |
| Spatial distance | ~20-line pure function over `Space.centroid` + manifest `bounding_box.width_m/height_m` (normalized coords are de-normalizable — verified) |

---

## 4. SATURATE — the data plan (building-agnostic, four stages)

Order: **bldg2 first** (52 rooms — smallest, proves the generator), then bldg3 (132), then
bldg1 (234 rooms, **all modalities including door/window contacts — full coverage is core
scope**, decision 2026-08-13). Build order ≠ scope: every building ends fully saturated.
Modality priority from `T5_new_capability_gaps.csv`: occupancy (21.7% of gap demand) → energy
→ lighting → IAQ → noise → water. The required-modality set is **config, not code** — any QA
family that demands a new modality gets a new narrow table + generated TTL in `input/` through
the same pipeline, zero code change (contract #8: onboarding a source = TTL + registry + rows).

1. **AUDIT** (`deliberation/coverage_audit.py` + script): subclass-closure SPARQL space
   enumeration (**bldg1 rooms are typed `Office`/`Laboratory`/… — a plain `?r a brick:Room`
   returns 0 there**; bldg2/3 use `a brick:Room`); read existing points via BOTH
   `brick:hasLocation` and `brick:isPointOf`→equipment paths; diff against required modality set
   {occupancy, CO₂, temp, humidity, noise, illuminance, door_contact, window_contact}. Output:
   per-building gap matrix CSV — itself a thesis artifact.
2. **PROVISION**: emit `input/<id>_saturation_<modality>.ttl` via
   `sensor_ttl_generator.generate_timeseries_ttl` (already namespace-parameterized) into named
   graphs `urn:ontosage:ds:sat_<modality>` (= on/off switch, reusing the bldg1
   `datasources.yaml` toggle framework — replicate to bldg2/3). **One UUID scheme**:
   deterministic uuid5 via `DataSourceRegistry.derive_point_uuid` (ends the
   uuid5/MD5/mnemonic divergence; hex-only satisfies both `_UUID_RE`s). Every sensor:
   `ontosage:isSimulated true` (formalize the `rdfs:comment "synthetic-…"` precedent into the
   OCBV TBox) + `ref:storedAt` to dedicated `sat_*` narrow keys **read from the active
   building's registry, never assumed**. Also emit a canonical `ontosage:zoneId` literal per
   space — this single triple repairs the **broken manifest↔ontology bridge** (0/101 spaces
   linked on bldg1 floor 5; exact-label match fails on `"HVAC Zone 5.28"@en`, dot-filter drops
   `3Z001` ids) without patching fragile label-matching code. Supersede
   `bldg1_enhancements.ttl`'s 106 placeholder UUIDs (TTL without rows violates contract #8).
3. **STORE**: runtime DDL (`load_timeseries_to_db.py` CREATE_SQL pattern — mysql-init only fires
   on first DB boot; never `USE sensordb`) creates narrow tables in the active building's DB
   (`${BUILDING_ID}_sensordb` / `sensordb`), adds `co2_data` + `contact_data` (0/1) to the
   existing 7; activate the narrow registry entries already present in all three
   `database_registry.yaml` via `building.yaml storage.databases` (today bldg1-only). Register
   every table in `datasources.yaml` **before first write** — and fix
   `provenance.build_tags`'s fallback: today an unregistered table is chip-labeled as REAL
   "Live Sensor Data" (`provenance.py:73`), which would torpedo the honesty story.
4. **SIGNAL** (correlated physics-lite publisher, extending `generate_dummy_timeseries.py`):
   per-room latent occupancy process (weekday/weekend, arrival/lunch/departure schedules by
   Brick room type) drives CO₂ (first-order lag + decay), noise (occupancy + transients), light
   (schedule + daylight), door-contact events at occupancy transitions; binary/state values
   supported (today: continuous floats only). Deterministic seed per (building, room, day) →
   reproducible ground truth for the L7 grader. 4–6 weeks backfill (ARIMA needs ≥30 points;
   today's fetch caps starve it — see §8 landmine 5) + live append. **Add the missing namespace
   filter to `fetch_points()`** (BUG-105 class). Realism claim: internal consistency for
   ground-truth grading, NOT fidelity to real buildings (SmartBuildSim-class realism explicitly
   out of scope).
5. **AMENITIES** (`generate_amenity_locations.py`): instantiate per-instance amenity individuals
   using the **already-defined but unused** OCBV vocabulary (`ontosage:locatedIn`, `onFloor`,
   `isSimulated`, 14 Amenity subclasses incl. DrinkingWater, StudyArea) so "near water" resolves
   to space IRIs + centroid distance, not prose `locationText`. Generated for bldg2/3, small
   hand-authored set for bldg1.

---

## 5. Clarification policy (deterministic, one-question budget)

Signals computed **before any data fetch**: S1 named referent NOT_FOUND (question embeds
referent_resolver's suggestion list as options) · S2 no mappable criteria ("I need a good spot")
· S3 horizon UNPARSEABLE and the goal is time-anchored · S4 hard-filtered candidate set empty ·
S5 conflicting constraints · S6 threshold ambiguity with high outcome divergence (candidate-set
Jaccard < 0.5 or top-1 flip across interpretations, measured on a metadata-only dry run — no data
fetched).

**ASK** exactly one question iff S1–S5 (blocking, no defensible default) or S6 above threshold —
the question targets the highest-divergence slot, template-generated (no LLM), surfaced as
**structured payload** (`needs_clarification`, `clarification_question`, `options[]` — new /chat
fields; today clarification is prose-only with nothing for a UI to bind to). **PROCEED** otherwise
with every default declared (recipe threshold + standard cited: "quiet = <40 dB per WHO", equal
weights, next-business-hours horizon) in an Assumptions block in both prose and dossier.
Asymmetric-failure rule inherited from the fabrication gate: existence check ERRORS → refuse to
assume, decline honestly. Parked CQ-IR persists via turn_memory carry-forward; the reply binds
through the newly implemented binder and the plan **resumes** (mid-plan resume does not exist
today — clarification always aborts to response). The same mechanism closes KNOWN-008
(maintenance-report slot filling). Policy thresholds are hyperparameters; §7 measures
clarification precision/recall — a first-class studied component, not UX polish.

---

## 6. Evidence dossier ("proof of analysis performed")

Typed pydantic `EvidenceDossier` in `intermediate_results['evidence_dossier']`, surfaced in
/chat + WebSocket payloads exactly like `sources`, persisted via `Message.metadata`;
`cacheable: false` (note: `response_cache.put` today stores only question/response/intent/media —
a cached deliberative answer would silently lose its proof). Contents:

1. **Interpretation** — compiled CQ-IR verbatim + Assumptions (each with source: recipe id +
   standard, or "user-stated") + the clarify decision and its trigger.
2. **Coverage ledger** — M candidates found, N instrumented per modality, excluded candidates
   with reasons (anti-survivor-bias guarantee: never rank silently over the instrumented subset).
3. **Evidence table** — rows of (candidate, criterion, value+unit, window, n_points, sensor
   UUID, storedAt table, provenance real|simulated, recipe id, normalized utility).
4. **Computation trace** — SPARQL/SQL texts, row counts, forecast entries (model chosen +
   hold-out MAE/**sMAPE** — MAPE is unstable on zero-heavy occupancy series), plan-step timings,
   and a **plan hash** (SHA of CQ-IR + candidate list + step DAG) proving replayability.
5. **Verdict** — scores, hard-filter survivors, tie-break rule, and the `verifier_agent`
   grounded/confidence record (finally surfaced).

Rendering: prose is template-generated with numbers substituted programmatically; a
**numeric-consistency guard** (extending `grounding_guard` with honesty_sweep's
`_MEASUREMENT_RE`) rejects any prose figure absent from the dossier — this guard is the
*mechanism* behind the fabrication-rate claim. Frontend: collapsible "How I worked this out"
panel — assumptions, coverage line, top-k evidence table with "· simulated" chips per synthetic
row, details link to the full trace. Honest declines carry a mini-dossier (candidates found,
missing modality, enablement_hint). **Machine contract:** the dossier is re-executable — the L7
grader replays its queries and recomputes the ranking; dossier fidelity is a reported metric.

---

## 7. Evaluation plan

- **Step 0 (prerequisite — NOTE-142):** split PASS into data-backed vs honest-decline rates
  everywhere; re-run the 240q replay on bldg1+bldg2 post-honesty-fixes. No L7 number is credible
  before this.
- **L7 bank (~120–150 questions, IN-REPO** at `tests/fixtures/l7_bank/` — `paper/` is untracked
  and machine-local): **seeded from `tasks/smart_building_questions.csv`** (100 hand-authored
  stakeholder questions across 22 categories, 2026-08; copy into `tests/fixtures/` since
  `tasks/` is untracked, then tag each row with expected behavior: `answer` / `clarify` /
  `decline+hint`, filling its empty `Latent_Architectural_Complexity` /
  `Required_Data_Sources` / `Answer_Type` columns) plus generated per-building template
  instantiations × live graph entities (no shared literals). Strata: single-constraint
  superlative ("zone with minimum occupancy") · multi-constraint ranking ·
  forecast-conditioned ("tomorrow") · spatial-anchored ("near water") · ambiguous
  (clarification expected, annotated) · unsatisfiable / phantom-referent (honest decline
  expected — fabrication bait). Wired via a `--strata-source` flag on `corpus_replay.py`
  (replacing the hardcoded `sample//6`), reusing its checkpoint/flush/auth chassis. TODO-054's
  "quiet spot to work?" becomes a canonical case.
- **Deterministic ground-truth grading:** the grader computes true answers **independently**
  from the narrow tables (its own SQL, not the system's). Metrics: top-1/top-3 accuracy, Kendall
  tau vs true ranking, constraint-satisfaction correctness, coverage-statement accuracy,
  clarify precision/recall (asked when annotated-ambiguous; targeted the right slot),
  honest-decline rate on unsatisfiable items, FABRICATED (prose number absent from dossier or
  inconsistent with DB). Circularity acknowledged and bounded: ground truth and system read the
  same synthetic DB, so the benchmark validates the **deliberation pipeline**, not sensing
  validity — plus a **real-data slice** (bldg1 floor-5 IAQ, genuinely instrumented) as contrast.
- **Ablations** (each isolates a contribution): (a) admission gate OFF → error prevention;
  (b) **LLM-ranked baseline** (LLM ranks from raw rows) → deterministic-scorer effect on accuracy
  + fabrication — the headline chart; (c) clarify OFF / always-clarify → policy value;
  (d) saturation 0/50/100% → answerability delta with epistemic labeling intact; (e) provider
  local↔OpenAI → **plan-hash equality = determinism proof** (only compiler + verbalizer may
  differ; scores must be identical); (f) **agent-loop baseline** — a ReAct-style free agent
  (same local model, same SPARQL/SQL/forecast/spatial tools, unconstrained tool choice) runs
  the same L7 bank; measure top-1 accuracy, fabrication rate on the honesty traps, p50/p95
  latency, LLM round-trips per question, and run-to-run variance (3 seeds) vs ARBITER. This is
  the pre-emptive "why not just an LLM agent / Claude-Code-with-a-local-model?" rebuttal with
  numbers instead of argument — expected outcome: slower, non-deterministic, fabricates under
  pressure; if it *doesn't* lose, that is a finding worth reporting too.
- **Portability:** identical harness + regenerated fixtures on bldg1/2/3 (swap-by-rename, zero
  code deltas), plus a source-scan test over `orchestrator/services/deliberation/**` mirroring
  `test_routing_contract.py`'s building-agnosticism scan.
- **Honesty:** honesty_sweep extended with ~20 deliberative traps; target 0 SUSPECT.
- **Context:** run BuildingGPT2/JARVIS question classes through OntoSage for the related-work
  chapter. Report p50/p95 latency per candidate-set size.

---

## 8. Landmines found during grounding (fix or they sink the thesis)

1. **RESOLVED AS BY-DESIGN (2026-08-13, user-confirmed):** the publisher's wide-table writes
   into bldg1's `sensor_data` are an **intentional dev-mode top-up** — the real snapshot
   (2025-01-01→2025-03-09, 576,557 rows) was manually loaded because the physical sensors
   feed a separate real DB this dev machine doesn't receive; generated "latest" rows keep
   real-time questions testable. `PUBLISH_WIDE` gate added (now `true`; becomes the
   end-of-development off-switch, after which the user repoints `database_registry.yaml` at
   the real/cloud DB). Thesis framing: bldg1 wide = "real historical + declared dev-mode live
   extension" — declared in the registry `note:`, CLAUDE.md, and BUG-144. No purge.
2. **Provenance mislabeling fallback:** `provenance.build_tags` (provenance.py:73) chips any
   unregistered table as REAL "Live Sensor Data". One missed `datasources.yaml` registration
   and a synthetic reading demos as real. Change fallback to a distinct "unknown source" tag.
3. **Clarification round-trip is half-broken today:** `extract_clarification_answer` is called
   (`_orchestrator.py:659`) but **does not exist** on DisambiguationService; the AttributeError
   is swallowed at debug level; numbered-choice replies are unreachable. The clarify
   contribution requires implementing the binder + structured API fields + mid-plan resume —
   scope as real work.
4. **Manifest↔ontology bridge broken:** 0/101 spaces on bldg1 floor 5 carry `ontology_iri` /
   `sensor_uuids`. Fix via the canonical `ontosage:zoneId` triple (one new generated triple
   beats three fragile label-match patches).
5. **Data-fetch starvation:** `sql_agent` caps at 30 UUIDs + global `LIMIT 1000` → ~33
   rows/sensor across 30 zones, **below ARIMA's 30-point gate**. Per-UUID partitioned fetch
   (narrow adapter's ROW_NUMBER already supports it) is a hard prerequisite for any fan-out.
6. **Fan-out latency:** auto_arima ≈ 5 s/series × 100 candidates = minutes. Hard-filter and
   spatially prune BEFORE forecasting; linear/ETS default for ranking, ARIMA only for top-K
   presented; forecast cache keyed (uuid, horizon, data-watermark).
7. **Stale facts to correct when touching docs/tests:** routing contract is 17+1+1 rules (not
   13+1); `PlannerAgent.is_complex_query` is dead; GoalPlanner is unwired dead code (its
   three-tier honest answer format is worth harvesting; the rest is superseded by ARBITER).
8. **Scoring-config portability wart:** `busyness_threshold` in shared `config/recipes.yaml`
   embeds bldg1 floor capacities — move capacities to per-building TTL/overlay (CAVEAT-094
   lesson); extend the source-scan test to new modules.

---

## 9. Phased roadmap (16 weeks, acceptance gates)

| Phase | Weeks | Work | Gate (must pass to proceed) |
|---|---|---|---|
| **P0 — Truth & metrics** | 1–2 | Fix NOTE-101 (publisher/wide-table) + provenance fallback; split replay metric + re-run 240q (bldg1+bldg2); correct stale counts; baseline honesty sweep | New split-metric baseline published in tracker; provenance chips correct for all current tables |
| **P1 — SATURATE bldg2** | 2–5 | Auditor; provisioner (TTL + zoneId + isSimulated + named graphs); runtime narrow DDL + registry activation; correlated publisher + 4–6 wk backfill; amenity ABox; datasources.yaml toggles | bldg2 gap matrix ≈ 0 for core modalities; honest-decline rate on modality questions drops to ~0 with "· simulated" chips rendering; `pytest -m unit` green in parked state |
| **P2 — ARBITER core** | 5–10 | CQ-IR compiler; capability schema + admission; candidate enumerator + coverage ledger; per-UUID fetch fix; fan-out executor + forecast top-K + cache; deterministic scorer; dossier + numeric guard + API field + frontend panel; clarify policy + binder + structured payload + resume; intent wiring + contract rule + GATED_INTENTS | Flagship query end-to-end on bldg2 with dossier; determinism check (plan-hash equal under provider swap); honesty traps HONEST |
| **P3 — L7 benchmark** | 9–12 (overlaps) | L7 bank generator + fixtures; DeliberativeGrader (independent SQL ground truth); clarify confusion matrix; ablation harness; real-data slice on bldg1 floor 5 | L7 numbers on bldg2 with split metrics; ablation (b) shows scorer > LLM-ranked baseline |
| **P4 — Portability + unification** | 12–14 | SATURATE bldg3 then bldg1; full battery on all 3; source-scan tests; **reflex-plan unification** (route_decision → plan-trace wrapper — "brain routes everything") | Zero code deltas across buildings; every answer carries a plan trace; 523+ tests green |
| **P5 — Thesis packaging** | 14–16 | BuildingGPT2/JARVIS comparison runs; delta-vs-WWW-paper table; demo hardening + rehearsal; fabrication before/after chart | 10-min demo runs cold; all claims have a number |

Scope discipline: **full saturation of all three buildings — including bldg1's 234 rooms and
door/window contacts — is core scope** (decision 2026-08-13: data coverage is never the
descope lever; if the schedule slips, extend P4 or trim P5 extras — competitor comparison
runs, figure polish — instead). New modalities demanded by QA get new narrow tables + `input/`
TTL through the existing pipeline, not code. The one-question clarify limit is a design
constraint (measured, discussed as future work); no new storage backends (TODO-143's
TimescaleDB/Cassandra stay out of scope unless time remains).

---

## 10. The 10-minute demo (supervisor/examiner)

Pre-demo: bldg2 active and warm (cold GraphDB warm-up eats minutes — BUG-100), saturation
toggles ON, `resp_cache` flushed on `redis-memory-store`, bldg3 results pre-captured, provider
flip rehearsed.

1. **(0–1)** Frame: "One building, its own data, any stakeholder. The LLM proposes; the symbolic
   layer disposes. Watch the proof, not the prose."
2. **(1–3)** Flagship, visitor persona: *"I'm visiting tomorrow — where can I sit that's quiet,
   with good air, near drinking water?"* → Assumptions block (WHO/ASHRAE-cited defaults) →
   ranked top-3 → open the dossier: CQ-IR, coverage ledger ("41 of 52 rooms instrumented for
   noise; 11 excluded, listed"), evidence table with sensor UUIDs and "· simulated" chips,
   forecast backtests. Point at one prose number, find its dossier row.
3. **(3–5)** Clarification: *"quietest spot near the lab?"* (two labs) → exactly ONE structured
   question with option buttons → reply → plan **resumes**, answers. Contrast: *"quiet spot on
   floor 2?"* → no outcome-changing ambiguity → proceeds, assumptions declared.
4. **(5–6)** Honesty: *"rank rooms by radiation levels"* → honest decline + enablement hint,
   zero numbers. Then toggle the saturation named graph OFF, re-ask the flagship → honest
   coverage collapse ("3 of 52 rooms have noise sensors — here's how to add them"): answers are
   data-bound, not memorized.
5. **(6–7)** Determinism: re-run flagship with `MODEL_PROVIDER` flipped local→openai → same plan
   hash, identical evidence table. "The LLM chooses words, never numbers."
6. **(7–8)** Proof is re-executable: run the L7 grader live on the answer just given → it
   replays the dossier SQL, recomputes the ranking, prints MATCH. Show the ablation chart
   (LLM-ranked baseline fabricates; ARBITER can't).
7. **(8–10)** Portability (pre-captured bldg3 run + zero-literal scan green) → close on the
   epistemic slide: real vs simulated grounding rates reported separately; the coverage
   auditor's gap matrix as the onboarding artifact ("this is what your building can't answer
   yet, and exactly what to install").

---

## 11. Tracker items this plan absorbs

NOTE-142 (split metric — P0) · NOTE-101 discrepancy (P0, new row needed) · TODO-054 (canonical
L7 case) · KNOWN-008 (clarify slot-filling mechanism) · CAVEAT-094 (source-scan test extended to
new modules; recipes literal moved) · TODO-081 (don't build on dead semantic-router infra;
excise opportunistically) · TODO-143/OPTIONAL-074 (out of scope unless time remains — noted).

**Execution tracker:** [`tasks/V4_TRACKER.csv`](./V4_TRACKER.csv) — 36 tasks (V4-T01…T36)
across the six phases, same schema as `implementation_tracker.csv` (V3 precedent), each with
objective, key steps, files, acceptance criteria, and a verify command. **Session protocol:**
read the tracker, take the first `todo` row whose dependencies are done, work it, flip
`status` + fill `notes` with evidence, keep `FIX_TRACKER.csv` current as bugs close
(BUG-144…NOTE-150 are the audit-found rows this plan absorbs). Phase gates: V4-T14 (P1),
V4-T26 (P2) — do not proceed past a red gate. No commits without explicit approval; all
buildings parked before any commit (Workflow rule 8).

---

## STATUS: DELIVERED (2026-08-14)

All 36 tracker tasks done. Evidence: tasks/V4_TRACKER.csv (per-task notes),
scripts/outputs/V4_RESULTS.md (3-building certification), tasks/V4_T34_COMPARISON.md
(delta vs paper), tasks/V4_DEMO_SCRIPT.md + scripts/demo_rehearsal.py (2x ALL BEATS PASS),
tasks/figures/ (architecture, coverage, ablation). FABRICATED = 0 on every benchmark run,
every building. No commits made - everything local pending review.
