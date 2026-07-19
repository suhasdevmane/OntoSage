"""
tests/test_input_ttl_store.py — the input/ folder as the source of truth for TTL.

Exercises the real file mutation (write / rdflib triple edit / backup-to-.trash / trash-move)
against a temp input dir, with the GraphDB sync mocked. This is the risky logic behind the
GUI <-> input/ two-way sync, so it is tested directly rather than only through the endpoints.
"""

from __future__ import annotations

from unittest.mock import AsyncMock, patch

import pytest

import orchestrator.services.input_ttl_store as store

pytestmark = pytest.mark.unit


@pytest.fixture
def tmp_input(tmp_path, monkeypatch):
    """Point the store at a throwaway input dir and stub GraphDB sync."""
    monkeypatch.setattr(store, "writable_input_dir", lambda: tmp_path)
    # Force capabilities_path to the temp dir (never the real repo TTL).
    monkeypatch.setattr(store, "resolve_building_file", lambda *a, **k: None)
    monkeypatch.setattr(
        store, "_sync_file_to_graph", AsyncMock(return_value={"ok": True, "graph": "g"})
    )
    return tmp_path


def _cafe_block():
    from orchestrator.services.capability_admin import build_amenity_ttl

    built = build_amenity_ttl(
        "bldg1",
        local="Cafe_Ground",
        cls="Cafe",
        label="Ground Cafe",
        location="Ground floor",
        lay_terms="coffee, cafe",
    )
    assert built["ok"]
    return built["subject"], built["ttl"]


# ---------------------------------------------------------------------------
# Graph-URI alignment with ttl_uploader
# ---------------------------------------------------------------------------


def test_graph_uri_matches_ttl_uploader_convention():
    from pathlib import Path

    from orchestrator.services.ttl_uploader import _graph_uri_for_path

    name = "bldg1_capabilities.ttl"
    assert store.graph_uri_for_filename(name) == _graph_uri_for_path(Path(name))


def test_filename_from_graph_uri_roundtrip():
    assert store.filename_from_graph_uri("urn:ontosage:ttl:bldg1_x.ttl") == "bldg1_x.ttl"
    assert store.filename_from_graph_uri("urn:ontosage:custom:extension") is None


# ---------------------------------------------------------------------------
# Capability upsert / remove (real file mutation)
# ---------------------------------------------------------------------------


async def test_upsert_amenity_creates_file(tmp_input):
    subject, block = _cafe_block()
    res = await store.upsert_amenity("bldg1", subject, block)
    assert res["ok"] is True

    path = tmp_input / "bldg1_capabilities.ttl"
    assert path.exists()
    text = path.read_text(encoding="utf-8")
    assert "Cafe_Ground" in text
    assert "ontosage:Amenity" in text
    # The graph sync was invoked with the file.
    store._sync_file_to_graph.assert_awaited()


async def test_upsert_is_idempotent_replace(tmp_input):
    """Upserting the same subject twice does not duplicate it."""
    subject, block = _cafe_block()
    await store.upsert_amenity("bldg1", subject, block)
    await store.upsert_amenity("bldg1", subject, block)

    from rdflib import Graph, URIRef

    g = Graph()
    g.parse(str(tmp_input / "bldg1_capabilities.ttl"), format="turtle")
    labels = list(g.triples((URIRef(subject), None, None)))
    # One rdf:type-pair + label + a couple of props — but exactly one subject block,
    # so the type triples must not have doubled.
    types = [t for t in labels if str(t[1]).endswith("type")]
    assert len(types) == 2  # ontosage:Cafe + ontosage:Amenity, not 4


async def test_remove_amenity_deletes_triples_and_backs_up(tmp_input):
    subject, block = _cafe_block()
    await store.upsert_amenity("bldg1", subject, block)

    res = await store.remove_amenity("bldg1", subject)
    assert res["ok"] is True

    text = (tmp_input / "bldg1_capabilities.ttl").read_text(encoding="utf-8")
    assert "Cafe_Ground" not in text
    # A backup was written to .trash before the mutating write.
    trash = tmp_input / ".trash"
    assert trash.exists() and any(trash.iterdir())


async def test_remove_absent_subject_falls_back_to_graph_delete(tmp_input):
    """Removing a subject that is in no file falls back to a direct graph delete."""
    with patch(
        "orchestrator.services.ontology_manager.delete_subject",
        new=AsyncMock(return_value={"ok": True, "subject": "x", "error": None}),
    ) as m:
        res = await store.remove_amenity("bldg1", "http://x#Nope")
    assert res["ok"] is True
    m.assert_awaited()


# ---------------------------------------------------------------------------
# Generic file persist / trash (Ontology tab)
# ---------------------------------------------------------------------------


async def test_persist_ttl_file_writes_and_syncs(tmp_input):
    ttl = "@prefix ex: <http://example.org/> .\nex:a ex:b ex:c .\n"
    res = await store.persist_ttl_file("my_ext.ttl", ttl)
    assert res["ok"] is True
    assert (tmp_input / "my_ext.ttl").read_text(encoding="utf-8") == ttl


async def test_persist_ttl_file_merge_unions_triples(tmp_input):
    await store.persist_ttl_file("m.ttl", "@prefix ex: <http://example.org/> .\nex:a ex:b ex:c .\n")
    await store.persist_ttl_file(
        "m.ttl", "@prefix ex: <http://example.org/> .\nex:d ex:e ex:f .\n", merge=True
    )
    from rdflib import Graph

    g = Graph()
    g.parse(str(tmp_input / "m.ttl"), format="turtle")
    assert len(g) == 2  # both triples survive the merge


async def test_trash_ttl_file_moves_and_drops(tmp_input):
    (tmp_input / "gone.ttl").write_text("@prefix ex: <http://x/> .\nex:a ex:b ex:c .\n")
    with patch(
        "orchestrator.services.ontology_manager.drop_named_graph",
        new=AsyncMock(return_value=True),
    ):
        res = await store.trash_ttl_file("gone.ttl")
    assert res["dropped"] is True
    assert not (tmp_input / "gone.ttl").exists()  # moved out
    assert res["trashed_to"] and ".trash" in res["trashed_to"]


# ---------------------------------------------------------------------------
# Durable + honest deletes (A1)
# ---------------------------------------------------------------------------


async def test_remove_amenity_in_other_file_persists(tmp_input):
    """An amenity defined in a NON-capabilities input TTL is removed from THAT file (durable
    across restart), not via a graph-only delete that would reload on the next boot."""
    other = tmp_input / "equipment_linkage.ttl"
    other.write_text(
        "@prefix ontosage: <http://ontosage.org/capabilities#> .\n"
        "@prefix rdfs: <http://www.w3.org/2000/01/rdf-schema#> .\n"
        "@prefix bldg: <http://x/> .\n"
        'bldg:TeaBar a ontosage:Cafe, ontosage:Amenity ; rdfs:label "Tea Bar" .\n',
        encoding="utf-8",
    )
    with patch(
        "orchestrator.services.ontology_manager.delete_subject",
        new=AsyncMock(return_value={"ok": True, "subject": "x", "error": None}),
    ) as m:
        res = await store.remove_amenity("bldg1", "http://x/TeaBar")

    assert res["ok"] is True
    assert res["file"] == str(other)
    assert "TeaBar" not in other.read_text(encoding="utf-8")
    m.assert_not_awaited()  # edited the owning file; did NOT fall back to a graph-only delete


async def test_delete_subject_clears_named_graphs():
    """delete_subject issues a GRAPH-scoped delete so triples living in a named graph (where
    ttl_uploader loads everything) are removed deterministically, not just the default graph."""
    from orchestrator.services import ontology_manager

    posted: dict = {}

    class _Resp:
        status_code = 204
        text = ""

    class _Client:
        async def post(self, url, content=None, headers=None):
            posted["body"] = content.decode("utf-8") if isinstance(content, bytes) else content
            return _Resp()

    res = await ontology_manager.delete_subject("http://x/Foo", client=_Client())
    assert res["ok"] is True
    assert "GRAPH ?g" in posted["body"]  # named-graph clause present
    assert "http://x/Foo" in posted["body"]


# ---------------------------------------------------------------------------
# Atomic writes (A2) + serialized writes (A3)
# ---------------------------------------------------------------------------


def test_atomic_write_preserves_original_on_failure(tmp_input, monkeypatch):
    """A failed rename leaves the original file intact (no truncation) and leaks no temp."""
    path = tmp_input / "keep.ttl"
    path.write_text("ORIGINAL", encoding="utf-8")

    def _boom(*_a, **_k):
        raise OSError("simulated crash during replace")

    monkeypatch.setattr(store.os, "replace", _boom)
    with pytest.raises(OSError):
        store._atomic_write(path, "NEW-CONTENT-THAT-MUST-NOT-LAND")

    assert path.read_text(encoding="utf-8") == "ORIGINAL"  # untouched
    assert not list(tmp_input.glob(".keep.ttl.*.tmp"))  # temp cleaned up


async def test_concurrent_upserts_both_survive(tmp_input):
    """Two concurrent upserts of different amenities both land — neither is lost-updated.
    (Cross-process exclusion is provided by filelock; this guards the in-process path.)"""
    import asyncio

    from orchestrator.services.capability_admin import build_amenity_ttl

    def _block(local: str, label: str):
        b = build_amenity_ttl("bldg1", local=local, cls="Cafe", label=label, lay_terms="x")
        return b["subject"], b["ttl"]

    s1, t1 = _block("Cafe_A", "Cafe A")
    s2, t2 = _block("Cafe_B", "Cafe B")
    await asyncio.gather(
        store.upsert_amenity("bldg1", s1, t1),
        store.upsert_amenity("bldg1", s2, t2),
    )

    text = (tmp_input / "bldg1_capabilities.ttl").read_text(encoding="utf-8")
    assert "Cafe_A" in text and "Cafe_B" in text


# ── persist_ttl_file upsert (replace_subjects) — sensor re-registration ──────


@pytest.mark.asyncio
async def test_persist_upsert_replaces_subject_no_dup_refnodes(tmp_input):
    """Re-registering a sensor REPLACES its triples (same uuid) and leaves exactly one external-ref
    node — the blank-node duplication a plain union merge would cause is avoided."""
    from rdflib import RDF, Graph, URIRef

    from orchestrator.services.db_ontology import build_points_ttl, sensors_filename

    ns = "http://x#"
    fn = sensors_filename("wh")
    pt = lambda label: [  # noqa: E731
        {
            "local": "S1",
            "brick_class": "brick:Temperature_Sensor",
            "location": "bldg:Z",
            "uuid": "u1",
            "label": label,
        }
    ]

    await store.persist_ttl_file(
        fn, build_points_ttl(ns, "wh", pt("Old Label")), merge=True, replace_subjects=True
    )
    await store.persist_ttl_file(
        fn, build_points_ttl(ns, "wh", pt("New Label")), merge=True, replace_subjects=True
    )

    g = Graph()
    g.parse(str(tmp_input / fn), format="turtle")
    sensor = URIRef("http://x#S1")
    label_p = URIRef("http://www.w3.org/2000/01/rdf-schema#label")
    labels = sorted(str(o) for o in g.objects(sensor, label_p))
    assert labels == ["New Label"]  # old label replaced, not duplicated

    ref_type = URIRef("https://brickschema.org/schema/Brick/ref#TimeseriesReference")
    assert len(list(g.subjects(RDF.type, ref_type))) == 1  # no accumulated duplicate ref node


@pytest.mark.asyncio
async def test_persist_upsert_preserves_other_sensors(tmp_input):
    """Registering a new sensor keeps previously-registered sensors — additive across subjects."""
    from rdflib import Graph, URIRef

    from orchestrator.services.db_ontology import build_points_ttl, sensors_filename

    ns = "http://x#"
    fn = sensors_filename("wh")

    def one(local, uuid):
        return build_points_ttl(
            ns,
            "wh",
            [
                {
                    "local": local,
                    "brick_class": "brick:Temperature_Sensor",
                    "location": "bldg:Z",
                    "uuid": uuid,
                }
            ],
        )

    await store.persist_ttl_file(fn, one("S1", "u1"), merge=True, replace_subjects=True)
    await store.persist_ttl_file(fn, one("S2", "u2"), merge=True, replace_subjects=True)

    g = Graph()
    g.parse(str(tmp_input / fn), format="turtle")
    assert any(g.triples((URIRef("http://x#S1"), None, None)))
    assert any(g.triples((URIRef("http://x#S2"), None, None)))
