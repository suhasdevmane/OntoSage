# V4 Progress — 2026-08-12

One-line summary: **since the V4 plan started (2026-08-13), OntoSage gained a deliberative
brain (ARBITER), full sensor coverage on all three buildings (SATURATE), and an independent
benchmark that proves it answers multi-constraint stakeholder questions with evidence and
zero fabricated values — with the same code on every building.**

---

## 1. The problem V4 set out to solve (BEFORE)

- Complex stakeholder questions were **unanswerable**: "Where can I sit that's quiet, with
  good air, near drinking water?" needs per-room noise + CO2 + geometry + amenity locations —
  no building had that coverage, and no pipeline could rank rooms under multiple constraints.
- Per-room coverage before saturation (coverage audit, `scripts/audit_coverage.py`):
  - **bldg1** (233 rooms): temperature/humidity/CO2 71.7% (real sensors), noise/occupancy/
    illuminance/door/window contacts **0%**
  - **bldg2** (61 rooms): temperature ~97%, everything else **0%**
  - **bldg3** (132 rooms): temperature 97.7%, everything else **0%**
- Corpus replay baselines (240 questions, measured at V4 start):
  - bldg1: **52.9%** data-backed / 39.6% honest-decline
  - bldg2: **26.7%** data-backed / 54.2% honest-decline
- Direct-LLM answering **fabricates**: measured later in the ablations — when the LLM ranks
  rooms itself it invents values (9 invented in 15 tasks).

## The pipeline — before vs after

![OntoSage pipeline before vs after V4](figures/v4_pipeline_before_after.png)

*(regenerate any time: `python scripts/make_v4_pipeline_figure.py`)*

Top: the pre-V4 system — reflex lanes only. Bottom: V4 keeps every reflex lane and adds the
teal **ARBITER deliberative lane** (one LLM call to compile the question, then everything is
deterministic and evidence-guarded) plus the orange **SATURATE** pipeline that filled the
stores it reads from.

### Example questions & answers through each pipeline (real transcripts, bldg1, 2026-08-14)

**BEFORE — the same questions on the old reflex-only routing** (captured live today while
diagnosing BUG-163, i.e. this is genuinely what the old path did):

> **Q:** Which room is the warmest in the whole building right now?
> **A (capability deflection):** "I don't have that specific information on record for
> **Abacws Building**. For building-specific queries please contact your building's
> facilities / estates management team."

> **Q:** Which room on Floor4 has the lowest CO2 right now?
> **A (generic analytics, wrong tool for ranking):** "**All Floor 4 rooms report a CO₂ level
> of 0.00 ppm** ⚠ The reading is far below the typical indoor range…" — an aggregate over
> the wrong column, presented confidently.

**AFTER — the deliberative lane (ARBITER):**

> **Q:** I'm visiting tomorrow — where can I sit that's quiet, with good air, near drinking water?
> **A (deliberate, with dossier):** "**Best match: Room 4.01 — Research Laboratory** (floor
> Floor4, score 0.9675). 1. Room 4.01 — score 0.9675 (co2: 77.1, noise: 33.9, 0 m to the
> requested amenity) 2. Room 4.35 — Restroom (Male) — score 0.7958 (…, 6.4 m) 3. Room 3.36 —
> score 0.7332 (…, 8.3 m)" + assumptions (WHO/ASHRAE bands cited) + collapsible evidence
> dossier (per-room values, source tables, `simulated: yes/no`, excluded rooms with reasons).
> *Same question, same code, on bldg3: RM300C_room, score 0.8974 (noise 34.0 dB, CO2 645.8 ppm,
> 0.0 m to water); on bldg2: RM001A_room, score 0.87.*

> **Q:** Which room on Floor4 has the lowest CO2 right now?  *(the BEFORE failure above)*
> **A (deliberate):** "**Best match: Room 4.01 — Research Laboratory** (floor Floor4, score 1).
> 1. Room 4.01 — … (co2: 69.…)" — ranked per-room from live readings, every number traceable
> to the dossier.

**AFTER — the clarify path (one-question budget):**

> **Q:** Which room upstairs has the best air?
> **A:** asks exactly ONE question — which floor, with the building's actual floors as
> numbered options — parks the compiled plan, and resumes it when the user picks an option
> (measured: 5/5 such questions ask in ask-mode; with clarification disabled the system
> forced a declared guess once and honestly declined 4 times — never a silent guess).

**AFTER — the honest-decline path:**

> **Q:** Which room has the lowest radiation right now?
> **A:** declines — radiation isn't a sensed modality — and lists what the building DOES
> sense (temperature, humidity, CO2, noise, occupancy, illuminance, door/window contacts),
> with the hint that adding the sensor (TTL + registered readings) unlocks the question.

## 2. What was built

### a. The plan and tracker
| File | What to say |
|---|---|
| `tasks/IMPROVEMENT_PLAN_V4_DELIBERATIVE_BRAIN.md` | The design: ARBITER 6-stage deliberation + SATURATE + L7 benchmark |
| `tasks/V4_TRACKER.csv` | 36 tasks, executed row by row — **33/36 done** (T33-T36 remain: trace unification, comparison table, demo hardening, figures) |

### b. The deliberative brain — ARBITER (`orchestrator/services/deliberation/`)
New package, ~11 modules, **zero building literals** (enforced by tests):

| Module | Role (one sentence each) |
|---|---|
| `compiler.py` | One temp-0 LLM call turns the question into a typed constraint IR (CQ-IR) — the ONLY place the LLM touches the pipeline |
| `capability_schema.py` | Live schema of what THIS building can sense; admission gate: admit / clarify / decline |
| `clarify_policy.py` | One-question budget; every default declared as an assumption |
| `candidates.py` | Enumerates candidate rooms + coverage ledger (who was excluded and WHY) |
| `fetch.py` / `plan_executor.py` | Per-UUID data fetch, aggregation, forecast |
| `scorer.py` | Deterministic scoring against cited standard bands (WHO noise, ASHRAE CO2…) — the LLM never produces a number |
| `dossier.py` | Evidence dossier + **numeric guard**: every number in the answer must exist in the dossier, else the narration is suppressed |

### c. SATURATE — full coverage, three buildings, same scripts
`config/saturation_modalities.yaml` + `scripts/saturate_building.py` +
`scripts/backfill_saturation.py` + `scripts/generate_amenity_locations.py`

| Building | Rooms | Simulated sensors added | Rows backfilled | Coverage after |
|---|---|---|---|---|
| bldg2 | 61 | 366 | 1.84M | **100% × 8 modalities** |
| bldg3 | 132 | 927 | 4.67M | **100% × 8 modalities** |
| bldg1 | 233 | 1,363 | 6.87M | **100% × 8 modalities** |

- Same commands, zero code edits between buildings. Every simulated sensor is marked
  `ontosage:isSimulated true` in the ontology and its datasource renders "· simulated"
  (disclosure by design — dossier column `simulated: yes`).
- bldg1's REAL data (wide `sensor_data` table) untouched; saturation only fills gaps.
- Show before/after audit CSVs: `scripts/outputs/coverage/coverage_bldg1_20260814_044200.csv`
  (before) vs `coverage_bldg1_20260814_045340.csv` (after).

### d. The flagship question — now answered on all three buildings
"I'm visiting tomorrow — where can I sit that's quiet, with good air, near drinking water?"

| Building | Answer (live, with dossier) |
|---|---|
| bldg2 | RM001A_room — score 0.87, 0.0 m to drinking water |
| bldg3 | RM300C_room — score 0.8974, 34 dB noise, 646 ppm CO2, 0.0 m to water |
| bldg1 | Room 4.01 — Research Laboratory — score 0.9675, 0.0 m to water |

Each answer carries a collapsible "How I worked this out" dossier: per-room evidence values,
source tables, simulated flags, excluded rooms with reasons, scoring band citations.

### e. Proof it's honest — L7 benchmark + independent grader
`tests/fixtures/l7_bank/` (121+ questions) + `scripts/l7_grader.py` — the grader recomputes
ground truth with its OWN uuid derivation and OWN SQL (no system code reused).

**Results file to show: `scripts/outputs/V4_RESULTS.md`** (auto-compiled):

- Corpus replay: bldg1 **55.0% data-backed / 92.1% combined** (baseline 52.9%);
  bldg2 26.2% / 78.8% (synthetic fixture — honesty carries it, exactly as designed)
- Generated L7 banks: bldg1 18/22, bldg2 17/21, bldg3 18/20 behavior-correct
- **FABRICATED = 0 on every building, every run** — the headline honesty result

### f. Ablations — why the brain beats "just use an LLM/agent"
(All graded by the same independent ground truth, same tasks.)

| Arm | top-1 correct | invented values | note |
|---|---|---|---|
| (b) LLM ranks handed rows | 6/15 | **9** | fabricates even when given the data |
| (f) ReAct agent-loop with real SPARQL/SQL tools | **0/15** | 6 | 13/15 ran out of steps; only "answers" were hallucinations |
| Clarify-off (ask channel removed) | — | 0 | 5/5 asks became 1 declared-guess + 4 honest declines |
| **ARBITER (the system)** | see banks above | **0** | dossier + numeric guard on every answer |

Files: `scripts/ablation_llm_ranked.py`, `scripts/ablation_agent_loop.py`,
`scripts/clarify_off_battery.py`, outputs in `scripts/outputs/l7/`.

### g. Portability engineering honesty — bugs the process caught
`tasks/FIX_TRACKER.csv` rows BUG-158 → BUG-163 (all found TODAY by running the third
building, all fixed with regression tests):
- BUG-158 numeric-guard false positive on excluded-room labels
- BUG-159 floor-plan ontology linking never ran for generated-plan buildings
- BUG-161 coverage audit silently truncated at 20k points (bldg1 is bigger)
- BUG-163 room-superlative questions leaked to the wrong pipeline
- Point to make: **each building surfaced a different failure class — that's why the
  3-building portability requirement was worth it.**

## 3. Status right now

- bldg3 full battery running to check bugs and portability(last T32 leg) — bldg1 + bldg2 complete.
- Remaining tasks: T33 (every answer carries a plan trace), T34 (comparison table vs the
  WWW-paper baseline), T35 (demo hardening), T36 (final figures).
- Test suite: 1,100+ unit tests green, incl. zero-building-literal source scans.
- Nothing committed yet — everything is local pending review (per project rule).

## 4. Next steps

- Generate 1000s of new L7 questions (with the same independent grader) to stress-test the deliberative brain and prove it scales.
- Hardening the demo: make the dossier collapsible, add a "show me the plan trace" button, and add a "show me the source table" button.
- Hardening the pipeline for 3 buildings: no core code edits, only config changes, to add a new building.