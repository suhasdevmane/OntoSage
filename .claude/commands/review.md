---
description: Full OntoSage system review — Docker health, intent routing matrix, persona testing, cache validation, pytest suite
argument-hint: [scope] e.g. "full", "routing", "personas", "cache", "pytest"
---

Run a structured system review of the live OntoSage stack. Scope: $ARGUMENTS (default: full).

## Phase 1 — Stack Health

Verify all services are up before testing anything. A failing service produces misleading test results.

```bash
docker-compose ps --format "table {{.Name}}\t{{.Status}}\t{{.Ports}}"
```

Then probe each health endpoint:
```bash
curl -sf http://localhost:8000/health | python -m json.tool   # Orchestrator
curl -sf http://localhost:8001/health | python -m json.tool   # RAG Service
curl -sf http://localhost:8002/health | python -m json.tool   # Code Executor
curl -sf http://localhost:7200/rest/repositories              # GraphDB
```

Check Redis:
```bash
docker exec redis-memory-store redis-cli ping
docker exec redis-memory-store redis-cli info keyspace
```

**Report**: Each service — HEALTHY / DEGRADED / DOWN. Do not proceed to Phase 2 if Orchestrator, GraphDB, or Redis is DOWN.

## Phase 2 — pytest Suite

```bash
pytest tests/ -v --tb=short -q 2>&1 | tail -30
pytest tests/ --cov=orchestrator --cov=shared --cov-report=term-missing 2>&1 | grep -E "TOTAL|FAILED|ERROR"
```

Report:
- Total: X pass / Y fail / Z skip
- Coverage: overall % and any module below 60%
- List every FAILED test with the first error line

If any test fails that was passing before this session's changes, treat it as a regression and stop — do not continue to live tests.

## Phase 3 — Intent Routing Matrix

Test every intent type against the live orchestrator. Use a unique session_id per call to avoid Redis contamination.

For each row, POST to `http://localhost:8000/chat` with a unique `session_id` and verify the response content matches the expected route.

| Intent | Test Query | Expected Route | Pass/Fail |
|--------|-----------|----------------|-----------|
| `sensor_data` | "What is the current CO2 level in zone 3?" | sparql → sql → response | |
| `analytics` | "Show average temperature trend for floor 2 last week" | sparql → sql → analytics → response | |
| `discovery` | "What sensor types are installed in this building?" | sparql → response | |
| `report` | "Generate an energy report for last month" | sparql → sql → report → response | |
| `anomaly` | "Were there any temperature spikes in the last 24 hours?" | sparql → sql → anomaly → response | |
| `comparison` | "Compare CO2 levels between floor 1 and floor 3" | sparql → sql → analytics → response | |
| `export` | "Export sensor data for zone 5 as CSV" | sparql → sql → export → response | |
| `forecast` | "Predict temperature for tomorrow afternoon" | sparql → sql → analytics → response | |
| `floor_plan` | "Show me floor 3 layout" | floor_plan → response | |
| `spatial_query` | "How many rooms are on floor 2?" | spatial_query → response | |
| `maintenance` | "Log a maintenance request for the HVAC on floor 4" | maintenance → response | |
| `capability` | "Does this building have fire evacuation procedures?" | capability → response | |
| `general` | "Hello, what can you help me with?" | response (general) | |
| `control` | "Turn off the lights in room 3.01" | response (control not supported) | |
| `clarification` | "It" | response (clarification) | |
| `alert` | "Alert me if CO2 exceeds 1000 ppm in any zone" | sparql → sql → anomaly → response | |

**Critical edge cases — routing hijack tests:**

These queries must NOT route to floor_plan:
- "What is the temperature on floor 3?" → must route sparql/sensor_data
- "Show me analytics for floor 2 sensors" → must route analytics
- "How many CO2 sensors are on floor 1?" → must route sparql/discovery
- "Compare energy usage on floor 1 vs floor 3" → must route comparison/analytics

Report each as PASS (correct route) or FAIL (wrong route, actual route shown).

**Score: X/20 passed**

## Phase 4 — Capability KB Coverage

Test each KB category with a question that should return KB content (not a generic "I don't know" or sensor data response).

For each, look for KB-specific language in the response (not just the query being echoed back):

| Category | Test Query | Pass/Fail | Response excerpt |
|----------|-----------|-----------|-----------------|
| Fire safety | "What are the fire evacuation procedures?" | | |
| Power outage | "What happens if there's a power outage?" | | |
| Access control | "How do I access the building after hours?" | | |
| Parking | "Where can I park near the building?" | | |
| Printing | "How do I print from my laptop?" | | |
| Wellbeing | "Is there a prayer room in the building?" | | |
| Data privacy | "Does the building track my location?" | | |
| Building contact | "Who manages this building?" | | |
| Visitor policy | "Can I bring a guest to the building?" | | |
| Thermal comfort | "The office is too cold — who do I contact?" | | |
| WiFi | "How do I connect to WiFi?" | | |
| Sustainability | "What green certifications does this building have?" | | |

**Score: X/12 passed**

## Phase 5 — Persona × Intent Spot-Check

Test 5 key persona/intent combinations. Use unique session IDs. The persona context comes from the system's persona detection — send queries that naturally identify the persona's role.

| Persona | Query | Expected intent | Pass/Fail |
|---------|-------|-----------------|-----------|
| facility_manager | "Show me a maintenance report for HVAC systems this week" | report/analytics | |
| energy_manager | "What is the energy consumption trend for floor 2?" | analytics | |
| occupant | "Is there a quiet room available on floor 3?" | capability | |
| safety_officer | "What are the fire evacuation assembly points?" | capability | |
| analyst | "Run a statistical analysis of CO2 sensor variance by floor" | analytics | |

For each: confirm the response is relevant to the persona's domain (not a generic error).

**Score: X/5 passed**

## Phase 6 — Cache Behavior Validation

**6a. Intent cache hit with capability override**
Send this query twice with the same content but different session IDs:
```
Query: "Does the building have fire evacuation procedures?"
```
First call: should classify as `capability` (cold cache).
Second call: should also return `capability` — verify the cache-hit override is working.

Check Redis to confirm cache was populated:
```bash
docker exec redis-memory-store redis-cli keys "cache:intent:*" | head -5
```

**6b. Floor plan heuristic not stealing data queries (cached)**
1. Send "What is the temperature on floor 3?" — verify routes to sparql (cold)
2. Send the same query again — verify cached result also routes to sparql (not floor_plan)

**6c. Response cache TTL check**
```bash
docker exec redis-memory-store redis-cli keys "cache:response:*" | wc -l
docker exec redis-memory-store redis-cli ttl "$(docker exec redis-memory-store redis-cli keys 'cache:response:*' | head -1)"
```
TTL should be > 0 (not persistent) and < 3600 seconds.

Report each as PASS/FAIL with evidence.

## Phase 7 — Edge Cases

Test these known problematic patterns:

| Test | Query | Expected behaviour | Pass/Fail |
|------|-------|-------------------|-----------|
| Empty query | "" (empty string) | Clarification response, no crash | |
| Multi-floor ambiguous | "Compare floor 1 and floor 3 temperatures" | analytics (not floor_plan) | |
| Sensor + floor | "CO2 readings floor 2 last hour" | sensor_data (not floor_plan) | |
| Unknown building | Query with `building_id: "bldg99"` | Graceful error, not 500 | |
| Very long query | 500-character query | Handled, not 422 | |
| SQL injection attempt | `"'; DROP TABLE sensors; --"` | Treated as natural language, no DB error | |
| Non-English query | "Quelle est la température au 3ème étage?" | Responds in English or detects clarification | |

**Score: X/7 passed**

## Phase 8 — Performance Spot-Check

Time these requests (target: < 5s for sensor queries, < 10s for analytics):

```bash
time curl -s -X POST http://localhost:8000/chat \
  -H "Content-Type: application/json" \
  -d '{"message":"What is the current temperature in zone 3?","session_id":"perf-test-1","building_id":"bldg1"}'
```

Run 3 queries and report:
- Cold cache latency (first request)
- Warm cache latency (same request, cached)
- Analytics query latency (trend/analysis query)

Flag anything over 15s as a performance issue.

## Final Report

```
SYSTEM REVIEW REPORT — OntoSage
Date: [date]
Stack: [all services health summary]

pytest:           X pass / Y fail / Z skip — [PASS/FAIL]
Intent routing:   X/20 — [PASS/FAIL]
Capability KB:    X/12 — [PASS/FAIL]
Persona matrix:   X/5  — [PASS/FAIL]
Cache behaviour:  X/3  — [PASS/FAIL]
Edge cases:       X/7  — [PASS/FAIL]

OVERALL: X/47 checks passed

REGRESSIONS FOUND:
- [list or "none"]

CRITICAL FAILURES (production risk):
- [list or "none"]

RECOMMENDED ACTIONS:
1. [highest priority fix]
2. [next]
```

Do not hedge the verdict. If routing is broken, say routing is broken. If all checks pass, say the system is healthy. A vague summary wastes the engineer's time.
