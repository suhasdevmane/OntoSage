# Improvement Plan V5 — Universal Coverage (OCBV-2 + Events + PREDICT + DETECT + PROTECT)

**Status: PROPOSED v3 (2026-08-15) — v2 extended with Pillar C (PROTECT: privacy-leading
access control) and the model-diversity benchmark, both informed by the BuildingChat
comparison (`paper/literature-recent work/COMPARISON_BuildingChat_vs_OntoSage.md`).
Execution tracker: [`tasks/V5_TRACKER.csv`](./V5_TRACKER.csv), 45 tasks.**

## Goal

Keep the V4 pipeline and ARBITER as the core. Extend the OntoSage schema (OCBV-2) only where
Brick 1.4 has no terminology, add the missing data shapes, and make **prediction** and
**anomaly** first-class, honestly-graded capabilities — so that any building modeled in
Brick+OCBV whose admin registers data through the onboarding contract can answer the full
stakeholder question space (1,100-question bank: 72 anomaly + 59 prediction + 116
retrospective questions directly in scope of the two new pillars).

## Corrections to the founding idea (carried from v1)

1. **Schema alone answers nothing.** Answerability = TBox term → ABox entity → registered
   source in a matching SHAPE → query skill. Every V5 capability ships all four.
2. **"Any given way" becomes an onboarding contract** — validated shapes, not arbitrary files.
3. **"All questions" = all CORRECT responses.** ~10% of the bank stays declined by design
   (privacy/actuation). Metrics stay split; fabricated stays 0.

## What the code audit found (drives the PREDICT/DETECT design)

| # | Deficiency (verified in code, 2026-08-15) | Consequence |
|---|---|---|
| D1 | `plan_executor._linear_forecast` is a least-squares midpoint; the REAL forecasting stack (`services/forecasting/ModelSelector`: linear/ETS/ARIMA, hold-out MAE, 80/95% CIs, `seasonal_periods` support in Holt-Winters) is only used by the trend lane | ARBITER forecast answers carry no uncertainty, no seasonality, no measured skill |
| D2 | `anomaly_agent` z-score uses the global mean/std of whatever one SQL fetch returned | Normal daily cycles read as anomalies; building-wide sweeps impossible; scope = one query |
| D3 | Anomaly summaries are LLM prose with numbers, **outside the numeric guard** | The only remaining unguarded fabrication surface in a data lane |
| D4 | No anomaly persistence — every question recomputes; no stable anomaly identity | "Summarise this week's anomalies" and "has this been flagged before?" unanswerable |
| D5 | No stuck-sensor, dropout, drift-vs-peers, schedule-violation, or cross-modality detectors | Majority of the bank's 72 anomaly questions unservable; the correlated synthetic data (occupancy→CO2/noise/door) makes consistency checks *exactly computable* |
| D6 | Grader covers ranking truth only — no forecast or anomaly ground truth | Can't measure predictive skill or detection quality |
| D7 | Horizon parsing duplicated (CQ-IR `TimeSpec` vs `forecasting/horizon_parser`) | Drift risk between lanes |

## The three data shapes (unchanged from v1)

S1 scalar time-series (✅ SATURATE) · S2 events/intervals (**new: Event Framework** — bookings,
work orders, access, compliance checks, and now **AnomalyEvent** as a first-class subtype) ·
S3 documents/registers (dates as triples). Anomalies persisting as S2 records is the unifying
move: detection writes interval records; retrospective anomaly questions become lookups; the
grader and provenance machinery apply unchanged.

## Pillar A — PREDICT (P3)

Design principles, informed by the code:
- **One forecasting core.** The executor's injectable `forecaster` hook is the swap point:
  an adapter around `ModelSelector`. No parallel implementations (kills D1/D7 — CQ-IR
  TimeSpec becomes the single horizon authority, `horizon_parser` folded in).
- **Two-tier ranking economics.** Fitting ARIMA per room across 233 rooms is not viable.
  Tier 1: deterministic **seasonal-naive / weekday-hour profile** forecast for ALL candidates
  (cheap, strong baseline for building data on the 10-min grid, daily period = 144).
  Tier 2: `ModelSelector` refinement for the top-K (existing hold-out MAE + CIs).
- **Measured skill, not vibes.** A walk-forward **backtest harness** runs per
  building×modality×horizon on schedule; results persist in a forecast-skill registry.
  Every predictive answer cites its measured error ("±1.2°C at 24h, 30-day backtest") —
  the honest version of "how confident are you?" (bank Q075-class).
- **Scenario conditioning through declared assumptions.** "Will the lecture theatre get
  uncomfortable with 200 people at 2pm?" = baseline forecast + occupancy scenario stated as
  an ARBITER assumption; weather feed and (once S2 lands) tomorrow's bookings become
  legitimate covariates. Never a silent physics claim.
- **Time-travel grading.** The grader asks the system to forecast from a historical cutoff
  it controls, so truth is already known — predictive skill measured in minutes, not days.

## Pillar B — DETECT (P4)

- **Detector suite v2** (deterministic library, building-agnostic): seasonal-residual bands
  (weekday-hour profile), stuck/flatline, dropout/gap, drift-vs-peer-group (same modality,
  same floor), schedule violation (activity outside occupancy hours), spike (kept from v1
  agent), cross-modality consistency (occupancy=0 but CO2 rising; door contacts silent but
  occupancy>0 — computable because the synthetic signals are correlated by construction).
- **Scheduled scanner + persistence.** Incremental sweep writes `AnomalyEvent` records to
  the S2 events store (stable IDs, ongoing-anomaly merge). Retro questions become lookups;
  complaints (user_reports) can cross-link ("people complain where data says fine" becomes
  a join, answering the bank's indirect class).
- **Diagnosis lens** for why-questions ("why was floor 2 freezing Tuesday?"): deterministic
  evidence assembly — target series, neighbors, weather window, overlapping anomalies,
  related complaints — rendered as a candidate-cause dossier in correlation language only.
- **Honest narration everywhere.** The allowed-numbers builder generalizes out of
  `dossier.py` so anomaly AND forecast narrations pass the same numeric guard (closes D3).
- **Injected-anomaly benchmark.** The synthetic generators inject labeled anomalies (spike,
  stuck, drift, schedule violation, correlation break); labels live OUTSIDE the building DB
  (grader-only), so the system cannot cheat. Detection quality = precision/recall/F1 per
  detector class + detection latency + zero fabricated explanations. This turns DETECT into
  a measurable contribution, same as the L7 fabrication result.

## Pillar C — PROTECT (P4b): privacy-leading multi-stakeholder access control

BuildingChat's genuine novelty is query-parameter access control enforced before retrieval
(k-anonymity, recency↔resolution tiers, rate limits) with a leak study. V5 adopts those
proven mechanisms AND goes past them on four axes their design cannot reach:

1. **Policy-as-triples (TTL-first privacy).** Access policies live in the ontology
   (OCBV-2 `ontosage:AccessPolicy` vocabulary + per-building policy TTL), not in code
   config. Consequences BuildingChat can't offer: policies are building-agnostic templates
   with per-building overrides; "what am I allowed to ask?" is SPARQL-answerable by the
   system itself (their usability study's top complaint — users couldn't tell what was
   queryable or why denials happened); the zero-literal scans apply to privacy too.
2. **Privacy provenance in the dossier.** The applied policy (id, k-floor, resolution cap)
   is RECORDED in the evidence dossier of every answer it shaped. BuildingChat displays
   denial reasons; OntoSage carries policy citations inside the proof artifact — auditable
   privacy, per answer, after the fact.
3. **One PDP, every lane.** A deterministic Policy Decision Point evaluates
   (role × spaces × modalities × window × resolution × sensor-count × rate) and returns
   allow / **restrict** (clamped resolution or aggregation floor, declared as an
   assumption) / deny (with nearest-allowed alternative). Enforced by construction at the
   fetch/adapter chokepoints — which means it covers ALL 30+ intents and the deliberative
   lane, not 6 templates. ARBITER's admission gate gains the verdict as a fourth outcome.
4. **Individual-inference guard + memory isolation.** Person-targeting questions ("is
   Prof. X in her office?", badge history of a person) are a policy CLASS with honest
   decline + aggregate alternative; conversation memory and preferences are role- and
   user-scoped with cross-user leakage tests; report intake redacts third-party PII.
   BuildingChat leaves conversational-memory privacy untouched.

Measured the way they measured, plus harder: a policy-trap bank (full/partial/no-access
strata + indirect-inference traps) across ALL lanes, target **0 leaks by construction**;
plus a prompt-only-policy ablation arm reproducing their 13–46% baseline-leak finding on
our stack (convergent evidence, cite both).

Governance (their declared open problem): the admin portal gains a policy editor tab —
policies are authored via GUI into TTL, versioned like any building input.

## Model-diversity benchmark (P6)

BuildingChat evaluated 6 LLMs on accuracy. V5 runs the generated L7 bank + flagship +
leak bank across ≥4 models (local: gpt-oss:20b + at least two others via `OLLAMA_MODEL`;
API: one OpenAI model) and reports behavior / proof / top-1 / **fabricated** / leak-rate
per model — and the stronger claim no accuracy table can make: **plan-fingerprint
invariance** (the deliberative plan is byte-identical across models, because the LLM only
compiles and the pipeline decides). Accuracy varies with the model; our architecture's
guarantees must not.

Model slate (decided at T44 with user sign-off): local Ollama pulls within the 16GB GPU
budget PLUS **Ollama Cloud** models (model name + API key, `MODEL_PROVIDER=cloud`) for
sizes local hardware can't hold — preferring BuildingChat's own open-weight trio
(Qwen-3 32B / Qwen-3 235B / GPT-OSS 120B) so the resulting table is directly comparable
to their published Fig. 6.

## Architecture invariants (the V4 contract, unchanged)

ARBITER stays core; routing changes only via `routing_contract.py` + pinned test; TBox
universal & versioned; ABox per building; zero building literals (scan-enforced); every
synthetic source declared; independent grader with fabricated = 0 as the hard gate;
split metrics per NOTE-142.

## Phases

- **P0 Measure (T01–T03):** 1,100 bank wired into replay; baseline + gap map tagged by shape
  AND by pillar (predict/detect/event/register/compute); OCBV-2 delta spec (Brick-first).
- **P1 TBox (T04–T06):** interval-record hierarchy incl. `AnomalyEvent` + forecast-skill
  vocabulary; compliance register template→TTL; TBox tests/docs/scans.
- **P2 Stores & generators (T07–T11):** events table + adapter; synthetic event generators;
  **injected-anomaly framework with external truth labels**; S1 modality expansion; admin
  ingestion path.
- **P3 PREDICT (T12–T17):** unified forecasting core; seasonal models; backtest harness +
  skill registry; scenario conditioning; forecast dossier + guard; time-travel grader.
- **P4 DETECT (T18–T23):** detector suite v2; scanner + persistence; diagnosis lens;
  guarded anomaly narration + routing for indirect phrasings; injected-anomaly benchmark;
  ECA/subscription bridge.
- **P5 Query skills (T24–T28):** event lane; ARBITER event criteria (availability windows,
  booking pressure); compliance QA; route-finder + recipes (degree-day, CO2-decay ACH,
  tariff cost); declared-assumption what-ifs (now largely powered by P3 scenarios).
- **P4b PROTECT (T37–T41):** policy vocabulary as triples; deterministic PDP; enforcement
  by construction at fetch chokepoints + ARBITER admission (restrict verdicts declared as
  assumptions, policies cited in the dossier); individual-inference guard + memory
  isolation; policy-denial reformulation with consent options.
- **P6 Honesty consolidation (T29–T31):** guard generalization audit across all lanes;
  grader consolidation (ranking + forecast + anomaly + events in one harness); provenance
  chips for all new sources.
- **P6b Benchmarks vs the field (T42–T44):** leak-rate benchmark across ALL lanes
  (+ prompt-only-policy ablation reproducing BuildingChat's finding); admin policy editor;
  multi-model benchmark (behavior/proof/fabricated/leak per model + fingerprint invariance).
- **P7 Portability & delivery (T32–T36, T45):** onboarding contract + validator; bldg2 full leg;
  bldg3; bldg1 (real-data constraints); certification ×3 + figures + DELIVERED sweep.

## Success criteria

1. 1,100 bank on the saturated test building: data-backed ≥70%, correct-response ≥95%,
   **fabricated = 0** — including the previously unguarded anomaly lane.
2. **Predictive skill is measured and cited**: backtest registry populated for every
   modality×horizon; every forecast answer carries model + CI + measured error; time-travel
   grader shows calibration (CI coverage within tolerance).
3. **Detection quality is measured**: precision/recall/F1 ≥ agreed bar (set after baseline)
   on injected anomalies per detector class, with zero fabricated explanations.
4. Three buildings, code diff = 0, scans green; onboarding contract machine-validated.
5. **Privacy leadership**: 0 leaks by construction on the policy-trap bank across ALL
   lanes; every policy-shaped answer carries the policy citation in its dossier; "what am
   I allowed to ask?" answered from policy triples; prompt-only-policy ablation reproduces
   the baseline-leak failure mode (cross-paper convergent evidence).
6. **Model invariance**: ≥4 models through the benchmark set; fabricated = 0 and leak = 0
   on every model; deliberative plan fingerprints identical across models.
