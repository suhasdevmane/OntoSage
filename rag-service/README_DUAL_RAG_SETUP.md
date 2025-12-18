# Dual RAG Architecture Setup

This directory contains two separate RAG (Retrieval-Augmented Generation) service implementations that can be used interchangeably or compared side-by-side.

## 📁 Directory Structure

```
rag-service/
├── graphdbRAG/              # Traditional RAG with GraphDB + Qdrant + Similarity Indexing
│   ├── main.py              # FastAPI application
│   ├── graphdb_retriever.py # GraphDB SPARQL queries
│   ├── retrieval.py         # Similarity search retrieval
│   ├── embeddings.py        # Vector embeddings (sentence-transformers/OpenAI)
│   ├── smart_retrieval.py   # Intelligent retrieval orchestration
│   ├── ontology_ingestion.py# Ontology loading and processing
│   ├── Dockerfile           # Docker build for GraphDB RAG service
│   ├── requirements.txt     # Python dependencies
│   └── scripts/             # Initialization scripts
│       ├── init_qdrant.py   # Initialize Qdrant collections
│       └── ingest_ontology.py # Load ontology into Qdrant
│
└── GraphRAG/                # Microsoft GraphRAG - Entity/Relationship/Community Extraction
    ├── src/
    │   ├── main.py          # FastAPI application
    │   ├── indexer.py       # GraphRAG pipeline
    │   ├── query_engine.py  # Local/Global search
    │   └── models.py        # Pydantic models
    ├── config/
    │   └── settings.yaml    # GraphRAG configuration
    ├── inputs/              # Input documents directory
    ├── outputs/             # Generated knowledge graph (parquet files)
    ├── Dockerfile           # Docker build for GraphRAG service
    ├── requirements.txt     # Python dependencies
    └── scripts/
        ├── init_graphrag.py # Initialize GraphRAG workspace
        └── test_service.py  # Test suite
```

---

## 🔀 Approach Comparison

### **Approach 1: GraphDB RAG** (`graphdbRAG/`)
- **Port**: 8001
- **Architecture**: GraphDB (structured ontology) + Qdrant (vector embeddings) + Similarity Indexing
- **Best For**: 
  - Structured ontology queries with SPARQL
  - Ontology reasoning (RDFS/OWL)
  - Similarity search on building concepts
  - Hybrid SPARQL + vector retrieval
- **Dependencies**: 
  - GraphDB (localhost:7200) - Ontology storage with reasoning
  - Qdrant (localhost:6333) - Vector database
- **Data**: 
  - 93,237 triples loaded in GraphDB
  - Vector embeddings in Qdrant
- **Query Types**:
  - Structured SPARQL queries
  - Vector similarity search
  - Hybrid queries combining both

### **Approach 2: Microsoft GraphRAG** (`GraphRAG/`)
- **Port**: 8004
- **Architecture**: Entity extraction → Relationship mapping → Community detection
- **Best For**:
  - Unstructured text processing
  - Automatic knowledge graph generation from documents
  - Community-based knowledge discovery
  - No pre-existing ontology required
- **Dependencies**:
  - OpenAI API (GPT-4 for entity extraction, embeddings)
  - Redis (localhost:6379) - Background task management
- **Data**:
  - Dynamically generated from input text documents
  - Entities, relationships, communities stored as parquet files
- **Query Types**:
  - Local search: Fast, community-focused queries (< 5 seconds)
  - Global search: Comprehensive graph-wide queries (10-30 seconds)

---

## 🚀 How to Switch Between Approaches

### **Option 1: Use GraphDB RAG (Default - Currently Active)**

1. **Ensure services are enabled in `docker-compose.agentic.yml`**:
   ```yaml
   # GraphDB RAG Service (ENABLED)
   rag-service:
     build:
       dockerfile: rag-service/graphdbRAG/Dockerfile
     ports: ["8001:8001"]
     # ... (uncommented)

   # Qdrant (ENABLED - Required for GraphDB RAG)
   qdrant:
     image: qdrant/qdrant:latest
     # ... (uncommented)

   # Microsoft GraphRAG (DISABLED)
   # graphrag-service:
   #   build:
   #     dockerfile: rag-service/GraphRAG/Dockerfile
   #   # ... (commented out)
   ```

2. **Start services**:
   ```powershell
   docker-compose -f docker-compose.agentic.yml up -d graphdb qdrant rag-service
   ```

3. **Initialize Qdrant collections**:
   ```powershell
   docker-compose -f docker-compose.agentic.yml run --rm rag-service python -m scripts.init_qdrant
   ```

4. **Embed ontology to Qdrant**:
   ```powershell
   docker-compose -f docker-compose.agentic.yml run --rm rag-service python -m scripts.ingest_ontology
   ```

5. **Verify**:
   ```powershell
   curl http://localhost:8001/health
   curl http://localhost:6333/health
   ```

### **Option 2: Use Microsoft GraphRAG**

1. **Update `docker-compose.agentic.yml`**:
   ```yaml
   # Comment out GraphDB RAG Service
   # rag-service:
   #   build:
   #     dockerfile: rag-service/graphdbRAG/Dockerfile
   #   # ... (comment entire block)

   # Comment out Qdrant (not needed for GraphRAG)
   # qdrant:
   #   image: qdrant/qdrant:latest
   #   # ... (comment entire block)

   # Uncomment Microsoft GraphRAG Service
   graphrag-service:
     build:
       dockerfile: rag-service/GraphRAG/Dockerfile
     ports: ["8004:8004"]
     # ... (uncomment entire block)
   ```

2. **Configure OpenAI API key**:
   ```powershell
   cd rag-service/GraphRAG
   Copy-Item .env.example .env
   notepad .env  # Add OPENAI_API_KEY=sk-your-key-here
   ```

3. **Add input documents**:
   ```powershell
   # Copy building documentation to inputs/
   Copy-Item ..\..\data\bldg1\building_description.txt inputs\
   ```

4. **Start service**:
   ```powershell
   docker-compose -f docker-compose.agentic.yml up -d graphdb graphrag-service redis
   ```

5. **Run indexing**:
   ```powershell
   curl -X POST http://localhost:8004/index -H "Content-Type: application/json" -d '{}'
   ```

6. **Monitor progress**:
   ```powershell
   curl http://localhost:8004/graph/stats
   ```

7. **Test queries**:
   ```powershell
   # Local search
   Invoke-RestMethod -Uri "http://localhost:8004/query/local" -Method POST -ContentType "application/json" -Body '{"query": "What temperature sensors are in the building?"}'
   
   # Global search
   Invoke-RestMethod -Uri "http://localhost:8004/query/global" -Method POST -ContentType "application/json" -Body '{"query": "Describe the HVAC system"}'
   ```

### **Option 3: Run Both for Comparison**

You can run both services simultaneously on different ports to compare results:

1. **Uncomment both services** in `docker-compose.agentic.yml`

2. **Start all services**:
   ```powershell
   docker-compose -f docker-compose.agentic.yml up -d graphdb qdrant rag-service redis graphrag-service
   ```

3. **Initialize both**:
   ```powershell
   # GraphDB RAG
   docker-compose -f docker-compose.agentic.yml run --rm rag-service python -m scripts.init_qdrant
   docker-compose -f docker-compose.agentic.yml run --rm rag-service python -m scripts.ingest_ontology
   
   # Microsoft GraphRAG
   curl -X POST http://localhost:8004/index -H "Content-Type: application/json" -d '{}'
   ```

4. **Compare queries**:
   ```powershell
   # GraphDB RAG (Port 8001)
   Invoke-RestMethod -Uri "http://localhost:8001/retrieve" -Method POST -ContentType "application/json" -Body '{"query": "temperature sensors", "top_k": 5}'
   
   # Microsoft GraphRAG (Port 8004)
   Invoke-RestMethod -Uri "http://localhost:8004/query/local" -Method POST -ContentType "application/json" -Body '{"query": "temperature sensors"}'
   ```

---

## 📊 When to Use Each Approach

### Use **GraphDB RAG** when:
- ✅ You have a well-defined ontology (RDF/OWL)
- ✅ You need SPARQL query capabilities
- ✅ You require ontology reasoning (RDFS/OWL inference)
- ✅ You want hybrid semantic + vector search
- ✅ You have 93K+ triples already loaded
- ✅ You need similarity indexing on ontology concepts

### Use **Microsoft GraphRAG** when:
- ✅ You have unstructured text documents about buildings
- ✅ You want automatic entity/relationship extraction
- ✅ You need community detection for knowledge organization
- ✅ You don't have a pre-existing ontology
- ✅ You want GPT-4 powered entity extraction
- ✅ You need both local (fast) and global (comprehensive) search

### Use **Both (Hybrid)** when:
- ✅ You want to compare results from both approaches
- ✅ You have both structured ontology and unstructured text
- ✅ You need the best of both worlds: reasoning + entity extraction
- ✅ You're evaluating which approach works better for your use case

---

## 🔧 Troubleshooting

### GraphDB RAG Issues

**Service won't start:**
```powershell
# Check GraphDB is running
curl http://localhost:7200/rest/repositories

# Check Qdrant is running
curl http://localhost:6333/health

# Rebuild service
docker-compose -f docker-compose.agentic.yml build rag-service
docker-compose -f docker-compose.agentic.yml up -d rag-service
```

**Empty Qdrant collection:**
```powershell
# Re-run ingestion
docker-compose -f docker-compose.agentic.yml run --rm rag-service python -m scripts.ingest_ontology
```

### Microsoft GraphRAG Issues

**Indexing fails:**
- Check OpenAI API key in `.env`
- Ensure rate limits not exceeded
- Verify input documents exist in `inputs/`

**Service won't start:**
```powershell
# Check logs
docker-compose -f docker-compose.agentic.yml logs graphrag-service

# Rebuild
docker-compose -f docker-compose.agentic.yml build graphrag-service
docker-compose -f docker-compose.agentic.yml up -d graphrag-service
```

---

## 📚 Additional Documentation

- **GraphDB RAG**: See individual files in `graphdbRAG/` for implementation details
- **Microsoft GraphRAG**: See `GraphRAG/README_GRAPHRAG.md` and `GraphRAG/QUICKSTART.md`
- **Docker Compose**: See `docker-compose.agentic.yml` for full service definitions

---

## 🎯 Next Steps

1. **Choose your approach** based on the comparison above
2. **Update docker-compose.agentic.yml** to enable/disable services
3. **Follow the setup steps** for your chosen approach
4. **Test and compare** results if running both
5. **Integrate with orchestrator** once you've validated the approach

---

**Current Status:**
- ✅ GraphDB RAG: Active (Port 8001) with GraphDB + Qdrant
- ⏸️ Microsoft GraphRAG: Available (Port 8004, commented out)
- 🔄 Easy switching via docker-compose comments
