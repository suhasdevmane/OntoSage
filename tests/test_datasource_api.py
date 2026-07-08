"""
Phase 1 tests — /api/v1/datasources admin endpoints (handlers called directly).

Uses the real handler functions from orchestrator.main with a stubbed manager on
app.state, so we exercise the endpoint contract without a live stack.
"""

from __future__ import annotations

import pytest

import orchestrator.main as m

pytestmark = pytest.mark.unit


class _StubManager:
    def __init__(self):
        self.enabled = set()

    def status(self):
        return [
            {"id": "occupancy", "enabled": "occupancy" in self.enabled, "unlocks": ["desk"]},
            {"id": "energy", "enabled": "energy" in self.enabled, "unlocks": ["peak"]},
        ]

    async def enable(self, source_id):
        if source_id not in {"occupancy", "energy"}:
            return {"ok": False, "source_id": source_id, "error": "unknown source"}
        self.enabled.add(source_id)
        return {"ok": True, "source_id": source_id, "enabled": True, "points": 1}

    async def disable(self, source_id):
        self.enabled.discard(source_id)
        return {"ok": True, "source_id": source_id, "enabled": False}

    def create(self, spec_dict):
        sid = spec_dict.get("id")
        if sid in {"occupancy", "energy"}:
            return {"ok": False, "error": f"data source id '{sid}' already exists"}
        return {"ok": True, "source_id": sid, "points": len(spec_dict.get("points", []))}


@pytest.fixture(autouse=True)
def _stub_state(monkeypatch):
    mgr = _StubManager()
    monkeypatch.setattr(m.app.state, "datasource_manager", mgr, raising=False)
    monkeypatch.setattr(m.app.state, "response_cache", None, raising=False)
    return mgr


@pytest.mark.asyncio
async def test_list_datasources_returns_status(_stub_state):
    resp = await m.list_datasources()
    assert resp.success is True
    ids = {s["id"] for s in resp.data["sources"]}
    assert ids == {"occupancy", "energy"}


@pytest.mark.asyncio
async def test_enable_endpoint(_stub_state):
    resp = await m.enable_datasource("occupancy", user=None)
    assert resp.success is True
    assert resp.data["enabled"] is True
    assert "occupancy" in _stub_state.enabled


@pytest.mark.asyncio
async def test_disable_endpoint(_stub_state):
    await m.enable_datasource("energy", user=None)
    resp = await m.disable_datasource("energy", user=None)
    assert resp.success is True
    assert resp.data["enabled"] is False
    assert "energy" not in _stub_state.enabled


@pytest.mark.asyncio
async def test_enable_unknown_source_reports_failure(_stub_state):
    resp = await m.enable_datasource("bogus", user=None)
    assert resp.success is False


@pytest.mark.asyncio
async def test_create_endpoint(_stub_state):
    from shared.models import DataSourceSpec

    spec = DataSourceSpec(
        id="footfall",
        label="Footfall",
        modality="footfall",
        kind="timeseries",
        provenance_system="Footfall System",
        ts_table="occupancy_data",
    )
    resp = await m.create_datasource(body=spec, user=None)
    assert resp.success is True
    assert resp.data["source_id"] == "footfall"


@pytest.mark.asyncio
async def test_create_endpoint_duplicate(_stub_state):
    from shared.models import DataSourceSpec

    spec = DataSourceSpec(id="occupancy", label="dup", modality="occupancy", provenance_system="x")
    resp = await m.create_datasource(body=spec, user=None)
    assert resp.success is False


@pytest.mark.asyncio
async def test_endpoints_when_feature_disabled(monkeypatch):
    monkeypatch.setattr(m.app.state, "datasource_manager", None, raising=False)
    resp = await m.enable_datasource("occupancy", user=None)
    assert resp.success is False
    listing = await m.list_datasources()
    assert listing.success is True and listing.data["sources"] == []
