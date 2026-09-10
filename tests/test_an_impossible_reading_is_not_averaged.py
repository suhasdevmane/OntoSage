# -*- coding: utf-8 -*-
"""A number outside its quantity's possible range is not a reading (BUG-439, V10 W1-3).

WHAT WENT WRONG
---------------
    "Floor 1's average CO2 (157 ppm) is higher than Floor 3's (111 ppm). Both averages are
     well below the 800 ppm guideline for healthy indoor air, so overall air quality is
     compliant. Actionable recommendation: install or verify adequate ventilation..."

Outdoor air is about 420 ppm. Eighteen lanes could have noticed and none did, because the
only plausibility bands in the system were a Python dict inside the deliberation scorer,
used by the ranking path alone.

WHAT THE GUARD MUST AND MUST NOT DO
-----------------------------------
1. POSSIBILITY, NOT COMFORT. 5,000 ppm of CO2 is an evacuation and it is still a reading.
   A guard tuned to comfort limits would suppress exactly the readings a building most
   needs to report, which is a worse failure than the one it prevents.

2. NO BAND IS NOT A FAIL. A sensor whose quantity the ontology has not declared keeps its
   readings. Absence of evidence is not evidence.

3. THE EXCLUSION IS NAMED. Silently dropping the bad rows leaves the remaining average
   looking authoritative -- which is precisely how the impossible figure reached a user
   with a capital-expenditure recommendation attached.

4. NOTHING LEFT IS NOT "NO DATA". When every reading is impossible, the honest statement is
   that the stream is not carrying this quantity, not that the building has no data.
"""

from __future__ import annotations

import pytest

pytestmark = pytest.mark.unit

from orchestrator.services.physical_bands import (  # noqa: E402
    Band,
    Implausible,
    PhysicalBands,
    caveat,
)

_CO2 = Band(kind="CarbonDioxide", low=350.0, high=40000.0, unit="ppm")


def _exec(rows):
    """A fake SPARQL executor returning band bindings."""

    async def run(_query):
        return {
            "results": {
                "bindings": [
                    {
                        "uuid": {"value": u},
                        "kind": {"value": "http://ontosage.org/capabilities#" + k},
                        "lo": {"value": str(lo)},
                        "hi": {"value": str(hi)},
                        "unit": {"value": unit},
                    }
                    for (u, k, lo, hi, unit) in rows
                ]
            }
        }

    return run


_BANDS = [
    ("u-co2", "CarbonDioxide", 350, 40000, "ppm"),
    ("u-temp", "AirTemperature", -30, 70, "degC"),
]


@pytest.mark.asyncio
async def test_the_reading_that_started_this_is_rejected():
    pb = PhysicalBands(_exec(_BANDS))
    keep, bad = await pb.check([("u-co2", 157.0), ("u-co2", 111.0)])
    assert keep == []
    assert [round(b.value) for b in bad] == [157, 111]
    assert bad[0].band.kind == "CarbonDioxide"


@pytest.mark.asyncio
async def test_a_dangerous_reading_survives_because_the_band_is_possibility_not_comfort():
    """The load-bearing distinction.

    ASHRAE's comfort band tops out at 1,500 ppm. A guard built on that would delete the
    2,400 ppm reading that means a room needs ventilating NOW -- turning a safety signal
    into silence. The physical band is 40,000 (the NIOSH IDLH), so it passes.
    """
    pb = PhysicalBands(_exec(_BANDS))
    keep, bad = await pb.check([("u-co2", 2400.0), ("u-co2", 4900.0)])
    assert bad == []
    assert [v for _u, v in keep] == [2400.0, 4900.0]


@pytest.mark.asyncio
async def test_a_sensor_with_no_declared_band_keeps_its_readings():
    """Absence of a band is not evidence of implausibility."""
    pb = PhysicalBands(_exec(_BANDS))
    keep, bad = await pb.check([("u-unknown", 1e9)])
    assert bad == []
    assert keep == [("u-unknown", 1e9)]


@pytest.mark.asyncio
async def test_good_and_bad_readings_are_both_returned():
    """The caller must be able to say what it excluded, so it gets both halves."""
    pb = PhysicalBands(_exec(_BANDS))
    keep, bad = await pb.check([("u-co2", 800.0), ("u-co2", 12.0), ("u-temp", 21.5)])
    assert sorted(v for _u, v in keep) == [21.5, 800.0]
    assert [b.value for b in bad] == [12.0]


@pytest.mark.asyncio
async def test_a_load_failure_excludes_nothing_rather_than_everything():
    """A guard that fails closed on infrastructure would delete every reading."""

    async def boom(_q):
        raise RuntimeError("graphdb unreachable")

    pb = PhysicalBands(boom)
    keep, bad = await pb.check([("u-co2", 157.0)])
    assert bad == []
    assert keep == [("u-co2", 157.0)]


def test_the_caveat_names_the_sensor_the_value_and_the_band():
    note = caveat([Implausible(uuid="abcdef1234", value=157.0, band=_CO2, label="CO2 5.01")])
    assert "CO2 5.01" in note
    assert "157" in note
    assert "350" in note and "40000" in note
    assert "excluded" in note.lower()


def test_no_caveat_when_nothing_was_excluded():
    assert caveat([]) == ""


def test_the_caveat_does_not_blame_the_building():
    """An index in a ppm column is a data-plumbing fault, not a facilities fault.

    The answer that started this recommended an HVAC upgrade. A caveat that reads like an
    alarm invites the same response one level down.
    """
    note = caveat([Implausible(uuid="u", value=157.0, band=_CO2)])
    assert "different quantity" in note


@pytest.mark.asyncio
async def test_a_band_holds_its_own_endpoints():
    """Inclusive, because a reading exactly at the bound is possible by definition."""
    assert _CO2.holds(350.0) and _CO2.holds(40000.0)
    assert not _CO2.holds(349.9)


def test_the_sql_lane_runs_the_guard():
    """Step 3 of the checklist this codebase keeps forgetting: built, correct, no invoker.

    A guard nothing calls is indistinguishable from no guard, and the tests above would
    pass either way.
    """
    import inspect

    from orchestrator.workflow import _orchestrator

    src = inspect.getsource(_orchestrator)
    assert "async def exclude_impossible_readings" in src
    assert "result = await exclude_impossible_readings(" in src, (
        "the plausibility gate is defined and never called from the SQL lane"
    )


# ── the cap that made the guard under-report (live probe, 2026-09-07) ────────


def test_the_band_query_carries_its_own_limit():
    """`SPARQLAgent._execute_query` appends `LIMIT 1000` to any SELECT without one.

    That cap is correct for a model-generated query and wrong for an EXHAUSTIVE map. It
    truncated the band map to 1,000 of this building's 2,841 instrumented uuids, so the
    gate had nothing to say about the other 65%.

    The symptom was a right-looking answer: the floor comparison reported 797 ppm against
    775 ppm -- both plausible, both a vast improvement on the 157/111 that started this --
    while a sensor reading 190 ppm was folded into the average because its uuid fell
    outside the truncated map. A cap on an exhaustive query does not fail; it under-reports,
    and under-reporting from a guard reads exactly like having nothing to report.
    """
    from orchestrator.services.physical_bands import _BANDS_BY_UUID

    assert "LIMIT" in _BANDS_BY_UUID.upper(), (
        "the band query carries no LIMIT, so the caller's 1,000-row safety cap applies "
        "and the map is silently truncated"
    )
    limit = int(_BANDS_BY_UUID.upper().split("LIMIT")[1].split()[0])
    assert limit >= 50000, f"the band map is capped at {limit}; that is a truncation"


@pytest.mark.asyncio
async def test_a_suspiciously_round_band_count_is_announced(caplog):
    """The only thing that revealed the truncation was the number 1,000 in a log line."""
    import logging

    rows = [(f"u-{i}", "CarbonDioxide", 350, 40000, "ppm") for i in range(1000)]
    pb = PhysicalBands(_exec(rows))
    with caplog.at_level(logging.INFO):
        await pb.check([("u-0", 800.0)])
    assert any("SUSPICIOUS" in r.message for r in caplog.records), (
        "an exact multiple of 1,000 is reported as a plain count, so the next truncation "
        "will look like a building with fewer sensors"
    )
