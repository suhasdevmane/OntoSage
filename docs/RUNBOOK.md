# Operations Runbook

Operational procedures for starting, stopping, validating, and maintaining OntoSage.

## Start Core Stack
```bash
docker-compose -f docker-compose.agentic.yml up -d --build orchestrator graphdb-rag-service code-executor whisper-stt frontend redis qdrant graphdb mysql
```

## Stop All
```bash
docker-compose -f docker-compose.agentic.yml down
```

## Health Checks
```bash
curl http://localhost:8000/health   # Orchestrator
curl http://localhost:8001/health   # RAG Service
curl http://localhost:8002/health   # Code Executor
curl http://localhost:3000          # Frontend
curl http://localhost:6333/health   # Qdrant
curl http://localhost:7200/rest/repositories  # GraphDB
```

## Logs
```bash
docker-compose -f docker-compose.agentic.yml logs -f orchestrator
```

## Backups
- Persistent data lives under `./volumes/*` and external `mysql-data`.
- Snapshot:
```powershell
Compress-Archive -Path .\volumes -DestinationPath .\backups\ontosage-$(Get-Date -Format 'yyyyMMdd-HHmmss').zip
```

## GPU Model Management (Ollama)
```bash
docker exec ollama-deepseek-r1 ollama pull deepseek-r1:32b
```

## Profiles
- Enable monitoring:
```bash
docker-compose -f docker-compose.agentic.yml --profile monitoring up -d prometheus grafana
```

## Common Issues
- Port conflicts: adjust host ports in compose
- Slow first start: model downloads and initial GraphDB setup
- OOM: lower `OLLAMA_GPU_LAYERS` or use a smaller model
