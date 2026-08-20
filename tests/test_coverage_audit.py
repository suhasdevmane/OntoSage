"""
V4-T06 tests — coverage auditor (space × modality gap matrix).

Fully offline: SPARQL exec is injected with canned SPARQL-JSON fixtures that
mirror the two real location idioms (bldg1: subclass-typed rooms + hasLocation;
bldg2/3: `a brick:Room` + isPointOf equipment).
"""

from __future__ import annotations

import re
from pathlib import Path

import pytest

from orchestrator.services.deliberation.coverage_audit import (
    STATUS_MISSING,
    STATUS_PRESENT,
    STATUS_UNBACKED,
    CoverageAuditor,
    ModalitySpec,
    load_modalities,
)

pytestmark = pytest.mark.unit

NS = "http://example.org/testbldg#"


def _b(**vars_):
    return {k: {"value": v} for k, v in vars_.items() if v is not None}


def _result(*bindings):
    return {"results": {"bindings": list(bindings)}}


def _specs():
    return [
        ModalitySpec("temperature", ["Zone_Air_Temperature_Sensor", "Temperature_Sensor"]),
        ModalitySpec("co2", ["CO2_Level_Sensor"]),
        ModalitySpec("door_contact", ["Contact_Sensor"], label_contains=["door"]),
        ModalitySpec("window_contact", ["Contact_Sensor"], label_contains=["window"]),
    ]


def _make_exec(space_result, point_result, calls=None):
    async def exec_(query: str):
        if calls is not None:
            calls.append(query)
        if "?space a" in query and "?sensor" not in query:
            return space_result
        return point_result

    return exec_


# ── discovery ─────────────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_spaces_discovered_via_subclass_closure():
    """bldg1 shape: rooms typed as Office (Room subclass) found by the path query."""
    spaces = _result(
        _b(space=f"{NS}Office_301", label="Office 3.01", floor=f"{NS}Floor3"),
        _b(space=f"{NS}Lab_302", floor=f"{NS}Floor3"),
    )
    auditor = CoverageAuditor(_make_exec(spaces, _result()), _specs())
    out = await auditor.discover_spaces(NS)
    assert {s.space_iri for s in out} == {f"{NS}Office_301", f"{NS}Lab_302"}
    by_iri = {s.space_iri: s for s in out}
    assert by_iri[f"{NS}Office_301"].label == "Office 3.01"
    assert by_iri[f"{NS}Lab_302"].label == "Lab_302"  # falls back to local name
    assert by_iri[f"{NS}Lab_302"].floor == "Floor3"


@pytest.mark.asyncio
async def test_spaces_fallback_to_direct_room_typing():
    """When the path query yields nothing (no Brick hierarchy), fall back to `a brick:Room`."""
    calls = []
    direct = _result(_b(space=f"{NS}RM001"))

    async def exec_(query):
        calls.append(query)
        if "?sensor" in query:
            return _result()
        if "rdfs:subClassOf* brick:Room" in query:
            return _result()  # closure query: empty
        return direct

    auditor = CoverageAuditor(exec_, _specs())
    out = await auditor.discover_spaces(NS)
    assert [s.space_iri for s in out] == [f"{NS}RM001"]
    assert any("a brick:Room" in q for q in calls)


@pytest.mark.asyncio
async def test_points_join_both_location_idioms():
    """Point discovery accepts hasLocation and isPointOf->equipment rows alike."""
    points = _result(
        _b(
            sensor=f"{NS}TempSensor_301",
            cls="https://brickschema.org/schema/Brick#Temperature_Sensor",
            space=f"{NS}Office_301",
            uuid="u-1",
            stored=f"{NS}database1",
        ),
        _b(
            sensor=f"{NS}RM001A_Zone_Air_Temp",
            cls="https://brickschema.org/schema/Brick#Zone_Air_Temperature_Sensor",
            space=f"{NS}RM001",
            uuid="u-2",
            stored=f"{NS}database2",
        ),
    )
    auditor = CoverageAuditor(_make_exec(_result(), points), _specs())
    out = await auditor.discover_points(NS)
    assert len(out) == 2
    assert out[0]["stored_at"] == "database1"
    assert out[1]["class_local"] == "Zone_Air_Temperature_Sensor"


@pytest.mark.asyncio
async def test_point_query_covers_zone_haspart_idiom_with_floor_guard():
    """Sensors located in an HVAC zone must cover the room(s) the zone hasPart,
    but a Floor's hasPart must never grant floor-wide coverage."""
    calls = []
    auditor = CoverageAuditor(_make_exec(_result(), _result(), calls), _specs())
    await auditor.discover_points(NS)
    point_query = calls[-1]
    assert "?zone brick:hasPart ?space" in point_query
    assert "FILTER NOT EXISTS { ?zone a brick:Floor }" in point_query
    assert "?zone2 brick:hasPart ?space" in point_query


# ── audit matrix ──────────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_audit_present_unbacked_missing():
    spaces = _result(_b(space=f"{NS}RoomA"), _b(space=f"{NS}RoomB"))
    points = _result(
        # RoomA temperature: fully backed (uuid + storedAt) -> present
        _b(
            sensor=f"{NS}TempA",
            cls="x#Temperature_Sensor",
            space=f"{NS}RoomA",
            uuid="u-a",
            stored="x#database1",
        ),
        # RoomA co2: sensor modeled, NO timeseries ref -> unbacked (contract #8 half-met)
        _b(sensor=f"{NS}CO2A", cls="x#CO2_Level_Sensor", space=f"{NS}RoomA"),
    )
    auditor = CoverageAuditor(_make_exec(spaces, points), _specs())
    out = await auditor.audit(NS)
    by_iri = {s.space_iri: s for s in out}
    room_a, room_b = by_iri[f"{NS}RoomA"], by_iri[f"{NS}RoomB"]
    assert room_a.modalities["temperature"]["status"] == STATUS_PRESENT
    assert room_a.modalities["temperature"]["uuid"] == "u-a"
    assert room_a.modalities["co2"]["status"] == STATUS_UNBACKED
    assert room_a.modalities["door_contact"]["status"] == STATUS_MISSING
    assert all(m["status"] == STATUS_MISSING for m in room_b.modalities.values())


@pytest.mark.asyncio
async def test_label_contains_splits_shared_brick_class():
    """door_contact vs window_contact share Contact_Sensor — label decides."""
    spaces = _result(_b(space=f"{NS}RoomA"))
    points = _result(
        _b(
            sensor=f"{NS}Main_Door_Contact",
            cls="x#Contact_Sensor",
            space=f"{NS}RoomA",
            label="Main door contact",
            uuid="u-d",
            stored="x#contact_data",
        ),
    )
    auditor = CoverageAuditor(_make_exec(spaces, points), _specs())
    out = await auditor.audit(NS)
    room = out[0]
    assert room.modalities["door_contact"]["status"] == STATUS_PRESENT
    assert room.modalities["window_contact"]["status"] == STATUS_MISSING


# ── reporting ─────────────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_rows_and_summary_shapes():
    spaces = _result(_b(space=f"{NS}RoomA"))
    points = _result(
        _b(
            sensor=f"{NS}TempA",
            cls="x#Temperature_Sensor",
            space=f"{NS}RoomA",
            uuid="u-a",
            stored="x#database1",
        )
    )
    auditor = CoverageAuditor(_make_exec(spaces, points), _specs())
    audited = await auditor.audit(NS)
    rows = CoverageAuditor.to_rows("anybldg", audited)
    assert len(rows) == len(_specs())  # one row per modality for the single space
    assert {r["status"] for r in rows} == {STATUS_PRESENT, STATUS_MISSING}
    assert rows[0]["building_id"] == "anybldg"
    summary = CoverageAuditor.summary(audited)
    assert summary["temperature"][STATUS_PRESENT] == 1
    assert summary["co2"][STATUS_MISSING] == 1
    assert summary["temperature"]["total"] == 1


# ── config ────────────────────────────────────────────────────────────────────


def test_load_modalities_from_shared_config():
    specs = load_modalities(building_id=None)
    names = {s.name for s in specs}
    assert {"occupancy", "co2", "noise", "temperature", "illuminance"} <= names
    assert all(s.brick_classes for s in specs)


def test_load_modalities_overlay_replaces_and_extends(tmp_path: Path):
    base = tmp_path / "base.yaml"
    base.write_text(
        "modalities:\n"
        "  co2:\n    brick_classes: [CO2_Level_Sensor]\n"
        "  noise:\n    brick_classes: [Sound_Level_Sensor]\n",
        encoding="utf-8",
    )
    # Overlay via the flat input layout: <input_root>/saturation_modalities.yaml.
    # resolve_building_file consults the repo's real input roots, so emulate the
    # merge contract directly through a second config load.
    overlay = tmp_path / "saturation_modalities.yaml"
    overlay.write_text(
        "modalities:\n"
        "  noise:\n    brick_classes: [Noise_Level_Sensor]\n"
        "  vibration:\n    brick_classes: [Vibration_Sensor]\n",
        encoding="utf-8",
    )
    import orchestrator.services.deliberation.coverage_audit as ca

    orig = ca.resolve_building_file
    ca.resolve_building_file = lambda bid, fname, input_root=None: overlay
    try:
        specs = {s.name: s for s in load_modalities("anybldg", config_path=base)}
    finally:
        ca.resolve_building_file = orig
    assert specs["noise"].brick_classes == ["Noise_Level_Sensor"]  # replaced
    assert "vibration" in specs  # extended
    assert specs["co2"].brick_classes == ["CO2_Level_Sensor"]  # untouched


# ── building-agnosticism scan (V4 contract) ──────────────────────────────────


def test_no_building_literals_in_deliberation_modules():
    """Mirror of test_routing_contract's scan: zero building literals in V4 modules."""
    banned = re.compile(r"abacws|cardiff|bldg[123]\b|buildsys\.org", re.IGNORECASE)
    pkg = Path(__file__).resolve().parents[1] / "orchestrator" / "services" / "deliberation"
    for py in pkg.glob("*.py"):
        text = py.read_text(encoding="utf-8")
        hits = [m.group(0) for m in banned.finditer(text)]
        assert not hits, f"building literal(s) {hits} in {py.name}"
