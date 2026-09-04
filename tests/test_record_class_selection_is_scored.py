# -*- coding: utf-8 -*-
"""A question naming several registers must reach the right one (Phase B).

`held_record_class` returned the FIRST class whose vocabulary matched, in whatever order
SPARQL happened to return them. Two consequences:

* a question naming several registers went to whichever the graph listed first, and
* the routing was not deterministic between runs, because that order is not guaranteed.

Harmless while twelve classes existed. It gets worse with every register added, which is why
this was fixed before building more of them. Measured live on three questions:

| question | reached | should reach |
|---|---|---|
| *"…planned, reactive, statutory, **contract-fixed**…"* | `Contract` | `CostLine` |
| *"unresolved exceptions for this shift **handover**"* | `HandoverRecord` | `PatrolCheckpoint` |
| *"is the Level 2 laboratory permission group approved"* | (sensor lane) | `AccessPermission` |

The scoring is deliberately conservative. BUG-372's lesson is that head words may find data
but must never justify a decline, and BUG-218's proportional-overlap fix was *measured and
rejected* for trading a fabrication-shaped failure for a coverage collapse. So a compound
match is DISCOUNTED rather than rejected: rejecting outright would lose real matches in a
building that hyphenates its compound names.
"""

import pytest

from orchestrator.services.record_registry import (
    RecordClass,
    _term_score,
    held_record_class,
)

pytestmark = pytest.mark.unit


def _cls(local, terms, instances=10):
    return RecordClass(local_name=local, label=local, instances=instances, terms=tuple(terms))


# Vocabularies as the TBox declares them, INCLUDING the plurals `_terms_for` adds. A
# hand-written fixture without plurals made two of these tests fail for the fixture's
# reasons rather than the code's, which is a test measuring itself.
CONTRACT = _cls("Contract", ("contract", "contracts", "agreement", "agreements", "supplier"))
COSTLINE = _cls("CostLine", ("cost", "costs", "spend", "budget", "commitment", "free balance"))
# "handover" alone belonged to both this and PatrolCheckpoint until the TBox disambiguated
# them; each now declares the phrase its own domain uses.
HANDOVER = _cls("HandoverRecord", ("project handover", "handover record", "as-built"))
PATROL = _cls(
    "PatrolCheckpoint",
    ("patrol", "patrols", "checkpoint", "checkpoints", "shift handover", "this shift"),
)
ACCESS = _cls("AccessPermission", ("access", "permission", "permission group", "credential"))
PERMIT = _cls("Permit", ("permit", "permits", "permit to work", "hot works permit"))
ALL = [CONTRACT, COSTLINE, HANDOVER, PATROL, ACCESS, PERMIT]


# ── the three measured misses ──────────────────────────────────────────────────────────


def test_a_hyphenated_compound_does_not_claim_the_question():
    q = "What proportion of current spend is planned, reactive, statutory, contract-fixed or demand-led?"
    assert held_record_class(q, ALL).local_name == "CostLine"


def test_a_shift_handover_reaches_the_patrol_register():
    q = "Which unresolved exceptions require an explicit call-out in this shift handover?"
    got = held_record_class(q, ALL)
    assert got is not None and got.local_name == "PatrolCheckpoint"


def test_a_multi_word_term_beats_a_common_single_word():
    q = "Which active permission group controls this opening?"
    assert held_record_class(q, ALL).local_name == "AccessPermission"


# ── the property behind them ───────────────────────────────────────────────────────────


def test_a_compound_match_scores_less_than_a_standalone_one():
    assert _term_score("contract", " a contract-fixed line ") < _term_score(
        "contract", " a contract for lifts "
    )


def test_a_compound_match_is_discounted_not_rejected():
    """Rejecting outright would lose real matches where a building hyphenates names."""
    assert _term_score("contract", " a contract-fixed line ") > 0


def test_a_longer_term_outranks_a_shorter_one():
    assert _term_score("permission group", " the permission group here ") > _term_score(
        "access", " the access here "
    )


def test_a_term_that_is_absent_scores_nothing():
    assert _term_score("permit", " nothing relevant here ") == 0


def test_a_substring_that_is_not_a_word_does_not_match():
    """'permit' must not match inside 'permitting' — \\b already does this; pinned so a
    future rewrite to a plain `in` test fails here rather than in production."""
    assert _term_score("permit", " permitting the works ") == 0


# ── determinism, which the old order-dependent version did not have ────────────────────


def test_the_same_question_routes_the_same_way_whatever_the_row_order():
    q = "Which permits and contracts are open?"
    forward = held_record_class(q, ALL)
    backward = held_record_class(q, list(reversed(ALL)))
    assert forward is not None and backward is not None
    assert forward.local_name == backward.local_name, (
        "routing depends on the order SPARQL returned the classes, which is not guaranteed "
        "between runs"
    )


def test_a_question_naming_nothing_still_returns_none():
    assert held_record_class("what is the temperature in room 5.04", ALL) is None
    assert held_record_class("", ALL) is None
    assert held_record_class("anything", []) is None


# ── the answers that already worked must keep working ──────────────────────────────────


@pytest.mark.parametrize(
    "question, expected",
    [
        ("which permits are open in the basement?", "Permit"),
        ("which contracts expire this year?", "Contract"),
        ("what is the decision-ready free balance?", "CostLine"),
        ("which scheduled patrol checkpoints are overdue?", "PatrolCheckpoint"),
        ("which plant has no handover record?", "HandoverRecord"),
    ],
)
def test_the_unambiguous_cases_are_unchanged(question, expected):
    got = held_record_class(question, ALL)
    assert got is not None and got.local_name == expected
