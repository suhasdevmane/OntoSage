# -*- coding: utf-8 -*-
"""BUG-1443: a fire risk assessment question must reach the register that holds it.

The building keeps its fire risk assessment reviews as ComplianceCheck records titled
"Fire risk assessment review (cycle -N)". The bare phrase "risk assessment" is declared on
RiskAssessment, so a fire question scored that register alone and answered from non-fire
assessments while the word "fire" was silently dropped. The fix is the record class's own
lay terms in the TBox, plus a second-register rule that will not merge a register whose
only matched words sit inside a longer phrase the primary already claims.

These tests read the REAL TBox and the building's compliance TTL with rdflib, the same way
the ontology-shaped tests do, so a renamed label or a removed lay term fails here.
"""

from pathlib import Path

import pytest
import rdflib
from rdflib import RDF, RDFS

from orchestrator.services import record_registry as rr

pytestmark = pytest.mark.unit

REPO = Path(__file__).resolve().parents[1]
ONT = rdflib.Namespace("http://ontosage.org/capabilities#")
LAY = ONT.layTerms


def _compliance_ttl() -> Path:
    for candidate in (
        REPO / "input" / "bldg1_compliance.ttl",
        REPO / "bldg1" / "bldg1_compliance.ttl",
    ):
        if candidate.exists():
            return candidate
    pytest.skip("bldg1_compliance.ttl is not present in this checkout")


@pytest.fixture(scope="module")
def graph() -> rdflib.Graph:
    g = rdflib.Graph()
    g.parse(REPO / "ontology" / "ontosage_schema.ttl", format="turtle")
    g.parse(_compliance_ttl(), format="turtle")
    return g


@pytest.fixture(scope="module")
def classes(graph: rdflib.Graph):
    """The record classes as the registry builds them: TBox terms, instances from the TTL."""
    out = []
    for name in ("ComplianceCheck", "RiskAssessment", "Permit", "Tariff"):
        ref = ONT[name]
        if (ref, None, None) not in graph:
            continue
        label = str(next(iter(graph.objects(ref, RDFS.label)), name))
        lay = "|".join(str(o) for o in graph.objects(ref, LAY))
        instances = len(set(graph.subjects(RDF.type, ref)))
        out.append(
            rr.RecordClass(
                local_name=name,
                label=label,
                instances=instances,
                terms=rr._terms_for(name, label, lay),
            )
        )
    return out


FIRE_QUESTIONS = (
    "What did the last fire risk assessment conclude, and when is the next one due?",
    "When is the next fire risk assessment due?",
    "Is the fire risk assessment review overdue?",
)


def test_the_building_holds_fire_reviews_as_compliance_checks(graph: rdflib.Graph):
    """The premise the fix rests on: the fire reviews are ComplianceCheck, not RiskAssessment."""
    fire = [
        s
        for s in graph.subjects(RDF.type, ONT.ComplianceCheck)
        if "fire risk assessment review"
        in str(next(iter(graph.objects(s, RDFS.label)), "")).lower()
    ]
    assert len(fire) == 7


@pytest.mark.parametrize("question", FIRE_QUESTIONS)
def test_matcher_finds_the_compliance_class_from_fire_wording(classes, question):
    held = rr.held_record_class(question, classes)
    assert held is not None, "a fire risk assessment question held no register"
    assert held.local_name == "ComplianceCheck"


@pytest.mark.parametrize("question", FIRE_QUESTIONS)
def test_fire_question_does_not_merge_the_non_fire_register(classes, question):
    """RiskAssessment matches only "risk assessment", which sits inside the fire phrase."""
    held = rr.held_record_class(question, classes)
    assert rr.second_record_class(question, classes, held) is None


@pytest.mark.parametrize("question", FIRE_QUESTIONS)
def test_fire_question_is_not_declined_as_absent_when_records_exist(classes, question):
    """Regression: the no-record decline must not fire while the register holds the records."""
    held = rr.held_record_class(question, classes)
    assert held is not None
    assert rr.absent_record_class(question, classes) is None


def test_a_non_fire_risk_question_still_reaches_the_risk_register(classes):
    """The fix narrows the fire phrase; plain risk-assessment questions keep their register."""
    held = rr.held_record_class("Which risk assessments are past review?", classes)
    assert held is not None and held.local_name == "RiskAssessment"


def test_second_register_is_kept_when_the_question_names_two_real_registers():
    """The coverage rule must not disable a genuine two-register question."""
    primary = rr.RecordClass("Permit", "Permit", 3, ("permit", "permits"))
    other = rr.RecordClass("Tariff", "Tariff", 2, ("tariff", "tariffs"))
    query = "which permit and which tariff apply to the plant room?"
    second = rr.second_record_class(query, [primary, other], primary)
    assert second is not None and second.local_name == "Tariff"


def test_second_register_is_skipped_when_its_term_sits_inside_the_primary_phrase():
    """A term inside a longer matched phrase of the primary is the same words, not a register."""
    primary = rr.RecordClass(
        "ComplianceCheck", "Compliance check", 5, ("fire risk assessment", "compliance")
    )
    other = rr.RecordClass("RiskAssessment", "Risk assessment", 4, ("risk assessment",))
    query = "what did the last fire risk assessment conclude?"
    assert rr.second_record_class(query, [primary, other], primary) is None
