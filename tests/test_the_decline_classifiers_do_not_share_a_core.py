# -*- coding: utf-8 -*-
"""Two classifiers with the same TOTAL are not two classifiers that agree.

WHY THIS FILE EXISTS BESIDE THE ONE THAT PINS THE COUNTS
--------------------------------------------------------
``tests/test_the_decline_classifiers_know_their_own_wording.py`` pins the number of
declines each classifier finds in the 73-answer evidence pack, and its docstring concluded
from ``publication_gate`` moving 6 -> 11 that "two of the three now split the same corpus
the same way, which is the first time that has been true".

**Measured, that is false.** The two classifiers report 11 and 11 and their decline SETS
overlap on three rows. Sixteen of the 73 are a decline to exactly one of them. A matching
total is the weakest possible evidence of agreement — it is lessons #160 one level up (a
metric that is arithmetically correct and structurally blind), occurring inside the test
written to guard against that class of error.

So this file asserts on SETS. Every assertion below is a row-level identity, and each
carries the measurement that produced it so a change is a decision with a number attached
rather than a side effect found later (lessons #141).

WHAT IS PINNED
--------------
* the row-level overlap of the two same-count classifiers on the 73-answer pack;
* that no answer in the whole stored corpus is called a decline by all four classifiers —
  the fact that makes "four implementations of one concept" the wrong description;
* that the hand-anchored trade-off between them has the ORDER it has, because that order is
  the justification for keeping three of them separate (see
  ``scripts/audit_measurement_instrument.py`` section 1).

Nothing here calls the live system or a model; every figure is recomputed from stored
answers on disk. Building-agnostic: no building name is asserted on.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Dict, List, Set

import pytest

pytestmark = pytest.mark.unit

REPO = Path(__file__).resolve().parent.parent
PACK = REPO / "Datasets" / "System evaluation" / "Evidence pack - 73 probes" / "answers.jsonl"


def _pack_rows() -> List[dict]:
    if not PACK.is_file():
        pytest.skip("evidence pack not present in this checkout")
    return [json.loads(x) for x in PACK.read_text(encoding="utf-8").splitlines() if x.strip()]


def _decline_sets(rows: List[dict]) -> Dict[str, Set[int]]:
    from orchestrator.services.publication_gate import is_decline as shared
    from scripts.grade_answers_rubric import is_decline as grader
    from scripts.regression_answerability import classify

    out: Dict[str, Set[int]] = {
        "publication_gate": set(),
        "grade_answers_rubric": set(),
        "regression_answerability": set(),
    }
    for r in rows:
        answer = r.get("answer") or ""
        n = int(r["n"])
        if shared(answer):
            out["publication_gate"].add(n)
        if grader(answer):
            out["grade_answers_rubric"].add(n)
        if classify(answer) in ("declined", "refused"):
            out["regression_answerability"].add(n)
    return out


def test_the_two_same_count_classifiers_disagree_on_sixteen_of_seventy_three():
    """11 and 11 is not agreement: the sets share three rows out of nineteen.

    Measured 2026-09-30 over the stored pack. `publication_gate` alone calls
    {2, 5, 7, 27, 28, 38, 52, 72} declines; the grader alone calls
    {13, 15, 22, 36, 42, 47, 54, 73}; both call {29, 34, 39}.

    The two families of disagreement have different causes and both are informative:

    * the eight `publication_gate`-only rows open with `clarification.compose_abstract`'s
      "I couldn't answer that from <building>'s records" — a real decline the GRADER misses,
      so the grader records them as GOOD_ANSWER or WEIRD;
    * the eight grader-only rows include pack #13, a ranked answer that states
      "Best match: Room 5.14 ... score 0.6405" with figures beside it. The grader's broad
      `do(es) not (contain|record|...)` pattern fires somewhere in its prose and the row is
      filed as a decline. That single pattern is the sole decline evidence for 128 of the
      535 hand-confirmed ANSWERS the grader calls declines across the whole corpus, which is
      CAVEAT-986's mechanism measured against hand labels instead of against a bucket delta.

    If this assertion fails, a marker list moved. That is allowed — but the new sets go in
    the docstring with the date, and the overlap is the number to look at, never the totals.
    """
    rows = _pack_rows()
    sets = _decline_sets(rows)
    pg, gr = sets["publication_gate"], sets["grade_answers_rubric"]

    assert len(pg) == len(gr) == 11, (len(pg), len(gr))
    assert pg & gr == {29, 34, 39}, sorted(pg & gr)
    assert pg - gr == {2, 5, 7, 27, 28, 38, 52, 72}, sorted(pg - gr)
    assert gr - pg == {13, 15, 22, 36, 42, 47, 54, 73}, sorted(gr - pg)
    assert len(pg ^ gr) == 16, len(pg ^ gr)


def test_no_stored_answer_is_a_decline_to_all_four_classifiers():
    """The four are not four readings of one concept — they have no common core.

    Measured 2026-09-30 over 2,868 stored answers (``docs/phase0/*.jsonl`` plus the
    73-answer pack): 0 are called a decline by all four, 1,632 by none, and 1,236 (43.1%)
    by some but not all. CAVEAT-991 describes the four as one concept implemented four
    times; an empty four-way intersection is the strongest available evidence against that
    reading, and it is why the reconciliation in
    ``scripts/audit_measurement_instrument.py`` keeps three of them separate on measured
    grounds rather than merging them.

    This test asserts the empty intersection, not the exact corpus size, because a new
    recorded run may be added to ``docs/phase0/`` at any time. Should the intersection ever
    become non-empty, that is a finding worth reading rather than a failure to silence.
    """
    from scripts.audit_measurement_instrument import classifiers, load_corpus

    corpus = load_corpus()
    assert len(corpus.answers) > 2000, len(corpus.answers)
    assert not corpus.alignment_failures, corpus.alignment_failures

    funcs = classifiers()
    assert len(funcs) == 4, sorted(funcs)
    unanimous = [a.answer for a in corpus.answers if all(fn(a.answer) for fn in funcs.values())]
    assert unanimous == [], f"{len(unanimous)} answers are now a decline to all four"


def test_the_hand_anchored_tradeoff_keeps_its_order():
    """The order of the trade-off is the justification for not unifying the classifiers.

    Anchored to the 1,012 rows a hand reader labelled GOOD_ANSWER or GOOD_DECLINE — the
    only two labels that settle KIND, since a false decline and a fabricated answer are both
    WEIRD — measured 2026-09-30:

    ======================================  ==============  ====================
    classifier                              recall floor    wrong on GOOD_ANSWER
    ======================================  ==============  ====================
    ``regression_answerability.classify``   138/477 28.9%   0/535    0.0%
    ``publication_gate.is_decline``          71/477 14.9%   11/535   2.1%
    ``grade_answers_rubric.is_decline``     251/477 52.6%   162/535 30.3%
    ``ttl_gap_audit.decline_phrases``        31/477  6.5%   9/535    1.7%
    ======================================  ==============  ====================

    What is asserted is the ORDER and the two boundaries that carry a decision, not the
    exact fractions, which move whenever a recorded run is added:

    * the gate's classifier must make NO false decline on hand-confirmed answers — for a
      gate, a manufactured regression is the expensive error (lessons #141);
    * the grader's must remain the most permissive, because that is the defect
      CAVEAT-784/788 describe and a reader needs to know it is still there;
    * ``ttl_gap_audit``'s must remain worse on recall than ``publication_gate``'s, which is
      why it has no defensible position and should be replaced rather than tuned.
    """
    from scripts.audit_measurement_instrument import classifiers, load_corpus

    corpus = load_corpus()
    funcs = classifiers()
    confirmed_decline = [a for a in corpus.answers if a.verdict == "GOOD_DECLINE"]
    confirmed_answer = [a for a in corpus.answers if a.verdict == "GOOD_ANSWER"]
    assert len(confirmed_decline) > 400, len(confirmed_decline)
    assert len(confirmed_answer) > 400, len(confirmed_answer)

    recall = {
        name: sum(1 for a in confirmed_decline if fn(a.answer)) / len(confirmed_decline)
        for name, fn in funcs.items()
    }
    wrong = {
        name: sum(1 for a in confirmed_answer if fn(a.answer)) / len(confirmed_answer)
        for name, fn in funcs.items()
    }

    assert wrong["regression_answerability.classify"] == 0.0, wrong
    assert wrong["grade_answers_rubric.is_decline"] == max(wrong.values()), wrong
    assert recall["grade_answers_rubric.is_decline"] == max(recall.values()), recall
    assert recall["ttl_gap_audit.decline_phrases"] < recall["publication_gate.is_decline"], recall
