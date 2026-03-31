# Configuration Guide

Centralized configuration is handled via `.env` and service-level environment variables.

## Model Provider Selection

- `MODEL_PROVIDER`: `local` | `cloud` (default `local`)
- Local (Ollama):
  - `OLLAMA_BASE_URL`: e.g., `http://ollama-deepseek-r1:11434`
  - `OLLAMA_MODEL`: e.g., `deepseek-r1:32b`
  - Performance: `OLLAMA_NUM_CTX`, `OLLAMA_KEEP_ALIVE`, `OLLAMA_GPU_LAYERS`
- Cloud (OpenAI):
  - `OPENAI_API_KEY`
  - `OPENAI_MODEL` (e.g., `gpt-4o-mini`)

## Orchestrator
- `REDIS_HOST`, `REDIS_PORT`
- `RAG_SERVICE_HOST`, `RAG_SERVICE_PORT`
- `CODE_EXECUTOR_HOST`, `CODE_EXECUTOR_PORT`
- `WHISPER_STT_HOST`, `WHISPER_STT_PORT`

## GraphDB Setup

For detailed instructions on setting up the GraphDB Similarity Index, please refer to the [GraphDB Setup Guide](GRAPHDB_SETUP.md).

- `GRAPHDB_HOST`, `GRAPHDB_PORT`
- `MYSQL_HOST`, `MYSQL_PORT`
- `LLM_TEMPERATURE`
- `USE_SEMANTIC_ONTOLOGY=true|false`
- `ONTOLOGY_QUERY_MODE=semantic|sparql`

## Databases
- MySQL:
  - `MYSQL_ROOT_PASSWORD`, `MYSQL_DATABASE`, `MYSQL_USER`, `MYSQL_PASSWORD`
- Postgres (user data):
  - `POSTGRES_USER_DB`, `POSTGRES_USER_USER`, `POSTGRES_USER_PASSWORD`

## RAG
- `GRAPHDB_REPOSITORY` (default `bldg`)
- `GRAPHDB_SIMILARITY_INDEX` (default `bldg_index`)

## Whisper STT
- `WHISPER_MODEL`: `tiny-int8` | `base` | `small-int8` | `medium`
- `WHISPER_BEAM`: `1` for speed, higher for accuracy
- `WHISPER_LANG`: `en` (set explicitly for best results)

## Ports & Networks
Reference: `docker-compose.agentic.yml` defines ports and two networks:
- `ontobot-agentic` (internal)
- `ontobot-network` (external integration)

## Volumes
- `./volumes/*` for persistent state (ollama, qdrant, redis, graphdb, mongo, artifacts)
- `mysql-data` external volume for MySQL
