# OntoSage — All-In-One Human-Building Interaction (HBI) Design

**Date:** 2026-05-16
**Author:** Suhas Devmane (via Claude Code brainstorm)
**Version:** 1.0
**Status:** Approved — ready for implementation planning

---

## 1. Executive Summary

This document specifies four sequential sprints that transform OntoSage from a 16-intent query platform into a fully bidirectional, all-in-one Human-Building Interaction (HBI) system. The additions are:

| Sprint | Deliverable | New intents |
|--------|-------------|-------------|
| S1 | Test stabilization — fix routing bugs, repair mocks | 0 |
| S2 | Device control with RBAC gate | 1 (`control`) |
| S3 | Proactive alert service — building speaks first | 0 (new background service) |
| S4 | Maintenance/work-order workflow | 1 (`maintenance`) |

After all four sprints, OntoSage supports **18 intent types** and the full HBI spectrum: query → command → alert → maintenance.

---

## 2. Design Principles

- **Fix before extend**: Sprint 1 stabilizes the test foundation. Sprints 2–4 add net-new capability on a green baseline.
- **RBAC everywhere**: Control and maintenance commands require explicit role permissions. No safety shortcuts.
- **In-app alerts only**: Proactive notifications are injected as WebUI system messages. No external webhook dependencies in this phase.
- **Simulate by default**: Device control works without a real BMS — `BMS_ENDPOINT` unset → simulation mode with full audit log.
- **State machine for maintenance**: Work-orders follow `OPEN → ASSIGNED → IN_PROGRESS → RESOLVED → CLOSED`. State transitions are the only valid mutations.

---

## 3. Sprint 1 — Test Stabilization

### 3.1 Goal

Raise passing tests from 229 to ≥ 300 (out of 337) by fixing pure-logic bugs that require no running infrastructure.

### 3.2 Routing Bugs (workflow.py)

Three confirmed bugs in `orchestrator/workflow.py`:

| Bug | File:line | Current behavior | Required behavior |
|-----|-----------|-----------------|-------------------|
| `report` misrouted | `workflow.py:~1565` | `return "sparql"` | `return "planner"` |
| `visualization` misrouted | `workflow.py:~1586` | `return "sparql"` | `return "visualization"` |
| HVAC template text | `agents/sparql_agent.py` | Template output has no "HVAC" string | Add `BIND("HVAC Equipment" AS ?category)` or similar |

**Fix for `_route_from_dialogue`:**
```python
elif intent == "report":
    return "planner"          # was: "sparql"

elif intent == "visualization":
    return "visualization"    # was: routed through sparql/sql chain
```

### 3.3 Test Mock Fixes

- `tests/test_floor_plan_e2e.py` — 4 errors: `FloorPlanAgent` mock setup uses incorrect fixture path. Fix by patching `FloorPlanPipeline.ingest_file` to return a synthetic manifest fixture.
- `tests/test_floor_plan_pipeline.py::TestPydanticModels::test_floor_plan_manifest_schema_version` — Assert `schema_version == "1.0"` but PDF-only manifests are now versioned differently. Update assertion to accept either `"1.0"` or `"2.0"`.
- `tests/test_routing_and_contracts.py::TestSPARQLTemplateCoverage::test_template_hvac_listing` — see §3.2.

### 3.4 Success Criteria

- `pytest tests/test_routing_and_contracts.py` — all 79 tests pass (currently 76/79)
- Total suite: ≥ 300 passing (currently 229)
- No new failures introduced

---

## 4. Sprint 2 — Control Intent (17th Intent)

### 4.1 New Intent: `control`

Added to `INTENT_DEFINITIONS` in `orchestrator/agents/dialogue_agent.py`:

```
- "control" : User issues a command to physically change a building system state.
              e.g. "Set HVAC zone 3 to 21°C", "Turn off the lights in room 2.04",
              "Lock down floor 4", "Increase ventilation in Lab 3.07".
              Entities: device, action (set/on/off/lock/unlock/increase/decrease),
              target_value (e.g. "21°C", "50%"), zone/room.
```

### 4.2 New RBAC Permission

In `orchestrator/middleware/rbac.py`:

```python
# New permission added to ROLE_PERMISSIONS:
"device:control"

# Granted to roles:
ROLE_PERMISSIONS = {
    "admin":              [..., "device:control"],
    "facility_manager":   [..., "device:control"],
    "operator":           [..., "device:control"],
    "analyst":            [...],           # no control
    "occupant":           [...],           # no control
    "readonly":           [...],           # no control
}
```

### 4.3 New LangGraph Node

In `orchestrator/workflow.py`:

```python
# _build_graph():
workflow.add_node("control", self._safe_node(self._control_node, "control"))
workflow.add_edge("control", "response")

# _route_from_dialogue():
elif intent == "control":
    return "control"
```

### 4.4 ControlAgent

New file: `orchestrator/agents/control_agent.py`

```python
class ControlAgent:
    async def execute_command(self, state: ConversationState) -> Dict[str, Any]:
        """Execute RBAC-gated building system command."""
        # 1. Extract device/action/value from state.intermediate_results["entities"]
        # 2. Check user has "device:control" permission (raise PermissionError if not)
        # 3. Call BMSAdapter.send_command(device, action, value)
        # 4. Write to control_log table
        # 5. Return structured result
```

### 4.5 BMSAdapter

New file: `orchestrator/services/bms_adapter.py`

```python
class BMSAdapter:
    def __init__(self):
        self.endpoint = settings.BMS_ENDPOINT  # None → simulation mode

    async def send_command(self, device, action, value) -> Dict:
        if not self.endpoint:
            # Simulation mode
            logger.info(f"[BMS SIMULATE] {device} → {action}({value})")
            return {"status": "simulated", "device": device, "action": action, "value": value}
        # Real BMS call (HTTP POST to self.endpoint)
        ...
```

### 4.6 control_log Table (PostgreSQL)

```sql
CREATE TABLE IF NOT EXISTS control_log (
    id          SERIAL PRIMARY KEY,
    timestamp   TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    building_id VARCHAR(64),
    device      VARCHAR(256),
    action      VARCHAR(64),
    target_value VARCHAR(128),
    status      VARCHAR(32),   -- 'executed', 'simulated', 'denied', 'failed'
    user_id     VARCHAR(256),
    role        VARCHAR(64),
    session_id  VARCHAR(256)
);
```

### 4.7 Response Format

```
✅ Command executed: HVAC Zone 3 → 21°C
Mode: simulation (BMS endpoint not configured)
Logged at: 2026-05-16 15:30:00 UTC
Reference: control-log-00142
```

If user lacks `device:control`:
```
🔒 You don't have permission to control building systems.
Your current role (analyst) does not include device control.
Contact your facility manager if you need this access.
```

### 4.8 New env var

```
BMS_ENDPOINT=         # empty = simulation mode
BMS_ENDPOINT=http://bms.internal/api/v1/command  # real actuation
```

### 4.9 Tests

Add to `tests/test_routing_and_contracts.py`:
```python
def test_control_routes_to_control():
    assert self._route("control") == "control"
```

Add `tests/test_control_agent.py`:
- Test permission denied for `analyst` role
- Test simulation mode executes and logs correctly
- Test control_log table schema

---

## 5. Sprint 3 — Proactive Alert Service

### 5.1 Goal

The building initiates conversations. No user query required. Critical sensor threshold breaches trigger system messages injected into active WebUI sessions.

### 5.2 Architecture

```
main.py:lifespan → asyncio.create_task(alert_monitor.run_forever())
                           ↓
                   AlertMonitor.poll()  ← every 60s (ALERT_POLL_INTERVAL_SECS)
                           ↓
                   SQLAgent.fetch_latest_readings()
                           ↓
                   ThresholdEvaluator.check()
                           ↓
                   Redis dedup check (alert:{sensor_id}:{threshold}, TTL=10min)
                           ↓
                   ConnectionManager.broadcast_alert(message)
                           ↓
                   WebSocket → Open WebUI chat
```

### 5.3 New file: `orchestrator/services/alert_monitor.py`

```python
class AlertMonitor:
    def __init__(self, sql_agent, connection_manager, redis_client):
        self.sql_agent = sql_agent
        self.conn_mgr = connection_manager
        self.redis = redis_client
        self.interval = settings.ALERT_POLL_INTERVAL_SECS  # default: 60

    async def run_forever(self):
        while True:
            try:
                await self.poll()
            except Exception as e:
                logger.error(f"[AlertMonitor] Poll failed: {e}", exc_info=True)
            await asyncio.sleep(self.interval)

    async def poll(self):
        thresholds = self._load_thresholds()
        for rule in thresholds:
            readings = await self.sql_agent.fetch_latest(rule["sensor_type"])
            for sensor_id, value, zone in readings:
                if self._breached(value, rule):
                    await self._maybe_fire(sensor_id, value, zone, rule)

    async def _maybe_fire(self, sensor_id, value, zone, rule):
        key = f"alert:{sensor_id}:{rule['threshold']}"
        if await self.redis.get(key):
            return  # dedup: already fired within TTL
        await self.redis.setex(key, 600, "1")
        message = rule["message"].format(zone=zone, value=value)
        await self.conn_mgr.broadcast_alert(severity=rule["severity"], message=message)
```

### 5.4 Threshold Configuration

New file: `/app/config/alert_thresholds.yaml`

```yaml
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
```

### 5.5 Alert Message Format (WebUI)

```
🚨 [SYSTEM ALERT — 15:31:02 UTC]
CO₂ in Lab 3.07 is 1,247 ppm — above safe limit (1,000 ppm).
Consider increasing ventilation.

You can ask:
• "Show me CO₂ trend in Lab 3.07 this week"
• "Export CO₂ data for Lab 3.07"
• "Recommend ventilation settings for Lab 3.07"
```

### 5.6 New env var

```
ALERT_POLL_INTERVAL_SECS=60   # default
ALERT_THRESHOLDS_PATH=/app/config/alert_thresholds.yaml
```

### 5.7 Tests

Add `tests/test_alert_monitor.py`:
- Test dedup: second breach within TTL window → no broadcast
- Test dedup expiry: after TTL, breach fires again
- Test threshold evaluation for each comparator (`>`, `<`, `>=`)
- Test broadcast injects correct severity and message

---

## 6. Sprint 4 — Maintenance Workflow Intent (18th Intent)

### 6.1 New Intent: `maintenance`

Added to `INTENT_DEFINITIONS`:

```
- "maintenance" : User reports a fault, raises a work order, checks ticket status,
                  or updates a maintenance ticket.
                  Trigger phrases: "broken", "not working", "report fault", "raise ticket",
                  "fix the", "maintenance request", "check ticket", "status of MT-".
                  Entities: device, location, fault_description, ticket_id.
```

### 6.2 State Machine

```
OPEN → ASSIGNED → IN_PROGRESS → RESOLVED → CLOSED
```

Valid transitions:
- `OPEN` → `ASSIGNED` (requires `facility_manager`+)
- `ASSIGNED` → `IN_PROGRESS` (requires `operator`+)
- `IN_PROGRESS` → `RESOLVED` (requires `operator`+)
- `RESOLVED` → `CLOSED` (requires `facility_manager`+)
- Any state → re-opened as `OPEN` (requires `facility_manager`+)

### 6.3 maintenance_tickets Table (PostgreSQL)

```sql
CREATE TABLE IF NOT EXISTS maintenance_tickets (
    id           VARCHAR(12) PRIMARY KEY,   -- MT-0001 format
    building_id  VARCHAR(64) NOT NULL,
    location     VARCHAR(256),
    device       VARCHAR(256),
    description  TEXT NOT NULL,
    status       VARCHAR(32) DEFAULT 'OPEN',
    reporter_id  VARCHAR(256),
    assignee     VARCHAR(256),
    created_at   TIMESTAMPTZ DEFAULT NOW(),
    updated_at   TIMESTAMPTZ DEFAULT NOW(),
    session_id   VARCHAR(256)
);
```

### 6.4 New LangGraph Node

```python
# _build_graph():
workflow.add_node("maintenance", self._safe_node(self._maintenance_node, "maintenance"))
workflow.add_edge("maintenance", "response")

# _route_from_dialogue():
elif intent == "maintenance":
    return "maintenance"
```

### 6.5 Conversational Operations

| User message | Sub-operation | Permission |
|---|---|---|
| "The heating in 4.02 is broken" | `CREATE` | all roles |
| "Check ticket MT-0042" | `STATUS` | all roles |
| "What open tickets exist?" | `LIST` | all roles |
| "Assign MT-0042 to John" | `ASSIGN` | facility_manager+ |
| "Mark MT-0042 as resolved" | `RESOLVE` | operator+ |
| "Close ticket MT-0042" | `CLOSE` | facility_manager+ |

### 6.6 Ticket ID Format

Auto-generated: `MT-{4-digit zero-padded sequence}`. Stored in Redis counter `maintenance:ticket_counter:{building_id}`.

### 6.7 Response Examples

**Create:**
```
🔧 Maintenance ticket created: MT-0043
Location: Room 4.02
Issue: Heating not working
Status: OPEN
Created: 2026-05-16 15:42:00 UTC

Use "Check ticket MT-0043" to follow up.
```

**Status check:**
```
📋 Ticket MT-0042
Location: Lab 3.07 — Ventilation fan
Status: IN_PROGRESS
Assignee: John Smith
Last updated: 2026-05-16 14:30 UTC
```

**Permission denied:**
```
🔒 Assigning tickets requires facility_manager role or above.
Your current role (occupant) cannot perform this action.
```

### 6.8 Tests

Add `tests/test_maintenance_agent.py`:
- Test ticket creation returns MT-XXXX format ID
- Test status query returns correct fields
- Test state transition permission enforcement
- Test list returns only tickets for correct building
- Test routing: `_route_from_dialogue("maintenance") == "maintenance"`

---

## 7. Updated Intent Table (post all sprints)

| # | Intent | Route | Description |
|---|--------|-------|-------------|
| 1 | `sensor_data` | sparql → sql → response | Current/historical sensor readings |
| 2 | `analytics` | sparql → sql → analytics → response | Statistical analysis |
| 3 | `discovery` | sparql → response | Explore sensors/zones/devices |
| 4 | `report` | sparql → sql → **planner** → response | *(fixed)* Structured building report |
| 5 | `anomaly` | sparql → sql → anomaly → response | Out-of-range detection |
| 6 | `comparison` | sparql → sql → analytics → response | Compare zones/periods |
| 7 | `export` | sparql → sql → export → response | Download CSV/JSON/HTML |
| 8 | `recommend` | sparql → sql → response | HVAC/energy recommendations |
| 9 | `planner` | planner → response | Multi-step orchestration |
| 10 | `forecast` | sparql → sql → analytics → response | Future predictions |
| 11 | `floor_plan` | floor_plan → response | Show floor map, locate room |
| 12 | `spatial_query` | spatial_query → response | Area, adjacency, counts |
| 13 | `compliance` | sparql → sql → response | Standards checking |
| 14 | `general` | response | Greetings / non-building |
| 15 | `clarification` | response | Query too vague |
| 16 | `visualization` | **visualization** → response | *(fixed)* Direct chart generation |
| **17** | **`control`** | **control → response** | **Device commands (RBAC-gated)** |
| **18** | **`maintenance`** | **maintenance → response** | **Work-order workflows** |

*(Proactive alerts are not an intent — they are a background-service event)*

---

## 8. New Files Created

| File | Purpose |
|------|---------|
| `orchestrator/agents/control_agent.py` | RBAC-gated device control |
| `orchestrator/services/bms_adapter.py` | BMS HTTP stub + simulation mode |
| `orchestrator/services/alert_monitor.py` | Background threshold polling |
| `orchestrator/agents/maintenance_agent.py` | Work-order CRUD + state machine |
| `/app/config/alert_thresholds.yaml` | Threshold configuration |
| `tests/test_control_agent.py` | Control intent tests |
| `tests/test_alert_monitor.py` | Alert service tests |
| `tests/test_maintenance_agent.py` | Maintenance workflow tests |

---

## 9. Modified Files

| File | Change |
|------|--------|
| `orchestrator/workflow.py` | Fix `report`/`visualization` routing; add `control`/`maintenance` nodes+edges |
| `orchestrator/agents/dialogue_agent.py` | Add `control`/`maintenance` to `INTENT_DEFINITIONS` |
| `orchestrator/middleware/rbac.py` | Add `device:control` permission |
| `orchestrator/main.py` | Start `AlertMonitor` in lifespan; add `control_log` migration |
| `shared/config.py` | Add `BMS_ENDPOINT`, `ALERT_POLL_INTERVAL_SECS`, `ALERT_THRESHOLDS_PATH` |
| `docker-compose.yml` | Add new env vars |
| `tests/test_routing_and_contracts.py` | Fix 3 failing assertions; add `control`/`maintenance` routing tests |
| `tests/test_floor_plan_e2e.py` | Fix 4 mock setup errors |

---

## 10. Non-Goals (Out of Scope)

- Voice/speech (Whisper STT integration) — deferred to future sprint
- External webhook delivery (Slack/Teams/email alerts) — deferred
- Real BMS integration (device-specific API) — BMS_ENDPOINT stub is the boundary
- Mobile app / PWA — existing WebUI is the delivery surface
- Multi-tenant alert routing (per-user alert preferences) — deferred

---

## 11. Definition of Done

- Sprint 1: `pytest tests/` ≥ 300 passing; all 3 routing bugs fixed; no regressions
- Sprint 2: `pytest tests/test_control_agent.py` all green; `_route("control") == "control"` passes
- Sprint 3: `pytest tests/test_alert_monitor.py` all green; AlertMonitor starts without error in docker-compose
- Sprint 4: `pytest tests/test_maintenance_agent.py` all green; `_route("maintenance") == "maintenance"` passes
- Full suite ≥ 320 passing after all sprints
