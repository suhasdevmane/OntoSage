"""Three aggregate-lane defects from the 2026-11-07 fresh probe.

1. "Compare the temperature in rooms 2.01 and 3.01 this morning" named no place to the lane (plural
   "rooms", and a bare "2.01 vs 3.01"), so two rooms were summarised "Across the building" with a
   per-floor table.
2. The same question's "this morning" was the classifier's guess: the trailing twelve hours,
   21:50 to 09:50, half of it last night.
3. "What was the average humidity across the building last week?" reached the ranking renderer and
   was headed "The highest average humidity in the period was 49.9 %, at Building exterior" -- a
   superlative nobody asked for, from the one sensor outside.
"""

from __future__ import annotations

import inspect
from datetime import datetime

import pytest

from orchestrator.services import aggregate_lane as al
from orchestrator.services.aggregate_support import names_a_place
from orchestrator.services.requested_interval import part_of_day_bounds

pytestmark = pytest.mark.unit

NOW = datetime(2026, 11, 7, 9, 50)  # a Saturday morning, building time = UTC in November


@pytest.mark.parametrize(
    "q",
    [
        "Compare the temperature in rooms 2.01 and 3.01 this morning.",
        "Rooms 2.01 and 3.01: which is warmer?",
        "temperature in 2.01 vs 3.01",
        "Is the fault in 4.09 upstream of the valve?",
    ],
)
def test_plural_rooms_and_bare_room_ids_name_a_place(q):
    assert names_a_place(q)


@pytest.mark.parametrize("q", ["What is the PM2.5 level?", "is 1.5 degrees a big change?"])
def test_a_decimal_quantity_is_not_a_room(q):
    assert not names_a_place(q)


def test_this_morning_is_six_until_now_while_it_is_still_running():
    assert part_of_day_bounds("CO2 this morning", None, now=NOW) == (
        "2026-11-07 06:00:00",
        "2026-11-07 09:50:00",
    )


def test_yesterday_afternoon_is_the_whole_part():
    assert part_of_day_bounds("CO2 yesterday afternoon", None, now=NOW) == (
        "2026-11-06 12:00:00",
        "2026-11-06 17:59:59",
    )


@pytest.mark.parametrize("q", ["noise this afternoon", "humidity this evening", "CO2 yesterday"])
def test_a_part_not_begun_or_a_whole_day_is_not_this_resolver(q):
    assert part_of_day_bounds(q, None, now=NOW) is None


def test_the_part_of_day_beats_the_pipelines_guess():
    w = al.resolve_window(
        "Compare the temperature in rooms 2.01 and 3.01 this morning.",
        "2026-11-06 21:50:00",
        "2026-11-07 09:50:00",
        None,
        now=NOW,
        parts_of_day=True,
    )
    assert (w.start, w.end) == ("2026-11-07 06:00:00", "2026-11-07 09:50:00")


def test_a_caller_reading_a_whole_day_still_gets_the_day():
    """comparison_windows reads 'yesterday morning' as a DAY and adds the hours itself."""
    w = al.resolve_window("CO2 yesterday morning", None, None, None, now=NOW)
    assert (w.start, w.end) == ("2026-11-06 00:00:00", "2026-11-06 23:59:59")


def test_the_pipelines_bounds_still_win_without_a_part_of_day():
    w = al.resolve_window(
        "humidity last week", "2026-10-26 00:00:00", "2026-11-01 23:59:59", None, now=NOW
    )
    assert (w.start, w.end) == ("2026-10-26 00:00:00", "2026-11-01 23:59:59")


def test_a_building_average_with_no_extreme_word_is_the_summary():
    src = inspect.getsource(al.try_answer)
    assert (
        'intent = AggregateIntent("summary", "floor", True, False, intent.now, intent.floors)'
        in src
    )
    assert (
        al.parse_intent("What was the average humidity across the building last week?").stat
        == "mean"
    )
    assert al._MAX.search("which floor had the highest average humidity")


def test_the_building_is_an_indoor_word_and_outdoors_still_wins():
    assert al._INDOOR_WORDS.search("average humidity across the building")
    assert al._OUTDOOR_WORDS.search("humidity outside the building")


def _floors_now():
    return [
        al.GroupStat(f, sensors=1, readings=1, value=v, low=v, high=v, mean=v, total=v)
        for f, v in (("5", 50.0), ("2", 44.0), ("0", 2.0))
    ]


def _occupancy(asks_extreme):
    return al.render_extreme(
        al.AggregateIntent("max", "floor", True, False, True, ()),
        _floors_now(),
        measurand="occupancy",
        unit="",
        window=al.Window("2026-11-07 09:00:00", "2026-11-07 10:00:00", "now", latest=True),
        sensors_used=3,
        sensors_requested=3,
        floors_seen=3,
        peak_at=None,
        excluded=0,
        excluded_sensors=0,
        no_reading=0,
        unplaced=0,
        bands_checked=True,
        additive=True,
        asks_extreme=asks_extreme,
    )


def test_a_head_count_with_no_most_word_leads_with_the_building_total():
    out = _occupancy(asks_extreme=False)
    assert out.startswith("**96 people are counted in the building right now**, across 3 floors")


def test_which_floor_has_the_most_people_still_leads_with_the_floor():
    assert _occupancy(asks_extreme=True).startswith(
        "**Floor 5 has the most people in it right now: 50**"
    )


# ── an end date that has passed is said to have passed (BUG-1715) ───────────────────────────


def test_a_narrated_end_date_that_has_passed_gets_a_system_line():
    from datetime import date

    from orchestrator.services.register_facts import passed_end_line

    rows = [{"recordId": {"value": "CON-2025-003"}, "effectiveTo": {"value": "2026-11-04"}}]
    text = "The contract CON-2025-003 expires on **4 November 2026**."
    line = passed_end_line(text, rows, date(2026, 11, 7))
    assert (
        "That date has already passed" in line and "CON-2025-003 ended on 4 November 2026" in line
    )
    assert (
        passed_end_line("CON-2025-003 expired on 4 November 2026.", rows, date(2026, 11, 7)) == ""
    )
    assert passed_end_line(text, rows, date(2026, 11, 1)) == ""  # not yet past


# ── a compliance question is a verdict against the limit, the right way round ───────────────


def test_a_compliance_question_is_an_exceedance_question():
    i = al.parse_intent("Is the building compliant with the CO2 guideline this month?")
    assert i is not None and i.stat == "exceed" and i.verdict
    assert al._COMPLIANCE_RE.search("Does CO2 meet the WELL standard on floor 3?")
    assert not al._COMPLIANCE_RE.search(
        "Which rooms can host events without breaching setup limits?"
    )


def _exceed(compliance, over):
    import dataclasses

    g = al.GroupStat(
        "Room 1",
        sensors=1,
        readings=10,
        value=900.0,
        low=500.0,
        high=1100.0,
        mean=900.0,
        total=9000.0,
    )
    if dataclasses.is_dataclass(g) and getattr(type(g), "__dataclass_params__").frozen:
        g = dataclasses.replace(
            g, exceed_readings=3 if over else 0, exceed_sensors=1 if over else 0
        )
    else:
        g.exceed_readings, g.exceed_sensors = (3, 1) if over else (0, 0)
    return al.render_exceedance(
        [g],
        [g],
        measurand="co2",
        unit="ppm",
        window=al.Window("2026-11-01 00:00:00", "2026-11-07 10:00:00", "this month"),
        threshold=al.Threshold(1000.0, "ppm", "WELL Building Standard v2", "co2"),
        sensors_used=1,
        sensors_requested=1,
        peak=g,
        peak_at=None,
        excluded=0,
        excluded_sensors=0,
        no_reading=0,
        unplaced=0,
        bands_checked=True,
        compliance=compliance,
    )


def test_compliance_puts_yes_and_no_the_right_way_round():
    assert _exceed(True, over=True).startswith("**Not fully.**")
    assert _exceed(True, over=False).startswith("**Yes, within the limit.**")
    assert _exceed(False, over=True).startswith("**Yes.**")  # "has it been high?" keeps its yes


# ── emissions: electricity x the building's declared grid carbon intensity ──────────────────


def _energy_answer():
    return {
        "formatted_response": "**13,845 kWh was used in the building**.",
        "aggregate": {"unit": "kWh"},
        "figures": {"total": 13845.0},
    }


def _sparql_factor(values):
    async def run(q):
        return {
            "results": {
                "bindings": [
                    {"f": {"value": str(v)}, "src": {"value": "the EPC record"}} for v in values
                ]
            }
        }

    return run


def test_an_electricity_total_gets_its_emissions_when_they_are_asked_for():
    import asyncio

    from orchestrator.services.utility_cost import append_carbon

    out = asyncio.run(
        append_carbon(
            _energy_answer(),
            "What was the carbon footprint of the electricity last week?",
            "energy",
            _sparql_factor([233.0]),
        )
    )
    assert "about 3,226 kg CO2e (3.2 t)" in out["formatted_response"]
    assert out["figures"]["kg CO2e"] == 3225.885


def test_no_declared_factor_is_said_never_a_national_average():
    import asyncio

    from orchestrator.services.utility_cost import append_carbon

    out = asyncio.run(
        append_carbon(
            _energy_answer(),
            "carbon emissions from electricity last week?",
            "energy",
            _sparql_factor([]),
        )
    )
    assert "declares no single grid carbon intensity" in out["formatted_response"]


def test_a_co2_concentration_question_is_not_an_emissions_question():
    from orchestrator.services.utility_cost import asks_for_carbon

    assert not asks_for_carbon("Is the CO2 high in room 5.01?")
    assert asks_for_carbon("How much CO2e did the electricity produce yesterday?")


def test_the_carbon_rule_routes_an_electricity_emissions_question_and_not_a_target():
    from types import SimpleNamespace

    from orchestrator.services import routing_contract as rc

    def ctx(q):
        return SimpleNamespace(intent="metadata", query=q, normalized={"concepts": []})

    assert (
        rc._r_metered_carbon_is_computed(
            ctx("What was the building's carbon footprint from electricity last month?")
        )
        == "analytics"
    )
    assert (
        rc._r_metered_carbon_is_computed(
            ctx("What are our carbon emissions targets for this month?")
        )
        is None
    )
    assert (
        al.parse_intent(
            "What was the building's carbon footprint from electricity last month?"
        ).stat
        == "total"
    )


# ── a comparison names the period its question asks about ──────────────────────────────────


def test_an_earlier_subject_is_judged_and_named_and_now_is_the_later_period():
    from orchestrator.services.comparison_lane import render
    from orchestrator.services.comparison_windows import WindowPair

    fri = al.Window("2026-11-06 00:00:00", "2026-11-06 23:59:59", "Fri 06 Nov")
    sat = al.Window("2026-11-07 00:00:00", "2026-11-07 11:00:00", "Sat 07 Nov")
    yesterday = {"aggregate": {"group": "floor", "unit": "°C"}, "figures": {"Floor 4 mean": 23.0}}
    today = {"aggregate": {"group": "floor", "unit": "°C"}, "figures": {"Floor 4 mean": 22.7}}
    out = render(
        WindowPair(current=fri, baseline=sat),
        yesterday,
        today,
        question="Was it warmer yesterday than today on floor 4?",
    )
    assert out.startswith(
        "**Yes — the Floor 4 average was higher in Fri 06 Nov: 23 against 22.7.**"
    )
    assert "Comparing Sat 07 Nov against Fri 06 Nov." in out


def test_the_same_time_yesterday_is_the_same_hour_a_day_earlier():
    from orchestrator.services.comparison_windows import resolve_pair

    p = resolve_pair(
        "How does the humidity in Room 5.01 compare with yesterday at the same time?",
        None,
        None,
        None,
        now=datetime(2026, 11, 7, 12, 25),
    )
    assert (p.current.start, p.current.end) == ("2026-11-07 11:25:00", "2026-11-07 12:25:00")
    assert (p.baseline.start, p.baseline.end) == ("2026-11-06 11:25:00", "2026-11-06 12:25:00")
    assert p.lane_question == "What was the average of the humidity in Room 5.01?"
    week = resolve_pair(
        "How does the noise compare with the same time last week?",
        None,
        None,
        None,
        now=datetime(2026, 11, 7, 12, 25),
    )
    assert week.baseline.start == "2026-10-31 11:25:00"


def test_the_week_before_last_is_two_weeks_back_even_over_a_last_week_guess():
    q = "How much electricity did the building use the week before last week?"
    w = al.resolve_window(q, "2026-10-26 00:00:00", "2026-11-01 23:59:59", None, now=NOW)
    assert (w.start, w.end) == ("2026-10-19 00:00:00", "2026-10-25 23:59:59")
    assert (
        al.resolve_window("energy last week", None, None, None, now=NOW).start
        == "2026-10-26 00:00:00"
    )


def test_a_too_warm_question_gets_a_verdict_against_the_standards_band():
    assert al.present_comfort_verdict(
        "Is it too warm on floor 3 right now?", "temperature", "°C", 23.3, 24.6
    ).startswith("**No.** Every reading is under the 26 °C upper limit")
    assert al.present_comfort_verdict(
        "Is it too warm on floor 3 right now?", "temperature", "°C", 23.3, 26.6
    ).startswith("**Yes, in places.**")
    assert (
        al.present_comfort_verdict("Will it get too warm tomorrow?", "temperature", "°C", 20, 30)
        == ""
    )
    assert al.present_comfort_verdict("What is the temperature?", "temperature", "°C", 20, 30) == ""
