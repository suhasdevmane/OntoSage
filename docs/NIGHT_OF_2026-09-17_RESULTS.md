# What changed on the night of 17–18 September 2026, and what it measures

**Written for the supervisor review and the demo on 18 September, 14:00.** Every number here is a
measurement with a named source. Where a claim could not be verified, it says so instead of
rounding up.

---

## 1 · The headline

Answer quality on a fixed bank of **147 stakeholder questions**, asked live through the demo path
(`/v1/chat/completions`, streamed, signed in as a facility manager) and **read by hand, question by
question**, against each question's written answer boundary.

| | run 1 | run 2 | run 3 | run 4 | run 5 | run 6 |
|---|---:|---:|---:|---:|---:|---:|
| Good answer | 19 | 10 | 14 | 16 | 19 | **17** |
| Honest decline | 21 | 24 | 37 | 36 | 38 | **34** |
| Weird | 107 | 113 | 96 | 95 | 90 | **96** |
| **Weird share** | **72.8%** | **76.9%** | **65.3%** | **64.6%** | **61.2%** | **65.3%** |

Acceptable answers (good answer + honest decline) went from **27% to 35%**; the best measured state
was run 5 at 39%.

> **CORRECTION, 18 September, after an architecture audit.** Three statements below were wrong
> when first written and are corrected in place, with the measurements that overturned them:
>
> 1. **The improvement is not statistically significant.** Paired exact McNemar over the same 147
>    questions: run 1 → run 6 is 28 improved against 17 regressed, **p = 0.135**; run 5 → run 6 is
>    5/11, p = 0.210. Only run 1 → run 5 is significant (28/11, **p = 0.009**). The 95% CI on a
>    share of 147 is about ±7.7 points, wider than most wave deltas. **High-confidence weird
>    answers are flat across the whole series: 60, 68, 65, 60, 55, 59.** The fall from 72.8% to
>    65.3% is carried by low-confidence labels (14, 7, 1, 2, 1, 1). The defensible claim is
>    narrower than the one this document originally made: run 5 beat the baseline; the frozen
>    state does not.
> 2. **The claim-binding headline is 52 of 703 claims unbound (7.4%) over the 71 answers with
>    complete evidence**, not 58 of 709 over 441. The partition excluded from it — answers whose
>    store read was not captured — runs **55.7% unbound**, and 55 of 147 answers are unassessable
>    because no evidence was recorded at all.
> 3. **Structured generation is NOT incompatible with this model.** See §2.4.

**Run 6 went backwards, and the code was frozen there.** Six answers improved, eleven regressed, and
the largest defect class grew from 19 to 27. It was the second wave in this sequence to pass its own
tests and make the bank worse. With five hours to the demo and no time to hand-read a seventh run,
the owner chose to freeze rather than land a third consecutive change nobody could measure. The
single highest-leverage remaining fix is named in §4.

Three things this table must not be read as saying:

* **Run 2 is worse than run 1.** A batch of fixes that passed their own tests made answers worse.
  That is why every later wave was judged by a hand read of the same bank rather than by a tool.
* **Most of the gain is honest declining, not new capability.** Declines rose 21 → 34 while good
  answers went 19 → 17. The system stopped pretending before it got cleverer, which is the right
  order, and is not the same as getting cleverer.
* **The trend is not monotone and is not claimed to be.** Two of six waves made it worse. What the
  sequence demonstrates is a method that CATCHES that — six independent hand reads of one fixed
  bank — not a smooth improvement curve.

**The demo path is measured separately and is in a different state:** the 44-question demo script
has been rehearsed six times end to end, and the last five passes were **44/44 clean** — no
broken-answer phrasing in any answer. The 60-case regression probe stands at **59/60**, with the
single failure analysed in §4.

---

## 2 · The four components built

Each one exists because a specific defect was measured, and each carries its own limit.

### 2.1 A grader calibrated against human labels
`scripts/grade_answers_rubric.py` · `docs/EVALUATION_CALIBRATION_2026-09-18.md`

The project's previous grader scored **20 of 147** answers weird where two careful human readings of
the same answers scored **107 and 113**. Calibrated on **294 hand-labelled answers**:

| grader | accuracy | κ (weird vs not) | weird recall | weird precision |
|---|---:|---:|---:|---:|
| the old heuristic | 40.5% | 0.116 | 21.8% | 98.0% |
| the new deterministic grader | 68.0% | **0.419** | **65.5%** | 94.7% |

The decisive evidence is direction, not accuracy: between the two runs the humans labelled, the
humans said quality got **worse**; the old grader said **better**. The new one agreed with the
humans. An LLM judge was built, measured and **not adopted** — on a 20-row sample the ranking
inverts, because κ depends on class balance, so graders may only be ranked on the same rows.

**Its limit, stated:** the new grader is still ~25 points optimistic in level. Trust its direction,
not its value. And see §3.

### 2.2 Claim binding — every figure must point at a row
`orchestrator/services/claim_binder.py`

Extracts three kinds of claim from a finished answer (figures, universals such as "all/none", and
inferences introduced by "so/therefore") and binds each against that turn's own evidence.

**Measured, from the committed artifact:** 52 of 703 claims unbound — **7.4%** — over the **71
answers that recorded complete evidence**. Two partitions sit outside that headline and matter more
than it does: answers whose store read was not captured run **55.7% unbound**, and **55 of 147
answers cannot be assessed at all** because no evidence reached the record. It flags 10 of the 17
answers a human marked as inventing a conclusion.

**It is switched OFF.** Enabled once, it deleted correct figures — "How many CO2 sensors are there?"
lost its number — because lanes that *compute* a figure never recorded it, so a computed number and
an invented one looked identical. Computed counts are now recorded as evidence and enforcement is
conditional on complete evidence; a replay shows correct figures removed falling **1 → 0**. It stays
off until one live probe run with enforcement on is green.

### 2.3 A portability conformance suite
`scripts/conformance_report.py` · `docs/CONFORMANCE_bldg1_2026-09-17.md`

One command reports what a building can answer, what it cannot, and what data would change that.
For this building: **7 checks pass, 4 pass with a limitation, 0 fail** — timeseries reference
fan-out 1.007, all 20 stores registered and answering, every measurable quantity reporting within
24 h; limitations named (two declared quantities resolve to no points; 66% of floor-plan spaces
carry a graph IRI). It derives a **capability matrix**: 9 question classes supported, 3 supported
with a stated limitation.

**Its tests run against a different building's fixture**, which is how portability is demonstrated
rather than asserted. Asked live, its own 36 generated questions came back **32 clean**, and the
three failures are logged — including one in the generator itself.

### 2.4 Structured generation — an honest negative
`orchestrator/llm_manager.py` (flag `STRUCTURED_PLAN_ENABLED`, default off)

The model fills a JSON schema and deterministic code builds the query, so a malformed generation
becomes impossible rather than repaired. Implemented, tested (27 tests), provider-agnostic.

**This section originally reported a negative result. The negative was wrong, and the error is
instructive.** The measurement was taken against Ollama's `/api/generate` endpoint, which is the one
langchain's `OllamaLLM` client uses. Re-measured on 18 September against the same model and build:

| call | result |
|---|---|
| `POST /api/generate` + JSON schema | **0 characters**, 16.3 s |
| `POST /api/chat` + the same JSON schema | **valid JSON**, 83 characters, 38.2 s |
| `POST /api/chat` + schema + `think:false` | **0 characters** |

So schema-constrained generation works on this model, on this machine, today — through the chat
endpoint. Disabling the model's thinking, which the original row offered as a remedy, is what breaks
it. Both other proposed remedies (serve on vLLM; use a non-reasoning model) were therefore
unnecessary, and the fallback of JSON mode without a schema returns reasoning prose rather than
JSON on the endpoint actually in use.

**What this costs and what it teaches.** A P1 architectural conclusion rested on one endpoint being
mistaken for the capability itself, and its acceptance artifact was written to a scratch directory
rather than committed — so the negative could not be re-examined from the tree. A negative result
presented in a viva needs its raw rows retained exactly like a positive one. The remedy is a
one-line client change (`OllamaLLM` → `ChatOllama`) and a re-run of the acceptance with the compile
cache disabled; it is now a work package rather than a dead end.

---

## 3 · The finding about measurement itself

Between run 4 and run 5 the new grader reported weird falling **36.1% → 29.9%**. The hand read of
the same files measured **64.6% → 61.2%**, and found why the gap widened: the grader's
**honest-decline bucket rose 42 → 75 in one night** while its answered bucket fell 52 → 28, because
a change we made started producing the phrasing its decline rule rewards — "the register does not
record X". **36 of its 75 honest declines are weird to a human.**

A gate reading "weird fell 6 points" would have passed a run in which four good answers became
confident declines of data the building holds.

**It got worse in run 6, in both directions.** The grader now reports 27.9% against a hand-measured
65.3%, and agreement has fallen for four consecutive runs (weird-or-not 54.4%). Its honest-decline
bucket holds 69 rows of which **40 (58%) are weird by hand**, 19 of them denying something another
answer in the same run holds — and its *answered* bucket has begun inflating too: it rose 28 → 37
and **21 of those 37 are weird**, because breadth refusals and bare list answers now score as
answers.

**The rule this establishes:** an automatic judge must be re-calibrated whenever the system's
wording changes, because a judge that scores shape can be gamed by the system it judges — without
anyone intending to. Until it is re-calibrated on the 441 newer hand labels, the hand read is the
only trustworthy measure here, and the grader may be used only for direction on a wave that does not
change wording.

---

## 4 · What is still wrong, named

* **The largest defect class grew: 21 → 19 → 27 answers** (28% of all weird ones). Its dominant
  shape in run 6 is a field's VALUE read as something it does not say — "you are the responsible
  role for this alarm", isolation points offered as trend points, an expired tariff described as
  currently in force. **The single highest-leverage fix, named by the reader and not yet attempted:
  forbid a causal clause that is not carried by a printed field value** — it covers 13 of those 27
  rows and 6 of run 6's 11 regressions.
* **The internal keyword census still reaches readers.** Halved but not gone: 17 → 8 answers name a
  word as the unit of absence, and 34 → 19 carry the "no field records X" paraphrase. It is the
  primary cause on 5 of run 6's 11 regressions.
* **False absence: 19 answers**, several contradicted by another answer in the same run.
* **The probe's one failure is deliberate.** "Which bookable rooms are suitable for a confidential
  call?" now names the room whose note says "suitable for confidential calls" instead of claiming
  all 18 qualify — defensible, but it does not surface the two rooms whose recorded noise profile is
  the only *silent* one. Fixing that by teaching the system "confidential means silent" was
  rejected: that word appears in no recorded value, so the mapping would be a building-specific rule
  wearing a general name. It belongs in the concept layer. The probe case stays red with the reason
  recorded (BUG-783).
* **Room identity is knowingly wrong and deliberately unchanged.** The graph disagrees with the
  architect's drawings for 132 rooms. The correction and its whole cascade are staged in
  `tasks/held_back/room_identity_2026-09-17/` and land after the demo, because loading identity
  without the timetable, bookings, registers and sensor labels that name those rooms creates
  contradictions a reader can see.

---

## 5 · What is deliberately switched off

| Component | State | What would switch it on |
|---|---|---|
| Claim-binding enforcement | record-only | one live probe run with enforcement on, green |
| Structured generation | off | a serving stack whose grammar support works with the model |
| Room-identity correction | staged, not loaded | the owner's four answers, then the cascade as one change |

**The code was frozen at 08:45 on demo day** (TODO-789). After the demo, in order: the causal-clause
fix (BUG-787), re-calibrating the grader on the newer labels (CAVEAT-788), then the held
room-identity cascade.

Nothing in this list is off because it is unfinished. Each is off because the evidence for switching
it on does not exist yet, and that evidence is named.

---

## 6 · How to check any of this

```bash
python scripts/conformance_report.py                 # what this building can answer
python scripts/grade_answers_rubric.py --calibrate   # the grader against 294 human labels
python scripts/measure_claim_binding.py              # the unbound-figure rate
python scripts/regression_probe.py                   # 60 cases, first-pass, no retries
python scripts/v12_coverage_audit.py                 # every open defect has an owner
```

The hand-read labels are in `docs/phase0/phase0_*_read.{md,jsonl}`; the answers they judge are in
`docs/phase0/phase0_*.md.jsonl`. Every defect named here has a row in `tasks/FIX_TRACKER.csv`.
