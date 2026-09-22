# Plan: from 52/73 to a system that answers most questions

**Baseline, measured 2026-09-22:** `docs/supervisor_evidence_pack` — 73 questions asked through the
browser, 52 answer the question, 21 do not. `tasks/FIX_TRACKER.csv` holds 124 items needing
attention, of which 21 are P1. Parked unit suite: 12,286 pass, 0 fail.

**The finding this plan is built on.** The failures are not spread evenly across the system. They
concentrate in one behaviour: **a question that needs more than one read gets a lane that does one
read.** Two modalities at once (0/5), two periods at once (0/3), a negation over the model (0/2),
"which sources did you use" (0/2). The data exists in every one of those cases — other answers in
the same pack read it. So the shortest path to a large improvement is one capability, not twenty
fixes.

Everything below is building-agnostic: no rule, class or property names a building. A new building
supplies its own TTL and the same questions answer.

**Execution is tracked in one file: [`tasks/PRODUCTION_TRACKER.csv`](../tasks/PRODUCTION_TRACKER.csv)
— 32 rows, 16.5 days.** Every row carries why it matters, the evidence in the pack that motivates
it, how it stays building-agnostic, the files it touches, and the acceptance test that closes it.
`Status` is the progress column; **do not add a second tracker file** — two disagreeing trackers is
how a fresh clone picks up the stale one.

Two rows are **BLOCKED-ON-OWNER** and cannot start without you: `W0-08` (confirm the three
defibrillator positions) and `W3-01` (is there a real weather feed?).

---

## Two decisions taken 2026-09-22, which change what "honest" means here

### D1 — All data is the building's data

The building has **680 physically installed sensors reporting real readings**. The rest of the
estate is modelled on those sensors to populate the floors and zones that are not yet instrumented.
**That disclosure belongs in the paper, once, not in every answer.**

So the system stops distinguishing the two. `ontosage:isSimulated` is removed from the graph and
from every code path that reads it. A reading is a reading; a record is a record.

**Why this is defensible.** Provenance is disclosed at publication scope instead of per answer.
A reader of the article knows exactly which 680 sensors are physical and that the remainder
replicate them. Repeating it inside every answer told a user nothing they could act on — they
cannot install a sensor — while making the system read as a prototype rather than as a building.

**What does NOT change.** Honest declines stay, and they are the core of the design: a quantity the
building does not measure, a record that does not exist, a referent that is not in the graph, a
question about a person. Those refusals are about *absence*, not about *authenticity*, and removing
the simulated flag does not create a single new answer — it only stops hedging the answers that
already existed.

### D2 — No access levels for now

`PROTECT_ENFORCE` goes to `off`. Everyone sees the whole building at full resolution. Roles will be
reintroduced after production against real people and real duties.

**One thing this deliberately does not switch off:** the refusal to answer about a named individual.
That lives outside the policy engine (`absence_wording`, `event_query_service`), and it is not an
access level — it is the design contract and a data-protection matter. "Which member of staff spent
longest in the building" keeps refusing. Say the word if you want that changed too; I have not
assumed it.

---

## Wave 0 — Carry out the two decisions (1.5 days)

| # | Task | Scope measured today |
|---|---|---|
| 0.1 | **Strip `ontosage:isSimulated` from the building data.** | 4,135 triples across 45 TTL files. One script, re-runnable per building, plus a test that no shipped TTL reintroduces it. |
| 0.2 | **Remove the property from the schema** and the Module F provenance text that explains it. | `ontology/ontosage_schema.ttl` |
| 0.3 | **Remove the ~30 code paths that read it**, in `amenity_proximity`, `asset_state_service`, `capability_graph_resolver`, `deliberation/*`, `observation_provenance`, `record_documents`, `sparql_agent` and others. Anywhere a record was ranked, labelled or degraded for being simulated, it stops being. | 30 modules, 53 test files touch the word |
| 0.4 | **Ranking must no longer prefer "measured" over "modelled".** The deliberation lane scored provenance; with one kind of data that scoring is meaningless and would silently bias every ranking toward the 680. | `deliberation/saturation.py`, `plan_executor.py` |
| 0.5 | **Retire the placeholder vocabulary in generated prose** — "placeholder", "modelled at", "to be replaced by real data" in `locationText` and record front-matter. A record either states a fact or is absent. | 45 TTL files + `answer_wording` (which already strips the flag from answers, BUG-699) |
| 0.6 | **`PROTECT_ENFORCE=off`**, and remove the access-policy preamble it produces — *"Served at 5-second resolution — this building's access policy sets the finest detail available to you"* — which currently opens many answers in the pack. | one setting + the wording it drives |
| 0.7 | **Repoint `scripts/owner_facts_report.py`.** With no simulated flag it reports one thing: facts the building has not stated at all. The HEDGED/PLACEHOLDER states go. | |
| 0.8 | **A regression gate over the 73 questions already evidenced.** A harness re-asks the 52 that answer and fails if one stops. Run before every merge from here on. | This is what "keep the answerability as it is" means in practice: the pack stops being a report and becomes a test. |

**One item needs you, not me (30 seconds).** The AED record's own text reads *"Defibrillators are
modelled at reception, floor 3 and floor 5."* Under D1 I remove the word "modelled" and the system
states those three positions as fact. **Please eyeball those three positions before I do.** It is
the only fact in the building where a wrong value could hurt somebody in an emergency, and it is
cheaper to confirm now than to discover later. Everything else in Wave 0 I will just do.

**Acceptance:** `grep -r isSimulated` returns nothing in `bldg1/`, `ontology/` or `orchestrator/`;
the 73-question pack re-runs with no answer mentioning simulation, placeholders or access policy;
suite green.

---

## Wave 1 — The multi-read lane (3 days) — *the largest single win*

One capability closes about half the open failures. The deliberation lane **already does this**: it
reads CO₂ and occupancy together and ranks on both (pack #14). Nothing else can.

| # | Task | Building-agnostic shape |
|---|---|---|
| 1.1 | **A question naming two measurands routes to a lane that fetches both.** Extend the concept stage: when two distinct measurand concepts resolve and it is not a register question, route to the multi-read lane. | Concepts come from the graph; the rule counts them, it does not name them. |
| 1.2 | **Fetch N modalities over one window, per room.** Generalise `deliberation/fetch.py` so any lane can ask for `[co2, temperature, occupancy]` across a candidate set. | Modalities are strings resolved from HBCO; the fetch routes by `ref:storedAt`. |
| 1.3 | **Say what two series together mean.** "Warm *and* stuffy" = both above band. "Ventilation keeping up" = CO₂ trend against occupancy trend. Expressed as **recipes in `config/recipes.yaml` + per-building overlay**, never as code. | A new building adds a recipe row; no code change. |
| 1.4 | **Two windows, one answer.** "This week against last week", "weekday against weekend". The second window is currently never fetched. Resolve both through `requested_interval`, fetch both, compare. | Windows come from the parser, in the building's local time. |
| 1.5 | **Negation over the model.** "Which rooms have *no* temperature sensor" — a set difference the graph answers in one SPARQL. | Pure SPARQL over Brick classes. |

**Expected effect:** diagnosis 0/5 → 4/5; period comparison 0/3 → 3/3; negation 0/2 → 2/2 —
about **+9 of the 21 failures**.

**Acceptance:** the five diagnosis and three comparison questions in
`docs/evidence_questions_50.txt` answer with both quantities named and both windows stated.

---

## Wave 2 — Prediction above the single sensor (1.5 days)

Per-room forecasting works end to end: 192 hourly points, two models on a 20 % hold-out,
walk-forward calibration, 80/95 % intervals (pack #3). Floor-level and building-level forecasts
never reach the forecaster and return a register decline.

| # | Task |
|---|---|
| 2.1 | Route "forecast the average temperature on floor N" and "…the building's electricity for 7 days" to the forecaster, not the register. |
| 2.2 | Aggregate first, then forecast: mean over the floor's sensors per hourly bucket, then the existing pipeline. The aggregation is `aggregate_lane`'s, so units and bands stay correct. |
| 2.3 | State the denominator: "averaged over 14 sensors on floor 3". |
| 2.4 | **Cross-entity prediction** — "will floor 3 be warmer than floor 4 tomorrow?" — forecast both, compare the intervals, and say when they overlap rather than asserting a winner. |

**Acceptance:** questions 2, 3 and 5 of the 50-set produce a forecast with its model table.

---

## Wave 3 — Close the data gaps, as triples (2.1 days)

With D1 there is no "synthetic" label to apply, so the rule is simpler: **a record either states a
fact or does not exist.** Add data where the building plausibly has it; leave a genuine absence
absent so the decline stays honest.

| # | Gap seen in the pack | New per-building TTL |
|---|---|---|
| 3.1 | No outdoor weather, so weather and weather-correlation questions decline (CAVEAT-844). | `<id>_weather.ttl` + a `rest_poll` feed in `feeds.yaml`. **A real feed if one is available — I asked and have not had an answer yet.** |
| 3.2 | Calibration answered in one pack and denied in the other (index #33 vs #49). | One calibration register; one lane reads it. |
| 3.3 | Parking cost declines; the cost register holds 24 lines and no parking line. | Add the tariff, or leave it absent if the building has none. |
| 3.4 | Design occupancy, for "observed against design" comparisons. | `ontosage:designOccupancy` on spaces. |
| 3.5 | "Which sensors stopped reporting, and when" is answered vaguely. | A last-seen timestamp per sensor, derived, not authored. |

---

## Wave 4 — Make provenance answerable (1 day)

Every answer already *carries* an evidence record; the system cannot *say* it. "Which data sources
did you use?" and "if two records disagree, which wins?" are declined (0/2). Under D1 this is about
**which record and which sensor**, never about whether data is real.

| # | Task |
|---|---|
| 4.1 | A `provenance` intent that reads the previous turn's evidence record from `turn_memory` and renders it. |
| 4.2 | Publish the precedence rules as a record class, so "which wins" is answered from the graph rather than from prose. |

---

## Wave 5 — Conversation memory that survives a long session (2.6 days)

**What exists today, read from the code rather than the docs.** The last 20 turns are kept verbatim
in Redis; every completed turn also writes one deterministic line to Postgres `turn_memory`; and
`get_older_context` injects turns 21–50 as one-liners. So there *is* long-term memory, and it is
wired — on `/v1/chat/completions` only.

**Three things are missing for it to behave like a modern assistant:**

| # | Task | Why |
|---|---|---|
| 5.1 | **A rolling session summary.** Beyond turn 50 the earliest history is silently dropped, and what survives are deterministic extracts, not a narrative of what the user is doing. Compact old turns into a summary that is *updated* as the session grows, so history is compressed rather than lost. | A 60-turn conversation currently cannot answer about turn 3. |
| 5.2 | **Carry the context on every entry point.** `/chat` and the websocket do not get the older-context block; only `/v1` does. One helper, called by all three. | The same follow-up works or fails depending on which door the user came through. |
| 5.3 | **Cross-session memory for a returning user.** A new chat starts blank. Recall what the user cares about, show it to them, and let them erase it. | This is personal data; it must be visible and clearable, not silently accumulated. |
| 5.4 | **Prove it with a 60-turn test** asserting recall at turns 3, 25 and 59. | A memory feature without a long test is one that works only in demos. |

---

## Wave 6 — Determinism and latency (2 days)

| # | Task | Evidence |
|---|---|---|
| 5.1 | **Make routing deterministic for a fixed question.** 6 of 50 answers differed between two identical runs. | Until this closes, no single-run pass rate is trustworthy to better than ±10 points — including the 52/73. |
| 5.2 | Cache the classifier decision per normalised question, as the concept match already does. | |
| 5.3 | **Latency:** median 100 s, slowest 273 s. Forecasts are genuinely expensive; most of the rest is not. Profile the register and metadata lanes first. | Wave 0.6 helps here: the PDP consultation comes out of every data turn. |

---

## Wave 7 — Re-earn the numbers (1 day)

| # | Task |
|---|---|
| 6.1 | Draw a **fresh held-out set** (C–L are spent), hand-label it, publish the rate with its denominator. |
| 6.2 | Re-run the 73-question pack and re-read every answer. The pass rate is a property of a build, not of the project. |
| 6.3 | Re-state the measurement conditions: with D2 there is one role, so the CLI and the browser should now agree — which removes a long-standing measurement artefact. |

---

## Order, and why

**Wave 0 → 1 → 2 → 3 → 5 → 4 → 6 → 7.** Wave 0 first because every later measurement is taken on the
post-decision system, and re-measuring before it lands measures a system we are not shipping.
Wave 1 next because it is the only item that moves many questions at once. Memory (5) comes before provenance (4) because 'which sources did you use for that?' is a question about an earlier turn, so it needs the memory to be reliable first.

**Total: 16.5 working days**, itemised in the tracker. Waves 0 and 1 (4.5 days) should take the pack from 52/73 to
roughly 61/73 on the same questions — a number to re-measure, not to assert.

## What this plan does not promise

- **Declines do not go to zero, and should not.** Seven current declines are correct: a quantity the
  building does not measure, a record that does not exist, a question about a person. D1 does not
  touch these — it removes hedging from answers that already existed, not the refusals. The target
  is the ~9 declines that are *wrong*, where the data is present and the question did not reach it.
- **The 21 open P1s are not all covered.** Five of them (BUG-709, 710, 711, 716, 718) describe the
  same lane-reach failure as Wave 1 and should close with it; the rest need their own pass.
- **One risk worth naming.** Removing `isSimulated` is not reversible from the graph alone — the
  distinction exists today only in those 4,135 triples. The TTL is in git, so it is recoverable from
  history, and Wave 0.1 writes the script rather than hand-editing, so it can be re-run or inverted
  per building.
