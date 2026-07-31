> **HISTORICAL DOCUMENT (2026-07-30):** the P0 blockers below are all FIXED and live on `main`
> (download-export auth, 12-char passwords, occupant default role, RBAC enforcement).
> The live source of truth for open issues is [`tasks/FIX_TRACKER.csv`](./FIX_TRACKER.csv).

# Production Readiness Audit — TODO Plan

**Date:** 2026-07-09 · **Branch:** `security/p0-hardening` · **Auditor:** senior review pass
**Scope of THIS pass:** deep-read of the auth/RBAC/session/admin-endpoint/SQL-adapter/secrets
surface (~10 files). **NOT yet audited** (see P3-12): analytics/code-executor sandbox, SPARQL
generation, forecasting, DWG/PDF pipeline, frontend, the ~120 other `orchestrator/services/*`.

Severities: **CRITICAL** (fix before prod traffic) · **MAJOR** · **MINOR**.
Each item is independently shippable. Nothing here has been changed — awaiting review/approval.

---

## P0 — Blockers (correctness / auth)

### 1. New users get `readonly`, which cannot call `/chat` — breaks the documented quickstart  — **CRITICAL (correctness/product)**
- **Where:** [auth_manager.py:166](orchestrator/auth_manager.py#L166) (`role: str = "readonly"` default) ← [main.py:1485](orchestrator/main.py#L1485) calls `register_user(username, password, email)` with no role.
- **Symptom:** `/auth/register` → login → `POST /chat` returns **403** because `/chat` needs `sensor:read` ([main.py:1884](orchestrator/main.py#L1884)) and `readonly` only has `metadata:read` + `system:health` ([rbac.py:142](orchestrator/middleware/rbac.py#L142)). The README §Quickstart and ONTOSAGE both show exactly this flow succeeding.
- **Extra contradiction:** the endpoint docstring claims new accounts get `facility_manager` ([main.py:1481](orchestrator/main.py#L1481)) — neither `readonly` nor the docstring is what actually happens end-to-end.
- **Decision needed (yours):** what role should self-registration grant? `occupant` (has `sensor:read`, can chat, minimal else) is the likely intended default. Options: (a) change default to `occupant`; (b) keep `readonly` and make self-registration require admin promotion — then fix README + docstring to say so.
- **Fix:** set the intended default in one place, align docstring + README quickstart, add a test asserting a freshly-registered user can/can't reach `/chat` per the decision.

### 2. `/api/files/{filename}` downloads exports without checking authentication — **CRITICAL (auth gap)**
- **Where:** [main.py:3373-3397](orchestrator/main.py#L3373-L3397). It declares `current_user: Optional[str] = Depends(get_current_user)` but **never checks it** — `get_current_user` returns `None` for anonymous callers and the handler proceeds.
- **Impact:** any unauthenticated caller can fetch any file in `EXPORTS_DIR` given the name (CSV/JSON exports contain building sensor data). Path traversal *is* handled ([L3384-3390](orchestrator/main.py#L3384-L3390)); auth is not. Directly contradicts "all data endpoints return 401 on missing/invalid token."
- **Fix:** replace with `user: UserContext = Depends(require_permission("export:read"))`, or at minimum `if not current_user: raise HTTPException(401)`. Add an unauth-download test.

### 3. No auth-aware login throttling; global limiter is proxy-blind and non-distributed — **CRITICAL (security)**
- **Where:** login has no per-account lockout ([main.py:1497](orchestrator/main.py#L1497)); the only defense is the global `RateLimitMiddleware` ([main.py:1060-1097](orchestrator/main.py#L1060-L1097)).
- **Problems:** (a) keyed on `request.client.host` — behind a reverse proxy/LB every client shares the proxy IP, so it either throttles all users collectively or is useless; it never reads a trusted `X-Forwarded-For`. (b) In-memory → breaks with >1 replica. (c) 60 req/min/IP still permits ~86k password guesses/day/IP; not auth-specific. (d) Minor: `_counts` grows per distinct IP with cleanup only on that IP's next request.
- **Fix:** add per-username failed-attempt lockout (Redis counter + exponential backoff) in `login_user`; make the IP limiter honor `X-Forwarded-For` only from a configured trusted-proxy CIDR; back the counter with Redis so it works across replicas.

---

## P1 — Major

### 4. `delete_user` does a blocking `KEYS conversation:*` + per-key GET (O(N) N+1) — **MAJOR (perf/resilience)**
- **Where:** [auth_manager.py:654-663](orchestrator/auth_manager.py#L654-L663). `redis.keys("conversation:*")` is O(total-keys) and blocks the Redis single thread; then one `GET` per key.
- **Impact:** on a production Redis with many conversations, deleting one user stalls the whole store (all requests behind it). `KEYS` is explicitly discouraged in prod.
- **Fix:** maintain a `user_conversations:<username>` set (write on save) and delete by membership; or iterate with `SCAN` + a pipeline. Never `KEYS` on a hot store.

### 5. Password minimum length is 6 — **MAJOR (security)**
- **Where:** [auth_manager.py:187](orchestrator/auth_manager.py#L187) (`len(password) < 6`).
- **Fix:** raise to ≥12, enforce at the Pydantic `RegisterRequest` boundary too; optionally screen against a breached-password list. Argon2id params ([L95](orchestrator/auth_manager.py#L95)) are fine.

### 6. Delete the dead, defective RBAC stack in `middleware/rbac.py` — **MAJOR (security hygiene / maintainability)**
- **Where:** [rbac.py](orchestrator/middleware/rbac.py) — `SimpleJWT`, `TokenManager`, `UserStore`, `RBACMiddleware`, `create_rbac_dependency`, `get_auth_manager`, `get_user_store`. Only `UserContext` + `ROLE_PERMISSIONS` are live.
- **Why it matters even though unwired:** `create_rbac_dependency` reads `authorization: str = ""` as a **query param** (not header) and `raise Exception` → HTTP 500 instead of 401/403 ([L358-368](orchestrator/middleware/rbac.py#L358-L368)); `UserStore` uses unsalted SHA-256 ([L310](orchestrator/middleware/rbac.py#L310)); `TokenManager` default secret `"change-me-in-production"` ([L243](orchestrator/middleware/rbac.py#L243)). A contributor copying the still-published example (see #7) reintroduces all three defects.
- **Fix:** move `UserContext` + `ROLE_PERMISSIONS` into a small `rbac_model.py`, delete the rest, update imports. If deletion is too aggressive for now, at least gate it behind an explicit "unused" module and remove it from all docs.

### 7. Doc↔code contradictions that will mislead operators/contributors — **MAJOR (correctness of docs)**
- `create_rbac_dependency(token_manager, "sensor:read")` is shown as THE endpoint-auth pattern in [.claude/rules/api-contracts.md](.claude/rules/api-contracts.md) and ONTOSAGE §6.6 — but the live pattern is `require_permission(...)`. The rules file even contradicts its own warning banner.
- Register default role: docstring says `facility_manager`, code gives `readonly` (see #1).
- `STRICT_SECRETS` default: docs (README §Required env flags, ONTOSAGE §8.1) say **false**; code defaults to **True** ([config.py:296](shared/config.py#L296)). Code is safer — fix the docs, not the code.
- **Fix:** one docs sweep aligning api-contracts.md, README, ONTOSAGE §6.6/§8.1 to the shipped code.

---

## P2 — Structural / maintainability

### 8. SQL built by f-string interpolation (guarded, but fragile) — **MAJOR-leaning MEDIUM**
- **Where:** [mysql_narrow_adapter.py:112-137](orchestrator/services/adapters/mysql_narrow_adapter.py#L112-L137) interpolates UUIDs/dates/limit directly. It **is** injection-safe *today* because `_UUID_RE`/`_TABLE_RE`/`_sanitize_dt` allow-list out quotes/semicolons/whitespace — but this is one regex edit away from an injection, and the wide adapter path needs the same verification.
- **Fix:** switch to parameterized placeholders (`WHERE uuid IN (%s, %s, ...)` with a params tuple). Keep the regex as defense-in-depth. Verify [mysql_adapter.py](orchestrator/services/adapters/mysql_adapter.py) and every other adapter in `services/adapters/` for the same pattern.
- **Related (MINOR):** `get_columns` does `SELECT DISTINCT uuid` (full-table) — cached, so fine for now; revisit if a narrow table grows large.

### 9. Monolith files raise merge/review risk — **MAJOR (maintainability)**
- `main.py` = **4960 lines / 70+ endpoints**; `workflow/_orchestrator.py` = **3012 lines**.
- **Fix (incremental, behavior-preserving):** split `main.py` into `APIRouter` modules by domain (auth, admin-ontology, admin-databases, chat, floor-plan, datasources) mounted on the app — no route changes, pure relocation. Do it router-by-router so the test suite guards each move.

### 10. `list(data.keys())[0]` in auth dict helpers — **MINOR (robustness)**
- **Where:** [auth_manager.py:319](orchestrator/auth_manager.py#L319) and [L551](orchestrator/auth_manager.py#L551). `IndexError` if the store returns an empty-but-truthy dict. Guarded upstream today; harden to `next(iter(data), None)`-style checks.

---

## P3 — Testing & audit-coverage gaps

### 11. Add a security-behavior test matrix — **MAJOR (readiness)**
The 416 tests are offline/unit and mostly exercise routing/persona/intent logic. Missing:
- 401 (no token) / 403 (wrong role) matrix across the data + admin endpoints.
- `download_export` unauthenticated → must 401 (locks in fix #2).
- `_oai_auth` rejects the shipped default key and empty `PIPELINE_API_KEY` ([main.py:2279-2289](orchestrator/main.py#L2279-L2289)).
- `STRICT_SECRETS=true` + a default password → boot raises ([config.py:520-544](shared/config.py#L520-L544)).
- login lockout after N failures (locks in fix #3).

### 12. Extend the audit to the unreviewed surface — **MAJOR (unknown risk)**
This pass covered auth/RBAC/adapters only. Schedule focused passes on:
- **`analytics_agent` → code-executor (8002)** — LLM-generated Python execution is the highest-value RCE/sandbox-escape surface in the system; audit isolation, resource limits, network egress.
- **`sparql_agent.py`** (2256 lines) — LLM→SPARQL generation: injection via entity names, unbounded queries/DoS, RAG fallback trust boundary.
- **DWG/PDF pipeline** (`dwg_pipeline.py`, `floor_plan_pipeline.py`) — untrusted file parsing (libredwg/weasyprint), resource exhaustion.
- **`frontend/src/pages/AdminPortal.js`** — XSS on rendered SPARQL/TTL results, token handling.
- **Docker/compose** — secret injection, `restart` endpoint ([main.py:4402](orchestrator/main.py#L4402)) blast radius, MySQL-on-host assumption.
- Remaining `services/*` (feeds, rules_engine, notification, actuation) for the same interpolation/blocking-call/swallowed-exception patterns found here.

---

## Suggested execution order
1. **#2** (delete one line of trust, add a dependency) and **#1** (one-line default + doc) — smallest, highest-severity.
2. **#3** login lockout, **#4** delete_user SCAN — the two prod-stability/security items.
3. **#7** doc sweep + **#6** dead-code removal — cheap, de-risks contributors.
4. **#11** test matrix (locks in 1–3), then **#5**, **#8**.
5. **#9** router split + **#12** extended audit — larger, schedule as their own workstreams.
