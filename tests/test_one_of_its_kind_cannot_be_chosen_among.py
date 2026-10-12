# -*- coding: utf-8 -*-
"""CAVEAT-1629: a modifier on a place the building holds ONE of describes it; it does not refute it.

"What is the CO2 in the glass atrium?" was answered "'glass atrium' does not exist in this
building" while "the atrium" read 750 ppm. The gate steps aside when the head exists and exactly
one same-kind place is suggested; several still get "which one?", and a head the building lacks
is still refused (BUG-189).
"""

from __future__ import annotations

import asyncio

import pytest

from orchestrator.services import referent_resolver as rr

pytestmark = pytest.mark.unit


def _resolver(found_terms, suggestions):
    r = rr.ReferentResolver.__new__(rr.ReferentResolver)

    async def _exists_terms(terms, namespace):
        return all(t in found_terms for t in terms)

    async def _suggest_terms(terms, namespace, kind):
        return list(suggestions)

    async def _holds_amenity_kind(head, namespace):
        return False

    r._exists_terms = _exists_terms
    r._exists_whole_words = _exists_terms
    r._suggest_terms = _suggest_terms
    r._holds_amenity_kind = _holds_amenity_kind
    r._typed_clarification = lambda typed, sugg, name, for_admin=False: "clarify"
    return r


def _typed(question):
    t = rr.detect_typed_referent(question)
    assert t is not None
    return t


def _resolve(r, question):
    return asyncio.run(r._resolve_typed(_typed(question), "http://x#", "B"))


def test_a_modifier_on_the_only_atrium_steps_aside():
    r = _resolver({"atrium"}, ["Atrium (Room 1.04)"])
    got = _resolve(r, "What is the CO2 in the glass atrium?")
    assert got.status == rr.STEPPED_ASIDE


def test_a_modifier_among_several_still_asks_which():
    r = _resolver({"corridor"}, ["Corridor 1", "Corridor 2", "Corridor 3"])
    got = _resolve(r, "What is the noise in the public corridor?")
    assert got.status == rr.NOT_FOUND


def test_a_head_the_building_lacks_is_still_refused():
    r = _resolver(set(), [])
    got = _resolve(r, "How warm is the swimming pool?")
    assert got.status == rr.NOT_FOUND


def _with_label(r, label):
    async def _label_of(local, namespace):
        return label

    r._label_of = _label_of
    return r


def test_the_suggestion_is_judged_by_its_label_not_its_iri():
    # Live, the one suggestion is the local name "Room1.04"; its label says Atrium.
    r = _with_label(_resolver({"atrium"}, ["Room1.04"]), "Room 1.04 — Common Area / Atrium")
    assert _resolve(r, "What is the CO2 in the glass atrium?").status == rr.STEPPED_ASIDE


def test_a_contrasting_modifier_still_asks_which():
    r = _with_label(_resolver({"atrium"}, ["Room1.04"]), "Room 1.04 — Common Area / Atrium")
    assert _resolve(r, "What is the CO2 in the west atrium?").status == rr.NOT_FOUND


def test_a_one_suggestion_without_the_head_word_is_not_stepped_aside():
    r = _with_label(_resolver({"atrium"}, ["Room1.04"]), "Room 1.04 — Seminar Room")
    assert _resolve(r, "What is the CO2 in the glass atrium?").status == rr.NOT_FOUND
