# V6 plan extension — the 243 questions the building cannot answer

**Added to `tasks/V6_TRACKER.csv` as phase `P12-Unanswered`, tasks V6-T70 … V6-T81.**
Source data: `docs/V6_unanswered_worklist.csv` (243 rows), built from the
2026-08-28 golden baseline by `scripts/build_unanswered_worklist.py`.

---

## The finding that shaped the plan

All 180 declines routed to **one intent: `capability`**, the catch-all — and they all
returned the **same sentence**:

> *"I don't have that specific information on record for Abacws Building."*

That single fact reframes the work. The 243 are not one problem with one fix. Reading
them, they divide into four kinds of work with very different costs:

| kind | n (approx) | what it actually takes |
|---|---|---|
| **a defect in code** | 45 | the spatial lane errors; breadth questions time out |
| **a routing gap** | 40 | the data exists and the question never reached it |
| **authoring** | 20 | Amenity and equipment triples nobody has declared |
| **a genuinely absent source** | 90 | documents, an asset register, tariffs |
| **out of scope** | 7 | scenario simulation the system has no model for |

The single highest-yield item is none of those. It is **V6-T70: make the decline
specific**. One sentence serving 180 different failures cannot be triaged by the person
reading it, teaches them nothing, and makes 180 distinct gaps look like one. Naming what
was looked for, what the building *does* hold, and how to add the missing thing improves
every one of them before a single new source is onboarded. It is an S-effort task and it
is first for that reason.

---

## The tasks, and why they are ordered this way

### Do first — cheap, and they unblock the measurement

| task | effort | what |
|---|---|---|
| **V6-T70** | S | Make the decline specific. Highest yield per hour in the whole list. |
| **V6-T71** | M | The spatial lane raises an **error**, not a decline, on 29 questions. An error hides which component failed; this is the clearest defect in the worklist and it is not a data problem. |
| **V6-T74** | S | Expose the provenance the evidence record **already holds**. Five questions ask "how do I know this is real?" — V6 built exactly that machinery and nothing reaches it by asking. |

### Then — the largest recoverable group

| task | effort | what |
|---|---|---|
| **V6-T73** | L | Route what other lanes can already answer. *"Give me a report on the anomalies this week"* has an events lane. *"Give me the sensor readings around 2.15 for the past hour"* is a plain sensor question that was declined. ~40 rows. |
| **V6-T72** | M | Breadth questions exceed the 150 s timeout. |
| **V6-T76** | M | Author the amenities and room equipment ~20 questions ask for. The lane works — bldg2's refill points prove it — so this is authoring, not engineering. |

### Then — genuinely new data

| task | effort | what |
|---|---|---|
| **V6-T75** | L | Document pack: water hygiene logbook, permits, asbestos register, COSHH, PEEPs, O&M manuals. 18 questions already say *"I could not find a passage"* — the document lane works and has nothing to read. |
| **V6-T78** | L | Energy cost and contracts. Submeter data exists; money does not. |
| **V6-T77** | L | Asset register: roof ages, U-values, ceiling heights, buried services. Brick models systems and spaces, not asset age — no amount of routing fixes this. |
| **V6-T79** | M | Executive summaries. Every input exists; nothing composes them. |

### Decide, then hold

| task | effort | what |
|---|---|---|
| **V6-T80** | S | Scenario questions — *"if power fails, how long do the lab freezers stay safe?"* The system has no thermal model. Decide the boundary and decline consistently, naming it. |

### Finally — prove it

| task | effort | what |
|---|---|---|
| **V6-T81** | M | Re-capture all 1,580, run the regression gate, rebuild the worklist, compare. |

---

## Decisions I made, and the reasoning

These are the judgement calls. Each is in the tracker's `alternatives_rejected` column
so the reasoning travels with the task.

**Raise the timeout — but not on its own.** Raising `REQUEST_TIMEOUT_SECS` from 150 s
admits the 16 questions while making a user wait minutes, and leaves the p99 creeping
toward whatever the new ceiling is. Answered questions already reach p99 96.4 s against
the current 150 s. So: aggregate in SQL first (the `sql_agent` currently coarsens *after*
fetching, which is the expensive half), bound the candidate set, **then** raise to 300 s
and re-measure. The raise is the unblock; the aggregation is the fix.

**Do not drop the 16 from the bank.** 1.0% of the corpus being unanswerable by *cost*
rather than by *capability* is a finding worth reporting.

**Never invent a compliance record for bldg1.** V6-T75 needs a legionella assessment, a
permit register, an asbestos survey. bldg1 is a **real building**. Synthetic compliance
documents are fine for bldg2/3/4 and are not acceptable for bldg1 — the same rule that
stopped the provisioner minting potability statements. This needs your decision: real
documents, or an explicit "not held".

**Never estimate cost from a hardcoded tariff.** An invented unit rate produces a
confident wrong number, which is the failure mode this project guards against hardest.
Either a tariff source is registered or the question declines naming the missing source.

**Never answer a scenario question from the model's physical intuition.** A confident
freezer-safety estimate with no model behind it is the most dangerous answer this system
could produce.

**Probe before adding a routing rule.** V6-T73 is the largest group and the easiest to
get wrong: a rule that sends a question to a lane with no data trades one decline for a
worse one. Each rule must be justified by a live probe showing the target lane answers.

**Route rather than widen the catch-all.** Teaching `capability` to answer anomaly,
wayfinding and forecast questions itself would duplicate four lanes inside it and put the
evidence record on the wrong lane.

---

## Two things I need from you

1. **bldg1 compliance documents (V6-T75).** Real records, or an explicit "not held"?
   I will not fabricate them for a real building.
2. **The scenario boundary (V6-T80).** Does OntoSage attempt what-if questions at all?
   My recommendation is no, with a decline that names what it would take — but that is
   a product decision, not an engineering one.

---

## Honest limits of the triage

`docs/V6_unanswered_worklist.csv` carries a `proposed_bucket` column. It is a
**keyword-driven first pass**, not a diagnosis:

* **90 of 243 rows are `UNTRIAGED`** — no pattern matched, and I would rather say so than
  guess. I read all 90 by hand to build this plan; the clusters above come from that
  reading, not from the keyword column.
* The buckets it *does* assign contain visible errors. *"Where can I wait comfortably? My
  meeting isn't for another 40 minutes"* landed in `DATA-SCHEDULE` on the word "meeting"
  when it is really a comfort recommendation. *"Which room did the marketing team use for
  their away day?"* landed in `DATA-PEOPLE` on "team" when it is booking history.

Confirm a row before acting on it. The file exists to **order** the work, not to conclude
it, and it carries `fixed` and `notes` columns so progress can be tracked as tasks land.

---

## Re-running any of this

```bash
# rebuild the worklist from a newer capture
python scripts/build_unanswered_worklist.py --capture <new_capture.csv>

# what changed against the 2026-08-28 baseline — regressions must be zero
python scripts/baseline_regression_gate.py --current <new_capture.csv>

# re-append the plan rows (idempotent; skips rows already present)
python scripts/extend_v6_plan_unanswered.py
```

*Written 2026-08-29 from `docs/V6_unanswered_worklist.csv`. The task rows live in
`tasks/V6_TRACKER.csv` phase `P12-Unanswered`; this document explains why they are
ordered as they are.*
