# -*- coding: utf-8 -*-
"""A report with no rows must not explain why (BUG-475).

MEASURED 2026-09-07, live. Asked "Give me a report on the CO2 in room 5.01 yesterday.",
the system produced SQL of `WHERE uuid = '5.01'` — the ROOM NUMBER used as a sensor id —
which matched nothing. `_narrate` was then handed `data_points: 0` and a prompt asking for
"Recommendations (2-3 actionable items)", and wrote:

    ### 2. Key Findings
    - No CO₂ sensor was active or present in Room 5.01 during the reporting period.
    - The monitoring system recorded zero data points for the specified room.

    ### 3. Anomalies / Concerns
    - **Data Void:** ... a critical monitoring gap that could compromise indoor air
      quality oversight.
    - **Potential System Failure:** The absence may stem from sensor malfunction,
      misconfiguration, or installation oversight.

    ### 4. Recommendations
    1. **Verify Sensor Installation** ...
    3. **Implement Redundancy:** Deploy a secondary CO₂ monitoring device in the room ...

`co2_data` held 889,235 rows, 77,088 of them for that day. The system converted its own
query error into a confident claim about the building's hardware and recommended buying
more of it.

WHAT MAKES THIS WORSE THAN AN ORDINARY WRONG ANSWER
---------------------------------------------------
It reads as HONESTY. "No data was recorded" is the shape of the honest no-data answer this
project is built around, so it passes every check aimed at fabrication — the referent gate
(the room exists), the leak grader (no figures), a reader's eye. The verifier had already
scored the turn `grounded=False, confidence=0.20, source=none, sql_rows=0` and the report
went out regardless.

THE RULE
--------
An empty result is STATED and NOT EXPLAINED. Whether the rows are missing because nothing
happened, because no such sensor exists, or because the query was wrong is not knowable
from a row count — and only the graph can answer the second. Narrating it is guessing with
a house style.
"""

from __future__ import annotations

import pytest

pytestmark = pytest.mark.unit

from orchestrator.agents.report_agent import ReportAgent  # noqa: E402

SECTIONS = {
    "overview": {
        "building": "Some Building",
        "report_type": "summary",
        "generated_at": "2026-09-07T17:47:18+01:00",
        "sensor_count": 0,
        "data_points": 0,
    },
    "readings_summary": {},
    "anomalies": [],
    "highlights": [],
}

QUERY = "Give me a report on the CO2 in room 5.01 yesterday."


def _text() -> str:
    return ReportAgent._no_data_narrative(QUERY, SECTIONS)


def test_it_says_no_data_was_retrieved():
    assert "no data was retrieved" in _text().lower()


@pytest.mark.parametrize(
    "claim",
    [
        # Every one of these appeared in the live answer.
        "monitoring gap",
        "system failure",
        "sensor malfunction",
        "not present",
        "was active or present",
        "verify sensor installation",
        "deploy a secondary",
        "install",
        "data void",
    ],
)
def test_it_never_diagnoses_the_building(claim):
    """A row count cannot establish any of these, and the live answer asserted all of them."""
    assert claim not in _text().lower(), (
        f"the empty-report text claims {claim!r}; an empty result says nothing about the "
        f"building's instrumentation"
    )


def test_it_says_explicitly_that_this_is_not_about_the_building():
    """Saying nothing wrong is not enough — a bare 'no data' still READS as absence."""
    low = _text().lower()
    assert "not about the building" in low or "not a statement about the building" in low
    assert "does not mean the sensor is missing" in low


def test_it_offers_a_way_forward_without_asserting_anything():
    assert "what sensors are in" in _text().lower()


def test_it_costs_no_llm_call():
    """There is nothing to narrate, and the narration is where the fabrication came from."""
    import inspect

    src = inspect.getsource(ReportAgent._no_data_narrative)
    assert "llm_manager" not in src and "await" not in src


def test_the_narrator_is_not_reached_at_all_when_nothing_was_retrieved():
    """The guard must sit BEFORE `_narrate`, not inside its prompt.

    Telling a model not to speculate is a request; not calling it is a guarantee.
    """
    import inspect

    src = inspect.getsource(ReportAgent.generate)
    assert "_no_data_narrative" in src
    guard = src.index("_no_data_narrative")
    narrate = src.index("self._narrate(")
    assert guard < narrate, "the narrator is still reached before the empty-result guard"


def test_a_report_with_rows_still_narrates():
    """The guard must not silence the ordinary case."""
    import inspect

    src = inspect.getsource(ReportAgent.generate)
    assert "else:" in src and "await self._narrate(" in src


def test_nothing_here_names_a_building():
    import inspect

    src = inspect.getsource(ReportAgent._no_data_narrative)
    for literal in ("bldg1", "bldg2", "abacws", "5.01", "co2"):
        assert literal not in src.lower().split('"""')[-1], (
            f"{literal!r} appears in the empty-report text; it must read the same for any "
            f"building, space and measurand"
        )


# ── the other half: the rows were there and the report could not see them ───
#
# Fixing the fabrication made the report HONEST about having no data. It was still the
# wrong answer, because 1,000 rows had been fetched for it. Two shape mismatches stood
# between the fetch and the report, and both callers had the same one (BUG-477):
#
#     planner: sensor_data=ctx.get("sql_result"),  metadata=ctx.get("sparql_result")
#     workflow: sensor_data=sql_result,            metadata=sparql_result
#
# `sql_result` carries its rows at ["results"]["data"]; this module read ["data"].
# `sparql_result` carries its rows at ["standardized"]["results"] and has no "sensors"
# key at all. So `data_points` and `sensor_count` were 0 on every report ever generated.


def test_rows_are_found_in_the_shape_the_sql_lane_actually_returns():
    from orchestrator.agents.report_agent import _records_from

    sql_result = {
        "success": True,
        "query": "Multiple Queries (Storage Aware)",
        "results": {"data": [{"timestamp": "t", "value": 1.0}] * 1000},
        "formatted_response": "...",
    }
    assert (
        len(_records_from(sql_result)) == 1000
    ), "the rows the planner fetched are still invisible to the report"


def test_the_unwrapped_shape_still_works():
    """Narrowing to one accepted shape is how a working caller breaks silently."""
    from orchestrator.agents.report_agent import _records_from

    assert _records_from({"data": [{"value": 1}]}) == [{"value": 1}]
    assert _records_from([{"value": 1}]) == [{"value": 1}]


def test_nothing_at_all_is_still_nothing():
    from orchestrator.agents.report_agent import _records_from

    for empty in ({}, None, "text", {"results": {}}, {"results": {"data": []}}):
        assert _records_from(empty) == []


def test_sensors_are_found_in_the_shape_the_sparql_lane_actually_returns():
    from orchestrator.agents.report_agent import _sensors_from

    sparql_result = {
        "success": True,
        "standardized": {"results": [{"uuid": "u1", "label": "CO2"}]},
        "results": {"results": {"bindings": []}},
    }
    assert len(_sensors_from(sparql_result)) == 1, "sensor_count is still 0 on every report"


def test_a_plain_metadata_dict_still_works():
    from orchestrator.agents.report_agent import _sensors_from

    assert _sensors_from({"sensors": [{"uuid": "u1"}]}) == [{"uuid": "u1"}]
    assert _sensors_from({}) == []
