# -*- coding: utf-8 -*-
"""'Is the parking free or is there a fee?' is answered from the record, or says the field is empty.

WHAT WENT WRONG
---------------
    "Is the parking free or is there a fee?"
      -> a passage from the Transport Parking document: train and bus directions.

The building records a ground-level parking area with six charging stations and NO tariff. The
question asks about an ATTRIBUTE of a kind of place -- a fee, opening hours, a capacity -- and the
lane that took it looked for prose that mentioned parking and found directions. An attribute of a
thing is a field on the thing's record. Either the field is there, and it answers; or it is not, and
the honest answer names what IS recorded and says the field is not.

"Not recorded" and "free" are different facts. An amenity with no fee field is not a free amenity, so
this never turns an empty field into "it is free" or "it is not free".

WHAT THIS DOES
--------------
Reads the amenity instances and their classes from the graph, picks the kind the question names (by
the words of the class name: ParkingArea -> "parking"), and reads the attribute the question asks
for from that kind's records. It answers only when the question is ABOUT that attribute of that kind
and says nothing else; a question with any other content is left to its own lane.

BUILDING-AGNOSTIC
-----------------
Kinds are the ontology's own `ontosage:Amenity` subclasses. Nothing here names a building, a floor
or a kind. A "free-space count" is a live measurement and is deliberately NOT an attribute: "are there
free spaces available now" is not this module's question.
"""

from __future__ import annotations

import re
import time
from dataclasses import dataclass, field
from typing import Any, Awaitable, Callable, Dict, FrozenSet, List, Optional, Sequence, Tuple

from orchestrator.services.room_type_lookup import _stem
from shared.utils import get_logger

logger = get_logger(__name__)

SparqlExec = Callable[[str], Awaitable[Dict[str, Any]]]

_ONTO = "http://ontosage.org/capabilities#"

#: Amenity instances with the classes they are typed with and the attribute fields this module reads.
#: A class the reasoner adds (Capability, Amenity) names no kind and is dropped in Python.
_QUERY = f"""
PREFIX o: <{_ONTO}>
PREFIX rdfs: <http://www.w3.org/2000/01/rdf-schema#>
SELECT ?a ?l ?cls ?cl ?ans ?hours ?fee WHERE {{
  ?a a o:Amenity ; a ?cls .
  FILTER(STRSTARTS(STR(?cls), "{_ONTO}") && ?cls != o:Amenity && ?cls != o:Capability)
  OPTIONAL {{ ?a rdfs:label ?l }}
  OPTIONAL {{ ?cls rdfs:label ?cl }}
  OPTIONAL {{ ?a o:answerText ?ans }}
  OPTIONAL {{ ?a o:openingHours ?hours }}
  OPTIONAL {{ ?a o:usageFee ?fee }}
}}
"""

#: Classes that name no kind of thing.
_GENERIC_CLASSES = frozenset(
    {
        "Capability",
        "Amenity",
        "KnowledgeTopic",
        "InformationTopic",
        "Policy",
        "Procedure",
        "Facility",
    }
)

#: Words of a class name that say "a place of some sort" and so cannot identify the kind by
#: themselves: "Parking area" is asked about as "the parking".
_KIND_FILLER = frozenset({"facility", "point", "area", "room", "space", "feature", "service"})


@dataclass(frozen=True)
class Attribute:
    """One thing a question can ask of an amenity, and the record field that answers it."""

    key: str
    pattern: "re.Pattern[str]"
    record_field: str
    #: How to say the field is empty: "it does not record ___".
    absent: str
    #: How to introduce a recorded value.
    present: str


#: Deliberately explicit. Bare "free" is NOT here: "are there free parking spaces available now" asks
#: about availability, which is a live measurement and somebody else's question.
ATTRIBUTES: Tuple[Attribute, ...] = (
    Attribute(
        "fee",
        re.compile(
            r"\bfees?\b|\bcharg(?:e|es|ed|ing)\b(?!\s+(?:point|station|bay))|\bcosts?\b|\bprices?\b"
            r"|\btariffs?\b|\bhow\s+much\b|\bfree\s+of\s+charge\b|\bpay(?:ing|ment)?\b|\bpaid\b",
            re.IGNORECASE,
        ),
        "fee",
        "whether there is a fee",
        "The recorded charge is",
    ),
    Attribute(
        "hours",
        re.compile(
            r"\bopening\s+(?:hours|times)\b|\bopen(?:ing)?\s+hours\b|\bhours\s+of\s+(?:opening|operation)\b"
            r"|\bclos(?:e|es|ing)\s+time\b|\bwhen\s+(?:is|does)\b.{0,30}\bopen\b|\bwhat\s+time\b.{0,30}\b(?:open|clos)\w*",
            re.IGNORECASE,
        ),
        "hours",
        "its opening hours",
        "Recorded opening hours:",
    ),
    Attribute(
        "capacity",
        re.compile(r"\bcapacity\b", re.IGNORECASE),
        "capacity",
        "its capacity",
        "Recorded capacity:",
    ),
)

#: Words that frame a question without adding content.
_FRAME = frozenset(
    "a an the is are was were be there any some this that these those in on at of for to from by with "
    "i me my we our you your it its do does did can could would will please what which who how when where "
    "or and if whether there's have has having got available building site here tell about kind "
    "there's information info details detail s free use using get".split()
)
#: Compared after stemming, as the question's words are: "does" becomes "doe" and would otherwise
#: be read as content.
_FRAME = _FRAME | frozenset(_stem(w) for w in _FRAME)


def _split_camel(name: str) -> List[str]:
    return [w.lower() for w in re.findall(r"[A-Z][a-z0-9]*|[a-z0-9]+", name)]


def class_words(local_name: str) -> FrozenSet[str]:
    """The words that identify a kind: 'ParkingArea' -> {'parking'}; 'DrinkingWater' -> both."""
    words = [_stem(w) for w in _split_camel(local_name)]
    kept = [w for w in words if w not in _KIND_FILLER]
    return frozenset(kept or words)


@dataclass
class Kind:
    """One amenity kind and its instances' fields."""

    local: str
    label: str
    words: FrozenSet[str]
    instances: Dict[str, Dict[str, str]] = field(default_factory=dict)


def parse_kinds(bindings: Sequence[Dict[str, Any]]) -> List[Kind]:
    """Group the query rows into kinds; instances keyed by IRI so a repeated row is one instance."""
    kinds: Dict[str, Kind] = {}
    for b in bindings:
        cls = b.get("cls", {}).get("value", "")
        local = cls.rsplit("#", 1)[-1]
        iri = b.get("a", {}).get("value", "")
        if not local or not iri or local in _GENERIC_CLASSES:
            continue
        kind = kinds.setdefault(
            local,
            Kind(
                local,
                b.get("cl", {}).get("value", "") or " ".join(_split_camel(local)),
                class_words(local),
            ),
        )
        inst = kind.instances.setdefault(iri, {})
        for key, col in (("label", "l"), ("answer", "ans"), ("hours", "hours"), ("fee", "fee")):
            value = b.get(col, {}).get("value", "").strip()
            if value and not inst.get(key):
                inst[key] = value
    return [k for k in kinds.values() if k.instances and k.words]


def _tokens(text: str) -> List[str]:
    return [_stem(w) for w in re.findall(r"[a-z0-9]+", (text or "").lower())]


def detect(question: str, kinds: Sequence[Kind]) -> Optional[Tuple[Kind, List[Attribute]]]:
    """The kind and attributes the question is ABOUT; None when it is about anything more."""
    q = question or ""
    asked = [a for a in ATTRIBUTES if a.pattern.search(q)]
    if not asked:
        return None
    stripped = q
    for a in asked:
        stripped = a.pattern.sub(" ", stripped)
    words = _tokens(stripped)
    matches = [k for k in kinds if k.words <= set(words)]
    if not matches:
        return None
    widest = max(len(k.words) for k in matches)
    top = [k for k in matches if len(k.words) == widest]
    if len(top) != 1:
        return None
    kind = top[0]
    covered = set(kind.words) | _FRAME
    leftover = [w for w in words if w not in covered and not w.isdigit()]
    return (kind, asked) if not leftover else None


def _first_sentence(text: str) -> str:
    return re.split(r"(?<=[.!?])\s", text.strip(), maxsplit=1)[0].rstrip(".")


def _describe(kind: Kind) -> str:
    """What the building records of this kind, in its own words when there is exactly one."""
    if len(kind.instances) == 1:
        only = next(iter(kind.instances.values()))
        if only.get("answer"):
            sentence = _first_sentence(only["answer"])
            if sentence.lower().startswith(("the building records", "there is", "there are")):
                return sentence
            return f"The building records: {sentence}"
        if only.get("label"):
            return f"The building records {only['label']}"
    return f"The building records {kind.label.lower()} locations"


def compose(kind: Kind, asked: Sequence[Attribute]) -> str:
    """The answer: the recorded values, and for each empty field, that it is not recorded."""
    recorded: List[str] = []
    missing: List[str] = []
    for attr in asked:
        values = []
        for inst in kind.instances.values():
            v = inst.get(attr.record_field)
            if v and v not in [x for _l, x in values]:
                values.append((inst.get("label", ""), v))
        if not values:
            missing.append(attr.absent)
        elif len(values) == 1 or len({v for _l, v in values}) == 1:
            recorded.append(f"{attr.present} {values[0][1]}.")
        else:
            recorded.append(
                attr.present + " " + "; ".join(f"{l or 'one'}: {v}" for l, v in values) + "."
            )
    parts: List[str] = []
    if missing:
        parts.append(f"**{_describe(kind)}; it does not record {_and(missing)}.**")
    else:
        parts.append(f"**{_describe(kind)}.**")
    parts.extend(recorded)
    return "\n\n".join(parts)


def _and(items: Sequence[str]) -> str:
    items = list(items)
    return items[0] if len(items) == 1 else ", ".join(items[:-1]) + " or " + items[-1]


async def answer(question: str, sparql_exec: SparqlExec) -> Optional[str]:
    """The attribute answer, or None when the question is not an attribute of a known kind."""
    if not any(a.pattern.search(question or "") for a in ATTRIBUTES):
        return None
    try:
        data = await sparql_exec(_QUERY)
    except Exception as exc:
        logger.warning(f"[amenity_attribute] fetch failed: {exc}")
        return None
    kinds = parse_kinds((data or {}).get("results", {}).get("bindings", []))
    hit = detect(question, kinds)
    if hit is None:
        return None
    return compose(*hit)


_TTL_S = 300.0
_RETRY_S = 60.0
_cache: Dict[str, Any] = {"at": 0.0, "kinds": None, "retry_at": 0.0}


async def answer_live(question: str, building_name: str) -> Optional[Dict[str, Any]]:
    """The capability-lane result for an attribute question against the live graph, or None."""
    if not any(a.pattern.search(question or "") for a in ATTRIBUTES):
        return None
    now = time.monotonic()
    if now < _cache["retry_at"]:
        return None
    try:
        from orchestrator.services.deliberation.live import sparql_exec

        if _cache["kinds"] is None or now - _cache["at"] > _TTL_S:
            data = await sparql_exec(_QUERY)
            kinds = parse_kinds((data or {}).get("results", {}).get("bindings", []))
            if not kinds:
                _cache["retry_at"] = now + _RETRY_S
                return None
            _cache["kinds"], _cache["at"] = kinds, now
        hit = detect(question, _cache["kinds"])
    except Exception as exc:
        _cache["retry_at"] = now + _RETRY_S
        logger.debug(f"[amenity_attribute] unavailable: {exc}")
        return None
    if hit is None:
        return None
    return {
        "success": True,
        "response": compose(*hit) + "\n\n*Answered live from the building's own records.*",
        "provenance": "amenity_record",
        "building_name": building_name,
    }
