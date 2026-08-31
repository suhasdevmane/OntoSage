# V7 — answering the 37 stakeholder catalogues

**Tracker:** [`docs/V7_TRACKER.csv`](./V7_TRACKER.csv) — 32 tasks, six phases.
**Corpus:** 4,060 questions (1,100 v5 synthetic · 480 supervisor · 2,480 catalogue).
**Regenerate:** `python scripts/build_v7_tracker.py` (preserves status and notes).

---

## The finding that shaped this plan

I expected the 37 catalogues to be a longer question list. They are not. Each of the 2,960
questions arrives with four authored fields — what evidence it needs, whose records are
authoritative, what operation to perform, and what the answer must never do — and those
fields are far more uniform than the questions. Read together they are a **specification
for how a building should answer**, and the questions are its test cases.

Counting the demands across all 2,960:

| the catalogues demand | mentions | OntoSage today |
|---|---:|---|
| the accountable **owner** of a record | 13,964 | ✗ not carried |
| **permission**, purpose-bound | 6,176 | partial — role only |
| **conflict** surfaced, never averaged | 5,437 | ✓ `conflicts[]` + `precedence.py` |
| **coverage** of the evidence | 4,704 | ✓ `completeness`, `spatial_adequacy` |
| **provenance** | 3,451 | ✓ `EvidenceSource` |
| record **version** and lineage | 3,357 | ✗ not carried |
| **clock** alignment | 3,009 | partial |
| **uncertainty** | 2,995 | ✓ |
| **commissioning** / **calibration** state | 2,396 / 2,473 | partial — calibration only |
| **minimum evidence** or stop | 2,512 | ✓ `NOT_ASSESSABLE` is first-class |
| **three times**: effective / observed / retrieved | 660 / 3,048 / 2,882 | ✗ two of three |
| "the May 2021 floor plan is **historical reference only**" | 725 | ✗ plans carry no date |

That table is the real V7 backlog. The good news is unignorable: **V6 already built most
of this.** `EvidenceRecord` carries eleven of the demanded fields, `Operation` has exactly
the seven operation types the catalogues name, `precedence.py` implements the
authoritative-over-measurement rule almost verbatim, and `NOT_ASSESSABLE` is already a
first-class success rather than an error. V7 is not a rewrite. It completes a grammar that
is three-quarters written.

---

## What the questions need, and what bldg1 holds

### Demand — measured, not guessed

The catalogues **name their own authoritative systems** ("Primary authority: the current
CAFM or EAM asset register"). `scripts/analyse_catalogue_demand.py` reads those
declarations rather than inferring intent from question wording — a distinction that
matters, because a keyword read of *"which room did the marketing team use"* lands on
"team" and files it as a people question when it is booking history.

27 source systems, led by: sensor telemetry (2,357 questions, 80%), space inventory (801),
IT/network (693), booking (672), policy (570), accessibility (566), access control (502),
asset register (488), permits (479), contracts (413).

### Supply — probed live, on all four stores

`scripts/source_system_readiness.py` asks the running building, three-valued:

* **DATA** — queryable triples or rows a lane can compute over
* **PROSE** — only a document says it; quotable, not calculable
* **ABSENT** — nothing holds it

bldg1, measured 2026-08-31: **17 DATA · 2 PROSE · 8 ABSENT**.

> A first version of that probe read GraphDB and documents only, and reported ABSENT for
> two systems bldg1 plainly holds — 199 user reports live in Postgres, and weather and
> timetable arrive as configured feeds. A readiness report that misses a whole store does
> not merely understate: it would have put "onboard this source" tasks in this plan for
> data already connected. It now probes graph, Postgres, feeds and documents.

### The gap

Taking each question's **worst-readiness** system as its ceiling:

| ceiling | questions | share |
|---|---:|---:|
| **DATA** — every system it needs is queryable | 1,069 | 36.1% |
| **PROSE** — capped by a document-only system | 703 | 23.8% |
| **ABSENT** — capped by a system nothing holds | 1,097 | 37.1% |
| names no system | 91 | 3.1% |

And the systems doing the capping:

| blocking system | questions | state |
|---|---:|---|
| booking | 543 | PROSE |
| contract_warranty | 413 | ABSENT |
| project_handover | 257 | ABSENT |
| permit_control | 160 | PROSE |
| finance_cost | 119 | ABSENT |
| hr_identity | 103 | ABSENT |
| survey_condition | 99 | ABSENT |
| training_competency | 79 | ABSENT |
| sustainability · risk_insurance | 27 | ABSENT |

**This is a ceiling, not a score.** It is an upper bound on what data alone can fix and a
lower bound on capability: a question whose systems are all DATA can still fail on
routing, on the referent, or on a timeout. Which is why the plan is measured against a
live replay and not against this table.

### Who is unserved

Aggregate coverage hides the thing that matters. Per role, share of the 80 questions not
fully backed by DATA:

| role | blocked | why |
|---|---:|---|
| Architects and building designers | 100% | handover, survey, contracts |
| External maintenance contractors | 100% | permits, contracts, competency |
| Waste-management teams | 100% | contracts, service records |
| BMS-HVAC operators | 100% | mostly PROSE, not ABSENT |
| Space-planning teams | 91% | tenure, survey |
| Finance and procurement | 90% | tariffs, contracts |
| Prospective students and family | 86% | **almost entirely PROSE** |

Architects and Prospective students are both ~100%/86% blocked and need completely
different work — one needs source systems that do not exist, the other needs documents it
already has turned into data. A single coverage number would rank the wrong work first.

---

## The two design decisions

### 1. A document must become data — the Record Document standard (V7-T18)

You asked for *"standards to use these docs automatically"*. This is that standard, and it
is the highest-leverage task in the plan: it lifts the 703-question PROSE ceiling and it is
what makes bldg1's existing permit register and booking log answerable.

Today `document_indexer` chunks documents into Qdrant and the capability lane retrieves
passages. That gives PROSE: *"the legionella assessment is dated 12 March"* answers a
question about the record. It cannot answer *"which outlets are overdue"*, because you
cannot aggregate over prose. Contract 2 settles the direction — a fact that can be a triple
belongs in the ontology — so the document must **become** triples, not remain a thing to
search.

The standard: a Markdown document carrying YAML front-matter that declares
`record_type`, `owner`, `authority`, `effective_from`, `version`, `review_due`,
`source_system`, `simulated` — plus body tables whose columns are declared. At ingest the
indexer keeps doing what it does *and* lifts front-matter and tables into RDF through a
**mapping shipped with the ontology, one per `record_type`**. A second building drops a
document of the same shape and gets the same triples with no code change. That is
contract 8 applied to documents.

Three guards, because lifting is where fabrication would enter:

* SHACL-validate before insert; a document that does not conform is indexed as prose and
  reported, never partially lifted.
* One named graph per document, so re-ingest replaces cleanly rather than accumulating —
  the blank-node duplication of CAVEAT-039 is exactly this failure.
* Lifted facts carry `derivedFromDocument` and sit **below** authored TTL in precedence
  (V7-T19). A document is a statement *about* a system of record, not the record. Without
  that tier a stale Markdown table silently outranks a live register, which is precisely
  what BUG-194 was.

**Rejected:** extracting facts from free prose with the LLM at query time — the
fabrication path this project guards against hardest, and it re-extracts on every
question. Requiring a hand-authored companion TTL per document — double authoring, and it
drifts. Simply making the retrieval lane "answer better" — it still cannot aggregate.

### 2. Answerability decided before routing, not guessed (V7-T21)

You asked what replaces the keyword guesses. This does.

Today 180 measured declines all route to the `capability` catch-all and all return the
same sentence, so 180 distinct gaps look like one problem and the reader learns nothing.
Adding routing rules does not fix that — there are already 17 ordered rules, and each new
one trades one wrong lane for another without ever saying what is missing.

The replacement rests on a fact that is **decidable rather than guessable**: whether this
building holds a given system of record. `source_system_readiness.py` measures it live. So
before a lane is chosen, resolve the referent, resolve which systems the question requires
(through the concept resolver and the ontology, not keywords), check their readiness, and
then either route to a lane that can succeed or decline naming the missing system and the
step that would supply it:

> *"This building has no permit register as data. It holds one as a document, so I can
> quote it but not count open permits by zone. Lifting it under the Record Document
> standard would make this answerable."*

That is triageable by the person reading it, and it is different for each missing system —
which is what V6-T70 was reaching for and could not express while a decline knew only that
a fact was absent.

**Rejected:** classifying questions with the LLM alone — it would name a source system the
building may not hold and produce a confident wrong route.

The catalogues also hand us a supervised signal for the routing itself. Every question
declares its operation, and the counts across all 2,960 are: comparison (1,486), lookup
(1,215), observation (1,153), recommendation (1,098), calculation (846), estimate (832),
forecast (714), diagnosis (577). That is **2,960 labelled examples** — a test set, not a
heuristic (V7-T22).

**And the most demanded operation is missing from the enum.** `Operation` has seven
members — observation, authoritative_lookup, calculation, estimate, forecast, diagnosis,
recommendation — and its docstring says they were derived from "all six catalogues". Six,
of thirty-seven. The 31 that were never read make **comparison** the single most frequent
operation in the corpus, ahead of lookup, and it has no member. It survives only as
`comparison_baseline`, an *attribute* of a record rather than an act the system performs,
so a comparison question is currently labelled as whatever it was computed with. The
catalogues treat it as its own operation with its own boundary — *compare like versions
and like periods* — which is a real constraint that nothing checks today.

---

## What probing the live building turned up

The readiness table is a prediction. Probing bldg1 to check it found three things the
analysis could not have.

**A live cross-role privacy leak (BUG-368, fixed).** An occupant asked for a room-level
temperature and was correctly refused above the k-anonymity floor. A facility manager then
asked the same words and was served the occupant's *refusal*. With the order reversed, the
occupant received the facility manager's room-level reading verbatim — the exact figure the
PDP had denied them minutes earlier. `resp_cache` keyed on building and question hash and
nothing else, so the first requester's privilege became everyone's until the TTL expired.
The PDP was right the whole time; it was skipped, because the cache answered first.

**No test could have caught it, and that is the more important half.** Every PROTECT trap
runs as a *single user*, so nothing in the suite ever put two roles behind one question —
and a certified "0.0% leak" was measured straight through that blind spot. A privacy
property is a statement about the *difference* between what two people see, and a one-user
harness cannot observe a difference. V7-T44 makes every trap run as two roles in both
orders.

**A refusal whose own remedy times out.** The k-floor refusal helpfully suggests *"ask the
floor average instead of one room"*. The floor average then exceeds the 150 s budget. A
refusal that hands the user an impossible remedy costs them a second wait to learn the same
nothing, and makes a correct privacy decision look like a broken system (V7-T39).

**And my own mid-run rebuild invalidated the first probe.** Deploying the cache fix while
111 questions were replaying produced 27 transport errors and 32 no-response rows. The
harness quarantined them, as it was built to after CAVEAT-173 — the run was discarded and
re-run on a stable stack rather than reported. Kept as
`scripts/outputs/replay/v7probe_INVALID_container_restart.csv` so the discard is auditable.

---

## The phases

| phase | tasks | what |
|---|---:|---|
| **P0-Carryover** | 4 | Every open V6 item, plus the stale-fixture defect found while probing |
| **P1-EvidenceGrammar** | 8 | The third time, owner, verification state, commissioning gate, staleness, purpose, version, the dated floor plan |
| **P2-DocumentStandard** | 3 | The standard, its precedence tier, and a document lane that answers |
| **P3-Answerability** | 4 | The precheck, the operation check, the spatial errors, the timeouts |
| **P4-SourceOnboarding** | 9 | The nine missing systems, ordered by blocked questions |
| **P5-Measurement** | 4 | Regression floor, 4,060-question baseline, per-role scorecard, bldg2 proof |

Ordering: P0 first because two of its items are the *measurement apparatus* and this
project has twice published fictitious numbers from a broken one. P1 before P4, because
authoring a contract register before `effective_at` exists means re-authoring it. P2
before most of P4, because six of the nine onboarding tasks are Record Documents and the
standard is their delivery mechanism. P5 runs continuously, not at the end.

---

## Decisions carried into the tracker

**Never a hardcoded tariff (V7-T34).** Cost questions decline today, correctly. An
invented unit rate produces a confident wrong number — the exact failure this project
guards against hardest. Either a tariff is registered, with rate, window and authority, or
the question declines naming it.

**Identity modelled at role level only (V7-T35).** The catalogues ask about entitlements
and prerequisites *and* forbid exposing person or credential records beyond an authorised
case. The answerable form is "this role requires these prerequisites", never "this person
holds this credential". Importing a person directory would build the disclosure surface
the catalogues prohibit, for questions that do not need it.

**Verification state is a new axis, not a seventh `AnswerStatus`.** Status says what kind
of claim this is; state says how well the evidence supports it. A CALCULATED answer can be
verified or conflicted. `AnswerStatus`'s own docstring says exactly six members, and
merging two axes reopens the ambiguity it exists to close.

**The floor plan's date belongs in the manifest, not in code.** "May 2021" is a bldg1
literal. `survey_date` and `authority` travel with each building's plans.

**Extend the OntoSage schema where Brick genuinely stops.** Condition grade, remaining
life, U-values and warranty terms have no Brick vocabulary — that is the clearest case in
the corpus for extending `ontosage:` rather than forcing Brick to carry it. Bookings,
permits and equipment stay on the classes that already exist.

**`questions_unblocked` counts overlap and must not be summed.** A question blocked by
both contracts and handover appears in both rows.

---

## What I need from you

1. **CAVEAT-362 — the leak grader counts numbers.** A correctly-restricted aggregate still
   grades LEAK. I deliberately did not change the grader in my own favour; it needs your
   call on the semantics before any V7 privacy number is trustworthy.
2. **Scenario and what-if questions (V6-T80, still open).** You said you wanted to discuss
   these separately. My recommendation stands: decline them, naming what a real answer
   would require, because a confident freezer-safety estimate with no thermal model behind
   it is the most dangerous answer this system could produce.
3. **Synthetic records for bldg1.** The compliance pack is done and banner-labelled. P4
   proposes the same for contracts, handover, condition survey, tariffs and competency —
   all synthetic, all labelled. Confirm that is the intent for a real building, or name
   which of them must be real or explicitly "not held".

---

*Written 2026-08-31 from `docs/V7_question_demand.csv`, `docs/V7_demand_by_source_system.csv`
and a live readiness probe of bldg1. Every figure is reproducible with the scripts named
above.*
