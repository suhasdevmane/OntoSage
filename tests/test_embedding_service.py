"""
Unit tests for orchestrator.services.embedding_service.EmbeddingService.

Covers §16.1.1 of the capability semantic routing spec.
Twelve tests:
  1. dimension correctness for OpenAI provider
  2. dimension correctness for local provider
  3. batch preserves order
  4. embed caches in Redis
  5. cache TTL ~ 24h
  6. retries on transient failure
  7. raises after 3 retries
  8. dimension property matches provider
  9. empty string raises
 10. very long text truncated (no crash)
 11. unicode handled
 12. provider switch invalidates cache (different key namespace)
"""

from __future__ import annotations

import asyncio
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from orchestrator.services.embedding_service import (
    EmbeddingService,
    EmbeddingServiceError,
    _PROVIDER_MAX_CHARS,
)


# ── Helpers ─────────────────────────────────────────────────────────────────────


class _FakeRedis:
    """In-memory stand-in for RedisManager.get_cache / set_cache."""

    def __init__(self):
        self.store = {}
        self.ttls = {}
        self.get_calls = 0
        self.set_calls = 0

    async def get_cache(self, key):
        self.get_calls += 1
        return self.store.get(key)

    async def set_cache(self, key, value, ttl=3600):
        self.set_calls += 1
        self.store[key] = value
        self.ttls[key] = ttl
        return True


def _fake_openai_response(vectors):
    """Build the structure openai.AsyncOpenAI().embeddings.create returns."""
    resp = MagicMock()
    resp.data = [MagicMock(embedding=v) for v in vectors]
    return resp


# ── Tests ───────────────────────────────────────────────────────────────────────


async def test_embed_returns_correct_dimension_openai():
    """Test 1: provider=openai → vector length matches EMBEDDING_DIMENSION_OPENAI."""
    redis = _FakeRedis()
    svc = EmbeddingService(redis_manager=redis, provider="openai")
    assert svc.dimension == 1536

    fake_vec = [0.1] * 1536
    with patch("openai.AsyncOpenAI") as mock_client_cls:
        mock_client = mock_client_cls.return_value
        mock_client.embeddings.create = AsyncMock(return_value=_fake_openai_response([fake_vec]))
        vec = await svc.embed("hello")

    assert isinstance(vec, list)
    assert len(vec) == 1536


async def test_embed_returns_correct_dimension_local():
    """Test 2: provider=local → vector length matches EMBEDDING_DIMENSION_LOCAL.

    We patch the local model loader so no sentence-transformers download happens
    in unit tests.
    """
    redis = _FakeRedis()
    svc = EmbeddingService(redis_manager=redis, provider="local")
    assert svc.dimension == 384

    fake_vec = [0.05] * 384
    mock_model = MagicMock()
    mock_model.encode.return_value = MagicMock(tolist=MagicMock(return_value=fake_vec))
    svc._local_model = mock_model  # bypass SentenceTransformer load

    vec = await svc.embed("hello")
    assert len(vec) == 384


async def test_embed_batch_preserves_order():
    """Test 3: embed_batch(["a","b","c"])[i] corresponds to input i."""
    redis = _FakeRedis()
    svc = EmbeddingService(redis_manager=redis, provider="openai")

    vec_a = [1.0] * 1536
    vec_b = [2.0] * 1536
    vec_c = [3.0] * 1536

    with patch("openai.AsyncOpenAI") as mock_client_cls:
        mock_client = mock_client_cls.return_value
        mock_client.embeddings.create = AsyncMock(
            return_value=_fake_openai_response([vec_a, vec_b, vec_c])
        )
        out = await svc.embed_batch(["a", "b", "c"])

    assert out[0][0] == 1.0
    assert out[1][0] == 2.0
    assert out[2][0] == 3.0


async def test_embed_caches_in_redis():
    """Test 4: second embed of same text makes 0 API calls."""
    redis = _FakeRedis()
    svc = EmbeddingService(redis_manager=redis, provider="openai")

    fake_vec = [0.42] * 1536
    create_mock = AsyncMock(return_value=_fake_openai_response([fake_vec]))

    with patch("openai.AsyncOpenAI") as mock_client_cls:
        mock_client_cls.return_value.embeddings.create = create_mock

        v1 = await svc.embed("hello world")
        v2 = await svc.embed("hello world")

    assert v1 == v2
    assert create_mock.call_count == 1, "Second call should hit Redis cache, not API"
    assert redis.set_calls == 1
    assert redis.get_calls == 2  # one miss, one hit


async def test_embed_cache_ttl_matches_settings():
    """Test 5: Redis TTL on cache:embed:* matches configured value (default ~24h)."""
    redis = _FakeRedis()
    svc = EmbeddingService(redis_manager=redis, provider="openai", cache_ttl_seconds=86400)

    fake_vec = [0.1] * 1536
    with patch("openai.AsyncOpenAI") as mock_client_cls:
        mock_client_cls.return_value.embeddings.create = AsyncMock(
            return_value=_fake_openai_response([fake_vec])
        )
        await svc.embed("ttl test")

    assert len(redis.ttls) == 1
    ttl = list(redis.ttls.values())[0]
    assert 86000 <= ttl <= 86500, f"TTL out of expected band: {ttl}"


async def test_embed_retries_on_transient_failure():
    """Test 6: 503 then 200 → returns vector after 1 retry."""
    redis = _FakeRedis()
    svc = EmbeddingService(redis_manager=redis, provider="openai")

    fake_vec = [0.7] * 1536
    call_count = {"n": 0}

    async def flaky(*_args, **_kwargs):
        call_count["n"] += 1
        if call_count["n"] == 1:
            raise RuntimeError("503 Service Unavailable")
        return _fake_openai_response([fake_vec])

    with patch("openai.AsyncOpenAI") as mock_client_cls, \
         patch("orchestrator.services.embedding_service.asyncio.sleep", new=AsyncMock()):
        mock_client_cls.return_value.embeddings.create = flaky
        vec = await svc.embed("retry test")

    assert len(vec) == 1536
    assert call_count["n"] == 2, "Should have retried once after first failure"


async def test_embed_raises_after_three_retries():
    """Test 7: persistent 503 × N → raises EmbeddingServiceError."""
    redis = _FakeRedis()
    svc = EmbeddingService(redis_manager=redis, provider="openai")

    async def always_fail(*_args, **_kwargs):
        raise RuntimeError("persistent failure")

    with patch("openai.AsyncOpenAI") as mock_client_cls, \
         patch("orchestrator.services.embedding_service.asyncio.sleep", new=AsyncMock()):
        mock_client_cls.return_value.embeddings.create = always_fail
        with pytest.raises(EmbeddingServiceError):
            await svc.embed("doomed")


def test_dimension_property_matches_provider():
    """Test 8: .dimension reads from the right setting per provider."""
    svc_openai = EmbeddingService(provider="openai")
    svc_local = EmbeddingService(provider="local")

    assert svc_openai.dimension == 1536
    assert svc_local.dimension == 384


async def test_embed_empty_string_raises():
    """Test 9: empty / whitespace-only input raises ValueError."""
    svc = EmbeddingService(provider="openai")

    with pytest.raises(ValueError):
        await svc.embed("")
    with pytest.raises(ValueError):
        await svc.embed("   ")


async def test_embed_very_long_text_truncated():
    """Test 10: 100k-char input is truncated, does not crash."""
    redis = _FakeRedis()
    svc = EmbeddingService(redis_manager=redis, provider="openai")

    fake_vec = [0.0] * 1536
    create_mock = AsyncMock(return_value=_fake_openai_response([fake_vec]))

    with patch("openai.AsyncOpenAI") as mock_client_cls:
        mock_client_cls.return_value.embeddings.create = create_mock

        big_text = "a" * 100000
        vec = await svc.embed(big_text)

    assert len(vec) == 1536
    # Verify truncation: openai mock should have been called with text ≤ provider max
    called_with = create_mock.call_args.kwargs["input"]
    max_chars = _PROVIDER_MAX_CHARS["openai"]
    assert len(called_with) <= max_chars


async def test_embed_unicode_handled():
    """Test 11: non-ASCII input does not raise UnicodeError."""
    redis = _FakeRedis()
    svc = EmbeddingService(redis_manager=redis, provider="openai")

    fake_vec = [0.0] * 1536
    with patch("openai.AsyncOpenAI") as mock_client_cls:
        mock_client_cls.return_value.embeddings.create = AsyncMock(
            return_value=_fake_openai_response([fake_vec])
        )
        # Includes Chinese, emoji, French — must not raise
        vec = await svc.embed("室温 🌡️ — quelle température fait-il?")

    assert len(vec) == 1536


async def test_provider_switch_invalidates_cache():
    """Test 12: switching provider produces different cache key for same text.

    This is the property that lets a deployment switch from local→openai (or vice
    versa) without serving stale 384-dim vectors when we now need 1536-dim.
    """
    redis = _FakeRedis()

    svc_openai = EmbeddingService(redis_manager=redis, provider="openai")
    svc_local = EmbeddingService(redis_manager=redis, provider="local")

    key_openai = svc_openai._cache_key("same text")
    key_local = svc_local._cache_key("same text")

    assert key_openai != key_local, "Different providers must produce different cache keys"

    # And the model name is also in the key, so a model change also invalidates
    svc_openai_alt = EmbeddingService(redis_manager=redis, provider="openai")
    svc_openai_alt._model_name = "different-model"
    assert svc_openai._cache_key("same text") != svc_openai_alt._cache_key("same text")
