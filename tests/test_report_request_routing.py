# -*- coding: utf-8 -*-
"""CAVEAT-201: a request for a report about measured data must reach the report lane.

"Give me a report on energy use last week." was answered with the building's
sustainability blurb. The ontology holds a KnowledgeTopic whose lay terms cover
"energy", and nothing in the phrasing looks like a sensor reading, so the
classifier chose capability — and the user got prose containing no data at all.
"""

from __future__ import annotations

import pytest

from orchestrator.services.routing_contract import _r_report_request_not_capability
from orchestrator.services.semantic_router import SemanticRouter

pytestmark = pytest.mark.unit


class _Ctx:
    def __init__(self, intent, query):
        self.intent = intent
        self.query = query
        self.ql = query.lower()
        self.sr = SemanticRouter


class TestTheRequestIsRescued:
    @pytest.mark.parametrize(
        "query",
        [
            "Give me a report on energy use last week.",
            "generate a summary of CO2 for floor 2",
            "I need a breakdown of power consumption",
            "show me the monthly report for temperature",
            "produce a weekly summary of occupancy",
        ],
    )
    def test_a_data_report_request_goes_to_report(self, query):
        assert _r_report_request_not_capability(_Ctx("capability", query)) == "report"

    @pytest.mark.parametrize("intent", ["general", "metadata", None])
    def test_the_other_weak_classifications_are_rescued_too(self, intent):
        q = "Give me a report on energy use last week."
        assert _r_report_request_not_capability(_Ctx(intent, q)) == "report"


class TestWhatMustKeepItsCapabilityAnswer:
    @pytest.mark.parametrize(
        "query",
        [
            "give me a report on the parking policy",
            "where can I find the fire safety report?",
            "is there a report about the building's history?",
        ],
    )
    def test_a_report_about_something_unmeasured_stays_put(self, query):
        """The prose answer is the CORRECT answer for these."""
        assert _r_report_request_not_capability(_Ctx("capability", query)) is None


class TestWhatMustNotBeHijacked:
    def test_a_reading_question_wearing_the_verb_is_not_a_report(self):
        """'report the average temperature' asks for a number, not a document."""
        q = "can you report the average temperature"
        assert _r_report_request_not_capability(_Ctx("capability", q)) is None

    def test_a_fault_statement_still_files_a_ticket(self):
        q = "send a report, the toilet is leaking and the temperature is freezing"
        assert SemanticRouter.report_intake_intent(q) is not None
        assert _r_report_request_not_capability(_Ctx("capability", q)) is None

    @pytest.mark.parametrize("intent", ["sensor_data", "analytics", "control", "floor_plan"])
    def test_a_confident_classification_is_left_alone(self, intent):
        q = "Give me a report on energy use last week."
        assert _r_report_request_not_capability(_Ctx(intent, q)) is None

    def test_a_plain_amenity_question_is_untouched(self):
        assert (
            _r_report_request_not_capability(_Ctx("capability", "where is the prayer room?"))
            is None
        )


class TestTheShortCircuitYields:
    """The rule alone could not fix this: the capability short-circuit in
    dialogue_agent returns intent="capability" BEFORE the LLM call and therefore
    before any contract rule runs. Both paths must consult the same predicate,
    or a unit-green rule stays dead in production (lessons.md #24)."""

    def test_the_predicate_is_shared_not_duplicated(self):
        import inspect

        from orchestrator.agents import dialogue_agent
        from orchestrator.services.routing_contract import report_request_about_data

        src = inspect.getsource(dialogue_agent)
        assert "report_request_about_data" in src, "the short-circuit does not consult it"
        assert report_request_about_data("Give me a report on energy use last week.")

    @pytest.mark.parametrize(
        "query,expected",
        [
            ("Give me a report on energy use last week.", True),
            ("generate a summary of CO2 for floor 2", True),
            ("where is the prayer room?", False),
            ("give me a report on the parking policy", False),
            ("can you report the average temperature", False),
        ],
    )
    def test_the_predicate_agrees_with_the_rule(self, query, expected):
        from orchestrator.services.routing_contract import report_request_about_data

        assert report_request_about_data(query) is expected
