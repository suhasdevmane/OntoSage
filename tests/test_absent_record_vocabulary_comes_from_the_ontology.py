# -*- coding: utf-8 -*-
"""A Python tuple decided which records a building could be asked about (W3-4).

`record_registry`'s own module docstring names this sin:

    IT USED TO BE THE ONLY SOURCE, and that was a contract-2 violation with teeth:
    adding ontosage:CleaningTask, ontosage:PublicEvent and ontosage:AccessPermission to
    the TBox, with lay terms, with documents lifted into 62 instances, changed nothing —
    every question about them still reached the document lane … because a Python tuple
    decided what the building could be asked about.

That was fixed for the HELD path, via `_discover_record_classes`. The ABSENT path was left
committing exactly the same sin: `_ALL_CLASS_TERMS` was seeded from
`_FALLBACK_RECORD_CLASSES`, `load_lay_terms` asked the graph only about those names, and
any class outside the tuple was skipped with `if local not in _ALL_CLASS_TERMS: continue`.

MEASURED ON THE LIVE BUILDING, before the fix:

    discovered record classes ....... 40
    absent-class vocabulary ......... the fallback tuple only

    "Have there been any alarms this week?"  held=None   absent=None
    "Show me the anomaly events."           held=PublicEvent  absent=None
    "What are our sustainability targets?"  held=None   absent=None

`ontosage:AlarmEvent`, `AnomalyEvent` and `AccessEvent` are declared, carry 8-10 lay terms
each, are discovered as record classes, and hold no instances — so they could not be named
as absent, and the questions fell to the document lane. "Show me the anomaly events"
matched **PublicEvent**, because "events" is one of its lay terms.

AND ONE CLASS WAS INVISIBLE WITH DATA IN IT
-------------------------------------------
`ontosage:SustainabilityTarget` was declared as a bare `owl:Class` with no
`rdfs:subClassOf`. Discovery walks `rdfs:subClassOf+` from Record and IntervalRecord, so it
found everything except this — while five instances sat in the graph with fourteen declared
lay terms. Data present, question unanswerable. Fixed in the TBox (contract rule 2), as
`rdfs:subClassOf ontosage:Record`: its instances carry recordStatus / recordOwner /
recordVersion / recordId, which is a standing record, not something with an interval
lifecycle like a booking or an alarm.
"""

from __future__ import annotations

import inspect
from pathlib import Path

import pytest

pytestmark = pytest.mark.unit

from orchestrator.services import record_registry as rr  # noqa: E402


def test_the_vocabulary_is_built_from_discovery_not_the_fallback_tuple():
    src = inspect.getsource(rr.load_lay_terms)
    assert "_discover_record_classes()" in src, (
        "the absent-class vocabulary is still seeded from the hardcoded tuple, so a class "
        "the ontology defines cannot be named as missing"
    )


def test_the_fallback_is_a_union_not_a_replacement():
    """Discovery can degrade to the fallback on a graph hiccup.

    Losing the whole vocabulary then would be worse than an over-broad one, so the two
    are unioned rather than swapped.
    """
    src = inspect.getsource(rr.load_lay_terms)
    assert "_FALLBACK_RECORD_CLASSES" in src
    assert "|" in src or "union" in src.lower()


def test_the_lay_term_query_asks_about_the_discovered_classes():
    """Asking only about the tuple is the same bug one line further down."""
    src = inspect.getsource(rr.load_lay_terms)
    values = src.index("values = ")
    names = src.index("names = tuple(")
    assert names < values, "the SPARQL VALUES clause is built before the discovered names"
    assert 'f"o:{c}" for c in names' in src


def test_a_class_outside_the_tuple_is_no_longer_skipped():
    """`if local not in _ALL_CLASS_TERMS: continue` was the skip; the seed now covers it."""
    src = inspect.getsource(rr.load_lay_terms)
    seed = src.index("_ALL_CLASS_TERMS.setdefault")
    skip = src.index("if local not in _ALL_CLASS_TERMS")
    assert seed < skip, (
        "the vocabulary is seeded after the skip check, so a discovered class is still "
        "dropped before its lay terms are read"
    )


# ── the TBox half ───────────────────────────────────────────────────────────

SCHEMA = Path("ontology/ontosage_schema.ttl")


def test_sustainability_target_is_a_record_class():
    """Five instances were unreachable because the class had no parent."""
    src = SCHEMA.read_text(encoding="utf-8")
    decl = [ln for ln in src.splitlines() if ln.startswith("ontosage:SustainabilityTarget ")]
    assert decl, "the declaration moved; this test can no longer see it"
    assert "rdfs:subClassOf ontosage:Record" in decl[0], (
        "SustainabilityTarget has no Record parent again, so `_discover_record_classes` "
        "cannot find it and its instances are unaskable"
    )


def test_every_record_class_in_the_tbox_has_a_discoverable_parent():
    """The class-with-no-parent shape, caught for the next one rather than this one.

    Discovery walks `rdfs:subClassOf+` from Record and IntervalRecord. A class declared
    with neither is invisible no matter how many instances or lay terms it has — a silent
    failure, because nothing errors and the question simply goes somewhere else.

    PARSED, not grepped. The first version of this test matched `rdfs:subClassOf` only on
    the class's own opening line and reported `ontosage:ServiceSchedule` as an orphan — it
    declares its parent on the NEXT line and is perfectly reachable. A guard that cries
    wolf about correct data is worse than no guard, so this one reads the graph the way
    the code does.
    """
    from rdflib import RDFS, Graph, URIRef

    NS = "http://ontosage.org/capabilities#"
    g = Graph()
    g.parse(str(SCHEMA), format="turtle")

    roots = {URIRef(NS + "Record"), URIRef(NS + "IntervalRecord")}

    def reaches_a_root(cls, seen=None):
        seen = seen or set()
        if cls in roots:
            return True
        if cls in seen:
            return False
        seen.add(cls)
        return any(reaches_a_root(p, seen) for p in g.objects(cls, RDFS.subClassOf))

    lay = URIRef(NS + "layTerms")
    orphans = sorted(
        str(c).rsplit("#", 1)[-1]
        for c in {s for s, _, _ in g.triples((None, lay, None))}
        if str(c).startswith(NS) and not reaches_a_root(c)
    )
    assert not orphans, (
        "these carry lay terms but no path to Record or IntervalRecord, so record "
        "discovery cannot reach them and questions about them go elsewhere silently: "
        + ", ".join(orphans)
    )
