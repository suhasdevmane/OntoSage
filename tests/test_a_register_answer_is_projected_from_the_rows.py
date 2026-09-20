# -*- coding: utf-8 -*-
"""2D-06: who / when / which / how-many is answered from the rows, not narrated (BUG-835, 811, 813).

The register lane fetched the right records and the narration then got the facts wrong or denied
fields that exist. Live, on 2026-09-18: "Which refuge points are defective, and who owns them?"
said the register has no ownership field (its owner column reads "Building Fire Warden
Coordinator"); "Which maintenance tasks are overdue?" said the building holds no maintenance
information; "Is there a quiet room?" called 26 rooms quiet because each has a *quietest period*
field. Those answers were wrong in three rehearsals each, and six prompt rewrites did not move them.

These tests run the real documents through the real lifter (``tests/register_fixture_rows.py``)
and compare what the projection says with the document's own table, read a second way. The last
block is a matrix over EVERY register the building holds: register x recorded status, register x
owner, register x due date.
"""

from __future__ import annotations

import re
from datetime import date

import pytest

from orchestrator.services import register_projection as rp
from tests.register_fixture_rows import (
    document_names,
    due_column,
    ground_truth,
    lifted_rows,
)

pytestmark = pytest.mark.unit

TODAY = date(2026, 9, 19)


def _answer(document: str, question: str, label: str = "") -> str:
    rows, doc_label = lifted_rows(document)
    return rp.deterministic_answer(rows, question, label or doc_label, TODAY)


def _line_with(text: str, ident: str) -> str:
    for line in text.splitlines():
        if re.search(r"(?<![\w-])" + re.escape(ident) + r"(?![\w-])", line):
            return line
    return ""


# ── the four defects, one real question each ─────────────────────────────────────────────────────


def test_the_defective_refuge_points_are_answered_with_their_owner():
    """BUG-835. The owner column reads 'Building Fire Warden Coordinator'; the narration denied it."""
    text = _answer(
        "evacuation_and_peeps.md",
        "Which refuge points are defective, and who owns them?",
        "Evacuation provision",
    )
    assert "EV-003" in text
    assert "Building Fire Warden Coordinator" in _line_with(text, "EV-003")
    # EV-007 is a DEFECTIVE evacuation chair, EV-011 an overdue plan: neither is a refuge point
    assert "EV-007" not in text and "EV-011" not in text
    assert "does not contain" not in text and "not recorded" not in text


def test_a_record_with_its_own_owner_is_given_that_owner_not_the_registers():
    """FSA-008's owner column is the M and E supervisor; the register itself is kept by the fire
    warden. The graph holds both on the record, comma-joined, and the record's own one answers."""
    text = _answer(
        "fire_safety.md",
        "Which fire safety assets are defective and who owns them?",
        "Fire safety asset",
    )
    assert "M and E Maintenance Supervisor" in _line_with(text, "FSA-008")
    assert "Building Fire Warden Coordinator" not in _line_with(text, "FSA-008")
    assert "Building Fire Warden Coordinator" in _line_with(text, "FSA-005")


def test_the_lift_last_serviced_date_comes_from_the_maintenance_log():
    """BUG-811: 'I don't hold a specific date' above a raw dump of the rows that carry one."""
    text = _answer("maintenance_log.md", "When was the lift last serviced?", "Work order")
    table = ground_truth("maintenance_log.md")
    lift = [r for r in table if "lift" in r["asset_name"].lower() and r["completed_on"]]
    newest = max(lift, key=lambda r: r["completed_on"])
    assert newest["_id"] == "WO-016" and newest["completed_on"] == "2026-06-03"
    assert newest["_id"] in text.splitlines()[0]
    assert "3 June 2026" in text.splitlines()[0]
    # work orders with no completion date are said to have none, never given one
    assert "WO-021" in text and "WO-022" in text and "no recorded" in text


def test_overdue_maintenance_says_what_is_recorded_and_what_is_not():
    """BUG-811: 'the records do not contain any information about maintenance tasks'. The log
    holds 24 work orders; it records no due date, so 'overdue' is not derivable — and 9 are not
    complete, which is a different fact that must not be passed off as overdue."""
    text = _answer("maintenance_log.md", "Which maintenance tasks are overdue?", "Work order")
    table = ground_truth("maintenance_log.md")
    not_complete = sorted(r["_id"] for r in table if r["_status"] != "completed")
    assert len(not_complete) == 9
    assert "no due date" in text and "not the same thing as overdue" in text
    assert all(ident in text for ident in not_complete)
    assert not any(r["_id"] in text for r in table if r["_status"] == "completed")


def test_overdue_assets_are_computed_from_last_visit_plus_interval():
    from datetime import timedelta

    text = _answer(
        "asset_engineering_register.md",
        "Which assets are overdue for maintenance?",
        "Asset engineering profile",
    )
    expected = sorted(
        r["_id"]
        for r in ground_truth("asset_engineering_register.md")
        if r["last_visited"]
        and r["inspection_interval_days"]
        and date.fromisoformat(r["last_visited"])
        + timedelta(days=int(r["inspection_interval_days"]))
        < TODAY
    )
    assert expected, "the fixture should hold assets past their interval"
    listed = sorted(set(re.findall(r"\bAEP-\d+\b", text)))
    assert listed == expected
    # what it is: an inspection interval, not a maintenance schedule the register does not hold
    assert "inspection" in text.lower() and "not a maintenance due date" in text


def test_a_quiet_room_is_read_from_the_noise_value_not_the_quietest_period_field():
    """BUG-813. 'quiet' names a recorded NOISE level (quiet or silent); a room that has a
    'quietest period' is not thereby quiet, and the two conversational spaces are not."""
    rows, label = lifted_rows("workspace_profile_register.md")
    res = rp.resolve(rows, "Which rooms are quiet?", label, TODAY)
    table = ground_truth("workspace_profile_register.md")
    expected = sorted(r["_id"] for r in table if r["noise"] in ("quiet", "silent"))
    assert sorted(rp._ident(r) for r in res.chosen()) == expected
    assert len(expected) == 26
    assert not {"WS-01", "WS-19"} & set(expected)
    assert any("noise" in f for f in res.filters) and not any("quietest" in f for f in res.filters)


# ── refusals: anything the projection cannot vouch for goes back to the narration ────────────────


@pytest.mark.parametrize(
    "question, why",
    [
        ("Who do I ask about the refuge points?", "the question is about the reader"),
        ("Why are the refuge points defective?", "asks for an explanation"),
        ("Which refuge point is the best one to use?", "asks for a judgement"),
        ("Who is the contact for the refuge points?", "the register holds no contact field"),
        ("Are the refuge points defective?", "not a lookup shape"),
        (
            "Which refuge points have a working communication unit?",
            "'working' occurs only inside a free-text state, where 'not working' would match too",
        ),
        ("Which refuge points are not defective?", "an absence is not a lookup"),
    ],
)
def test_a_question_the_rows_cannot_settle_is_left_to_the_narration(question, why):
    assert _answer("evacuation_and_peeps.md", question, "Evacuation provision") == "", why


def test_a_word_the_register_cannot_place_is_named_rather_than_silently_dropped():
    """Wave 4: the owners ARE recorded, so they are given, and the word the register knows
    nothing about is named in one closing sentence instead of the whole question being refused."""
    text = _answer(
        "evacuation_and_peeps.md", "Who owns the refuge points on the moon?", "Evacuation provision"
    )
    assert "Building Fire Warden Coordinator" in text
    assert "does not record moon" in text


def test_only_part_of_a_register_is_left_to_the_narration():
    rows, label = lifted_rows("evacuation_and_peeps.md")
    q = "Which refuge points are defective, and who owns them?"
    assert rp.deterministic_answer(rows, q, label, TODAY, partial=True) == ""


def test_the_deterministic_answer_can_be_switched_off(monkeypatch):
    monkeypatch.setenv("REGISTER_PROJECTION_ANSWER", "false")
    assert _answer("evacuation_and_peeps.md", "Which refuge points are defective?") == ""


def test_a_missing_vocabulary_file_leaves_the_lane_as_it_was(monkeypatch):
    from orchestrator.services import register_vocabulary as rv

    monkeypatch.setattr(rv, "_PATHS", ())
    monkeypatch.setattr(rv, "_REPO_PATH", rv.Path("/nonexistent/register_vocabulary.yaml"))
    rv.get_vocabulary.cache_clear()
    try:
        # "owns" is matched to the owner column only through the table; without it the word
        # is unplaced, and an answer with an unplaced word is never composed here
        assert _answer("evacuation_and_peeps.md", "Who owns the refuge points?") == ""
    finally:
        rv.get_vocabulary.cache_clear()


def test_no_answer_names_the_data_as_simulated_or_synthetic():
    for question in (
        "Which refuge points are defective, and who owns them?",
        "Which personal plans are overdue?",
    ):
        text = _answer("evacuation_and_peeps.md", question, "Evacuation provision").lower()
        assert not any(w in text for w in ("simulated", "synthetic", "fake"))


# ── a composed answer must be the WHOLE answer, or not composed at all ───────────────────────────


def test_the_scripted_open_and_overdue_question_answers_both_halves():
    """Demo question 3. Answering only the overdue half (or only the count) would replace an
    answer that rehearsals rated good with a shorter one."""
    text = _answer(
        "maintenance_log.md",
        "How many open work orders are there, and which are overdue?",
        "Work order",
    )
    table = ground_truth("maintenance_log.md")
    open_ids = sorted(r["_id"] for r in table if r["_status"] in ("open", "in_progress"))
    assert text.splitlines()[0].startswith("**9 of the 24")
    assert "6 in progress, 3 open" in text.splitlines()[0]
    assert all(ident in text for ident in open_ids)
    assert "records no due date and no 'overdue' status" in text
    assert not any(r["_id"] in text for r in table if r["_status"] == "completed")


def test_a_state_plus_a_field_the_answer_would_not_show_is_left_to_the_narration():
    """'overdue OR cannot be evidenced' names an evidence column. Composing only the overdue half
    would state half an answer as the whole."""
    assert (
        _answer(
            "fire_safety.md",
            "Which fire safety assets are overdue or cannot be evidenced?",
            "Fire safety asset",
        )
        == ""
    )


def test_a_topic_word_beside_a_due_date_does_not_narrow_the_answer():
    """'overdue for maintenance': maintenance says why it is due, and selects nothing."""
    text = _answer(
        "asset_engineering_register.md",
        "Which assets are overdue for maintenance?",
        "Asset engineering profile",
    )
    assert re.findall(r"\bAEP-\d+\b", text)
    assert "mentioning" not in text


def test_a_question_that_singles_out_no_record_is_not_answered_by_dumping_a_column():
    """'Who owns the building data?' reduces to 'owns'. Grouping all 32 approvals by owner would
    be an answer to a question nobody asked."""
    assert _answer("approval_evidence_register.md", "Who owns the building data?", "Approval") == ""


def test_a_status_word_no_record_carries_is_not_searched_for_in_record_text():
    """'planned' is a state a register may or may not record. Where none does, it is a word the
    question used that the records cannot place; it must not become a text filter that selects an
    arbitrary few records and then reports that they have no next-due date."""
    text = _answer(
        "service_schedules.md", "When is the next planned maintenance?", "Service schedule entry"
    )
    assert "None of the selected records" not in text


def test_records_named_only_by_their_reference_are_described_by_what_they_are():
    """A permit register's records are named PTW-2026-0416; the kind of permit says what it is."""
    text = _answer("permit_to_work_register.md", "Which permits are open?", "Permit to work")
    table = ground_truth("permit_to_work_register.md")
    open_rows = [r for r in table if r["_status"] == "open"]
    assert open_rows
    for row in open_rows:
        line = _line_with(text, row["_id"])
        assert line and row["type"] in line, (row["_id"], line)


def test_several_columns_that_record_an_owner_are_told_apart_when_grouped():
    rows = [
        {
            "recordId": {"value": f"R-{i}"},
            "recordStatus": {"value": "active"},
            "accountableRole": {"value": "Head of Security" if i % 2 else "Estates Lead"},
            "recordOwner": {"value": "Governance Lead"},
            "kind": {"value": "door" if i < 9 else "lift"},
        }
        for i in range(10)
    ]
    text = rp.deterministic_answer(
        rows, "Which doors are active and who owns them?", "Access", TODAY
    )
    assert "accountable role: Head of Security; owner: Governance Lead" in text


# ── "planned" is a kind of work and a kind of spend (2D-06 follow-up) ────────────────────────────


def test_planned_work_orders_are_the_ones_the_log_records_as_planned():
    rows, label = lifted_rows("maintenance_log.md")
    text = _answer("maintenance_log.md", "Which planned work orders are open?", "Work order")
    table = ground_truth("maintenance_log.md")
    expected = sorted(
        r["_id"] for r in table if r["category"] == "planned" and r["_status"] != "completed"
    )
    assert expected
    listed = sorted(set(re.findall(r"\bWO-\d+\b", text)))
    assert listed == expected


def test_unplanned_work_is_the_reactive_kind():
    text = _answer("maintenance_log.md", "How many unplanned work orders are there?", "Work order")
    table = ground_truth("maintenance_log.md")
    expected = sorted(r["_id"] for r in table if r["category"] == "reactive")
    assert text.splitlines()[0].startswith(f"**{len(expected)} of the 24")
    assert sorted(set(re.findall(r"\bWO-\d+\b", text))) == expected


def test_planned_cost_lines_are_the_planned_spend_category_and_lines_is_not_left_over():
    """'cost lines' names the 'Building cost line' register; the plural must not be reported as a
    word the records failed to match."""
    text = _answer(
        "cost_line_register.md", "How many planned cost lines are there?", "Building cost line"
    )
    table = ground_truth("cost_line_register.md")
    expected = sorted(r["_id"] for r in table if r["category"].lower() == "planned")
    assert expected
    assert sorted(set(re.findall(r"\bCL-[\w-]+\b", text))) == expected


def test_a_word_that_is_both_a_status_group_and_a_recorded_value_is_read_as_the_value():
    """'planned' is in the scheduled-state group; no work order has that STATUS, and the word is
    recorded as a schedule KIND. It must not be left over, and must not be searched for in text."""
    rows, label = lifted_rows("maintenance_log.md")
    res = rp.resolve(rows, "Which planned work orders are open?", label, TODAY)
    assert not res.unresolved
    assert any(f.startswith("schedule kind: planned") for f in res.filters)


# ── the matrix: every register the building holds ─────────────────────────────────────────────────

#: question word -> the canonical recorded statuses it stands for (stated here, not read from the
#: vocabulary file, so the expectation does not come from the code under test)
_WORDS = {
    "defective": {"defective"},
    "completed": {"completed"},
    "active": {"active"},
    "open": {"open", "in_progress"},
}


def _status_cases():
    cases = []
    for document in document_names():
        present = {r["_status"] for r in ground_truth(document)}
        for word, statuses in _WORDS.items():
            if present & statuses:
                cases.append((document, word))
    return cases


@pytest.mark.parametrize("document, word", _status_cases())
def test_matrix_the_records_in_a_named_status_are_exactly_the_documents_rows(document, word):
    rows, label = lifted_rows(document)
    res = rp.resolve(rows, f"Which records are {word}?", label, TODAY)
    expected = sorted(r["_id"] for r in ground_truth(document) if r["_status"] in _WORDS[word])
    assert not res.unresolved, res.unresolved
    assert sorted(rp._ident(r) for r in res.chosen()) == expected


@pytest.mark.parametrize("document, word", _status_cases())
def test_matrix_every_owner_printed_is_the_documents_owner_for_that_record(document, word):
    rows, label = lifted_rows(document)
    question = f"Which records are {word} and who owns them?"
    text = rp.deterministic_answer(rows, question, label, TODAY)
    truth = {r["_id"]: r for r in ground_truth(document) if r["_status"] in _WORDS[word]}
    if len(truth) > rp.MAX_ANSWER_ROWS:
        # a survey, not a lookup: refusing to list 82 records is the right answer to it
        assert text == "", document
        return
    assert text, f"{document}: not composed deterministically"
    for ident, row in truth.items():
        line = _line_with(text, ident)
        assert line, f"{document}: {ident} missing from the answer"
        assert row["_owner"] in line, f"{document}: {ident} owner {row['_owner']!r} not in {line!r}"


def _due_cases():
    cases = []
    for document in document_names():
        if not due_column(document):
            continue
        present = {r["_status"] for r in ground_truth(document)}
        for word, statuses in _WORDS.items():
            if present & statuses:
                cases.append((document, word))
    return cases


@pytest.mark.parametrize("document, word", _due_cases())
def test_matrix_the_next_due_date_is_the_soonest_one_the_table_holds(document, word):
    column = due_column(document)
    truth = [
        date.fromisoformat(r[column][:10])
        for r in ground_truth(document)
        if r["_status"] in _WORDS[word] and re.match(r"\d{4}-\d{2}-\d{2}", r.get(column, ""))
    ]
    if not truth:
        pytest.skip("no dated record in that status")
    upcoming = [d for d in truth if d >= TODAY]
    expected = min(upcoming) if upcoming else min(truth)
    rows, label = lifted_rows(document)
    text = rp.deterministic_answer(
        rows, f"What is the next due date of the {word} records?", label, TODAY
    )
    assert text, f"{document}: not composed deterministically"
    assert rp._fmt_date(expected) in text.splitlines()[0]
