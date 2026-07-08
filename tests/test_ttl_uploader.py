"""Phase 3 — idempotent TTL auto-upload tests.

Covers:
  1. SHA cache load/save (atomic-ish, survives missing files).
  2. TTL discovery (per-building + legacy flat layouts).
  3. Schema vs per-building separation.
  4. Idempotency: unchanged TTLs skipped without network call.
  5. Failed uploads logged but non-fatal.
  6. GraphDB PUT-to-named-graph contract (URL, context param, content-type).
  7. Named-graph URI determinism (_graph_uri_for_path).
"""

from __future__ import annotations

import json
from pathlib import Path
from unittest.mock import AsyncMock, patch

import httpx
import pytest

from orchestrator.services import ttl_uploader as uploader

# ─────────────────────────────────────────────────────────────────────────────
# SHA / cache helpers
# ─────────────────────────────────────────────────────────────────────────────


def test_compute_sha_deterministic(tmp_path):
    p = tmp_path / "x.ttl"
    p.write_bytes(b"@prefix : <http://x#> . :a :b :c .")
    sha1 = uploader.compute_sha(p)
    sha2 = uploader.compute_sha(p)
    assert sha1 == sha2
    assert len(sha1) == 64  # SHA-256 hex


def test_compute_sha_changes_when_content_changes(tmp_path):
    p = tmp_path / "x.ttl"
    p.write_bytes(b"first")
    a = uploader.compute_sha(p)
    p.write_bytes(b"second")
    b = uploader.compute_sha(p)
    assert a != b


def test_load_cache_missing_file(tmp_path):
    """A missing cache file returns {} and does NOT raise."""
    with patch.object(uploader, "_CACHE_SEARCH_PATHS", [tmp_path / "missing.json"]):
        cache = uploader.load_cache()
    assert cache == {}


def test_save_then_load_cache_roundtrip(tmp_path):
    cache_path = tmp_path / "cache.json"
    with patch.object(uploader, "_CACHE_SEARCH_PATHS", [cache_path]):
        uploader.save_cache({"foo.ttl": "abc123", "bar.ttl": "def456"})
        loaded = uploader.load_cache()
    assert loaded == {"foo.ttl": "abc123", "bar.ttl": "def456"}


def test_load_cache_handles_corrupted_file(tmp_path):
    """A non-JSON or non-dict cache returns {} and does NOT raise."""
    bad = tmp_path / "bad.json"
    bad.write_text("this is not json {{{")
    with patch.object(uploader, "_CACHE_SEARCH_PATHS", [bad]):
        cache = uploader.load_cache()
    assert cache == {}


# ─────────────────────────────────────────────────────────────────────────────
# TTL discovery
# ─────────────────────────────────────────────────────────────────────────────


def _write_ttl(path: Path, body: str = "@prefix : <http://x#> .\n:a :b :c .\n") -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(body)


def test_discover_ttls_new_layout(tmp_path):
    """TTLs under input/<bldg>/ are discovered."""
    _write_ttl(tmp_path / "bldgX" / "metadata.ttl")
    _write_ttl(tmp_path / "bldgX" / "instances.ttl")
    with patch.object(uploader, "_INPUT_SEARCH_PATHS", [tmp_path]):
        ttls = uploader.discover_ttls("bldgX")
    names = sorted(p.name for p in ttls)
    assert names == ["instances.ttl", "metadata.ttl"]


def test_discover_ttls_legacy_flat_layout(tmp_path):
    """TTLs at input/<bldg>_*.ttl are discovered (legacy)."""
    _write_ttl(tmp_path / "bldg1_abacws_metadata.ttl")
    _write_ttl(tmp_path / "bldg1_enhancements.ttl")
    _write_ttl(tmp_path / "Brick_v1.4.ttl")  # schema — should NOT match per-bldg
    with patch.object(uploader, "_INPUT_SEARCH_PATHS", [tmp_path]):
        ttls = uploader.discover_ttls("bldg1")
    names = sorted(p.name for p in ttls)
    assert "bldg1_abacws_metadata.ttl" in names
    assert "bldg1_enhancements.ttl" in names
    assert "Brick_v1.4.ttl" not in names  # schema is separate


def test_discover_schema_ttls_at_top_level(tmp_path):
    """Schema files (Brick*, *_schema*) are discovered separately."""
    _write_ttl(tmp_path / "Brick_v1.4.ttl")
    _write_ttl(tmp_path / "Brick+extensions.ttl")
    _write_ttl(tmp_path / "rec_schema.ttl")
    _write_ttl(tmp_path / "bldg1_abacws_metadata.ttl")
    with patch.object(uploader, "_INPUT_SEARCH_PATHS", [tmp_path]):
        ttls = uploader.discover_schema_ttls()
    names = sorted(p.name for p in ttls)
    assert "Brick_v1.4.ttl" in names
    assert "Brick+extensions.ttl" in names
    assert "rec_schema.ttl" in names
    assert "bldg1_abacws_metadata.ttl" not in names


def test_discover_no_input_dir():
    """When no input/ exists, discovery returns []."""
    with (
        patch.object(uploader, "_INPUT_SEARCH_PATHS", [Path("/nonexistent")]),
        patch.object(uploader, "_ONTOLOGY_SEARCH_PATHS", [Path("/nonexistent")]),
    ):
        assert uploader.discover_ttls("bldg1") == []
        assert uploader.discover_schema_ttls() == []


# ─────────────────────────────────────────────────────────────────────────────
# upload_to_graphdb
# ─────────────────────────────────────────────────────────────────────────────


def test_graph_uri_for_path_deterministic(tmp_path):
    """Same file always produces the same named-graph URI."""
    p = tmp_path / "bldg1_metadata.ttl"
    uri1 = uploader._graph_uri_for_path(p)
    uri2 = uploader._graph_uri_for_path(p)
    assert uri1 == uri2
    assert uri1.startswith("urn:ontosage:ttl:")
    assert "bldg1_metadata.ttl" in uri1


def test_graph_uri_for_path_different_files(tmp_path):
    """Different files produce different named-graph URIs."""
    p1 = tmp_path / "file_a.ttl"
    p2 = tmp_path / "file_b.ttl"
    assert uploader._graph_uri_for_path(p1) != uploader._graph_uri_for_path(p2)


@pytest.mark.asyncio
async def test_upload_to_graphdb_uses_put_with_named_graph(tmp_path):
    """Upload uses PUT to a per-file named graph (prevents blank-node duplication)."""
    ttl = tmp_path / "x.ttl"
    ttl.write_text("@prefix : <http://x#> . :a :b :c .")
    mock_client = AsyncMock()
    mock_client.put = AsyncMock(
        return_value=httpx.Response(status_code=204, request=httpx.Request("PUT", "http://x"))
    )
    ok = await uploader.upload_to_graphdb(
        ttl, repository="testrepo", graphdb_url="http://gdb:7200", client=mock_client
    )
    assert ok is True
    assert mock_client.put.await_count == 1
    # URL must contain the statements endpoint + context query param
    url_called = mock_client.put.await_args.args[0]
    assert "/repositories/testrepo/statements" in url_called
    assert "context=" in url_called
    assert mock_client.put.await_args.kwargs["headers"]["Content-Type"] == "application/x-turtle"


@pytest.mark.asyncio
async def test_upload_to_graphdb_4xx_returns_false(tmp_path):
    """A 4xx response logs a warning and returns False."""
    ttl = tmp_path / "x.ttl"
    ttl.write_text("@prefix : <http://x#> . :a :b :c .")
    mock_client = AsyncMock()
    mock_client.put = AsyncMock(
        return_value=httpx.Response(
            status_code=400,
            text="bad turtle",
            request=httpx.Request("PUT", "http://x"),
        )
    )
    ok = await uploader.upload_to_graphdb(ttl, client=mock_client)
    assert ok is False


@pytest.mark.asyncio
async def test_upload_to_graphdb_network_error_returns_false(tmp_path):
    """Network exceptions return False (non-fatal)."""
    ttl = tmp_path / "x.ttl"
    ttl.write_text("@prefix : <http://x#> . :a :b :c .")
    mock_client = AsyncMock()
    mock_client.put = AsyncMock(side_effect=httpx.ConnectError("refused"))
    ok = await uploader.upload_to_graphdb(ttl, client=mock_client)
    assert ok is False


# ─────────────────────────────────────────────────────────────────────────────
# run_idempotent_uploads
# ─────────────────────────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_idempotent_skip_when_sha_matches(tmp_path):
    """A TTL whose SHA matches the cache is SKIPPED (no network call)."""
    _write_ttl(tmp_path / "bldg1" / "x.ttl", body="static-content")
    ttl_path = tmp_path / "bldg1" / "x.ttl"
    sha = uploader.compute_sha(ttl_path)

    upload_mock = AsyncMock(return_value=True)
    with (
        patch.object(uploader, "_INPUT_SEARCH_PATHS", [tmp_path]),
        patch.object(uploader, "upload_to_graphdb", upload_mock),
    ):
        summary = await uploader.run_idempotent_uploads(
            ["bldg1"],
            include_schemas=False,
            cache={str(ttl_path): sha},
        )
    assert summary["skipped"] == [str(ttl_path)]
    assert summary["uploaded"] == []
    upload_mock.assert_not_awaited()


@pytest.mark.asyncio
async def test_idempotent_uploads_when_sha_differs(tmp_path):
    """A TTL with new SHA is UPLOADED and cached."""
    _write_ttl(tmp_path / "bldg1" / "x.ttl", body="new-content")
    ttl_path = tmp_path / "bldg1" / "x.ttl"

    upload_mock = AsyncMock(return_value=True)
    cache: dict = {str(ttl_path): "stale-sha-value"}
    with (
        patch.object(uploader, "_INPUT_SEARCH_PATHS", [tmp_path]),
        patch.object(uploader, "upload_to_graphdb", upload_mock),
    ):
        summary = await uploader.run_idempotent_uploads(
            ["bldg1"], include_schemas=False, cache=cache
        )
    assert str(ttl_path) in summary["uploaded"]
    upload_mock.assert_awaited_once()
    # Cache was updated to the new SHA
    assert cache[str(ttl_path)] == uploader.compute_sha(ttl_path)


@pytest.mark.asyncio
async def test_failed_upload_recorded_and_non_fatal(tmp_path):
    """When GraphDB returns failure, the path goes into 'failed' and cache is unchanged."""
    _write_ttl(tmp_path / "bldg1" / "x.ttl")
    ttl_path = tmp_path / "bldg1" / "x.ttl"
    cache: dict = {}

    upload_mock = AsyncMock(return_value=False)
    with (
        patch.object(uploader, "_INPUT_SEARCH_PATHS", [tmp_path]),
        patch.object(uploader, "upload_to_graphdb", upload_mock),
    ):
        summary = await uploader.run_idempotent_uploads(
            ["bldg1"], include_schemas=False, cache=cache
        )
    assert summary["failed"] == [str(ttl_path)]
    assert summary["uploaded"] == []
    # SHA NOT cached on failure (so next boot retries)
    assert cache == {}


@pytest.mark.asyncio
async def test_empty_input_dir_returns_empty_summary(tmp_path):
    upload_mock = AsyncMock(return_value=True)
    with (
        patch.object(uploader, "_INPUT_SEARCH_PATHS", [tmp_path]),
        patch.object(uploader, "_ONTOLOGY_SEARCH_PATHS", [tmp_path / "no_ontology"]),
        patch.object(uploader, "upload_to_graphdb", upload_mock),
    ):
        summary = await uploader.run_idempotent_uploads(["bldg1"])
    assert summary == {"uploaded": [], "skipped": [], "failed": []}
    upload_mock.assert_not_awaited()


@pytest.mark.asyncio
async def test_schemas_included_when_flag_set(tmp_path):
    """Schema TTLs at top of input/ are processed when include_schemas=True."""
    _write_ttl(tmp_path / "Brick_v1.4.ttl")
    _write_ttl(tmp_path / "bldg1_abacws_metadata.ttl")
    upload_mock = AsyncMock(return_value=True)
    cache: dict = {}
    with (
        patch.object(uploader, "_INPUT_SEARCH_PATHS", [tmp_path]),
        patch.object(uploader, "_ONTOLOGY_SEARCH_PATHS", [tmp_path / "no_ontology"]),
        patch.object(uploader, "upload_to_graphdb", upload_mock),
    ):
        summary = await uploader.run_idempotent_uploads(
            ["bldg1"], include_schemas=True, cache=cache
        )
    # Both schema (Brick) and per-bldg (bldg1_abacws_metadata) were uploaded
    assert len(summary["uploaded"]) == 2
    paths_uploaded = [Path(p).name for p in summary["uploaded"]]
    assert "Brick_v1.4.ttl" in paths_uploaded
    assert "bldg1_abacws_metadata.ttl" in paths_uploaded
