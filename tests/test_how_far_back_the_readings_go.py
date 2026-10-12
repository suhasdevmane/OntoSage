""""How long has CO2 been recorded?" -- the first and last reading and the months with none.

2026-10-11 battery (researcher): the question had no lane. The answer is derived from the stores
on every ask, and the gaps are stated, because a store holding a snapshot, months of nothing and
then a live record must not be described as continuous. Data here is synthetic.
"""

from dataclasses import dataclass, field
from datetime import datetime
from typing import List

import pytest

from orchestrator.services.adapters.mysql_adapter import MySQLAdapter
from orchestrator.services.adapters.mysql_narrow_adapter import MySQLNarrowAdapter
from orchestrator.services.observability import is_observability_question
from orchestrator.services.record_span import (
    asked_modalities,
    format_span,
    is_record_span_question,
    month_gaps,
)

pytestmark = pytest.mark.unit


@pytest.mark.parametrize(
    "question",
    [
        "how long has CO2 been recorded?",
        "How long have you been measuring temperature? How long has it been monitored?",
        "Since when has humidity been logged?",
        "How far back does the energy data go?",
        "What is the earliest reading of noise?",
        "When did occupancy monitoring start?",
        "How long has the building been recording energy?",
    ],
)
def test_history_questions_are_recognised_and_reach_the_lane(question):
    assert is_record_span_question(question)
    assert is_observability_question(question)


@pytest.mark.parametrize(
    "question",
    [
        "What is the CO2 in room 2.01?",
        "How long has the boiler been running today?",
        "How long will the meeting last?",
        "What was the first meeting this morning?",
    ],
)
def test_other_questions_are_not(question):
    assert not is_record_span_question(question)


@dataclass
class _Spec:
    name: str
    brick_classes: List[str] = field(default_factory=list)


def test_the_quantity_is_found_by_name_or_everyday_word():
    specs = [_Spec("co2"), _Spec("temperature"), _Spec("illuminance")]
    assert [s.name for s in asked_modalities("how long has CO2 been recorded?", specs)] == ["co2"]
    assert [s.name for s in asked_modalities("since when is light logged?", specs)] == [
        "illuminance"
    ]
    assert asked_modalities("how far back does the data go?", specs) == []


def test_missing_months_are_runs_between_the_months_held():
    held = ["2025-01", "2025-02", "2025-03", "2026-03", "2026-04", "2026-06"]
    assert month_gaps(held) == [("2025-04", "2026-02"), ("2026-05", "2026-05")]
    assert month_gaps(["2026-07", "2026-08"]) == []


def test_the_answer_states_the_start_the_latest_and_the_gap():
    out = format_span(
        "CO2",
        datetime(2025, 1, 1, 0, 0, 5),
        datetime(2026, 10, 11, 9, 51),
        ["2025-01", "2025-02", "2025-03", "2026-03", "2026-10"],
        points=12,
        stores=2,
        not_probed=[],
    )
    assert "1 January 2025" in out and "11 October 2026" in out
    assert "not continuous" in out and "April 2025 to February 2026" in out
    assert "12 CO2 points across 2 stores" in out


def test_no_readings_is_said_and_a_store_not_asked_is_named():
    out = format_span(
        "radon", None, None, [], 0, 1, ["x_data (3 points: this store cannot be asked)"]
    )
    assert "no stored **radon** readings" in out and "could ask" in out


class _Result:
    def __init__(self, data):
        self.success, self.data = True, data


class _FakeNarrow(MySQLNarrowAdapter):
    """Rows exist in January, March and April; nothing in February."""

    def __init__(self):
        super().__init__(table="co2_data")
        self.sql: List[str] = []

    async def execute_query(self, sql, *a, **k):
        self.sql.append(sql)
        if "ORDER BY `datetime` ASC" in sql:
            return _Result([{"t": datetime(2026, 1, 3)}])
        if "ORDER BY `datetime` DESC" in sql:
            return _Result([{"t": datetime(2026, 4, 9)}])
        held = ("2026-01-01", "2026-03-01", "2026-04-01")
        return _Result(
            [{"t": datetime(2026, 1, 1)}] if any(f">= '{m}'" in sql for m in held) else []
        )


@pytest.mark.asyncio
async def test_the_narrow_probe_reports_first_last_and_months_held():
    ad = _FakeNarrow()
    got = await ad.months_with_readings(["a1b2c3d4-0000-0000-0000-000000000001"])
    assert got["first"] == datetime(2026, 1, 3) and got["last"] == datetime(2026, 4, 9)
    assert got["months"] == ["2026-01", "2026-03", "2026-04"]
    assert all("`uuid` IN (" in s for s in ad.sql)


@pytest.mark.asyncio
async def test_a_wide_store_selects_rows_where_a_sensor_column_is_not_null():
    ad = MySQLAdapter.__new__(MySQLAdapter)
    ad._LAST_SEEN_CHUNK = 2

    async def cols():
        return {"u-aaaaaaaa1", "u-aaaaaaaa2", "u-aaaaaaaa3", "Datetime"}

    ad.get_columns = cols
    conds = await ad._span_conditions(["u-aaaaaaaa1", "u-aaaaaaaa2", "u-aaaaaaaa3", "u-notacolumn"])
    assert len(conds) == 2 and "`u-aaaaaaaa1` IS NOT NULL OR `u-aaaaaaaa2` IS NOT NULL" in conds[0]
    assert "notacolumn" not in " ".join(conds)
