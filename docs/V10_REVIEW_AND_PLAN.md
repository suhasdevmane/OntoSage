# V10 — Codebase review: building-agnostic QA, what is wrong, why, and how to fix it

**Written:** 2026-09-06 · **Branch:** `development` (V9 work committed locally, nothing pushed)
**Active building during review:** bldg1 · **Model:** local `gpt-oss:20b`
**Method:** five parallel read-only reviews (arbiter, orchestrator/routing, building-agnostic
literals, ontology layer, onboarding + measurement), a 12-question live probe with the response
cache flushed, GraphDB/MySQL spot checks, and the offline unit suite.

---

## 0. Verdict in five sentences

The **intent** — connect one building's TTL + documents, ask anything, get grounded
building-specific answers — is right, and the parts of the system built to that contract
(record registers lifted from documents, the capability graph resolver, the evidence ledger,
the honesty gates) are genuinely well designed. But the system is **not building-agnostic in
practice**: it is a bldg1 system whose second, third and fourth buildings receive the skeleton
and none of the flesh, and whose routing, prompts and lexicons carry Abacws's vocabulary in
~800 hard-coded strings that a literal-scan test cannot see. The **ARBITER** is a disciplined
symbolic ranking lane on 1 of 37 intents, never executed end-to-end by any test, and not the
brain the V4 plan describes. The **orchestrator** is a 50-rule, 5-stage deterministic expert
system that overrides the LLM classifier and frequently never calls it; its single most
dangerous construct is a pre-LLM capability short-circuit with 16 exception clauses. On the
development building itself, **5 of 12 basic questions came back wrong or as non-answers** with
every V9 fix in place — so the first job is not more registers, it is making the six systemic
causes below impossible by construction.

The unit suite is green: **5,004 passed, 44 skipped** (7m51s, parked-state safe).

---

## 1. Live evidence — bldg1, 2026-09-06, cache flushed

| # | Question | Intent | Result | Root cause (verified) |
|---|---|---|---|---|
| 1 | How many temperature sensors are in the building? | metadata | OK | — |
| 2 | How many sensors are there in total? | metadata | **Inconsistent** | "2,720 declared", "2,763 reported in 24 h" (more reporting than exist), "Floors: 8" — GraphDB types `Rooftop` and `Parking_Level_Ground` as `brick:Floor`. Modelling smell surfaced as fact. |
| 3 | CO₂ in room 5.01 right now? | sensor_data | OK, provenance broken | Sources rendered as `Unknown Source`; "served zone link not validated" caveat shown. |
| 4 | Temperature in Room 9.99? | sensor_data | Honest but slow (46 s) | Referent-existence check timed out on a non-existent room; the decline blames time, not absence. Regression probe fails the same case. |
| 5 | Which rooms are on floor 2? | **capability** | **WRONG** | Answered 6 rooms from *Cleaning Task Register / Public Event Register / Timetabled Sessions*. GraphDB holds **47** rooms on Floor 2. The pre-LLM capability short-circuit (`dialogue_agent.py:832-960`) ate a structural question. |
| 6 | Is the lift working? | asset_state | **WRONG** | "No lifts recorded." `bldg:status_lift_0 a ontosage:AssetStatus; statusOf bldg:Lift_Main` IS in the graph, but **`bldg:Lift_Main` has no triples** — the generator wrote a status for an asset it never declared; `_status_query` requires `?asset a ontosage:Lift` (`asset_state_service.py:228-253`). Dangling reference, not caught by validation. Lesson #87 recorded this exact symptom as fixed. |
| 7 | Nearest accessible toilet to room 3.10? | planner | **Non-answer** | Returned the Floor 3 plan for 3.10. Wayfinding never ran. |
| 8 | Which permits are open? | metadata | OK | Register lane, 3 of 15, correct. |
| 9 | Compare avg CO₂ floor 1 vs floor 3, last week | compare | **WRONG + recommendation** | 155 ppm vs 110 ppm, floor 3 "75–78 ppm" — physically impossible (outdoor air is ~420). `co2_data` narrow table has min 400 / avg 853. The wide-table top-up publisher falls to a type-based random range for any sensor name not matching `_WIDE_RANGES` substrings (`mysql_dummy_publisher.py:315-345`, 37% of names measured 2026-09-03). No plausibility band exists outside the deliberation scorer. Then it recommended an HVAC upgrade. 118 s. |
| 10 | What is this building and who runs it? | **privacy_refusal** | **WRONG refusal** | `INDIVIDUAL_PRESENCE_RE` clause `\b(?:and|but)\s+who\b` (`privacy/inference_classes.py:41`) fires on "…and who runs it". The governance register that answers this (commit `cd324de`) never ran. |
| 11 | Which rooms are stuffy right now? | sensor_data | **Broken** | HBCO maps "stuffy" → CO₂, but the generated SPARQL returned sensor counts per space and the LLM narrated *"the data you've provided only tells us how many sensors…if you can run a query…"* — developer-facing chatter reached the user; no guard caught a meta-answer. |
| 12 | Show me floor 3 | floor_plan | OK | — |

**Read this table before reading any coverage percentage.** Four of the five failures are
not data gaps; they are routing and guard defects that a register cannot fix.

---

## 2. What is actually built (maturity, honestly)

### 2.1 ARBITER (`services/deliberation/`, 17 modules, ~4.6k LOC; `services/evidence/`, 25 modules, ~6.8k LOC)

- **Real and disciplined:** CQ-IR compile (one LLM call, temp 0, JSON-validated field by field),
  admission gate over a live per-request SPARQL schema, clarify policy, deterministic scorer with
  cited bands, coverage ledger, dossier, numeric guard. Zero building literals in the package.
- **Not a brain:** it is one graph node (`_deliberate_node`, `_orchestrator.py:5793-6053`)
  reached by a regex (`DELIBERATE_RE`, `routing_contract.py:697-720`) plus two intent sets.
  **36 of 37 intents never touch it.** `build_plan_trace` (`_orchestrator.py:356-401`) emits a
  constant six-step list regardless of what ran — V4-T33 "brain routes everything" is cosmetic.
- **Never executed end-to-end by a test.** `grep _deliberate_node tests/` returns nothing;
  every deliberation test injects fakes. V4-T26 (the flagship e2e gate) is marked done.
- **Determinism claim rests on a Redis cache.** `compiler.py:145-148`: "cache OFF … the honest
  wobble, 3/8." With the cache on (default), `plan_fingerprint` measures the cache.
- **Specific defects:** stability sentence computed by a different scorer than the ranking
  (`scorer.py:353-390` vs `287-303`); `simulated` never mentioned in prose, only a collapsed
  table (`dossier.py:324-331`); a failed SQL table is skipped with a log line and no ledger entry
  (`fetch.py:71-73`); `deliberate_result` absent from `_LANE_KEYS_FOR_DIAGNOSIS`
  (`_orchestrator.py:428-439`) so its failures cannot be named; gating env vars
  `DELIBERATE_CLARIFY_OFF` / `CQIR_COMPILE_CACHE` exist in no `.env*` and no `Settings`.
- `ONTOSAGE.md` (126 KB) contains **zero** occurrences of "ARBITER" or "dossier".

### 2.2 ORCHESTRATOR (`workflow/_orchestrator.py` 8,064 lines; `routing_contract.py` 2,011)

- **Decision flow for one question:** (A) two pre-LLM short-circuits in `detect_intent`
  (record-class probe → `metadata`; capability doc-score ≥ 0.50 → `capability`, guarded by 16
  `and not` predicates) → (B) LLM classification → (C) 36 ordered contract rules, **last match
  wins** (`routing_contract.py:1857-1876`; the docstring says the opposite) → (D) 1 post rule →
  (E) 3 concept rules → (F) inline overrides in `_dialogue_node` → (G) 7 more overrides in
  `_route_from_dialogue_impl` before the registry. **≈50 rule objects over ≈800 literal
  strings/patterns.** The LLM's label is a filter input, not the decision.
- **Methods:** `_dialogue_node` 695 lines, `_response_node` 663, `_route_from_dialogue_impl`
  634, `_sql_node` 446, `_sparql_node` 428. Node list maintained in three places
  (`_route_from_dialogue_impl:5327-5357`, `_graph.py:209,243`).
- **Response dispatch fragility:** `dialogue_response` is checked *second* (`:4189`), above
  every computed lane — any node that writes it pre-empts a richer result in the same turn.
  `analytics_result`/`forecast_result` are deliberately carried across turns (`:457`).
- **Referent gate** (`apply_referent_gate`, `:486`) runs in **2 of ~18 lanes** (sparql, events)
  and fails open on exception. Register, asset_state, observability, readiness, diagnosis,
  deliberate, capability, spatial, floor_plan, analytics all bypass it.
- **Building leakage is vocabulary, not names** — invisible to
  `test_contract_is_building_agnostic` (greps six strings): `EVENTS_RE` needs
  `lecture|teaching session|timetabled`; `_READINESS_RE` needs `class|lecture|seminar`;
  `REGISTER_RE` needs `legionella|LOLER|PAT test|F-gas`; `_SPACE_NOUNS` has `lab`;
  `_SPATIAL_BYPASS_PHRASES` is UK English (`lift`, `toilet` — "elevator"/"restroom" get no
  wayfinding); `_ROOM_ID_RE`/`_ZONE_ID_RE` assume `\d+\.\d+` (`semantic_router.py:45-60`);
  `_DATA_ANALYTIC_WORDS` (~60 measurands) and `_DATA_KW` (17) are bldg1's modality set;
  `_MODALITY_STOPWORDS` (`routing_contract.py:1892-1908`) hand-tuned to bldg1 names.
  `metered_vocabulary()` and `_plant_measurand_re()` are config-derived — the right pattern,
  used twice.
- **The overlay tiers collapse under the flat layout.** `intents/registry.py:349-369` and
  `persona_loader.py:54-55` implement three tiers (`_defaults` → `input/` → `input/<id>/`), but
  swap-by-rename means tier 3 never exists and tier 2 *is* the active building. So
  `input/intents.yaml` holding bldg1's `lab_booking` intent is correct placement, not a leak
  (an earlier draft of this review said otherwise); the per-`building_id` cache in
  `get_intent_registry` offers the interface of multi-tenancy over a filesystem that cannot
  deliver it. Collapse the dead tier and document that `input/intents.yaml` is the building's own.
- **Un-namespaced caches** (`cache:concept:hbco_all`, 24 h, `concept_resolver.py:37-38`;
  `record_registry._CACHE["_active"]`; `_active_namespace()` / `run_sparql_select` with no
  `building_id`) are **consistent with the v1 one-building-per-process contract**. They are not
  bugs today; they are the concrete blockers for the v2 simultaneous-buildings path that
  `swap_building.py:32-38` anticipates, and a stale-after-swap risk if Redis is not flushed.

### 2.3 ONTOLOGY layer (`ontology/ontosage_schema.ttl` 2,915 lines; 97 classes, 292 properties, 572 layTerms on 40 classes)

- **Record lane is the best-designed thing in the repo:** class list discovered by SPARQL,
  predicates and enumerations read live from instances and `rdfs:comment`, mapping ships with
  the ontology (`record_documents/*.yaml`, 34 of 39 record classes). `held_record_class`
  scoring is real (length-weighted, compound-aware).
- **But 34 of 39 record classes have zero TTL instances in every building** — they exist only
  after lifting `input/documents/*.md`. bldg1: 37 register documents. bldg2: 10. **bldg3: 1.
  bldg4: 1.** The "37 catalogues" coverage is one building's hand-authored document set.
- `AlarmEvent`/`AnomalyEvent`/`AccessEvent`: declared, lay-termed, **no mapping, no instances,
  no reader** — unfillable. `SustainabilityTarget` has a mapping but sits outside
  `_DISCOVER_QUERY`'s roots (`record_registry.py:72-80`) — undiscoverable even when lifted.
- **SPARQL prompt is bldg1 few-shot:** `sparql_agent.py:1371,1390,1426,1458,1513,3458-3466`
  and 4/17 entries of `data/few_shot_library.json` teach `Room_5.01`, `CO2_Level_Sensor_5.08`,
  `CONTAINS "5.08"`. `prompt_builder.py:5` claims to have eliminated these.
- **`ontosage:` is missing from `sparql_validator._PREFIX_INJECT`** (`:71-77`) — the project's
  own vocabulary fails pre-flight unless the LLM emits the PREFIX itself (lesson #89's residue).
- **Validation cannot see an empty ontology layer.** Swap/boot checks: parses, `bldg:` prefix
  matches `ontology_namespace`, optional SHACL WARN. **A building with valid Brick and zero
  `ontosage:` triples boots green and declines every capability, record and knowledge
  question.** bldg4 is nearly that building. Nothing checks dangling object references
  (`statusOf` → untyped IRI, the lift defect).
- `swap_building.py:346-372` archives a hard-coded file list; any other TTL the old building
  dropped in `input/` is loaded for the new one.
- Hygiene: `owl:versionInfo "2.1.0"` unchanged across seven later modules; module letter J used
  twice, no L; `layTerms` comma-packed in instances but one-per-triple in the TBox (resolver
  handles only the instance form); `_SHARED_SCHEMA_TOKENS` matches `"rec"` as a substring.
- **278 of 429 declared `ontosage:`/`hbco:` terms have no literal reader** in `orchestrator/`.
  ~55 are legitimately declarative, ~180 are reached generically (needs RDFS inference ON),
  and the remainder are answerable data with no reader: `AccessibilityFeature` properties
  (8 instances render as bare labels), `ServedZone` + 5 properties, Module K sensor/equipment
  classes with instances (`Soil_Moisture_Sensor`, `Heat_Pump`, `Emergency_Generator`…).
  `scripts/audit_unread_stores.py` covers SQL only; the RDF half of lesson #90 was never scripted.

### 2.4 Building-agnostic code audit (orchestrator, shared, rag-service, frontend)

141 raw hits for `bldg[1-4]|abacws|cardiff`; **15 real defects (A)**, 12 harmless (B), ~114
comments (C). The (A) list:

| file:line | defect |
|---|---|
| `floor_plan_service.py:237-239` | **Invents** rooms `f"{floor}.{n:02d}"` for n=1..14 when PDF text is empty — fabricates referents in Abacws's grammar. Contract 3 *and* 4. |
| `anomaly/diagnosis.py:394` | literal `stored_at: "plant_data"` — only bldg1's registry defines it; plant diagnosis dark elsewhere. |
| `building_context.py:124-125` | reads `building_prefix`/`building_timezone`; every building.yaml writes `ontology_prefix`/`timezone`; admin_config writes the latter. Silently falls to env defaults. |
| `sparql_agent.py:1390,1514` | prompt exemplars `Room_5.01`, `CONTAINS "5.08"`. |
| `self_correction_engine.py:253` | repair query defaults namespace to `http://example.com/building#` → zero rows, no error. |
| `adapters/registry.py:448-464` | no-YAML path hardcodes `database1`/`database2`. |
| `shared/config.py:452,457` | `ABOX_FILE` default `trial/dataset/bldg1_protege.ttl`, alias `BLDG1_ABOX_FILE`. |
| `frontend/.../TopNav.js:21`, `Home.js:33,57` | "Abacws SmartBot", "3D-Abacws Service". |
| `FloorPlanViewer.js:122` | `manifest?.building_id \|\| "abacws"`. |
| `admin/OntologyTab.js:4-5` | TTL editor placeholder pre-seeds bldg1's namespace — the footgun `input/README.md` warns about, wired into the onboarding GUI. |
| `rag-service/graphdbRAG/Get llm response.py:46,61,204` | `PREFIX bldg: <…abacws#>` three times. |
| `docker-compose.yml:357` | `./data/bldg1:/staging:ro` — survives every swap. |
| `scripts/check_building_literals.py` | the guard scans `orchestrator/`+`shared/` only, has no room-id rule despite its docstring, misses `cardiff`/`example.com`/table names — reports "clean". |

**Path resolution:** 16 call sites use `shared/building_paths`; **60+ hardcode
`Path("/app/input")`/`Path("input")`**; six services re-implement the nested/flat search with
only the nested form (`rules.yaml`, `channels.yaml`, `recipes.yaml`, `goals.yaml`,
`actuation`, `feeds`) — same logic written seven ways.

**Input divergence** (what bldg1 has that the others do not):

| lane / data | bldg1 | bldg2 | bldg3 | bldg4 |
|---|---|---|---|---|
| register documents lifted | 37 | 10 | 1 | 1 |
| `KnowledgeTopic` / `Amenity` | 48 / 47 | 14 / 23 | 12 / 27 | 5 / 2 |
| `ConfigurationPeriod` | 2,175 | 0 | 0 | 0 |
| `AssetStatus` | 128 | 6 | 6 | 2 |
| AV/Alarm/Network/ServiceSchedule/Accessibility/Closure/Parking… | ✅ | 0 | 0 | 0 |
| saturation modalities | 10 | 12 | 9 | **0** |
| floor plans | 6 real DWG+PDF | 3 stub | 4 stub | **none** |
| feeds / rules / channels / intents / RBAC datasource yaml / timetable / `floors/` | ✅ | ❌ | ❌ | ❌ |
| `*_policies.ttl` (PROTECT) / `*_compliance.ttl` | ✅ / 82 | ✅ / 82 | ✅ / 82 | **❌ / 0** |
| real telemetry | 1 source (snapshot + dev top-up) | 0 | 0 | 0 |
| question bank / regression baseline | 4,060 / ✅ | 0 / ✅ | 0 / ✅ | 0 / ❌ |

`input/_templates/` ships **5** files. **24 of bldg1's 39 TTLs have no template and no
generator.** A new building gets identity + storage routing and nothing else.

### 2.5 Deployment and measurement

- **Fresh machine blockers:** MySQL is a host prerequisite listed nowhere (`docker-compose.yml:554-574`
  disabled; `data/mysql-init/*.sql` mounted in no compose file; `docs/DEPLOYMENT.md` lists no DB);
  `.env.example` lacks **31** settings the live `.env` uses and contradicts compose on 4;
  fixed `container_name`s and host ports → one building per host; `PUBLISH_WIDE=true` ships
  (`:599`); the OnboardingTab React screen is **not in the deployed stack** (frontend service
  disabled `:937-953`; `config-panel/html/app.js` never calls `/admin/onboarding/status`).
  TODO-072 is `FIXED_UNVERIFIED`; the cold run defined in `COLD_START_VERIFICATION.md` was
  never executed; bldg4 has no tracked `.env4.example` or compose file.
- `scripts/onboard_building.py` sets **none** of the 7 per-building env settings and scaffolds a
  nested layout the swap procedure does not consume; `/new-building` command calls it with a
  flag it rejects (`--building-id` vs `--id`) and queries repository `ontosage` (real: `bldg`).
- **Grader:** `_heuristic_grade` never reads the question (`corpus_replay.py:384-385`);
  `has_counted_records` is `\b\d+\s+[a-z]{3,}`; judge exceptions silently downgrade mid-run;
  `--building` defaults to `"bldg1"`; 572 of 2,960 headline rows carry `provider=model=unrecorded`;
  V9 Phase D2 (re-capture under the corrected grader) not done; `V9_PLAN.md`/`V8_REPORT.md` say
  CAVEAT-418 open, `FIX_TRACKER.csv` says FIXED same day.
- **Tests:** 4,180 functions; 156 files (40.6%) mention `abacws`/`bldg1`; routing tests use
  `room 5.01` shapes throughout — they prove routing on bldg1 grammar and nothing about `RM-204`.
- `CLAUDE.md`'s orientation block says branch `main`, V6 state, 2,488 tests. Reality: branch
  `development`, V9, 5,004 tests. Three plans stale.

---

## 3. Why — six systemic causes

1. **Building-agnostic was asserted by a grep, so it was achieved as a grep.** The guard and the
   contract test look for six literal strings. The real coupling is *vocabulary* (UK-HE facilities
   lexicon, `N.NN` room grammar, bldg1's modality names, bldg1 few-shot in prompts). Nothing
   derived those from the active graph, so every rule that was tuned against bldg1's corpus
   encoded bldg1.
2. **Routing was debugged into existence one incident at a time.** Every rule has a measured
   failure behind it (the comments are exemplary), but the aggregate is five override stages,
   last-match-wins, and a pre-LLM veto that needs an exception per lane. New lanes are discovered
   to be shadowed only by a live wrong answer (floor-2 rooms → cleaning register is today's).
3. **bldg1 was hand-built; the pipeline that would rebuild it does not exist.** Generators exist
   for 15 of 39 TTLs and templates for 5. Registers are hand-authored Markdown. So "drop TTL in"
   produces a building that declines what bldg1 answers — and no validator says why.
4. **Honesty gates are lane-local, not universal.** Referent gate in 2 of 18 lanes; plausibility
   bands only in the deliberation scorer; privacy regex with a bare `and who` clause; no
   meta-answer guard on LLM narration. Each lane re-implements or skips the guard.
5. **Data integrity is not validated at the reference level.** `statusOf` → undeclared IRI;
   `Rooftop a brick:Floor`; wide-table top-up falling to random type ranges for unmatched names.
   The two-half rule is checked for sensors; nothing equivalent exists for records, statuses or
   value plausibility.
6. **Measurement is one building, one model, and half-attributed**, and the plan documents
   disagree with the tracker. Coverage numbers cannot be compared across buildings because no
   other building has a bank, and cannot be trusted on bldg1 until D1/D2 land.

---

## 4. Improvement plan V10 — make agnosticism structural, then measure it on bldg3

Ordering principle: **nothing in Phase C (more data for bldg1) until Phase A and B make a
second building behave like the first for the data it has.** The acceptance test for every
item is stated against **bldg3 or bldg4**, never bldg1.

### Phase A — stop the live wrong answers (1–2 days)

| id | change | files | acceptance |
|---|---|---|---|
| A1 | Referent gate becomes universal: run `apply_referent_gate` in `_safe_node` (or top of `_response_node`) for every lane that names a space/floor/zone; fail **closed** on timeout with "could not verify"; cache the space IRI set per building for the request. | `_orchestrator.py:486,748` | "Room 9.99" declines in < 5 s on all lanes; "vibration on floor 9" declines in register/asset/spatial lanes. |
| A2 | Invert the capability short-circuit: probe documents **after** classification + contract, as a target with a threshold, never as a pre-LLM gate. Delete the 16 `and not` clauses. | `dialogue_agent.py:832-960` | "Which rooms are on floor 2?" returns 47 from the graph; the register/observability/readiness bypass regexes are no longer imported into `dialogue_agent`. |
| A3 | Privacy regex: drop `\b(?:and|but)\s+who\b`; require a presence predicate. Add "who runs/manages/owns/is responsible" to a governance allow-list. | `privacy/inference_classes.py:41` | "What is this building and who runs it?" answers from the governance register. |
| A4 | Plausibility bands per measurand, applied in **every** numeric lane (sql, compare, analytics, deliberate): move `DEFAULT_ANCHORS` to `ontology/measurand_kinds.ttl` as `ontosage:physicalMin/Max`; a value outside the band is reported as implausible, never averaged, never turned into a recommendation. | `scorer.py:50-61`, `measurand_kinds.ttl`, compare/sql lanes | The floor 1 vs 3 CO₂ question either reports valid figures or says which sensors returned implausible values. |
| A5 | Meta-answer guard: reject LLM narration matching "the data you've provided / run a query / if you can" and re-route to `_unanswered_response`. | `_response_node`, `grounding_guard.py` | "Stuffy rooms" never emits developer chatter. |
| A6 | Reference-integrity validator: every `ontosage:statusOf`, `servesSpace`, `locatedIn`, `hasPart` object must be a typed subject in the same namespace; report as HARD_FAIL on swap and as WARN in the admin Ontology tab. Fix `bldg1_synthetic_status.ttl` (declare `Lift_Main a ontosage:Lift`) and the generator. | `input_validators.py`, `provision_synthetic_sources.py` | "Is the lift working?" answers "operational, simulated, observed 2026-08-21". |
| A7 | `Rooftop`/`Parking_Level_Ground` retyped (`brick:Space`/`brick:Outside`), or the floor count excludes non-`Floor_N` subclasses. | `bldg1_*.ttl` | "Floors: 6". |
| A8 | Wide-table top-up: unmatched sensor names **skip** rather than fall to type ranges; list the unmatched names at publisher start. | `mysql_dummy_publisher.py:395-410` | Zero wide columns with 7-day CO₂/temp/RH averages outside physical bands. |

### Phase B — derive vocabulary and identity from the active building (1 week)

| id | change | acceptance (bldg3 active) |
|---|---|---|
| B1 | **Vocabulary from the graph, not from code.** Build `BuildingLexicon` once per building (cached under `building_id`): measurand words from the modality config + HBCO layTerms; room-ID regex learned from the actual `brick:Room` labels/IRIs (`\d+\.\d+`, `RM\d+`, `L\d-\w+`…); space nouns from Brick subclasses present; asset kinds from `ontosage:` classes instantiated. Replace `_DATA_ANALYTIC_WORDS`, `_DATA_KW`, `_ROOM_ID_RE`, `_ZONE_ID_RE`, `_SPACE_NOUNS`, `_MODALITY_STOPWORDS` with lexicon lookups. Keep `EVENTS_RE`/`_READINESS_RE`/`REGISTER_RE` but source their nouns from the layTerms of classes that *have instances*. | A synthetic bldg with `RM-204` rooms and an `NO2` modality routes "NO2 in RM-204" to sensor_data. `test_contract_is_building_agnostic` replaced by a **two-fixture test** that boots the lexicon on two different room grammars. |
| B2 | Flush-on-swap made structural: key `cache:concept:*`, `record_registry._CACHE` and the response cache by `building_id` so a swap cannot serve the previous building's concepts or record classes. (Full `building_id` plumbing through `_active_namespace()`/`run_sparql_select` is v2 work; not required for v1.) | Swapping bldg1 → bldg3 without a manual Redis flush produces no bldg1 concept or record class. |
| B3 | SPARQL prompt: delete all `5.01`/`5.08` exemplars; generate the few-shot **from the live graph** (one real room IRI, one real sensor IRI, one real record class) at boot. Add `ontosage:` to `sparql_validator._PREFIX_INJECT`. | Prompt dump on bldg3 contains only bldg3 IRIs; a generated query using `ontosage:` passes validation. |
| B4 | One path resolver: replace the 60+ `Path("input")` literals and the 6 re-implementations with `building_paths`. Fix `building_context.py` keys (`ontology_prefix`, `timezone`). | `grep -c 'Path("input\|/app/input' orchestrator shared` == count inside `building_paths.py`. |
| B5 | Fix the 15 (A) literals from §2.4; extend `check_building_literals.py` to frontend/rag-service/compose, add room-id, `cardiff`, `example.com`, table-name rules, and a *vocabulary* rule (any regex/frozenset > 10 English nouns in `routing_contract`/`semantic_router` must cite a lexicon source). | Guard fails on the current tree, then passes. |
| B6 | Collapse the overlay tiers to what the flat layout can deliver: `input/intents.yaml` and `input/personas/` are the active building's own files; drop the dead `input/<id>/` tier from `intents/registry.py` and `persona_loader.py` and document the contract in `input/README.md`. | Registry and persona loaders have one search path; `test_intent_overlays.py` asserts the flat file wins. |
| B7 | Response dispatch: `dialogue_response` moves **below** computed lanes; `analytics_result`/`forecast_result` carry-over becomes explicit (a "that" co-reference sets a flag) instead of default. | A turn that computes a register result and a clarification shows the register result. |

### Phase C — a building gets what bldg1 has, by construction (1–2 weeks)

| id | change | acceptance |
|---|---|---|
| C1 | **Ontology-layer readiness validator.** On swap/boot and in the admin Onboarding view: for each `ontosage:` class with layTerms, instance count in this building; for each record mapping, whether a document of that `record_type` exists; for each lane, GREEN/EMPTY. Nothing is a hard fail, but the report is the answer to "why does bldg4 decline everything". | `certify_building.py --preflight-only` on bldg4 prints 34 EMPTY record classes and the missing `_policies.ttl`. |
| C2 | **Register scaffolder.** `scripts/scaffold_registers.py --building bldgN` writes one **empty, front-mattered** register per mapping (columns from the mapping, `simulated: true`, building name from `building.yaml`) plus an optional `--synthetic N` rows mode — the same generator that produced bldg1's registers, made building-agnostic. | bldg3 with `--synthetic 10` computes "which permits are open" and "which cleaning tasks are due". |
| C3 | Templates for the 24 TTLs with no path: `knowledge`, `building_facts`, `site`, `description`, `synthetic_status` (with typed assets), `synthetic_hours/schedules/accessibility/amenity_state`, `zone_room_links`, `policies`, `compliance`. Each template is the generator's output for an empty building; `onboard_building.py` writes them **flat**, sets all 7 env settings, and is what `/new-building` calls (fix flags + repository name). | `onboard_building.py --id bldg5 --namespace … ` + `swap_building.py --to bldg5` boots to `/health` 200 with every lane EMPTY-but-declared, not dark. |
| C4 | Fill the three unfillable record classes (`AlarmEvent`, `AnomalyEvent`, `AccessEvent`) with mappings or remove their layTerms; put `SustainabilityTarget` under `ontosage:Record`; script the RDF half of the reader audit (`audit_unread_terms.py`) and add readers for `AccessibilityFeature` properties and `ServedZone`. | Audit lists 0 answerable classes with no reader. |
| C5 | Deployment truth: MySQL in compose (or a documented host prerequisite + DDL step run by compose init); `.env.example` regenerated from the union of `.env*` with per-building keys marked; `PUBLISH_WIDE=false` default; parametrise `container_name`/ports by `COMPOSE_PROJECT_NAME`; remove `./data/bldg1:/staging`; ship `.env4.example` + `docker-compose.bldg4.yml`; make the OnboardingTab reachable (config-panel calls `/admin/onboarding/status`) or delete it. Then **run the cold start in `COLD_START_VERIFICATION.md` on bldg4** and close TODO-072 with evidence. | Fresh clone → `onboard` → `up -d` → 5 sensor questions answer on bldg4 with no host MySQL pre-existing. |

### Phase D — the arbiter earns its name or its size (1 week, after A–C)

| id | change | acceptance |
|---|---|---|
| D1 | One end-to-end test of `_deliberate_node` with a fake LLM and a seeded in-memory graph; `deliberate_result` added to `_LANE_KEYS_FOR_DIAGNOSIS`; failed-table ledger entry; `simulated` share in prose; `_plain_rank` uses the same anchors as the ranking. `DELIBERATE_CLARIFY_OFF`/`CQIR_COMPILE_CACHE` become `Settings`. | Test fails when any of the five is reverted. |
| D2 | Decide the brain question honestly: either (a) the CQ-IR compile + admission gate + plan trace run for **every data intent** (sensor_data, compare, trend, analytics, metadata) and `build_plan_trace` reports real steps — or (b) rename the lane `ranking` and delete the "brain routes everything" claim from V4 docs and `ONTOSAGE.md`. Recommendation: **(a) for the admission gate only** (it is cheap, deterministic, and would have caught floor-2-from-cleaning-register and the untyped lift), (b) for the rest. | Plan trace on a `compare` turn names the gate decision. |
| D3 | Delete `amenities.py`, `saturation.py`, `scenarios.py`, `synthetic_signals.py` from `deliberation/` (script-only) and `matrix.py`/`omissions.py` duplication in `evidence/`, or wire them. | No module under `orchestrator/` with zero importers. |

### Phase E — measure on a building that is not bldg1 (ongoing)

| id | change |
|---|---|
| E1 | **Portable question bank:** template the 4,060 questions over the lexicon (room ids, modalities, register names substituted from the active building) so bldg3/bldg4 can be captured with the same grader. |
| E2 | Land V9 D1 (grader reads the question; `has_counted_records` tightened) and D2 (full re-capture) — but run D2 on **bldg1 and bldg3**, report both. Reconcile `FIX_TRACKER.csv` with `V8_REPORT`/`V9_PLAN` on CAVEAT-418. Record provider/model on every row. |
| E3 | Regression probe gains a **bldg3 leg** and the 12 probe questions from §1 as a permanent smoke set, run before any coverage claim. |
| E4 | Refresh `CLAUDE.md` orientation (branch, plan, suite count) and add "ARBITER" to `ONTOSAGE.md`. Rewrite `input/README.md` to list every input the code reads (§2.4 undocumented list: `datasources.yaml`, `saturation_modalities.yaml`, `recipes.yaml`, `goals.yaml`, `role_datasource_access.yaml`, `evidence_policy.yaml`, `access_tiers.yaml`, `<id>_policies.ttl` exact-name rule, `floors/`). |

### What not to do

- Do not add registers C1–C4 from `V9_PLAN.md` before Phase A/B: today's floor-2 answer shows a
  new register can *lower* accuracy by feeding the capability short-circuit.
- Do not fix the probe failures by adding a 17th `and not` clause, a 37th contract rule, or a
  bldg1-shaped regex. Every one of those is the disease.
- Do not publish another coverage number until E2 runs on two buildings with attributed rows.
- Do not delete `bldg1`'s hand-built data; make it reproducible instead (C2/C3).

---

## 5. Sizing

| phase | effort | blocks |
|---|---|---|
| A | 1–2 days | everything — these are live wrong answers |
| B | ~1 week | C's acceptance on bldg3 |
| C | 1–2 weeks | the deployment claim |
| D | ~1 week | V4 claims in the paper |
| E | ongoing | any coverage number |

Nothing here is committed. Per project rule, no commit or push without explicit approval.
