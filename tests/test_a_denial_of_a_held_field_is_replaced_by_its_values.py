# -*- coding: utf-8 -*-
"""2D-06 / BUG-835: a narration that denies a field the rows hold has the denial REPLACED.

W19's guard appended a note beside the denial, and the note named the field, not its value. In the
scripted demo question "Which refuge points are defective, and who owns them?" it did not even
fire, three rehearsals running: the question says "owns", the paragraph says "ownership" (an exact
word match misses that), and the 'already shown' test was satisfied by ANOTHER register's
``recordOwner`` named in the same paragraph. The reader was told the owner is not recorded; the
register's owner column reads "Building Fire Warden Coordinator".

The narration below is the live one, verbatim from docs/phase0/demo_rehearsal_2026-09-18_run3.jsonl.
"""

from __future__ import annotations

from datetime import date

import pytest

from orchestrator.services import register_facts as rf
from orchestrator.services import register_projection as rp
from tests.register_fixture_rows import lifted_rows

pytestmark = pytest.mark.unit

TODAY = date(2026, 9, 19)
QUESTION = "Which refuge points are defective, and who owns them?"

#: verbatim, non-breaking hyphens and all
LIVE_NARRATION = (
    "There are 12 records in total — active 9 (EV‑001, EV‑002, EV‑004, "
    "EV‑005, EV‑006, EV‑008, EV‑009, EV‑010, EV‑012), defective 2 "
    "(EV‑003, EV‑007), overdue 1 (EV‑011).\n\n"
    "**Defective refuge points**\n\n"
    "- **EV‑003 – Refuge point – Level 3 north stair**  \n"
    "  *Status:* defective  \n"
    "  *Provenance:* Evacuation provision register\n\n"
    "**Ownership**\n\n"
    "The Evacuation provision register, which lists refuge points, does not contain an "
    "ownership field, so the owner of EV‑003 is not recorded in these records. The Approval "
    "and evidence register does record a `recordOwner` (Estates Governance Lead) for its own "
    "entries, but that field does not apply to refuge points.\n\n"
    "---\n**You might also ask:** Who owns these records? | Which of these are on floor 3?"
)


def _guard(narration: str, question: str = QUESTION) -> str:
    rows, _label = lifted_rows("evacuation_and_peeps.md")
    return rp.guard_narration(narration, rows, question, "Evacuation provision", TODAY)


def test_the_live_denial_of_the_owner_is_replaced_by_the_owner():
    out = _guard(LIVE_NARRATION)
    assert "does not contain an ownership field" not in out
    assert "is not recorded in these records" not in out
    assert "Building Fire Warden Coordinator" in out
    # the value sits on the record it belongs to
    line = next(l for l in out.splitlines() if "Building Fire Warden Coordinator" in l)
    assert "EV‑003" in line or "EV-003" in line
    # everything that was right is kept, in place
    assert out.startswith("There are 12 records in total")
    assert "**Defective refuge points**" in out and "**Ownership**" in out
    assert "**You might also ask:**" in out


def test_the_other_registers_owner_is_not_offered_as_this_registers():
    """The denial paragraph named Estates Governance Lead (the approvals register's owner). The
    replacement must not carry it: it is another register's fact."""
    out = _guard(LIVE_NARRATION)
    assert "Estates Governance Lead" not in out


def test_a_narration_that_already_gives_the_owner_is_left_alone():
    narration = (
        "EV-003 is the only defective refuge point. Its owner is the Building Fire Warden "
        "Coordinator."
    )
    assert _guard(narration) == narration


def test_a_denial_of_a_field_the_register_really_lacks_is_left_alone():
    """No contact field exists in the evacuation register: saying so is true."""
    narration = "The register does not contain a contact phone number for these records."
    assert (
        _guard(narration, "Which refuge points are defective, and what is their phone number?")
        == narration
    )


def test_a_denial_about_something_the_question_never_asked_is_left_alone():
    narration = (
        "EV-003 is defective.\n\nThe register does not contain any information about "
        "carbon emissions."
    )
    assert _guard(narration) == narration


def test_without_a_filter_the_records_named_in_the_narration_get_their_owner():
    """No status or kind in the question: the records the narration talks about are the subject."""
    narration = (
        "EV-008 and EV-011 are assisted routes and plans.\n\nThe register has no information on "
        "who owns them."
    )
    out = _guard(narration, "Who owns EV-008 and EV-011?")
    assert "no information on who owns them" not in out
    assert "Accessibility Adviser" in out


# ── the older note-appending path still runs when nothing was replaced, and now carries values ────


def test_the_appended_note_gives_the_value_not_only_the_field_name():
    rows = [
        {"recordId": "A", "recordStatus": "active", "recordOwner": "Estates Operations Manager"},
        {"recordId": "B", "recordStatus": "active", "recordOwner": "Estates Operations Manager"},
    ]
    columns = sorted({k for r in rows for k in r})
    out = rf.false_absence_corrections(
        "The register does not record who owns these.",
        rows,
        columns,
        "Who owns these?",
        register_label="Asset register",
    )
    assert "Estates Operations Manager" in out
    assert "recordOwner" not in out


def test_another_registers_owner_named_in_the_paragraph_does_not_count_as_showing_this_one():
    rows = [
        {
            "recordId": "A",
            "recordStatus": "active",
            "recordOwner": "Building Fire Warden Coordinator",
        }
    ]
    columns = sorted({k for r in rows for k in r})
    narration = (
        "The register does not contain an ownership field. The approvals register does record a "
        "record owner (Estates Governance Lead) for its own entries."
    )
    out = rf.false_absence_corrections(
        narration, rows, columns, "Who owns A?", register_label="Evacuation provision"
    )
    assert "Building Fire Warden Coordinator" in out


def test_a_word_the_vocabulary_joins_to_the_question_word_is_recognised_in_the_paragraph():
    assert rf._paragraph_says("the register has no ownership field", "owns")
    assert rf._paragraph_says("nobody is responsible for it", "owner")
    assert not rf._paragraph_says("the register records floors", "owns")


def test_guard_never_raises_and_fails_open():
    assert rp.guard_narration("", [{"a": "1"}], "q") == ""
    assert rp.guard_narration("text", [], "q") == "text"
    rows, _ = lifted_rows("evacuation_and_peeps.md")
    assert rp.guard_narration("plain answer", rows, "") == "plain answer"


# ── wave 3: the denial's OWN words, when the question named no field ────────────────────────────


def _approvals():
    rows, _label = lifted_rows("approval_evidence_register.md")
    return rows


APPROVAL_DENIAL = (
    "The register records the evidence and the dates.\n\n"
    "Because those fields are missing, the responsibilities for these activities are "
    "currently unrecorded."
)


def test_a_register_may_not_contradict_itself_between_two_questions():
    """Live 2026-09-19: one answer grouped the approval register's accountable roles and owners
    correctly; another said the responsibilities were unrecorded. The second question asked about
    competence, which names no column, so the question's own words pointed at nothing — the
    denial's words are read too, and only concepts the register really holds are replaced."""
    out = rp.guard_narration(
        APPROVAL_DENIAL,
        _approvals(),
        "Did the assurance activities have competent people assigned?",
        "Approval and evidence record",
        TODAY,
    )
    assert "currently unrecorded" not in out
    assert "Estates Duty Manager" in out and "APR-004" in out
    assert out.startswith("The register records the evidence and the dates.")


def test_a_large_register_is_folded_by_role_rather_than_listed_record_by_record():
    out = rp.guard_narration(
        APPROVAL_DENIAL,
        _approvals(),
        "Did the assurance activities have competent people assigned?",
        "Approval and evidence record",
        TODAY,
    )
    assert out.count("\n- ") < 32  # 32 records folded into one line per role, not one per record
    assert "— 5: APR-004" in out


def test_a_denial_of_something_the_register_really_lacks_is_still_left_alone():
    out = rp.guard_narration(
        "APR-001 is approved.\n\nThe carbon figure for these approvals is currently unrecorded.",
        _approvals(),
        "What is the carbon figure?",
        "Approval and evidence record",
        TODAY,
    )
    assert "currently unrecorded" in out


def test_a_denial_about_a_date_is_not_overwritten_by_the_registers_dates():
    """Only the WHO concepts are read out of a denial: a date named inside one is as often the
    thing genuinely missing as the thing the register holds."""
    out = rp.guard_narration(
        "APR-001 is approved.\n\nThe completion dates for these approvals are not recorded.",
        _approvals(),
        "When were they completed?",
        "Approval and evidence record",
        TODAY,
    )
    assert "are not recorded" in out


@pytest.mark.parametrize(
    "sentence, denies",
    [
        ("those fields are missing", True),
        ("the responsibilities are currently unrecorded", True),
        ("the owner is not recorded", True),
        ("the owner remains unspecified", True),
        ("the register records the owner for every entry", False),
        ("five approvals are missing their evidence date", True),
    ],
)
def test_a_denial_written_as_a_state_is_recognised_as_one(sentence, denies):
    assert bool(rf._ABSENCE_SENTENCE_RE.search(sentence)) is denies
