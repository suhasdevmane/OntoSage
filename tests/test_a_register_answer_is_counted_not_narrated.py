"""BUG-581: register counts and filters are computed in code and handed to the narration.

Rehearsed 3x on 2026-09-15: one work-order question gave "9 open, all 9 overdue" (no due date
is recorded), "the records do not say" and "3 open"; a refuge-point question listed an
evacuation chair as a defective refuge point. Shapes below are the lifted registers'.
"""

from datetime import date
from pathlib import Path

import pytest

from orchestrator.services.register_facts import register_facts, strip_leaked_code_line

pytestmark = pytest.mark.unit


def _row(**kw):
    return {k: {"value": v} for k, v in kw.items()}


WORK_ORDERS = (
    [_row(recordId=f"WO-{i:03}", recordStatus="completed", effectiveFrom="2026-05-01") for i in range(1, 16)]
    + [_row(recordId=i, recordStatus="open", effectiveFrom="2026-05-20") for i in ("WO-016", "WO-017", "WO-018")]
    + [_row(recordId=f"WO-{i}", recordStatus="in_progress", effectiveFrom="2026-06-01") for i in range(19, 25)]
)

EVACUATION = [
    _row(recordId="EV-001", provisionKind="refuge point", recordStatus="active", reviewDue="2026-11-14"),
    _row(recordId="EV-002", provisionKind="refuge point", recordStatus="active", reviewDue="2026-11-14"),
    _row(recordId="EV-003", provisionKind="refuge point", recordStatus="defective", reviewDue="2026-11-14"),
    _row(recordId="EV-006", provisionKind="evacuation chair", recordStatus="active", reviewDue="2026-12-11"),
    _row(recordId="EV-007", provisionKind="evacuation chair", recordStatus="defective", reviewDue="2026-12-11"),
    _row(recordId="EV-011", provisionKind="personal plan", recordStatus="overdue", reviewDue="2026-08-29"),
]


def test_every_status_is_counted_with_its_ids():
    facts = register_facts(WORK_ORDERS, "How many open work orders are there?")
    assert "Records held: 24." in facts
    assert "completed 15" in facts
    assert "open 3 (WO-016, WO-017, WO-018)" in facts
    assert "in_progress 6" in facts


def test_overdue_with_no_due_date_is_stated_as_not_recorded():
    facts = register_facts(
        WORK_ORDERS, "How many open work orders are there, and which are overdue?", date(2026, 9, 15)
    )
    assert "OVERDUE IS NOT RECORDED" in facts
    # an effective date is not a deadline, and the block says so
    assert "effective" in facts


def test_a_question_that_does_not_ask_about_overdue_gets_no_overdue_line():
    assert "OVERDUE" not in register_facts(WORK_ORDERS, "Which permits are open?")


def test_status_is_split_within_each_kind_so_a_chair_is_not_a_refuge_point():
    facts = register_facts(EVACUATION, "Which refuge points are defective, and who owns them?")
    refuge = next(l for l in facts.splitlines() if l.strip().startswith("- refuge point:"))
    chair = next(l for l in facts.splitlines() if l.strip().startswith("- evacuation chair:"))
    assert "defective 1 (EV-003)" in refuge and "EV-007" not in refuge
    assert "EV-007" in chair


def test_a_due_column_yields_the_records_whose_date_has_passed():
    facts = register_facts(EVACUATION, "Which provisions are overdue for review?", date(2026, 9, 15))
    assert "reviewDue already passed on 2026-09-15 for 1 record(s)" in facts
    assert "EV-011 (2026-08-29)" in facts
    assert "NOT RECORDED" not in facts


def test_rows_without_a_recorded_status_produce_nothing():
    assert register_facts([_row(label="x")], "anything") == ""


@pytest.mark.parametrize(
    "leaked,expected_first",
    [
        ("EV-003, 3  \n\nThe only refuge point recorded as defective is EV-003.", "The only"),
        ("**EV-003, EV-007**\n\nThe building records show", "The building"),
    ],
)
def test_a_first_line_of_bare_codes_is_removed(leaked, expected_first):
    assert strip_leaked_code_line(leaked).startswith(expected_first)


def test_a_sentence_that_starts_with_a_code_is_kept():
    text = "WO-013 is the only high-priority open work order."
    assert strip_leaked_code_line(text) == text


def test_the_register_handover_uses_the_facts_and_the_strip():
    src = (Path(__file__).resolve().parent.parent / "orchestrator" / "agents" / "sparql_agent.py").read_text(
        encoding="utf-8"
    )
    assert "register_facts(" in src and "strip_leaked_code_line(" in src


def test_a_passed_due_date_on_a_record_not_marked_overdue_is_stated_separately():
    rows = [
        _row(recordId="FSA-001", recordStatus="overdue", nextTestDue="2026-09-02"),
        _row(recordId="FSA-010", recordStatus="active", nextTestDue="2026-09-14"),
        _row(recordId="FSA-020", recordStatus="active", nextTestDue="2026-10-08"),
    ]
    facts = register_facts(rows, "Which fire safety assets are overdue?", date(2026, 9, 15))
    assert "STATE BOTH: 1 record(s) have the recorded status 'overdue'; 1 more" in facts
    assert "FSA-010 (2026-09-14)" in facts and "FSA-020" not in facts.split("STATE BOTH")[1]
