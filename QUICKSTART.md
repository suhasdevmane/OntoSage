# OntoSage 2.0 - Quick Start Guide

## 🚀 One-Command Startup

### Option 1: Automated Script (Recommended)
```powershell
# Run the complete startup script
pwsh scripts/start-ontosage.ps1
```
**What it does:**
- ✅ Creates all required directories
- ✅ Builds Docker images
- ✅ Starts services in correct order
- ✅ Downloads DeepSeek-R1:32b model (~20GB)
- ✅ Initializes Qdrant collections
- ✅ Ingests ontology with generic extraction
- ✅ Performs health checks
- ✅ Displays access URLs

**Time:** 15-20 minutes first run, 2-3 minutes subsequent runs

---

### Option 2: Manual Docker Compose
```powershell
# Navigate to root directory
cd c:\Users\suhas\Documents\GitHub\OntoBot

# Start everything
docker-compose -f docker-compose.agentic.yml up -d

# Wait for services to initialize (2-3 minutes)
Start-Sleep -Seconds 180

# Initialize Qdrant collections
docker-compose -f docker-compose.agentic.yml run --rm rag-service python -m scripts.init_qdrant

# Ingest ontology data (includes generic extraction)
docker-compose -f docker-compose.agentic.yml run --rm rag-service python -m scripts.ingest_ontology

# Download DeepSeek model (if not already downloaded)
docker exec ollama-deepseek-r1 ollama pull deepseek-r1:32b
```

---

### Option 3: Ultra-Quick (If already initialized)
```powershell
# Just start everything
docker-compose -f docker-compose.agentic.yml up -d
```
Use this if you've already:
- Downloaded the DeepSeek model
- Initialized Qdrant collections
- Ingested the ontology

---

## 🌐 Access Your System

Once started, access these URLs:

| Service | URL | Description |
|---------|-----|-------------|
| **Frontend** | http://localhost:3000 | Chat UI - Main interface |
| **Orchestrator** | http://localhost:8000 | API endpoint |
| **Fuseki** | http://localhost:3030 | SPARQL endpoint |
| **Qdrant** | http://localhost:6333/dashboard | Vector database |
| **3D Visualiser** | http://localhost:8090 | Building visualization |
| **ThingsBoard** | http://localhost:8082 | IoT platform |
| **pgAdmin** | http://localhost:5050 | Database admin |

---

## ✅ Verify Everything Works

### Test 1: Basic Chat
1. Open http://localhost:3000
2. Ask: **"What is the location of Abacws building?"**
3. Expected: Address with full details

### Test 2: Custom Property (Generic Extraction)
Ask: **"Who designed the Abacws building?"**
Expected: Answer about architect (from `rec:architectedBy`)

### Test 3: Sensor Query
Ask: **"How many CO2 sensors are in the building?"**
Expected: Count of CO2 sensors

### Test 4: Health Check
```powershell
# Check all services
docker-compose -f docker-compose.agentic.yml ps

# Should show all services as "Up" and "healthy"
```

---

## 🛠️ Common Commands

### View Logs
```powershell
# Orchestrator logs
docker-compose -f docker-compose.agentic.yml logs -f orchestrator

# RAG service logs
docker-compose -f docker-compose.agentic.yml logs -f rag-service

# All services
docker-compose -f docker-compose.agentic.yml logs -f
```

### Stop System
```powershell
# Graceful shutdown
docker-compose -f docker-compose.agentic.yml down

# Force stop
docker-compose -f docker-compose.agentic.yml down -v  # Removes volumes too
```

### Restart Services
```powershell
# Restart specific service
docker-compose -f docker-compose.agentic.yml restart orchestrator

# Restart all
docker-compose -f docker-compose.agentic.yml restart
```

### Re-ingest Ontology
```powershell
# Full re-ingestion (TBox + ABox)
docker-compose -f docker-compose.agentic.yml run --rm rag-service python -m scripts.ingest_ontology

# Only building instances (ABox)
docker-compose -f docker-compose.agentic.yml run --rm rag-service python -m scripts.ingest_ontology --abox-only

# Only schema (TBox)
docker-compose -f docker-compose.agentic.yml run --rm rag-service python -m scripts.ingest_ontology --tbox-only
```

---

## 🔧 Troubleshooting

### Issue: "Connection refused" errors
**Solution:** Wait 2-3 minutes for services to fully initialize
```powershell
# Check service status
docker-compose -f docker-compose.agentic.yml ps
```

### Issue: GPU not detected
**Solution:** Ensure nvidia-docker2 is installed
```powershell
# Test GPU access
docker exec ollama-deepseek-r1 nvidia-smi

# If fails, install: https://docs.nvidia.com/datacenter/cloud-native/container-toolkit/install-guide.html
```

### Issue: Out of memory
**Solution:** Reduce GPU layers or use smaller model
```powershell
# Edit docker-compose.agentic.yml
# Change: OLLAMA_GPU_LAYERS=-1
# To:     OLLAMA_GPU_LAYERS=20  (reduce if needed)
```

### Issue: Model download slow
**Solution:** Download offline and import
```powershell
# On machine with good internet:
ollama pull deepseek-r1:32b

# Copy model files to your machine, then:
docker exec ollama-deepseek-r1 ollama list
```

### Issue: Qdrant corrupted
**Solution:** Clear and re-initialize
```powershell
# Stop Qdrant
docker-compose -f docker-compose.agentic.yml stop qdrant

# Remove data
Remove-Item -Recurse -Force .\volumes\qdrant

# Restart and re-initialize
docker-compose -f docker-compose.agentic.yml up -d qdrant
Start-Sleep -Seconds 10
docker-compose -f docker-compose.agentic.yml run --rm rag-service python -m scripts.init_qdrant
docker-compose -f docker-compose.agentic.yml run --rm rag-service python -m scripts.ingest_ontology
```

---

## 📊 System Requirements

### Minimum
- **CPU:** 8 cores
- **RAM:** 32GB
- **GPU:** NVIDIA with 12GB VRAM
- **Storage:** 100GB SSD
- **OS:** Windows 10/11, WSL2 enabled

### Recommended (Current Setup)
- **CPU:** AMD Ryzen 9 or Intel i9
- **RAM:** 64GB
- **GPU:** NVIDIA RTX 4090 (16GB VRAM)
- **Storage:** 500GB NVMe SSD
- **OS:** Windows 11 Pro with WSL2

---

## 🎯 Key Features

### ✅ Generic Extraction
- Works with **ANY TTL file**
- Extracts **ALL triples** automatically
- No code changes needed when ontology changes
- Enterprise-grade approach (Google Knowledge Graph inspired)

### ✅ Semantic Search
- Find information about **ANY property**
- Query **custom relationships**
- Natural language understanding
- Context-aware responses

### ✅ GPU Acceleration
- DeepSeek-R1:32b runs on GPU
- Model kept in VRAM (24h keep-alive)
- Fast inference (4-6 seconds)
- Optimized for RTX 4090

### ✅ Multi-Building Support
- Easy to switch between buildings
- Just change TTL file and re-ingest
- No code modifications required

---

## 📚 Documentation

- **Generic Extraction Implementation:** `GENERIC_EXTRACTION_IMPLEMENTATION.md`
- **RAG Fix Summary:** `RAG_FIX_SUMMARY.md`
- **Ingestion Files Analysis:** `INGESTION_FILES_ANALYSIS.md`
- **Semantic Architecture:** `SEMANTIC_ONTOLOGY_ARCHITECTURE.md`
- **Full Docker Compose Guide:** See comments in `docker-compose.agentic.yml`

---

## 🔄 Replace Ontology (Zero Code Changes)

### Step 1: Prepare new TTL file
```powershell
# Copy your new ontology to data directory
cp /path/to/new_building.ttl ./data/bldg1/trial/dataset/
```

### Step 2: Update config (optional)
Edit `shared/config.py`:
```python
BLDG1_ABOX_FILE = "trial/dataset/new_building.ttl"
```

### Step 3: Re-ingest
```powershell
docker-compose -f docker-compose.agentic.yml run --rm rag-service python -m scripts.ingest_ontology --abox-only
```

### Step 4: Restart orchestrator
```powershell
docker-compose -f docker-compose.agentic.yml restart orchestrator
```

**Done!** System now works with new ontology. No code changes needed.

---

## 💡 Pro Tips

1. **Keep Model in GPU:** Default `OLLAMA_KEEP_ALIVE=24h` prevents reload delays
2. **Monitor Memory:** Use `nvidia-smi` to watch GPU usage
3. **Batch Questions:** System is optimized for conversational flow
4. **Use Semantic Mode:** Set `ONTOLOGY_QUERY_MODE=semantic` for best results
5. **Backup Volumes:** Regularly backup `./volumes` directory

---

## 🆘 Getting Help

**Check Logs:**
```powershell
# Orchestrator (main service)
docker logs ontosage-orchestrator --tail 100

# RAG service (retrieval)
docker logs rag-service --tail 100

# All services
docker-compose -f docker-compose.agentic.yml logs --tail 50
```

**Health Status:**
```powershell
# Individual service
curl http://localhost:8000/health

# All services
docker-compose -f docker-compose.agentic.yml ps
```

**System Info:**
```powershell
# GPU status
docker exec ollama-deepseek-r1 nvidia-smi

# Ollama models
docker exec ollama-deepseek-r1 ollama list

# Qdrant collections
curl http://localhost:6333/collections
```

---

**Ready to start? Run:**
```powershell
pwsh scripts/start-ontosage.ps1
```

🎉 **Enjoy your enterprise-grade ontology-agnostic chatbot!**
