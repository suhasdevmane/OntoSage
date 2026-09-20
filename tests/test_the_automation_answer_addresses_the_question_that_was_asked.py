# -*- coding: utf-8 -*-
"""'Can the building alert someone to a task?' is not a question about a measured quantity (C19).

Two questions on the 2026-09-18 held-out reads -- "can the building alert someone to a task?" and
"is there a manual override for standby mode?" -- were both answered with "I couldn't tell which
measured quantity the condition corresponds to ... No notification channel is set up", which
answers neither. The lane now tells three kinds of question apart and answers each as asked, from
what the building holds (measured quantities, record classes, rules, channels), read live.

A question that identifies a measured quantity keeps the answers pinned by
test_the_building_says_what_it_measures; this file pins the rest.
"""

from __future__ import annotations

import asyncio
from types import SimpleNamespace

import pytest

from orchestrator.services import automation_answer as aa
from orchestrator.workflow import _orchestrator as mod
from shared.models import ConversationState, Message

pytestmark = pytest.mark.unit


def _run(coro):
    return asyncio.run(coro)


# ── which kind of question is it ─────────────────────────────────────────────


@pytest.mark.parametrize(
    "question,kind",
    [
        ("Is there a manual override for standby mode?", aa.KIND_OVERRIDE),
        ("Can I switch the ventilation off from here?", aa.KIND_OVERRIDE),
        ("Can I take manual control of the lights?", aa.KIND_OVERRIDE),
        ("Can the building alert someone to a task?", aa.KIND_TASK),
        ("Can it notify the cleaners when a bin is full?", aa.KIND_TASK),
        ("Can it remind staff about the overdue inspection?", aa.KIND_TASK),
        ("Can the building automatically alert me when CO2 gets too high?", aa.KIND_QUANTITY),
        ("Can it monitor energy use and notify me if it spikes?", aa.KIND_QUANTITY),
        ("Could the building send me a message if there is a fault?", aa.KIND_QUANTITY),
    ],
)
def test_the_kind_of_question_is_read_from_its_wording(question, kind):
    assert aa.question_kind(question) == kind


# ── the answers ──────────────────────────────────────────────────────────────

FACTS = aa.Facts(
    building="Example Building",
    measured=["CO2", "humidity", "temperature"],
    record_labels=["Waste collection point", "Work order"],
    rules=[aa.RuleView("CO2 elevated in a room", "co2"), aa.RuleView("Damp on a floor", "damp")],
    delivers=False,
    for_admin=False,
)


def test_an_override_question_is_told_plainly_that_this_service_does_not_operate_equipment():
    text = aa.compose(aa.KIND_OVERRIDE, FACTS)
    assert text.startswith("**This service cannot operate equipment or override a mode.**")
    assert "control system" in text
    assert "CO2" in text, "what it CAN tell is offered: the readings that show the effect"
    assert "couldn't tell which measured quantity" not in text


def test_a_task_question_says_alerts_come_from_measurements_not_tasks():
    text = aa.compose(aa.KIND_TASK, FACTS)
    assert text.startswith("**Not on its own.**")
    assert "Waste collection point" in text and "no rule watches them" in text
    assert "2 rules are set up: CO2 elevated in a room and Damp on a floor." in text
    assert aa.NO_CHANNEL in text


def test_an_overview_names_what_it_watches_the_rules_and_the_channel():
    text = aa.compose(aa.KIND_QUANTITY, FACTS)
    assert "CO2, humidity and temperature" in text
    assert "Standing rules" in text
    assert aa.NO_CHANNEL in text
    assert "operate equipment" in text


def test_a_delivering_channel_is_reported_and_no_remediation_is_offered_to_a_reader():
    facts = aa.Facts(building="B", measured=["noise"], delivers=True)
    text = aa.compose(aa.KIND_TASK, facts)
    assert "configured channel" in text and aa.NO_CHANNEL not in text
    assert "channels.yaml" not in text


def test_only_an_administrator_is_told_how_to_add_a_channel():
    reader = aa.Facts(building="B", measured=["noise"], delivers=False, for_admin=False)
    admin = aa.Facts(building="B", measured=["noise"], delivers=False, for_admin=True)
    assert "channels.yaml" not in aa.compose(aa.KIND_TASK, reader)
    assert "channels.yaml" in aa.compose(aa.KIND_TASK, admin)


def test_no_rules_is_said_as_no_rules_never_as_no_capability():
    text = aa.compose(aa.KIND_TASK, aa.Facts(building="B", measured=["noise"]))
    assert "none are set up, so nothing is being watched for you yet" in text


def test_a_building_that_reports_nothing_is_not_padded_with_a_guess():
    text = aa.compose(aa.KIND_OVERRIDE, aa.Facts(building="B"))
    assert "What I can tell you" not in text


def test_the_rules_are_read_from_the_engine_that_runs_them(monkeypatch, tmp_path):
    from orchestrator.services import rules_engine as re_mod

    (tmp_path / "rules.yaml").write_text(
        "rules:\n"
        "  - id: co2_high\n    name: CO2 too high\n    enabled: true\n"
        "    trigger: {concept: co2, op: '>', threshold: 1000, scope: all}\n"
        "    action: {type: notify, message: x}\n"
        "  - id: off_rule\n    name: Disabled rule\n    enabled: false\n"
        "    trigger: {concept: co2, op: '>', threshold: 1, scope: all}\n",
        encoding="utf-8",
    )
    monkeypatch.setattr(
        re_mod.RulesEngine, "_find_yaml", lambda self: tmp_path / "rules.yaml", raising=True
    )
    views = aa.load_rule_views("bx")
    assert [v.name for v in views] == ["CO2 too high"], "a disabled rule is not running"
    assert views[0].watches == "co2"


def test_unreadable_rules_are_no_rules_not_an_error(monkeypatch):
    from orchestrator.services import rules_engine as re_mod

    def boom(self):
        raise OSError("disk gone")

    monkeypatch.setattr(re_mod.RulesEngine, "_find_yaml", boom, raising=True)
    assert aa.load_rule_views("bx") == []


# ── through the workflow node, with the same fakes the existing tests use ────


def _orch():
    return mod.WorkflowOrchestrator.__new__(mod.WorkflowOrchestrator)


def _state(question: str, role="facility_manager") -> ConversationState:
    s = ConversationState(
        conversation_id="c",
        user_id="u",
        user_message=question,
        messages=[Message(role="user", content=question)],
    )
    s.intermediate_results["user_role"] = role
    return s


@pytest.fixture
def building(monkeypatch):
    from orchestrator.services.deliberation import coverage_audit
    from orchestrator.services.deliberation.coverage_audit import ModalitySpec

    monkeypatch.setattr(
        coverage_audit,
        "load_modalities",
        lambda _b=None, **_k: [
            ModalitySpec(name="noise", brick_classes=["Sound_Level_Sensor"]),
            ModalitySpec(name="co2", brick_classes=["CO2_Level_Sensor"]),
        ],
    )
    box = SimpleNamespace(delivers=False, counts={"noise": 12, "co2": 40})

    async def _counts(timeout_s, building_id=None, **_k):
        return dict(box.counts)

    monkeypatch.setattr(mod, "_measured_modality_counts", _counts, raising=False)
    monkeypatch.setattr(
        mod, "_notification_delivery_configured", lambda _b=None: box.delivers, raising=False
    )

    async def _records(timeout_s=5.0):
        return ["Waste collection point"]

    monkeypatch.setattr(aa, "record_labels", _records)
    monkeypatch.setattr(aa, "load_rule_views", lambda _b: [aa.RuleView("CO2 too high", "co2")])
    return box


def _ask(question: str, role="facility_manager"):
    state = _state(question, role)
    _run(_orch()._automation_capability_check_node(state))
    return (
        state.intermediate_results["dialogue_response"],
        state.intermediate_results["automation_capability_result"],
    )


def test_the_task_question_that_failed_on_the_held_out_read(building):
    text, result = _ask("Can the building alert someone to a task?")
    assert "couldn't tell which measured quantity" not in text
    assert text.startswith("**Not on its own.**")
    assert result["kind"] == aa.KIND_TASK


def test_the_override_question_that_failed_on_the_held_out_read(building):
    text, result = _ask("Is there a manual override for standby mode?")
    assert "cannot operate equipment" in text
    assert "couldn't tell which measured quantity" not in text
    assert result["kind"] == aa.KIND_OVERRIDE


def test_a_question_with_no_identifiable_quantity_gets_the_overview(building):
    text, result = _ask("Can the building automatically do something when it's odd?")
    assert "Here is what this building can do about alerts" in text
    assert result["sensor_available"] is None, "still 'could not check', never 'absent'"


def test_a_question_that_names_a_measured_quantity_keeps_its_own_answer(building):
    text, result = _ask("Can the building automatically alert me when noise gets too high?")
    assert result["sensor_available"] is True
    assert "12 sensor point(s)" in text
    assert result["kind"] == aa.KIND_QUANTITY


# ── a notification-provision question is not a question about a measured quantity ────────────

PROVISION_Q = (
    "I may not see visual alerts. Which verified audible or staff-assisted notification "
    "provision is available?"
)


@pytest.mark.parametrize(
    "question",
    [
        PROVISION_Q,
        "What audible alarm provision is in place for the deaf?",
        "How will I be notified if the fire alarm sounds?",
        "Which visual alert provisions exist in the toilets?",
    ],
)
def test_a_provision_question_is_recognised_as_one(question):
    assert aa.question_kind(question) == aa.KIND_PROVISION


@pytest.mark.parametrize(
    "question",
    [
        "Can the building automatically alert me when CO2 gets too high?",
        "Can it monitor energy use and notify me if it spikes?",
        "Is there a manual override for standby mode?",
    ],
)
def test_the_other_shapes_are_unchanged_by_the_provision_rule(question):
    assert aa.question_kind(question) != aa.KIND_PROVISION


def test_a_provision_question_is_answered_from_the_records_that_hold_provisions():
    """Live wave-2: it answered 'this building does measure **empty space** (270 sensor point(s))'."""
    facts = aa.Facts(
        building="Example Building",
        measured=["co2", "noise"],
        record_labels=["Coordination function", "Evacuation provision", "Room booking"],
        delivers=False,
    )
    text = aa.compose(aa.KIND_PROVISION, facts)
    assert "Coordination function" in text and "Evacuation provision" in text
    assert "Room booking" not in text, "a record that holds no provision is not named"
    assert "does measure" not in text and "sensor point(s)" not in text
    assert "empty space" not in text


def test_a_building_with_no_provision_record_declines_and_invents_no_measurand():
    facts = aa.Facts(building="B", measured=["co2"], record_labels=["Room booking"], delivers=True)
    text = aa.compose(aa.KIND_PROVISION, facts)
    assert text.startswith("**I can't tell you which notification provisions B has.**")
    assert "does measure" not in text and "Room booking" not in text


def test_the_provision_records_are_picked_from_the_buildings_own_class_names():
    assert aa.provision_records(["Evacuation provision", "Cost line", "Fire safety asset"]) == [
        "Evacuation provision",
        "Fire safety asset",
    ]
    assert aa.provision_records(["Cost line", "Room booking"]) == []


def test_the_provision_answer_reaches_the_reader_through_the_node(building):
    text, result = _ask(PROVISION_Q)
    assert result["kind"] == aa.KIND_PROVISION
    assert "does measure" not in text and "sensor point(s)" not in text
