# -*- coding: utf-8 -*-
"""Wave 5 (2D-06): a question naming a record id reaches the register that holds that id.

Scored on the live build, the register oracle read 75/94, and most of the 19 failures named a
record by its identifier and were sent to the wrong register:

    "Who owns CLN-0010?"            -> the APPROVALS register, which then said, honestly and
                                       uselessly, that it does not record CLN-0010 — while the
                                       cleaning-task register holds it, owned by the Caretaking
                                       Supervisor.
    "What is the name of WS-28?"    -> "I don't have that specific information on record", over
                                       a register holding WS-28 = "Meeting room 5.18".

An id is DATA, not vocabulary: the prefix of every record id is read from the records themselves
(one grouped query, cached with the class list), so a building that names its rows differently is
served without configuration. A prefix two registers share decides nothing, and the word scoring
runs as before — which is what keeps CL (cost lines) and CLN (cleaning tasks) apart.

The index here is built from the real register documents, so the prefixes are the building's own.
"""

from __future__ import annotations

from datetime import date

import pytest

from orchestrator.services import record_registry as rr
from orchestrator.services import register_projection as rp
from tests.register_fixture_rows import document_names, ground_truth, lifted_rows

pytestmark = pytest.mark.unit

TODAY = date(2026, 9, 19)

#: document -> the class its records are lifted into, as the mapping declares
_CLASS_OF = {
    "cleaning_task_register.md": "CleaningTask",
    "workspace_profile_register.md": "WorkspaceProfile",
    "cost_line_register.md": "CostLine",
    "approval_evidence_register.md": "ApprovalRecord",
    "evacuation_and_peeps.md": "EvacuationProvision",
    "permit_to_work_register.md": "Permit",
    "coshh_and_lev.md": "HazardControl",
    "department_directory.md": "Department",
    "circulation_times.md": "CirculationTime",
    "service_schedules.md": "ServiceSchedule",
    "accessible_route_register.md": "AccessibleRoute",
    "competency_requirements.md": "CompetencyRecord",
}


def _prefix(record_id: str) -> str:
    return "".join(c for c in record_id if c.isalpha() or not c.isalnum()).split("-")[0].upper()


@pytest.fixture(scope="module")
def building():
    """(classes, prefix index) built from the building's own register documents."""
    pairs = []
    classes = []
    for document, local_name in _CLASS_OF.items():
        rows, label = lifted_rows(document)
        classes.append(
            rr.RecordClass(local_name, label, len(rows), rr._terms_for(local_name, label))
        )
        for row in rows:
            ident = rp._value(row, "recordId")
            if ident:
                pairs.append((local_name, _prefix(ident)))
    return classes, rr.index_id_prefixes(pairs)


# ── the live failures ────────────────────────────────────────────────────────────────────────────


@pytest.mark.parametrize(
    "question, expected",
    [
        ("Who owns CLN-0010?", "CleaningTask"),
        ("Briefly: What is the name of WS-28?", "WorkspaceProfile"),
        ("Who is accountable for CL-2026-012?", "CostLine"),
        ("Briefly: When is APR-029 due for review?", "ApprovalRecord"),
        ("For my notes: When is EV-011 due for review?", "EvacuationProvision"),
        ("How many permits like PTW-2026-0416 are open?", "Permit"),
        ("For the audit record: When is HZ-012 next due for testing?", "HazardControl"),
        ("What are the responds within hours for DEP-01?", "Department"),
        ("Could you tell me: how long is CIRC-06?", "CirculationTime"),
        ("For my notes: When was SVC-01 last completed?", "ServiceSchedule"),
        ("Which lift does RTE-001 depend on?", "AccessibleRoute"),
        # an id written in words, not numbers
        ("What does CMP-ROOF require?", "CompetencyRecord"),
    ],
)
def test_the_register_holding_the_id_is_selected(building, question, expected):
    classes, index = building
    picked = rr.class_for_record_id(question, classes, index)
    assert picked is not None and picked.local_name == expected, question


def test_a_similar_prefix_is_not_confused_with_another_registers(building):
    """CL-2026-011 is a cost line and CLN-0010 a cleaning task: the prefix is the whole of it."""
    classes, index = building
    assert rr.class_for_record_id("Who owns CL-2026-011?", classes, index).local_name == "CostLine"
    assert rr.class_for_record_id("Who owns CLN-0010?", classes, index).local_name == "CleaningTask"
    assert "CL" in index and "CLN" in index and index["CL"] != index["CLN"]


def test_the_id_beats_the_words_that_name_another_register(building):
    """ "Who owns CLN-0010?" says "owns", which every register answers, and CLN-0010, which one
    register holds. The id decides."""
    classes, index = building
    rr._ID_PREFIXES.clear()
    rr._ID_PREFIXES.update(index)
    try:
        assert rr.held_record_class("Who owns CLN-0010?", classes).local_name == "CleaningTask"
        assert (
            rr.held_record_class("What is the name of WS-28?", classes).local_name
            == "WorkspaceProfile"
        )
    finally:
        rr._ID_PREFIXES.clear()


# ── what must NOT be read as a record id ─────────────────────────────────────────────────────────


@pytest.mark.parametrize(
    "question",
    [
        "Which rooms have good Wi-Fi?",
        "Which routes are step-free?",
        "Is there a room on floor 3?",
        "Which permits are open?",
        "Who owns the refuge points?",
        "What happens out-of-hours?",
    ],
)
def test_a_question_naming_no_id_is_left_to_the_word_scoring(building, question):
    classes, index = building
    assert rr.class_for_record_id(question, classes, index) is None, question


def test_an_unknown_prefix_decides_nothing(building):
    classes, index = building
    assert rr.class_for_record_id("Who owns ZZZ-0001?", classes, index) is None


def test_a_prefix_two_registers_share_decides_nothing(building):
    """Ambiguity is not a decision: the word scoring runs, as it did before."""
    classes, _index = building
    shared = rr.index_id_prefixes([("CleaningTask", "X"), ("CostLine", "X")])
    assert rr.class_for_record_id("Who owns X-0001?", classes, shared) is None


def test_an_empty_index_changes_nothing(building):
    classes, _index = building
    assert rr.class_for_record_id("Who owns CLN-0010?", classes, {}) is None


def test_a_class_the_building_does_not_hold_is_never_returned(building):
    _classes, index = building
    assert rr.class_for_record_id("Who owns CLN-0010?", [], index) is None


# ── end to end: the right register then answers the asked field ──────────────────────────────────


@pytest.mark.parametrize(
    "document, question, column",
    [
        ("cleaning_task_register.md", "Who owns CLN-0010?", "_owner"),
        ("workspace_profile_register.md", "What is the name of WS-28?", "name"),
    ],
)
def test_the_selected_register_then_answers_from_that_record(document, question, column):
    rows, label = lifted_rows(document)
    ident = question.split()[-1].rstrip("?")
    truth = next(r for r in ground_truth(document) if r["_id"] == ident)
    text = rp.deterministic_answer(rows, question, label, TODAY)
    assert text, question
    assert ident in text and truth[column] in text


def test_every_register_in_the_building_can_be_reached_by_one_of_its_ids():
    """A register whose ids are not recognised is one an id question cannot reach."""
    missing = []
    for document in document_names():
        rows, _label = lifted_rows(document)
        idents = [rp._value(r, "recordId") for r in rows]
        if idents and not any(rr._RECORD_ID_RE.match(i) for i in idents if i):
            missing.append(document)
    assert missing == [], missing
