"""
Phase 1 tests — DataSourceManager enable/disable engine (offline, fake GraphDB).

See tasks/IMPLEMENTATION_PLAN_DATASOURCE_TOGGLES_AND_PROVENANCE.md.
"""

from __future__ import annotations

import textwrap
from pathlib import Path

import pytest

from orchestrator.services.datasource_manager import DataSourceManager
from orchestrator.services.datasource_registry import DataSourceRegistry

pytestmark = pytest.mark.unit


MANIFEST = textwrap.dedent(
    """
    version: 1
    datasources:
      - id: occupancy
        label: "Occupancy Sensing"
        modality: occupancy
        kind: timeseries
        enabled: false
        provenance_system: "Occupancy Sensing System"
        color: "#3B82F6"
        ts_table: occupancy_data
        unlocks: [desk_availability]
        points:
          - local: Occupancy_Sensor_Floor5
            brick_class: brick:Occupancy_Sensor
            location: bldg:Floor5
            unit: unit:PERCENT
      - id: complaints
        label: "Student Complaint System"
        modality: complaints
        kind: text_reports
        enabled: false
        provenance_system: "Student Complaint System"
        color: "#DB2777"
        unlocks: [complaint_trends]
    """
)


class _FakeResp:
    def __init__(self, status_code: int, text: str = ""):
        self.status_code = status_code
        self.text = text


class _FakeClient:
    """Records PUT/DELETE calls; returns 204 by default."""

    def __init__(self, put_status: int = 204, delete_status: int = 204):
        self.puts = []
        self.deletes = []
        self._put_status = put_status
        self._delete_status = delete_status

    async def put(self, url, content=None, headers=None):
        self.puts.append({"url": url, "content": content, "headers": headers})
        return _FakeResp(self._put_status)

    async def delete(self, url):
        self.deletes.append({"url": url})
        return _FakeResp(self._delete_status)


def _manager(tmp_path: Path, client=None) -> DataSourceManager:
    (tmp_path / "datasources.yaml").write_text(MANIFEST, encoding="utf-8")
    reg = DataSourceRegistry("bldg1", input_root=tmp_path)
    reg.load()
    return DataSourceManager(
        "bldg1",
        reg,
        graphdb_url="http://graphdb:7200",
        repository="bldg",
        building_namespace="http://abacwsbuilding.cardiff.ac.uk/abacws#",
        state_path=tmp_path / "state.json",
        client=client,
    )


# ── TTL construction ──────────────────────────────────────────────────────────


def test_build_point_ttl_matches_canonical_pattern(tmp_path: Path):
    mgr = _manager(tmp_path)
    spec = mgr._registry.get("occupancy")
    ttl = mgr.build_point_ttl(spec)
    # canonical bldg1 syntax: rdf:type (not `a`), brick:Class/Entity in the type list
    assert "bldg:Occupancy_Sensor_Floor5 rdf:type" in ttl
    assert "brick:Occupancy_Sensor" in ttl
    assert "brick:Class" in ttl and "brick:Entity" in ttl
    assert "ref:hasExternalReference" in ttl
    assert "ashrae:hasExternalReference" in ttl
    assert "ref:hasTimeseriesId" in ttl
    assert "ref:storedAt bldg:occupancy_data" in ttl
    assert "brick:hasUnit unit:PERCENT" in ttl
    # ONE shared named blank node referenced by both external-ref properties
    assert "_:ref_Occupancy_Sensor_Floor5" in ttl
    assert ttl.count("_:ref_Occupancy_Sensor_Floor5") == 3  # 2 refs + the node decl
    assert "[" not in ttl  # no inline anonymous blank nodes
    # UUID is the deterministic registry-derived one
    assert spec.points[0].uuid in ttl


# ── Enable / disable ────────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_enable_puts_named_graph(tmp_path: Path):
    client = _FakeClient()
    mgr = _manager(tmp_path, client)
    res = await mgr.enable("occupancy")
    assert res["ok"] and res["enabled"] and res["points"] == 1
    assert mgr.is_enabled("occupancy")
    # PUT hit the source's named graph
    assert len(client.puts) == 1
    assert "urn%3Aontosage%3Ads%3Aoccupancy" in client.puts[0]["url"]


@pytest.mark.asyncio
async def test_disable_clears_named_graph(tmp_path: Path):
    client = _FakeClient()
    mgr = _manager(tmp_path, client)
    await mgr.enable("occupancy")
    res = await mgr.disable("occupancy")
    assert res["ok"] and res["enabled"] is False
    assert not mgr.is_enabled("occupancy")
    assert len(client.deletes) == 1


@pytest.mark.asyncio
async def test_state_persists_across_instances(tmp_path: Path):
    client = _FakeClient()
    mgr = _manager(tmp_path, client)
    await mgr.enable("occupancy")
    # new manager instance reads the persisted state file
    reg2 = DataSourceRegistry("bldg1", input_root=tmp_path)
    reg2.load()
    mgr2 = DataSourceManager("bldg1", reg2, state_path=tmp_path / "state.json", client=client)
    assert mgr2.is_enabled("occupancy")


@pytest.mark.asyncio
async def test_text_reports_source_toggles_without_graph_write(tmp_path: Path):
    client = _FakeClient()
    mgr = _manager(tmp_path, client)
    res = await mgr.enable("complaints")
    assert res["ok"] and res["enabled"] and res["points"] == 0
    assert mgr.is_enabled("complaints")
    # no points -> no GraphDB PUT
    assert client.puts == []


@pytest.mark.asyncio
async def test_graphdb_failure_does_not_enable(tmp_path: Path):
    client = _FakeClient(put_status=500)
    mgr = _manager(tmp_path, client)
    res = await mgr.enable("occupancy")
    assert res["ok"] is False
    assert not mgr.is_enabled("occupancy")


@pytest.mark.asyncio
async def test_unknown_source(tmp_path: Path):
    mgr = _manager(tmp_path, _FakeClient())
    res = await mgr.enable("nope")
    assert res["ok"] is False and "error" in res


def test_status_view(tmp_path: Path):
    mgr = _manager(tmp_path, _FakeClient())
    st = {s["id"]: s for s in mgr.status()}
    assert st["occupancy"]["enabled"] is False
    assert st["occupancy"]["unlocks"] == ["desk_availability"]
    assert st["complaints"]["kind"] == "text_reports"


def test_preview_without_generator_reports_error(tmp_path: Path):
    # the manifest here has no generator block, so preview yields empty sample
    mgr = _manager(tmp_path, _FakeClient())
    prev = mgr.preview("occupancy")
    # ok True but nothing to sample (no generator) -> total_rows 0
    assert prev["ok"] is True
    assert prev["total_rows"] == 0


def test_regenerate_updates_state(tmp_path: Path):
    class _FakeSynth:
        def regenerate(self, spec):
            return {"ok": True, "source_id": spec.id, "rows": 96, "ts_table": spec.ts_table}

    (tmp_path / "datasources.yaml").write_text(MANIFEST, encoding="utf-8")
    reg = DataSourceRegistry("bldg1", input_root=tmp_path)
    reg.load()
    mgr = DataSourceManager(
        "bldg1",
        reg,
        state_path=tmp_path / "state.json",
        client=_FakeClient(),
        synthetic_service=_FakeSynth(),
    )
    res = mgr.regenerate("occupancy")
    assert res["ok"] and res["rows"] == 96
    st = {s["id"]: s for s in mgr.status()}
    assert st["occupancy"]["last_generated_at"] is not None
