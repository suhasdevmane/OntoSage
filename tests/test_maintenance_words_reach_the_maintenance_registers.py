# -*- coding: utf-8 -*-
"""2D-06 follow-up: the words a person uses for the maintenance log select a register.

Live, 2026-09-18: "When was the lift last serviced?", "Which assets are overdue for maintenance?"
and "Which maintenance tasks are overdue?" selected NO register (checked with register_reach), so
they fell to generated SPARQL, which answered from the patrol checkpoints or said the building
holds no maintenance information — while 24 work orders and 17 planned service entries are held.

The vocabulary lives in the TBox (``ontosage:layTerms``), read here from the schema file with the
router's own scoring, exactly as ``scripts/register_reach.py`` measures it. Also pinned: what the
new phrases must NOT take — every one is a whole phrase, because a bare word moved eight of the
2,960 catalogue questions on the first attempt and two of those were wrong (a booking question
and two inspection questions pulled to a register that has no due date).
"""

from __future__ import annotations

import importlib.util
import json
import sys
from pathlib import Path

import pytest

pytestmark = pytest.mark.unit

REPO = Path(__file__).resolve().parents[1]
GUARD = REPO / "docs" / "phase0" / "guard_set.jsonl"


def _harness():
    name = "_test_register_reach_harness"
    if name in sys.modules:
        return sys.modules[name]
    spec = importlib.util.spec_from_file_location(name, REPO / "scripts" / "register_reach.py")
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    spec.loader.exec_module(module)
    return module


@pytest.fixture(scope="module")
def reach():
    harness = _harness()
    meta, _rows = harness.read_guard(GUARD)
    return harness.Reach(harness.load_schema(), meta["snapshot"])


@pytest.mark.parametrize(
    "question, held",
    [
        ("When was the lift last serviced?", "WorkOrder"),
        ("When was the main lift last maintained?", "WorkOrder"),
        ("When was the chiller last serviced?", "WorkOrder"),
        ("Show me the maintenance history of the lift", "WorkOrder"),
        ("Which maintenance tasks are overdue?", "WorkOrder"),
        ("Are any maintenance tasks overdue?", "WorkOrder"),
        ("Which assets are overdue for maintenance?", "ServiceSchedule"),
        ("Which maintenance is overdue?", "ServiceSchedule"),
        ("Is any maintenance overdue?", "ServiceSchedule"),
    ],
)
def test_the_maintenance_question_selects_its_register(reach, question, held):
    assert reach.register(question)["held"] == held


@pytest.mark.parametrize(
    "question, held",
    [
        # whole phrases only: these say "maintenance task" or "inspection" in another setting
        (
            "Can the authorised maintenance task fit between reservations without putting the "
            "next booking at risk?",
            "Booking",
        ),
        (
            "Which fire-safety inspections, tests and maintenance tasks fall due within 7, 30 or "
            "90 days, and which are already overdue?",
            "ComplianceCheck",
        ),
        (
            "Which inspections, maintenance tasks and access actions are due, overdue or awaiting "
            "acceptable completion evidence?",
            "ComplianceCheck",
        ),
        ("What is the maintenance contract for the lifts?", "Contract"),
        ("How much did maintenance cost last year?", "CostLine"),
        ("Which assets are overdue for inspection?", "ComplianceCheck"),
    ],
)
def test_the_new_phrases_do_not_take_questions_that_belong_elsewhere(reach, question, held):
    assert reach.register(question)["held"] == held


def test_the_guard_set_still_selects_what_it_selected(reach):
    """The 124 probe, demo and trap questions: not one selects a different register."""
    harness = _harness()
    _meta, rows = harness.read_guard(GUARD)
    violations = [v for v in harness.guard_violations(reach, rows) if v["status"] == "VIOLATION"]
    assert not violations, json.dumps(violations, indent=1)


def test_work_orders_still_hold_no_due_date_in_the_schema():
    """The word 'overdue' is not declared on the work order class: it has no due date, and the
    answer to an overdue question put to it is read from its statuses."""
    text = (REPO / "ontology" / "ontosage_schema.ttl").read_text(encoding="utf-8")
    block = text[text.index("ontosage:WorkOrder ontosage:layTerms") :].split(" .\n", 1)[0]
    assert '"overdue"' not in block
    assert "maintenance tasks are overdue" in block and "last serviced" in block
