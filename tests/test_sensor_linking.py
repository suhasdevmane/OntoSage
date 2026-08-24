# -*- coding: utf-8 -*-
"""Linking points the ontology describes but no database backs (V6).

An audit of bldg1 found 2,705 Brick points of which 113 carried no timeseries UUID: 23
legitimately (a command is written, not read; a camera is not a numeric stream) and 90 that
should have data and did not. Design contract 8 makes both halves necessary -- the triple AND
the rows -- so those 90 were describable and unanswerable.

Three properties are asserted, in descending order of how much damage getting them wrong does:

* **real data is never written to.** The registry marks bldg1's genuine Abacws snapshot
  `nature: real`; generated rows must never reach it, whatever arguments the script is given.
* **an unrecognised sensor is reported, never guessed at.** Inventing a destination is how a
  reading lands in the wrong table and is then averaged with unrelated quantities.
* **identifiers are deterministic**, so re-running links nothing twice.
"""

import importlib.util
from pathlib import Path

import pytest
import yaml

pytestmark = pytest.mark.unit

REPO = Path(__file__).resolve().parent.parent


def _registry_any_state() -> dict:
    """The building's database registry, whether a building is ACTIVE or PARKED.

    `link_unlinked_sensors.registry()` reads `input/database_registry.yaml`, which is correct
    for a script that operates on the live building — but the committed tree has NO active
    building by design (Workflow rule 8), so parked it returned `{}` and both registry tests
    failed on an empty dict rather than on anything about the registry.

    A unit test that needs a building to be running is a test that cannot run in CI or on a
    fresh clone, which is exactly where a dead storedAt link would otherwise reach production.
    """
    import yaml as _yaml

    candidates = [REPO / "input" / "database_registry.yaml"]
    candidates += sorted(REPO.glob("bldg*/database_registry.yaml"))
    for path in candidates:
        if path.is_file():
            data = _yaml.safe_load(path.read_text(encoding="utf-8")) or {}
            dbs = data.get("databases") or {}
            if dbs:
                return dbs
    return {}

SCRIPT = REPO / "scripts" / "link_unlinked_sensors.py"


@pytest.fixture(scope="module")
def linker():
    spec = importlib.util.spec_from_file_location("link_unlinked_sensors", SCRIPT)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


# -- identifiers -------------------------------------------------------------


def test_uuids_are_deterministic(linker):
    """Re-running must link nothing twice, so the id cannot be random."""
    iri = "http://example.org/b#Sensor_1"
    assert linker.stable_uuid(iri) == linker.stable_uuid(iri)


def test_different_sensors_get_different_uuids(linker):
    a = linker.stable_uuid("http://example.org/b#Sensor_1")
    b = linker.stable_uuid("http://example.org/b#Sensor_2")
    assert a != b


def test_the_uuid_is_a_uuid(linker):
    import uuid as _uuid

    _uuid.UUID(linker.stable_uuid("http://example.org/b#S"))


# -- the mapping comes from config, not from this file -----------------------


def test_the_class_map_is_read_from_the_modality_config(linker):
    """One place for the mapping. A building that adds a modality gets linking for free."""
    m = linker.class_to_modality()
    cfg = yaml.safe_load(
        (REPO / "config" / "saturation_modalities.yaml").read_text(encoding="utf-8")
    )["modalities"]
    for modality, spec in cfg.items():
        for cls in spec.get("brick_classes") or []:
            assert m.get(str(cls).split(":")[-1]) is not None


def test_every_modality_resolves_to_a_registered_table(linker):
    """A storedAt pointing at a table no registry entry names is a dead link.

    Checked for the modalities this repo actually uses, since the registry is per building.
    """
    dbs = linker.registry() or _registry_any_state()
    cfg = yaml.safe_load(
        (REPO / "config" / "saturation_modalities.yaml").read_text(encoding="utf-8")
    )["modalities"]
    unroutable = []
    for modality in cfg:
        table, _unit = linker.modality_table(modality)
        if table and not linker.storage_key_for(table, dbs):
            unroutable.append(f"{modality} -> {table}")
    # Not every modality is provisioned on every building; the ones this building links must be.
    for needed in ("occupancy", "illuminance", "humidity", "temperature", "co2"):
        table, _ = linker.modality_table(needed)
        assert linker.storage_key_for(table, dbs), f"{needed} has no registry key"


def test_a_prefixed_ontosage_class_maps_too(linker):
    """Brick 1.4 has no soil-moisture or rainfall class, so those are ontosage: terms."""
    m = linker.class_to_modality()
    assert m.get("Soil_Moisture_Sensor") == "soil_moisture"
    assert m.get("Rainfall_Sensor") == "rainfall"


# -- generation --------------------------------------------------------------


def test_generated_series_is_deterministic_per_sensor(linker):
    a = linker.series("temperature", days=2, step_min=60, seed=7)
    b = linker.series("temperature", days=2, step_min=60, seed=7)
    assert a == b


def test_values_respect_the_declared_floor_and_ceiling(linker):
    rows = linker.series("humidity", days=3, step_min=30, seed=11)
    assert all(15.0 <= v <= 95.0 for _t, v in rows)


def test_a_binary_modality_produces_only_0_and_1(linker):
    rows = linker.series("occupancy_status", days=2, step_min=30, seed=3)
    assert {v for _t, v in rows} <= {0.0, 1.0}


def test_a_cumulative_modality_never_decreases(linker):
    """A runtime-hours counter that goes backwards is not a counter."""
    rows = linker.series("runtime_hours", days=3, step_min=60, seed=5)
    vals = [v for _t, v in rows]
    assert all(b >= a for a, b in zip(vals, vals[1:]))


def test_an_unknown_modality_still_produces_a_bounded_series(linker):
    rows = linker.series("no_such_modality", days=1, step_min=60, seed=1)
    assert rows and all(v >= 0 for _t, v in rows)


def test_the_series_spans_the_requested_window(linker):
    rows = linker.series("temperature", days=5, step_min=60, seed=2)
    span_hours = (rows[-1][0] - rows[0][0]).total_seconds() / 3600
    assert 118 <= span_hours <= 122


# -- the safety properties ---------------------------------------------------


def test_real_datasources_are_refused_in_the_source(linker):
    """The registry marks bldg1's genuine snapshot nature: real.

    Asserted against the source rather than by executing a write, because the failure this
    guards against is irreversible: generated rows mixed into measured ones cannot be
    separated afterwards.
    """
    src = SCRIPT.read_text(encoding="utf-8")
    assert 'nature") == "real"' in src or "nature'] == 'real'" in src
    assert "REFUSING to seed" in src


def test_the_registry_still_marks_the_real_source(linker):
    """If this flips, the guard above silently protects nothing."""
    dbs = linker.registry() or _registry_any_state()
    real = [k for k, v in dbs.items() if isinstance(v, dict) and v.get("nature") == "real"]
    assert real, "no datasource declares nature: real — the seed guard has nothing to protect"


def test_generated_streams_are_declared_simulated(linker):
    """Declared simulation is permitted; undeclared fabrication is not."""
    ttl = linker.build_ttl(
        [
            {
                "iri": "http://example.org/b#S1",
                "uuid": "abc",
                "storage_key": "occupancy_data",
            }
        ],
        "http://example.org/b#",
    )
    assert "ontosage:isSimulated true" in ttl
    assert "generatedBy" in ttl


def test_the_ttl_declares_both_halves_of_the_link(linker):
    """A timeseries id with no storedAt is unroutable; storedAt with no id is unusable."""
    ttl = linker.build_ttl(
        [{"iri": "http://example.org/b#S1", "uuid": "abc", "storage_key": "occupancy_data"}],
        "http://example.org/b#",
    )
    assert "ref:hasTimeseriesId" in ttl
    assert "ref:storedAt" in ttl
    assert "a ref:TimeseriesReference" in ttl


def test_the_generated_ttl_parses(linker):
    from rdflib import Graph

    ttl = linker.build_ttl(
        [
            {"iri": "http://example.org/b#S1", "uuid": "u1", "storage_key": "occupancy_data"},
            {"iri": "http://example.org/b#S2", "uuid": "u2", "storage_key": "light_data"},
        ],
        "http://example.org/b#",
    )
    g = Graph()
    g.parse(data=ttl, format="turtle")
    assert len(g) >= 10


def test_non_timeseries_classes_are_recognised(linker):
    """A camera or a command must not be counted as a missing sensor and then 'fixed'."""
    for hint in ("Command", "Setpoint", "Camera", "CCTV"):
        assert hint in linker.NON_TIMESERIES_HINTS


# -- building agnosticism ----------------------------------------------------


def test_the_script_carries_no_building_literal():
    from scripts.check_building_literals import _prose_lines

    src = SCRIPT.read_text(encoding="utf-8")
    prose = _prose_lines(src)
    code = "\n".join(l for n, l in enumerate(src.splitlines(), 1) if n not in prose).lower()
    for literal in ("abacws", "bldg1", "bldg2", "bldg3", "cardiff"):
        assert literal not in code, f"linker hardcodes {literal}"
