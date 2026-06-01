# Configuration Reference

This page documents every environment variable, configuration file, and tuning parameter available in OntoSage. All configuration is driven by the `.env` file and two YAML files in `config/`.

---

## Quick Setup

```bash
# Copy the template
cp .env.example .env

# Edit the minimal required settings
nano .env
```

Required minimum for OpenAI mode:
```bash
MODEL_PROVIDER=openai
OPENAI_API_KEY=sk-...
MYSQL_PASSWORD=yourpassword
POSTGRES_USER_PASSWORD=yourpassword
```

Required minimum for local GPU mode:
```bash
MODEL_PROVIDER=local
OLLAMA_MODEL=deepseek-r1:32b
MYSQL_PASSWORD=yourpassword
POSTGRES_USER_PASSWORD=yourpassword
```

---

## LLM Provider

### `MODEL_PROVIDER`

Selects the LLM backend for all inference tasks (intent classification, SPARQL generation, code generation, response synthesis).

| Value | Description | Requirements |
|-------|-------------|-------------|
| `openai` | OpenAI API | `OPENAI_API_KEY` required |
| `local` | Ollama running in Docker | NVIDIA GPU + CUDA recommended |
| `cloud` | Ollama Cloud (external) | `OLLAMA_BASE_URL` pointing to remote |

Default: `local`

You can switch providers at runtime without rebuilding:
```bash
MODEL_PROVIDER=openai docker compose restart orchestrator
```

---

### OpenAI Settings

Used when `MODEL_PROVIDER=openai`.

| Variable | Default | Description |
|----------|---------|-------------|
| `OPENAI_API_KEY` | — | **Required.** Your OpenAI API key (starts with `sk-`) |
| `OPENAI_MODEL` | `gpt-4-turbo-preview` | Model for LLM inference. Options: `gpt-4o`, `gpt-4o-mini`, `gpt-4-turbo`, `gpt-3.5-turbo` |
| `OPENAI_TEMPERATURE` | `0.1` | Sampling temperature (0.0 = deterministic, 1.0 = creative). Keep at 0.0–0.2 for SPARQL generation |
| `OPENAI_RETRY_DELAY_S` | `20` | Seconds to wait between retries on rate limit (429) errors |
| `EMBEDDING_MODEL_OPENAI` | `text-embedding-3-small` | Embedding model for RAG. Options: `text-embedding-3-large`, `text-embedding-ada-002` |
| `EMBEDDING_DIMENSION_OPENAI` | `1536` | Dimension of embedding vectors (must match model) |

---

### Local Ollama Settings

Used when `MODEL_PROVIDER=local`.

| Variable | Default | Description |
|----------|---------|-------------|
| `OLLAMA_BASE_URL` | `http://ollama:11434` | Internal Docker URL for the Ollama service |
| `OLLAMA_MODEL` | `deepseek-r1:32b` | Model to use for inference. Pull with `docker exec ollama ollama pull <model>` |
| `OLLAMA_GPU_LAYERS` | `-1` | Number of layers to offload to GPU. `-1` = all layers on GPU. `0` = CPU only |
| `OLLAMA_NUM_CTX` | `8192` | Context window size (tokens). Larger = more conversation history but slower |
| `OLLAMA_KEEP_ALIVE` | `5m` | How long to keep the model loaded after last request. `0` = unload immediately |

**Recommended models by VRAM:**

| VRAM | Recommended Model | Quality |
|------|-------------------|---------|
| 8 GB | `llama3.2:7b` or `mistral:7b` | Good |
| 16 GB | `llama3.1:13b` or `deepseek-r1:14b` | Very Good |
| 24 GB | `deepseek-r1:32b` | Excellent |
| 48 GB+ | `llama3.1:70b` | Best |

---

### Embedding Provider

| Variable | Default | Description |
|----------|---------|-------------|
| `EMBEDDING_PROVIDER` | `local` | `local` = sentence-transformers, `openai` = OpenAI embeddings API |
| `EMBEDDING_MODEL_LOCAL` | `sentence-transformers/all-MiniLM-L6-v2` | Local embedding model (downloaded on first use) |
| `EMBEDDING_DIMENSION_LOCAL` | `384` | Vector dimension for local embeddings |

---

## Building Configuration

### Core Building Settings

| Variable | Default | Description |
|----------|---------|-------------|
| `BUILDING_ID` | `bldg1` | Identifier passed to the orchestrator. Must match an ontology loaded in GraphDB |
| `BUILDING_NAME` | `Abacws Building` | Human-readable name used in AI responses |
| `BUILDING_CONFIG_FILE` | — | Path to a `building_config.yaml` file. If set, overrides individual env vars |

### `config/building_config.yaml`

Structured building metadata read at orchestrator startup. See the [Building Onboarding Guide](BUILDING_ONBOARDING.md) for full field documentation.

```yaml
building:
  id: "bldg1"
  name: "Abacws Building"
  namespace: "http://abacwsbuilding.cardiff.ac.uk/abacws#"
  prefix: "bldg"
  timezone: "Europe/London"
  abox_file: "trial/dataset/bldg1_protege.ttl"
  tbox_file: "trial/dataset/Brick.ttl"

ontology:
  schema: "brick"          # brick | rec | s223 | custom
  schema_uri: "https://brickschema.org/schema/Brick#"
  extra_prefixes: []

storage:
  backend: "mysql"
  database: "abacws"
  table: "sensor_data"
  columns:
    uuid: "uuid"
    value: "value"
    timestamp: "time"
    sensor_name: "sensor_name"
```

---

## GraphDB

| Variable | Default | Description |
|----------|---------|-------------|
| `GRAPHDB_HOST` | `graphdb` | Docker service name (or external hostname) |
| `GRAPHDB_PORT` | `7200` | HTTP port for GraphDB REST API |
| `GRAPHDB_REPOSITORY` | `ontosage` | Repository ID to query. Must exist in GraphDB before use |
| `GRAPHDB_SIMILARITY_INDEX` | `bldg_index` | Name of the text similarity index for semantic entity search |
| `GDB_HEAP_SIZE` | `2g` | Java heap for GraphDB JVM. Increase to `4g`–`8g` for large ontologies (>500K triples) |
| `GDB_MAX_MEM` | `4g` | Java max memory (`-Xmx`). Set to 2–4 GB more than `GDB_HEAP_SIZE` |

---

## Relational Databases

### MySQL (Building 1 / Primary Time-Series)

| Variable | Default | Description |
|----------|---------|-------------|
| `MYSQL_HOST` | `mysql` | MySQL server hostname |
| `MYSQL_PORT` | `3306` | MySQL port |
| `MYSQL_USER` | `root` | Username |
| `MYSQL_PASSWORD` | `mysql` | Password — change in production |
| `MYSQL_DATABASE` | `sensordb` | Database name containing sensor data |
| `MYSQL_ROOT_PASSWORD` | — | Root password for container initialization |

### PostgreSQL (User Accounts and RBAC)

OntoSage uses a dedicated PostgreSQL instance for user accounts, sessions, and role assignments. This is separate from sensor data storage.

| Variable | Default | Description |
|----------|---------|-------------|
| `POSTGRES_USER_USER` | `ontosage` | PostgreSQL username for user data |
| `POSTGRES_USER_PASSWORD` | `ontosage` | Password — change in production |
| `POSTGRES_USER_DB` | `ontosage_users` | Database name |
| `POSTGRES_USER_PORT` | `5433` | External host port (internal is 5432) |

### Multi-Building Database Registry

Additional databases for Buildings 2–8 are configured in `config/database_registry.yaml`. Each entry uses env var substitution:

```bash
# Building 2 (PostgreSQL)
PG_HOST=postgres
PG_PORT=5432
PG_USER=ontosage
PG_PASSWORD=yourpassword
PG_DATABASE=bldg2

# Building 3 (TimescaleDB)
TIMESCALE_HOST=timescaledb
TIMESCALE_PORT=5432
TIMESCALE_USER=ontosage
TIMESCALE_PASSWORD=yourpassword
TIMESCALE_DATABASE=bldg3

# Building 4 (MongoDB)
MONGO_HOST=mongodb
MONGO_PORT=27017
MONGO_USER=
MONGO_PASSWORD=
MONGO_DATABASE=bldg4
MONGO_COLLECTION=sensor_data

# Building 5 (InfluxDB 2.x)
INFLUX_URL=http://influxdb:8086
INFLUX_TOKEN=your_influx_token_here
INFLUX_ORG=ontosage
INFLUX_BUCKET=sensors

# Building 6 (SQLite)
SQLITE_PATH=/app/data/bldg6.db

# Building 7 (Cassandra)
CASSANDRA_HOST=cassandra
CASSANDRA_PORT=9042
CASSANDRA_KEYSPACE=bldg7
CASSANDRA_TABLE=sensor_data

# Building 8 (Redis TimeSeries)
REDIS_TS_URL=redis://redis:6379/1
REDIS_TS_KEY_PREFIX=sensor
```

See `config/database_registry.yaml` for the full list of supported databases including cloud variants (AWS RDS, Aurora, Atlas, Timescale Cloud, InfluxDB Cloud, AstraDB).

---

## Service URLs

These URL environment variables point services to each other within the Docker network. Only change them if you are running services outside Docker or on non-standard ports.

| Variable | Default | Service |
|----------|---------|---------|
| `QDRANT_URL` | `http://qdrant:6333` | Vector database for agent memory |
| `REDIS_URL` | `redis://redis:6379/0` | Conversation state and caching |
| `RAG_SERVICE_URL` | `http://rag-service:8001` | RAG context retrieval |
| `CODE_EXECUTOR_URL` | `http://code-executor:8002` | Python analytics sandbox |
| `WHISPER_STT_URL` | `http://whisper-stt:8003` | Speech-to-text service |

---

## Code Executor (Analytics Sandbox)

| Variable | Default | Description |
|----------|---------|-------------|
| `CODE_EXECUTOR_TIMEOUT` | `30` | Maximum execution time in seconds per analytics job |
| `CODE_EXECUTOR_MEMORY_LIMIT` | `1g` | RAM limit per execution. Raise to `2g` for complex analytics on large datasets |
| `CODE_EXECUTOR_CPU_LIMIT` | `1.0` | CPU core limit (1.0 = 1 full core) |

---

## Conversation and Session Settings

| Variable | Default | Description |
|----------|---------|-------------|
| `CONVERSATION_TTL` | `0` | Seconds before Redis time-expires a conversation's state. **`0` = no time-expiry** (state is count-bounded instead, see below). Set e.g. `86400` to re-enable 24-hour expiry |
| `CONVERSATION_MAX_MESSAGES` | `20` | Count-based eviction — max messages retained in the stored Redis conversation blob. The active bound when `CONVERSATION_TTL=0` |
| `MAX_CONVERSATION_HISTORY` | `20` | Maximum prior turns injected into the LLM context (sliding window) |
| `COREFERENCE_REWRITE_ENABLED` | `true` | Resolve context-dependent follow-ups ("and humidity *there*?") into self-contained queries via a gated fast-LLM rewrite. See [Conversation Intelligence](CONVERSATION_INTELLIGENCE.md) |
| `MAX_RETRY_ATTEMPTS` | `3` | Automatic retry count for SPARQL errors, code execution failures, and LLM API timeouts |

!!! note "Memory eviction changed"
    OntoSage now bounds conversation state by **message count** (`CONVERSATION_MAX_MESSAGES`) rather than a fixed TTL. `CONVERSATION_TTL` defaults to `0` (no time-expiry). See [Conversation Intelligence](CONVERSATION_INTELLIGENCE.md) for the two-tier memory model (Redis + Postgres `turn_memory`).

---

## RAG and Semantic Search

| Variable | Default | Description |
|----------|---------|-------------|
| `GRAPHDB_SIMILARITY_INDEX` | `bldg_index` | GraphDB similarity plugin index name |
| `SIMILARITY_THRESHOLD` | `0.7` | Minimum similarity score (0.0–1.0) for entity retrieval. Lower = more results but less relevant |
| `RAG_TOP_K` | `5` | Maximum number of entities returned per semantic search query |

---

## Qdrant Vector Database

Qdrant stores agent memory, floor-plan vectors, and (v3.1) per-building capability KB collections.

| Variable | Default | Description |
|----------|---------|-------------|
| `QDRANT_URL` | `http://qdrant:6333` | Qdrant REST API endpoint |
| `QDRANT_ONTOLOGY_COLLECTION` | `ontology` | Collection for Brick Schema triples |
| `QDRANT_QUERIES_COLLECTION` | `queries` | Collection for historical SPARQL query cache |
| `QDRANT_ANALYTICS_COLLECTION` | `analytics` | Collection for reusable analytics code snippets |
| `QDRANT_DOCS_COLLECTION` | `documentation` | Collection for help text and documentation |

Per-building collections (auto-managed; no env var needed):

| Collection name pattern | Created by | Purpose |
|---|---|---|
| `capability_<building_id>` | `CapabilityIndexer` at startup | KB lookup for off-ontology questions |
| `intent_<building_id>_<intent>` | Indexer if `intent_routing.enabled: true` | Multi-intent routing (opt-in) |
| `floor_plans` | `FloorPlanRegistry` | Room description + DWG geometry |
| `user_memory` | `AgentMemoryService` | Per-user cross-session memory |

---

## Capability Semantic Routing *(v3.1)*

Controls the embedding provider behind the capability KB indexer and the query-time semantic router. When `EMBEDDING_PROVIDER` is unset, it defaults to `openai` (uses `OPENAI_API_KEY`).

| Variable | Default | Description |
|----------|---------|-------------|
| `EMBEDDING_PROVIDER` | `openai` | `openai` (uses OpenAI API) or `local` (uses sentence-transformers in-process) |
| `EMBEDDING_MODEL_OPENAI` | `text-embedding-3-small` | OpenAI embedding model (1536 dims) |
| `EMBEDDING_MODEL_LOCAL` | `sentence-transformers/all-MiniLM-L6-v2` | Local model name (384 dims, ~90 MB) |
| `EMBEDDING_CACHE_TTL_SECONDS` | `86400` | Redis `cache:embed:*` TTL — 24 h by default |

> **Provider switching is free at runtime.** Changing `EMBEDDING_PROVIDER` and restarting triggers automatic Qdrant collection rebuild — `CapabilityIndexer` detects the dimension mismatch and re-embeds. Thresholds in `input/<bldg>/building.yaml` may need re-calibration when switching models (the score distribution differs); see [Capability Routing § Threshold calibration](CAPABILITY_ROUTING.md#threshold-calibration).

### Per-building routing config

Lives in `input/<building_id>/building.yaml`. Read by `SemanticRouter` at query time.

```yaml
capability_routing:
  enabled: true
  embedding_model: auto       # 'auto' follows EMBEDDING_PROVIDER
  threshold: 0.56             # soft-override band lower bound
  override_min: 0.60          # hard skip-LLM threshold
  top_k: 5                    # max KB entries returned
  fallback_on_qdrant_failure: skip   # silent LLM-only fallback
```

**Calibrated values for bldg1 (Abacws, 32 KB entries):**

| Embedding model | Dimensions | `threshold` | `override_min` |
|---|---|---|---|
| OpenAI `text-embedding-3-small` | 1536 | 0.50 | 0.55 |
| Local `all-MiniLM-L6-v2` | 384 | **0.56** | **0.60** |

**Validation rules** (Pydantic, fail-fast at startup):
- `override_min >= threshold` (boundary `==` allowed)
- `0.0 <= threshold, override_min <= 1.0`
- `1 <= top_k <= 50`
- `fallback_on_qdrant_failure ∈ {"skip"}` (legacy `"keyword"` removed in Phase 3 cleanup)

---

## Logging

| Variable | Default | Description |
|----------|---------|-------------|
| `LOG_LEVEL` | `INFO` | Python logging level: `DEBUG`, `INFO`, `WARNING`, `ERROR` |
| `LOG_FORMAT` | `%(asctime)s - %(name)s - %(levelname)s - %(message)s` | Python logging format string |

For debugging, set `LOG_LEVEL=DEBUG` to see:
- Full SPARQL queries generated and executed
- SQL queries with bound parameters
- LLM prompt/response pairs
- State transitions between LangGraph nodes

**Never set `LOG_LEVEL=DEBUG` in production** — it logs sensitive data including query parameters.

---

## Ontology Settings

| Variable | Default | Description |
|----------|---------|-------------|
| `USE_SEMANTIC_ONTOLOGY` | `true` | Enable semantic RAG fallback when SPARQL returns empty results |
| `ONTOLOGY_QUERY_MODE` | `sparql` | `sparql` = direct SPARQL query first; `semantic` = RAG-first approach |

---

## Speech-to-Text (Optional)

| Variable | Default | Description |
|----------|---------|-------------|
| `STT_PROVIDER` | `local` | `local` = faster-whisper container, `openai` = Whisper API |
| `WHISPER_MODEL_LOCAL` | `base` | Local Whisper model size: `tiny`, `base`, `small`, `medium`, `large` |
| `WHISPER_MODEL` | `tiny-int8` | Model variant when using local Whisper container |
| `WHISPER_BEAM` | `1` | Beam search width. `1` = fastest, higher = more accurate |
| `WHISPER_LANG` | `en` | Language code. Set explicitly for best results |
| `MAX_UPLOAD_SIZE_MB` | `25` | Maximum audio file size in MB (OpenAI API limit) |
| `ALLOWED_AUDIO_FORMATS` | `wav,mp3,m4a,ogg,webm` | Accepted audio MIME types |

---

## Security

| Variable | Default | Description |
|----------|---------|-------------|
| `API_KEY` | `change_me` | API key for the building management API. **Change in production** |
| `SECRET_KEY` | — | Application secret key for token signing. Generate with `openssl rand -hex 32` |
| `STRICT_SECRETS` | `false` | When `true`, the orchestrator **refuses to start** if any password (GraphDB, Postgres, MySQL) is still its built-in default — a fail-closed guard for production |

!!! tip "Secret hygiene"
    Secret-bearing settings (`OPENAI_API_KEY`, `GRAPHDB_PASSWORD`, `SECRET_KEY`, …) are masked in the application's config representation, so they are not echoed into logs or test output. Enable `STRICT_SECRETS=true` in production to block startup on default credentials.

See the [Security Guide](SECURITY.md) for full documentation on authentication, RBAC, and secrets management.

---

## Monitoring (Optional)

Enable with `docker compose --profile monitoring up -d`.

| Variable | Default | Description |
|----------|---------|-------------|
| Prometheus UI | `http://localhost:9090` | Metrics scraping from all services |
| Grafana UI | `http://localhost:3001` | Dashboard: OntoSage Overview (latency, throughput, service health) |
| Grafana login | `admin/admin` | Change in production |

---

## Development Settings

| Variable | Notes |
|----------|-------|
| `DEV_MODE=true` | Enables hot reload on code changes (mount source as volumes) |
| `SKIP_MODEL_DOWNLOAD=false` | Set to `true` to skip model pulls if already cached |
| `MOCK_LLM=false` | Set to `true` to use deterministic mock LLM responses for testing |
| `ABACWS_DEBUG=1` | Enable verbose 3D loader logging in the browser console |

---

## Complete `.env.example` Reference

The `.env.example` file in the repository root is the canonical reference for all configuration options. It includes comments explaining every variable, valid values, trade-offs, and security warnings.

```bash
# View all options with comments
cat .env.example
```

Copy it to `.env` and change only the values you need:

```bash
cp .env.example .env
# At minimum, set:
# MODEL_PROVIDER (openai or local)
# OPENAI_API_KEY (if using openai)
# Database passwords
```

---

## Configuration Precedence

When the same variable is set in multiple places, the following precedence applies (highest wins):

1. **Docker Compose override** — `-e VAR=value` on the command line
2. **`.env` file** — loaded by Docker Compose automatically
3. **`config/building_config.yaml`** — building-specific overrides
4. **`config/database_registry.yaml`** — `${VAR_NAME:-default}` fallbacks
5. **Application defaults** — hardcoded in `shared/config.py`
