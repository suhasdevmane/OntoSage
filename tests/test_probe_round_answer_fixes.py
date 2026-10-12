"""Answer defects found by the 2026-10-10 Open WebUI probe rounds, pinned below the lanes.

BUG-1513 a light-level chart refused as the wrong quantity ("Luminance Sensor");
BUG-1516 a study area placed in a plant room;
BUG-1517/1541 a facet value the model paraphrased, or matched too narrowly;
BUG-1529 two parts of days could not be compared;
BUG-1537 the register's counted "none" rewritten as a search miss;
BUG-1538 forecasts began where TRAINING ended; BUG-1539 a "total" fold was a mean of single sensors.
No building, room of the study, or study date is named; every record is synthetic.
"""

from datetime import datetime

import numpy as np
import pandas as pd
import pytest

pytestmark = pytest.mark.unit


# ── forecasting ──────────────────────────────────────────────────────────────────────────────


def _seasonal_series(n: int = 193) -> pd.Series:
    idx = pd.date_range("2026-10-02 11:00", periods=n, freq="h")
    t = np.arange(n)
    vals = 100 + 80 * np.sin(t * 2 * np.pi / 24) + np.linspace(0, 60, n)
    vals = vals + np.random.RandomState(1).normal(0, 5, n)
    return pd.Series(vals, index=idx)


def test_holt_winters_forecasts_from_the_last_observation():
    from orchestrator.services.forecasting.models.exp_smoothing_forecaster import (
        ExpSmoothingForecaster,
    )

    s = _seasonal_series()
    out = ExpSmoothingForecaster(seasonal_periods=24).fit_predict(s, 24)
    assert pd.Timestamp(out["future_index"][0]) == s.index[-1] + pd.Timedelta("1h")
    # the level continues from the end of the series, not from the end of the training span
    assert abs(out["forecast"][0] - s.iloc[-1]) < 40


def test_a_total_fold_sums_sensors_that_report_at_different_seconds():
    from orchestrator.services.forecasting.scope import aggregate_records

    rows = []
    for sensor, (second, value) in enumerate(
        [(3, 10), (17, 20), (29, 30), (41, 40), (53, 50), (59, 60)]
    ):
        for hour in range(3):
            stamp = datetime(2026, 10, 10, 8 + hour, 0, second).isoformat()
            rows.append({"uuid": f"u{sensor}", "timestamp": stamp, "value": value})
    total, n = aggregate_records(rows, "total", freq="1h")
    assert n == 6
    assert [r["value"] for r in total] == [210.0, 210.0, 210.0]
    mean, _ = aggregate_records(rows, "mean", freq="1h")
    assert [r["value"] for r in mean] == [35.0, 35.0, 35.0]


def test_a_total_bucket_with_too_few_sensors_is_not_published():
    from orchestrator.services.forecasting.scope import aggregate_records

    rows = [{"uuid": f"u{i}", "timestamp": "2026-10-10 08:00:05", "value": 10} for i in range(5)]
    rows.append({"uuid": "u0", "timestamp": "2026-10-10 09:00:05", "value": 10})  # one of five
    total, _ = aggregate_records(rows, "total", freq="1h")
    assert [r["timestamp"] for r in total] == ["2026-10-10 08:00:00"]


# ── two parts of days ────────────────────────────────────────────────────────────────────────


def test_this_morning_is_compared_with_yesterday_morning_like_for_like():
    from orchestrator.services.comparison_windows import resolve_pair

    now = datetime(2026, 10, 10, 9, 30)  # store (UTC) time: 10:30 in British Summer Time
    pair = resolve_pair(
        "Compare CO2 in room 1.06 this morning with yesterday morning.",
        None,
        None,
        "Europe/London",
        now=now,
    )
    assert pair is not None
    assert (pair.current.start, pair.current.end) == ("2026-10-10 05:00:00", "2026-10-10 09:30:00")
    assert (pair.baseline.start, pair.baseline.end) == (
        "2026-10-09 05:00:00",
        "2026-10-09 09:30:00",
    )
    assert "so far" in pair.current.label


def test_a_part_of_day_that_has_not_started_is_not_compared():
    from orchestrator.services.comparison_windows import resolve_pair

    now = datetime(2026, 10, 10, 9, 30)
    assert (
        resolve_pair(
            "Was it warmer this afternoon than yesterday afternoon?",
            None,
            None,
            "Europe/London",
            now=now,
        )
        is None
    )


def test_week_comparisons_are_unchanged_by_the_part_of_day_rule():
    from orchestrator.services.comparison_windows import _part_day_pair

    assert _part_day_pair("the temperature this week", "last week", "Europe/London", None) is None


# ── charts ───────────────────────────────────────────────────────────────────────────────────


def test_a_luminance_sensor_is_a_light_level_series():
    from orchestrator.services.chart_policy import series_matches

    rows = [{"uuid": "a", "value": 400}]
    meta = {"a": {"label": "Overhead Luminance Sensor - Floor 4", "unit": ""}}
    assert series_matches(["illuminance"], rows, meta)
    meta_cls = {
        "a": {
            "label": "Point 17",
            "brick_class": "https://brickschema.org/schema/Brick#Luminance_Sensor",
        }
    }
    assert series_matches(["illuminance"], rows, meta_cls)


# ── amenities ────────────────────────────────────────────────────────────────────────────────


def test_no_amenity_is_placed_in_a_service_space():
    from orchestrator.services.deliberation.amenities import plan_amenities
    from orchestrator.services.deliberation.coverage_audit import SpaceCoverage

    ns = "http://example.org/b#"
    spaces = [
        SpaceCoverage(space_iri=f"{ns}R0.0{i}", label=label, floor="Floor0")
        for i, label in enumerate(["Mechanical Plant Room", "Storage Room", "Common Room"], 1)
    ] + [
        SpaceCoverage(space_iri=f"{ns}R1.0{i}", label=label, floor="Floor1")
        for i, label in enumerate(["Plant Room", "Service Room"], 1)
    ]
    plan = plan_amenities(spaces)
    placed = [p["space_label"] for kind in plan.values() for p in kind]
    assert placed and all(
        "Plant" not in p and "Storage" not in p and "Service" not in p for p in placed
    )
    assert not any(p["floor"] == "Floor1" for kind in plan.values() for p in kind)


# ── facet values ─────────────────────────────────────────────────────────────────────────────

RECORDED = [
    "Atrium / reception area",
    "Collaborative pod / group study room",
    "Large seminar / teaching room",
    "Lecture / seminar room",
    "Meeting room / office",
    "Research lab / seminar room",
    "Seminar room",
    "Study room",
    "Study room / seminar room",
    "Teaching lab",
    "Teaching room",
]


def test_a_paraphrased_value_is_matched_on_the_question_s_own_words():
    from orchestrator.services.deliberation.compiler import _match_enum_by_word

    got = _match_enum_by_word(
        "Open study", RECORDED, "Where's the quietest place to study right now?"
    )
    assert set(got) == {
        "Collaborative pod / group study room",
        "Study room",
        "Study room / seminar room",
    }
    assert (
        _match_enum_by_word("Open room", RECORDED, "a quiet room") == []
    )  # a generic word matches nothing
    assert _match_enum_by_word("Library", RECORDED, "quiet library spot") == []  # not recorded


# ── chat shorthand (BUG-1542) and the "muggy" lay term (BUG-1543) ───────────────────────────


@pytest.mark.parametrize(
    "typed, plain",
    [
        ("temp in rm 5.01 now", "temperature in room 5.01 now"),
        ("co2 lvl room 2.01??", "co2 level room 2.01??"),
        ("whats the humidty on floor 3 today", "whats the humidity on floor 3 today"),
        ("how many ppl on flr 4 rn", "how many people on floor 4 right now"),
    ],
)
def test_chat_shorthand_is_expanded(typed, plain):
    from orchestrator.workflow._orchestrator import normalise_query_text

    assert normalise_query_text(typed) == plain


@pytest.mark.parametrize(
    "text", ["Is the temporary exhibition open?", "The RM tool is broken", "turn the rn on"]
)
def test_words_that_only_look_like_shorthand_are_left_alone(text):
    from orchestrator.workflow._orchestrator import normalise_query_text

    assert normalise_query_text(text) == text


def test_muggy_is_a_humidity_word_not_a_co2_word():
    import csv
    from pathlib import Path

    path = Path(__file__).resolve().parents[1] / "ontology" / "mining" / "concept_terms_raw.csv"
    rows = {
        r["concept_id"]: r["lay_terms"].split("|")
        for r in csv.DictReader(path.open(encoding="utf-8"))
    }
    assert "muggy" in rows["too_humid"]
    assert "muggy" not in rows["stuffiness"]


# ── the register's counted answer ────────────────────────────────────────────────────────────


def test_a_counted_register_answer_is_never_reopened():
    from orchestrator.services.absence_second_chance import skip_reason

    answer = (
        "**None of the 28 records in the Workspace profile register match** (on the ground floor)."
    )
    # "metadata" is a reopenable lane, so it is the counted-answer rule that declines here
    why = skip_reason({}, "metadata", "Where can I study on the ground floor?", answer)
    assert why == "the register's own counted answer"
    # and an ordinary miss in the same lane is still reopened
    assert (
        skip_reason({}, "metadata", "Where is the bike store?", "I could not find a bike store.")
        is None
    )


# ── round 2 (2026-10-10) ─────────────────────────────────────────────────────────────────────


@pytest.mark.parametrize(
    "question, quantity",
    [
        ("Was yesterday warmer than the day before on floor 4?", "temperature"),
        ("Which floor was coldest yesterday?", "temperature"),
        ("Is floor 5 noisier than floor 3?", "sound"),
        ("Was it brighter on floor 2 today?", "illuminance"),
    ],
)
def test_comparative_words_name_their_quantity(question, quantity):
    from orchestrator.services.aggregate_lane import question_measurands

    assert quantity in question_measurands(question)
    assert question_measurands("Is the hot water working?") == set()


def test_the_day_before_is_a_one_day_shift():
    from orchestrator.services.comparison_windows import resolve_pair

    pair = resolve_pair(
        "Was yesterday warmer than the day before on floor 4?",
        None,
        None,
        "Europe/London",
        now=datetime(2026, 10, 10, 11, 0),
    )
    assert pair is not None and pair.shifted
    assert (pair.current.start, pair.baseline.start) == (
        "2026-10-08 23:00:00",
        "2026-10-07 23:00:00",
    )


@pytest.mark.parametrize(
    "after, is_count",
    [
        (" humidity readings from room", True),
        (" noise level readings on floor 5", True),
        (" degrees in room 2.01", False),
        (" % at 03:37", False),
    ],
)
def test_a_count_with_a_quantity_word_before_its_noun_is_not_a_reading(after, is_count):
    from orchestrator.services.plausibility import _COUNT_NOUN_RE

    assert bool(_COUNT_NOUN_RE.match(after)) is is_count


def test_when_a_record_expires_is_its_end_date_not_its_state():
    from datetime import date

    from orchestrator.services.register_projection import resolve

    rows = [
        {
            "recordId": "W-1",
            "label": "lift warranty",
            "coveredScope": "Passenger lift",
            "effectiveFrom": "2021-05-01",
            "effectiveTo": "2026-05-01",
            "recordStatus": "expired",
        },
        {
            "recordId": "W-2",
            "label": "chiller warranty",
            "coveredScope": "Chiller",
            "effectiveFrom": "2022-06-01",
            "effectiveTo": "2027-06-01",
            "recordStatus": "active",
        },
    ]
    res = resolve(rows, "When does the lift warranty expire?", "Warranty", today=date(2026, 10, 10))
    assert res.fields.get("ends") == ["effectiveTo"]
    assert res.status_values == []
    res = resolve(rows, "Which warranties have expired?", "Warranty", today=date(2026, 10, 10))
    assert res.status_values == ["expired"]
