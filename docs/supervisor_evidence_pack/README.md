# OntoSage — evidence pack

**73 questions asked of the running system, one screenshot each, with a verdict on every answer.**

This is the combined pack: 26 questions covering the shapes the system is designed for, and 50
harder ones of the kind a viva asks — predictions that must show their model, charts drawn from the
readings behind them, reasoning across two sensors at once, questions whose answer is a *method*
rather than a number, and questions the system must refuse. Three questions appeared in both sets
and are kept once.

**52 of the 73 answer the question; 21 do not — 20 that miss, and 1 flagged as not to be relied on.**

Both halves are here on purpose. A pack in which everything succeeds is evidence of easy questions,
not of a working system; the twenty failures are what make the fifty-two checkable, and they turn
out to share a single cause (below).

## What to read

| file | what it is |
|---|---|
| **[INDEX.md](INDEX.md)** | Every question with its verdict, timing and screenshot, and the answer quoted so the pack reads without opening 73 images. |
| **[screenshots/](screenshots/)** | 73 full-page captures of the real browser, numbered to match the index. |
| `answers.jsonl` · `review.json` | The raw capture record and the hand-written verdicts, kept so the index regenerates and the judgements can be audited. |
| [`../SUPERVISOR_BRIEF.md`](../SUPERVISOR_BRIEF.md) | One page on which question shapes work and which do not. |

## Results by kind of question

| family | answered | |
|---|---|---|
| Registers — permits, fire assets, hazards, work orders | **11 / 11** | record ids, owners, due dates; absence stated as absence |
| Live readings and readiness | **10 / 10** | values with their timestamp and the access policy that set the resolution |
| Deliberation — rank under several constraints | **4 / 4** | ranks rooms on noise, light, CO₂ and occupancy together, with the reading behind each |
| Reports filed from a statement | **2 / 2** | a fault and a suggestion, each returned with its ticket id |
| Honest declines and refusals | **7 / 8** | not measured, not recorded, out of scope, a person, a blanket compliance claim. The eighth is the flagged one |
| Prediction | **4 / 6** | per-room forecasts pick between models on a hold-out; floor- and building-level do not reach the forecaster |
| Spatial, operations, anomaly | **5 / 8** | |
| Charts | **3 / 5** | a day, a week, six floors at once — each with the reading in words beside it |
| Comparison | **3 / 6** | comparing two floors works; comparing two PERIODS does not |
| Method and provenance | **2 / 5** | it can show the evidence for a ranking; it cannot say which sources answered the previous turn |
| Data quality | **1 / 3** | |
| **Cross-modal diagnosis** | **0 / 5** | the clearest gap — see below |

## The finding worth a supervisor's attention

**Every question that required reasoning across two quantities at once failed** — "which rooms are
both warm and stuffy", "is ventilation keeping up with occupancy", "are there rooms where CO₂ rises
while occupancy stays flat". The building measures all of those quantities, and other answers in
this same pack read each of them successfully. One reply even stated that the building model
"does not contain any current temperature, humidity, CO₂ or other air-quality readings", which is
false and is contradicted a few screenshots earlier.

The bottleneck is therefore **not the data, the ontology, or the models**. It is the step that
decides which lane a question belongs to: a question naming two modalities reaches a lane that can
read one. The same fault explains most of the comparison failures and several others where the
record plainly exists and the question did not reach it.

That is a narrower and more useful claim than "71% of questions work", and it is what the twenty
failures are evidence for. One cross-modal question *does* succeed — the meeting-room question
ranks on CO₂ and occupancy together — which shows the capability exists and is reached only from
the deliberation lane.

## What this pack does not claim

- **It is one building on one day.** It shows these 73 question shapes behaving as recorded; it is
  not a measurement of how often an arbitrary question succeeds. That figure is measured separately
  on questions nobody tuned the system on, and is quoted in the brief.
- **Six of the fifty answers differed between two identical runs** (index 12, 18, 22, 34, 45, 47) —
  about one in eight. The verdicts describe the run that was captured. Routing is not deterministic,
  and that is recorded rather than hidden.
- **One answer must not be relied on.** The defibrillator answer states positions as fact while the
  record behind it calls them "modelled". It is flagged in the index and open as BUG-858 (P1).
- **Timings are the local model.** Median 100 s, slowest 273 s. The predictions are slow because
  they fit and score several models on real history.

## How it was produced

Every question was asked through Open WebUI in a **fresh chat**, signed in as `facility01` — a
facility-manager account, not an administrator, so nothing here is admin-only output. Both answer
caches were flushed before each run, so every answer is a first pass and none was served from cache.
The capture waits for the whole answer, records whether it completed, and sizes the page to the
content so nothing is cut off.

```bash
python scripts/demo_prepare.py                       # health, flush caches, warm the model
python scripts/capture_evidence_screenshots.py --questions docs/evidence_questions_50.txt \
    --out docs/supervisor_evidence_50_v2 --timeout 600
python scripts/combine_evidence_packs.py --packs docs/supervisor_evidence \
    docs/supervisor_evidence_50_v2 --out docs/supervisor_evidence_pack
python scripts/build_evidence_index.py --dir docs/supervisor_evidence_pack
```

Supporting state at the time of capture: **12,393 unit tests pass, 0 fail.**

---

# To make this production grade

Ordered by what a reader of this pack would challenge first. Each item names the evidence in the
pack that motivates it.

### P1 — correctness and safety

1. **A safety-critical fact is asserted as surveyed when the record hedges.** The defibrillator
   answer gives positions and an emergency number as fact; its own `ontosage:locationText` says they
   are "modelled". Either the owner confirms the three positions, or the record is flagged
   `ontosage:isSimulated true` so the system declines. Until then the answer must not be used.
   *(BUG-858; index entry flagged. Four further safety facts are recorded but hedged —
   `docs/OWNER_FACTS_CHECKLIST.md`.)*

2. **Answers must not contradict each other within one session.** A diagnosis reply claimed the
   building model holds no current readings, a few screenshots after readings were returned from it.
   A claim about what the system *can* read should be derived from the same place the reader uses,
   not composed by the model.

### P2 — the capability gap this pack measures

3. **Route a question naming two modalities to a lane that can read both.** 0 of 5 cross-modal
   questions succeeded, while the one that reached the deliberation lane answered on CO₂ and
   occupancy together. The deliberation lane already does what the others need. *(Largest single
   win available: it would move about a third of the failures in this pack.)*

4. **Period-over-period comparison.** Comparing two *places* works (floor 1 against floor 3, with
   each side's sensor count and reading count stated). Comparing two *periods* does not: "this week
   against last week" and "weekday against weekend" both return one period's figures and say the
   other is unavailable. The readings exist; the second window is never fetched.

5. **Forecasting above the single sensor.** Per-room forecasts work end to end, with model
   selection on a hold-out. A floor-level or building-level forecast does not reach the forecaster
   and is answered by a register decline.

6. **Negation and absence over the model.** "Which rooms have *no* temperature sensor" is not
   answerable, though the model holds everything needed to compute it.

### P3 — determinism, provenance and latency

7. **Make routing deterministic for a fixed question.** Six of fifty answers flipped between two
   identical runs. Until that is closed, no measured pass rate from a single run is trustworthy to
   better than about ±10 points, including the ones in this README.

8. **Make provenance answerable, not only attached.** Every answer carries an evidence record, yet
   "which data sources did you use?" and "if two records disagree, which wins?" are declined. The
   system knows both; it cannot say them.

9. **Latency.** Median 100 s, slowest 273 s. Acceptable for a demonstration, not for interactive
   use. The forecasts are genuinely expensive; most of the rest is not.

10. **Charts: fix the two that failed.** The hourly occupancy profile found nothing to plot, and the
    humidity-against-temperature request plotted temperature alone and dated the answer 2022.

### P4 — engineering hygiene before anyone else runs this

11. **One role, one answer.** The CLI runs as `readonly` and the browser as `facility_manager`, and
    the same question can be answered in one and refused in the other. Every measurement in this
    repository should state the role it ran as; several older ones do not.

12. **Re-measure the parked suite.** The committed tree has no active building, and that is the
    number CI sees. The active-building figure quoted here (12,393) is not it.

13. **A held-out question set per release.** Sets C–L are spent. Draw a fresh set, hand-label it,
    and publish the weird rate with its denominator — the number in the brief should be re-earned
    each time the routing changes, not carried forward.
