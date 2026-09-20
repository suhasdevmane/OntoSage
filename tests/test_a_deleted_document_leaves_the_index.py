# -*- coding: utf-8 -*-
"""A document deleted from disk stops being searchable.

Measured 2026-09-18: the document index held `water_hygiene_legionella.md` and
`asbestos_register.md`, neither of which exists in `input/documents/`. "Are there any showers in
the building?" was answered from the first, contradicting the building's authored data. Indexing
added and updated; nothing removed. Replacing placeholder documents with real ones means deleting
files, so without this the placeholders stay searchable beside the real ones for ever.

The property that matters most is what the prune can NOT do: an unmounted volume or an emptied
folder must never wipe the index.
"""

from __future__ import annotations

import hashlib
from unittest.mock import AsyncMock, MagicMock

import pytest

from orchestrator.services.document_indexer import DocumentIndexer

pytestmark = pytest.mark.unit


def _qdrant(existing: dict):
    m = AsyncMock()
    cols = MagicMock()
    col = MagicMock()
    col.name = "documents_bldg1"
    cols.collections = [col] if existing else []
    m.get_collections = AsyncMock(return_value=cols)
    records = []
    for fname, sha in existing.items():
        rec = MagicMock()
        rec.payload = {"doc_filename": fname, "file_sha": sha, "building_id": "bldg1"}
        records.append(rec)
    m.scroll = AsyncMock(return_value=(records, None))
    m.create_collection = AsyncMock()
    m.delete_collection = AsyncMock()
    m.upsert = AsyncMock()
    m.delete = AsyncMock()
    return m


def _embedder():
    m = AsyncMock()
    m.dimension = 4
    m.embed_batch = AsyncMock(side_effect=lambda texts: [[0.1] * 4 for _ in texts])
    return m


def _deleted_names(qdrant):
    """The doc_filename list of every delete the indexer sent."""
    out = []
    for call in qdrant.delete.await_args_list:
        selector = call.kwargs["points_selector"]
        out.append(list(selector.must[0].match.any))
    return out


def _docs(tmp_path, **files):
    d = tmp_path / "bldg1" / "documents"
    d.mkdir(parents=True)
    shas = {}
    for name, text in files.items():
        p = d / name
        p.write_text(text)
        shas[name] = hashlib.sha256(p.read_bytes()).hexdigest()
    return d, shas


@pytest.mark.asyncio
async def test_an_indexed_document_with_no_file_is_removed_from_the_index(tmp_path):
    _, shas = _docs(tmp_path, **{"policy.md": "Policy content."})
    qdrant = _qdrant({**shas, "water_hygiene_legionella.md": "deadbeef", "asbestos_register.md": "x"})
    indexer = DocumentIndexer(qdrant, _embedder(), input_root=str(tmp_path))

    result = await indexer.index_building("bldg1")

    assert result.pruned_files == ["asbestos_register.md", "water_hygiene_legionella.md"]
    assert _deleted_names(qdrant) == [["asbestos_register.md", "water_hygiene_legionella.md"]]
    assert result.status == "skipped", "nothing changed on disk, so nothing is re-embedded"


@pytest.mark.asyncio
async def test_a_document_that_is_still_on_disk_is_never_pruned(tmp_path):
    _, shas = _docs(tmp_path, **{"a.md": "Alpha.", "b.md": "Bravo."})
    qdrant = _qdrant(shas)
    indexer = DocumentIndexer(qdrant, _embedder(), input_root=str(tmp_path))

    result = await indexer.index_building("bldg1")

    assert result.pruned_files == []
    qdrant.delete.assert_not_awaited()


@pytest.mark.asyncio
async def test_a_folder_that_is_missing_prunes_nothing(tmp_path):
    """An unmounted volume looks exactly like this. It must not wipe the index."""
    (tmp_path / "bldg1").mkdir()  # no documents/ at all
    qdrant = _qdrant({"policy.md": "abc"})
    indexer = DocumentIndexer(qdrant, _embedder(), input_root=str(tmp_path))

    result = await indexer.index_building("bldg1")

    assert result.status == "no_documents"
    qdrant.delete.assert_not_awaited()
    qdrant.delete_collection.assert_not_awaited()


@pytest.mark.asyncio
async def test_an_emptied_folder_prunes_nothing(tmp_path):
    """No supported file at all is indistinguishable from a failed mount, so it is left alone."""
    (tmp_path / "bldg1" / "documents").mkdir(parents=True)
    qdrant = _qdrant({"policy.md": "abc"})
    indexer = DocumentIndexer(qdrant, _embedder(), input_root=str(tmp_path))

    result = await indexer.index_building("bldg1")

    assert result.status == "no_documents"
    qdrant.delete.assert_not_awaited()


@pytest.mark.asyncio
async def test_a_changed_document_and_a_removed_one_are_both_handled(tmp_path):
    _, shas = _docs(tmp_path, **{"keep.md": "Kept and unchanged.", "edit.md": "Edited text now."})
    stale = dict(shas)
    stale["edit.md"] = "an-older-sha"
    qdrant = _qdrant({**stale, "gone.md": "abc"})
    indexer = DocumentIndexer(qdrant, _embedder(), input_root=str(tmp_path))

    result = await indexer.index_building("bldg1")

    assert result.pruned_files == ["gone.md"]
    assert result.status == "indexed"
    assert "edit.md" in result.indexed_files and "keep.md" in result.skipped_files
    assert ["gone.md"] in _deleted_names(qdrant)
