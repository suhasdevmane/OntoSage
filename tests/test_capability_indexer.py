"""
Unit tests for orchestrator.services.capability_indexer.CapabilityIndexer.

Covers §16.1.2 of the capability semantic routing spec.

Fourteen tests:
   1. first_index_creates_collection
   2. unchanged_yaml_skips_reindex (idempotency core)
   3. changed_yaml_rebuilds_collection
   4. point_count_matches_keyword_sum
   5. yaml_sha_recorded_in_payload
   6. uuid_v5_deterministic
   7. missing_yaml_returns_degraded
   8. malformed_yaml_returns_degraded
   9. qdrant_unreachable_returns_degraded
  10. embedding_api_down_returns_degraded
  11. dim_mismatch_rebuilds
  12. multiple_buildings_isolated
  13. batch_upsert_used_for_efficiency
  14. disabled_config_skipped
"""

from __future__ import annotations

import hashlib
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock

import pytest

from orchestrator.services.capability_indexer import (
    CapabilityIndexer,
    IndexResult,
    _CAPABILITY_NAMESPACE,
)


# ── Fixtures ────────────────────────────────────────────────────────────────────


_MINIMAL_CAPABILITY_YAML = """
building_info:
  id: testbldg
  name: Test Building
capabilities:
  - id: fire_safety
    category: FIRE_SAFETY
    keywords: [fire, evacuation, smoke detector]
    content: Fire safety features include smoke detectors and sprinklers.
    source: test_source
  - id: lift_details
    category: ACCESSIBILITY
    keywords: [lift dimensions, lift weight, braille lift]
    content: Lift is 106cm x 220cm, weight limit 1000kg.
    source: test_source
"""


def _write_capability_yaml(root: Path, building_id: str, content: str) -> Path:
    bldg_dir = root / building_id
    bldg_dir.mkdir(parents=True, exist_ok=True)
    yaml_path = bldg_dir / "capability.yaml"
    yaml_path.write_text(content, encoding="utf-8")
    return yaml_path


def _write_building_yaml(root: Path, building_id: str, routing_block: str = "") -> Path:
    bldg_dir = root / building_id
    bldg_dir.mkdir(parents=True, exist_ok=True)
    bldg_path = bldg_dir / "building.yaml"
    bldg_path.write_text(routing_block, encoding="utf-8")
    return bldg_path


class _FakeEmbedder:
    """Stand-in for EmbeddingService."""

    def __init__(self, dim=4):
        self.dimension = dim
        self.batch_calls = 0
        self.single_calls = 0
        self._fail_next = False

    async def embed_batch(self, texts):
        if self._fail_next:
            raise RuntimeError("embedding api down")
        self.batch_calls += 1
        return [[0.1 * (i + 1)] * self.dimension for i in range(len(texts))]

    async def embed(self, text):
        self.single_calls += 1
        return [0.1] * self.dimension


def _make_collection_info(dim=4):
    info = MagicMock()
    info.config.params.vectors.size = dim
    return info


def _make_get_collections(names):
    result = MagicMock()
    result.collections = [MagicMock(name=n) for n in names]
    # MagicMock's `name` is special — override with the real value
    for col, n in zip(result.collections, names):
        col.name = n
    return result


def _make_scroll_result(payload=None):
    """Mimic Qdrant's scroll() return shape: tuple (records, next_offset).
    If payload is None → empty records (collection was created but unpopulated).
    """
    if payload is None:
        return ([], None)
    rec = MagicMock()
    rec.payload = payload
    return ([rec], None)


def _make_qdrant_client(
    existing_collections=None,
    existing_sha=None,
    existing_dim=4,
    create_should_fail=False,
):
    """Build an AsyncMock Qdrant client with the given state."""
    existing_collections = existing_collections or []
    client = MagicMock()
    client.get_collections = AsyncMock(
        return_value=_make_get_collections(existing_collections)
    )
    client.get_collection = AsyncMock(return_value=_make_collection_info(existing_dim))
    client.scroll = AsyncMock(
        return_value=_make_scroll_result(
            payload={"yaml_sha": existing_sha} if existing_sha else None
        )
    )
    client.create_collection = AsyncMock()
    if create_should_fail:
        client.create_collection.side_effect = RuntimeError("qdrant connection refused")
    client.delete_collection = AsyncMock()
    client.upsert = AsyncMock()
    return client


# ── Tests ───────────────────────────────────────────────────────────────────────


async def test_first_index_creates_collection(tmp_path):
    """Test 1: collection missing → create + upsert."""
    _write_capability_yaml(tmp_path, "testbldg", _MINIMAL_CAPABILITY_YAML)
    client = _make_qdrant_client(existing_collections=[])
    indexer = CapabilityIndexer(client, _FakeEmbedder(), input_root=str(tmp_path))

    result = await indexer.index_building("testbldg")

    assert result.status == "indexed"
    assert result.entries == 2  # fire_safety + lift_details
    # 3 keywords + 1 content per entry = 4 points × 2 entries = 8 points
    assert result.points == 8
    client.create_collection.assert_awaited_once()
    client.upsert.assert_awaited()


async def test_unchanged_yaml_skips_reindex(tmp_path):
    """Test 2: SHA-256 match → status='skipped', 0 embedding calls.

    This is the core idempotency property. Restart with unchanged YAML must
    NOT re-embed.
    """
    yaml_path = _write_capability_yaml(tmp_path, "testbldg", _MINIMAL_CAPABILITY_YAML)
    existing_sha = hashlib.sha256(yaml_path.read_bytes()).hexdigest()

    client = _make_qdrant_client(
        existing_collections=["capability_testbldg"],
        existing_sha=existing_sha,
        existing_dim=4,
    )
    embedder = _FakeEmbedder()
    indexer = CapabilityIndexer(client, embedder, input_root=str(tmp_path))

    result = await indexer.index_building("testbldg")

    assert result.status == "skipped"
    assert result.entries == 2
    assert embedder.batch_calls == 0, "Skipped path must not call embedding API"
    client.create_collection.assert_not_awaited()
    client.upsert.assert_not_awaited()


async def test_changed_yaml_rebuilds_collection(tmp_path):
    """Test 3: SHA mismatch → delete + recreate + upsert."""
    _write_capability_yaml(tmp_path, "testbldg", _MINIMAL_CAPABILITY_YAML)

    client = _make_qdrant_client(
        existing_collections=["capability_testbldg"],
        existing_sha="OLD_DIFFERENT_SHA",
        existing_dim=4,
    )
    indexer = CapabilityIndexer(client, _FakeEmbedder(), input_root=str(tmp_path))

    result = await indexer.index_building("testbldg")

    assert result.status == "indexed"
    client.delete_collection.assert_awaited_once_with("capability_testbldg")
    client.create_collection.assert_awaited_once()


async def test_point_count_matches_keyword_sum(tmp_path):
    """Test 4: points = sum(len(keywords) for each entry) + 1 per entry (content)."""
    _write_capability_yaml(tmp_path, "testbldg", _MINIMAL_CAPABILITY_YAML)
    client = _make_qdrant_client()
    indexer = CapabilityIndexer(client, _FakeEmbedder(), input_root=str(tmp_path))

    result = await indexer.index_building("testbldg")

    # fire_safety: 3 keywords + 1 content = 4 points
    # lift_details: 3 keywords + 1 content = 4 points
    # total: 8
    assert result.points == 8


async def test_yaml_sha_recorded_in_payload(tmp_path):
    """Test 5: every upserted point's payload contains the parent YAML's SHA."""
    yaml_path = _write_capability_yaml(tmp_path, "testbldg", _MINIMAL_CAPABILITY_YAML)
    expected_sha = hashlib.sha256(yaml_path.read_bytes()).hexdigest()

    client = _make_qdrant_client()
    indexer = CapabilityIndexer(client, _FakeEmbedder(), input_root=str(tmp_path))

    await indexer.index_building("testbldg")

    # Inspect the upsert call
    upsert_calls = client.upsert.await_args_list
    assert len(upsert_calls) >= 1
    points = upsert_calls[0].kwargs["points"]
    for p in points:
        assert p.payload["yaml_sha"] == expected_sha


async def test_uuid_v5_deterministic(tmp_path):
    """Test 6: Reindexing same content → same point IDs (deterministic)."""
    _write_capability_yaml(tmp_path, "testbldg", _MINIMAL_CAPABILITY_YAML)

    client_1 = _make_qdrant_client()
    indexer_1 = CapabilityIndexer(client_1, _FakeEmbedder(), input_root=str(tmp_path))
    await indexer_1.index_building("testbldg")
    ids_1 = sorted(p.id for p in client_1.upsert.await_args_list[0].kwargs["points"])

    # Fresh client, fresh indexer, same YAML
    client_2 = _make_qdrant_client()
    indexer_2 = CapabilityIndexer(client_2, _FakeEmbedder(), input_root=str(tmp_path))
    await indexer_2.index_building("testbldg")
    ids_2 = sorted(p.id for p in client_2.upsert.await_args_list[0].kwargs["points"])

    assert ids_1 == ids_2, "UUID v5 must produce identical IDs for identical content"


async def test_missing_yaml_returns_degraded(tmp_path):
    """Test 7: capability.yaml not present → degraded, no crash."""
    # tmp_path has no building dirs
    client = _make_qdrant_client()
    indexer = CapabilityIndexer(client, _FakeEmbedder(), input_root=str(tmp_path))

    result = await indexer.index_building("nonexistent")

    assert result.status == "degraded"
    assert "not found" in result.reason.lower()


async def test_malformed_yaml_returns_degraded(tmp_path):
    """Test 8: invalid YAML → degraded; orchestrator still boots."""
    _write_capability_yaml(tmp_path, "testbldg", "this: is: not: valid: yaml:: %%%")

    client = _make_qdrant_client()
    indexer = CapabilityIndexer(client, _FakeEmbedder(), input_root=str(tmp_path))

    result = await indexer.index_building("testbldg")
    assert result.status == "degraded"
    assert "yaml" in result.reason.lower() or "load" in result.reason.lower()


async def test_qdrant_unreachable_returns_degraded(tmp_path):
    """Test 9: Qdrant errors during probe → degraded; no exception escapes."""
    _write_capability_yaml(tmp_path, "testbldg", _MINIMAL_CAPABILITY_YAML)

    client = MagicMock()
    client.get_collections = AsyncMock(side_effect=RuntimeError("connection refused"))

    indexer = CapabilityIndexer(client, _FakeEmbedder(), input_root=str(tmp_path))
    result = await indexer.index_building("testbldg")

    assert result.status == "degraded"
    assert "qdrant" in result.reason.lower() or "probe" in result.reason.lower()


async def test_embedding_api_down_returns_degraded(tmp_path):
    """Test 10: EmbeddingService raises → degraded; no exception escapes."""
    _write_capability_yaml(tmp_path, "testbldg", _MINIMAL_CAPABILITY_YAML)
    client = _make_qdrant_client()
    embedder = _FakeEmbedder()
    embedder._fail_next = True

    indexer = CapabilityIndexer(client, embedder, input_root=str(tmp_path))
    result = await indexer.index_building("testbldg")

    assert result.status == "degraded"
    assert "embedding" in result.reason.lower()


async def test_dim_mismatch_rebuilds(tmp_path):
    """Test 11: existing collection has dim=1536 but embedder.dimension=4 → rebuild."""
    _write_capability_yaml(tmp_path, "testbldg", _MINIMAL_CAPABILITY_YAML)

    client = _make_qdrant_client(
        existing_collections=["capability_testbldg"],
        existing_sha="some_sha",
        existing_dim=1536,  # mismatch with embedder's dim=4
    )
    indexer = CapabilityIndexer(client, _FakeEmbedder(dim=4), input_root=str(tmp_path))

    result = await indexer.index_building("testbldg")

    assert result.status == "indexed"
    client.delete_collection.assert_awaited_once()
    client.create_collection.assert_awaited_once()


async def test_multiple_buildings_isolated(tmp_path):
    """Test 12: bldg1 and bldg2 get separate collections; no cross-contamination."""
    _write_capability_yaml(tmp_path, "bldg1", _MINIMAL_CAPABILITY_YAML)
    bldg2_yaml = _MINIMAL_CAPABILITY_YAML.replace(
        "id: testbldg", "id: bldg2"
    ).replace("name: Test Building", "name: Building 2")
    _write_capability_yaml(tmp_path, "bldg2", bldg2_yaml)

    client = _make_qdrant_client()
    indexer = CapabilityIndexer(client, _FakeEmbedder(), input_root=str(tmp_path))

    results = await indexer.index_all_buildings()

    assert set(results.keys()) == {"bldg1", "bldg2"}
    assert results["bldg1"].status == "indexed"
    assert results["bldg2"].status == "indexed"

    # Distinct collections created
    create_calls = [c.kwargs["collection_name"] for c in client.create_collection.await_args_list]
    assert "capability_bldg1" in create_calls
    assert "capability_bldg2" in create_calls


async def test_batch_upsert_used_for_efficiency(tmp_path):
    """Test 13: indexer calls embed_batch (one call), not embed (N calls)."""
    _write_capability_yaml(tmp_path, "testbldg", _MINIMAL_CAPABILITY_YAML)
    client = _make_qdrant_client()
    embedder = _FakeEmbedder()
    indexer = CapabilityIndexer(client, embedder, input_root=str(tmp_path))

    await indexer.index_building("testbldg")

    # Should use embed_batch exactly once (collects ALL texts then embeds once)
    assert embedder.batch_calls == 1, (
        f"Expected exactly 1 batch call, got {embedder.batch_calls}. "
        "Indexer must batch embeddings, not call embed() per keyword."
    )
    assert embedder.single_calls == 0


async def test_disabled_config_skipped(tmp_path):
    """Test 14: capability_routing.enabled=false → status='disabled', no Qdrant writes."""
    _write_capability_yaml(tmp_path, "testbldg", _MINIMAL_CAPABILITY_YAML)
    _write_building_yaml(
        tmp_path,
        "testbldg",
        routing_block="capability_routing:\n  enabled: false\n",
    )

    client = _make_qdrant_client()
    indexer = CapabilityIndexer(client, _FakeEmbedder(), input_root=str(tmp_path))

    result = await indexer.index_building("testbldg")

    assert result.status == "disabled"
    client.create_collection.assert_not_awaited()
    client.upsert.assert_not_awaited()
