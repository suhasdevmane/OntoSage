# -*- coding: utf-8 -*-
"""BUG-195: the most natural presence questions must be tagged presence-adjacent.

k-anonymity floors are forwarded to the PDP only for PRESENCE_ADJACENT modalities
(occupancy / motion / door_contact / window_contact / access / presence). The
modality is inferred from the question text, and that inference matched
"people count" but not "how many people are in the building" — so the commonest
phrasing of a presence question reached the decision point as modality="-", the
k-check was skipped, and the floor could be raised to 900 sensors without
changing the answer.

Widening errs toward MORE privacy: a capacity question ("how many people can this
room seat") being treated as presence-adjacent only makes the PDP stricter, which
is the safe direction.
"""

from __future__ import annotations

import pytest

from orchestrator.services.privacy.enforcement import PRESENCE_ADJACENT

pytestmark = pytest.mark.unit


def _kind(text: str):
    from orchestrator.workflow._orchestrator import WorkflowOrchestrator

    return WorkflowOrchestrator._infer_query_kind(None, text)


@pytest.mark.parametrize(
    "question",
    [
        "How many people are in the building right now?",
        "how many people are in room 101",
        "How many people are on floor 2 at the moment?",
        "What is the headcount in the atrium?",
        "How busy is the building right now?",
        "Is the canteen crowded?",
        "What is the attendance in the lecture theatre?",
        "how many occupants are here",
        "show me the motion sensor data",
        "what is the occupancy of floor 1",
        "footfall today",
    ],
)
def test_presence_questions_are_tagged_presence_adjacent(question):
    kind = _kind(question)
    assert kind in PRESENCE_ADJACENT, (
        f"{question!r} inferred as {kind!r}; the PDP would drop n_sensors and skip "
        "the k-anonymity floor"
    )


@pytest.mark.parametrize(
    "question, expected",
    [
        ("What is the temperature in RM101?", "temperature"),
        ("What is the CO2 level?", "co2"),
        ("How humid is it?", "humidity"),
        ("What is the energy use today?", "energy"),
    ],
)
def test_other_modalities_are_unchanged(question, expected):
    """Widening presence detection must not steal other modalities."""
    assert _kind(question) == expected


def test_a_question_naming_no_quantity_is_still_unclassified():
    assert _kind("where is the nearest lift?") is None
