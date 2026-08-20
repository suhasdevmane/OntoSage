# -*- coding: utf-8 -*-
"""
recipes_compute.py — deterministic computation classes with method citations
(V5-T27).

Three canonical building-analytics formulas the analytics lane can call
instead of asking an LLM to invent arithmetic. Every result carries its
``method`` and ``citation`` so the final answer can (and must) say HOW the
number was produced. Inputs that make a formula invalid return an ``error``
dict — never a silently wrong number.

Pure python, building-agnostic, no I/O.
"""

from __future__ import annotations

import math
from typing import Dict, Optional, Union

Number = Union[int, float]

#: UK convention heating base temperature (CIBSE TM41)
DEFAULT_BASE_TEMP_C = 15.5


def degree_day_normalized_kwh(
    kwh: Number, degree_days: Number, base_temp_c: Number = DEFAULT_BASE_TEMP_C
) -> Dict[str, object]:
    """Weather-normalized consumption: kWh per heating degree day.

    Lets two periods (or two buildings) be compared fairly: a cold month is
    EXPECTED to use more heat, so raw kWh comparisons mislead.
    """
    if degree_days is None or float(degree_days) <= 0:
        return {
            "error": "degree_days must be positive — cannot normalize against zero weather",
            "method": "degree-day normalization",
        }
    value = float(kwh) / float(degree_days)
    return {
        "value": round(value, 3),
        "unit": "kWh per degree day",
        "inputs": {
            "kwh": float(kwh),
            "degree_days": float(degree_days),
            "base_temp_c": float(base_temp_c),
        },
        "method": (
            f"consumption ÷ heating degree days (base {float(base_temp_c):g} °C): "
            f"{float(kwh):g} kWh ÷ {float(degree_days):g} DD"
        ),
        "citation": "CIBSE TM41: Degree days — theory and application",
    }


def ach_from_co2_decay(
    c_start_ppm: Number,
    c_end_ppm: Number,
    hours: Number,
    c_outdoor_ppm: Number = 420.0,
) -> Dict[str, object]:
    """Air changes per hour from CO2 tracer decay in an empty space.

    ACH = ln((C0 − Cout) / (C1 − Cout)) / t. Only valid while the space is
    unoccupied and BOTH concentrations sit above outdoor background.
    """
    try:
        c0, c1, cout, t = (
            float(c_start_ppm),
            float(c_end_ppm),
            float(c_outdoor_ppm),
            float(hours),
        )
    except (TypeError, ValueError):
        return {"error": "non-numeric input", "method": "CO2 tracer decay"}
    if t <= 0:
        return {"error": "decay window must be positive", "method": "CO2 tracer decay"}
    if not (c0 > c1 > cout):
        return {
            "error": (
                "decay requires start > end > outdoor CO2 "
                f"(got {c0:g} → {c1:g} vs outdoor {cout:g}) — the space was not in "
                "clean decay (occupied, or already at background)"
            ),
            "method": "CO2 tracer decay",
        }
    ach = math.log((c0 - cout) / (c1 - cout)) / t
    return {
        "value": round(ach, 3),
        "unit": "air changes per hour",
        "inputs": {"c_start_ppm": c0, "c_end_ppm": c1, "c_outdoor_ppm": cout, "hours": t},
        "method": (
            f"ACH = ln((C0−Cout)/(C1−Cout))/t = ln(({c0:g}−{cout:g})/({c1:g}−{cout:g}))/{t:g}h"
        ),
        "citation": "ASTM D6245 / Persily (1997): CO2 tracer-gas decay method",
    }


def tariff_cost(
    kwh: Number,
    tariff_per_kwh: Number,
    currency: str = "GBP",
    standing_charge: Optional[Number] = None,
) -> Dict[str, object]:
    """Metered energy × registered tariff rate (+ optional standing charge)."""
    try:
        e, rate = float(kwh), float(tariff_per_kwh)
    except (TypeError, ValueError):
        return {"error": "non-numeric input", "method": "kWh × tariff"}
    if rate <= 0:
        return {"error": "tariff rate must be positive", "method": "kWh × tariff"}
    cost = e * rate
    method = f"{e:g} kWh × {rate:g} {currency}/kWh"
    if standing_charge is not None:
        cost += float(standing_charge)
        method += f" + {float(standing_charge):g} {currency} standing charge"
    return {
        "value": round(cost, 2),
        "unit": currency,
        "inputs": {"kwh": e, "tariff_per_kwh": rate, "standing_charge": standing_charge},
        "method": method,
        "citation": "metered consumption × the building's registered tariff rate",
    }
