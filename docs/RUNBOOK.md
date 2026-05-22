# Operations Runbook

This runbook covers day-to-day operation of OntoSage: starting and stopping services, health monitoring, backup and restore procedures, scaling, and troubleshooting common problems.

---

## Start / Stop Procedures

### Start the Full Stack

```bash
# Standard mode (OpenAI or local models already configured)
docker compose up -d

# With local GPU (Ollama)
docker compose --profile local-gpu up -d

# Start a specific service only
docker compose up -d orchestrator
```

Wait for all services to be healthy before sending queries:

```bash
# Watch container status until all are Up/healthy
watch docker compose ps

# Or check once
docker compose ps
```

Expected output (all services healthy):
```
NAME                        STATUS      PORTS
ontosage-orchestrator       Up (healthy)   0.0.0.0:8000->8000/tcp
ontosage-rag-service        Up (healthy)   0.0.0.0:8001->8001/tcp
ontosage-code-executor      Up (healthy)   0.0.0.0:8002->8002/tcp
ontosage-graphdb            Up (healthy)   0.0.0.0:7200->7200/tcp
ontosage-mysql              Up (healthy)   0.0.0.0:3307->3306/tcp
ontosage-postgres-user-data Up (healthy)   0.0.0.0:5433->5432/tcp
ontosage-redis              Up (healthy)   0.0.0.0:6379->6379/tcp
ontosage-mongodb            Up             0.0.0.0:27017->27017/tcp
ontosage-qdrant             Up             0.0.0.0:6333->6333/tcp
open-webui                  Up             0.0.0.0:3000->8080/tcp
```

### Stop the Stack (Data Preserved)

```bash
docker compose down
```

### Stop and Remove All Volumes (WARNING: Deletes All Data)

```bash
docker compose down -v
```

### Restart a Single Service

```bash
# After code or config changes
docker compose restart orchestrator

# Rebuild image before restarting (after code changes)
docker compose build orchestrator
docker compose up -d orchestrator
```

---

## Health Checks

### Quick Health Check

```bash
# All critical services
curl -s http://localhost:8000/health | python -m json.tool
curl -s http://localhost:8001/health
curl -s http://localhost:8002/health
```

Expected healthy response from orchestrator:

```json
{
  "status": "healthy",
  "services": {
    "graphdb": "healthy",
    "redis": "healthy",
    "mysql": "healthy",
    "postgresql": "healthy",
    "rag_service": "healthy",
    "code_executor": "healthy",
    "ollama": "skipped"
  }
}
```

### Detailed Service Checks

```bash
# GraphDB repository available
curl -s http://localhost:7200/repositories | python -m json.tool

# GraphDB triple count
curl -s -X POST http://localhost:7200/repositories/ontosage/sparql \
  -H "Content-Type: application/sparql-query" \
  -H "Accept: application/sparql-results+json" \
  -d "SELECT (COUNT(*) as ?n) WHERE { ?s ?p ?o }"

# Redis ping
docker exec ontosage-redis redis-cli ping   # should return: PONG

# MySQL connection test
docker exec ontosage-mysql mysql -u root -p"${MYSQL_ROOT_PASSWORD}" -e "SHOW DATABASES;"

# Code executor sandbox test
curl -s -X POST http://localhost:8002/execute \
  -H "Content-Type: application/json" \
  -d '{"code": "result = {\"status\": \"ok\"}", "timeout": 5}'
```

### End-to-End Query Test

Send a test query through the full pipeline:

```bash
curl -s -X POST http://localhost:8000/v1/chat/completions \
  -H "Content-Type: application/json" \
  -d '{
    "model": "ontosage",
    "messages": [{"role": "user", "content": "What sensors are available?"}]
  }' | python -m json.tool
```

A healthy response will include intent `"discovery"` and a list of sensor types. Any `"error"` key in the response indicates a pipeline failure.

---

## Log Access

### Tail Live Logs

```bash
# Orchestrator (most useful)
docker compose logs -f orchestrator

# RAG service
docker compose logs -f rag-service

# All services at once
docker compose logs -f

# Last 100 lines
docker compose logs --tail=100 orchestrator
```

### Log Filtering

```bash
# Find ERROR entries
docker compose logs orchestrator | grep -E "ERROR|CRITICAL"

# Find a specific trace ID
docker compose logs orchestrator | grep "abc-123-trace-id"

# Find SPARQL generation events
docker compose logs orchestrator | grep "\[sparql_agent\]"

# Find routing decisions
docker compose logs orchestrator | grep "_route_from_dialogue"
```

### Log Levels

The default log level is `INFO`. Set `LOG_LEVEL=DEBUG` in `.env` and restart the orchestrator for full trace output (shows all SPARQL queries, LLM prompts, and state transitions). **Never use DEBUG in production** — it logs query parameters.

---

## Backup and Restore

### What to Back Up

| Data | Service | Criticality | Frequency |
|------|---------|-------------|-----------|
| Building ontology (TTL) | GraphDB | Critical | After every ontology update |
| GraphDB repository | GraphDB | Critical | Daily |
| User accounts and RBAC | PostgreSQL | Critical | Daily |
| Sensor time-series | MySQL (Building 1) | High | Per your BMS data policy |
| Chat history | MongoDB | Medium | Weekly |
| Similarity index | GraphDB | Medium | After each rebuild |
| Redis state | Redis | Low | Not needed (ephemeral, 1h TTL) |

### Backup Procedures

#### GraphDB (Ontology)

```bash
# Full GraphDB backup (all repositories)
docker exec graphdb tar czf - /opt/graphdb/home/data > \
  graphdb-backup-$(date +%Y%m%d-%H%M).tar.gz

# Export a single repository as N-Quads
curl -s "http://localhost:7200/repositories/ontosage/statements?infer=false" \
  -H "Accept: application/n-quads" > ontosage-export-$(date +%Y%m%d).nq
```

#### PostgreSQL (Users)

```bash
docker exec postgres-user-data pg_dump \
  -U ontosage ontosage_users > \
  users-backup-$(date +%Y%m%d).sql
```

#### MySQL (Sensor Data)

```bash
docker exec ontosage-mysql mysqldump \
  -u root -p"${MYSQL_ROOT_PASSWORD}" \
  --single-transaction \
  sensordb > sensordb-backup-$(date +%Y%m%d).sql
```

#### MongoDB (Chat History)

```bash
docker exec ontosage-mongodb mongodump \
  --db=ontosage_chat \
  --out=/tmp/mongo-backup

docker cp ontosage-mongodb:/tmp/mongo-backup ./mongo-backup-$(date +%Y%m%d)
```

#### All Volumes (Single Command)

```bash
tar czf ontosage-volumes-$(date +%Y%m%d).tar.gz ./volumes/
```

### Restore Procedures

#### GraphDB Restore

```bash
# Stop GraphDB
docker compose stop graphdb

# Restore from backup
docker run --rm \
  -v $(pwd)/volumes/graphdb:/opt/graphdb/home/data \
  busybox tar xzf - < graphdb-backup-20240101-1200.tar.gz

# Restart GraphDB
docker compose start graphdb
```

#### PostgreSQL Restore

```bash
docker exec postgres-user-data psql -U ontosage -c "DROP DATABASE IF EXISTS ontosage_users;"
docker exec postgres-user-data psql -U ontosage -c "CREATE DATABASE ontosage_users;"
docker exec -i postgres-user-data psql -U ontosage ontosage_users < users-backup-20240101.sql
```

#### MySQL Restore

```bash
docker exec -i ontosage-mysql mysql \
  -u root -p"${MYSQL_ROOT_PASSWORD}" sensordb < sensordb-backup-20240101.sql
```

---

## Switching LLM Providers

### Switch to OpenAI

```bash
# Update .env
MODEL_PROVIDER=openai
OPENAI_API_KEY=sk-your-key
OPENAI_MODEL=gpt-4o-mini

# Restart orchestrator
docker compose restart orchestrator
```

Or using the PowerShell script (Windows):

```powershell
.\switch-provider.ps1 openai
```

### Switch to Local Ollama

```bash
MODEL_PROVIDER=local
docker compose --profile local-gpu restart orchestrator
```

Verify the switch:

```bash
docker compose logs orchestrator | grep "MODEL_PROVIDER"
```

---

## Rebuilding the Similarity Index

The GraphDB similarity index should be rebuilt after:
- New ontology data is loaded
- The building ontology is significantly updated

### Via SPARQL

```sparql
PREFIX similarity-index: <http://www.ontotext.com/graphdb/similarity/instance/>
PREFIX similarity: <http://www.ontotext.com/graphdb/similarity/>

INSERT DATA {
    similarity-index:bldg_index similarity:rebuildIndex "" .
}
```

Via curl:

```bash
curl -X POST "http://localhost:7200/repositories/ontosage/statements" \
  -H "Content-Type: application/sparql-update" \
  -d 'PREFIX similarity-index: <http://www.ontotext.com/graphdb/similarity/instance/>
      PREFIX similarity: <http://www.ontotext.com/graphdb/similarity/>
      INSERT DATA { similarity-index:bldg_index similarity:rebuildIndex "" . }'
```

---

## Updating OntoSage

```bash
# Pull latest changes
git pull origin main

# Rebuild changed services
docker compose build orchestrator rag-service

# Rolling restart (minimal downtime)
docker compose up -d --no-deps orchestrator rag-service
```

### Full Rebuild

```bash
docker compose down
git pull origin main
docker compose build
docker compose up -d
```

Data volumes are preserved across rebuilds.

---

## Performance Tuning

### GraphDB Heap Size

For large ontologies (> 500K triples):

```bash
GDB_HEAP_SIZE=8g
GDB_MAX_MEM=12g
docker compose restart graphdb
```

### Orchestrator Workers

For high concurrency (> 50 simultaneous users):

```yaml
# docker-compose.yml
orchestrator:
  command: uvicorn orchestrator.main:app --host 0.0.0.0 --port 8000 --workers 4
```

### Analytics Sandbox Memory

For complex analytics on large datasets:

```bash
CODE_EXECUTOR_MEMORY_LIMIT=2g
CODE_EXECUTOR_TIMEOUT=60
docker compose restart code-executor
```

---

## Troubleshooting

### Orchestrator Fails to Start

```bash
docker compose logs orchestrator | tail -50
```

Common causes:
- Redis not ready — wait 30 seconds and restart
- Missing env vars — check `OPENAI_API_KEY` or database passwords
- Port 8000 in use — change to `"8001:8000"` in `docker-compose.yml`

---

### GraphDB Out of Memory

```
java.lang.OutOfMemoryError: Java heap space
```

```bash
GDB_HEAP_SIZE=8g
GDB_MAX_MEM=10g
docker compose restart graphdb
```

---

### SPARQL Returns Empty Results

1. Check data is loaded: `curl http://localhost:7200/repositories/ontosage/size`
2. Test query directly in GraphDB Workbench
3. Verify `GRAPHDB_REPOSITORY` matches the repository that contains data
4. If RAG fallback is triggered, check: `curl http://localhost:8001/health`

---

### Analytics Code Execution Fails

```bash
docker compose logs code-executor | tail -30
docker stats ontosage-code-executor   # check if hitting memory limit
```

If the container is OOMing, increase `CODE_EXECUTOR_MEMORY_LIMIT`.

---

### LLM Responses Are Slow

For Ollama (local mode):
- Check GPU: `nvidia-smi`
- Verify model is loaded: `docker exec ollama ollama list`
- Switch to a smaller model: `OLLAMA_MODEL=llama3.2:7b`

For OpenAI:
- Check for 429 rate limiting in logs
- Increase `OPENAI_RETRY_DELAY_S=30`

---

### Open WebUI Cannot Connect to Orchestrator

```bash
# The URL must use the container name, not localhost
OPENAI_API_BASE_URL=http://ontosage-orchestrator:8000/v1   # correct
OPENAI_API_BASE_URL=http://localhost:8000/v1               # wrong
```

---

### Redis Connection Errors

```bash
docker exec ontosage-redis redis-cli ping   # should return PONG

# Check memory
docker exec ontosage-redis redis-cli info memory | grep used_memory_human

# Clear all sessions (last resort — users will be logged out)
docker exec ontosage-redis redis-cli FLUSHALL
```

---

### Circuit Breaker Open

If a downstream service is unavailable, the circuit breaker opens after repeated failures:

```
[circuit_breaker] Circuit OPEN for mysql_adapter — failing fast
```

The circuit resets automatically after 60 seconds when the service recovers. Force reset:

```bash
docker compose restart orchestrator
```

### Capability Semantic Routing Not Firing *(v3.1)*

**Symptom:** Off-ontology queries ("What are the fire procedures?") fall through to SPARQL or get a generic LLM response instead of a KB answer.

**Diagnostic steps:**

```bash
# 1. Verify the per-building Qdrant collection exists
curl -s http://localhost:6333/collections | jq '.result.collections[].name' | grep capability_

# Expected: capability_bldg1 (one per onboarded building)
# Missing: indexer didn't run — check next step

# 2. Check indexer status at startup
docker logs ontosage-orchestrator 2>&1 | grep capability_indexer

# Healthy:  status=indexed  entries=N  points=M  sha=<8-hex>
# Skipped:  status=skipped  reason=sha_match     (idempotent, good)
# Degraded: status=degraded reason=<error>       (see below)
# Missing:  no log line                          (capability.yaml absent for that building)

# 3. Inspect a stored point's yaml_sha (idempotency check)
curl -s 'http://localhost:6333/collections/capability_bldg1/points/scroll?limit=1' \
  | jq '.result.points[0].payload.yaml_sha'

# 4. Inspect router behaviour on a specific query
docker logs ontosage-orchestrator 2>&1 | grep "\[semantic-route\]"

# Look for lines like:
# [semantic-route] score=0.72 source=qdrant matches=3 → HARD override (capability)
# [semantic-route] score=0.58 source=qdrant matches=2 → SOFT override band
# [semantic-route] score=0.32 source=qdrant matches=0 → below threshold
```

**Common causes:**

| Symptom | Likely cause | Fix |
|---|---|---|
| `status=degraded reason=qdrant_unreachable` | Qdrant container down | `docker compose restart qdrant` |
| `status=degraded reason=embedding_api_down` | OpenAI API key invalid or rate-limited | check `OPENAI_API_KEY`; or switch to `EMBEDDING_PROVIDER=local` |
| `status=degraded reason=yaml_parse_error` | Malformed `capability.yaml` | validate with `python -c "import yaml; yaml.safe_load(open('input/bldg1/capability.yaml'))"` |
| `[semantic-route] score=<low>` for clear KB queries | Thresholds too high for embedding model | re-tune `building.yaml::capability_routing.threshold` and `override_min` (see [Capability Routing § Threshold calibration](CAPABILITY_ROUTING.md#threshold-calibration)) |

### Capability Returns Wrong KB Entry

Lower the threshold temporarily to see all candidates ranked:

```yaml
# input/<bldg>/building.yaml
capability_routing:
  threshold: 0.30      # see everything in logs
  override_min: 0.50
```

Restart, send the query, check logs for `[semantic-route]` lines showing per-entry scores. The router groups raw Qdrant points by `entry_id` with max-pool scoring.

### Provider Switch Didn't Trigger Collection Rebuild

When `EMBEDDING_PROVIDER` changes, `CapabilityIndexer` should detect the dimension mismatch and rebuild. If it doesn't:

```bash
# 1. Force delete the collection
curl -X DELETE http://localhost:6333/collections/capability_bldg1

# 2. Restart orchestrator — indexer will rebuild from capability.yaml
docker compose restart orchestrator

# 3. Verify new dimensions
curl -s http://localhost:6333/collections/capability_bldg1 \
  | jq '.result.config.params.vectors.size'
# Expected: 1536 (OpenAI) or 384 (local MiniLM)
```

---

## Disaster Recovery

### Complete Data Loss Recovery

1. `docker compose up -d` — start fresh
2. Restore GraphDB from `graphdb-backup-*.tar.gz`
3. Restore PostgreSQL from `users-backup-*.sql`
4. Restore MySQL from `sensordb-backup-*.sql`
5. Rebuild GraphDB similarity index (see [GraphDB Setup Guide](GRAPHDB_SETUP.md))
6. `docker compose restart` — pick up restored data

### RTO / RPO Targets

| Component | Recovery Time Objective | Recovery Point Objective |
|-----------|------------------------|-------------------------|
| Orchestrator | < 5 min | No data to recover |
| GraphDB ontology | 10–30 min | Last backup |
| User accounts | < 5 min | Last backup |
| Sensor time-series | < 30 min | Last backup |
| Conversation history | < 10 min | Last backup |
