# -*- coding: utf-8 -*-
"""What a metered total COST: consumption x the registered tariff in force (TODO-1646, 2026-10-11).

"How much did the building's water cost last week?" was answered from the cost register's monthly
lines -- the building held the metered litres and the water tariff and nothing joined them. The
method is the building's own, from its tariff document: "A cost answer is metered consumption
multiplied by the unit rate of the tariff in force for that period, plus the standing charge for
the days covered. Where no tariff covers a period, no cost is stated." So:

* the tariff is chosen by utility AND by the dates it is in force; a period no single tariff covers
  gets no figure, never a neighbouring year's rate;
* consumption is converted to the unit the rate is charged per (``ontosage:rateUnit``); a unit that
  cannot be converted gets no figure;
* the standing charge is per day covered, and the answer says rates exclude VAT.

Building-agnostic: tariffs, rates, units and currency are read from the graph.
"""

from __future__ import annotations

import math
import re
from datetime import datetime
from typing import Any, Dict, List, Optional

from shared.utils import get_logger

logger = get_logger(__name__)

_COST_RE = re.compile(
    r"\b(?:cost|costs|costing|spend|spent|spending|bill|bills|charges?|expense|expenditure|"
    r"price|paid|pay)\b|£|\$|€",
    re.IGNORECASE,
)

TARIFF_QUERY = """PREFIX ontosage: <http://ontosage.org/capabilities#>
SELECT ?t ?id ?kind ?rate ?unit ?standing ?currency ?from ?to ?provider WHERE {
  ?t a ontosage:Tariff ; ontosage:utilityKind ?kind ; ontosage:unitRate ?rate .
  OPTIONAL { ?t ontosage:recordId ?id }
  OPTIONAL { ?t ontosage:rateUnit ?unit }
  OPTIONAL { ?t ontosage:standingCharge ?standing }
  OPTIONAL { ?t ontosage:currencyCode ?currency }
  OPTIONAL { ?t ontosage:effectiveFrom ?from }
  OPTIONAL { ?t ontosage:effectiveTo ?to }
  OPTIONAL { ?t ontosage:providerName ?provider }
} LIMIT 200"""

#: unit -> (rate unit, factor): consumption in `unit` x factor = consumption in the rate's unit.
_TO_RATE_UNIT = {
    ("l", "m3"): 0.001,
    ("m³", "m3"): 1.0,
    ("m3", "m3"): 1.0,
    ("kwh", "kwh"): 1.0,
    ("wh", "kwh"): 0.001,
    ("mwh", "kwh"): 1000.0,
}

_SYMBOL = {"GBP": "£", "EUR": "€", "USD": "$"}


def asks_for_cost(question: str) -> bool:
    """The question asks what something cost, not how much was used."""
    return bool(_COST_RE.search(question or ""))


def utility_for(measurand: Optional[str], unit: str) -> Optional[str]:
    """The tariff utility a metered quantity is billed under, or None when it is not billed."""
    m = (measurand or "").lower()
    u = (unit or "").strip().lower()
    if "water" in m or u in ("l", "m3", "m³"):
        return "water"
    if "gas" in m:
        return "gas"
    if any(w in m for w in ("energy", "electric")) or u in ("kwh", "wh", "mwh"):
        return "electricity"
    return None


def _value(b: Dict[str, Any], key: str) -> str:
    return str((b.get(key) or {}).get("value") or "")


def _date(text: str) -> Optional[datetime]:
    try:
        return datetime.fromisoformat(str(text)[:10])
    except ValueError:
        return None


def pick_tariff(
    bindings: List[Dict[str, Any]], utility: str, start: datetime, end: datetime
) -> Optional[Dict[str, Any]]:
    """The ONE tariff of this utility in force for the whole period, else None."""
    fits = []
    for b in bindings or []:
        if _value(b, "kind").strip().lower() != utility:
            continue
        lo, hi = _date(_value(b, "from")), _date(_value(b, "to"))
        if lo is None or hi is None:
            continue
        if lo.date() <= start.date() and end.date() <= hi.date():
            fits.append(b)
    if len(fits) != 1:
        return None
    b = fits[0]
    try:
        return {
            "id": _value(b, "id") or _value(b, "t").rsplit("/", 1)[-1],
            "rate": float(_value(b, "rate")),
            "rate_unit": _value(b, "unit"),
            "standing": float(_value(b, "standing") or 0.0),
            "currency": _value(b, "currency") or "",
            "provider": _value(b, "provider"),
        }
    except ValueError:
        return None


def cost_of(total: float, unit: str, days: int, tariff: Dict[str, Any]) -> Optional[Dict[str, Any]]:
    """Consumption x rate (in the rate's unit) + standing charge x days, or None."""
    factor = _TO_RATE_UNIT.get(
        ((unit or "").strip().lower(), (tariff.get("rate_unit") or "").lower())
    )
    if factor is None or tariff.get("rate", 0) <= 0:
        return None
    quantity = total * factor
    energy_cost = quantity * tariff["rate"]
    standing = tariff.get("standing", 0.0) * max(days, 0)
    return {
        "quantity": quantity,
        "energy_cost": energy_cost,
        "standing": standing,
        "total": energy_cost + standing,
    }


def cost_sentence(total: float, unit: str, days: int, tariff: Dict[str, Any]) -> str:
    """The sentence a cost answer adds, or "" when no figure may be stated."""
    got = cost_of(total, unit, days, tariff)
    if got is None:
        return ""
    cur = tariff.get("currency") or ""
    sym = _SYMBOL.get(cur.upper(), "")
    money = (lambda x: f"{sym}{x:,.2f}") if sym else (lambda x: f"{x:,.2f} {cur}".strip())
    # a RATE keeps the precision the tariff states (£1.945, £0.2847); only sums are rounded
    rate = (lambda x: f"{sym}{x:g}") if sym else (lambda x: f"{x:g} {cur}".strip())
    rate_unit = "m³" if tariff["rate_unit"].lower() == "m3" else tariff["rate_unit"]
    source = tariff["id"] + (f", {tariff['provider']}" if tariff.get("provider") else "")
    text = (
        f"**At the tariff in force ({source}: {rate(tariff['rate'])} per {rate_unit}), that is "
        f"about {money(got['total'])}**"
    )
    if got["standing"]:
        text += (
            f" — {money(got['energy_cost'])} for {got['quantity']:,.1f} {rate_unit} plus "
            f"{rate(tariff['standing'])} a day standing charge for {days} day(s)"
        )
    return text + ". Rates exclude VAT."


async def append_cost(
    answer: Dict[str, Any],
    question: str,
    measurand: Optional[str],
    start: str,
    end: str,
    tz_name: Optional[str],
    sparql_exec,
) -> Dict[str, Any]:
    """``answer`` with the cost of its total added when the question asks for one."""
    if not (answer and asks_for_cost(question) and sparql_exec is not None):
        return answer
    agg = answer.get("aggregate") or {}
    unit = str(agg.get("unit") or "")
    total = (answer.get("figures") or {}).get("total")
    utility = utility_for(measurand, unit)
    if total is None or not utility:
        return answer
    try:
        from orchestrator.services.requested_interval import to_local

        lo = to_local(datetime.fromisoformat(str(start)[:19]), tz_name)
        hi = to_local(datetime.fromisoformat(str(end)[:19]), tz_name)
        rows = ((await sparql_exec(TARIFF_QUERY)) or {}).get("results", {}).get("bindings", [])
    except Exception as exc:  # a cost is an addition; it never costs the answer
        logger.info(f"[cost] tariff lookup skipped: {exc}")
        return answer
    days = max(1, math.ceil((hi - lo).total_seconds() / 86400.0 - 1e-6))
    tariff = pick_tariff(rows, utility, lo, hi)
    if tariff is None:
        note = (
            f"No single {utility} tariff in the building's register covers this whole period, so "
            "no cost is stated."
        )
    else:
        note = cost_sentence(float(total), unit, days, tariff)
        if not note:
            note = f"The {utility} tariff's rate unit does not match the meter's, so no cost is stated."
    out = dict(answer)
    out["formatted_response"] = f"{answer.get('formatted_response') or ''}\n\n{note}".strip()
    logger.info(f"[cost] {utility}: {note[:120]}")
    return out


# ── emissions: electricity x the building's declared grid carbon intensity (2026-11-07) ──────

#: "carbon footprint", "emissions", "CO2e", "greenhouse gas" -- a question about EMISSIONS, not
#: about the CO2 concentration a room sensor reads ("is the CO2 high?" names no emission word).
_CARBON_RE = re.compile(
    r"\b(?:carbon\s+(?:footprint|emissions?|output|impact)|co2e|co2\s+emissions?|emissions?|"
    r"greenhouse\s+gas(?:es)?|ghg|kg\s*co2|tonnes?\s+of\s+(?:co2|carbon))\b",
    re.IGNORECASE,
)

CARBON_QUERY = """PREFIX ontosage: <http://ontosage.org/capabilities#>
PREFIX brick: <https://brickschema.org/schema/Brick#>
SELECT ?b ?f ?src WHERE {
  ?b ontosage:gridCarbonIntensity ?f .
  OPTIONAL { ?b ontosage:gridCarbonIntensitySource ?src }
} LIMIT 5"""


def asks_for_carbon(question: str) -> bool:
    """The question asks for the EMISSIONS of what was used, not a CO2 concentration."""
    return bool(_CARBON_RE.search(question or ""))


def carbon_sentence(total_kwh: float, grams_per_kwh: float, source: str = "") -> str:
    """'... that is about 3,226 kg CO2e (3.2 t)' -- the arithmetic and its factor, stated."""
    kg = total_kwh * grams_per_kwh / 1000.0
    tonnes = f" ({kg / 1000.0:,.1f} t)" if kg >= 1000 else ""
    where = f", {source}" if source else ""
    return (
        f"**At the building's declared grid carbon intensity ({grams_per_kwh:g} gCO2e per kWh"
        f"{where}), that is about {kg:,.0f} kg CO2e{tonnes}** from electricity. This counts "
        "electricity only, at one factor for the whole period; other fuels are not included."
    )


async def append_carbon(
    answer: Dict[str, Any], question: str, measurand: Optional[str], sparql_exec
) -> Dict[str, Any]:
    """``answer`` with the emissions of its electricity total added when the question asks."""
    if not (answer and asks_for_carbon(question) and sparql_exec is not None):
        return answer
    agg = answer.get("aggregate") or {}
    unit = str(agg.get("unit") or "")
    total = (answer.get("figures") or {}).get("total")
    if total is None or utility_for(measurand, unit) != "electricity":
        return answer
    factor = _TO_RATE_UNIT.get((unit.strip().lower(), "kwh"))
    if factor is None:
        return answer
    try:
        rows = ((await sparql_exec(CARBON_QUERY)) or {}).get("results", {}).get("bindings", [])
    except Exception as exc:  # an emissions line is an addition; it never costs the answer
        logger.info(f"[carbon] factor lookup skipped: {exc}")
        return answer
    values = sorted({float(_value(r, "f")) for r in rows if _value(r, "f")})
    if len(values) != 1:
        note = (
            "The building declares no single grid carbon intensity, so no emissions figure is "
            "stated."
            if not values
            else "The building declares more than one grid carbon intensity, so no emissions "
            "figure is stated."
        )
    else:
        source = next((_value(r, "src") for r in rows if _value(r, "src")), "")
        note = carbon_sentence(float(total) * factor, values[0], source)
    out = dict(answer)
    out["formatted_response"] = f"{answer.get('formatted_response') or ''}\n\n{note}".strip()
    figures = dict(out.get("figures") or {})
    if len(values) == 1:
        figures["kg CO2e"] = round(float(total) * factor * values[0] / 1000.0, 3)
        figures["gCO2e per kWh"] = values[0]
    out["figures"] = figures
    logger.info(f"[carbon] {note[:120]}")
    return out
