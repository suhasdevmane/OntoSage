"""
Tests for db_ontology — register external-DB sensor metadata (triples + UUIDs).

Registration now writes the metadata to an ``input/db_<key>_sensors.ttl`` file (the source of
truth) via ``input_ttl_store.persist_ttl_file`` and syncs that file's named graph to GraphDB, so
sensors survive a volume reset and reload on restart. These tests mock ``persist_ttl_file`` to
assert db_ontology's contract (build TTL → persist with merge=True → map the result) without any
filesystem or network side effects.
"""

from __future__ import annotations

import pytest

from orchestrator.services import db_ontology as dbo
from orchestrator.services import input_ttl_store

pytestmark = pytest.mark.unit


POINTS = [
    {
        "local": "Warehouse_Temp_1",
        "brick_class": "brick:Temperature_Sensor",
        "location": "bldg:Zone_A",
        "unit": "unit:DEG_C",
        "uuid": "11111111-2222-3333-4444-555555555555",
    }
]


@pytest.fixture
def fake_persist(monkeypatch):
    """Replace persist_ttl_file with a recorder that succeeds; returns the call log."""
    calls = []

    async def _fake(filename, ttl_text, *, merge=False, replace_subjects=False, client=None):
        calls.append(
            {
                "filename": filename,
                "ttl": ttl_text,
                "merge": merge,
                "replace_subjects": replace_subjects,
            }
        )
        return {"ok": True, "file": f"input/{filename}", "graph": f"urn:ontosage:ttl:{filename}"}

    monkeypatch.setattr(input_ttl_store, "persist_ttl_file", _fake)
    return calls


# ── pure helpers ────────────────────────────────────────────────────────────


def test_graph_uri_sanitized():
    # Legacy DB graph (pre file-persistence) — kept for migration/cleanup.
    assert dbo.graph_uri_for_db("warehouse1") == "urn:ontosage:db:warehouse1"
    assert dbo.graph_uri_for_db("weird key!") == "urn:ontosage:db:weird_key_"


def test_sensors_filename_and_file_graph():
    assert dbo.sensors_filename("warehouse1") == "db_warehouse1_sensors.ttl"
    assert dbo.sensors_filename("weird key!") == "db_weird_key__sensors.ttl"
    # The file graph must match ttl_uploader's convention so live-sync and restart-load agree.
    assert dbo.graph_uri_for_db_file("warehouse1") == "urn:ontosage:ttl:db_warehouse1_sensors.ttl"


def test_build_points_ttl_canonical_and_storedat():
    ttl = dbo.build_points_ttl("http://abacwsbuilding.cardiff.ac.uk/abacws#", "warehouse1", POINTS)
    assert "bldg:Warehouse_Temp_1 rdf:type" in ttl  # canonical rdf:type, not `a`
    assert "brick:Temperature_Sensor" in ttl
    assert "brick:Class" in ttl and "brick:Entity" in ttl
    assert "ref:hasExternalReference" in ttl and "ashrae:hasExternalReference" in ttl
    assert 'ref:hasTimeseriesId "11111111-2222-3333-4444-555555555555"' in ttl
    assert "ref:storedAt bldg:warehouse1" in ttl
    assert "brick:hasUnit unit:DEG_C" in ttl
    # one shared named external-ref node (like bldg1's _:genidNNN), no inline [ ]
    assert "_:ref_Warehouse_Temp_1" in ttl and "[" not in ttl


def test_validate_points_catches_missing_and_dupes():
    issues = dbo.validate_points(
        [{"local": "a"}, {"local": "a", "brick_class": "x", "location": "y", "uuid": "u"}]
    )
    assert any("missing 'uuid'" in i for i in issues)
    assert any("duplicate local" in i for i in issues)


def test_validate_ttl_parse_error():
    issues = dbo.validate_ttl("this is not turtle @@@", "warehouse1")
    assert issues and "parse error" in issues[0]


def test_validate_ttl_warns_when_key_absent():
    good = (
        "@prefix bldg: <http://x#> . @prefix brick: <https://brickschema.org/schema/Brick#> . "
        "bldg:S1 a brick:Temperature_Sensor ."
    )
    issues = dbo.validate_ttl(good, "warehouse1")
    assert any(i.startswith("warning:") and "warehouse1" in i for i in issues)


# ── registration (persist_ttl_file mocked) ──────────────────────────────────


@pytest.mark.asyncio
async def test_register_points_persists_and_merges(fake_persist):
    res = await dbo.register_points("warehouse1", POINTS, building_namespace="http://x#")
    assert res["ok"] and res["points"] == 1 and res["persisted"] is True
    assert res["graph"] == "urn:ontosage:ttl:db_warehouse1_sensors.ttl"
    assert res["file"] == "input/db_warehouse1_sensors.ttl"
    # Exactly one persist, additive (merge=True), to the DB's sensor file, with the storedAt link.
    assert len(fake_persist) == 1
    call = fake_persist[0]
    assert call["filename"] == "db_warehouse1_sensors.ttl"
    assert call["merge"] is True and call["replace_subjects"] is True  # upsert, not blind append
    assert "ref:storedAt bldg:warehouse1" in call["ttl"]


@pytest.mark.asyncio
async def test_register_points_rejects_invalid(fake_persist):
    res = await dbo.register_points("warehouse1", [{"local": "a"}])
    assert res["ok"] is False and "missing" in res["error"]
    assert fake_persist == []  # invalid input never touches persistence


@pytest.mark.asyncio
async def test_register_ttl_rejects_bad_turtle(fake_persist):
    res = await dbo.register_ttl("warehouse1", "@@@ not ttl")
    assert res["ok"] is False and "parse error" in res["error"]
    assert fake_persist == []


@pytest.mark.asyncio
async def test_register_ttl_persists_valid(fake_persist):
    ttl = (
        "@prefix bldg: <http://x#> . @prefix brick: <https://brickschema.org/schema/Brick#> . "
        "@prefix ref: <https://brickschema.org/schema/Brick/ref#> . "
        "bldg:S1 a brick:Temperature_Sensor ; ref:storedAt bldg:warehouse1 ."
    )
    res = await dbo.register_ttl("warehouse1", ttl)
    assert res["ok"] is True and res["warnings"] == [] and res["persisted"] is True
    assert len(fake_persist) == 1 and fake_persist[0]["replace_subjects"] is True


@pytest.mark.asyncio
async def test_register_points_persist_failure(monkeypatch):
    async def _fail(filename, ttl_text, *, merge=False, replace_subjects=False, client=None):
        return {"ok": False, "file": None, "graph": None}

    monkeypatch.setattr(input_ttl_store, "persist_ttl_file", _fail)
    res = await dbo.register_points("warehouse1", POINTS, building_namespace="http://x#")
    assert res["ok"] is False
