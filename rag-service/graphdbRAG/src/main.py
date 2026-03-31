"""
GraphRAG Service - Main FastAPI Application
Handles entity extraction, relationship mapping, and community detection
Using Microsoft GraphRAG for knowledge graph generation
"""
import sys
sys.path.append('/app')

from fastapi import FastAPI, HTTPException, UploadFile, File, BackgroundTasks
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
import uvicorn
from datetime import datetime
from pathlib import Path
from typing import Optional, List, Dict, Any
import asyncio

from shared.config import settings
from shared.models import HealthResponse
from shared.utils import get_logger

from .indexer import GraphRAGIndexer
from .query_engine import GraphRAGQueryEngine
from .models import (
    IndexRequest,
    IndexResponse,
    QueryRequest,
    QueryResponse,
    GraphStatsResponse
)

# Initialize logger
logger = get_logger(__name__)

# Create FastAPI app
app = FastAPI(
    title="GraphRAG Service",
    description="Entity-Relationship-Community extraction using Microsoft GraphRAG",
    version="1.0.0"
)

# Add CORS
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Initialize GraphRAG components
indexer: Optional[GraphRAGIndexer] = None
query_engine: Optional[GraphRAGQueryEngine] = None

@app.on_event("startup")
async def startup_event():
    """Initialize GraphRAG services on startup"""
    global indexer, query_engine
    
    logger.info("🚀 Starting GraphRAG Service")
    logger.info(f"Input directory: {Path('/app/graphrag-service/inputs').absolute()}")
    logger.info(f"Output directory: {Path('/app/graphrag-service/outputs').absolute()}")
    
    try:
        # Initialize indexer
        indexer = GraphRAGIndexer()
        logger.info("✅ GraphRAG Indexer initialized")
        
        # Initialize query engine
        query_engine = GraphRAGQueryEngine()
        logger.info("✅ GraphRAG Query Engine initialized")
        
        # Check for existing index
        if indexer.has_existing_index():
            logger.info("📊 Found existing GraphRAG index")
            stats = await indexer.get_index_stats()
            logger.info(f"  - Entities: {stats.get('entities', 0)}")
            logger.info(f"  - Relationships: {stats.get('relationships', 0)}")
            logger.info(f"  - Communities: {stats.get('communities', 0)}")
        else:
            logger.info("⚠️  No existing index found. Use /index endpoint to create one.")
            
    except Exception as e:
        logger.error(f"❌ Failed to initialize GraphRAG: {e}")
        raise

@app.on_event("shutdown")
async def shutdown_event():
    """Cleanup on shutdown"""
    logger.info("👋 Shutting down GraphRAG Service")

# ====================== Health Check ======================
@app.get("/health", response_model=HealthResponse)
async def health_check():
    """Health check endpoint"""
    return HealthResponse(
        status="healthy",
        service="graphrag-service",
        timestamp=datetime.now().isoformat(),
        details={
            "indexer_ready": indexer is not None,
            "query_engine_ready": query_engine is not None,
            "has_index": indexer.has_existing_index() if indexer else False
        }
    )

# ====================== Indexing Endpoints ======================
@app.post("/index", response_model=IndexResponse)
async def create_index(
    request: IndexRequest,
    background_tasks: BackgroundTasks
):
    """
    Create GraphRAG index from input documents
    Extracts entities, relationships, and communities
    """
    if not indexer:
        raise HTTPException(status_code=503, detail="Indexer not initialized")
    
    try:
        logger.info(f"Starting indexing process for: {request.input_path or 'default inputs'}")
        
        # Start indexing in background
        task_id = await indexer.start_indexing(
            input_path=request.input_path,
            config_override=request.config_override
        )
        
        return IndexResponse(
            task_id=task_id,
            status="started",
            message="Indexing process started in background",
            estimated_time="5-15 minutes depending on input size"
        )
        
    except Exception as e:
        logger.error(f"Indexing failed: {e}")
        raise HTTPException(status_code=500, detail=str(e))

@app.get("/index/status/{task_id}")
async def get_index_status(task_id: str):
    """Get indexing task status"""
    if not indexer:
        raise HTTPException(status_code=503, detail="Indexer not initialized")
    
    try:
        status = await indexer.get_task_status(task_id)
        return status
    except Exception as e:
        logger.error(f"Failed to get task status: {e}")
        raise HTTPException(status_code=404, detail="Task not found")

@app.get("/graph/stats", response_model=GraphStatsResponse)
async def get_graph_stats():
    """Get statistics about the generated knowledge graph"""
    if not indexer:
        raise HTTPException(status_code=503, detail="Indexer not initialized")
    
    try:
        stats = await indexer.get_index_stats()
        return GraphStatsResponse(**stats)
    except Exception as e:
        logger.error(f"Failed to get graph stats: {e}")
        raise HTTPException(status_code=500, detail=str(e))

# ====================== Query Endpoints ======================
@app.post("/query/local", response_model=QueryResponse)
async def local_query(request: QueryRequest):
    """
    Perform local search query
    Fast, focused search within specific communities
    """
    if not query_engine:
        raise HTTPException(status_code=503, detail="Query engine not initialized")
    
    try:
        logger.info(f"Local query: {request.query}")
        
        result = await query_engine.local_search(
            query=request.query,
            community_level=request.community_level,
            response_type=request.response_type
        )
        
        return QueryResponse(
            query=request.query,
            answer=result["answer"],
            context=result.get("context", []),
            entities=result.get("entities", []),
            relationships=result.get("relationships", []),
            communities=result.get("communities", []),
            query_type="local"
        )
        
    except Exception as e:
        logger.error(f"Local query failed: {e}")
        raise HTTPException(status_code=500, detail=str(e))

@app.post("/query/global", response_model=QueryResponse)
async def global_query(request: QueryRequest):
    """
    Perform global search query
    Comprehensive search across entire knowledge graph
    """
    if not query_engine:
        raise HTTPException(status_code=503, detail="Query engine not initialized")
    
    try:
        logger.info(f"Global query: {request.query}")
        
        result = await query_engine.global_search(
            query=request.query,
            community_level=request.community_level,
            response_type=request.response_type
        )
        
        return QueryResponse(
            query=request.query,
            answer=result["answer"],
            context=result.get("context", []),
            entities=result.get("entities", []),
            relationships=result.get("relationships", []),
            communities=result.get("communities", []),
            query_type="global"
        )
        
    except Exception as e:
        logger.error(f"Global query failed: {e}")
        raise HTTPException(status_code=500, detail=str(e))

# ====================== Data Management ======================
@app.post("/upload")
async def upload_document(file: UploadFile = File(...)):
    """Upload document to inputs directory"""
    try:
        input_dir = Path("/app/graphrag-service/inputs")
        input_dir.mkdir(parents=True, exist_ok=True)
        
        file_path = input_dir / file.filename
        
        with open(file_path, "wb") as f:
            content = await file.read()
            f.write(content)
        
        logger.info(f"Uploaded file: {file.filename}")
        
        return {
            "filename": file.filename,
            "size": len(content),
            "path": str(file_path)
        }
        
    except Exception as e:
        logger.error(f"Upload failed: {e}")
        raise HTTPException(status_code=500, detail=str(e))

@app.get("/documents")
async def list_documents():
    """List all documents in inputs directory"""
    try:
        input_dir = Path("/app/graphrag-service/inputs")
        files = []
        
        if input_dir.exists():
            for file_path in input_dir.glob("*"):
                if file_path.is_file():
                    files.append({
                        "name": file_path.name,
                        "size": file_path.stat().st_size,
                        "modified": datetime.fromtimestamp(file_path.stat().st_mtime).isoformat()
                    })
        
        return {"documents": files, "count": len(files)}
        
    except Exception as e:
        logger.error(f"Failed to list documents: {e}")
        raise HTTPException(status_code=500, detail=str(e))

# ====================== Debug Endpoints ======================
@app.get("/debug/entities")
async def get_entities(limit: int = 10):
    """Get sample entities from the graph"""
    if not indexer:
        raise HTTPException(status_code=503, detail="Indexer not initialized")
    
    try:
        entities = await indexer.get_sample_entities(limit)
        return {"entities": entities, "count": len(entities)}
    except Exception as e:
        logger.error(f"Failed to get entities: {e}")
        raise HTTPException(status_code=500, detail=str(e))

@app.get("/debug/relationships")
async def get_relationships(limit: int = 10):
    """Get sample relationships from the graph"""
    if not indexer:
        raise HTTPException(status_code=503, detail="Indexer not initialized")
    
    try:
        relationships = await indexer.get_sample_relationships(limit)
        return {"relationships": relationships, "count": len(relationships)}
    except Exception as e:
        logger.error(f"Failed to get relationships: {e}")
        raise HTTPException(status_code=500, detail=str(e))

if __name__ == "__main__":
    uvicorn.run(
        "main:app",
        host="0.0.0.0",
        port=8004,
        reload=True
    )
