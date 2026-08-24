# -*- coding: utf-8 -*-
"""Which sensor a room's modality resolves to when it has more than one (BUG-255).

Room 5.01 carries two CO2 populations: the real `CO2_Level_Sensor_5.01` (current) and
`Room5.01_sat_co2` (SATURATE, last row four days old). The auditor took whichever the graph
returned first and stopped, so the stale one won — and the diagnosis lane then reported
**"I have no co2 readings over the last 24 hours"** for a room the sensor_data lane answered
with live CO2 in the same minute. Two lanes, two sensors, opposite answers, each honest about
what it happened to hold.

The property that makes this safe to change is the one most easily lost:

**`None` and `set()` mean opposite things.** `None` is "freshness could not be measured" and
must restore the historical first-match behaviour exactly. `set()` is "nothing is fresh".
Collapsing them would mark every sensor in a building stale the moment the adapters were
unavailable — the degrade-to-a-legal-value failure this codebase keeps paying for.
"""

import pytest

from orchestrator.services.deliberation.coverage_audit import (
    STATUS_PRESENT,
    CoverageAuditor,
    ModalitySpec,
)

pytestmark = pytest.mark.unit

SPACE = "http://x#Room5.01"
STALE = "uuid-saturate-stale"
FRESH = "uuid-real-fresh"


def _spec():
    return ModalitySpec(name="co2", brick_classes=["CO2_Level_Sensor"])


def _points():
    """Stale first — the order the live graph actually returned, and the whole problem."""
    return [
        {
            "space": SPACE,
            "sensor": "http://x#Room5.01_sat_co2",
            "class_local": "CO2_Level_Sensor",
            "text": "room5.01 sat co2",
            "uuid": STALE,
            "stored_at": "co2_data",
        },
        {
            "space": SPACE,
            "sensor": "http://x#CO2_Level_Sensor_5.01",
            "class_local": "CO2_Level_Sensor",
            "text": "co2 level sensor 5.01",
            "uuid": FRESH,
            "stored_at": "database1",
        },
    ]


async def _audit(fresh):
    """Run the selection loop against fixed points, bypassing SPARQL entirely."""
    from orchestrator.services.deliberation.coverage_audit import SpaceCoverage

    auditor = CoverageAuditor(None, [_spec()], fresh_uuids=fresh)
    space = SpaceCoverage(space_iri=SPACE, label="Room 5.01", floor="5")

    async def _discover_spaces(_ns):
        return [space]

    async def _discover_points(_ns):
        return _points()

    auditor.discover_spaces = _discover_spaces
    auditor.discover_points = _discover_points
    spaces = await auditor.audit("http://x#")
    return spaces[0].modalities["co2"]


@pytest.mark.asyncio
async def test_the_fresh_sensor_wins_even_when_the_stale_one_comes_first():
    got = await _audit({FRESH})
    assert got["uuid"] == FRESH, (
        "the stale sensor was chosen again — the diagnosis lane will report 'no readings' for "
        "a room that is reporting"
    )
    assert got["status"] == STATUS_PRESENT
    assert got["fresh"] is True
    assert got["candidates"] == 2, "the room's second sensor was not even considered"


@pytest.mark.asyncio
async def test_no_freshness_signal_restores_the_exact_previous_behaviour():
    """`None` means the measurement could not run. It must NOT be read as 'nothing is fresh',
    which would change selection on every building whose adapters are unavailable."""
    got = await _audit(None)
    assert got["uuid"] == STALE, "first-match behaviour changed when freshness was unavailable"
    assert got["fresh"] is None, "an unmeasured sensor was recorded as a measured verdict"


@pytest.mark.asyncio
async def test_when_nothing_is_fresh_a_sensor_is_still_chosen_and_marked_stale():
    """A stale sensor is not the same as no sensor. Returning MISSING here would tell a user
    the room is uninstrumented when it is instrumented and silent — different facts, different
    remedies."""
    got = await _audit(set())
    assert got["status"] == STATUS_PRESENT
    assert got["uuid"] == STALE
    assert got["fresh"] is False, (
        "the answer cannot say its only sensor is stale, so 'no readings' will read as "
        "'no sensor'"
    )


@pytest.mark.asyncio
async def test_a_single_sensor_room_is_unaffected():
    """The overwhelmingly common case must not change shape."""
    from orchestrator.services.deliberation.coverage_audit import SpaceCoverage

    auditor = CoverageAuditor(None, [_spec()], fresh_uuids={FRESH})
    space = SpaceCoverage(space_iri=SPACE, label="Room 5.01", floor="5")

    async def _ds(_ns):
        return [space]

    async def _dp(_ns):
        return _points()[:1]

    auditor.discover_spaces, auditor.discover_points = _ds, _dp
    got = (await auditor.audit("http://x#")).pop().modalities["co2"]
    assert got["uuid"] == STALE and got["candidates"] == 1


@pytest.mark.asyncio
async def test_an_unbacked_sensor_never_beats_a_backed_one():
    """Contract #8 still governs: a sensor with no timeseries id cannot be read at all, so it
    can never be preferred over one that can — fresh or not."""
    from orchestrator.services.deliberation.coverage_audit import SpaceCoverage

    pts = [
        {
            "space": SPACE,
            "sensor": "http://x#Unbacked",
            "class_local": "CO2_Level_Sensor",
            "text": "unbacked",
            "uuid": "",
            "stored_at": "",
        }
    ] + _points()[:1]
    auditor = CoverageAuditor(None, [_spec()], fresh_uuids=set())
    space = SpaceCoverage(space_iri=SPACE, label="Room 5.01", floor="5")

    async def _ds(_ns):
        return [space]

    async def _dp(_ns):
        return pts

    auditor.discover_spaces, auditor.discover_points = _ds, _dp
    got = (await auditor.audit("http://x#")).pop().modalities["co2"]
    assert got["status"] == STATUS_PRESENT and got["uuid"] == STALE


def test_the_freshness_accessor_distinguishes_unavailable_from_empty():
    """The cached accessor's contract, asserted at the source so the docstring cannot drift
    from the behaviour every caller depends on."""
    from pathlib import Path

    src = Path("orchestrator/services/building_metrics.py").read_text(encoding="utf-8")
    body = src[src.index("async def fresh_uuids") : src.index("async def _default_reporting")]
    assert "None if by_store is None else" in body, (
        "an unavailable measurement now collapses to an empty set — every sensor in the "
        "building would be treated as stale"
    )
    assert "NEVER as" in body, "the None-vs-empty contract is no longer documented"


def test_the_schema_builder_never_fails_on_a_freshness_error():
    """Freshness is an optimisation of WHICH sensor is chosen. If it throws, the schema — and
    every lane that depends on it — must still be built."""
    from pathlib import Path

    src = Path("orchestrator/services/deliberation/capability_schema.py").read_text(
        encoding="utf-8"
    )
    block = src[src.index("BUG-255") : src.index("auditor = CoverageAuditor")]
    assert "except Exception" in block and "fresh = None" in block
