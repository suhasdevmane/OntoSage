"""
tests/test_admin_ontology_endpoints.py — Unit tests for the 8 admin ontology + re-index endpoints.

All tests use @pytest.mark.unit — no live services required.
Authentication is bypassed via app.dependency_overrides[get_user_context], which is the
dependency that require_permission() chains through in the security branch.
Service functions are mocked with unittest.mock.patch so no GraphDB or Qdrant is needed.

Note: starlette.testclient.TestClient is incompatible with httpx>=0.23 in this env
(TestClient passes `app=` kwarg that httpx.Client dropped).  We use the same pattern
the rest of this codebase adopts: httpx.AsyncClient + ASGITransport.
`asyncio_mode = auto` in pytest.ini means `async def` tests run automatically.
"""

from __future__ import annotations

from unittest.mock import AsyncMock, patch

import pytest

import orchestrator.main as _main_module

pytestmark = pytest.mark.unit


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture(autouse=True)
def reset_reindex_service():
    """Reset the _reindex_service module-level singleton before and after each test."""
    _main_module._reindex_service_instance = None
    yield
    _main_module._reindex_service_instance = None


def _admin_user_context():
    """Return a UserContext with admin role and all permissions."""
    from orchestrator.middleware.rbac import ROLE_PERMISSIONS, UserContext

    return UserContext(
        user_id="testadmin",
        username="testadmin",
        role="admin",
        tenant_id="default",
        allowed_buildings=[],
        permissions=ROLE_PERMISSIONS.get("admin", set()),
    )


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _setup_auth(app, get_user_context):
    """Install auth override — returns a full admin UserContext."""
    ctx = _admin_user_context()
    app.dependency_overrides[get_user_context] = lambda: ctx


def _teardown_auth(app, get_user_context):
    """Remove auth override."""
    app.dependency_overrides.pop(get_user_context, None)


async def _get(url, *, auth=True):
    """Make a GET request via ASGITransport."""
    from httpx import ASGITransport, AsyncClient

    from orchestrator.main import app, get_user_context

    if auth:
        _setup_auth(app, get_user_context)
    try:
        transport = ASGITransport(app=app)
        async with AsyncClient(transport=transport, base_url="http://test") as client:
            resp = await client.get(url)
    finally:
        if auth:
            _teardown_auth(app, get_user_context)
    return resp


async def _post(url, body, *, auth=True):
    """Make a POST request via ASGITransport."""
    from httpx import ASGITransport, AsyncClient

    from orchestrator.main import app, get_user_context

    if auth:
        _setup_auth(app, get_user_context)
    try:
        transport = ASGITransport(app=app)
        async with AsyncClient(transport=transport, base_url="http://test") as client:
            resp = await client.post(url, json=body)
    finally:
        if auth:
            _teardown_auth(app, get_user_context)
    return resp


async def _delete(url, *, auth=True):
    """Make a DELETE request via ASGITransport."""
    from httpx import ASGITransport, AsyncClient

    from orchestrator.main import app, get_user_context

    if auth:
        _setup_auth(app, get_user_context)
    try:
        transport = ASGITransport(app=app)
        async with AsyncClient(transport=transport, base_url="http://test") as client:
            resp = await client.delete(url)
    finally:
        if auth:
            _teardown_auth(app, get_user_context)
    return resp


# ---------------------------------------------------------------------------
# 1. List named graphs — authenticated, mock list_named_graphs
# ---------------------------------------------------------------------------


async def test_ontology_graphs_endpoint_exists():
    """GET /api/v1/admin/ontology/graphs returns graphs data with auth."""
    with patch(
        "orchestrator.services.ontology_manager.list_named_graphs",
        new=AsyncMock(return_value={"urn:x": 10}),
    ):
        resp = await _get("/api/v1/admin/ontology/graphs")

    assert resp.status_code == 200
    body = resp.json()
    assert body["success"] is True
    assert "urn:x" in body["data"]["graphs"]


# ---------------------------------------------------------------------------
# 2. Validate TTL — valid input, calls real validate_ttl_text (rdflib)
# ---------------------------------------------------------------------------


async def test_validate_ttl_valid():
    """POST /api/v1/admin/ontology/validate with valid Turtle returns success=True."""
    ttl = (
        "@prefix brick: <https://brickschema.org/schema/Brick#> .\n"
        "<urn:example:sensor1> a brick:Sensor ."
    )
    resp = await _post("/api/v1/admin/ontology/validate", {"ttl": ttl})

    assert resp.status_code == 200
    body = resp.json()
    assert body["success"] is True
    assert body["data"]["triple_count"] >= 1


# ---------------------------------------------------------------------------
# 3. Validate TTL — invalid input
# ---------------------------------------------------------------------------


async def test_validate_ttl_invalid():
    """POST /api/v1/admin/ontology/validate with garbage Turtle returns success=False."""
    resp = await _post(
        "/api/v1/admin/ontology/validate",
        {"ttl": "not turtle !!!"},
    )

    assert resp.status_code == 200
    body = resp.json()
    assert body["success"] is False


# ---------------------------------------------------------------------------
# 4. Upload TTL — mock upload_ttl
# ---------------------------------------------------------------------------


async def test_upload_ttl_custom_graph_graphdb_only():
    """Upload to a NON-file graph writes GraphDB only (persisted=False)."""
    mock_result = {
        "ok": True,
        "triple_count": 3,
        "graph": "urn:ontosage:custom:test",
        "error": None,
    }
    with patch(
        "orchestrator.services.ontology_manager.upload_ttl",
        new=AsyncMock(return_value=mock_result),
    ):
        resp = await _post(
            "/api/v1/admin/ontology/upload",
            {
                "ttl": "@prefix ex: <http://example.org/> . ex:a ex:b ex:c .",
                "graph_uri": "urn:ontosage:custom:test",
            },
        )

    assert resp.status_code == 200
    body = resp.json()
    assert body["success"] is True
    assert body["data"]["persisted"] is False


async def test_upload_ttl_file_graph_persists_to_input():
    """Upload to a file graph (urn:ontosage:ttl:<file>) persists to input/ (persisted=True)."""
    persisted = {"ok": True, "file": "/app/input/test.ttl", "graph": "urn:ontosage:ttl:test.ttl"}
    with patch(
        "orchestrator.services.input_ttl_store.persist_ttl_file",
        new=AsyncMock(return_value=persisted),
    ):
        resp = await _post(
            "/api/v1/admin/ontology/upload",
            {
                "ttl": "@prefix ex: <http://example.org/> . ex:a ex:b ex:c .",
                "graph_uri": "urn:ontosage:ttl:test.ttl",
            },
        )

    assert resp.status_code == 200
    body = resp.json()
    assert body["success"] is True
    assert body["data"]["persisted"] is True
    assert body["data"]["file"].endswith("test.ttl")


# ---------------------------------------------------------------------------
# 5. Drop named graph — mock drop_named_graph
# ---------------------------------------------------------------------------


async def test_drop_graph_endpoint():
    """DELETE /api/v1/admin/ontology/graphs/{id} returns dropped=True."""
    with patch(
        "orchestrator.services.ontology_manager.drop_named_graph",
        new=AsyncMock(return_value=True),
    ):
        resp = await _delete("/api/v1/admin/ontology/graphs/urn:ontosage:ttl:test.ttl")

    assert resp.status_code == 200
    body = resp.json()
    assert body["data"]["dropped"] is True


# ---------------------------------------------------------------------------
# 6. SPARQL browser — mock run_sparql_select
# ---------------------------------------------------------------------------


async def test_sparql_endpoint():
    """POST /api/v1/admin/ontology/sparql returns rows when mock returns ok."""
    mock_result = {
        "ok": True,
        "columns": ["s"],
        "rows": [{"s": "x"}],
        "count": 1,
        "error": None,
    }
    with patch(
        "orchestrator.services.ontology_manager.run_sparql_select",
        new=AsyncMock(return_value=mock_result),
    ):
        resp = await _post(
            "/api/v1/admin/ontology/sparql",
            {"query": "SELECT ?s WHERE {?s ?p ?o}", "limit": 10},
        )

    assert resp.status_code == 200
    body = resp.json()
    assert body["data"]["count"] == 1


# ---------------------------------------------------------------------------
# 7. Trigger reindex — POST returns job_id
# ---------------------------------------------------------------------------


async def test_reindex_trigger():
    """POST /api/v1/admin/reindex returns a job_id in data."""
    resp = await _post("/api/v1/admin/reindex", {"targets": ["capability"]})

    assert resp.status_code == 200
    body = resp.json()
    assert body["success"] is True
    assert "job_id" in body["data"]


# ---------------------------------------------------------------------------
# 8. List reindex jobs — GET returns jobs key
# ---------------------------------------------------------------------------


async def test_reindex_list_jobs():
    """GET /api/v1/admin/reindex returns a jobs key (may be empty list)."""
    resp = await _get("/api/v1/admin/reindex")

    assert resp.status_code == 200
    body = resp.json()
    assert "jobs" in body["data"]


# ---------------------------------------------------------------------------
# 9. Unauthenticated request returns error
# ---------------------------------------------------------------------------


async def test_unauthenticated_returns_error():
    """GET /api/v1/admin/ontology/graphs with no token returns 401."""
    resp = await _get("/api/v1/admin/ontology/graphs", auth=False)
    assert resp.status_code == 401


# ---------------------------------------------------------------------------
# 10. Invalid reindex target
# ---------------------------------------------------------------------------


async def test_reindex_invalid_target():
    """POST /api/v1/admin/reindex with nonsense target returns success=False."""
    resp = await _post("/api/v1/admin/reindex", {"targets": ["nonsense"]})

    assert resp.status_code == 200
    body = resp.json()
    assert body["success"] is False


# ---------------------------------------------------------------------------
# 11. Reindex job status — job exists (found=True)
# ---------------------------------------------------------------------------


async def test_reindex_job_status_found():
    """GET /api/v1/admin/reindex/{job_id} returns found=True for a real job."""
    start = await _post("/api/v1/admin/reindex", {"targets": ["capability"]})
    assert start.status_code == 200
    job_id = start.json()["data"]["job_id"]

    resp = await _get(f"/api/v1/admin/reindex/{job_id}")
    assert resp.status_code == 200
    body = resp.json()
    assert body["success"] is True
    assert body["data"].get("id") == job_id


# ---------------------------------------------------------------------------
# 12. Reindex job status — job does not exist (found=False)
# ---------------------------------------------------------------------------


async def test_reindex_job_status_not_found():
    """GET /api/v1/admin/reindex/{job_id} with unknown ID returns success=False."""
    resp = await _get("/api/v1/admin/reindex/does-not-exist-xyz")
    assert resp.status_code == 200
    body = resp.json()
    assert body["success"] is False


# ---------------------------------------------------------------------------
# 13. Validate TTL — empty string returns success=False (not a valid graph)
# ---------------------------------------------------------------------------


async def test_validate_ttl_empty():
    """POST /api/v1/admin/ontology/validate with empty string is rejected."""
    resp = await _post("/api/v1/admin/ontology/validate", {"ttl": ""})
    # 422: Pydantic min_length rejects before handler; 200+success=False: handler rejects
    assert resp.status_code in (200, 422)
    if resp.status_code == 200:
        assert resp.json()["success"] is False
