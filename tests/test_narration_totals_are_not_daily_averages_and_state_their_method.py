# -*- coding: utf-8 -*-
"""A total is not a daily average, and a computed total says how it was computed (2D-09, wave 2).

Both cases are wave-1 live answers. *"Compare this week's electricity use with last week"* called
the two week TOTALS "the highest daily average" and "the lowest" one line after giving the real
per-day figures. *"How much water did floor 3 use yesterday?"* printed "used 2,058,048 L" beside an
average flow of 23.82 L/s and nothing else: 2,058,048 is exactly 23.82 x 86,400, the average rate
multiplied by a full day whatever part of the day the readings covered.
"""

import pytest

from orchestrator.services import narration_totals as nt
from orchestrator.services import narration_validators as nv

pytestmark = pytest.mark.unit

WEEKS = (
    "**This week’s average electricity use is 115 kWh per day lower than last week’s "
    "(1,712 kWh day⁻¹ vs. 1,827 kWh day⁻¹).**  \n"
    "The 2026‑W37 total of 12,077 kWh (3462 readings, 1.93–4.94 kWh) represents the highest daily "
    "average, while the 2026‑W38 total of 8,863 kWh (2538 readings, 0.26–6.21 kWh) represents "
    "the lowest.  \n"
    "The spread between the two weeks is 115 kWh per day, a 6.3 % decrease.  \n"
    "2026‑W38 is still in progress, covering only 124 of 168 hours.\n\n"
    "---\n**You might also ask:** Plot the comparison? | Export results?\n\n"
    "---\n*Sources: `Building model` `Energy Metering System`*"
)

WATER = (
    "**Floor3 water_flow_rate [L/s] used 2,058,048 L yesterday.**  \n"
    "The average flow rate was 23.82 L/s, with a median of 23.73 L/s.  \n"
    "The lowest recorded rate was 16.73 L/s and the highest was 31.29 L/s, giving a spread of "
    "14.56 L/s.  \n"
    "Thus, Floor3 water_flow_rate [L/s] consumed 2,058,048 L of water yesterday.\n\n"
    "---\n**You might also ask:** Plot this data? | Compare with another zone?\n\n"
    "---\n*Sources: `Building model` `Water Flow Sensing System` `Analytics Engine`*"
)


# ── a total called a daily average ───────────────────────────────────────────


def test_a_sentence_that_calls_two_week_totals_the_highest_and_lowest_daily_average_is_rebuilt():
    out = nt.fix_total_called_daily_average(WEEKS)
    assert "daily average, while" not in out and "represents the lowest" not in out
    assert (
        "The 2026‑W37 total was 12,077 kWh (3462 readings, 1.93–4.94 kWh), and the 2026‑W38 total "
        "was 8,863 kWh (2538 readings, 0.26–6.21 kWh)." in out
    )


def test_the_per_day_figures_the_answer_already_states_are_untouched():
    out = nt.fix_total_called_daily_average(WEEKS)
    assert "1,712 kWh day⁻¹ vs. 1,827 kWh day⁻¹" in out
    assert "a spread" not in out and "The spread between the two weeks is 115 kWh per day" in out
    assert "covering only 124 of 168 hours" in out
    assert "You might also ask" in out and "Sources" in out


@pytest.mark.parametrize(
    "text",
    [
        # a real daily average, no total in the sentence
        "The daily average was 1,712 kWh per day, the highest of the two weeks.",
        # a total and a daily average, not tied to each other
        "The 2026‑W37 total of 12,077 kWh spans 7 days. The daily average is 1,725 kWh.",
        # a total said to be a total
        "The 2026‑W37 total of 12,077 kWh is the highest total of the two weeks.",
    ],
)
def test_a_sentence_that_does_not_call_a_total_a_daily_average_is_left_alone(text):
    assert nt.fix_total_called_daily_average(text) == text


def test_a_total_that_names_nothing_to_rebuild_around_is_dropped():
    text = "Floor 3 was busy. A total of 12,077 kWh is the highest daily average of the two weeks."
    assert nt.fix_total_called_daily_average(text) == "Floor 3 was busy."


# ── a computed total states its method ───────────────────────────────────────


def test_a_volume_total_beside_its_average_rate_gets_the_method_that_produced_it():
    out = nt.state_method_of_computed_total(WATER)
    assert "**Method:** computed as the average flow rate (23.82 L/s) × 24 h" in out
    assert "used 2,058,048 L yesterday" in out, "the total is kept; it now says what it is"
    body, _, footer = out.partition("\n---\n")
    assert "Method" in body and "You might also ask" in out and "Sources" in out


def test_a_total_that_is_not_a_whole_number_of_hours_reports_the_hours_it_really_covers():
    text = "**Floor 3 used 1,234,567 L.**  \nThe average flow rate was 23.82 L/s."
    out = nt.state_method_of_computed_total(text)
    assert "× 14.4 h" in out, "an integral over part of a day says how much of the day it covers"


def test_an_energy_total_beside_its_average_power_gets_its_method():
    text = "Floor 3 consumed 240 kWh yesterday. The average power was 10 kW."
    assert "average power (10 kW) × 24 h" in nt.state_method_of_computed_total(text)


@pytest.mark.parametrize(
    "text",
    [
        # the answer already says how
        "**Floor 3 used 2,058,048 L.** It is the sum of the interval volumes. Average flow rate 23.82 L/s.",
        WEEKS.replace("The spread", "These figures are the sum of readings. The spread"),
        # the meter boundary line is a method
        "Floor 3 used 12 kWh. **Boundary:** summed across 6 meters. Average power was 0.5 kW.",
        # a total with no rate beside it: nothing to check it by, so nothing is added
        "Floor 3 used 4.51 kWh yesterday.",
        # a rate with no total
        "The average flow rate was 23.82 L/s.",
        # a unit family that does not match (energy total, flow rate)
        "Floor 3 consumed 240 kWh. The average flow rate was 23.82 L/s.",
    ],
)
def test_a_total_that_already_says_how_or_has_nothing_to_check_it_by_is_left_alone(text):
    assert nt.state_method_of_computed_total(text) == text


# ── the pair, and the pipeline ───────────────────────────────────────────────


def test_validate_totals_runs_both_and_is_idempotent():
    # one answer carrying both defects; two whole answers concatenated would put the second
    # past the first one's footer, which is not a shape the pass ever sees
    both = (
        "**Floor 3 used 2,058,048 L yesterday.**  \n"
        "The average flow rate was 23.82 L/s.  \n"
        "The 2026‑W37 total of 12,077 kWh represents the highest daily average.\n"
    )
    res = nt.validate_totals(both, "analytics")
    assert {c.validator for c in res.changes} == {
        "fix_total_called_daily_average",
        "state_method_of_computed_total",
    }
    assert nt.validate_totals(res.text, "analytics").text == res.text


def test_content_lanes_are_never_edited():
    assert nt.validate_totals(WATER, "capability").text == WATER
    assert nt.validate_totals(WEEKS, "register").text == WEEKS


def test_the_full_pipeline_applies_them_to_a_narrated_answer():
    out = nv.validate_narration("How much water did floor 3 use yesterday?", WATER, "analytics")
    assert "**Method:** computed as the average flow rate" in out.text
    out = nv.validate_narration(
        "Compare this week's electricity use with last week.", WEEKS, "compare"
    )
    assert "represents the lowest" not in out.text
    assert "The 2026‑W37 total was 12,077 kWh" in out.text
