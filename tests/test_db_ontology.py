"""
Tests for db_ontology — register external-DB sensor metadata (triples + UUIDs)
into a GraphDB named graph so a connected database becomes queryable.
"""

from __future__ import annotations

import pytest

from orchestrator.services import db_ontology as dbo

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


class _Resp:
    def __init__(self, code, text=""):
        self.status_code = code
        self.text = text

    def json(self):
        return {"results": {"bindings": [{"n": {"value": "3"}}]}}


class _Client:
    def __init__(self, put_code=204):
        self.puts = []
        self._code = put_code

    async def put(self, url, content=None, headers=None):
        self.puts.append({"url": url, "content": content})
        return _Resp(self._code)

    async def post(self, url, content=None, headers=None):
        return _Resp(200)


# ── pure helpers ────────────────────────────────────────────────────────────


def test_graph_uri_sanitized():
    assert dbo.graph_uri_for_db("warehouse1") == "urn:ontosage:db:warehouse1"
    assert dbo.graph_uri_for_db("weird key!") == "urn:ontosage:db:weird_key_"


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


# ── registration (fake GraphDB client) ─────────────────────────────────────────


@pytest.mark.asyncio
async def test_register_points_puts_named_graph():
    client = _Client()
    res = await dbo.register_points(
        "warehouse1",
        POINTS,
        graphdb_url="http://g:7200",
        repository="bldg",
        building_namespace="http://x#",
        client=client,
    )
    assert res["ok"] and res["points"] == 1
    assert res["graph"] == "urn:ontosage:db:warehouse1"
    assert "urn%3Aontosage%3Adb%3Awarehouse1" in client.puts[0]["url"]


@pytest.mark.asyncio
async def test_register_points_rejects_invalid():
    res = await dbo.register_points("warehouse1", [{"local": "a"}], client=_Client())
    assert res["ok"] is False and "missing" in res["error"]


@pytest.mark.asyncio
async def test_register_ttl_rejects_bad_turtle():
    res = await dbo.register_ttl("warehouse1", "@@@ not ttl", client=_Client())
    assert res["ok"] is False and "parse error" in res["error"]


@pytest.mark.asyncio
async def test_register_ttl_uploads_valid():
    ttl = (
        "@prefix bldg: <http://x#> . @prefix brick: <https://brickschema.org/schema/Brick#> . "
        "@prefix ref: <https://brickschema.org/schema/Brick/ref#> . "
        "bldg:S1 a brick:Temperature_Sensor ; ref:storedAt bldg:warehouse1 ."
    )
    client = _Client()
    res = await dbo.register_ttl(
        "warehouse1", ttl, graphdb_url="http://g:7200", repository="bldg", client=client
    )
    assert res["ok"] is True and res["warnings"] == []
    assert len(client.puts) == 1


@pytest.mark.asyncio
async def test_register_points_graphdb_failure():
    res = await dbo.register_points(
        "warehouse1",
        POINTS,
        graphdb_url="http://g:7200",
        repository="bldg",
        building_namespace="http://x#",
        client=_Client(put_code=500),
    )
    assert res["ok"] is False
