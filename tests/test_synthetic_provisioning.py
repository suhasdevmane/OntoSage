# -*- coding: utf-8 -*-
"""Synthetic provisioning must be declared, deduplicated and imperfect (V6-T56/T58/T60).

Three properties, each guarding a specific way this could go wrong:

* **Declared.** Every provisioned subject carries ``ontosage:isSimulated``. An undeclared
  synthetic record would turn the system's strongest claim -- zero fabrication across every
  V5 grader round -- into a false one.
* **Deduplicated.** Discovery aggregates labels. A subject with two ``rdfs:label``s fans an
  OPTIONAL out into two rows, and the generator would provision a duplicate entity for each.
  This building has exactly that (six floors labelled twice), which presented as "14 floors"
  in a six-storey building and would have produced 40 phantom spaces.
* **Imperfect.** Some assets are degraded and some accessibility features unverified, on
  purpose. A building where everything works cannot test the accessibility hard filter, and
  every gate would pass by construction.
"""

from pathlib import Path

import pytest

rdflib = pytest.importorskip("rdflib")
from rdflib import Graph, URIRef  # noqa: E402

pytestmark = pytest.mark.unit

REPO = Path(__file__).resolve().parent.parent
GEN = REPO / "scripts" / "provision_synthetic_sources.py"
ONTO = "http://ontosage.org/capabilities#"
SIM = URIRef(ONTO + "isSimulated")


def _generated_files():
    return sorted((REPO / "input").glob("*_synthetic_*.ttl"))


needs_files = pytest.mark.skipif(
    not _generated_files(), reason="no provisioned files present (no active building)"
)


# ── the generator itself, testable without a building ────────────────────────


def test_generator_carries_no_building_literal():
    """It reads the ACTIVE building's graph; nothing about a building may be written in."""
    src = GEN.read_text(encoding="utf-8").lower()
    for literal in ("abacws", "buildsys", "cardiff.ac.uk", '"bldg1"', '"bldg2"', '"bldg3"'):
        assert literal not in src, f"building literal in the generator: {literal}"


def test_discovery_aggregates_labels_rather_than_selecting_them():
    """The fan-out guard.

    `SELECT DISTINCT ?s ?label` returns one row PER LABEL, so a doubly-labelled floor becomes
    two floors. Every discovery query must aggregate.
    """
    src = GEN.read_text(encoding="utf-8")
    assert "SAMPLE(?lab)" in src
    assert "GROUP BY ?s" in src
    assert "SELECT DISTINCT ?s ?l " not in src, "un-aggregated label select would fan out"


def test_generator_documents_why_declared_simulation_is_not_fabrication():
    src = GEN.read_text(encoding="utf-8")
    assert "isSimulated" in src
    assert "UNDECLARED" in src or "undeclared" in src


def test_generator_documents_that_imperfection_is_deliberate():
    """If a later maintainer 'fixes' the degraded assets, the gates stop being testable."""
    src = GEN.read_text(encoding="utf-8")
    assert "untestable" in src or "pass by construction" in src


# ── the generated files, when a building is active ───────────────────────────


@needs_files
def test_every_provisioned_subject_declares_its_provenance():
    """The rule V6-T62 will enforce system-wide, checked here at the source."""
    for f in _generated_files():
        g = Graph()
        g.parse(str(f), format="turtle")
        undeclared = set(g.subjects()) - set(g.subjects(SIM, None))
        assert not undeclared, f"{f.name}: {len(undeclared)} subjects lack isSimulated"


@needs_files
def test_generated_files_parse_as_turtle():
    for f in _generated_files():
        Graph().parse(str(f), format="turtle")


@needs_files
def test_accessibility_register_contains_unverified_entries():
    """Both directions of the hard filter must be exercisable.

    A register where every feature is verified cannot test the rule that an unverified
    feature is NOT accessible -- and that rule protects the highest-consequence answer in
    the whole question bank.
    """
    files = [f for f in _generated_files() if "accessibility" in f.name]
    if not files:
        pytest.skip("accessibility family not provisioned")
    g = Graph()
    g.parse(str(files[0]), format="turtle")
    values = {str(o).lower() for o in g.objects(None, URIRef(ONTO + "accessibilityVerified"))}
    assert "true" in values, "no verified feature to test the positive case"
    assert "false" in values, "no UNVERIFIED feature - the hard filter cannot be tested"


@needs_files
def test_asset_status_records_carry_a_source_and_an_observation_time():
    """A status with no traceable issuer cannot support a safety-adjacent decision."""
    files = [f for f in _generated_files() if "status" in f.name]
    if not files:
        pytest.skip("status family not provisioned")
    g = Graph()
    g.parse(str(files[0]), format="turtle")
    statuses = set(g.subjects(URIRef(ONTO + "statusValue"), None))
    assert statuses, "no AssetStatus records provisioned"
    for s in statuses:
        assert list(g.objects(s, URIRef(ONTO + "statusSource"))), f"{s} has no issuing source"
        assert list(
            g.objects(s, URIRef(ONTO + "statusObservedAt"))
        ), f"{s} has no observation time - freshness could not judge it"


@needs_files
def test_no_duplicate_entities_from_label_fanout():
    """The concrete symptom of the fan-out bug: two records for one floor."""
    files = [f for f in _generated_files() if "accessibility" in f.name]
    if not files:
        pytest.skip("accessibility family not provisioned")
    g = Graph()
    g.parse(str(files[0]), format="turtle")
    located = [str(o) for o in g.objects(None, URIRef(ONTO + "locatedIn"))]
    assert len(located) == len(set(located)), f"duplicate locations provisioned: {located}"
