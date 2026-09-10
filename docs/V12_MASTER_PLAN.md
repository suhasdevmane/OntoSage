# V12 — the plan after the supervisor review

**Date:** 9 September 2026
**Built from:** `docs/OntoSage_Architecture_Review_Corrected_v1.1.pdf` (33 pp.) ·
`docs/V11_PHASE0_INVENTORY.md` (its nine risks checked against the running code) ·
the V10 and V11 leftovers · `tasks/FIX_TRACKER.csv` (494 rows, the live defect log)
**Execution:** [`tasks/V12_TRACKER.csv`](../tasks/V12_TRACKER.csv) — 31 rows, one file
**Proof:** [`tasks/V12_LEDGER.csv`](../tasks/V12_LEDGER.csv) ·
[`tasks/V12_WONTDO.csv`](../tasks/V12_WONTDO.csv) · `python scripts/v12_coverage_audit.py`

---

## 0 · Scope, and what was deliberately left out

V12 covers exactly four sources:

| Source | Open items |
|---|---:|
| Supervisor review — tickets T01-T10, cases A01-A16 / B01-B16 | 42 |
| `tasks/FIX_TRACKER.csv` — non-closed rows, plus closed rows whose own text says work is owed | 43 |
| `tasks/V11_TRACKER.csv` | 14 |
| `tasks/V10_TRACKER.csv` | 6 |
| | **109** |

**V5, V6 and V7 are out of scope, by decision on 9 September 2026.** Their substance
shipped; what survives in those CSVs is stale status, not open work. A spot-check agreed on
the load-bearing rows — freshness and staleness thresholds are implemented,
`answer_provenance.py` exposes the provenance chain, `enablement_hint` makes declines
specific, and the golden-baseline harnesses exist. (My first grep said otherwise and my
first grep was wrong: `grep -E` treats `\|` as a literal pipe. The measurement apparatus
was the bug again.)

**Two concepts from those plans had NO code when checked**, and are the only candidates for
resurrection: `CONFLICTED` as a distinct verification state (V7-T12), and purpose-bound
permission as opposed to role-only (V7-T16). If either is wanted, **file it as a new
`FIX_TRACKER` row** — that is what makes a thing current — rather than reviving a
three-week-old status column.

---

## 1 · What the code inspection changed before any repair was planned

The reviewer read a PDF, not the repository, so its risks are predictions. Three of them
resolved differently once checked, and that changed the plan:

**R7 is already closed.** All 37 intents audited: every lane's bus key is read on the
response path, zero uncollected. So V12-07 is a **test, not a repair** — the review's own
warning about treating a historical defect as still open, applied to itself.

**R6 resolves in our favour.** 35 LLM call sites, three lanes generating executable
artifacts — and every one already passes a control, with the Python sandbox verified **live**
to have no network egress at all. That is why case **B16 is closed as conditional** rather
than scheduled.

**R4 is worse than the review assumed.** 3,004 points declare simulated, **zero declare
measured**, 1,342 are silent — and silence reads as measured. `scorer.py` contains no
reference to provenance, admissibility or eligibility; it filters on `Hardness` alone. A
simulated candidate can win a ranking and is merely *labelled* in a table underneath. That
moved from "inspect" to **V12-04**, the largest single row.

---

## 2 · The order, and why it is this order

**The verification debt is paid before the routing work.** Every expensive mistake in this
project has the same shape: a guard added for one question shape quietly took another with
it, and nothing noticed until someone asked. BUG-431's first fix corrected *"how many CO2
sensors"* and began answering it with the building-wide total. W0-2's inversion was safe
**only** because seventeen probe cases were written first, one per escape clause.

So **V12-01 leads**, and **no routing change lands without the probe green before and after,
one rule at a time.**

### The order, revised 9 September 2026

Two corrections were applied to this section on the day the work started. Both were found by
summing the tracker instead of reading this paragraph.

**Correction 1 — "V12-01 → V12-08, about 12 days" did not reach Gate A.** Gate A (review
p. 22) requires a documented supported scope, hard-gate regressions, every quantitative claim
reproducible *with matching scope, units, interval and origin*, rankings using ARBITER's
dossier, simulated kept distinct from observed, published cases and rubric, and **zero known
unresolved misrepresentation or privacy failure in scope**. Rows 01-08 deliver none of the
last five. Calling rows 09-31 "the register that proves nothing was lost" undersold ten days
of gate-critical work — rows 09/10/11 *are* ticket T05, and "matching units and interval" is
in the gate text itself.

**Correction 2 — V12-26 was scheduled at 26 and the review makes it a prerequisite.** T03,
T04 and T05 each say *"After T01-T02"*; T06 says *"After T01"*. T01 is the supported-scope
statement, which is V12-26. It moved to **order 3**. It costs one day and it can only shrink
the twelve rows behind it: anything declared out of scope is work not done.

**The active subset is the 15 rows flagged `gate_a=yes`, worked in `order` 1-15.**

| # | Row | Why it is in the gate |
|---|---|---|
| 1-2 | V12-01, V12-02 | The probe gates every later change; the owed re-asks clear rows falsely marked closed |
| 3 | **V12-26** | T01 — the supported scope, moved from 26 |
| 4-8 | V12-03..07 | Publication (R1), simulation (R4), typed outcomes (R3), the unserved half, the collection contract |
| 9-12 | V12-08..11 | T05 — one resolved interval, counts, units, shared labels |
| 13 | V12-17 | Gate A's "zero privacy failures in scope" |
| 14 | V12-25 | Gate A's "rankings use ARBITER's dossier" (review: T08 after T04-T06) |
| 15 | V12-29 | T09 — the held-out set, run once, and the Gate A decision. Must be last. |

**Gate A subset: 22.0 days over 15 rows. Post-Gate-A backlog: 20.0 days over 16 rows.
Total 42.0 days** — not the ~44 this document claimed, which was arithmetic nobody re-derived,
the same failure the review's own correction C02 records against the source note.

`needs_gpu` is a column, not a second file. Counted from the file, not asserted: **yes**
(**7** rows) needs a live model throughout, **no** (**11**) needs none, **partial** (**13**)
builds and tests offline then verifies on live turns. This paragraph previously said 12/10/9.

---

## 3 · What changed from V11

| Item | V11 | V12 | Why |
|---|---|---|---|
| Scope | review + V10 remainder | + the whole live defect log | V11 read only the four rows marked `OPEN` and missed the `PARTIALLY_FIXED`, `MITIGATED` and owed-re-ask rows, which are the same thing wearing a friendlier word |
| Completeness | asserted in prose | `scripts/v12_coverage_audit.py`, exit code | A prose claim rots on the next bug |
| Owed live re-asks | 4 named in passing | **V12-02**, seven rows, one session | A row at `FIXED` that says "live re-ask owed" is not fixed |
| Unit conversion (A11) | absent | **V12-10** | In no plan anywhere |
| Cache vs authorisation (B12) | absent | **V12-16** | Same |
| Return contracts (A01/A02) | absent | **V12-12** | BUG-476 was literally A01: a function with no `return`, whose `None` became an empty answer |
| Default-graph shadowing | absent | **V12-15** | BUG-194 was a P1 whose row closes *"other subjects may be shadowed the same way — not yet verified"* |
| The four open routing rows | absent | **V12-23** | BUG-395's routing half, CAVEAT-396, BUG-231, BUG-354 — code landed, behaviour did not |
| Ordering | honesty before portability | **unchanged** | The review's reasoning holds |
| Gate A as the target | chosen | **unchanged** | Still the right target for a thesis demo |
| W3-2 / W3-3 scaffolding | deferred | **still deferred** | The review agrees: defer until V12-30's manual second onboarding shows which work repeats |

---

## 4 · How completeness stays true

`scripts/v12_coverage_audit.py` re-derives the open set on demand rather than trusting a
saved list. It counts as open every non-closed `FIX_TRACKER` status — including the ones that
read like success, `PARTIALLY_FIXED`, `MITIGATED`, `READY`, `FIXED_UNVERIFIED` — **and** every
*closed* row whose own Verification text says `LIVE RE-ASK OWED`, `OWED:`, `RESIDUAL`,
`WHY UNVERIFIED` or `DECISION NEEDED`. Then it asserts each derived id is claimed by exactly
one V12 row or listed in `V12_WONTDO.csv` with a reason.

It fails three ways: **uncovered**, **claimed twice**, and **stale coverage** — a row claiming
something no source calls open, which is how a plan quietly starts describing finished work.
It found five errors in this plan on its first run and two stale won't-do entries on its
last. It also refuses to run when `tasks/` is absent rather than reporting a clean sheet from
a starved input.

Current: **109 derived · 86 scheduled · 23 dispositioned · 0 uncovered · 0 stale.**

---

## 5 · What is deliberately not being done

Twenty-three items in `tasks/V12_WONTDO.csv`, each with a written reason:

- **Deferred, with the review concurring (5)** — the register scaffolder, the 24 TTL
  templates, the packaging half of W3-5. The `.env.example` and deployment-truth half *is*
  scheduled, as V12-27.
- **Closed residuals (6)** — rows whose "residual" names something fixed in the same row or
  tracked under another id.
- **Cosmetic (2)** — BUG-134 and BUG-135 leave one stale label in GraphDB's default graph.
  The *mechanism* is not cosmetic and is V12-15; these two instances are.
- **Folded elsewhere (3)** — CAVEAT-006's nested census is an aggregation contract failure
  (V12-09); CAVEAT-418's grader residual belongs with V12-29's grading discipline.
- **Conditionally closed (1)** — B16, settled by the LLM inventory.
- **Decided or accepted by the user (2)** — CAVEAT-404's +1h stamps, TODO-049's reload.
- **Already fixed on 2026-09-09 (3)** — CLAUDE.md's two active workstreams and its stale
  open list, and the divergent V7 tracker copies.
- **Needs you (1)** — CAVEAT-233.

---

## 6 · Two things that need you, neither blocking

1. **CAVEAT-233** — should the publisher feed every declared stream? 683 of 2,796 declared
   sensors report in the last 24 hours. A dev-data decision, not a defect.
2. **The multi-model benchmark is blocked on a paid plan.** Twelve of nineteen hosted models
   return HTTP 403 *"requires a subscription"*. It is not a V12 row because it is not work we
   can do; if the plan appears, it becomes one. **A seven-model benchmark must not be
   reported as if it were the planned one.**

---

## 7 · How progress is measured

*"Do not measure progress by the length of the todo list."* V12 has 31 rows and that number
means nothing. Four metrics, each with a denominator:

| Metric | Definition |
|---|---|
| Substantive-answer correctness | outputs whose substantive claims all pass the rubric / all substantive outputs |
| Answerable-request completion | correct full completions / supported, authorised, answerable requests |
| Unnecessary abstention | deliberate abstentions on answerable cases / same denominator |
| Operational outcome | **first-pass success, timeout, error and retry recovery reported separately** |

**The retry rule applies retroactively.** A run reported as "49/50, the failure passed on
retry" is a **first-pass failure that recovered**, and stays visible as such.

**And the uncomfortable one:** all 50 probe cases have been used to tune the implementation,
so none is held-out evidence. Adding cases to that set cannot fix it. V12-29 draws a sealed
set and runs it once, at the end.

---

## 8 · Standing method

- **The probe is the gate, not the report.** Run it before a routing change and after.
- **Ask the system, do not only test the code.** BUG-473 through BUG-478, BUG-481, BUG-485
  and BUG-486 were all found by asking a question. The suite passed throughout.
- **A measurement that disagrees with the system is usually the measurement.** Four of five
  P1s in one session were in graders and harnesses — and the first grep in §0 of this
  document was wrong the same way.
- **Verify the process, not the file.** `/app` is bind-mounted; check `StartedAt`.
- **A source fix is not a deployed fix.** Compose builds a per-building image and `restart`
  never rebuilds it.
- **Park all buildings before every commit or push** (Workflow rule 8), and never commit
  without explicit approval.
