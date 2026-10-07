# OntoSage v2 — answering compound, multi-criteria questions

**Status:** plan, 2026-10-07. v1 is frozen as tag `v1.0-demo` before any v2 code is written.
**Owner decision being served:** compound questions are the core claim of the thesis — a
building knowledge graph should let a stakeholder ask one natural question that combines
several kinds of evidence, and get one grounded answer.

---

## 1. What "compound" means — six shapes, from real questions

Measured from the real survey corpus (`classified_corpus.csv`, 7,151 questions, 96
participants: 6,293 LOOKUP, 610 AGGREGATION, 248 MULTI_STEP) and the 37-role stakeholder
catalogue. Every compound question we have seen is one of these:

| Shape | What it needs | Real example |
|---|---|---|
| **C1 multi-criteria selection** | filter/rank ONE set of entities on criteria from DIFFERENT sources | "Find a quiet room for 12 with a projector, free this afternoon, step-free from reception" |
| **C2 cross-source comparison** | two facts about the SAME entity from different sources | "What is the real-time occupancy versus the evacuation capacity?" |
| **C3 group → aggregate → rank** | aggregate per group, then compare groups | "Which floor has less crowd now?" · "How evenly is air distributed across areas?" |
| **C4 period comparison** | one quantity over two named periods | "Peak vs off-peak usage?" · "This week's electricity vs last week's, by floor" |
| **C5 series/event relation** | relation between two series, or a series and events | "CO2 rises while occupancy stays flat" · "Do VOC levels spike after night-shift cleaning?" |
| **C6 multi-part** | two independent asks in one message | "What's the temperature on floor 2, and when is the next service?" |

C1 is the one stakeholders ask most and the one the thesis should lead with.

---

## 2. What v1 does today — measured against the code, not assumed

v1 already has **two** compound mechanisms. The gap is between them.

**ARBITER (the `deliberate` lane, `orchestrator/services/deliberation/`, 6,400 lines).**
A real compile-then-compute engine: the LLM's only job is to compile the question into a
typed, closed-vocabulary IR (`cqir.py`: decision kind, hard/soft constraints, direction,
threshold source, spatial qualifiers, resolved time window, ambiguity signals); a live
capability schema admits / clarifies / declines it (`capability_schema.py`, computed from the
graph); a deterministic executor fetches, aggregates, forecasts and scores
(`plan_executor.py`, `scorer.py`); a dossier explains every number (`dossier.py`); and a
plan fingerprint anchors determinism (`CQIR.plan_fingerprint`).
**Its limit is one sentence:** the vocabulary is `saturation_modalities.yaml` — *sensed
quantities only* — and the target is always a *space*. Capacity, seats, projector/AV
readiness, step-free routes, maintenance windows, daylight aspect, bookability beyond
free/busy, network rating — everything the building holds as **records or TTL properties** —
compiles to an "unmapped term" and the question is clarified away or declined.

**MultiIntentDetector + PlannerAgent** (`MULTI_INTENT_ENABLED=true` by default). Decomposes a
message into sub-intents and runs them **sequentially** through existing lanes, concatenating
answers. It can reach every lane — but it cannot **join**: it can say which rooms are quiet
and, separately, which are bookable; it cannot say which rooms are both.

**Every other lane answers one facet.** A compound question routed to one of them answers
one part. Measured tonight on a 210-question stakeholder sample: 29 answers (14%) took the
shape *"The X register (N records) cannot answer this: it records … and nothing about …"* —
the register lane found the right register for ONE criterion and declined the rest.

**The structural cause, found in the data:** 21 of the 38 register mappings
(`ontology/record_documents/*.yaml`) locate a record by **text** (`ontosage:locationText
"Room 1.06"`, `ontosage:onFloor "Floor 1"`), not by a link to the room's IRI. Sensors are keyed
by room IRI. So "quiet" (sensor) and "seats ≥ 12" (register) cannot be joined in the graph at
all today — only by string matching, which nothing does.

### Shape-by-shape, v1

| Shape | v1 path | v1 result |
|---|---|---|
| C1, sensed criteria only | ARBITER | **works** (ranked, with dossier) |
| C1, any record criterion | ARBITER → unmapped term | clarify / decline |
| C2 | single lane | answers one side |
| C3 | aggregate lane (some), ARBITER (no) | partial — some group-by works, "largest gap" did not (pack #24) |
| C4 | aggregate/analytics | partial — pack #22/#23 failed |
| C5 | none | decline (pack #25) |
| C6 | PlannerAgent | works, sequentially |

---

## 3. The external proposal (`tasks/plan_inputs/agentic_supervisor_proposal_2026-09-29.md`)

Its central recommendation is right, and it says so itself: *"Your ARBITER design already
embodies much of the right principle: compile language into a validated representation, then
calculate results in code. Extend that principle to more workflows rather than introducing an
unconstrained autonomous agent."* And: *"Let the LLM decide which supported work to propose.
Let code decide whether that work is valid, permitted, executable, and supported by evidence."*

It was written without seeing the repository (its own words: "not a repository or live-stack
audit"). Checked component by component:

| Proposal item | v1 status | Where |
|---|---|---|
| Keep LangGraph; bounded supervisor, not an external runtime | **agree** | `workflow/_graph.py` |
| Fast path for simple questions | **exists** | `routing_contract.py` (68 rules) |
| Compile to a typed plan, compute in code | **exists — sensors only** | `cqir.py`, `compiler.py`, `plan_executor.py` |
| Executable capability catalog with *Declared/Linked/Populated* status, computed in code | **exists — sensors + amenities only** | `capability_schema.py`, `coverage_audit.py` |
| Catalog entries for records and TTL properties | **partial** — classes and their predicates are discoverable | `record_registry.record_classes`, `schema_hint` |
| Join path from a record to the entity it describes | **missing** | 21/38 mappings use text |
| Evidence, coverage, typed absence | **exists** | `evidence/`, `retrieval_outcome.py`, `dossier.py` |
| Clarify when ambiguity changes the answer | **exists** | `clarify_policy.py` |
| Bounded replan | **missing** | — |
| Shadow mode before cutover | **missing** (cheap) | — |
| goose / OpenHands / AutoGPT as the runtime | **reject** — adds a second runtime, non-determinism and a privilege boundary, and supplies no building semantics. The proposal itself recommends against it for serving. | — |
| Building packages / onboarding | separate track; not needed for this claim | `onboarding_status.py` |

**Verdict.** Adopted literally — a new supervisor plus a new capability catalog — it would
duplicate ARBITER. Most of what it calls new already exists. The part that is genuinely
missing is narrower and more interesting: **ARBITER's vocabulary must come from the whole
knowledge graph, not from a sensor list, and records must be joinable to the entities they
describe.** That is the v2 design.

---

## 4. v2 design — generalise ARBITER from *sensed modalities* to *facets of the graph*

One sentence: **the same compile → admit → execute → explain pipeline, over a facet catalogue
the system derives by inspecting its own graph, with a richer set of operations.**

### 4.1 Entity linking at lift time (TTL-first; the load-bearing new piece)

When a register document is lifted into triples (`record_documents.lift_document`), resolve
`locationText` / `onFloor` / `routeFrom` / `routeTo` / `servesArea` to the building's own
space and floor IRIs and emit explicit object properties (`ontosage:locatedIn`,
`ontosage:onFloorEntity`, `ontosage:routeFromSpace`, `ontosage:routeToSpace`). Resolution is
deterministic and building-agnostic: a dotted room id in the text, else an exact label match
against the graph. Ambiguous or unresolved text is **reported, never guessed** (the referent
gate's rule, applied to data). After this, "quiet AND seats ≥ 12" is a graph join.

### 4.2 The facet catalogue — "the system inspects its own TTLs", computed in code

A **facet** is one thing that can be known about one kind of entity:
`(entity type, name, source kind, value type, unit, join path, lay terms, availability)`.

Derived at boot and on graph change, cached, with no building literal in code:

| Source kind | Derived from | Example facets |
|---|---|---|
| sensor modality | `coverage_audit` (exists) | noise, CO2, temperature, illuminance, occupancy |
| record field | `record_classes()` + predicates on instances (`schema_hint` logic) + 4.1's link | seat count, bookable, daylight aspect, AV status, next service due |
| TTL property | datatype properties on space/floor instances | room capacity (with the E6 authority order), area |
| spatial | floors, adjacency, accessible-route register | on floor N, step-free route minutes from X |
| event | booking store (exists as `EventCriterion`) | free for the next N hours |

Each facet carries the proposal's availability ladder, **computed, never guessed**:
*Declared → Linked → Populated → Suitable*. Lay terms come from the TBox (`ontosage:layTerms`,
`rdfs:label`, `rdfs:comment`) and HBCO concepts — the same TTL-first vocabulary v1 uses.

### 4.3 Facet IR — CQ-IR generalised, backward-compatible

- **target**: entity type (`space` in v1; plus `floor`, `asset`, `route`, `period`) and scope.
- **criteria**: `{facet, operator, value, hard|soft, weight, time, source_phrase}`. `facet`
  must be a catalogue key; the operator must fit the facet's value type (a number gets
  `below/above/min/max/near`, an enum gets `equals/in`, a boolean gets `is`, an event gets
  `free_for`). v1's `Constraint` is the special case `facet = sensor modality`.
- **operation** — the decision algebra:
  `select_one | rank | filter | compare(entities) | aggregate(group_by, statistic) then rank |
  period_compare(periods) | relation(series_a, series_b|events, kind) | multi(sub-plans)`.
- **signals**: anything unmapped → clarify, or an honest partial — never a guess.
- **fingerprint** over the behavioural core, as v1.

### 4.4 Compiler — still the only generative step, now with a bounded inspection loop

1. **Retrieve candidate facets** for the question: lexical + concept match over facet lay
   terms → the top ~25 facets with type, unit and two example values. The prompt stays
   bounded however big the building is.
2. **One structured LLM call** emits Facet IR. Code validates every field against the
   catalogue; anything unknown becomes a signal.
3. **Bounded inspection** — the "agentic" part, and the only place the model chooses tools:
   if signals remain, the compiler may call at most two rounds of **read-only, deterministic**
   tools — `facet_search(term)`, `describe_facet(name)` (values actually present),
   `resolve_place(text)` — and recompile once. It never writes SPARQL or SQL.

### 4.5 Admission, execution, explanation

- **Admit per criterion** (extends `capability_schema`): executable / partial coverage / not
  assessable. A hard criterion that cannot be assessed yields an **honest partial answer that
  names it** — never silently dropped, never invented.
- **Execute deterministically**: resolve candidates → each facet's resolver fetches values
  (SPARQL generated from catalogue metadata by code; time series through the existing
  adapters; spatial from the route register and floor plans) → join on entity IRI → an
  **evidence matrix** entity × criterion (value, unit, record id or sensor uuid, timestamp,
  met / unmet / unknown) → apply the operation. Soft criteria use the existing scorer;
  booleans and enums get explicit utilities. Relations (C5) are reported as co-occurrence
  statistics with n and window — **never a causal claim**.
- **Explain**: a deterministic table from the matrix, narrated by the LLM under the existing
  claim binder (every number bound to a cell) and the BUG-787 rule (no causal clause that no
  field carries). Unknown criteria are stated.

### 4.6 Routing — escalate, don't replace

The 88% of questions that are single lookups keep their v1 lanes and the 51-case gate keeps
guarding them. v2 takes a question only when the compiled plan needs **≥ 2 facets from
different source kinds, or a non-lookup operation** — decided after facet retrieval, not by
keywords. First in **shadow mode** (compile + admit + log, v1 still answers), then live per
shape once its acceptance holds.

### 4.7 Invariants (tested, non-negotiable)

No facet outside the catalogue · no LLM-written SPARQL/SQL on the v2 path · read-only · bounded
steps and time · RBAC/privacy enforced inside every resolver · every number bound to an evidence
cell · zero fabricated figures · fingerprint stable across repeats.

---

## 5. Evaluation — pre-registered before any v2 code

**The developer must not see the test set.** The held-out sets are built and frozen by an
isolated agent; v2 is developed only against the development split. This is what makes the
after-number a measurement and not a tuning result (the project's own lesson: tail O was 85%
tuned-on, tail P 65% never-asked).

| Set | Source | Role |
|---|---|---|
| **DEV** (2,477) | 37-role catalogue minus T-CAT and the 210 already asked | development input — its documented role |
| **T-REAL** (27) | real survey corpus, MULTI_STEP + AGGREGATION, never asked, codebook-compound, ≤ 2 per participant | **primary** (with the supplement) |
| **T-REAL-SUPPLEMENT** (22) | the same corpus and screening applied to rows its classifier labelled LOOKUP | **primary** (with T-REAL) |
| **T-CAT** (42) | catalogue items never shown to development, ≤ 2 per persona | secondary |

**Frozen 2026-10-07, before any v2 code** — `eval/compound/MANIFEST.json` holds every file's
SHA256; `build_sets.py` regenerates them byte for byte.

**Why the sets are smaller than first targeted (~80 / ~60).** The builder found the
orchestrator's own answer log (`outputs/query_results/`): 2,249 survey questions and 2,246
catalogue items had already been asked or shown during development. Every one of them is
excluded. A larger set would have meant admitting questions the system has seen; the honest
pool after exclusion and screening was 29 + 22 real compound questions.

**Pre-registered analysis decision (made here, before any v2 commit).** The primary analysis is
on **T-REAL ∪ T-REAL-SUPPLEMENT (n = 49)**. The corpus's complexity label is an automatic
classifier's output and only a prior; the operational definition of "compound" is the written
codebook, which both sets pass. **Sensitivity analysis:** T-REAL alone (n = 27). **Secondary:**
T-CAT (n = 42). **Power, stated in advance:** with about 44 answerable items, an exact McNemar
test reaches p < 0.05 only if v2 gains at least ~6 more acceptable answers than it loses; a
smaller true improvement would be reported as not significant, with its effect size and CI.
Shape C1 is thin in the real sets (5 items) and stronger in T-CAT (13); per-shape results are
reported with their n and without a significance claim.

Each test item carries a pre-computed **answerability label** — FULL / PARTIAL / NONE: are the
facets it needs present in the building's data? This separates *missing data* from *planning
failure*, which is the distinction the claim rests on.

**Capture.** v1 answers are captured now, on the `v1.0-demo` build. v2 answers are captured on
the final build. Same questions, same identity (`facility_manager`), same endpoint (`/v1`),
caches flushed, fresh chat per question.

**Scoring — one blinded hand read of all pairs, at the end.** For each item the two answers are
shown in random order as X and Y; the reader does not know which system wrote which. One reader,
one session, so reader drift cannot masquerade as improvement. Labels:

| Label | Meaning |
|---|---|
| A — full | every criterion addressed with grounded evidence, right operation |
| B — honest partial | answerable criteria addressed, the rest named as not assessable |
| C — correct decline | item is NONE, or the system correctly states the missing data |
| D — false decline / silent partial | answerable but declined, or parts dropped without saying so |
| E — wrong | wrong entity, facet, operation or number |
| F — fabricated | a figure or fact the building's data does not support |

**Primary hypothesis (one):** on answerable items (FULL + PARTIAL) of T-REAL, v2's acceptable
rate (A+B+C) exceeds v1's. Paired exact McNemar test, α = 0.05, with the difference and a
bootstrap 95% CI. **Secondary:** criterion coverage (Wilcoxon signed-rank), T-CAT, per-shape
results, latency p50/p90, plan-fingerprint stability (20 items × 3 asks). **Safety:** F must
stay 0; the 51-case regression gate must stay 51/51 in substance.

### Threats to validity — stated now, not discovered later

- **Earlier offline exposure of the real corpus.** Before this plan, routing changes were
  measured against `docs/smart_building_questions.csv` (4,060 questions), which overlaps the
  survey corpus T-REAL is drawn from. Those scans counted regex matches; no answer was tuned
  on them, and every question ever *asked live* is excluded from T-REAL. From this point,
  `eval/compound/HELDOUT_HASHES.txt` (hashes only) is used to exclude held-out items from any
  offline scan during v2 development.
- **One building.** T-REAL and T-CAT are answered against bldg1. P2's acceptance requires the
  facet catalogue to derive for bldg2 with no code change, but the before/after claim is about
  bldg1; generalisation is argued from the mechanism, not measured.
- **One reader.** A single blinded reader removes drift between v1 and v2 but not the reader's
  own bias; a second reader on a 20% subsample with Cohen's κ is the cheap fix if time allows.
- **Model nondeterminism.** Each item is asked once per version. Plan-fingerprint stability on
  20 items × 3 asks bounds how much of any difference could be run-to-run variance.
- **Test-set construction by the same project.** The sets were built by a separate agent under a
  written codebook before any v2 code; the codebook and the builder script are committed with
  them, so the selection can be audited and re-run.

---

## 6. Versioning on GitHub

- **`v1.0-demo`** — annotated tag on the commit that adds this plan and the frozen test sets
  (code identical to `9fd0831`). The "before" system.
- v1 answers stored under `eval/compound/results/v1/`.
- v2 built on `development` in reviewable commits; **`v2.0-demo`** tagged when its gates pass.
- `eval/compound/BEFORE_AFTER.md` — the comparison, written only after the blinded read.

---

## 7. Phases and acceptance

| Phase | Work | Accepted when |
|---|---|---|
| **P0** | this plan; frozen test sets; `v1.0-demo` tag; v1 answers captured | sets SHA-pinned before any v2 commit; capture complete |
| **P1** | entity linking at lift time (4.1) | every resolvable `locationText` gets an IRI link; unresolved ones listed; zero wrong links on a hand-checked sample |
| **P2** | facet catalogue (4.2) | derives facets for bldg1 **and bldg2** with no code change; statuses match a hand check |
| **P3** | Facet IR + compiler + bounded inspection (4.3–4.4) | v1's ARBITER tests unchanged; DEV C1 items compile to valid IR |
| **P4** | executor: select / rank / filter / compare first; aggregate and period next; relation last | evidence matrix correct on hand-checked DEV items |
| **P5** | explanation + claim binding | no unbound number in DEV answers |
| **P6** | routing: shadow → live per shape | gate 51/51 in substance; no regression on DEV lookups |
| **P7** | capture v2; blinded read; before/after report; `v2.0-demo` | report written from the read, not from a grader |

**What this plan deliberately does not do:** replace the router with an LLM; adopt an external
agent runtime for serving; let the model write queries on the v2 path; claim causes from
correlations; or quote any number that did not come from the blinded read.
