"""
Response Cache Service — Redis-backed QA Cache
================================================
Caches full user-question → assistant-response pairs so that identical
or semantically similar questions get instant answers without re-running
the multi-agent pipeline.

Cache layers:
  1. Exact-match cache:  SHA-256 hash of normalised question text
  2. Fuzzy-match cache:  Trigram-based similarity (optional, configurable threshold)

Key schema:
  resp_cache:exact:<hash>     → JSON {response, intent, media, timestamp, hit_count}
  resp_cache:fuzzy:<trigram>   → list of exact hashes (for fuzzy lookup)

Configuration (env vars):
  RESPONSE_CACHE_TTL=3600       — TTL for cached responses (seconds, default 1 hour)
  RESPONSE_CACHE_ENABLED=true   — Enable/disable the cache
  RESPONSE_CACHE_FUZZY=false    — Enable fuzzy matching (slower, more hits)
  RESPONSE_CACHE_MIN_SIMILARITY=0.85 — Minimum trigram similarity for fuzzy match

Usage:
    from orchestrator.services.response_cache import ResponseCacheService

    cache = ResponseCacheService(redis_client)

    # Check cache before running pipeline
    cached = await cache.get("What is the temperature in room 5.04?")
    if cached:
        return cached["response"]

    # After pipeline completes, store the result
    await cache.put(
        question="What is the temperature in room 5.04?",
        response="The temperature is 22.5°C.",
        intent="analytics",
        media=[]
    )
"""

from __future__ import annotations

import hashlib
import json
import logging
import os
import re
import time
from typing import Any, Dict, List, Optional

logger = logging.getLogger(__name__)

# ─────────────────────────────────────────────────────────────────────────────
# Configuration
# ─────────────────────────────────────────────────────────────────────────────

CACHE_ENABLED = os.environ.get("RESPONSE_CACHE_ENABLED", "true").lower() == "true"
CACHE_TTL = int(os.environ.get("RESPONSE_CACHE_TTL", "3600"))
FUZZY_ENABLED = os.environ.get("RESPONSE_CACHE_FUZZY", "false").lower() == "true"
MIN_SIMILARITY = float(os.environ.get("RESPONSE_CACHE_MIN_SIMILARITY", "0.85"))

# Intents that are NOT safe to cache (dynamic per-request)
# general_knowledge is non-cacheable: answer length is steered by the user's
# phrasing (short/summary/long), so a cached answer could be served at the wrong
# length (especially via fuzzy match). Fresh LLM calls keep length control
# reliable — the credit cost is an accepted trade-off.
NON_CACHEABLE_INTENTS = {"clarification", "discovery", "control", "general_knowledge"}

# ─────────────────────────────────────────────────────────────────────────────
# Query normalisation
# ─────────────────────────────────────────────────────────────────────────────

_STOP_WORDS = {
    "a",
    "an",
    "the",
    "is",
    "are",
    "was",
    "were",
    "be",
    "been",
    "being",
    "have",
    "has",
    "had",
    "do",
    "does",
    "did",
    "will",
    "would",
    "could",
    "should",
    "may",
    "might",
    "shall",
    "can",
    "to",
    "of",
    "in",
    "for",
    "on",
    "with",
    "at",
    "by",
    "from",
    "as",
    "into",
    "through",
    "during",
    "before",
    "after",
    "and",
    "but",
    "or",
    "not",
    "no",
    "so",
    "if",
    "then",
    "than",
    "too",
    "very",
    "just",
    "about",
    "it",
    "its",
    "this",
    "that",
    "these",
    "those",
    "my",
    "your",
    "our",
    "their",
    "me",
    "you",
    "us",
    "them",
    "what",
    "which",
    "who",
    "whom",
    "whose",
    "where",
    "when",
    "how",
    "please",
    "thanks",
    "thank",
}


def normalise_query(query: str) -> str:
    """
    Normalise a user query for cache key generation.
    Strips punctuation, lowercases, removes stop words, sorts remaining tokens.
    """
    text = query.lower().strip()
    text = re.sub(r"[^\w\s.]", "", text)  # keep dots for sensor IDs
    text = re.sub(r"\s+", " ", text).strip()
    # Keep single-DIGIT tokens: a bare floor/zone/room number ("floor 3", "zone 9") is a
    # meaningful entity id. Dropping it (the old `len(t) > 1`) made "floor 3" and "floor 5"
    # normalise to the SAME key, so the exact/fuzzy cache served one floor's answer for
    # another — a wrong-entity answer (CAVEAT-035). Single-char *letters* are still dropped.
    tokens = [t for t in text.split() if t not in _STOP_WORDS and (len(t) > 1 or t.isdigit())]
    return " ".join(sorted(tokens))


def query_hash(query: str) -> str:
    """SHA-256 hash of normalised query."""
    normalised = normalise_query(query)
    return hashlib.sha256(normalised.encode("utf-8")).hexdigest()[:24]


# ─────────────────────────────────────────────────────────────────────────────
# Trigram similarity (for fuzzy matching)
# ─────────────────────────────────────────────────────────────────────────────


def _trigrams(text: str) -> set:
    """Generate character trigrams from text."""
    text = f"  {text} "
    return {text[i : i + 3] for i in range(len(text) - 2)}


def trigram_similarity(a: str, b: str) -> float:
    """Jaccard similarity of trigram sets."""
    ta, tb = _trigrams(a), _trigrams(b)
    if not ta or not tb:
        return 0.0
    intersection = ta & tb
    union = ta | tb
    return len(intersection) / len(union)


def salient_ids(text: str) -> set:
    """Numeric identifiers in a query (room/zone dotted ids, floor/room/sensor numbers).

    Two questions that differ only in one of these name DIFFERENT entities with DIFFERENT
    data — e.g. "temperature in room 5.04" vs "room 5.05" have >0.85 trigram similarity but
    must NOT share a cached answer, or one room's reading is served for another (a wrong,
    fabrication-adjacent answer). The fuzzy matcher requires these sets to be equal.
    """
    return set(re.findall(r"\d[\d.]*", text or ""))


# ─────────────────────────────────────────────────────────────────────────────
# Response Cache Service
# ─────────────────────────────────────────────────────────────────────────────


class ResponseCacheService:
    """
    Redis-backed response cache for the OntoSage pipeline.

    Requires an *async* Redis client (redis.asyncio.Redis).
    Initialised in main.py lifespan and attached to WorkflowOrchestrator.
    """

    PREFIX_EXACT = "resp_cache:exact:"
    PREFIX_FUZZY = "resp_cache:fuzzy:"
    PREFIX_STATS = "resp_cache:stats"

    def __init__(
        self,
        redis_client,
        ttl: int = CACHE_TTL,
        fuzzy: bool = FUZZY_ENABLED,
        min_similarity: float = MIN_SIMILARITY,
    ):
        self._redis = redis_client  # must be redis.asyncio.Redis
        self._ttl = ttl
        self._fuzzy = fuzzy
        self._min_similarity = min_similarity
        self._enabled = CACHE_ENABLED

    # ─────────────────────────────────────────────────────────────────────────
    # Cache lookup
    # ─────────────────────────────────────────────────────────────────────────

    async def get(
        self, question: str, building_id: str = "default", user_id: str = ""
    ) -> Optional[Dict]:
        """
        Look up a cached response for the given question.

        Returns:
            Dict with keys: response, intent, media, cached_at, hit_count
            or None if no cache hit.
        """
        if not self._enabled:
            return None

        qhash = query_hash(question)
        cache_key = f"{self.PREFIX_EXACT}{building_id}:{qhash}"

        # 1. Exact match
        cached_raw = await self._redis_get(cache_key)
        if cached_raw:
            try:
                entry = json.loads(cached_raw)
                entry["hit_count"] = entry.get("hit_count", 0) + 1
                entry["cache_type"] = "exact"
                # Update hit count
                await self._redis_set(cache_key, json.dumps(entry), self._ttl)
                await self._increment_stats("hits")
                logger.info(f"Response cache HIT (exact): {qhash[:12]}")
                return entry
            except json.JSONDecodeError:
                pass

        # 2. Fuzzy match (if enabled)
        if self._fuzzy:
            fuzzy_result = await self._fuzzy_lookup(question, building_id)
            if fuzzy_result:
                fuzzy_result["cache_type"] = "fuzzy"
                await self._increment_stats("fuzzy_hits")
                logger.info(
                    f"Response cache HIT (fuzzy): similarity={fuzzy_result.get('similarity', 0):.2f}"
                )
                return fuzzy_result

        await self._increment_stats("misses")
        return None

    # ─────────────────────────────────────────────────────────────────────────
    # Cache storage
    # ─────────────────────────────────────────────────────────────────────────

    async def put(
        self,
        question: str,
        response: str,
        intent: str,
        media: Optional[List] = None,
        building_id: str = "default",
        metadata: Optional[Dict] = None,
    ):
        """
        Store a response in the cache.

        Non-cacheable intents (clarification, discovery, control) are skipped.
        """
        if not self._enabled:
            return

        if intent in NON_CACHEABLE_INTENTS:
            logger.debug(f"Response cache SKIP: intent '{intent}' is not cacheable")
            return

        qhash = query_hash(question)
        cache_key = f"{self.PREFIX_EXACT}{building_id}:{qhash}"

        entry = {
            "question": question,
            "normalised": normalise_query(question),
            "response": response,
            "intent": intent,
            "media": media or [],
            "building_id": building_id,
            "cached_at": time.strftime("%Y-%m-%dT%H:%M:%SZ"),
            "hit_count": 0,
            "metadata": metadata or {},
        }

        await self._redis_set(cache_key, json.dumps(entry, ensure_ascii=False), self._ttl)
        await self._increment_stats("stores")
        logger.info(f"Response cache STORE: {qhash[:12]} (intent={intent})")

        # Store fuzzy index entry
        if self._fuzzy:
            normalised = normalise_query(question)
            fuzzy_key = f"{self.PREFIX_FUZZY}{building_id}"
            await self._redis_hset(fuzzy_key, qhash, normalised)

    # ─────────────────────────────────────────────────────────────────────────
    # Cache invalidation
    # ─────────────────────────────────────────────────────────────────────────

    async def invalidate(
        self, question: str = None, building_id: str = "default", flush_all: bool = False
    ):
        """Invalidate cached responses."""
        if flush_all:
            pattern = f"{self.PREFIX_EXACT}{building_id}:*"
            await self._redis_delete_pattern(pattern)
            fuzzy_key = f"{self.PREFIX_FUZZY}{building_id}"
            await self._redis_delete(fuzzy_key)
            logger.info(f"Response cache FLUSH: building={building_id}")
            return

        if question:
            qhash = query_hash(question)
            cache_key = f"{self.PREFIX_EXACT}{building_id}:{qhash}"
            await self._redis_delete(cache_key)
            logger.info(f"Response cache INVALIDATE: {qhash[:12]}")

    async def invalidate_by_sensor(self, uuid: str, building_id: str = "default"):
        """Invalidate all cached responses that mention a specific sensor UUID."""
        pattern = f"{self.PREFIX_EXACT}{building_id}:*"
        keys = await self._redis_keys(pattern)
        count = 0
        for key in keys:
            cached_raw = await self._redis_get(key)
            if cached_raw and uuid in cached_raw:
                await self._redis_delete(key)
                count += 1
        if count > 0:
            logger.info(f"Response cache INVALIDATE: {count} entries for sensor {uuid}")

    # ─────────────────────────────────────────────────────────────────────────
    # Statistics
    # ─────────────────────────────────────────────────────────────────────────

    async def stats(self) -> Dict:
        """Get cache hit/miss statistics."""
        raw = await self._redis_hgetall(self.PREFIX_STATS)
        return {
            "enabled": self._enabled,
            "ttl_seconds": self._ttl,
            "fuzzy": self._fuzzy,
            "hits": int(raw.get("hits", 0)),
            "fuzzy_hits": int(raw.get("fuzzy_hits", 0)),
            "misses": int(raw.get("misses", 0)),
            "stores": int(raw.get("stores", 0)),
            "hit_rate": self._compute_hit_rate(raw),
        }

    def _compute_hit_rate(self, raw: Dict) -> float:
        hits = int(raw.get("hits", 0)) + int(raw.get("fuzzy_hits", 0))
        misses = int(raw.get("misses", 0))
        total = hits + misses
        return round(hits / total * 100, 1) if total > 0 else 0.0

    # ─────────────────────────────────────────────────────────────────────────
    # Fuzzy logic
    # ─────────────────────────────────────────────────────────────────────────

    async def _fuzzy_lookup(self, question: str, building_id: str) -> Optional[Dict]:
        """Find the best fuzzy match for a question."""
        normalised = normalise_query(question)
        fuzzy_key = f"{self.PREFIX_FUZZY}{building_id}"
        all_entries = await self._redis_hgetall(fuzzy_key)

        best_sim = 0.0
        best_hash = None
        q_ids = salient_ids(normalised)

        for qhash, stored_norm in all_entries.items():
            # Only fuzzy-match questions that name the SAME specific entity. Two questions
            # differing only in a room/zone/floor id score >0.85 but refer to different
            # entities — returning one's cached data for the other is a wrong answer.
            if salient_ids(stored_norm) != q_ids:
                continue
            sim = trigram_similarity(normalised, stored_norm)
            if sim > best_sim:
                best_sim = sim
                best_hash = qhash

        if best_sim >= self._min_similarity and best_hash:
            cache_key = f"{self.PREFIX_EXACT}{building_id}:{best_hash}"
            cached_raw = await self._redis_get(cache_key)
            if cached_raw:
                try:
                    entry = json.loads(cached_raw)
                    entry["similarity"] = round(best_sim, 3)
                    return entry
                except json.JSONDecodeError:
                    pass

        return None

    # ─────────────────────────────────────────────────────────────────────────
    # Redis abstraction (works with both sync and async redis clients)
    # ─────────────────────────────────────────────────────────────────────────

    async def _redis_get(self, key: str) -> Optional[str]:
        try:
            val = await self._redis.get(key)
            return val.decode("utf-8") if isinstance(val, bytes) else val
        except Exception:
            return None

    async def _redis_set(self, key: str, value: str, ttl: int):
        try:
            await self._redis.setex(key, ttl, value)
        except Exception as e:
            logger.warning(f"Redis SET error: {e}")

    async def _redis_delete(self, key: str):
        try:
            await self._redis.delete(key)
        except Exception:
            pass

    async def _redis_delete_pattern(self, pattern: str):
        try:
            keys = await self._redis_keys(pattern)
            for key in keys:
                await self._redis_delete(key)
        except Exception:
            pass

    async def _redis_keys(self, pattern: str) -> List[str]:
        try:
            result = await self._redis.keys(pattern)
            return [k.decode("utf-8") if isinstance(k, bytes) else k for k in result]
        except Exception:
            return []

    async def _redis_hset(self, key: str, field: str, value: str):
        try:
            await self._redis.hset(key, field, value)
        except Exception:
            pass

    async def _redis_hgetall(self, key: str) -> Dict[str, str]:
        try:
            result = await self._redis.hgetall(key)
            return {
                (k.decode("utf-8") if isinstance(k, bytes) else k): (
                    v.decode("utf-8") if isinstance(v, bytes) else v
                )
                for k, v in result.items()
            }
        except Exception:
            return {}

    async def _increment_stats(self, field: str):
        try:
            await self._redis.hincrby(self.PREFIX_STATS, field, 1)
        except Exception:
            pass
