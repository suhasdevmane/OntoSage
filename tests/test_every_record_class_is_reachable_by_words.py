# -*- coding: utf-8 -*-
"""A register nobody can name is a register nobody can reach.

`_terms_for` deliberately refuses to derive terms from PART of a phrase. That rule is
right — a bare "room" lifted from the label "Room booking" pulled every wayfinding
question into the register lane, and two more defects came the same way. But the rule
only works because of a promise made in its own docstring:

    "Short forms are not lost by this, because they are declared: the TBox lists
     'permit', 'booking', 'condition' and the rest as layTerms. That is the design."

The guard and the promise are two halves of one mechanism, and nothing checked that the
second half was kept. Five classes — AssetStatus, ClosurePeriod, AnomalyEvent,
AccessEvent, AlarmEvent — were declared as record classes and given no lay terms at all,
so each was reachable only by its formal class name. 41 questions in the 2,960-question
capture use their ordinary vocabulary.

This is the check that keeps the promise. It is deliberately a check on the ONTOLOGY, not
on code: a new register is three files and none of them is Python, so the thing that can
be forgotten is a TTL statement.
"""

import re
from pathlib import Path

import pytest

pytestmark = pytest.mark.unit

REPO = Path(__file__).resolve().parent.parent
SCHEMA = REPO / "ontology" / "ontosage_schema.ttl"


def _schema() -> str:
    return SCHEMA.read_text(encoding="utf-8")


def _record_classes(ttl: str) -> set:
    """Classes beneath a record root, however the declaration is ORDERED.

    The first version required ``rdfs:subClassOf`` to follow the class name immediately.
    ``ontosage:ServiceSchedule`` writes ``a owl:Class ;`` first and ``rdfs:subClassOf`` on
    the next line, so it was invisible here — and it carried no lay terms at all, which a
    different test caught and this one did not.

    A parser that silently sees fewer things than exist makes every assertion built on it
    weaker than it appears. That mistake has now been made twice in this file's history,
    which is why the discovery is checked by its own test below rather than trusted.
    """
    found = set()
    for block in re.split(r"\n(?=ontosage:\w+\s)", ttl):
        m = re.match(r"ontosage:(\w+)\s", block)
        if not m:
            continue
        head = block.split("\n\n", 1)[0]
        if re.search(r"rdfs:subClassOf\s+ontosage:(?:Record|IntervalRecord)\b", head):
            found.add(m.group(1))
    return found


def _declared_terms(ttl: str) -> dict:
    """Class -> its declared lay terms, read as standalone statements."""
    out = {}
    for m in re.finditer(r"ontosage:(\w+)\s+ontosage:layTerms\s+((?:[^.]|\.\d)*?)\s*\.\s*\n", ttl):
        out[m.group(1)] = [t.strip().lower() for t in re.findall(r'"([^"]+)"', m.group(2))]
    return out


def test_the_schema_declares_record_classes_at_all():
    """Guards the parser itself: a regex that matches nothing would pass every test below."""
    assert len(_record_classes(_schema())) >= 20


def test_every_record_class_declares_lay_terms():
    ttl = _schema()
    declared = _declared_terms(ttl)
    missing = sorted(c for c in _record_classes(ttl) if not declared.get(c))
    assert not missing, (
        f"these record classes declare no ontosage:layTerms: {missing}. Nothing is derived "
        f"from part of a phrase, so each is reachable only by its full formal name — a "
        f"question using ordinary words for it reaches the document lane instead."
    )


def test_no_lay_term_is_a_bare_generic_head_word():
    """The defect the derivation rule was written to stop, arriving by the declared route.

    Declaring "room" by hand does exactly what deriving it did.
    """
    banned = {"room", "rooms", "work", "roof", "area", "space", "building", "floor", "check"}
    offences = {
        cls: sorted(set(terms) & banned) for cls, terms in _declared_terms(_schema()).items()
    }
    offences = {c: t for c, t in offences.items() if t}
    assert not offences, (
        f"generic head words declared as lay terms: {offences}. These match nearly every "
        f"question and pull unrelated lanes into the register lane."
    )


#: Lay terms that two registers both legitimately claim. English is ambiguous — a
#: "lecture" really is both a published public event and a timetabled teaching session,
#: and a "certificate" really is both a compliance artefact and an approval record.
#: Forbidding the overlap would mean deleting a term people actually use.
#:
#: What must not happen is an overlap nobody looked at. `held_record_class` breaks a score
#: tie on class name, so an unreviewed shared term routes alphabetically — deterministic,
#: and arbitrary. Pinning the known set means a NEW clash fails here and gets a decision.
KNOWN_AMBIGUOUS = {
    "my shift": {"CleaningTask", "PatrolCheckpoint"},
    "authorisation": {"ApprovalRecord", "CompetencyRecord"},
    "overdue check": {"ComplianceCheck", "PatrolCheckpoint"},
    "certificate": {"ApprovalRecord", "ComplianceCheck"},
    "ticket": {"PublicEvent", "WorkOrder"},
    "lecture": {"PublicEvent", "TimetabledSession"},
}


def test_no_unreviewed_lay_term_is_claimed_by_two_registers():
    declared = _declared_terms(_schema())
    record = _record_classes(_schema())
    owners = {}
    for cls, terms in declared.items():
        if cls not in record:
            continue
        for t in terms:
            owners.setdefault(t, set()).add(cls)
    shared = {t: cs for t, cs in owners.items() if len(cs) > 1}
    new = {t: sorted(cs) for t, cs in shared.items() if KNOWN_AMBIGUOUS.get(t) != cs}
    assert not new, (
        f"lay terms claimed by more than one record class and not reviewed: {new}. "
        f"A tie routes alphabetically, so decide which register owns the term — or add it "
        f"to KNOWN_AMBIGUOUS with the reason it is genuinely both."
    )


def test_the_ambiguity_list_does_not_outlive_its_terms():
    """A pinned exception for a term nobody declares any more is stale documentation."""
    declared = _declared_terms(_schema())
    all_terms = {t for terms in declared.values() for t in terms}
    stale = sorted(t for t in KNOWN_AMBIGUOUS if t not in all_terms)
    assert not stale, f"KNOWN_AMBIGUOUS lists terms no class declares: {stale}"
