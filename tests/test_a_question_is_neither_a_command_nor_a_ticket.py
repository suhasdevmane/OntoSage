# -*- coding: utf-8 -*-
"""A question about what the building does is neither a control command nor a report
(BUG-1417, BUG-1418 -- Phase 1.1 of the QA-trial plan).

MEASURED on tail Q, 2026-10-02 (occupant01, /v1):

    "If 3 people enter a room and the sensors see 2 leave do the lights turn off?"
    "Do ozone sensors alert people or do they just activate ventilation or filtration?"
        -> "You don't have permission to control building systems (role: occupant)"
    "can you clean graffitti by yourself"
        -> FILED as maintenance ticket REP-EB3D5D, an administrator notified

The first two: `_INFORMATION_QUESTION_RE` knows an auxiliary + pronoun/determiner subject, not
an auxiliary + bare noun ("do ozone sensors ..."), and the subordinate-lead form required a
comma. Measured over the 4,060 bank: 326 "?"-questions open with an auxiliary and a bare word,
and NONE of those words is a command verb, so the question mark plus a non-command first word
decides it. The third: the LLM classifier said `maintenance`, the deterministic report test said
None, and nothing corrected the classifier -- `question_is_not_a_report` now does, after the
comfort rule (so a comfort question still reaches analytics) and only for maintenance /
complaint / safety_report (wave 8 deliberately files question-shaped WISHES as suggestions).

Guard tests that caught the first drafts, all still green: "can you turn off the lights?" is a
polite COMMAND ("you" is excluded from the bare subjects), "Could someone look at the broken
light?" is a REQUEST to file, and "Since the lift is broken, when will it be fixed?" carries a
fault in its lead and is still filed.
"""

import pytest

from orchestrator.services import routing_contract as rc
from orchestrator.services.semantic_router import SemanticRouter as S

pytestmark = pytest.mark.unit


class TestAQuestionIsNotACommand:
    @pytest.mark.parametrize(
        "q",
        [
            "If 3 people enter a room and the sensors see 2 leave do the lights turn off?",
            "Do ozone sensors alert people or do they just activate ventilation or filtration?",
            "Does the heating switch off at night?",
            "Can anyone use the EV chargers?",
            "Are blinds closed automatically when it is sunny?",
        ],
    )
    def test_not_a_command(self, q):
        assert not S.is_control_command(q), q
        assert S.is_information_question(q), q

    @pytest.mark.parametrize(
        "q",
        [
            "can you turn off the lights?",
            "could you open the window please?",
            "turn off the lights in room 2.01",
            "Do open the window",
            "Close the blinds on the west side, the glare is unbearable.",
        ],
    )
    def test_a_command_is_still_a_command(self, q):
        assert S.is_control_command(q), q


class TestAQuestionIsNotATicket:
    def _apply(self, q, intent="maintenance"):
        n = {"intent": intent, "analytics": False, "general": False}
        applied = rc.apply_contract(q, n, stage="parse")
        return n["intent"], applied

    def test_the_graffiti_question_is_answered_not_filed(self):
        intent, applied = self._apply("can you clean graffitti by yourself")
        assert intent == "capability"
        assert "question_is_not_a_report" in applied

    @pytest.mark.parametrize(
        "q",
        [
            "the toilet is leaking on floor 2",
            "The accessible toilet door button isn't working again - third time this month.",
            "Could someone look at the broken light in room 2.01?",
        ],
    )
    def test_a_statement_or_request_is_still_filed(self, q):
        intent, applied = self._apply(q)
        assert "question_is_not_a_report" not in applied
        assert intent == "maintenance"

    def test_a_fault_in_the_lead_still_files(self):
        assert not S.is_information_question("Since the lift is broken, when will it be fixed?")

    def test_a_question_shaped_wish_stays_a_suggestion(self):
        intent, applied = self._apply(
            "is there a way to tell the system I prefer it cooler?", "suggestion"
        )
        assert "question_is_not_a_report" not in applied

    def test_the_rule_sits_after_the_comfort_rule(self):
        names = [r.name for r in rc.PARSE_STAGE_RULES]
        assert (
            names.index("question_is_not_a_report")
            == names.index("comfort_question_not_report") + 1
        )
