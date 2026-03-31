# OntoSage Project Structure, Architecture, and End-to-End Flow

This document provides a comprehensive, end-to-end overview of the OntoSage framework: its folders and services, the cognitive workflow from user input to final answer, data models and databases, runtime conditions and routing, and how multiple personas can interact to make safe, sustainable, and profitable building decisions. It is written to be exhaustive and descriptive, capturing all working parts, connections, and behaviors as implemented in the repository and the agentic runtime.


**Purpose**
- Enable role-specific, question-answering workflows for smart buildings (facility managers, building owners, occupants, H&S officers, sustainability teams, compliance bodies, insurers, architects, IT/data scientists, vendors, real estate developers).
- Operate on an ontology-first paradigm where building entities (sensors, zones, equipment) are modeled in RDF/TTL. Each sensor may carry an external reference (UUID) linking to a time-series data source for analytics.
- Retrieve metadata from the knowledge graph (GraphDB), fetch values from relational stores (e.g., MySQL), analyze and visualize results, and return clear, persona-aware responses.


**Key Design Principles**
- Ontology-centric: Brick/REC/ASHRAE 223-aligned modeling in TTL files for zones, equipment, sensors, and relationships.
- Memory and context: Conversation state, summaries, and redis-based caching for responsiveness and continuity.
- Two-tier retrieval: Knowledge (GraphDB semantic search + SPARQL) and Data (SQL over time-series, standardized output for analytics).
- Modular agents: Dialogue, SPARQL, SQL, Analytics, Visualization — orchestrated in a LangGraph state machine with conditional routing.
- Safe execution: SQL validation, sandboxed Python execution for analytics, retries with automatic code fixes, and controlled visualization pipelines.
- Deployable stack: Docker Compose services for LLMs, orchestrator, RAG, GraphDB, databases, UI, monitoring.


**Personas and Benefits**
- Facility managers / Maintenance teams: Ask about equipment status, sensor locations, abnormal readings, maintenance priorities, and historical trends.
- Building owners / Property managers: Demand portfolio-level KPIs, energy costs, comfort metrics, and investment decisions.
- Occupants / Tenants / Employees: Query room comfort (temperature/CO2), air quality, noise complaints, and booking details.
- Health and safety officers: Check compliance thresholds, alerts, recent incidents, evacuation routes, and safety device status.
- Sustainability and energy teams: Analyze consumption patterns, baselines vs. targets, anomalies, carbon metrics, and retrofit impact.
- Compliance and regulatory bodies: Audit metadata (what sensors exist, where they are, who maintains them) and evidence trails.
- Insurance companies: Assess risk exposure, event histories, and predictive maintenance indicators.
- Architects / Building designers: Explore spatial semantics, equipment zoning, adjacency, and design-performance links.
- IT / Data scientists: Inspect data models, connectors, schemas, and perform advanced analytics.
- Vendors / Service providers: Validate integrations, SLAs, device inventories, and service health.
- Real estate developers: Compare buildings, plan upgrades, track ROI and occupant satisfaction.


---

## Repository Structure (Top-Level)

- [docker-compose.agentic.yml](docker-compose.agentic.yml): Main agentic deployment for local LLMs, orchestrator, GraphDB, databases, and supporting services.
- [orchestrator/](orchestrator): FastAPI application coordinating LangGraph agents and conversation state.
- [rag-service/graphdbRAG/](rag-service/graphdbRAG): RAG service using GraphDB’s native similarity index and graph traversal to return entities and bounded context triples for SPARQL generation.
- [shared/](shared): Shared utilities, configuration, models used by multiple services.
- [frontend/](frontend): Open WebUI integration and static assets for chat/voice frontends.
- [code-executor/](code-executor): Sandboxed Python execution microservice for analytics and visualization code.
- [whisper-stt/](whisper-stt): Faster-Whisper speech-to-text service for voice input.
- [Abacws/](Abacws): Building management API and visualiser (legacy/integration components).
- [data/](data): Shared datasets (e.g., sensor UUID mappings) and building-specific imports.
- [Assets/](Assets): Building datasets, notebooks, and processed JSONs.
- [docs/](docs): Documentation set; this file lives here along with architecture, deployment, services, workflow guides.
- [outputs/](outputs): Standardized outputs (data JSON, plots/images) written by analytics/visualization.
- [volumes/](volumes): Persisted storage for GraphDB, databases, LLMs, etc.


---

## Core Services and Their Roles

- Orchestrator (FastAPI + LangGraph)
  - Hosts the conversation state machine and agents.
  - Provides `/health` and OpenAI-compatible endpoints for UI.
  - Interacts with Redis for caching and conversation scaffolding.
  - Reads building sensor maps and settings from environment.

- DialogueAgent
  - Detects intent (general, metadata, analytics, visualization), extracts entities, determines time ranges, and composes persona-aware prompts.
  - Retrieves ontology context via the RAG service to ground intent detection.
  - Calls clarification prompts when input is underspecified.
  - Formats final responses and can auto-title new conversations.

- SPARQLAgent
  - Uses RAG-provided GraphDB context to generate syntactically valid SPARQL.
  - Executes against GraphDB (native RDF store) and returns bindings.
  - Enforces metadata-vs-data decision: when analytics are needed, collects `uuid` and `storage` references using ontology properties (e.g., `ashrae:hasExternalReference`, `ref:hasTimeseriesId`, `ref:storedAt`).
  - Provides semantic fallback (LLM reasoning over retrieved triples) when SPARQL returns no results.

- SQLAgent
  - If SPARQL produced UUIDs, fetches time-series data by unpivoting wide MySQL tables (UUIDs as columns; `Datetime` as timestamp).
  - Validates SQL for safety (SELECT-only; blocks DDL/DML) and uses aiomysql to execute.
  - Generates text-to-SQL when UUIDs are absent, still honoring time filters (today, yesterday, last N hours/days).
  - Standardizes results to `{ "data": [{timestamp, uuid, value}, ...]}` for analytics.

- AnalyticsAgent
  - Generates Python analytics code (stats, trends, filters) using pandas/seaborn.
  - Writes and reads standardized data from [outputs/data](outputs).
  - Executes code via `code-executor` with retries and automatic error fixes; prints `PLOT_GENERATED: <filename>` when graphs are produced.
  - Produces a formatted, human-readable summary; maps UUIDs to labels for clarity.

- VisualizationAgent
  - Generates code for charts (line/bar/scatter/histogram/heatmap/pie), executes via `code-executor`, and embeds resulting images as base64.
  - Returns concise descriptions and media payloads for UI.

- RAG Service (GraphDB)
  - Endpoint `/graphdb/retrieve`: cleans query; performs vector similarity over GraphDB’s index; traverses up to `hops` depth; returns `prefixes`, `entities`, `triples`, `summary`, and metadata counts.
  - Ingest compatible TTLs and similarity index; supports health checks.

- GraphDB
  - RDF/TTL store replacing Fuseki. Hosts ontology repositories and similarity indexing.
  - Handles SPARQL execution and REST interfaces.

- Databases
  - MySQL: Primary time-series store for sensor readings (wide table with UUID columns and `Datetime`).
  - Redis: Memory/cache store for conversation state, LLM results, and prompt-level caches.
  - Postgres (user-data): Open WebUI chat persistence and consolidated user data when configured.
  - Mongo (chat-history): Alternate or legacy chat history storage for Abacws API and related.
  - Qdrant: Optional vector DB; can be enabled for additional embedding workflows. Current RAG uses GraphDB’s similarity indexing.

- Code Executor
  - Sandboxes Python execution with resource limits; returns stdout, errors, and supports plotting.

- Whisper STT
  - Faster-Whisper container for speech-to-text; maps port for API access.

- Open WebUI
  - Frontend for chat/voice; points to orchestrator’s OpenAI-compatible endpoint and to Ollama for local models.

- Abacws API and Visualiser
  - Building management backend and 3D/interactive visualization; can query MySQL, expose health endpoints, and serve dashboards.


---

## Data Model: Linking Ontology to Time-Series Data

- Ontology TTL files (Brick/REC/ASHRAE 223) define entities like sensors, equipment, zones, locations, and relationships (e.g., `brick:hasLocation`, `rec:containsElement`, `rec:adjacentElement`).
- External references bind ontology instances to time-series sources via patterns such as:
  - `?sensor ashrae:hasExternalReference ?extRef .`
  - `?extRef ref:hasTimeseriesId ?timeseriesID ; ref:storedAt ?database .`
- `ref:hasTimeseriesId` carries the UUID that identifies a sensor’s column in MySQL wide tables.
- `ref:storedAt` allows storage-aware routing (e.g., different DBs) if present.
- This enables metadata queries (SPARQL-only) and analytics queries (SPARQL→UUID→SQL→Analytics).


---

## End-to-End Cognitive Workflow (Input→Answer)

The orchestrator implements a LangGraph state machine with nodes: `dialogue`, `sparql`, `sql`, `analytics`, `visualization`, `response`. Conditional edges route based on intent and results.

1) Input Capture
- User interacts via chat (Open WebUI) or voice (Whisper STT). Messages enter the orchestrator as `ConversationState` with `messages`, `user_id`, `conversation_id`, and optional `summary`.

2) Memory and Context
- Redis caches intent results, SPARQL gen, and summaries; DialogueAgent periodically updates the conversation summary.
- Recent history is formatted and included in prompts; auto-titling occurs for new conversations.

3) Intent Detection and Clarification (DialogueAgent)
- Uses persona-aware system messages and calls LLM to produce:
  - `intent`: general | metadata | analytics | visualization
  - `entities`: normalized building entity mentions
  - `required_analytics`: operations like min/max/avg/trend/latest
  - `time_range`: start/end (absolute or relative)
  - `response`: direct answer for general questions
  - `explanation`: LLM rationale
- If underspecified, requests clarifying info (e.g., missing zone or time window).
- Routes: general → `response`; metadata/analytics → `sparql`; visualization → `visualization`.

4) Knowledge Retrieval (RAG Service via GraphDB)
- DialogueAgent and SPARQLAgent call `/graphdb/retrieve` to fetch a grounded context:
  - Vector similarity returns entity IRIs; graph traversal collects nearby triples.
  - Returns a unified context block with prefixes, summary, and triple text for LLM prompting.

5) Ontology Query (SPARQLAgent)
- Generates SPARQL using the RAG context, conversation history, and optionally discovered instance candidates.
- Validates and repairs syntax; executes against GraphDB.
- If no results, performs semantic fallback: LLM reasons directly over triples to produce an answer.
- For sensor/device queries where analytics are needed, retrieves the essential `uuid` and `storage` via `ashrae:hasExternalReference` → `ref:hasTimeseriesId` and `ref:storedAt`.
- Sets `analytics_required` accordingly.

6) Data Fetch (SQLAgent)
- If UUIDs are available: groups by storage (when present) and generates MySQL queries that unpivot wide tables using `UNION ALL`.
- Enforces time filters (today, yesterday, last N hours/days) with `Datetime` column; returns up to 1000 rows ordered by `Datetime DESC`.
- Validates queries: SELECT-only; blocks DDL/DML.
- When UUIDs are absent: uses text-to-SQL with schema-aware guidance.
- Standardizes output to `{ "data": [ { "timestamp": ..., "uuid": ..., "value": ... }, ... ] }`.

7) Analytics (AnalyticsAgent)
- Saves standardized data to [outputs/data](outputs) with per-user/conversation files.
- Generates Python code (templates for avg/max/min/latest/count; or general-purpose code) using pandas/seaborn.
- Executes via `code-executor` with up to 3 retries and automatic code fixes; prints `PLOT_GENERATED: <filename>` if a graph is created.
- Produces `formatted_response` and optional media payloads.

8) Visualization (VisualizationAgent)
- If explicitly requested or analytics didn’t produce its own plot, generates visualization code (line, bar, scatter, histogram, heatmap, pie).
- Executes via `code-executor`, saves image in outputs, returns base64-embedded link and description.

9) Final Response (Response Node)
- Prioritizes downstream results: visualization → analytics → SQL → SPARQL → dialogue.
- Replaces any UUIDs in text with human-readable sensor labels gathered earlier.
- Uses DialogueAgent to format persona-aware responses and attaches media when present.

10) Output and State Updates
- Appends assistant message to `ConversationState`.
- Writes data and images to `outputs/`; caches query artifacts; maintains conversation summary.


---

## Conditional Routing and Behaviors

- Dialogue → SPARQL: When intent indicates metadata or analytics.
- SPARQL → SQL: If `analytics_required` is true and UUIDs/storage are found (or implied).
- SQL → Analytics: All SQL queries imply data analysis (e.g., computing statistics or formatting).
- Analytics → Visualization: If user asks for plots or analytics code did not already produce a plot.
- Visualization → Response: Visual content formatted and returned.
- General → Response: Direct answers for generic questions.

Runtime safeguards and optimizations:
- Cache keys: prompt hashes for intent/SPARQL generation avoid redundant LLM calls.
- SPARQL repair: automatic syntax fixes and prefix normalization; semantic fallback when bindings are empty.
- SQL validation: strict SELECT-only checks, single-statement enforcement, forbidden keyword filtering.
- Analytics retries: automatic code fix loop using error context; standardized data format ensures predictable processing.
- UUID to label mapping: final responses substitute technical identifiers with readable sensor names.


---

## Databases and Storage

- GraphDB (RDF + Similarity)
  - Hosts repositories (e.g., `bldg`) and similarity indexes (e.g., `bldg_index`).
  - Exposes REST/SPARQL endpoints and powers `/graphdb/retrieve` RAG.

- MySQL (Time-Series)
  - Wide table design: `sensor_data` with `Datetime` + many UUID-named columns.
  - SQLAgent unpivots through `UNION ALL`, filters by `Datetime`, standardizes output rows.

- Redis (Memory/Cache)
  - Stores conversation-level caches, intent results, SPARQL generation caches, and helper state.

- Postgres (User Data / Open WebUI)
  - Optional persistence for chat/user data when using Open WebUI settings.

- Mongo (Chat History)
  - Optional/legacy store for chat histories used by Abacws components.

- Qdrant (Optional Vector DB)
  - Available for future embedding workflows. Current RAG operates entirely on GraphDB’s similarity index.

- Volumes
  - Persist GraphDB home, MySQL data, Ollama models, Redis/Mongo/Postgres, Open WebUI storage, and outputs.


---

## APIs and Interfaces

- Orchestrator
  - `/health`: health check and readiness signal.
  - OpenAI-compatible endpoint (via environment) for UI integrations.

- RAG Service (GraphDB)
  - `POST /graphdb/retrieve`: `{ query, top_k, hops, min_score }` → returns prefixes, triples, entities, labels, summary, metadata.
  - `GET /health`: backend status check.

- Code Executor
  - `POST /execute`: `{ code }` → returns stdout, errors, and status.

- Whisper STT
  - `GET /health`: service status; accepts audio for transcription via API.

- Abacws API / Visualiser
  - `/health`, building visualizer at port 8090; reaches API at 5000 for building data queries.


---

## Deployment and Configuration

- Docker Compose (`docker-compose.agentic.yml`)
  - Services: `ollama`, `ollama-health`, `orchestrator`, `graphdb-rag-service`, `graphdb`, `mysql`, `redis`, `postgres-user-data`, `mongo`, `code-executor`, `whisper-stt`, `open-webui`, `api` (Abacws), `visualiser`, `pgadmin`.
  - Health checks for critical services; GPU reservations for LLMs where available.
  - Environment variables configure hosts, ports, model provider (`local`, `ollama_cloud`, `openai`), semantic ontology usage, and LLM parameters.
  - Volumes map data directories and outputs; aliases ensure backward-compatible networking (`rag-service`).

- Environment and Settings
  - Orchestrator reads `USE_SEMANTIC_ONTOLOGY` and `ONTOLOGY_QUERY_MODE` to choose query strategy.
  - LLMManager applies rate-limiting for OpenAI-compatible providers; supports Ollama local/Cloud.


---

## Error Handling, Safety, and Observability

- SPARQL syntax validation and repair when needed.
- SQL validation to block non-SELECT operations and multi-statement injections.
- Analytics code fix loop (up to 3 retries) driven by LLM feedback from errors.
- Standardized data format guarantees predictable downstream analytics and visualization.
- Health endpoints (`/health`) across services; logs include structured markers (e.g., `PLOT_GENERATED`).


---

## Example Persona-Flows

- Facility Manager: “List CO2 sensors in Zone 5.01 and show their latest readings.”
  - DialogueAgent → intent: analytics, entities recognized.
  - RAG → context with CO2 sensors and zone relationships.
  - SPARQL → sensor URIs + `uuid`/`storage`.
  - SQL → unpivot for UUIDs, filter last 24h.
  - Analytics → latest readings, summary.
  - Response → sensor names and values; optional visualization.

- Sustainability Team: “Average temperature trend for Level 3 in the last 7 days.”
  - DialogueAgent → analytics + time range.
  - RAG/SPARQL → Level 3 sensors and UUIDs.
  - SQL → 7-day filter, unpivot.
  - Analytics → groupby trend, produce line plot.
  - Response → embed plot; highlight anomalies.

- Compliance Officer: “Where is Air_Temperature_Sensor_5.04 located and who maintains it?”
  - DialogueAgent → metadata.
  - RAG/SPARQL → sensor location, maintenance properties.
  - Response → direct metadata (no SQL/Analytics).


---

## Summary

OntoSage unifies ontology-driven metadata retrieval with time-series analytics under an agentic workflow. It grounds each question in GraphDB context, maps entities to data via explicit external references (UUID + storage), runs safe SQL and sandboxed analytics, and returns persona-aware, readable answers with optional visualizations. The architecture is modular, deployable, and designed for multi-persona collaboration across smart building operations, sustainability, compliance, and decision support.
