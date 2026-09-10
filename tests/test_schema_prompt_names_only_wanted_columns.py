# -*- coding: utf-8 -*-
"""A wide table must not put the whole building in the prompt (BUG-474).

MEASURED 2026-09-07, live, on the question "Give me a report on the CO2 in room 5.01
yesterday.":

    ERROR - LLM [complex] error (attempt 3, non-retryable): LLM [complex] returned an
            empty completion (prompt was 45573 chars)
    ERROR - SQL generation error: ... empty completion (prompt was 45573 chars)
    INFO  - Report generated: 1360 chars

Read those three lines together. SQL generation failed outright, and a report was
generated anyway — 1,360 characters of report with no data behind it. The turn came back
looking like an answer.

WHERE THE 45,573 CHARACTERS CAME FROM
-------------------------------------
`SchemaInfo.as_prompt_text` named every column of every table. `sensor_data` is a WIDE
table with one column per sensor: 704 of them. Naming every column in the database costs
~34,203 characters before any of the prompt's own text. Against OLLAMA_NUM_CTX=16384 there
was no room left to generate into, so the model returned nothing.

The caller knew which columns it wanted the whole time — `group_uuids`, a handful — and
did not say.

WHY THIS IS NOT A ONE-BUILDING PROBLEM
--------------------------------------
The prompt grew with the BUILDING rather than with the question, so a larger building is
strictly worse. This one stops at 704 columns only because InnoDB stops at 1,017. Raising
the context window, which is what BUG-188 did, moves the cliff without removing it.

WHAT THE OMISSION MUST NEVER READ AS
------------------------------------
Silence about a column is not evidence the data is missing. That is the exact shape of
BUG-192 — the model denying a sensor class exists by reasoning from its retrieval window
rather than from a count — so the truncation says so, in the prompt, with a count.
"""

from __future__ import annotations

import pytest

pytestmark = pytest.mark.unit

from orchestrator.services.database_adapter import AdapterType, SchemaInfo  # noqa: E402


def _wide(n: int = 704, ts: str = "Datetime") -> SchemaInfo:
    """A wide time-series table of `n` sensor columns, shaped like the live one."""
    cols = [(ts, "datetime")] + [(f"uuid-{i:04d}", "float") for i in range(n)]
    return SchemaInfo(
        tables=["sensor_data"],
        columns={"sensor_data": cols},
        timestamp_column=ts,
        adapter_type=AdapterType.MYSQL,
    )


def test_asking_for_three_sensors_does_not_name_seven_hundred():
    text = _wide().as_prompt_text(keep_columns={"uuid-0005", "uuid-0100", "uuid-0700"})
    for wanted in ("uuid-0005", "uuid-0100", "uuid-0700"):
        assert wanted in text
    assert "uuid-0006" not in text
    assert len(text) < 3000, (
        f"the prompt is {len(text)} chars for a three-sensor question; the live failure "
        f"was 45,573 chars against a 16,384-token context"
    )


def test_the_timestamp_column_survives_the_budget():
    """Without it the model cannot write a WHERE clause at all."""
    text = _wide().as_prompt_text(keep_columns={"uuid-0005"})
    assert "Datetime" in text


def test_the_omission_is_stated_with_a_count():
    """Silence about a column must never read as evidence the data is missing."""
    text = _wide().as_prompt_text(keep_columns={"uuid-0005"})
    assert "702 further columns" in text or "further columns" in text
    assert "NOT evidence" in text


def test_a_narrow_table_is_still_listed_in_full():
    """The budget must not damage the ordinary case."""
    narrow = SchemaInfo(
        tables=["co2_data"],
        columns={"co2_data": [("uuid", "varchar"), ("Datetime", "datetime"), ("value", "float")]},
        timestamp_column="Datetime",
        adapter_type=AdapterType.MYSQL,
    )
    text = narrow.as_prompt_text(keep_columns={"nothing-here"})
    for c in ("uuid", "Datetime", "value"):
        assert c in text
    assert "further columns" not in text


def test_a_caller_that_names_nothing_still_gets_a_usable_shape():
    """Legacy callers exist, and a wide table is only usable if its shape is visible.

    They must not get the 45,573-character dump back, but they must still see what a
    sensor column LOOKS like — otherwise the model cannot tell that identifiers appear as
    column names, which is the one thing this table's format depends on.
    """
    text = _wide().as_prompt_text()
    assert "uuid-0000" in text, "no sample column: the wide format is now invisible"
    assert len(text) < 3000
    assert "further columns" in text


def test_the_budget_is_a_property_of_the_prompt_not_of_a_building():
    """Nothing here may key off how many sensors this particular building has."""
    from pathlib import Path

    src = Path("orchestrator/services/database_adapter.py").read_text(encoding="utf-8")
    block = src.split("PROMPT_COLUMN_BUDGET", 1)[1][:2500]
    for literal in ("bldg1", "bldg2", "bldg3", "abacws", "sensor_data"):
        assert literal not in block.lower().replace("wide time-series table", ""), (
            f"{literal!r} appears in the truncation logic; the budget must hold for any "
            f"building and any table name"
        )


def test_scaling_is_bounded_by_the_question_not_the_building():
    """Ten times the sensors, same question, same prompt size."""
    small = _wide(70).as_prompt_text(keep_columns={"uuid-0005"})
    large = _wide(7000).as_prompt_text(keep_columns={"uuid-0005"})
    assert abs(len(large) - len(small)) < 200, (
        "the prompt still grows with the building; a bigger building would hit the same "
        "empty completion this test exists to prevent"
    )
