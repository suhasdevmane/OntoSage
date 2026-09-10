# -*- coding: utf-8 -*-
"""A short term on an EMPTY class must not beat a long one on a class with data (TODO-490).

The problem to solve was small: `AlarmEvent` and `AccessEvent` declared only compound
phrases — "alarm activation", "false alarm", "access event", "entry log" — so the words
people actually type missed entirely. "Have there been any alarms this week?" and "Who
accessed the server room?" matched neither a held class nor an absent one and fell through
to the document lane.

The obvious fix is a bare "alarm". The obvious fix was a trap.

`ontosage:FireSafetyAsset` declares "fire alarm", holds 30 instances, and answers "when was
the fire alarm last tested?" today — it is a passing regression case. `absent_record_class`
returned the FIRST absent class whose vocabulary matched, in dict order, so a bare "alarm"
on an empty class would have claimed that question and produced "this building holds no
alarm event records" for a question the building answers.

So the ordering was fixed first, and the terms added second:

  * the LONGEST matching term wins, so "fire alarm" beats "alarm"
  * a HELD class wins ties, because a decline costs a real answer while a held class
    merely routes to data that exists and is checkable
  * two absent classes tie on their name, never on dict order, so a question resolves the
    same way twice

MEASURED before and after across all 50 regression-probe questions plus 7 written for this
change: **3 of 57 moved**, and all three were the intended ones. No probe question changed.

    Have there been any alarms this week?   absent: None -> AlarmEvent
    Who accessed the server room?           absent: None -> AccessEvent
    Show me the access log for yesterday.   absent: None -> AccessEvent

    When was the fire alarm last tested?    held: FireSafetyAsset, absent: None  (unmoved)
"""

from __future__ import annotations

import re

import pytest

pytestmark = pytest.mark.unit

from orchestrator.services.record_registry import (  # noqa: E402
    RecordClass,
    absent_record_class,
)


def _held(name: str, *terms: str) -> RecordClass:
    return RecordClass(local_name=name, label=name, instances=30, terms=tuple(terms))


FIRE = _held("FireSafetyAsset", "fire alarm", "extinguisher", "smoke detector")


@pytest.fixture(autouse=True)
def _vocabulary(monkeypatch):
    """A small, explicit vocabulary — the real one is loaded from the graph."""
    from orchestrator.services import record_registry as rr

    monkeypatch.setattr(
        rr,
        "_ALL_CLASS_TERMS",
        {
            "AlarmEvent": ("alarm", "alarms", "alarm event", "false alarm"),
            "AccessEvent": ("accessed", "access log", "access event", "tailgating"),
            "AnomalyEvent": ("anomaly", "anomalies", "unusual reading"),
        },
    )


def test_a_held_class_keeps_its_question():
    """The whole reason the ordering had to change before the terms could be added."""
    assert absent_record_class("When was the fire alarm last tested?", [FIRE]) is None


def test_the_absent_class_still_claims_its_own_question():
    assert absent_record_class("Have there been any alarms this week?", [FIRE]) == "AlarmEvent"


def test_the_longest_match_wins_not_the_first():
    """Dict order used to decide this, which is not a decision at all."""
    assert absent_record_class("Was that an unusual reading?", [FIRE]) == "AnomalyEvent"


def test_the_longer_term_wins_between_two_absent_classes():
    """ "anomaly" (7) beats "alarm" (5) — length, not declaration order."""
    assert absent_record_class("alarm and anomaly", [FIRE]) == "AnomalyEvent"


def test_a_genuine_tie_breaks_on_the_name(monkeypatch):
    """Two absent classes matching terms of EQUAL length must not depend on dict order.

    Built deliberately: "alarm" and "badge" are both five characters, so nothing but the
    tie-break separates them. Without it the winner is whichever the dict happened to
    yield first, and the same question routes two ways on two runs.
    """
    from orchestrator.services import record_registry as rr

    monkeypatch.setattr(
        rr,
        "_ALL_CLASS_TERMS",
        {"ZebraEvent": ("badge",), "AlarmEvent": ("alarm",)},
    )
    q = "badge and alarm"
    assert absent_record_class(q, [FIRE]) == "AlarmEvent"

    # And the other insertion order gives the same answer.
    monkeypatch.setattr(
        rr,
        "_ALL_CLASS_TERMS",
        {"AlarmEvent": ("alarm",), "ZebraEvent": ("badge",)},
    )
    assert absent_record_class(q, [FIRE]) == "AlarmEvent"


def test_a_held_class_wins_a_TIE_not_just_a_longer_match():
    """The asymmetry: a wrong decline costs a real answer; a wrong route costs a lookup."""
    tied = _held("Something", "alarm")
    assert absent_record_class("any alarm here", [tied]) is None


def test_a_question_about_nothing_claims_nothing():
    for q in ("Where is the nearest toilet?", "How warm is room 5.01?", ""):
        assert absent_record_class(q, [FIRE]) is None


def test_matching_is_on_whole_words():
    """'alarm' must not fire inside 'alarming' or a longer unrelated word."""
    assert absent_record_class("that is an alarming trend", [FIRE]) is None


# ── the declared terms themselves ───────────────────────────────────────────

SCHEMA = "ontology/ontosage_schema.ttl"


def _terms(cls: str) -> set:
    from pathlib import Path

    src = Path(SCHEMA).read_text(encoding="utf-8")
    m = re.search(rf"^ontosage:{cls} ontosage:layTerms(.*?)\.\s*$", src, re.M | re.S)
    assert m, f"{cls} declares no lay terms"
    return {t.lower() for t in re.findall(r'"([^"]+)"', m.group(1))}


@pytest.mark.parametrize("word", ["alarm", "alarms"])
def test_the_bare_alarm_forms_are_declared(word):
    assert word in _terms("AlarmEvent")


@pytest.mark.parametrize("word", ["accessed", "access log", "who entered"])
def test_the_colloquial_access_forms_are_declared(word):
    assert word in _terms("AccessEvent")


def test_fire_alarm_still_belongs_to_the_asset_class():
    """If this ever moves, the specificity rule stops protecting the question."""
    assert "fire alarm" in _terms("FireSafetyAsset")
    assert "fire alarm" not in _terms("AlarmEvent")
