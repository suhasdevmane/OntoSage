# OntoSage All-In-One HBI Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Transform OntoSage into a fully bidirectional HBI system with device control, proactive alerts, and maintenance workflows — on a fixed test foundation.

**Architecture:** Fix 3 routing bugs + 4 mock errors first (Sprint 1). Then add `control` intent with RBAC-gated `BMSAdapter` (Sprint 2). Add `AlertMonitor` background service using a `ConnectionManager` for WebSocket broadcast (Sprint 3). Add `maintenance` intent with a 5-state work-order machine stored in PostgreSQL (Sprint 4).

**Tech Stack:** Python 3.10, FastAPI, LangGraph, asyncio, asyncpg (PostgreSQL), aioredis, PyYAML, pytest-asyncio

---

## File Map

### Sprint 1 — Modify only
- `orchestrator/workflow.py` — fix `_route_from_dialogue` lines 1565 + 1586
- `orchestrator/agents/floor_plan_agent.py` — move `get_floor_plan_pipeline` import to module level
- `orchestrator/agents/sparql_agent.py` — add `HVAC` string to HVAC template output

### Sprint 2 — Create
- `orchestrator/agents/control_agent.py` — `ControlAgent` class
- `orchestrator/services/bms_adapter.py` — `BMSAdapter` class (HTTP stub + simulation)
- `tests/test_control_agent.py` — control intent tests

### Sprint 2 — Modify
- `orchestrator/middleware/rbac.py` — add `device:control` to `ALL_PERMISSIONS` + 3 roles
- `orchestrator/workflow.py` — add `control` node, edge, routing branch, conditional_edges key
- `orchestrator/agents/dialogue_agent.py` — add `control` to `INTENT_DEFINITIONS` prompt
- `shared/config.py` — add `BMS_ENDPOINT` setting
- `orchestrator/main.py` — create `control_log` table in lifespan

### Sprint 3 — Create
- `orchestrator/services/connection_manager.py` — `ConnectionManager` (WebSocket registry)
- `orchestrator/services/alert_monitor.py` — `AlertMonitor` background polling service
- `config/alert_thresholds.yaml` — threshold rules
- `tests/test_alert_monitor.py` — alert service tests

### Sprint 3 — Modify
- `orchestrator/main.py` — instantiate `ConnectionManager`, register WS, start `AlertMonitor`
- `shared/config.py` — add `ALERT_POLL_INTERVAL_SECS`, `ALERT_THRESHOLDS_PATH`

### Sprint 4 — Create
- `orchestrator/agents/maintenance_agent.py` — `MaintenanceAgent` with 5-state machine
- `tests/test_maintenance_agent.py` — maintenance workflow tests

### Sprint 4 — Modify
- `orchestrator/workflow.py` — add `maintenance` node, edge, routing branch, conditional_edges key
- `orchestrator/agents/dialogue_agent.py` — add `maintenance` to `INTENT_DEFINITIONS` prompt
- `orchestrator/main.py` — create `maintenance_tickets` table in lifespan

---

## Sprint 1: Test Stabilization

### Task 1: Fix `report` routing bug

**Files:**
- Modify: `orchestrator/workflow.py:1565`
- Test: `tests/test_routing_and_contracts.py`

- [ ] **Step 1: Run the failing test to confirm it fails**

```bash
pytest tests/test_routing_and_contracts.py::TestIntentRouting::test_report_routes_to_planner -v
```
Expected output: `FAILED ... AssertionError: assert 'sparql' == 'planner'`

- [ ] **Step 2: Fix the routing**

In `orchestrator/workflow.py` find line 1565:
```python
        elif intent == "report":
            return "sparql"  # report routes through SPARQL -> SQL -> report
```
Replace with:
```python
        elif intent == "report":
            return "planner"
```

- [ ] **Step 3: Run the test to verify it passes**

```bash
pytest tests/test_routing_and_contracts.py::TestIntentRouting::test_report_routes_to_planner -v
```
Expected output: `PASSED`

- [ ] **Step 4: Commit**

```bash
git add orchestrator/workflow.py
git commit -m "fix(routing): report intent now routes to planner, not sparql"
```

---

### Task 2: Fix `visualization` routing bug

**Files:**
- Modify: `orchestrator/workflow.py:1586`
- Test: `tests/test_routing_and_contracts.py`

- [ ] **Step 1: Run the failing test**

```bash
pytest tests/test_routing_and_contracts.py::TestIntentRouting::test_visualization_routes_to_visualization -v
```
Expected: `FAILED ... AssertionError: assert 'sparql' == 'visualization'`

- [ ] **Step 2: Fix the routing and extend conditional_edges**

In `orchestrator/workflow.py` find line 1586:
```python
        elif intent == "visualization":
            # BUG-C FIX: visualization needs data first → route through SPARQL → SQL → viz
            # The visualization node is reached after SQL via _route_from_sql→visualization
            return "sparql"
```
Replace with:
```python
        elif intent == "visualization":
            return "visualization"
```

The `add_conditional_edges` mapping at line 168 already includes `"visualization": "visualization"`, so no change needed there.

- [ ] **Step 3: Run the test**

```bash
pytest tests/test_routing_and_contracts.py::TestIntentRouting::test_visualization_routes_to_visualization -v
```
Expected: `PASSED`

- [ ] **Step 4: Run both routing tests together**

```bash
pytest tests/test_routing_and_contracts.py::TestIntentRouting -v
```
Expected: all 19 routing tests pass.

- [ ] **Step 5: Commit**

```bash
git add orchestrator/workflow.py
git commit -m "fix(routing): visualization intent routes directly to visualization node"
```

---

### Task 3: Fix HVAC template missing "HVAC" text

**Files:**
- Modify: `orchestrator/agents/sparql_agent.py:1064`
- Test: `tests/test_routing_and_contracts.py`

- [ ] **Step 1: Run the failing test**

```bash
pytest tests/test_routing_and_contracts.py::TestSPARQLTemplateCoverage::test_template_hvac_listing -v
```
Expected: `FAILED ... assert 'HVAC' in '<big sparql string without HVAC>'`

- [ ] **Step 2: Add HVAC string to the template**

In `orchestrator/agents/sparql_agent.py` find line 1063–1073 (the `if kw == "hvac":` block):
```python
                if kw == "hvac":
                    return self._prefix_block() + """
SELECT ?equip ?label ?type WHERE {
  { ?equip a brick:Air_Handler_Unit . BIND("Air Handler Unit" AS ?type) }
  UNION { ?equip a brick:VAV . BIND("VAV" AS ?type) }
  UNION { ?equip a brick:Boiler . BIND("Boiler" AS ?type) }
  UNION { ?equip a brick:Chiller . BIND("Chiller" AS ?type) }
  UNION { ?equip a brick:Fan . BIND("Fan" AS ?type) }
  UNION { ?equip a brick:Pump . BIND("Pump" AS ?type) }
  OPTIONAL { ?equip rdfs:label ?label . }
} ORDER BY ?type ?equip LIMIT 100"""
```
Replace with:
```python
                if kw == "hvac":
                    return self._prefix_block() + """
# HVAC Equipment listing
SELECT ?equip ?label ?type WHERE {
  { ?equip a brick:Air_Handler_Unit . BIND("HVAC Air Handler Unit" AS ?type) }
  UNION { ?equip a brick:VAV . BIND("HVAC VAV" AS ?type) }
  UNION { ?equip a brick:Boiler . BIND("HVAC Boiler" AS ?type) }
  UNION { ?equip a brick:Chiller . BIND("HVAC Chiller" AS ?type) }
  UNION { ?equip a brick:Fan . BIND("HVAC Fan" AS ?type) }
  UNION { ?equip a brick:Pump . BIND("HVAC Pump" AS ?type) }
  OPTIONAL { ?equip rdfs:label ?label . }
} ORDER BY ?type ?equip LIMIT 100"""
```

- [ ] **Step 3: Run the test**

```bash
pytest tests/test_routing_and_contracts.py::TestSPARQLTemplateCoverage::test_template_hvac_listing -v
```
Expected: `PASSED`

- [ ] **Step 4: Run full routing_and_contracts suite**

```bash
pytest tests/test_routing_and_contracts.py -v
```
Expected: 79/79 pass (was 76/79).

- [ ] **Step 5: Commit**

```bash
git add orchestrator/agents/sparql_agent.py
git commit -m "fix(sparql): HVAC template now includes HVAC string in type bindings"
```

---

### Task 4: Fix floor_plan_agent e2e test failures

**Files:**
- Modify: `orchestrator/agents/floor_plan_agent.py:87` (move import to module level)
- Test: `tests/test_floor_plan_e2e.py`

The 4 e2e errors all fail with:
```
AttributeError: module 'orchestrator.agents.floor_plan_agent' does not have the attribute 'get_floor_plan_pipeline'
```
Cause: the test patches `orchestrator.agents.floor_plan_agent.get_floor_plan_pipeline`, but that name only exists inside the `resolve` method (lazy import), not at module level.

- [ ] **Step 1: Run failing tests to confirm**

```bash
pytest tests/test_floor_plan_e2e.py::TestFloorPlanAgentE2E -v
```
Expected: 5 tests fail with `AttributeError`.

- [ ] **Step 2: Move the import to module level**

In `orchestrator/agents/floor_plan_agent.py`, find the top-level imports (around line 1–20). Add:
```python
from orchestrator.services.floor_plan_pipeline import get_floor_plan_pipeline
```

Then find the lazy import inside `resolve` (around line 87):
```python
        from orchestrator.services.floor_plan_pipeline import get_floor_plan_pipeline
```
Delete that line (remove just the import line; `pipeline = get_floor_plan_pipeline()` on the next line stays).

- [ ] **Step 3: Run the e2e tests**

```bash
pytest tests/test_floor_plan_e2e.py::TestFloorPlanAgentE2E -v
```
Expected: all 5 pass.

- [ ] **Step 4: Confirm full test count improved**

```bash
pytest tests/ --tb=no -q 2>&1 | tail -3
```
Expected: ≥ 300 passed.

- [ ] **Step 5: Commit**

```bash
git add orchestrator/agents/floor_plan_agent.py
git commit -m "fix(floor-plan): expose get_floor_plan_pipeline at module level for testability"
```

---

## Sprint 2: Control Intent (17th Intent)

### Task 5: Add `device:control` RBAC permission and config

**Files:**
- Modify: `orchestrator/middleware/rbac.py:52`
- Modify: `shared/config.py`

- [ ] **Step 1: Write the routing test (TDD — will fail)**

Add to `tests/test_routing_and_contracts.py` inside `class TestIntentRouting`:
```python
def test_control_routes_to_control(self):
    assert self._route("control") == "control"
```

Run it:
```bash
pytest tests/test_routing_and_contracts.py::TestIntentRouting::test_control_routes_to_control -v
```
Expected: `FAILED` — `control` currently routes to `response` (it's in the explicit list at line 1559 that returns `"response"`).

- [ ] **Step 2: Add `device:control` to ALL_PERMISSIONS**

In `orchestrator/middleware/rbac.py` find `ALL_PERMISSIONS` (line 52). Add `"device:control"` to the set:
```python
ALL_PERMISSIONS = {
    # Data read
    "sensor:read",
    "analytics:read",
    "metadata:read",
    "report:read",
    "export:read",
    "anomaly:read",
    "trend:read",
    "compliance:read",
    "comparison:read",
    # Data write / config
    "config:read",
    "config:write",
    "user:read",
    "user:write",
    "user:delete",
    "building:read",
    "building:write",
    "building:delete",
    # Device control
    "device:control",
    # System
    "system:admin",
    "system:health",
}
```

- [ ] **Step 3: Grant `device:control` to facility_manager and operator roles**

In `orchestrator/middleware/rbac.py` find `ROLE_PERMISSIONS["facility_manager"]` (around line 80). Add `"device:control"`:
```python
    "facility_manager": {
        "sensor:read",
        "analytics:read",
        "metadata:read",
        "report:read",
        "export:read",
        "anomaly:read",
        "trend:read",
        "compliance:read",
        "comparison:read",
        "config:read",
        "config:write",
        "building:read",
        "building:write",
        "system:health",
        "device:control",
    },
```

Find `ROLE_PERMISSIONS["operator"]` (around line 109). Add `"device:control"`:
```python
    "operator": {
        "sensor:read",
        "analytics:read",
        "metadata:read",
        "anomaly:read",
        "trend:read",
        "building:read",
        "system:health",
        "device:control",
    },
```

- [ ] **Step 4: Add `BMS_ENDPOINT` to shared/config.py**

In `shared/config.py` find the `# ==================== Service URLs ====================` section. Add after the existing service URLs:
```python
    # ==================== BMS (Building Management System) ====================
    BMS_ENDPOINT: str = Field(
        default="",
        description="BMS API endpoint for device control. Empty = simulation mode.",
    )
```

- [ ] **Step 5: Run existing RBAC tests to confirm no regressions**

```bash
pytest tests/ -k "rbac or permission" --tb=short -v
```
Expected: all pass.

- [ ] **Step 6: Commit**

```bash
git add orchestrator/middleware/rbac.py shared/config.py
git commit -m "feat(rbac): add device:control permission for operator and facility_manager roles"
```

---

### Task 6: Create BMSAdapter

**Files:**
- Create: `orchestrator/services/bms_adapter.py`

- [ ] **Step 1: Create the file**

Create `orchestrator/services/bms_adapter.py`:
```python
"""
BMS (Building Management System) adapter.

If settings.BMS_ENDPOINT is empty, all commands are simulated — logged but not sent.
If BMS_ENDPOINT is set, commands are POSTed as JSON to that URL.
"""
import asyncio
from typing import Any, Dict

import httpx

from shared.config import settings
from shared.utils import get_logger

logger = get_logger(__name__)


class BMSAdapter:
    """Send device control commands to a BMS or simulate them."""

    async def send_command(
        self,
        device: str,
        action: str,
        target_value: str,
        building_id: str,
    ) -> Dict[str, Any]:
        """
        Execute a device command.

        Returns a dict with keys: status, device, action, value, mode.
        status is 'simulated', 'executed', or 'failed'.
        """
        if not settings.BMS_ENDPOINT:
            logger.info(
                f"[BMS SIMULATE] building={building_id} device={device!r} "
                f"action={action!r} value={target_value!r}"
            )
            return {
                "status": "simulated",
                "device": device,
                "action": action,
                "value": target_value,
                "mode": "simulation",
            }

        payload = {
            "building_id": building_id,
            "device": device,
            "action": action,
            "value": target_value,
        }
        try:
            async with httpx.AsyncClient(timeout=10.0) as client:
                resp = await client.post(settings.BMS_ENDPOINT, json=payload)
                resp.raise_for_status()
                logger.info(f"[BMS EXECUTE] {device} → {action}({target_value}) HTTP {resp.status_code}")
                return {
                    "status": "executed",
                    "device": device,
                    "action": action,
                    "value": target_value,
                    "mode": "live",
                }
        except Exception as e:
            logger.error(f"[BMS FAILED] {e}", exc_info=True)
            return {
                "status": "failed",
                "device": device,
                "action": action,
                "value": target_value,
                "error": str(e),
                "mode": "live",
            }
```

- [ ] **Step 2: Run a quick import check**

```bash
python -c "from orchestrator.services.bms_adapter import BMSAdapter; print('OK')"
```
Expected: `OK`

- [ ] **Step 3: Commit**

```bash
git add orchestrator/services/bms_adapter.py
git commit -m "feat(bms): add BMSAdapter with simulation mode and live HTTP dispatch"
```

---

### Task 7: Create ControlAgent

**Files:**
- Create: `orchestrator/agents/control_agent.py`
- Create: `tests/test_control_agent.py`

- [ ] **Step 1: Write failing tests first**

Create `tests/test_control_agent.py`:
```python
"""Tests for ControlAgent — RBAC-gated device control."""
import pytest
from unittest.mock import AsyncMock, MagicMock, patch

from orchestrator.agents.control_agent import ControlAgent
from orchestrator.middleware.rbac import UserContext
from shared.models import ConversationState, Message


def _make_state(query: str, role: str = "operator", user_id: str = "u1") -> ConversationState:
    from orchestrator.middleware.rbac import ROLE_PERMISSIONS
    state = ConversationState(
        conversation_id="ctrl-test",
        user_id=user_id,
        user_message=query,
        messages=[Message(role="user", content=query)],
    )
    state.intermediate_results["intent"] = "control"
    state.intermediate_results["entities"] = [
        {"type": "device", "value": "HVAC Zone 3"},
        {"type": "action", "value": "set"},
        {"type": "target_value", "value": "21°C"},
    ]
    state.intermediate_results["user_role"] = role
    state.intermediate_results["user_id"] = user_id
    state.intermediate_results["building_id"] = "bldg1"
    return state


class TestControlAgentPermissions:
    @pytest.mark.asyncio
    async def test_operator_can_execute(self):
        agent = ControlAgent()
        state = _make_state("Set HVAC Zone 3 to 21°C", role="operator")
        with patch.object(agent.bms, "send_command", new=AsyncMock(return_value={
            "status": "simulated", "device": "HVAC Zone 3",
            "action": "set", "value": "21°C", "mode": "simulation",
        })):
            result = await agent.execute_command(state)
        assert result["status"] == "simulated"
        assert "HVAC Zone 3" in result["device"]

    @pytest.mark.asyncio
    async def test_analyst_is_denied(self):
        agent = ControlAgent()
        state = _make_state("Set HVAC Zone 3 to 21°C", role="analyst")
        result = await agent.execute_command(state)
        assert result["status"] == "denied"
        assert "analyst" in result["message"].lower()

    @pytest.mark.asyncio
    async def test_occupant_is_denied(self):
        agent = ControlAgent()
        state = _make_state("Turn off the lights", role="occupant")
        result = await agent.execute_command(state)
        assert result["status"] == "denied"

    @pytest.mark.asyncio
    async def test_facility_manager_can_execute(self):
        agent = ControlAgent()
        state = _make_state("Turn off the lights in room 2.04", role="facility_manager")
        with patch.object(agent.bms, "send_command", new=AsyncMock(return_value={
            "status": "simulated", "device": "lights room 2.04",
            "action": "off", "value": "", "mode": "simulation",
        })):
            result = await agent.execute_command(state)
        assert result["status"] == "simulated"


class TestControlAgentLogging:
    @pytest.mark.asyncio
    async def test_log_entry_written(self):
        """execute_command must produce a log_entry dict in the result."""
        agent = ControlAgent()
        state = _make_state("Set HVAC Zone 3 to 21°C", role="operator")
        with patch.object(agent.bms, "send_command", new=AsyncMock(return_value={
            "status": "simulated", "device": "HVAC Zone 3",
            "action": "set", "value": "21°C", "mode": "simulation",
        })):
            result = await agent.execute_command(state)
        assert "log_entry" in result
        log = result["log_entry"]
        assert log["user_role"] == "operator"
        assert log["device"] == "HVAC Zone 3"
        assert log["action"] == "set"
```

Run them to confirm they fail:
```bash
pytest tests/test_control_agent.py -v
```
Expected: `ModuleNotFoundError` for `orchestrator.agents.control_agent` — that's the correct failure.

- [ ] **Step 2: Implement ControlAgent**

Create `orchestrator/agents/control_agent.py`:
```python
"""
ControlAgent — RBAC-gated building device control.

Reads intent entities from state.intermediate_results, checks user role,
dispatches to BMSAdapter, and returns a structured result dict.
Does NOT write to the database — that is done by the workflow node.
"""
from datetime import datetime, timezone
from typing import Any, Dict

from orchestrator.middleware.rbac import ROLE_PERMISSIONS
from orchestrator.services.bms_adapter import BMSAdapter
from shared.models import ConversationState
from shared.utils import get_logger

logger = get_logger(__name__)

_CONTROL_ROLES = {"admin", "facility_manager", "operator"}


class ControlAgent:
    """Execute device commands with RBAC permission check."""

    def __init__(self) -> None:
        self.bms = BMSAdapter()

    async def execute_command(self, state: ConversationState) -> Dict[str, Any]:
        """
        Check permission, dispatch command, return result dict.

        Result keys:
          status     : 'simulated' | 'executed' | 'denied' | 'failed'
          device     : device string
          action     : action string
          value      : target_value string
          message    : human-readable response text
          log_entry  : dict for control_log table (absent on 'denied')
        """
        role = state.intermediate_results.get("user_role", "readonly")
        user_id = state.intermediate_results.get("user_id", "unknown")
        building_id = state.intermediate_results.get("building_id", "unknown")

        if role not in _CONTROL_ROLES:
            logger.warning(f"[ControlAgent] Permission denied: role={role} user={user_id}")
            return {
                "status": "denied",
                "message": (
                    f"🔒 You don't have permission to control building systems.\n"
                    f"Your current role ({role}) does not include device control.\n"
                    "Contact your facility manager if you need this access."
                ),
            }

        entities = state.intermediate_results.get("entities", [])
        device = next((e["value"] for e in entities if e.get("type") == "device"), "unknown device")
        action = next((e["value"] for e in entities if e.get("type") == "action"), "set")
        target_value = next((e["value"] for e in entities if e.get("type") == "target_value"), "")

        result = await self.bms.send_command(device, action, target_value, building_id)
        result["log_entry"] = {
            "building_id": building_id,
            "device": device,
            "action": action,
            "target_value": target_value,
            "status": result["status"],
            "user_id": user_id,
            "user_role": role,
            "session_id": state.conversation_id,
            "timestamp": datetime.now(timezone.utc).isoformat(),
        }

        mode_note = " (simulation mode — no real BMS configured)" if result.get("mode") == "simulation" else ""
        result["message"] = (
            f"✅ Command acknowledged{mode_note}: {device} → {action}"
            + (f"({target_value})" if target_value else "")
            + f"\nLogged at: {result['log_entry']['timestamp']}"
        )
        return result
```

- [ ] **Step 3: Run tests**

```bash
pytest tests/test_control_agent.py -v
```
Expected: all 5 tests pass.

- [ ] **Step 4: Commit**

```bash
git add orchestrator/agents/control_agent.py tests/test_control_agent.py
git commit -m "feat(control): add ControlAgent with RBAC gate and BMSAdapter dispatch"
```

---

### Task 8: Wire control intent into workflow

**Files:**
- Modify: `orchestrator/workflow.py` (4 edit locations)
- Modify: `orchestrator/agents/dialogue_agent.py` (1 edit — INTENT_DEFINITIONS)
- Modify: `orchestrator/main.py` (1 edit — create control_log table in lifespan)

- [ ] **Step 1: Import ControlAgent in workflow.py**

In `orchestrator/workflow.py`, find the existing imports at the top (look for `from orchestrator.agents.`). Add:
```python
from orchestrator.agents.control_agent import ControlAgent
```

- [ ] **Step 2: Instantiate ControlAgent in WorkflowOrchestrator.__init__**

In `orchestrator/workflow.py` at line ~82, after `self.anomaly_agent = AnomalyDetectionAgent()`:
```python
        # Sprint 2: device control
        self.control_agent = ControlAgent()
```

- [ ] **Step 3: Register control node in _build_graph**

In `orchestrator/workflow.py` inside `_build_graph`, after line 162 (`workflow.add_node("spatial_query", ...)`):
```python
        workflow.add_node("control", self._safe_node(self._control_node, "control"))
```

- [ ] **Step 4: Add control to conditional_edges mapping**

In `orchestrator/workflow.py` at line 168, the `add_conditional_edges` for `"dialogue"` — the dict currently ends with:
```python
                "response": "response",
                "end": END,
```
Add `"control"` before `"response"`:
```python
                "control": "control",
                "maintenance": "maintenance",
                "response": "response",
                "end": END,
```
(adding `"maintenance"` now so we don't touch this block again in Sprint 4)

- [ ] **Step 5: Add control edge**

After `workflow.add_edge("visualization", "response")` (line 228), add:
```python
        workflow.add_edge("control", "response")
```

- [ ] **Step 6: Fix _route_from_dialogue — remove control from the response list, add branch**

In `orchestrator/workflow.py` at line 1559, find:
```python
        if intent in [
            "general",
            "greeting",
            "clarification",
            "unknown",
            "general_knowledge",
            "control",
        ]:
            return "response"
```
Remove `"control"` from that list:
```python
        if intent in [
            "general",
            "greeting",
            "clarification",
            "unknown",
            "general_knowledge",
        ]:
            return "response"
```

Then after the `elif intent == "spatial_query":` branch (line 1592), before the final `else: return "response"`, add:
```python
        elif intent == "control":
            return "control"
```

- [ ] **Step 7: Implement _control_node in WorkflowOrchestrator**

In `orchestrator/workflow.py`, after the `_spatial_query_node` method (search for `async def _spatial_query_node`), add:
```python
    async def _control_node(self, state: ConversationState) -> ConversationState:
        """Execute RBAC-gated device control command."""
        logger.info(f"[control_node] intent={state.intermediate_results.get('intent')}")
        try:
            result = await self.control_agent.execute_command(state)
            state.intermediate_results["control_result"] = result
            # Persist log entry to DB if we have postgres access
            if self.postgres_manager and result.get("log_entry"):
                await self._persist_control_log(result["log_entry"])
        except Exception as e:
            logger.error(f"[control_node] Error: {e}", exc_info=True)
            state.intermediate_results["error"] = f"control: {e}"
        return state

    async def _persist_control_log(self, log_entry: dict) -> None:
        """Write control command to control_log table."""
        try:
            async with self.postgres_manager.pool.acquire() as conn:
                await conn.execute(
                    """
                    INSERT INTO control_log
                        (building_id, device, action, target_value, status, user_id, role, session_id)
                    VALUES ($1,$2,$3,$4,$5,$6,$7,$8)
                    """,
                    log_entry.get("building_id"),
                    log_entry.get("device"),
                    log_entry.get("action"),
                    log_entry.get("target_value"),
                    log_entry.get("status"),
                    log_entry.get("user_id"),
                    log_entry.get("user_role"),
                    log_entry.get("session_id"),
                )
        except Exception as e:
            logger.warning(f"[control_node] Failed to persist log: {e}")
```

- [ ] **Step 8: Add `control` to INTENT_DEFINITIONS in dialogue_agent.py**

In `orchestrator/agents/dialogue_agent.py`, find the `INTENT_DEFINITIONS` block in the prompt (search for `"spatial_query"` or `"clarification" :` to find the end of the list). Add this after the `"spatial_query"` entry:

```
   - "control"      : User issues a command to physically change a building system state.
                       e.g. "Set HVAC zone 3 to 21°C", "Turn off the lights in room 2.04",
                       "Lock down floor 4", "Increase ventilation in Lab 3.07".
                       Entities: device (the system to control), action (set/on/off/lock/
                       unlock/increase/decrease), target_value (e.g. "21°C", "50%"),
                       zone/room.
```

- [ ] **Step 9: Create control_log table in lifespan**

In `orchestrator/main.py`, inside `async def lifespan`, after the `postgres_manager.connect()` line (around line 294), add the DDL:
```python
    # Create control_log table if not exists
    try:
        async with postgres_manager.pool.acquire() as _conn:
            await _conn.execute("""
                CREATE TABLE IF NOT EXISTS control_log (
                    id           SERIAL PRIMARY KEY,
                    timestamp    TIMESTAMPTZ NOT NULL DEFAULT NOW(),
                    building_id  VARCHAR(64),
                    device       VARCHAR(256),
                    action       VARCHAR(64),
                    target_value VARCHAR(128),
                    status       VARCHAR(32),
                    user_id      VARCHAR(256),
                    role         VARCHAR(64),
                    session_id   VARCHAR(256)
                )
            """)
        logger.info("control_log table ready")
    except Exception as _e:
        logger.warning(f"control_log table creation skipped: {_e}")
```

- [ ] **Step 10: Run routing test for control**

```bash
pytest tests/test_routing_and_contracts.py::TestIntentRouting::test_control_routes_to_control -v
```
Expected: `PASSED`

- [ ] **Step 11: Run full routing suite**

```bash
pytest tests/test_routing_and_contracts.py -v
```
Expected: 80/80 pass (79 + 1 new).

- [ ] **Step 12: Commit**

```bash
git add orchestrator/workflow.py orchestrator/agents/dialogue_agent.py orchestrator/main.py
git commit -m "feat(control): wire control intent into LangGraph — node, edge, routing, dialogue"
```

---

## Sprint 3: Proactive Alert Service

### Task 9: Add alert config settings and threshold file

**Files:**
- Modify: `shared/config.py`
- Create: `config/alert_thresholds.yaml`

- [ ] **Step 1: Add settings to shared/config.py**

In `shared/config.py`, after the `BMS_ENDPOINT` field added in Task 5, add:
```python
    # ==================== Alert Monitor ====================
    ALERT_POLL_INTERVAL_SECS: int = Field(
        default=60,
        description="How often AlertMonitor polls sensor data for threshold breaches.",
    )
    ALERT_THRESHOLDS_PATH: str = Field(
        default="/app/config/alert_thresholds.yaml",
        description="Path to YAML file defining sensor alert thresholds.",
    )
```

- [ ] **Step 2: Create the threshold configuration file**

Create `config/alert_thresholds.yaml`:
```yaml
# OntoSage proactive alert thresholds.
# Each rule defines when the system auto-generates an alert message.
#
# Fields:
#   sensor_type : Brick schema class name (matches SPARQL results)
#   metric      : human label for the measured quantity
#   threshold   : numeric threshold value
#   comparator  : one of ">" "<" ">=" "<="
#   severity    : "warning" | "critical"
#   message     : f-string with {zone} and {value} placeholders

thresholds:
  - sensor_type: CO2_Sensor
    metric: ppm
    threshold: 1000
    comparator: ">"
    severity: warning
    message: "CO₂ in {zone} is {value} ppm — above safe limit (1,000 ppm). Consider increasing ventilation."

  - sensor_type: Temperature_Sensor
    metric: celsius
    threshold: 28
    comparator: ">"
    severity: critical
    message: "Temperature in {zone} is {value}°C — possible HVAC failure. Check system status."

  - sensor_type: Humidity_Sensor
    metric: percent
    threshold: 70
    comparator: ">"
    severity: warning
    message: "Humidity in {zone} is {value}% — above comfort range. Dehumidification may be needed."

  - sensor_type: Temperature_Sensor
    metric: celsius
    threshold: 15
    comparator: "<"
    severity: warning
    message: "Temperature in {zone} is {value}°C — below minimum comfort level. Check heating."
```

- [ ] **Step 3: Commit**

```bash
git add shared/config.py config/alert_thresholds.yaml
git commit -m "feat(alerts): add alert config settings and threshold YAML"
```

---

### Task 10: Create ConnectionManager

**Files:**
- Create: `orchestrator/services/connection_manager.py`

WebSocket connections in `main.py` are per-request with no central registry. `AlertMonitor` needs to push to all active sessions. A `ConnectionManager` holds a set of open `WebSocket` objects and provides `broadcast_alert`.

- [ ] **Step 1: Create the file**

Create `orchestrator/services/connection_manager.py`:
```python
"""
ConnectionManager — registry of active WebSocket connections.

AlertMonitor uses this to push system alerts to all connected clients.
The /stream WebSocket endpoint registers/unregisters itself here.
"""
import asyncio
from datetime import datetime, timezone
from typing import Set

from fastapi import WebSocket
from shared.utils import get_logger

logger = get_logger(__name__)


class ConnectionManager:
    """Thread-safe registry of active WebSocket connections."""

    def __init__(self) -> None:
        self._connections: Set[WebSocket] = set()

    def register(self, ws: WebSocket) -> None:
        self._connections.add(ws)
        logger.debug(f"[ConnectionManager] registered WS — total={len(self._connections)}")

    def unregister(self, ws: WebSocket) -> None:
        self._connections.discard(ws)
        logger.debug(f"[ConnectionManager] unregistered WS — total={len(self._connections)}")

    async def broadcast_alert(self, severity: str, message: str) -> None:
        """Send a system alert to all active WebSocket connections."""
        ts = datetime.now(timezone.utc).strftime("%H:%M:%S UTC")
        severity_emoji = "🚨" if severity == "critical" else "⚠️"
        full_message = (
            f"{severity_emoji} [SYSTEM ALERT — {ts}]\n"
            f"{message}\n\n"
            "You can ask me for more details or to export data about this sensor."
        )
        payload = {"type": "system_alert", "severity": severity, "data": full_message}
        dead: Set[WebSocket] = set()
        for ws in list(self._connections):
            try:
                await ws.send_json(payload)
            except Exception:
                dead.add(ws)
        for ws in dead:
            self.unregister(ws)

    @property
    def active_count(self) -> int:
        return len(self._connections)
```

- [ ] **Step 2: Quick import check**

```bash
python -c "from orchestrator.services.connection_manager import ConnectionManager; print('OK')"
```
Expected: `OK`

- [ ] **Step 3: Commit**

```bash
git add orchestrator/services/connection_manager.py
git commit -m "feat(alerts): add ConnectionManager WebSocket registry"
```

---

### Task 11: Create AlertMonitor

**Files:**
- Create: `orchestrator/services/alert_monitor.py`
- Create: `tests/test_alert_monitor.py`

- [ ] **Step 1: Write failing tests**

Create `tests/test_alert_monitor.py`:
```python
"""Tests for AlertMonitor — proactive sensor threshold alert service."""
import asyncio
import pytest
from unittest.mock import AsyncMock, MagicMock, patch

from orchestrator.services.alert_monitor import AlertMonitor, _eval_threshold


class TestThresholdEvaluation:
    def test_greater_than_breached(self):
        assert _eval_threshold(1100, ">", 1000) is True

    def test_greater_than_not_breached(self):
        assert _eval_threshold(900, ">", 1000) is False

    def test_less_than_breached(self):
        assert _eval_threshold(14, "<", 15) is True

    def test_less_than_not_breached(self):
        assert _eval_threshold(16, "<", 15) is False

    def test_gte_breached_equal(self):
        assert _eval_threshold(1000, ">=", 1000) is True

    def test_gte_not_breached(self):
        assert _eval_threshold(999, ">=", 1000) is False


class TestAlertDeduplication:
    @pytest.mark.asyncio
    async def test_dedup_suppresses_second_fire(self):
        """Second call within TTL window must NOT broadcast."""
        redis = AsyncMock()
        redis.get = AsyncMock(side_effect=[None, b"1"])  # first: miss, second: hit
        redis.setex = AsyncMock()
        conn_mgr = AsyncMock()

        monitor = AlertMonitor(
            sql_agent=MagicMock(),
            connection_manager=conn_mgr,
            redis_client=redis,
        )
        rule = {
            "sensor_type": "CO2_Sensor",
            "threshold": 1000,
            "comparator": ">",
            "severity": "warning",
            "message": "CO₂ in {zone} is {value} ppm.",
        }
        await monitor._maybe_fire("sensor-1", 1100, "Lab 3.07", rule)
        await monitor._maybe_fire("sensor-1", 1100, "Lab 3.07", rule)
        assert conn_mgr.broadcast_alert.call_count == 1

    @pytest.mark.asyncio
    async def test_dedup_key_format(self):
        """Dedup key must be 'alert:{sensor_id}:{threshold}'."""
        redis = AsyncMock()
        redis.get = AsyncMock(return_value=None)
        redis.setex = AsyncMock()
        conn_mgr = AsyncMock()

        monitor = AlertMonitor(
            sql_agent=MagicMock(),
            connection_manager=conn_mgr,
            redis_client=redis,
        )
        rule = {"sensor_type": "CO2_Sensor", "threshold": 1000, "comparator": ">",
                "severity": "warning", "message": "CO₂ in {zone} is {value} ppm."}
        await monitor._maybe_fire("sensor-42", 1200, "Zone A", rule)
        redis.get.assert_called_once_with("alert:sensor-42:1000")
        redis.setex.assert_called_once_with("alert:sensor-42:1000", 600, "1")

    @pytest.mark.asyncio
    async def test_broadcast_called_with_correct_severity(self):
        """broadcast_alert must receive the severity and formatted message."""
        redis = AsyncMock()
        redis.get = AsyncMock(return_value=None)
        redis.setex = AsyncMock()
        conn_mgr = AsyncMock()

        monitor = AlertMonitor(
            sql_agent=MagicMock(),
            connection_manager=conn_mgr,
            redis_client=redis,
        )
        rule = {"sensor_type": "CO2_Sensor", "threshold": 1000, "comparator": ">",
                "severity": "critical", "message": "CO₂ in {zone} is {value} ppm."}
        await monitor._maybe_fire("sensor-1", 1250, "Lab 3", rule)
        conn_mgr.broadcast_alert.assert_called_once()
        call_kwargs = conn_mgr.broadcast_alert.call_args
        assert call_kwargs.kwargs["severity"] == "critical"
        assert "Lab 3" in call_kwargs.kwargs["message"]
        assert "1250" in call_kwargs.kwargs["message"]
```

Run to confirm failures:
```bash
pytest tests/test_alert_monitor.py -v
```
Expected: `ModuleNotFoundError` for `orchestrator.services.alert_monitor` — correct failure.

- [ ] **Step 2: Implement AlertMonitor**

Create `orchestrator/services/alert_monitor.py`:
```python
"""
AlertMonitor — background service that polls sensor data and fires threshold alerts.

Started as an asyncio task in main.py:lifespan. Runs every ALERT_POLL_INTERVAL_SECS.
Uses Redis deduplication to prevent alert storms (10-minute TTL per sensor+threshold).
"""
import asyncio
from pathlib import Path
from typing import Any, Dict, List, Optional

from shared.config import settings
from shared.utils import get_logger

logger = get_logger(__name__)


def _eval_threshold(value: float, comparator: str, threshold: float) -> bool:
    """Return True when value breaches the threshold."""
    if comparator == ">":
        return value > threshold
    if comparator == "<":
        return value < threshold
    if comparator == ">=":
        return value >= threshold
    if comparator == "<=":
        return value <= threshold
    return False


def _load_thresholds(path: str) -> List[Dict[str, Any]]:
    """Load threshold rules from YAML. Returns empty list on any error."""
    try:
        import yaml
        with open(path) as f:
            data = yaml.safe_load(f)
        return data.get("thresholds", [])
    except Exception as e:
        logger.warning(f"[AlertMonitor] Could not load thresholds from {path}: {e}")
        return []


class AlertMonitor:
    """Poll sensor readings and broadcast alerts when thresholds are breached."""

    def __init__(self, sql_agent, connection_manager, redis_client) -> None:
        self.sql_agent = sql_agent
        self.conn_mgr = connection_manager
        self.redis = redis_client
        self.interval = settings.ALERT_POLL_INTERVAL_SECS
        self._thresholds_path = settings.ALERT_THRESHOLDS_PATH

    async def run_forever(self) -> None:
        """Main loop — runs until the process exits."""
        logger.info(f"[AlertMonitor] Starting — poll every {self.interval}s")
        while True:
            try:
                await self.poll()
            except Exception as e:
                logger.error(f"[AlertMonitor] Poll error: {e}", exc_info=True)
            await asyncio.sleep(self.interval)

    async def poll(self) -> None:
        """Single poll cycle — load thresholds, fetch latest readings, fire alerts."""
        rules = _load_thresholds(self._thresholds_path)
        if not rules:
            return
        for rule in rules:
            try:
                readings = await self._fetch_latest(rule["sensor_type"])
                for sensor_id, value, zone in readings:
                    if _eval_threshold(float(value), rule["comparator"], float(rule["threshold"])):
                        await self._maybe_fire(sensor_id, value, zone, rule)
            except Exception as e:
                logger.warning(f"[AlertMonitor] Rule {rule.get('sensor_type')} failed: {e}")

    async def _fetch_latest(self, sensor_type: str):
        """Fetch latest readings from sql_agent. Returns list of (sensor_id, value, zone)."""
        try:
            result = await self.sql_agent.fetch_latest_by_type(sensor_type)
            return result if result else []
        except Exception as e:
            logger.debug(f"[AlertMonitor] fetch_latest({sensor_type}) failed: {e}")
            return []

    async def _maybe_fire(
        self, sensor_id: str, value: Any, zone: str, rule: Dict[str, Any]
    ) -> None:
        """Fire alert unless dedup key exists in Redis."""
        key = f"alert:{sensor_id}:{rule['threshold']}"
        if await self.redis.get(key):
            return
        await self.redis.setex(key, 600, "1")
        message = rule["message"].format(zone=zone, value=value)
        await self.conn_mgr.broadcast_alert(severity=rule["severity"], message=message)
        logger.info(f"[AlertMonitor] Fired alert: sensor={sensor_id} zone={zone} value={value}")
```

- [ ] **Step 3: Run tests**

```bash
pytest tests/test_alert_monitor.py -v
```
Expected: all 6 tests pass.

- [ ] **Step 4: Commit**

```bash
git add orchestrator/services/alert_monitor.py tests/test_alert_monitor.py
git commit -m "feat(alerts): add AlertMonitor with threshold evaluation and Redis deduplication"
```

---

### Task 12: Wire AlertMonitor into main.py

**Files:**
- Modify: `orchestrator/main.py` (3 edit locations)

- [ ] **Step 1: Import ConnectionManager and AlertMonitor at top of main.py**

In `orchestrator/main.py`, find the existing service imports. Add:
```python
from orchestrator.services.connection_manager import ConnectionManager
from orchestrator.services.alert_monitor import AlertMonitor
```

- [ ] **Step 2: Create module-level connection_manager instance**

In `orchestrator/main.py`, near the other module-level instances (search for `app = FastAPI`). After `app = FastAPI(...)`, add:
```python
connection_manager = ConnectionManager()
```

- [ ] **Step 3: Start AlertMonitor in lifespan**

In `orchestrator/main.py` inside `async def lifespan`, after the orchestrator initialization block (after `logger.info("Workflow orchestrator initialized")`), add:
```python
    # Start proactive alert monitor
    try:
        alert_monitor = AlertMonitor(
            sql_agent=orchestrator.sql_agent,
            connection_manager=connection_manager,
            redis_client=redis_manager.client,
        )
        asyncio.create_task(alert_monitor.run_forever())
        logger.info("AlertMonitor started")
    except Exception as _e:
        logger.warning(f"AlertMonitor not started: {_e}")
```

- [ ] **Step 4: Register/unregister WebSocket connections in /stream endpoint**

In `orchestrator/main.py`, find the `@app.websocket("/stream")` endpoint (around line 1808). Inside the handler, after `await websocket.accept()`, add:
```python
    connection_manager.register(websocket)
```

In the `except WebSocketDisconnect:` block and the outer `except Exception:` block, add before closing:
```python
        connection_manager.unregister(websocket)
```

Also add the unregister in the `finally` pattern — if there's no `finally`, add after the `except` blocks:
```python
    finally:
        connection_manager.unregister(websocket)
```
Remove the duplicate `register/unregister` calls added in the except blocks if you used `finally`.

- [ ] **Step 5: Run import and startup check**

```bash
python -c "from orchestrator.main import app; print('main imports OK')"
```
Expected: `main imports OK`

- [ ] **Step 6: Commit**

```bash
git add orchestrator/main.py
git commit -m "feat(alerts): wire AlertMonitor and ConnectionManager into FastAPI lifespan"
```

---

## Sprint 4: Maintenance Workflow Intent (18th Intent)

### Task 13: Create MaintenanceAgent

**Files:**
- Create: `orchestrator/agents/maintenance_agent.py`
- Create: `tests/test_maintenance_agent.py`

- [ ] **Step 1: Write failing tests**

Create `tests/test_maintenance_agent.py`:
```python
"""Tests for MaintenanceAgent — work-order CRUD and state machine."""
import re
import pytest
from unittest.mock import AsyncMock, MagicMock, patch

from orchestrator.agents.maintenance_agent import MaintenanceAgent, _detect_operation
from shared.models import ConversationState, Message


def _make_state(query: str, role: str = "occupant") -> ConversationState:
    state = ConversationState(
        conversation_id="maint-test",
        user_id="u1",
        user_message=query,
        messages=[Message(role="user", content=query)],
    )
    state.intermediate_results["intent"] = "maintenance"
    state.intermediate_results["user_role"] = role
    state.intermediate_results["user_id"] = "u1"
    state.intermediate_results["building_id"] = "bldg1"
    state.intermediate_results["entities"] = [
        {"type": "location", "value": "Room 4.02"},
        {"type": "fault_description", "value": "heating not working"},
    ]
    return state


class TestOperationDetection:
    def test_create_from_broken(self):
        assert _detect_operation("The heating in 4.02 is broken") == "CREATE"

    def test_create_from_not_working(self):
        assert _detect_operation("The lift is not working") == "CREATE"

    def test_status_from_check_ticket(self):
        assert _detect_operation("Check ticket MT-0042") == "STATUS"

    def test_status_from_mt_id(self):
        assert _detect_operation("What is the status of MT-0001?") == "STATUS"

    def test_list_from_open_tickets(self):
        assert _detect_operation("What open tickets exist?") == "LIST"

    def test_assign(self):
        assert _detect_operation("Assign MT-0042 to John") == "ASSIGN"

    def test_resolve(self):
        assert _detect_operation("Mark MT-0042 as resolved") == "RESOLVE"

    def test_close(self):
        assert _detect_operation("Close ticket MT-0042") == "CLOSE"


class TestTicketIdFormat:
    def test_id_matches_pattern(self):
        agent = MaintenanceAgent()
        ticket_id = agent._generate_ticket_id(42)
        assert re.match(r"^MT-\d{4}$", ticket_id), f"Bad format: {ticket_id}"
        assert ticket_id == "MT-0042"


class TestPermissions:
    @pytest.mark.asyncio
    async def test_occupant_can_create(self):
        agent = MaintenanceAgent()
        state = _make_state("The heating in room 4.02 is broken", role="occupant")
        with patch.object(agent, "_create_ticket", new=AsyncMock(return_value={
            "status": "created", "ticket_id": "MT-0001",
            "message": "🔧 Maintenance ticket created: MT-0001\nLocation: Room 4.02",
        })):
            result = await agent.handle(state)
        assert result["status"] == "created"

    @pytest.mark.asyncio
    async def test_occupant_cannot_assign(self):
        agent = MaintenanceAgent()
        state = _make_state("Assign MT-0042 to John", role="occupant")
        state.intermediate_results["entities"] = [{"type": "ticket_id", "value": "MT-0042"}]
        result = await agent.handle(state)
        assert result["status"] == "denied"
        assert "occupant" in result["message"].lower()

    @pytest.mark.asyncio
    async def test_facility_manager_can_assign(self):
        agent = MaintenanceAgent()
        state = _make_state("Assign MT-0042 to John", role="facility_manager")
        state.intermediate_results["entities"] = [
            {"type": "ticket_id", "value": "MT-0042"},
            {"type": "assignee", "value": "John"},
        ]
        with patch.object(agent, "_assign_ticket", new=AsyncMock(return_value={
            "status": "assigned", "ticket_id": "MT-0042",
            "message": "📋 MT-0042 assigned to John",
        })):
            result = await agent.handle(state)
        assert result["status"] == "assigned"
```

Run to confirm they fail:
```bash
pytest tests/test_maintenance_agent.py -v
```
Expected: `ModuleNotFoundError` for `orchestrator.agents.maintenance_agent`.

- [ ] **Step 2: Implement MaintenanceAgent**

Create `orchestrator/agents/maintenance_agent.py`:
```python
"""
MaintenanceAgent — conversational work-order CRUD with 5-state machine.

States: OPEN → ASSIGNED → IN_PROGRESS → RESOLVED → CLOSED
All DB operations are async stubs that return a result dict.
The actual DB writes are done by _maintenance_node in workflow.py using postgres_manager.
"""
import re
from typing import Any, Dict, Optional

from shared.models import ConversationState
from shared.utils import get_logger

logger = get_logger(__name__)

# Operation detection patterns (order matters — more specific first)
_OP_PATTERNS = [
    ("ASSIGN",  re.compile(r"\bassign\b", re.I)),
    ("RESOLVE", re.compile(r"\b(resolve|resolved|mark.*resolved)\b", re.I)),
    ("CLOSE",   re.compile(r"\bclose\b", re.I)),
    ("STATUS",  re.compile(r"\b(check|status|MT-\d{4})\b", re.I)),
    ("LIST",    re.compile(r"\b(list|show|what).*(open|all|ticket)", re.I)),
    ("CREATE",  re.compile(r"\b(broken|not working|fault|report|raise ticket|fix the|maintenance)\b", re.I)),
]

_ASSIGN_ROLES  = {"admin", "facility_manager"}
_RESOLVE_ROLES = {"admin", "facility_manager", "operator"}
_CLOSE_ROLES   = {"admin", "facility_manager"}


def _detect_operation(query: str) -> str:
    """Return the operation name for a user query."""
    for op, pattern in _OP_PATTERNS:
        if pattern.search(query):
            return op
    return "CREATE"


class MaintenanceAgent:
    """Handle maintenance ticket operations."""

    def _generate_ticket_id(self, counter: int) -> str:
        return f"MT-{counter:04d}"

    async def handle(self, state: ConversationState) -> Dict[str, Any]:
        """Route to the correct sub-operation based on query content."""
        query = state.user_message or ""
        operation = _detect_operation(query)
        role = state.intermediate_results.get("user_role", "readonly")

        if operation == "ASSIGN" and role not in _ASSIGN_ROLES:
            return self._denied(role, "assign tickets")
        if operation in ("RESOLVE",) and role not in _RESOLVE_ROLES:
            return self._denied(role, "resolve tickets")
        if operation == "CLOSE" and role not in _CLOSE_ROLES:
            return self._denied(role, "close tickets")

        if operation == "CREATE":
            return await self._create_ticket(state)
        elif operation == "STATUS":
            return await self._status_ticket(state)
        elif operation == "LIST":
            return await self._list_tickets(state)
        elif operation == "ASSIGN":
            return await self._assign_ticket(state)
        elif operation == "RESOLVE":
            return await self._resolve_ticket(state)
        elif operation == "CLOSE":
            return await self._close_ticket(state)
        return self._denied(role, "perform this operation")

    def _denied(self, role: str, action: str) -> Dict[str, Any]:
        return {
            "status": "denied",
            "message": (
                f"🔒 {role.replace('_', ' ').title()} role cannot {action}.\n"
                "Contact your facility manager if you need this access."
            ),
        }

    async def _create_ticket(self, state: ConversationState) -> Dict[str, Any]:
        entities = state.intermediate_results.get("entities", [])
        location = next((e["value"] for e in entities if e.get("type") == "location"), "Unknown")
        description = next(
            (e["value"] for e in entities if e.get("type") == "fault_description"),
            state.user_message,
        )
        building_id = state.intermediate_results.get("building_id", "unknown")
        user_id = state.intermediate_results.get("user_id", "unknown")
        return {
            "status": "created",
            "operation": "CREATE",
            "building_id": building_id,
            "location": location,
            "description": description,
            "reporter_id": user_id,
            "session_id": state.conversation_id,
        }

    async def _status_ticket(self, state: ConversationState) -> Dict[str, Any]:
        entities = state.intermediate_results.get("entities", [])
        ticket_id = next((e["value"] for e in entities if e.get("type") == "ticket_id"), None)
        query = state.user_message or ""
        if not ticket_id:
            m = re.search(r"MT-\d{4}", query, re.I)
            ticket_id = m.group(0).upper() if m else None
        return {"status": "lookup", "operation": "STATUS", "ticket_id": ticket_id}

    async def _list_tickets(self, state: ConversationState) -> Dict[str, Any]:
        building_id = state.intermediate_results.get("building_id", "unknown")
        return {"status": "list", "operation": "LIST", "building_id": building_id, "filter": "OPEN"}

    async def _assign_ticket(self, state: ConversationState) -> Dict[str, Any]:
        entities = state.intermediate_results.get("entities", [])
        ticket_id = next((e["value"] for e in entities if e.get("type") == "ticket_id"), None)
        assignee = next((e["value"] for e in entities if e.get("type") == "assignee"), None)
        return {"status": "assigned", "operation": "ASSIGN", "ticket_id": ticket_id, "assignee": assignee}

    async def _resolve_ticket(self, state: ConversationState) -> Dict[str, Any]:
        entities = state.intermediate_results.get("entities", [])
        ticket_id = next((e["value"] for e in entities if e.get("type") == "ticket_id"), None)
        query = state.user_message or ""
        if not ticket_id:
            m = re.search(r"MT-\d{4}", query, re.I)
            ticket_id = m.group(0).upper() if m else None
        return {"status": "resolved", "operation": "RESOLVE", "ticket_id": ticket_id}

    async def _close_ticket(self, state: ConversationState) -> Dict[str, Any]:
        entities = state.intermediate_results.get("entities", [])
        ticket_id = next((e["value"] for e in entities if e.get("type") == "ticket_id"), None)
        query = state.user_message or ""
        if not ticket_id:
            m = re.search(r"MT-\d{4}", query, re.I)
            ticket_id = m.group(0).upper() if m else None
        return {"status": "closed", "operation": "CLOSE", "ticket_id": ticket_id}
```

- [ ] **Step 3: Run tests**

```bash
pytest tests/test_maintenance_agent.py -v
```
Expected: all 11 tests pass.

- [ ] **Step 4: Commit**

```bash
git add orchestrator/agents/maintenance_agent.py tests/test_maintenance_agent.py
git commit -m "feat(maintenance): add MaintenanceAgent with 5-state machine and operation routing"
```

---

### Task 14: Wire maintenance intent into workflow

**Files:**
- Modify: `orchestrator/workflow.py` (4 locations)
- Modify: `orchestrator/agents/dialogue_agent.py`
- Modify: `orchestrator/main.py`

- [ ] **Step 1: Import MaintenanceAgent in workflow.py**

In `orchestrator/workflow.py` find the agent imports. Add:
```python
from orchestrator.agents.maintenance_agent import MaintenanceAgent
```

- [ ] **Step 2: Instantiate in WorkflowOrchestrator.__init__**

In `orchestrator/workflow.py` after `self.control_agent = ControlAgent()`:
```python
        self.maintenance_agent = MaintenanceAgent()
```

- [ ] **Step 3: Register node and edge in _build_graph**

In `orchestrator/workflow.py` inside `_build_graph`, after `workflow.add_node("control", ...)`:
```python
        workflow.add_node("maintenance", self._safe_node(self._maintenance_node, "maintenance"))
```

After `workflow.add_edge("control", "response")`:
```python
        workflow.add_edge("maintenance", "response")
```

The `add_conditional_edges` mapping was already updated in Task 8 Step 4 (we pre-added `"maintenance": "maintenance"` in that step) — verify it is there.

- [ ] **Step 4: Add routing branch in _route_from_dialogue**

In `orchestrator/workflow.py`, after the `elif intent == "control": return "control"` branch added in Task 8, add:
```python
        elif intent == "maintenance":
            return "maintenance"
```

- [ ] **Step 5: Implement _maintenance_node**

In `orchestrator/workflow.py`, after `_control_node`, add:
```python
    async def _maintenance_node(self, state: ConversationState) -> ConversationState:
        """Handle maintenance ticket CRUD operations."""
        logger.info(f"[maintenance_node] intent={state.intermediate_results.get('intent')}")
        try:
            result = await self.maintenance_agent.handle(state)
            state.intermediate_results["maintenance_result"] = result
            if self.postgres_manager and result.get("operation"):
                await self._execute_maintenance_db(result, state)
        except Exception as e:
            logger.error(f"[maintenance_node] Error: {e}", exc_info=True)
            state.intermediate_results["error"] = f"maintenance: {e}"
        return state

    async def _execute_maintenance_db(self, result: dict, state: ConversationState) -> None:
        """Persist maintenance ticket operation to PostgreSQL."""
        op = result.get("operation")
        try:
            async with self.postgres_manager.pool.acquire() as conn:
                if op == "CREATE":
                    counter = await conn.fetchval(
                        "SELECT COALESCE(MAX(CAST(SUBSTRING(id FROM 4) AS INTEGER)), 0) + 1 "
                        "FROM maintenance_tickets WHERE building_id = $1",
                        result.get("building_id"),
                    )
                    ticket_id = self.maintenance_agent._generate_ticket_id(counter)
                    await conn.execute(
                        """
                        INSERT INTO maintenance_tickets
                            (id, building_id, location, description, status, reporter_id, session_id)
                        VALUES ($1,$2,$3,$4,'OPEN',$5,$6)
                        """,
                        ticket_id,
                        result.get("building_id"),
                        result.get("location"),
                        result.get("description"),
                        result.get("reporter_id"),
                        result.get("session_id"),
                    )
                    result["ticket_id"] = ticket_id
                    result["message"] = (
                        f"🔧 Maintenance ticket created: {ticket_id}\n"
                        f"Location: {result.get('location')}\n"
                        f"Issue: {result.get('description')}\n"
                        f"Status: OPEN\n\n"
                        f"Use \"Check ticket {ticket_id}\" to follow up."
                    )
                elif op == "STATUS":
                    row = await conn.fetchrow(
                        "SELECT * FROM maintenance_tickets WHERE id = $1",
                        result.get("ticket_id"),
                    )
                    if row:
                        result["message"] = (
                            f"📋 Ticket {row['id']}\n"
                            f"Location: {row['location']}\n"
                            f"Status: {row['status']}\n"
                            f"Assignee: {row['assignee'] or 'unassigned'}\n"
                            f"Last updated: {row['updated_at']}"
                        )
                    else:
                        result["message"] = f"Ticket {result.get('ticket_id')} not found."
                elif op == "LIST":
                    rows = await conn.fetch(
                        "SELECT id, location, description, status FROM maintenance_tickets "
                        "WHERE building_id = $1 AND status = $2 LIMIT 10",
                        result.get("building_id"), result.get("filter", "OPEN"),
                    )
                    if rows:
                        lines = [f"📋 Open tickets ({len(rows)}):"]
                        for r in rows:
                            lines.append(f"• {r['id']}: {r['location']} — {r['description'][:60]}")
                        result["message"] = "\n".join(lines)
                    else:
                        result["message"] = "No open tickets found."
                elif op == "ASSIGN":
                    await conn.execute(
                        "UPDATE maintenance_tickets SET assignee=$1, status='ASSIGNED', "
                        "updated_at=NOW() WHERE id=$2",
                        result.get("assignee"), result.get("ticket_id"),
                    )
                    result["message"] = f"✅ Ticket {result.get('ticket_id')} assigned to {result.get('assignee')}."
                elif op in ("RESOLVE", "CLOSE"):
                    new_status = "RESOLVED" if op == "RESOLVE" else "CLOSED"
                    await conn.execute(
                        "UPDATE maintenance_tickets SET status=$1, updated_at=NOW() WHERE id=$2",
                        new_status, result.get("ticket_id"),
                    )
                    result["message"] = f"✅ Ticket {result.get('ticket_id')} marked as {new_status}."
        except Exception as e:
            logger.warning(f"[maintenance_node] DB operation failed: {e}")
            if "message" not in result:
                result["message"] = f"Operation completed but could not update database: {e}"
```

- [ ] **Step 6: Add `maintenance` to INTENT_DEFINITIONS in dialogue_agent.py**

In `orchestrator/agents/dialogue_agent.py`, after the `"control"` entry added in Task 8, add:
```
   - "maintenance"   : User reports a fault, raises a work order, checks ticket status,
                       or updates a maintenance ticket.
                       Trigger phrases: "broken", "not working", "report fault", "raise ticket",
                       "fix the", "maintenance request", "check ticket", "status of MT-".
                       Entities: device, location, fault_description, ticket_id (format MT-XXXX),
                       assignee.
```

- [ ] **Step 7: Create maintenance_tickets table in lifespan**

In `orchestrator/main.py`, after the `control_log` DDL added in Task 8 Step 9, add:
```python
    # Create maintenance_tickets table if not exists
    try:
        async with postgres_manager.pool.acquire() as _conn:
            await _conn.execute("""
                CREATE TABLE IF NOT EXISTS maintenance_tickets (
                    id          VARCHAR(12)  PRIMARY KEY,
                    building_id VARCHAR(64)  NOT NULL,
                    location    VARCHAR(256),
                    device      VARCHAR(256),
                    description TEXT         NOT NULL,
                    status      VARCHAR(32)  DEFAULT 'OPEN',
                    reporter_id VARCHAR(256),
                    assignee    VARCHAR(256),
                    created_at  TIMESTAMPTZ  DEFAULT NOW(),
                    updated_at  TIMESTAMPTZ  DEFAULT NOW(),
                    session_id  VARCHAR(256)
                )
            """)
        logger.info("maintenance_tickets table ready")
    except Exception as _e:
        logger.warning(f"maintenance_tickets table creation skipped: {_e}")
```

- [ ] **Step 8: Add routing test for maintenance**

Add to `tests/test_routing_and_contracts.py` inside `class TestIntentRouting`:
```python
def test_maintenance_routes_to_maintenance(self):
    assert self._route("maintenance") == "maintenance"
```

Run:
```bash
pytest tests/test_routing_and_contracts.py::TestIntentRouting::test_maintenance_routes_to_maintenance -v
```
Expected: `PASSED`

- [ ] **Step 9: Run full test suite**

```bash
pytest tests/ --tb=no -q 2>&1 | tail -5
```
Expected: ≥ 320 passing, 0 new failures compared to Sprint 1 baseline.

- [ ] **Step 10: Commit**

```bash
git add orchestrator/workflow.py orchestrator/agents/dialogue_agent.py orchestrator/main.py tests/test_routing_and_contracts.py
git commit -m "feat(maintenance): wire maintenance intent — node, routing, DB table, dialogue"
```

---

## Final Verification

- [ ] **Run full suite**

```bash
pytest tests/ -v --tb=short 2>&1 | tail -20
```
Expected summary: ≥ 320 passed.

- [ ] **Verify all 4 sprint deliverables**

```bash
# Sprint 1: all 3 routing fixes
pytest tests/test_routing_and_contracts.py::TestIntentRouting -v

# Sprint 2: control agent
pytest tests/test_control_agent.py -v

# Sprint 3: alert monitor
pytest tests/test_alert_monitor.py -v

# Sprint 4: maintenance agent + routing
pytest tests/test_maintenance_agent.py tests/test_routing_and_contracts.py::TestIntentRouting::test_maintenance_routes_to_maintenance -v
```
Expected: all green.

- [ ] **Final commit**

```bash
git add docs/superpowers/plans/2026-05-16-ontosage-all-in-one-hbi.md
git commit -m "docs: add OntoSage all-in-one HBI implementation plan"
```
