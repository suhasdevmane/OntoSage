"""
T24 — Tests for RBAC control:write permission and the approval workflow.
"""

from __future__ import annotations

import json
import time
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from orchestrator.middleware.rbac import ROLE_PERMISSIONS, UserContext
from orchestrator.services.actuation.approval_store import (
    APPROVAL_TTL_SECONDS,
    ActuationApprovalStore,
)

# ── RBAC permission tests ─────────────────────────────────────────────────────


class TestControlWritePermission:
    def test_admin_has_control_write(self):
        assert "control:write" in ROLE_PERMISSIONS["admin"]

    def test_facility_manager_has_control_write(self):
        assert "control:write" in ROLE_PERMISSIONS["facility_manager"]

    def test_operator_does_not_have_control_write(self):
        assert "control:write" not in ROLE_PERMISSIONS["operator"]

    def test_analyst_does_not_have_control_write(self):
        assert "control:write" not in ROLE_PERMISSIONS["analyst"]

    def test_occupant_does_not_have_control_write(self):
        assert "control:write" not in ROLE_PERMISSIONS["occupant"]

    def test_readonly_does_not_have_control_write(self):
        assert "control:write" not in ROLE_PERMISSIONS["readonly"]

    def test_user_context_has_permission(self):
        ctx = UserContext(
            user_id="u1",
            username="alice",
            role="facility_manager",
            tenant_id="bldg1",
            allowed_buildings=[],
            permissions=ROLE_PERMISSIONS["facility_manager"],
        )
        assert ctx.has_permission("control:write") is True

    def test_guest_context_no_control_write(self):
        ctx = UserContext(
            user_id="guest",
            username="guest",
            role="readonly",
            tenant_id="bldg1",
            allowed_buildings=[],
            permissions=ROLE_PERMISSIONS["readonly"],
        )
        assert ctx.has_permission("control:write") is False


# ── Approval store ────────────────────────────────────────────────────────────


def _make_redis_mock(stored: dict):
    """Return a mock Redis client backed by an in-memory dict."""
    client = AsyncMock()

    async def setex(key, ttl, value):
        stored[key] = value

    async def get(key):
        return stored.get(key)

    client.setex = setex
    client.get = get
    return client


class TestApprovalStore:
    @pytest.fixture
    def store_and_redis(self):
        db: dict = {}
        client = _make_redis_mock(db)
        store = ActuationApprovalStore()
        return store, client, db

    @pytest.mark.asyncio
    async def test_create_pending_stores_in_redis(self, store_and_redis):
        store, client, db = store_and_redis
        with patch("orchestrator.services.actuation.approval_store.redis_manager") as rm:
            rm._ensure_client = AsyncMock(return_value=client)
            approval_id = await store.create_pending(
                building_id="bldg1",
                user_id="alice",
                point_uri="urn:bldg1:VAV-501-SP",
                value=22.5,
            )

        assert approval_id is not None
        assert len(approval_id) == 8
        # The key should be in our in-memory db
        key = f"actuation:pending:bldg1:{approval_id}"
        assert key in db
        doc = json.loads(db[key])
        assert doc["status"] == "pending"
        assert doc["point_uri"] == "urn:bldg1:VAV-501-SP"
        assert doc["user_id"] == "alice"

    @pytest.mark.asyncio
    async def test_get_pending_returns_doc(self, store_and_redis):
        store, client, db = store_and_redis
        approval_id = "abc12345"
        doc = {
            "approval_id": approval_id,
            "building_id": "bldg1",
            "user_id": "alice",
            "point_uri": "urn:bldg1:VAV-501-SP",
            "value": 22.5,
            "status": "pending",
            "created_at": time.time(),
            "approved_by": None,
            "approved_at": None,
            "audit_id": None,
        }
        db[f"actuation:pending:bldg1:{approval_id}"] = json.dumps(doc)

        with patch("orchestrator.services.actuation.approval_store.redis_manager") as rm:
            rm._ensure_client = AsyncMock(return_value=client)
            result = await store.get_pending("bldg1", approval_id)

        assert result is not None
        assert result["approval_id"] == approval_id
        assert result["status"] == "pending"

    @pytest.mark.asyncio
    async def test_get_pending_missing_returns_none(self, store_and_redis):
        store, client, db = store_and_redis
        with patch("orchestrator.services.actuation.approval_store.redis_manager") as rm:
            rm._ensure_client = AsyncMock(return_value=client)
            result = await store.get_pending("bldg1", "nonexistent")

        assert result is None

    @pytest.mark.asyncio
    async def test_approve_updates_status(self, store_and_redis):
        store, client, db = store_and_redis
        approval_id = "app11111"
        doc = {
            "approval_id": approval_id,
            "building_id": "bldg1",
            "user_id": "alice",
            "point_uri": "urn:bldg1:VAV-501-SP",
            "value": 22.5,
            "status": "pending",
            "created_at": time.time(),
            "approved_by": None,
            "approved_at": None,
            "audit_id": None,
        }
        key = f"actuation:pending:bldg1:{approval_id}"
        db[key] = json.dumps(doc)

        with patch("orchestrator.services.actuation.approval_store.redis_manager") as rm:
            rm._ensure_client = AsyncMock(return_value=client)
            ok = await store.approve("bldg1", approval_id, approved_by="facility_bob")

        assert ok is True
        updated = json.loads(db[key])
        assert updated["status"] == "approved"
        assert updated["approved_by"] == "facility_bob"
        assert updated["approved_at"] is not None

    @pytest.mark.asyncio
    async def test_approve_returns_false_for_missing(self, store_and_redis):
        store, client, db = store_and_redis
        with patch("orchestrator.services.actuation.approval_store.redis_manager") as rm:
            rm._ensure_client = AsyncMock(return_value=client)
            ok = await store.approve("bldg1", "no-such-id", approved_by="bob")

        assert ok is False

    @pytest.mark.asyncio
    async def test_approve_already_approved_returns_false(self, store_and_redis):
        store, client, db = store_and_redis
        approval_id = "already11"
        doc = {
            "approval_id": approval_id,
            "building_id": "bldg1",
            "user_id": "alice",
            "point_uri": "urn:bldg1:VAV-501-SP",
            "value": 22.5,
            "status": "approved",  # already done
            "created_at": time.time(),
            "approved_by": "bob",
            "approved_at": time.time(),
            "audit_id": "some-audit",
        }
        db[f"actuation:pending:bldg1:{approval_id}"] = json.dumps(doc)

        with patch("orchestrator.services.actuation.approval_store.redis_manager") as rm:
            rm._ensure_client = AsyncMock(return_value=client)
            ok = await store.approve("bldg1", approval_id, approved_by="bob2")

        assert ok is False

    @pytest.mark.asyncio
    async def test_cancel_by_requester(self, store_and_redis):
        store, client, db = store_and_redis
        approval_id = "cancel11"
        doc = {
            "approval_id": approval_id,
            "building_id": "bldg1",
            "user_id": "alice",
            "point_uri": "urn:bldg1:VAV-501-SP",
            "value": 22.5,
            "status": "pending",
            "created_at": time.time(),
            "approved_by": None,
            "approved_at": None,
            "audit_id": None,
        }
        key = f"actuation:pending:bldg1:{approval_id}"
        db[key] = json.dumps(doc)

        with patch("orchestrator.services.actuation.approval_store.redis_manager") as rm:
            rm._ensure_client = AsyncMock(return_value=client)
            ok = await store.cancel("bldg1", approval_id, user_id="alice")

        assert ok is True
        updated = json.loads(db[key])
        assert updated["status"] == "cancelled"

    @pytest.mark.asyncio
    async def test_cancel_by_other_user_denied(self, store_and_redis):
        store, client, db = store_and_redis
        approval_id = "cancel22"
        doc = {
            "approval_id": approval_id,
            "building_id": "bldg1",
            "user_id": "alice",
            "status": "pending",
            "point_uri": "urn:bldg1:VAV-501-SP",
            "value": 22.5,
            "created_at": time.time(),
            "approved_by": None,
            "approved_at": None,
            "audit_id": None,
        }
        db[f"actuation:pending:bldg1:{approval_id}"] = json.dumps(doc)

        with patch("orchestrator.services.actuation.approval_store.redis_manager") as rm:
            rm._ensure_client = AsyncMock(return_value=client)
            ok = await store.cancel("bldg1", approval_id, user_id="bob")

        assert ok is False  # only requester can cancel

    def test_approval_ttl_is_15_minutes(self):
        assert APPROVAL_TTL_SECONDS == 15 * 60
