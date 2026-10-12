"""CAVEAT-1628: 'what did they record yesterday?' after 'how many water meters?' asks the meters.

The model's rewrite made "they" the building and the document lane declined.
"""

from __future__ import annotations

import pytest

from orchestrator.services.context_switch import resolve_counted_instruments

pytestmark = pytest.mark.unit


@pytest.mark.parametrize(
    "prev, latest, want",
    [
        (
            "How many water meters does the building have?",
            "What did they record yesterday?",
            "What did the water meters record yesterday?",
        ),
        (
            "how many CO2 sensors are on floor 3?",
            "and what do they read right now?",
            "and what do the CO2 sensors read right now?",
        ),
        (
            "How many energy meters are there?",
            "show me what those measured last week",
            "show me what the energy meters measured last week",
        ),
    ],
)
def test_they_is_the_instruments_just_counted(prev, latest, want):
    assert resolve_counted_instruments(latest, prev) == want


@pytest.mark.parametrize(
    "prev, latest",
    [
        ("How many people are in the building?", "What did they record yesterday?"),
        ("How many water meters are there?", "Where are they?"),
        ("How many water meters are there?", "What did the energy meters record?"),
        ("What is the CO2 in room 2.05?", "What did they record yesterday?"),
        ("How many rooms are there?", "What did they record yesterday?"),
    ],
)
def test_it_stands_down_otherwise(prev, latest):
    assert resolve_counted_instruments(latest, prev) is None
