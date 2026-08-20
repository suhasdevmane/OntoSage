# -*- coding: utf-8 -*-
"""V5-T06: OCBV-2 (Module J) TBox contract tests."""

import re
from pathlib import Path

import pytest
import rdflib

pytestmark = pytest.mark.unit

_SCHEMA = Path(__file__).resolve().parents[1] / "ontology" / "ontosage_schema.ttl"
_NS = "http://ontosage.org/capabilities#"


@pytest.fixture(scope="module")
def graph():
    g = rdflib.Graph()
    g.parse(str(_SCHEMA), format="turtle")
    return g


def test_schema_parses_and_versioned(graph):
    versions = [str(o) for o in graph.objects(None, rdflib.OWL.versionInfo)]
    assert versions and versions[0] >= "2.1.0"


def test_interval_record_hierarchy_complete(graph):
    expected = {
        "Booking",
        "WorkOrder",
        "AccessEvent",
        "AlarmEvent",
        "ComplianceCheck",
        "AnomalyEvent",
    }
    subs = {
        str(s).rsplit("#", 1)[-1]
        for s in graph.subjects(rdflib.RDFS.subClassOf, rdflib.URIRef(_NS + "IntervalRecord"))
    }
    assert expected <= subs, f"missing: {expected - subs}"


def test_every_module_j_term_has_label_and_comment(graph):
    terms = [
        "IntervalRecord",
        "Booking",
        "WorkOrder",
        "AccessEvent",
        "AlarmEvent",
        "ComplianceCheck",
        "AnomalyEvent",
        "ForecastSkill",
        "AccessPolicy",
        "recordStatus",
        "dueDate",
        "responsibleRole",
        "detectedBy",
        "backtestMAE",
        "ciCoverage80",
        "appliesToRole",
        "minAggregationSensors",
        "resolutionTier",
        "rateLimit",
        "inferenceClass",
    ]
    for t in terms:
        node = rdflib.URIRef(_NS + t)
        assert list(graph.objects(node, rdflib.RDFS.label)), f"{t} lacks rdfs:label"


def test_privacy_by_design_wording_present(graph):
    """responsibleRole must forbid person identifiers in its own documentation."""
    comments = " ".join(
        str(o) for o in graph.objects(rdflib.URIRef(_NS + "responsibleRole"), rdflib.RDFS.comment)
    )
    assert "never a person" in comments.lower()


def test_no_building_literals_in_schema():
    banned = re.compile(r"abacws|cardiff|bldg[123]\b|buildsys\.org", re.IGNORECASE)
    hits = [m.group(0) for m in banned.finditer(_SCHEMA.read_text(encoding="utf-8"))]
    assert not hits, f"building literal(s) in TBox: {hits}"


def test_new_amenity_kinds_present(graph):
    for kind in ("Locker", "PrinterPoint"):
        assert (
            rdflib.URIRef(_NS + kind),
            rdflib.RDFS.subClassOf,
            rdflib.URIRef(_NS + "Amenity"),
        ) in graph
