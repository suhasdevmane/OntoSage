# -*- coding: utf-8 -*-
"""The embedding setup must follow the model that is loaded, not a frozen constant.

Two defects, one cause: the code decided things about embeddings from the PROVIDER
name instead of the model.

  * The retrieval floor was `0.50 if EMBEDDING_PROVIDER == "local" else 0.35`. That
    0.50 was calibrated for MiniLM at 384 dimensions; the local model actually
    loaded is bge-large at 1024. A floor tuned for a model that is not running is
    worse than no floor, because it looks deliberate.
  * Nothing compared an EXISTING Qdrant collection's vector width against the
    current model. The SHA cache lives inside the collection, so unchanged
    documents skipped re-indexing, the collection kept its old width, and every
    search failed on a dimension mismatch — silently, since a failed search
    returns [].
"""

from __future__ import annotations

from types import SimpleNamespace

import pytest

from orchestrator.services.document_indexer import DocumentIndexer

pytestmark = pytest.mark.unit


# ── the floor follows the model ──────────────────────────────────────────────


class _Cfg:
    """Only what the property reads: an override and the loaded model name."""

    def __init__(self, model, override=None):
        self.DOCUMENT_SCORE_FLOOR = override
        self.embedding_model = model


def _floor(model, override=None):
    from shared.config import Settings

    return Settings.document_score_floor.fget(_Cfg(model, override))


@pytest.mark.parametrize(
    "model,expected",
    [
        # 0.55 since TODO-222: 0.45 admitted every retrieved hit (148/148 off-topic
        # and 187/187 on-topic in the labelled set), so it filtered nothing at all;
        # 0.50 was the free step; 0.55 removes 54% of off-topic document answers for
        # 18% of correct ones, re-derived post-routing at 2.60:1 on the questions the
        # floor can still reach.
        ("BAAI/bge-large-en-v1.5", 0.55),
        ("sentence-transformers/all-MiniLM-L6-v2", 0.50),
        ("text-embedding-3-small", 0.35),
    ],
)
def test_the_floor_is_keyed_on_the_model_not_the_provider(model, expected):
    assert _floor(model) == expected


def test_an_unknown_model_under_filters_rather_than_over_filters():
    """A new model must not silently drop real answers. Showing a weak chunk is
    recoverable; hiding the right one is not."""
    assert _floor("some/brand-new-embedder") <= 0.35


def test_an_explicit_override_wins():
    assert _floor("BAAI/bge-large-en-v1.5", override=0.62) == 0.62


def test_the_running_model_and_its_floor_agree():
    """The live setting must resolve to a floor that was chosen for THIS model —
    the defect was a 384-dimension floor applied to a 1024-dimension model."""
    from shared.config import settings

    assert "bge-large" in settings.embedding_model.lower()
    # Pinned deliberately: this number is expected to be TUNED, and a tuning that nobody
    # noticed is how a floor ends up calibrated for a model that is not running. Changing it
    # should require changing this line, with the measurement that justifies it.
    assert settings.document_score_floor == 0.55


# ── a collection built at another width is rebuilt ───────────────────────────


def _indexer(existing_size, embedder_dim, names=("documents_bldgX",)):
    idx = DocumentIndexer.__new__(DocumentIndexer)
    idx._embedder = SimpleNamespace(dimension=embedder_dim)
    deleted = []

    class _Q:
        async def get_collections(self):
            return SimpleNamespace(collections=[SimpleNamespace(name=n) for n in names])

        async def get_collection(self, _n):
            return SimpleNamespace(
                config=SimpleNamespace(
                    params=SimpleNamespace(vectors=SimpleNamespace(size=existing_size))
                )
            )

        async def delete_collection(self, n):
            deleted.append(n)

    idx._qdrant = _Q()
    return idx, deleted


async def test_a_collection_of_the_wrong_width_is_dropped():
    idx, deleted = _indexer(existing_size=384, embedder_dim=1024)
    assert await idx._ensure_dimension("documents_bldgX") is True
    assert deleted == ["documents_bldgX"], "the stale-width collection must be removed"


async def test_a_matching_collection_is_left_alone():
    idx, deleted = _indexer(existing_size=1024, embedder_dim=1024)
    assert await idx._ensure_dimension("documents_bldgX") is False
    assert deleted == [], "a usable collection must never be destroyed"


async def test_a_collection_that_does_not_exist_yet_is_not_an_error():
    idx, deleted = _indexer(existing_size=1024, embedder_dim=1024, names=())
    assert await idx._ensure_dimension("documents_bldgX") is False
    assert deleted == []


async def test_a_failing_check_never_blocks_indexing():
    """Qdrant being briefly unavailable must not stop documents being indexed."""
    idx, _ = _indexer(existing_size=384, embedder_dim=1024)

    async def _boom(_n):
        raise RuntimeError("qdrant unreachable")

    idx._qdrant.get_collection = _boom
    assert await idx._ensure_dimension("documents_bldgX") is False


def test_the_width_check_runs_before_the_sha_cache_is_read():
    """The SHA cache lives INSIDE the collection, so reading it first would report
    every file unchanged and the stale collection would never be rebuilt."""
    import inspect

    src = inspect.getsource(DocumentIndexer.index_building)
    assert src.index("_ensure_dimension") < src.index("_load_existing_shas")


# ── the MODEL settles its own width ──────────────────────────────────────────


@pytest.mark.parametrize(
    "model,expected",
    [
        ("BAAI/bge-large-en-v1.5", 1024),
        ("BAAI/bge-small-en-v1.5", 384),
        ("sentence-transformers/all-MiniLM-L6-v2", 384),
        ("sentence-transformers/all-mpnet-base-v2", 768),
        ("text-embedding-3-small", 1536),
        ("text-embedding-3-large", 3072),
    ],
)
def test_a_known_model_reports_its_real_width(model, expected):
    from shared.config import dimension_for_model

    assert dimension_for_model(model) == expected


def test_an_unknown_model_defers_to_the_configured_value():
    from shared.config import dimension_for_model

    assert dimension_for_model("some/model-nobody-has-shipped-yet") is None


def test_the_model_overrides_a_stale_configured_dimension():
    """The failure this prevents: EMBEDDING_MODEL_LOCAL is changed to MiniLM while
    EMBEDDING_DIMENSION_LOCAL is left at 1024. Every collection would be built 1024
    wide for a model emitting 384, and searches would return nothing rather than
    raise."""
    from shared.config import Settings

    class _S:
        EMBEDDING_PROVIDER = "local"
        EMBEDDING_DIMENSION_LOCAL = 1024  # stale
        EMBEDDING_DIMENSION_OPENAI = 1536
        embedding_model = "sentence-transformers/all-MiniLM-L6-v2"  # actually 384

    assert Settings.embedding_dimension.fget(_S()) == 384


def test_the_configured_value_still_applies_to_an_unknown_model():
    from shared.config import Settings

    class _S:
        EMBEDDING_PROVIDER = "local"
        EMBEDDING_DIMENSION_LOCAL = 999
        EMBEDDING_DIMENSION_OPENAI = 1536
        embedding_model = "some/model-nobody-has-shipped-yet"

    assert Settings.embedding_dimension.fget(_S()) == 999


def test_the_running_configuration_is_internally_consistent():
    """bge-large at 1024 — the model, the setting and the derived value must agree."""
    from shared.config import dimension_for_model, settings

    assert settings.embedding_dimension == 1024
    assert dimension_for_model(settings.embedding_model) == settings.embedding_dimension
    assert settings.EMBEDDING_DIMENSION_LOCAL == settings.embedding_dimension
