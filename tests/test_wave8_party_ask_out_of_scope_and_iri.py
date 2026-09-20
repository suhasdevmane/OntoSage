# -*- coding: utf-8 -*-
"""2D-06 wave 8: the generic owner list, the out-of-scope decline, and an IRI given as an answer.

Measured over the recorded runs (5,143 rows, every dev tail except the held-out K): 12 answers
BEGIN "The register records the owner:". Nine of them answered a question that never asked for an
owner, six distinct questions:

    "What owner-confirmed changes since the last signed handover alter this shift's posts ...?"
    "Which reporting periods ... are not directly comparable because contracts, streams ... changed?"
    "Can People Count data be used to redirect cleaning crews to the most heavily used restrooms?"
    "Which current supplier, producer-responsibility or contractor take-back route applies ...?"
    "Which landlord, utility, supplier ... where does evidence responsibility transfer?"
    "Do current room readings provide any safety clearance for running this experiment alone ...?"

The vocabulary treats "owner", "ownership" and "responsible" as the owner concept wherever they
sit, so a qualifier or a subject noun asked for a party, and the composed answer was the
register's owner list: confident, and about a different question. The three that did ask were
right to get one. The fix is to tell them apart by what the question ASKS.
"""

from __future__ import annotations

import asyncio
import importlib.util
import sys
from datetime import date
from pathlib import Path

import pytest

from orchestrator.services import register_facts as rf
from orchestrator.services import register_projection as rp
from tests.register_fixture_rows import lifted_rows

pytestmark = pytest.mark.unit

TODAY = date(2026, 9, 20)
REPO = Path(__file__).resolve().parents[1]

ASKED = [
    "Who is accountable for every reported outcome, source, threshold, exception and resulting "
    "action, and where is ownership missing?",
    "Who is accountable for the event activities with event EVT-2026-0045?",
    "Which refuge points are defective, and who owns them?",
    "Who owns CLN-0010?",
    "Which patrol checkpoints have a recorded owner and a heartbeat signal?",
    "Which assurance activities were performed by people with the required competence?",
    "Which authorisations are in place for the people assigned to high-risk tasks?",
    "Who is in charge of the Level 5 general waste?",
    "Who is responsible for the lift maintenance contract?",
    "Show me the owners of each permit",
]

NOT_ASKED = [
    "What owner-confirmed changes since the last signed handover alter this shift's posts, "
    "patrols or public interface?",
    "Which reporting periods or service points are not directly comparable because contracts, "
    "streams, occupancy context, measurement methods or service definitions changed?",
    "Can People Count data be used to redirect cleaning crews to the most heavily used restrooms?",
    "Which current supplier, producer-responsibility or contractor take-back route applies to a "
    "specific purchased item or material?",
    "Which landlord, utility, supplier, maintenance, cloud or shared services fall inside the "
    "boundary, and where does evidence responsibility transfer?",
    "What safety evidence is still missing before the proposed change can be presented to the "
    "responsible owner for a start, approval or commissioning decision?",
    "Is the proposed cost eligible against the current fund, project, cost centre, ownership and "
    "benefit-period rules before procurement starts?",
]


@pytest.mark.parametrize("question", ASKED)
def test_a_question_that_asks_for_a_party_is_recognised(question):
    assert rp.asks_for_a_party(question), question


@pytest.mark.parametrize("question", NOT_ASKED)
def test_a_question_that_only_contains_the_word_is_not_one(question):
    assert not rp.asks_for_a_party(question), question


def test_a_denial_is_not_filled_with_an_owner_list_nobody_asked_for():
    """The narration says the register does not record something; the old guard answered by
    printing the owners. With no owner asked for, the denial stands."""
    rows, label = lifted_rows("patrol_checkpoint_register.md")
    narration = (
        "The register does not record owner-confirmed changes since the last handover.\n\n"
        "It holds patrol checkpoints."
    )
    out = rp.guard_narration(
        narration,
        rows,
        "What owner-confirmed changes since the last signed handover alter this shift's posts?",
        label,
        TODAY,
    )
    assert "The register records the owner" not in out
    assert "does not record owner-confirmed changes" in out


def test_a_denial_of_an_owner_that_was_asked_for_is_still_replaced():
    rows, label = lifted_rows("evacuation_and_peeps.md")
    narration = "The register does not record who owns the refuge points."
    out = rp.guard_narration(narration, rows, "Who owns the refuge points?", label, TODAY)
    assert "does not record who owns" not in out
    assert "Building Fire Warden Coordinator" in out


# ── the decline ─────────────────────────────────────────────────────────────────────────────────

DECLINES = [
    (
        "patrol_checkpoint_register.md",
        "What owner-confirmed changes since the last signed handover alter this shift's posts, "
        "patrols or public interface?",
    ),
    (
        "contract_register.md",
        "Which reporting periods or service points are not directly comparable because contracts, "
        "streams, occupancy context, measurement methods or service definitions changed?",
    ),
    (
        "cleaning_task_register.md",
        "Can People Count data be used to redirect cleaning crews to the most heavily used "
        "restrooms?",
    ),
    (
        "asset_engineering_register.md",
        "Which asset identifiers, locations, controlled drawings or controller configurations "
        "conflict between the asset register, the drawings and the BMS?",
    ),
]

ANSWERS = [
    (
        "competency_requirements.md",
        "Do current authorisations and competence records exist for the people assigned to "
        "the named equipment or high-risk task?",
    ),
    (
        "approval_evidence_register.md",
        "Which assurance activities were performed by people with the required competence and "
        "independence?",
    ),
    ("cleaning_task_register.md", "Who owns CLN-0010?"),
    ("cleaning_task_register.md", "Which cleaning tasks are overdue?"),
    ("evacuation_and_peeps.md", "Which refuge points are defective, and who owns them?"),
    ("department_directory.md", "Which departments have no out-of-hours route?"),
    (
        "continuity_provision_register.md",
        "Which critical services depend on networks or cloud platforms, and what safe local "
        "function remains?",
    ),
]


@pytest.mark.parametrize("document, question", DECLINES)
def test_a_question_the_register_holds_none_of_gets_one_sentence_naming_it(document, question):
    rows, label = lifted_rows(document)
    text = rp.out_of_scope_decline(rows, question, label, TODAY)
    assert text, question
    assert f"({len(rows)} records) cannot answer this" in text
    assert "it records" in text and "nothing about" in text
    assert "\n" not in text, "one sentence, not a listing"


@pytest.mark.parametrize("document, question", ANSWERS)
def test_a_question_the_register_can_speak_to_is_never_declined(document, question):
    rows, label = lifted_rows(document)
    assert rp.out_of_scope_decline(rows, question, label, TODAY) == "", question


def test_the_decline_reaches_the_reader_without_asking_the_model_or_reading_another_register():
    rows, label = lifted_rows("patrol_checkpoint_register.md")

    async def refuse(_cls):
        raise AssertionError("another register was read to write a decline")

    text = asyncio.run(
        rp.answer_before_narration(
            DECLINES[0][1], rows, label, "PatrolCheckpoint", [], refuse, TODAY, False
        )
    )
    assert "cannot answer this" in text


def test_a_partial_read_is_never_declined_on_the_strength_of_missing_rows():
    rows, label = lifted_rows("patrol_checkpoint_register.md")

    async def refuse(_cls):
        raise AssertionError("not read")

    text = asyncio.run(
        rp.answer_before_narration(
            DECLINES[0][1], rows, label, "PatrolCheckpoint", [], refuse, TODAY, True
        )
    )
    assert text == ""


# ── an instruction to query the system is never an answer ───────────────────────────────────────


def test_a_sentence_handing_the_reader_a_class_iri_is_removed():
    text = (
        "Work orders carry a status.\n"
        "There are 24 instances of http://ontosage.org/capabilities#WorkOrder in the graph.\n"
        "Open ones are listed above."
    )
    out = rf.strip_query_instructions(text)
    assert "http://" not in out and "ontosage" not in out.lower()
    assert "Work orders carry a status." in out and "Open ones are listed above." in out


def test_an_answer_that_is_only_an_iri_instruction_becomes_empty_for_the_caller_to_replace():
    assert rf.strip_query_instructions("Query ontosage:WorkOrder to see them.") == ""


def test_the_register_guard_never_returns_the_instruction():
    rows, label = lifted_rows("maintenance_log.md")
    out = rp.guard_narration(
        "Check the records. Instances of http://ontosage.org/capabilities#WorkOrder hold them.",
        rows,
        "Which assigned tasks are open?",
        label,
        TODAY,
    )
    assert "ontosage" not in out.lower()


def test_a_normal_answer_is_left_exactly_as_it_was():
    text = "**9 of the 24 records in the Work order register match**."
    assert rf.strip_query_instructions(text) == text


# ── selection: the past tense and the assigned task ─────────────────────────────────────────────


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
    meta, _rows = harness.read_guard(REPO / "docs" / "phase0" / "guard_set.jsonl")
    return harness.Reach(harness.load_schema(), meta["snapshot"])


@pytest.mark.parametrize(
    "question",
    [
        "When was the last time that the furnace was serviced?",
        "Which assigned tasks are now at real risk of missing their required completion time?",
    ],
)
def test_the_service_and_assigned_task_questions_select_the_work_orders(reach, question):
    assert reach.register(question)["held"] == "WorkOrder"


@pytest.mark.parametrize(
    "question",
    [
        "Since the equipment was serviced, have room and service conditions been more stable?",
        "What is the temperature in Room 5.01?",
    ],
)
def test_the_new_phrases_do_not_take_a_reading_question(reach, question):
    assert reach.register(question)["held"] != "WorkOrder"
