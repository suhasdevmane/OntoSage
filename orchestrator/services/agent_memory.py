"""
Phase 7.4 — Agent Memory Service (Per-User Learning)
=====================================================
Stores successful QA patterns, entity preferences, and query history
per user in Qdrant, and retrieves relevant context at conversation start
to prime the Dialogue Agent and reduce repetitive clarification loops.

Architecture:
  ┌────────────┐  store()    ┌──────────────┐
  │ Workflow   │────────────▶│ Qdrant       │
  │ on success │             │ user_memory  │
  └────────────┘             │ collection   │
  ┌────────────┐  retrieve() │              │
  │ Dialogue   │◀────────────│ (cosine sim) │
  │ Agent      │             └──────────────┘
  └────────────┘

Memory types stored:
  - successful QA pairs (query → answer summary)
  - preferred sensor names ("user calls CO2 sensors 'air quality sensors'")
  - common time references ("user usually means last week by default")
  - failed clarification patterns (avoid repeating same clarification question)

Usage:
    from orchestrator.services.agent_memory import AgentMemoryService

    memory = AgentMemoryService(qdrant_url="http://qdrant:6333")

    # At conversation start
    context = await memory.retrieve_context(user_id="alice", query="temp in room 5")

    # After successful response
    await memory.store_success(
        user_id="alice",
        query="What is the temperature in room 5.04?",
        intent="analytics",
        entities=["Air_Temperature_Sensor_5.04"],
        answer_summary="Temperature is 22.5°C, within ASHRAE comfort range."
    )
"""

from __future__ import annotations

import hashlib
import json
import logging
import os
import time
from typing import Any, Dict, List, Optional

from shared.config import settings

logger = logging.getLogger(__name__)

QDRANT_URL = os.environ.get("QDRANT_URL", "http://qdrant:6333")
MEMORY_ENABLED = os.environ.get("AGENT_MEMORY_ENABLED", "true").lower() == "true"
CROSS_SESSION_MEMORY_ENABLED = os.environ.get("CROSS_SESSION_MEMORY_ENABLED", "true").lower() == "true"
COLLECTION_NAME = "user_memory"
MAX_MEMORIES = int(os.environ.get("AGENT_MEMORY_MAX", "200"))  # per user
RETRIEVE_TOP_K = int(os.environ.get("AGENT_MEMORY_TOP_K", "5"))  # memories per query
EMBED_MODEL = os.environ.get("AGENT_MEMORY_EMBED_MODEL", "text-embedding-3-small")

# Known OpenAI embedding model → vector dimension mapping
_EMBED_MODEL_DIMS: Dict[str, int] = {
    "text-embedding-3-small": 1536,
    "text-embedding-3-large": 3072,
    "text-embedding-ada-002": 1536,
}


class MemoryEntry:
    """A single episodic memory record."""

    def __init__(
        self,
        user_id: str,
        query: str,
        intent: str,
        entities: List[str],
        answer_summary: str,
        memory_type: str = "qa_pair",
        score: float = 1.0,
    ):
        self.user_id = user_id
        self.query = query
        self.intent = intent
        self.entities = entities
        self.answer_summary = answer_summary
        self.memory_type = memory_type
        self.score = score
        self.timestamp = time.strftime("%Y-%m-%dT%H:%M:%SZ")
        self.id = hashlib.sha256(f"{user_id}{query}{self.timestamp}".encode()).hexdigest()[:24]

    def to_payload(self) -> Dict:
        return {
            "user_id": self.user_id,
            "query": self.query,
            "intent": self.intent,
            "entities": self.entities,
            "answer_summary": self.answer_summary,
            "memory_type": self.memory_type,
            "score": self.score,
            "timestamp": self.timestamp,
        }

    @classmethod
    def from_payload(cls, payload: Dict) -> "MemoryEntry":
        m = cls.__new__(cls)
        m.user_id = payload.get("user_id", "")
        m.query = payload.get("query", "")
        m.intent = payload.get("intent", "general")
        m.entities = payload.get("entities", [])
        m.answer_summary = payload.get("answer_summary", "")
        m.memory_type = payload.get("memory_type", "qa_pair")
        m.score = payload.get("score", 1.0)
        m.timestamp = payload.get("timestamp", "")
        m.id = payload.get("id", "")
        return m


class AgentMemoryService:
    """
    Per-user episodic memory backed by Qdrant.

    Falls back to a simple in-memory dict when Qdrant is unavailable
    (development mode). In-memory store is NOT persisted across restarts.
    """

    def __init__(
        self, qdrant_url: str = QDRANT_URL, llm_manager=None, enabled: bool = MEMORY_ENABLED
    ):
        self._url = qdrant_url
        self._llm = llm_manager
        self._enabled = enabled
        self._client = None
        self._fallback_store: Dict[str, List[MemoryEntry]] = {}  # user_id → memories
        self._ready = False

    async def initialise(self):
        """Connect to Qdrant and ensure collection exists."""
        if not self._enabled:
            logger.info("Agent memory disabled")
            return
        try:
            from qdrant_client import AsyncQdrantClient
            from qdrant_client.models import Distance, VectorParams

            self._client = AsyncQdrantClient(url=self._url)

            # Determine the actual embedding dimension from the embed model name.
            # Use the known-dims lookup first; fall back to settings.embedding_dimension.
            embed_dim = _EMBED_MODEL_DIMS.get(EMBED_MODEL, settings.embedding_dimension)

            collections = await self._client.get_collections()
            names = [c.name for c in collections.collections]

            # If collection exists with wrong dimensions, recreate it
            if COLLECTION_NAME in names:
                info = await self._client.get_collection(COLLECTION_NAME)
                existing_size = info.config.params.vectors.size
                if existing_size != embed_dim:
                    logger.warning(
                        f"Collection '{COLLECTION_NAME}' has dim {existing_size}, "
                        f"expected {embed_dim} — recreating"
                    )
                    await self._client.delete_collection(COLLECTION_NAME)
                    names = [n for n in names if n != COLLECTION_NAME]

            if COLLECTION_NAME not in names:
                await self._client.create_collection(
                    collection_name=COLLECTION_NAME,
                    vectors_config=VectorParams(size=embed_dim, distance=Distance.COSINE),
                )
                logger.info(f"Qdrant collection '{COLLECTION_NAME}' created (dim={embed_dim})")
            self._ready = True
            logger.info("Agent memory service initialised (Qdrant)")
        except ImportError:
            logger.warning("qdrant-client not installed — agent memory in fallback mode")
            self._ready = False
        except Exception as e:
            logger.warning(f"Qdrant connection failed — fallback mode: {e}")
            self._ready = False

    # ─────────────────────────────────────────────────────────────────────────
    # Store
    # ─────────────────────────────────────────────────────────────────────────

    async def store_success(
        self,
        user_id: str,
        query: str,
        intent: str,
        entities: List[str],
        answer_summary: str,
        memory_type: str = "qa_pair",
    ):
        """Persist a successful QA interaction to memory."""
        if not self._enabled:
            return
        entry = MemoryEntry(user_id, query, intent, entities, answer_summary, memory_type)
        if self._ready and self._client:
            try:
                embedding = await self._embed(query)
                from qdrant_client.models import PointStruct

                await self._client.upsert(
                    collection_name=COLLECTION_NAME,
                    points=[
                        PointStruct(
                            id=int(hashlib.sha256(entry.id.encode()).hexdigest()[:15], 16),
                            vector=embedding,
                            payload=entry.to_payload(),
                        )
                    ],
                )
                logger.debug(f"Memory stored for {user_id}: {intent}")
            except Exception as e:
                logger.warning(f"Memory store error: {e}")
                self._fallback_append(user_id, entry)
        else:
            self._fallback_append(user_id, entry)

    def _fallback_append(self, user_id: str, entry: MemoryEntry):
        store = self._fallback_store.setdefault(user_id, [])
        store.append(entry)
        if len(store) > MAX_MEMORIES:
            store.pop(0)

    # ─────────────────────────────────────────────────────────────────────────
    # Retrieve
    # ─────────────────────────────────────────────────────────────────────────

    async def retrieve_context(self, user_id: str, query: str) -> str:
        """
        Retrieve relevant memories for a user+query and return a
        formatted context string to inject into the Dialogue Agent prompt.
        """
        if not self._enabled:
            return ""

        memories = await self._search(user_id, query)
        if not memories:
            return ""

        lines = ["**Relevant memories from this user's history:**"]
        for m in memories[:RETRIEVE_TOP_K]:
            lines.append(
                f'- Q: "{m.query}" → Intent: {m.intent}, '
                f"Entities: {', '.join(m.entities) or 'none'}, "
                f"Answer: {m.answer_summary[:120]}..."
            )
        return "\n".join(lines)

    async def _search(self, user_id: str, query: str) -> List[MemoryEntry]:
        if self._ready and self._client:
            try:
                from qdrant_client.models import FieldCondition, Filter, MatchValue

                embedding = await self._embed(query)
                results = await self._client.query_points(
                    collection_name=COLLECTION_NAME,
                    query=embedding,
                    query_filter=Filter(
                        must=[FieldCondition(key="user_id", match=MatchValue(value=user_id))]
                    ),
                    limit=RETRIEVE_TOP_K,
                )
                return [MemoryEntry.from_payload(r.payload) for r in results.points]
            except Exception as e:
                logger.warning(f"Memory search error: {e}")

        # Fallback: simple recency-based retrieval
        store = self._fallback_store.get(user_id, [])
        return store[-RETRIEVE_TOP_K:]

    # ─────────────────────────────────────────────────────────────────────────
    # Embedding
    # ─────────────────────────────────────────────────────────────────────────

    async def _embed(self, text: str) -> List[float]:
        """Generate embedding via OpenAI or fallback to simple hash-based vector."""
        try:
            import openai

            response = await openai.AsyncOpenAI().embeddings.create(model=EMBED_MODEL, input=text)
            return response.data[0].embedding
        except Exception:
            # Fallback: deterministic pseudo-embedding (for dev/CI)
            import hashlib
            import math

            h = hashlib.sha256(text.encode()).digest()
            dim = settings.embedding_dimension
            vals = []
            for i in range(dim):
                byte_idx = i % len(h)
                angle = (h[byte_idx] / 255.0) * 2 * math.pi * (i + 1)
                vals.append(math.sin(angle) * 0.1)
            return vals

    # ─────────────────────────────────────────────────────────────────────────
    # Phase 5 — Failure / correction capture (G4 "closed-loop feedback log")
    # ─────────────────────────────────────────────────────────────────────────

    async def store_failure(
        self,
        user_id: str,
        query: str,
        intent: str,
        entities: List[str],
        error_summary: str,
        persona: str = "general",
    ):
        """
        Persist a FAILED interaction so the correction corpus can grow.
        Survey G4: "closed-loop feedback log — failures too, not just successes."
        Stored with memory_type='failure' for separate retrieval/analysis.
        """
        await self.store_success(
            user_id=user_id,
            query=query,
            intent=intent,
            entities=entities,
            answer_summary=f"[FAILURE] {error_summary[:200]}",
            memory_type="failure",
        )

    async def store_correction(
        self,
        user_id: str,
        query: str,
        wrong_answer: str,
        corrected_answer: str,
        intent: str,
        persona: str = "general",
    ):
        """
        Persist a user-corrected interaction as a few-shot example.
        Used by the dialogue agent for retrieval-augmented intent + entity resolution.
        Stored with memory_type='correction'.
        """
        summary = f"[CORRECTION] wrong={wrong_answer[:100]} → correct={corrected_answer[:100]}"
        await self.store_success(
            user_id=user_id,
            query=query,
            intent=intent,
            entities=[],
            answer_summary=summary,
            memory_type="correction",
        )

    # ─────────────────────────────────────────────────────────────────────────
    # Housekeeping
    # ─────────────────────────────────────────────────────────────────────────

    async def forget_user(self, user_id: str):
        """Delete all memories for a user (GDPR right to be forgotten)."""
        if self._ready and self._client:
            try:
                await self._client.delete(
                    collection_name=COLLECTION_NAME,
                    points_selector={
                        "filter": {"must": [{"key": "user_id", "match": {"value": user_id}}]}
                    },
                )
                logger.info(f"Memories deleted for user: {user_id}")
            except Exception as e:
                logger.warning(f"Memory delete error: {e}")
        self._fallback_store.pop(user_id, None)

    async def stats(self, user_id: Optional[str] = None) -> Dict:
        if self._ready and self._client:
            try:
                info = await self._client.get_collection(COLLECTION_NAME)
                return {
                    "backend": "qdrant",
                    "total_points": info.points_count,
                    "enabled": self._enabled,
                }
            except Exception:
                pass
        return {
            "backend": "fallback",
            "total_points": sum(len(v) for v in self._fallback_store.values()),
            "enabled": self._enabled,
        }
