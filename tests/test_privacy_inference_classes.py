# -*- coding: utf-8 -*-
"""A refusal that fires on grammar protects nobody (BUG-442, 2026-09-06).

Measured live on the development building, response cache flushed:

    "What is this building and who runs it?"
      -> privacy_refusal: "I can't answer that. The system explains the building; it
         never tracks individuals."

The refusal is true and has nothing to do with the question. The clause responsible was a
bare `(?:and|but)\s+who` inside INDIVIDUAL_PRESENCE_RE, added for a genuine follow-up case
-- "is anyone in the wellness room? ...and who?" -- and matching ANY compound question whose
second half began with those words. The governance register that answers the question holds
82 stakeholder groups and never ran.

Two mistakes are equally bad here and this file guards against both. Refusing a governance
question teaches people to stop asking and protects no one. Allowing an identification
question strands the person it identifies. "Who manages this building?" and "who manages
this building and is she in her office right now?" differ by one clause, so the allow-list
requires the ABSENCE of any presence predicate rather than merely outranking it.
"""

from __future__ import annotations

import pytest

pytestmark = pytest.mark.unit

from orchestrator.services.privacy.inference_classes import (  # noqa: E402
    classify_inference,
    is_governance_question,
)

# ── a refusal that fires on grammar protects nobody (BUG-442, 2026-09-06) ─────
#
# "What is this building and who runs it?" was refused as individual tracking. The clause
# responsible was a bare `(?:and|but)\s+who`, added for the genuine follow-up case
# ("is anyone in the wellness room? …and who?") and matching any compound question whose
# second half began with those words.
#
# The refusal text -- "the system explains the building; it never tracks individuals" -- is
# true and has nothing to do with the question. The governance register that answers it
# holds 82 stakeholder groups and never ran. A refusal like this teaches people to stop
# asking, and it protects no one: naming the organisation responsible for a building is not
# tracking a person.


@pytest.mark.parametrize(
    "question",
    [
        "What is this building and who runs it?",
        "Who manages this building?",
        "Who owns the building?",
        "Who is responsible for the lifts?",
        "Who is in charge of the labs?",
        "Who do I contact about a leak?",
        "Who should I email about a broken door closer?",
        "Who is the facilities manager?",
    ],
)
def test_a_governance_question_is_not_individual_tracking(question):
    assert classify_inference(question) is None, (
        f"{question!r} asks who RUNS something, not where somebody IS"
    )


@pytest.mark.parametrize(
    "question",
    [
        # The follow-up the clause exists for: a count, then an identification.
        "Is anyone in the wellness room, and who?",
        "How many people are on floor 3 and who is in there?",
        # A governance question with a presence question attached is still two questions,
        # and the second one is denied. One letter apart from the allowed shapes above.
        "Who manages this building and is she in her office right now?",
    ],
)
def test_asking_to_identify_someone_is_still_refused(question):
    assert classify_inference(question) == "individual_presence"


@pytest.mark.parametrize(
    "question, expected",
    [
        # PRONOUNS. Found while narrowing the clause above, and it predated that: these
        # passed every rule and reached the data lanes. A pronoun is the most natural way
        # to ask where a named person is once the name has been said, so the leak sat
        # exactly where a real conversation puts it.
        ("Is he at his desk?", "individual_presence"),
        ("Is she in the building?", "individual_presence"),
        # NOT he/she. "they" and "it" are how people ask about a delivery, a meeting or a
        # set of sensors, and refusing those protects nobody.
        ("Are they in the meeting room?", None),
        ("Is it in the lab?", None),
    ],
)
def test_a_pronoun_asking_where_a_person_is_counts_as_a_person(question, expected):
    assert classify_inference(question) == expected


def test_the_governance_check_runs_before_the_presence_rule():
    """Order is the whole fix.

    An allow-list placed after the presence rule would never fire: that rule returns first,
    which is exactly how "and who runs it" came to be refused.
    """
    import inspect

    from orchestrator.services.privacy import inference_classes as ic

    src = inspect.getsource(ic.classify_inference)
    assert src.index("is_governance_question") < src.index("INDIVIDUAL_PRESENCE_RE"), (
        "the governance allow-list now runs after the presence rule and can never fire"
    )
