# -*- coding: utf-8 -*-
"""2D-06 / BUG-829: a conclusion about a whole subject is not one register's to draw.

"Is the building up to date with its fire safety inspections?" was answered "the building is up to
date ... none are overdue" from the compliance-check register (82 records, none past due), beside
a fire safety asset register in which FSA-027, the dry riser's annual pressure test, is overdue
since 5 May 2026 with no evidence reference. Each register was right about itself; the conclusion
belonged to the subject.

The compliance rows here are built by hand in the shape the graph gives them (no record id, a due
date and a completion date, status open or done); the fire safety rows are the building's own
register, lifted from input/documents.
"""

from __future__ import annotations

import asyncio
from dataclasses import dataclass
from datetime import date
from typing import Any, List, Tuple

import pytest

from orchestrator.services import register_projection as rp
from tests.register_fixture_rows import lifted_rows

pytestmark = pytest.mark.unit

TODAY = date(2026, 9, 19)
QUESTION = "Is the building up to date with its fire safety inspections?"


@dataclass
class _Cls:
    """The three things a RecordClass gives the cross-register check."""

    local_name: str
    label: str
    terms: Tuple[str, ...]


COMPLIANCE = _Cls(
    "ComplianceCheck",
    "Compliance check",
    ("compliance", "compliance check", "compliance checks", "inspection", "inspections"),
)
FIRE = _Cls(
    "FireSafetyAsset",
    "Fire safety asset",
    ("fire alarm", "fire door", "fire safety asset", "fire safety assets", "extinguisher"),
)
SERVICE = _Cls(
    "ServiceSchedule",
    "Service schedule entry",
    ("maintenance schedule", "planned maintenance", "service schedule"),
)
CLASSES = [COMPLIANCE, FIRE, SERVICE]


def _cell(value: str):
    return {"type": "literal", "value": value}


def _compliance_rows(open_past_due: int = 0) -> List[dict]:
    """72 done (due long ago, completed) and 10 open (due ahead) — the live register's shape."""
    rows = []
    for i in range(72):
        rows.append(
            {
                "record": _cell(f"http://example.org/bldg/check/done{i}"),
                "label": _cell(f"Fire risk assessment review {i}"),
                "recordStatus": _cell("done"),
                "dueDate": _cell("2025-06-01T04:31:24"),
                "completedDate": _cell("2025-05-20T01:31:24"),
            }
        )
    for i in range(10):
        due = "2026-05-01T00:00:00" if i < open_past_due else "2026-10-23T00:00:00"
        rows.append(
            {
                "record": _cell(f"http://example.org/bldg/check/open{i}"),
                "label": _cell(f"Fire door quarterly inspection {i}"),
                "recordStatus": _cell("open"),
                "dueDate": _cell(due),
                "completedDate": _cell(""),
            }
        )
    return rows


def _run(question: str, primary_rows, primary_cls, fetch, classes=None) -> str:
    return asyncio.run(
        rp.cross_register_answer(
            question,
            primary_rows,
            primary_cls.label,
            primary_cls.local_name,
            classes or CLASSES,
            fetch,
            TODAY,
        )
    )


async def _fire_rows(_cls: Any):
    rows, _label = lifted_rows("fire_safety.md")
    return rows


def test_the_compliance_register_alone_says_nothing_overdue():
    """The setup of the live defect: taken by itself, that register is right."""
    rows = _compliance_rows()
    info = rp.overdue_info(rows, rp._all_columns(rows), TODAY)
    assert info.basis == "due" and not info.computed and not info.recorded


def test_the_fire_safety_register_is_read_too_and_its_overdue_assets_are_named():
    text = _run(QUESTION, _compliance_rows(), COMPLIANCE, _fire_rows)
    assert text.startswith("**No —")
    assert "up to date" in text.splitlines()[0]  # says it is NOT up to date, and when
    assert "FSA-027" in text and "5 May 2026" in text
    assert "FSA-001" in text
    assert "Compliance check register" in text and "none overdue" in text


def test_only_registers_named_by_the_subject_are_read():
    """The service schedule shares no two-word phrase with the question, so it is not pulled in."""
    picked = rp.related_classes(QUESTION, CLASSES, "ComplianceCheck")
    assert [c.local_name for c in picked] == ["FireSafetyAsset"]


def test_when_every_register_is_clean_the_answer_is_scoped_to_what_was_read():
    async def _clean(_cls):
        rows, _label = lifted_rows("fire_safety.md")
        for row in rows:
            row["recordStatus"]["value"] = "active"
            row["nextTestDue"]["value"] = "2027-01-01"
        return rows

    text = _run(QUESTION, _compliance_rows(), COMPLIANCE, _clean)
    assert "Nothing is recorded as overdue" in text
    assert "not a statement about anything they do not cover" in text
    assert "Compliance check register" in text and "Fire safety asset register" in text
    assert not text.startswith("**No —")


def test_an_open_record_past_its_due_date_is_overdue_and_a_done_one_is_not():
    rows = _compliance_rows(open_past_due=3)
    info = rp.overdue_info(rows, rp._all_columns(rows), TODAY)
    assert len(info.computed) == 3
    assert all(rows[i]["recordStatus"]["value"] == "open" for i in info.computed)


def test_a_register_that_cannot_be_read_is_named_not_silently_dropped():
    async def _broken(_cls):
        raise RuntimeError("graph timeout")

    text = _run(QUESTION, _compliance_rows(open_past_due=2), COMPLIANCE, _broken)
    assert "Not read: the Fire safety asset register" in text
    assert "2 overdue" in text  # what could be read is still reported


def test_a_register_with_no_dates_at_all_says_it_cannot_show_this():
    async def _undated(_cls):
        return [
            {
                "record": _cell("http://x/1"),
                "recordId": _cell("A-1"),
                "recordStatus": _cell("active"),
            }
        ]

    text = _run(QUESTION, _compliance_rows(open_past_due=1), COMPLIANCE, _undated)
    assert "records no due date and no overdue status" in text


def test_nothing_is_composed_when_no_register_records_a_date():
    async def _undated(_cls):
        return [
            {
                "record": _cell("http://x/1"),
                "recordId": _cell("A-1"),
                "recordStatus": _cell("active"),
            }
        ]

    plain = [
        {"record": _cell("http://x/2"), "recordId": _cell("B-1"), "recordStatus": _cell("active")}
    ]
    assert _run(QUESTION, plain, COMPLIANCE, _undated) == ""


@pytest.mark.parametrize(
    "question",
    [
        "Which fire safety assets are overdue?",  # a list: the single-register path answers it
        "When was the fire alarm last tested?",
        "How many fire doors are there?",
        "Who owns the fire safety assets?",
    ],
)
def test_only_a_yes_no_question_about_a_subjects_state_is_taken_across_registers(question):
    assert _run(question, _compliance_rows(), COMPLIANCE, _fire_rows) == ""


@pytest.mark.parametrize(
    "question",
    [
        "Is the building up to date with its fire safety inspections?",
        "Are all our statutory inspections up to date?",
        "Are there any overdue fire safety checks?",
        "Is anything overdue?",
        "Are any fire doors overdue for inspection?",
        "Are we compliant with the fire safety schedule?",
    ],
)
def test_the_questions_that_ask_for_a_whole_subjects_state(question):
    assert rp.wants_whole_subject(question)


@pytest.mark.parametrize(
    "question",
    [
        "Which assets are overdue?",
        "How many checks are overdue?",
        "What is the next inspection due date?",
        "Who is responsible for fire safety?",
        "Is the fire alarm weekly test overdue?",  # one named thing, not a whole subject
    ],
)
def test_the_questions_that_do_not(question):
    assert not rp.wants_whole_subject(question)


def test_the_switch_turns_the_cross_register_answer_off(monkeypatch):
    monkeypatch.setenv("REGISTER_PROJECTION_ANSWER", "false")
    assert _run(QUESTION, _compliance_rows(), COMPLIANCE, _fire_rows) == ""


def test_a_partial_register_is_never_counted_as_the_register():
    rows = _compliance_rows()[:5]

    async def _go():
        return await rp.answer_before_narration(
            QUESTION, rows, "Compliance check", "ComplianceCheck", CLASSES, _fire_rows, TODAY, True
        )

    assert asyncio.run(_go()) == ""


def test_the_entry_point_falls_back_to_a_deterministic_lookup_when_it_is_not_a_state_question():
    rows, label = lifted_rows("evacuation_and_peeps.md")

    async def _go():
        return await rp.answer_before_narration(
            "Which refuge points are defective, and who owns them?",
            rows,
            "Evacuation provision",
            "EvacuationProvision",
            [],
            _fire_rows,
            TODAY,
            False,
        )

    text = asyncio.run(_go())
    assert "EV-003" in text and "Building Fire Warden Coordinator" in text
