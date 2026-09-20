# -*- coding: utf-8 -*-
"""A passage that ANSWERS must not be rejected, and a decline must stand alone (2D-16 wave 4).

Measured live, the gate was costing more than it saved in the other direction:

* *"is there a muster point outside the building?"* got generic fire prose. Three chunks say
  "Proceed to the assembly point on Senghennydd Road" and the gate REJECTED every one -- the
  question says muster, the building says assembly, so they shared only "point" -- while admitting
  a spill row that happened to contain "outside".
* *"Can I get tips to improve sustainability in my workspace?"* declined and then listed workspace
  kinds and counts: a tally after a decline, which reads as though it were the answer after all.

So: ordinary English synonyms are matched, the best WINDOW inside a passage is scored rather than
the whole passage, hits are RANKED by how tightly they answer, and a decline is the whole answer.
"""

from __future__ import annotations

import pytest

from orchestrator.services import absence_wording as aw
from orchestrator.services import passage_relevance as pr

pytestmark = pytest.mark.unit

MUSTER_Q = "is there a muster point outside the building?"
ASSEMBLY = "In an evacuation, proceed to the assembly point on Senghennydd Road and report to your floor warden."
SPILL_ROW = (
    "| spill outside a laboratory | Not met | RES-EV-2026-0909 | false | Confirmed | CF-12 |"
)


def test_the_sentence_that_answers_is_no_longer_rejected():
    verdict = pr.assess(MUSTER_Q, ASSEMBLY, doc_name="fire_safety")
    assert verdict.relevant, "the passage naming the assembly point must be allowed to answer"
    assert "muster" in verdict.shared


def test_the_answering_passage_outranks_a_row_that_shares_a_word_by_accident():
    hits = [
        {"doc_name": "coordination_function_register", "text": SPILL_ROW, "score": 0.62},
        {"doc_name": "fire_safety", "text": ASSEMBLY, "score": 0.58},
    ]
    kept, _dropped = pr.relevant_hits(MUSTER_Q, hits)
    assert kept and kept[0]["text"] == ASSEMBLY, "the passage that answers must lead"


@pytest.mark.parametrize(
    "question,passage",
    [
        ("where is the muster point?", "Assembly point A is on the north side."),
        ("is the elevator working?", "The lift is in service."),
        ("where is the nearest loo?", "Toilets are on floors 0, 1 and 3."),
        ("which bins are overdue?", "Waste collection points WCP-001 and WCP-002 are overdue."),
    ],
)
def test_ordinary_english_synonyms_are_matched(question, passage):
    assert pr.assess(question, passage, doc_name="x").relevant


def test_a_long_passage_is_scored_on_its_best_window_not_diluted_by_the_rest():
    """The answering sentence buried in a long record must still carry the passage."""
    noise = " ".join(["Cost centre ABW-UTIL was reconciled for the period."] * 40)
    answering = "The chiller pump service is due on 2026-11-01."
    q = "when is the chiller pump service due?"
    assert pr.assess(q, answering, doc_name="x").relevant
    long_passage = noise + " " + answering + " " + noise
    verdict = pr.assess(q, long_passage, doc_name="x")
    assert verdict.relevant and verdict.window >= 2, verdict


def test_scattered_terms_rank_below_terms_said_together():
    together = pr.assess("muster point outside", ASSEMBLY, doc_name="x")
    scattered = pr.assess(
        "muster point outside",
        "The assembly of parts is recorded. " + "Filler. " * 60 + "A point outside the fence.",
        doc_name="x",
    )
    assert together.window >= scattered.window


def test_a_question_with_no_subject_terms_still_fails_open():
    assert pr.assess("tell me more", "anything at all").relevant


def test_an_unrelated_passage_is_still_rejected():
    """The wave-1 defect must not come back: one incidental word is still not an answer."""
    cost = "Free balance = budget minus actual minus committed. Ventilation contract renewals."
    assert not pr.assess(
        "How are the ventilation readings aggregated across the overnight periods?", cost
    ).relevant


# ── a decline is the whole answer ────────────────────────────────────────────

TIPS_Q = "Can I get tips to improve sustainability in my workspace?"
DECLINE_THEN_TALLY = (
    "I could not find this in Abacws Building's documents. I searched them and none is about "
    "this question.\n\nWorkspace kinds recorded: desk (120), focus room (8), collaboration "
    "area (5).\n\n---\n*Sources: `Building model`*"
)


def test_a_tally_after_a_decline_is_dropped():
    out = aw.strip_unrelated_body_after_decline(DECLINE_THEN_TALLY, TIPS_Q)
    assert "desk (120)" not in out and "focus room" not in out
    assert out.startswith("I could not find this in")
    assert "*Sources:" in out, "the footer is left as it was"


def test_a_decline_that_names_the_nearest_records_is_untouched():
    good = (
        "I could not find this in Abacws Building's documents.\n\nAbacws Building does keep "
        "Sustainability target records, which I can read for you."
    )
    assert aw.strip_unrelated_body_after_decline(good, TIPS_Q) == good


def test_an_answer_that_does_not_open_with_a_decline_is_never_trimmed():
    answer = "Sustainability targets are recorded.\n\nEnergy (12), waste (4), water (3)."
    assert aw.strip_unrelated_body_after_decline(answer, TIPS_Q) == answer
    assert not aw.opens_with_a_decline(answer)


@pytest.mark.parametrize(
    "opener",
    [
        "I could not find this in the documents.",
        "I couldn't answer that from the records.",
        "'swimming pool' does not exist in this building, so there is nothing to report about it.",
        "I don't have that specific information on record.",
    ],
)
def test_the_decline_openers_this_system_uses_are_recognised(opener):
    assert aw.opens_with_a_decline(opener)


def test_a_count_listing_is_told_from_prose():
    assert aw._is_count_listing("desk (120), focus room (8), collaboration area (5)")
    assert aw._is_count_listing("| a | b |\n| c | d |")
    assert not aw._is_count_listing("Sustainability targets are recorded for energy and waste.")
