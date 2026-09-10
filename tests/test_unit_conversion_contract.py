# -*- coding: utf-8 -*-
"""Approved conversions are explicit; unsupported pairings are refused (V12-10, A11).

The fixtures are not invented. Every incompatible pairing tested here exists in bldg1's
live graph, measured 2026-09-10:

    Occupancy_Count_Sensor   NUM (6 points)  ·  PERCENT (2)
    Air_Quality_Sensor       PPM (2)  ·  PPB (1)  ·  MicroGM-PER-M3 (1)
    Particulate_Matter       MicroGM-PER-M3  ·  PPB
    Flow_Sensor              L-PER-MIN  ·  M3  ·  "L/s" (13)
    Sound_Level_Sensor       DeciB  ·  DEC   (both on ONE point, Noise_Sensor_Floor5)

WHY REFUSAL IS THE INTERESTING HALF
-----------------------------------
A wrong conversion is indistinguishable from a right answer once it reaches a sentence.
A refusal is visible and recoverable. So the tests that matter most here are the ones
asserting that nothing is guessed.
"""

from __future__ import annotations

import pytest

pytestmark = pytest.mark.unit

from orchestrator.services import units as U  # noqa: E402


# ── approved conversions, and the factor is named ────────────────────────────


@pytest.mark.parametrize(
    "value,frm,to,expected",
    [
        (1.0, "ppm", "ppb", 1000.0),
        (1000.0, "ppb", "ppm", 1.0),
        (0.0, "°C", "°F", 32.0),
        (100.0, "°C", "°F", 212.0),
        (212.0, "°F", "°C", 100.0),
        (0.0, "°C", "K", 273.15),
        (1.0, "kWh", "Wh", 1000.0),
        (1.0, "m³", "L", 1000.0),
        (1.0, "L/s", "L/min", 60.0),
        (1.0, "L/s", "m³/h", 3.6),
        (1.0, "kPa", "Pa", 1000.0),
    ],
)
def test_an_approved_conversion_is_exact(value, frm, to, expected):
    c = U.convert(value, frm, to)
    assert c.ok, c.reason
    assert c.value == pytest.approx(expected), f"{value}{frm} -> {c.value}{to}"


def test_the_conversion_states_what_it_applied():
    """A11: the conversion must be EXPLICIT — the evidence record has to be able to say
    what was done to the number, not merely that it changed."""
    c = U.convert(1.0, "L/s", "m³/h")
    assert c.ok and c.factor and "L/s" in c.factor and "m³/h" in c.factor


def test_an_identity_conversion_is_not_silent_either():
    c = U.convert(5.0, "ppm", "ppm")
    assert c.ok and c.value == 5.0 and c.factor


# ── the refusals, all of them from the live graph ────────────────────────────


def test_a_mass_concentration_is_not_a_volume_ratio():
    """Air_Quality_Sensor carries ppm, ppb AND µg/m³. The last cannot be converted to the
    others without the substance's molar mass and the air temperature and pressure."""
    c = U.convert(12.0, "µg/m³", "ppm")
    assert not c.ok
    assert "molar mass" in c.reason


def test_a_count_is_not_a_percentage():
    """Occupancy_Count_Sensor carries NUM and PERCENT."""
    c = U.convert(4.0, "count", "%")
    assert not c.ok
    assert "different quantities" in c.reason or "cannot be averaged" in c.reason


def test_an_unknown_unit_is_not_assumed_compatible_with_anything():
    for frm, to in [("widgets", "ppm"), ("ppm", "widgets"), ("widgets", "widgets2")]:
        c = U.convert(1.0, frm, to)
        assert not c.ok, f"{frm}->{to} was allowed"
        assert "not a unit this contract knows" in c.reason


def test_a_missing_unit_is_refused_rather_than_treated_as_matching():
    for frm, to in [(None, "ppm"), ("ppm", ""), ("", "")]:
        assert not U.convert(1.0, frm, to).ok


def test_same_kind_but_undeclared_pair_is_refused_not_inferred():
    """dB and dBA are both sound_level, but no conversion between them is declared —
    A-weighting is a filter, not a factor. The contract must not invent one."""
    c = U.convert(60.0, "dB", "dBA")
    assert not c.ok
    assert "no approved conversion" in c.reason


# ── aggregation, which is the question the analytics lane actually asks ──────


def test_one_unit_aggregates():
    d = U.aggregation_decision(["ppm", "ppm", "ppm"])
    assert d.ok and d.target == "ppm"


def test_convertible_units_aggregate_and_name_the_conversion():
    d = U.aggregation_decision(["L/s", "L/min"])
    assert d.ok and d.note and "→" in d.note


def test_occupancy_count_and_percent_cannot_be_aggregated():
    """Six points report NUM and two report PERCENT under one Brick class. Averaging them
    produces a number about nothing."""
    d = U.aggregation_decision(["count", "%"])
    assert not d.ok
    assert "cannot be averaged" in d.reason or "different quantities" in d.reason


def test_air_quality_three_units_cannot_be_aggregated():
    d = U.aggregation_decision(["ppm", "ppb", "µg/m³"])
    assert not d.ok, "ppm and ppb convert, but µg/m³ does not — the set as a whole must fail"


def test_no_declared_unit_is_not_permission_to_aggregate():
    """The silent failure this exists to prevent: unlabelled numbers averaged happily."""
    for empty in ([], [None], ["", None, "  "]):
        d = U.aggregation_decision(empty)
        assert not d.ok
        assert "not established" in d.reason or "no unit" in d.reason


def test_one_unknown_unit_poisons_the_set():
    d = U.aggregation_decision(["ppm", "widgets"])
    assert not d.ok


# ── the spelling layer it depends on (BUG-512) ───────────────────────────────


@pytest.mark.parametrize(
    "token,expected",
    [
        ("L/s", "L/s"),
        ("m3/h", "m³/h"),
        ("ug/m3", "µg/m³"),
        ("http://qudt.org/vocab/unit/PA", "Pa"),
        ("unit:PA", "Pa"),
        ("degc", "°C"),
    ],
)
def test_a_compound_unit_survives_normalisation(token, expected):
    """BUG-512: `qudt_unit_display` split every token on '/', so "L/s" became "s" — a flow
    rate reported as a time. Thirteen live Flow_Sensor points declare "L/s"."""
    assert U.normalise(token) == expected


def test_a_unit_that_normalises_wrongly_would_break_every_decision_above():
    """The contract is only as good as the spelling layer beneath it, so pin the link."""
    assert U.quantity_kind("L/s") == "volumetric_flow"
    assert U.quantity_kind("m3/h") == "volumetric_flow"
    assert U.quantity_kind("ug/m3") == "concentration_mass"
    assert U.quantity_kind("s") is None, (
        "'s' is seconds and must NOT be a flow unit — that is what BUG-512 produced"
    )


def test_every_unit_in_the_contract_is_spelt_the_way_the_normaliser_spells_it():
    """A self-consistency guard, added after `dBA` was in _KIND but normalised to `dB(A)`.

    A key the normaliser can never produce is dead: the contract would report a unit it
    fully understands as "not a unit this contract knows". That refusal is safe but it is
    the WRONG refusal, and the difference is what an operator reads when deciding whether
    the data or the contract needs fixing.
    """
    wrong = {u: U.normalise(u) for u in U._KIND if U.normalise(u) != u}
    assert not wrong, (
        "these _KIND keys are not stable under normalise(), so they can never be "
        f"matched: {wrong}"
    )
