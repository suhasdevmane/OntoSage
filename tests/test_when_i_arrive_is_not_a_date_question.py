""""Where do I go when I arrive?" asks for a place, not a date (2026-10-11 battery, visitor).

The answer from the visitor topic was prefixed "I don't hold a specific date for this", because
the caveat read the conjunction "when" as a date question.
"""

import pytest

from orchestrator.services.grounding_guard import missing_fact_caveat

pytestmark = pytest.mark.unit

POLICY = "All external visitors must sign in at the main reception and are issued a badge."


def test_a_condition_is_not_a_date_question():
    q = "I'm visiting the building for the first time, where do I go when I arrive?"
    assert missing_fact_caveat(q, POLICY) is None


def test_a_when_question_still_gets_the_caveat():
    assert "specific date" in missing_fact_caveat("When was the reception refurbished?", POLICY)
