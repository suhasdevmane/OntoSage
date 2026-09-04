# -*- coding: utf-8 -*-
"""A computed answer that hedges is still a computed answer (CAVEAT-418).

`_heuristic_grade` listed the bare words **"requires"** and **"capability"** as evidence
that an answer declines. Both are ordinary English. Measured across the 2,945 answered
questions, 61 answers carried a record count or a data marker and were still graded
`honest-capability-answer`; **56 of the 61 were pulled out by "requires" alone**.

Hand-labelling a sample of eight found six genuinely computed — *"the building holds seven
competency-requirement records"*, a warranty table, an open-permit table, *"in total, 3
hazard categories"*. Every one carried a sentence like *"because each task requires a
different access method"*: a statement ABOUT the data, not an admission it is missing.

**Reordering was considered and rejected.** Promoting the computed test above the capability
test would make a decline that happens to mention a number read as computed — which is
BUG-370 and BUG-191 exactly, both of which cost this project a fictitious score. This
narrows the *evidence* instead of reranking the checks.

MEASURED BEFORE AND AFTER over all 2,945: 57 moved honest → computed, of which **50 came
from the `metadata` lane** (SPARQL over the registers) and exactly **one** was a false
promotion — a general-knowledge answer about planning law. 3 moved honest → failed, 2 of
them arguably correct declines. Computed 42.6% → 44.5%.
"""

import importlib.util
import sys
from pathlib import Path

import pytest

pytestmark = pytest.mark.unit

REPO = Path(__file__).resolve().parent.parent


def _grader():
    spec = importlib.util.spec_from_file_location(
        "_replay_grade", REPO / "scripts" / "corpus_replay.py"
    )
    mod = importlib.util.module_from_spec(spec)
    sys.modules["_replay_grade"] = mod
    spec.loader.exec_module(mod)
    return mod


replay = _grader()
grade = replay._heuristic_grade
COMPUTED = {"answered-with-data", "answered-with-proof"}
HONEST = {"honest-capability-answer", "clarified-appropriately"}


# ── the measured misgradings, using the REAL answers ───────────────────────────────────
#
# Fixtures are captured from the actual capture rather than invented. A first version of
# these tests used hand-written answers and failed for the fixtures' own reasons: one spelled
# a count as "seven" so no digit signal fired at all, and one invented a "quoted passage"
# that does not match the opener _QUOTED_PASSAGE actually looks for. A grader test written
# against imagined data measures the imagination.

import json

FIXTURES = json.loads(
    (Path(__file__).parent / "fixtures" / "grader_labelled_answers.json").read_text(
        encoding="utf-8"
    )
)


def _fixture(name):
    f = FIXTURES.get(name)
    if not f:
        pytest.skip(f"fixture {name} was not captured from this corpus")
    return f


def test_a_record_count_with_an_ordinary_requires_is_computed():
    """AU-071: 'the building holds seven competency-requirement records', graded a decline
    because the same sentence says a task 'requires qualification'."""
    f = _fixture("count_over_records")
    assert grade(f["question"], f["answer"]) in COMPUTED


def test_a_table_answer_that_mentions_requires_is_computed():
    """FM-006: an open-permit table, graded a decline on 'because each task requires a
    different access method'."""
    f = _fixture("table_with_requires")
    assert grade(f["question"], f["answer"]) in COMPUTED


def test_the_genuine_decline_in_the_same_shape_stays_a_decline():
    """FM-072: 'comparing recurring faults requires sensors with linked time-series data'.
    Same verb, and this one really is a missing capability."""
    f = _fixture("real_capability_decline")
    assert grade(f["question"], f["answer"]) not in COMPUTED


def test_the_specific_phrases_are_what_is_listed():
    """The fix is narrower EVIDENCE, not a different order. Pinned so a future edit that
    re-adds a bare verb fails here."""
    import inspect

    src = inspect.getsource(replay._heuristic_grade)
    start = src.index("capability_phrases = [")
    block = src[start : src.index("]", start)]
    assert '"requires",' not in block, "bare 'requires' is back; it is an ordinary verb"
    assert '"capability",' not in block, "bare 'capability' is back"
    assert '"requires sensors"' in block
    assert '"requires hardware"' in block


def test_the_computed_test_was_not_promoted_above_the_capability_test():
    """Reordering is the tempting fix and it is the wrong one: a decline that mentions a
    number would read as computed, which is BUG-370 and BUG-191."""
    import inspect

    src = inspect.getsource(replay._heuristic_grade)
    cap_at = src.index('return "honest-capability-answer"')
    computed_at = src.index('return "answered-with-data"')
    assert cap_at < computed_at, (
        "the capability branch must still be tested BEFORE the computed branch; the fix is "
        "narrower evidence, not a different order"
    )


# ── the guards that predate this and must survive it ───────────────────────────────────


def test_a_quoted_passage_is_still_not_computed():
    """BUG-370: a pasted passage is full of digits and must not count as a calculation.

    Uses a real one from the corpus, because _QUOTED_PASSAGE matches specific OPENERS and
    an invented example simply does not look like one.
    """
    f = _fixture("quoted_passage")
    assert grade(f["question"], f["answer"]) not in COMPUTED


def test_an_empty_or_tiny_answer_is_still_wrong():
    assert grade("q", "") == "wrong"
    assert grade("q", "No.") == "wrong"
