# V5 Handoff Pack — everything a fresh session/model needs to finish V5

_Last updated 2026-08-15 (bldg2 active). Read this + `IMPROVEMENT_PLAN_V5_UNIVERSAL_COVERAGE.md`
(v3) + `V5_TRACKER.csv` before touching anything. CLAUDE.md rules apply throughout —
especially: NEVER commit/push without explicit user approval; park all buildings first._

## Current state (2026-08-15)

- **Active building: bldg2** (input/ + .env + docker-compose.yml). bldg1/bldg3 parked.
  Stack is UP. All three buildings are fully saturated from V4 (100% × 8 modalities).
- **Tracker status**: T01 done · T02 **skipped** (user decision — MVP-first; static
  classification replaced the live baseline; partial 103-question run archived at
  `scripts/outputs/replay/v5_baseline_bldg2.csv`) · T03 done · T04 done · T06 done ·
  T37 done (policies generated ALL buildings, bldg2 uploaded+SPARQL-verified; demo
  switch = rerun `generate_access_policies.py --profile demo_open --all` + restart).
  T07 done (events store live, adapter resolves bldg:events_data) - T05 done (compliance
  register: 82 checks/building uploaded, overdue SPARQL verified). T09 done (sat.scope room|floor|building shipped; pm25/submeter/waterflow/parking live on
  bldg2, ARBITER ranks on pm25 - parked buildings re-run saturate+backfill on their legs).
  T08 done (3,173 events on bldg2, live hourly tick, ghost/occupancy consistency tested;
  subject_uuid = derive_point_uuid(bid,'evt_subject',local) - T24 derives the same).
  T11 done (admin-API register round-trip proven; upload field is graph_uri, drop is
  DELETE /api/v1/admin/ontology/graphs/{id} URL-encoded). STORES PHASE COMPLETE.
  T24 done (event lane live: all 6 kinds verified on real store; see tracker notes for the
  3 shakedown fixes incl. the two-cache flush rule and the JSON-fallback parse-stage fix).
  T26 done (register lane live 5/5 on bldg2: overdue→PAT+fire door w/ roles, fire alarm
  last tested→15 Aug next 23 Aug, due-30d→4 items; events + legacy compliance untouched.
  KEY LESSON: the dialogue capability short-circuit fires BEFORE the routing contract —
  "fire alarm" lay-term matched the fire-safety KnowledgeTopic and answered dateless
  prose. Fix pattern: PUBLIC predicate `routing_contract.register_question()` shared by
  the rule AND a bypass guard next to _DELIB_RE in dialogue_agent; pinned by
  test_capability_short_circuit_honours_register_bypass. Any future lane whose vocabulary
  overlaps capability topics needs the same bypass. last_done claims only KNOWN register
  items — equipment service-history stays history_question_not_report→capability).
  T12+T13 done (PREDICT core live: plan_executor default = ModelSelector adapter
  (services/forecasting/adapter.py) — dossier forecast line now carries model + 95% CI +
  backtest MAE (live: 'ARIMA(1, 0, 0), 95% CI 400.014–450.33, backtest MAE 168.624');
  numeric_guard extended for band numbers. Two-tier: pure-python seasonal-naive
  (models/seasonal_naive_forecaster.py, 0.6ms/room) ranks ALL candidates, adapter refines
  top-5 (52-room co2 forecast: 4.2s forecast stage). Horizon authority folded:
  horizon_parser.match_horizon + compiler._fold_deterministic_horizon — trend lane and
  ARBITER agree by construction. Real-data backtest: seasonal-naive wins 25/37 series,
  sweeps pm25/humidity/light/submeter/temperature (scripts/outputs/v5_t13_backtest_bldg2.csv,
  regen: python scripts/forecast_backtest_table.py). ForecastRecord/DossierForecast gained
  ci80/ci95/backtest_mae/n_train — injected tuple forecasters still work.)
  T18+T19 done (DETECT live: services/anomaly/detectors.py 7 deterministic detectors +
  scanner.py persisting episodes to the events store with STABLE IDs — re-scan 0 inserted/
  3599 extended across processes; lifespan scheduler ANOMALY_SCAN_INTERVAL_SECS=3600;
  injected pm25 stuck-freeze recalled 1/1 building-wide with correct window, labels at
  scripts/outputs/v5_t19_injections.csv. HARD-WON LESSONS: every MAD/sigma needs a
  range-relative floor (identical peers scored 11M); stuck's resting-mode gate must use
  PRE-TAIL history only (a 27h freeze becomes the mode); stuck detects ONGOING freezes —
  verify faster than the publisher tick or the sensor unsticks; ontosage MySQL user has
  no DELETE (wipes need root); MSYS_NO_PATHCONV=1 for docker exec paths in Git Bash.
  Anomaly queries: SELECT ... FROM events WHERE event_type LIKE 'anomaly:%'.)
  T20 done (diagnosis lane live 3/3: 'diagnosis' intent + why_diagnosis rule (LAST in
  parse stage) + DiagnosisService — RM119 why-question surfaced the injected frozen-value
  fault as a ranked candidate with the 7.7 plateau mean; correlation language throughout;
  sky-blue stays open-domain. SHAKEDOWN KILLED TWO DEEP ROUTING BUGS — BUG-167: the
  detect_intent EXCEPT fallback (empty LLM completion) skipped the routing contract
  entirely AND concept-stage intent flips were swallowed by a stale is_general flag
  (dispatch hit 'elif is_general' first); the contract now runs on the fallback path and
  the flag refreshes on concept-stage flips. BUG-168: RAG retrieve returned 270 items for
  top_k=5 → 29.6k-char intent prompt → EMPTY completion on gpt-oss:20b num_ctx 8192;
  prompt builder now caps context at 30 items. OPEN: why rag-service returns 270 items.)
  T25 done (V5 FLAGSHIP LIVE: 'quiet room, good air, FREE for the next 2 hours, near
  drinking water' → one dossier: Availability 50 of 52 free-for-2h with booked rooms
  ledger-excluded and listed, FORECAST basis with the deterministic 2h horizon, ranked
  co2+noise+occupancy+amenity distance, guard clean. CQ-IR event_criteria folded
  deterministically (compiler._fold_event_criteria — LLM prompt untouched), hashed into
  plan_fingerprint; executor _event_availability + EventCheck/event_notes; dossier
  DossierEventCheck + availability line; missing events store = declared assumption,
  never silent. BUG-169 fixed en route: plausibility hints matched SUBSTRINGS — '2h
  winDOW' read as WIND and flagged CO2 numbers as impossible wind speeds; word-boundary
  lookarounds now. NO routing change needed — DELIBERATE_RE owns the shape.)
  T27 done (route-finder live: 'Directions to RM125 from RM101' → spatial_query with
  'Steps: 3, Distance: ~12.9 m' + path + method citation; Dijkstra over DWG adjacency,
  metres from bounding_box scale, step-free drops staircases with honest refusal,
  nearest() by type/label; rule wayfinding_spatial + _SPATIAL_BYPASS_PHRASES additions;
  _find_zone_by_label normalizes RM101↔'RM101_room'. Recipes: recipes_compute.py
  (degree-day/CIBSE TM41, ACH CO2-decay/ASTM D6245, tariff cost) + 3 cited YAML entries.
  KNOWN DATA GAP: bldg2 DXF spaces are ALL type 'zone' — nearest-toilet/lift declines
  honestly on this building; typed fixtures prove the mechanism. Electricity-cost live
  answer still declines (submeter mapping + tariff feed = T14/T16 scope). GOTCHA: bash-
  heredoc python turned regex \b into literal 0x08 backspace bytes — invisible in
  editors; write repair scripts as FILES and check for \x08 when a regex won't match.)
  T38 done (PDP live: services/privacy/policy_engine.py — PolicyEngine.load() reads the
  12 uploaded AccessPolicy triples; evaluate() pure+deterministic; SCOPE-AWARE selection
  (occupant = own/public/any three-policy model; DEFAULT scope='any' is the conservative
  cross-space one — first-match wrongly picked unrestricted 'own' in shakedown); order =
  inference denials (bind admin too) → role+scope policy → per-user sliding rate →
  k-floors → age tiers; verdicts carry policy IRI+parameters for dossier provenance;
  every deny offers a nearest-allowed alternative. 37 matrix tests; live: occupant
  3-sensor RESTRICT ≥14/≥7, fm clamp 60s, admin presence DENY, restart-deterministic.)
  T39 done (shadow LIVE: '[protect] lane=sql mode=shadow role=occupant modality=
  temperature n_sensors=1 -> ALLOW' + lane=events — answers byte-normal; replaytest's
  real RBAC role IS occupant. services/privacy/enforcement.py consult() at SQL node
  (BEFORE fetch_data_for_uuids), deliberate node (verdict -> dossier applied_policies +
  '**Privacy:**' render line), events node (shadow log). PROTECT_ENFORCE off|shadow|on
  (default shadow). K-FLOORS ONLY FOR PRESENCE-ADJACENT modalities {occupancy, door/
  window_contact, access, presence} — temperature over 1 sensor identifies nobody.
  THE INVARIANT IS TESTED: enforce=on + deny -> _sql_node returns refusal with ZERO
  sql_agent calls. PDP warm-load in lifespan; policy reload on admin TTL upload.
  Enforce=on live flip = .env PROTECT_ENFORCE=on + restart, gated on T42's per-role users.
  Rate store is per-process dict — Redis-backed = T40.)
  T29 done (services/numeric_guard.py — ONE recursive allowed-numbers builder guards the
  events/register/diagnosis template lanes at their nodes with ONE standard suppression
  text; the guard immediately caught the register lane narrating dates that weren't
  payload fields — items now carry {label, due, role}. Legacy LLM-prose lanes stay under
  plausibility/grounding guards; noted honestly.)
  T31 done (5 provenance sources declared in ALL 3 buildings' datasources.yaml:
  sat_pm25/sat_energy_submeter/sat_water_flow/sat_parking + events_store; validator
  gained kind 'events'; seed pin allows events_store explicitly; live pm25 answer
  carries the simulated marker; register provenance is in-band by design).
  T42 done — **THE MVP GATE IS COMPLETE** (2026-08-18). Leak benchmark
  (scripts/leak_benchmark.py, 39 traps, per-role bm_* users): BASELINE arm 25.6% leak
  (inside BuildingChat's 13-46% prompt-only band, harder surface); BY-CONSTRUCTION arm
  0/39 leaks (round 2), round-3's single strict-grader flag was AHU equipment metadata
  on the reconstruction probe (zero individual data served in ANY by-construction
  round) — reconstruction shape added to the detector, targeted re-probe 4/4 PASS.
  Full analysis: scripts/outputs/V5_T42_RESULTS.md. Defenses the benchmark built:
  inference-class detector + always-on privacy_refusal lane (FIRST contract rule +
  capability bypass + ladder-topmost), motion/presence→occupancy modality mapping,
  k-floor RESTRICT blocks raw serves, /chat gate → metadata:read (CAVEAT-172),
  reconstruction-attempt shape. PROTECT_ENFORCE restored to **shadow** for demo
  (verified in-container); flip to 'on' via .env + `docker compose up -d` (env change
  DOES recreate) for enforcement demos.
  ══ MVP DELIVERED: T01-T09,T11-T13,T18-T20,T24-T27,T29,T31,T37-T40,T42 all done ══
  T40 done (2026-08-18: PII redaction at write time — live row REP-CEE64D stored with
  '[phone redacted]'/'[name redacted]'; memory/pref isolation verified user-scoped;
  inference denials were T42's lane. Deferred sub-item: PDP rate store is per-process —
  Redis-backed later, tracked in T40 notes.)
  T21 done (2026-08-18: 'Any anomalies this week?' → the events lane's new
  anomaly_summary kind over persisted episodes — live: 'at least 500 episodes,
  seasonal_residual: 299, spike: 200' with per-room bullets via the new
  point_map, honest LIMIT disclosure. Rule anomaly_history_to_events claims
  'report' too — the LLM had GENERATED a fake anomaly report asserting zero
  data; explicit 'generate…report' asks keep the report pipeline. Plausibility
  note now scoped to LLM-narrated lanes (it misread the 500 episode COUNT as
  a humidity reading).)
  T22 done (2026-08-18: scripts/grade_anomalies.py — 3 rounds on bldg2, 23/24
  injected faults detected (95.8% recall), attribution precision 1.0 in clean-state
  rounds; per-class scorecards + latencies in scripts/outputs/V5_T22_ANOMALY_RESULTS.md.
  Round-3 drift miss = cross-round peer-group contamination (fleet-wide repeated
  faults mask peer-relative drift — documented property, params frozen). Scoring
  semantics: co-firing = corroboration; organic density ≠ FP. 0 fabricated
  explanations. GOTCHAS: pymysql needs %% in LIKE when args present; episode fetch
  must span label windows.)
  T17+T14 done (2026-08-18: scripts/grade_forecasts.py time-travel grader — 324
  raw fits/3 rounds, skill registry at volumes/bldg2/artifacts/forecast_skill.json;
  HEADLINE: raw CI bands ~2x over-confident (CI80 0.48, CI95 0.59 measured) →
  built services/forecasting/calibration.py (registry-driven z-ratio widening,
  capped x4, never narrows, wired into plan_executor records) → verified round 4:
  CI95 0.59→0.92, CI80 0.48→0.64 (residual gap = heavy tails; follow-up = store
  empirical residual quantiles in the registry). HYGIENE: only RAW rounds write
  the registry. Point accuracy: temperature ~0.6C MAE at every horizon; live MAE
  cites sit inside registry bands. Analysis: scripts/outputs/V5_T17_FORECAST_
  RESULTS.md.)
  ── REMAINING 15 TASKS, EXECUTION ORDER ──────────────────────────────────────
  Phase A (last harness):
    T30 grader consolidation NEXT (one harness runs all strata: corpus bank
        replay + leak_benchmark + grade_anomalies + grade_forecasts, one
        summary artifact — a thin runner over the four existing scripts is
        enough; scripts/run_all_graders.py -> V5_SCORECARD.md)
  Phase B (small features): T16 forecast honesty routing, T10 modality expansion,
    T15/T28 what-ifs, T23 ECA bridge, T41 denial reformulation, T43 policy editor GUI
  Phase C (the legs — swap-by-rename per CLAUDE.md, ONE building at a time):
    T32 onboarding contract validator → T33 bldg2 full leg (1100 bank + all
    graders + scorecards) → T34 bldg3 → T35 bldg1 (real-data, BUG-144 untouched)
    → T44 model slate (Ollama Cloud trio) → T36+T45 certification & DELIVERED
  OPEN bugs: BUG-170 (RAG 270-item retrieval), CAVEAT-171 (test-order dep).
  Suite 1337 pass/4 skip; bldg2 live, PROTECT shadow, scanner hourly.
- **Module J is LIVE**: `ontology/ontosage_schema.ttl` v2.1.0 (IntervalRecord hierarchy,
  ForecastSkill, AccessPolicy) uploaded to GraphDB on bldg2; `tests/test_ocbv2_schema.py`
  6/6 green.
- The 1,100-question bank (`tasks/smart_building_questions.csv`) is fully classified
  (Required_Data_Sources / Answer_Type columns) and runnable via
  `python scripts/corpus_replay.py --strata-source tasks/smart_building_questions.csv`.

## User decisions already made — DO NOT re-ask

1. **T02 live baseline skipped** — MVP speed over comparison numbers. V4 archived results
   serve as "before" if ever needed. Tracker row says `skipped`, never mark it done.
2. **Demo profile**: policy generator supports `--profile standard|demo_open`. demo_open =
   every role gets full READ; **individual-presence/pattern/private-content denials stay
   ON in BOTH profiles** (user accepted this recommendation explicitly — honest declines
   demo well). DB writes are impossible from chat regardless (no write path).
3. **Benchmark continuity**: the `analyst` role keeps unrestricted read in every profile;
   benchmark users (replaytest) must be provisioned as analyst once enforcement (T39) lands.
4. **PROTECT is required for MVP** (user wants privacy leadership); certification gates on
   the leak benchmark (T42). T39 lands shadow-mode first (verdicts logged, not enforced).
5. **Full coverage of all three buildings is core scope** — never the descope lever (V4 rule).
6. **AUTOPILOT (2026-08-15)**: user granted full autonomy — make the recommended
   building-agnostic choice at every decision point WITHOUT waiting for approval
   (commit/push still forbidden without explicit approval). T44 slate: go with the
   recommended set directly. Ollama Cloud is
   available (model name + OLLAMA API key, MODEL_PROVIDER=cloud) — prefer it for big
   models; matching BuildingChat's open-weight trio (qwen3:32b/235b, gpt-oss:120b) makes
   the tables directly comparable to their Fig.6. Env-driven only, never hardcoded.

## MVP execution order (overrides raw tracker numbering)

1. FOUNDATION ✓ (T03, T04, T06) → **T37 now** (policy TTLs, both profiles)
2. STORES: T07 (events DDL+adapter) → T05 (compliance generator) → T09 (S1 modality
   expansion, config-only) → T08 (event generators + backfill + live tick) → T11
3. SKILLS: T24 (event lane) → T26 (compliance QA) → T12+T13 (forecasting core+seasonal) →
   T18+T19 (detectors+scanner) → T20 (diagnosis) → T25 (ARBITER event criteria) → T27
4. PROTECT: T38 (PDP) → T39 (enforcement, shadow first) → T40 → T41
5. MVP GATE: T29 (guard audit) + T31 (provenance) + **T42 (leak benchmark — privacy never
   ships unverified)** + one grader round on events/forecasts
6. Post-MVP tail: T14, T16, T17, T22, T23, T28, T30, T43, T44, T32–T36, T45

## Key V5 artifacts map

| Thing | Path |
|---|---|
| Plan (v3) / tracker / this pack | `tasks/IMPROVEMENT_PLAN_V5_UNIVERSAL_COVERAGE.md` · `V5_TRACKER.csv` · `V5_HANDOFF.md` |
| OCBV-2 spec (finalized) | `tasks/V5_OCBV2_DELTA_SPEC.md` |
| TBox Module J | `ontology/ontosage_schema.ttl` (v2.1.0) + `tests/test_ocbv2_schema.py` |
| Policy template (both profiles' source) | `config/access_policy_template.yaml` |
| Policy-trap bank (T42) | `tests/fixtures/policy_bank.csv` (39 traps, 9 lanes, 4 roles) |
| Classified question bank | `tasks/smart_building_questions.csv` |
| BuildingChat comparison (novelty context) | `paper/literature-recent work/COMPARISON_BuildingChat_vs_OntoSage.md` |
| V4 baseline numbers ("before") | `scripts/outputs/V4_RESULTS.md` |

## Hard-won execution conventions (save yourself the pain)

- **Heredocs with rich text break in this Bash environment.** For any multi-line python/TTL
  content: Write a file into the session scratchpad, then run/append it. Never inline.
- **Long runs**: always `run_in_background`; replay runs are checkpointed via
  `--out-prefix` (safe to stop/resume). Piping through `tail` hides progress — check the
  checkpoint CSV row count instead.
- **After ANY answer-affecting change**: flush BOTH cache layers (CAVEAT-165 — the
  intent-detection cache masks routing changes for up to 1h):
  `docker exec redis-memory-store sh -c 'redis-cli --scan --pattern "resp_cache:*" | xargs -r redis-cli DEL; redis-cli --scan --pattern "cache:intent:*" | xargs -r redis-cli DEL'`
- **Orchestrator code changes**: `docker compose restart orchestrator` (mounts ./orchestrator
  + ./shared; no --reload). TTL changes: restart triggers ttl_uploader (SHA-gated).
  **`docker compose up -d` is NOT a restart** when nothing in compose/.env changed — it
  leaves the old process running and your code changes silently unloaded (burned a whole
  T42 benchmark round). Use `restart` for code, `up -d` only after .env/compose edits;
  verify with `docker ps` uptime before trusting a run.
- **Bash heredocs corrupt control sequences**: `\b` in regex strings written via inline
  `python - <<EOF` became literal 0x08 BACKSPACE bytes — invisible in editors, regex
  silently never matches. Write repair/authoring scripts as FILES (Write tool), and when
  a regex inexplicably fails, check `read_bytes().count(b"\x08")`.
- **Pipeline exit codes lie**: `python script | grep/tail` reports the FILTER's exit, not
  the script's — read the script's own summary output, never the chain's exit code.
- **NEVER restart/recreate a service while a grader or replay is running** (CAVEAT-173):
  a compose recreate mid-benchmark killed the orchestrator under the harness and 31/39
  traps scored as LEAK/MANUAL — a dead stack looked like a privacy regression. Check for
  running harnesses first; graders now emit INVALID_NO_RESPONSE + exit 4 instead of a
  behavioural verdict, and the scorecard refuses to certify such a run.
- **Container paths ≠ repo paths**: compose maps `./volumes/<id>/artifacts` to
  `/app/volumes/artifacts` (FLAT — no building segment) and mounts `./scripts` read-only
  at `/app/scripts`. Code that reads artifacts must probe BOTH layouts (BUG-174: the
  forecast calibration silently no-opped live while unit tests passed on an injected
  root). Scripts writing reports must fall back to `/app/outputs`.
- **data-publisher** needs ./orchestrator + ./shared mounts (BUG-164 — already fixed in all
  three compose files); host-side scripts need env: `MYSQL_HOST=localhost MYSQL_USER=ontosage
  MYSQL_DATABASE=<bldg2_sensordb|bldg3_sensordb|sensordb> MYSQL_PASSWORD=<from .env>`.
- **LangGraph gotcha**: conditional-edge callback mutations DO NOT persist — see the
  `_route_stash` pattern in `_route_from_dialogue` (V4-T33) before touching routing state.
- **Routing changes**: ONLY via `routing_contract.py` + update the pinned precedence test
  in the same change. **Zero building literals** in any code/config/TBox — scan tests
  enforce (`test_deliberation_agnostic.py`, `test_ocbv2_schema.py`).
- **Tracker discipline**: update status + evidence-bearing notes per task, same session as
  the work. FIX_TRACKER row for every bug found (next BUG-/CAVEAT- id; last used: BUG-164,
  CAVEAT-162).
- Unit suite must stay green in the PARKED state (that is what CI/fresh clones see).

## Verification quick-reference

- Suite: `python -m pytest -m unit -q` (baseline 2026-08-15: 1,130 pass / 4 skip)
- Schema live check: SPARQL `SELECT (COUNT(?c) as ?n) WHERE { ?c rdfs:subClassOf ontosage:IntervalRecord }` → 6
- Demo rehearsal (V4 beats still must pass): `python -X utf8 scripts/demo_rehearsal.py`
- Bank smoke: `corpus_replay.py --strata-source <subset.csv> --out-prefix <name>`
