# Pipeline planning, memory, retry and honesty — audit

**Date:** 2026-09-17 · **Branch:** `development` · **Scope:** read-only audit, no code changed
**Against:** *"My system should always smartly plan the flow of the pipeline based on the
questions and the previous questions and guess the intents and plan the pipeline and give the
right and honest replies with retry loop on failures within the system."*

---

## 1. Verdict in one paragraph

Four of the five clauses are built, and two of them are built unusually well. **Intent guessing**
is a 44-rule ordered contract with a pinned-precedence test — this is real, deterministic, and
survives an LLM outage. **Honest replies** is the strongest part of the system: a referent
existence gate, a publication gate, a disclosure gate, a typed turn-outcome taxonomy and a
co-reference safety check that refuses to launder a swapped room. **Previous questions** are used,
but only by a rewrite and a two-key carry-forward, neither of which reaches the planner or the
routing contract — and the carry-forward's safety guard exists on **one endpoint only** (§4.2b).
The two genuinely weak clauses are **"plan the pipeline"** — the LangGraph topology is static,
every node leads to `response`, and there is no re-plan edge — and **"retry loop on failures"**,
which works at the LLM call, SQL syntax and analytics code, and nowhere else: `_safe_node`
records a typed failure and moves on with **zero** retries, while the one multi-strategy
self-correction engine has two of its four strategies inert and a fast path that has never fired.

The serious risk for tomorrow is not the missing retry loop. It is that several failure paths
**substitute a different answer** instead of retrying or declining — and the worst of them, the
semantic-RAG fallback, both **discards an honest decline that was already composed** and
**structurally bypasses the publication gate**, because the verifier crashes on its own result
shape and the crash is logged at DEBUG.

---

## 2. Scorecard

| Clause of the intention | State | Where |
|---|---|---|
| Guess the intent | **Built, strong** | `routing_contract.py` 44 ordered rules + LLM classifier that sees ~5 prior messages |
| Use previous questions | **Partial, and endpoint-dependent** | rewrite + 2-key carry-forward; `prune_inherited` on `/v1/chat/completions` only (§4.2b); planner and routing are single-turn |
| Plan the pipeline | **Weak / mostly static** | `_graph.py:41` static topology, no re-plan edge; `goal_planner.py` unwired |
| Honest replies | **Built, strongest part** | referent gate, publication gate, disclosure gate, turn_outcome — with one structural hole (§5 S4) |
| Retry loop on failures | **Three places, one of them half-inert** | `llm_manager` 3 attempts, `sql_agent._repair_sql` 2, `analytics_agent` 3-with-deadline. `_safe_node`: **none**. Self-correction: 2 of 4 strategies inert |

---

## 3. Already implemented — do not build these again

### 3.1 Intent guessing (strong)

- **The routing contract is real and ordered.** `orchestrator/services/routing_contract.py`
  holds **40 parse-stage + 1 post-stage + 3 concept-stage = 44** rules
  (`routing_contract.py:1798`, `:2016`, `:2025`). Precedence is the contract: `apply_contract`
  walks the stage tuple in order, first rule whose `fn` returns an intent wins the rewrite, and
  every applied name is recorded on `normalized["routing_rules_applied"]`
  (`routing_contract.py:2059-2104`). A rule that raises is logged and skipped so a broken rule
  cannot break routing (`:2085-2087`).
  > **CLAUDE.md is stale here.** It says "36 parse-stage + 1 post-stage + 3 concept-stage,
  > counted 2026-09-08". The file now holds 40 parse-stage rules. Same failure mode the file
  > itself warns about.
- Order is pinned by a test that asserts the literal name list:
  `tests/test_routing_contract.py:237 test_precedence_order_is_pinned`.
- **The contract survives an LLM outage.** On a classification exception the fallback dict is
  still run through parse and post stages (`dialogue_agent.py:1171-1190`) and documents may still
  claim it (`:1200`). This is BUG-167's fix and it is correct.
- **A classification failure is never cached** (`dialogue_agent.py:1146-1149`) — a wrong intent
  cannot get pinned to a question for an hour.
- The intent-detection prompt cache key is a hash of the **whole prompt**, which includes the
  conversation history (`dialogue_agent.py:1095-1106`), so the cache is history-sensitive by
  construction. Good.

### 3.2 Honest replies (strongest part of the system)

These are all live on the request path and all worth demoing:

| Guarantee | File:line | Failure direction |
|---|---|---|
| Referent existence gate, once for every lane | `_orchestrator.py:1931 _gate_referent_once` | fails **open** (deliberate) |
| Publication gate — withholds text, chart *and* export | `_orchestrator.py:5526-5559`, `publication_gate.py:170` | fails **open** (deliberate) |
| Disclosure gate — a policy refusal governs every channel | `_orchestrator.py:5503-5522` | fails **closed** (deliberate) |
| Typed turn outcome — timeout ≠ unreachable ≠ defect | `services/turn_outcome.py:46-57`, surfaced at `_orchestrator.py:5475-5490` | never costs the turn |
| Co-reference rewrite cannot swap the referent | `context_switch.py:131 rewrite_is_safe`, called `dialogue_agent.py:668-677` | rejects the rewrite |
| Context switch prunes place-bound carry-forward | `context_switch.py:112 prune_inherited`, called `main.py:3736` | prunes only on a positive switch |
| Reference to an earlier reply that does not exist | `_orchestrator.py:1314-1324` | declines |
| CQ-IR compiler declines rather than guesses | `compiler.py:193-262`, `:429-440` | emits `AmbiguitySignal` → clarification |
| Graph drift during the turn is reported, never retried | `_orchestrator.py:5431-5466` | reports |

The comment at `_orchestrator.py:5434-5435` is the design principle the owner is asking for,
already written down: *"It reports and never retries: a retry would answer from the NEW mapping
and say nothing about the old one, which is the same silent substitution one layer up."*

### 3.3 Retry that is already correct

- **LLM calls**: `LLM_MAX_RETRIES=3` with exponential backoff (`llm_manager.py:53-56`,
  loop at `:354-419`), a circuit breaker at 5 failures / 30 s recovery (`:180`), retryability
  classification (`:281-302`), an **empty completion promoted to a retryable error**
  (`:374-383`), and a longer wait when the local runner has *crashed* rather than merely stalled
  (`:59-95`, `:411-417`). Identical prompt, identical client, no model downgrade — the model is
  chosen once before the loop at `:331`. Correct shape. On exhaustion it re-raises after
  `record_llm_failure` (`:421-423`); it never fabricates text.
- **SQL syntax repair**: `sql_agent.py:959-1013 _repair_sql`, 2 bounded attempts, feeds the DB
  error back, *keeps the same logical intent*, and **returns `[]` when exhausted** rather than
  substituting (`:1012-1013`). This is the pattern the owner wants — with one caveat, see R3 below.
- **Analytics / code-executor repair**: `analytics_agent.py:834-903 _execute_with_retries`, up to
  3 executions with up to 2 LLM code repairs, governed by a **deadline** rather than a backoff —
  50 % of `WORKFLOW_TIMEOUT_S` (`:76-94`) — and returns an explicit failure, never a fabricated
  number (`:896-903`). Good shape. (`gave_up_early` at `:873-888` has no production consumer.)
- **Embedding service**: 3 attempts, explicit `(1.0, 2.0, 4.0)` backoff, raises `EmbeddingError`
  on exhaustion — `embedding_service.py:44`, `:202-233`.
- **Per-lane retry accounting already exists and is correct.** `_record_lane_outcome`
  (`_orchestrator.py:575-601`) sets `first_pass=False` automatically when a lane already has an
  entry for this turn, and `TurnOutcome.first_pass_ok` / `.retried` roll it up
  (`turn_outcome.py:189-201`). **Nothing currently re-runs a lane, so this never fires** — but
  it means a lane-level retry can be added with zero accounting work.

---

## 4. Genuinely missing

### 4.1 The pipeline is routed, not planned

`_build_graph` (`workflow/_graph.py:41-245`) builds a **static DAG**. Every intent node gets
exactly one outgoing edge to `response` (`:232-234`), the data lanes go
`sparql → sql → analytics → response` through conditional edges that only look *forward*
(`:145-174`), and there is **no edge that returns to `dialogue` or to any earlier stage**. A turn
therefore executes exactly one attempt at exactly one shape. "Plan the pipeline" is currently
"choose a lane once, from the text of one question."

Three would-be planners exist and none of them plans:

| Component | State | Evidence |
|---|---|---|
| `GoalPlanner` | **completely unwired** — zero importers in `orchestrator/` | only reference is the flag definition `shared/config.py:567` |
| `GOAL_PLANNER_ENABLED` | default `False` | `shared/config.py:568` |
| `MultiIntentDetector` → `planner` | **wired and on by default** | `_orchestrator.py:1886-1910`; `MULTI_INTENT_ENABLED` default `True` at `shared/config.py:564` |
| CQ-IR compiler (ARBITER) | **wired**, single-shot, no re-compile on ambiguity | `_orchestrator.py:6792`, `compiler.py:429-450` |

Multi-intent decomposition is the one genuine planner: it decomposes a compound question and
overrides the intent to `planner` (`_orchestrator.py:1908`). It is guarded against eating a
register-answerable question (`:1866-1884`). But it plans from **the current question's text
only** — `_detector.detect(_user_q, state.current_intent, entities)` at `:1898` receives no
history.

### 4.2 Previous questions reach two places, and neither is the planner

There is no single "conversation memory". **Four independent channels** carry state, with
different scopes, bounds and consumers:

| Channel | Storage | Bound | Read by |
|---|---|---|---|
| A. `state.messages` | Redis `conversation:<id>` + client-supplied `messages[]` | 20 (`CONVERSATION_MAX_MESSAGES`, `config.py:674`) | coref rewrite, intent prompt, SPARQL prompt, affirmation detector |
| B. `turn_memory.carry_forward` | Postgres `turn_memory` | **last 1 row**, exactly 2 keys | `main.py:3710` → `intermediate_results` |
| C. `turn_memory.get_older_context()` | Postgres `turn_memory` | 30 rows, offset 20 | injected as a `system` message |
| D. `agent_memory` (per-**user**, cross-session) | Qdrant `user_memory` | top-5 of 200 | `memory_context` in the intent prompt only |

Channel B's whitelist is exactly two keys: `_CARRY_FORWARD_KEYS = {"forecast_result",
"analytics_result"}` (`turn_memory.py:24`; mirrored as `_CARRIED_FORWARD_ON_PURPOSE` at
`_orchestrator.py:507`). Everything else is wiped each turn by `_clear_stale_lane_results`
(`_orchestrator.py:712-738`).

**The previous turn's intent is persisted and never read back.** `turn_memory.py:61` writes it;
`get_carry_forward` selects only the `carry_forward` column (`turn_memory.py:99-100`), and
`get_older_context` uses intent only as display text inside a prose line (`:144`). A repo-wide
grep for `previous_intent` / `last_intent` / `previous_answer` / `already_tried` in
`orchestrator/` returns nothing.

Answering the specific question "does prior context influence planning?":

| Consumer | Sees history? | Evidence |
|---|---|---|
| LLM intent classifier | **Yes** — summary + last 5 messages | `dialogue_agent.py:1074-1079`, injected at `:1385` |
| Routing contract rules | **No.** `_Ctx` carries `query`, `ql`, `normalized`, `sr` and nothing else | `routing_contract.py:310-321` |
| `MultiIntentDetector` | **No** | `_orchestrator.py:1898` |
| CQ-IR compiler | **No** — compiles `query` + this building's modalities | `compiler.py` `compile_query` signature |
| Co-reference rewrite | **Yes** — last 6 messages | `dialogue_agent.py:626` |
| Carry-forward (`analytics_result`, `forecast_result`) | **Yes**, pruned on subject switch | `main.py:3736`, `context_switch.py:112` |
| Agent memory (`user_memory` Qdrant) | **Yes**, injected into the classifier prompt | `_orchestrator.py:1201-1203` |

The follow-up detector is a **keyword heuristic**: `_is_followup_query`
(`dialogue_agent.py:266-282`) returns True for ≤ 4 words, a leading "and/also/then/what about",
or a deictic word. A follow-up phrased as a full sentence without a pronoun —
*"And what were the humidity levels over the same period?"* — depends on the marker list; anything
outside it gets **no rewrite at all** and is classified as if the conversation had not happened
(the classifier still sees history in its prompt, so this degrades rather than breaks).

Also worth knowing: every **deterministic pre-LLM short-circuit** inside `detect_intent` is
history-blind — self-description (`dialogue_agent.py:766-782`), the TTL capability/record probes
(`:833-840`), the readiness/metrology/events/wayfinding regexes (`:805-820`). They fire before the
history-bearing prompt is ever built.

And the classifier's window is much smaller than the stored history: `prune_messages(...,
max_messages=5)` at `dialogue_agent.py:1075`, then `format_conversation_history` drops the current
message and truncates each remaining one to 200 chars (`:205-216`). **The classifier sees ~4-5
prior messages, not 20.** The rewrite sees 6 (`:626`).

Silent truncation to be aware of: `get_older_context(skip_recent=20, max_older=30)`
(`turn_memory.py:112-137`) means turns 21-50 back are summarised and **anything older than ~50
turns is invisible** although 500 rows are retained (`turn_memory.py:30`). Every Postgres failure
in that module degrades to `{}` / `""` behind a `logger.warning` (`:88-89`, `:108-109`,
`:148-149`) — carry-forward and older context can vanish with no user-visible signal.

### 4.2b The demo endpoint and the probe endpoint do not share their memory wiring

**This is the finding I would most want the owner to know before tomorrow.**

`turn_memory` — `save_turn`, `get_carry_forward`, `get_older_context` — and the context-switch
guard `prune_inherited` are wired into **`/v1/chat/completions` only**
(`main.py:3710`, `:3736-3744`, `:3759`, `:3894`, `:3975`; endpoint at `:3572`).

`/chat` (`main.py:2363`), `/chat/stream` (`:2619`) and the `/stream` websocket (`:3152`) call
**none** of them. Those paths load the whole prior `ConversationState` from Redis, and
`_clear_stale_lane_results` deliberately **preserves** `forecast_result` and `analytics_result`
(`_orchestrator.py:507`, `:728-729`). So on those three endpoints the exact V12-11/A14 bug
`context_switch.py` was written to fix — *"what is the temperature in 5.01?"* then *"what about
room 3.27? plot it"* — is **still reachable**, because nothing prunes the place-bound carry-forward.

The consequence cuts both ways and both halves matter:

- **The demo is safe on this axis.** Open WebUI uses `/v1/chat/completions`
  (CLAUDE.md says so explicitly), which is the endpoint that *has* the guard.
- **The probe cannot see it.** `scripts/regression_probe.py` uses `/chat`, which has no turn
  memory at all. So **60/60 on the probe is not evidence about conversational behaviour** — the
  probe path does not carry state forward, does not prune it, and does not exercise
  `prune_inherited` even once.

Do not "fix" this today by wiring turn_memory into `/chat`. Note it, and rely on the demo
endpoint.

### 4.3 No memory of failure

Failures **are** stored: `agent_memory.store_failure` (`_orchestrator.py:5622`,
`agent_memory.py:365-386`). But:

1. Nothing reads them back to change behaviour. There is no "this shape failed last time, try
   differently."
2. Worse: `_search` (`agent_memory.py:309-329`) applies **no filter on `memory_type`** and **no
   score threshold**, so a stored failure is retrieved alongside successes and rendered into the
   classifier prompt as `Answer: [FAILURE] ...` under the heading *"Relevant memories from this
   user's history"* (`agent_memory.py:300-307`). The Qdrant path passes no `score_threshold`; the
   fallback path (`:327-329`) is pure recency with no relevance test at all.

This is prompt contamination, not a wrong answer, and it is low-severity. But it is the opposite
of a learning loop. `agent_memory.py:22` claims the module implements *"failed clarification
patterns (avoid repeating same clarification question)"*; no retrieval-side logic implements it.

The closest thing to a cross-turn behavioural memory is `pending_clarification_type` /
`user_context` (`_orchestrator.py:1210-1227`) — "I asked a question last turn, here is the
answer" — and it is a resume mechanism, cleared unconditionally at `:1226-1227`. The only true
*negative* memory in the system is `_orchestrator.py:1311-1324`, which refuses when the user
refers to an earlier reply that does not exist. That is absence-of-history, not memory-of-failure.

`self_correction_engine`, `turn_outcome` and `retrieval_outcome` are all **within-turn**
classifiers. Nothing survives the turn boundary as a "do not try that again" signal.

### 4.4 The SPARQL self-correction engine is wired, and two of its four legs are inert

`SelfCorrectionEngine` **is** on the live request path: constructed at `sparql_agent.py:205`,
invoked at `:551`, reached from the graph at `_orchestrator.py:2201`. It runs 4 iterations
(`self_correction_engine.py:331`, `max_attempts=3` at `:43`) over 4 strategies (`:299-302`),
each execution capped at 30 s. As wired:

| Leg | State | Evidence |
|---|---|---|
| `SyntaxFixStrategy` | live | `self_correction_engine.py:299` |
| `PrefixRepairStrategy` | live | `:300` |
| `LLMRegenerationStrategy` | **no-op** — the caller passes `"llm_call": None` | `sparql_agent.py:549`; strategy returns unchanged at `self_correction_engine.py:194-195` |
| `TemplateSchemaFallbackStrategy` | **computed, never executed** — at `attempt_num == 4` the break guard `4 > 4` is False, so the strategy runs and assigns `current_query`, then `range(1, 5)` is exhausted | guard `:387`, apply `:402-409`, loop `:331` |

So "self-correction" is, in practice, two regex passes. Three further defects:

- **The empty-result fast path never fires.** The engine short-circuits on the exact string
  `"Empty result set"` (`:395`), but its own executor emits `"Empty results"`
  (`sparql_agent.py:516`) and `error` takes that first (`:349-351`). Every genuinely empty graph
  result therefore burns all four iterations — **up to three extra SPARQL executions, 30 s
  timeout each** — before falling through. On the demo path, every honest "no data" answer pays
  that latency. This is the opposite of the documented intent at `:391-394`.
- **The engine's honest decline is discarded.** On exhaustion it composes
  *"I attempted to answer your query but encountered difficulties after N correction attempts…"*
  (`:436-442`). `sparql_agent.py:554-565` reads only `correction_result["results"]` and, finding
  none, calls `answer_semantically`. **The decline the engine wrote never reaches the user; RAG
  prose does.** This is the single clearest instance of the owner's stated concern in the
  codebase.
- Minor: `state` is not passed at `sparql_agent.py:551-553`, so
  `state.intermediate_results["correction_log"]` is never written on the live path, despite the
  module docstring claiming it.

### 4.5 `_safe_node` never retries

`_orchestrator.py:960-1024`. One `await node_fn(state)`, one `except`. It classifies the failure
type correctly (`:983`), records it (`:984`), seeds empty-but-valid results for the data lanes
(`:1001-1017`) and appends a user-visible degradation notice (`:1019-1021`). Zero retries. A
`ReadTimeout` on GraphDB — which `turn_outcome.py:23-29` documents as *frequently latency rather
than a defect*, with a measured 10.7 s / 61.1 s / 13.3 s spread on the same question — costs the
whole answer, and the user is told to ask again (`turn_outcome.py:140-143`) by a system that
could have asked again itself.

### 4.6 Retry configuration that does nothing

| Symbol | Claim | Reality |
|---|---|---|
| `settings.MAX_RETRY_ATTEMPTS` (`shared/config.py:561`) | `config.py:949` states *"llm_manager retries each call up to MAX_RETRY_ATTEMPTS times"* | **Never read anywhere.** `llm_manager.py:53` reads the env var `LLM_MAX_RETRIES` and ignores the setting. Changing it does nothing. |
| `ConversationState.retry_count` (`shared/models.py:316`) | "Number of retry attempts" | Declared; never incremented, never read. |
| `self_correction_policy.SelfCorrectionPolicy` (`services/self_correction_policy.py:48`) | its own docstring at `:125` says *"imported by sql_agent and analytics_agent"* | **Zero production importers.** Only the module, four references in `tests/test_survey_aligned_phases.py`, and a plan doc. `correction_trace` is never written by any live turn. |
| Circuit breakers | `circuit_breaker.py:4` advertises GraphDB and RAG | Only **two** exist in product code: `llm` (`llm_manager.py:180`) and `mysql` (`adapters/mysql_adapter.py:250`). **There is no GraphDB breaker** — the store whose failure started BUG-631. |

One sceptical note on the LLM breaker: `record_failure()` fires on *every* failed attempt
(`llm_manager.py:392`, `:395`), so one user request that burns all 3 attempts contributes 3 of
the 5 failures needed to open it. Two unlucky consecutive requests open the LLM breaker for 30 s
— during a demo, that is every lane failing at once.

---

## 5. The failure mode the owner most wants to avoid — every instance found

**A "retry" that answers a different question.** Ordered by severity. Tier 1 drops the
constraint the user named.

### Tier 1 — unscoped substitution

| # | What substitutes | file:line | What it drops |
|---|---|---|---|
| S1 | `_get_instances_for_class` — first N instances of a Brick class, building-namespace filter only | `sparql_agent.py:2997` | **all** spatial scope. This is the BUG-631 primitive; BUG-631 fixed the *prefix bug upstream* and explicitly left this in |
| S2 | Its caller runs **before** floor scoping and feeds 40 unscoped IRIs to the LLM as candidates | `sparql_agent.py:429-437`, used at `:487`; `_floor_scoped_sparql` not called until `:449` | floor/room |
| S3 | `_pattern_instance_search` — IRI substring match, no spatial predicate | `sparql_agent.py:3286` | all scope |
| S4 | **Semantic-RAG fallback on zero SPARQL results** — answers from vector retrieval over a different corpus, **discarding the honest decline the correction engine just composed** (`self_correction_engine.py:436-442`) | `sparql_agent.py:554-565` → `answer_semantically` `:256-277` | everything. Context came from `top_k=10, min_score=0.3` with no building/floor/class filter (`:1478-1486`) |
| S5 | `_fallback_pattern_search` preserves dotted room ids only | `sparql_agent.py:3663-3664`, returns at `:3690` | `floor 3` / `3rd floor` produce no dotted id → `loc_filter` empty → 50 building-wide points |
| S6 | Wrong-modality UUIDs kept when the kind filter matches nothing (`else` branch keeps the unfiltered set) | `_orchestrator.py:2635-2640` | modality |
| S7 | **SQL auto-expand** — 0 rows in window → refetch last 200 rows *regardless of date* | `sql_agent.py:643-690` | the time window |
| S8 | Anomaly lane rewrites the question's modality to temperature | `_orchestrator.py:2005-2007` | modality (documented/deliberate) |

**S4 is the one I would fix first, and here is why it is worse than it looks.**
`answer_semantically` returns `"success": True` with `results` as a **list**
(`sparql_agent.py:267-277`). The verifier reads
`sparql_result.get("results", {}).get("results", {}).get("bindings", [])`
(`verifier_agent.py:168`) — on a list that raises `AttributeError`. I confirmed this by
evaluating the expression against the exact literal shape. The call site swallows it at
**DEBUG** (`_orchestrator.py:4774-4777`), so **no `verification` record is written**, and
`publication_gate.evaluate` returns `publish=True` on a missing record by design
(`publication_gate.py:189-192`). Net effect:

> The single path most likely to produce an ungrounded answer is the single path on which the
> publication gate never runs — and nothing logs above DEBUG that this happened.

**S7 is the one most likely to embarrass the demo.** The guard is a keyword list
(`sql_agent.py:644-663`) that includes `today`, `hour`, `week`… but **not** `right now`,
`currently`, `at the moment`, `latest`, or `live`. So *"what is the CO2 right now?"* with no
recent rows returns up to 200 rows of arbitrary age, and **nothing sets a flag** — I grepped for
`window_expanded` / `expanded_window` / `fallback_window` and the only hits are the two log lines
at `sql_agent.py:666` and `:689`. The answer reaches the user with no indication its window moved.

### Tier 2 — residual scope holes in the BUG-632 fix

| # | Issue | file:line |
|---|---|---|
| S9 | Floor extraction for the modality repair is `\b(?:floor\|level)\s*(\d+)\b` — misses `3rd floor`, `ground floor`, `top floor`; and a **room**-scoped question has no floor token at all, so the repair reverts to building-wide | `_orchestrator.py:2236`, `:2245-2247` |
| S10 | Uses `settings.BUILDING_NAMESPACE` (process-global) rather than the per-request namespace; `building_id` is not threaded into `needs_repair` / `build_modality_query` | `_orchestrator.py:2245`, `modality_repair.py:198,241,277` |
| S11 | The `_miss` branch replaces results unconditionally — the under-populated branch has a "never shrink" guard, this one has none | `_orchestrator.py:2257-2263` |

### Tier 3 — substituted results that then get cached or reused

| # | Issue | file:line |
|---|---|---|
| S12 | **Unscoped fallback rows are written under the scoped query's cache key** for 1 h, so every later run of the *correct* query is served the substituted result — without even the fallback log line | `sparql_agent.py:3558` (key), `:3595`, `:3630` |
| S13 | `_instance_cache` keyed by Brick class only, not by building, on a long-lived agent instance | `sparql_agent.py:2993-2994`, `:203`; instance at `_orchestrator.py:891` |
| S14 | Prior turn's rows restored as this turn's answer for `compliance`/`compare`/`trend` with no check that they cover this question's entity/floor/window | `_orchestrator.py:2316-2320` (saved at `:2016`); same shape `:1383-1390`, inheriting prior entities at `:1374-1376` |
| S16 | `_repair_sql` exhaustion returns `[]` — **indistinguishable from "the database has no rows"**. Downstream "no data found" prose is then a false statement about the building | `sql_agent.py:1012-1013` |

### Tier 4 — the guard stands down on the error that starts the cascade

| # | Issue | file:line |
|---|---|---|
| S15 | `ReferentResolver` fails **open** on any exception, returning `SKIPPED`. BUG-631's trigger *was* a GraphDB error (`MALFORMED QUERY: Multiple prefix declarations`) — the gate would have skipped on exactly that query | `referent_resolver.py:520-522`, also `:394-396` |

Failing open is a defensible choice (the comment says so, and I agree with it for a live demo).
The problem is that failing open is **silent to the user**: nothing tells them the existence
check did not run.

### Checked and NOT this bug shape — these are honest retries, leave them alone

- `sql_agent.py:959-1013 _repair_sql` — same question, fixed SQL. Honest, but see **S16**: the
  empty list it returns on exhaustion is indistinguishable from a genuinely empty table.
- `sparql_agent.py:1881-1902 _repair_query` and `self_correction_engine.py` `SyntaxFixStrategy` /
  `PrefixRepairStrategy` — syntax repair of the same intent, `user_query` carried through.
- `modality_repair` (`_orchestrator.py:2205-2275`) is a substitution, but it is the **best-behaved
  one**: it fails open on exception (`:2272-2275`) and it **records what it swapped** in
  `intermediate_results["modality_repair"] = {modality, reason, was, now}` (`:2266-2271`). That
  audit trail is what S4, S7 and S12 are missing.
- `planner_agent.py:303-327 _fallback_plan` — degrades the *plan*, not the scope.
- `mysql_events_adapter.py:249` — `return "1=0"  # explicit empty match — never silently widen scope`. **This is the model to copy.**
- `response_cache` fuzzy match is **off by default** (`response_cache.py:80`) and gated on
  `salient_ids()` equality plus role/user partitioning. Residual: `salient_ids` matches only
  `\d[\d.]*` (`:225`), so two questions differing only in a *non-numeric* window ("this week" vs
  "this month") could fuzzy-match **if** fuzzy is ever turned on. Leave it off.
- **The pre-graph cache lookup looks dangerous and is not.** `_serve_from_cache` runs at
  `_orchestrator.py:9004`, *before* `graph.ainvoke` and therefore before the co-reference rewrite
  at `:1283`, and the cache key carries **no conversation id** (`response_cache.py:325-327`). But
  `put` stores under `state.messages[-2].content` (`_orchestrator.py:5578-5581`), which by then is
  the **rewritten** text — so a raw follow-up like *"what about there?"* can never match a stored
  entry. The asymmetry costs a cache miss, not a wrong answer. I checked this specifically
  because it is the shape that would be worst; it does not bite.

---

## 6. Ranked shortlist — at most 5, smallest change first

I am ranking by *(harm prevented) ÷ (blast radius)* with the 18:00 freeze in mind.
**A1, A2 and A3 are landable today. A4 and A5 are not, and I would say no to both if asked.**

If you only have appetite for one, take **A3** — it is a one-string change, it is provably safe in
direction, and it removes both a latency risk and a substitution vector.
If you want the biggest honesty win, take **A1**, but read its risk paragraph first: it changes
answers.

---

### A1 — Make the semantic-RAG fallback visible to the verifier · **LAND TODAY**

**Fixes:** the one path where the publication gate structurally never runs (S4).
**Change:** two lines. In `verifier_agent._sparql_returned_data`
(`verifier_agent.py:162-169`), guard the chained `.get()` so a list-shaped `results` returns
`False` instead of raising. That alone turns the semantic-RAG turn into
`grounded=False, source="none", confidence=0.20`, which the publication gate already knows how
to handle.
**Files:** `orchestrator/agents/verifier_agent.py` (1 function).
**Blast radius:** every turn calls `verify()`, but the guarded branch only changes behaviour for
result dicts whose `results` is not a dict — today that is the semantic-RAG shape and nothing
else. Turns that currently produce a verification record produce the identical one.
**Risk:** low-to-moderate, and the *direction* matters: it will start **withholding** answers that
are currently published. If the demo script contains a question that currently reaches
semantic RAG, this will change that answer from confident prose to a withheld/declined one.
That is the correct behaviour and it is also a demo-day surprise.
**Verify:** grep the demo script for questions that log
`"SPARQL returned no results, attempting semantic fallback"`; run those five or six by hand and
look at what the publication gate does. `pytest -m unit -q -k "verifier or publication"`.
**If you are not willing to accept a changed answer today:** land only the `logger.debug` →
`logger.warning` half at `_orchestrator.py:4777`, so you can *see* it happening during the demo
without changing any answer. That half is zero-risk.

---

### A2 — Name the expanded window when SQL auto-expands · **LAND TODAY**

**Fixes:** S7 — "what is the CO2 right now?" answered from rows of arbitrary age with no notice.
**Change:** at `sql_agent.py:686-690`, when the fallback query returns rows, set one bus flag
(e.g. `sql_result["window_expanded"] = True` with the oldest/newest timestamp actually returned),
and append one sentence in `_response_node` next to the existing turn-outcome note
(`_orchestrator.py:5475-5490`), which is already the place a caveat sentence goes. Optionally add
`right now`, `currently`, `at the moment`, `latest`, `live` to the keyword guard at `:644-663` —
that one-line list edit is independently worth doing and is the lowest-risk part.
**Files:** `orchestrator/agents/sql_agent.py`, `orchestrator/workflow/_orchestrator.py`
(response node, one insert).
**Blast radius:** only turns that currently hit the auto-expand. It **adds** a sentence; it never
withholds. No answer changes.
**Risk:** low. This is additive text on an already-degraded path.
**Verify:** ask a "right now" question against a sensor with no recent rows and read the answer;
`pytest -m unit -q -k sql`.

---

### A3 — Make the empty-result fast path actually fire · **LAND TODAY (lowest risk of the three)**

**Fixes:** up to **three redundant SPARQL executions, 30 s timeout each**, on every honest
"no data" answer — a demo-latency risk — and removes a substitution vector at the same time.
**The bug:** `self_correction_engine.py:395` short-circuits on the literal string
`"Empty result set"`, but the executor it is given emits `"Empty results"`
(`sparql_agent.py:516`) and `error` takes that value first (`self_correction_engine.py:349-351`).
The branch has never fired.
**Change:** one string. Either make `sparql_agent.py:516` emit `"Empty result set"`, or widen the
comparison at `:395`. I prefer widening the comparison — it does not change a value other code
may read.
**Files:** one line in `orchestrator/services/self_correction_engine.py`.
**Blast radius:** only turns where SPARQL executed successfully and returned zero rows.
**Risk: the lowest of the three, and the direction is provably safe.** `error == "Empty results"`
can only occur with `success=True` (`sparql_agent.py:513-519`), i.e. the query parsed and ran — so
`SyntaxFixStrategy` and `PrefixRepairStrategy` cannot be *repairing* anything; they can only
mutate a valid query into a different one. Today, if such a mutation happens to return rows, those
rows become the answer to a question they do not match. This change removes that. Control flow on
the break is already correct: `last_result` is set immediately above (`:384`) and the function
returns it (`:411-445`), so the caller's behaviour is unchanged — it still falls to semantic RAG,
just ~90 s sooner.
**Verify:** ask a question about a sensor class the building does not have; confirm the log shows
`⚡ Empty result set` once instead of three `🔄 Self-correction attempt` lines, and time it.
`pytest -m unit -q -k correction`.

---

### A4 — One bounded lane retry on TIMEOUT only · **DEFER TO AFTER THE DEMO**

**Fixes:** the missing "retry loop on failures" clause, in the one case where retrying is
honest: `Outcome.TIMEOUT`, which `turn_outcome.py:23-29` documents as usually latency.
**Change:** in `_safe_node` (`_orchestrator.py:967-1022`), when `_classify_failure(e)` is
`TIMEOUT` and the lane has not already been retried this turn, `await node_fn(state)` once more.
The accounting is **already built**: `_record_lane_outcome` sets `first_pass=False` on the second
entry automatically (`:590`), and `TurnOutcome.first_pass_ok` / `.retried` already publish it
(`turn_outcome.py:189-201`). Explicitly do **not** retry `FAILED` (reproducible) or
`BACKEND_UNAVAILABLE` (nothing to talk to).
**Files:** `orchestrator/workflow/_orchestrator.py` (one function).
**Blast radius:** **every lane in the system.** That is exactly why it should not land today.
**Risk:** the failure mode is latency, not wrongness — a retried 60 s lane can take 120 s, and
`CAVEAT-500` records a 121 s client timeout already being hit. A demo that hangs is worse than a
demo that says "that timed out."
**Verify:** the 60-case regression probe, before and after, both green. That is a 20-minute run
you do not have room for today.

---

### A5 — Give the modality repair the room, not just the floor · **DEFER**

**Fixes:** S9 — BUG-632's fix covers `floor N` and leaves `3rd floor`, `ground floor` and every
**room**-scoped question reverting to building-wide.
**Change:** extend the floor regex at `_orchestrator.py:2236` to ordinal and named floors, and —
the larger half — pass a room/zone constraint into `modality_repair.build_modality_query` when the
question names one, so a repair can widen the class but never the place. The BUG-632 note already
states that rule: *"A repair may widen the CLASS it looks for, never the PLACE it looks in."*
**Files:** `orchestrator/workflow/_orchestrator.py`, `orchestrator/services/modality_repair.py`.
**Blast radius:** every question that reaches the modality repair — which, per BUG-632, includes
the flagship *"what is the air quality on floor N?"* demo question that was fixed **yesterday**.
**Risk:** high for today. This is the single most recently-touched code path in the demo script.
Touching it on freeze day, after it was verified live yesterday, is how a green demo goes red.

---

### Also considered and ranked below the cut

- **Filter `memory_type == "failure"` out of `AgentMemory._search`** (`agent_memory.py:309-329`),
  and add a `score_threshold` to the Qdrant query at `:315-322`. Low risk, but the benefit is
  prompt hygiene rather than a wrong answer, and it touches classification input on freeze day.
- **Add a GraphDB circuit breaker.** There isn't one (`circuit_breaker.py:4` advertises it;
  only `llm` at `llm_manager.py:180` and `mysql` at `adapters/mysql_adapter.py:250` exist). Worth
  doing, not today.
- **Surface the correction engine's decline instead of falling to RAG** — the honest text already
  exists at `self_correction_engine.py:436-442` and is thrown away at `sparql_agent.py:554-565`.
  This is the *most correct* fix for S4 and the *worst* one to land today: it turns every
  empty-SPARQL question in the demo script into a decline. A1 gets most of the safety for a
  fraction of the behaviour change.

---

## 7. Things I deliberately am **not** recommending

- **Do not add a re-plan loop to the LangGraph topology.** That is the textbook answer to "plan
  the pipeline" and it is a large refactor of `_build_graph` (`workflow/_graph.py:41-245`) plus
  every conditional-edge map. The static DAG is not currently costing you wrong answers; the
  substitutions in §5 are.
- **Do not wire `GoalPlanner`.** It is unwired, `GOAL_PLANNER_ENABLED` defaults to `False`
  (`shared/config.py:568`), and it decomposes by literal substring trigger
  (`goal_planner.py:134-145`). Wiring an unexercised planner the day before a demo buys nothing.
- **Do not give the routing contract access to conversation history.** `_Ctx`
  (`routing_contract.py:310-321`) being text-only is *why* the 44-rule precedence order is
  testable and why `test_precedence_order_is_pinned` means anything. Making rules history-dependent
  makes the contract untestable. If prior context needs to influence routing, it should do so by
  improving the **rewrite** (which already feeds every stage), not by making rules stateful.
- **Do not turn on fuzzy response caching.** `response_cache.py:80` defaults it off and
  `salient_ids` (`:225`) only protects numeric discriminators.
- **Do not wire `turn_memory` / `prune_inherited` into `/chat` today** (§4.2b). It is the right
  fix and it is a four-endpoint change touching state loading, which is the last thing to move
  the day before a demo that runs on the *other* endpoint.
- **Do not remove any of the substituting fallbacks in §5 outright.** Several of them are the
  reason some questions answer at all. The correct treatment for every one of them is the
  `modality_repair` treatment: keep it, scope it, and **record what it swapped** on the bus
  (`_orchestrator.py:2266-2271`) so a caveat can be written from the record. That is post-demo
  work with a clear shape.

---

## 8. One thing I would say plainly

The owner's intention describes a system that plans and retries. What the code actually is, and
is *good* at, is a system that **routes deterministically and declines honestly**. Those are not
the same thing, and the second is the harder one to build — it is largely built, and it is worth
demoing as what it is rather than as a planner.

The gap between the two is not filled by adding a planner. It is filled by making sure that every
time the system cannot answer, the thing the user receives is the decline it already knows how to
write — instead of a different question's answer. Several of the sixteen substitutions in §5 exist
because a decline was composed and then thrown away (S4), or never reached a gate that would have
caught it (S4 again, via the verifier crash), or was made indistinguishable from real absence
(S7, S16). That is the work, and it is smaller than a planner.

---

## 9. Corrections owed to `CLAUDE.md` and to module docstrings

- Routing contract rule count: the file says **36+1+3**; the code holds **40+1+3** (counted
  2026-09-17 from `PARSE_STAGE_RULES`/`POST_STAGE_RULES`/`CONCEPT_STAGE_RULES`).
- `shared/config.py:949` states *"llm_manager retries each call up to MAX_RETRY_ATTEMPTS times"*.
  False — `llm_manager.py:53` reads the env var `LLM_MAX_RETRIES`; the setting is never read.
- `services/self_correction_policy.py:125` states the module is *"imported by sql_agent and
  analytics_agent"*. False — zero production importers.
- `services/circuit_breaker.py:4` advertises GraphDB and RAG breakers. Neither exists.
- `.claude/rules/agent-patterns.md:15` says `_graph.py` contains `_safe_node`. It does not —
  `_safe_node` is at `_orchestrator.py:960`.

---

## 10. New defects found by this audit (not yet in `FIX_TRACKER.csv`)

Filed here for the owner to decide; **I have not added tracker rows** (not my file).

| Proposed | Sev | Summary |
|---|---|---|
| BUG | **P1** | Verifier raises `AttributeError` on the semantic-RAG result shape (`verifier_agent.py:168` vs `sparql_agent.py:270`); swallowed at DEBUG (`_orchestrator.py:4777`); no verification record is written, so `publication_gate` publishes by design (`publication_gate.py:189-192`). The path most likely to be ungrounded is the path with no gate. |
| BUG | P2 | SQL auto-expand replaces the asked-for time window with "latest 200 rows, any date" and sets no flag (`sql_agent.py:643-690`). Guard keyword list omits `right now` / `currently` / `latest` / `live` (`:644-663`). |
| BUG | P2 | Unscoped fallback rows are cached under the **scoped** query's key for 1 h (`sparql_agent.py:3558`, `:3595`, `:3630`), so the substitution outlives the failure and recurs silently. |
| BUG | P2 | The self-correction engine's empty-result fast path has never fired: it tests `error == "Empty result set"` (`self_correction_engine.py:395`) while its executor emits `"Empty results"` (`sparql_agent.py:516`). Every empty graph result burns 3 extra SPARQL executions at 30 s each, and a mutated-but-valid query that happens to return rows becomes the answer. |
| BUG | P2 | `prune_inherited` and all of `turn_memory` are wired into `/v1/chat/completions` only (`main.py:3710-3975`). On `/chat`, `/chat/stream` and the `/stream` websocket, `analytics_result` / `forecast_result` survive a subject change unpruned (`_orchestrator.py:507`, `:728-729`) — the V12-11/A14 bug is still reachable there, and the regression probe runs on that endpoint. |
| BUG | P2 | The correction engine composes an honest decline on exhaustion (`self_correction_engine.py:436-442`) and `sparql_agent.py:554-565` discards it in favour of semantic-RAG prose. |
| CAVEAT | P3 | Two of four self-correction strategies are inert: `LLMRegenerationStrategy` is a no-op because the caller passes `"llm_call": None` (`sparql_agent.py:549`), and `TemplateSchemaFallbackStrategy` is applied at attempt 4 and then never executed because the loop ends (`self_correction_engine.py:331`, `:387`, `:402-409`). |
| CAVEAT | P3 | Dead retry surface: `settings.MAX_RETRY_ATTEMPTS` (`config.py:561`) never read; `ConversationState.retry_count` (`models.py:316`) never written; `SelfCorrectionPolicy` (`self_correction_policy.py:48`) has zero production importers; no GraphDB circuit breaker exists. |
| CAVEAT | P3 | `record_failure()` fires per *attempt* (`llm_manager.py:392`, `:395`), so one request burning 3 attempts contributes 3 of the 5 failures that open the LLM breaker for 30 s. |
| CAVEAT | P3 | `_instance_cache` is keyed by Brick class only on a process-lifetime agent instance (`sparql_agent.py:2993`, `:203`) — cross-building leakage in a multi-building deployment. |
| CAVEAT | P3 | `AgentMemory._search` returns stored failures with no `memory_type` filter and no score threshold (`agent_memory.py:309-329`); they render as `Answer: [FAILURE] …` in the classifier prompt. |
| CAVEAT | P3 | `_repair_sql` recovery does not touch `_record_lane_outcome`, so a turn that needed 2 SQL repairs still reports `first_pass_ok=True` — the exact conflation `turn_outcome.py:31-35` warns about. |
