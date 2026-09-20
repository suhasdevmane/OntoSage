# -*- coding: utf-8 -*-
"""A declarative fault followed by a request is a report (tail L, 2026-09-20).

"the waste bin of the cafe is overflowing. can you fix this pronto?" ended in "?", so the whole
message was read as a question, the classifier called it `metadata`, and the waste REGISTER answered
"cannot answer this: it records aperture kind, location and service frequency, and nothing about
cafe, overflowing and pronto". Nothing was filed. "overflowing" was also not a fault word at all.

Two changes, each pinned here: the overflow vocabulary, and judging a message on its declarative
lead when a plain fault statement precedes the closing question. Every QUESTION shape stays unfiled.
"""

from __future__ import annotations

import pytest

from orchestrator.services.semantic_router import SemanticRouter as SR

pytestmark = pytest.mark.unit


@pytest.mark.parametrize(
    "message",
    [
        "the waste bin of the cafe is overflowing. can you fix this pronto?",
        "The waste bin in the cafe is overflowing.",
        "The bin needs emptying",
        "The toilet on floor 2 is leaking. Can someone come and look?",
        "The projector is not working. Please fix it.",
    ],
)
def test_a_fault_statement_is_filed_even_with_a_request_after_it(message):
    assert SR.report_intake_intent(message) == "maintenance", message


@pytest.mark.parametrize(
    "message",
    [
        "Is the lift broken?",
        "Which bins are overflowing?",
        "Is the recycling bin overflowing?",
        "How many bins are close to overflowing?",
        "When does the waste bin get emptied?",
        "Are any waste points overflowing right now?",
        "The lift is a nice feature. Is it broken today?",  # the lead states no fault
        "Can you fix the cost report?",
    ],
)
def test_a_question_is_never_filed(message):
    assert SR.report_intake_intent(message) is None, message


def test_a_message_that_opens_with_a_question_keeps_its_reading():
    """The lead-statement rule applies only when the message does not START as a question."""
    assert SR.report_intake_intent("Is the printer jammed? It is not working.") is None
