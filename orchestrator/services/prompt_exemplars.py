# -*- coding: utf-8 -*-
"""Real identifiers from the ACTIVE building, for the SPARQL prompt to teach from.

WHY THIS EXISTS
---------------
The SPARQL prompt taught the model one building's room grammar, in six places:

    - "room 5.01" -> bldg:Room_5.01 or filter CONTAINS "5.01"
    - e.g. bldg:CO2_Level_Sensor_5.08
    - FILTER(CONTAINS(STR(?sensor), "5.08") || CONTAINS(STR(?label), "5.08"))

`5.01` is not a placeholder. It is a room in one building, written in that building's
`N.NN` numbering, and a model shown three examples of it will reach for that shape when
asked about a building that numbers rooms `RM-204` or names them `Atrium`. Worse, the
guidance is CORRECT for bldg1, so nothing about the resulting answers looks wrong until
somebody checks whether the room exists.

An exemplar has to be an exemplar OF SOMETHING. Deleting these and leaving the instruction
abstract would make the prompt worse -- the CONTAINS-filter advice is genuinely useful and
hard to state without an example. So the examples are read from the building itself.

WHAT IT GUARANTEES
------------------
* Every identifier it returns EXISTS in the active graph, so the prompt can never teach a
  referent the building does not have.
* It fails to empty, never to a default. A building whose graph is not loaded yet gets a
  prompt with the example lines omitted, which is worse guidance and not wrong guidance --
  and a hardcoded fallback here would reintroduce exactly the defect.
* One query, cached per building for the process lifetime. The graph's room names do not
  change between requests, and the prompt is built on every turn.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Callable, Dict, Optional

from shared.utils import get_logger

logger = get_logger(__name__)


@dataclass(frozen=True)
class Exemplars:
    """One real room and one real sensor, or empty."""

    room_local: str = ""
    room_identifier: str = ""
    sensor_local: str = ""

    @property
    def usable(self) -> bool:
        return bool(self.room_local and self.sensor_local)


#: A room with a label, and a sensor located in it. Asked together so the two examples are
#: CONSISTENT -- teaching "room X" and "sensor in room Y" would model a relationship the
#: building does not have.
_QUERY = """
PREFIX brick: <https://brickschema.org/schema/Brick#>
PREFIX rdfs:  <http://www.w3.org/2000/01/rdf-schema#>
SELECT ?room ?sensor WHERE {
  ?room a brick:Room .
  ?sensor a ?scls . ?scls rdfs:subClassOf* brick:Sensor .
  { ?sensor brick:hasLocation ?room } UNION { ?room brick:hasPart ?sensor }
  FILTER(STRSTARTS(STR(?room), "%(ns)s"))
} LIMIT 1
"""

_CACHE: Dict[str, Exemplars] = {}


def _local(iri: str) -> str:
    return str(iri).rsplit("#", 1)[-1].rsplit("/", 1)[-1]


def _identifier(local: str) -> str:
    """The part a person would say.

    `Room_5.01` -> `5.01`; `RM-204` -> `RM-204`; `Atrium` -> `Atrium`. Derived by stripping
    a leading type word, NOT by matching a number format -- the format is the thing that
    must not be assumed.
    """
    words = ("room", "space", "zone", "office", "lab")
    text = local.replace("_", " ").replace("-", " ").strip()
    parts = [p for p in text.split() if p]
    if len(parts) > 1 and parts[0].lower() in words:
        return " ".join(parts[1:])
    # `Room0.01` -- a type word run straight into an identifier, with no separator to split
    # on. Stripped only when what FOLLOWS starts with a digit, so `Roomy Suite` and
    # `Laboratory` keep their names.
    low = local.lower()
    for w in words:
        if low.startswith(w) and len(local) > len(w) and local[len(w)].isdigit():
            return local[len(w) :]
    return local


async def exemplars_for(building_id: str, namespace: str, sparql_exec: Callable) -> Exemplars:
    """One real room and sensor from this building, cached. Empty when none can be read."""
    key = f"{building_id}|{namespace}"
    hit = _CACHE.get(key)
    if hit is not None:
        return hit

    found = Exemplars()
    if namespace:
        try:
            res = await sparql_exec(_QUERY % {"ns": namespace})
            rows = (res or {}).get("results", {}).get("bindings", [])
            if rows:
                room = _local(rows[0].get("room", {}).get("value", ""))
                sensor = _local(rows[0].get("sensor", {}).get("value", ""))
                if room and sensor:
                    found = Exemplars(
                        room_local=room, room_identifier=_identifier(room), sensor_local=sensor
                    )
        except Exception as exc:
            # Not fatal and not silent. An empty result means the prompt loses two example
            # lines; a wrong result would mean the prompt teaches a room that does not exist.
            logger.warning(f"[prompt_exemplars] could not read an exemplar: {exc}")

    _CACHE[key] = found
    if not found.usable:
        logger.info(
            "[prompt_exemplars] no room-with-sensor found; the SPARQL prompt will omit its "
            "worked examples rather than invent one"
        )
    return found


def clear_cache(building_id: Optional[str] = None) -> None:
    """Drop cached exemplars — after a swap, or a re-ingest that renamed rooms."""
    if building_id is None:
        _CACHE.clear()
        return
    for k in [k for k in _CACHE if k.startswith(f"{building_id}|")]:
        _CACHE.pop(k, None)
