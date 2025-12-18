# OntoSage 2.0 - DeepSeek-R1:32b Deployment Guide

**Hardware Configuration:**
- RAM: 64GB
- GPU: NVIDIA RTX 4090 16GB
- Model: DeepSeek-R1:32b (~20GB)
- Ontology: bldg1_protege.ttl (9,184 triples)
- Database: Existing MySQL volume with sensor data

---

## 🚀 Quick Start (Automated)

### Option 1: Full Automated Deployment

```powershell
cd OntoBot2.0
pwsh scripts/deploy.ps1
```

This will:
1. Create volume directories
2. Start all infrastructure services
3. Pull DeepSeek-R1:32b model (~20GB, 10-20 min)
4. Load ontology to Fuseki (9,184 triples)
5. Build and start OntoSage services
6. Run health checks

**Total time:** ~30-40 minutes

### Option 2: Skip Model Download (If Already Downloaded)

```powershell
pwsh scripts/deploy.ps1 -SkipModelPull
```

### Option 3: Skip Ontology Load (If Already Loaded)

```powershell
pwsh scripts/deploy.ps1 -SkipOntologyLoad
```

### Option 4: Clean Start (Remove All Volumes)

```powershell
pwsh scripts/deploy.ps1 -Clean
```

---

## 📋 Manual Deployment (Step-by-Step)

### 1. Create Volume Directories

```powershell
cd OntoBot2.0
mkdir volumes\ollama, volumes\qdrant, volumes\redis, volumes\fuseki, volumes\mongo, volumes\artifacts
```

### 2. Start Infrastructure Services

```powershell
docker-compose -f docker-compose.agentic.yml up -d mysql redis qdrant fuseki ollama mongo file-server
```

Wait 30 seconds for services to initialize.

### 3. Pull DeepSeek-R1:32b Model

```powershell
docker exec ollama-deepseek-r1 ollama pull deepseek-r1:32b
```

**Download size:** ~20GB  
**Time:** 10-20 minutes (depending on network)  
**Storage:** Model saved to `.\volumes\ollama\`

### 4. Load Ontology to Fuseki

```powershell
pwsh scripts\load-fuseki.ps1
```

This creates dataset "abacws" and uploads 9,184 triples from `bldg1_protege.ttl`.

**Verify:**
- SPARQL endpoint: http://localhost:3030/dataset.html?ds=/abacws
- Admin password: `Admin@12345`

### 5. Build OntoSage Services

```powershell
docker-compose -f docker-compose.agentic.yml up -d --build orchestrator rag-service code-executor whisper-stt frontend
```

**First build:** 5-10 minutes  
**Subsequent builds:** 1-2 minutes

### 6. Initialize Qdrant Collections (Optional)

```powershell
docker-compose -f docker-compose.agentic.yml run --rm rag-service python -m scripts.init_qdrant
```

### 7. Embed Ontology to Qdrant (Optional)

```powershell
docker-compose -f docker-compose.agentic.yml run --rm rag-service python -m scripts.ingest_ontology
```

---

## ✅ Verify Deployment

### Automated Testing

```powershell
pwsh scripts\test-deployment.ps1
```

Tests:
- ✅ Service health (9 services)
- ✅ DeepSeek-R1:32b model loaded
- ✅ GPU acceleration enabled
- ✅ Fuseki ontology (9,184 triples)
- ✅ MySQL sensor data
- ✅ Qdrant collections
- ✅ Chat API with DeepSeek

### Manual Health Checks

```powershell
# Check all containers
docker-compose -f docker-compose.agentic.yml ps

# Test orchestrator
curl http://localhost:8000/health

# Test RAG service
curl http://localhost:8001/health

# Test code executor
curl http://localhost:8002/health

# Test Whisper STT
curl http://localhost:8003/health

# Test Fuseki
curl http://localhost:3030/$/ping

# Test Qdrant
curl http://localhost:6333/health

# Check GPU usage
docker exec ollama-deepseek-r1 nvidia-smi
```

---

## 🌐 Access Points

| Service | URL | Credentials |
|---------|-----|-------------|
| **Frontend** | http://localhost:3000 | - |
| **Orchestrator API** | http://localhost:8000/docs | - |
| **RAG Service** | http://localhost:8001/docs | - |
| **Code Executor** | http://localhost:8002/docs | - |
| **Whisper STT** | http://localhost:8003/docs | - |
| **Fuseki SPARQL** | http://localhost:3030/dataset.html | admin / Admin@12345 |
| **Qdrant Dashboard** | http://localhost:6333/dashboard | - |
| **MySQL** | localhost:3307 | root / mysql |

---

## 🧪 Test Queries

### SPARQL (Fuseki)

**Count sensors:**
```powershell
curl -X POST http://localhost:3030/abacws/sparql --data-urlencode "query=PREFIX brick: <https://brickschema.org/schema/Brick#> SELECT (COUNT(?sensor) AS ?count) WHERE { ?sensor a brick:Sensor }"
```

**List all sensors:**
```powershell
curl -X POST http://localhost:3030/abacws/sparql --data-urlencode "query=PREFIX brick: <https://brickschema.org/schema/Brick#> SELECT ?sensor ?type WHERE { ?sensor a brick:Sensor . ?sensor a ?type } LIMIT 10"
```

### SQL (MySQL)

**Count sensor readings:**
```powershell
docker exec mysql-bldg1 mysql -uroot -pmysql -e "SELECT COUNT(*) FROM sensordb.ts_kv;"
```

**Show tables:**
```powershell
docker exec mysql-bldg1 mysql -uroot -pmysql -e "SHOW TABLES FROM sensordb;"
```

**Sample sensor data:**
```powershell
docker exec mysql-bldg1 mysql -uroot -pmysql -e "SELECT * FROM sensordb.ts_kv LIMIT 5;"
```

### Chat API (DeepSeek)

**Simple test:**
```powershell
curl -X POST http://localhost:8000/chat -H "Content-Type: application/json" -d '{\"message\":\"Hello! What can you help me with?\",\"conversation_id\":\"test\"}'
```

**SPARQL generation test:**
```powershell
curl -X POST http://localhost:8000/chat -H "Content-Type: application/json" -d '{\"message\":\"Show me all temperature sensors in the building\",\"conversation_id\":\"test\"}'
```

**Analytics test:**
```powershell
curl -X POST http://localhost:8000/chat -H "Content-Type: application/json" -d '{\"message\":\"Calculate average temperature for the past 7 days\",\"conversation_id\":\"test\"}'
```

---

## 📁 Data Persistence

All data is stored in local directories:

```

└── volumes/
    ├── ollama/      # DeepSeek-R1:32b model (~20GB)
    ├── fuseki/      # Brick ontology (9,184 triples)
    ├── qdrant/      # Embedded ontology vectors
    ├── redis/       # Conversation state
    ├── mongo/       # Chat history
    └── artifacts/   # Generated files (plots, CSVs)
```

**Backup:**
```powershell
Compress-Archive -Path .\volumes -DestinationPath .\backups\ontosage-$(Get-Date -Format 'yyyyMMdd-HHmmss').zip
```

**Restore:**
```powershell
Expand-Archive -Path .\backups\ontosage-YYYYMMDD-HHMMSS.zip -DestinationPath .
```

**External Volumes:**
- `mysql-data` - Reused from existing OntoBot deployment (sensor UUIDs match ontology)

---

## 📊 Monitoring

### View Logs

```powershell
# All services
docker-compose -f docker-compose.agentic.yml logs -f

# Specific service
docker-compose -f docker-compose.agentic.yml logs -f orchestrator
docker-compose -f docker-compose.agentic.yml logs -f ollama
docker-compose -f docker-compose.agentic.yml logs -f rag-service

# Last 100 lines
docker-compose -f docker-compose.agentic.yml logs --tail=100 orchestrator
```

### Resource Usage

```powershell
# Container stats
docker stats

# GPU usage
docker exec ollama-deepseek-r1 nvidia-smi

# Disk usage
docker system df
```

### Service Status

```powershell
# List all containers
docker-compose -f docker-compose.agentic.yml ps

# Check specific service
docker inspect ollama-deepseek-r1
docker inspect jena-fuseki
```

---

## 🔧 Troubleshooting

### DeepSeek Model Not Loading

**Symptom:** Chat API times out or returns errors

**Solution 1:** Check if model is downloaded
```powershell
docker exec ollama-deepseek-r1 ollama list
```

**Solution 2:** Pull model manually
```powershell
docker exec ollama-deepseek-r1 ollama pull deepseek-r1:32b
```

**Solution 3:** Check GPU availability
```powershell
docker exec ollama-deepseek-r1 nvidia-smi
```

If GPU not detected:
1. Install nvidia-docker2: https://docs.nvidia.com/datacenter/cloud-native/container-toolkit/install-guide.html
2. Restart Docker daemon
3. Recreate ollama container

### Fuseki Dataset Not Created

**Symptom:** SPARQL queries fail with "Dataset not found"

**Solution:**
```powershell
pwsh scripts\load-fuseki.ps1
```

Or create manually:
1. Open http://localhost:3030
2. Login: admin / Admin@12345
3. Create dataset "abacws" (TDB2)
4. Upload `data\bldg1\trial\dataset\bldg1_protege.ttl`

### MySQL Connection Refused

**Symptom:** Orchestrator logs show "Can't connect to MySQL server"

**Solution:** Check if mysql-data volume exists
```powershell
docker volume ls | Select-String mysql-data
```

If not found, the external volume doesn't exist. You need to either:
1. Use existing mysqlserver container (if running)
2. Create new mysql-data volume
3. Import sensor data

### Qdrant Collections Empty

**Symptom:** RAG service returns no results

**Solution:** Initialize and embed ontology
```powershell
docker-compose -f docker-compose.agentic.yml run --rm rag-service python -m scripts.init_qdrant
docker-compose -f docker-compose.agentic.yml run --rm rag-service python -m scripts.ingest_ontology
```

### Out of Memory (GPU)

**Symptom:** Ollama crashes or model inference very slow

**Solution:** Reduce GPU layers in .env
```
OLLAMA_GPU_LAYERS=25  # Reduce from 33
```

Then restart:
```powershell
docker-compose -f docker-compose.agentic.yml restart ollama
```

### Port Already in Use

**Symptom:** "Bind for 0.0.0.0:XXXX failed: port is already allocated"

**Solution:** Check what's using the port
```powershell
netstat -ano | Select-String :3030  # Replace with your port
```

Stop conflicting service or change port in docker-compose.agentic.yml

---

## 🛑 Stop & Clean

### Stop All Services

```powershell
docker-compose -f docker-compose.agentic.yml down
```

### Stop and Remove Volumes (Clean Slate)

```powershell
docker-compose -f docker-compose.agentic.yml down -v
```

**Warning:** This removes all data except external mysql-data volume.

### Remove Specific Service

```powershell
docker-compose -f docker-compose.agentic.yml stop orchestrator
docker-compose -f docker-compose.agentic.yml rm -f orchestrator
```

---

## 🔄 Update Workflow

### Rebuild After Code Changes

```powershell
# Rebuild specific service
docker-compose -f docker-compose.agentic.yml up -d --build orchestrator

# Rebuild all Python services
docker-compose -f docker-compose.agentic.yml up -d --build orchestrator rag-service code-executor whisper-stt

# Rebuild frontend
docker-compose -f docker-compose.agentic.yml up -d --build frontend
```

### Update DeepSeek Model

```powershell
# Pull latest version
docker exec ollama-deepseek-r1 ollama pull deepseek-r1:32b

# Remove old version
docker exec ollama-deepseek-r1 ollama rm deepseek-r1:32b-old
```

### Reload Ontology

```powershell
pwsh scripts\load-fuseki.ps1
```

---

## 📚 Next Steps

1. **Add Functions:** Implement custom analytics in `orchestrator/agents/analytics_agent.py`
2. **Extend Ontology:** Add more sensors/spaces to `bldg1_protege.ttl`
3. **Custom Queries:** Create query templates in `orchestrator/templates/`
4. **Fine-tune RAG:** Adjust chunking/embeddings in `rag-service/config.py`
5. **Monitor Performance:** Enable Prometheus/Grafana with `--profile monitoring`

---

## 📞 Support

**Logs:**
```powershell
docker-compose -f docker-compose.agentic.yml logs -f
```

**Health Check:**
```powershell
pwsh scripts\test-deployment.ps1
```

**Documentation:**
- Architecture: `AGENTIC_ARCHITECTURE.md`
- Migration: `MIGRATION_ROADMAP.md`
- Implementation: `IMPLEMENTATION_GUIDE.md`

---

## 🎯 Performance Tuning

### DeepSeek-R1:32b Settings

**For 16GB GPU (RTX 4090):**
```env
OLLAMA_GPU_LAYERS=33        # Use all layers on GPU
OLLAMA_NUM_GPU=1            # Single GPU
LLM_TEMPERATURE=0.1         # More deterministic
LLM_MAX_TOKENS=4096         # Longer responses
LLM_CONTEXT_WINDOW=32768    # Full context
```

**For 8GB GPU:**
```env
OLLAMA_GPU_LAYERS=20        # Reduce layers
OLLAMA_NUM_GPU=1
```

### Fuseki JVM Settings

**For 64GB RAM:**
```yaml
JVM_ARGS=-Xmx8g  # 8GB heap (current)
```

**For 32GB RAM:**
```yaml
JVM_ARGS=-Xmx4g  # 4GB heap
```

### Qdrant Performance

**For large ontologies (10K+ triples):**
```yaml
QDRANT__SERVICE__MAX_SEARCH_RESULTS=100
```

---

**Deployment Date:** $(Get-Date -Format "yyyy-MM-dd HH:mm:ss")  
**OntoSage Version:** 2.0  
**Model:** DeepSeek-R1:32b  
**Hardware:** 64GB RAM + NVIDIA RTX 4090 16GB
