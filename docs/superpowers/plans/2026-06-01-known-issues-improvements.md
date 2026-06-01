# Known-Issues Improvement Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Resolve all five known remaining issues identified in `review docs/system-review-2026-06-01.md` without breaking any existing passing tests.

**Architecture:** Each issue is a targeted, isolated fix. No cross-cutting refactors. Order: quick wins first (T1–T3, each under 30 min), then structural fixes (T4 multi-intent aggregation, T5 async job queue). Every task is test-driven: write the failing test first, then the fix.

**Tech Stack:** Python 3.10, FastAPI, LangGraph, Redis (`aioredis`), Pydantic v2, pytest-asyncio, `requests` (live tests)

---

## File Map

| File | Change |
|------|--------|
| `orchestrator/agents/dialogue_agent.py` | T1: add `_FORECAST_KWS` post-LLM override; T2: add `_MAINTENANCE_SCHEDULE_KWS` override |
| `orchestrator/services/semantic_router.py` | T2: extend `_DATA_BYPASS_PHRASES` with maintenance-schedule phrases |
| `shared/config.py` | T3: add `STRICT_SECRETS` flag + Pydantic validator |
| `.env.example` | T3: document `STRICT_SECRETS=true` for production |
| `orchestrator/agents/planner_agent.py` | T4: fix `_execute_multi_intent` to include sensor_data results in section_results |
| `orchestrator/main.py` | T5: add `POST /jobs` background execution + `GET /jobs/{job_id}` polling |
| `tests/test_forecast_routing.py` | T1: new test file |
| `tests/test_maintenance_routing.py` | T2: new test file |
| `tests/test_strict_secrets.py` | T3: new test file |
| `tests/test_multi_intent_aggregation.py` | T4: new test file |
| `tests/test_async_jobs.py` | T5: new test file |

---

## Task 1 — Forecast/Predict Intent Pre-classifier

**Problem:** "Predict temperature for tomorrow afternoon" → `general_knowledge`. The LLM does not reliably map predict/forecast queries to the `trend` intent even after YAML update.

**Fix:** Add a post-LLM keyword override in `dialogue_agent.py` at the same location as the existing `_FLOOR_PLAN_KWS` override (line ~930). If query contains a forecast keyword **and** a sensor/metric keyword, force `trend`.

**Files:**
- Modify: `orchestrator/agents/dialogue_agent.py` (after line 951, before the G1 taxonomy block at line 953)
- Create: `tests/test_forecast_routing.py`

---

- [ ] **Step 1.1 — Write failing test**

```python
# tests/test_forecast_routing.py
import pytest

FORECAST_QUERIES = [
    "Predict temperature for tomorrow afternoon",
    "Forecast energy usage for next week",
    "What will the CO2 level be tomorrow?",
    "Expected temperature next Monday",
    "Is temperature projected to rise next week?",
    "What will humidity be like tomorrow morning?",
]

NON_FORECAST_QUERIES = [
    "Show me floor 3 layout",
    "What are the fire evacuation procedures?",
    "Hello, what can you do?",
]


def _is_forecast_query(query: str) -> bool:
    """Mirror of the bypass logic we will add to dialogue_agent.py."""
    from orchestrator.agents.dialogue_agent import _FORECAST_KWS, _SENSOR_METRIC_KWS
    q = query.lower()
    return any(kw in q for kw in _FORECAST_KWS) and any(kw in q for kw in _SENSOR_METRIC_KWS)


@pytest.mark.unit
def test_forecast_queries_detected():
    for q in FORECAST_QUERIES:
        assert _is_forecast_query(q), f"Expected forecast detection for: {q!r}"


@pytest.mark.unit
def test_non_forecast_queries_not_detected():
    for q in NON_FORECAST_QUERIES:
        assert not _is_forecast_query(q), f"False positive forecast for: {q!r}"
```

- [ ] **Step 1.2 — Run test to verify it fails**

```bash
cd c:/Users/suhas/Documents/GitHub/OntoSage
python -m pytest tests/test_forecast_routing.py -v
```

Expected: `ImportError: cannot import name '_FORECAST_KWS'`

- [ ] **Step 1.3 — Add constants and override to dialogue_agent.py**

Open `orchestrator/agents/dialogue_agent.py`. After the `_FLOOR_PLAN_KWS` block (after line 951, before the G1 taxonomy comment at line 953), add:

```python
                # Forecast / prediction queries must route to trend, not general.
                # The LLM sometimes classifies "predict X tomorrow" as general
                # because it treats future-state queries as outside building-data.
                _FORECAST_KWS = (
                    "predict", "forecast", "projected", "projection",
                    "what will", "what would", "expected to be",
                    "likely to be", "tomorrow", "next week", "next month",
                    "next hour", "in the next",
                )
                _SENSOR_METRIC_KWS = (
                    "temperature", "temp", "co2", "humidity", "energy",
                    "consumption", "power", "air quality", "occupancy",
                    "noise", "pressure", "sensor", "reading",
                )
                _has_forecast_kw = any(kw in _q_lower for kw in _FORECAST_KWS)
                _has_metric_kw = any(kw in _q_lower for kw in _SENSOR_METRIC_KWS)
                if (
                    _has_forecast_kw
                    and _has_metric_kw
                    and normalized.get("intent") not in ("trend", "analytics", "sensor_data")
                ):
                    logger.info(
                        f"[intent-override] Forcing 'trend' (was '{normalized.get('intent')}') "
                        "— forecast/predict keyword with sensor metric detected"
                    )
                    normalized["intent"] = "trend"
                    normalized["analytics"] = True
                    normalized["general"] = False
```

Also add module-level exports so tests can import them. At the **top of the file** (after existing module-level constants, search for `_FLOOR_PLAN_KWS` in module scope or just add near line 160):

```python
# Exported for testing
_FORECAST_KWS = (
    "predict", "forecast", "projected", "projection",
    "what will", "what would", "expected to be",
    "likely to be", "tomorrow", "next week", "next month",
    "next hour", "in the next",
)
_SENSOR_METRIC_KWS = (
    "temperature", "temp", "co2", "humidity", "energy",
    "consumption", "power", "air quality", "occupancy",
    "noise", "pressure", "sensor", "reading",
)
```

Inside the `classify_intent` method, replace the inline tuple literals with references to these module-level constants:
```python
                _has_forecast_kw = any(kw in _q_lower for kw in _FORECAST_KWS)
                _has_metric_kw = any(kw in _q_lower for kw in _SENSOR_METRIC_KWS)
```

- [ ] **Step 1.4 — Run test to verify it passes**

```bash
python -m pytest tests/test_forecast_routing.py -v
```

Expected: `2 passed`

- [ ] **Step 1.5 — Rebuild orchestrator and live-smoke-test**

```bash
docker-compose build orchestrator && docker-compose up -d orchestrator
# wait ~20s for startup
curl -s -X POST http://localhost:8000/chat \
  -H "Content-Type: application/json" \
  -H "Authorization: Bearer <token>" \
  -d '{"message":"Predict temperature for tomorrow afternoon","session_id":"t1-smoke","building_id":"bldg1"}' \
  | python -m json.tool | grep '"intent"'
```

Expected: `"intent": "trend"`

- [ ] **Step 1.6 — Commit**

```bash
git add orchestrator/agents/dialogue_agent.py tests/test_forecast_routing.py
git commit -m "fix(routing): add forecast/predict keyword pre-classifier → trend intent"
```

---

## Task 2 — Maintenance Schedule Routing Fix

**Problem:** "What maintenance work is scheduled this week?" → `metadata`. The capability KB intercepts it (HVAC entries score 0.608), and even when it escapes the KB, the LLM maps it to `metadata`.

**Fix (two parts):**
1. Add maintenance-schedule phrases to `_DATA_BYPASS_PHRASES` in `semantic_router.py` (blocks capability KB interception).
2. Add `_MAINTENANCE_SCHEDULE_KWS` post-LLM override in `dialogue_agent.py` (forces `maintenance` when LLM returns `metadata` for schedule-type queries).

**Files:**
- Modify: `orchestrator/services/semantic_router.py`
- Modify: `orchestrator/agents/dialogue_agent.py`
- Create: `tests/test_maintenance_routing.py`

---

- [ ] **Step 2.1 — Write failing test**

```python
# tests/test_maintenance_routing.py
import pytest

MAINTENANCE_SCHEDULE_QUERIES = [
    "What maintenance work is scheduled this week?",
    "What maintenance is planned for next month?",
    "Show me all open maintenance tickets",
    "List outstanding maintenance tasks",
    "What is scheduled for building maintenance?",
    "Any planned maintenance on floor 3?",
]

NON_MAINTENANCE_QUERIES = [
    "the light in room 3.01 is broken",
    "What sensors are installed?",
    "Show me floor 2 layout",
]


def _router_would_bypass(query: str) -> bool:
    """Verify the semantic router skips KB for these queries."""
    from orchestrator.services.semantic_router import SemanticRouter
    return SemanticRouter.is_data_query(query)


def _dialogue_would_override(current_intent: str, query: str) -> bool:
    """Verify dialogue agent would force maintenance for schedule queries."""
    from orchestrator.agents.dialogue_agent import _MAINTENANCE_SCHEDULE_KWS
    q = query.lower()
    return any(kw in q for kw in _MAINTENANCE_SCHEDULE_KWS)


@pytest.mark.unit
def test_maintenance_schedule_bypasses_kb():
    for q in MAINTENANCE_SCHEDULE_QUERIES:
        assert _router_would_bypass(q), f"KB not bypassed for: {q!r}"


@pytest.mark.unit
def test_non_maintenance_not_bypassed():
    # These should NOT be in data-bypass (they go through normal KB / LLM)
    assert not _router_would_bypass("the light in room 3.01 is broken")


@pytest.mark.unit
def test_maintenance_schedule_kws_exported():
    from orchestrator.agents.dialogue_agent import _MAINTENANCE_SCHEDULE_KWS
    assert len(_MAINTENANCE_SCHEDULE_KWS) >= 4
```

- [ ] **Step 2.2 — Run test to verify it fails**

```bash
python -m pytest tests/test_maintenance_routing.py -v
```

Expected: `FAILED test_maintenance_schedule_bypasses_kb` + `ImportError: _MAINTENANCE_SCHEDULE_KWS`

- [ ] **Step 2.3 — Extend `_DATA_BYPASS_PHRASES` in semantic_router.py**

In `orchestrator/services/semantic_router.py`, inside `_DATA_BYPASS_PHRASES`, after the existing "alert/anomaly pipeline" block add:

```python
    # Maintenance schedule / ticket queries — these go to maintenance intent, not KB
    "maintenance schedule", "scheduled maintenance", "planned maintenance",
    "maintenance this week", "maintenance this month", "maintenance next",
    "open maintenance tickets", "outstanding maintenance", "maintenance tasks",
    "maintenance work scheduled", "what maintenance",
```

- [ ] **Step 2.4 — Add `_MAINTENANCE_SCHEDULE_KWS` constant and override in dialogue_agent.py**

At module level in `orchestrator/agents/dialogue_agent.py` (near the `_FORECAST_KWS` constants added in T1):

```python
_MAINTENANCE_SCHEDULE_KWS = (
    "maintenance schedule", "scheduled maintenance", "planned maintenance",
    "maintenance this week", "maintenance this month", "maintenance next",
    "open maintenance tickets", "outstanding maintenance", "maintenance tasks",
    "maintenance work scheduled", "what maintenance is",
    "list maintenance", "show maintenance",
)
```

Inside `classify_intent`, after the forecast override block (T1), add:

```python
                # Maintenance schedule queries must route to maintenance, not metadata.
                # "What maintenance is scheduled" has structural similarity to
                # metadata list queries, so the LLM often picks metadata.
                _has_maintenance_schedule = any(
                    kw in _q_lower for kw in _MAINTENANCE_SCHEDULE_KWS
                )
                if (
                    _has_maintenance_schedule
                    and normalized.get("intent") not in ("maintenance",)
                ):
                    logger.info(
                        f"[intent-override] Forcing 'maintenance' (was '{normalized.get('intent')}') "
                        "— maintenance schedule keyword detected"
                    )
                    normalized["intent"] = "maintenance"
                    normalized["analytics"] = False
                    normalized["general"] = False
```

- [ ] **Step 2.5 — Run tests to verify they pass**

```bash
python -m pytest tests/test_maintenance_routing.py -v
```

Expected: `3 passed`

- [ ] **Step 2.6 — Rebuild and live-smoke-test**

```bash
docker-compose build orchestrator && docker-compose up -d orchestrator
# wait ~20s
curl -s -X POST http://localhost:8000/chat \
  -H "Content-Type: application/json" \
  -H "Authorization: Bearer <token>" \
  -d '{"message":"What maintenance work is scheduled this week?","session_id":"t2-smoke","building_id":"bldg1"}' \
  | python -m json.tool | grep '"intent"'
```

Expected: `"intent": "maintenance"`

- [ ] **Step 2.7 — Commit**

```bash
git add orchestrator/services/semantic_router.py orchestrator/agents/dialogue_agent.py tests/test_maintenance_routing.py
git commit -m "fix(routing): maintenance-schedule queries bypass KB and route to maintenance intent"
```

---

## Task 3 — Strict Secrets Validation

**Problem:** `shared/config.py` has hardcoded default passwords for GraphDB (`Admin@GraphDB2024`), Postgres (`ontobot_secret`), and MySQL (`mysql`). A new deployment that forgets to set these env vars silently uses the insecure defaults.

**Fix:** Add `STRICT_SECRETS: bool` flag. When `True`, a Pydantic `model_validator` raises `ValueError` if any password equals its default value.

**Files:**
- Modify: `shared/config.py`
- Modify: `.env.example`
- Create: `tests/test_strict_secrets.py`

---

- [ ] **Step 3.1 — Write failing test**

```python
# tests/test_strict_secrets.py
import os
import pytest


@pytest.mark.unit
def test_strict_secrets_off_by_default(monkeypatch):
    """STRICT_SECRETS defaults to False — default passwords should not raise."""
    monkeypatch.delenv("STRICT_SECRETS", raising=False)
    from shared.config import Settings
    # Should not raise even with default passwords
    s = Settings()
    assert s.STRICT_SECRETS is False


@pytest.mark.unit
def test_strict_secrets_raises_on_default_graphdb_password(monkeypatch):
    """When STRICT_SECRETS=true, default GraphDB password should raise ValueError."""
    monkeypatch.setenv("STRICT_SECRETS", "true")
    monkeypatch.setenv("GRAPHDB_PASSWORD", "Admin@GraphDB2024")  # default value
    monkeypatch.setenv("SECRET_KEY", "changed-key-for-testing-purposes-1234567890ab")
    from importlib import reload
    import shared.config as cfg
    reload(cfg)
    with pytest.raises(ValueError, match="STRICT_SECRETS"):
        cfg.Settings()
    reload(cfg)  # restore


@pytest.mark.unit
def test_strict_secrets_passes_with_custom_password(monkeypatch):
    """When STRICT_SECRETS=true and passwords are custom, no error raised."""
    monkeypatch.setenv("STRICT_SECRETS", "true")
    monkeypatch.setenv("GRAPHDB_PASSWORD", "my-secure-graphdb-pass-xyz!")
    monkeypatch.setenv("POSTGRES_USER_PASSWORD", "my-secure-postgres-pass!")
    monkeypatch.setenv("MYSQL_PASSWORD", "my-secure-mysql-pass!")
    monkeypatch.setenv("SECRET_KEY", "changed-key-for-testing-purposes-1234567890ab")
    from importlib import reload
    import shared.config as cfg
    reload(cfg)
    s = cfg.Settings()
    assert s.STRICT_SECRETS is True
    reload(cfg)  # restore
```

- [ ] **Step 3.2 — Run test to verify it fails**

```bash
python -m pytest tests/test_strict_secrets.py -v
```

Expected: `FAILED test_strict_secrets_raises_on_default_graphdb_password` — no validator exists yet.

- [ ] **Step 3.3 — Add `STRICT_SECRETS` field and validator to config.py**

In `shared/config.py`, add the field after the existing `RBAC_ENABLED` field (around line 260):

```python
    STRICT_SECRETS: bool = Field(
        default=False,
        description=(
            "When True, the application refuses to start if any service password "
            "equals its default value. Set to True in all production deployments."
        ),
    )
```

Add a `model_validator` **after** the existing `SECRET_KEY` validator at the bottom of the `Settings` class (search for `@model_validator` or `@validator` near line 590):

```python
    @model_validator(mode="after")
    def _check_strict_secrets(self) -> "Settings":
        """Refuse startup when STRICT_SECRETS=True and any password is the default."""
        if not self.STRICT_SECRETS:
            return self
        _DEFAULT_PASSWORDS = {
            "GRAPHDB_PASSWORD": "Admin@GraphDB2024",
            "POSTGRES_USER_PASSWORD": "ontobot_secret",
            "MYSQL_PASSWORD": "mysql",
        }
        offenders = [
            name
            for name, default in _DEFAULT_PASSWORDS.items()
            if getattr(self, name, None) == default
        ]
        if offenders:
            raise ValueError(
                f"STRICT_SECRETS=true but the following passwords equal their "
                f"insecure defaults — set them via environment variables before "
                f"starting: {', '.join(offenders)}"
            )
        return self
```

Ensure `model_validator` is imported at the top of `shared/config.py`:
```python
from pydantic import Field, model_validator
```
(It is likely already imported — check and add only if missing.)

- [ ] **Step 3.4 — Update `.env.example`**

Find the production/deployment section in `.env.example`. Add after the `RBAC_ENABLED` line:

```bash
# Set to true in all production deployments. Refuses startup if any
# service password (GraphDB, Postgres, MySQL) equals its insecure default.
# STRICT_SECRETS=true
```

- [ ] **Step 3.5 — Run tests to verify they pass**

```bash
python -m pytest tests/test_strict_secrets.py -v
```

Expected: `3 passed`

- [ ] **Step 3.6 — Commit**

```bash
git add shared/config.py .env.example tests/test_strict_secrets.py
git commit -m "feat(config): add STRICT_SECRETS validator — blocks startup with default passwords in prod"
```

---

## Task 4 — Multi-Intent Result Aggregation Fix

**Problem:** For compound queries like "tell me CO2 levels on floor 2 AND generate an energy report", the planner's `_execute_multi_intent` skips `sensor_data` sub-intents (line 185: `if agent in ("sparql", "sql", "sensor_data"): continue`). The sensor readings data-pipeline result is never added to `section_results`, so only the last standalone result (often `floor_plan`) appears in the response.

**Fix:** After the data pipeline (sparql+sql) completes, extract the SQL time-series result and add it as a `sensor_data` section in `section_results` — but only when `sensor_data` was one of the original sub-intents. Use `_extract_section_content("sensor_data", sql_result)` for the content.

**Files:**
- Modify: `orchestrator/agents/planner_agent.py:329-424` (`_execute_multi_intent`)
- Create: `tests/test_multi_intent_aggregation.py`

---

- [ ] **Step 4.1 — Write failing test**

```python
# tests/test_multi_intent_aggregation.py
import pytest
from unittest.mock import AsyncMock, MagicMock, patch
from orchestrator.agents.planner_agent import PlannerAgent, ExecutionPlan, PlanStep


def _make_plan(sub_intents):
    """Build a multi-intent ExecutionPlan from a list of {'intent', 'sub_query'} dicts."""
    steps = []
    idx = 1
    for s in sub_intents:
        if s["intent"] in ("sparql", "sql"):
            continue
        if s["intent"] == "sensor_data":
            steps.append(PlanStep(index=idx, agent="sparql", description="sparql", params={}))
            idx += 1
            steps.append(PlanStep(index=idx, agent="sql", description="sql", params={}))
            idx += 1
        else:
            steps.append(PlanStep(index=idx, agent=s["intent"], description=s["sub_query"], params={"sub_query": s["sub_query"]}))
            idx += 1
    return ExecutionPlan(
        user_query="compound test query",
        steps=steps,
        rationale="test",
        multi_intent=True,
    )


@pytest.mark.asyncio
@pytest.mark.unit
async def test_sensor_data_section_included_in_multi_intent_result():
    """sensor_data sub-intent result must appear in the aggregated response."""
    from shared.models import ConversationState, Message
    from datetime import datetime

    state = ConversationState(
        conversation_id="test-conv",
        messages=[Message(role="user", content="CO2 on floor 2 and show floor 2 plan", timestamp=datetime.now())],
        building_id="bldg1",
    )
    state.intermediate_results["multi_intent_plan"] = {
        "sub_intents": [
            {"intent": "sensor_data", "sub_query": "CO2 on floor 2"},
            {"intent": "floor_plan", "sub_query": "show floor 2 plan"},
        ]
    }

    agent = PlannerAgent()

    # Mock all dispatch methods to avoid real API calls
    async def fake_sparql(state, query, params):
        return {"results": {}, "uuids": ["uuid-co2-001"]}

    async def fake_sql(state, query, uuids, storage_map, params):
        return {
            "results": {"data": [{"sensor": "CO2_Sensor_2.01", "value": 450}]},
            "formatted_text": "CO2 in floor 2: 450 ppm",
        }

    async def fake_floor_plan(state, query, params):
        from orchestrator.agents.floor_plan_agent import FloorPlanResult
        return FloorPlanResult(markdown="## Floor 2 Plan\nSome rooms", floors=[2])

    with patch.object(agent, "_run_sparql", side_effect=fake_sparql), \
         patch.object(agent, "_run_sql", side_effect=fake_sql), \
         patch.object(agent, "_run_floor_plan", side_effect=fake_floor_plan):
        result = await agent.plan_and_execute(state, state.messages[-1].content)

    assert result["success"] is True
    response = result["formatted_response"]
    # Both sensor data AND floor plan must appear
    assert "CO2" in response or "450" in response or "Sensor" in response, \
        f"Sensor data missing from response: {response[:300]}"
    assert "Floor" in response or "floor" in response or "Plan" in response, \
        f"Floor plan missing from response: {response[:300]}"
```

- [ ] **Step 4.2 — Run test to verify it fails**

```bash
python -m pytest tests/test_multi_intent_aggregation.py::test_sensor_data_section_included_in_multi_intent_result -v
```

Expected: `FAILED` — sensor data section missing or only floor plan present.

- [ ] **Step 4.3 — Fix `_execute_multi_intent` in planner_agent.py**

Read current `_execute_multi_intent` at lines 329–424. After the `data_steps` sequential execution loop (after line ~371), add a block that captures the SQL result as a sensor_data section **when sensor_data was a requested sub-intent**:

```python
        # After data pipeline completes: if sensor_data was a requested sub-intent,
        # add the SQL time-series result as a section so it appears in the response.
        # Previously, sensor_data was silently skipped (group_a filter excluded it).
        multi_intent_plan = state.intermediate_results.get("multi_intent_plan", {})
        _requested_sub_intents = {
            s.get("intent") for s in multi_intent_plan.get("sub_intents", [])
        }
        if "sensor_data" in _requested_sub_intents:
            sql_r = context.get("sql_result")
            if sql_r:
                sensor_content = self._extract_section_content("sql", sql_r)
                if sensor_content and sensor_content.strip():
                    section_results.append({
                        "agent": "sensor_data",
                        "description": next(
                            (s.get("sub_query", "sensor readings")
                             for s in multi_intent_plan.get("sub_intents", [])
                             if s.get("intent") == "sensor_data"),
                            "sensor readings",
                        ),
                        "content": sensor_content,
                    })
                    logger.info(
                        "[multi-intent] Added sensor_data section from SQL result "
                        f"({len(sensor_content)} chars)"
                    )
```

Place this block between the `data_steps` loop and the `# Phase 2: Run post-data agents AND standalone agents in parallel` comment.

- [ ] **Step 4.4 — Also add `sensor_data` to `_section_header` map**

In `_section_header` (line ~551), ensure `"sensor_data"` and `"sql"` are mapped:

```python
        _HEADERS = {
            "analytics": "Sensor Data Analysis",
            "anomaly": "Anomaly Detection",
            "capability": "Building Information",
            "floor_plan": "Floor Plan",
            "spatial_query": "Spatial Information",
            "report": "Report",
            "compare": "Comparison",
            "trend": "Trend Analysis",
            "recommend": "Recommendations",
            "compliance": "Compliance Check",
            "maintenance": "Maintenance",
            "export": "Data Export",
            "sensor_data": "Sensor Readings",
            "sql": "Sensor Readings",        # ← add these two
        }
```

- [ ] **Step 4.5 — Run test to verify it passes**

```bash
python -m pytest tests/test_multi_intent_aggregation.py -v
```

Expected: `1 passed`

- [ ] **Step 4.6 — Run full suite to check for regressions**

```bash
python -m pytest tests/ -q --tb=short -x 2>&1 | tail -20
```

Expected: same number of failures as before (846 pass, 2 fail) — no new failures.

- [ ] **Step 4.7 — Rebuild and live-smoke-test**

```bash
docker-compose build orchestrator && docker-compose up -d orchestrator
# flush cache so previous planner result doesn't mask the fix
docker exec redis-memory-store redis-cli eval "local keys = redis.call('keys', 'resp_cache:*') for i,k in ipairs(keys) do redis.call('del', k) end return #keys" 0
# wait ~20s
curl -s -X POST http://localhost:8000/chat \
  -H "Content-Type: application/json" \
  -H "Authorization: Bearer <token>" \
  -d '{"message":"Show me CO2 levels on floor 2 and also show me the floor 2 layout","session_id":"t4-smoke","building_id":"bldg1"}' \
  | python -c "import sys,json; d=json.load(sys.stdin); r=d.get('"'"'data'"'"',{}).get('"'"'response'"'"',''); print('HAS_CO2:', '"'"'CO2'"'"' in r or '"'"'co2'"'"' in r.lower()); print('HAS_FLOOR:', '"'"'Floor'"'"' in r or '"'"'floor'"'"' in r.lower()); print(r[:400])"
```

Expected: both `HAS_CO2: True` and `HAS_FLOOR: True`.

- [ ] **Step 4.8 — Commit**

```bash
git add orchestrator/agents/planner_agent.py tests/test_multi_intent_aggregation.py
git commit -m "fix(planner): include sensor_data section in multi-intent aggregated response"
```

---

## Task 5 — Async Job Queue for Long-Running Reports

**Problem:** `report` intent routes through the planner (4 LLM steps ≈ 3–5 min). The synchronous `/chat` endpoint times out for clients (45s in tests, browser ~60s). Users get an error even though the report eventually completes.

**Fix:** Add a lightweight Redis-backed async job queue:
1. When `/chat` detects `report` (or `planner`) intent on a cold cache, start a background task and return `{"job_id": "...", "status": "queued", "poll_url": "/jobs/<id>"}` immediately with HTTP 202.
2. `GET /jobs/{job_id}` returns `{"status": "running"|"done"|"failed", "result": {...}}`.
3. Jobs expire from Redis after 1 hour.
4. If the result is already cached (warm response cache hit), the synchronous path is used as before — no job overhead.

**Files:**
- Create: `orchestrator/services/job_queue.py`
- Modify: `orchestrator/main.py` — detect report intent before executing, start background task, add `/jobs/{job_id}` endpoint
- Create: `tests/test_async_jobs.py`

---

- [ ] **Step 5.1 — Write failing test**

```python
# tests/test_async_jobs.py
import pytest
import asyncio


@pytest.mark.unit
def test_job_queue_module_importable():
    """Job queue module must exist and expose the required API."""
    from orchestrator.services.job_queue import JobQueue, JobStatus
    assert hasattr(JobQueue, "create_job")
    assert hasattr(JobQueue, "update_job")
    assert hasattr(JobQueue, "get_job")
    assert JobStatus.QUEUED.value == "queued"
    assert JobStatus.RUNNING.value == "running"
    assert JobStatus.DONE.value == "done"
    assert JobStatus.FAILED.value == "failed"


@pytest.mark.asyncio
@pytest.mark.unit
async def test_job_lifecycle(mocker):
    """A job goes queued → running → done and result is retrievable."""
    from orchestrator.services.job_queue import JobQueue, JobStatus
    import json

    # Mock redis
    store = {}
    mock_redis = mocker.AsyncMock()
    mock_redis.set = mocker.AsyncMock(side_effect=lambda k, v, ex=None: store.update({k: v}))
    mock_redis.get = mocker.AsyncMock(side_effect=lambda k: store.get(k))

    jq = JobQueue(mock_redis)
    job_id = await jq.create_job("test-conv", "Generate energy report")
    assert job_id is not None

    raw = await mock_redis.get(f"job:{job_id}")
    job = json.loads(raw)
    assert job["status"] == JobStatus.QUEUED.value

    await jq.update_job(job_id, JobStatus.RUNNING)
    raw = await mock_redis.get(f"job:{job_id}")
    job = json.loads(raw)
    assert job["status"] == JobStatus.RUNNING.value

    await jq.update_job(job_id, JobStatus.DONE, result={"response": "Report complete"})
    raw = await mock_redis.get(f"job:{job_id}")
    job = json.loads(raw)
    assert job["status"] == JobStatus.DONE.value
    assert job["result"]["response"] == "Report complete"


@pytest.mark.unit
def test_jobs_endpoint_exists():
    """GET /jobs/{job_id} endpoint must be registered in FastAPI app."""
    from orchestrator.main import app
    routes = [r.path for r in app.routes]
    assert "/jobs/{job_id}" in routes, f"Missing /jobs/{{job_id}} in routes: {routes}"
```

- [ ] **Step 5.2 — Run test to verify it fails**

```bash
python -m pytest tests/test_async_jobs.py -v
```

Expected: `FAILED test_job_queue_module_importable` — module does not exist yet.

- [ ] **Step 5.3 — Create `orchestrator/services/job_queue.py`**

```python
"""
JobQueue — lightweight Redis-backed async job store for long-running requests.

Jobs live at key ``job:{job_id}`` with a 1-hour TTL.
Callers create a job, fire a background task that calls update_job() on
completion, and let clients poll GET /jobs/{job_id}.
"""

import json
import secrets
from datetime import datetime
from enum import Enum
from typing import Any, Dict, Optional

from shared.utils import get_logger

logger = get_logger(__name__)

_JOB_TTL_S = 3600  # 1 hour


class JobStatus(str, Enum):
    QUEUED = "queued"
    RUNNING = "running"
    DONE = "done"
    FAILED = "failed"


class JobQueue:
    """Thin wrapper around a Redis client for job lifecycle management."""

    def __init__(self, redis_client) -> None:
        self._redis = redis_client

    async def create_job(
        self,
        conversation_id: str,
        user_message: str,
        intent: Optional[str] = None,
    ) -> str:
        """Create a new job and return its job_id."""
        job_id = secrets.token_urlsafe(12)
        payload = {
            "job_id": job_id,
            "conversation_id": conversation_id,
            "user_message": user_message[:200],
            "intent": intent,
            "status": JobStatus.QUEUED.value,
            "created_at": datetime.utcnow().isoformat(),
            "updated_at": datetime.utcnow().isoformat(),
            "result": None,
            "error": None,
        }
        await self._redis.set(
            f"job:{job_id}", json.dumps(payload), ex=_JOB_TTL_S
        )
        logger.info(f"[job_queue] created job_id={job_id} intent={intent}")
        return job_id

    async def update_job(
        self,
        job_id: str,
        status: JobStatus,
        result: Optional[Dict[str, Any]] = None,
        error: Optional[str] = None,
    ) -> None:
        """Update job status (and optionally result/error). Resets TTL."""
        raw = await self._redis.get(f"job:{job_id}")
        if not raw:
            logger.warning(f"[job_queue] update_job: job_id={job_id} not found")
            return
        payload = json.loads(raw)
        payload["status"] = status.value
        payload["updated_at"] = datetime.utcnow().isoformat()
        if result is not None:
            payload["result"] = result
        if error is not None:
            payload["error"] = error
        await self._redis.set(
            f"job:{job_id}", json.dumps(payload), ex=_JOB_TTL_S
        )

    async def get_job(self, job_id: str) -> Optional[Dict[str, Any]]:
        """Return the job payload dict, or None if not found / expired."""
        raw = await self._redis.get(f"job:{job_id}")
        if not raw:
            return None
        return json.loads(raw)
```

- [ ] **Step 5.4 — Add `/jobs/{job_id}` endpoint and background execution to `main.py`**

**Part A — import and initialise JobQueue**

In `orchestrator/main.py`, find where the other service instances are initialised (search for `redis_manager = RedisManager()` or similar, around the startup lifespan block). Add after Redis is connected:

```python
from orchestrator.services.job_queue import JobQueue, JobStatus as _JobStatus
# ... (place near other service initialisations)
job_queue: Optional[JobQueue] = None
```

In the `lifespan` function, after `await redis_manager.connect()` succeeds:

```python
        global job_queue
        job_queue = JobQueue(redis_manager.redis)
        logger.info("Job queue initialised")
```

**Part B — background worker helper**

Add this helper function to `main.py` (just before the `/chat` endpoint at line ~1608):

```python
async def _run_workflow_as_job(
    job_id: str,
    state,
    user_message: str,
    conversation_id: str,
    username: str,
) -> None:
    """Background coroutine: run orchestrator, update job status in Redis."""
    try:
        await job_queue.update_job(job_id, _JobStatus.RUNNING)
        updated_state = await orchestrator.execute(state)
        await redis_manager.save_state(updated_state)

        response_text = updated_state.intermediate_results.get("response", "")
        intent = getattr(updated_state, "current_intent", "unknown")

        await job_queue.update_job(
            job_id,
            _JobStatus.DONE,
            result={
                "conversation_id": conversation_id,
                "response": response_text,
                "intent": intent,
                "username": username,
            },
        )
        logger.info(f"[job] job_id={job_id} completed intent={intent}")
    except Exception as e:
        logger.error(f"[job] job_id={job_id} failed: {e}", exc_info=True)
        await job_queue.update_job(
            job_id, _JobStatus.FAILED, error=str(e)
        )
```

**Part C — detect long-running intent in `/chat` and offload to background**

In the `/chat` handler, after the state is prepared and just before `updated_state = await orchestrator.execute(state)` (line ~1708), add:

```python
        # Long-running intents (report, planner) are offloaded to a background
        # job so the client does not time out waiting for 3–5 minute pipelines.
        # The response cache is checked first — warm-cache hits are still sync.
        _ASYNC_INTENTS = frozenset({"report", "planner"})
        _pre_intent = req.intent if hasattr(req, "intent") and req.intent else None

        # Peek at the semantic router to detect report/planner before full execution
        # by checking for explicit report/planner keywords in the message.
        _REPORT_TRIGGER_PHRASES = (
            "generate report", "create report", "build report", "energy report",
            "generate a report", "create a report", "monthly report", "weekly report",
            "daily report", "annual report", "generate an energy", "full report",
        )
        _is_long_running = any(ph in user_message.lower() for ph in _REPORT_TRIGGER_PHRASES)

        if _is_long_running and job_queue is not None:
            # Check response cache first — if already cached, skip async path
            from orchestrator.services.response_cache import response_cache
            _cache_hit = await response_cache.get_exact(user_message, state.building_id)
            if _cache_hit:
                logger.info(f"[async-job] cache hit for report query — serving sync")
            else:
                job_id = await job_queue.create_job(
                    conversation_id, user_message, intent="report"
                )
                import asyncio as _asyncio
                _asyncio.create_task(
                    _run_workflow_as_job(job_id, state, user_message, conversation_id, username)
                )
                logger.info(f"[async-job] report offloaded job_id={job_id}")
                return APIResponse(
                    success=True,
                    data={
                        "job_id": job_id,
                        "status": "queued",
                        "message": (
                            "Your report is being generated. "
                            "Poll GET /jobs/" + job_id + " for the result."
                        ),
                        "poll_url": f"/jobs/{job_id}",
                        "conversation_id": conversation_id,
                        "intent": "report",
                        "username": username,
                    },
                )
```

**Part D — Add `GET /jobs/{job_id}` endpoint**

Add this endpoint to `main.py` after the `/conversation/{conversation_id}` endpoints (around line 2345):

```python
@app.get("/jobs/{job_id}", response_model=APIResponse)
async def get_job_status(
    job_id: str,
    current_user: Optional[str] = Depends(get_current_user),
):
    """Poll status of a background job (created when a long-running report was queued)."""
    if job_queue is None:
        return APIResponse(success=False, error="Job queue not initialised")
    job = await job_queue.get_job(job_id)
    if job is None:
        return APIResponse(
            success=False,
            error=f"Job {job_id!r} not found or expired (TTL 1 hour)",
        )
    return APIResponse(success=True, data=job)
```

- [ ] **Step 5.5 — Run tests to verify they pass**

```bash
python -m pytest tests/test_async_jobs.py -v
```

Expected: `3 passed`

- [ ] **Step 5.6 — Run full suite to check for regressions**

```bash
python -m pytest tests/ -q --tb=short 2>&1 | tail -15
```

Expected: ≥ 846 pass, same 2 pre-existing failures.

- [ ] **Step 5.7 — Rebuild and live-smoke-test the async job path**

```bash
docker-compose build orchestrator && docker-compose up -d orchestrator
# flush cache
docker exec redis-memory-store redis-cli eval "local keys = redis.call('keys', 'resp_cache:*') for i,k in ipairs(keys) do redis.call('del', k) end return #keys" 0

# wait ~20s then request a report (should return 202 with job_id)
TOKEN=$(curl -s -X POST http://localhost:8000/auth/login \
  -H "Content-Type: application/json" \
  -d '{"username":"reviewer","password":"Review@2024!"}' \
  | python -c "import sys,json; print(json.load(sys.stdin)['data']['session_token'])")

RESP=$(curl -s -X POST http://localhost:8000/chat \
  -H "Content-Type: application/json" \
  -H "Authorization: Bearer $TOKEN" \
  -d '{"message":"Generate an energy report for last month","session_id":"t5-smoke","building_id":"bldg1"}')

echo $RESP | python -m json.tool | grep -E "job_id|status|poll_url"
JOB_ID=$(echo $RESP | python -c "import sys,json; print(json.load(sys.stdin)['data']['job_id'])")
echo "Polling job: $JOB_ID"

# Poll until done (max 5 min)
for i in $(seq 1 30); do
  STATUS=$(curl -s "http://localhost:8000/jobs/$JOB_ID" \
    -H "Authorization: Bearer $TOKEN" \
    | python -c "import sys,json; print(json.load(sys.stdin)['data']['status'])")
  echo "  [$i] status=$STATUS"
  if [ "$STATUS" = "done" ] || [ "$STATUS" = "failed" ]; then break; fi
  sleep 10
done
```

Expected:
1. First `curl` returns immediately with `"status": "queued"` and `"job_id": "..."`.
2. Polling eventually returns `"status": "done"` with the full report in `result.response`.

- [ ] **Step 5.8 — Commit**

```bash
git add orchestrator/services/job_queue.py orchestrator/main.py tests/test_async_jobs.py
git commit -m "feat(jobs): async job queue for long-running report generation — GET /jobs/{id} polling"
```

---

## Task 6 — Post-Fix Full Review Run

Run the complete review test suite and save the output as a new review document.

**Files:**
- Run: `scripts/review_test_suite.py` (update token)
- Create: `review docs/system-review-2026-06-01-post-fixes.md`

---

- [ ] **Step 6.1 — Get fresh auth token and flush cache**

```bash
docker exec redis-memory-store redis-cli eval \
  "local keys = redis.call('keys', 'resp_cache:*') for i,k in ipairs(keys) do redis.call('del', k) end return #keys" 0

TOKEN=$(curl -s -X POST http://localhost:8000/auth/login \
  -H "Content-Type: application/json" \
  -d '{"username":"reviewer","password":"Review@2024!"}' \
  | python -c "import sys,json; print(json.load(sys.stdin)['data']['session_token'])")
# Update TOKEN in scripts/review_test_suite.py
```

- [ ] **Step 6.2 — Run full pytest suite**

```bash
python -m pytest tests/ -q --tb=short 2>&1 | tee /tmp/pytest-post-fixes.txt | tail -15
```

- [ ] **Step 6.3 — Run live review test suite**

```bash
python -X utf8 scripts/review_test_suite.py 2>&1 | tee /tmp/review-post-fixes.txt
```

- [ ] **Step 6.4 — Save review report**

Create `review docs/system-review-2026-06-01-post-fixes.md` with:
- Stack health (from `GET /health`)
- pytest results (from `/tmp/pytest-post-fixes.txt`)
- Live test scores (from `/tmp/review-post-fixes.txt`)
- Changes-since-last-review section summarising what each task fixed
- Any new issues discovered

- [ ] **Step 6.5 — Commit final report**

```bash
git add "review docs/system-review-2026-06-01-post-fixes.md"
git commit -m "docs(review): post-improvement review report — all 5 known issues addressed"
```

---

## Self-Review Checklist

- [x] **Spec coverage:** All 5 known issues from review report have a corresponding task (T1–T5). Task 6 runs and saves the new review.
- [x] **No placeholders:** Every step has exact code, exact commands, and exact expected output.
- [x] **Type consistency:** `JobStatus` enum defined in T5.3 is imported in T5.1, T5.4 — consistent names throughout.
- [x] **TDD order:** Every task writes the failing test first (Step N.1), verifies failure (Step N.2), implements fix (Step N.3+), verifies pass (Step N.4/N.5).
- [x] **No regression risk:** Each change is isolated to a specific bypass/override pattern or a new module; existing routing paths are unaffected unless the new conditions trigger.
- [x] **Imports:** `_FORECAST_KWS` and `_MAINTENANCE_SCHEDULE_KWS` are exported at module level so tests can import them without instantiating a full agent.
