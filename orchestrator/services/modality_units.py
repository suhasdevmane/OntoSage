"""The unit a reading is measured in, resolved from the modality config (BUG-257).

``_unit_for_kind`` in the orchestrator hardcoded eight units behind nine
``if "temperature" in text`` branches, while ``config/saturation_modalities.yaml``
declares thirty-five modalities each carrying its own ``sat.unit``. So a sound
level, an illuminance reading and a PM2.5 concentration — all of which bldg1
instruments and saturates — reached the narration with no unit at all, and the
answer said the unit was unspecified about a quantity the config names in one
line. That is the code-constant-restating-config drift the project's own design
contract forbids (rule 2: if a fact can live in the config or the ontology, it
does not belong in a code constant).

Resolution order, strongest evidence first:

1. A unit asserted on the point itself (``brick:hasUnit`` / ``qudt:hasUnit``).
   The building said it; nothing here second-guesses that.
2. The modality config, matched on Brick class AND label. Class alone is not
   enough — PM1, PM2.5, PM10 and TVOC are all ``Particulate_Matter_Sensor`` and
   are told apart only by the label, so ``ModalitySpec.matches`` does both.
3. Nothing. An unknown quantity gets no unit rather than a plausible one; a
   number printed in the wrong unit is a wrong answer, and "unspecified" is
   merely an incomplete one.

Loaded through ``coverage_audit.load_modalities``, the one loader that merges the
shared config with ``input/<id>/saturation_modalities.yaml``. Reading the shared
file directly is how a building-agnostic feature stops being one.
"""

from __future__ import annotations

from typing import Dict, Optional

from shared.utils import get_logger

logger = get_logger(__name__)

#: The config stores machine tokens; an answer needs the printed form. A token
#: with no entry is passed through unchanged, so a new modality is never blocked
#: on editing this table.
_DISPLAY: Dict[str, str] = {
    "degc": "°C",
    "degf": "°F",
    "percent": "%",
    "pct": "%",
    "ppm": "ppm",
    "ppb": "ppb",
    "ug/m3": "µg/m³",
    "mg/m3": "mg/m³",
    "pa": "Pa",
    "kpa": "kPa",
    "m3h": "m³/h",
    "m3/h": "m³/h",
    "m3/s": "m³/s",
    "l": "L",
    "l/s": "L/s",
    "kwh": "kWh",
    "kw": "kW",
    "w": "W",
    "w/m2": "W/m²",
    "db": "dB",
    "dba": "dB(A)",
    "lux": "lux",
    "k": "K",
    "kg": "kg",
    "mm": "mm",
    "hours": "hours",
    "persons": "people",
    "bays": "bays",
    "count": "count",
    "index": "index",
}

#: Quantities where a unit would be nonsense next to a number. A contact sensor
#: reading 1 is open, not "1 binary".
_UNITLESS = {"binary", "bool", "boolean", "state", "status", "none", ""}


def display_unit(token: Optional[str]) -> str:
    """The printable form of a config unit token ('degC' -> '°C')."""
    t = (token or "").strip()
    if t.lower() in _UNITLESS:
        return ""
    return _DISPLAY.get(t.lower(), t)


#: QUDT publishes units as IRIs (``http://qudt.org/vocab/unit/PA``). bldg1 carries
#: both conventions on the same point — ``qudt:hasUnit <unit:PA>`` beside
#: ``brick:hasUnit "Pa"`` — and a query that binds only one loses the unit
#: whenever the building used the other (BUG-257). Only the local names this
#: estate actually uses are mapped; anything else passes through, so an unmapped
#: unit is printed as QUDT spells it rather than dropped.
_QUDT_LOCAL: Dict[str, str] = {
    "deg_c": "°C",
    "degreecelsius": "°C",
    "deg_f": "°F",
    "percent": "%",
    "ppm": "ppm",
    "ppb": "ppb",
    "pa": "Pa",
    "kilopa": "kPa",
    "lux": "lux",
    "lx": "lux",
    "decibel": "dB",
    "db": "dB",
    "kilow-hr": "kWh",
    "kilow": "kW",
    "w": "W",
    "microgm-per-m3": "µg/m³",
    "m3-per-hr": "m³/h",
    "m3-per-sec": "m³/s",
    "l": "L",
    "kilogm": "kg",
    "millim": "mm",
    "k": "K",
}


def qudt_unit_display(iri: Optional[str]) -> str:
    """The printable form of a QUDT unit IRI ('.../unit/PA' -> 'Pa')."""
    local = _class_local(iri)
    if not local:
        return ""
    return _QUDT_LOCAL.get(local.lower(), local)


def _class_local(class_iri: Optional[str]) -> str:
    """Local name of a class IRI or CURIE ('brick:CO2_Level_Sensor' -> 'CO2_Level_Sensor')."""
    s = (class_iri or "").strip()
    for sep in ("#", "/", ":"):
        s = s.rsplit(sep, 1)[-1]
    return s


def unit_for_sensor(
    class_iri: Optional[str] = None,
    label: Optional[str] = None,
    *,
    building_id: Optional[str] = None,
) -> str:
    """The declared unit for a sensor, from the building's modality config.

    Returns "" when no modality claims it — deliberately, rather than guessing.
    """
    local = _class_local(class_iri)
    if not local:
        return ""
    text = f"{label or ''} {class_iri or ''}"
    try:
        from orchestrator.services.deliberation.coverage_audit import load_modalities

        specs = load_modalities(building_id)
    except Exception as exc:  # pragma: no cover — the config is optional
        logger.debug(f"[modality_units] modality config unavailable: {exc}")
        return ""

    for spec in specs:
        # Same class+label discrimination the auditor uses. Matching on class
        # alone would give every Particulate_Matter_Sensor whichever of PM1,
        # PM2.5, PM10 or TVOC happens to be declared first.
        try:
            if spec.matches(local, text):
                return display_unit((spec.sat or {}).get("unit"))
        except Exception:  # pragma: no cover — a malformed spec must not break an answer
            continue
    return ""
