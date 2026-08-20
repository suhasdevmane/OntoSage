"""
Phase 0 tests — DataSource manifest, registry loader, and validator.

See tasks/IMPLEMENTATION_PLAN_DATASOURCE_TOGGLES_AND_PROVENANCE.md.
"""

from __future__ import annotations

import textwrap
from pathlib import Path

import pytest
import yaml

from orchestrator.services.datasource_registry import (
    BUILTIN_PROVENANCE,
    DataSourceRegistry,
    derive_point_uuid,
)
from orchestrator.services.input_validators import validate_datasources_yaml

pytestmark = pytest.mark.unit


VALID_MANIFEST = textwrap.dedent(
    """
    version: 1
    datasources:
      - id: occupancy
        label: "Occupancy Sensing"
        modality: occupancy
        kind: timeseries
        enabled: true
        synthetic: true
        provenance_system: "Occupancy Sensing System"
        color: "#3B82F6"
        ts_table: occupancy_data
        unlocks: [desk_availability, occupancy_peak_hours]
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


def _write(tmp_path: Path, name: str, content: str) -> Path:
    p = tmp_path / name
    p.write_text(content, encoding="utf-8")
    return p


# ── Registry ────────────────────────────────────────────────────────────────


def test_registry_loads_flat_manifest(tmp_path: Path):
    _write(tmp_path, "datasources.yaml", VALID_MANIFEST)
    reg = DataSourceRegistry("bldg1", input_root=tmp_path)
    assert reg.load() == 2
    assert {s.id for s in reg.list()} == {"occupancy", "complaints"}
    assert reg.enabled_ids() == ["occupancy"]


def test_registry_derives_point_uuids(tmp_path: Path):
    _write(tmp_path, "datasources.yaml", VALID_MANIFEST)
    reg = DataSourceRegistry("bldg1", input_root=tmp_path)
    reg.load()
    occ = reg.get("occupancy")
    assert occ is not None and occ.points[0].uuid
    # deterministic + matches the standalone helper
    assert occ.points[0].uuid == derive_point_uuid("bldg1", "occupancy", "Occupancy_Sensor_Floor5")


def test_uuid_is_deterministic_and_building_scoped():
    a = derive_point_uuid("bldg1", "occupancy", "X")
    b = derive_point_uuid("bldg1", "occupancy", "X")
    c = derive_point_uuid("bldg2", "occupancy", "X")
    assert a == b
    assert a != c


def test_unlocks_index(tmp_path: Path):
    _write(tmp_path, "datasources.yaml", VALID_MANIFEST)
    reg = DataSourceRegistry("bldg1", input_root=tmp_path)
    reg.load()
    idx = reg.unlocks_index()
    assert idx["desk_availability"] == "occupancy"
    assert idx["complaint_trends"] == "complaints"


def test_graph_uri_default(tmp_path: Path):
    _write(tmp_path, "datasources.yaml", VALID_MANIFEST)
    reg = DataSourceRegistry("bldg1", input_root=tmp_path)
    reg.load()
    assert reg.get("occupancy").graph_uri() == "urn:ontosage:ds:occupancy"


def test_provenance_for_source_and_table(tmp_path: Path):
    _write(tmp_path, "datasources.yaml", VALID_MANIFEST)
    reg = DataSourceRegistry("bldg1", input_root=tmp_path)
    reg.load()
    tag = reg.provenance_for("occupancy")
    assert tag.label == "Occupancy Sensing System" and tag.synthetic is True
    assert tag.store == "mysql:occupancy_data"
    assert reg.provenance_for_table("occupancy_data").source_id == "occupancy"
    # built-in real store
    assert reg.provenance_for("ontology").synthetic is False


def test_missing_manifest_is_idle(tmp_path: Path):
    reg = DataSourceRegistry("bldg1", input_root=tmp_path)
    assert reg.load() == 0
    assert reg.list() == []


def test_builtin_provenance_present():
    assert "ontology" in BUILTIN_PROVENANCE
    assert BUILTIN_PROVENANCE["analytics"].synthetic is False


# ── Validator ─────────────────────────────────────────────────────────────────


def test_validator_accepts_valid(tmp_path: Path):
    # supply a database_registry.yaml so the ts_table cross-check passes
    _write(
        tmp_path, "database_registry.yaml", yaml.safe_dump({"databases": {"occupancy_data": {}}})
    )
    p = _write(tmp_path, "datasources.yaml", VALID_MANIFEST)
    ok, issues = validate_datasources_yaml(p, input_root=tmp_path)
    assert ok, issues


def test_validator_absent_is_ok(tmp_path: Path):
    ok, issues = validate_datasources_yaml(tmp_path / "nope.yaml")
    assert ok and issues == []


def test_validator_catches_duplicate_id(tmp_path: Path):
    # append a second `occupancy` at the same 6-space list indent (no dedent,
    # which would strip the indent and lift it to top level)
    dup = VALID_MANIFEST + (
        "  - id: occupancy\n"
        '    label: "dup"\n'
        "    modality: occupancy\n"
        '    provenance_system: "x"\n'
        "    ts_table: occupancy_data\n"
    )
    p = _write(tmp_path, "datasources.yaml", dup)
    ok, issues = validate_datasources_yaml(p, input_root=tmp_path)
    assert not ok
    assert any("duplicate source id" in i for i in issues)


def test_validator_catches_bad_kind_and_color(tmp_path: Path):
    bad = textwrap.dedent(
        """
        datasources:
          - id: x
            label: "X"
            modality: energy
            kind: bogus
            provenance_system: "X"
            color: "notacolor"
            ts_table: energy_data
        """
    )
    p = _write(tmp_path, "datasources.yaml", bad)
    ok, issues = validate_datasources_yaml(p, input_root=tmp_path)
    assert not ok
    assert any("kind=" in i for i in issues)
    assert any("hex color" in i for i in issues)


def test_validator_timeseries_requires_ts_table(tmp_path: Path):
    bad = textwrap.dedent(
        """
        datasources:
          - id: x
            label: "X"
            modality: energy
            kind: timeseries
            provenance_system: "X"
        """
    )
    p = _write(tmp_path, "datasources.yaml", bad)
    ok, issues = validate_datasources_yaml(p, input_root=tmp_path)
    assert not ok
    assert any("requires 'ts_table'" in i for i in issues)


def test_validator_unknown_ts_table(tmp_path: Path):
    _write(tmp_path, "database_registry.yaml", yaml.safe_dump({"databases": {"energy_data": {}}}))
    bad = textwrap.dedent(
        """
        datasources:
          - id: x
            label: "X"
            modality: occupancy
            kind: timeseries
            provenance_system: "X"
            ts_table: no_such_table
        """
    )
    p = _write(tmp_path, "datasources.yaml", bad)
    ok, issues = validate_datasources_yaml(p, input_root=tmp_path)
    assert not ok
    assert any("not declared in" in i for i in issues)


def test_validator_point_missing_fields(tmp_path: Path):
    bad = textwrap.dedent(
        """
        datasources:
          - id: x
            label: "X"
            modality: occupancy
            kind: timeseries
            provenance_system: "X"
            ts_table: occupancy_data
            points:
              - local: p1
        """
    )
    _write(
        tmp_path, "database_registry.yaml", yaml.safe_dump({"databases": {"occupancy_data": {}}})
    )
    p = _write(tmp_path, "datasources.yaml", bad)
    ok, issues = validate_datasources_yaml(p, input_root=tmp_path)
    assert not ok
    assert any("brick_class" in i for i in issues)


# ── Seed manifest sanity (the real bldg1 file) ────────────────────────────────


def test_seed_manifest_is_valid():
    # The seed being validated is BLDG1's manifest specifically (all-disabled
    # toggles). Resolve it wherever bldg1 lives — parked folder or active input/
    # — never another building's file that happens to be active.
    seed = Path("bldg1/datasources.yaml")
    if not seed.exists():
        env = Path("input/env.building")
        if env.exists() and "BUILDING_ID=bldg1" in env.read_text(encoding="utf-8"):
            seed = Path("input/datasources.yaml")
    if not seed.exists():
        pytest.skip("bldg1 seed manifest not present")
    ok, issues = validate_datasources_yaml(seed, input_root=seed.parent)
    assert ok, issues
    reg = DataSourceRegistry("bldg1", input_root=seed.parent)
    assert reg.load() >= 7
    # Seed invariant: no capability is unlocked by default. TOGGLE sources
    # (non-empty `unlocks`) ship disabled; SATURATE provenance-only sources
    # (V4-T31, `unlocks: []`) are enabled by design — they gate nothing and
    # exist so provenance chips render '· simulated' for the sat tables.
    enabled = {s.id: s for s in reg.list() if s.enabled}
    gating_enabled = [sid for sid, s in enabled.items() if getattr(s, "unlocks", [])]
    assert gating_enabled == [], f"seed manifest enables gating sources: {gating_enabled}"
    # provenance-only sources: the sat_* saturation legs + the V5 events store
    # (bookings/work orders/access, T31) — all synthetic, none gate anything
    assert all(sid.startswith("sat_") or sid == "events_store" for sid in enabled), sorted(enabled)
