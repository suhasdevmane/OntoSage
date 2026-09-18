# Calibrating the grader against human labels

**Workstream A3 of `tasks/ARCH_UPGRADE_PLAN_2026-09-18.md`. Measured 2026-09-17, offline, over
294 hand-labelled answers.**

Every claim this project makes of the form *"this change improved things"* is produced by a
grader. On 2026-09-17 the project's grader (`scripts/grade_stakeholder_answers.py`) scored 20 of
147 live answers weird; two careful hand reads of the same answers scored 107 and 113. Until the
gap between those two numbers is measured, no quality claim in the thesis is supported. This
document measures it.

Nothing here decides that a grader is good. It reports agreement with the human labels, which are
treated as ground truth, and it reports the cases where the winning grader still disagrees.

---

## 1 · What was measured

| | |
|---|---|
| Corpus | 294 answers: `docs/phase0/phase0_read.jsonl` (147, baseline run 14:10-15:20) and `docs/phase0/phase0_rerun_read.jsonl` (147, the same questions re-asked 16:00-17:30 after the day's fixes) |
| Ground truth | the human's three verdicts: `GOOD_ANSWER`, `GOOD_DECLINE`, `WEIRD`. An honest decline is a correct answer, not a failure |
| Answers graded | `phase0_baseline.md.jsonl`, `phase0_rerun.md.jsonl` — recorded text only, never a live re-ask |
| Graders compared | **old heuristic** (its recorded output in `phase0_graded.jsonl` / `phase0_rerun_graded.jsonl`, six buckets collapsed onto the human's three), **deterministic** (`scripts/grade_answers_rubric.py --judge deterministic`), **LLM judge** (`--judge llm`, structured output) |
| Statistic | Cohen's kappa, three-class and weird/not-weird, plus precision and recall on WEIRD, per split and overall |

The rubric is five dimensions, each scored PASS / FAIL / NA, collapsed into one verdict — any FAIL
makes the answer WEIRD:

| dimension | the question it asks |
|---|---|
| `answers_question` | does it answer what was asked, rather than apologise, template, name its own machinery, or tell the reader to add data? |
| `figures_traceable` | is every figure traceable to something the answer itself names? |
| `honest_absence` | if it states an absence, is that absence stated honestly and about the right thing? |
| `no_invented_claim` | is it free of conclusions the cited evidence cannot support? |
| `right_subject` | is the whole answer, footers included, about the subject asked about? |

The deterministic judge's rules were written from the defect classes the human reader wrote up in
`docs/phase0/phase0_read.md` (C1-C22), not invented for this measurement.

---

## 2 · The kappa table

| grader | split | n | accuracy | kappa (3-class) | kappa (weird / not) | weird P | weird R | weird F1 | weird share it reports |
|---|---|---:|---:|---:|---:|---:|---:|---:|---:|
| old heuristic | baseline | 147 | 45.6% | 0.272 | 0.168 | 100.0% | 27.1% | 42.6% | 19.7% |
| old heuristic | rerun | 147 | 35.4% | 0.181 | 0.071 | 95.0% | 16.8% | 28.6% | 13.6% |
| **old heuristic** | **overall** | **294** | **40.5%** | **0.226** | **0.116** | **98.0%** | **21.8%** | **35.7%** | **16.7%** |
| deterministic | baseline | 147 | 68.7% | 0.451 | 0.457 | 95.9% | 65.4% | 77.8% | 49.7% |
| deterministic | rerun | 147 | 67.3% | 0.385 | 0.376 | 93.7% | 65.5% | 77.1% | 53.7% |
| **deterministic** | **overall** | **294** | **68.0%** | **0.420** | **0.419** | **94.7%** | **65.5%** | **77.4%** | **51.7%** |
| LLM judge | smoke sample | 20 | 60.0% | 0.401 | 0.432 | 57.1% | 66.7% | 61.5% | 35.0% |

*(the human's own figures: 72.8% weird on the baseline, 76.9% on the rerun)*

**The LLM row is not comparable with the two above it** — see §2.1. It is a 20-row sample with a
different weird share, and kappa moves with the class balance on its own.

**The deterministic rubric grader wins, and by a wide margin on the class that matters.** On the
weird/not-weird decision its kappa is **0.419 against the old heuristic's 0.116 — a gain of
+0.303**, and it finds **65.5% of the answers the human called weird against the old grader's
21.8%**, at 94.7% precision. Three-class kappa: 0.420 vs 0.226.

Both numbers are modest in absolute terms. 0.42 is "moderate" agreement, not good agreement. The
honest reading is: the old instrument was close to useless for the weird class (it missed four out
of five), the new one is usable as a direction indicator and is not usable as a level.

### 2.1 · The LLM judge is not adopted, and the reason is a measurement error worth naming

The LLM judge ran on a verdict-stratified sample of 20 rows (7 GOOD_ANSWER, 7 GOOD_DECLINE, 6
WEIRD) — the GPU budget for this workstream. 20 of 20 replies parsed and satisfied the schema;
**zero UNGRADED**, which is the one thing the smoke test does establish.

Ranking graders on their headline rows would have said *"the LLM judge wins, +0.316 over the old
heuristic"*. That is wrong, and the script printed it before it was fixed. On **the same 20 rows**:

| grader | n | accuracy | kappa (3-class) | kappa (weird/not) | weird P | weird R |
|---|---:|---:|---:|---:|---:|---:|
| **old heuristic** | 20 | 85.0% | **0.772** | **0.583** | 100.0% | 50.0% |
| deterministic | 20 | 65.0% | 0.474 | 0.524 | 66.7% | 66.7% |
| LLM judge | 20 | 60.0% | 0.401 | 0.432 | 57.1% | 66.7% |

**On that sample the old heuristic wins.** The sample is 30% weird; the corpus is 74.8% weird. A
high-precision, low-recall grader looks excellent on a balanced sample and fails on the real
distribution, which is exactly how the old grader survived this long. The script now decides the
winner only on rows every grader scored, and says so when that set is a sample.

So: **the LLM judge is not adopted, and on this evidence it is not better than either of the
others.** Its errors were mostly the GOOD_ANSWER/GOOD_DECLINE boundary, which does not matter, but
it also called a correct work-order listing weird ("a figure not traceable to a named register",
when the register was named) and a correct clarification weird. **Full LLM-judge calibration over
all 294 rows is owed and needs a GPU slot from the lead** (~13 min of exclusive GPU at the smoke
rate; budget 45-60 min for 294 rows under rehearsal contention).

### 2.2 · The test that matters more than the kappa

The two runs are a natural experiment. The human read both and said the system got **worse**
after the day's fixes: weird 72.8% → **76.9%**, +4.1 points.

| grader | baseline | rerun | movement | agrees with the human? |
|---|---:|---:|---:|---|
| human (ground truth) | 72.8% | 76.9% | **+4.1 pts** | — |
| old heuristic | 19.7% | 13.6% | **-6.1 pts** | **no — opposite direction** |
| deterministic rubric | 49.7% | 53.7% | **+4.1 pts** | yes, same direction and same size |

The old grader reported a 31% relative improvement on a day the system got worse. That is the
precise failure this workstream existed to remove, and it is removed: the rubric gate run over the
same two files exits non-zero and names the regression.

The agreement in magnitude (+4.1 vs +4.1) is a coincidence of this corpus and must not be quoted
as a property of the grader.

---

## 3 · Confusion matrices (overall, n=294)

### Old heuristic

| human \ grader | GOOD_ANSWER | GOOD_DECLINE | WEIRD |
|---|---:|---:|---:|
| GOOD_ANSWER | 27 | 2 | 0 |
| GOOD_DECLINE | 0 | 44 | 1 |
| **WEIRD** | **86** | **86** | **48** |

172 of 220 weird answers were passed: 86 as good answers, 86 as honest declines. The grader reads
shape, and both a confident misreading and a decline citing the wrong register have the right
shape.

### Deterministic rubric

| human \ grader | GOOD_ANSWER | GOOD_DECLINE | WEIRD |
|---|---:|---:|---:|
| GOOD_ANSWER | 23 | 6 | 0 |
| GOOD_DECLINE | 4 | 33 | 8 |
| **WEIRD** | **40** | **36** | **144** |

It never calls a human GOOD_ANSWER weird. Its 8 false alarms are all declines. Its 76 misses split
40 / 36 between answers and declines, and section 5 says what they are.

---

## 4 · What each rule is worth

Each rule was removed in turn and the weird/not kappa re-measured. A rule that does not pay is
visible rather than assumed.

| rule | fires on human-WEIRD | fires on human-GOOD | kappa without it | delta |
|---|---:|---:|---:|---:|
| NON_ANSWER_TEMPLATE | 31 | 0 | 0.349 | +0.070 |
| FOOTER_MISFIRE | 31 | 0 | 0.362 | +0.057 |
| ONTOLOGY_NAMED | 40 | 0 | 0.376 | +0.043 |
| FRAGMENT | 9 | 0 | 0.376 | +0.043 |
| USER_ATTRIBUTION | 18 | 0 | 0.380 | +0.038 |
| OPEN_DOMAIN_PROSE | 6 | 0 | 0.390 | +0.029 |
| INTERNAL_TOKEN | 19 | 0 | 0.399 | +0.019 |
| DOCUMENT_CATCHALL | 20 | **5** | 0.400 | +0.018 |
| ADD_DATA_INSTRUCTION | 19 | 0 | 0.404 | +0.015 |
| PHRASE_NOT_A_PLACE | 2 | 0 | 0.409 | +0.010 |
| BREAKDOWN_SUM / TABLE_COUNT_MISMATCH / DEICTIC_BOUND / STALE_FUTURE_DATE | 1 each | 0 | 0.414 | +0.005 each |
| UNRELATED_REGISTER | 7 | **3** | 0.416 | +0.003 |
| PROVENANCE_LEAK / LANE_JARGON / REPETITION | 4 / 14 / 6 | 0 | 0.419 | +0.000 |
| COUNT_CONTRADICTION | 0 | 0 | 0.419 | +0.000 |

Read with care:

* A `+0.000` delta does not mean the rule is useless. `LANE_JARGON` fires on 14 weird rows and no
  good ones; it contributes nothing to kappa only because those rows already fail another rule. It
  is kept because it names the defect correctly in the reason line, which is what a developer acts
  on.
* `UNRELATED_REGISTER` (+0.003 at the cost of 3 false alarms) and `DOCUMENT_CATCHALL` (+0.018 at
  the cost of 5) are the two rules paying the least for the damage they do. Both are kept for now
  and both are the first candidates to drop if precision has to rise.
* `COUNT_CONTRADICTION` never fires on this corpus. It stays because it is free and the defect it
  describes (a part stated larger than its whole) is one the register lane can produce.
* The four arithmetic and date rules fire once each. They are the rules that would matter most in
  a thesis — "the answer contradicts its own table" — and on 294 rows they are barely exercised.
  Do not report them as working.

---

## 5 · Where the winning grader still disagrees with the human

The 76 missed weird rows are not spread evenly. By the human's own defect classes:

| class | missed | caught | what the class is |
|---|---:|---:|---|
| C7 | 28 | 7 | register narration misreads a status or date, or invents a conclusion |
| C8 | 18 | 4 | a register chosen on one bare word; the lane then declines with that register's statistics |
| C9 | 9 | 8 | the building holds the data and no lane reaches it (false absence) |
| C19 | 7 | 4 | shortcut misroutes |
| C4 | 3 | 17 | metadata RAG fallback |
| others | 11 | 24 | |

**The single disagreement pattern, stated plainly: a fluent, well-formed answer that is simply
untrue about what the building holds.** Three quarters of the misses (C7, C8, C9) share it. Two
examples:

> **baseline row 50 (IR-034)** — asked whether digital evidence items can be authenticated,
> scoped, permissioned and preserved with an unbroken chain of custody. Answer: *"No — the
> waste-collection records do not contain any information about authentication, scope,
> permissioning or preservation of a chain of custody."* Well formed, honest in tone, correct
> about the register it read. Weird because it read the waste register for a records-management
> question while an approval-and-evidence register sat unread.

> **baseline row 19 (CT-065)** — *"the next authorised collection is scheduled for 8 September
> 2026"*, said on 17 September. Caught here, by the date rule, and only because the claim carried
> a literal date. The same class of error without a date literal — *"all lifts are available"*
> beside a table showing one out of service — is invisible to text alone.

Nothing in the recorded text distinguishes these from a correct decline. Closing this gap needs
the evidence the answer was built from, not a better reading of the prose. That is what A2's claim
binder produces; when it lands, the grader should consume the evidence record rather than the
answer alone, and that is the single change most likely to move kappa past 0.42.

For scale on the movement it does see: run over the two Phase 0 files the gate reports **16
questions improved and 22 regressed**, against the human's 9 improved and 15 regressed. The same
story, slightly louder, in the same direction.

**In the other direction — the 8 false alarms — all are declines, and 5 of them expose a
disagreement between the two human readers rather than a grader fault.** The document lane's
catch-all (*"the documents do not answer this. I searched … Register; they are the closest
material and none of them contains the answer"*) was labelled WEIRD by the baseline reader and
GOOD_DECLINE by the rerun reader, on the same template. The remaining 3 are declines that cite a
register sharing no vocabulary with the question but which the human judged reasonable
(*"sampling rates … they only record observed duty values"*).

---

## 6 · The two backends

Both sit behind one interface (`Judge.grade`), so the calibration, the run grader and the gate are
identical code with a different judge.

* **`--judge deterministic`** — features only. No model, no network; a test asserts it by making
  `urlopen` raise. Every verdict carries the rule that decided it and the text that triggered it.
* **`--judge llm`** — one structured-output call per answer. The JSON schema is passed to the
  provider as the requested `format`, temperature 0, and the reply is validated against the schema
  field by field. **A reply that does not parse, or parses but does not satisfy the schema, is
  recorded as `UNGRADED` — never guessed, never defaulted.** `UNGRADED` rows are excluded from
  kappa and counted separately, so an unreliable judge shows up as a shrinking denominator instead
  of as agreement.

### What the LLM judge run established, and what it did not

| | |
|---|---|
| ran | 20 answers, verdict-stratified across both splits, `gpt-oss:20b` via Ollama, temperature 0 |
| schema compliance | **20 / 20 parsed and validated; 0 UNGRADED** |
| agreement | see §2.1 — third of three on the rows it shared with the others |
| **owed** | **full calibration over all 294 rows, which needs an exclusive GPU slot from the lead** |

Artifacts: `scripts/outputs/rubric_calibration_smoke.{md,json}` and
`rubric_calibration_smoke_rows.jsonl` (every row, every grader, every reason). The saved rows can
be re-summarised with `--recompute` without spending a single further model call.

---

## 7 · Honest limits

1. **294 rows, one building, one labeller per split.** There is no second annotator, so there is
   no human-human kappa to compare against. The two splits were read by two readers following the
   same written method, and section 5 shows they disagree with each other on at least one whole
   template. An inter-annotator study on a shared subset is owed before any of these kappas is
   quoted as a measurement of the rubric rather than of one reader.
2. **The deterministic rules were written from this corpus.** The class descriptions they encode
   came from the baseline read. The rerun split is the closest thing to held-out data here, and
   the grader does lose ground on it (kappa 0.457 → 0.376) — partly for that reason, and partly
   because the day's fixes removed exactly the phrasings the rules match while leaving the defect
   underneath. **A phrase-matching grader is fooled by phrase-level fixes.** That is the same
   failure mode as the old grader, one level down, and it is the reason the gate is a direction
   indicator and not a score.
3. **The level is wrong; only the direction is calibrated.** The grader reports a 51.7% weird
   share where the human reads 74.8%. Never quote the grader's weird share as the system's weird
   share.
4. **Text-only.** The grader cannot see the evidence an answer was built from, so it cannot check
   whether a figure is true — only whether the answer names something that could support it. Every
   figure-level check here is a consistency check, not a fact check.
5. **The arithmetic and date rules are barely exercised** (one firing each) and must not be
   reported as validated.
6. **The old heuristic's numbers are read from its recorded output**, not re-derived, so they are
   exactly the numbers that were acted on that day.
7. **The LLM judge has been measured on 20 rows, which is not a measurement.** Nothing in §2.1
   should be quoted except "20/20 replies satisfied the schema" and "it is not adopted".
8. **Kappa is sensitive to the class balance.** §2.1 is a worked example of that inside this very
   corpus: the same three graders rank in two different orders on two different row sets. Any
   future comparison must state the row set and its weird share.

---

## 8 · How it is used

```bash
# Calibration (offline, no GPU, ~20 s)
python scripts/grade_answers_rubric.py --calibrate --asof 2026-09-17 \
    --out scripts/outputs/rubric_calibration

# Add the LLM judge. --llm-sample N keeps it to N stratified rows; --llm-all is the owed run.
python scripts/grade_answers_rubric.py --calibrate --asof 2026-09-17 --with-llm --llm-all \
    --out scripts/outputs/rubric_calibration_llm

# Re-summarise a saved calibration without grading anything again
python scripts/grade_answers_rubric.py --recompute scripts/outputs/<name>_rows.jsonl

# Grade one recorded run
python scripts/grade_answers_rubric.py --grade <run>.md.jsonl \
    --bank docs/phase0/phase0_bank.jsonl --asof <run date> --out scripts/outputs/<name>

# Regression gate: prints what moved each way, exits non-zero when the weird share rises
python scripts/grade_answers_rubric.py --gate <new>.md.jsonl --baseline <previous>.md.jsonl \
    --asof <run date>
```

The gate reads two recorded runs and nothing else. It never asks the live system — a test asserts
that by making `urlopen` raise inside the gate path. It matches questions across the two files,
prints every question that moved in each direction with the rule that decided it, and exits 1 when
the weird share rises. Run over the baseline and the rerun it exits 1 and names 22 regressions
against 16 improvements, which is the correct direction.

Tests: `tests/test_grade_answers_rubric.py` (48 tests, `-m unit`). Two of them pin this document:
the corpus is 294 rows, and the deterministic judge beats the old heuristic on weird kappa,
recall and precision. If either stops being true, a test goes red rather than a claim going stale.
