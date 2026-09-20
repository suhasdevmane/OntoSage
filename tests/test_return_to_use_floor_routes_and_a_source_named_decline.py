# -*- coding: utf-8 -*-
"""2D-06 wave 5: three questions that reached no register, and a decline that named nothing.

Live, on the final held-out run:

* "I need to carry approved service or event materials to another floor. Which authorised route
  is currently suitable?" was answered "the information returned only lists the building's
  floors" while the circulation register holds 21 floor-to-floor routes with the lift each depends
  on and whether the route is Active.
* "Which evidence-based prerequisites remain before each area, asset or service can return to
  authorised use?" was answered from the ONTOLOGY's own property definitions.
* "What current space-inventory view can this planning group use, and which fields must be
  suppressed, aggregated, caveated or confirmed by an owner?" was answered with a table of spaces
  and sensor counts; nothing the building holds is a rule about which fields to suppress, and the
  honest answer says so.
* A compliance-register answer "Which required lone-worker check-ins are ... overdue ...?" came
  back as "I computed an answer but its narration failed the evidence check". The cause was the
  sentence I had just written: it quoted the register's size (82) while the payload carried no
  such number, so the numeric guard read an honest sentence as an unbacked figure. Both halves
  are fixed: the size is in the payload, and a guard suppression now names its source.

The vocabulary lives in the TBox and is read with the router's own scoring, exactly as
``scripts/register_reach.py`` measures it.
"""

from __future__ import annotations

import asyncio
import importlib.util
import sys
from datetime import datetime
from pathlib import Path

import pytest

from orchestrator.services.compliance_register_service import ComplianceRegisterService
from orchestrator.services.numeric_guard import SUPPRESSION_TEXT, guard_payload

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


# ── selection ────────────────────────────────────────────────────────────────────────────────────


@pytest.mark.parametrize(
    "question, held",
    [
        (
            "I need to carry approved service or event materials to another floor. "
            "Which authorised route is currently suitable?",
            "CirculationTime",
        ),
        ("Which route to another floor avoids the lift?", "CirculationTime"),
        (
            "Which evidence-based prerequisites remain before each area, asset or service can "
            "return to authorised use?",
            "AssetStatus",
        ),
        ("What has to happen before the lift can return to service?", "AssetStatus"),
    ],
)
def test_the_question_selects_the_register_that_holds_the_answer(reach, question, held):
    assert reach.register(question)["held"] == held


def test_a_question_about_suppression_rules_names_the_absent_register(reach):
    picked = reach.register(
        "What current space-inventory view can this planning group use, and which fields must "
        "be suppressed, aggregated, caveated or confirmed by an owner?"
    )
    assert picked["held"] is None and picked["absent"] == "DisclosureRule"


@pytest.mark.parametrize(
    "question, not_held",
    [
        # the accessible-route and evacuation registers own a bare "route"
        ("Which accessible route from the drop-off has seated rests?", "CirculationTime"),
        ("Which evacuation route is blocked?", "CirculationTime"),
        ("How many floors does the building have?", "CirculationTime"),
        # a route to a floor is not a return to use
        ("Is the lift in service today?", "DisclosureRule"),
    ],
)
def test_the_new_phrases_do_not_take_neighbouring_questions(reach, question, not_held):
    picked = reach.register(question)
    assert picked["held"] != not_held and picked["absent"] != not_held


# ── the compliance sentence and the guard ────────────────────────────────────────────────────────


def _service(size: int = 82, due_rows=None) -> ComplianceRegisterService:
    service = ComplianceRegisterService.__new__(ComplianceRegisterService)
    service._ns = "http://x/"

    async def _select(query: str):
        if "COUNT" in query:
            return [{"n": str(size)}]
        return list(due_rows or [])

    service._select = _select
    return service


def test_the_no_overdue_sentence_passes_the_numeric_guard():
    """The size it quotes is now in the payload, so it is backed rather than 'unbacked'."""
    out = asyncio.run(
        _service()._overdue(
            "Which required lone-worker check-ins are overdue?", datetime(2026, 9, 20)
        )
    )
    assert "82 checks" in out["formatted_response"] and out["register_size"] == 82
    guarded = guard_payload(out, "register")
    assert guarded["formatted_response"] == out["formatted_response"]
    assert "guard_violations" not in guarded


def test_the_sentence_says_the_register_covers_compliance_checks_only():
    text = asyncio.run(_service()._overdue("anything overdue?", datetime(2026, 9, 20)))[
        "formatted_response"
    ]
    assert "compliance register" in text and "compliance checks only" in text


def test_a_question_the_register_cannot_place_is_not_given_a_due_date_verdict():
    out = asyncio.run(
        _service().answer("What minimum evidence is still missing before the decision?")
    )
    assert out["kind"] == "unplaced"
    assert "Nothing is overdue" not in out["formatted_response"]
    assert "cannot answer what this question asks" in out["formatted_response"]


def test_a_suppressed_narration_names_the_source_it_came_from():
    payload = {
        "success": True,
        "count": 3,
        "source": "compliance register (graph)",
        "formatted_response": "**999 items** are late.",
    }
    text = guard_payload(payload, "register")["formatted_response"]
    assert "compliance register" in text
    assert "narration failed the evidence check" not in text
    assert "I could not confirm every figure" in text


def test_a_suppression_with_no_named_source_keeps_the_standard_text():
    payload = {"success": True, "count": 3, "formatted_response": "**999 items** are late."}
    assert guard_payload(payload, "events")["formatted_response"] == SUPPRESSION_TEXT


# ── the W19 note and a common verb ───────────────────────────────────────────────────────────────


def test_a_common_verb_is_never_the_subject_of_a_correction_note():
    """Live: "**Also recorded in this register:** *start* — recorded as started" was printed under
    an answer about HVAC start and stop times. The register does record a start time; the note
    treated the WORD as though it were a field."""
    from orchestrator.services import register_facts as rf

    rows = [
        {"recordId": "REG-001", "recordStatus": "active", "startedAt": "07:00"},
        {"recordId": "REG-002", "recordStatus": "active", "startedAt": "08:00"},
    ]
    note = rf.false_absence_corrections(
        "The register does not record when systems start.",
        rows,
        sorted(rows[0]),
        "When do the HVAC systems start?",
        "Operating regime",
    )
    assert "start" not in (note or "")
    assert rf._is_a_generic_word("start") and not rf._is_a_generic_word("open")
