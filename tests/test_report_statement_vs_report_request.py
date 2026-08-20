# -*- coding: utf-8 -*-
"""BUG-200: a fault STATEMENT must be filed, not summarised.

"The toilet on floor 1 is leaking." is someone reporting a problem. The word
"report" sits in the same semantic neighbourhood as the summary-generation
intent, so the classifier reaches for it and produces an executive summary
*about* the leak. The intake override that exists to catch exactly this only
ran for a short allow-list of intents, and "report" was not among them — so the
one misclassification most likely to happen was the one not rescued, and
nothing recorded the fault.
"""

from __future__ import annotations

import pytest

from orchestrator.services.routing_contract import _r_report_intake
from orchestrator.services.semantic_router import SemanticRouter

pytestmark = pytest.mark.unit


class _Ctx:
    """Minimal stand-in for the rule context: intent, query, and the guards."""

    def __init__(self, intent, query):
        self.intent = intent
        self.query = query
        self.ql = query.lower()
        self.sr = SemanticRouter


STATEMENTS = [
    ("The toilet on floor 1 is leaking.", "maintenance"),
    ("the light in RM101 is broken", "maintenance"),
    ("Suggestion: add more bike racks", "suggestion"),
]

REPORT_REQUESTS = [
    "give me a report on energy use",
    "generate a summary report for floor 2",
    "report on CO2 last week",
    "I need a report of all anomalies",
    "show me the monthly report",
]


class TestAFaultStatementIsRescued:
    @pytest.mark.parametrize("query,kind", STATEMENTS)
    def test_misclassified_as_report_it_still_goes_to_intake(self, query, kind):
        assert _r_report_intake(_Ctx("report", query)) == kind

    @pytest.mark.parametrize("query,kind", STATEMENTS)
    def test_the_previously_covered_intents_still_work(self, query, kind):
        for intent in ("capability", "general", "metadata", None):
            assert _r_report_intake(_Ctx(intent, query)) == kind


class TestAGenuineReportRequestIsLeftAlone:
    @pytest.mark.parametrize("query", REPORT_REQUESTS)
    def test_the_summary_lane_is_not_hijacked(self, query):
        """The rescue is conditional on intake detection, which these do not trip."""
        assert SemanticRouter.report_intake_intent(query) is None
        assert _r_report_intake(_Ctx("report", query)) is None


class TestUnrelatedIntentsAreStillExcluded:
    @pytest.mark.parametrize("intent", ["sensor_data", "analytics", "control", "floor_plan"])
    def test_widening_did_not_open_the_gate_generally(self, intent):
        """A data or control question is never re-routed to intake."""
        assert _r_report_intake(_Ctx(intent, "The toilet on floor 1 is leaking.")) is None
