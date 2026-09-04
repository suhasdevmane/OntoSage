# V9 — the plan to close the remaining gap

**Written:** 2026-09-04 · **Building:** bldg1 · **Model:** local `gpt-oss:20b` (GPU)
**Basis:** the V8 measurement (`tasks/V8_REPORT.md`, `tasks/V8_QA_RESULTS.csv`)

---

## 0. Where things stand, precisely

The corpus is now two sources and 37 catalogues in one folder:

| source | questions | measured? |
|---|---:|---|
| `stakeholder_catalogue_37` | **2,960** (37 roles × 80) | 2,480 measured 2026-09-03/04 |
| | | **480 have NO current measurement** |
| `v5_synthetic_bank` | 1,100 | in the 1,580 golden baseline (2026-08-28) |
| **total** | **4,060** | |

Of the 2,480 measured: **935 computed (37.7%)**, 522 quoted, 789 honest declines, 227 failed,
7 unmeasured — **1,023 did not answer with data**.

Seven registers are now live (128 records). Measured effect on the four roles they targeted:
**23% → 55% computed, +32 points, 115 questions newly computing.**

### The one number in this plan that is an estimate

Keyword-matching the 1,023 against what the seven registers now hold suggests **689 are
plausibly addressed and 334 are beyond them**. That is an *upper bound from wording*, not a
measurement. The only measured evidence is the 320-question re-measure. Everything sized
below is a question count from the corpus; the *effect* of any item is unknown until asked.

---

## Phase A — finish the measurement before building more (≈1.5 h machine, 0 h mine)

### A1. Capture the 480 occupant questions · **the only block with no current number**

The six occupant catalogues — undergraduates, taught postgraduates, PhD students, research
staff, lecturers and tutors, academic office occupants — were last measured in the
2026-08-28 golden baseline, on a **different model and before every fix in V8**. They are
1 in 6 of the whole catalogue corpus and nothing current is known about them.

They also matter more than their share suggests. **Design contract 5 names occupants first**
among the stakeholders this system exists to serve, and the roles closest to them in kind
scored worst in V8 — visitors 16%, prospective students 26%. If the pattern holds, this is
the weakest part of the system and it is currently invisible.

- **Do:** `capture_golden_baseline.py --source stakeholder_catalogue_37`, resumed against the
  existing capture so only the 480 new rows are asked.
- **Cost:** 480 × ~9 s ≈ **1.2 hours**, unattended.
- **Gives:** the first complete picture of all 37 catalogues, and the per-role table that
  decides Phase C's order.
- **Risk if skipped:** Phase C gets built for the roles I happen to have measured rather
  than the roles that are worst.

**This runs first and everything else waits on its per-role table.**

---

## Phase B — the one code change (≈2 h mine)

### B1. Class selection in `held_record_class` · ~150 questions

`record_registry.held_record_class` picks **one** record class by lay-term match. Questions
routinely name several, so:

| question | matched | should have matched |
|---|---|---|
| *"…planned, reactive, statutory, **contract-fixed**…"* | `Contract` | `CostLine` |
| *"which unresolved exceptions for this shift **handover**"* | `HandoverRecord` | `PatrolCheckpoint` |
| *"is the **Level 2 laboratory** permission group approved"* | (observability lane) | `AccessPermission` |

This is a *different* problem from BUG-417. That one made classes unreachable; this one picks
the wrong class among reachable ones — and it gets **worse with every register added**, so it
should be fixed before Phase C rather than after.

- **Approach:** score every candidate class instead of returning the first match, and prefer
  the class whose *distinctive* terms match over one matched by a shared word. `"contract"`
  inside `"contract-fixed"` is a substring of a compound, not a mention of a contract.
- **Guard:** the same trap as BUG-372 — head words may find data but must never justify a
  decline. A scoring change must not turn a correct answer into a confident wrong one, so it
  needs a labelled set of the ~150 before/after, the way BUG-218's fix was measured and
  rejected.

---

## Phase C — registers for what remains (≈1 h each, mine)

Ordered by measured question count. Each is the same shape as the seven already built: a
mapping in `ontology/record_documents/`, a document in `input/documents/`, a class in Module R
with `ontosage:layTerms`. **No code.**

### C1. `schedule_state` — what is on, due, closed or reassigned *today* · ~188 questions

18.4% of the unanswered ask about timing and current state — *"which rooms must be ready
first"*, *"is this closed today"*, *"when is the next window"*. Individual registers each
answer this for their own domain; nothing answers it **across** them.

Columns: subject, subject_kind, state (on / due / overdue / closed / reassigned), effective
window, reason, replaces, owner. One row per thing whose availability changes today.

### C2. `risk_exception` — open exceptions and who owns them · ~75 questions

7.3% ask about risk and exceptions. `RiskAssessment` holds 6 records of *assessments*;
nothing holds the **open exceptions** those assessments raised, their escalation state or
their owner. The registers already surface exceptions in prose (`patrol_checkpoint` has three
open, `approval_evidence` has four findings) — this makes them countable and cross-cutting.

### C3. Space **approved purpose and capacity** baseline · 43 questions · leadership at 8%

Leadership is the worst-served role in the corpus and asks a shape nothing else does:
*"which spaces have materially drifted from their approved purpose, capacity or service
requirement?"* Drift is computable only against a recorded baseline — approved purpose,
approved capacity, approved service level, per space, with the approval that set it.

Pairs naturally with `approval_evidence`, which already records who approved a space use.

### C4. Event **agenda** rows · 42 questions · prospective students at 26%

`public_event` answers admission, entrance and check-in. Prospective students ask about the
*inside* of the event: *"how much time for the course talk, tour and questions"*, *"we only
have two hours, what should we prioritise"*, *"where can my family wait quietly between
activities"*. One row per activity within an event: sequence, duration, location, whether a
companion may attend, whether it is optional.

---

## Phase D — measurement integrity (≈2 h mine + 7.5 h machine)

### D1. CAVEAT-418 — the grader marks computed answers as honest declines

Four of twelve "regressions" in the V8 re-measure were computed answers carrying a qualifying
sentence. `_heuristic_grade` tests for capability phrases *before* it tests for computation.

**This changes the number, not the system**, and it changes it upward — every coverage figure
reported so far is a floor. Fix it before the final re-capture so that run is graded correctly,
and re-grade the existing captures with the corrected grader so the comparison stays valid.

**Do not simply reorder the checks.** The reverse error — marking a decline that mentions a
number as computed — is BUG-370 and BUG-191, both of which cost this project a fictitious
score. Needs a labelled set swept before and after.

### D2. One full re-capture of all 2,960 · ≈7.5 hours machine

**At the end, not before.** Re-measuring between changes spends hours on a configuration
about to be abandoned. This produces the single headline number for all 37 catalogues, graded
by the corrected grader, on one model, with provider and model stamped per row.

---

## Sequence and cost

| phase | item | my time | machine | blocks |
|---|---|---:|---:|---|
| **A** | Capture the 480 occupant questions | — | 1.2 h | Phase C order |
| **B** | Class selection scoring | 2 h | — | Phase C value |
| **C1** | `schedule_state` register | 1 h | — | |
| **C2** | `risk_exception` register | 1 h | — | |
| **C3** | Space purpose/capacity baseline | 1 h | — | |
| **C4** | Event agenda rows | 1 h | — | |
| **D1** | Grader fix + re-grade | 2 h | — | D2 |
| **D2** | Full 2,960 re-capture | — | 7.5 h | — |
| | **total** | **~8 h** | **~9 h** | |

A and D2 are unattended. B must precede C, because every register added makes class selection
harder. D1 must precede D2, or the final number is measured with a grader known to
under-count.

## What is deliberately not in this plan

- **Person records**, under any register. V7-T35, and the catalogues forbid it. Only 11 of the
  1,023 mention a person and every one asks who is *accountable* — a role.
- **Design-judgement questions.** 243 of `policy_governance`'s 283 ask architects *"where
  **should** zones begin and end"*. A register cannot answer those and should not pretend to.
- **`weather_external`.** Still WIRED with 0 rows (NOTE-413), worth 79 questions, but it is a
  live feed rather than a register — a different kind of work, and cheaper to leave until the
  register pattern is exhausted.
