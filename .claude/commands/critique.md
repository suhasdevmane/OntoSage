---
description: Deep adversarial critique of OntoSage code — routing, caching, security, test coverage
argument-hint: [file-or-component] e.g. workflow.py, dialogue_agent.py, "routing logic", "capability KB"
---

You are a hostile senior engineer doing a pre-merge review of $ARGUMENTS in the OntoSage codebase. Your job is to find every real problem before it reaches production. Do not summarise what the code does — find what is wrong with it.

## Phase 1 — Static Analysis

Run these and report every warning as a finding:

```bash
black --check --line-length 100 orchestrator/ shared/ tests/
isort --check --profile black orchestrator/ tests/
flake8 orchestrator/ shared/ scripts/ --max-line-length 110 --extend-ignore=E203,E501,W503 --per-file-ignores="__init__.py:F401"
bandit -r orchestrator/ shared/ -ll --exclude orchestrator/tests -f text
```

For each tool: list every violation with file:line and severity. If clean, say so explicitly — do not skip.

## Phase 2 — LangGraph Routing Integrity

This is the highest-risk area. A silent routing bug loses user queries with no error.

**2a. Node registration completeness**
Read `orchestrator/workflow.py`. For every `add_node("X", ...)` call, verify there is a matching `elif intent == "X": return "X"` branch (or equivalent) in `_route_from_dialogue()`. List every node that is registered but never reachable, and every intent branch that names an unregistered node.

**2b. `_data_intents` completeness**
Find the `_data_intents` frozenset in `_route_from_dialogue()`. Verify it contains ALL intents that should never be overridden by the `is_floor_plan_query()` heuristic:
- Required: `sensor_data`, `analytics`, `anomaly`, `comparison`, `compare`, `forecast`, `report`, `export`, `recommend`, `planner`, `spatial_query`, `maintenance`, `sparql`, `sql`, `discovery`, `alert`, `control`, `trend`, `compliance`, `visualization`
- List any missing entries — each is a potential routing hijack.

**2c. `_safe_node` wrapper audit**
Every `workflow.add_node()` call MUST use `self._safe_node(fn, "name")` — never a bare function reference. List every violation.

**2d. Edge completeness**
For every registered node, verify there is a `workflow.add_edge("X", ...)` or `workflow.add_conditional_edges("X", ...)` call. A node with no outgoing edge silently terminates the pipeline.

**2e. Intent label consistency**
The string returned by `_route_from_dialogue()` must exactly match the string passed to `add_node()`. Check for case mismatches, underscores vs hyphens, or plural vs singular differences.

## Phase 3 — Capability KB and Intent Override

**3a. `_CAPABILITY_KW` single-source-of-truth**
Confirm `_CAPABILITY_KW` is defined exactly once in `orchestrator/agents/dialogue_agent.py` as a module-level `frozenset`. If it is duplicated inline anywhere (in the cache-hit branch, the hot-path branch, or tests), that is a critical finding — duplicates go out of sync.

**3b. Cache-hit path uses module-level constant**
Read the `if cached_result:` branch in `detect_intent()`. Confirm it references `_CAPABILITY_KW` (not a local tuple or list). If it redefines keywords locally, the override will silently diverge from the hot-path.

**3c. Capability KB coverage gaps**
Read `input/bldg1/capability.yaml`. For each of these question categories, verify at least one KB entry exists with matching keywords:
- Fire safety / evacuation
- Power outage / backup power
- Access control / swipe card / after hours
- Parking / transport / cycling
- Printing / scanning / PaperCut
- Wellbeing / prayer room / nursing room / gender neutral
- GDPR / data privacy / sensor privacy
- Building management contact
- Visitor / guest policy
- Thermal comfort complaints (too hot / too cold)
- WiFi / eduroam / IT support
- Sustainability / BREEAM / recycling

List any category with no matching KB entry — users asking these questions will get a generic response.

**3d. Keyword-to-intent alignment**
Every keyword in `_CAPABILITY_KW` should map to a question answerable by the capability KB. Check for keywords so broad they would incorrectly classify genuine sensor/analytics queries as `capability` (e.g., single-word terms like "policy", "security", "temperature").

## Phase 4 — Redis Cache Safety

**4a. Intent cache bypass risk**
In `detect_intent()`, the cached result is returned after the capability override check. Confirm:
1. The override check runs BEFORE `return cached_result`
2. The override mutates a copy (`dict(cached_result)`) — not the original cached object
3. The mutated copy is NOT written back to Redis (which would poison the cache for future requests)

**4b. Response cache invalidation**
The response cache at `cache:response:{hash}` serves full pipeline responses. If a routing bug was fixed and the cache flushed, but the code now has a new routing path, stale cache entries could mask the fix. Verify there is a mechanism (TTL or flush endpoint) to clear response cache when routing logic changes.

**4c. Cache key collision risk**
Check that `cache:intent:{hash}` keys include enough context (building_id, session context) to prevent cross-building cache hits. A cache key based only on the query text would serve bldg1 responses to bldg2 users.

**4d. Session contamination**
Confirm that conversation history loaded from Redis uses session-scoped keys, not global keys. A shared session ID between test runs would load contaminated history.

## Phase 5 — Security

**5a. Secret leakage in logs**
Grep for patterns that could log secrets:
```bash
grep -rn "api_key\|password\|token\|secret\|auth" orchestrator/ --include="*.py" | grep -i "logger\|print\|log\."
```
Flag any line where a secret-like variable is passed to a logger.

**5b. RBAC on every data endpoint**
In `orchestrator/main.py`, every `@app.get` / `@app.post` / `@app.websocket` endpoint that returns building data MUST have `Depends(create_rbac_dependency(...))`. List any endpoint missing this dependency.

**5c. Pydantic validation on all request bodies**
No endpoint should use `await request.json()` directly. Every body must be validated through a Pydantic model. Find violations.

**5d. SPARQL injection**
In `sparql_agent.py`, confirm that user input is NEVER string-interpolated directly into a SPARQL query. The LLM generates SPARQL from the user's natural language — but verify no f-string inserts `state.user_query` or `state.intermediate_results["entities"]` directly into a SPARQL template.

**5e. Code executor sandboxing**
In `analytics_agent.py`, the LLM generates Python that runs in the code-executor sandbox. Verify:
1. The generated code is sent to port 8002, not `exec()`-ed in the orchestrator process
2. The executor response is validated before being returned to the user

## Phase 6 — Async / Performance

**6a. Blocking calls in async context**
Grep for synchronous blocking patterns inside `async def` functions:
```bash
grep -rn "time\.sleep\|open(\|\.read()\|\.write(" orchestrator/ --include="*.py"
```
Each is a potential event-loop stall under load.

**6b. Missing timeouts**
Any `await` on an external service (GraphDB, MySQL, Redis, RAG service, LLM API) must have a timeout. Flag `await` calls with no `timeout=` or `asyncio.wait_for(..., timeout=)` wrapper.

**6c. N+1 query patterns**
In nodes that process lists of sensors/rooms, check for loops that call an async service once per item instead of batching. These are catastrophic at 680+ sensors.

## Phase 7 — Test Coverage

**7a. Intent routing tests**
In `tests/test_workflow_wiring.py` (or equivalent), verify every intent in `_route_from_dialogue()` has a test asserting the correct node is reached. List any intent with no test.

**7b. Capability override tests**
Verify tests exist for:
- Cache-hit path: cached `general` intent with capability keyword → overridden to `capability`
- Hot-path: LLM returns `general`, capability keyword present → overridden to `capability`
- Negative: genuine sensor query (e.g., "temperature on floor 3") is NOT overridden to `capability`

**7c. `_data_intents` guard tests**
Verify a test exists for: "What is the temperature on floor 3" → routes to `sparql` (not `floor_plan`).

**7d. No mocks hiding real failures**
Check for tests that mock Redis, GraphDB, or the LLM and would pass even if the real service was broken. Flag unit tests that mock so heavily they test no real logic.

## Phase 8 — Final Verdict

After all phases, output:

```
CRITICAL (must fix before merge):
- [list]

IMPORTANT (fix before merge if touched):
- [list]

MINOR (can defer):
- [list]

CLEAN (explicitly verified):
- [list]

VERDICT: APPROVED / NEEDS WORK / BLOCKED
```

Be specific: file, line number, and the exact problem for every finding. "Consider improving X" is not a finding — name the bug or say it is clean.
