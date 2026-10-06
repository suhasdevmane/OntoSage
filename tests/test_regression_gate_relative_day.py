# -*- coding: utf-8 -*-
"""The regression gate judges a relative-day question against the day it NAMES, not the capture day.

`scripts/regression_answerability.py` stored "Which floor used the most energy yesterday?" as
answered, on the day that pack was captured. Two days later "yesterday" names a day with no energy
readings, the honest answer is a decline, and the gate reported REGRESSED for a correct answer.

Every clock and every data check here is injected. Nothing reads the real date.
"""

from __future__ import annotations

from datetime import date

import pytest

from scripts.regression_answerability import (
    REPO,
    expected_for_relative_day,
    load_pack,
    mysql_has_data_factory,
)

pytestmark = pytest.mark.unit

TODAY = date(2026, 10, 6)
YESTERDAY = date(2026, 10, 5)


def _case(question: str, stored: str = "answered") -> dict:
    return {"question": question, "expected_kind": stored}


def _data_on(*days: date):
    """A `has_data_for(day, table)` that reports readings only on the given days."""
    seen = []

    def has_data_for(day: date, table: str) -> bool:
        seen.append((day, table))
        return day in days

    has_data_for.seen = seen
    return has_data_for


def test_yesterday_with_no_energy_readings_expects_declined():
    case = _case("Which floor used the most energy yesterday?")
    got = expected_for_relative_day(case, TODAY, _data_on(date(2026, 10, 4)))
    assert got["expected_kind"] == "declined"
    assert got["resolved_date"] == "2026-10-05"
    assert "energy_data" in got["basis"]


def test_yesterday_with_energy_readings_expects_answered():
    case = _case("Which floor used the most energy yesterday?", stored="declined")
    got = expected_for_relative_day(case, TODAY, _data_on(YESTERDAY))
    assert got["expected_kind"] == "answered"
    assert got["resolved_date"] == "2026-10-05"


def test_the_data_check_asks_the_day_it_resolved_and_the_matching_table():
    has = _data_on()
    expected_for_relative_day(
        _case("Show me a chart of electricity use by floor yesterday."), TODAY, has
    )
    assert has.seen == [(YESTERDAY, "energy_data")]


def test_occupancy_question_asks_the_occupancy_table():
    has = _data_on(YESTERDAY)
    got = expected_for_relative_day(
        _case("Chart the hourly occupancy profile of the building yesterday."), TODAY, has
    )
    assert has.seen == [(YESTERDAY, "occupancy_data")]
    assert got["expected_kind"] == "answered"


def test_non_relative_case_keeps_its_stored_label_and_no_date():
    has = _data_on()
    got = expected_for_relative_day(
        _case("What is the maintenance schedule?", "answered"), TODAY, has
    )
    assert got == {"resolved_date": None, "expected_kind": "answered", "basis": "stored label"}
    assert has.seen == []


def test_refusal_is_not_data_dependent():
    case = _case("Where was John Smith in the building yesterday?", stored="refused")
    got = expected_for_relative_day(case, TODAY, _data_on(YESTERDAY))
    assert got["expected_kind"] == "refused"
    assert got["resolved_date"] == "2026-10-05"


def test_relative_word_with_no_topic_table_keeps_label_but_reports_the_date():
    got = expected_for_relative_day(_case("Is Room 2.15 free this morning?"), TODAY, _data_on())
    assert got["resolved_date"] == "2026-10-06"
    assert got["expected_kind"] == "answered"
    assert "no data table" in got["basis"]


def test_failed_data_check_falls_back_to_the_stored_label():
    def broken(day, table):
        raise ConnectionError("mysql down")

    got = expected_for_relative_day(
        _case("Which floor used the most energy yesterday?"), TODAY, broken
    )
    assert got["expected_kind"] == "answered"
    assert "data check failed (ConnectionError)" in got["basis"]


def test_day_before_yesterday_resolves_two_days_back():
    got = expected_for_relative_day(
        _case("How much electricity was used the day before yesterday?"), TODAY, _data_on()
    )
    assert got["resolved_date"] == "2026-10-04"
    assert got["expected_kind"] == "declined"


def test_this_week_and_last_week_span_both_weeks():
    # 2026-10-06 is a Tuesday: last week is Mon 28 Sep to Sun 4 Oct, this week Mon 5 Oct to today.
    got = expected_for_relative_day(
        _case("Compare this week's electricity use with last week's, by floor."), TODAY, _data_on()
    )
    assert got["resolved_date"] == "2026-09-28..2026-10-06"
    assert got["expected_kind"] == "declined"


def test_today_resolves_to_the_injected_clock_not_the_real_one():
    got = expected_for_relative_day(_case("Plot the humidity on floor 4 today."), TODAY, _data_on())
    assert got["resolved_date"] == "2026-10-06"


def test_the_shipped_pack_cases_11_and_20_follow_the_calendar():
    rows = {r["n"]: r for r in load_pack(REPO / "docs" / "supervisor_evidence_pack")}
    for n in (11, 20):
        got = expected_for_relative_day(
            rows[n], TODAY, _data_on(date(2026, 10, 4), date(2026, 10, 6))
        )
        assert got["resolved_date"] == "2026-10-05"
        assert got["expected_kind"] == "declined", n
        assert rows[n]["expected_kind"] == "answered"  # the stored label is untouched


def test_factory_refuses_a_table_outside_the_gate_set():
    has = mysql_has_data_factory(None)
    with pytest.raises(ValueError):
        has(YESTERDAY, "sensor_data; DROP TABLE x")
