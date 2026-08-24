# -*- coding: utf-8 -*-
"""BUG-192 — an answer may not claim the building lacks a sensor class it has.

Measured on bldg2, which has 138 temperature sensors:

    "The ontology data you provided does **not** contain any temperature
     sensors ... Therefore, I cannot list live room temperatures."

The refusal itself was right — that request asks for raw, high-frequency,
whole-building data — but the REASON was false. The user is told the building
cannot sense temperature, which is a statement about the building, not about the
request. Worse, the leak grader counts refusal markers, so the false claim scored
as a privacy PASS: a wrong answer hiding inside a green result.

Why it happens: the answering LLM is handed a bounded slice of retrieved ontology
context (30 lines since BUG-170) and generalises "not in what I was given" to
"not in the building". Non-existence is only knowable from the GRAPH — a COUNT —
never from a retrieval window, which is the same principle the referent-existence
gate already enforces for spaces.

This module is deliberately split into a pure detector (no I/O, fully testable)
and a verifier that needs the graph, so the decision logic can be pinned by unit
tests without a live stack.
"""

from __future__ import annotations

import re
from typing import Any, Callable, Dict, List, Optional, Tuple

from shared.utils import get_logger

logger = get_logger(__name__)

#: English phrasings -> the modality NAME used by the building's modality config.
#: Only the left-hand side is language; the classes themselves are resolved live
#: from config + the per-building overlay, so a building that defines its own
#: modalities is covered without touching this file.
_MODALITY_ALIASES: Dict[str, Tuple[str, ...]] = {
    "temperature": ("temperature", "temp", "room.temperature"),
    "humidity": ("humidity", "humid"),
    "co2": ("co2", "carbon dioxide"),
    "occupancy": ("occupancy", "occupant", "people count", "motion", "presence"),
    "noise": ("noise", "sound level", "sound"),
    "illuminance": ("illuminance", "lux", "light level"),
    "pm25": ("pm2.5", "pm25", "particulate"),
    "energy_submeter": ("energy", "electricity", "power"),
    # V6-T43/T44: these were missing, so a false "this building has no water sensors"
    # claim sailed past the guard that exists precisely to catch it. The alias table
    # must track config/saturation_modalities.yaml -- a modality the guard does not
    # know about is a modality the system can be wrong about, unchallenged.
    "water_flow": ("water", "water flow", "water usage", "water consumption"),
    # V6-T44 split. Listed separately because "no hot water sensors" is a different false
    # claim from "no water sensors", and a guard that only knew the umbrella term would let
    # the narrower one through unchallenged.
    "water_flow_hot": ("hot water", "hot water flow", "domestic hot water"),
    "water_flow_chilled": ("chilled water", "chilled water flow", "cooling water"),
    "waste_fill": ("waste", "bin", "recycling", "rubbish", "refuse"),
    "waste_weight": ("waste weight", "waste tonnage", "recycling weight"),
    "lift_state": ("lift", "elevator"),
    "parking_free": ("parking", "parking space", "car park"),
}


def modality_classes(modality: str, building_id: Optional[str] = None) -> Tuple[str, ...]:
    """Brick class local names for a modality, via the overlay-aware loader."""
    from orchestrator.services.modality_repair import modality_classes as _mc

    return _mc(modality, building_id)


#: Phrasings that assert absence. Deliberately narrow: each requires an explicit
#: negation ADJACENT to the modality, so "there is no data for 9am" (a windowing
#: statement) and "no rooms above 25 degrees" (a result set) are NOT caught.
_ABSENCE_PATTERNS: Tuple[str, ...] = (
    r"do(?:es)?\s+not\s+(?:contain|have|include)\s+any\s+(?:\w+\s+){0,3}?{m}",
    r"(?:contains?|has|have)\s+no\s+(?:\w+\s+){0,3}?{m}\s+sensors?",
    r"\bno\s+{m}\s+sensors?\b",
    r"\bno\s+instances?\s+of\s+[`'\"]?\w*:?{m}",
    r"there\s+are\s+no\s+(?:\w+\s+){0,3}?{m}\s+sensors?",
    r"lacks?\s+(?:any\s+)?{m}\s+sensors?",
)


def detect_absence_claim(text: str) -> Optional[str]:
    """Return the modality an answer claims the building lacks, else None.

    Pure and side-effect free. Precision-first: an unmatched answer returns None
    and passes through untouched, because a false positive here would rewrite a
    correct answer.
    """
    if not text:
        return None
    # Answers are markdown, and the live failure read "does **not** contain any
    # temperature sensors" — emphasis markers split the phrase and defeated a
    # plain regex. Strip them before matching.
    low = re.sub(r"[*_`]+", "", text.lower())
    if not any(w in low for w in ("not contain", "no ", "lacks", "does not have", "doesn't have")):
        return None  # cheap reject before the regex work
    for modality, aliases in _MODALITY_ALIASES.items():
        for alias in aliases:
            token = re.escape(alias).replace(r"\.", r"[.\s]?")
            for pat in _ABSENCE_PATTERNS:
                if re.search(pat.replace("{m}", token), low):
                    return modality
    return None


def _count_query(class_locals: Tuple[str, ...], namespace: str) -> str:
    """COUNT instances of any of these classes, matched on the class LOCAL NAME."""
    values = " ".join(f'"{c}"' for c in class_locals)
    return (
        "SELECT (COUNT(DISTINCT ?s) AS ?n) WHERE {\n"
        "  ?s a ?cls .\n"
        f"  VALUES ?local {{ {values} }}\n"
        '  FILTER(STRENDS(STR(?cls), CONCAT("#", ?local)) || '
        'STRENDS(STR(?cls), CONCAT("/", ?local)))\n'
        f'  FILTER(STRSTARTS(STR(?s), "{namespace}"))\n'
        "}"
    )


async def count_sensors(
    modality: str,
    namespace: str,
    sparql_exec: Callable[[str], Any],
    building_id: Optional[str] = None,
) -> Optional[int]:
    """How many sensors of this modality the building really has; None if unknown.

    None means "could not check" and must be treated as *do not intervene* — a
    guard that cannot verify has no business rewriting an answer.
    """
    classes = modality_classes(modality, building_id)
    if not classes:
        return None
    try:
        res = await sparql_exec(_count_query(classes, namespace))
        bindings = (res or {}).get("results", {}).get("bindings", [])
        if not bindings:
            return None
        return int(float(bindings[0]["n"]["value"]))
    except Exception as exc:  # pragma: no cover - live wiring
        logger.warning(f"[absence_guard] count failed for {modality}: {exc}")
        return None


def correction_text(modality: str, count: int, original: str) -> str:
    """Replace a false absence claim without inventing a reason for the refusal.

    The answer was declining; we do not know from here WHY it should decline
    (policy, volume, resolution), and guessing would swap one false statement for
    another. So state only what is verifiable — the building does sense this —
    and say the limitation is not a sensing one.
    """
    return (
        f"I can't complete that request as asked.\n\n"
        f"To be accurate about one thing: this building **does** have "
        f"{count} {modality} sensor(s) — the limitation isn't a lack of sensing. "
        f"Try narrowing the request (fewer spaces, a coarser interval, or a "
        f"specific room) and I'll answer from the building's own data."
    )


async def guard_answer(
    text: str,
    namespace: str,
    sparql_exec: Callable[[str], Any],
    building_id: Optional[str] = None,
) -> Tuple[str, Optional[Dict[str, Any]]]:
    """Return (possibly corrected answer, violation record or None)."""
    modality = detect_absence_claim(text)
    if not modality:
        return text, None
    count = await count_sensors(modality, namespace, sparql_exec, building_id)
    if not count:  # 0 = the claim is TRUE; None = unverifiable. Neither intervenes.
        return text, None
    logger.warning(
        f"[absence_guard] answer claimed no {modality} sensors, graph has {count} — corrected"
    )
    return correction_text(modality, count, text), {
        "modality": modality,
        "graph_count": count,
        "original": text[:300],
    }
