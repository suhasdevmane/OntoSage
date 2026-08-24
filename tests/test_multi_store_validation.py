# -*- coding: utf-8 -*-
"""UUID validation must ask the store each sensor actually lives in (BUG-234).

*"What's the biggest single-day water use we've ever logged?"* was answered **"Found 3 sensors
in metadata, but none exist in the time-series database."** All four water sensors have rows;
`Water_Flow_Sensor_Main` alone has 27,454 spanning 2026-06-08 to now.

The cause was structural rather than incidental. `sql_agent` took the FIRST non-null `storedAt`
it could find and validated EVERY uuid against that one adapter. bldg1's water sensors span
`water_data` and `waterflow_data`, so whichever table lost the coin toss had its sensors
declared absent. Any building with narrow per-modality tables meets this on any question
spanning two modalities -- which is most interesting questions.

The message was the second defect: "none exist in the time-series database" is a claim about
the estate's configuration, and it was false. Telling someone their sensors are not connected
when they are sends them to fix the wrong thing.
"""

import pytest

from orchestrator.services.adapters.registry import AdapterRegistry

pytestmark = pytest.mark.unit


class FakeDiscovery:
    """Knows about exactly the uuids held in one store."""

    def __init__(self, known):
        self.known = set(known)

    async def get_valid_uuids(self, candidates):
        return [c for c in candidates if c in self.known]


def _registry(**stores):
    r = AdapterRegistry()
    r._discoveries = {k: FakeDiscovery(v) for k, v in stores.items()}
    return r


@pytest.mark.asyncio
async def test_uuids_are_validated_against_their_own_store():
    """The defect, directly: two sensors, two stores, one call."""
    r = _registry(water_data=["u-water"], waterflow_data=["u-flow"])
    valid = await r.get_valid_uuids(
        ["u-water", "u-flow"],
        "bldg:water_data",
        storage_map={"u-water": "bldg:water_data", "u-flow": "bldg:waterflow_data"},
    )
    assert set(valid) == {"u-water", "u-flow"}


@pytest.mark.asyncio
async def test_the_single_store_path_is_what_produced_the_bug():
    """Kept as a regression witness. This IS the wrong answer, and it is what the caller got
    before the map was passed -- so it also documents why the map is not optional in practice.
    """
    r = _registry(water_data=["u-water"], waterflow_data=["u-flow"])
    valid = await r.get_valid_uuids(["u-water", "u-flow"], "bldg:water_data")
    assert "u-flow" not in valid


@pytest.mark.asyncio
async def test_without_the_map_the_old_behaviour_is_unchanged():
    """Callers that genuinely have one store must be unaffected."""
    r = _registry(water_data=["u-water"], waterflow_data=["u-flow"])
    assert await r.get_valid_uuids(["u-water", "u-flow"], "bldg:water_data") == ["u-water"]


@pytest.mark.asyncio
async def test_an_unknown_store_passes_its_candidates_through():
    """An unknown store is not an empty one. Declaring its sensors absent would reproduce the
    original defect in a new place."""
    r = _registry(water_data=["u-water"])
    valid = await r.get_valid_uuids(
        ["u-water", "u-elsewhere"],
        "bldg:water_data",
        storage_map={"u-water": "bldg:water_data", "u-elsewhere": "bldg:nosuch"},
    )
    assert "u-elsewhere" in valid


@pytest.mark.asyncio
async def test_no_discovery_at_all_passes_everything_through():
    r = AdapterRegistry()
    r._discoveries = {}
    got = await r.get_valid_uuids(["a", "b"], "", storage_map={"a": "x", "b": "y"})
    assert set(got) == {"a", "b"}


@pytest.mark.asyncio
async def test_a_uuid_missing_from_its_own_store_is_still_reported_missing():
    """The validation must keep working. This fix widens WHERE it looks, not WHETHER it looks."""
    r = _registry(water_data=["u-water"], waterflow_data=["u-flow"])
    valid = await r.get_valid_uuids(
        ["u-water", "u-ghost"],
        "bldg:water_data",
        storage_map={"u-water": "bldg:water_data", "u-ghost": "bldg:water_data"},
    )
    assert valid == ["u-water"]


def test_the_message_no_longer_claims_the_sensors_are_absent_from_the_database():
    """It asserted something false about the estate. What was actually checked is whether the
    identifiers appear in the store they are registered to."""
    from pathlib import Path

    src = (
        Path(__file__).resolve().parent.parent / "orchestrator" / "agents" / "sql_agent.py"
    ).read_text(encoding="utf-8")
    assert "none exist in the time-series database" not in src
    assert "have not been loaded yet" in src


def test_the_caller_passes_the_whole_map():
    """A per-store validator that is handed one store is the bug with extra steps."""
    from pathlib import Path

    src = (
        Path(__file__).resolve().parent.parent / "orchestrator" / "agents" / "sql_agent.py"
    ).read_text(encoding="utf-8")
    assert "storage_map=storage_map" in src
