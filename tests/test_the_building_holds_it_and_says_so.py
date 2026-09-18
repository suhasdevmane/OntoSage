# -*- coding: utf-8 -*-
"""The register a question names is the one that holds the answer (BUG-710 / BUG-711).

Run 3 of the 147-question live read (``docs/phase0/phase0_run3_read.md``) put eight rows in
class C9 — "the building holds the data but no lane reaches it" — and nine in C4, where the
metadata lane answered from the ontology's CLASS DEFINITIONS and declared an absence the
graph does not support. Three of the C9 rows are contradicted by another answer in the SAME
run: a supervisor who asks two related questions sees the contradiction himself.

Eight of those rows reached no held register at all, so nothing downstream could have saved
them. Each one is pinned here BY ITS REAL QUESTION, against the real schema TTL and the real
scorer, with the count that proves the building holds what the answer denied:

    row 4   AC-064  no register -> AccessPermission     20 permission groups, one "withdrawn"
    row 9   AD-072  no register -> CirculationTime      21 floor pairs, walking + step-free
    row 33  FM-014  ComplianceCheck -> AccessibleRoute  16 surveyed routes with entrances
    row 44  HS-071  no register -> ComplianceCheck      82 compliance checks
    row 49  IR-045  no register -> WorkOrder            24 work orders, 15 completed
    row 76  RD-010  no register -> OperatingRegime      10 operating regimes
    row 85  SO-013  ClosurePeriod -> AccessibleRoute    RTE-016 closed, Lift B out of service
    row 129 Q440    no register -> WorkOrder            WO-015 "Condensate drain clearance"

Row 86 is DELIBERATELY not among them. It spans four registers, and the prior decision that
no single one may claim it is pinned by
``test_register_reach.py::test_a_security_records_question_claims_no_register_at_all``. That
test names the real fix — what the decline SAYS — and it is
``test_a_decline_names_only_what_it_searched.py`` plus the wording change in
``capability_agent`` that landed with this one.

The counts are from read-only SPARQL SELECTs against the live repository on 2026-09-18 and
are recorded in the report, not asserted here — these tests are offline and read the schema
file, so they run in a parked tree exactly as CI sees it.

The vocabulary model is built the way ``scripts/register_reach.py`` builds it: the router's
own scoring functions, fed from the schema TTL through rdflib and from the cached instance
snapshot. Nothing here restates the router's logic.
"""

from __future__ import annotations

import importlib.util
import sys
from pathlib import Path

import pytest

pytestmark = pytest.mark.unit

REPO = Path(__file__).resolve().parents[1]
SCHEMA = REPO / "ontology" / "ontosage_schema.ttl"


def _harness():
    name = "_test_holds_it_harness"
    if name in sys.modules:
        return sys.modules[name]
    spec = importlib.util.spec_from_file_location(name, REPO / "scripts" / "register_reach.py")
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    spec.loader.exec_module(module)
    return module


@pytest.fixture(scope="module")
def reach():
    harness = _harness()
    return harness.Reach(harness.load_schema(SCHEMA), harness.load_snapshot())


#: (row, question, the register that holds the answer, a register that must ALSO be handed
#: over because the question equally names it).
ROWS = [
    (
        4,
        "What authority, prior-state evidence and independent checks are required before "
        "considering restoration after an erroneous suspension?",
        "AccessPermission",
        None,
    ),
    (
        9,
        "How do observed route lengths, waits and hand-offs compare with the workflow and "
        "adjacency assumptions used in the design?",
        "CirculationTime",
        None,
    ),
    (
        33,
        "Which entrances or route segments need a facilities inspection before the next "
        "high-footfall transition?",
        "AccessibleRoute",
        None,
    ),
    (
        44,
        "For the scheduled assurance activity, which required evidence is current, "
        "permissioned, traceable and reproducible, and which evidence is missing?",
        "ComplianceCheck",
        None,
    ),
    (
        49,
        "For each defect, what remedial scope and acceptance evidence were required, what "
        "was completed, and has the corrected condition remained stable?",
        "WorkOrder",
        None,
    ),
    (
        76,
        "To which buildings, systems and operating conditions could a result reasonably "
        "transfer, and which target settings remain unsupported?",
        "OperatingRegime",
        None,
    ),
    (
        85,
        "Which authorised public routes are interrupted by an official closure, unavailable "
        "door, lift fault or unverified segment?",
        "AccessibleRoute",
        # The question names the closures too, and the run-3 answer reported those three
        # correctly. Reaching the route register must not cost them.
        "ClosurePeriod",
    ),
    (129, "Which drains have needed jetting more than twice this year?", "WorkOrder", None),
]


@pytest.mark.parametrize("row,question,expected,second", ROWS, ids=[f"row{r[0]}" for r in ROWS])
def test_the_register_that_holds_the_answer_is_selected(reach, row, question, expected, second):
    outcome = reach.register(question)
    assert outcome["held"] == expected, (
        f"row {row} selects {outcome['held']!r}, not the register that holds its answer "
        f"({expected!r}). matched terms: {reach.matched_terms(question, expected)}"
    )
    if second:
        assert outcome["second"] == second, (
            f"row {row} lost {second!r}, which the question equally names — "
            f"second is {outcome['second']!r}"
        )


@pytest.mark.parametrize("row,question,expected,second", ROWS, ids=[f"row{r[0]}" for r in ROWS])
def test_no_row_is_declined_as_an_absent_register(reach, row, question, expected, second):
    """A decline naming an absent class is the same false absence wearing a name."""
    assert reach.register(question)["absent"] is None, f"row {row} would be declined"


# ── the terms that reach them are PHRASES, never bare words (BUG-729) ──────────────────

#: Terms added for the rows above. Each must be a phrase or a word that names its class on
#: its own — a narrowing to bare words lost four working answers once already.
ADDED = {
    "AccessPermission": ("erroneous suspension", "restore access", "access suspended"),
    "AccessibleRoute": ("public route", "route segment", "lift fault"),
    "CirculationTime": ("route length", "lift wait"),
    "ComplianceCheck": ("assurance activity",),
    "OperatingRegime": ("operating conditions",),
    "WorkOrder": ("remedial scope", "drain clearance", "jetting"),
}

#: Terms tried, read against the corpus, and REJECTED — pinned so they are not re-added
#: without re-reading the rows that rejected them. Both cost a working answer.
REJECTED = {
    "WorkOrder": ("defect", "defects"),
    "PatrolCheckpoint": ("security record", "security records"),
}


@pytest.mark.parametrize("class_name,terms", sorted(REJECTED.items()))
def test_the_rejected_vocabulary_stayed_rejected(reach, class_name, terms):
    declared = {
        term for record in reach.held if record.local_name == class_name for term in record.terms
    }
    present = [t for t in terms if t in declared]
    assert not present, (
        f"{class_name} declares {present}, which was measured taking answers away — see the "
        f"comment on the class in ontology/ontosage_schema.ttl"
    )


@pytest.mark.parametrize("class_name,terms", sorted(ADDED.items()))
def test_the_added_vocabulary_is_declared_on_the_class(reach, class_name, terms):
    """On the CLASS, so it works for any building that types its records with it."""
    declared = {
        term for record in reach.held if record.local_name == class_name for term in record.terms
    }
    assert declared, f"{class_name} holds no instances in the snapshot"
    missing = [t for t in terms if t not in declared]
    assert not missing, f"{class_name} does not declare {missing}"


def test_no_building_literal_entered_the_vocabulary(reach):
    """A term naming one building's rooms, floors or name would not travel (contract 3)."""
    forbidden = ("abacws", "cardiff", "senghennydd", "bldg1", "room 1.06", "room 0.01")
    for record in reach.held:
        for term in record.terms:
            assert not any(
                literal in term for literal in forbidden
            ), f"{record.local_name} declares a building literal: {term!r}"


def test_the_drain_question_reaches_the_maintenance_log_not_continuity(reach):
    """Row 129 was answered from `bldg:continuity/CP-001`; WO-015 is a drain clearance."""
    outcome = reach.register("Which drains have needed jetting more than twice this year?")
    assert outcome["held"] == "WorkOrder"
    assert outcome["second"] != "ContinuityProvision"


def test_the_security_records_question_does_not_land_on_work_orders(reach):
    """Row 86: a bare "defects" on WorkOrder claimed it, which is a wrong-register decline.

    The row's own fix is the decline's wording, not the selection — see the module docstring
    and test_register_reach.py::test_a_security_records_question_claims_no_register_at_all.
    """
    outcome = reach.register(
        "Which current Security records are incomplete, stale, duplicated or conflicting, "
        "and which operational decisions do those defects block?"
    )
    assert outcome["held"] is None, f"row 86 landed on {outcome['held']!r}"
    assert outcome["absent"] is None


def test_the_cost_view_question_keeps_its_cost_register(reach):
    """FP-010: "defects" moved a management-accounts question to the maintenance log."""
    outcome = reach.register(
        "Is the current management cost view decision-ready, and which unresolved defects "
        "could move the reported position above materiality?"
    )
    assert outcome["held"] == "CostLine"
