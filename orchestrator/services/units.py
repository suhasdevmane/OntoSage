# -*- coding: utf-8 -*-
"""A unit conversion contract: approved conversions are explicit, the rest are refused.

V12-10, review case A11 — *"Supply compatible convertible units, then unknown or
incompatible units. Approved conversion is explicit; unsupported combinations are
rejected."*

WHY THIS IS NEEDED HERE, MEASURED RATHER THAN ASSUMED
-----------------------------------------------------
Nothing in this pipeline converted units before this module — which sounds safe until you
ask what happens when one aggregation spans sensors that disagree. Measured on bldg1's
live graph, 2026-09-10, several concrete Brick classes carry more than one unit:

    Occupancy_Count_Sensor   NUM (6 points)  ·  PERCENT (2)
    Air_Quality_Sensor       PPM (2)  ·  PPB (1)  ·  MicroGM-PER-M3 (1)
    Particulate_Matter       MicroGM-PER-M3 (1)  ·  PPB (1)
    Flow_Sensor              L-PER-MIN  ·  M3  ·  "L/s" (13)
    Sound_Level_Sensor       DeciB  ·  DEC

Averaging a count with a percentage produces a number with no meaning. So does averaging
µg/m³ with ppb, which cannot be converted at all without the molar mass of the substance
and the temperature and pressure — none of which this building declares.

``Noise_Sensor_Floor5`` carries **both** ``DeciB`` and ``DEC`` at once: one point, two
contradictory unit declarations.

THE SHAPE OF THE CONTRACT
-------------------------
Refusal is the default. A conversion happens only when this module names it, and the
factor it used is returned so the evidence record can state it. An unknown unit is not
assumed compatible with anything, including itself under a different spelling — the
`_QUDT_LOCAL` table in `modality_units` is what reconciles spellings, and anything it does
not know arrives here as an unknown and is refused.

That default matters more than the conversion table. A silently wrong conversion is
indistinguishable from a correct answer; a refusal is visible and recoverable.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Dict, Iterable, Optional, Set, Tuple

from orchestrator.services.modality_units import display_unit, qudt_unit_display

#: Canonical symbol -> quantity kind. Units in different kinds are NEVER interconvertible.
#:
#: `count` and `ratio` are listed separately on purpose: an occupancy sensor reporting NUM
#: and one reporting PERCENT are measuring different quantities about the same room, and
#: the live graph has both under `Occupancy_Count_Sensor`.
_KIND: Dict[str, str] = {
    "°C": "temperature", "°F": "temperature", "K": "temperature",
    "ppm": "concentration_ratio", "ppb": "concentration_ratio",
    "µg/m³": "concentration_mass", "mg/m³": "concentration_mass",
    "Pa": "pressure", "kPa": "pressure",
    "W": "power", "kW": "power",
    "Wh": "energy", "kWh": "energy",
    "L": "volume", "m³": "volume",
    "L/s": "volumetric_flow", "L/min": "volumetric_flow", "m³/h": "volumetric_flow",
    "m³/s": "volumetric_flow",
    "lux": "illuminance",
    # `dB(A)` and not `dBA`: that is what `display_unit` produces, and a key the
    # normaliser can never emit is dead weight that reports a known unit as unknown.
    "dB": "sound_level", "dB(A)": "sound_level",
    "%": "ratio",
    "count": "count",
    "mm": "length", "m": "length",
    "kg": "mass",
    "ppm-CO2e": "concentration_ratio",
}

#: Approved conversions, as (from, to) -> (multiply, then add). Affine so temperature is
#: expressible without a special case. Every pair here is exact and dimensionally sound.
_FACTOR: Dict[Tuple[str, str], Tuple[float, float]] = {
    ("ppm", "ppb"): (1000.0, 0.0),
    ("ppb", "ppm"): (0.001, 0.0),
    ("°C", "°F"): (1.8, 32.0),
    ("°F", "°C"): (1 / 1.8, -32.0 / 1.8),
    ("°C", "K"): (1.0, 273.15),
    ("K", "°C"): (1.0, -273.15),
    ("Pa", "kPa"): (0.001, 0.0),
    ("kPa", "Pa"): (1000.0, 0.0),
    ("W", "kW"): (0.001, 0.0),
    ("kW", "W"): (1000.0, 0.0),
    ("Wh", "kWh"): (0.001, 0.0),
    ("kWh", "Wh"): (1000.0, 0.0),
    ("L", "m³"): (0.001, 0.0),
    ("m³", "L"): (1000.0, 0.0),
    ("L/s", "L/min"): (60.0, 0.0),
    ("L/min", "L/s"): (1 / 60.0, 0.0),
    ("L/s", "m³/h"): (3.6, 0.0),
    ("m³/h", "L/s"): (1 / 3.6, 0.0),
    ("L/min", "m³/h"): (0.06, 0.0),
    ("m³/h", "L/min"): (1 / 0.06, 0.0),
    ("mm", "m"): (0.001, 0.0),
    ("m", "mm"): (1000.0, 0.0),
}

#: Pairs that share no quantity kind but which somebody will eventually try, each with the
#: reason a refusal is the correct answer rather than a missing feature.
_WHY_REFUSED: Dict[frozenset, str] = {
    frozenset({"concentration_ratio", "concentration_mass"}):
        "converting between a volume ratio (ppm/ppb) and a mass concentration (µg/m³) "
        "requires the substance's molar mass and the air temperature and pressure, none "
        "of which this building declares",
    frozenset({"count", "ratio"}):
        "a count and a percentage are different quantities — a room holding 4 people and "
        "a room at 40% of capacity cannot be averaged together",
    frozenset({"sound_level", "ratio"}):
        "decibels are logarithmic; they cannot be averaged with, or converted to, a "
        "dimensionless ratio",
}


def normalise(token: Optional[str]) -> str:
    """A unit token, IRI or literal, as its canonical printed symbol.

    Goes through `modality_units` so there is ONE spelling table, not two. A token it does
    not recognise is returned as given and will be treated as unknown below — never
    guessed at.
    """
    raw = (token or "").strip()
    if not raw:
        return ""
    if "://" in raw or "#" in raw or (":" in raw and "/" not in raw):
        return qudt_unit_display(raw)
    return display_unit(raw) or raw


def quantity_kind(unit: Optional[str]) -> Optional[str]:
    """What this unit measures, or None when the unit is unknown to the contract."""
    return _KIND.get(normalise(unit))


@dataclass(frozen=True)
class Conversion:
    """The result of asking for a conversion. `ok` False means nothing was converted."""

    ok: bool
    value: Optional[float] = None
    from_unit: str = ""
    to_unit: str = ""
    #: Human-readable statement of what was applied, for the evidence record.
    factor: str = ""
    reason: str = ""


def convert(value: float, frm: Optional[str], to: Optional[str]) -> Conversion:
    """Convert, or refuse and say why. Never guesses."""
    a, b = normalise(frm), normalise(to)
    if not a or not b:
        return Conversion(False, from_unit=a, to_unit=b,
                          reason="a unit was missing, and an unlabelled number cannot be converted")
    if a == b:
        return Conversion(True, value, a, b, factor="no conversion needed")

    ka, kb = _KIND.get(a), _KIND.get(b)
    if ka is None or kb is None:
        unknown = a if ka is None else b
        return Conversion(False, from_unit=a, to_unit=b,
                          reason=f"{unknown!r} is not a unit this contract knows; it is not "
                                 "assumed compatible with anything")
    if ka != kb:
        why = _WHY_REFUSED.get(frozenset({ka, kb}))
        return Conversion(False, from_unit=a, to_unit=b,
                          reason=why or f"{a} measures {ka} and {b} measures {kb}; there is no "
                                        "conversion between different quantities")

    pair = _FACTOR.get((a, b))
    if pair is None:
        return Conversion(False, from_unit=a, to_unit=b,
                          reason=f"{a} and {b} are both {ka}, but no approved conversion between "
                                 "them is declared; add one deliberately rather than inferring it")
    mul, add = pair
    return Conversion(True, value * mul + add, a, b,
                      factor=f"{a} → {b}: ×{mul:g}" + (f" {add:+g}" if add else ""))


@dataclass(frozen=True)
class AggregationDecision:
    """Whether a set of units may be aggregated, and into which unit."""

    ok: bool
    target: str = ""
    units: Tuple[str, ...] = ()
    note: str = ""
    reason: str = ""


def aggregation_decision(units: Iterable[Optional[str]]) -> AggregationDecision:
    """May these units be averaged, summed or compared together?

    This is the question the analytics lane actually has, and the one the live graph makes
    urgent: `Occupancy_Count_Sensor` carries NUM and PERCENT, `Air_Quality_Sensor` carries
    ppm, ppb and µg/m³.

    An EMPTY set is not permission. Aggregating values whose units are unknown is exactly
    the silent failure this exists to prevent, so it is refused with that said.
    """
    seen: Set[str] = {normalise(u) for u in units if (u or "").strip()}
    seen.discard("")
    ordered = tuple(sorted(seen))

    if not ordered:
        return AggregationDecision(False, units=ordered,
                                   reason="no unit is declared for these readings, so what an "
                                          "aggregate of them would mean is not established")
    if len(ordered) == 1:
        return AggregationDecision(True, target=ordered[0], units=ordered,
                                   note="all readings share one unit")

    kinds = {(_KIND.get(u) or f"unknown:{u}") for u in ordered}
    if len(kinds) > 1:
        known = {k for k in kinds if not k.startswith("unknown:")}
        why = _WHY_REFUSED.get(frozenset(known)) if len(known) == 2 else None
        return AggregationDecision(
            False, units=ordered,
            reason=why or ("these readings measure different quantities ("
                           + ", ".join(sorted(kinds)) + "), so no single aggregate is meaningful"))

    # One kind, several units: convertible only if every one converts to the first.
    target = ordered[0]
    for u in ordered[1:]:
        if not convert(1.0, u, target).ok:
            return AggregationDecision(
                False, units=ordered,
                reason=f"{u} and {target} are both "
                       f"{_KIND.get(target)} but no approved conversion is declared between them")
    return AggregationDecision(
        True, target=target, units=ordered,
        note="converted to " + target + " via " + "; ".join(
            convert(1.0, u, target).factor for u in ordered[1:]))
