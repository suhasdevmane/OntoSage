# -*- coding: utf-8 -*-
"""Wave 4 (2D-06): a question naming five things is answered for the ones the register holds.

The stakeholder catalogue asks four and five things at once, and the register lane either took one
clause or declined the lot. Measured live 2026-09-19: "Was each assurance activity performed by
people with the required competence, independence, authority and access, against an explicit and
current scope?" was declined whole, over a register that records the responsible role and the
dates. A question of the same shape about competency records was answered well — seven records,
and honest that the assignment of people to them is not recorded. That is the shape wanted
everywhere. (The good example is not quoted here: it belongs to a held-out set, and a question
copied into a fixture stops being one nobody tuned towards.)

So the census is used to SPLIT the question: what the register holds is answered from the rows,
and what it does not hold is named once, in the asker's own words. The guard that keeps this from
becoming a fabrication is ``Resolution.pinned`` — a word that merely appears in the text of a few
rows can no longer select them, because in a question naming five properties one incidental hit
would pick an arbitrary handful and present them as the answer.
"""

from __future__ import annotations

from datetime import date

import pytest

from orchestrator.services import register_projection as rp
from tests.register_fixture_rows import ground_truth, lifted_rows

pytestmark = pytest.mark.unit

TODAY = date(2026, 9, 19)

APPROVALS = ("approval_evidence_register.md", "Approval and evidence record")
COMPETENCY = ("competency_requirements.md", "Competency requirement")
PATROLS = ("patrol_checkpoint_register.md", "Patrol checkpoint")


def _resolve(register, question: str):
    rows, _label = lifted_rows(register[0])
    return rows, rp.resolve(rows, question, register[1], TODAY)


def _facts(register, question: str) -> str:
    rows, _label = lifted_rows(register[0])
    return "\n".join(rp.facts_lines(rows, question, register[1], TODAY))


# ── the register answers the clauses it holds ────────────────────────────────────────────────────


def test_the_assurance_question_is_answered_from_the_roles_the_register_records():
    """Three clauses of five are beyond the approval register; the roles are not."""
    question = (
        "Which assurance activities were performed by people with the required competence "
        "and independence?"
    )
    facts = _facts(APPROVALS, question)
    assert facts, "the register holds the roles; the question must not reach the model empty"
    assert "THIS COVERS PART OF THE QUESTION" in facts
    assert "competence" in facts and "independence" in facts
    # the part it does hold is stated, with the register's own roles
    truth = {r["accountable_role"] for r in ground_truth(APPROVALS[0])}
    assert any(role in facts for role in truth)
    assert "Never decline the whole question" in facts


def test_the_closing_sentence_names_only_properties_not_qualifiers():
    _rows, res = _resolve(
        APPROVALS,
        "Which assurance activities were performed by people with the required competence "
        "and independence?",
    )
    assert "competence" in res.unanswered and "independence" in res.unanswered
    for qualifier in ("required", "current", "explicit", "performed"):
        assert qualifier not in res.unanswered, qualifier


def test_a_competency_question_keeps_the_clause_the_register_holds():
    question = (
        "Which authorisations and competence records are in place for the people assigned "
        "to high-risk tasks?"
    )
    rows, res = _resolve(COMPETENCY, question)
    assert res.pinned(), "the register records the authority and the role"
    facts = _facts(COMPETENCY, question)
    assert facts and "THIS COVERS PART OF THE QUESTION" in facts


def test_a_patrol_question_names_what_the_register_cannot_show():
    question = "Which patrol checkpoints have a recorded owner and a heartbeat signal?"
    _rows, res = _resolve(PATROLS, question)
    assert "heartbeat" in res.unanswered
    assert res.pinned() and res.fields, "the owner is recorded and must still be answered"


@pytest.mark.parametrize("register", [APPROVALS, COMPETENCY, PATROLS])
def test_the_unanswered_sentence_is_written_once_and_in_the_askers_words(register):
    question = "Which records have a recorded owner, a heartbeat and a telemetry feed?"
    rows, _label = lifted_rows(register[0])
    res = rp.resolve(rows, question, register[1], TODAY)
    lines = rp._unanswered_line(res)
    if not res.unanswered:
        pytest.skip("this register records them all")
    text = "\n".join(lines)
    assert text.count("does not record") == 1
    assert "heartbeat" in text or "telemetry" in text


# ── the guard: an incidental word must not select the records ────────────────────────────────────


def test_a_word_that_merely_appears_in_a_few_rows_does_not_pick_the_answer():
    """ "required" and "access" occur in some approval rows. In a question naming five properties
    they are not a filter, and the records they hit are not the answer."""
    question = (
        "Was each assurance activity performed by people with the required competence, "
        "independence, authority and access, against an explicit and current scope?"
    )
    _rows, res = _resolve(APPROVALS, question)
    assert not [f for f in res.filters if f.startswith("mentioning")], res.filters


def test_nothing_is_composed_when_the_register_holds_none_of_what_was_singled_out():
    question = (
        "Which critical services depend on networks or cloud platforms, and what safe local "
        "function remains?"
    )
    rows, res = _resolve(
        ("continuity_provision_register.md", "Service continuity provision"), question
    )
    assert not res.pinned()
    assert rp._ineligible(res, question, False).startswith("the register holds none of what")
    assert rp.facts_lines(rows, question, "Service continuity provision", TODAY) == []


def test_a_judgement_question_is_still_refused():
    for question in (
        "Is it safe to work in the plant room?",
        "How risky is the lift?",
        "Which approval is the best one?",
    ):
        rows, _label = lifted_rows(APPROVALS[0])
        assert rp.deterministic_answer(rows, question, APPROVALS[1], TODAY) == "", question


def test_a_noun_carrying_a_judgement_word_is_not_mistaken_for_one():
    """ "high-risk task" and "safe local function" name things a register records."""
    assert rp.question_shape("Which authorisations cover high-risk tasks?") == "list"
    assert rp.question_shape("Which services keep a safe local function?") == "list"
    assert rp.question_shape("Is it safe?") == ""
    assert rp.question_shape("How safe is the building?") == ""
