# -*- coding: utf-8 -*-
"""A verdict over an impossible number is a fabrication wearing a real value.

CAVEAT-053. "is the wind strong?" answered "Yes - the wind is very strong right
now. The most recent reading shows a value of approximately 8308 (the unit used in
your data)." The reply admits it cannot name the unit and rules on the value
anyway. The column behind it ranges 0.14 to 9998.58 with a mean of 4506 — not wind
speed in any unit anyone uses.

"Strong" claims the number was compared against something. When it cannot be a
reading of that quantity in ANY usual unit, there is nothing to compare it to.

The bounds are facts about the physical world, not about a building — air
temperature has the same range everywhere — so this guard travels with the code.
"""

from __future__ import annotations

import pytest

from orchestrator.services import plausibility as pl

pytestmark = pytest.mark.unit


# ── the live failure ─────────────────────────────────────────────────────────


def test_the_wind_verdict_that_started_this_is_caught():
    draft = (
        "Yes - the wind is very strong right now. The most recent reading shows a "
        "value of approximately 8308 (the unit used in your data)."
    )
    note = pl.implausibility_note("is the wind strong?", draft)
    assert note is not None
    assert "8308" in note
    assert "raw or unscaled" in note


def test_a_believable_reading_is_left_alone():
    """A verdict over a plausible value is a legitimate answer."""
    draft = "The wind is fairly strong right now, at 14.2 m/s."
    assert pl.implausibility_note("is the wind strong?", draft) is None


def test_reporting_an_odd_number_without_judging_it_is_fine():
    """A raw number reported AS a raw number needs no caveat — only a verdict does."""
    draft = "The sensor's most recent value is 8308."
    assert pl.implausibility_note("what does the wind sensor read?", draft) is None


# ── the pieces ───────────────────────────────────────────────────────────────


@pytest.mark.parametrize(
    "text,expected",
    [
        ("is the wind strong?", "wind"),
        ("what is the temperature in room 5?", "temperature"),
        ("how humid is it?", "humidity"),
        ("what is the CO2 level?", "co2"),
        ("how loud is the noise?", "sound"),
        ("who wrote Hamlet?", None),
    ],
)
def test_the_measurand_is_identified_from_ordinary_wording(text, expected):
    assert pl.measurand_of(text) == expected


@pytest.mark.parametrize(
    "value,measurand,flagged",
    [
        (8308, "wind", True),
        (14.2, "wind", False),
        (22.5, "temperature", False),
        (-273, "temperature", True),
        (45, "humidity", False),
        (5000, "humidity", True),
        (850, "co2", False),
        (99999, "co2", True),
    ],
)
def test_values_are_judged_against_the_physical_range(value, measurand, flagged):
    got = pl.implausible_values(f"the reading is {value}", measurand)
    assert bool(got) is flagged


@pytest.mark.parametrize(
    "text,is_verdict",
    [
        ("the wind is very strong", True),
        ("CO2 is high in this room", True),
        ("the temperature is comfortable", True),
        ("the most recent value is 8308", False),
        ("the sensor reported 22.4 at 14:05", False),
    ],
)
def test_a_verdict_is_told_apart_from_a_report(text, is_verdict):
    assert pl.asserts_verdict(text) is is_verdict


def test_an_unknown_quantity_is_never_flagged():
    """Precision-first: no range known means no opinion, not a blanket warning."""
    assert (
        pl.implausibility_note("how many badges were issued?", "That is very high, at 99999.")
        is None
    )


@pytest.mark.parametrize("blank", ["", "   ", None])
def test_blank_input_is_silent(blank):
    assert pl.implausibility_note(blank, "very strong at 8308") is None
    assert pl.implausibility_note("is the wind strong?", blank) is None


def test_the_ranges_describe_physics_not_a_building():
    import inspect

    src = inspect.getsource(pl).lower()
    for literal in ("bldg1", "bldg2", "bldg3", "abacws", "buildsys", "cardiff"):
        assert literal not in src, f"plausibility must not name a building: {literal}"


# ── numbers that are not readings ────────────────────────────────────────────


@pytest.mark.parametrize(
    "text",
    [
        "On 2026-08-06 the wind sensor was installed.",
        "Readings taken at 14:40 and 09:15 on 6 August 2026.",
    ],
)
def test_years_and_clock_times_are_not_judged_as_readings(text):
    """Flagging the year 2026 as an impossible wind speed would discredit the
    caveat wherever it is right."""
    assert pl.implausible_values(text, "wind") == []


def test_a_real_reading_beside_a_timestamp_is_still_caught():
    text = "At 14:40 on 2026-08-06 the wind value was 8308."
    assert pl.implausible_values(text, "wind") == [8308.0]
