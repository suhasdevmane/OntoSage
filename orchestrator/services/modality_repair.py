# -*- coding: utf-8 -*-
"""CAVEAT-148 — when retrieval returns the WRONG sensors, ask the graph directly.

Measured on bldg2. The question was "What is the building-wide average humidity
this week?" and the generated SPARQL opened with:

    BIND(bldg:Building_Air_Static_Pressure_Sensor.01 AS ?sensor)

A PRESSURE sensor, for a HUMIDITY question. The vector retrieval anchored on
"building-wide" and surfaced ``Building_Air_Static_Pressure_Sensor``; SPARQL
generation then faithfully bound what it was given. Two symptoms followed from
that one cause:

* **wrong modality** — the answer had to decline ("the analysis only includes
  pressure readings"), which is honest but useless;
* **tiny population** — 2 sensors reached the fetch stage, so a "building-wide
  average" would have been computed from 2 of ~70 humidity sensors had they been
  the right type. The PDP even blocked a variant of this for k-anonymity, which
  is how the correctness bug first surfaced.

The repair is deliberately narrow. It fires ONLY when the question names a
modality unambiguously AND not one returned sensor matches it — i.e. exactly the
case that is already broken. A retrieval that got the modality right, or a
question with no clear modality (metadata, hierarchy, "what sensors are there"),
is left untouched, because the LLM path handles those shapes better than a class
lookup would.

The class list is resolved from ``config/saturation_modalities.yaml`` — the same
config that drives the coverage audit and SATURATE — so a building that adds a
modality gets this for free, and no building's vocabulary appears here.
"""

from __future__ import annotations

import re
from typing import Any, Dict, List, Optional, Sequence, Tuple

from shared.utils import get_logger

logger = get_logger(__name__)

#: Ceiling on the deterministic query. High enough that a whole building's
#: sensors of one modality fit (bldg2's largest class is ~140), bounded so a
#: pathological graph cannot return an unbounded result set.
MAX_SENSORS = 400


def modality_classes(modality: str, building_id: Optional[str] = None) -> Tuple[str, ...]:
    """Brick class LOCAL NAMES for a modality, honouring the building's overlay.

    Goes through coverage_audit.load_modalities, the ONE loader that merges the
    shared config with ``input/<id>/saturation_modalities.yaml``. Reading the
    shared file directly would silently ignore a building that defines its own
    modalities — the exact way a "building-agnostic" feature stops being one.
    """
    try:
        from orchestrator.services.deliberation.coverage_audit import load_modalities

        for spec in load_modalities(building_id):
            if spec.name == modality:
                return tuple(spec.brick_classes)
    except Exception as exc:  # pragma: no cover - config is optional
        logger.debug(f"[modality_repair] modality config unavailable: {exc}")
    return ()


#: Words that appear in EVERY sensor's class or IRI and therefore prove nothing.
#: Without this, splitting "Relative_Humidity_Sensor" yields "sensor", which
#: matches "Building_Air_Static_Pressure_Sensor" and the repair never fires.
_GENERIC_TOKENS = frozenset(
    {
        "sensor",
        "sensors",
        "meter",
        "meters",
        "level",
        "levels",
        "status",
        "point",
        "points",
        "equipment",
        "air",
        "zone",
        "room",
        "building",
        "relative",
        "count",
        "state",
        "contact",
        "data",
        "value",
    }
)


def _binding_text(binding: Dict[str, Any]) -> str:
    """All values of one SPARQL binding, lowercased — the haystack for matching."""
    parts: List[str] = []
    for val in (binding or {}).values():
        if isinstance(val, dict) and val.get("value"):
            parts.append(str(val["value"]))
    return " ".join(parts).lower()


def results_match_modality(
    bindings: Sequence[Dict[str, Any]], modality: str, building_id: Optional[str] = None
) -> bool:
    """True when ANY returned sensor plausibly belongs to this modality.

    Deliberately generous: one match is enough to leave the result alone. The
    repair exists for the total-miss case, and a mixed result set is better
    handled downstream than replaced wholesale.
    """
    if not bindings:
        return False
    classes = modality_classes(modality, building_id)
    needles = {c.lower() for c in classes}
    needles.add(modality.lower())
    # class local names are CamelCase_With_Underscores; also try the bare words
    for c in classes:
        for word in re.split(r"[_\W]+", c):
            w = word.lower()
            if len(w) > 3 and w not in _GENERIC_TOKENS:
                needles.add(w)
    for b in bindings:
        text = _binding_text(b)
        if any(n in text for n in needles):
            return True
    return False


def build_modality_query(
    modality: str, namespace: str, limit: int = MAX_SENSORS, building_id: Optional[str] = None
) -> Optional[str]:
    """A deterministic SPARQL for every sensor of this modality that HAS readings.

    Requires a timeseries reference, because a sensor with no UUID cannot answer
    a data question — returning it would only reproduce the "no data" dead end.
    """
    classes = modality_classes(modality, building_id)
    if not classes or not namespace:
        return None
    values = " ".join(f'"{c}"' for c in classes)
    return (
        "PREFIX rdfs: <http://www.w3.org/2000/01/rdf-schema#>\n"
        "PREFIX ref: <https://brickschema.org/schema/Brick/ref#>\n"
        "SELECT DISTINCT ?sensor ?label ?uuid ?storage WHERE {\n"
        "  ?sensor a ?cls .\n"
        f"  VALUES ?local {{ {values} }}\n"
        '  FILTER(STRENDS(STR(?cls), CONCAT("#", ?local)) || '
        'STRENDS(STR(?cls), CONCAT("/", ?local)))\n'
        f'  FILTER(STRSTARTS(STR(?sensor), "{namespace}"))\n'
        "  OPTIONAL { ?sensor rdfs:label ?label }\n"
        "  ?sensor ref:hasExternalReference ?r .\n"
        "  ?r ref:hasTimeseriesId ?uuid .\n"
        "  OPTIONAL { ?r ref:storedAt ?storage }\n"
        f"}} LIMIT {int(limit)}"
    )


def needs_repair(
    bindings: Sequence[Dict[str, Any]],
    modality: Optional[str],
    building_id: Optional[str] = None,
) -> bool:
    """Should the deterministic query replace what retrieval returned?"""
    if not modality:
        return False  # no clear modality — the LLM path owns these shapes
    if not modality_classes(modality, building_id):
        return False  # unknown modality for THIS building: never guess
    return not results_match_modality(bindings, modality, building_id)


#: Phrasings that make the QUESTION about a population rather than a place.
#: "building-wide average humidity" is answered wrongly by 8 sensors even when
#: all 8 are genuinely humidity sensors — the aggregate must span what the
#: question claims to span. Single-space questions ("temperature in RM101")
#: match none of these and keep their one sensor.
_AGGREGATE_RE = re.compile(
    r"\b(building[- ]wide|across the (?:building|site)|whole building|entire building|"
    r"every (?:room|space|zone|floor)|all (?:rooms|spaces|zones|floors)|"
    r"overall average|site[- ]wide)\b",
    re.IGNORECASE,
)


def is_aggregate_question(query: str) -> bool:
    """Does the question claim to span the building rather than one place?"""
    return bool(query) and bool(_AGGREGATE_RE.search(query))


def needs_population(
    query: str, bindings: Sequence[Dict[str, Any]], modality: Optional[str]
) -> bool:
    """True when an aggregate question is about to be answered from a SAMPLE.

    Separate from needs_repair: that one catches the WRONG modality, this one
    catches the right modality with too few of it. Measured: "building-wide
    average humidity this week" aggregated 8 of ~70 humidity sensors, and the
    k-anonymity floor blocked it at k=8 — the privacy gate catching a
    correctness bug, because an average over 8 sensors is not building-wide.
    """
    if not modality or not is_aggregate_question(query):
        return False
    if not modality_classes(modality):
        return False
    return True  # the caller compares against the graph population
