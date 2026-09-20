# -*- coding: utf-8 -*-
"""'Is there step-free access to the first floor?' was answered from a security sensor (BUG-830).

The building holds surveyed step-free routes (ontosage:AccessibleRoute: entrance, whether the way is
step-free, its lift, its doors). The question named none of that register's phrases -- "step-free
route", "step-free entrance", "wheelchair access" -- so no register was selected, the SPARQL lane
generated its own query, and it answered from an Access READER because it contains the word
"access". The reader is a door sensor; it says nothing about steps.

The fix is vocabulary, and it is measured, not guessed. The bare phrase "step-free access" moved
eleven of the 2,960 catalogue questions, nine of them AWAY from the register that chooses rooms
("which bookable room has step-free access and AV?"). "step-free access TO" moved none, passes the
124 guard questions, and is what a journey sounds like. These tests pin both halves: the question
that should reach the register does, and the one that must not, does not.
"""

from pathlib import Path

import pytest

pytestmark = pytest.mark.unit

_SCHEMA = Path(__file__).resolve().parents[1] / "ontology" / "ontosage_schema.ttl"
_ONTO = "http://ontosage.org/capabilities#"


def _terms(local: str):
    from rdflib import Graph, Namespace, URIRef

    g = Graph()
    g.parse(str(_SCHEMA), format="turtle")
    o = Namespace(_ONTO)
    lays = sorted({str(v) for v in g.objects(URIRef(_ONTO + local), o.layTerms)})
    return lays


def _classes():
    from orchestrator.services import record_registry as rr

    def cls(name, label, lays, n=5):
        return rr.RecordClass(name, label, n, rr._terms_for(name, label, "|".join(lays)))

    return rr, [
        cls("AccessibleRoute", "Accessible route", _terms("AccessibleRoute"), 16),
        cls("WorkspaceProfile", "Workspace profile", _terms("WorkspaceProfile"), 20),
        cls("AccessEventPlaceholder", "Access event", ["access reader", "badge swipe"], 10),
    ]


def test_the_register_declares_step_free_access_to_a_place_as_its_own_phrase():
    lays = {t.lower() for t in _terms("AccessibleRoute")}
    assert "step-free access to" in lays and "step free access to" in lays


def test_the_bare_phrase_is_not_declared_because_it_pulled_room_choices_away_from_their_register():
    lays = {t.lower() for t in _terms("AccessibleRoute")}
    assert "step-free access" not in lays and "step free access" not in lays


@pytest.mark.parametrize(
    "question",
    [
        "Is there step-free access to the first floor?",
        "Is there step free access to floor 3?",
        "Is there step-free access to the library from the entrance?",
    ],
)
def test_step_free_access_to_a_place_selects_the_accessible_route_register(question):
    rr, classes = _classes()
    held = rr.held_record_class(question, classes)
    assert held is not None and held.local_name == "AccessibleRoute"


def test_a_room_choice_that_mentions_step_free_access_does_not_select_it():
    rr, classes = _classes()
    held = rr.held_record_class(
        "Which bookable room has step-free access, a working display and quiet acoustics?",
        classes,
    )
    assert held is None or held.local_name != "AccessibleRoute"
