"""BUG-1429: "which doors do you have records for?" names the door-event register, not a refuge point.

The question contains no word of any class's vocabulary, so the register selector ranked nothing
and the metadata lane answered with the nearest record it could find. The routing contract now
claims the shape, and the selector ranks the held door-event class (the TBox's AccessEvent) first.

Also pinned here: the schema's measured decision that a BARE "door" is not DoorHardware
vocabulary (ontology/ontosage_schema.ttl). That decision is not reversed by this fix.
"""

import re
from pathlib import Path

import pytest

from orchestrator.services import record_registry as rr
from orchestrator.services import routing_contract as rc

pytestmark = pytest.mark.unit

ROOT = Path(__file__).resolve().parents[1]

ACCESS_TERMS = (
    "access event",
    "access events",
    "door event",
    "door events",
    "entry log",
    "access log",
    "door held open",
    "forced door",
)


def _cls(name, terms, instances=1):
    return rr.RecordClass(
        local_name=name,
        label=name,
        instances=instances,
        terms=tuple(sorted(terms)),
    )


ACCESS = _cls("AccessEvent", ACCESS_TERMS)
FIRE = _cls("FireSafetyAsset", ("fire door", "fire doors", "fire alarm", "smoke detector"))
HARDWARE = _cls(
    "DoorHardware", ("door lock", "door locks", "fail open", "fail secure", "turnstile")
)
EVACUATION = _cls("EvacuationProvision", ("refuge", "refuge point", "refuge points"))


@pytest.mark.parametrize(
    "question",
    [
        "which doors do you have records for?",
        "Which doors do you have records for",
        "do you have door records?",
        "what door records do you hold?",
    ],
)
def test_door_record_questions_are_claimed_by_the_shape(question):
    assert rc.door_records_question(question) is True


@pytest.mark.parametrize(
    "question",
    [
        # fire doors belong to the fire-safety register, never the access events
        "Which fire doors do you have records for?",
        # hardware: the measured DoorHardware decision
        "Which shutters or doors fail open versus fail locked on power loss?",
        # a bare "door" with no record noun
        "Show me all doors currently propped or held open.",
        # a statement is not a question
        "I have door records to share with you.",
        # a single door's log is a different question (AccessEvent by its own term)
        "Give me the access log for the loading bay door since Friday night.",
    ],
)
def test_other_door_shapes_are_not_claimed(question):
    assert rc.door_records_question(question) is False


def test_the_register_selector_names_the_door_event_class_for_the_question():
    q = "which doors do you have records for?"
    ranked = rr.rank_record_classes(q, [ACCESS, FIRE, HARDWARE, EVACUATION])
    assert ranked and ranked[0][1].local_name == "AccessEvent"


def test_the_fire_door_question_is_not_forced_to_the_access_register():
    q = "Which fire doors do you have records for?"
    ranked = rr.rank_record_classes(q, [ACCESS, FIRE, HARDWARE, EVACUATION])
    assert ranked and ranked[0][1].local_name == "FireSafetyAsset"
    assert "AccessEvent" not in {r.local_name for _, r in ranked}


def test_an_absent_door_event_register_invents_no_record():
    # The building holds no access events: the selector must not name a class it does not hold.
    q = "which doors do you have records for?"
    ranked = rr.rank_record_classes(q, [FIRE, HARDWARE, EVACUATION])
    assert "AccessEvent" not in {r.local_name for _, r in ranked}


def test_the_routing_contract_routes_the_question_to_the_register_lane():
    n = {"intent": "capability", "analytics": False, "general": False}
    rc.apply_contract("which doors do you have records for?", n, "parse")
    assert n["intent"] == "metadata"


def test_a_fault_statement_keeps_its_intake_lane():
    # The rule itself, with the intake check forced on: a fault statement files a ticket.
    rule = next(r for r in rc.PARSE_STAGE_RULES if r.name == "door_records_are_a_register_question")
    fake_sr = type(
        "SR",
        (),
        {
            "is_control_command": staticmethod(lambda _q: False),
            "report_intake_intent": staticmethod(lambda _q: "maintenance"),
        },
    )
    ctx = rc._Ctx(
        query="which doors do you have records for?",
        ql="which doors do you have records for?",
        normalized={"intent": "capability"},
        sr=fake_sr,
    )
    assert rule.fn(ctx) is None


def test_the_schema_still_declares_no_bare_door_for_door_hardware():
    # ontology/ontosage_schema.ttl records the measured 2026-09-17 decision that bare "door" and
    # "doors" asked about door HARDWARE in about two of seven reads. This fix must not reverse it.
    text = (ROOT / "ontology" / "ontosage_schema.ttl").read_text(encoding="utf-8")
    m = re.search(r"ontosage:DoorHardware ontosage:layTerms(.*?)\.\s*$", text, re.M | re.S)
    assert m, "DoorHardware layTerms block not found"
    block = m.group(1)
    assert '"door"' not in block and '"doors"' not in block
