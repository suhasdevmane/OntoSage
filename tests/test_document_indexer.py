"""T08 — Document KB indexer unit tests.

Covers:
  1. _chunk_text splits text into overlapping chunks
  2. index_building skips files with matching SHA
  3. index_building indexes new files and writes points
  4. index_building returns no_documents when folder absent
  5. Degraded status on Qdrant failure (non-fatal)
"""

from __future__ import annotations

import hashlib
import math
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from orchestrator.services.document_indexer import DocumentIndexer, DocIndexResult, _chunk_text

# ─── _chunk_text ──────────────────────────────────────────────────────────────


def test_chunk_text_empty_returns_empty():
    assert _chunk_text("") == []


def test_chunk_text_short_document_is_single_chunk():
    text = "The building has sensors on floor 5."
    chunks = _chunk_text(text, chunk_words=400)
    assert len(chunks) == 1
    assert chunks[0] == text.strip()


def test_chunk_text_long_document_produces_multiple_chunks():
    # 1000-word document should produce multiple chunks with 400-word target
    words = ["word"] * 1000
    text = " ".join(words)
    chunks = _chunk_text(text, chunk_words=400)
    assert len(chunks) > 1
    # Each chunk has at most 400 words
    for chunk in chunks:
        assert len(chunk.split()) <= 400


def test_chunk_text_overlapping():
    """With 80% step, chunks should overlap."""
    words = [str(i) for i in range(100)]
    text = " ".join(words)
    chunks = _chunk_text(text, chunk_words=20)
    # First chunk starts at 0, step is 16 → overlap of 4 words
    assert chunks[0].split()[0] == "0"
    assert chunks[1].split()[0] == "16"


# ─── Fixtures ─────────────────────────────────────────────────────────────────


def _make_qdrant_mock(existing_shas: dict | None = None):
    """Return a mock AsyncQdrantClient."""
    m = AsyncMock()

    # get_collections — return empty unless we're told otherwise
    collections_result = MagicMock()
    collections_result.collections = []
    m.get_collections = AsyncMock(return_value=collections_result)

    # scroll — simulate per-file SHA tracking
    if existing_shas:
        records = []
        for fname, sha in existing_shas.items():
            rec = MagicMock()
            rec.payload = {"doc_filename": fname, "file_sha": sha, "building_id": "bldg1"}
            records.append(rec)
        # Pretend collection exists
        mock_col = MagicMock()
        mock_col.name = "documents_bldg1"
        collections_result.collections = [mock_col]
        m.scroll = AsyncMock(return_value=(records, None))
    else:
        m.scroll = AsyncMock(return_value=([], None))

    m.create_collection = AsyncMock()
    m.delete_collection = AsyncMock()
    m.upsert = AsyncMock()
    return m


def _make_embedder_mock(dim: int = 4):
    m = AsyncMock()
    m.dimension = dim
    m.embed_batch = AsyncMock(side_effect=lambda texts: [[0.1] * dim for _ in texts])
    m.embed_single = AsyncMock(return_value=[0.1] * dim)
    return m


# ─── index_building ───────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_index_building_no_documents_dir(tmp_path):
    qdrant = _make_qdrant_mock()
    embedder = _make_embedder_mock()
    indexer = DocumentIndexer(qdrant, embedder, input_root=str(tmp_path))
    (tmp_path / "bldg1").mkdir()  # no documents/ subdir

    result = await indexer.index_building("bldg1")
    assert result.status == "no_documents"
    qdrant.upsert.assert_not_called()


@pytest.mark.asyncio
async def test_index_building_indexes_new_file(tmp_path):
    qdrant = _make_qdrant_mock()
    embedder = _make_embedder_mock()
    indexer = DocumentIndexer(qdrant, embedder, input_root=str(tmp_path))

    docs_dir = tmp_path / "bldg1" / "documents"
    docs_dir.mkdir(parents=True)
    (docs_dir / "governance.md").write_text("This is the governance document. " * 10)

    result = await indexer.index_building("bldg1")
    assert result.status == "indexed"
    assert "governance.md" in result.indexed_files
    assert result.chunks > 0
    qdrant.upsert.assert_called()


@pytest.mark.asyncio
async def test_index_building_skips_unchanged_file(tmp_path):
    docs_dir = tmp_path / "bldg1" / "documents"
    docs_dir.mkdir(parents=True)
    doc_file = docs_dir / "policy.md"
    doc_file.write_text("Policy content.")

    sha = hashlib.sha256(doc_file.read_bytes()).hexdigest()
    qdrant = _make_qdrant_mock(existing_shas={"policy.md": sha})
    embedder = _make_embedder_mock()
    indexer = DocumentIndexer(qdrant, embedder, input_root=str(tmp_path))

    result = await indexer.index_building("bldg1")
    assert result.status == "skipped"
    assert "policy.md" in result.skipped_files
    embedder.embed_batch.assert_not_called()


@pytest.mark.asyncio
async def test_index_building_degraded_on_qdrant_error(tmp_path):
    qdrant = _make_qdrant_mock()
    qdrant.upsert = AsyncMock(side_effect=Exception("Qdrant unavailable"))
    embedder = _make_embedder_mock()
    indexer = DocumentIndexer(qdrant, embedder, input_root=str(tmp_path))

    docs_dir = tmp_path / "bldg1" / "documents"
    docs_dir.mkdir(parents=True)
    (docs_dir / "doc.md").write_text("Some content.")

    result = await indexer.index_building("bldg1")
    assert result.status == "degraded"


@pytest.mark.asyncio
async def test_index_all_buildings_skips_dirs_without_documents(tmp_path):
    """Buildings without a documents/ dir are silently skipped."""
    (tmp_path / "bldg1").mkdir()
    (tmp_path / "bldg2").mkdir()
    # bldg2 has documents
    docs = tmp_path / "bldg2" / "documents"
    docs.mkdir()
    (docs / "manual.md").write_text("Manual content.")

    qdrant = _make_qdrant_mock()
    embedder = _make_embedder_mock()
    indexer = DocumentIndexer(qdrant, embedder, input_root=str(tmp_path))

    results = await indexer.index_all_buildings()
    assert "bldg1" not in results
    assert "bldg2" in results
    assert results["bldg2"].status == "indexed"
