"""
RAG Service - Main FastAPI Application
Handles embeddings and retrieval for OntoSage 2.0
Uses GraphDB for vector similarity and graph traversal.
"""

import os
import sys

sys.path.append("/app")

from fastapi import FastAPI, HTTPException, Body
from fastapi.middleware.cors import CORSMiddleware
import uvicorn

from shared.config import settings, validate_config
from shared.utils import get_logger
from graphdb_retriever import GraphDBRetriever
import asyncio

# Import the auto-loader
from import_ontology import import_ontology

# Initialize logger
logger = get_logger(__name__)

# Validate configuration
try:
    validate_config()
except ValueError as e:
    logger.error(f"Configuration error: {e}")
    logger.info("RAG Service will start but may fail on API calls")

# Create FastAPI app
app = FastAPI(
    title="OntoSage RAG Service",
    description="Retrieval-Augmented Generation service using GraphDB",
    version="2.0.0",
)

# Add CORS
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Initialize GraphDB retriever
graphdb_retriever = GraphDBRetriever()


@app.on_event("startup")
async def startup_event():
    """Initialize services on startup"""
    logger.info("🚀 Starting RAG Service (GraphDB Mode)")
    logger.info(f"GraphDB URL: {settings.GRAPHDB_URL}")

    # OFF BY DEFAULT — this importer was the source of the graph bloat.
    #
    # It scans the SAME /app/input/*.ttl the orchestrator's ttl_uploader already
    # ingests, but POSTs each file to /statements with no context, so every file
    # landed in the DEFAULT graph and POST appends rather than replaces. Every
    # rag-service restart therefore added another full copy of every ontology file,
    # Brick_v1.4 and Brick+extensions included, each with fresh blank nodes that
    # nothing can dedupe.
    #
    # Measured 2026-08-26: 20.3M triples for a building with 10,969 IRI subjects;
    # 15.4M of them SHACL machinery, 4.19M blank-node subjects, and 55,706
    # timeseries references for 2,872 distinct UUIDs — 19.4 copies of each, up from
    # 13.4 the previous day purely from restarts during development.
    #
    # The orchestrator owns ingestion: ttl_uploader uploads each file into its own
    # named graph with a SHA skip, so re-running is a no-op. This service only READS
    # from GraphDB. Set RAG_IMPORT_ONTOLOGY=true to re-enable, but fix the context
    # first — see BUG-250 and CAVEAT-287.
    if os.getenv("RAG_IMPORT_ONTOLOGY", "false").lower() in ("1", "true", "yes"):
        logger.warning(
            "RAG_IMPORT_ONTOLOGY is on — this appends to the DEFAULT graph on every "
            "boot and is what caused the 20M-triple bloat. Prefer the orchestrator's "
            "ttl_uploader."
        )
        asyncio.create_task(import_ontology())
    logger.info(f"Repository: {settings.GRAPHDB_REPOSITORY}")

    # Check GraphDB connection
    is_healthy = await graphdb_retriever.health_check()
    if is_healthy:
        logger.info("✅ Connected to GraphDB")
    else:
        logger.warning("⚠️ Could not connect to GraphDB")


@app.get("/health")
async def health_check():
    """Health check endpoint"""
    try:
        is_healthy = await graphdb_retriever.health_check()
        status = "healthy" if is_healthy else "unhealthy"
        return {
            "status": status,
            "service": "rag-service",
            "version": "2.0.0",
            "backend": "graphdb",
            # Build provenance — which commit/time this image was built from (baked as ENV at build).
            "build": {
                "sha": os.environ.get("BUILD_SHA", "unknown"),
                "time": os.environ.get("BUILD_TIME", "unknown"),
            },
            "details": {
                "graphdb_url": settings.GRAPHDB_URL,
                "repository": settings.GRAPHDB_REPOSITORY,
            },
        }
    except Exception as e:
        logger.error(f"Health check failed: {e}")
        return {"status": "unhealthy", "service": "rag-service", "error": str(e)}


@app.post("/graphdb/retrieve")
async def graphdb_retrieve(
    query: str = Body(..., embed=True),
    top_k: int = Body(10, embed=True),
    hops: int = Body(2, embed=True),
    min_score: float = Body(0.3, embed=True),
):
    """
    GraphDB-based RAG retrieval for SPARQL generation

    Uses 2-step Ontotext technique:
    1. Vector similarity search returns entity IRIs
    2. SPARQL fetches bounded context (triples around entities)

    Args:
        query: User's natural language query
        top_k: Number of entities to retrieve
        hops: Graph traversal depth (1 or 2)
        min_score: Minimum similarity score

    Returns:
        Dict with prefixes, triples, entities, and summary for LLM
    """
    try:
        # Clean query text - remove leading/trailing whitespace, bullet points, markdown, etc.
        cleaned_query = query.strip().lstrip("*-•▪︎►▸ \t").rstrip("*-•▪︎►▸ \t").strip()

        logger.info(f"🔍 GraphDB retrieval: {cleaned_query[:100]}")
        if query != cleaned_query:
            logger.info(f"   Original query: {query[:100]}")

        result = await graphdb_retriever.retrieve_for_sparql(
            query=cleaned_query, top_k=top_k, hops=hops, min_score=min_score
        )

        logger.info(
            f"✅ Retrieved {result['triple_count']} triples for {result['retrieved_entity_count']} entities"
        )

        return {
            "status": "success",
            "query": cleaned_query,  # Return cleaned query
            "prefixes": result["prefixes"],
            "prefix_declarations": result["prefix_declarations"],
            "triples": result["triples"],
            "entities": result["entities"],
            "entity_labels": result["entity_labels"],
            "summary": result["summary"],
            "metadata": {
                "entity_count": result["retrieved_entity_count"],
                "triple_count": result["triple_count"],
                "hops": hops,
            },
        }

    except Exception as e:
        logger.error(f"❌ GraphDB retrieval error: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail=str(e))


if __name__ == "__main__":
    uvicorn.run("main:app", host="0.0.0.0", port=8001, reload=True, log_level="info")
