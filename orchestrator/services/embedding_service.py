"""
EmbeddingService — provider-agnostic text embedding with Redis caching.

Used by:
  - CapabilityIndexer (startup-time: batch-embed KB entries into Qdrant)
  - SemanticRouter   (query-time: embed user query, search Qdrant)

Provider auto-switch:
  - settings.EMBEDDING_PROVIDER == "openai" → openai.AsyncOpenAI().embeddings.create(...)
  - settings.EMBEDDING_PROVIDER == "local"  → sentence-transformers (run in executor)

Cache:
  - Redis key: cache:embed:<sha256(text+":"+provider+":"+model)>
  - TTL: settings.EMBEDDING_CACHE_TTL_SECONDS (default 24h)
  - Cache key includes provider+model so a provider/model switch invalidates cleanly.

Retry policy:
  - 3 attempts with exponential backoff (1s, 2s, 4s)
  - Persistent failure raises EmbeddingServiceError
"""

from __future__ import annotations

import asyncio
import hashlib
import json
from typing import List, Optional

from shared.config import settings
from shared.utils import get_logger

logger = get_logger(__name__)

# Per-provider maximum input length (characters, conservative).
# OpenAI text-embedding-3-small accepts ~8191 tokens (~32000 chars).
# Local sentence-transformers: bge-large-en-v1.5 max_seq_length is 512 tokens (~2048 chars);
# the model truncates internally, so 2048 lets a full ~500-token doc chunk be embedded
# (MiniLM's old 256-token/1024-char limit dropped half of each chunk).
_PROVIDER_MAX_CHARS = {
    "openai": 30000,
    "local": 2048,
}

_RETRY_BACKOFF_SECONDS = (1.0, 2.0, 4.0)


class EmbeddingServiceError(Exception):
    """Raised when embedding generation fails after all retries."""


class EmbeddingService:
    """Provider-agnostic embedding wrapper. See module docstring."""

    def __init__(
        self,
        redis_manager=None,
        provider: Optional[str] = None,
        cache_ttl_seconds: Optional[int] = None,
    ):
        self._redis = redis_manager
        self._provider = provider or settings.EMBEDDING_PROVIDER
        self._cache_ttl = cache_ttl_seconds or getattr(
            settings, "EMBEDDING_CACHE_TTL_SECONDS", 86400
        )
        self._model_name = (
            settings.EMBEDDING_MODEL_OPENAI
            if self._provider == "openai"
            else settings.EMBEDDING_MODEL_LOCAL
        )
        self._dimension = (
            settings.EMBEDDING_DIMENSION_OPENAI
            if self._provider == "openai"
            else settings.EMBEDDING_DIMENSION_LOCAL
        )
        # Lazy-loaded local model — only instantiated if EMBEDDING_PROVIDER=local
        self._local_model = None

    @property
    def dimension(self) -> int:
        """Vector dimension for the current provider."""
        return self._dimension

    @property
    def provider(self) -> str:
        """Current provider identifier ('openai' or 'local')."""
        return self._provider

    @property
    def model(self) -> str:
        """Current model identifier."""
        return self._model_name

    async def embed(self, text: str) -> List[float]:
        """Embed a single text. Raises ValueError on empty input.

        Caches result in Redis if redis_manager was provided.
        Truncates input to provider's max chars before embedding.
        """
        if not text or not text.strip():
            raise ValueError("EmbeddingService.embed: text cannot be empty")

        truncated = text[: _PROVIDER_MAX_CHARS.get(self._provider, 30000)]
        cache_key = self._cache_key(truncated)

        # Cache lookup
        if self._redis is not None:
            cached = await self._redis.get_cache(cache_key)
            if cached is not None:
                # Stored as list[float]
                return cached if isinstance(cached, list) else json.loads(cached)

        # Cache miss — call provider
        vector = await self._embed_with_retries(truncated)

        # Cache store (best-effort)
        if self._redis is not None:
            try:
                await self._redis.set_cache(cache_key, vector, ttl=self._cache_ttl)
            except Exception as e:
                logger.debug(f"[embedding] cache store failed (non-fatal): {e}")

        return vector

    async def embed_batch(self, texts: List[str]) -> List[List[float]]:
        """Embed a list of texts. Preserves order. Empty list → empty result.

        Per-item cache lookup so a partial cache hit doesn't re-embed cached items.
        Uncached items are batched together for one provider call.
        """
        if not texts:
            return []
        if any(not t or not t.strip() for t in texts):
            raise ValueError("EmbeddingService.embed_batch: all texts must be non-empty")

        max_chars = _PROVIDER_MAX_CHARS.get(self._provider, 30000)
        truncated_texts = [t[:max_chars] for t in texts]
        results: List[Optional[List[float]]] = [None] * len(truncated_texts)
        misses: List[int] = []

        # Per-item cache lookup
        if self._redis is not None:
            for i, t in enumerate(truncated_texts):
                cached = await self._redis.get_cache(self._cache_key(t))
                if cached is not None:
                    results[i] = cached if isinstance(cached, list) else json.loads(cached)
                else:
                    misses.append(i)
        else:
            misses = list(range(len(truncated_texts)))

        # Batch-call provider for misses
        if misses:
            miss_texts = [truncated_texts[i] for i in misses]
            miss_vectors = await self._embed_batch_with_retries(miss_texts)
            for i, vec in zip(misses, miss_vectors):
                results[i] = vec
                if self._redis is not None:
                    try:
                        await self._redis.set_cache(
                            self._cache_key(truncated_texts[i]),
                            vec,
                            ttl=self._cache_ttl,
                        )
                    except Exception as e:
                        logger.debug(f"[embedding] batch cache store failed (non-fatal): {e}")

        return results  # type: ignore[return-value]

    # ── internal: cache key ─────────────────────────────────────────────────────

    def _cache_key(self, text: str) -> str:
        """sha256(text + ":" + provider + ":" + model) → cache:embed:<hash>.

        Including provider+model means a provider/model switch invalidates
        the cache automatically (different key namespace).
        """
        h = hashlib.sha256(
            f"{text}:{self._provider}:{self._model_name}".encode("utf-8")
        ).hexdigest()
        return f"cache:embed:{h}"

    # ── internal: retry wrappers ────────────────────────────────────────────────

    async def _embed_with_retries(self, text: str) -> List[float]:
        last_exc: Optional[Exception] = None
        for attempt, backoff in enumerate(_RETRY_BACKOFF_SECONDS, start=1):
            try:
                return await self._embed_single(text)
            except Exception as e:
                last_exc = e
                logger.warning(
                    f"[embedding] attempt {attempt}/{len(_RETRY_BACKOFF_SECONDS)} "
                    f"failed for provider={self._provider}: {e}"
                )
                if attempt < len(_RETRY_BACKOFF_SECONDS):
                    await asyncio.sleep(backoff)
        raise EmbeddingServiceError(
            f"All {len(_RETRY_BACKOFF_SECONDS)} embed attempts failed: {last_exc}"
        ) from last_exc

    async def _embed_batch_with_retries(self, texts: List[str]) -> List[List[float]]:
        last_exc: Optional[Exception] = None
        for attempt, backoff in enumerate(_RETRY_BACKOFF_SECONDS, start=1):
            try:
                return await self._embed_batch(texts)
            except Exception as e:
                last_exc = e
                logger.warning(
                    f"[embedding] batch attempt {attempt}/{len(_RETRY_BACKOFF_SECONDS)} "
                    f"failed for provider={self._provider}: {e}"
                )
                if attempt < len(_RETRY_BACKOFF_SECONDS):
                    await asyncio.sleep(backoff)
        raise EmbeddingServiceError(
            f"All {len(_RETRY_BACKOFF_SECONDS)} batch embed attempts failed: {last_exc}"
        ) from last_exc

    # ── internal: provider-specific implementations ─────────────────────────────

    async def _embed_single(self, text: str) -> List[float]:
        if self._provider == "openai":
            return await self._embed_openai_single(text)
        return await self._embed_local_single(text)

    async def _embed_batch(self, texts: List[str]) -> List[List[float]]:
        if self._provider == "openai":
            return await self._embed_openai_batch(texts)
        return await self._embed_local_batch(texts)

    async def _embed_openai_single(self, text: str) -> List[float]:
        from openai import AsyncOpenAI

        client = AsyncOpenAI(api_key=settings.OPENAI_API_KEY)
        resp = await client.embeddings.create(model=self._model_name, input=text)
        return list(resp.data[0].embedding)

    async def _embed_openai_batch(self, texts: List[str]) -> List[List[float]]:
        from openai import AsyncOpenAI

        client = AsyncOpenAI(api_key=settings.OPENAI_API_KEY)
        resp = await client.embeddings.create(model=self._model_name, input=texts)
        # OpenAI preserves input order in resp.data
        return [list(item.embedding) for item in resp.data]

    async def _embed_local_single(self, text: str) -> List[float]:
        model = self._get_local_model()
        loop = asyncio.get_event_loop()
        vec = await loop.run_in_executor(
            None, lambda: model.encode(text, convert_to_numpy=True).tolist()
        )
        return vec

    async def _embed_local_batch(self, texts: List[str]) -> List[List[float]]:
        model = self._get_local_model()
        loop = asyncio.get_event_loop()
        vecs = await loop.run_in_executor(
            None,
            lambda: model.encode(texts, convert_to_numpy=True, batch_size=32).tolist(),
        )
        return vecs

    def _get_local_model(self):
        """Lazy-load sentence-transformers model."""
        if self._local_model is None:
            from sentence_transformers import SentenceTransformer

            logger.info(f"[embedding] loading local model: {self._model_name}")
            self._local_model = SentenceTransformer(self._model_name)
        return self._local_model

    def warm(self) -> None:
        """Eagerly load the local embedding model so the first user request does
        not pay the ~5-7s cold-load. No-op for the OpenAI provider. Safe to call
        from a startup background thread (model load is CPU-bound and sync)."""
        if self._provider != "local":
            return
        try:
            self._get_local_model()
            logger.info("[embedding] local model warmed at startup")
        except Exception as e:
            logger.warning(f"[embedding] warm-up failed (non-fatal): {e}")
