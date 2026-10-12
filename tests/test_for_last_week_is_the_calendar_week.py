""""for last week" names the calendar week; "over the last week" is a trailing duration.

2026-10-11 battery (researcher): "can I export the CO2 readings for floor 3 for last week as CSV?"
was fetched as the default 30 days, because every "<preposition> last <unit>" was refused as a
trailing duration. The article is what makes it one.
"""

import pytest

from orchestrator.services.requested_interval import named_period

pytestmark = pytest.mark.unit


@pytest.mark.parametrize(
    "text, unit",
    [
        ("export the CO2 readings for floor 3 for last week as CSV", "week"),
        ("how much energy was used during last month", "month"),
        ("what happened in last week's readings", "week"),
    ],
)
def test_without_an_article_the_calendar_period_is_named(text, unit):
    assert named_period(text) == (unit, [1])


@pytest.mark.parametrize(
    "text",
    [
        "CO2 over the last week",
        "temperature for the past month",
        "energy in the previous week",
        "readings from the past week",
        "noise across 3 weeks",
    ],
)
def test_a_trailing_duration_is_still_refused(text):
    assert named_period(text) is None
