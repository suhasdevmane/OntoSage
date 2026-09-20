# -*- coding: utf-8 -*-
"""Five answers that were not answers, and the guard that replaces them (2D-16 wave 3).

A hand read of 62 unscripted stakeholder questions on the final build found five, from five
different lanes, sharing one shape: something internal, or the question's own words, emitted where
an answer belongs. Every text below is the LIVE text, verbatim.

The guard is precision-first, and the standard it is held to is in
``test_no_recorded_good_answer_is_touched``: replayed over the 1,521 answers in ``docs/phase0``, it
flags none. A rule that suppressed a good answer would cost more than the defect it removes.
"""

from __future__ import annotations

import glob
import json
import os
import re

import pytest

from orchestrator.services import answer_shape as ash

pytestmark = pytest.mark.unit

SPILL_Q = (
    "Has this reported spill already been attended, or is it still an open action for our team?"
)
DEPENDENCY_Q = (
    "Where do declared assets or activities accumulate behind a common fire, water, power, "
    "cooling, security, network or access dependency?"
)
SAFETY_Q = "are there any safety concern i should be aweare of"
ENERGY_Q = "What are the top reasons for energy spikes? Suggest remedies."
PRIVACY_Q = (
    "I may need privacy to manage medication or another personal need. Which official "
    "private-space or support option can staff confirm?"
)

FIVE = [
    (SPILL_Q, "**Not met**\n\n---\n*Sources: `Building model`*", "only a verdict, with no subject"),
    (DEPENDENCY_Q, "continuity_provision_register", "only a file or class name"),
    (
        SAFETY_Q,
        "A sensor that measures the difference of a quantity between any two points in the system",
        "a definition of a kind of thing, not an answer about this building",
    ),
    (
        ENERGY_Q,
        "**No — top reasons for energy is not measured in this building.** There is no sensor of "
        "that kind there",
        "the question's own words treated as a measurand",
    ),
    (
        PRIVACY_Q,
        "'privacy to manage medication or another personal need', 'privacy to manage medication "
        "or another personal need' isn't something this building senses",
        "the same phrase printed twice",
    ),
]


@pytest.mark.parametrize("question,answer,reason", FIVE, ids=lambda v: None)
def test_each_live_defect_is_caught_and_named(question, answer, reason):
    assert ash.non_answer_reason(answer, question) == reason
    assert ash.is_non_answer(answer, question)


# ── each rule on its own ─────────────────────────────────────────────────────


@pytest.mark.parametrize(
    "body",
    [
        "continuity_provision_register",
        "coordination_function_register",
        "asset_engineering_register.md",
        "brick:Differential_Sensor",
        "hasTimeseriesId",
        "**`maintenance_log`**",
    ],
)
def test_a_machine_name_alone_is_not_an_answer(body):
    assert ash.is_bare_identifier(body)


@pytest.mark.parametrize(
    "body",
    [
        "Room 5.01 is a research laboratory.",
        "The register records eight waste streams.",
        "Floor 3 holds 56 rooms.",
        "Yes — the lift is working.",
        "No records of that are held.",
    ],
)
def test_prose_is_never_mistaken_for_a_machine_name(body):
    assert not ash.is_bare_identifier(body)


def test_a_verdict_that_names_its_subject_is_kept():
    assert not ash.is_bare_verdict("Not met", "was the fire inspection met?")
    assert ash.is_bare_verdict("**Not met**", SPILL_Q)


@pytest.mark.parametrize(
    "body,question",
    [
        ("42", "how many rooms?"),  # a figure is a fact, however short
        ("Yes, on floor 3.", "is there a toilet on floor 3?"),
        ("Closed on 14 March.", "is the work order closed?"),
    ],
)
def test_a_short_answer_carrying_a_fact_is_kept(body, question):
    assert not ash.is_bare_verdict(body, question)


def test_a_class_comment_that_does_answer_the_question_is_kept():
    """Asked what a differential sensor IS, the same sentence is the right answer."""
    body = "A sensor that measures the difference of a quantity between any two points."
    assert not ash.is_class_definition(body, "what is a differential sensor?")
    assert ash.is_class_definition(body, SAFETY_Q)


def test_a_measurand_decline_is_kept_when_the_question_really_names_a_quantity():
    body = "Radon isn't something this building senses."
    assert not ash.echoes_the_question_as_a_measurand(body, "what is the radon level?")
    assert ash.echoes_the_question_as_a_measurand(body, ENERGY_Q)


def test_the_repeat_rule_only_fires_on_a_quoted_phrase_printed_twice():
    """It first compared word n-grams anywhere and flagged four answers the hand read called GOOD."""
    assert ash.repeats_a_phrase("'the north stair', 'the north stair' isn't sensed")
    table = (
        "| Floor | Zone | Area |\n| 0 | 0.01 | 184.5 |\n| 0 | 0.04 | 69.3 |\n"
        "The Evacuation provision register lists five refuge points. "
        "The Evacuation provision register does not record an owner."
    )
    assert not ash.repeats_a_phrase(table)


def test_long_prose_is_always_left_alone():
    prose = " ".join(["The building records its waste streams and collection points."] * 12)
    assert ash.non_answer_reason(prose, ENERGY_Q) is None


def test_an_empty_answer_is_not_this_guards_business():
    assert ash.non_answer_reason("", SPILL_Q) is None
    assert ash.non_answer_reason("   \n ", SPILL_Q) is None


def test_the_footer_is_not_mistaken_for_the_answer():
    assert ash.body_of("**Not met**\n\n---\n*Sources: `Building model`*") == "Not met"


# ── the standard the guard is held to ────────────────────────────────────────

_PH = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "docs", "phase0")


def _recorded():
    """(question, answer, hand-read verdict) for every recorded live answer."""
    for path in sorted(glob.glob(os.path.join(_PH, "*.jsonl"))):
        base = os.path.basename(path)
        if "tail_D" in base or base.endswith("_read.jsonl"):
            continue
        read_path = path.replace(".jsonl", "_read.jsonl")
        reads = []
        if os.path.exists(read_path):
            reads = [json.loads(l) for l in open(read_path, encoding="utf-8") if l.strip()]
        rows = [json.loads(l) for l in open(path, encoding="utf-8") if l.strip()]
        for i, row in enumerate(rows):
            verdict = (reads[i].get("verdict") if i < len(reads) else None) or "?"
            yield row.get("q") or "", row.get("answer") or "", verdict


@pytest.mark.skipif(not os.path.isdir(_PH), reason="the recorded runs are not in this checkout")
def test_no_recorded_good_answer_is_touched():
    """Replay. A GOOD answer this guard would change is a failure of the guard, not of the answer."""
    changed = [
        (q, ash.non_answer_reason(a, q), a)
        for q, a, v in _recorded()
        if a.strip() and v == "GOOD_ANSWER" and ash.non_answer_reason(a, q)
    ]
    assert not changed, "\n".join(
        f"{why}: {q[:70]} -> {re.sub(r'[[:space:]]+', ' ', a)[:120]}" for q, why, a in changed
    )


@pytest.mark.skipif(not os.path.isdir(_PH), reason="the recorded runs are not in this checkout")
def test_the_replay_covers_a_real_corpus_and_flags_no_answer_read_as_good():
    """Wave 5 widened the guard to the tail-F shapes, which the hand read marked WEIRD (or left unread)."""
    rows = [(q, a, v) for q, a, v in _recorded() if a.strip()]
    assert len(rows) > 1000, "the replay must actually read the recorded runs"
    assert [q for q, a, v in rows if ash.non_answer_reason(a, q) and v.startswith("GOOD")] == []
