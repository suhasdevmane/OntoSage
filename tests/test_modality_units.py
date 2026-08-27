# -*- coding: utf-8 -*-
"""A reading's unit reaches the answer (BUG-257, 2026-08-27).

"What is the filter differential pressure?" answered *152 - 154 units (the exact
unit isn't specified)* about a point carrying ``qudt:hasUnit <unit:PA>`` AND
``brick:hasUnit "Pa"``. The unit was declared twice, in two conventions, and
neither reached the narration.

Two causes, both fixed here:

* ``_unit_for_kind`` hardcoded eight units behind nine ``if "temperature" in
  text`` branches, while ``config/saturation_modalities.yaml`` declares
  thirty-five modalities each carrying its own ``sat.unit``. Sound level,
  illuminance and PM2.5 — all instrumented and saturated on bldg1 — reached the
  narration with no unit at all, about quantities the config names in one line.
  That is the drift the project's own design contract forbids: a code constant
  restating what config declares, and falling behind it.

* Every sensor template bound ``brick:hasUnit`` only. A building that published
  the QUDT convention lost its unit at the query, before any of this ran.

The resolution order is strongest-evidence-first, and an unknown quantity gets no
unit rather than a plausible one: a number printed in the wrong unit is a wrong
answer, while "unspecified" is merely incomplete.
"""

import types

import pytest

from orchestrator.services.modality_units import (
    display_unit,
    qudt_unit_display,
    unit_for_sensor,
)

pytestmark = pytest.mark.unit

_BRICK = "https://brickschema.org/schema/Brick#"


@pytest.fixture()
def build():
    """The real builder, bound to a bare object — it needs only two helpers."""
    from orchestrator.workflow._orchestrator import WorkflowOrchestrator as W

    o = types.SimpleNamespace()
    o._infer_sensor_kind = types.MethodType(W._infer_sensor_kind, o)
    o._unit_for_kind = types.MethodType(W._unit_for_kind, o)
    return types.MethodType(W._build_sensor_metadata_from_bindings, o)


def _binding(label, class_iri, *, unit=None, qunit=None):
    b = {
        "sensor": {"value": f"{_BRICK}instance_of_{label.replace(' ', '_')}"},
        "type": {"value": class_iri},
        "uuid": {"value": "11111111-2222-3333-4444-555555555555"},
        "label": {"value": label},
    }
    if unit is not None:
        b["unit"] = {"value": unit}
    if qunit is not None:
        b["qunit"] = {"value": qunit}
    return [b]


def _unit(build, *args, **kw):
    return list(build(_binding(*args, **kw)).values())[0]["unit"]


# ── the modalities the hardcoded table never covered ─────────────────────────
@pytest.mark.parametrize(
    "label,cls,expected",
    [
        ("Sound Level Sensor 5.01", f"{_BRICK}Sound_Level_Sensor", "dB"),
        ("Illuminance Sensor 5.01", f"{_BRICK}Illuminance_Sensor", "lux"),
        ("PM2.5 Level Sensor 5.34", f"{_BRICK}PM2.5_Level_Sensor", "µg/m³"),
        (
            "Filter Differential Pressure - AHU F5",
            f"{_BRICK}Filter_Differential_Pressure_Sensor",
            "Pa",
        ),
        ("Zone Air Temperature 5.01", f"{_BRICK}Zone_Air_Temperature_Sensor", "°C"),
    ],
)
def test_the_config_supplies_units_the_code_table_never_had(build, label, cls, expected):
    assert _unit(build, label, cls) == expected


def test_a_binary_quantity_gets_no_unit(build):
    """A contact sensor reading 1 is open, not "1 binary"."""
    assert _unit(build, "Door Contact 5.01", f"{_BRICK}Contact_Sensor") == ""


def test_an_unknown_class_gets_no_unit_rather_than_a_plausible_one(build):
    assert _unit(build, "Mystery Reading", f"{_BRICK}Not_A_Real_Sensor_Class") == ""


# ── both conventions the building publishes ──────────────────────────────────
def test_the_qudt_convention_is_read(build):
    """The point carried qudt:hasUnit <unit:PA>; every template bound only the
    brick literal, so the unit was lost at the query."""
    got = _unit(
        build,
        "Filter Differential Pressure",
        f"{_BRICK}Filter_Differential_Pressure_Sensor",
        qunit="http://qudt.org/vocab/unit/PA",
    )
    assert got == "Pa"


def test_an_asserted_unit_beats_the_config(build):
    """The building said it. Nothing here second-guesses that."""
    got = _unit(build, "Zone Air Temperature", f"{_BRICK}Zone_Air_Temperature_Sensor", unit="degF")
    assert got == "degF"


def test_the_brick_literal_wins_over_the_qudt_iri(build):
    """When a point publishes both, prefer the one a human wrote."""
    got = _unit(
        build,
        "Filter Differential Pressure",
        f"{_BRICK}Filter_Differential_Pressure_Sensor",
        unit="Pa",
        qunit="http://qudt.org/vocab/unit/KiloPA",
    )
    assert got == "Pa"


# ── the query actually asks for both ─────────────────────────────────────────
def test_every_unit_bearing_template_binds_both_conventions():
    """Reading two conventions is useless if the query only ever returns one."""
    import inspect

    from orchestrator.agents import sparql_agent

    src = inspect.getsource(sparql_agent)
    assert src.count("brick:hasUnit ?unit") == src.count("qudt:hasUnit ?qunit"), (
        "a template that binds brick:hasUnit without qudt:hasUnit loses the unit "
        "for any building using the other convention"
    )


# ── the small pieces ─────────────────────────────────────────────────────────
@pytest.mark.parametrize(
    "token,expected",
    [("degC", "°C"), ("percent", "%"), ("ug/m3", "µg/m³"), ("pa", "Pa"), ("binary", "")],
)
def test_display_tokens(token, expected):
    assert display_unit(token) == expected


def test_an_unmapped_token_passes_through_rather_than_vanishing():
    """A modality added to the config tomorrow must not silently lose its unit
    because this table has not been edited."""
    assert display_unit("furlongs") == "furlongs"


def test_an_unmapped_qudt_iri_is_printed_as_qudt_spells_it():
    assert qudt_unit_display("http://qudt.org/vocab/unit/SOMETHING_ODD") == "SOMETHING_ODD"


def test_no_class_means_no_unit():
    assert unit_for_sensor(None, "a label") == ""
