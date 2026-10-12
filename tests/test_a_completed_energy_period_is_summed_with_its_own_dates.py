""""How much electricity did the building use last week?" -- a sum over a completed period.

2026-10-11 battery (energy/finance): the question went to the analytics template, whose narration
printed the week's UTC bounds under an invented year, "27 September 2023 23:00 to 04 October
2023", for a week of 2026. The aggregate lane now sums interval energy over a period that is OVER
(no partial last unit, so BUG-936's reason for leaving it to the period summary does not arise),
and any narration that still writes a year its sources do not hold is corrected.
"""

import pytest

from orchestrator.services.aggregate_lane import _names_a_completed_period, wants_lane
from orchestrator.services.narration_validators import correct_unwritten_years

pytestmark = pytest.mark.unit


@pytest.mark.parametrize(
    "question",
    [
        "How much electricity did the building use last week?",
        "How much energy was used yesterday?",
        "What was the total electricity consumption last month?",
    ],
)
def test_energy_over_a_completed_period_is_claimed(question):
    intent = wants_lane(question, 6, False, True, {"energy"})
    assert intent is not None and intent.stat == "total"


@pytest.mark.parametrize(
    "question",
    [
        "How much electricity has the building used this week?",
        "How much electricity is being used right now?",
    ],
)
def test_a_period_still_running_is_left_to_the_period_summary(question):
    assert wants_lane(question, 6, False, True, {"energy"}) is None


def test_completed_periods_are_recognised():
    assert _names_a_completed_period("energy use the week before")
    assert not _names_a_completed_period("energy use this month")


def test_an_invented_year_is_replaced_by_the_window_year():
    out = correct_unwritten_years(
        "**15,148 kWh** from 27 September 2023 23:00 to 04 October 2023 22:50.",
        ["Sensor readings 2026-09-27 23:00"],
        ("2026-09-27 23:00:00", "2026-10-04 22:59:59"),
    )
    assert "2023" not in out and "27 September 2026" in out and "04 October 2026" in out


def test_a_year_the_question_wrote_is_kept():
    out = correct_unwritten_years(
        "In 3 March 2025 the mean was 21 C.",
        ["what was the temperature on 3 March 2025?"],
        ("2025-03-03 00:00:00", "2025-03-03 23:59:59"),
    )
    assert "3 March 2025" in out


def test_a_window_spanning_two_years_drops_rather_than_guesses():
    out = correct_unwritten_years("from 30 December 2019", [], ("2025-12-28", "2026-01-03"))
    assert out == "from 30 December"
