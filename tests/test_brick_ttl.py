"""
Tests for brick_ttl — the single canonical Brick point-TTL builder.

Verifies the output PARSES as Turtle and is semantically identical in shape to the
hand-authored bldg1 ontology (rdf:type list incl. brick:Class/Entity; ONE shared
external-reference node carrying hasTimeseriesId + storedAt).
"""

from __future__ import annotations

import pytest

from orchestrator.services import brick_ttl

pytestmark = pytest.mark.unit

BRICK = "https://brickschema.org/schema/Brick#"
REF = "https://brickschema.org/schema/Brick/ref#"
NS = "http://abacwsbuilding.cardiff.ac.uk/abacws#"

POINT = {
    "local": "Zone_Air_Humidity_Sensor_5_28",
    "brick_class": "brick:Zone_Air_Humidity_Sensor",
    "location": "bldg:Zone_5.28",
    "uuid": "7c28dec2-4d1b-4c70-99c2-4094f9f7de82",
    "stored_at": "database1",
    "label": "Zone Air Humidity Sensor installed-node 5.28",
}


def _graph(ttl: str):
    import rdflib

    g = rdflib.Graph()
    g.parse(data=ttl, format="turtle")
    return g


def test_document_parses_as_valid_turtle():
    ttl = brick_ttl.points_document(NS, [POINT])
    g = _graph(ttl)  # raises if invalid
    assert len(g) > 0


def test_single_shared_external_reference_node():
    """Both ashrae:hasExternalReference and ref:hasExternalReference point to the
    SAME node — like bldg1's _:genidNNN — not two separate blank nodes."""
    import rdflib

    ttl = brick_ttl.points_document(NS, [POINT])
    g = _graph(ttl)
    sensor = rdflib.URIRef(NS + "Zone_Air_Humidity_Sensor_5_28")
    ashrae_ref = list(
        g.objects(sensor, rdflib.URIRef("http://data.ashrae.org/standard223#hasExternalReference"))
    )
    ref_ref = list(g.objects(sensor, rdflib.URIRef(REF + "hasExternalReference")))
    assert len(ashrae_ref) == 1 and len(ref_ref) == 1
    assert ashrae_ref[0] == ref_ref[0]  # the SAME node


def test_external_reference_has_uuid_and_storedat():
    import rdflib

    ttl = brick_ttl.points_document(NS, [POINT])
    g = _graph(ttl)
    sensor = rdflib.URIRef(NS + "Zone_Air_Humidity_Sensor_5_28")
    node = list(g.objects(sensor, rdflib.URIRef(REF + "hasExternalReference")))[0]
    uuid = list(g.objects(node, rdflib.URIRef(REF + "hasTimeseriesId")))
    stored = list(g.objects(node, rdflib.URIRef(REF + "storedAt")))
    assert str(uuid[0]) == POINT["uuid"]
    assert str(stored[0]) == NS + "database1"


def test_type_list_matches_bldg1_shape():
    import rdflib

    ttl = brick_ttl.points_document(NS, [POINT])
    g = _graph(ttl)
    sensor = rdflib.URIRef(NS + "Zone_Air_Humidity_Sensor_5_28")
    types = {str(t) for t in g.objects(sensor, rdflib.RDF.type)}
    for expected in (
        "http://www.w3.org/2002/07/owl#NamedIndividual",
        BRICK + "Class",
        BRICK + "Entity",
        BRICK + "Zone_Air_Humidity_Sensor",
        BRICK + "Point",
        BRICK + "Sensor",
    ):
        assert expected in types, f"missing type {expected}"


def test_location_present():
    import rdflib

    ttl = brick_ttl.points_document(NS, [POINT])
    g = _graph(ttl)
    sensor = rdflib.URIRef(NS + "Zone_Air_Humidity_Sensor_5_28")
    loc = list(g.objects(sensor, rdflib.URIRef(BRICK + "hasLocation")))
    assert str(loc[0]) == NS + "Zone_5.28"
