# -*- coding: utf-8 -*-
"""Served-zone vocabulary (V6-T12, Master Report 8).

The Master Report permits exactly one alternative to an in-room sensor: a *validated served
zone*. This module is that alternative, and the tests pin the property that makes it safe —
**validation is required, and absence fails closed**.

Two shortcuts are permanently out of bounds and are asserted against here:

* *same floor* — that IS the corridor substitution the report forbids; a corridor sensor
  shares a floor with every room it cannot speak for;
* *geometrically nearest* — nearness implying attribution is how BUG-189 attributed a room's
  reading to a corridor the building did not have.
"""

from pathlib import Path

import pytest

rdflib = pytest.importorskip("rdflib")
from rdflib import RDFS, Graph, URIRef  # noqa: E402

pytestmark = pytest.mark.unit

REPO = Path(__file__).resolve().parent.parent
SCHEMA = REPO / "ontology" / "ontosage_schema.ttl"
NS = "http://ontosage.org/capabilities#"


@pytest.fixture(scope="module")
def g() -> "Graph":
    graph = Graph()
    graph.parse(str(SCHEMA), format="turtle")
    return graph


def _t(name: str) -> URIRef:
    return URIRef(NS + name)


@pytest.mark.parametrize(
    "term",
    [
        "ServedZone",
        "servesSpace",
        "servedByPoint",
        "zoneValidated",
        "zoneValidationMethod",
        "zoneValidatedOn",
    ],
)
def test_served_zone_term_is_defined(g, term):
    assert (_t(term), None, None) in g


def test_validation_flag_documents_that_absence_fails_closed(g):
    """The single most important semantic in this module.

    An unvalidated zone that were trusted is a silent substitution wearing a label. The gate
    must treat absent-or-false as proxy, so the comment has to say so unambiguously — this is
    the text an author reads before deciding whether to set the flag.
    """
    comment = str(list(g.objects(_t("zoneValidated"), RDFS.comment))[0]).lower()
    assert "absent or false" in comment
    assert "proxy" in comment
    assert "fail-closed" in comment or "fail closed" in comment


def test_serving_is_documented_as_mechanical_not_geometric(g):
    """Adjacency, floor membership and distance are all explicitly excluded."""
    comment = str(list(g.objects(_t("servesSpace"), RDFS.comment))[0]).lower()
    assert "never" in comment
    for forbidden in ("adjacency", "floor", "distance"):
        assert forbidden in comment, f"servesSpace must rule out {forbidden}"


def test_validation_method_is_recorded_not_just_a_boolean(g):
    """'Validated' means little without saying against what.

    A tracer test and an as-built drawing are not equally strong evidence, and a zone
    validated against a schedule predating a refurbishment describes a building that no
    longer exists.
    """
    assert (_t("zoneValidationMethod"), None, None) in g
    assert (_t("zoneValidatedOn"), None, None) in g


def test_served_zone_is_a_location_not_a_point(g):
    """It is a place, so it can be reasoned about spatially alongside rooms and floors."""
    parents = {str(o) for o in g.objects(_t("ServedZone"), RDFS.subClassOf)}
    assert any("Location" in p for p in parents)


def test_module_records_why_inference_is_forbidden():
    """The reasoning must survive in the schema, not only in the plan."""
    text = SCHEMA.read_text(encoding="utf-8")
    assert "Module N" in text
    assert "BUG-189" in text, "the concrete precedent for forbidding geometric inference"
    assert "same floor" in text.lower()


def test_tbox_still_parses_after_two_new_modules(g):
    assert len(g) > 990
