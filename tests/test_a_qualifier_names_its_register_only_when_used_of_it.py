# -*- coding: utf-8 -*-
"""BUG-545: "approved" is an approval question only when something is being asked approved.

Stakeholder run #1 (2026-09-15), through Open WebUI as the demo admin:

* "Which systems started late or stopped late against today's approved schedule?" was
  answered from the approvals register — "APR-010 ... 1 day late", an approval date read as
  a plant start time.
* "Which occupied zones lack confirmed fire-warden or marshal coverage?" was answered "none
  of the occupied zones have coverage": the absence of wardens in the APPROVALS register,
  stated as a fact about fire safety.

The words are declared by the TBox as qualifiers (ontosage:qualifierTerms); grammar decides
whether one is describing the next noun or being asked about.
"""

import re
from pathlib import Path

import pytest

from orchestrator.services.record_registry import RecordClass, rank_record_classes

pytestmark = pytest.mark.unit

APPROVAL = RecordClass(
    "ApprovalRecord", "Approval and evidence record", 32,
    ("approval", "approvals", "approved", "confirmed", "evidence", "evidenced", "verified"),
    qualifiers=("approved", "confirmed", "evidenced", "verified"),
)
REGIME = RecordClass("OperatingRegime", "Operating regime", 6, ("operating regime", "schedule"))
ROUTE = RecordClass("AccessibleRoute", "Accessible route", 16, ("accessible route", "route"))


def _top(q):
    ranked = rank_record_classes(q, [APPROVAL, REGIME, ROUTE])
    return ranked[0][1].local_name if ranked else None


@pytest.mark.parametrize(
    "question, expected",
    [
        ("Which systems started late against today's approved schedule?", "OperatingRegime"),
        ("Which occupied zones lack confirmed fire-warden coverage?", None),
        ("Which services have a verified alternative location and capacity?", None),
        ("Are there heavy doors on my verified route?", "AccessibleRoute"),
    ],
)
def test_a_qualifier_describing_another_noun_is_not_evidence(question, expected):
    assert _top(question) == expected


@pytest.mark.parametrize(
    "question",
    [
        "Is this route approved?",
        "Is the route approved and what evidence supports it?",
        "Who approved the change?",
        "Was it verified by an engineer?",
        "Which permission groups are orphaned because no owner can be evidenced?",
        "Has the lab been approved for teaching use",
    ],
)
def test_a_qualifier_asked_about_still_names_its_register(question):
    assert _top(question) == "ApprovalRecord"


def test_a_noun_lay_term_is_unaffected():
    assert _top("show me the approvals due for review") == "ApprovalRecord"


def test_a_class_without_declared_qualifiers_scores_as_before():
    plain = RecordClass("Booking", "Room booking", 16, ("booked", "booking"))
    ranked = rank_record_classes("which booked rooms are empty?", [plain])
    assert ranked and ranked[0][1].local_name == "Booking"


def _schema():
    return (Path(__file__).resolve().parent.parent / "ontology" / "ontosage_schema.ttl").read_text(
        encoding="utf-8"
    )


def test_the_tbox_declares_the_qualifiers_and_the_property():
    ttl = _schema()
    assert re.search(r"ontosage:qualifierTerms a owl:DatatypeProperty", ttl)
    block = ttl[ttl.index("ontosage:ApprovalRecord ontosage:layTerms"):]
    block = block[: block.index(" .\n")]
    for word in ("approved", "confirmed", "verified", "evidenced"):
        assert f'"{word}"' in block.split("qualifierTerms", 1)[1]


def test_the_event_agenda_is_not_claimed_by_a_bare_activities():
    ttl = _schema()
    block = ttl[ttl.index("ontosage:EventActivity ontosage:layTerms"):]
    block = block[: block.index(" .\n")]
    assert '"activity"' not in block and '"activities"' not in block
