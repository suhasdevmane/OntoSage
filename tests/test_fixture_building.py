# -*- coding: utf-8 -*-
"""The fixture building must stay unlike every real building (V6-T64).

V6 is developed entirely against bldg1, so a test written against bldg1's data passes for
bldg1-shaped reasons and the assumption stays invisible until somebody swaps buildings. This
fixture exists to break those assumptions on the commit that introduces them.

Its value depends on it staying adversarial. If someone later "tidies" it to look like a
normal building -- dotted room ids, numbered floors, a floor plan -- it silently stops
testing anything, and no other test would notice. These tests pin the properties that make
it useful.
"""

from pathlib import Path

import pytest
import yaml

pytestmark = pytest.mark.unit

FIXTURE = Path(__file__).resolve().parent / "fixtures" / "fixture_building"
CFG = yaml.safe_load((FIXTURE / "building.yaml").read_text(encoding="utf-8"))
TTL = (FIXTURE / "fixture_model.ttl").read_text(encoding="utf-8")


def test_fixture_exists_and_is_declared_synthetic():
    assert CFG["building_id"] == "fixture"
    assert CFG["provenance"]["nature"] == "synthetic"


def test_namespace_resembles_no_real_building():
    """A test that passes here cannot be matching on a real building's namespace."""
    ns = CFG["ontology_namespace"]
    for real in ("cardiff.ac.uk", "abacws", "buildsys.org", "bldg1", "bldg2", "bldg3"):
        assert real not in ns.lower()
    # Deliberately terminated with "/" rather than "#": both are legal RDF, and code that
    # assumes one of them breaks on the other.
    assert ns.endswith("/")


def test_room_ids_are_not_dotted():
    """bldg1 numbers rooms `2.15`; anything that assumes that pattern must fail here."""
    assert "fix:W-A1" in TTL
    import re

    # No `N.NN`-shaped room identifier anywhere in the fixture.
    assert not re.search(r"fix:\d+\.\d{2}\b", TTL)


def test_floors_are_named_not_numbered():
    """Code that parses a floor NUMBER out of an id has nothing to parse here."""
    assert 'rdfs:label "Ground"' in TTL
    assert 'rdfs:label "Upper"' in TTL


def test_fixture_has_no_floor_plans():
    """Geometry, spatial and wayfinding must DECLINE, not assume a DWG exists."""
    for pattern in ("*.dwg", "*.dxf", "*.pdf"):
        assert not list(FIXTURE.glob(pattern)), f"fixture must have no {pattern}"


def test_fixture_has_no_optional_config_files():
    """Every optional per-building file absent, so absence is the tested default."""
    for name in ("feeds.yaml", "rules.yaml", "channels.yaml", "benchmarks.csv", "intents.yaml"):
        assert not (FIXTURE / name).exists(), f"{name} must stay absent"
    assert not (FIXTURE / "personas").exists()


def test_fixture_distinguishes_not_connected_from_not_instrumented():
    """The state that is easiest to conflate, and therefore worth having.

    fix:Co2B1 is DECLARED in the graph but has no ref:TimeseriesReference. That is a
    different answer from "this building has no CO2 sensor" -- one says connect the data,
    the other says install a sensor -- and code that collapses them gives the wrong remedy.
    """
    assert "fix:Co2B1" in TTL
    co2_block = TTL.split("fix:Co2B1")[1]
    assert "hasTimeseriesId" not in co2_block, "Co2B1 must stay unconnected"
    # ...while the temperature sensor IS connected, giving the contrast.
    temp_block = TTL.split("fix:TempA1")[1].split("fix:Co2B1")[0]
    assert "hasTimeseriesId" in temp_block


def test_fixture_offers_all_three_spatial_adequacy_cases():
    """in-room (W-A1 has a sensor), no-sensor (W-A2), and a wholly uninstrumented floor."""
    assert "fix:W-A1" in TTL and "brick:isPointOf fix:W-A1" in TTL
    assert "fix:W-A2" in TTL
    assert "brick:isPointOf fix:W-A2" not in TTL


def test_every_fixture_sensor_declares_its_provenance():
    """A synthetic source that does not say so is the failure V6-T62 exists to prevent."""
    for sensor in ("fix:TempA1", "fix:Co2B1"):
        block = TTL.split(sensor)[1].split(" .\n")[0]
        assert "ontosage:isSimulated" in block, f"{sensor} must declare provenance"
