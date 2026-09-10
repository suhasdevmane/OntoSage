> **SUPERSEDED 9 September 2026** by
> [`docs/V11_IMPLEMENTATION_PLAN.md`](../docs/V11_IMPLEMENTATION_PLAN.md), after the
> supervisor's architecture review. This document is kept because its *reasoning* still
> holds — the review independently reached the same conclusion on deferring W3-2/W3-3, and
> the same ordering rule that the probe gates every routing change. What changed is that
> W2-1 and W2-5 move behind publication enforcement and simulation governance, neither of
> which appears anywhere in this plan.

# V10 — what is left, in the order I would do it

Written 2026-09-08, after W0-2 closed and the report and ECA lanes were made to work.

**State it plans from:** 5,419 offline tests passing, live probe 50/50, no P1 open,
19/28 V10 rows done. Open elsewhere: `TODO-463`, `BUG-482`.

Nine V10 rows remain, carrying 19 days of tracker estimate. Two of those estimates are
stale and one block of six days is, I think, work that should not be done yet — see
**What I would not do** at the end.

---

## The ordering principle

Two of the remaining rows change **routing** (W2-1, and W2-5 through the prompts that feed
it). Every expensive mistake in this project's history has the same shape: a guard added
for one question shape quietly took another with it, and nothing noticed until someone
asked. BUG-431's first fix corrected "how many CO2 sensors" and began answering it with
the building-wide total. W0-2's inversion was safe **only** because 17 probe cases were
written first, one per escape clause, and the run afterwards could be compared against
them.

So: **the verification debt is paid before the routing work, not after it.** That is the
whole reason W4-4 leads.

---

## 1 · W4-4 — the seven W0 questions become permanent cases · ~1 day

The seven live failures that opened V10 are still not in the probe. Four were routing and
guard defects that no register can fix and no unit test can see — exactly the class the
next item is about to disturb.

Also owed: a bldg3 leg, so the probe says something about portability rather than only
about bldg1.

**Acceptance:** the probe covers all seven; no coverage number is published from a run
that has not passed them.

**Why first:** it is the gate for item 2. Doing it after would be measuring the change
with an instrument the change already influenced.

---

## 2 · W2-1 / TODO-463 — the BuildingLexicon into routing · ~1 day, not 4

**This is the last real hardcoding, and the answer to "what is left that is
building-specific".**

The tracker says 4 days. That is stale: `services/building_lexicon.py` is built, has 25
offline tests over three room grammars, and is populated at boot — the live building logs
*429 measurand words, 31 space nouns, 5 identifier shapes*. What remains is consumption.
`_ROOM_ID_RE`, `_ZONE_ID_RE`, `_SENSOR_ID_RE`, `_DATA_ANALYTIC_WORDS`, `_SPACE_NOUNS` and
`_MODALITY_STOPWORDS` still carry hand-written, bldg1-shaped values.

**Consume it ADDITIVELY — generic list OR lexicon, never lexicon alone.** "temperature"
and "last week" are domain English, and a building whose graph is still loading must not
lose them.

**Acceptance:** a fixture building with `RM-204` rooms and an NO2 modality routes
"NO2 in RM-204" to `sensor_data`; `test_contract_is_building_agnostic` is replaced by a
two-fixture test over two room grammars.

**Method:** probe green → swap one rule → probe → keep or revert. One rule at a time. A
batch swap cannot tell you which rule traded which question.

---

## 3 · W2-5 — generate the SPARQL few-shot from the live graph · ~1 day

Six prompt sites teach `Room_5.01` and `CO2_Level_Sensor_5.08`. On any other building the
model is being shown examples that do not exist. The project's own vocabulary
(`ontosage:`, `hbco:`) fails its own pre-flight.

Same theme as item 2 and it follows naturally: both are "stop teaching the system about
one building".

**Acceptance:** a prompt dump on bldg3 contains only bldg3 IRIs; a generated query using
`ontosage:` passes validation.

---

## 4 · W3-4 — close the unfillable record classes · ~1 day

`AlarmEvent`, `AnomalyEvent` and `AccessEvent` are declared and lay-termed with **no
mapping, no instances and no reader**. They can only ever produce a confident silence —
the failure mode this project cares most about, and the same shape as BUG-475's fabricated
monitoring gap. `SustainabilityTarget` has a mapping and is undiscoverable.

No dependencies. Cheap. Removes a class of wrong answer rather than adding a feature.

**Acceptance:** the RDF reader audit lists 0 answerable classes with no reader.

---

## 5 · W4-1 — the deliberation lane · ~2 days

Zero tests exercise `_deliberate_node` end to end, while V4-T26 is marked done.
`ONTOSAGE.md` never mentions ARBITER or the dossier. `build_plan_trace` emits a constant
six-step list. Two gating env vars exist in no `Settings` and no `.env`.

The lane demonstrably works — it answers both probe cases — so this is documentation and
test debt, not a defect. It ranks here because an untested lane is where the next silent
regression will land.

**Do not rename the package to settle a documentation error.**

**Acceptance:** the e2e test fails when any of the five findings is reverted; `ONTOSAGE.md`
describes the lane as what it is.

---

## 6 · BUG-482 — a concept rule watches one point · ~1 day

`temperature_reading` currently binds to the outside weather feed. That is a legal choice
and almost certainly not the intended one. A concept trigger evaluates ONE point of
however many carry the class, and nothing lets a rule state a scope.

Partly mitigated already: the engine now picks a point that is actually reporting, and
names it in the log with *"this rule watches THIS point only"*. The real fix is to evaluate
across every matching point, or to require a scope in the rule.

---

## 7 · CAVEAT-467's residual — a deterministic path for common aggregates · ~2-3 days

Not a correctness bug any more; the lane no longer loses the whole turn. This is latency.

Every analytics question is LLM-writes-Python → sandbox → LLM-narrates. `config/recipes.yaml`
already holds 41 recipes including `co2_average` and `temperature_average`, and they are
injected into the code prompt **as text** — the LLM still writes the loop. Recognising
"average/min/max of X grouped by floor" and computing it directly would take the common
case off the LLM path entirely.

Ranked last of the real work because typical questions already answer in ~14s. It matters
if the demo audience asks comparisons, or if the corpus replay's wall-clock becomes a
constraint.

---

## What I would not do yet

**W3-2 (register scaffolder, 3d), W3-3 (templates for 24 TTLs, 3d) and W3-5 (deployment
truth, 3d) — 9 days of onboarding machinery.**

These pay off only when somebody actually onboards a new building without you. They were
already deferred once as speculative, and nothing has changed to make them less so: bldg4
turned out to be a GUI upload test rather than a building to serve, and W3-5's acceptance
test had to be re-pointed at bldg2 or bldg3 as a result.

**Two exceptions worth carving out of that block, ~1 day total:**

- **W3-1 alone (1d)** — the readiness report. A building with valid Brick and zero
  `ontosage:` triples boots green and declines every capability, record and knowledge
  question. That is a *diagnostic*, and it pays for itself the first time a building looks
  healthy and answers nothing. Worth doing on its own, detached from the chain below it.
- **The `.env.example` half of W3-5 (a few hours)** — 31 live settings are undocumented and
  MySQL is an undocumented host prerequisite. This is the difference between a fresh clone
  starting and a fresh clone failing mysteriously. The guard that caught
  `WORKFLOW_TIMEOUT_S` this session already exists; point it at the rest.

Leave the scaffolder, the 24 templates and the container-naming work until a real second
deployment is actually on the calendar.

---

## Suggested sequence

| # | Item | Est. | Why here |
|---|------|------|----------|
| 1 | W4-4 | 1d | Gate for everything below it |
| 2 | W2-1 / TODO-463 | 1d | The last hardcoding; needs the gate |
| 3 | W2-5 | 1d | Same theme, follows naturally |
| 4 | W3-4 | 1d | Cheap, removes a confident-silence class |
| 5 | W3-1 | 1d | Diagnostic, pays for itself, no chain |
| 6 | `.env.example` half of W3-5 | ~½d | Fresh-clone correctness |
| 7 | W4-1 | 2d | Test and doc debt on a working lane |
| 8 | BUG-482 | 1d | Scope for concept rules |
| 9 | CAVEAT-467 residual | 2-3d | Latency, if it becomes a constraint |

**About 8 working days** to a state where the remaining V10 rows are only the onboarding
machinery — versus 19 days if the whole tracker is worked as written.

---

## Standing method, for whoever picks this up

- **The probe is the gate, not the report.** Run it before a routing change and after.
- **Ask the system, do not only test the code.** Every one of BUG-473 through BUG-478,
  BUG-481, BUG-485 and BUG-486 was found by asking a question. The suite passed throughout.
- **A measurement that disagrees with the system is usually the measurement.** The overdue
  count went 194 → 201 → 206 while the system stayed correct.
- **Verify the process, not the file.** `/app` is bind-mounted; check `StartedAt`.
