# Deployment plan — Abacws (bldg1), 4 days to users

Written 2026-09-29. Target: a defensible deployment to real users at Abacws bldg1.
Source of truth for status stays `tasks/PRODUCTION_TRACKER.csv` and `tasks/FIX_TRACKER.csv`.

## The one sentence

Two things make this deployable and they are not features: **the same question must get the
same answer** (W6-01) and **an answer must arrive before the user gives up** (W6-02, median
is currently 100 s). Everything else is second.

## Why this order, and a correction

W6-01's own note is the argument: *"Six of fifty answers differed between two identical runs.
Until this closes, no single-run pass rate is trustworthy to better than about ten points."*
So determinism comes BEFORE the fresh measurement, not after — the tracker's existing
dependency (W7-01 needs W6-01) is correct.

Last hand-read quality on unseen questions: **26.6% weird, 8.9% confidently wrong**
(2026-09-20, BEFORE Waves 1–2). Nothing has been hand-read since. Three open P1s
(CAVEAT-784/788/790) say the automatic grader is unreliable in BOTH directions, so the
automatic numbers cannot stand in for that read.

---

## Day 0 — tonight, ~1 hour. Prove what is actually deployed.

Not optional: the stack is down, bldg1 is parked, and the running images may predate three
sessions of fixes.

1. Un-park bldg1 and boot (`CLAUDE.md` "Run building N", steps 1–7).
2. **Rebuild the images** — `docker compose build orchestrator rag-service` then `up -d`.
   Check `docker compose images <service>` CREATED against the last commit date. BUG-343.
3. Flush `resp_cache:*` AND `cache:sparql*`.
4. Baseline: `python scripts/regression_answerability.py` — expect 50/51 (the one is BUG-866).
   **If it is not 50/51, stop and find out why before any other work.**

Exit: health 200, images newer than `e0c14ae`, gate at its known number.

## Day 1 — determinism and latency. The two real blockers.

| Track | Work | Who |
|---|---|---|
| **Main (serial)** | **W6-01** determinism: cache the classifier decision per normalised question, make tie-breaks explicit | main thread |
| **Parallel A** | **W6-02** latency: profile the register and metadata lanes first. Forecasts are genuinely expensive and stay slow | agent |

Routing work is SERIAL — one rule at a time, regression gate green before and after
(`CLAUDE.md` V12 order rule). Do not parallelise it.

Exit: same question asked 5× gives one routing decision; median latency measured and the
top two contributors named.

## Day 2 — measure honestly, and take the cheap unlocks.

| Track | Work | Who |
|---|---|---|
| **Main (serial)** | **BUG-879** — the aggregate lane declines any question naming a place. Fixing it alone converts **W1-04 and W2-03** from PARTIAL to done | main thread |
| **Parallel A** | **W7-01** draw tail M (fresh held-out set; C–L are spent) and hand-read it | agent |
| **Parallel B** | **W3-04** design occupancy + **W3-05** last-seen per sensor (TTL + one lane each, disjoint files) | agent |

Exit: tail M read by hand with a weird/confidently-wrong rate you can state; two PARTIAL rows
closed.

## Day 3 — memory, and fix what the measurement found.

| Track | Work | Who |
|---|---|---|
| **Main** | Fix the top 2–3 failure CLASSES tail M exposes (class-level, not case-level — that is what moved 61%→26.6% last time) | main thread |
| **Parallel A** | **W5-01** rolling session summary + **W5-02** carry it on every entry point | agent |
| **Parallel B** | **W3-02** calibration register (one register, one lane, pinned by a test) | agent |

Exit: the failure classes are fixed and re-asked; a 60-turn conversation still answers about
turn 3.

## Day 4 — freeze, re-measure, decide.

1. **W7-02** — re-run the 73-question pack and re-read every answer by hand.
2. **Write the supported scope**: what the system answers, what it declines, and what it must
   never be asked. This is the document that makes a deployment defensible; without it every
   out-of-scope confident answer is your problem.
3. Park bldg1, run `pytest -m unit` IN THE PARKED STATE, commit, tag.

### Go / no-go, decided on numbers not feeling

| Gate | Threshold |
|---|---|
| Answerability gate | ≥ 50/51 |
| Determinism | same question, same route, 5/5 |
| Median latency | under 30 s (100 s today) |
| **Confidently wrong on tail M** | **< 5%** — this is the one that matters |
| Supported scope | written and agreed |

A confidently wrong answer about a refuge point, an AED or a CO2 level is the failure that
ends a pilot. Declining is recoverable; being confidently wrong is not.

## What I cut if we fall behind (none are deployment blockers)

W5-03 / W5-04 (cross-session memory), W4-01 / W4-02 (provenance intent), W3-03 (parking
tariff — an honest decline is already correct), W2-03's interval arithmetic beyond what
BUG-879 gives for free.

## Standing rules while working fast

* Routing changes are serial, one rule at a time, gate green before AND after.
* A long pytest run PINS the tree — do not edit any `.py` while one is running (#101).
* Never write Python source through a shell heredoc (#125).
* Flush BOTH caches after any data or code fix, or the change is invisible.
* Re-ask the question by hand. The suite passed through every worst defect this project has had.

## Needs the owner (blocking two rows)

* **W0-08** — confirm the three defibrillator positions. Also closes **BUG-858 (P1)**, where an
  AED position is asserted as fact while the same record calls it unverified.
* **W3-01** — is a real outdoor weather feed available, or should it be modelled?

---

## Progress, end of 2026-09-29

**Suite, bldg1 ACTIVE, final: 12,932 pass / 0 fail / 54 skip / 3 xfail (16m47s).** Two earlier
runs the same day, same tree: 12,879/3 in 1h07m and 12,905/1 in 16m21s. The 3 were
order-dependent flakes in one new instrumentation file (11/11 alone, 226/226 in a slice) and
**did not recur**. The 1 was real and fixed: a test asserting a contiguous substring that
`black` had wrapped across lines, so a correctly wired hook failed a test about formatting
(lessons #151). The 4x spread in wall clock came from a live probe holding the stack, not from
the tests (lessons #152). One hypothesis for the flakes — a leaked `time` patch — was checked
against the tree and **disproven**; do not spend it again. The PARKED number is still owed and
is what gates a commit (Workflow rule 8).

### Verified live this day (re-asked after restart, both caches flushed)

| ID | Severity | What it did |
|---|---|---|
| BUG-936 | P1 | "energy this week vs last week" answered about **W38 vs W39 on a day in W40** and reported a **19% decrease** where the truth is a **22.7% rise** |
| BUG-940 | P1 | a follow-up saying "there" was rewritten to **"Telecommunications Room 1.34"**, a room the user never named, and answered with a mean, a range and no hedge |
| BUG-904 | P1-shaped | the publication gate needed a COMMA before a fourth digit, so `1,240 ppm` was a claim and **`1200 ppm` was not** |
| BUG-879 | — | room comparisons declined entirely; blocked W1-04 and W2-03 |
| CAVEAT-938 | P2 | one room's single sensor labelled `5 mean` — a room's reading wearing floor 5's name |
| BUG-937 | P2 | quoted a spread of 4.0 from its own range of 20.4–25.4, then drew the opposite conclusion |
| CAVEAT-892 | — | "outdoor temperature" bound a synthetic green-roof proxy over the live weather feed |

### Three plan premises were wrong, and each was measured rather than assumed

* **W6-01 (routing determinism).** 10 questions x 5 asks, fresh chat each: **0 of 10 unstable.**
  Routing was ALREADY deterministic. The variance the row was opened about is in GENERATION.
* **W6-02 (latency).** **4.46 s p50 over 48 requests.** The register and metadata lanes are not
  where the time is. No reduction was shipped and none is claimed; what shipped is the
  instrument (`plan_trace.stage_ms`, now on `/v1` too). dialogue 43.1%, sparql 28.1%.
* **W5-01/W5-02 (session memory).** The summary IS built and IS injected on all four entry
  points — 453 chars, confirmed in the log. **Nothing consumes it for a referent** (BUG-941).

### Three of my own claims were wrong and are corrected on the record

CAVEAT-892 was logged FIXED on a hand-run SPARQL query **that was not the query the code sent**
(one class against eight) — it verified the intent, not the code. BUG-879's first fix lifted a
gate that was not the one shut. BUG-936's first root cause was a guess that one line of
container log disproved. **lessons #145, #146, #149, #150.**

### Still open, in the order they are worth doing

1. **BUG-921** — a 4.27 s RAG fetch and an LLM summarisation sit ABOVE the classifier cache
   lookup and are discarded on every hit. Not side-effect free: the skipped block assigns
   `state.summary`, which `_orchestrator.py:5071` also reads. Highest-value latency work left.
2. **BUG-939** — the fetch ignores the period the question names (fixed 30 days), then a
   1000-row-per-sensor cap clips it further. **Read CLOCKS in CLAUDE.md first**: three wrong
   fixes and a withdrawn P1 came from measuring MySQL through a non-UTC session.
3. **BUG-941 / W5-04** — a question about the CONVERSATION routes to a data lane.
4. **W2-03 and W3-01** — both need their OWN acceptance question asked, not a proxy.
5. **W7-01 / W7-02** — the fresh held-out set, LAST, per the plan's own sequencing.

---

## Later the same evening — three more fixes, all verified live

| ID | what it did |
|---|---|
| **BUG-947** (part) | "what kind of data is collected?" — the first question anyone asks — answered *"I don't have that specific information on record… contact your facilities team"*, then offered waste collection records. It now names all 45 modalities. |
| **BUG-950** | a decline's "nearest things I can answer" was the **first four modalities alphabetically**, omitting the one that WAS the answer: `pm25`, of which the building holds 210 sensors. It now leads with it. |
| **BUG-921** | 4.27 s of RAG fetch sat ABOVE the classifier cache lookup, discarded on every hit. Dialogue stage on a hit **17,270 → 132 ms**; probe median 21.0 → 13.0 s. |

**Two gates, not one.** BUG-947 is worth reading as a method note. Teaching `CAN_MEASURE_RE`
about the verb "collect" routed the question to the reach lane — which then answered "Which
space did you mean?", because the branch that lists measurands is gated on `OPEN_QUESTION_RE`
instead. **Widening one gate looks like a fix if you only check the route.** It was caught by
asking the question, not by reading the diff.

**Two fixes reverted on purpose, and the attempts are the record:**

* **BUG-948** — `"escalation route"` ranks Department at 32.0; `"escalation routes"` ranks
  nothing, because `<term>` ends at the "s". The obvious fix broke a guard test that
  rejects `WorkspaceProfile` **by name**. Cause found exactly: `WorkspaceProfile` carries the
  generic phrase "eligible alternative" as a NAMING term and scores 40 against `Booking`'s
  legitimate 8. The module already has `qualifiers` for precisely that, and the set is empty —
  so the fix is two ordered steps, and doing the second first trades a known false decline for
  an unknown wrong answer. **A guard test that fails your fix is doing its job** (lessons #153).
* **BUG-947 cause (2)** — `ConfigurationPeriod`'s 2,175 records are invisible because the class
  has no `subClassOf` link to the record roots. One triple fixes it, in the **core** schema —
  which lands for every building and turns a provenance structure into a user-facing register.
  Decide that deliberately.

**New this evening:** BUG-949 (the deliberation lane drops a stated scope constraint silently,
and a deictic floor does not bind where an explicit one does — measured at the compiler),
CAVEAT-951 (on a cold container a decline omits every measurand with no sign the catalogue was
unavailable — *unavailable is not absent*).

---

## The regression gate, all five runs — the honest record

| run | after | result |
|---|---|---|
| 1 | the day's routing/comparison fixes | **51/51** |
| 2 | BUG-921, the classifier-cache move | **51/51** |
| 3 | BUG-947, the observability widening | **51/51** |
| 4 | BUG-950, the decline-wording change | **51/51** |
| 5 | BUG-897, the declared-capacity composition | **50/51 + 1 intermittent** |

**Zero REGRESSED in all five.** Run 5's case #59 ("What is the nearest accessible toilet to
room 3.10?") failed its first pass and answered on re-ask. The harness refuses to count that as
passing — *"the lane is not gone; it is not reliable either"* — which is the right call and is
the "report first-pass failures" rule working.

**It is not attributable to the change**, and that was checked rather than assumed: #59 came back
`ok` in all four earlier runs the same day (15.4 s, 18.1 s, 12.8 s, 11.6 s), and the
declared-capacity gate cannot fire on it — the question names no capacity property. It is
generation variance in that lane, which is what W6-01's corrected premise says the real
run-to-run instability is.

## The occupancy defects — what was fixed and what was not

A declared safety limit was being answered from a sensor's observed peak: *"What is the maximum
occupancy of room 2.15?"* → **"30.00 people"**, where the graph declares **40**. And *"design
occupancy of room 5.01"* → *"not recorded in the data"*, where the graph declares it **twice**
(25 and 20, which disagree — BUG-896, a DATA conflict for the owner).

The declared figure was already on the bus, offered to the narrator as a **hint**, and the
narrator answered from the sensor anyway. It now **composes** in `_response_node` — the one place
every lane passes, which matters because the old hook sat inside `_analytics_node` and room 5.01
routed through `sensor_data`, so it never ran.

**Three attempts at the skip condition were wrong, and each is recorded rather than tidied away:**

1. `publication_gate.is_decline` returns **False** for the commonest decline this system emits,
   so it cannot detect one (**CAVEAT-952** — it is a shared classifier other code reasons from).
2. Skipping when any declared figure appeared anywhere tested nothing: room 5.01 declares 20 and
   25, and the sensor text contained **"at 25 Sep 01:22"** — a date. Now idempotent on the
   sentence.
3. A truncated `tail` made me briefly think the fix had not fired when it had.

**Residual, stated plainly (BUG-953):** the declared figure is now always present and the false
denial is gone, but the narrator still asserts the observed peak *as* the limit — so the answer
contains the correct figure **and a contradiction of it**. Whether it denies or invents varies
run to run. The additive approach has reached its limit; the two candidate ways to constrain the
narration are written down in that row rather than attempted as a fourth variant.
