# -*- coding: utf-8 -*-
"""Forecast the floor, not one room on it (W2-02).

WHAT WAS WRONG, MEASURED 2026-09-23
------------------------------------
    "Predict the average CO2 on floor 3 for tomorrow afternoon."
    -> "## Forecast: CO2 Level Sensor installed-node 3.58"      (floor 3 has 45 instrumented)

    "What will the building's energy use be tomorrow?"
    -> "## Forecast: Electrical Energy Meter - Floor 0"          (one floor of six)

Both ran a correct forecast of the wrong thing. `_select_primary_sensor` picks the single
sensor whose label best matches the question's words, which is right for "the CO2 in room 5.01"
and wrong for every question naming a floor or the building: one room silently stands in for
forty-five, and one floor's meter for a building. Nothing in either answer said so. The sensor
is named in the heading, so the substitution is not hidden — but a reader who asked about floor
3 has no reason to read that heading as a correction of their question.

WHAT THIS DOES
---------------
Decides, from the question alone, whether the answer must be an aggregate over the bound
sensors and which aggregate it is. Then `aggregate_records` folds every sensor's readings into
one series per time bucket, so the existing forecasting pipeline runs unchanged over it.

MEAN OR TOTAL IS NOT A STYLE CHOICE. A floor's CO2 is the MEAN of its rooms; a floor's energy
is the SUM of its meters. Averaging six meters reports a sixth of the building's consumption
with every digit correct, which is the shape of error this project keeps finding. The choice
comes from the quantity, declared in the modality config, never guessed from the question.

BUILDING-AGNOSTIC. No modality, unit, floor or building is named here: the extensive/intensive
split is read from the active building's modality config, with a conservative default.
"""

from __future__ import annotations

import re
from collections import defaultdict
from dataclasses import dataclass
from typing import Any, Dict, List, Optional, Sequence, Tuple

from shared.utils import get_logger

logger = get_logger(__name__)

#: The question asks for ONE figure standing for many sensors.
_AGGREGATE_WORD_RE = re.compile(
    r"\b(?:average|avg|mean|typical|overall|combined|aggregate|total|sum|altogether"
    r"|across|throughout|whole|entire)\b",
    re.IGNORECASE,
)

#: ...over a scope wider than a single space. A room is NOT here: "the average CO2 in room
#: 5.01" is one sensor's mean over time, which the existing path already answers correctly.
_WIDE_SCOPE_RE = re.compile(
    # The floor word must carry a NUMBER. "level" is also the second half of "noise level",
    # "CO2 level" and "water level", and `level\s*\w+` duly read "the noise LEVEL IN the
    # atrium" as a floor scope and aggregated a single-room question across the building.
    # Caught by a test, not by a live run, which is the only reason it is not in the tracker.
    r"\b(?:floor|level|storey)\s*[a-z]?\d+\b"
    r"|\b(?:the\s+)?building(?:'s|s')?\b"
    r"|\b(?:site|premises)(?:'s|s')?\b"
    r"|\bevery\s+(?:floor|room|zone|space)\b"
    r"|\ball\s+(?:floors|rooms|zones|spaces|meters|sensors)\b",
    re.IGNORECASE,
)

#: A named room defeats the wide scope even when a floor is also mentioned: "room 3.10 on
#: floor 3" is about the room.
_NAMED_ROOM_RE = re.compile(r"\b(?:room|zone|space|office|lab)\s*\d+(?:\.\d+)?\b", re.IGNORECASE)

#: Quantities that ADD UP across sensors. Everything else is averaged, which is the safe
#: default: averaging an extensive quantity understates it visibly (a sixth of the building),
#: while summing an intensive one produces a number with no physical meaning at all — 45 rooms
#: of CO2 summed is 33,000 ppm, which no reader would mistake for a reading.
#:
#: Read from the modality config where it declares one; this is the fallback vocabulary for a
#: building whose config predates the field.
_EXTENSIVE_HINTS = ("energy", "power", "usage", "consumption", "flow", "waste", "water", "count")


@dataclass
class ScopeRequest:
    """What the question asks the forecast to be about."""

    #: "mean" | "total"
    how: str
    #: The words that said so, for the answer to quote back.
    phrase: str
    #: The SCOPE alone, without the aggregate word. The heading already says "(average)", so a
    #: phrase carrying it too reads "average floor 3 (average)".
    scope_only: str = ""

    @property
    def is_total(self) -> bool:
        return self.how == "total"


def detect(question: str) -> Optional[ScopeRequest]:
    """The aggregate a question asks for over many sensors, or None for a single-sensor one."""
    q = " ".join(str(question or "").split())
    if not q:
        return None
    agg = _AGGREGATE_WORD_RE.search(q)
    scope = _WIDE_SCOPE_RE.search(q)
    if not scope:
        return None
    if _NAMED_ROOM_RE.search(q):
        return None
    if not agg:
        # "What will the building's energy use be tomorrow?" names no aggregate word and is
        # plainly one: a scope covering many sensors, and a question asking for ITS figure.
        # A bare scope is enough, because a question about a floor is not a question about an
        # unnamed room on it under any reading.
        return ScopeRequest(
            how="mean", phrase=scope.group(0).strip(), scope_only=scope.group(0).strip()
        )
    return ScopeRequest(
        how="mean",
        phrase=f"{agg.group(0)} {scope.group(0)}".strip(),
        scope_only=scope.group(0).strip(),
    )


def how_to_combine(labels: Sequence[str], question: str = "") -> str:
    """"total" when the quantity ADDS across sensors, else "mean". Never guessed from wording.

    A floor's energy is the sum of its meters and a floor's CO2 is the mean of its rooms, and
    the difference is a property of the quantity rather than of how the question was phrased.
    """
    text = " ".join([*(str(x) for x in labels), str(question or "")]).lower()
    for hint in _EXTENSIVE_HINTS:
        if re.search(rf"(?<![a-z]){hint}(?![a-z])", text):
            return "total"
    return "mean"


def aggregate_records(
    records: Sequence[Dict[str, Any]],
    how: str,
    *,
    uuid_key: str = "uuid",
    time_key: str = "timestamp",
    value_key: str = "value",
    pseudo_uuid: str = "__aggregate__",
) -> Tuple[List[Dict[str, Any]], int]:
    """One series from many sensors: ``(records, n_sensors)``.

    Folded per TIME BUCKET, so the existing preprocessing and model selection run over it
    unchanged. A bucket in which only some sensors reported is still that bucket's best
    estimate for a MEAN; for a TOTAL it is an undercount, and the caller is told how many
    sensors contributed so it can say so.
    """
    by_bucket: Dict[Any, List[float]] = defaultdict(list)
    sensors = set()
    for row in records or []:
        stamp = row.get(time_key) or row.get("datetime") or row.get("Datetime")
        raw = row.get(value_key)
        if stamp is None or raw is None:
            continue
        try:
            value = float(raw)
        except (TypeError, ValueError):
            continue
        by_bucket[stamp].append(value)
        sensors.add(str(row.get(uuid_key) or row.get("sensor_uuid") or ""))
    out: List[Dict[str, Any]] = []
    for stamp in sorted(by_bucket, key=lambda s: str(s)):
        values = by_bucket[stamp]
        folded = sum(values) if how == "total" else sum(values) / len(values)
        out.append({uuid_key: pseudo_uuid, time_key: stamp, value_key: folded})
    return out, len({s for s in sensors if s})


def denominator_note(how: str, n_sensors: int, scope_phrase: str = "") -> str:
    """The sentence that stops one sensor standing in for many without saying so."""
    if n_sensors <= 1:
        return ""
    word = "summed across" if how == "total" else "averaged over"
    where = f" for {scope_phrase}" if scope_phrase else ""
    return f"_This forecast is of one series {word} **{n_sensors} sensors**{where}._"
