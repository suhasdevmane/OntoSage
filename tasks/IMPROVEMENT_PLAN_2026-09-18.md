# OntoSage improvement plan — from "it answers" to "it is right, and it transfers"

**Written 18 September 2026**, from an audit of the code (9 agents, 651 tool calls), five competing
architectures, three judges, four adversarial critics, and a set of measurements taken on the
running system today. Every number below has a source. Where a number in an earlier document was
wrong, the correction is stated, not quietly replaced.

---

## 0 · The finding that reframes the work

Six development waves were measured on one fixed bank of 147 stakeholder questions, hand-read six
times. The project reported the "weird share" falling 72.8% → 65.3%. Decomposed, on the same labels:

| run 1 → run 6 | gained | lost | p (exact paired) |
|---|---:|---:|---:|
| Correct **answers** | 9 | 11 | 0.82 |
| Correct **declines** | 21 | 8 | **0.024** |
| Either (the reported "weird share") | 28 | 17 | 0.135 |

Per run, out of 147:

| | run 1 | run 2 | run 3 | run 4 | run 5 | run 6 |
|---|---:|---:|---:|---:|---:|---:|
| Correct answer | 19 | 10 | 14 | 16 | 19 | **17** |
| Correct decline | 21 | 24 | 37 | 36 | 38 | **34** |
| Weird | 107 | 113 | 96 | 95 | 90 | **96** |

**Six waves of work significantly improved how often the system correctly refuses, and did not
improve how often it correctly answers.** The collapsed metric could not show this, because refusing
more improves it. High-confidence weird answers are flat across the whole series (60, 68, 65, 60,
55, 59), and the headline fall is carried by low-confidence labels (14, 7, 1, 2, 1, 1).

The honest headline for a viva is therefore: **the system correctly answers 17 of 147 questions on
its own development bank (11.6%)**, and declines correctly on 34 more.

Three of the five proposed architectures would have made this worse, because their central mechanism
— an admission gate, typed declines, withholding unbound claims — produces *more declines*. A plan
that optimises the collapsed metric optimises refusal. This plan therefore splits the outcome into
two co-primary measures so that a seventh wave cannot repeat the sixth.

### 0.1 · And the correction the owner made to the first draft

> *"I DO NOT WANT TO ADD MORE DECLINES AS WE NEED TO ADD MORE DATA TO MAKE IT ANSWERABLE."*

The first draft of this plan diagnosed the problem correctly and then scheduled the wrong work: it
put twelve measurement packages ahead of three that could raise answering. Splitting the metric stops
a seventh wave from *claiming* progress it did not make; it does not by itself make the system answer
one more question.

Half of that steer is confirmed and half is corrected by the count in §3: **55 of the 96 weird
answers are about data the building already holds** — refused, denied, or computed correctly and then
contradicted. Those 55 do not need one new triple. The other 41 do, and Stage 3 is where they are
addressed — after Stage 1, because loading data into lanes that demonstrably do not read what is
already loaded changes nothing.

---

## 1 · What the audit measured

**Of 96 audited mechanisms, 22 are derived from the building's own data. 39 are handwritten and 35
are mixed.** For a system whose claim is *connect a building's data, then ask it anything*, that
ratio is the thesis problem stated as a number.

Concretely, and each verified:

- **Routing** is decided at four sites and recorded at none. 41 of 43 contract rules are lexical
  tests over the raw string; zero consult the graph. Every matching rule fires and the last wins,
  though the module says earlier rules win. `intent_definitions.yaml` carries no data requirement,
  so nothing ever asks whether the chosen lane can answer with *this* building's data.
- **Vocabulary lives in code**: 65 Brick class names (216 occurrences), 102 OCBV terms and 138
  `ref:*` uses across `orchestrator/` and `shared/`. The portability guard cannot see any of it,
  because none of it is a *building* literal. Five separate quantity tables exist (sizes 5, 8, 13,
  15, 45).
- **Ingestion validates nothing**: the only hard gates are "it parses" and "one prefix string
  matches". SHACL is shipped, documented and never executed — `pyshacl` is not a dependency and the
  validator returns "no violations" on ImportError, indistinguishable from a pass.
- **Retrieval returns schema, not data**: of 50 triples handed to the model on a live instance
  question, 50 subjects were Brick classes and 0 were building instances. Context is truncated
  positionally; there is no reranker anywhere; 69.5% of document chunks are truncated before
  embedding while the untruncated text is stored and shown.
- **Guards observe rather than enforce**: two unconstrained model rewrites run *after* every
  deterministic guard; 8 of 9 evidence gates are advisory; 13 of 23 lanes record evidence the claim
  binder cannot read; `grounded` means "a lane returned rows".
- **Units are order-dependent**: `unit_for_sensor('brick:Water_Flow_Sensor')` returns `L` — a volume
  for a flow rate — while the ontology declares `L/min`. 1,046 of 3,507 points match two or more
  modalities with conflicting units, decided by SPARQL result order.
- **The instruments overlap and self-calibrate**: all 60 probe questions are inside the 125-question
  guard set, so the "two independent gates" are one instrument. The grader's κ = 0.419 is a
  resubstitution estimate — its rules were written from the labels it is scored against — and the
  first reader could see the machine's verdict on all 147 rows.
- **No building but bldg1 has ever been asked a question.** bldg1 has 63–65 TTLs, bldg2 has 25,
  bldg3 has 20, bldg4 has 5. Unit-catalogue fit: bldg1 98.9%, bldg3 75.8%, bldg2 52.5%.

### Corrections to earlier documents

1. **Structured generation is not incompatible with this model.** Schema-constrained output returns
   valid JSON on `/api/chat` and zero characters on `/api/generate` — the endpoint the client uses
   and the only one previously tested. `think:false` is what breaks it. CAVEAT-786 is withdrawn.
2. **The headline improvement is not significant** (p = 0.135); only run 1 → run 5 was (p = 0.009).
3. **The claim-binding headline is 52/703 unbound (7.4%) over the 71 answers with complete
   evidence** — not 58/709 over 441. The excluded partition runs 55.7% unbound; 55 answers record
   no evidence at all. Over the whole corpus the rate is 19.2%.

---

## 2 · The claims this plan is built to support

| # | Claim | Status today | What will support it |
|---|---|---|---|
| 1 | Six waves improved refusal, not answering — and the project's own metric could not see it | **measured, unpublished** | W03's pre-registered decomposition |
| 2 | The system correctly answers 17 of 147 questions on its development bank | **computed, never stated** | W03, with Wilson intervals and n |
| 3 | No gate in this project has ever had a null distribution | **true, unmeasured** | W02's control arm |
| 4 | "Any TTL" is falsifiable *inside* Brick, and nobody has run the test | **not run** | W13, six serialisations of one manifest |
| 5 | A building whose readings live in the graph is not an absent building | **every lane refuses it** | W11's INAPPLICABLE verdict, W13 arms 3–5 |
| 6 | A unit that disagrees dimensionally with its own quantity is live and one line to reproduce | **live defect** | W09 |
| 7 | Every routing decision is recorded nowhere, and one field changes that | **true** | W04 |

---

## 3 · The twenty-four work packages

**Re-ordered 18 September, after the owner's challenge**, which was correct: the first draft put
twelve measurement packages ahead of three that could raise answering. Measurement stays — two of
six previous waves passed their own tests and made the bank worse, and without a hand read nobody
would have known — but it is the **gate**, not the **goal**. Stage 1 is now the work that converts
weird answers into correct ones, and it is sized from a counted pool rather than from a hunch.

### The pool Stage 1 is aimed at

Of the 96 weird answers in the frozen run, **55 are about data this building already holds.**
Counted from `docs/phase0/phase0_run6_read.jsonl`:

| cause, as hand-labelled | answers | what is actually wrong |
|---|---:|---|
| FALSE_ABSENCE | 38 | says "no record of X" while a register row or graph triple holds X |
| WRONG_REGISTER | 9 | reads a register that cannot contain the answer, then reports absence |
| UNGROUNDED | 11 | states a conclusion no field value carries |
| INCOMPLETE | 11 | answers one part of a multi-part question and stops |
| WRONG_LANE_OTHER | 3 | correct data, wrong lane asked for it |
| **Recoverable union (defect classes C7 + false-absence family)** | **55 → 60, corrected 18 Sep** | 5 more (`FM-040`, `Q358`, `Q972`, `TT-070`, `WM-047`) use false-absence phrasing the original keyword split missed |
| Residue: genuinely absent data, out-of-scope, or needs new ingestion | 41 → 37 | Stage 3 and the data work |

**W19 SHIPPED 18 September** (BUG-792) — see
[`docs/PROGRESS_2026-09-18_W19_STAGE1.md`](../docs/PROGRESS_2026-09-18_W19_STAGE1.md) for the
full account. 6 new unit tests + 118 existing register-lane tests pass; **live re-ask as
facility01, complete: 39 questions from the false-absence pool asked, the guard fired 11 times,
every firing checked correct against the actual rows — zero false positives.** On inspection
about half those 11 are *useful* (change whether the question is answerable) and half are
*low-value* (a real but coincidental word match, e.g. "talk" matching an activity record's own
label) — the guard is precise, not always informative. It catches only a same-paragraph denial
(a deliberate scope limit — see the doc for what it does not catch and why); the true conversion
rate against the 60-pool needs a fresh hand read (Stage 2's `W03`/`W06`), not a re-use of stale
run-6 percentages or a raw firing count. One question in the batch timed out at 150s (a
large-occupancy-scan question) — unrelated to W19, logged separately.

Two structural findings explain most of the pool, and both are measured, not inferred:

* **Absence is currently inferred from a missing *word*, not proved by a *read*.** The internal
  keyword census decides that a topic is unrecorded when no field name matches, so a register that
  holds the answer under a different field name is reported as silent. This is the cause on 38 rows,
  and it is the same mechanism that leaked census wording to readers on 23 answers in run 5.
* **Retrieval returns the ontology, not the building.** On a live instance question, retrieval
  returned **50 of 50 Brick-class subjects and 0 building instances**. A lane that asks "which rooms"
  and receives the definition of `brick:Room` has no path to a correct answer.

**Target: convert 30–45 of the 55.** That moves correct answers from **17/147 (12%)** to
**≈ 45–60/147 (31–41%)**. Stated as a range because the conversion rate is unmeasured; the floor of
the range is what Stage 1 must clear to be worth its days.

---

### Stage 1 — answer what is already loaded (days 1–7) · the only stage that targets GOOD_ANSWER

| id | title | pool | acceptance |
|---|---|---:|---|
| **W19** | **Absence must be proved by a read, not inferred from a missing word.** No lane may emit "no record of X" unless it can name the query it ran and the row count it got back. A field-name miss is not evidence. | 38 | 0 answers asserting absence with no recorded read; on the 38, DECLINED-WRONGLY falls to ≤ 8; probe within its measured distribution |
| **W20** | **Choose the register by what it contains, not by what it is called.** Rank candidate registers by field-level match against the question's referents, not by name or vocabulary overlap. | 9 | correct register on ≥ 8 of 9; published confusion matrix over all registers |
| **W21** | **Retrieval returns building instances, not Brick classes.** Instance-first ranking with the class tier as fallback, measured on a fixed instance-question set. | ~15 of the 38 | instance share ≥ 80% (it is **0%** today on the measured question); before/after published on the same questions |
| **W22** | **A causal clause must be carried by a printed field value** (BUG-787). The reader named this as the highest-leverage unattempted fix. | 13 of 27 C7 | those 13 re-read clean; 6 of run 6's 11 regressions recovered |
| **W23** | **Typed composition for the register lane.** The lane computes a correct structure and then a free-text narration contradicts it; emit the fields and render deterministically. | 14 of 27 C7 | 0 answers whose narration disagrees with its own printed fields |
| **W24** | **A multi-part question is covered or explicitly partial.** | 11 | every multi-part question either covers each part or names the parts it did not cover |
| **W15** | **Evidence emitters for the 55 answers that record nothing.** Promoted from below the cut line: it is the prerequisite for W19's proof-of-read and for switching claim binding on. | 11 UNGROUNDED | unassessable answers fall 55 → ≤ 10; frozen-denominator rate published beside the whole-corpus rate so the number cannot improve by shrinking its denominator |
| **W10** | A deterministic guarantee that survives to the reader | — | reversion rate published per rewrite; 0 surviving rewrites whose claim set is not a subset of the pre-rewrite bound set |

**Gate — and this is the whole point of the re-ordering:** a hand read of the same 147 questions
after Stage 1 must show **GOOD_ANSWER up by more than the noise floor**. Correct declines may rise
or fall; they are not the target and will not be quoted as progress. If GOOD_ANSWER has not moved
past the floor, Stage 1 has failed and no later stage redeems it.

### Stage 2 — the instruments that gate Stage 1 (days 1–7, in parallel)

Cut from eight packages to four. These run *alongside* Stage 1 because Stage 1's gate needs them,
not ahead of it.

| id | title | acceptance |
|---|---|---|
| **W02** | **The control arm** — ask the same bank twice on one frozen build | `docs/NOISE_FLOOR_<date>.md` publishes the verdict-flip rate between two identical runs with a bootstrap CI, and the probe's first-pass distribution over ≥ 3 repeats. **Day 2, because Stage 1's gate is meaningless without it** — between run 1 and run 6 only 4 of 147 answers were byte-identical |
| **W03** | Decompose the outcome and pre-register the analysis | reproduces, offline, GOOD_ANSWER ~ run p = 0.82 and GOOD_DECLINE ~ run p = 0.024; a test asserts it makes no network call |
| **W04** | Record the lane and the rules for every answer | 147/147 replayed rows carry a final lane equal to `ontosage_intent`, and rules fired for exactly the turns whose contract run was non-empty. **Kept because W19/W20 cannot be diagnosed without it** |
| **W06** | Blinded re-read and out-of-sample grader | frozen codebook pinned by SHA; blind-vs-sighted intra-rater κ, out-of-sample grader κ, and the drift estimate, each with a CI |
| **W01** | Freeze point and the three landmines | Redis below 60% of `maxmemory` with `conversation:*` bounded (**99.77% of 2 GB** today under `allkeys-lru`); no second compose project on the host; owner-approved checkpoint SHA with buildings parked |

#### Stage 2 — status, 18 September evening

| package | state | evidence |
|---|---|---|
| **W01** | Redis **done**; second compose project **measured, no conflict**; checkpoint SHA **not done** (needs the owner's approval to commit) | Redis 2.135 GB → 5.7 MB of a 2 GB cap; `scripts/redis_hygiene.py --check`; `ask_questions.py` now flushes both caches once per run and purges only the conversations it created. The `kg` stack uses different ports and ~2 GB of 46 GB. |
| **W02** | **Done on the held-out set (38 questions), NOT on the 147-question bank** | same build, asked twice: **4 of 38 verdicts changed (10.5%, 95% CI 2.6–21.1%)**; weird share 55.3% → 50.0%, p = 0.63; **18 of 21 weird answers weird both times** (`docs/phase0/fresh_tail_B_run{1,2}_read.jsonl`). The bank-level pair costs ~3 h of GPU and ~200 hand reads and is still owed. |
| **W03** | **Done** | `scripts/decompose_outcomes.py`; reproduces p = 0.824 / 0.024 exactly; 5 tests, one proving it imports nothing that can reach a network. |
| **W04** | **Done, live-verified** | `ontosage_route` on every `/v1` turn; 42/42 and 44/44 replayed rows carried both fields. |
| **W06** | **Partly done** | codebook frozen and SHA-pinned. Out-of-sample grader agreement with the hand labels: **κ = 0.31, weird-precision 44%** on 86 untuned rows, against κ = 0.42 / 95% on the 294 it was tuned on. **The automatic grader is not a substitute for a hand read.** An independent blind read is **not possible from here** and is not claimed. |

**The unscripted rate, measured.** Held-out tail B, final build: **21 of 38 weird (55%), 13 high-confidence**;
repeated: 19 of 38. The 14 rewordings written after tail A failed: **11 weird**. So a rewording does not reliably
rescue a failed question, and the workarounds recorded on BUG-808..811 were corrected.

**What Stage 2 changed about the plan.** Its own gate ("GOOD_ANSWER up past the noise floor") was
never the right first instrument. The 147-question bank is a *stakeholder-catalogue* set the system
was tuned against for six waves; asking it 42 and then 40 **unscripted** questions in a supervisor's
register found nine root causes in two hours, none of which the bank, the 60-case probe or the
44-question demo script could see. **A held-out, unscripted tail is now a standing instrument**
(`docs/phase0/fresh_tail_*`, `CODEBOOK.md`), and any further wave should be judged on it as well as on
the bank.

**And what it changed about Stage 1.** The plan's diagnosis — "55 answers concern data already held"
— was right, and the cause it named (absence inferred from a missing word) is real. But the fixes that
moved natural questions were **not** in W19–W24: they were a prompt that overflowed its context, a
total computed from the wrong operation, a store column read under one name only, a modality repair
that bailed on a name, and a document index that never forgot a deleted file. All were found by asking
questions a person would ask. W20 (register selection) and W23 (typed composition) are untouched.

### Remaining, in order (after 18 September)

1. **Owed to the plan's own gate:** the 147-question bank on the final build, hand-read, with the
   decomposition (`scripts/decompose_outcomes.py`) run against run 6; then the bank-level control arm.
2. **The open defects from the unscripted tail** (`BUG-808`…`BUG-815`, `BUG-825`…`BUG-832`,
   `CAVEAT-816/817/833/834` in `tasks/FIX_TRACKER.csv`), **in this order of yield:** (a) *held but
   unreached* (C9): room/occupancy questions answered "the building model only records sensor counts"
   (BUG-825), a forecast that works on one run and refuses on the next (BUG-826), heat-pump and atrium
   referents (BUG-831); a room-bound repair must bind to the room asked, never the building; (b) lane
   and window: "this week", "this afternoon", "when" (BUG-828), amenities that ignore the floor
   (BUG-827); (c) maintenance/asset-history (**still the largest source of weird answers**, W20/W23);
   (d) whole-building exceedance needs a SQL aggregate lane (BUG-808); (e) generic advice and uncited
   norms appended to numbers (BUG-832); (f) an invented compliance conclusion (BUG-829).
3. **W20, W22, W23, W24, W15, W10** (Stage 1's unbuilt packages), now with a held-out tail to judge them.
4. **Stage 3, revised.** Adding data is *not* the main lever: of the questions read this session,
   the data was almost always already held. What remains genuinely missing is small and listed in
   `READINESS_2026-09-18_STAGE2.md` §5. **Replace the placeholders before deployment** — one query lists
   them (`ontosage:isSimulated true`: 4,762 records, 52 classes).
5. **Decisions that are the owner's:** Redis production policy (`CAVEAT-801`); commit and push (needs the
   buildings parked, Workflow rule 8); a second annotator.

### Stage 3 — add the data that is genuinely missing (days 7–11) · the owner's instinct, in its right place

The residue of 41 weird answers is not a reach problem. This stage is deliberately **after** Stage 1,
because loading data into lanes that have just been shown not to read what is already loaded buys
nothing — the same questions fail the same way on more triples.

| id | title | acceptance |
|---|---|---|
| **W25** | **Close the gaps the conformance report already names.** Two declared quantities resolve to no points; 34% of floor-plan spaces (119) carry no graph IRI. | conformance moves from 7 pass / 4 limited to ≥ 10 pass / ≤ 1 limited; each closure re-asked on the bank |
| **W26** | **Reach the registers the building holds and no lane asks.** Calibration dates on 1,929 sensors, AV readiness, cleaning tasks, permits, drinking water, projectors — held, unreachable (audit finding C9). | each named register answers ≥ 1 bank question it currently cannot; counted, not asserted |
| **W09** | One quantity authority with a dimensional check | 0 (class, unit) pairs whose dimension disagrees with the declared quantity kind, across bldg1–4, with catalogue-fit published **first** so correctness cannot be bought by covering fewer classes |

**Gate:** every addition is re-asked on the bank. A triple that changes no answer is recorded as
such rather than counted as progress.

### Stage 4 — make "any TTL" a measured property (days 11–15)

| id | title | acceptance |
|---|---|---|
| **W11** | Bind vocabulary roles by counting, with a fourth verdict | every tier-0/1 role bound on bldg1 with the flag on; a report prints role → chosen term → count → how chosen → all candidate counts, for bldg1–4 and every W13 arm |
| **W12** | The answerability report an adopter reads | generated for bldg1–4; on bldg1 its UNSUPPORTED list must include the classes the probe already declines — if it claims more than the system does, the report is wrong |
| **W13** | **One manifest, six serialisations** | published 6-arm table. Pre-registered one-sided primary: ANSWERED-WRONGLY = 0. Arm 2 is *standard* Brick 1.4 and runs first, with the prediction registered in advance that it fails on `ref:storedAt` |
| **W14** | Live bldg2 — the first quality number for another building | published table for bldg1 and bldg2: conformance verdicts, generated-question counts, and GOOD_ANSWER / GOOD_DECLINE / DECLINED-WRONGLY rates with n |
| **W08** | Make the offline conformance report read the TTLs | `--offline --input-dir bldg2` runs ≥ 20 checks (**2** today) and generates ≥ 100 questions (**0** today) in ≤ 5 minutes with no service running |

**Gate:** arm 2's result is published *whatever it says*, with its prediction visible beforehand.

### Stage 5 — below the cut line (only if the calendar holds)

**W05** make the two gates two gates (probe ∩ guard = **60/60** today — they are one instrument) ·
**W07** contamination scan that reads `docs/` · **W16** split the context budget only if the
measurement says so · **W17** make each lane declare the data it needs.

*The drop order is committed in advance, so that when the calendar slips the victims are chosen by
this document rather than by whatever is half-finished.* W05 and W07 moved down from Stage B in the
first draft: they protect the *credibility* of a number, and the number has to move first.

### Stage 6 — pack it (1.5 days, never cut)

**W18** the viva pack: one revision, one command, every offline number reproducible from a fresh
clone in under 15 minutes with no network, and a supported-scope document with no hand-maintained
capability claim in it.

---

### What the re-ordering cost and what it bought

| | first draft | now |
|---|---:|---:|
| Packages whose mechanism can raise GOOD_ANSWER | 3 | **10** (W19–W26, W10, W15) |
| Packages that only produce numbers | 12 | 5 |
| Stage whose gate is "GOOD_ANSWER up past the floor" | none | Stage 1 |
| Packages dropped or demoted | — | W05, W07 to Stage 5 |

**The risk this re-ordering takes on, stated plainly:** Stage 2's instruments now run *beside* the
behaviour change rather than before it, so Stage 1's first gate leans on a noise floor measured in
the same week it is used. If W02 reports a wide floor, Stage 1's result may be unreadable and the
gate becomes "no regression" rather than "measurable gain" — which is exactly the weaker claim this
project has been making for six waves. W02 therefore still runs on day 2, not day 7.


## 4 · The evaluation protocol

**Co-primary outcomes, never reported alone:**
1. **GOOD_ANSWER rate on questions whose conformance class is SUPPORTED** — here a decline is a
   *failure*. Baseline 17/147 overall.
2. **GOOD_DECLINE rate on NOT-SUPPORTED classes.** Baseline 34/147.

Two new outcome classes the old scheme could not express: **DECLINED-WRONGLY** (refused when the
data was in the delivered input — the predicted modal failure for SAREF, SOSA and REC arms) and
**ANSWERED-WRONGLY** (a plausible wrong answer — the one-sided primary for the vocabulary arms,
which must be 0).

**Sets:** control arm (the same bank twice on one build) · dev bank 147 (open, never used to claim
an improvement without the floor) · probe 60 (per-change gate, disjoint from the guard set after
W05) · guard residual 43 (reported for a human, never an auto-fail) · **sealed set 116, opened once,
after the contamination scan** · per-building generated sets · the six-serialisation set · bldg2
live set with its own noise floor.

**Statistics:** GEE (binomial, logit, clustered on question, exchangeable, robust SEs) with run as a
categorical factor and a joint Wald test, on the decomposition rather than the collapsed share; all
15 pairwise McNemar tests reported together, Holm-adjusted; Wilson intervals on every rate; power
stated (n = 147 gives power ≈ 0.32 at the observed discordance — so "no change" claims are bounded,
not asserted).

**Human protocol:** one frozen codebook, SHA-pinned by a test; de-identified shuffled packets built
by script with run labels and all prior verdicts stripped — because the first reader could see the
machine's verdict on 147/147 rows and the sixth could see all five predecessors.

---

## 5 · Technology decisions, and what was rejected

| Decision | Chosen | Rejected | Because |
|---|---|---|---|
| Constrained generation | `ChatOllama` → `/api/chat` with a JSON schema in `format`, thinking left on | the current `/api/generate` path; `think:false`; vLLM/TGI; a different model | Verified today: schema on `/api/chat` returns valid JSON, on `/api/generate` returns nothing, and `think:false` breaks it |
| Quantity authority | `measurand_kinds.ttl` extended with a QUDT quantity kind and dimension, reached via `brick:hasQuantity` where available | QUDT alone; keeping the YAML as master; a sixth table; `pint` | The defect is one line — a flow rate reported in litres — and the ontology already declares the right unit with a `bandSource` provenance field |
| TTL validation | `pyshacl` in **dev** requirements, run from the host, with the ImportError path made to fail loudly | pyshacl/brickschema as runtime dependencies; Brick's 1,752 stock shapes as acceptance | Today the validator returns "no violations" when the library is missing — indistinguishable from a pass |
| Per-turn record | PostgreSQL (already holds turn memory) plus a JSONL sidecar | Redis (three proposals chose it) | Redis is at 99.77% of a 2 GB cap with `allkeys-lru`; adding turn records evicts the demo's warm cache |
| Flags | A mounted config file read at request time, tri-state off/record/enforce | environment variables, as every current flag works | The response-cache key carries the boot revision, so an env flip costs a recreate and a cold cache |
| Portability fixture | **One vocabulary-free manifest, six committed serialisers**, graded against the manifest | independently hand-authored fixtures per vocabulary | Otherwise the instrument carries the vocabulary commitment it is testing |
| Retrieval | measurement only; a conditional context split behind a flag | cross-encoder reranker, BM25 fusion, re-chunk + reindex | There is no recall baseline, so no fix could be shown to help; and the embedder is bge-large-en-v1.5 at 1024 dims, not what three proposals assumed |

---

## 6 · What this plan refuses to do

- **Not retiring the 43 routing rules.** One rule at a time with a probe run each is ~6 days, and
  the probe cannot see a routing change: it was green throughout BUG-631, a P1.
- **Not shipping a retrieval fix** before there is a recall number.
- **Not flipping claim-binding enforcement.** It was switched on once and reverted in 25 minutes;
  13 of 23 lanes still cannot be assessed, so enforcement would leave 53% of turns unguarded.
- **Not building four synthetic buildings** to test one hypothesis four times.
- **Not expanding the probe** beyond lane markers.
- **Not making the PDP a real decision point** across 38 lanes — it is consulted on 4 and the events
  lane discards its verdict. That is named in the scope document as a limitation, not fixed.
- **Not hardening i18n**, where a non-English answer is translated *before* the English-regex guards
  and therefore bypasses all of them. Named, not fixed.
- **Not auditing** actuation, the analytics sandbox, floor plans, the admin portal, conversation
  memory, the rules engine or the report lanes. Unmeasured, and stated as unmeasured.

---

## 7 · Decisions only you can make

1. **Is there a second annotator?** Without one, the human protocol yields intra-rater consistency
   and the thesis must say so. This is the plan's most fragile dependency.
2. **Do you publish the decomposition**, knowing it makes six waves look thinner? It is the honest
   reading.
3. **Do you want the blunt headline** — "correctly answers 17 of 147" — in the thesis, or only the
   decomposed rates? Same fact, two framings; the blunt one is harder to attack.
4. **Can the machine be exclusive during measured runs?** Three other containers are using the same
   host Ollama right now, and a 13.8 GB model cannot co-reside on a 16 GB card.
5. **One live building or two?** bldg2 live is 2 days; bldg3 another 2. Recommendation: one live,
   the rest offline, plus the six vocabulary arms.
6. **If arm 2 (standard Brick) fails as predicted, pivot into fixing it, or publish the
   falsification and stop?** Publishing is cheaper and more defensible.
7. **Commit approval and timing** for the checkpoint SHA and the final viva-pack SHA.

---

## 8 · Known weaknesses of this plan

- **It WAS mostly measurement, and the owner caught it.** The first draft had ~12 of 18 packages
  producing numbers and only three whose mechanism could move correct answering. Re-ordered on
  18 September: 10 of 24 packages now target GOOD_ANSWER and Stage 1's gate is "correct answers up
  past the noise floor". The original criticism is kept here rather than deleted, because the
  failure mode it names — optimising the thing that is easiest to measure — is the same one that
  produced six waves of better refusing.
- **The 55-answer pool is one reader's labels.** The conversion target (30-45 of 55) assumes those
  labels are right about which answers the data supports. W06's blinded re-read is the only check on
  that, and it is intra-rater unless a second annotator exists.
- **The decomposition rests on the same contaminated labels it reframes** — one reader, six passes,
  with prior verdicts visible. W06 is intra-rater only unless a second annotator exists.
- **If the noise floor turns out wide, most gates here stop working.** That is why W02 runs on day 2
  rather than day 14.
- **The falsification experiment is authored by the same person it tests.** One manifest removes the
  confound *between arms*, not between the author and a real adopter.
- **Binding a role is not answering a question.** W11 can go green over a dead lane.
- **The bound-but-wrong class is untouched**: 77 sensors carry two timeseries references and the SQL
  lane merges both into one answer's statistics (BUG-531).
- **It does not deliver the architectural contribution** that the typed-plan proposal reached for —
  an admission gate deciding lanes from counts in the building's own graph. That is the best viva
  answer available and it is deferred, deliberately, because the measurements that would prove it
  helps do not exist yet.
