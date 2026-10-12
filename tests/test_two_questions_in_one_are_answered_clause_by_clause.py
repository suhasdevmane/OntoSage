# -*- coding: utf-8 -*-
"""CAVEAT-1618: "Which floors have accessible toilets and where is baby changing?" is two questions.

No topic was the subject of the whole sentence, so the capability lane declined while holding
both. Clause by clause each topic is judged against the question it answers -- but only when
EVERY clause has a topic it is about (measured: 111 bank moves without that rule, 5 with it).
"""

from __future__ import annotations

from types import SimpleNamespace

import pytest

from orchestrator.services import capability_graph_resolver as cgr

pytestmark = pytest.mark.unit


def _fact(label, terms):
    return SimpleNamespace(label=label, lay_terms=list(terms), terms=list(terms), kind="Amenity")


def test_the_split_points_are_clause_joins_only():
    split = [
        c.strip()
        for c in cgr._CLAUSE_SPLIT_RE.split("Which floors have toilets and where is baby changing?")
    ]
    assert split == ["Which floors have toilets", "where is baby changing?"]
    assert len(cgr._CLAUSE_SPLIT_RE.split("Where are the toilets and showers?")) == 1
    assert len(cgr._CLAUSE_SPLIT_RE.split("Where is the cafe? When does it open?")) == 2


def test_a_half_question_is_not_answered_as_whole(monkeypatch):
    toilets = _fact("Toilets", ["toilet", "toilets"])
    monkeypatch.setattr(
        cgr,
        "topic_is_the_subject",
        lambda q, f: "toilet" in q.lower() and "rain" not in q.lower(),
    )
    monkeypatch.setattr(cgr, "_subject_leftover", lambda q, f: [])
    got = cgr.subject_facts("Where are the toilets and will it rain tomorrow?", [toilets])
    assert got == []


def test_two_answerable_halves_are_both_kept(monkeypatch):
    toilets = _fact("Toilets", ["toilet"])
    changing = _fact("Baby changing", ["baby changing"])

    def about(q, f):
        ql = q.lower()
        whole = "toilet" in ql and "baby" in ql
        if whole:
            return False
        return (f is toilets and "toilet" in ql) or (f is changing and "baby" in ql)

    monkeypatch.setattr(cgr, "topic_is_the_subject", about)
    monkeypatch.setattr(cgr, "_subject_leftover", lambda q, f: [])
    got = cgr.subject_facts(
        "Which floors have accessible toilets and where is baby changing?", [toilets, changing]
    )
    assert got == [toilets, changing]
