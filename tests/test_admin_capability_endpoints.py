"""
tests/test_admin_capability_endpoints.py — Unit tests for the guided capability CRUD
endpoints (TODO-014) and the Turtle builder they rely on.

Same pattern as test_admin_ontology_endpoints.py: auth bypassed via
app.dependency_overrides[get_user_context]; the service layer is mocked so no GraphDB is
touched. The pure Turtle builder is validated directly with rdflib (no network).
"""

from __future__ import annotations

from unittest.mock import AsyncMock, patch

import pytest

pytestmark = pytest.mark.unit


# ---------------------------------------------------------------------------
# Pure builder — build_amenity_ttl (no network)
# ---------------------------------------------------------------------------


def test_build_amenity_ttl_valid_is_parseable_and_dual_typed():
    from orchestrator.services.capability_admin import build_amenity_ttl
    from orchestrator.services.ontology_manager import validate_ttl_text

    built = build_amenity_ttl(
        "bldg1",
        local="PrayerRoom_104",
        cls="PrayerRoom",
        label="Prayer & Reflection Room",
        location="Room 1.04, first floor",
        floor="1",
        category="wellbeing",
        lay_terms="pray, prayer, quiet room, reflection",
        note="Open 24/7 to staff and students.",
    )
    assert built["ok"] is True
    assert built["subject"].endswith("PrayerRoom_104")
    # Dual-typed: the specific class AND ontosage:Amenity
    assert "ontosage:PrayerRoom" in built["ttl"]
    assert "ontosage:Amenity" in built["ttl"]
    # And it must actually parse as Turtle.
    v = validate_ttl_text(built["ttl"])
    assert v["ok"] is True
    assert v["triple_count"] >= 3


def test_build_amenity_ttl_rejects_unknown_type():
    from orchestrator.services.capability_admin import build_amenity_ttl

    built = build_amenity_ttl("bldg1", local="X", cls="Teleporter", label="X")
    assert built["ok"] is False
    assert "unknown capability type" in built["error"]


def test_build_amenity_ttl_rejects_bad_local_name():
    from orchestrator.services.capability_admin import build_amenity_ttl

    built = build_amenity_ttl("bldg1", local="bad name!", cls="Cafe", label="Cafe")
    assert built["ok"] is False
    assert "local name" in built["error"]


def test_build_amenity_ttl_requires_label():
    from orchestrator.services.capability_admin import build_amenity_ttl

    built = build_amenity_ttl("bldg1", local="Cafe1", cls="Cafe", label="   ")
    assert built["ok"] is False
    assert "label" in built["error"]


def test_build_amenity_ttl_escapes_quotes():
    """A label with a double-quote must not break the Turtle literal."""
    from orchestrator.services.capability_admin import build_amenity_ttl
    from orchestrator.services.ontology_manager import validate_ttl_text

    built = build_amenity_ttl("bldg1", local="Cafe1", cls="Cafe", label='The "Best" Cafe')
    assert built["ok"] is True
    assert validate_ttl_text(built["ttl"])["ok"] is True


def test_build_amenity_ttl_omits_blank_optional_fields():
    from orchestrator.services.capability_admin import build_amenity_ttl

    built = build_amenity_ttl("bldg1", local="Lift1", cls="Lift", label="Main Lift")
    assert built["ok"] is True
    assert "locationText" not in built["ttl"]
    assert "onFloor" not in built["ttl"]


# ---------------------------------------------------------------------------
# HTTP helpers (mirror test_admin_ontology_endpoints.py)
# ---------------------------------------------------------------------------


def _admin_user_context():
    from orchestrator.middleware.rbac import ROLE_PERMISSIONS, UserContext

    return UserContext(
        user_id="testadmin",
        username="testadmin",
        role="admin",
        tenant_id="default",
        allowed_buildings=[],
        permissions=ROLE_PERMISSIONS.get("admin", set()),
    )


async def _request(method, url, *, body=None, auth=True):
    from httpx import ASGITransport, AsyncClient

    from orchestrator.main import app, get_user_context

    if auth:
        app.dependency_overrides[get_user_context] = lambda: _admin_user_context()
    try:
        transport = ASGITransport(app=app)
        async with AsyncClient(transport=transport, base_url="http://test") as client:
            resp = await client.request(method, url, json=body)
    finally:
        if auth:
            app.dependency_overrides.pop(get_user_context, None)
    return resp


# ---------------------------------------------------------------------------
# GET /api/v1/admin/capabilities — list
# ---------------------------------------------------------------------------


async def test_list_capabilities():
    rows = [{"a": "http://x#PrayerRoom_104", "label": "Prayer Room"}]
    with patch(
        "orchestrator.services.capability_admin.list_amenities",
        new=AsyncMock(return_value=rows),
    ):
        resp = await _request("GET", "/api/v1/admin/capabilities")
    assert resp.status_code == 200
    body = resp.json()
    assert body["success"] is True
    assert body["data"]["total"] == 1
    assert "PrayerRoom" in body["data"]["types"]


# ---------------------------------------------------------------------------
# POST /api/v1/admin/capabilities — create (happy path, upload mocked)
# ---------------------------------------------------------------------------


async def test_create_capability_happy_path():
    # Mock the file-as-truth writeback so no file/GraphDB is touched; build_amenity_ttl
    # still runs (validates + produces the Turtle surfaced in the response).
    up = {"ok": True, "subject": "x", "file": "/app/input/bldg1_capabilities.ttl", "error": None}
    with patch(
        "orchestrator.services.input_ttl_store.upsert_amenity",
        new=AsyncMock(return_value=up),
    ):
        resp = await _request(
            "POST",
            "/api/v1/admin/capabilities",
            body={
                "id": "Cafe_Ground",
                "type": "Cafe",
                "label": "Ground Floor Cafe",
                "lay_terms": "coffee, cafe, food",
            },
        )
    assert resp.status_code == 200
    body = resp.json()
    assert body["success"] is True
    assert body["data"]["subject"].endswith("Cafe_Ground")
    assert "ontosage:Cafe" in body["data"]["ttl"]
    assert body["data"]["file"].endswith("bldg1_capabilities.ttl")


# ---------------------------------------------------------------------------
# POST — invalid amenity type flows to success=False (real helper, no network)
# ---------------------------------------------------------------------------


async def test_create_capability_bad_type_rejected():
    resp = await _request(
        "POST",
        "/api/v1/admin/capabilities",
        body={"id": "X1", "type": "Teleporter", "label": "X"},
    )
    assert resp.status_code == 200
    body = resp.json()
    assert body["success"] is False
    assert "unknown capability type" in body["error"]


# ---------------------------------------------------------------------------
# DELETE /api/v1/admin/capabilities/{local_name}
# ---------------------------------------------------------------------------


async def test_delete_capability():
    with patch(
        "orchestrator.services.input_ttl_store.remove_amenity",
        new=AsyncMock(return_value={"ok": True, "subject": "x", "file": "f", "error": None}),
    ):
        resp = await _request("DELETE", "/api/v1/admin/capabilities/PrayerRoom_104")
    assert resp.status_code == 200
    assert resp.json()["success"] is True


async def test_delete_capability_invalid_id():
    """A local name that fails the regex is rejected before any network call."""
    resp = await _request("DELETE", "/api/v1/admin/capabilities/bad%20name")
    assert resp.status_code == 200
    assert resp.json()["success"] is False


# ---------------------------------------------------------------------------
# Auth gate
# ---------------------------------------------------------------------------


async def test_capabilities_unauthenticated():
    resp = await _request("GET", "/api/v1/admin/capabilities", auth=False)
    assert resp.status_code == 401
