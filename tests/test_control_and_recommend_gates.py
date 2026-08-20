# -*- coding: utf-8 -*-
"""BUG-156 / BUG-157: two paths that answered instead of declining.

BUG-157 — "Fix the temperature in here" is an actuation REQUEST. Routing precedence
says actuation -> control -> polite decline, but `fix` was in neither the control
verb set nor its target set (which listed plant nouns like `hvac`, never the
comfort quantity a user actually names), so the classifier's `analytics` stood and
the system answered with real AHU temperatures — doing nothing while sounding like
it had.

BUG-156 — `recommend` was missing from GATED_INTENTS, so no referent/sensor-type
existence gate ran on it. "Should we charge the battery now or wait?" collapsed to
generic analytics over whatever rows were to hand and quoted a real reading in a
battery context the building does not model.
"""

from __future__ import annotations

import pytest

from orchestrator.services.referent_resolver import GATED_INTENTS
from orchestrator.services.semantic_router import SemanticRouter

pytestmark = pytest.mark.unit


# ── BUG-157: imperative comfort fixes are actuation ──────────────────────────


@pytest.mark.parametrize(
    "query",
    [
        "Fix the temperature in here.",
        "fix the temperature in here",
        "Can you fix the temperature in this room?",
        "Sort out the temperature in here",
        "Please sort the heating in room 101",
        "Do something about the temperature in here",
        "Fix the humidity on floor 2",
        "sort out the stuffiness in this room",
        "Adjust the temperature in here",
    ],
)
def test_imperative_comfort_fix_is_an_actuation_command(query):
    assert SemanticRouter.is_control_command(query) is True, query


@pytest.mark.parametrize(
    "query",
    [
        # questions about state — never commands
        "Is the temperature ok in here?",
        "What is the temperature in here?",
        "Why is the temperature so high in here?",
        "How do I fix the temperature in here myself?",
        # a fault STATEMENT is a report, not an actuation request
        "The temperature in here is broken",
        # past tense — a maintenance history question
        "When was the thermostat last fixed?",
        # capability question, not a command
        "Can the building automatically fix the temperature?",
    ],
)
def test_questions_and_reports_are_not_actuation_commands(query):
    assert SemanticRouter.is_control_command(query) is False, query


def test_existing_control_commands_still_match():
    for q in ("open the windows", "unlock the front door", "turn off the lights"):
        assert SemanticRouter.is_control_command(q) is True, q


# ── BUG-156: recommend must be existence-gated ───────────────────────────────


def test_recommend_is_existence_gated():
    """Otherwise 'should we charge the battery now?' answers from an unrelated series."""
    assert "recommend" in GATED_INTENTS


def test_the_other_data_intents_are_still_gated():
    for intent in ("sensor_data", "analytics", "trend", "compare", "anomaly", "metadata"):
        assert intent in GATED_INTENTS


def test_broad_intents_remain_ungated():
    """These legitimately answer without a named referent — gating them would break them."""
    for intent in ("capability", "floor_plan", "greeting", "general"):
        assert intent not in GATED_INTENTS
