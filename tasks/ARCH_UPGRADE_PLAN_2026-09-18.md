# Architecture upgrade plan — from "it answers" to "it is right, and it is portable"

**Written 2026-09-17 ~21:00, after a hand read of 147 live stakeholder answers.** Owner decision
the same evening: the seven weaknesses named in the architecture review are to be fixed as
**components**, not as more rules — and the result must be a system another OntoSage building can
adopt by supplying data alone. Target: the first tranche inside 12 hours, with 2-3 further days
available if the evidence says an item needs them.

**The demo is 2026-09-18 14:00.** Nothing in this plan may make the demo worse. Every workstream
below therefore lands BEHIND A FLAG, default OFF, and is turned on only when the probe (60 cases)
and the demo rehearsal (44 questions) are green with it on. That is not caution for its own sake:
today a fix that was green on its own targets moved the hand-read weird share from 72.8% to 76.9%.

---

## 0 · What the evidence says is actually wrong

Three defect families account for nearly every weird answer. They are not framework problems.

| # | Weakness | Evidence (2026-09-17) |
|---|---|---|
| W1 | **Understanding a question is done by rules that accumulate.** | `routing_contract.py` is 41 ordered parse-stage rules + 1 post + 3 concept; plus lay-term lists per class, a register ranker, and HBCO concept mappings. Every defect fixed today added or narrowed a rule, and narrowing broke four answers that had been right (BUG-729). |
| W2 | **Grounding is asserted, not enforced.** | 17 answers carried the right register and an invented conclusion ("each record has a mapped opening, **so none lack evidence of ownership**"). Tonight's countermeasure is a prompt rule — the weakest possible enforcement. |
| W3 | **The instrument disagrees with reality.** | The automatic grader scored 20 of 147 answers weird; a careful human reading the same answers scored 113. Every quality claim downstream of that grader is unsupported. |

Two further weaknesses are real but smaller, and both are data-shaped rather than model-shaped:

* **W4 — retrieval reaches the wrong evidence.** A cleaning question was declined over three
  unrelated registers while 30 `CleaningTask` records sat unread; document search is dense-only.
* **W5 — comparisons and periods are not normalised.** "Compare this week's electricity use with
  last week" compares a partial week (Mon-Thu) with a full one and does not say so; measured
  2026-09-17 rehearsal 2, figures correct, comparison not like-for-like.

---

## 1 · Workstreams

Each is independent, owns disjoint files, and carries its own flag, acceptance test and rollback.
**A1-A4 are the 12-hour tranche. A5-A7 are scoped here and start after the demo**, because each
needs either a model pull, a schema migration or a rewrite that cannot be verified before 14:00.

### A1 · Structured generation: the model fills a schema, code writes the query
*Answers W1 and part of W2. Flag `STRUCTURED_PLAN_ENABLED`.*

**Problem.** Every lane that asks the model for SPARQL or JSON parses free text and repairs it.
BUG-631 (every floor-scoped SPARQL query rejected as malformed, fallback answered about a
different floor, three verification layers blind) is the worst case this shape produces, and the
CQ-IR compiler already shows the alternative working: the model emits a constrained plan and
deterministic code builds the query.

**Change.** Ollama supports a JSON-schema `format` parameter; llama.cpp supports GBNF grammars.
1. `llm_manager.generate_structured(prompt, schema)` — passes the schema to the provider, validates
   the parse against it, retries once with the validation error appended, and records a typed
   outcome. No free-text JSON parsing anywhere it is used.
2. Convert the two highest-traffic call sites first: the CQ-IR compile and the dialogue
   intent+entity extraction. Both already have a JSON contract written in prose in the prompt.
3. SPARQL is NOT generated under a grammar in this tranche. The safer and more defensible route is
   that the model emits a *plan* (class, filters, fields, scope) and a deterministic builder emits
   SPARQL — which is what the register lane already does (`whole-register fetch … no SPARQL
   generated`). Extending the builder is A6.

**Acceptance.** Compile a fixed set of 40 questions 3× each with the flag on: zero parse failures,
zero repair retries, and the same plan each time (the compiler's own `plan_fingerprint`). Probe and
rehearsal green with the flag on.

**Files.** `orchestrator/llm_manager.py`, `orchestrator/services/deliberation/compiler.py`,
`orchestrator/agents/dialogue_agent.py` (+ tests).
**Rollback.** Flag off restores the current text parse; both paths stay until a full rehearsal
passes with the flag on.
**Thesis artifact.** A measured table: parse failures and repair retries per 100 calls, before and
after, plus plan-stability across repeats.

### A2 · Claim binding: every figure in an answer points at a row
*Answers W2. Flag `CLAIM_BINDING_ENABLED`.*

**Problem.** The evidence dossier records what was fetched; nothing checks that the prose ONLY says
what the evidence supports. Measured: 17 invented conclusions, plus "all lifts are available" beside
a table showing one out of service.

**Change.** A post-answer binder that runs where the answer becomes final (the one chokepoint that
`answer_wording.polish_answer` already uses):
1. Extract every quantitative claim from the answer (number + unit + subject).
2. Match each against the evidence set on the bus (SQL rows, register fields, dossier cells).
3. Unmatched claim -> it is removed and the answer says which claim could not be evidenced, or the
   answer is returned to the lane for a bounded retry. Never silently kept.
4. Record per answer: claims made, claims bound, claims dropped. That number is the headline
   honesty metric for the thesis.

**Acceptance.** On the 147-question bank: no answer contains a number absent from its own evidence
record; the 17 C7 rows lose their invented verdicts; binding coverage reported per lane.

**Files.** new `orchestrator/services/claim_binder.py`, `orchestrator/services/evidence/*`,
wiring in `_orchestrator._response_node` (+ tests).
**Rollback.** Flag off = record-only mode (count claims, change nothing) — which is itself the
measurement that justifies turning it on.
**Thesis artifact.** Bound-claim ratio per lane, before/after, with the drop list.

### A3 · A grader calibrated against human labels
*Answers W3. No flag — it is a script, not a runtime path.*

**Problem.** 20 vs 113. Every "we improved it" claim in this project is currently unfalsifiable.

**Change.**
1. Use the two hand-read sets (`docs/phase0/phase0_read.jsonl`, `phase0_rerun_read.jsonl` — 294
   labelled answers) as the calibration corpus.
2. Build `scripts/grade_answers_rubric.py`: a rubric judge (LLM, structured output from A1) scoring
   each answer on grounded / answers-the-question / honest-absence / invented / wrong-lane.
3. **Report agreement with the human labels (Cohen's kappa) before the grader is used for anything.**
   A grader that cannot beat the old heuristic's agreement is discarded, and that result is itself
   reportable.
4. Wire the winner into a regression gate: a fixed 60-question subset, run per change, with the
   score and the disagreements printed.

**Acceptance.** Kappa reported against 294 human labels; gate script runs offline over recorded
answers and exits non-zero on regression.
**Files.** `scripts/grade_answers_rubric.py`, `docs/phase0/*` (read-only), new eval docs.
**Thesis artifact.** The calibration table — this is the methodological backbone of any quality
claim in the thesis.

### A4 · Portability conformance suite
*Answers "works for any OntoSage building". No flag.*

**Problem.** Portability is asserted from three buildings that were onboarded by hand. There is no
artifact a new adopter can run that says what their building can and cannot answer.

**Change.** `scripts/conformance_report.py`, building-agnostic, reading only the active building:
1. **Data contract check** — every declared modality resolves to points; every point resolves to one
   timeseries reference (the fan-out metric, which caught BUG-531); every registered store answers.
2. **Capability matrix** — for each question class the system claims (sensor now, per-floor
   ranking, register lookup, document answer, spatial, privacy refusal…), does THIS building hold
   what that class needs? Report supported / supported-with-limitation / not-supported-and-why.
3. **A conformance question set**, derived from the classes rather than written per building, asked
   live and graded by A3.
4. Output: `docs/CONFORMANCE_<building>.md` + JSON, plus a one-page adopter summary.

**Acceptance.** Runs on bldg1 tonight; runs on bldg2 or bldg3 unchanged after the demo and produces
a different, correct matrix.
**Files.** `scripts/conformance_report.py`, `docs/CONFORMANCE_*.md` (+ tests).
**Thesis artifact.** The matrix per building — the evidence that the architecture, not the tuning,
is what transfers.

### A5 · Hybrid retrieval with a reranker *(starts after the demo)*
*Answers W4. Flag `HYBRID_RETRIEVAL_ENABLED`.*

Dense-only search over documents and a substring match over register terms is why a question meets
the wrong register. Add BM25 alongside the dense index, fuse (reciprocal rank), and rerank the top
k with a cross-encoder; link entities against graph labels rather than substrings. Measure on the
questions whose right register is known from tonight's reach measurement (`register_reach.py`),
and on the document questions in the bank. Deferred because it adds a model and latency to every
document turn — not something to introduce hours before a demo.

### A6 · One typed plan for every lane *(2-3 days, starts after the demo)*
*Answers W1 properly.*

The CQ-IR the deliberation lane compiles is the right idea confined to one lane. Extend it to the
register/metadata and sensor lanes so a question becomes a typed plan and the 41 routing rules
collapse into capability declarations that each lane publishes. **Scoped first step (1 day):** a
rule-coverage report that maps each of the 41 rules to the typed plan that would subsume it, and a
typed plan for the register lane only, behind a flag, measured against the register questions.
Attempting the whole unification tonight would put the demo at risk for no measurable gain.

### A7 · Model strategy *(starts after the demo)*
A small model for classification and a stronger one for synthesis, with structured output
throughout (A1 is its prerequisite). Needs a second model pulled and a full re-measure of latency
and quality; the evidence for "the 20B is doing work it is bad at" should come from A3's grader,
not from intuition.

### A8 · Like-for-like periods
*Answers W5. Small, safe, do it in the 12-hour tranche if A1-A4 leave room.*

A comparison of an incomplete period with a complete one must either normalise (per-day mean) or
say so in the answer. Measured tonight: "-50.8% from W37 to W38" where W38 is Mon-Thu.
`requested_interval` already knows the bounds; the comparison lanes must consume them.

---

## 2 · Scheduling, and why this order

**GPU is the scarce resource, not developer time.** The local model serves one request at a time,
and heavy parallel test runs starve it (CAVEAT-734: a 43-minute answer). So:

* **Agents work offline** — code, unit tests, offline measurement. No live asks.
* **Live runs are serialised by the lead**, one at a time: probe, rehearsal, bank re-ask.
* A workstream is "done" when its offline tests pass AND one serialised live run confirms it.

**Order inside the 12 hours**
1. A3 first (2-3 h, offline): without a trustworthy grader, nothing else can be shown to have
   helped. It also produces the gate the other three are measured by.
2. A1 and A2 in parallel (4-6 h, offline, disjoint files), each flag OFF.
3. A4 in parallel (3-4 h, offline + one live conformance run).
4. Serialised verification: probe with flags off (regression), then flags on, then rehearsal, then
   the 147-question bank re-asked and graded by A3 and read by hand.
5. Flags flipped only where the evidence says so. Demo runs on whatever passed.

---

## 3 · What must stay true

* No building literals in code, `shared/` or the TBox — the conformance suite exists to prove it.
* No user-visible text ever says simulated, synthetic or fake.
* Nothing is committed or pushed without the owner's explicit approval.
* Every claim in this plan's acceptance criteria is a measurement, not a judgement.
