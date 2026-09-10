> **SUPERSEDED 9 September 2026** by [`docs/V12_MASTER_PLAN.md`](./V12_MASTER_PLAN.md),
> which sweeps the sources this plan never opened: V5, V6, V7 and the 494-row fix tracker.
> 156 unresolved items against this plan's 14. Its *reasoning* is unchanged and still
> governs V12 — Gate A as the target, honesty work before portability work, and the probe
> gating every routing change. Only its scope was wrong.

# V11 — implementation plan after the supervisor review

**Date:** 9 September 2026
**Inputs:** `docs/OntoSage_Architecture_Review_Corrected_v1.1.pdf` (33 pp., 9 Sep) ·
`docs/V11_PHASE0_INVENTORY.md` (the code-verified status of its nine risks) ·
`tasks/V10_REMAINING_PLAN.md` (the plan this replaces) · `tasks/V10_TRACKER.csv` ·
`tasks/FIX_TRACKER.csv` (494 rows)

---

## 0 · The decision the review demands first

> *"Choose the next target explicitly: a defensible demonstration of one building, a
> supervised operational pilot, or portable onboarding of another building… it does not
> treat the goals as interchangeable."* — p. 3

**Recommendation: Gate A — a defensible demonstration of bldg1, with a written supported
scope.**

Why not the other two. A **pilot** (Gate B) needs permission tests, a backend-outage
exercise, stale-series handling, a rollback path and an owner who responds to a broken
mapping — none of which exists, and none of which a thesis demo requires. **Portability**
(Gate C) needs a second-building run on the current revision; the review explicitly says to
defer the scaffolding for it until a manual second onboarding has shown which work actually
repeats.

What Gate A obliges us to do, and this is the part that bites: *"Require zero known
unresolved critical misrepresentation or privacy failures **in the demonstration scope**…
Do not advertise all 37 intents as equally reliable merely because each routes."* We
therefore have to **write down the supported scope and shrink it** until the honesty
guarantees hold across it.

---

## 1 · What the inspection changed

I checked the review's nine risks against the running system before planning any repair,
which is its own Phase 0 instruction. Three results changed the plan:

**R7 is already closed.** All 37 intents were audited: every lane's bus keys are read on the
response path, zero uncollected. The "lane computes and the answer is lost" incident is
historical. **We do not need the repair. We need the regression test.** This is the review's
own warning applied — *"do not treat a historical defect as still open"* — and it removes
roughly a ticket of work.

**R6 resolves in our favour, and against my own note.** 35 LLM call sites, three lanes
generating executable artifacts — but every one already passes a control, and the Python
sandbox has **no network egress at all** (verified live, not read from compose). The review
had to assume this was unknown. It is now documented.

**R4 is worse than the review assumed.** 3,004 points declared simulated, **zero declared
measured**, 1,342 silent — and `scorer.py` contains no reference to provenance whatsoever. A
simulated candidate can win a ranking and is merely *labelled* in a table below the answer.
This moves from "inspect" to the top of the build queue.

---

## 2 · What changed from the V10 plan, and why

| Item | V10 plan | Now | Why |
|---|---|---|---|
| **W4-4** — 7 W0 cases into the probe | #1 | **#1, unchanged** | Both plans agree it gates the routing work. The review adds a requirement: assert the **final output**, not only the route. The seven cases are now enumerated (inventory §5) — the review said the source did not list them. |
| **W2-1** — lexicon into routing | #2 | **moved to #6** | Not because it stopped mattering. It is a *portability* improvement, and R1/R4 are *release-gate* risks. A demo whose ranking can be won by simulated data is a worse demo than one with bldg1-shaped regexes. The review puts vocabulary in Phase 2, behind Phase 1's honesty work, and I agree. |
| **W2-5** — SPARQL few-shot from the graph | #3 | **moved to #7, conditional** | Review p. 16: *"Keep conditionally. First inspect which lanes actually generate queries and how examples are validated."* That inspection is now done (inventory §1): three lanes generate, all validated. So W2-5 is safe to do — and it must **not expand execution privileges** while removing building-specific examples. |
| **Publication enforcement** | *absent* | **#2** | R1. `grounded` currently decides only which memory bucket a turn is filed in. A boolean annotation is not a publication policy. This was not on our list at all. |
| **Simulation governance** | *absent* | **#3** | R4. See above. Not on our list at all. |
| **Typed retrieval outcomes** | *absent* | **#4** | R3. Our BUG-475/487 fixes were point repairs on two lanes; the seven-state distinction is systemic. |
| **Collection contract test** | *absent* | **#5** | R7 — test only, no repair, because the defect is already fixed. |
| **BUG-489** — held register beats absent on a generic word | open, ungated | **folded into #6** | It is the same "claim authority" question the review raises (p. 5). Do it with the probe, alongside W2-1. |
| **CAVEAT-467** — analytics latency | #9 | **stays last** | The review never raises latency as a correctness risk. Answers are ~14 s typical. Not a Gate A blocker. |
| **W3-2 / W3-3** — scaffolder, 24 templates | deferred | **deferred, now with backing** | Review p. 16 independently reaches the same conclusion: defer until a manual second onboarding demonstrates repeated work. |
| **Normalized request object** | *absent* | **#8, scoped down** | R2/T05. The review proposes a full versioned request envelope (p. 25). We have already fixed the two symptoms it was designed to prevent (wrong day, row-limit-as-count). I propose the **narrow version** — see §4. |

---

## 3 · The work, in order

Each item states what it closes, how it is verified, and whether it needs the GPU.

### #1 · W4-4 — the seven W0 questions become permanent cases · GPU
Closes: the gate for everything in §6. Review T02.
Add all seven (inventory §5) to `scripts/regression_cases.json` with **final-output**
assertions, not route assertions. Add the bldg3 leg.
**Done when:** probe covers all seven; a first-pass failure is reported as a first-pass
failure (see §5).

### #2 · Publication enforcement — `grounded=False` must withhold · offline build, GPU verify
Closes: **R1**, review T03, cases B04/B05.
Today `grounded` is read once and only routes the turn into `store_success` or
`store_failure`. Make a failed verification **change what the user receives**: withhold the
unsupported claim, state the limitation, and apply the same decision to the chart and the
export — the review is specific that all three must change.
Start narrow: `analytics`, `report`, `compare`, `trend`. Do not touch honest-decline paths.
**Done when:** a forced verifier failure cannot publish the affected claim through text,
chart *or* export.

### #3 · Simulation governance · offline build, GPU verify
Closes: **R4**, review T06, case B06. **Largest genuine gap.**
Three parts, in order:
1. **Positive provenance.** Assert measured origin where it is true, so silence stops
   defaulting to "measured". 1,342 points are currently silent.
2. **Per-observation, not per-store.** `synthetic_lookup(stored_at)` is a function of a table
   name; provenance must travel with the row.
3. **Admissibility in the scorer.** In operational mode, simulation-origin evidence is
   excluded *before* ranking, and the exclusion is stated — not merely displayed in a table
   under the answer.
**Done when:** an attractive simulated candidate cannot win an operational ranking even after
its values are transformed, and simulated coverage does not inflate measured coverage.

### #4 · Typed retrieval outcomes · offline
Closes: **R3**, review T04, cases A03–A06.
Implement the seven internal states (`NOT_DECLARED`, `REFERENCE_MISSING`,
`SERIES_UNRESOLVED`, `BACKEND_UNAVAILABLE`, `NO_OBSERVATIONS`, `INSUFFICIENT_QUALITY`,
`ACCESS_RESTRICTED`) with authorised external wording per state.
**Keep the review's qualification (C08):** where the adapter has no series catalogue, an
empty result cannot distinguish a broken identifier from an empty window — the honest state
is **unknown**, not a guess in either direction.
**Done when:** each state is seeded deliberately and neither an exception wrapper nor the
response collector converts a failure into ordinary success.

### #4b · A request whose second half went unserved must say so · offline build, GPU verify
Closes: the mixed-source misrepresentation. Review T07, case B14.
**Verified:** `_promote_to_capability_from_documents` returns immediately unless the intent is
weak, so *"which rooms were stuffy yesterday, and what does the manual say to do?"* returns the
observations and the procedure half is **never attempted and never mentioned**.
Cheap honest version first: detect the second, unserved sub-request and state it. Full
composition only if the demo scope needs it — the review is explicit this must be a *small
bounded rule*, not an autonomous planner.
**Done when:** a lane claiming a question is no longer treated as evidence that the whole
request was answered.

### #5 · The collection contract test · offline, cheap
Closes: **R7 regression**, review T07/B02. *No repair — the defect is already fixed.*
Promote the Phase-0 audit into a test: every declared intent's node writes a bus key that is
read on the response path. Fails when intent #38 arrives without a collector.

### #6 · W2-1 — the lexicon into routing, plus BUG-489 · GPU
Closes: the last building-shaped vocabulary; review's claim-authority concern.
Consume additively (generic OR lexicon, never lexicon alone). One rule at a time, probe
between each. Fold in BUG-489: a held register matched on a generic word should not outrank
an absent one matched on a specific phrase.
**Review's added requirement:** define ambiguous-name behaviour first, and test with another
building's labels.

### #7 · W2-5 — SPARQL few-shot from the live graph · GPU
Closes: six prompts teaching `Room_5.01`. Now unblocked by the §1 inspection.
**Constraint:** remove building-specific examples **without expanding execution privileges**.

### #8 · Narrow normalized request · offline
Closes: **R2** residual, review T05.
Not the full envelope on review p. 25. The two failures it was designed to prevent are
already fixed. What remains worth building is the **single-resolution rule**: resolve the
time interval once, carry it, and forbid the formatter from re-deriving it — which is what
made a report headed "Yesterday" describe that afternoon.

### #9 · CAVEAT-467 — deterministic aggregates · optional
Latency only. Not a Gate A blocker.

---

## 4 · What we are deliberately not building

**The full request envelope (review p. 25).** Proposed as illustrative, and the review says
so. Our CQ-IR already carries a typed interpretation for the deliberation lane; adding a
second, parallel request object across every lane is the "parallel framework" the review
warns against on p. 16. We take the invariant (resolve once, never reinterpret) and not the
schema.

**A separate evidence framework.** The review is explicit (p. 26): its lane and claim
contracts *"strengthen those existing concepts rather than requiring a separate reasoning
framework."* We extend `evidence/assemble.py`, we do not replace it.

**W3-2, W3-3, and the packaging half of W3-5.** Deferred, with the review concurring.

**Physical actuation.** Review p. 27: an ECA rule firing in a test should mean its condition
matched, *not* that equipment moved. Our engine is notify-only. Keep it that way for Gate A.

---

## 5 · How progress gets measured from here

The review is blunt: *"Do not measure progress by the length of the todo list."* Replacing
the count with four numbers, each with a denominator:

| Metric | Definition |
|---|---|
| Substantive-answer correctness | outputs whose substantive claims all pass the rubric / all substantive outputs |
| Answerable-request completion | correct full completions / supported, authorised, answerable requests |
| Unnecessary abstention | deliberate abstentions on answerable cases / same denominator |
| Operational outcome | **first-pass success, timeout, error and retry recovery reported separately** |

**The retry rule applies retroactively.** I reported a run as "49/50, the one failure passed
on retry". Under the review's rule (p. 14) that is a **first-pass failure that recovered**,
and it stays visible as such.

**The uncomfortable one.** All 50 probe cases have been used to tune the implementation.
By the review's definition (p. 14) **none of them is held-out evidence.** No amount of adding
cases to that set fixes it. Gate A needs a small held-out set written from the question corpus
and *not consulted* while fixing anything.

---

## 6 · Sequencing against the GPU

**Offline now:** #4 typed outcomes · #5 contract test · #3 parts 1–2 (provenance data and
plumbing) · #8 single-resolution rule.

**Needs the model:** #1 W4-4 · #2 publication enforcement (verify) · #3 part 3 (verify) ·
#6 W2-1 · #7 W2-5.

**Standing rule, unchanged and now endorsed by the review:** no routing change without the
probe green before and after. It is why W0-2 landed safely, and why BUG-489 is still open.
