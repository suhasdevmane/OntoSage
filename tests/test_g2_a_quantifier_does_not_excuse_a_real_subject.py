# -*- coding: utf-8 -*-
"""G2 (QA-trial plan, 2026-10-04): "How many bathrooms do you have and where are they
located." declined although "bathrooms" IS a declared ToiletFacility lay term -- the
leftover was ['many', 'they'], and the subject test's one-leftover threshold refused at
two. `ungrounded_question.quantifier_question` + `QUANTIFIER_FRAME`/`QUANTIFIER_PRONOUNS`
fix the counting-and-back-reference shape, deliberately narrow.

MEASURED AND CAUGHT BEFORE SHIPPING: the first version dropped "many" whenever the
question merely LOOKED like a count, with no requirement that a pronoun also be present.
Over the full 4,060-question bank that moved a wrong case too: "How many open work
orders are there, and which are overdue?" against the "Lift out of order" topic left
[many, overdue], and losing "many" alone made "overdue" cross the threshold -- qualifying
a topic the question is not about. Fixed by requiring a genuine back-reference pronoun
(they/them/their) already in the leftover before "many" is also dropped. Both cases are
pinned here so neither regresses silently.
"""
from types import SimpleNamespace

import pytest

from orchestrator.services.capability_graph_resolver import topic_is_the_subject
from orchestrator.services.ungrounded_question import quantifier_question

pytestmark = pytest.mark.unit

TOILETS = SimpleNamespace(
    label="Toilets", lay_terms="toilet,toilets,bathroom,bathrooms,restroom,washroom"
)
LIFT_OUT_OF_ORDER = SimpleNamespace(
    label="Lift out of order",
    lay_terms=(
        "lift broken, lift not working, elevator broken, lift out of order, lift "
        "stuck, elevator not working, is the lift broken"
    ),
)


class TestTheMotivatingCaseNowAnswers:
    def test_how_many_bathrooms_and_where_are_they_reaches_the_toilet_topic(self):
        q = "How many bathrooms do you have and where are they located."
        assert topic_is_the_subject(q, TOILETS) is True

    def test_quantifier_question_recognises_the_shape(self):
        assert quantifier_question("How many bathrooms do you have and where are they located.")
        assert quantifier_question("How many fire exits are there and where are they?")

    def test_the_shape_alone_does_not_decide_the_answer(self):
        """quantifier_question() tests the QUESTION's shape only; whether the
        subtraction actually fires also needs a pronoun in the leftover (see
        TestTheMeasuredFalsePositiveStaysGuarded below) -- the two checks are separate
        on purpose, so this shape matching is not itself a claim about any topic."""
        assert quantifier_question("How many open work orders are there?")


class TestTheMeasuredFalsePositiveStaysGuarded:
    def test_a_work_order_count_does_not_qualify_an_unrelated_lift_topic(self):
        q = "How many open work orders are there, and which are overdue?"
        assert topic_is_the_subject(q, LIFT_OUT_OF_ORDER) is False

    def test_many_alone_with_no_pronoun_in_the_leftover_is_not_dropped(self):
        """The guard condition directly: quantifier_question() can be True while the
        pronoun requirement is what actually withholds the subtraction."""
        q = "How many open work orders are there, and which are overdue?"
        assert quantifier_question(q)  # the shape matches...
        assert topic_is_the_subject(q, LIFT_OUT_OF_ORDER) is False  # ...but doesn't fire
