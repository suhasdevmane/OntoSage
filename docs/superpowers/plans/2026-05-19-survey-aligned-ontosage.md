# Survey-Aligned OntoSage Implementation Plan

> Fuses the architecture critique ("The Plan", 5 phases) with the pre-development
> survey analysis in `paper/Survey analysis and results/`. Every phase is now
> justified by a survey statistic and emits a measurable artifact that doubles as
> a thesis figure/table. Not for commit/stage yet — planning document.

**Date:** 2026-05-19
**Author context:** PhD study (OntoSage++, IMWUT submission). Co-authors: Rana, Perera.
**Survey corpus:** N=5,916 classified questions, 81 participants, 4 elicitation stages.

---

## 0. The survey-driven reprioritisation (read this first)

The original 5-phase plan ordered work by *architectural elegance* (self-correction →
semantic grounding → dialogue state → learning → persona). The survey says that order
is wrong. Re-derived priorities:

| Survey finding | Source | Consequence for the plan |
|---|---|---|
| STATUS 65.4% + CAPABILITY 25.6% = **91% of corpus**, both P1 | `G2_capability_matrix.csv` | A fast, grounded STATUS path and a CAPABILITY knowledge facility must come **before** deep semantic grounding of the hard cases. |
| MULTI_STEP only **3.0%**; LOOKUP 84–92% for every persona | `taxonomy_v1.md`, `D3`, `F2` | The 91% common path must be made solid **without** weakening the complex path. Low volume ≠ low priority — see next row. |
| COMPARISON, ANOMALY, HISTORICAL are low-volume but **`analytical_share_pct=100` and tiered "P1 — must support at launch"** | `G2_capability_matrix.csv` | Complex analytical queries are the system's **core differentiator**, not a tail to de-scope. They are the questions a zero-knowledge user *cannot express any other way*; nailing them is the thesis. Protected, not frozen. |
| **24.0% OTHER** (off-ontology: amenity, wayfinding, safety-feature, policy) | `G4_gap_analysis.md` | Need an explicit, graceful, *useful* off-ontology path — not SPARQL-fail→RAG-hallucinate. |
| Disambiguation rate **26.7%**, data-grounded only **20.0%** | `H_evaluation_summary.md` | The system over-asks for clarification and under-grounds. Structured clarification + grounding verification are high-leverage. |
| Personas have **distinct domain mixes**, not just tone | `D3_user_personas.md`, `G4` | Persona must bias *retrieval and routing*, backed by D3 priors — promoted, not deferred. |
| Borda top-6 topics: Temperature, Air Quality, **Fire Safety (#3)**, **Security (#4)**, Lighting, Energy | `E1_topic_priority_table.csv` | Fire Safety & Security are top-4 priorities but are almost entirely CAPABILITY/INFO, not telemetry. The capability facility (Phase 0) directly serves the #3/#4 topics. |
| Survey eval P90 latency target 15.0s; current E2E P95 ≈ 68s | `H`, E2E run | STATUS queries (65%) need a sub-5s deterministic fast-path. |

**Revised sequence:** Phase 0 (Capability+Off-ontology facility) → Phase 1 (STATUS
fast-path + grounding verification) → Phase 2 (closed-loop self-correction =
thesis contribution) → Phase 3 (persona-as-router) → Phase 4 (structured
clarification + dialogue state) → Phase 5 (learning loop).

Rationale: Phases 0–1 fix the 91% case and the 24% off-ontology hole — the
largest answer-rate gains — **while the existing complex path (analytics,
compare, trend, anomaly, planner) is protected by a regression gate (see
Cross-cutting) so it cannot degrade.** Phase 2's self-correction is the headline
research contribution *and* it benefits the complex path most: a STATUS lookup
rarely needs repair, but a MULTI_STEP analytics query is exactly where bounded
reflexion earns its keep. So "fix the common path" and "complex path is the
differentiator" are complementary, not competing. Phases 3–5 are the
conversational-quality contributions the survey explicitly demands (G4 "persona
registry, not template strings"; "closed-loop feedback log").

**Evaluation note (no post-development study exists):** the post-design numbers
in the paper draft are placeholders. This plan's per-phase *measurable
artifacts* are therefore the project's only real evaluation. Instrumentation is
not optional polish — it is the empirical core of the thesis. Every phase below
must emit its artifact before it is considered done.

---

## Phase 0 — Capability & Off-Ontology Knowledge Facility (NEW)

**Why (survey):** CAPABILITY = 25.6% of corpus (P1). OTHER = 24.0%. Together
**~50% of all questions** currently have no grounded path — they fall through
SPARQL→RAG and hallucinate or refuse. The #3 and #4 Borda topics (Fire Safety,
Security) are dominated by these. Representative corpus questions: "what are
safety features?", "Can the building operate during a power outage?", "Are there
smart devices in this room I can control?", "How would I pass on a complaint?"

**What to build:**
1. A structured **Building Capability KB**: a per-building YAML/JSON
   (`input/<bldg>/capability.yaml`) enumerating real building features &
   system capabilities (HVAC zoning, fire/evacuation, access control, lighting
   control scope, amenities, policies, contacts). Schema-validated.
2. A `capability` intent route → `CapabilityAgent` that answers from the KB with
   provenance ("This building has X; source: capability profile"), and an
   explicit, honest boundary when the KB has no entry ("I don't have that on
   record for this building" — not a hallucinated guess).
3. Off-ontology classifier hook: when `domain_l1=OTHER` or `query_type=CAPABILITY`,
   route to `CapabilityAgent` *before* attempting SPARQL.

**Files:**
- Create: `input/bldg1/capability.yaml`, `shared/capability_schema.py`
- Create: `orchestrator/agents/capability_agent.py`
- Modify: `orchestrator/workflow.py` (`_build_graph`, `_route_from_dialogue`)
- Modify: `orchestrator/agents/dialogue_agent.py` (emit `query_type_l2`,
  `domain_l1` per `G1_classification_framework.md` six-tuple)

**Measurable artifact / paper hook:** answer-rate lift on the OTHER + CAPABILITY
strata (currently the worst), reported as a before/after on the H-phase
`answer_rate_by_query_type` table. Direct evidence for RQ on coverage.

---

## Phase 1 — STATUS Fast-Path + Grounding Verification

**Why (survey):** STATUS = 65.4% of corpus, P1, but only 8.68% analytical —
i.e. almost all STATUS answers are a single point/recent reading that needs no
LLM SPARQL synthesis. Survey eval data-grounded rate is only 20.0% and P90
latency target is 15s vs current P95 ≈68s.

**What to build:**
1. Extend the existing template-first SPARQL path into a true **STATUS
   fast-path**: deterministic entity-link → templated SPARQL → single SQL → no
   analytics node. Target <5s, no complex-model LLM call.
2. A `VerifierNode` after sparql/sql: cheap-model structured check —
   does the answer follow from the retrieved triples/rows?
   `{grounded: bool, confidence: 0–1, missing: [...]}`.
3. Attach a **confidence + provenance** object to every answer
   (SPARQL-grounded vs RAG-inferred, source sensor IDs, time window). Removes
   the validity threat to any accuracy number in the paper.

**Files:**
- Modify: `orchestrator/agents/sparql_agent.py` (promote template path,
  STATUS detection), `orchestrator/workflow.py` (add VerifierNode + edge)
- Create: `orchestrator/agents/verifier_agent.py`
- Modify: `shared/models.py` (`ConversationState`: add `provenance`, `confidence`)

**Measurable artifact:** data-grounded rate (target: 20% → materially higher on
STATUS stratum), median latency back toward survey's 5.33s, and a
grounded-vs-inferred split that becomes a paper figure.

---

## Phase 2 — Closed-Loop Self-Correction (THESIS CONTRIBUTION)

**Why (survey):** G4 "Future work hooks" explicitly calls for a *closed-loop
feedback log*. The original Q3 ("system fixes itself") becomes the headline
research methodology, now measurable because Phases 0–1 made the common path
solid (so correction traces reflect genuine reasoning failures, not trivia).

**What to build:**
1. Generalise the SPARQL repair loop + analytics code-fix loop into one
   `SelfCorrectionPolicy` interface. **Give SQL the same loop** (feed DB error +
   failed SQL + question back to the LLM) — currently the only data node with
   no repair (`sql_agent.py:608-615`).
2. Wire the Phase-1 `VerifierNode` into a bounded reflexion edge: on
   `not grounded`/low confidence, loop **once** back to the failed node with the
   verifier critique injected (Reflexion pattern). Hard cap, fully instrumented.
3. Emit a structured `correction_trace` per query: attempt count, strategy,
   before/after query, final confidence, terminal outcome.

**Files:**
- Create: `orchestrator/services/self_correction_policy.py`
- Modify: `orchestrator/agents/sql_agent.py` (add repair loop),
  `orchestrator/workflow.py` (`_route_from_verifier` conditional edge),
  `orchestrator/agents/sparql_agent.py`, `orchestrator/agents/analytics_agent.py`
  (conform to the policy interface)

**Measurable artifact:** the `correction_trace` corpus → recovery-rate,
attempts-to-success distribution, and "self-healed without user intervention"
% — the central quantitative result of the methodology contribution. **Report
this split by query complexity (LOOKUP / AGGREGATION / MULTI_STEP):** the
expected and most defensible result is that self-correction recovers the
complex/analytical strata (where single-shot fails most) — turning the survey's
"low volume" complex queries into the strongest evidence for the contribution
rather than a de-scoped tail.

---

## Phase 3 — Persona-as-Router (not post-hoc restyling)

**Why (survey):** D3 gives hard per-persona domain priors (Guests/Occupants →
AIR_QUALITY/THERMAL/ENERGY, INFORMATIONAL ≥93%, LOOKUP 84–88%; IT → DIAGNOSTIC
9%; Building Owners → Temperature priority rank 2.2). G4: "response generator
must consult a persona registry, not just template strings." Current
`persona_adapter.py` only restyles the finished answer.

**What to build:**
1. A **persona registry** seeded directly from `D3_user_personas.md` +
   `E1_topic_priority_table.csv`: per-persona domain priors, default complexity,
   default temporal scope, clarification aggressiveness.
2. Inject persona priors into (a) entity/domain disambiguation (break ties
   toward the persona's top domains), (b) sensor selection ordering, (c) answer
   depth — *before* generation, not after.
3. Keep the existing post-hoc styler as the final formatting step only.

**Files:**
- Create: `shared/persona_registry.py` (data sourced from survey D3/E1)
- Modify: `orchestrator/agents/dialogue_agent.py` (consult registry in
  disambiguation), `orchestrator/agents/sparql_agent.py` (persona-biased
  candidate ordering), `orchestrator/services/persona_adapter.py` (formatting only)

**Measurable artifact:** per-persona answer-rate (H9 `answer_rate_by_role`)
before/after; demonstrate persona-conditioned retrieval improves the personas
the survey shows are currently underserved.

---

## Phase 4 — Structured Clarification + Dialogue State

**Why (survey):** Disambiguation rate is **26.7%** (H) — over a quarter of
queries end in a clarification request, and the audit shows those requests are
*passive/vague* ("I need more info") even though `disambiguation_service.py`
already computes the candidate list.

**What to build:**
1. Add `dialogue_state` to `ConversationState` (turn phase, pending
   clarification, bound entities).
2. Convert passive clarification into structured choice: surface the
   `disambiguation_service` candidates as "Did you mean A / B / C?" and resume
   on the bound entity in the next turn.
3. Clarification-aggressiveness from the persona registry (Phase 3): occupants
   tolerate fewer round-trips than IT.

**Files:**
- Modify: `shared/models.py` (`dialogue_state`),
  `orchestrator/workflow.py` (clarification loop edge),
  `orchestrator/agents/dialogue_agent.py`,
  `orchestrator/services/disambiguation_service.py`

**Measurable artifact:** convert "DISAMBIGUATION" outcomes into resolved
GROUNDED answers within 2 turns; report disambiguation→resolution rate as a
conversational-quality result.

---

## Phase 5 — Learning / Feedback Loop

**Why (survey):** G4 future-work hook #3: "Add a closed-loop feedback log so
production responses feed Phase-B-style corpus statistics, allowing priority
tiers to drift with usage." Closes the loop between deployment and the corpus
methodology — a defensible longitudinal contribution.

**What to build:**
1. Capture corrections & rejections: store `(query, wrong, corrected,
   persona, outcome)` — **failures too**, not just successes (current
   `agent_memory.py` stores only successes).
2. Use stored corrections as retrieval-augmented few-shot for intent + entity
   resolution (no retraining).
3. Periodic export in the Phase-B taxonomy six-tuple so production traffic can
   be re-scored against the survey corpus.

**Files:**
- Modify: `orchestrator/services/agent_memory.py` (store failures + corrections)
- Create: `scripts/export_production_corpus.py` (six-tuple per `G1`)
- Modify: `orchestrator/agents/dialogue_agent.py` (RAG few-shot from corrections)

**Measurable artifact:** drift analysis — production query distribution vs
survey corpus distribution over time; improvement in intent accuracy as the
correction corpus grows.

---

## Cross-cutting: classification alignment

The dialogue agent should emit the **G1 six-tuple**
(`domain_l1, query_type_l2, intent, temporal, spatial, complexity`) on every
turn and persist it. This: (a) drives Phase 0 routing, (b) makes every later
phase measurable against the survey's own taxonomy, (c) lets production traffic
be analysed with the *exact* Phase-B scripts. This is the single highest-leverage
cross-cutting change and should land alongside Phase 0.

## Complex-query path: protected differentiator (NOT de-scoped)

Earlier framing wrongly proposed de-scoping the analytical path. Corrected:

- **COMPARISON, ANOMALY, HISTORICAL** — low volume but `analytical_share_pct=100`
  and survey-tiered **P1 must-support** (`G2`). These are the system's core
  differentiator: the questions a zero-knowledge user cannot otherwise express.
  Treated as first-class. Phase 1's grounding verifier and Phase 2's
  self-correction apply to them *first*, because that is where they pay off.
- **MULTI_STEP analytics/planner (3.0%)** — maintained as a working capability
  and regression-gated. Not expanded with new features until Phases 0–1 land,
  but explicitly **not allowed to regress**.
- **DIAGNOSTIC causal model (1.98%, P3)** and **RECOMMENDATION depth (1.72%,
  P3)** — the *only* genuine deferrals, and by the survey's own tiering, not by
  fiat. Current behaviour maintained; deeper causal/prescriptive modelling is
  post-thesis.

The narrative: the system democratises expert building analytics for the ~96%
of users who could never write it themselves. Rarity is what makes nailing it
impressive, not a reason to neglect it.

## Cross-cutting: no-regression discipline (mandatory for every phase)

The explicit requirement is "improve the system without introducing issues or
errors." No plan can guarantee zero bugs, but this discipline makes regressions
detectable and cheap to revert:

1. **E2E gate.** The 142-question harness (`scripts/pipeline_test_openwebui.py`)
   is the regression oracle. Capture a baseline PASS/WARN/FAIL + per-intent
   table before a phase; a phase is *not done* if any previously-PASS question
   regresses to WARN/FAIL, or if the complex-intent pass rates
   (analytics/compare/trend/anomaly) drop.
2. **Feature-flag risky routing.** New routes (Phase 0 capability route, Phase 1
   STATUS fast-path, Phase 2 reflexion edge) land behind an env flag, default
   off, enabled per-phase after the E2E gate passes — so any regression is a
   one-line revert, not a rebuild.
3. **One phase at a time, behind its own branch.** No phase starts until the
   previous phase's E2E gate is green and its measurable artifact is emitted.
4. **Additive, not destructive.** Each phase adds nodes/edges/agents; it must
   not rewrite the working SPARQL/SQL/analytics core. The forward DAG keeps
   working even with every new flag off (graceful no-op).
5. **Golden-path smoke tests** for the 6 Borda-top domains
   (Temperature, Air Quality, Fire Safety, Security, Lighting, Energy) run
   before every restart, mirroring the two smoke-tests already used this session.

This section is binding on Phases 0–5; treat it as acceptance criteria, not
advice.

## Sequencing summary

```
Phase 0  Capability + off-ontology facility   ──┐  (largest answer-rate gain)
Phase 1  STATUS fast-path + grounding verify  ──┤  fixes the 91% case
   ── G1 six-tuple emission lands here ──────────┘
Phase 2  Closed-loop self-correction          ───  THESIS CONTRIBUTION
                                                   (recovers the complex strata)
Phase 3  Persona-as-router                    ──┐
Phase 4  Structured clarification + state     ──┤  conversational-quality
Phase 5  Learning / feedback loop             ──┘  contributions (G4 asks)

   complex path (compare/anomaly/historical/analytics) ── protected by the
   no-regression E2E gate through ALL phases; never de-scoped, never regressed
```

Each phase is independently shippable and independently measurable against an
existing survey table — so each maps to a thesis result without waiting for the
whole programme. The no-regression discipline section is binding acceptance
criteria, directly answering the requirement that changes "only improve the
system without introducing issues or errors."

## Suggested starting point

Phase 0 is the highest answer-rate gain and the lowest regression risk (it adds
a new route + KB; it touches no existing SPARQL/SQL/analytics logic). Recommend
starting there. Before writing code, this plan should be turned into a
task-by-task spec (writing-plans flow) so each step has exact file paths, the
capability schema, and TDD steps — implementation should not begin from this
strategic document alone.
