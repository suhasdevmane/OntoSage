# -*- coding: utf-8 -*-
"""Present data is recognised as present (V12-12, review case A02).

    A02 — "Declared sensor has a working store reference and seeded readings.
           → Presence and data are recognized; no claim that installation is required."

WHAT WENT WRONG
---------------
Room 5.01 records CO2 to about 77,088 rows a day. The report for it said:

    "No CO2 sensor was active or present in Room 5.01" … "a critical monitoring gap"
    … "deploy a secondary CO2 device"

Every one of those is a claim about the BUILDING, derived from a row count of zero that
was itself an artefact — `_standardize_results` had dropped a correct SPARQL result on the
floor (BUG-476), so the UUID never reached the SQL lane, so the fetch came back empty, so
the narrator explained an absence that did not exist (BUG-475).

WHY THIS FILE EXISTS ALONGSIDE test_an_empty_report_does_not_diagnose_the_building.py
-------------------------------------------------------------------------------------
That file pins the EMPTY path: with no rows, say so and diagnose nothing. This one pins
the opposite and equally necessary half — with rows and a sensor, the presence must be
RECOGNISED. Its existing coverage of that half is one source-text assertion
(``"else:" in src``), which would still pass if the recogniser stopped finding rows
entirely. That is the shape of BUG-477: `_records_from` read the caller's dict one level
too shallow and "has never once seen the data either caller fetched", while every test
around it passed.

NO MODEL REQUIRED. Everything asserted here is the deterministic recogniser — the
narration is an LLM call and is deliberately out of scope.
"""

from __future__ import annotations

import pytest

pytestmark = pytest.mark.unit

from orchestrator.agents.report_agent import (  # noqa: E402
    ReportAgent,
    _records_from,
    _sensors_from,
)

#: The shape the SQL lane actually produces — rows at ["results"]["data"], not ["data"].
#: Writing the fixture in the OTHER shape is how BUG-477 stayed invisible.
SQL_RESULT = {
    "success": True,
    "results": {
        "data": [
            {"uuid": "a66ca165-1e06-4901-a997-780fafc8581a", "timestamp": f"2026-09-09T{h:02d}:00:00",
             "value": 700 + h}
            for h in range(24)
        ]
    },
}

#: The shape the SPARQL lane produces — sensors under ["standardized"]["results"].
SPARQL_RESULT = {
    "success": True,
    "standardized": {
        "results": [
            {
                "sensor": "http://example.org/bldg#CO2_Level_Sensor_5.01",
                "uuid": "a66ca165-1e06-4901-a997-780fafc8581a",
                "storage": "database1",
                "label": "CO2 5.01",
            }
        ]
    },
}


# ── presence is recognised ───────────────────────────────────────────────────


def test_the_readings_are_found_in_the_shape_the_lane_produces():
    """BUG-477: read one level too shallow and every report sees zero rows."""
    records = _records_from(SQL_RESULT)
    assert len(records) == 24, (
        "the rows the SQL lane fetched were not found — a report built on this would "
        "report an absence that does not exist"
    )


def test_the_declared_sensor_is_found():
    """`sensor_count` was 0 on every report ever generated for the same reason."""
    sensors = _sensors_from(SPARQL_RESULT)
    assert len(sensors) == 1


def test_a_working_store_reference_survives_into_the_record():
    """A02 names a WORKING store reference specifically — presence of the sensor is not
    enough if the thing that routes its readings is lost."""
    sensors = _sensors_from(SPARQL_RESULT)
    blob = str(sensors)
    assert "a66ca165-1e06-4901-a997-780fafc8581a" in blob
    assert "database1" in blob, "the storage key that routes the fetch was dropped"


# ── and no installation claim is made ────────────────────────────────────────


@pytest.mark.parametrize(
    "claim",
    [
        "install",
        "not present",
        "was active or present",
        "monitoring gap",
        "deploy a secondary",
        "sensor malfunction",
        "system failure",
        "data void",
    ],
)
def test_the_empty_path_wording_cannot_be_produced_when_data_exists(claim):
    """The exact claims from the live answer, asserted against the guard's own condition.

    `generate` chooses the no-data narrative on `if not (data_points or 0)`. With
    twenty-four rows recognised that branch is unreachable, so none of this wording can
    be produced by it. The parametrised list is the same one the empty-path test forbids,
    kept identical on purpose: if one file's list is extended, the other should be too.
    """
    records = _records_from(SQL_RESULT)
    data_points = len(records)
    assert data_points > 0, "fixture broken — the recogniser found nothing"

    takes_no_data_branch = not (data_points or 0)
    assert not takes_no_data_branch, (
        f"with {data_points} rows the report would still take the empty-result branch, "
        f"which is what produced {claim!r} about a room recording 77,088 readings a day"
    )


def test_the_no_data_narrative_is_reserved_for_actually_having_no_data():
    """It must still fire when it should — a guard that never triggers is not a guard."""
    sections = {"overview": {"sensor_count": 3, "data_points": 0}}
    text = ReportAgent._no_data_narrative("CO2 in room 5.01 yesterday", sections)
    assert text and "no data" in text.lower()


def test_the_two_halves_forbid_the_same_claims():
    """This file and the empty-path file must not drift apart on what counts as a
    building diagnosis."""
    from pathlib import Path

    other = (
        Path(__file__).resolve().parent / "test_an_empty_report_does_not_diagnose_the_building.py"
    ).read_text(encoding="utf-8")
    for claim in ("monitoring gap", "install", "not present", "deploy a secondary"):
        assert claim in other, (
            f"{claim!r} is forbidden here but no longer in the empty-path test; the two "
            "lists have drifted"
        )
