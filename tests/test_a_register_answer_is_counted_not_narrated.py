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


def test_past_due_records_the_narration_left_out_are_stated_by_the_system():
    from orchestrator.services.register_facts import completeness_line, passed_due_not_marked

    rows = [
        _row(recordId="FSA-001", recordStatus="overdue", nextTestDue="2026-09-02"),
        _row(recordId="FSA-010", recordStatus="active", nextTestDue="2026-09-14"),
        _row(recordId="FSA-011", recordStatus="completed", nextTestDue="2026-09-01"),
    ]
    missing = passed_due_not_marked(rows, "Which assets are overdue?", date(2026, 9, 15))
    assert missing == ["FSA-010 (nextTestDue 2026-09-14, recorded active)"]
    assert "FSA-010" in completeness_line("Only FSA-001 is overdue.", missing)
    assert completeness_line("FSA-001 and FSA-010 ...", missing) == ""
    assert passed_due_not_marked(rows, "Which assets are active?", date(2026, 9, 15)) == []


REGIMES = [
    _row(recordId="REG-001", recordStatus="active", operatingWindow="Mon-Fri 07:00-19:00"),
    _row(recordId="REG-002", recordStatus="active", operatingWindow="Mon-Fri 07:00-20:00",
         approvedException="extends to 22:00 in assessment weeks"),
    _row(recordId="REG-003", recordStatus="active", operatingWindow="continuous",
         approvedException="continuous is the approved regime"),
    _row(recordId="REG-004", recordStatus="under_review", operatingWindow="Mon-Fri"),
]


def test_a_field_the_question_names_is_counted_with_its_records():
    facts = register_facts(REGIMES, "Which HVAC systems run outside normal hours, and is each exception approved?")
    line = next(l for l in facts.splitlines() if "approvedException" in l)
    assert "recorded for 2 of 4 records: REG-002, REG-003" in line


def test_a_field_nobody_asked_about_is_not_counted():
    facts = register_facts(REGIMES, "Which regimes are under review?")
    assert "approvedException" not in facts


def test_provenance_fields_are_never_counted_as_content():
    rows = [_row(recordId="A", recordStatus="active", recordOwner="X"), _row(recordId="B", recordStatus="active")]
    assert "recordOwner" not in register_facts(rows, "Who is the record owner of each?")


DEPARTMENTS = [
    _row(recordId=f"DEP-{i:02}", recordStatus="active",
         outOfHoursRoute=("No cover, next working day" if i % 2 else "Security control room"))
    for i in range(1, 21)
]


def test_a_value_that_says_none_answers_a_question_asking_which_have_none():
    """BUG-613: "which departments have no out-of-hours route?" was answered "every department
    has an out-of-hours route value recorded" — true of the FIELD, false of the building."""
    facts = register_facts(DEPARTMENTS, "Which departments have no out-of-hours route?")
    line = next(l for l in facts.splitlines() if "state that there is NONE" in l)
    assert "10 record(s)" in line and "DEP-01" in line and "DEP-02" not in line


def test_a_question_not_about_absence_gets_no_such_line():
    facts = register_facts(DEPARTMENTS, "Who do I contact out of hours?")
    assert "state that there is NONE" not in facts


def test_a_field_with_no_none_like_values_produces_no_line():
    rows = [_row(recordId="A", recordStatus="active", outOfHoursRoute="Security control room")]
    assert "NONE" not in register_facts(rows, "Which departments have no out-of-hours route?")


SESSIONS = [
    _row(recordId=f"TS-{i:04}", recordStatus=("scheduled" if i > 17 else "completed"))
    for i in range(1, 24)
]


def test_a_question_word_that_is_also_a_status_gets_both_readings():
    """CAVEAT-604: "which teaching sessions are scheduled in Room 1.06?" answered six — the
    records whose recordStatus is 'scheduled' — of the 23 the room holds."""
    facts = register_facts(SESSIONS, "Which teaching sessions are scheduled in Room 1.06?")
    line = next(l for l in facts.splitlines() if l.startswith("- CAREFUL"))
    assert "'scheduled' is also a recorded STATUS" in line
    # The wording changed when the instruction stopped DESCRIBING the shape and started
    # writing the sentence out: reporting the status count alone happened about one run in
    # three otherwise. What must hold is that both numbers are present and the total is
    # named as the total.
    assert "23 records in total" in line
    # The sentence it dictates must not assume WHAT holds the rows. It said "The room holds",
    # right for this timetable and wrong for every other register the same rule fires on —
    # washroom and server-room answers opened by calling their register a room.
    assert "room holds" not in line.lower()


def test_the_opening_sentence_does_not_call_a_non_room_register_a_room():
    """The same rule, fired by a register that has nothing to do with rooms."""
    permits = [
        {"recordStatus": "open" if i % 3 else "closed", "id": f"PTW-{i:03d}"}
        for i in range(1, 10)
    ]
    facts = register_facts(permits, "Which permits are open?")
    careful = [l for l in facts.splitlines() if l.startswith("- CAREFUL")]
    assert careful, "the status-word rule was expected to fire for 'open'"
    assert "room" not in careful[0].lower()
    assert "9 records in total" in careful[0]


def test_a_question_that_does_not_use_a_status_word_gets_no_warning():
    assert "CAREFUL" not in register_facts(SESSIONS, "Which sessions are in Room 1.06?")


PLANT = [
    _row(recordId="AEP-015", recordStatus="active", lastVisited="2026-06-08",
         inspectionIntervalDays="365"),
    _row(recordId="AEP-016", recordStatus="active", lastVisited="2025-10-15",
         inspectionIntervalDays="365"),
    _row(recordId="AEP-017", recordStatus="active", lastVisited="2025-09-12",
         inspectionIntervalDays="180"),
]


def test_longest_unseen_is_computed_not_read_off_the_interval_column():
    """Probe: 'which rarely visited plant areas have the longest blind intervals?' named the two
    meters with a 365-day INTERVAL, neither of them due, over an exhaust fan 369 days unseen
    against a 180-day interval."""
    facts = register_facts(PLANT, "Which rarely visited plant areas have the longest blind intervals?",
                           date(2026, 9, 16))
    elapsed = next(l for l in facts.splitlines() if "Days since lastVisited" in l)
    assert elapsed.index("AEP-017") < elapsed.index("AEP-016") < elapsed.index("AEP-015")
    assert "AEP-017 369d (+189d" in elapsed
    past = next(l for l in facts.splitlines() if l.startswith("- PAST its"))
    assert "AEP-017 by 189d" in past and "AEP-016" not in past


def test_a_question_not_about_elapsed_time_gets_no_such_lines():
    facts = register_facts(PLANT, "Which assets are in the service room?", date(2026, 9, 16))
    assert "Days since" not in facts


def test_without_today_nothing_is_computed():
    assert "Days since" not in register_facts(PLANT, "longest blind interval?", None)
