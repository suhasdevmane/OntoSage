# -*- coding: utf-8 -*-
"""2D-06 wave 9: four register misselections on an unseen set.

1. "Is there a way that I will be notified when systems are down and how long they will take to
   get back up?" selected the circulation register on "take to get". A duration word may select a
   register only when the question is also about that register's subject.
2. "Has the authorised AV service confirmed readiness for the next booking after the previous
   event?" went to the booking register. The AV readiness register was NAMED in the question and
   lost to a noun the question merely used, because a term scores its own length ("booking" seven,
   "av" two).
3. Two runs of the isolation / permit / asset-state question declined in two slightly different
   sentences (no action; both are declines by construction, checked below).
4. "are VOC levels safe in my workspace?" selected the workspace register on "workspace" and was
   answered "the building's records do not contain any information about VOC concentrations" — the
   building has VOC sensors. A measured quantity asked for as a reading belongs to the readings
   lane, or to a clarification about the place.
"""

from __future__ import annotations

import asyncio
import importlib.util
import sys
from datetime import date
from pathlib import Path
from types import SimpleNamespace

import pytest

from orchestrator.services import register_projection as rp
from orchestrator.services import routing_contract as rc
from tests.register_fixture_rows import lifted_rows
from tests.test_the_register_lane_answers_a_lookup_from_the_rows_end_to_end import _lane

pytestmark = pytest.mark.unit

REPO = Path(__file__).resolve().parents[1]
TODAY = date(2026, 9, 20)


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


# ── 1. a duration word needs the register's subject ─────────────────────────────────────────────


@pytest.mark.parametrize(
    "question",
    [
        "Is there a way that I will be notified when systems are down and how long they will "
        "take to get back up?",
    ],
)
def test_a_duration_about_something_else_selects_no_register(reach, question):
    assert reach.register(question)["held"] is None


@pytest.mark.parametrize(
    "question",
    [
        "How long does it take to get to Level 3 from the entrance?",
        "How long does it take to get between floors?",
        "How long does it take to walk from Level 0 to Level 5?",
    ],
)
def test_a_journey_between_places_still_selects_the_circulation_register(reach, question):
    assert reach.register(question)["held"] == "CirculationTime"


# ── 2. a register named in the question outranks a status noun ──────────────────────────────────


@pytest.mark.parametrize(
    "question",
    [
        "Has the authorised AV service confirmed readiness for the next booking after the "
        "previous event?",
        "Is the AV readiness confirmed for tomorrow's session?",
    ],
)
def test_the_register_the_question_names_beats_a_noun_it_merely_uses(reach, question):
    assert reach.register(question)["held"] == "AVReadiness"


@pytest.mark.parametrize(
    "question",
    [
        "Which bookings are confirmed?",
        "How many bookings are provisional?",
        "Which room booking is for Room 5.15?",
    ],
)
def test_a_plain_booking_question_still_selects_the_booking_register(reach, question):
    assert reach.register(question)["held"] == "Booking"


@pytest.mark.parametrize(
    "question",
    [
        "Which scheduled sessions depend on the failed AV service during the current outage?",
        "If the room, lift or AV service becomes unavailable, what fallback should we follow?",
    ],
)
def test_the_phrases_do_not_take_an_outage_question(reach, question):
    assert reach.register(question)["held"] != "AVReadiness"


# ── 3. the isolation question declines, and what it says is true ────────────────────────────────


def test_the_isolation_question_is_never_composed_into_an_answer_from_one_register():
    q = (
        "Do the current isolation record, permit boundary and independently verified asset state "
        "agree for the exact electrical, mechanical, gas or other system?"
    )
    for document in ("asset_engineering_register.md", "permit_to_work_register.md"):
        rows, label = lifted_rows(document)
        assert rp.deterministic_answer(rows, q, label, TODAY) == "", document


# ── 4. a measured quantity asked for as a reading ───────────────────────────────────────────────


@pytest.mark.parametrize(
    "question",
    [
        "are VOC levels safe in my workspace?",
        "What is the CO2 level in Room 5.01?",
        "Is the temperature too high on floor 3?",
        "How high is the formaldehyde concentration?",
        "what are the humidity readings in the lab",
    ],
)
def test_a_measured_quantity_asked_as_a_reading_is_not_a_register_question(question):
    assert rc.measured_reading_question(question)


@pytest.mark.parametrize(
    "question",
    [
        "Where can I work for three hours with power, good Wi-Fi and a low risk of noise?",
        "Which workspaces have a quiet noise profile?",
        "Which fire safety assets are due for test?",
        "Who owns the ventilation plant?",
        "Which rooms have good daylight?",
        "How many bookings are there?",
    ],
)
def test_a_question_about_what_a_register_records_is_not_taken_for_a_reading(question):
    assert not rc.measured_reading_question(question)


def test_the_register_lane_leaves_a_reading_question_to_the_readings_lanes(monkeypatch):
    agent, calls = _lane(
        "workspace_profile_register.md",
        "WorkspaceProfile",
        "Workspace profile",
        monkeypatch,
        lay="workspace",
    )
    state = SimpleNamespace(building_id=None, intermediate_results={})
    out = asyncio.run(agent._whole_register(state, "are VOC levels safe in my workspace?"))
    assert out is None
    assert not calls["llm"]


def test_the_register_lane_still_answers_the_workspace_demo_question(monkeypatch):
    agent, _calls = _lane(
        "workspace_profile_register.md",
        "WorkspaceProfile",
        "Workspace profile",
        monkeypatch,
        lay="work for three hours|good wi-fi",
        llm="narrated",
    )
    state = SimpleNamespace(building_id=None, intermediate_results={})
    out = asyncio.run(
        agent._whole_register(
            state,
            "Where can I work for three hours with power, good Wi-Fi and a low risk of noise?",
        )
    )
    assert out is not None and out["method"] == "whole_register"
