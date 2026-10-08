# v1 → v2 on compound, multi-criteria questions — the before/after result

**Before:** tag `v1.0-demo` (`8965cd1`). **After:** `9e7d275`, the v2 build — ARBITER generalised
from sensed modalities to the building's facets (`tasks/V2_COMPOUND_PLAN.md` sections 4 and 8).
Analysis fixed in advance (plan section 5, before any v2 code was committed). Every figure below
comes from `scripts/score_blinded.py` and `scripts/score_ablation.py` run over the filled sheets in
`eval/compound/scoring/`; re-running them reproduces every number.

## Result in one paragraph

**The pre-registered primary hypothesis is not supported.** On the 44 answerable items of the
real-question sets, the acceptable rate (labels A, B or C) was **13.6% for v1 and 15.9% for v2**
(+2.3 points, paired-bootstrap 95% CI −9.1 to +13.6; exact McNemar p = 1.00, 3 items lost and 4
gained). The secondary set and the sensitivity analysis agree: no difference distinguishable from
zero. **The safety criterion failed once:** one v2 answer on the secondary set (T-CAT C037) states
alarms that the building's alarm records do not contain. The answers that reached the new compound
machinery were few — **2 of 91 held-out items** — so the experiment measured routing coverage as
much as it measured the architecture.

## Protocol deviation — read before citing any number here

The plan named one human reader (the author). **The read was carried out by a panel of LLM judges
instead**, at the author's request on 2026-10-08. What was done to keep it blinded and checkable:

- Each of the 231 answers (v1 91, v2 91, ablation arm 49) was judged **on its own by three
  independent judges** — 693 judgments, 99 judge agents, each holding up to seven answers. No judge
  saw two answers to the same question, and no judge was told which system wrote an answer. The
  keys were not opened until every label was written.
- Judges had read-only access to the building's own input files (`bldg1/*.ttl`,
  `bldg1/documents/*.md`) to check entities, registers and whether data exists. They had no
  access to the live sensor database, and were told not to mark a reading wrong merely because
  they could not reproduce it. E and F required positive evidence.
- Final label = majority of three; an all-different split would go to a fourth, senior judge. No
  answer split three ways, so no adjudication ran.
- **Agreement:** 211 of 231 unanimous, 20 two-to-one; Fleiss' κ = **0.885** over the six labels and
  **0.895** for acceptable vs not.

**What that agreement does not establish.** The three judges are the same model family that helped
build v2. High agreement among correlated raters shows consistency, not validity. The author hand-
checked a random sample of eight D labels against the building files and agreed with seven; the
eighth was a two-to-one borderline. The plan's own stated remedy for single-reader bias — a second
reader on a 20% subsample with Cohen's κ — applies here with more force. **A human read of a
stratified subsample is needed before these labels are reported as a human-equivalent read.** The
paired comparison between v1 and v2 is less exposed to this than the absolute rates: a judge who is
systematically harsh is harsh on both arms.

Full record: `eval/compound/scoring/llm_panel_record.json` (every judgment and its reason),
`llm_panel_agreement.json`, `llm_panel/panel_workflow.js` (the exact prompt and rubric),
`llm_panel/panel_result.json` and `llm_panel/answer_map.json`; rebuild with
`scripts/llm_panel_build.py` and `scripts/llm_panel_apply.py`.

## Primary analysis — T-REAL ∪ T-REAL-SUPPLEMENT (n = 49, answerable 44)

| | A | B | C | D | E | F | acceptable / answerable |
|---|---|---|---|---|---|---|---|
| v1 | 5 | 1 | 5 | 32 | 6 | 0 | 6 / 44 = 13.6% |
| v2 | 5 | 1 | 6 | 32 | 5 | 0 | 7 / 44 = 15.9% |

Difference +2.3 points (95% CI −9.1 to +13.6); discordant pairs 3 lost, 4 gained; exact McNemar
p = 1.00. Criterion coverage, mean per item: v1 0.21, v2 0.23; Wilcoxon p = 0.55.

**Provider-failure sensitivity (pre-registered):** no item in the primary set was provider-failed in
either version, so this analysis is identical to the primary one.

**Sensitivity — T-REAL alone (n = 22 answerable):** v1 13.6%, v2 18.2%, +4.5 points (95% CI −9.1 to
+18.2), 1 lost, 2 gained, p = 1.00.

**Power, as stated in advance:** a significant result needed v2 to gain about six more acceptable
answers than it lost. It gained one more.

## By shape (primary set; acceptable / items, no significance claimed)

| shape | v1 | v2 |
|---|---|---|
| C1 multi-criteria selection | 0/5 | 0/5 |
| C2 measured vs declared | 1/14 | 2/14 |
| C3 group → aggregate → rank | 8/16 | 7/16 |
| C4 two periods | 0/3 | 0/3 |
| C5 series vs events | 1/6 | 2/6 |
| C6 other compound | 1/5 | 1/5 |

## Attribution — what the architecture did, and what the incidental fixes did

The ablation arm is the v2 build with `ARBITER_FACETS_ENABLED=false` and `ARBITER_V2_ROUTING=off`,
captured on the primary set in the same session as v2 and judged in the same blinded read.

| comparison (primary set, n = 44) | acceptable | lost / gained | p |
|---|---|---|---|
| v1 → ablated (incidental fixes only) | 13.6% → 13.6% | 2 / 2 | 1.00 |
| ablated → v2 (the architecture alone) | 13.6% → 15.9% | 2 / 3 | 1.00 |
| v1 → v2 (total) | 13.6% → 15.9% | 3 / 4 | 1.00 |

**Per answer, from the route records (`*.attribution.json`, read without the answer text):**

- v2's escalation rule moved **2 of 91** held-out items into the compound lane, both in
  T-REAL-SUPPLEMENT. **X010:** v1 D, ablated D, v2 **A** — the one improvement attributable to the
  architecture alone. **X004:** D in both versions.
- 12 further v2 answers (11 of them in the primary set) reached the deliberation lane by v1's own
  routing and ran on the generalised compiler. That compiler helped once and hurt once against the ablated build: **X011**
  ablated E → v2 A; **X017** ablated A → v2 D ("I couldn't map part of your request (this time)").
  X017 is the compile instability already logged as CAVEAT-1477, appearing on the held-out set.
- The remaining answers came from v1 lanes and are v1 behaviour plus run-to-run variance.

## Secondary — T-CAT (n = 42, answerable 38)

v1 2/38 = 5.3%, v2 1/38 = 2.6%, −2.6 points (95% CI −10.5 to +5.3), 2 lost, 1 gained, p = 1.00.
Dropping the two items provider-failed in v1 (C013, C015): 2/36 vs 1/36, unchanged; v2 answered
both and both were labelled E. **F: v1 0, v2 1.**

### The fabrication (T-CAT C037, all three judges F, confirmed by the author)

Asked which alarms and abnormal readings came before, during and after a fault, v2 answered that
**ten Air-Quality Level sensors on floor 5 alarmed at 2026-07-09 15:33:47, "with 990 more of the
same type across the building"**. The building's alarm records hold one alarm at that instant — a
VAV damper on floor 5 (ALM-45E12290) — and do not mention air quality anywhere. The timeseries IDs
the answer lists are real sensors. So every token in the answer can be found in the graph, and the
answer as a whole is false. The likely mechanism is a generated query joining the alarm's timestamp
to every sensor of a class with no shared variable, cut off at a 1,000-row limit, which is where
"1,000 alarms" comes from. The orchestrator logs from the capture are gone, so this is inferred, not
verified. The answer came from the **metadata lane, which is v1 code**. v1 timed out on this item
after 300 s and never produced an answer, so v2 did not introduce this behaviour; it surfaced it.
Logged as BUG-1478 (P1). It is deliberately **not fixed against this set**: a fix tuned on a held-out
answer would contaminate any later comparison that uses it.

## What the result says about the system

1. **The dominant failure, in both versions, is the false decline.** D is 32 of 49 primary
   answers in each version, and 64 of v1's 91 answers overall. The judges' reasons repeat one
   pattern: the building holds the data (per-floor lighting meters, the waste-returns register, the
   incident log's location column, lift status, vibration sensors), and the answer gives a generic
   "couldn't tie that to a reading" or "couldn't put an answer together". The metadata lane alone
   gave 22 D in 30 v2 answers.
2. **v2's architecture works when it is reached, and it is rarely reached.** The routing was
   designed to be conservative — escalate only what v1 is known to get wrong — and on real phrasing
   it fired 2 times in 91. On development probes the same machinery answered C3 and C5 questions that v1
   answered wrongly or not at all, every time it was asked, and C2 questions only intermittently. The held-out set shows that this does not reach users
   through the current routing.
3. **The compiler is not stable enough.** Within the few items that reached it, one gain and one
   loss trace to the same compile varying between asks (CAVEAT-1477).

## Limitations

- **One building, one model, one capture per version.** Each item was asked once. Run-to-run
  variance (CAVEAT-891, CAVEAT-1475) is of the same size as the difference measured.
- **Small n.** 44 answerable items cannot detect a difference of a few points. The real-corpus pool
  after excluding every question ever asked was 51; T-REAL and its supplement are now spent.
- **LLM-judge read**, as above. A human subsample check is outstanding.
- **Answerability labels** (FULL / PARTIAL / NONE) were pre-computed before the read and accepted by
  the judges as given. A PARTIAL item answered with a bare decline is D under the rubric. That is
  strict but pre-registered.
