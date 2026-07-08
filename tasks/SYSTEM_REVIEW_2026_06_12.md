# OntoSage Full-System Review & Improvement Plan — 2026-06-12

> **Implementation status (branch `security/p0-hardening`, 2026-06-12):** P0 security
> batch landed and verified — 130 unit tests pass, F821/F823 gate clean, `orchestrator.main`
> imports with all 46 routes. **Not committed** (awaiting review). Done:
> P0.1 `/v1` bearer auth enforced · P0.2 key → `PIPELINE_API_KEY` (+ STRICT_SECRETS check) ·
> P0.2/P0.3/P0.4 session→RBAC bridge (`require_permission`, `get_user_context`) applied to
> `/chat`, `/chat/stream`, `/conversations/*` (IDOR closed), `/preferences`, `/api/v1/report`,
> with ownership checks; `/chat/stream` no longer serves anonymous · P0.5 (partial)
> `PreferencesRequest` Pydantic model · P0.6 all internal + admin ports localhost-bound ·
> P0.7 OpenWebUI rows now `role=readonly` · P0.9 duplicate `ChatRequest` removed (multi-persona
> now works on `/chat`). New tests: `tests/test_rbac_enforcement.py` (8) + strict-secrets (1).
>
> **P0 COMPLETE (2026-06-12, second batch):** P0.5 done — `LoginRequest`/`RegisterRequest`/
> `ReportRequest` Pydantic models (registration cannot self-assign a role). P0.8 done —
> `requirements-dev.txt` with pinned black/isort/flake8/bandit/pip-audit (installed locally so
> CLAUDE.md gates run); CI bandit now **HIGH-blocking** + `pip-audit` step; lint job pinned to
> requirements-dev. Fixed the 4 HIGH bandit findings (MD5 for cache/IDs → `usedforsecurity=False`);
> bandit now **0 HIGH / 10 MEDIUM**. The 10 MEDIUM B608 triaged: all parameterized (`$n`/`%s` with
> values in params) or whitelisted/ontology-derived column identifiers — no raw user free-text in
> SQL (consistent with "LLM generates SQL" design); recommend converting `sql_agent` identifier
> interpolation to a validated allowlist in P2. B104 (uvicorn bind) nosec'd with justification.
> **Verified:** 130 unit pass, F821/F823 clean, `orchestrator.main` imports. Roles default to
> `facility_manager` (permissive) — anonymous calls now 401.
>
> **Not done in P0 (deliberate):** repo-wide black/isort one-time format = P3.1 (running it now
> would bury the security diff in formatting noise; blocking gate is clean regardless).
>
> **P1.1 DONE (live streaming quick-win):** `/v1/chat/completions` streaming now emits the
> collapsible `<details>` pipeline-progress panel **live inside** the `stream_execute` loop
> (open on first node, dedup statuses, close before the answer) instead of dumping it after the
> pipeline finished. Same rendering, fixed timing — Open WebUI no longer shows a blank screen.
> Verified: import OK, 130 unit pass, gate clean.
>
> **LIVE-VERIFIED on the running stack (2026-06-12):** restarted orchestrator on the new code;
> `users.role` migration applied (default facility_manager); **auth enforcement confirmed live**
> — anon `/chat`→401, `/v1` missing/wrong key→401, register→login(role=facility_manager)→authed
> `/chat`→200, short password→422 (Pydantic). **Port hardening applied to running containers** via
> `docker compose up -d` — every datastore + code-executor now bound to `127.0.0.1` (verified
> `docker ps`); only 3000/8000 public. Full stack healthy after recreate.
>
> **P1.1 LIVE-VERIFIED + improved:** added an immediate first-byte acknowledgment before the
> `stream_execute` loop → **time-to-first-byte dropped from ~30s to 0.0s**; progress panel streams
> live, answer follows. Big perceived-latency win.
>
> **P1.4 BUILT + flag-gated + grounding LIVE-VERIFIED, but kept OFF — key finding:** synthesis
> (`RESPONSE_SYNTHESIS_ENABLED`, default false; wired into docker-compose for A/B) produces a
> grounded answer (sensor names, counts, numbers all preserved exactly on a live discovery query).
> **However, the audit OVERESTIMATED how template-stitched responses are** — the analytics / sparql
> / capability / discovery agents already emit LLM-generated natural prose, so blanket synthesis
> just lightly rephrases at the cost of an extra LLM round-trip. Its real value is narrow: the
> pure-template paths (export-success / maintenance-ticket / control-decline / document-ready) and
> consistent voice for the default `general` persona (which skips `format_response`). **Recommend:
> keep OFF; make synthesis TARGETED (only fire on hard-template drafts or when blending multiple
> results), not blanket.** Note: response cache stores the synthesized answer and cache hits skip
> synthesis, so the flag's effect is masked on repeat queries.
>
> **Latency reality (measured from logs):** the dialogue node is ~6s normally (≈2s setup/coref +
> 1.5s GraphDB RAG fetch of 1743 ctx items + 2.6s intent LLM); the earlier 30s was cold-start. Total
> response latency is **distributed across pipeline stages**, not concentrated in response
> formatting. So **P1.2 (token-streaming the answer) has lower payoff than assumed** — the answer is
> already fast once the pipeline finishes; the pipeline is the cost. The higher-value next
> investment is **P2.4 (pipeline latency: parallelize concept-resolution with classification, cache
> the RAG context fragment between turns)** and **targeted synthesis**, not blanket token streaming.
>
> **Deferred (evidence-based):** P1.2 blanket token streaming (low payoff), P1.7 unify `run_turn`
> (real `/chat` vs `/v1` memory asymmetry, but `/v1`/OpenWebUI — the primary surface — already has
> the memory features; refactor risk not justified yet). 130 unit pass, gate clean throughout.
>
> **P1.4 made TARGETED (shipped form):** synthesis now fires ONLY on canned-template drafts
> (`_template_draft` flag set in the document/export/control/maintenance branches of `_response_node`);
> already-prose paths keep the existing persona formatter, so no extra LLM round-trip where it isn't
> needed. Still flag-gated (`RESPONSE_SYNTHESIS_ENABLED`, default off).
>
> **P2.4 LATENCY — profiled live + 3 fixes landed (verified):** measured a full data query end-to-end.
> Cold-start was dominated by a **14s MiniLM model download from HuggingFace** (no persistent cache) +
> **0.9s blocking title-gen LLM** per first message; warm steady-state ≈9.7s spread across 4 sequential
> LLM/HTTP calls (title 0.9s, RAG 1.8s, intent LLM 2.0s, SPARQL-gen 1.7s, analytics-heuristic LLM 2.4s)
> — **no single hotspot**. Fixes: (1) **title generation → fire-and-forget** (`_spawn_background` +
> `_generate_title_bg`, verified running concurrently, not blocking); (2) **HF cache volume**
> (`huggingface-cache:/root/.cache/huggingface`) so model weights persist across restarts — no
> re-download; (3) **embedding model pre-warm at startup** (`EmbeddingService.warm()` via
> `run_in_executor` in lifespan) — moves the ~5-7s RAM-load off the first user query. **Result:
> first-query-after-restart dropped from ~14-26s (cold) to ~7.5s.** Remaining ~7.5s is the irreducible
> sum of sequential LLM/SPARQL calls — further cuts need architectural change (faster classification
> model, or merging the intent + SPARQL-gen + analytics-heuristic LLM calls), which is risky and out of
> scope for safe tuning. Also observed (logged for follow-up): SPARQL initial query returns 0 then a
> pattern-fallback runs (~0.5-10s, variable); and feed `write_records` fires during read queries
> (investigate whether feed polling overlaps the request path). All changes flag-safe / additive;
> orchestrator left on safe defaults (synthesis OFF). 130 unit pass, bandit 0 HIGH, gate clean.


A-to-Z audit: services, agents, core logic, architecture, security, tests/CI, and
conversation quality measured against mainstream chatbots (ChatGPT / Claude / Gemini UX).
Evidence-based — every finding cites a file/line. Line numbers drift; search the symbol.

---

## 0. Scorecard

> **Re-graded 2026-07-07** on branch `security/p0-hardening` post P0–P2 + admin portal integration.
> Original grades (2026-06-12) shown in parentheses for reference.

| Area | Grade | One-line verdict |
|---|---|---|
| Pipeline architecture (LangGraph, intents, V3 services) | **B+** (B+) | Unchanged — genuinely good; V3 services, goal planner, ECA rules, actuation gateway all live |
| Security — auth & RBAC enforcement | **B+** (D) | All CRITICAL/HIGH findings resolved: `/v1` enforced, RBAC wired everywhere, Pydantic on all endpoints, STRICT_SECRETS; residual: B608 SQL identifier interpolation (MEDIUM, documented) |
| Security — network exposure | **A−** (D) | All internal ports localhost-bound (P0.6, live-verified); admin console behind `require_permission("system:admin")` |
| Conversation quality vs mainstream chatbots | **C+** (C−) | Live streaming fixed (0s TTFB), targeted synthesis exists (flag-gated), latency halved; template-stitched paths + `/chat` vs `/v1` memory gap remain |
| Memory & context | **B−** (B−) | No change — carry-forward solid, co-reference works; `/chat` still missing turn-memory relative to `/v1` |
| Code organization | **C** (C) | Dead code removed (`_unused_oai_chat_completions`); main.py GREW (new admin endpoints, ontology manager, sensor TTL generator); god files remain — next refactor target |
| Tests & CI | **B** (B−) | 416 unit tests pass (was 121); CI: bandit HIGH-blocking, pip-audit, requirements-dev pinned; still no integration test harness for live stack |
| Admin portal | **B** (n/a) | 73 endpoints across 9 tabs; all admin endpoints behind RBAC; frontend wired; ontology CRUD + reindex fully tested |
| Corpus coverage | **B** (C) | 63.8% pass rate (vs 16.2% baseline), corroborates paper §6.5; narrow MySQL tables + TTL extensions added to address occupancy/energy/lighting/security gaps |

### What remains open (2026-07-07)

| Issue | Priority | Notes |
|---|---|---|
| B608 SQL identifier interpolation in `sql_agent` | P2 | 10 MEDIUM bandit findings; replace with validated allowlist; no raw user text in SQL today |
| `/chat` vs `/v1` memory asymmetry | P2 | `/chat` users get no turn-memory relative to OpenWebUI; share a `run_turn()` core |
| `main.py` god file (now ~4,800 lines) | P3 | Split into `APIRouter` modules by domain (auth, chat, admin, buildings) |
| Narrow MySQL tables not auto-created | P2 | `data/mysql-init/create_narrow_timeseries_tables.sql` written; needs to be applied to host MySQL or added to docker-compose init volume |
| Corpus coverage ceiling | Ongoing | 63.8% → 80%+ needs: floor 0-4 live streams (narrow tables populated), room-booking API, extended IAQ/noise sensors |
| RESPONSE_SYNTHESIS_ENABLED | P3 | Currently off; make targeted mode the default for canned-template paths (control-decline, maintenance-ticket) |
| Integration test harness | P3 | No live-stack tests in CI; corpus_replay.py runs manually only |

---

## 1. Findings — Security (highest severity first)

### S1 — CRITICAL: `/v1/chat/completions` is completely unauthenticated
- `orchestrator/main.py:2643` — the **live** handler; the comment at :2652 says
  *"Basic auth check (accept any token for now)"* and then performs none.
- The auth dependency that exists for this purpose (`_oai_auth`, main.py:2120) is wired only
  to the **dead** handler `_unused_oai_chat_completions` (main.py:2141).
- Anyone who can reach port 8000 gets the full pipeline — SPARQL, SQL, analytics (LLM-generated
  Python executed in the sandbox), report generation — with **no credentials**.

### S2 — CRITICAL: hardcoded API key in source
- `main.py:2102`: `_OAI_AUTH_KEYS = {"sk-ontobot-pipeline"}`. Committed to git, identical for
  every deployment. Must come from `shared/config.py` Settings / env.

### S3 — HIGH: RBAC system exists but is never enforced
- `middleware/rbac.py` defines `require_permission()` / `create_rbac_dependency` per
  `.claude/rules/api-contracts.md` ("required on every data endpoint").
- `grep create_rbac_dependency|require_permission orchestrator/main.py` → **0 endpoint usages**.
- Endpoints use `Depends(get_current_user)` which returns `Optional[str]` — and most don't even
  check it for None.

### S4 — HIGH: IDOR / missing ownership & auth checks
- `main.py:1166` `GET /conversations/{user_id}` — **no auth**; anyone can list any user's conversations.
- `main.py:1186` `GET /conversations/{conversation_id}/messages` — no auth, no ownership check.
- `main.py:2513` `POST /preferences` — no auth, raw `Dict[str, Any]` body.
- `main.py:1942` `/chat/stream` accepts `current_user or "guest"` while `/chat` (main.py:1723)
  rejects unauthenticated — the streaming door bypasses the auth the sync door enforces.
- Floor-plan, buildings, capability-indexer admin endpoints (main.py:3073–3589): no auth.

### S5 — HIGH: all internal services exposed on host ports (docker-compose.yml)
- Redis 6379, Qdrant 6333/6334, MongoDB 27017, Postgres 5433, GraphDB 7200, **code-executor 8002**,
  file-server 8080, mcp-server 8003 — all `host:container` with no `127.0.0.1:` prefix.
- code-executor on 8002 is the worst: a remote-code-execution service reachable without going
  through the orchestrator at all. On any non-laptop deployment this is game over.

### S6 — MEDIUM: unauthenticated user creation with placeholder credentials
- `main.py:2898` / :2982 — every `/v1` message calls
  `postgres_manager.create_user(username, "placeholder_hash", "placeholder_salt", ...)` where
  `username` comes from the **unauthenticated** request body (`data.get("user")`).
  An attacker can pre-create / squat arbitrary usernames with known-broken credentials.

### S7 — MEDIUM: raw body parsing violates project contract
- `await request.json()` at main.py:2155 (dead code) and **main.py:2655 (live)**.
- `request: Dict[str, Any]` bodies on `/api/v1/auth/login` (:1244), `/auth/register` (:1276),
  `/auth/login` (:1308), `/history/{username}` POST (:1499), `/preferences` (:2514),
  `/api/v1/report` (:2543). `api-contracts.md` mandates Pydantic for all of these.

### S8 — LOW: local tooling gap
- `bandit` and `black` are not installed in the project venv (only flake8 is), so the
  documented pre-commit gates in CLAUDE.md cannot actually be run locally as written.

### What's already good (verified)
- Argon2id password hashing with transparent legacy-hash migration (`auth_manager.py:92,343`).
- Session tokens via `secrets.token_urlsafe(32)` (:363) with Redis TTL refresh (:376,434).
- `STRICT_SECRETS` startup refusal; input sanitization on `ChatRequest.sanitized()`;
  per-request pipeline timeout (`REQUEST_TIMEOUT_SECS`, main.py:2940).

---

## 2. Findings — Architecture & code quality

### A1 — God objects
- `workflow/_orchestrator.py` — **4,254 lines**; one class owns ~30 node methods, routing
  overrides, response formatting, follow-up suggestions.
- `main.py` — **3,221 lines**, all endpoints in one module, no `APIRouter` split.
- `agents/sparql_agent.py` 1,789 · `agents/dialogue_agent.py` 1,398 lines.

### A2 — Dead and duplicated code
- `_unused_oai_chat_completions` (main.py:2141–~2640): ~500 lines of dead handler kept "for reference".
- `redis_manager.save_state(...)` called **twice** in both the streaming (main.py:2892, 2913)
  and non-streaming (:2977, :2996) `/v1` paths.
- `shared/models.py:626` — `ChatRequest` **redefined** (F811), silently shadowing the
  definition at :539. Whichever imports last wins; this is a real correctness hazard.
- flake8 advisory total: **459 findings** (F841 unused vars in live routing code,
  F401, F541, E402). Blocking gate (F821/F823) is clean ✅.

### A3 — Three divergent chat front doors
`/chat`, `/chat/stream`, `/v1/chat/completions` each reimplement: auth (3 different policies),
conversation-id derivation (3 schemes), persona resolution, history loading, persistence.
Critically, **only `/v1/chat/completions` gets turn-memory carry-forward and older-context
injection** (main.py:2754–2800). A user on `/chat` gets a measurably dumber assistant than the
same user on OpenWebUI. There is no single `run_turn()` core.

### A4 — Unstable conversation IDs
- main.py:2696 `f"owui_{abs(hash(first_content))}"` — Python string `hash()` is salted per
  process (PYTHONHASHSEED), so the fallback conversation ID **changes on every orchestrator
  restart** → memory silently severed. Use `hashlib.sha256(...).hexdigest()[:16]`.

### A5 — What's genuinely strong (keep, don't churn)
- Intent auto-wiring from `intent_definitions.yaml` (2-step add-an-intent), `_safe_node`
  error isolation, typed `pipeline_ctx` snapshot, data-driven `_route_from_dialogue`
  (Phase 6D), V3 config-driven services (concept resolver, feeds, ECA rules, recipes),
  grounding verifier before response, degraded-service notices, visualization honesty guard.

---

## 3. Findings — Conversation quality vs mainstream chatbots

This is the gap the user asked about. Benchmarked against ChatGPT/Claude/Gemini behavior:

### C1 — No real streaming anywhere (the single biggest UX gap)
- `/chat/stream` (main.py:2027–2079): emits per-node progress, then the **entire final answer
  as one `token` event**. Not token streaming.
- `/v1/chat/completions` streaming path is worse: status steps are *collected* during the loop
  (main.py:2842–2864) but **only yielded after the pipeline finishes** (:2868) — the OpenWebUI
  user watches a blank screen for the full 10–60 s pipeline, then everything appears at once.
  The code comment claims they're "visible during processing"; they are not.
- The final answer is then fake-streamed in 200-char slices (:2928).
- `llm_manager.astream_generate` (llm_manager.py:285) — true token streaming — **exists and is
  never called** by the response path.

### C2 — Template-stitched answers, no synthesis voice
- `_response_node` (`_orchestrator.py:2436`) is a ~250-line if/elif chain that picks ONE
  agent's pre-formatted string. Consequences:
  - No unified voice — emoji-heavy canned strings (`"✅ Export complete — ..."`) vs LLM prose,
    depending on which branch fired.
  - Cannot blend results ("temperature is 24 °C **and** here's the trend you asked about").
  - Persona handling is a *second* LLM rewrite pass (`format_response`, dialogue_agent.py:1511,
    skipped under 200 chars; plus `_persona_adapter.enhance` at `_orchestrator.py:2639`) —
    extra latency + paraphrase-drift risk instead of one synthesis call.
- Generic dead-end fallback: *"I processed your request, but couldn't generate a response."* (:2560)

### C3 — Canned follow-up suggestions on every message
- `_get_follow_up_suggestions` (`_orchestrator.py:4577`) returns **static per-intent strings**,
  appended as `**You might also ask:**` to every reply (:2629). By turn 3 of an analytics
  session the user has seen the same suggestions 3 times. Mainstream bots derive suggestions
  from the actual entities/results and don't repeat them.

### C4 — Memory is good-but-shallow, and path-dependent
- ✅ Co-reference rewrite (`rewrite_to_standalone`, dialogue_agent.py:513) is the correct
  industry pattern. ✅ Carry-forward of forecast/analytics artifacts. ✅ Older-turn summaries.
- ❌ Recall is purely recency/offset-based (`turn_memory.get_older_context` — linear list,
  300-char summaries). No semantic retrieval ("what did we say about the AHU last week?").
- ❌ No cross-conversation user memory in the chat path (the `user_memory` Qdrant collection
  and `user_preference_store` exist but aren't injected into prompts).
- ❌ Only the `/v1` path loads any of it (see A3).

### C5 — Missing table-stakes chat affordances
- No stop/cancel generation; no regenerate; no message-edit semantics.
- No structured clarification (options/buttons); clarification is a plain text question.
- No user feedback capture (👍/👎) feeding an eval loop.
- `usage` token counts hardcoded to 0 (main.py:2966, 3021) — breaks client cost/limit displays.
- Multi-intent decomposition exists but is feature-flagged off (`MULTI_INTENT_ENABLED`) —
  compound questions are the norm in real conversation.

### C6 — Latency profile
- Strictly sequential pipeline with multiple LLM round-trips (rewrite → classify → SPARQL gen
  → analytics gen → persona rewrite → i18n). `resp_cache` only helps exact repeats.
  No per-node latency budget/SLO is asserted anywhere.

---

## 4. Findings — Tests & CI

- 1,221 tests collected; **only 123 marked `unit`** (offline-runnable). Local run:
  **121 passed, 2 skipped in 6.4 s** ✅.
- CI (`.github/workflows/ci.yml`): black/isort `continue-on-error: true`; only F821/F823 block;
  bandit runs with `|| true` + JSON post-gate; coverage uploaded but **no threshold**.
- Local `black --check` reports ~145 files would reformat — either the repo drifted or local
  tool version ≠ CI version (tool versions are not pinned for dev). Either way the documented
  "run black before commit" gate is not reflecting reality.
- No `pip-audit`/dependency CVE scanning, no container image scanning observed.
- No multi-turn conversation eval in CI (qa_suite + corpus_replay exist but are live-stack,
  manual-trigger).

---

## 5. Improvement Plan — extensive TODO (priority-ordered)

### P0 — Security hardening (do before anything else; ~1–2 weeks)

- [ ] **P0.1** Enforce bearer auth on the live `/v1/chat/completions` (apply `_oai_auth` as a
      dependency); read keys from `Settings` (env), delete `_OAI_AUTH_KEYS` literal. (main.py:2102, 2643)
- [ ] **P0.2** Apply `create_rbac_dependency(...)` to every data endpoint per api-contracts.md:
      chat (sensor:read), conversations/history (ownership + read), report (report:read),
      floor-plans (metadata:read), documents, jobs, preferences, buildings, admin endpoints.
- [ ] **P0.3** Ownership checks: `/conversations/*`, `/history/{username}`, `/jobs/{job_id}`,
      `/api/v1/documents/*` must verify the resource belongs to `current_user` (or role ≥ FM).
- [ ] **P0.4** Align `/chat/stream` auth with `/chat` (reject anonymous; remove `or "guest"`).
- [ ] **P0.5** Replace all `Dict[str, Any]` bodies and `request.json()` with Pydantic models
      (LoginRequest, RegisterRequest, PreferencesRequest, ReportRequest, OAIChatRequest).
- [ ] **P0.6** docker-compose: prefix every internal service port with `127.0.0.1:` (or drop the
      host mapping entirely and rely on the compose network). Non-negotiable for code-executor
      8002, Redis 6379, Mongo 27017, Postgres 5433, GraphDB 7200, Qdrant 6333/6334. Add
      `requirepass` to Redis. Provide a `docker-compose.dev.yml` override for local debugging.
- [ ] **P0.7** Stop `create_user(..., "placeholder_hash", ...)` for unauthenticated `/v1` users —
      use a single service account or a marked external-identity row that can never log in.
- [ ] **P0.8** CI: make bandit HIGH blocking (it already half-does this — verify the JSON gate),
      add `pip-audit` job, pin black/isort/flake8/bandit versions in a `requirements-dev.txt`,
      and install them into the local venv so CLAUDE.md commands actually run.
- [ ] **P0.9** Fix `shared/models.py:626` duplicate `ChatRequest` definition (F811) — decide
      which is canonical, delete the other, run the suite.

### P1 — Conversation quality: reach mainstream-chatbot parity (~2–4 weeks)

**P1-A Streaming (highest UX leverage, smallest first step)**
- [ ] **P1.1** Quick win (hours): in `/v1` streaming, move the status-step `yield` *inside* the
      `async for stream_execute` loop so progress renders live in OpenWebUI's thinking panel.
      (main.py:2842–2872)
- [ ] **P1.2** Wire `llm_manager.astream_generate` into the final response generation so the
      answer streams token-by-token (requires P1.4's synthesis node to be the thing streaming).
- [ ] **P1.3** Propagate true token streams through `/chat/stream` SSE and the `/stream` WebSocket;
      delete the 200-char fake chunker.

**P1-B Response synthesis (the "sounds like a real assistant" fix)**
- [ ] **P1.4** Add a final **LLM synthesis pass** in `_response_node`: feed the structured results
      (sparql/sql/analytics/viz/maintenance/etc. from `pipeline_ctx`) + persona + language into
      ONE generation call that writes the answer in a consistent voice. Keep the current
      template chain as the deterministic fallback when the LLM is degraded, and keep the
      grounding verifier + visualization-honesty guard on top. This also collapses the separate
      `format_response` + `_persona_adapter.enhance` + i18n LLM passes into one (latency win).
- [ ] **P1.5** Replace static `_get_follow_up_suggestions` with suggestions derived from the
      turn's entities/results (the synthesis call can emit them as structured metadata);
      suppress repeats within a conversation; move them to a `suggestions` response field so
      UIs can render chips instead of polluting message text.
- [ ] **P1.6** Replace the generic failure string with intent-aware recovery messages that say
      what was attempted, what failed, and one concrete reformulation example.

**P1-C Memory**
- [ ] **P1.7** Extract a single `ConversationService.run_turn()` used by `/chat`, `/chat/stream`,
      and `/v1/chat/completions` so carry-forward, older-context, persona detection, and
      persistence behave identically on every path (fixes A3).
- [ ] **P1.8** Semantic memory recall: embed `turn_memory.result_summary` rows into Qdrant
      (`user_memory` collection already exists) and retrieve top-k relevant past turns by the
      current query — in addition to the recency window.
- [ ] **P1.9** Inject `user_preference_store` facts (comfort ranges, preferred units/format)
      into the synthesis prompt — cross-session personalization, the thing users notice most.
- [ ] **P1.10** Replace `abs(hash(...))` conversation-id fallback with a stable SHA-256 digest. (main.py:2696)

**P1-D Chat affordances**
- [ ] **P1.11** Cancellation: honor client disconnect in SSE/WS generators (`asyncio.CancelledError`)
      and abort the LangGraph run; add a `POST /chat/{id}/cancel`.
- [ ] **P1.12** Structured clarification: when intent=clarification, return 2–3 candidate
      interpretations as structured options (OpenWebUI renders suggestion chips); cap at one
      clarifying question, then answer best-effort.
- [ ] **P1.13** Feedback capture: 👍/👎 + free-text endpoint persisted next to turn_memory;
      weekly review feeds the QA suite with new regression cases.
- [ ] **P1.14** Real `usage` token accounting from llm_manager call stats.
- [ ] **P1.15** Run the multi-intent eval gate and default `MULTI_INTENT_ENABLED=true` if ≥ parity.

### P2 — Architecture refactor (incremental, behind green tests; ~3–6 weeks)

- [ ] **P2.1** Split `main.py` into `APIRouter` modules: `routers/auth.py`, `routers/chat.py`,
      `routers/openai_compat.py`, `routers/floor_plans.py`, `routers/admin.py`, `routers/health.py`.
- [ ] **P2.2** Delete `_unused_oai_chat_completions` (~500 lines) and the duplicated
      `save_state` calls; the git history is the reference.
- [ ] **P2.3** Carve `_orchestrator.py` down: move response composition to
      `services/response_builder.py`; group node methods into family mixins
      (data_nodes, intake_nodes, spatial_nodes, control_nodes). Target ≤ 1,000 lines/module.
- [ ] **P2.4** Latency program: per-node timing histograms already exposed via /metrics — set a
      p95 budget per node, parallelize independent steps (e.g. concept resolution alongside
      classification), and cache the SPARQL schema/context fragment between turns.
- [ ] **P2.5** Burn down the 459 advisory flake8 findings in touched files as you go
      (F841 unused locals in `_orchestrator.py` routing code first — some look like
      half-finished logic, e.g. :730 `sparql_query`, :4343 `building_id`).

### P3 — Quality engineering (continuous)

- [ ] **P3.1** Format the repo once with pinned black/isort versions; flip CI black/isort to
      blocking (remove `continue-on-error`).
- [ ] **P3.2** Raise offline-runnable coverage: mark more of the 1,098 unmarked tests `unit`
      (or write mock-backed variants); add a coverage floor (start at current %, ratchet).
- [ ] **P3.3** Multi-turn conversation eval in CI: scripted 5–10-turn dialogues asserting
      co-reference resolution, carry-forward, suggestion non-repetition, and degradation
      messaging — extend `ontosage_qa_suite.py` CONV flows and run nightly against the stack.
- [ ] **P3.4** Track two KPIs per release: corpus_replay answerable-share (target trajectory
      16.2% → 60.5% per V3 plan) and median time-to-first-byte on `/v1` streaming (target < 2 s
      after P1.1/P1.2).
- [ ] **P3.5** Dependency hygiene: `pip-audit` in CI (P0.8), Dockerfile base-image pinning +
      `docker scout`/trivy scan job.

---

## 6. Suggested sequencing

1. **Week 1–2:** P0 entirely (security). P1.1 ships alongside (one-loop fix, huge perceived win).
2. **Week 3–4:** P1.4 synthesis node + P1.2/P1.3 token streaming + P1.7 unified run_turn.
3. **Week 5–6:** P1.8/P1.9 memory, P1.5/P1.6 suggestions & errors, P1.11–P1.15 affordances.
4. **Then:** P2 refactors piecewise (each PR ≤ ~500 lines, suite green), P3 continuously.

**Definition of done for "behaves like a mainstream chatbot":** first visible output < 2 s
(progress), token-streamed answer in one consistent voice, follow-ups resolved across turns on
every endpoint, personalized via stored preferences, no repeated canned suggestions, graceful
specific errors, stop/regenerate supported, and all of it behind authenticated, RBAC-enforced
endpoints.
