"""V4-T12 tests — amenity ABox builder (structured locations for proximity)."""

from __future__ import annotations

import pytest
import rdflib

from orchestrator.services.deliberation.amenities import (
    build_amenity_ttl,
    plan_amenities,
)
from orchestrator.services.deliberation.coverage_audit import SpaceCoverage

pytestmark = pytest.mark.unit

NS = "http://example.org/testbldg#"
ONTOSAGE = rdflib.Namespace("http://ontosage.org/capabilities#")


def _spaces():
    out = []
    for floor, locals_ in (("floor0", ["RM001", "RM002", "RM003"]), ("floor1", ["RM101", "RM102"])):
        for loc in locals_:
            sc = SpaceCoverage(space_iri=f"{NS}{loc}", label=loc, floor=floor)
            out.append(sc)
    return out


def test_plan_one_of_each_kind_per_floor_deterministic():
    plan1 = plan_amenities(_spaces())
    plan2 = plan_amenities(list(reversed(_spaces())))
    assert plan1 == plan2  # order-independent
    for kind in ("DrinkingWater", "ToiletFacility", "StudyArea"):
        assert [p["floor"] for p in plan1[kind]] == ["floor0", "floor1"]


def test_ttl_parses_dual_typed_and_located():
    plan = plan_amenities(_spaces())
    ttl = build_amenity_ttl(NS, plan)
    g = rdflib.Graph()
    g.parse(data=ttl, format="turtle")
    water0 = rdflib.URIRef(f"{NS}Amenity_DrinkingWater_floor0")
    # dual typing keeps the CapabilityGraphResolver's exact `a ontosage:Amenity` match working
    assert (water0, rdflib.RDF.type, ONTOSAGE.Amenity) in g
    assert (water0, rdflib.RDF.type, ONTOSAGE.DrinkingWater) in g
    located = list(g.objects(water0, ONTOSAGE.locatedIn))
    assert len(located) == 1 and str(located[0]).startswith(NS)
    assert (water0, ONTOSAGE.isSimulated, rdflib.Literal(True)) in g
    # every amenity individual carries a structured location
    for amenity in g.subjects(rdflib.RDF.type, ONTOSAGE.Amenity):
        assert list(g.objects(amenity, ONTOSAGE.locatedIn)), f"{amenity} has no locatedIn"


def test_ttl_idempotent():
    s = _spaces()
    assert build_amenity_ttl(NS, plan_amenities(s)) == build_amenity_ttl(NS, plan_amenities(s))
