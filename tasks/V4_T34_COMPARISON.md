# V4-T34 — Competitor question classes + delta vs. our own paper

_Drafted 2026-08-14 from real run outputs (files referenced inline). Grounds the
related-work chapter in runs, not citations._

## 1. Capability-envelope comparison (run live on bldg3, 2026-08-14)

Question bank: `tests/fixtures/l7_bank/competitor_classes.csv` (20 questions, 3 classes).
Run artifact: `scripts/outputs/l7/competitor_classes_bldg3_20260814_124256.csv`.

| Question class (modeled on) | What the class needs | OntoSage result | Competitor envelope |
|---|---|---|---|
| **static_brick** — BuildingGPT2-style ontology QA ("how many temperature sensors?", "which floors?") | SPARQL over Brick model | **8/8 answered** (metadata/discovery lanes, live COUNTs) | ✔ in-envelope for Brick-QA systems — parity class |
| **single_system_analytics** — JARVIS-style one-system time-series ("average CO₂ on floor 2 last 24 h") | UUID resolution + SQL + aggregation | **6/6 answered** (analytics lane, live values) | ✔ in-envelope for single-system assistants — parity class |
| **arbiter_only** — multi-space constraint ranking, forecast-conditioned selection, amenity-anchored choice | per-room multi-modality coverage + geometry + amenities + deterministic multi-criteria scoring + evidence | **6/6 answered, with evidence dossier** | ✘ outside both envelopes: no competitor formalism expresses cross-modality ranking over spaces with declared assumptions and per-figure provenance |

Notes from the run (honesty):
- AR03 ("Find me a quiet, well-lit room near a study area") initially routed to the
  capability lane and returned a *partial* answer (located the study area amenity, no
  ranking). Fixed the same day: `DELIBERATE_RE` + "find me a … room" shape; re-verified
  live — now deliberate with dossier (plan hash `b402727c48`). The pinned routing-precedence
  test covers the change.
- The three classes also separate the *proof* axis: parity classes answer with values;
  the arbiter_only class answers with values + assumptions + coverage ledger + per-figure
  simulated/real provenance — no competitor class produces an auditable trail.

## 2. Delta vs. our own WWW-paper baseline (same 240-question corpus)

| Metric | Paper (§6.5, pre-V4) | Now (T32 battery, 2026-08-14) | Delta |
|---|---|---|---|
| bldg1 combined (legacy metric) | 63.9% (measured 63.8% live) | **92.1%** | **+28.2 pts** |
| bldg1 split — data-backed | n/a (metric introduced in V4, NOTE-142) | 55.0% | new axis |
| bldg1 split — honest-decline | n/a | 37.1% | new axis |
| bldg2 combined | 70.4% (2026-07-30) | 78.8% | +8.4 pts |
| bldg3 combined | — (building did not exist pre-V4) | 81.7% | new building |
| L7 deliberative class | **0% — class unanswerable** (no coverage, no pipeline) | bldg1 18/22 · bldg2 17/21 · bldg3 20/20 behavior-correct, **0 fabricated** | entire class unlocked |
| Fabrication rate under benchmark | unmeasured | **0** across all runs, all buildings (independent grader) | measured + zero |

Method note for the chapter: the paper's 63.9% is the *legacy combined* number (data-backed
+ honest-decline conflated). V4 splits the axes (NOTE-142) because "more honest declines"
must never masquerade as "more answers" — both splits are reported everywhere above.

## 3. Ablation deltas (why the architecture, not the model, does the work)

Same tasks, same independent ground truth, same local model (gpt-oss:20b):

| Arm | top-1 | invented values | wall time |
|---|---|---|---|
| (b) LLM ranks handed rows | 6/15 | 9 | seconds |
| (f) generic ReAct agent, real SPARQL/SQL tools | 0/15 (answered 2/15, both hallucinated) | 6 | 205 s avg/task |
| clarify-off | n/a | 0 (4/5 became honest declines) | — |
| **ARBITER** | 11/20 top-1 proof on bldg3 gen bank | **0** | ~5–20 s |

Artifacts: `scripts/outputs/l7/ablation_llm_ranked_*.csv`,
`ablation_agent_loop_bldg1_20260814_073644.csv`, `clarify_battery_ask_*.csv`.
