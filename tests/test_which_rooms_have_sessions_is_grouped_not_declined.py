# -*- coding: utf-8 -*-
"""Wave 2 (2D-06): "which rooms have X" is a grouping, counted, not a decline (BUG-811 class).

Measured live 2026-09-19: "Which rooms have teaching sessions this week?" reached the register
lane, the timetable holds 675 sessions with a room on every one, and the answer was "the
building's records do not contain any information about teaching sessions ... the data only lists
how many sensors are installed in each space". The register is past the hand-over limit (675 rows
against a 120-row budget) and the question names no room to scope by, so the lane declined and a
generated query answered about something else entirely.

Counting records per value is an aggregation. With the rows in hand it is done here; for a
register too large to hand over, the same lines are built from a GROUP BY the graph runs. Both
paths are checked below against the register documents, and the period the answer was NOT
narrowed by ("this week") has to be said rather than ignored.
"""

from __future__ import annotations

import re
from collections import Counter
from datetime import date

import pytest

from orchestrator.services import register_projection as rp
from tests.register_fixture_rows import ground_truth, lifted_rows

pytestmark = pytest.mark.unit

TODAY = date(2026, 9, 19)
SESSION_TERMS = ("timetabled session", "teaching session", "teaching sessions", "timetable")


# ── which questions are groupings, and which are not ─────────────────────────────────────────────


@pytest.mark.parametrize(
    "question, expected",
    [
        ("Which rooms have teaching sessions this week?", "room"),
        ("Which rooms have bookings?", "room"),
        ("What rooms have sessions today?", "room"),
        ("Which floors have overdue assets?", "floor"),
    ],
)
def test_a_grouping_question_names_the_column_it_groups_by(question, expected):
    assert expected in rp.grouping_words(question)


@pytest.mark.parametrize(
    "question",
    [
        "Which rooms are quiet?",  # a filter over records, not a grouping
        "Which refuge points are defective?",
        "Who owns the refuge points?",
        "Which permits are open?",
        "How many rooms are there?",
        "Which records have no owner?",
    ],
)
def test_an_ordinary_register_question_is_not_read_as_a_grouping(question):
    assert rp.grouping_words(question) == ()


def test_the_period_the_answer_does_not_filter_by_is_named(
    question="Which rooms have sessions this week?",
):
    assert rp.unfiltered_periods(question) == ["this week"]
    assert rp.unfiltered_periods("Which rooms have sessions?") == []


# ── with the rows in hand ────────────────────────────────────────────────────────────────────────


def test_the_timetable_is_grouped_by_room_with_the_counts_the_table_holds():
    rows, _label = lifted_rows("timetabled_sessions.md")
    text = rp.deterministic_answer(
        rows,
        "Which rooms have teaching sessions this week?",
        "Timetabled session",
        TODAY,
        register_terms=SESSION_TERMS,
    )
    truth = Counter(r["room"] for r in ground_truth("timetabled_sessions.md"))
    assert text.startswith(f"**{len(truth)} rooms** appear on the {sum(truth.values())} records")
    top, count = truth.most_common(1)[0]
    assert f"- **{top}** — {count}" in text
    # every printed count is the table's own
    for value, printed in re.findall(r"- \*\*(.+?)\*\* — (\d+)$", text, re.MULTILINE):
        assert truth[value] == int(printed), (value, printed, truth[value])


def test_the_answer_says_it_was_not_narrowed_to_the_week_asked_about():
    rows, _label = lifted_rows("timetabled_sessions.md")
    text = rp.deterministic_answer(
        rows,
        "Which rooms have teaching sessions this week?",
        "Timetabled session",
        TODAY,
        register_terms=SESSION_TERMS,
    )
    assert "every record the register holds" in text and "this week" in text


def test_a_small_register_groups_too_and_uses_the_askers_word():
    rows, _label = lifted_rows("room_bookings.md")
    text = rp.deterministic_answer(rows, "Which rooms have bookings?", "Room booking", TODAY)
    truth = Counter(r["room"] for r in ground_truth("room_bookings.md"))
    assert text.startswith(f"**{len(truth)} rooms** appear on the {sum(truth.values())} records")
    assert "locations" not in text  # the asker said rooms


def test_a_grouping_column_the_register_does_not_hold_is_left_to_the_narration():
    rows, label = lifted_rows("maintenance_log.md")
    assert rp.deterministic_answer(rows, "Which floors have work orders?", label, TODAY) == ""


def test_two_candidate_columns_are_refused_rather_than_guessed():
    assert rp.grouping_column(["onFloor", "floorServed"], ["floor"]) is None
    assert rp.grouping_column(["locationText"], ["room", "location"]) == "locationText"
    assert rp.grouping_column(["recordStatus"], ["room"]) is None


# ── "which X have no Y": the reported live defect, and its shape across registers ───────────────


def test_the_live_no_owner_question_is_answered_from_the_column_that_holds_one():
    """Live 2026-09-19: "Which provisions have no owner?" was answered "none of the approval
    provisions have an owner recorded" — every one of the 32 approvals carries an accountable
    role. The answer is the opposite claim, and it is computed from the blank cells."""
    rows, _label = lifted_rows("approval_evidence_register.md")
    text = rp.deterministic_answer(
        rows, "Which provisions have no owner?", "Approval and evidence record", TODAY
    )
    assert text.startswith("**None of the 32 records")
    # both readings of "no owner" are reported: no empty cell, and no value that says none
    assert "has no owner" in text
    assert "every one records one" in text and "none of them records that there is none" in text


@pytest.mark.parametrize(
    "document, label, question, column",
    [
        (
            "approval_evidence_register.md",
            "Approval and evidence record",
            "Which approvals have no evidence reference recorded?",
            "evidence_ref",
        ),
        (
            "fire_safety.md",
            "Fire safety asset",
            "Which fire safety assets have no evidence reference recorded?",
            "evidence_ref",
        ),
        (
            "maintenance_log.md",
            "Work order",
            "Which work orders have no completed date recorded?",
            "completed_on",
        ),
    ],
)
def test_a_blank_field_question_names_exactly_the_records_with_an_empty_cell(
    document, label, question, column
):
    text = rp.deterministic_answer(*lifted_rows(document)[:1], question, label, TODAY)
    expected = sorted(r["_id"] for r in ground_truth(document) if not r[column])
    assert expected, document
    listed = sorted(set(re.findall(r"\*\*([A-Z][\w.-]*-[\w.-]+)\*\*", text)))
    assert listed == expected, (document, listed, expected)
    assert f"{len(expected)} of the" in text


# ── the lane path: a register too large to hand over ─────────────────────────────────────────────


def test_the_lines_are_built_from_counts_the_graph_returns():
    pairs = [("Room 1.06 - Computer Laboratory", 23), ("Room 2.15 - Seminar Room", 24)]
    lines = rp.grouping_lines(pairs, "Timetabled session", "room", 675, ["this week"])
    text = "\n".join(lines)
    assert text.startswith(
        "**2 rooms** appear on the 675 records in the Timetabled session register"
    )
    assert text.index("Room 2.15") < text.index("Room 1.06")  # largest group first
    assert "this week" in text


def test_a_register_where_nothing_records_the_field_says_so():
    text = "\n".join(rp.grouping_lines([], "Timetabled session", "room", 675))
    assert text.startswith("**No room is recorded**")


def test_the_lane_asks_the_graph_to_count_before_it_declines_an_oversized_register():
    import inspect

    from orchestrator.agents.sparql_agent import SPARQLAgent

    src = inspect.getsource(SPARQLAgent._whole_register)
    assert "_register_grouping" in src
    assert src.index("_register_grouping") < src.index("falling back to a generated query")
    grouping = inspect.getsource(SPARQLAgent._register_grouping)
    assert "COUNT(DISTINCT ?record)" in grouping and "GROUP BY" in grouping
    # one field or nothing: grouping by the wrong column files records under the wrong heading
    assert "if len(by_predicate) != 1:" in grouping
    # the total is the register's own size, never the sum of the groups
    assert "record.instances" in grouping
