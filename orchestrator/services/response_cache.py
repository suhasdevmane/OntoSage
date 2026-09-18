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
  resp_cache:exact:<partition>:<hash>         → JSON {response, intent, media, timestamp, hit_count}
  resp_cache:fuzzy:<partition>[|c<context>]  → hash of exact hashes → normalised question

  <hash> is the normalised question alone for an OPENING question, and the question plus
  the preceding user questions for any later turn (BUG-668, see CONTEXT_TURNS).

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
from typing import Any, Dict, List, Optional, Sequence

logger = logging.getLogger(__name__)

# ─────────────────────────────────────────────────────────────────────────────
# Configuration
# ─────────────────────────────────────────────────────────────────────────────

CACHE_ENABLED = os.environ.get("RESPONSE_CACHE_ENABLED", "true").lower() == "true"
CACHE_TTL = int(os.environ.get("RESPONSE_CACHE_TTL", "3600"))

#: The revision an answer was produced under. Part of every cache partition, so a
#: deployment cannot serve answers the current code would not produce (BUG-498).
#:
#: BUILD_SHA when the image carries one. It does NOT here — `docker exec` reports
#: `BUILD_SHA=unknown` — and in this deployment `/app/orchestrator` is BIND-MOUNTED, so a
#: `docker compose restart` is itself a deployment: new source, same image. Process boot
#: time is therefore the honest revision proxy in development, and it is the case that
#: actually bit us: a guard was fixed, the orchestrator restarted, and the pre-fix answer
#: was still served from cache.
#:
#: COST, stated rather than discovered: with no BUILD_SHA every restart starts from a cold
#: cache. With one, restarts of the same image keep their entries and only a new build
#: invalidates. A cold cache is cheap; an answer from code that no longer exists is not.
_BUILD_SHA = (os.environ.get("BUILD_SHA") or "").strip().lower()
REVISION = (
    _BUILD_SHA[:12]
    if _BUILD_SHA and _BUILD_SHA != "unknown"
    else f"boot{int(time.time())}"
)
FUZZY_ENABLED = os.environ.get("RESPONSE_CACHE_FUZZY", "false").lower() == "true"
MIN_SIMILARITY = float(os.environ.get("RESPONSE_CACHE_MIN_SIMILARITY", "0.85"))

# Intents that are NOT safe to cache (dynamic per-request)
# general_knowledge is non-cacheable: answer length is steered by the user's
# phrasing (short/summary/long), so a cached answer could be served at the wrong
# length (especially via fuzzy match). Fresh LLM calls keep length control
# reliable — the credit cost is an accepted trade-off.
NON_CACHEABLE_INTENTS = {"clarification", "discovery", "control", "general_knowledge", "deliberate"}

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


#: How many preceding USER questions a follow-up's cache entry is bound to (BUG-668).
#:
#: A follow-up's meaning lives in the turns before it: "How has that changed over the last
#: week?" is a different question after "CO2 in room 5.01" than after "temperature on floor
#: 3", and a key holding only its own words served one conversation's answer to the other.
#:
#: Three, because the co-reference rewrite -- the step that turns a follow-up's words into a
#: definite question -- reads the last six messages, three user/assistant exchanges
#: (`dialogue_agent.rewrite_to_standalone`, `format_conversation_history(max_messages=6)`).
#: Two turns that share a key were therefore rewritten from the same user-side history.
#: A longer bound buys nothing that rewrite can see, and costs reuse: turn five of a scripted
#: conversation could no longer share an entry with the same script opened differently.
#:
#: Assistant replies are NOT in the key. They are a function of the user turns, the partition
#: and the revision (all already keyed) plus the clock, so including them would make every
#: follow-up a miss without making any hit more correct.
#:
#: Residual, stated rather than discovered: state carried from OLDER turns -- a forecast or
#: analytics result kept by carry-forward since before the last three questions -- is not in
#: the key.
CONTEXT_TURNS = 3


def context_turns(context: Optional[Sequence[str]]) -> List[str]:
    """The normalised preceding user questions that bind a cache entry, oldest first."""
    turns = [normalise_query(str(t)) for t in (context or []) if str(t or "").strip()]
    return turns[-CONTEXT_TURNS:]


def context_fingerprint(context: Optional[Sequence[str]]) -> str:
    """A stable id for the preceding questions; the empty string for an opening question."""
    turns = context_turns(context)
    if not turns:
        return ""
    joined = f"{len(turns)}\x1d" + "\x1e".join(turns)
    return hashlib.sha256(joined.encode("utf-8")).hexdigest()[:16]


def cache_hash(question: str, context: Optional[Sequence[str]] = None) -> str:
    """The entry id for a question asked after ``context`` (earlier user questions).

    An opening question -- no preceding question -- keeps exactly ``query_hash``, so a
    standalone question still reuses the cache across conversations. Any later turn only
    matches an entry made after the same preceding questions. There is no anaphora word list:
    a standalone question asked second merely loses cross-conversation reuse, which costs
    time and never correctness.
    """
    fingerprint = context_fingerprint(context)
    if not fingerprint:
        return query_hash(question)
    joined = f"{normalise_query(question)}\x1f{fingerprint}"
    return hashlib.sha256(joined.encode("utf-8")).hexdigest()[:24]


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

    #: Roles whose policies are scoped to the individual ("own" spaces), so two people
    #: holding the SAME role can be owed different answers to the same words. "What is
    #: the temperature in my office" is one question and two rooms.
    _PER_USER_ROLES = frozenset({"occupant", "readonly", "guest", ""})

    @classmethod
    def _partition(
        cls, building_id: str, role: str, user_id: str, revision: str = None
    ) -> str:
        """The cache partition a requester may read from and write to.

        A cached answer is only reusable by someone the access policy would have given
        the same answer to. The PDP decides on ROLE, so role is part of the key; and for
        roles whose policies are scoped to a person's own spaces, on the PERSON too.

        This was measured, not theorised. With role absent from the key an occupant asked
        a room-level temperature question and was correctly refused above the k-floor;
        a facility_manager then asked the same words and was served the occupant's
        refusal; and with the order reversed the occupant received the facility
        manager's room-level reading verbatim — the very figure the PDP had just denied
        them. The leak traps never caught it because they run as a single user, and a
        cache that ignores who is asking makes the first requester's privilege the
        privilege of everyone after them.

        The cost is a lower hit rate on questions that are genuinely public. That is the
        right trade: a wrong-privilege answer is not a cheaper answer, it is a disclosure.

        WHO is asking was only half of it (BUG-498, V12-16). An answer is also only
        reusable while the CODE and the POLICY that produced it are still the ones in
        force, and neither was in the key. Measured 2026-09-10: a dishonest answer was
        served at 0.9 s — a cache hit — from a revision whose guard had since been fixed
        and redeployed. The running code would not have produced it; the cache did.

        `revision` closes that. `policy_admin.invalidate_policy_caches` already flushes
        on a policy edit, but a flush is best-effort — it is wrapped in try/except and
        logs a warning if the cache object is missing — so it fails OPEN, leaving stale
        answers servable. A key component fails CLOSED: a changed signature is a miss,
        with nothing to remember to do.
        """
        role = (role or "").strip().lower()
        scope = f"{role}:{user_id}" if role in cls._PER_USER_ROLES else role
        rev = (revision if revision is not None else REVISION) or "dev"
        # Revision LAST so `invalidate`'s `{building_id}|*` pattern still matches every
        # partition — partition-blind invalidation is deliberate and must keep working.
        return f"{building_id}|{scope}|r{rev}"

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
        self,
        question: str,
        building_id: str = "default",
        user_id: str = "",
        role: str = "",
        context: Optional[Sequence[str]] = None,
    ) -> Optional[Dict]:
        """
        Look up a cached response for the given question.

        ``context`` is the conversation's earlier USER questions, oldest first (BUG-668). A
        follow-up only matches an entry stored after the same ones; an opening question passes
        none and matches entries from any conversation.

        Returns:
            Dict with keys: response, intent, media, cached_at, hit_count
            or None if no cache hit.
        """
        if not self._enabled:
            return None

        qhash = cache_hash(question, context)
        partition = self._partition(building_id, role, user_id)
        cache_key = f"{self.PREFIX_EXACT}{partition}:{qhash}"

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
            fuzzy_result = await self._fuzzy_lookup(question, partition, context)
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
        user_id: str = "",
        role: str = "",
        context: Optional[Sequence[str]] = None,
    ):
        """
        Store a response in the cache.

        ``context`` must be what the matching ``get`` passed -- the earlier user questions --
        or the entry is unreachable (BUG-668).

        Non-cacheable intents (clarification, discovery, control) are skipped.
        """
        if not self._enabled:
            return

        if intent in NON_CACHEABLE_INTENTS:
            logger.debug(f"Response cache SKIP: intent '{intent}' is not cacheable")
            return

        qhash = cache_hash(question, context)
        partition = self._partition(building_id, role, user_id)
        cache_key = f"{self.PREFIX_EXACT}{partition}:{qhash}"

        entry = {
            "question": question,
            "context": context_turns(context),
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
            fuzzy_key = self._fuzzy_index_key(partition, context)
            await self._redis_hset(fuzzy_key, qhash, normalised)

    # ─────────────────────────────────────────────────────────────────────────
    # Cache invalidation
    # ─────────────────────────────────────────────────────────────────────────

    async def invalidate(
        self, question: str = None, building_id: str = "default", flush_all: bool = False
    ):
        """Invalidate cached responses across EVERY requester partition.

        Invalidation is deliberately partition-blind while lookup is partition-bound:
        entries are now keyed per role (and per person for individually-scoped roles),
        so a flush that matched only ``building_id:`` would leave every partition
        untouched and the stale answer would keep being served to the one requester who
        could still reach it.

        A single ``question`` reaches only its OPENING-question entries: an entry stored as a
        follow-up is keyed on the questions before it too (BUG-668), which a bare question
        cannot name. Nothing calls it that way today; use ``flush_all`` to be sure.
        """
        if flush_all:
            pattern = f"{self.PREFIX_EXACT}{building_id}|*"
            await self._redis_delete_pattern(pattern)
            await self._redis_delete_pattern(f"{self.PREFIX_FUZZY}{building_id}|*")
            logger.info(f"Response cache FLUSH: building={building_id} (all partitions)")
            return

        if question:
            qhash = query_hash(question)
            for key in await self._redis_keys(f"{self.PREFIX_EXACT}{building_id}|*:{qhash}"):
                await self._redis_delete(key)
            logger.info(f"Response cache INVALIDATE: {qhash[:12]} (all partitions)")

    async def invalidate_by_sensor(self, uuid: str, building_id: str = "default"):
        """Invalidate all cached responses that mention a specific sensor UUID."""
        pattern = f"{self.PREFIX_EXACT}{building_id}|*"
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

    @classmethod
    def _fuzzy_index_key(cls, partition: str, context: Optional[Sequence[str]] = None) -> str:
        """The fuzzy index a question is filed in: one per partition AND preceding questions.

        Similarity is only ever scored between questions asked after the SAME earlier
        questions (BUG-668), so a near-identical follow-up in another conversation is never
        a candidate. An opening question keeps the original per-partition index. The context
        rides after the partition, so `invalidate`'s `{building_id}|*` pattern still reaches it.
        """
        fingerprint = context_fingerprint(context)
        base = f"{cls.PREFIX_FUZZY}{partition}"
        return f"{base}|c{fingerprint}" if fingerprint else base

    async def _fuzzy_lookup(
        self, question: str, partition: str, context: Optional[Sequence[str]] = None
    ) -> Optional[Dict]:
        """Find the best fuzzy match for a question WITHIN the caller's partition.

        Takes a partition, not a building: a fuzzy match that crossed partitions would
        reintroduce the cross-role leak by the back door, and less visibly, since the
        served answer would not even be to the same question. For the same reason it takes
        the preceding questions: only entries made after the same ones are scored.
        """
        normalised = normalise_query(question)
        fuzzy_key = self._fuzzy_index_key(partition, context)
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
            cache_key = f"{self.PREFIX_EXACT}{partition}:{best_hash}"
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
