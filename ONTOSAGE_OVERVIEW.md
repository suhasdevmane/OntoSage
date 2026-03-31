# OntoSage: Coverage and System Overview

> Agentic AI framework for smart buildings — answers any question from any user, produces any output format, powered by your TTL ontology and sensor databases.

---

## 1. The Entry Point: Understanding Who Is Asking

Before any query is processed, the system resolves two things: who is asking, and how should the answer be framed.

### Persona Mapping

| User Type | Assigned Persona | What They Get |
|---|---|---|
| Building guest checking comfort | `occupant` | Plain English, no jargon |
| Facilities manager checking HVAC | `facility_manager` | Technical KPIs, zone-level detail |
| Executive reviewing energy spend | `executive` | Headline numbers, trend narrative |
| PhD researcher analyzing CO₂ | `researcher` | Full statistics, confidence intervals |
| Sustainability officer | `sustainability_officer` | Standards compliance, carbon context |
| IT admin checking system state | `it_admin` | Sensor UUIDs, connection status |

The persona is set by the client or derived from the RBAC role. Every answer is rewritten through that persona's voice via `dialogue_agent.py:format_response()` — the underlying data is identical; the framing is completely different.

**No domain knowledge required.** All 14 intents handle natural language input. The LLM classifier maps "Is the air ok?" to `compliance` intent and "show me 5bc3... readings" to `analytics` intent automatically.

---

## 2. The Knowledge Sources: Your TTL File and Databases

Everything the system knows comes from two layers you have already configured.

### Layer A — The Ontology (`.ttl` file → GraphDB)

```
bldg1_protege.ttl  (9,184 triples)
    ├── Building topology    →  floor / zone / room hierarchy
    ├── Sensor instances     →  UUID, type, location, unit
    ├── Equipment            →  HVAC, AHU, VAV boxes
    ├── Systems              →  Electrical, Water, HVAC
    ├── ref:storedAt         →  which database holds each sensor's data
    └── Relationships        →  "sensor X measures zone Y on floor Z"
```

The SPARQL agent generates queries against this graph. When a user asks "what temperature sensors are on floor 2?" it:

1. Generates SPARQL targeting `brick:Temperature_Sensor` with a location filter
2. Receives sensor URIs, UUIDs, and their storage location
3. Passes those UUIDs downstream to the SQL agent

You never maintain a sensor catalog separately — the TTL file **is** the catalog.

### Layer B — The Time-Series Databases

The `ref:storedAt` property in the TTL maps each sensor UUID to a database. The adapter registry reads this at startup:

```
sensor UUID abc-123  →  ref:storedAt bldg:database1  →  MySQLAdapter     (port 3306)
sensor UUID def-456  →  ref:storedAt bldg:database2  →  PostgreSQLAdapter (port 5433)
```

When you onboard a second building with a different database backend, you update the TTL — routing is automatic. No code changes required.

---

## 3. The Pipeline: How a Question Becomes an Answer

Every query flows through the same LangGraph state machine regardless of complexity:

```
User Question
    ↓
[Dialogue Agent]  ← RAG context + Agent Memory + Few-shot library
    │               → classifies into 1 of 14 intents
    │               → extracts entities, time range, analytics ops
    ↓
[Routing]
    ├── "what sensors exist?"           → SPARQL → Response
    ├── "current temperature zone 3"    → SPARQL → SQL → Analytics → Response
    ├── "plot CO₂ last 7 days"          → SPARQL → SQL → Analytics → Visualization → Response
    ├── "weekly report as PDF"          → Report Agent → DocumentBuilder → Response
    ├── "anomaly in humidity sensors"   → SPARQL → SQL → Anomaly Agent → Response
    ├── "export readings as CSV"        → SPARQL → SQL → Export Agent → Response
    ├── "check ASHRAE compliance"       → SPARQL → SQL → Analytics → Response
    └── "hello / general question"      → Dialogue → Response  (no DB needed)
```

The user never sees this routing. They ask in natural language; the right agents fire.

---

## 4. The 14 Recognized Intents

| Intent | Trigger Examples | Agents Used |
|---|---|---|
| `general` | "Hello", "what can you do?" | Dialogue only |
| `metadata` | "List all CO₂ sensors on floor 2" | SPARQL |
| `analytics` | "Average temperature last 24h" | SPARQL → SQL → Analytics |
| `discovery` | "What data do you have?" | Sensor map + SPARQL |
| `compare` | "Compare zones 1 and 2 temperatures" | SPARQL → SQL → Analytics |
| `trend` | "Show CO₂ trend over the past month" | SPARQL → SQL → Analytics → Viz |
| `anomaly` | "Any spikes in humidity today?" | SPARQL → SQL → Anomaly |
| `compliance` | "Are we within ASHRAE 62.1 limits?" | SPARQL → SQL → Analytics |
| `report` | "Generate weekly summary report" | Report Agent → DocumentBuilder |
| `export` | "Export sensor data as CSV" | SPARQL → SQL → Export |
| `recommend` | "How can I improve air quality?" | SPARQL → SQL → Analytics |
| `planner` | "Analyse CO₂ then export as PDF" | Planner (multi-agent) |
| `clarification` | Ambiguous query | Dialogue → follow-up question |
| `control` | "Turn off HVAC zone 4" | Graceful decline (reserved) |

---

## 5. Output Types: Everything the System Produces

| What the User Asks | Output Format | Produced By |
|---|---|---|
| "What is the CO₂ level?" | Inline number + context sentence | SQL → formatted text |
| "Plot temperature last week" | Matplotlib / Plotly chart | Code Executor (sandboxed Python) |
| "Generate weekly summary report" | PDF or DOCX download | DocumentBuilder + Jinja2 templates |
| "Show compliance status" | Standards assessment card | Analytics Engine + compliance_report.html |
| "Export sensor data" | CSV / JSON / HTML file | DataExportAgent |
| "Explain the building layout" | Natural language description | SPARQL ontology traversal |
| "Who manages zone 5?" | Person + role | SPARQL RDF property lookup |

### Report Templates

Four professional templates are available, selected automatically by `(report_type, persona)`:

| Template | Used For |
|---|---|
| `executive_kpi.html` | Hero KPI section, gradient background, executive brief |
| `weekly_summary.html` | KPIs, readings table, anomalies, operational highlights |
| `compliance_report.html` | Standards cards (ASHRAE / WELL / BREEAM), evidence data, violations |
| `anomaly_digest.html` | Anomaly summary, KPIs, outlier details table |

---

## 6. How the System Gets Smarter Per User

Three memory layers work together:

**Short-term (Redis, 1h TTL)**
Full conversation state is preserved. The user can say "now plot that" and the system knows what "that" refers to from two messages ago.

**Medium-term (Agent Memory, Qdrant)**
Past successful interactions are embedded as vectors. If a `facility_manager` always asks about zone 3, the next session's intent detection context already includes "this user cares about zone 3" — improves routing accuracy without retraining any model.

**Response Cache (Redis, fuzzy matching at 85% similarity)**
Identical or semantically similar questions are answered from cache instantly. A 200-user deployment does not re-run the same SPARQL + SQL pipeline 200 times for the same popular question.

---

## 7. Safety and Production Hardening

| Risk | Defense |
|---|---|
| LLM provider goes down | Circuit breaker: fast-fails after 5 failures, auto-recovers in 30s |
| MySQL crashes mid-query | Circuit breaker + graceful degradation: SPARQL/ontology answers still work |
| Malicious SQL injection | Parameterized adapters + `_FORBIDDEN_KEYWORDS` blocklist |
| SPARQL data extraction attack | `LIMIT 1000` safety cap enforced before every GraphDB call |
| 10,000-char prompt bomb | `ChatRequest` Pydantic model rejects at HTTP boundary |
| Unauthorized access | RBAC enabled by default; 6 roles with 20 granular permissions |
| Query hangs forever | 120s workflow timeout + 60s per-LLM-call timeout |
| Default credentials in production | Startup raises `ValueError` if default `SECRET_KEY` + RBAC enabled |
| Cascading failures | `_safe_node` wrappers catch exceptions in every data node — pipeline continues |
| Stale cached data | SmartCacheManager invalidates sensor caches after 100 new readings |

---

## 8. Multi-Building Architecture

The TTL file drives everything, including multi-tenancy. Adding a new building requires only a config entry:

```yaml
# config/building_config.yaml
buildings:
  building1:
    ttl_file: input/bldg1_protege.ttl
    graphdb_repository: bldg1
    storage_adapters:
      database1: mysql://host.docker.internal:3306/sensordb

  building2:
    ttl_file: input/bldg2_protege.ttl
    graphdb_repository: bldg2
    storage_adapters:
      database1: postgresql://postgres:5433/sensordb_bldg2
```

The MultiBuilding Manager discovers all buildings at startup. A query with `building_id=building2` automatically routes SPARQL to the correct GraphDB repository and SQL to the correct adapter — no code changes needed per building.

---

## 9. Concrete End-to-End Example

**User asks:** *"Show me average CO₂ levels in Zone 3 for the past week and flag any ASHRAE violations"*

```
Step 1 — Dialogue Agent
    intent:              "compliance"
    entities:            ["CO₂", "Zone 3"]
    time_range:          { start: "now-7d", end: "now" }
    required_analytics:  ["avg", "anomaly"]

Step 2 — SPARQL Agent  (GraphDB)
    query:   SELECT ?uuid ?storedAt WHERE {
                 ?sensor brick:hasLocation ?zone3 ;
                         a brick:CO2_Sensor ;
                         ref:storedAt ?storedAt .
             } LIMIT 1000
    result:  uuid="5bb3...", storedAt="bldg:database1"

Step 3 — SQL Agent  (MySQL via adapter registry)
    query:   SELECT Datetime AS timestamp, `5bb3...` AS value
             FROM sensor_data
             WHERE Datetime >= NOW() - INTERVAL 7 DAY
             LIMIT 10000;
    result:  2,016 rows of readings

Step 4 — Analytics Agent  (Code Executor, sandboxed)
    generated Python:  df.mean(), df.resample('1H').mean(), flag > 1000 ppm
    result:            avg = 782 ppm
                       3 violations: Tuesday 14:00–16:00

Step 5 — Response Node
    compliance card:   ASHRAE 62.1 threshold 1000 ppm — 3 breaches flagged
    persona rewrite:   facility_manager voice — actionable KPI briefing
    follow-up:         "Generate compliance report as PDF? | View trend? | Check other zones?"
    saved to Redis:    conversation state preserved for follow-up questions

Total wall-clock time: ~3–8 seconds end-to-end
```

---

## 10. Service Map

| Service | Port | Role |
|---|---|---|
| Orchestrator (FastAPI) | 8000 | LangGraph pipeline, all endpoints, RBAC |
| RAG Service | 8001 | GraphDB + Qdrant semantic retrieval |
| Code Executor | 8002 | Sandboxed Python for analytics + plots |
| MCP Server | 8003 | Claude Desktop / Cursor tool integration |
| GraphDB | 7200 | RDF triple store (TTL ontology) |
| Redis | 6379 | Conversation state, response cache, session tokens |
| PostgreSQL | 5433 | User accounts, RBAC roles, conversation history |
| MySQL (host) | 3306 | Building 1 time-series sensor data |
| Qdrant | 6333 | Agent memory vector store |
| MongoDB | 27017 | Chat history archive |
| File Server (nginx) | 8080 | Generated plots, reports, exports |
| Prometheus | 9090 | Metrics (monitoring profile) |
| Grafana | 3002 | Dashboards (monitoring profile) |

---

## 11. Key Files Reference

| File | Purpose |
|---|---|
| `orchestrator/main.py` | FastAPI app, all endpoints, startup lifecycle |
| `orchestrator/workflow.py` | LangGraph state machine, all routing logic |
| `shared/config.py` | Every env var and service URL — single source of truth |
| `shared/models.py` | `ConversationState`, `ChatRequest`, all Pydantic models |
| `orchestrator/agents/dialogue_agent.py` | Intent detection, persona formatting, few-shot library |
| `orchestrator/agents/sparql_agent.py` | SPARQL generation + GraphDB execution |
| `orchestrator/agents/sql_agent.py` | Text-to-SQL + time-series data fetch |
| `orchestrator/agents/analytics_agent.py` | LLM-generated Python analytics via Code Executor |
| `orchestrator/services/document_builder.py` | PDF / DOCX / HTML report rendering |
| `orchestrator/services/circuit_breaker.py` | CLOSED → OPEN → HALF_OPEN failure protection |
| `orchestrator/services/smart_cache.py` | Event-driven cache invalidation |
| `orchestrator/services/adapters/registry.py` | Database adapter routing by `ref:storedAt` |
| `orchestrator/middleware/rbac.py` | 6 roles, 20 permissions, JWT enforcement |
| `docker-compose.yml` | All 13 services, volumes, networks |
| `scripts/verify_services.sh` | Health check script for all services |
