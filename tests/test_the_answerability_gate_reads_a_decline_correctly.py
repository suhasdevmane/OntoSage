# -*- coding: utf-8 -*-
"""The gate that protects the evidence pack must itself be right about what it reads.

`scripts/regression_answerability.py` re-asks every answerable question in the shipped pack and
compares the KIND of reply. Its classifier decides what counts as a decline, and it was wrong
twice in one day — both times in the direction that HIDES a regression, by scoring a decline as
an answer:

* "I couldn't answer that ABOUT **Room2.01** FROM Abacws Building's records" — the referent is
  inserted into the middle of the fixed marker, so no substring spans it (BUG-876).
* "there is no air-pressure sensor INSTALLED IN Room 2.01" — the same decline the marker spells
  "...sensor DATA available for room 2.01".

And the fix for the second was wrong twice before it was right, both times in the OTHER
direction — scoring a real answer as a decline, which manufactures regressions and gets the gate
switched off:

* `there (?:is|are) no .{0,40} sensors?` also matches "there are no GAPS IN SENSOR COVERAGE",
  which is a completeness answer asserting the opposite.
* a rule keyed on `installed` alone matches the label "CO2 Level Sensor installed-node 3.07".

This file pins all four.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from scripts.regression_answerability import classify

pytestmark = pytest.mark.unit

REPO = Path(__file__).resolve().parent.parent


# ── declines the gate must recognise ─────────────────────────────────────────────────


@pytest.mark.parametrize(
    "answer",
    [
        "I couldn't answer that from Abacws Building's records.",
        # the referent inserted into the middle of the marker (BUG-876)
        "I couldn't answer that about **Room2.01** from Abacws Building's records.",
        # a non-breaking hyphen, which a hand-written pattern does not contain
        "I’m sorry, but there is no air‑pressure sensor installed in Room 2.01, "
        "so I can’t provide a current pressure reading.",
        "There is no CO2 sensor fitted in that room.",
        "I couldn't tie that question to a reading I can give you.",
    ],
)
def test_a_decline_is_never_scored_as_an_answer(answer):
    """The direction that HIDES a regression, which is the worse one for a gate."""
    assert classify(answer) == "declined", answer[:70]


# ── and answers it must not mistake for declines ─────────────────────────────────────


@pytest.mark.parametrize(
    "answer",
    [
        # a completeness answer asserting the OPPOSITE of an absence
        "All sensors are represented, so there are no gaps in sensor coverage, "
        "and the mean is 792 ppm across 50 floor-3 sensors.",
        # a label that merely contains the word "installed"
        "Highest CO2 reading: 792 ppm from CO2 Level Sensor installed-node 3.07.",
        # a real ranking
        "**Best match: Room 3.50** (floor Floor3, score 0.3761 out of 1).",
        # an aggregate that happens to mention sensors with no readings
        "Across the building CO2 averages 750 ppm from 280 sensors; 0 sensors without readings.",
    ],
)
def test_a_substantive_answer_is_never_scored_as_a_decline(answer):
    """The direction that MANUFACTURES a regression, which gets the gate switched off."""
    assert classify(answer) == "answered", answer[:70]


def test_a_refusal_is_its_own_kind_and_not_a_decline():
    """A refusal is the system declining ON PURPOSE; counting it as a regression would be wrong."""
    assert classify("I can't answer that — this building never tracks individuals.") == "refused"


def test_an_empty_reply_is_its_own_kind():
    assert classify("") == "empty"
    assert classify("   \n ") == "empty"


# ── the shipped baseline must not move under a classifier change ─────────────────────


def test_every_stored_pack_answer_still_classifies_as_recorded():
    """The pack's expected_kind is DERIVED by this classifier from the stored answer.

    So a classifier change silently rewrites the baseline the gate compares against. This pins
    the distribution: if a change moves one of these, that is a decision to take deliberately,
    not a side effect to discover during a release.
    """
    pack = REPO / "docs" / "supervisor_evidence_pack" / "answers.jsonl"
    if not pack.is_file():
        pytest.skip("evidence pack not present")
    rows = [
        json.loads(line)
        for line in pack.read_text(encoding="utf-8").splitlines()
        if line.strip()
    ]
    kinds = {}
    for r in rows:
        kind = classify(r.get("answer") or "")
        kinds[kind] = kinds.get(kind, 0) + 1
    # 73 stored answers. This is the distribution BEFORE the two classifier fixes of
    # 2026-09-23 and after them: both were checked against every stored answer, and the
    # narrow forms leave all 73 exactly as recorded. An intermediate, broader pattern moved
    # two of them (57/14 -> 55/16) and was rejected for it.
    assert kinds == {"answered": 57, "declined": 14, "refused": 2}, kinds
    assert sum(kinds.values()) == 73


def test_the_third_wording_of_the_same_decline_in_one_day():
    """"I don't have any air-pressure data for Room 2.01", then the room's OTHER sensors.

    The asked quantity is declined; offering what the building DOES have does not make it an
    answer to the question. Three phrasings of one decline appeared in a single day — see
    CAVEAT-887 on why a marker list is the wrong long-term instrument for this.
    """
    answer = (
        "I don\u2019t have any air\u2011pressure data for Room\u202f2.01.\n\n"
        "- **Air Temperature Sensor installed-node 2.01**: 23.1\u202f\u00b0C\n"
        "- **Room 2.01 illuminance**: 820 lux\n"
    )
    assert classify(answer) == "declined"


def test_offering_alternatives_does_not_turn_a_decline_into_an_answer():
    for answer in (
        "I don't have any radiation data for the atrium. The atrium does have CO2 and noise.",
        "There is no air pressure sensor installed in Room 2.01. Temperature is 23.1 C.",
    ):
        assert classify(answer) == "declined", answer[:60]
