"""
HybridRetrievalOrchestrator — Phase 3.5
=========================================
Routes retrieval to the optimal backend based on query type,
and merges context from multiple backends when needed.

Tier hierarchy:
  Tier 1: Template SPARQL (0 LLM calls, handled in sparql_agent.py)
  Tier 2: GraphDB Similarity RAG (fast, entity-precise)
  Tier 3: Community-Based LanceDB RAG (richer spatial/relational context)
  Tier 4: Hybrid (Tier 2 + Tier 3 merged for complex multi-hop queries)

Usage:
    from orchestrator.services.hybrid_retrieval import hybrid_retrieval
    context = await hybrid_retrieval.retrieve(query, query_type="entity_lookup")
"""
import sys
sys.path.append('/app')

import httpx
from enum import Enum
from typing import Any, Dict, List, Optional

from shared.config import settings
from shared.utils import get_logger

logger = get_logger(__name__)

RAG_SERVICE_URL = f"http://{settings.RAG_SERVICE_HOST}:{settings.RAG_SERVICE_PORT}"


class QueryType(str, Enum):
    ENTITY_LOOKUP = "entity_lookup"        # "Where is sensor X?" → GraphDB RAG
    SPATIAL_REASONING = "spatial_reasoning"  # "What rooms share a floor?" → Community RAG
    SENSOR_DATA = "sensor_data"             # "What is current CO2?" → GraphDB RAG for UUID
    COMPLEX_MULTI_HOP = "complex_multi_hop"  # "Which floor has highest CO2?" → Hybrid
    GENERAL_KNOWLEDGE = "general_knowledge"  # "What is brick schema?" → GraphDB RAG
    UNKNOWN = "unknown"


def classify_query_type(user_query: str) -> QueryType:
    """Simple keyword-based query type classifier."""
    q = user_query.lower()
    if any(w in q for w in ["which floor", "which room", "across all", "compare", "highest", "lowest"]):
        return QueryType.COMPLEX_MULTI_HOP
    if any(w in q for w in ["adjacent", "next to", "near", "spatial", "proximity"]):
        return QueryType.SPATIAL_REASONING
    if any(w in q for w in ["current", "reading", "level", "value", "now", "today", "yesterday"]):
        return QueryType.SENSOR_DATA
    if any(w in q for w in ["where is", "location", "type of", "what is", "define", "uuid", "list all"]):
        return QueryType.ENTITY_LOOKUP
    return QueryType.UNKNOWN


class HybridRetrievalOrchestrator:
    """
    Routes retrieval to optimal backend(s) per query type.
    Falls back gracefully if a backend is unavailable.
    """

    def __init__(self) -> None:
        self._community_rag_available: Optional[bool] = None  # lazy check

    async def retrieve(
        self,
        query: str,
        query_type: Optional[QueryType] = None,
        top_k: int = 10,
        hops: int = 2,
    ) -> List[str]:
        """
        Main entry: returns a list of context strings for LLM SPARQL generation.
        """
        if query_type is None:
            query_type = classify_query_type(query)

        logger.info(f"HybridRetrieval: query_type={query_type.value} for '{query[:60]}'")

        if query_type == QueryType.COMPLEX_MULTI_HOP:
            return await self._hybrid_retrieve(query, top_k, hops)
        elif query_type == QueryType.SPATIAL_REASONING:
            return await self._community_retrieve(query, top_k)
        else:
            # Default: GraphDB RAG (fast, precise)
            return await self._graphdb_retrieve(query, top_k, hops)

    # ------------------------------------------------------------------
    # Tier 2: GraphDB Similarity RAG
    # ------------------------------------------------------------------

    async def _graphdb_retrieve(
        self, query: str, top_k: int = 10, hops: int = 2
    ) -> List[str]:
        """GraphDB 2-step retrieval: vector similarity → bounded graph context."""
        try:
            async with httpx.AsyncClient(timeout=30.0) as client:
                resp = await client.post(
                    f"{RAG_SERVICE_URL}/graphdb/retrieve",
                    json={"query": query, "top_k": top_k, "hops": hops, "min_score": 0.3},
                )
                resp.raise_for_status()
                data = resp.json()
                if data.get("status") == "success":
                    prefix_decl = data.get("prefix_declarations", "")
                    summary = data.get("summary", "")
                    triples = data.get("triples", [])
                    triple_text = "\n".join(
                        f"  {t['subject']} {t['predicate']} {t['object']} ."
                        for t in triples[:50]
                    )
                    context = (
                        f"=== GRAPHDB KNOWLEDGE BASE ===\n\nPREFIXES:\n{prefix_decl}\n\n"
                        f"{summary}\n\nTRIPLES:\n{triple_text}\n"
                    )
                    logger.info(
                        f"GraphDB RAG: {data['metadata']['entity_count']} entities, "
                        f"{data['metadata']['triple_count']} triples"
                    )
                    return [context]
        except Exception as e:
            logger.warning(f"GraphDB RAG failed: {e}")
        return []

    # ------------------------------------------------------------------
    # Tier 3: Community-Based LanceDB RAG
    # ------------------------------------------------------------------

    async def _community_retrieve(
        self, query: str, top_k: int = 10
    ) -> List[str]:
        """Community cluster retrieval via LanceDB (advanced RAG service)."""
        try:
            async with httpx.AsyncClient(timeout=30.0) as client:
                resp = await client.post(
                    f"{RAG_SERVICE_URL}/community/retrieve",
                    json={"query": query, "top_k": top_k},
                )
                resp.raise_for_status()
                data = resp.json()
                if data.get("status") == "success":
                    context = data.get("context", "")
                    logger.info(f"Community RAG: retrieved context ({len(context)} chars)")
                    return [f"=== COMMUNITY KNOWLEDGE BASE ===\n\n{context}"]
        except Exception as e:
            logger.warning(f"Community RAG failed (may not be deployed yet): {e}")
        # Fallback to GraphDB
        return await self._graphdb_retrieve(query, top_k)

    # ------------------------------------------------------------------
    # Tier 4: Hybrid (Tier 2 + Tier 3)
    # ------------------------------------------------------------------

    async def _hybrid_retrieve(
        self, query: str, top_k: int = 10, hops: int = 2
    ) -> List[str]:
        """Combine GraphDB and Community RAG for maximum context richness."""
        import asyncio
        graphdb_ctx, community_ctx = await asyncio.gather(
            self._graphdb_retrieve(query, top_k, hops),
            self._community_retrieve(query, top_k),
            return_exceptions=True,
        )
        context = []
        if isinstance(graphdb_ctx, list):
            context.extend(graphdb_ctx)
        if isinstance(community_ctx, list):
            context.extend(community_ctx)
        if not context:
            logger.warning("Hybrid retrieval: both backends failed")
        else:
            logger.info(f"Hybrid retrieval: {len(context)} context blocks")
        return context


# Module-level singleton
hybrid_retrieval = HybridRetrievalOrchestrator()
