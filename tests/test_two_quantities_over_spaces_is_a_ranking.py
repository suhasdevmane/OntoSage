# -*- coding: utf-8 -*-
"""A which-rooms question naming two measured quantities reaches the deliberation lane
(Phase 1.5 of the QA-trial plan).

Tail Q #46 "Are there any empty rooms with lights on?" (occupancy AND illuminance) and tail P #51
"how are common areas managed to maintain comfort during busy times?" are questions whose answer
is a set of spaces ranked on more than one modality -- the deliberation lane's job, and the one
thing the reading lane cannot do (it fetches one quantity or refuses the breadth, BUG-722).
MEASURED 2026-10-02 over the 4,060 bank: 20 which-rooms questions name two or more measurands;
5 already reached `deliberate` by a superlative, 12 landed in `sensor_data`. The quantities are
counted deterministically, so the rule fires at parse time with no concept resolved; a question
about the SENSORS ("which rooms have co-located temperature, CO2 and noise sensors") stays an
inventory question.
"""

import pytest

from orchestrator.services import routing_contract as rc

pytestmark = pytest.mark.unit


def _route(q, intent="sensor_data"):
    n = {"intent": intent, "analytics": False, "general": False}
    applied = rc.apply_contract(q, n, stage="parse")
    return n["intent"], applied


class TestTwoQuantitiesOverSpaces:
    @pytest.mark.parametrize(
        "q",
        [
            "Which student-accessible study area has had the most stable temperature and lighting so far?",
            "Which available area is likely to have lower noise, lower crowding and less glare?",
            "Are there any empty rooms with lights on?",
            "Which zones show repeated temperature or humidity excursions at roughly the same time?",
        ],
    )
    def test_reaches_the_deliberation_lane(self, q):
        intent, applied = _route(q)
        assert intent == "deliberate", (q, applied)

    @pytest.mark.parametrize(
        "q",
        [
            "Which rooms have co-located temperature, CO2 and noise sensors for a multi-modal study?",
            "What is the temperature in room 2.01?",
            "Which rooms are warmer than 24 degrees?",
            "turn off the lights and the heating in room 2.01",
        ],
    )
    def test_is_left_alone(self, q):
        intent, applied = _route(q)
        assert "two_quantities_over_spaces" not in applied, (q, intent)

    def test_the_rule_is_pinned_after_existential_comfort(self):
        names = [r.name for r in rc.PARSE_STAGE_RULES]
        assert (
            names.index("two_quantities_over_spaces")
            == names.index("existential_comfort_is_deliberate") + 1
        )
