"""
Unit + integration tests for /api/v1/admin/capability-indexer/status.

The endpoint surfaces the IndexResult stored on app.state by the FastAPI lifespan.
Closes the gap for 4 tests previously skipped with "Verified via docker logs only".

Three tests:
  1. Status endpoint returns 200 and the documented schema (integration)
  2. yaml_sha is a 64-char hex string when status != 'degraded' (idempotency proof)
  3. router_intents includes 'capability' (proves SemanticRouter binding wired)

These tests REQUIRE the orchestrator to be running with semantic routing enabled
(post-Phase-3 state). They auto-skip if /health is unreachable.
"""

from __future__ import annotations

import pytest
import requests

pytestmark = pytest.mark.live


def test_status_endpoint_returns_documented_schema(chat_client):
    """Endpoint returns 200 with the schema documented in main.py."""
    r = requests.get(f"{chat_client.base}/api/v1/admin/capability-indexer/status", timeout=10)
    assert r.status_code == 200
    body = r.json()
    assert body.get("success") is True
    data = body.get("data") or {}

    # Top-level required fields
    for field in (
        "indexer_ready",
        "router_ready",
        "router_intents",
        "embedding_provider",
        "embedding_dimension",
        "buildings",
    ):
        assert field in data, f"Missing field '{field}' in response: {data!r}"

    # Types
    assert isinstance(data["indexer_ready"], bool)
    assert isinstance(data["router_ready"], bool)
    assert isinstance(data["router_intents"], list)
    assert isinstance(data["buildings"], dict)


def test_status_yaml_sha_is_valid_when_indexed(chat_client):
    """For any building reporting status='indexed' or 'skipped', yaml_sha must
    be a 64-char hex sha256 — that's the idempotency fingerprint."""
    r = requests.get(f"{chat_client.base}/api/v1/admin/capability-indexer/status", timeout=10)
    body = r.json()["data"]
    buildings = body.get("buildings", {})

    if not buildings:
        pytest.skip("No buildings indexed; nothing to verify")

    for bldg_id, info in buildings.items():
        if info["status"] in ("indexed", "skipped"):
            sha = info.get("yaml_sha", "")
            assert len(sha) == 64, (
                f"{bldg_id}: expected 64-char hex sha, got len={len(sha)}: {sha!r}"
            )
            # Hex-only
            assert all(c in "0123456789abcdef" for c in sha.lower()), (
                f"{bldg_id}: yaml_sha is not hex: {sha!r}"
            )


def test_status_router_intents_includes_capability(chat_client):
    """The semantic router must have 'capability' registered.
    If this fails, capability semantic routing won't fire at query time."""
    r = requests.get(f"{chat_client.base}/api/v1/admin/capability-indexer/status", timeout=10)
    data = r.json()["data"]
    assert data["router_ready"] is True
    assert "capability" in data["router_intents"], (
        f"Expected 'capability' in router_intents, got: {data['router_intents']!r}"
    )
