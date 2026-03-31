# RAG System Selection Guide

## Overview
OntoSage 2.0 supports **4 different RAG (Retrieval-Augmented Generation) approaches** for ontology context retrieval. Each approach has different strengths and use cases.

## Available RAG Systems

### 1. **graphdbRAG** (Currently Active) ✅
**Location:** `rag-service/graphdbRAG/`

**Technology:**
- GraphDB 10.7.4 with built-in similarity indexing
- Uses `bldg_index` similarity index
- 2-step retrieval: Entity retrieval → Bounded context (2-hop SPARQL)

**Strengths:**
- ✅ Native RDF/SPARQL support
- ✅ Fast entity retrieval via similarity index
- ✅ Structured graph context (preserves relationships)
- ✅ No need for separate vector database (Qdrant)
- ✅ Excellent for precise ontology queries

**Best For:**
- Sensor metadata queries ("what is the label of sensor X?")
- Relationship queries ("which sensors are in room Y?")
- Property lookups (UUID, location, type, etc.)

**Configuration:**
```env
RAG_SYSTEM=graphdbRAG
GRAPHDB_URL=http://graphdb:7200
GRAPHDB_REPOSITORY=bldg
GRAPHDB_SIMILARITY_INDEX=bldg_index
GRAPHDB_USE_SIMILARITY=true
```

**Test Query:**
```
"What is the label of the air quality level sensor 5.03?"
```

---

### 2. **GraphRAG** (Microsoft)
**Location:** `rag-service/GraphRAG/`

**Technology:**
- Microsoft GraphRAG library
- Entity-Relationship-Community extraction
- Local-to-Global reasoning

**Strengths:**
- ✅ Automatically builds knowledge graph from unstructured text
- ✅ Community detection for hierarchical understanding
- ✅ Good for complex multi-hop reasoning

**Best For:**
- Unstructured documentation
- Multi-document synthesis
- Complex analytical questions

**Configuration:**
```env
RAG_SYSTEM=GraphRAG
# Uncomment graphrag-service in docker-compose.agentic.yml
# Comment out graphdb-rag-service
```

**Setup Steps:**
1. Edit `docker-compose.agentic.yml`:
   - Comment out `graphdb-rag-service` (lines 293-331)
   - Uncomment `graphrag-service` (lines 338-375)
2. Update `.env`: `RAG_SYSTEM=GraphRAG`
3. Restart: `docker-compose -f docker-compose.agentic.yml up -d`

---

### 3. **RAG system** (Traditional Vector RAG)
**Location:** `rag-service/RAG system/`

**Technology:**
- Qdrant vector database
- Dense embeddings (sentence-transformers or OpenAI)
- Chunk-based retrieval

**Strengths:**
- ✅ Simple and fast
- ✅ Works with any text corpus
- ✅ Good semantic matching

**Best For:**
- General knowledge questions
- Document similarity search
- Semantic text retrieval

**Configuration:**
```env
RAG_SYSTEM=RAG_system
QDRANT_URL=http://qdrant:6333
EMBEDDING_PROVIDER=local  # or openai
```

**Setup Steps:**
1. Create new service in `docker-compose.agentic.yml` (TBD)
2. Implement API endpoint compatible with orchestrator
3. Update `.env`: `RAG_SYSTEM=RAG_system`

---

### 4. **RAG system advance** (Hybrid Retrieval)
**Location:** `rag-service/RAG system advance/`

**Technology:**
- Hybrid retrieval (dense + sparse)
- Re-ranking models
- Advanced filtering

**Strengths:**
- ✅ Best of both worlds (semantic + keyword)
- ✅ Re-ranking for precision
- ✅ Handles edge cases better

**Best For:**
- Production deployments
- High-precision requirements
- Complex queries requiring multiple retrieval strategies

**Configuration:**
```env
RAG_SYSTEM=RAG_system_advance
# Additional config TBD
```

**Setup Steps:**
1. Create new service definition (TBD)
2. Implement advanced retrieval pipeline
3. Update `.env`: `RAG_SYSTEM=RAG_system_advance`

---

## How to Switch RAG Systems

### Quick Switch (graphdbRAG → GraphRAG)

1. **Update docker-compose.agentic.yml:**
   ```yaml
   # Comment out:
   # graphdb-rag-service:
   #   ...
   
   # Uncomment:
   graphrag-service:
     build:
       context: .
       dockerfile: rag-service/GraphRAG/Dockerfile
     ...
   ```

2. **Update .env:**
   ```env
   RAG_SYSTEM=GraphRAG
   ```

3. **Restart services:**
   ```powershell
   docker-compose -f docker-compose.agentic.yml up -d --build
   ```

4. **Verify:**
   ```powershell
   curl http://localhost:8001/health
   ```

### Testing Each System

**Current System (graphdbRAG):**
```powershell
# Test similarity indexing directly
python test_graphdb_similarity.py

# Test via orchestrator
curl -X POST http://localhost:8000/chat `
  -H "Content-Type: application/json" `
  -d '{"message":"What is the label of the air quality level sensor 5.03?","conversation_id":"test"}'
```

**After Switching to GraphRAG:**
```powershell
# Test GraphRAG indexing
docker exec graphrag-service python -m graphrag.index --root /app/graphrag-service

# Test query
curl -X POST http://localhost:8004/query `
  -H "Content-Type: application/json" `
  -d '{"query":"What sensors are in room 5.03?"}'
```

---

## Performance Comparison Template

Use this template to compare RAG systems:

| Metric | graphdbRAG | GraphRAG | RAG_system | RAG_system_advance |
|--------|-----------|----------|------------|-------------------|
| **Latency** | ? | ? | ? | ? |
| **Accuracy** | ? | ? | ? | ? |
| **Context Quality** | ? | ? | ? | ? |
| **Setup Complexity** | Medium | High | Low | High |
| **Memory Usage** | ~4GB | ~8GB | ~2GB | ~6GB |

### Test Questions for Comparison

1. **Metadata Query:** "What is the label of the air quality level sensor 5.03?"
2. **Relationship Query:** "Which sensors are located in room 5.26?"
3. **Property Query:** "What is the UUID of the CO2 sensor in zone 5.03?"
4. **Analytics Query:** "Show me the average temperature readings for all sensors."
5. **Complex Query:** "Which rooms have both CO2 and temperature sensors?"

---

## Current Status

✅ **graphdbRAG**: Fully configured and tested
⚠️ **GraphRAG**: Service defined, needs testing
⚠️ **RAG_system**: Needs service definition
⚠️ **RAG_system_advance**: Needs service definition

## Next Steps

1. ✅ Test graphdbRAG with similarity indexing
2. ⏳ Document GraphRAG service integration
3. ⏳ Create service definitions for RAG_system and RAG_system_advance
4. ⏳ Run comparative performance tests
5. ⏳ Update orchestrator to route based on `RAG_SYSTEM` env variable

---

## Notes

- All RAG systems should expose the same API contract for compatibility with the orchestrator
- The orchestrator currently expects the `/graphdb/retrieve` endpoint
- Consider creating a unified `/retrieve` endpoint that routes to the active RAG system
- Monitor performance metrics to choose the best system for production

