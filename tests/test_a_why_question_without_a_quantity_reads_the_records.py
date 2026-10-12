"""A why-question the diagnosis lane cannot diagnose goes to the records lane (2026-10-11).

The diagnosis lane explains comfort conditions and needs a quantity; on the role-stratified bank
sample it received 6 why-questions about other things and declined all 6.
"""

from __future__ import annotations

from types import SimpleNamespace

import pytest

from orchestrator.services import routing_contract as rc

pytestmark = pytest.mark.unit


def _ctx(intent: str, query: str):
    return SimpleNamespace(intent=intent, query=query)


@pytest.mark.parametrize(
    "q",
    [
        "Why was the fire door inspection postponed?",
        "Why does the building have two grounds contractors?",
        "Why is the car park closed at weekends?",
    ],
)
def test_a_why_about_records_goes_to_metadata(q):
    assert rc._r_diagnosis_without_a_quantity(_ctx("diagnosis", q)) == "metadata"


@pytest.mark.parametrize(
    "q",
    ["Why is it so stuffy in room 2.05?", "Why was floor 2 freezing on Tuesday?"],
)
def test_a_comfort_why_stays_with_diagnosis(q):
    assert rc._r_diagnosis_without_a_quantity(_ctx("diagnosis", q)) is None


def test_other_intents_are_untouched():
    assert rc._r_diagnosis_without_a_quantity(_ctx("metadata", "Why was it postponed?")) is None
