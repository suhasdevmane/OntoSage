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

---

## Wave 0 — Two things that must not ship as they are (0.5 day)

| # | Item | Why now |
|---|---|---|
| 0.1 | **BUG-858** — the defibrillator answer states positions as fact while the record says "modelled". Either the owner confirms them or the record gets `ontosage:isSimulated true` so the system declines. | Safety-critical and already in a pack a supervisor will read. |
| 0.2 | **Self-contradiction inside one session.** A diagnosis reply claimed the building model holds no current readings, a few screenshots after readings were returned from it. Derive any claim about what the system *can* read from the same place the reader uses. | It discredits every other answer in the pack. |

**Acceptance:** ask the AED question and the "warm and stuffy" question; neither asserts something
the graph contradicts.

---

## Wave 1 — The multi-read lane (3 days) — *the whole point of this plan*

One capability closes about half the open failures. The deliberation lane **already does this**: it
reads CO₂ and occupancy together and ranks on both (pack #14). Nothing else can.

| # | Task | Building-agnostic shape |
|---|---|---|
| 1.1 | **A question naming two measurands routes to a lane that fetches both.** Extend the concept stage: when two distinct measurand concepts resolve and the question is not a register question, route to the multi-read lane. | Concepts come from the graph; the rule counts them, it does not name them. |
| 1.2 | **Fetch N modalities over one window, per room.** Generalise `deliberation/fetch.py` so any lane can ask for `[co2, temperature, occupancy]` across a candidate set. | Modalities are strings resolved from HBCO; the fetch is by `ref:storedAt`. |
| 1.3 | **Say what two series together mean.** "Warm *and* stuffy" = both above band. "Ventilation keeping up" = CO₂ trend against occupancy trend. Express as **recipes in `config/recipes.yaml` + per-building overlay**, never as code. | A new building adds a recipe row; no code change. |
| 1.4 | **Two windows, one answer.** "This week against last week", "weekday against weekend". The second window is currently never fetched. Reuse `requested_interval` to resolve both, fetch both, compare. | Windows come from the parser, in the building's local time. |
| 1.5 | **Negation over the model.** "Which rooms have *no* temperature sensor" — a set difference the graph can answer in one SPARQL. | Pure SPARQL over Brick classes. |

**Expected effect:** diagnosis 0/5 → 4/5; period comparison 0/3 → 3/3; negation 0/2 → 2/2.
About **+9 of the 21 failures**.

**Acceptance:** the five diagnosis questions and three comparison questions in
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
| 2.3 | State the denominator in the answer: "averaged over 14 sensors on floor 3". |

**Acceptance:** questions 2, 3 and 5 of the 50-set produce a forecast with its model table.

---

## Wave 3 — Make provenance answerable (1 day)

Every answer already *carries* an evidence record; the system cannot *say* it. "Which data sources
did you use?" and "if two records disagree, which wins?" are declined (0/2).

| # | Task |
|---|---|
| 3.1 | A `provenance` intent that reads the previous turn's evidence record from `turn_memory` and renders it. |
| 3.2 | Publish the precedence rules as a record class, so "which wins" is answered from the graph rather than from prose. |

---

## Wave 4 — Close the data gaps, as triples (2 days)

The rule stays: **synthetic data is DECLARED** (`ontosage:isSimulated true`), and **never for a
safety-critical fact**. Fewer declines must not mean more invention.

| # | Gap seen in the pack | New per-building TTL |
|---|---|---|
| 4.1 | No outdoor weather, so weather and weather-correlation questions decline (CAVEAT-844). | `<id>_weather.ttl` + a `rest_poll` feed in `feeds.yaml`. Real feed where available; declared synthetic otherwise. |
| 4.2 | "Measured or modelled?" cannot be answered although `isSimulated` exists on every record. | A provenance summary the `metadata` lane can read. |
| 4.3 | Calibration answered in one pack and denied in the other (regression, index #33 vs #49). | One calibration register; one lane reads it. |
| 4.4 | Parking cost declines; the cost register holds 24 lines and no parking line. | Add the line, or keep the honest decline if the building genuinely has no tariff. |
| 4.5 | Design occupancy for "observed against design" comparisons. | `ontosage:designOccupancy` on spaces. |

**Rule for this wave:** every new file is listed in `config/safety_critical_facts.yaml` if it could
ever bear on safety, so `scripts/owner_facts_report.py` keeps reporting what the owner still owes.

---

## Wave 5 — Determinism and latency (2 days)

| # | Task | Evidence |
|---|---|---|
| 5.1 | **Make routing deterministic for a fixed question.** 6 of 50 answers differed between two identical runs. | Until this closes, no single-run pass rate is trustworthy to better than ±10 points — including the 52/73. |
| 5.2 | Cache the classifier decision per normalised question, as the concept match already does. | |
| 5.3 | **Latency:** median 100 s, slowest 273 s. Forecasts are genuinely expensive; most of the rest is not. Profile the register and metadata lanes first. | |

---

## Wave 6 — Re-earn the numbers (1 day)

| # | Task |
|---|---|
| 6.1 | Draw a **fresh held-out set** (C–L are spent), hand-label it, publish the weird rate with its denominator. |
| 6.2 | Re-run the 73-question pack and re-read every answer. The pass rate is a property of a build, not of the project. |
| 6.3 | State the **role** every measurement ran as. The CLI runs `readonly` and the browser `facility_manager`, and the same question can be answered in one and refused in the other. |

---

## Order, and why

**Wave 0 → 1 → 2 → 4 → 3 → 5 → 6.** Wave 1 first because it is the only item that moves many
questions at once, and waves 2–4 are cheaper to verify once a question can trigger more than one
read. Wave 6 last because measuring before the changes land measures the old system.

**Total: about 11 working days.** Wave 0 and 1 alone (3.5 days) should take the pack from 52/73 to
roughly 61/73 on the same questions — and that is the number to re-measure, not to assert.

## What this plan does not promise

- **It will not take declines to zero, and should not.** Seven of the current declines are correct:
  a quantity the building does not measure, a fact nobody recorded, a question about a person. Those
  must keep declining. The target is to remove declines that are *wrong* — where the data is present
  and the question did not reach it — and there are about nine of those.
- **The 21 open P1s in `FIX_TRACKER.csv` are not all covered here.** Several (BUG-709, BUG-710,
  BUG-711, BUG-716, BUG-718) describe the same lane-reach failure as Wave 1 and should be closed by
  it; the rest need their own pass and are not in this estimate.
