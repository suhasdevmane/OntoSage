# Improvement Plan V6 — Evidence Discipline and Observability

**Status:** PROPOSED · **Date:** 2026-08-21 · **Tracker:** [`V6_TRACKER.csv`](./V6_TRACKER.csv)
**Source material:** `QuestionBank/` — 1 Master Technical Report (25 pp) + 6 Stakeholder Question
Catalogues (46 pp each, 480 catalogued questions), plus the existing 1,100-question synthetic bank
(`tasks/smart_building_questions.csv`) and the 5,604-question pre-design survey corpus.
**Extractions:** `tasks/v6/extract_readers.json` (7 docs), `tasks/v6/extract_inventory.json`
(44 verified capability areas), `tasks/v6/extract_gaps.json` (19 verified findings, 3 of 24 categories).

---

## 0. The finding that should change the plan before it starts

The supervisors' catalogues classify every one of their 480 questions into a readiness tier. Counted
across all six documents:

| Tier | Meaning | Count | Share |
|---|---|---:|---:|
| **R1** | Answerable with core sensing + basic verified spatial/access/service data | **27** | **5.6%** |
| **R2** | Requires an *integration* — timetable, booking, BMS, access control, AV, lift, network, meters | **303** | **63.1%** |
| **R3** | Requires research-grade validation, governed data, or restricted permissions | **150** | **31.3%** |

**Roughly 94% of what the supervisors are asking for is not blocked by OntoSage's code.** It is
blocked by data the buildings have not connected, and by validation and governance that do not yet
exist. No amount of engineering in this repository makes an R2 question answerable if the building
never connects its timetable.

That is not a reason to do less. It is a reason to do something different from "add features until
the question bank passes". A plan that measured itself by raw answer rate would be measuring the
estates department's integration backlog, and would be under quiet pressure to fabricate — which is
the one failure mode this project has spent two versions eliminating.

**So V6 optimises three things instead:**

1. **Every unanswerable question returns a precise, actionable, auditable non-answer** — naming the
   missing variable, the missing coverage, the missing authority, or the missing permission. The
   Master Report is unambiguous that this is the deliverable: *"the building should never sound more
   certain than the evidence available inside the building"*, and *"a correct non-answer is
   preferable to a fluent but unsupported conclusion."*
2. **Every R2 question becomes answerable by connecting data, not by writing code.** V6 builds the
   adapters and the ontology so that a building which connects its booking system lights up dozens of
   catalogue questions with zero code change — the same contract that already holds for sensors
   (drop TTL + register DB + load rows).
3. **The system can state, per building and per question, exactly what it would take.** The Master
   Report calls this the *Question-to-Observability Matrix* and says it is the artefact that
   *"prevents the project from claiming capabilities that the physical deployment cannot support."*

Measured that way, a building with 6% instrumentation and a 94%-precise account of its own blindness
is a success, and it is a far stronger research claim than a high answer rate on a synthetic bank.

---

## 1. What the documents actually demand

The seven documents are strikingly consistent. They are not asking for more question coverage; they
are asking for an **evidence-discipline retrofit**. The same rules recur near-verbatim across all six
stakeholder catalogues and the Master Report:

| # | Rule | Where it appears |
|---|---|---|
| R-1 | **Answer-status taxonomy** — every answer is one of *Observed / Calculated / Inferred / Predicted / Recommended / Not assessable* | Master Table 16 |
| R-2 | **Operation labelling** — label the operation as observation, authoritative lookup, calculation, estimate, forecast, diagnosis or recommendation; never blur them into one figure | all 6 catalogues |
| R-3 | **11-field machine-readable evidence record** on every consequential answer | Master 12.1 |
| R-4 | **Non-substitution** — a room-level answer needs a sensor *inside* the room or a validated served zone; corridor data may be labelled context, never silently substituted | Master 8; LT, PhD (PHD-077 is a dedicated test) |
| R-5 | **Final answerability rule** — answer only when variables, spatial coverage, time window, source authority, data quality and permissions are *all* adequate; else clarify, omit, or decline | all 6 catalogues, ~60 of 80 records each |
| R-6 | **Freshness and completeness floors** — 1-minute records; live values ≤5 min old; historical windows ≥90% complete | LT, AO, PGT |
| R-7 | **Source precedence** — bookings, access, timetables, alarms come from authoritative systems, *never* from environmental inference | PhD, RS, AO |
| R-8 | **Never infer permission from physical state** — an empty room is not available; an open door is not access; a quiet room is not private | PhD |
| R-9 | **Omitted-criteria reporting** — "*[criterion] was omitted because [missing / stale / restricted] source*" | PhD, RS |
| R-10 | **Primary + independent backup** on every recommendation (the backup must not share the same unverified service, circuit or network path) | PhD, RS |
| R-11 | **Accessibility is a hard filter, not a preference** — if step-free status is unverified, do not label it step-free | PhD, UG, LT |
| R-12 | **Consequence-scaled evidence** — the threshold rises with the cost of being wrong; correlation is never reported as cause; a standards claim needs calibrated evidence | Master 1.1, 12.2 |
| R-13 | **Six access tiers**, and the conversational layer must not become a route around existing access control | Master 11.2, Table 15 |
| R-14 | **Separate measurement change from environmental change** — relocation, recalibration, replacement and firmware changes must not read as building behaviour | PhD, AO |

And eight **acceptance-test scenarios** (Master 14.1) that read like a V6 test plan:

1. Remove the room sensor → the system refuses a room-level claim rather than silently using corridor data.
2. Introduce missing intervals → duration and average calculations change appropriately.
3. Move a sensor in metadata → historical observations stay linked to the correct prior location.
4. Create conflicting sensors → the answer reports the disagreement rather than averaging it away.
5. Ask a causal question with only correlational evidence → wording remains qualified.
6. Public user requests restricted security/occupancy data → access control is enforced.
7. Standards question without calibrated evidence → returns *not assessable*.
8. Same factual question across roles → the underlying result is consistent; only explanation depth adapts.

---

## 2. Where OntoSage already stands

The 44-area inventory (`tasks/v6/extract_inventory.json`) was built by reading the code, not the
docs, and was spot-verified during planning. The honest summary:

**Already strong — V6 should extend, not rebuild:**

- **Anti-fabrication.** Referent-existence gate, grounding guard, plausibility guard, shared numeric
  guard, dossier numeric guard. *Measured 0 fabricated across every V5 grader round and every model
  in T44.* This is the foundation R-1…R-5 bolt onto.
- **Deterministic routing contract.** 28 ordered, individually-tested, building-agnostic rules with a
  pinned precedence order. New evidence rules have a home that is already disciplined.
- **Evidence dossier** (`services/deliberation/dossier.py`) — carries space, modality, value, basis,
  window, n_points, sensor_uuid, stored_at, simulated, threshold source, data gaps, exclusions.
  **This is roughly 6 of the Master Report's 11 fields, already built.**
- **Honest declines that name the fix** — actionable refusals already tell the user what to connect.
- **Config/TTL-first extension path** — `saturate_building.py` provisions a whole new modality into
  per-building TTL + narrow table with zero code change. This is exactly the mechanism R2 unlocks need.
- **PDP / privacy engine, RBAC, compliance register, events lane, route finder, forecast calibration,
  anomaly detectors** — all present and certified on bldg2.

**Verified absent — this is the V6 work:**

| Demand | Status in code (verified during planning) |
|---|---|
| Answer-status taxonomy (R-1) | **Absent.** Grep for the six statuses returns only unrelated docstring prose. |
| Universal evidence record (R-3) | **Lane-scoped.** The dossier exists only on the deliberate lane; sparql/sql/analytics/capability lanes emit nothing comparable. |
| Sensor calibration / drift / quality flag / fault state (R-6, R-12) | **Absent.** Grep across all three buildings' TTL and `ontology/` finds two prose mentions and no property. |
| Effective-dated sensor location history (R-14, test 3) | **Absent.** No temporal validity on any sensor-to-space relation. |
| Spatial adequacy — in-room vs served-zone vs proxy (R-4, test 1) | **Partial.** The referent gate refuses *unknown referents* and *modality substitution* ("no CO₂ sensor → I won't substitute a different measurement"), but there is no gate for the case the supervisors test hardest: the room exists, a CO₂ sensor exists in the building, just not in *that* room. |
| Freshness / completeness gates (R-6) | **Absent** as first-class gates. |
| Conflicting-sensor disagreement (test 4) | **Absent.** |
| Source precedence (R-7, R-8) | **Absent** as an explicit contract. |
| Six access tiers (R-13) | **Partial.** 6 RBAC roles × 20 permissions exist but are not mapped to the Master Report's tiers, and cross-role answer consistency (test 8) is untested. |
| Consequence scaling (R-12) | **Absent.** |
| Primary + independent backup (R-10) | **Absent.** |
| Recurring time-of-day windows (night baselines, after-hours) | **Absent** — `sql_agent._build_uuid_union_query` supports only contiguous ranges. Blocks night-leak, after-hours-energy and "full by lunchtime" questions across several categories. |
| Human reports bound to a space IRI | **Absent** — reports are free text; a suggestion about "level 5" is not structurally linked to level 5. |
| One ticket universe | **Absent** — user reports and work orders are disjoint stores that never join. |
| Waste / recycling domain | **Absent entirely** — already recorded as a backlog item by `scripts/ttl_gap_audit.py`. |

---

## 3. Design decisions, and why

### D-1. The evidence record is a *chokepoint*, not a per-lane feature
**Choice:** one `EvidenceRecord` assembled at a single point in `_response_node`, populated by
whatever the lane put on the state bus.
**Why:** V5 already proved the alternative fails. BUG-210 in this very repository was two copies of
the same linking step drifting apart until identical inputs produced different results depending on
which path ran. Nine lanes each building their own record would reproduce that failure nine times.
**Rejected:** per-lane records (drift, as above); LLM-generated provenance prose (unverifiable — the
whole point is that the record is machine-readable and checkable).

### D-2. Sensor quality metadata goes in the TTL, not a sidecar
**Choice:** extend the OCBV TBox with calibration, quality state, environmental boundary, the three
clocks, access classification and effective-dated validity.
**Why:** design contract #2 — if a fact can be a triple, it is a triple. These *are* facts about the
building's instrumentation, they are exactly what Brick/`ref:` is for, and putting them in the graph
means SPARQL can gate on them and the admin ontology GUI can edit them with no new UI.
**Rejected:** `sensor_quality.yaml` (a second source of truth about the same sensors, guaranteed to
drift from the TTL); computing quality only at query time (cannot express calibration date or
mounting height, which are asserted facts, not derived ones).

### D-3. Spatial adequacy is a *classification*, not a boolean
**Choice:** every value carries one of `in_room` / `served_zone` / `proxy` / `none`, and the policy
decides what each answer type may use.
**Why:** the Master Report explicitly permits proxy data *labelled as context* — a blanket refusal
would be less useful and less honest than the rule it is trying to enforce. "The corridor outside
2.15 read 900 ppm at 14:02; I have no sensor inside 2.15" is a good answer. "900 ppm" is a lie, and
"I don't know" throws away real evidence.
**Rejected:** boolean has-sensor/no-sensor (throws away usable context); distance-based proxying
(BUG-189 is precisely what happens when geometric nearness is allowed to imply attribution).

### D-4. Thresholds are policy, not constants
**Choice:** `config/evidence_policy.yaml` + per-building overlay, holding freshness, completeness,
agreement and consequence thresholds with citations.
**Why:** the 5-minute and 90% figures come from the supervisors' catalogues, but a different building
in a different climate with a different sampling regime will need different numbers, and design
contract #3 forbids building literals in code. This also mirrors the pattern that already works —
`config/recipes.yaml`, `config/benchmarks.csv`, `saturation_modalities.yaml`.
**Rejected:** hardcoding 5 min / 90% (would silently misgrade any building sampled differently);
per-building only, with no default (a new building would have no gate at all — absence must fail safe).

### D-5. R2 unlocks are adapters, not features
**Choice:** timetable, booking, access-control and BMS arrive through the existing feed/adapter
registry shape, declared in per-building config.
**Why:** 63% of the catalogue is R2. Building nine bespoke integrations would be nine building-specific
code paths — the exact thing design contract #9 forbids. The adapter registry already routes
time-series by `ref:storedAt` with no agent edits; the same discipline extends to institutional data.
**Rejected:** direct integration per building (unportable); waiting for buildings to connect before
building the shape (the shape is what makes connecting cheap, so it must come first).

### D-6. Consequence classes are declared per question shape, not inferred by the LLM
**Choice:** a shape → consequence-class map in config, with the evidence threshold rising per class.
**Why:** BUG-213 in this session is the cautionary tale — the model emitted an intent that existed in
no registry, and because nothing validated it, it bypassed every deterministic rule. Letting the same
model self-assess "how bad would it be if I'm wrong here" puts the safety property in the least
reliable component.
**Rejected:** LLM self-assessment (above); a single global threshold (defeats the point — Master 1.1
is explicit that reporting a temperature and declaring a workplace safe are different).

### D-7. The 480 catalogue questions become the acceptance corpus, tagged by tier
**Choice:** import them with their R1/R2/R3 and L1–L4 tags, and report coverage *per tier*.
**Why:** an untiered aggregate would hide the only number that matters. R1 coverage measures
OntoSage; R2 coverage measures the estate's integrations; R3 coverage measures governance. Reporting
them together would let a good R1 score mask an empty R2 — and would tempt exactly the kind of
scoring inflation that CAVEAT-173, BUG-176 and BUG-177 already cost this project three false results.
**Rejected:** a single coverage percentage (see above); replacing the 1,100-question bank (it is
already V5-T03-classified across 24 categories and 15 stakeholder roles — both corpora are kept).

### D-8. "Not assessable" is a first-class outcome, not an error
**Choice:** it is one of the six statuses, it carries the reason and the remedy, and it is *scored as
correct* when the evidence genuinely does not support an answer.
**Why:** this is the Master Report's single most important design requirement (15.5), and V5's
graders already learned the lesson the hard way — BUG-191 counted a refusal as a pass because a digit
appeared in it. If a correct refusal is not explicitly scored as correct, the metric quietly punishes
the behaviour the whole design is built to produce.

### D-9. Existing answerability is protected by a baseline, not by good intentions
**Choice:** capture a golden baseline over all 1,580 questions *before* any V6 code lands (T54), and
run every gate in advisory mode before it enforces (T55).
**Why:** V6's gates are restrictive by design, so answers will change — and an intended tightening
(an answer that its evidence never supported) is indistinguishable from a regression (an answer that
was correct and now is not) in any aggregate number. The distinction has to be mechanised: every
changed answer must classify as improved, unchanged, tightening-with-a-named-gate, or regression, and
**a regression blocks the task**. Advisory mode then makes each gate's blast radius reviewable
*before* it is felt — "this freshness floor would change 340 of 1,580 answers, here they are" is a
decision that can be taken; "coverage dropped 11% overnight" is not.
**Rejected:** relying on the unit suite (it tests components, not answers); comparing coverage
percentages (an aggregate hides which questions moved, and equal totals can conceal offsetting gains
and losses); enabling gates and reverting if the numbers look bad (the damage is already in the
measurement, and revert-by-feel is how thresholds get tuned to flatter the score).

### D-10. The missing 94% is provisioned as *declared* synthetic data
**Choice:** a single building-agnostic generator (T56) provisions every unconnected source family —
timetable, bookings, opening hours, lifts, AV, network, BMS/plant, submeters, alarms, work orders,
cleaning, accessibility — reading the **active building's own graph** and stamping every record
`ontosage:isSimulated`.
**Why:** without it the system can only ever *demonstrate honest declines*, and 94% of the
supervisors' bank stays untestable end-to-end. This is not a departure from the honesty contract — it
is already how this project works: bldg2 and bldg3 are wholly synthetic and declared so, and SATURATE
already provisions modalities this way with zero code change. The contract forbids *undeclared*
fabrication, not *declared* simulation.
**Rejected:** hand-authored fixtures per building (unportable, stale the moment the graph changes);
one generator per family (duplicated building-resolution logic, which is exactly how building
literals creep in); inferring institutional facts from sensors (bookings from occupancy is the
inference R-8 explicitly forbids).

### D-11. Synthetic data must carry the same defects real data has
**Choice:** T61 injects gaps, stale streams, drift, disagreeing pairs, relocations, uncalibrated
points and out-of-service amenities — deterministically, with a ground-truth manifest.
**Why:** this is the task that makes the rest of V6 falsifiable. **Perfect synthetic data would make
every V6 gate untestable.** If nothing is ever stale, incomplete, drifting or uncalibrated, then
acceptance scenarios 1, 2, 4 and 7 can never fire, every gate passes by construction, and the
scorecard would be measuring a system that has never once been required to refuse. That is precisely
the self-flattering measurement that has already cost this project three false results (CAVEAT-173,
BUG-176, BUG-177). A manifest of injected defects also lets the grader score each gate's **precision
and recall**, not just whether it fired.
**Rejected:** clean synthetic data (gates pass by construction); random noise (unrepeatable, and
expected behaviour becomes unknowable); defects only in unit fixtures (the live system is then never
seen under the conditions the gates exist for).

### D-12. Building-agnosticism is enforced by a gate, not by discipline
**Choice:** T63 fails the build on any building literal in core code, and asserts all three buildings
pass the V6 suite with an identical code path.
**Why:** V6 adds ~60 tasks of code and eight new input-file kinds. Manual review is demonstrably
insufficient — in this session alone the guards caught two building literals that had been written by
accident (a TBox comment and a docstring). Finding the third at certification time is far too late.
Every task in the tracker now also carries a written `building_agnostic_how` answering the project's
own litmus test: *would this run unchanged for bldg2?*

### D-13. Local model and one building for the whole plan
**Choice (user decision, 2026-08-21):** `MODEL_PROVIDER=local` on `gpt-oss:20b` throughout, and
**bldg1 (Abacws) stays the active building for the entire plan**. Hosted API models are evaluated
once, at the end (T49, now gated behind T48).
**Why:** hosted calls are metered, and V6 is a long development effort — spending the quota on
development traffic would exhaust it before there is a finished system worth benchmarking. Evaluating
hosted models against a *finished* system is also the more meaningful comparison. V5 already showed
the local 20B beating the hosted 120B on coverage (80.6% vs 78.8%), so nothing about the local choice
weakens the result. Keeping bldg1 active is the right development target for a different reason: it
is the **only building with real data**, so the freshness, completeness, drift and conflict gates get
exercised against genuinely messy input instead of data engineered to be clean.
**The risk this creates, and the mitigation:** developing on one building means building-specific
assumptions will not surface naturally — and bldg1 is atypically rich (6 floors, 267 spaces with
measured geometry, real time-series), so code may come to require a DWG, a six-floor hierarchy or
dotted room ids without anyone noticing. Two mitigations, both cheap: **T63's static literal scan runs
after every task** (it needs no active building and takes seconds), and **T64 adds a shared fixture
building deliberately unlike bldg1** — different namespace, non-dotted ids, two floors, no DWG, one
modality with no data — so a structural assumption fails on the commit that introduces it rather than
at certification. The three-building runtime check still happens, at wave boundaries and at T48.
**Rejected:** hosted models during development (burns the quota on throwaway traffic); rotating the
active building during development (each swap costs a full stack cycle and would slow every wave);
relying on the static scan alone (it catches hardcoded strings, not structural assumptions).

---

## 4. Structure — 11 phases, 53 tasks

| Phase | Theme | Tasks | Why it sits here |
|---|---|---|---|
| **P0** | Answer contract, policy foundation + regression protection | T01–T05, T54–T55 | Everything else writes into this record; building it late means retrofitting nine lanes twice. T54/T55 make the difference between an intended tightening and a regression *enforceable* rather than asserted |
| **P1** | Observability — knowing what the building can see | T06–T11 | The Question-to-Observability Matrix is the Master Report's central artefact |
| **P2** | Non-substitution and spatial adequacy | T12–T15 | Acceptance test 1; the highest-consequence honesty gap |
| **P3** | Quality gates — freshness, completeness, conflict | T16–T20 | Acceptance tests 2 and 4 |
| **P4** | Authority, precedence and the R2 unlocks | T21–T27 | 63% of the catalogue lives here |
| **P5** | Access tiers and privacy | T28–T31 | Acceptance tests 6 and 8 |
| **P6** | Consequence scaling and claim discipline | T32–T35 | Acceptance tests 5 and 7 |
| **P7** | Recommendation contract | T36–T39 | R-9, R-10, R-11 |
| **P8** | Long-horizon and comparison analysis | T40–T42 | Recurring windows unlock several categories at once |
| **P9** | Domain extensions found by gap analysis | T43–T45 | Waste, water, amenity status |
| **P10** | Certification | T46–T48 | Tiered scorecard across three buildings |
| **P11** | V5 carry-over | T49–T53 | The five V5 tasks, deliberately last. T49 (hosted-model benchmark) is gated behind T48 — the plan runs local-only until certification |
| **P12** | Synthetic provisioning of the missing 94% | T56–T63 | Turns "honest decline" into "answered from declared simulated data"; T61 keeps the gates falsifiable; T63 keeps it portable |

**64 tasks total.** T54 and T55 were added after review: the plan named the regression risk in its
limitations and then relied on care to manage it. Care is not a mechanism.

**MVP order** — 17 tasks, dependency-closed (verified against the tracker; an earlier draft of this
line was *not* closed, which would have stalled execution at the first spatial task):

> **T54** → T01 → T04 → **T55** → T06 → T02 → T03 → T08 → T12 → T13 → T14 → T15 → T16 → T17 → T19 → T18 → T20

**T54 runs before any V6 code lands** — a golden baseline taken afterwards has already absorbed
whatever it was meant to detect.

That delivers: the evidence record and six-status taxonomy on **every** lane, policy-driven freshness
and completeness gates, the non-substitution gate with proxy labelling, and **acceptance scenarios 1,
2 and 4 automated** — the strongest defensible claim available before any R2 integration work.

Scenarios 3, 5, 6, 7 and 8 need T07, T29, T33 and T34 as well; the full eight-scenario suite (T47) is
the phase-10 goal, not the MVP.

---

## 5. Honest limitations of this plan

- **Only 3 of 24 question-bank categories were gap-analysed in depth.** The other 21 died with the
  model session limit after substantial work. The three completed (`Maintenance`, `Cleaning`,
  `Water & waste`) yielded 19 verified findings including two entirely missing domains, so the
  remaining 21 will very likely surface more. **T05 completes the sweep** and is expected to add
  tasks to P9. Treat the 53-task count as a floor.
- ~~The R1/R2/R3 counts are transcribed and should be re-verified in T46.~~ **RESOLVED 2026-08-21.**
  `scripts/extract_catalogue_questions.py` parses all 480 records straight from the PDFs and derives
  the tiers per question. The independently-derived totals are **27 / 303 / 150**, matching every
  catalogue's own summary table exactly — including the two that had been transcribed by hand. The
  structure also validates: 6 documents × 8 sections × 10 questions. The counts can be relied on.
- ~~This plan cannot deliver R2 coverage.~~ **REVISED 2026-08-21 — phase P12.** The missing sources
  are now provisioned as *declared synthetic data* generated from each building's own graph, so R2
  and much of R3 become answerable end-to-end on all three buildings. Two things that does **not**
  change, and both belong on the same page as any V6 score: a synthetic booking is still synthetic,
  so the scorecard reports the real/synthetic share per building and mixed answers say which source
  is which; and a real deployment still has to connect real systems — P12's value is that doing so
  becomes config plus rows, never code.
- **Perfect synthetic data would be worse than none** (D-11). Provisioning without T61's injected
  defects would make every gate pass by construction and the whole evidence programme unfalsifiable.
- **The Master Report is a concept design, not a procurement specification** — it says so on its
  cover. Its sensor counts (~72 core + ~18 specialist) are planning estimates. V6 should not treat
  them as targets to hit, and the observability matrix should report against what a building actually
  has, not against the report's indicative deployment.

---

## 6. Relationship to V5

V5 is **not** superseded. Its five open tasks are carried into V6 as P11 (T49–T53) unchanged, exactly
as requested, and V5's certified bldg2 scorecard remains the baseline V6 must not regress:
COVERAGE 80.6% combined / 26.2% data-backed · PROTECT 0.0% leak · DETECT 96.9% recall · PREDICT CI95 0.92.

V6's headline metric is deliberately different and deliberately harder: **evidence-record completeness
and non-answer precision**, reported per readiness tier. A V6 that lowers combined coverage while
raising non-answer precision is a *success*, because the coverage it loses was coverage the evidence
never supported.
