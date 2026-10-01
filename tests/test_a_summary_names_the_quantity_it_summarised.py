# -*- coding: utf-8 -*-
"""A summary must name the quantity it summarised, and must not claim a question it cannot answer.

Three defects, all measured live on 2026-09-30 with a container-log trace, all on the SAME code
path -- `aggregate_lane.wants_lane` case 6, the "a bare measurand is not a refusal" summary -- and
all with DIFFERENT causes. The answer-relevance gate was right about every one of them; the gate is
the messenger and these are the upstream defects (BUG-1252).

BUG-1255 -- "What is the return air temperature?"
    The pipeline bound this building's six AHU return-air points correctly, one per floor, about
    13,120 rows each, newest four minutes before the ask. The answer was
    **"Across the building temperature is averaging 21.4 degC"** with a per-floor table under it
    reading "Floor 0 | 26.0". An occupant is told their floor is 26 degC when the figure is the
    air inside the ductwork. The fetch was right and the LABEL was false.

BUG-1316 -- "Has the humidity changed significantly in the past hour?"
    `parse_intent` REFUSES a change question by design -- `_NOT_AN_AGGREGATE` exists for exactly
    that -- and case 6 could not tell that refusal apart from "found no statistic word", so it
    re-admitted the question and answered with a window summary. Measured the same day:
    "how's the air quality index trending over the last few hours?" was answered
    "Across the building air quality is averaging 69.2 level" and **the gate did not fire**, so
    the gate is not a backstop for this family.

BUG-1317 -- "how is water consumption montored here?"
    A question about the METHOD, parsed as a TOTAL because `_TOTAL` matches `consum\\w*`, and
    answered with seven flow meters' latest values.

Every question here is VERBATIM from a live run or from `classified_corpus.csv`.
"""

from __future__ import annotations

import inspect

import pytest

from orchestrator.services import aggregate_lane as al

# ─────────────────────────────────────────────────────────────────────────────
# The real label sets, read from this building's graph on 2026-09-30
# ─────────────────────────────────────────────────────────────────────────────

AHU_RETURN_AIR = [f"Air Handling Unit — Floor {n} return air temperature" for n in range(6)]
ROOM_TEMP = [f"Room {n}.01 — Office temperature [degC]" for n in range(6)]
WATER_FLOW = [f"Floor{n} water_flow_rate [L/s]" for n in range(6)] + [
    "Water Flow Sensor - Hot Water Circuit"
]
SOUND = [f"Room 0.0{n} — Service Room noise [dB]" for n in range(1, 8)]


# ─────────────────────────────────────────────────────────────────────────────
# BUG-1255: what the answer CALLS the quantity
# ─────────────────────────────────────────────────────────────────────────────


def test_the_return_air_question_is_named_return_air_temperature():
    """The verbatim question that produced the false lead."""
    assert (
        al.asked_quantity_name("What is the return air temperature?", "temperature", AHU_RETURN_AIR)
        == "return air temperature"
    )


def test_a_bare_temperature_question_is_still_called_temperature():
    """The qualifier is the READER'S. A question that names none is untouched."""
    assert al.asked_quantity_name("What is the temperature?", "temperature", ROOM_TEMP) == (
        "temperature"
    )
    assert al.asked_quantity_name("What is the average temperature?", "temperature", ROOM_TEMP) == (
        "temperature"
    )


def test_a_qualifier_the_bound_sensors_do_not_carry_is_refused():
    """The safety property: the name cannot claim a quantity the bound set does not measure.

    If the reader asks for the outside air temperature and the pipeline binds room sensors, the
    coarse name is kept and the relevance gate goes on catching the off-topic answer as before.
    """
    assert al.asked_quantity_name(
        "What is the outside air temperature?", "temperature", ROOM_TEMP
    ) == ("temperature")
    # ... and the same question against the sensors that DO carry it is named precisely.
    outside = [f"Outside Air Temperature Sensor feed outside_weather_temperature {n}" for n in "ab"]
    assert (
        al.asked_quantity_name("What is the outside air temperature?", "temperature", outside)
        == "outside air temperature"
    )


def test_no_labels_at_all_keeps_the_coarse_name():
    assert al.asked_quantity_name("What is the return air temperature?", "temperature", []) == (
        "temperature"
    )


@pytest.mark.parametrize(
    "question, measurand, labels, expected",
    [
        # Measured over both corpora: the only name this moved in 11,211 questions before the
        # guard was a possessive.
        ("What's today's occupancy?", "occupancy", ["Entry Count Sensor - Floor 1"], "occupancy"),
        # "ai" is a SUBSTRING of "air", and a substring check named the quantity "ai temperature".
        (
            "What can people do if they don't like the AI temperature settings?",
            "temperature",
            AHU_RETURN_AIR,
            "temperature",
        ),
        # A truncated question from the real corpus: "re" inside "Reception".
        (
            "re temperature conditions consistent throughout the building?",
            "temperature",
            ROOM_TEMP,
            "temperature",
        ),
        # An evaluative adjective is not a qualifier: "low water flow" is not a quantity.
        (
            "If low water flow is detected by AI does it call a plumber?",
            "flow",
            WATER_FLOW,
            "water flow",
        ),
        # A word the coarse name already carries must not be repeated ("air air quality").
        (
            "how has air quality changed since the building opened today?",
            "air quality",
            ["Air Quality Level Sensor (low/medium/high) installed-node 5.01"],
            "air quality",
        ),
    ],
)
def test_the_name_is_not_moved_by_a_fragment_a_possessive_or_an_adjective(
    question, measurand, labels, expected
):
    assert al.asked_quantity_name(question, measurand, labels) == expected


def test_the_qualifier_is_matched_word_by_word_not_by_substring():
    """Pins the MECHANISM, so nobody can satisfy the cases above with a stop-list of words."""
    src = inspect.getsource(al.asked_quantity_name)
    assert "_WORDS_RE.findall" in src, "the label check must tokenise, not use `in`"
    assert "set(extra) <= nm" in src, "each qualifier word must be a WORD of every label"


def test_the_summary_lead_and_its_boundary_both_carry_the_specific_name():
    """The two places the reader sees the quantity named."""
    groups = [
        al.GroupStat(
            key=str(n),
            value=20.0 + n,
            low=19.0 + n,
            high=21.0 + n,
            sensors=1,
            readings=10,
            total=200.0 + 10 * n,
        )
        for n in range(3)
    ]
    text = al.render_summary(
        groups,
        measurand="temperature",
        quantity="return air temperature",
        unit="°C",
        window=al.Window(start=None, end=None, label="the last hour", latest=True),
        sensors_used=6,
        sensors_requested=6,
        floors_seen=6,
        excluded=0,
        excluded_sensors=0,
        no_reading=0,
        unplaced=0,
        bands_checked=True,
    )
    assert "Across the building return air temperature is averaging" in text
    assert "return air temperature sensors" in text
    assert "Across the building temperature is averaging" not in text


def test_the_renderers_prefer_the_specific_name_and_fall_back_to_the_coarse_one():
    for fn in (al.render_summary, al.render_extreme, al.render_exceedance):
        sig = inspect.signature(fn)
        assert "quantity" in sig.parameters, f"{fn.__name__} must accept the specific name"
        assert sig.parameters["quantity"].default == "", f"{fn.__name__} must default to coarse"
        assert "quantity or display_name(measurand)" in inspect.getsource(fn)


def test_the_lane_passes_the_specific_name_to_its_renderers():
    """Wiring read from the source: a helper nothing calls is lesson #170's defect again."""
    src = inspect.getsource(al.try_answer)
    assert "quantity=asked_quantity_name(" in src


# ─────────────────────────────────────────────────────────────────────────────
# BUG-1316: a question this module REFUSED must not be re-admitted as a summary
# ─────────────────────────────────────────────────────────────────────────────


def _wants(question: str, kinds=("temperature",)):
    """wants_lane as the caller reaches it for a bare-measurand value question."""
    return al.wants_lane(question, 6, False, True, list(kinds), False, True, False)


@pytest.mark.parametrize(
    "question",
    [
        # the three measured live on 2026-09-30
        "Has the humidity changed significantly in the past hour?",
        "How has the temperature changed over time?",
        "how's the air quality index trending over the last few hours?",
        # four more of the shape, verbatim from classified_corpus.csv
        "are there any areas where noise levels suddenly increased?",
        "how has air quality changed since the building opened today?",
        "is the CO2 trend rising fast enough to signal poor ventilation?",
        "Has the air quality suddenly decreased?",
    ],
)
def test_a_change_or_trend_question_is_not_answered_with_a_snapshot(question):
    assert _wants(question) is None, "a summary of the window does not say whether it changed"


@pytest.mark.parametrize(
    "question",
    [
        # the method questions the aggregate lane claimed, verbatim from classified_corpus.csv
        "How do you measure noise levels in dB?",
        "how is humidity monitored",
        "How do you track occupancy?",
        "How does the building detect poor air quality?",
        "How do you monitor water usage and flow rate?",
        "How is relative humidity monitored in the building?",
    ],
)
def test_a_monitoring_method_question_is_not_answered_with_a_statistic(question):
    assert al.parse_intent(question) is None, "a method question is not an aggregate"
    assert _wants(question) is None


@pytest.mark.parametrize(
    "question",
    [
        # THE COUNTERFACTUAL. Case 6 exists for these and must keep taking them.
        "What is the return air temperature?",
        "What is the CO2 level right now?",
        "how does the building prevent overheating in sun exposed areas?",
        "What is the humidity?",
    ],
)
def test_a_bare_measurand_value_question_is_still_summarised(question):
    assert _wants(question) is not None, "case 6 must still answer a question with no statistic"


def test_a_genuine_total_still_parses_as_a_total():
    """The method pattern must not swallow a real consumption question."""
    got = al.parse_intent("How much water did we use this week?")
    assert got is not None and got.stat == "total"


def test_a_time_of_day_question_still_reaches_the_hourly_profile():
    """`_NOT_AN_AGGREGATE` matches "when"; the profile branch sits ABOVE the new gate and so is
    unaffected. Ordering is the whole correctness argument, so it is pinned."""
    assert (
        al.wants_lane("When is the building busiest?", 6, False, True, [], False, True, True)
        is not None
    )


def test_the_gate_is_keyed_on_the_modules_own_refusal_not_on_a_second_word_list():
    """Pins the MECHANISM. A second regex beside `_NOT_AN_AGGREGATE` is two parts of the system
    holding their own answer to one question, which is the shape this repo keeps paying for."""
    src = inspect.getsource(al.wants_lane)
    assert "_NOT_AN_AGGREGATE.search(question" in src
    assert src.index("if intent is None and profile") < src.index("_NOT_AN_AGGREGATE.search")
