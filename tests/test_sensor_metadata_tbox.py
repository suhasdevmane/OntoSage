# -*- coding: utf-8 -*-
"""Sensor-metadata vocabulary, Master Report Table 14 (V6-T06).

These terms are what let the building reason about how much its own evidence is worth.
The tests pin three things that are easy to lose in a later edit:

* the terms exist and the TBox still parses (a broken schema takes every building down);
* ``environmentalBoundary`` is a SEPARATE relation from containment - the whole point is
  that a sensor's containing space is not always the space it measures;
* the three clocks are three distinct properties, because a freshness gate must judge
  against transmission interval while a completeness gate derives expected counts from
  archival interval, and collapsing them silently misgrades one or the other.
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


def test_schema_still_parses(g):
    """A malformed TBox takes every building down, so this guards the whole file."""
    assert len(g) > 900


@pytest.mark.parametrize(
    "term",
    [
        "calibratedOn",
        "calibrationMethod",
        "calibrationDueOn",
        "qualityFlag",
        "faultState",
        "mountingHeightM",
        "environmentalBoundary",
        "samplingIntervalS",
        "transmissionIntervalS",
        "archivalIntervalS",
        "accessClassification",
        "ConfigurationPeriod",
        "hasConfigurationPeriod",
        "effectiveFrom",
        "effectiveTo",
        "configurationChange",
        "periodLocation",
    ],
)
def test_table_14_term_is_defined(g, term):
    assert (_t(term), None, None) in g, f"Master Table 14 term missing: {term}"


def test_every_new_term_carries_a_comment(g):
    """A vocabulary term with no rdfs:comment is a term nobody will author correctly."""
    for term in ("calibratedOn", "environmentalBoundary", "archivalIntervalS", "effectiveTo"):
        comments = list(g.objects(_t(term), RDFS.comment))
        assert comments, f"{term} has no rdfs:comment"
        assert len(str(comments[0])) > 60, f"{term} comment is too thin to guide authoring"


def test_environmental_boundary_is_not_containment(g):
    """The reason the property exists at all.

    A sensor in a duct, a plenum, or on a corridor wall serving an adjacent room has a
    CONTAINING space that is not the space whose conditions it measures. The
    non-substitution rule is enforced against the boundary, never against containment - so
    if this ever becomes an alias for brick:hasLocation the gate silently weakens.
    """
    comment = str(list(g.objects(_t("environmentalBoundary"), RDFS.comment))[0]).lower()
    assert "not always" in comment or "duct" in comment
    # It is its own property, not a subproperty of a Brick location relation.
    assert not list(g.objects(_t("environmentalBoundary"), RDFS.subPropertyOf))


def test_the_three_clocks_are_three_properties(g):
    """Master Table 12 keeps sampling, transmission and archival distinct on purpose.

    Freshness judges against TRANSMISSION (a point reporting every 15 min is not stale at
    10); completeness derives expected counts from ARCHIVAL. Collapsing them misgrades one.
    """
    clocks = {"samplingIntervalS", "transmissionIntervalS", "archivalIntervalS"}
    assert len({str(list(g.objects(_t(c), RDFS.comment))[0]) for c in clocks}) == 3


def test_effective_to_documents_that_absent_means_still_in_force(g):
    """The open interval is the normal case; a far-future sentinel silently expires."""
    comment = str(list(g.objects(_t("effectiveTo"), RDFS.comment))[0]).lower()
    assert "absent" in comment and "in force" in comment


def test_calibration_absence_is_documented_as_unknown(g):
    """Absence must never be read as 'fine' - that would let a building claim conformance."""
    comment = str(list(g.objects(_t("calibratedOn"), RDFS.comment))[0]).lower()
    assert "unknown" in comment
    assert "not fine" in comment or "not uncalibrated" in comment


def test_module_documents_why_it_is_ttl_not_yaml():
    """The design decision must survive in the file, not only in the plan."""
    text = SCHEMA.read_text(encoding="utf-8")
    assert "Module M" in text
    assert "sidecar" in text.lower() or "YAML" in text


def test_no_building_literal_entered_the_schema():
    """The TBox is shared vocabulary; instances are per-building."""
    text = SCHEMA.read_text(encoding="utf-8").lower()
    for literal in ("abacws", "cardiff.ac.uk", "buildsys.org"):
        assert literal not in text, f"building literal '{literal}' in the shared TBox"
