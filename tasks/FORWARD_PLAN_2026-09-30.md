# Forward plan — everything still open, 2026-09-30

Derived from `tasks/FIX_TRACKER.csv` (932 rows; **83 OPEN / PARTIALLY_FIXED / FIXED_UNVERIFIED**
found on or after 2026-09-18) and `tasks/PRODUCTION_TRACKER.csv` (9 rows not DONE). Nothing here
is invented: every item names a tracker row.

---

## The finding that should order the work

**About thirty of the 83 were logged on 2026-09-18, during the Stage-2 unscripted read, and have
not been re-asked since.** Waves 1 and 2, the readiness push, and 2026-09-29/30 have all landed
on top of them. At least one is provably stale already:

* **CAVEAT-844** — "No outdoor weather is held (no weather feed); weather questions decline
  honestly." A live Open-Meteo feed has existed since 2026-09-29 (BUG-888, CAVEAT-892), and
  "what is the outdoor temperature right now?" answers 21.9 °C from it.
* **TODO-789** — "FREEZE 2026-09-18 08:45 — no source change after this point until the demo."
  The demo was 2026-09-18. This row is expired, and it currently reads as a live prohibition on
  every change made since.

So the first wave is **not fixing — it is asking.** A row that no longer reproduces costs nothing
to close and stops the next session budgeting for it. A row that still reproduces gets a fresh
observation, which is worth more than the eleven-day-old one it replaces. This is the discipline
CLAUDE.md states twice: *ask the running system before building what a row names* (lessons #133,
#136), and *a static completeness claim rots*.

**Second ordering rule: the measurement apparatus comes before anything it measures.** Five of the
nine open P1s are about the GRADER, not the system — CAVEAT-784 (honest declines 42 → 7 under our
own new wording), CAVEAT-788 (the ANSWERED bucket inflating too), CAVEAT-790 (the headline
improvement is not statistically significant), CAVEAT-791 (the headline covers 48% of the bank and
excludes the worst performers), BUG-785/787. The project's own hardest-won lesson is that **the
measurement apparatus was wrong more often than the system** — four of five P1s in one earlier
session were in graders, and the same weak heuristic hid a fabrication one day and manufactured a
perfect score the next. No quality number should be published until these are settled.

---

## Wave A — TRIAGE (do first; it is measurement, not change)

Re-ask every open row that names a concrete reproducing question, and close the ones that no
longer reproduce. **Read-only on source.** Output is tracker status plus a fresh observation.

Candidates with a question in the row: BUG-774, BUG-775, BUG-808, BUG-809, BUG-810, BUG-811,
BUG-812, BUG-813, BUG-814, BUG-815, BUG-825, BUG-826, BUG-827, BUG-828, BUG-829, BUG-830,
BUG-831, BUG-832, BUG-835, BUG-836, BUG-837, BUG-838, BUG-860, BUG-880, BUG-894, CAVEAT-833,
CAVEAT-834, CAVEAT-843, CAVEAT-844, CAVEAT-847, CAVEAT-903.

Known-stale, close with the evidence: **CAVEAT-844** (the weather feed exists), **TODO-789** (the
freeze expired eleven days ago).

**Grade honestly.** A row is closed only when the question is asked and the answer read; "probably
fixed by Wave 1" is not a verification. Two labels in an earlier wave were wrong until the source
table was checked (lessons #121).

## Wave B — THE FALSE-DECLINE CLUSTER (largest measured quality lever)

One shape, measured on the held-out tail M: **a lane identifies the right register and does not
read it.** Four of seven false declines named the register in the same sentence as the refusal.
11.3% of held-out questions.

* **BUG-947** (P1, PARTIALLY_FIXED) — five causes remain, each already diagnosed in the row.
* **BUG-948** — a trailing "s" ends a `\b<term>\b` match. **Cause found exactly:**
  `WorkspaceProfile` carries the generic phrase "eligible alternative" as a NAMING term and
  scores 40 against `Booking`'s legitimate 8. **Two ordered steps: move generic modifier phrases
  into `qualifiers` FIRST, then apply plural tolerance.** Doing the second first trades a known
  false decline for an unknown wrong answer, and over-capture is the worse direction (BUG-893).
  A guard test that fails the fix is doing its job (lessons #153).
* **CAVEAT-922** — the register lane's two paths differ by 40×; all four slow cases were the same
  question failing on one word (`could not place: communication`).
* Same family, pending triage: BUG-774, BUG-811, BUG-836, BUG-838, BUG-860, BUG-894.

## Wave C — SCOPE AND REFERENCE

* **BUG-949** — the deliberation lane drops "public seating area", "meeting room" and "this floor"
  with **no signal to disclose**; measured at the compiler (`spatial=[]` for all three, while "on
  floor 3" binds). Two halves wanting opposite treatment: a DEICTIC scope should ASK (the
  clarification lane already writes the right sentence for "this room"); a SPACE TYPE should be
  DISCLOSED, copying `build_assumptions`' forecast-horizon precedent.
* **BUG-943** — a deictic binds to the most RECENT user-named place, not the declared subject.
  Resist over-fixing: recency is defensible. The cheap honest improvement is **disclosure** —
  "taking 'there' as floor 1" — so a wrong guess costs one correction, not a wrong number.
* Pending triage, same family: BUG-810, BUG-813, BUG-825, BUG-827.

## Wave D — TIME AND WINDOW

* **BUG-939** — the fetch ignores the period the question names (fixed 30 days), then a
  1000-row-per-sensor cap clips it further. **Read CLOCKS in CLAUDE.md first**: three wrong fixes
  and a withdrawn P1 came from measuring MySQL through a non-UTC session (lessons #103).
* **BUG-946** — a "tomorrow" comparison never reaches the forecaster; W2-03's acceptance.
* **BUG-945** — "how does today compare with the outside temperature" is read as a forecast
  request; W3-01's acceptance.
* **BUG-874** (PARTIALLY_FIXED) — a forecast asked for a MEAN returns an hourly table.
* Pending triage: BUG-826, BUG-828.

## Wave E — NARRATION HONESTY

* **BUG-953** — an occupancy answer now states the declared capacity AND asserts the observed peak
  as the capacity. The additive fix has reached its limit; the narration must be constrained.
* **CAVEAT-951** — on a cold container a decline omits every measurand with no sign the catalogue
  was unavailable. *Unavailable is not absent*; the observability lane already writes the right
  sentence for its own cold case.
* **CAVEAT-952** — `publication_gate.is_decline` returns False for the commonest decline this
  system emits. Derive the marker set from the source that emits it, and verify against all 73
  stored answers (lessons #141).
* **BUG-898** — one planner answer gave two occupancy figures for one room, 190× apart. Not
  diagnosed; needs the turn traced to see which lane bound the 4,401.86 series.
* Pending triage: BUG-829, BUG-832, BUG-814, BUG-837, BUG-809, CAVEAT-833.

## Wave F — MEASUREMENT APPARATUS (before any published number)

* **CAVEAT-784** (P1) — the calibrated grader is gamed by our own new wording: honest declines
  42 → 7.
* **CAVEAT-788** (P1) — the ANSWERED bucket is inflating too; both buckets move.
* **CAVEAT-790** (P1) — the headline quality improvement is **not statistically significant**.
* **CAVEAT-791** (P1) — the headline covers 48% of the bank and **excludes the worst performers**.
* **BUG-785 / BUG-787** (P1) — the register census printed to the reader on 23 answers; run 6
  regressed the bank 61.2% → 65.3% weird.
* **CAVEAT-887** — marker-based decline detection cannot keep up with a system free to reword.

## Wave G — MEMORY AND PROVENANCE

* **BUG-941** — a question about the CONVERSATION routes to a data lane and is declined as if it
  were about the building. The session summary IS on the bus and that lane never reads it.
* **W5-03 / W5-04** — cross-session memory, and the long-conversation test that currently FAILS
  (`scratchpad/memory_probe.py`).
* **W4-01 / W4-02** — a provenance intent over the previous turn; publish the precedence rules.
* **CAVEAT-910** — an unbounded LLM summary generated on EVERY `/v1` turn, injected into the
  classification prompt, then discarded.
* **CAVEAT-911** (PARTIALLY_FIXED) — the live check is now done; W5-04's acceptance still fails.

## Wave H — OWNER DECISIONS (cannot be resolved without the owner)

* **BUG-896** (P1) — design occupancy declared twice and disagreeing for three spaces: Room 1.04
  50 vs 25, Room 4.01 25 vs 20, Room 5.01 25 vs 20. The CODE side is done and states the conflict
  honestly; **the DATA side is a decision only the owner can make.**
* **CAVEAT-842** — facts the owner must supply, deliberately not invented.
* **CAVEAT-843** — reception hours made consistent at 09:00–16:30 Mon–Fri: owner to veto.
* **CAVEAT-841** — room identity in the graph disagrees with the architect's drawings for 132
  rooms.
* **BUG-947 cause (2)** — one triple would expose `ConfigurationPeriod`'s 2,175 records, in the
  **core** schema, for every building, turning a provenance structure into a user-facing register.

---

## Standing rules for every wave

1. **Ask the running system before building what a row names** (lessons #133, #136). Four Wave-1
   rows asked for something already built; only the routing was missing.
2. **A source fix is not a deployed fix.** `./orchestrator` is bind-mounted, so a **restart** loads
   a `.py` change — but Python does not hot-reload, so the restart is required (BUG-343 covers the
   image case).
3. **Flush both caches before every measurement**, and use a fresh chat id per question. Identical
   questions come back in 0.0 s having never run, and never save a turn (BUG-662, lessons #149).
4. **The probe green BEFORE and AFTER any routing change**, one rule at a time. ALL rules run and
   the LAST one wins, so a corrective rule goes AFTER the one it corrects, and
   `test_precedence_order_is_pinned` updates in the SAME commit.
5. **Never write Python source through a shell heredoc** (lessons #125). It cost three separate
   repairs on 2026-09-29 alone.
6. **Redirect a long pytest run through `tee`, not `>`** (lessons #152), or a failure that does not
   recur leaves no evidence behind.
7. **Do not quote a suite or probe duration as a property** (CAVEAT-500). The same suite ran 67
   minutes and 16 minutes on the same tree.
8. **A guard test that fails your fix is doing its job** (lessons #153). Revert and log the
   attempt rather than editing the guard to suit the change.

---

# Outcome — four waves run in parallel, 2026-09-30

**Regression gate: 51/51, zero regressed, zero intermittent**, after four agents touched eleven
production modules and the ontology. Run once at the end, on a single coordinated restart, with
all three caches flushed.

## Verified live after the restart

| was | now |
|---|---|
| "escalation **routes**" → *"I could not find this in Abacws Building's documents"* | a table of six departments with contact, escalation target and out-of-hours route |
| "Do you have a maintenance crew?" → the same false decline | DEP-02 Mechanical and Electrical Maintenance with email, phone and hours — **and** *"the register does not record a separate 'crew' entity, only the department that performs the work"* |
| "meeting room" silently ignored, Academic Offices ranked | *"I could not narrow to 'meeting room' — the building model does not record which spaces are one — so this ranks every space considered and does not describe only meeting rooms"* |
| "this week vs last week" fetched a rolling 30 days, then truncated | `>= 2026-09-13 23:00:00` .. `<= 2026-10-04 22:59:59`, **W39 → W40**, **zero truncation warnings in 15 minutes of log** |
| a deictic silently resolved | *"Taking \"there\" as floor 1."* — and, in the same probe, an invented referent still **REJECTED** |

## What the waves found that the plan did not anticipate

1. **BUG-947's real root cause, which nobody suspected.** The decline's POINTER and the register
   SELECTOR use different matchers, and the pointer is the more capable one: `content_terms`
   singularises ("escalation routes" → {escalation, rout}) while `rank_record_classes` matches
   `\b<term>\b` and a trailing "s" ends it. **So the wording was never accidentally accurate** —
   the pointer really had found the right register and the selector could not reach it. That is
   why four of seven false declines name the right register in the same sentence as the refusal.
   Now logged at INFO, so the gap is countable rather than anecdotal.

2. **Two of my own prescriptions were measured and proved wrong.** BUG-948's step 1 (move generic
   phrases into `qualifiers`) cannot work: `_qualifier_score` returns 0.00 for BOTH test
   questions, which are grammatically identical at the critical phrase. And plural tolerance,
   measured over all **2,960** catalogue questions rather than the two guard cases, is wrong 25
   times in 79 moves. Reverted; the two real questions were fixed TTL-first instead, which cannot
   over-capture because nothing generic was added.

3. **A fix that would have re-broken yesterday's fix.** Fetching exactly the two weeks a question
   names would make `_bucket_size` compare two partial days — BUG-936's 291.7% rise — because it
   needs 1.5 units and two weeks on a Wednesday is 9.2 days against 10.5. The bounds reach one
   period further back, and the coupling is **pinned by a test** rather than remembered.

4. **A routing rule declined on principle.** BUG-946 routed to the forecaster as it stands gives
   one confident forecast of one floor presented as a two-floor comparison — worse than today's
   honest decline, because side assignment could only come from the sensor LABEL, which is
   BUG-884 exactly. The honesty half was built instead and the three owed steps written down.

5. **The grader's `--gate` passed the run-pair that decided the freeze.** It called run 6 the best
   of six where the hand read called it a regression, and exited 0 "GATE PASSED". Now exits 1
   "GATE NOT CALIBRATED" when a decline pattern shifts, and stays silent on the two pairs where
   wording was stable.

## The two new P1s, both independently re-verified

* **BUG-954** — "which rooms are occupied at the moment" answers **two**; measured at each
  series' latest reading, **372 of 514** are non-zero. Wrong by ~190×, the same magnitude as
  BUG-898 on the same quantity. Worth checking whether they share a cause.
* **BUG-955** — the same question named **1, then 6, then 0** alarms across three identical asks.
  The graph makes the truth exact: `acknowledgedAt` is on 264 of 270, so precisely six lack it,
  **two of them HIGH**. And the fetch is PERFECT every time — the LLM generates the right SPARQL
  and the store returns the right six rows. **All the variance is in the narration.** This is the
  clearest safety-relevant instance of what CAVEAT-891 describes: the route is deterministic, the
  answer is not.

## The observation that should shape the next session

Wave A's triage found that **five of fourteen CHANGED rows moved from a visible failure to an
invisible one**: a decline became a wrong answer, a decline became a silently mis-bound alert
*reported as success*, a wrong-content answer became a false decline. The jargon and refusal work
landed; what replaced it is harder to catch. That is the argument for Wave F before any published
number, and Wave F's own conclusion sharpens it: **whether a stated absence is TRUE is not
checkable from the answer text.** Only the graph can settle it, which is why tail M's seven false
declines needed a hand read.
