"""A question about a measured gas is not a question about a carbon target (BUG-625).

"What is the carbon monoxide level on floor 1?" was answered from the sustainability target
register — baselines and percentage reductions for Scope 1 and 2 emissions — because that
register declared the bare lay term "carbon". Carbon monoxide and carbon dioxide are gases the
building MEASURES, with sensors and readings; a reduction target is a commitment about a
different quantity entirely. The word they share is the first half of two different nouns.

Same shape as BUG-611 ("circuit" claiming a plant reading for the patrol register) and BUG-623
("focused work" claiming a live-conditions question): a single broad term claiming questions
that belong to another lane.
"""

import re
from pathlib import Path

import pytest

from orchestrator.services.record_registry import RecordClass, held_record_class

pytestmark = pytest.mark.unit


def _lay_terms(class_local_name: str):
    """Read from the shared schema, so adding a term makes this test speak up."""
    text = Path("ontology/ontosage_schema.ttl").read_text(encoding="utf-8")
    start = text.index(f"ontosage:{class_local_name} ontosage:layTerms")
    statement = text[start : text.index(" .\n", start)]
    return [t.lower() for t in re.findall(r'"([^"]+)"', statement)]


def _sustainability_class():
    return RecordClass(
        local_name="SustainabilityTarget",
        label="Sustainability target",
        instances=5,
        terms=tuple(_lay_terms("SustainabilityTarget")),
    )


_GAS_QUESTIONS = [
    "What is the carbon monoxide level on floor 1?",
    "What is the carbon dioxide level in room 5.01?",
    "Is the carbon monoxide safe on the ground floor?",
    "How much carbon dioxide is there right now?",
]


@pytest.mark.parametrize("question", _GAS_QUESTIONS)
def test_a_gas_reading_is_not_claimed_by_the_target_register(question):
    held = held_record_class(question, [_sustainability_class()])
    assert held is None, (
        f"the sustainability register claimed {question!r} — that question wants a reading "
        f"from a sensor, not a percentage reduction against a baseline"
    )


_TARGET_QUESTIONS = [
    "What are our carbon emissions targets?",
    "Are we on track to hit net zero?",
    "What is the carbon reduction target for scope 1?",
    "Show me the sustainability targets.",
]


@pytest.mark.parametrize("question", _TARGET_QUESTIONS)
def test_the_register_still_answers_what_it_is_for(question):
    """The guard must not be satisfied by the register claiming nothing at all."""
    held = held_record_class(question, [_sustainability_class()])
    assert held is not None and held.local_name == "SustainabilityTarget", question


def test_the_bare_word_stays_out():
    """Named explicitly: re-adding "carbon" alone fails the four gas questions above."""
    assert "carbon" not in _lay_terms("SustainabilityTarget")


def test_the_replacement_phrases_are_present():
    """Removing the bare term must not cost the register the questions it does own."""
    terms = _lay_terms("SustainabilityTarget")
    for phrase in ("carbon emissions", "carbon footprint", "carbon target"):
        assert phrase in terms
