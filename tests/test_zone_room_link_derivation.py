# -*- coding: utf-8 -*-
"""The derived zone <-> room links must be conservative and loadable (BUG-388).

bldg1's spatial graph was two disconnected overlays: real sensors on HVAC zones, the
synthetic saturation overlay on rooms, 39 zones, 234 rooms and ZERO joining predicates. A
question about "room 5.04" therefore never saw the room's real sensor, which is the second
half of BUG-378.

Two things are pinned here.

**Conservatism.** These triples go into the source of truth, and a wrong containment claim is
worse than the gap it fills — it would let an answer about one room be served from another
room's sensor, the exact substitution the honesty contract forbids. So a link is asserted
only where one zone and one room share an identifier exactly. On bldg1 that is 24 of 34
zones; the 10 zones with no matching room and the 201 rooms with no zone are left alone.

**Loadability.** The first version emitted full IRIs and was HARD-FAILED at boot by the TTL
validator, which requires every per-building file to declare `@prefix bldg:` agreeing with
the building's ontology_namespace. The file was written, looked right, and the orchestrator
refused to start. That check belongs in a test, not in a restart.
"""

import importlib.util
from pathlib import Path

import pytest

pytestmark = pytest.mark.unit

_SCRIPT = Path(__file__).resolve().parent.parent / "scripts" / "derive_zone_room_links.py"


def _load():
    spec = importlib.util.spec_from_file_location("derive_zone_room_links", _SCRIPT)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)  # type: ignore[union-attr]
    return mod


gen = _load()

NS = "http://example.org/bldgX#"
LINKS = [(f"{NS}Zone_5.04", f"{NS}Room5.04", "5.04"), (f"{NS}Zone_5.01", f"{NS}Room5.01", "5.01")]


# ── the file must load ─────────────────────────────────────────────────────────────────


def test_the_building_prefix_is_declared():
    """Its absence HARD-FAILS the validator and stops the orchestrator booting."""
    ttl = gen.render_ttl(LINKS, "bldgX")
    assert f"@prefix bldg:  <{NS}> ." in ttl


def test_the_namespace_is_read_from_the_data_not_configured():
    """A declaration that disagrees with the entities is the failure being prevented."""
    assert gen._namespace_of(f"{NS}Zone_5.04") == NS
    assert gen._namespace_of("http://x.org/ns/Zone_1.01") == "http://x.org/ns/"


def test_entities_are_written_as_prefixed_names():
    ttl = gen.render_ttl(LINKS, "bldgX")
    assert "bldg:Zone_5.04 brick:hasPart bldg:Room5.04" in ttl
    assert f"<{NS}Zone_5.04>" not in ttl


def test_both_directions_are_asserted():
    """Traversal must work from either end; the lane may start at the room or the zone."""
    ttl = gen.render_ttl(LINKS, "bldgX")
    assert "bldg:Zone_5.04 brick:hasPart bldg:Room5.04" in ttl
    assert "bldg:Room5.04 brick:isPartOf bldg:Zone_5.04" in ttl


def test_every_link_declares_that_it_was_derived_not_surveyed():
    """A derived containment claim must never be mistaken for a survey result."""
    ttl = gen.render_ttl(LINKS, "bldgX")
    assert ttl.count("derived-zone-room-link-v1") == len(LINKS) * 2
    assert "not surveyed" in ttl


# ── conservatism ───────────────────────────────────────────────────────────────────────


def test_an_identifier_is_taken_only_from_the_end_of_a_name():
    """A digit elsewhere must not masquerade as the identifier."""
    by_id = gen._by_identifier([f"{NS}Zone_5.04", f"{NS}Block2_Corridor", f"{NS}AHU_3.01"])
    assert set(by_id) == {"5.04", "3.01"}


def test_matching_pairs_one_zone_to_one_room():
    by_id = gen._by_identifier([f"{NS}Zone_5.04", f"{NS}Room5.04"])
    assert by_id["5.04"] == [f"{NS}Zone_5.04", f"{NS}Room5.04"]


def test_a_name_with_no_trailing_identifier_is_ignored():
    assert gen._by_identifier([f"{NS}HVAC_Zone_F0", f"{NS}east-Zone"]) == {}


def test_the_generated_file_parses_as_turtle():
    """Cheapest possible guard against emitting something GraphDB will reject."""
    rdflib = pytest.importorskip("rdflib")
    graph = rdflib.Graph()
    graph.parse(data=gen.render_ttl(LINKS, "bldgX"), format="turtle")
    # two entities x (one link + one comment) each, per pair
    assert len(graph) == len(LINKS) * 4
