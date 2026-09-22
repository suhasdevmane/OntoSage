# -*- coding: utf-8 -*-
"""Deterministic sensor binding: (measured quantity, named place) -> the series to read.

2D-05 (BUG-825, BUG-826, BUG-831, BUG-809). Six unscripted questions of the same shape --
"how stuffy is Room 1.06", "which rooms are occupied", "the CO2 in the atrium", "what will
the temperature be tomorrow in Room 2.01", "the temperature of the heat pump water loop" --
ended in four different wrong answers, and the cause was one and the same: the sensor(s) that
answer a QUANTITY at a PLACE were left to whatever the retrieval happened to return.

Measured against the code, not assumed. With no entity IRI from the dialogue stage, the
"list all rooms" template of `SPARQLAgent._template_sparql` claims any question that contains
the word "room" or "rooms", and it returns `?space (COUNT(?sensor) AS ?sensor_count)` -- rows
with NO timeseries id, so the answer narrates "the building only records how many sensors are
installed in each space" (B04, G04). With an entity IRI the "sensors located in X" template
returns EVERY sensor in the room, and a forecast then picks one by a loose keyword match on
the word "room" (B38), which is why the same question forecast in one run and refused in the
next. "The atrium" matched no space at all and the fallback answered from a floor's zone
sensor (G09).

WHAT THIS DOES, in the order it decides
---------------------------------------
1. The quantity: the classes the HBCO concept resolver already chose for the question, else
   the modality catalogue's own words (`absence_guard` aliases). No quantity, no binding: an
   ask that names nothing measurable is left to the path that handles those.
2. The scope: a dotted room / zone id, a named space ("the atrium"), or a piece of plant
   ("the heat pump"), resolved against the LIVE graph by id or label -- never by a literal.
   A floor, several places, or a phrase the graph cannot place is left to the existing paths.
3. The sensors: the place's OWN sensors of that quantity. Only when it has none does a zone
   that provably relates to the room stand in, and then the binding says so (`basis="zone"`),
   the spatial-adequacy grade turns to proxy, and the answer carries its "Spatial basis" line.
4. If the place has no such sensor at all the result is a TYPED ABSENCE -- the same outcome
   the floor-scoped resolver produces -- naming what the place does record. It is never
   widened to the building: a wrong-subject answer is worse than an honest decline.

Building-agnostic. Everything about a building (classes, label discriminators, namespaces)
comes from its own config and graph; the only vocabulary here is English.
"""

from __future__ import annotations

import asyncio
import re
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from typing import (
    Any,
    Awaitable,
    Callable,
    Dict,
    Iterable,
    List,
    Optional,
    Sequence,
    Set,
    Tuple,
)

from orchestrator.services.deliberation.coverage_audit import load_modalities
from shared.utils import get_logger

logger = get_logger(__name__)

#: An injected async callable: SPARQL text -> standard SPARQL-results JSON. Production passes
#: `deliberation.live.sparql_exec`, which does NOT run `_fallback_pattern_search` on an empty
#: result -- for a binder an empty result is the answer, not a miss to be papered over.
RunQuery = Callable[[str], Awaitable[Dict[str, Any]]]

STATUS_BOUND = "bound"
STATUS_ABSENT = "absent"
STATUS_NOT_APPLICABLE = "not_applicable"

BASIS_OWN = "own"
BASIS_ZONE = "zone"
BASIS_EQUIPMENT = "equipment"
BASIS_POPULATION = "population"

SCOPE_SPACE = "space"
SCOPE_EQUIPMENT = "equipment"
SCOPE_BUILDING = "building"

#: Intents whose answer is a reading of a measured quantity. The intents that ask ABOUT sensors
#: (metadata, discovery) are left alone: "how many sensors are in each room" is exactly the
#: question the sensor-count template answers correctly.
BINDER_INTENTS = frozenset({"sensor_data", "analytics", "trend", "anomaly", "compliance"})

#: Ceiling on a building-wide population: the sql lane's own per-store sensor cap. Above it the
#: lane would read a sorted SLICE of the building and say so; binding a population that cannot
#: be read whole would only move that truncation upstream, where nothing announces it.
MAX_POPULATION = 600
#: Ceiling on the sensors of ONE place; a room with more is not a room question.
MAX_PLACE_ROWS = 3000
#: One graph lookup may not hold a turn. On timeout the binder steps aside (fails OPEN): a
#: lookup that did not finish must never become a claim of absence.
QUERY_TIMEOUT_S = 10.0

_PREFIXES = (
    "PREFIX rdf: <http://www.w3.org/1999/02/22-rdf-syntax-ns#>\n"
    "PREFIX rdfs: <http://www.w3.org/2000/01/rdf-schema#>\n"
    "PREFIX brick: <https://brickschema.org/schema/Brick#>\n"
    "PREFIX ref: <https://brickschema.org/schema/Brick/ref#>\n"
    "PREFIX ontosage: <http://ontosage.org/capabilities#>\n"
)

#: IRIs and tokens reach a query only after these checks (values come from the graph or from
#: a token the resolver already validated; a stray quote would still break the query).
_SAFE_IRI_RE = re.compile(r"^[A-Za-z][A-Za-z0-9+.\-]*:[^\s<>\"{}|\\^`]+$")
_SAFE_LOCAL_RE = re.compile(r"^[A-Za-z0-9_.\-]{1,80}$")


def _esc(text: str) -> str:
    """Escape a value for a SPARQL string literal."""
    return str(text).replace("\\", "\\\\").replace('"', '\\"')


def _local(iri: str) -> str:
    """The local name of an IRI or CURIE ('brick:CO2_Sensor' -> 'CO2_Sensor')."""
    text = str(iri or "")
    for sep in ("#", "/", ":"):
        if sep in text:
            text = text.rsplit(sep, 1)[-1]
    return text


# ── data ─────────────────────────────────────────────────────────────────────────────


@dataclass(frozen=True)
class QuantitySpec:
    """One measured quantity: Brick/OCBV class local names plus the modality's label filters."""

    name: str
    label: str
    classes: Tuple[str, ...]
    label_contains: Tuple[str, ...] = ()
    label_excludes: Tuple[str, ...] = ()
    #: True when the building's modality catalogue names this quantity, i.e. a space is EXPECTED to
    #: be able to measure it. Only such a quantity can support "this place has no such sensor":
    #: an arbitrary concept class ("fire alarm", "lift") missing from a room is not an absence.
    catalogued: bool = True

    def matches(self, class_locals: Iterable[str], text: str) -> bool:
        """True when a sensor with these classes and this name-text is this quantity."""
        wanted = {c.lower() for c in self.classes}
        if not wanted & {str(c).lower() for c in class_locals}:
            return False
        hay = (text or "").lower()
        if self.label_excludes and any(s.lower() in hay for s in self.label_excludes):
            return False
        if self.label_contains:
            return any(s.lower() in hay for s in self.label_contains)
        return True


@dataclass
class ScopeAsk:
    """What the question names as its place, before the graph has been asked."""

    kind: str = "none"  # none | space | equipment | floor | other
    id_token: str = ""  # a dotted id: "1.06"
    head: str = ""  # the word before an id ("room", "zone") or the equipment noun
    words: str = ""  # a named place ("atrium", "server room") or equipment ("heat pump 1")
    phrase: str = ""  # what to echo back to the reader
    multiple: bool = False  # more than one dotted id: a comparison, not this module's job
    generic: bool = False  # found by a determiner phrase, not by a known space noun


@dataclass
class ScopeHit:
    """One place (or piece of equipment) the graph holds that matches the ask."""

    iri: str
    label: str
    is_zone: bool = False
    is_room: bool = False


@dataclass
class BoundSensor:
    """A sensor selected for the answer, with the routing the SQL lane needs."""

    iri: str
    label: str
    uuid: str
    storage: str = ""
    type_iri: str = ""
    location: str = ""
    simulated: bool = False
    quantity: str = ""


@dataclass
class Binding:
    """The outcome of binding one question."""

    status: str = STATUS_NOT_APPLICABLE
    reason: str = ""
    quantity_label: str = ""
    classes: Tuple[str, ...] = ()
    scope_kind: str = ""
    scope_iri: str = ""
    scope_label: str = ""
    alias: str = ""
    basis: str = ""
    zone_label: str = ""
    sensors: List[BoundSensor] = field(default_factory=list)
    holdings: List[str] = field(default_factory=list)
    candidates: List[str] = field(default_factory=list)
    queries: List[str] = field(default_factory=list)

    @property
    def display_scope(self) -> str:
        """The place as the reader named it plus the building's id: "the atrium (Room 1.04)"."""
        name = self.scope_label or "that place"
        if self.alias and self.alias.lower() not in name.lower():
            return f"the {self.alias} ({name})"
        return name

    @property
    def is_bound(self) -> bool:
        """True when at least one sensor was selected."""
        return self.status == STATUS_BOUND and bool(self.sensors)

    def envelope(self) -> Dict[str, Any]:
        """The selection as a SPARQL-results document, so every reader downstream is unchanged."""
        variables = ["sensor", "label", "type", "uuid", "storage", "location"]
        rows: List[Dict[str, Dict[str, str]]] = []
        for s in self.sensors:
            row = {
                "sensor": {"type": "uri", "value": s.iri},
                "label": {"type": "literal", "value": s.label or _local(s.iri)},
                "uuid": {"type": "literal", "value": s.uuid},
            }
            if s.type_iri:
                row["type"] = {"type": "uri", "value": s.type_iri}
            if s.storage:
                row["storage"] = {"type": "uri", "value": s.storage}
            if s.location:
                row["location"] = {"type": "uri", "value": s.location}
            rows.append(row)
        return {"head": {"vars": variables}, "results": {"bindings": rows}}

    def to_record(self) -> Dict[str, Any]:
        """A small, serialisable account of what was decided, for the bus and the logs."""
        return {
            "status": self.status,
            "reason": self.reason,
            "quantity": self.quantity_label,
            "scope_kind": self.scope_kind,
            "scope": self.scope_label,
            "scope_iri": self.scope_iri,
            "basis": self.basis,
            "zone": self.zone_label,
            "sensors": [s.uuid for s in self.sensors],
            "holdings": list(self.holdings),
        }

    def summary(self) -> str:
        """One factual line naming what was bound; never a claim about a reading."""
        names = ", ".join(s.label or _local(s.iri) for s in self.sensors[:6])
        more = f" and {len(self.sensors) - 6} more" if len(self.sensors) > 6 else ""
        where = f" for {self.display_scope}" if self.scope_label else ""
        note = ""
        if self.basis == BASIS_ZONE and self.zone_label:
            note = (
                f" The {self.quantity_label} reading for {self.display_scope} comes from "
                f"{self.zone_label}, the zone that covers it."
            )
        return f"{self.quantity_label} sensors{where}: {names}{more}.{note}"


# ── quantity ─────────────────────────────────────────────────────────────────────────

#: Lay words for quantities, KEYED BY THE MODALITY NAME the building's own catalogue declares.
#: The catalogue owns the classes; this only says which English words point at which entry.
#: Kept small on purpose: `absence_guard` already carries the wider alias table, which is
#: merged in below, and the HBCO concept resolver carries the lay-terms ("stuffy", "too warm").
_EXTRA_WORDS: Dict[str, Tuple[str, ...]] = {
    "occupancy": (
        "occupied",
        "people",
        "persons",
        "headcount",
        "head count",
        "occupants",
        "anyone",
        "anybody",
        "someone",
        "in use",
    ),
    "occupancy_status": (
        "occupied",
        "anyone",
        "anybody",
        "someone",
        "in use",
        "vacant",
        "presence",
    ),
    "humidity": ("humid", "damp"),
    "noise": ("noisy", "loud", "decibels", "decibel"),
    "illuminance": ("bright", "brightness", "daylight"),
    "pm25": ("dust", "particulates"),
    "co2": ("stuffy", "stale air"),
}

_ACRONYMS = {
    "co2": "CO2",
    "pm25": "PM2.5",
    "pm10": "PM10",
    "pm1": "PM1",
    "tvoc": "TVOC",
    "no2": "NO2",
    "cct": "CCT",
}

#: Questions ABOUT the sensors, not a reading from them. They are answered by the sensor
#: listing and the count templates, which are right for them.
_ABOUT_SENSORS_RE = re.compile(
    r"\bhow\s+many\s+(?:\w+\s+){0,3}?(?:sensors?|devices?|points?)\b"
    r"|\b(?:list|which|what)\s+(?:\w+\s+){0,3}?sensors?\s+(?:are|do|does|exist|is|were)\b"
    r"|\bwhat\s+sensors?\b",
    re.IGNORECASE,
)


def _modalities(building_id: Optional[str]) -> List[Any]:
    """The building's modality catalogue (config + overlay); empty when unreadable."""
    try:
        return list(load_modalities(building_id))
    except Exception as exc:  # the catalogue is optional; concepts still work without it
        logger.debug(f"[sensor_binder] modality catalogue unavailable: {exc}")
        return []


def _pretty_modality(name: str) -> str:
    """'co2' -> 'CO2', 'water_flow' -> 'water flow' — how a reader would say it."""
    words = str(name or "").split("_")
    return " ".join(_ACRONYMS.get(w.lower(), w.lower()) for w in words if w).strip()


def _modality_words(specs: Sequence[Any]) -> Dict[str, Tuple[str, ...]]:
    """{modality name: the words that point at it}: aliases + its own name + the extras."""
    try:
        from orchestrator.services.absence_guard import _MODALITY_ALIASES as aliases
    except Exception:  # pragma: no cover - the alias table is an import away
        aliases = {}
    out: Dict[str, Tuple[str, ...]] = {}
    for spec in specs:
        name = spec.name
        words = list(aliases.get(name, ())) + list(_EXTRA_WORDS.get(name, ()))
        pretty = _pretty_modality(name)
        if pretty and pretty not in words:
            words.append(pretty)
        out[name] = tuple(dict.fromkeys(w.lower() for w in words if w))
    return out


def _sibling_excludes(spec: Any, specs: Sequence[Any]) -> Tuple[str, ...]:
    """Label words of OTHER modalities that share a class with this one and split it by label.

    "occupancy" and "parking_free" are both Occupancy_Count_Sensor and are told apart only by
    the word "parking" in the label. Taking the class alone takes the whole superclass
    population (the absence guard once told a reader this building had 257 parking sensors).
    """
    mine = {c.lower() for c in spec.brick_classes}
    if spec.label_contains:
        return ()
    words: List[str] = []
    for other in specs:
        if other is spec or not other.label_contains:
            continue
        if mine & {c.lower() for c in other.brick_classes}:
            words.extend(other.label_contains)
    return tuple(dict.fromkeys(w.lower() for w in words))


def _spec_from_modality(spec: Any, specs: Sequence[Any]) -> QuantitySpec:
    return QuantitySpec(
        name=spec.name,
        label=_pretty_modality(spec.name),
        classes=tuple(spec.brick_classes),
        label_contains=tuple(spec.label_contains or ()),
        label_excludes=tuple(spec.label_excludes or ()) + _sibling_excludes(spec, specs),
    )


def detect_quantities(
    question: str,
    concepts: Optional[Sequence[Dict[str, Any]]] = None,
    building_id: Optional[str] = None,
) -> List[QuantitySpec]:
    """The measured quantities a question asks for, or [] when it asks for none.

    The classes the concept resolver chose come FIRST: it is the component whose job is to map
    "stuffy" to CO2, and a second opinion here would be a second definition of the same word.
    The catalogue's own words are the fallback for what the resolver has no lay-term for
    ("which rooms are occupied"). The catalogue is what turns a class set into the building's
    modality, so a concept's classes also inherit that modality's label discriminators.
    """
    if _ABOUT_SENSORS_RE.search(question or ""):
        return []
    specs = _modalities(building_id)
    found: List[QuantitySpec] = []

    for cm in concepts or []:
        if not isinstance(cm, dict):
            continue
        classes = tuple(dict.fromkeys(_local(c) for c in (cm.get("brick_classes") or []) if c))
        if not classes:
            continue
        home = next(
            (s for s in specs if {c.lower() for c in classes} & _lower(s.brick_classes)), None
        )
        label = _pretty_modality(home.name) if home else _pretty_class(classes[0])
        found.append(
            QuantitySpec(
                name=str(cm.get("concept_id") or label),
                label=label,
                classes=classes,
                label_excludes=_sibling_excludes(home, specs) if home else (),
                catalogued=home is not None,
            )
        )
    if found:
        return _dedupe_specs(found)

    q = (question or "").lower()
    words = _modality_words(specs)
    by_name = {s.name: s for s in specs}
    for name, ws in words.items():
        if any(re.search(r"(?<![a-z0-9])" + re.escape(w) + r"(?![a-z0-9])", q) for w in ws):
            found.append(_spec_from_modality(by_name[name], specs))
    return _dedupe_specs(found)


def _lower(items: Iterable[str]) -> Set[str]:
    return {str(i).lower() for i in items}


def _pretty_class(local: str) -> str:
    """'Occupancy_Count_Sensor' -> 'occupancy count'."""
    core = re.sub(r"_(Sensor|Status|Command|Setpoint)$", "", str(local or ""))
    return " ".join(
        w if any(c.isdigit() for c in w) else w.lower() for w in core.split("_")
    ).strip()


def _dedupe_specs(specs: List[QuantitySpec]) -> List[QuantitySpec]:
    """Drop a spec whose classes another spec already covers (one concept, two words)."""
    out: List[QuantitySpec] = []
    seen: List[Set[str]] = []
    for s in specs:
        cls = _lower(s.classes)
        if any(cls <= prior for prior in seen):
            continue
        seen.append(cls)
        out.append(s)
    return out


# ── scope ────────────────────────────────────────────────────────────────────────────

#: "room 1.06", "Zone5.01". The lookahead lets a sentence-final full stop follow the id
#: ("...in Room 1.06.") but not another digit group ("1.06.3") or a longer word.
_ID_HEAD_RE = re.compile(
    r"\b(zone|room|space|area)\s*(\d{1,2}\.\d{1,2}[A-Za-z]?)(?!\w|\.\d)", re.IGNORECASE
)
#: A question that names a SENSOR by its own id ("CO2_Level_Sensor_5.01", "...installed-node
#: 5.01"). The number in it is a device's, not a room's: reading it as a room would answer with
#: the room's sensors in place of the one that was asked for.
_SENSOR_NAMED_RE = re.compile(r"(?:sensor|point|meter)[_\s-]*\d|_sat_|installed[- ]node", re.I)
_BARE_ID_RE = re.compile(r"(?<![\d.])(\d{1,2}\.\d{1,2}[A-Za-z]?)(?!\w|\.\d)")
_FLOOR_ASK_RE = re.compile(
    r"\b(?:floor|level|storey)\s+\d{1,3}\b|\b\d{1,3}\s*(?:st|nd|rd|th)\s+floor\b", re.IGNORECASE
)

#: A place named by a determiner phrase: "in the server room", "at the reception desk".
_PLACE_PHRASE_RE = re.compile(
    r"\b(?:in|at|inside|within|around|near|of|for)\s+(?:the|this|that|our)\s+"
    r"([a-z][a-z'\- ]{1,32}?)"
    r"(?=\s+(?:right|now|today|tonight|currently|at|on|in|during|this|for|please|be|is|are|"
    r"will|would|and|or)\b|[?.!,;:]|$)",
    re.IGNORECASE,
)
#: Words that make a determiner phrase a TIME or a WHOLE, not a place inside the building.
_NOT_A_PLACE = frozenset(
    {
        "moment",
        "morning",
        "evening",
        "afternoon",
        "night",
        "day",
        "days",
        "week",
        "weeks",
        "weekend",
        "month",
        "months",
        "year",
        "years",
        "hour",
        "hours",
        "minute",
        "minutes",
        "today",
        "tomorrow",
        "yesterday",
        "time",
        "period",
        "past",
        "last",
        "next",
        "present",
        "current",
        "previous",
        "following",
        "meantime",
        "future",
        "coming",
        "upcoming",
        "same",
        "event",
        "order",
        "case",
        "long",
        "short",
        "whole",
        "entire",
        "building",
        "site",
        "campus",
        "premises",
        "estate",
        "world",
        "data",
        "system",
        "records",
        "record",
        "ontology",
        "model",
        "graph",
        "sensor",
        "sensors",
        "reading",
        "readings",
        "value",
        "values",
    }
)


def extract_scope_ask(question: str, entities: Optional[Sequence[str]] = None) -> ScopeAsk:
    """The place a question is about, by English structure alone; nothing is checked yet.

    Precedence: a dotted room/zone id (the strongest, and the only kind that can be a
    comparison), a named space or piece of equipment, a floor, then a determiner phrase. A floor
    beside a room id is context: the room is what the question is about.
    """
    q = question or ""
    if _SENSOR_NAMED_RE.search(q) or any(_SENSOR_NAMED_RE.search(str(e)) for e in entities or []):
        return ScopeAsk(kind="sensor", phrase="a named sensor")
    ids: Dict[str, str] = {}
    for m in _ID_HEAD_RE.finditer(q):
        ids.setdefault(m.group(2).lower(), m.group(1).lower())
    for ent in entities or []:
        # A bare number ("26.5", from "above 26.5 degrees") is a threshold, not a room.
        if not re.search(r"[A-Za-z]", str(ent)):
            continue
        m = _BARE_ID_RE.search(str(ent))
        if m and m.group(1).lower() not in ids:
            # An entity IRI carries the id but not always the word before it.
            head = "zone" if re.search(r"zone", str(ent), re.IGNORECASE) else "room"
            ids[m.group(1).lower()] = head
    if len(ids) > 1:
        return ScopeAsk(kind="space", multiple=True, phrase=", ".join(sorted(ids)))
    if len(ids) == 1:
        token, head = next(iter(ids.items()))
        return ScopeAsk(kind="space", id_token=token, head=head, phrase=f"{head} {token}")

    from orchestrator.services.referent_resolver import (
        KIND_EQUIPMENT,
        KIND_FLOOR,
        KIND_LOCATION,
        KIND_SPACE,
        detect_typed_referent,
    )

    typed = detect_typed_referent(q)
    if typed is not None:
        words = typed.token.replace("|", " ").strip()
        if typed.kind == KIND_SPACE:
            return ScopeAsk(kind="space", words=words, head=typed.head, phrase=typed.phrase)
        if typed.kind == KIND_EQUIPMENT:
            return ScopeAsk(kind="equipment", words=words, head=typed.head, phrase=typed.phrase)
        if typed.kind == KIND_FLOOR:
            return ScopeAsk(kind="floor", phrase=typed.phrase)
        if typed.kind == KIND_LOCATION:
            return ScopeAsk(kind="other", phrase=typed.phrase)
    if _FLOOR_ASK_RE.search(q):
        return ScopeAsk(kind="floor")

    for m in _PLACE_PHRASE_RE.finditer(q):
        phrase = m.group(1).strip().lower()
        tokens = [t for t in re.split(r"[\s\-]+", phrase) if t]
        if not tokens or tokens[0] in _NOT_A_PLACE or tokens[-1] in _NOT_A_PLACE:
            continue
        return ScopeAsk(kind="space", words=phrase, phrase=phrase, generic=True)
    return ScopeAsk()


def _bindings(res: Any) -> List[Dict[str, Any]]:
    """The bindings list of a SPARQL-results document, defensively."""
    if not isinstance(res, dict):
        return []
    inner = res.get("results")
    rows = inner.get("bindings") if isinstance(inner, dict) else None
    return rows if isinstance(rows, list) else []


def _val(row: Dict[str, Any], name: str) -> str:
    cell = row.get(name)
    return str(cell.get("value") or "") if isinstance(cell, dict) else ""


async def _ask(run: RunQuery, query: str, record: Optional[List[str]] = None) -> Optional[Any]:
    """Run one query; None on failure or timeout (the caller steps aside, never asserts)."""
    if record is not None:
        record.append(query)
    try:
        return await asyncio.wait_for(run(query), timeout=QUERY_TIMEOUT_S)
    except Exception as exc:
        logger.warning(f"[sensor_binder] graph lookup failed ({type(exc).__name__}): {exc}")
        return None


def _place_terms_query(words: str, namespace: str) -> str:
    """Spaces whose label or local name holds every word ('atrium', 'server room')."""
    terms = [t for t in re.split(r"\s+", words.lower()) if t]
    conds = " && ".join(
        f'(CONTAINS(?local, "{_esc(t)}") || CONTAINS(?lbl, "{_esc(t)}"))' for t in terms
    )
    return (
        _PREFIXES + "SELECT DISTINCT ?s ?label ?zone ?room WHERE {\n"
        "  ?s a ?cls . ?cls rdfs:subClassOf* brick:Location .\n"
        f'  FILTER(STRSTARTS(STR(?s), "{_esc(namespace)}"))\n'
        f"  BIND(LCASE(SUBSTR(STR(?s), {len(namespace) + 1})) AS ?local)\n"
        "  OPTIONAL { ?s rdfs:label ?label }\n"
        '  BIND(LCASE(COALESCE(STR(?label), "")) AS ?lbl)\n'
        f"  FILTER({conds})\n"
        "  OPTIONAL { ?s rdf:type/rdfs:subClassOf* brick:Zone . BIND(true AS ?zone) }\n"
        "  OPTIONAL { ?s rdf:type/rdfs:subClassOf* brick:Room . BIND(true AS ?room) }\n"
        "} LIMIT 40"
    )


def _place_id_query(token: str, namespace: str) -> str:
    """Spaces whose local name ENDS with the dotted id; the exact test is made in Python."""
    return (
        _PREFIXES + "SELECT DISTINCT ?s ?label ?zone ?room WHERE {\n"
        "  ?s a ?cls . ?cls rdfs:subClassOf* brick:Location .\n"
        f'  FILTER(STRSTARTS(STR(?s), "{_esc(namespace)}"))\n'
        f"  BIND(LCASE(SUBSTR(STR(?s), {len(namespace) + 1})) AS ?local)\n"
        f'  FILTER(STRENDS(?local, "{_esc(token.lower())}"))\n'
        "  OPTIONAL { ?s rdfs:label ?label }\n"
        "  OPTIONAL { ?s rdf:type/rdfs:subClassOf* brick:Zone . BIND(true AS ?zone) }\n"
        "  OPTIONAL { ?s rdf:type/rdfs:subClassOf* brick:Room . BIND(true AS ?room) }\n"
        "} LIMIT 40"
    )


def _equipment_query(words: str, namespace: str) -> str:
    """Equipment whose label, local name or class holds every word ('heat pump', 'boiler 2')."""
    terms = [t for t in re.split(r"\s+", words.lower()) if t]
    conds = " && ".join(
        f'(CONTAINS(?local, "{_esc(t.replace(" ", "_"))}") || CONTAINS(?lbl, "{_esc(t)}")'
        f' || CONTAINS(?clsl, "{_esc(t.replace(" ", "_"))}"))'
        for t in terms
    )
    return (
        _PREFIXES + "SELECT DISTINCT ?s ?label WHERE {\n"
        "  ?s a ?cls . ?cls rdfs:subClassOf* brick:Equipment .\n"
        f'  FILTER(STRSTARTS(STR(?s), "{_esc(namespace)}"))\n'
        f"  BIND(LCASE(SUBSTR(STR(?s), {len(namespace) + 1})) AS ?local)\n"
        '  BIND(LCASE(REPLACE(STR(?cls), "^.*[#/]", "")) AS ?clsl)\n'
        "  OPTIONAL { ?s rdfs:label ?label }\n"
        '  BIND(LCASE(COALESCE(STR(?label), "")) AS ?lbl)\n'
        f"  FILTER({conds})\n"
        "} LIMIT 20"
    )


async def resolve_scope(
    ask: ScopeAsk, namespace: str, run: RunQuery, record: Optional[List[str]] = None
) -> Tuple[List[ScopeHit], bool]:
    """(the places the graph holds for this ask, whether the lookup ran at all)."""
    if ask.kind == "equipment":
        res = await _ask(run, _equipment_query(ask.words, namespace), record)
        if res is None:
            return [], False
        hits = [ScopeHit(iri=_val(r, "s"), label=_val(r, "label")) for r in _bindings(res)]
        return [h for h in hits if _SAFE_IRI_RE.match(h.iri)], True

    if ask.id_token:
        res = await _ask(run, _place_id_query(ask.id_token, namespace), record)
    elif ask.words:
        res = await _ask(run, _place_terms_query(ask.words, namespace), record)
    else:
        return [], True
    if res is None:
        return [], False

    hits: List[ScopeHit] = []
    seen: Set[str] = set()
    exact = (
        re.compile(r"(^|[^0-9.])" + re.escape(ask.id_token.lower()) + r"$")
        if ask.id_token
        else None
    )
    for r in _bindings(res):
        iri = _val(r, "s")
        if not iri or iri in seen or not _SAFE_IRI_RE.match(iri):
            continue
        local = iri[len(namespace) :].lower() if iri.startswith(namespace) else _local(iri).lower()
        if exact is not None and not exact.search(local):
            continue
        seen.add(iri)
        hits.append(
            ScopeHit(
                iri=iri,
                label=_val(r, "label"),
                is_zone=bool(_val(r, "zone")),
                is_room=bool(_val(r, "room")),
            )
        )
    return hits, True


def choose_place(ask: ScopeAsk, hits: Sequence[ScopeHit]) -> Tuple[Optional[ScopeHit], List[str]]:
    """The one place the ask means, or (None, candidates) when it is not one place.

    A room and its HVAC zone share an id ("5.01"); the word the asker used decides which
    ("zone 5.01" is the zone, "room 5.01" the room). An id with no word before it prefers the
    room. Two places that survive the preference are AMBIGUOUS, and ambiguity is never
    resolved by picking one: an answer about the wrong room reads exactly like a right one.
    """
    pool = list(hits)
    if not pool:
        return None, []
    if ask.id_token:
        if ask.head == "zone":
            zones = [h for h in pool if h.is_zone]
            pool = zones or pool
        else:
            rooms = [h for h in pool if h.is_room and not h.is_zone]
            pool = rooms or [h for h in pool if not h.is_zone] or pool
    if len(pool) == 1:
        return pool[0], []
    return None, [h.label or _local(h.iri) for h in pool[:6]]


# ── sensors ──────────────────────────────────────────────────────────────────────────

_SENSOR_TAIL = (
    "  ?sensor ref:hasExternalReference ?ref .\n"
    "  ?ref ref:hasTimeseriesId ?uuid .\n"
    "  OPTIONAL { ?ref ref:storedAt ?storage }\n"
    "  OPTIONAL { ?sensor rdfs:label ?label }\n"
)


def _own_sensors_query(scope_iri: str) -> str:
    return (
        _PREFIXES + "SELECT DISTINCT ?sensor ?label ?uuid ?storage ?cls WHERE {\n"
        f"  ?sensor (brick:hasLocation|^brick:isLocationOf) <{scope_iri}> .\n"
        "  ?sensor rdf:type/rdfs:subClassOf* ?cls .\n" + _SENSOR_TAIL + f"}} LIMIT {MAX_PLACE_ROWS}"
    )


def _declared_sensors_query(scope_iri: str) -> str:
    """The place's sensors WITH OR WITHOUT a readable series: what the graph says it holds."""
    return (
        _PREFIXES + "SELECT DISTINCT ?sensor ?label ?uuid ?cls WHERE {\n"
        f"  ?sensor (brick:hasLocation|^brick:isLocationOf) <{scope_iri}> .\n"
        "  ?sensor rdf:type/rdfs:subClassOf* ?cls .\n"
        "  OPTIONAL { ?sensor rdfs:label ?label }\n"
        "  OPTIONAL { ?sensor ref:hasExternalReference ?ref . ?ref ref:hasTimeseriesId ?uuid }\n"
        f"}} LIMIT {MAX_PLACE_ROWS}"
    )


def _zone_sensors_query(scope_iri: str) -> str:
    return (
        _PREFIXES
        + "SELECT DISTINCT ?sensor ?label ?uuid ?storage ?cls ?zone ?zlabel WHERE {\n"
        f"  ?zone (brick:hasPart|brick:feeds) <{scope_iri}> .\n"
        "  ?zone rdf:type/rdfs:subClassOf* brick:Zone .\n"
        "  OPTIONAL { ?zone rdfs:label ?zlabel }\n"
        "  ?sensor (brick:hasLocation|^brick:isLocationOf) ?zone .\n"
        "  ?sensor rdf:type/rdfs:subClassOf* ?cls .\n" + _SENSOR_TAIL + f"}} LIMIT {MAX_PLACE_ROWS}"
    )


def _equipment_sensors_query(scope_iris: Sequence[str]) -> str:
    values = " ".join(f"<{i}>" for i in scope_iris)
    return (
        _PREFIXES + "SELECT DISTINCT ?sensor ?label ?uuid ?storage ?cls ?equip WHERE {\n"
        f"  VALUES ?equip {{ {values} }}\n"
        "  ?sensor (brick:isPointOf|^brick:hasPoint) ?equip .\n"
        "  ?sensor rdf:type/rdfs:subClassOf* ?cls .\n" + _SENSOR_TAIL + f"}} LIMIT {MAX_PLACE_ROWS}"
    )


def _population_query(classes: Sequence[str], namespace: str, rooms_only: bool = False) -> str:
    values = " ".join(f'"{_esc(c)}"' for c in classes if _SAFE_LOCAL_RE.match(c))
    # "Which ROOMS are occupied" is about spaces people are in: a booking flag, a charger's state
    # or an entrance counter carries an occupancy class in this graph without being in a room.
    where = (
        "  ?sensor brick:hasLocation ?loc .\n  ?loc rdf:type/rdfs:subClassOf* brick:Room .\n"
        if rooms_only
        else "  OPTIONAL { ?sensor brick:hasLocation ?loc }\n"
    )
    return (
        _PREFIXES + "SELECT DISTINCT ?sensor ?label ?uuid ?storage ?cls ?loc WHERE {\n"
        f"  VALUES ?local {{ {values} }}\n"
        "  ?sensor a ?cls .\n"
        '  FILTER(STRENDS(STR(?cls), CONCAT("#", ?local)) || '
        'STRENDS(STR(?cls), CONCAT("/", ?local)))\n'
        f'  FILTER(STRSTARTS(STR(?sensor), "{_esc(namespace)}"))\n' + where + _SENSOR_TAIL + "} "
        f"LIMIT {MAX_POPULATION * 8}"
    )


@dataclass
class _Raw:
    """One sensor as the graph returned it, its class rows folded together."""

    iri: str
    label: str = ""
    uuid: str = ""
    storage: str = ""
    classes: Set[str] = field(default_factory=set)
    class_iris: Dict[str, str] = field(default_factory=dict)
    simulated: bool = False
    location: str = ""
    zone: str = ""
    zone_label: str = ""


def _fold(rows: Sequence[Dict[str, Any]], require_uuid: bool = True) -> List[_Raw]:
    """Fold the one-row-per-class result into one record per (sensor, uuid).

    A sensor with no timeseries id is dropped unless `require_uuid` is False: it cannot be read,
    but its existence is what separates "no such sensor" from "a sensor with no link to its data".
    """
    acc: Dict[Tuple[str, str], _Raw] = {}
    for r in rows:
        iri, uuid = _val(r, "sensor"), _val(r, "uuid")
        if not iri or (require_uuid and not uuid):
            continue
        item = acc.setdefault((iri, uuid), _Raw(iri=iri, uuid=uuid))
        item.label = item.label or _val(r, "label")
        item.storage = item.storage or _val(r, "storage")
        cls = _val(r, "cls")
        if cls:
            item.classes.add(_local(cls))
            item.class_iris.setdefault(_local(cls), cls)
        item.location = item.location or _val(r, "loc")
        item.zone = item.zone or _val(r, "zone")
        item.zone_label = item.zone_label or _val(r, "zlabel")
    return sorted(acc.values(), key=lambda x: ((x.label or x.iri).lower(), x.uuid))


def _classify(raws: Sequence[_Raw], specs: Sequence[QuantitySpec]) -> List[BoundSensor]:
    """The sensors that are one of the asked-for quantities, most specific class first."""
    out: List[BoundSensor] = []
    for raw in raws:
        text = f"{raw.label} {_local(raw.iri)}"
        for spec in specs:
            if spec.matches(raw.classes, text):
                pick = next((c for c in spec.classes if c in raw.classes), "")
                out.append(
                    BoundSensor(
                        iri=raw.iri,
                        label=raw.label,
                        uuid=raw.uuid,
                        storage=raw.storage,
                        type_iri=raw.class_iris.get(pick, ""),
                        location=raw.location or raw.zone,
                        simulated=raw.simulated,
                        quantity=spec.label,
                    )
                )
                break
    return out


def _prefer_measured(sensors: List[BoundSensor]) -> List[BoundSensor]:
    """Kept as a seam; it no longer ranks by origin (2026-09-22).

    It used to prefer a measured sensor over a stand-in where a place held both, because the two
    series disagree and the narration then reports them as if they were two rooms. Every reading is
    now the building's own, so there is no origin to prefer.

    THE PROBLEM IT GUARDED AGAINST IS STILL REAL: two sensors bound to one place with different
    readings (BUG-531 found 77 sensors carrying two timeseries references). That is a data defect
    to fix in the graph, not something to settle by where a number came from.
    """
    return sensors


def _holdings(raws: Sequence[_Raw], specs: Sequence[Any]) -> List[str]:
    """What a place DOES record, as readers say it, from the building's own catalogue."""
    names: List[str] = []
    for raw in raws:
        text = f"{raw.label} {_local(raw.iri)}"
        for spec in specs:
            # The catalogue's own matcher takes ONE class at a time.
            if any(spec.matches(cls, text) for cls in raw.classes):
                pretty = _pretty_modality(spec.name)
                if pretty and pretty not in names:
                    names.append(pretty)
                break
    return sorted(names)[:12]


# ── the binder ───────────────────────────────────────────────────────────────────────


async def bind_sensors(
    question: str,
    entities: Optional[Sequence[str]],
    concepts: Optional[Sequence[Dict[str, Any]]],
    run: RunQuery,
    namespace: str,
    building_id: Optional[str] = None,
    allow_population: bool = True,
) -> Binding:
    """Bind a (quantity, place) question to its sensors, or say why this module steps aside.

    Never raises: a binder that can take a turn down is worse than the gap it fills.
    """
    try:
        return await _bind(
            question, entities, concepts, run, namespace, building_id, allow_population
        )
    except Exception as exc:
        logger.warning(f"[sensor_binder] stepped aside ({type(exc).__name__}): {exc}")
        return Binding(reason="error")


async def _bind(
    question: str,
    entities: Optional[Sequence[str]],
    concepts: Optional[Sequence[Dict[str, Any]]],
    run: RunQuery,
    namespace: str,
    building_id: Optional[str],
    allow_population: bool,
) -> Binding:
    if not namespace:
        return Binding(reason="no_namespace")
    quantities = detect_quantities(question, concepts, building_id)
    if not quantities:
        return Binding(reason="no_quantity")
    label = " and ".join(dict.fromkeys(q.label for q in quantities if q.label))
    classes = tuple(dict.fromkeys(c for q in quantities for c in q.classes))

    ask = extract_scope_ask(question, entities)
    if ask.multiple:
        return Binding(reason="several_places", quantity_label=label, classes=classes)
    if ask.kind in ("floor", "other", "sensor"):
        return Binding(reason=f"{ask.kind}_scope", quantity_label=label, classes=classes)

    if ask.kind == "none":
        if not allow_population:
            return Binding(reason="no_scope", quantity_label=label, classes=classes)
        return await _bind_population(question, quantities, run, namespace, label, classes)

    record: List[str] = []
    hits, ran = await resolve_scope(ask, namespace, run, record)
    if not ran:
        return Binding(reason="graph_unavailable", quantity_label=label, classes=classes)
    if ask.kind == "equipment":
        if not hits:
            return Binding(reason="scope_unresolved", quantity_label=label, classes=classes)
        return await _bind_equipment(
            ask, hits, quantities, run, building_id, label, classes, record
        )

    place, candidates = choose_place(ask, hits)
    if place is None:
        return Binding(
            reason="scope_ambiguous" if candidates else "scope_unresolved",
            quantity_label=label,
            classes=classes,
            candidates=candidates,
            queries=record,
        )
    scope_label = place.label or _local(place.iri)
    if ask.id_token and not place.label:
        scope_label = f"{ask.head or 'room'} {ask.id_token}"
    base = Binding(
        scope_kind=SCOPE_SPACE,
        scope_iri=place.iri,
        scope_label=_plain_label(scope_label),
        alias="" if ask.id_token else ask.words,
        quantity_label=label,
        classes=classes,
        queries=record,
    )

    own = await _ask(run, _own_sensors_query(place.iri), record)
    if own is None:
        base.reason = "graph_unavailable"
        return base
    own_raw = _fold(_bindings(own))
    own_hits = _classify(own_raw, quantities)
    own_measured = [s for s in own_hits if not s.simulated]
    if own_measured:
        base.status, base.basis, base.sensors = STATUS_BOUND, BASIS_OWN, own_measured
        return base

    # No MEASURED sensor of its own. The room's HVAC zone may hold the real instrument: in a
    # building whose physical sensors are attached to zones, the room carries only stand-ins for
    # a quantity the zone actually measures, and the stand-in must not outrank the instrument.
    # A zone-basis answer says where its reading is from (the "Spatial basis" line).
    zone = await _ask(run, _zone_sensors_query(place.iri), record)
    if zone is None:
        base.reason = "graph_unavailable"
        return base
    zone_raw = _fold(_bindings(zone))
    zone_hits = _classify(zone_raw, quantities)
    zone_measured = [s for s in zone_hits if not s.simulated]
    chosen = zone_measured or (zone_hits if not own_hits else [])
    if chosen:
        base.status, base.basis, base.sensors = STATUS_BOUND, BASIS_ZONE, chosen
        base.zone_label = _plain_label(
            next((r.zone_label for r in zone_raw if r.zone_label), "")
            or _local(next((r.zone for r in zone_raw if r.zone), "the zone that covers it"))
        )
        return base
    if own_hits:  # stand-ins only, and nothing better anywhere: still an answer, never silence
        base.status, base.basis, base.sensors = STATUS_BOUND, BASIS_OWN, own_hits
        return base

    # Nothing READABLE. Whether that is an ABSENCE is a separate question, and the two must not be
    # confused (BUG-475 told a reader to install a sensor the room already had): a quantity the
    # building does not catalogue is not evidence of a gap, and a sensor the graph declares but
    # links to no series is a broken link, not a missing sensor.
    if not any(q.catalogued for q in quantities):
        base.reason = "uncatalogued_quantity"
        return base
    declared = await _ask(run, _declared_sensors_query(place.iri), record)
    if declared is None:
        base.reason = "graph_unavailable"
        return base
    unlinked = _classify(_fold(_bindings(declared), require_uuid=False), quantities)
    base.status = STATUS_ABSENT
    base.reason = "reference_missing" if unlinked else "no_such_sensor_in_place"
    base.holdings = _holdings(own_raw, _modalities(building_id))
    return base


async def _bind_equipment(
    ask: ScopeAsk,
    hits: Sequence[ScopeHit],
    quantities: Sequence[QuantitySpec],
    run: RunQuery,
    building_id: Optional[str],
    label: str,
    classes: Tuple[str, ...],
    record: List[str],
) -> Binding:
    """Points of the named plant: 'the heat pump' reads every heat pump's matching points."""
    if len(hits) > 6:
        return Binding(
            reason="scope_ambiguous",
            quantity_label=label,
            classes=classes,
            candidates=[h.label or _local(h.iri) for h in hits[:6]],
        )
    base = Binding(
        scope_kind=SCOPE_EQUIPMENT,
        scope_iri=hits[0].iri if len(hits) == 1 else "",
        scope_label=(
            _plain_label(hits[0].label or _local(hits[0].iri)) if len(hits) == 1 else ask.phrase
        ),
        quantity_label=label,
        classes=classes,
        queries=record,
    )
    res = await _ask(run, _equipment_sensors_query([h.iri for h in hits]), record)
    if res is None:
        base.reason = "graph_unavailable"
        return base
    raws = _fold(_bindings(res))
    matched = _prefer_measured(_classify(raws, quantities))
    if matched:
        base.status, base.basis, base.sensors = STATUS_BOUND, BASIS_EQUIPMENT, matched
        return base
    # Plant carries points of many classes the room-oriented catalogue does not name, so the
    # graph finding none here is not evidence the plant lacks the measurement: step aside and let
    # the plant-specific resolver in the sparql lane stand.
    base.reason = "equipment_no_match"
    return base


#: An ask about ROOMS in general ("which rooms are occupied", "every room's noise").
_ROOMS_IN_GENERAL_RE = re.compile(
    r"\b(?:rooms|spaces|labs|offices|classrooms|studios)\b"
    r"|\b(?:each|every|which|what|any)\s+(?:room|space|lab|office)\b",
    re.IGNORECASE,
)


async def _bind_population(
    question: str,
    quantities: Sequence[QuantitySpec],
    run: RunQuery,
    namespace: str,
    label: str,
    classes: Tuple[str, ...],
) -> Binding:
    """Every sensor of the quantity, building-wide, for an ask that names no single place.

    Used ONLY to replace a retrieval that returned no timeseries ids at all. It never answers
    an ask that named a place: that case is bound to the place or declined, not widened. A
    population too large to be read whole is not bound either (see MAX_POPULATION).
    """
    record: List[str] = []
    rooms_only = bool(_ROOMS_IN_GENERAL_RE.search(question or ""))
    res = await _ask(run, _population_query(classes, namespace, rooms_only), record)
    if res is None:
        return Binding(reason="graph_unavailable", quantity_label=label, classes=classes)
    matched = _classify(_fold(_bindings(res)), quantities)
    if not matched:
        # An empty population is NOT an absence claim here: the sensor-kind existence check
        # (`_kind_is_confirmed_absent`) owns that, with the guard rails it needs.
        return Binding(
            reason="empty_population", quantity_label=label, classes=classes, queries=record
        )
    if len(matched) > MAX_POPULATION:
        return Binding(
            reason="population_too_large", quantity_label=label, classes=classes, queries=record
        )
    return Binding(
        status=STATUS_BOUND,
        basis=BASIS_POPULATION,
        scope_kind=SCOPE_BUILDING,
        quantity_label=label,
        classes=classes,
        sensors=matched,
        queries=record,
    )


def _plain_label(label: str) -> str:
    """A space's label as a reader says it: 'Room 1.06 — Computer Laboratory' -> 'Room 1.06'."""
    text = str(label or "").strip()
    head = re.split(r"\s+[–—\-]\s+|\s{2,}", text, maxsplit=1)[0].strip()
    return head or text


# ── the answer, when there is no sensor ──────────────────────────────────────────────


def absence_text(binding: Binding) -> str:
    """The honest decline: the one authorised NOT_DECLARED wording, plus what the place holds."""
    from orchestrator.services.retrieval_outcome import classify as classify_nothing

    where = binding.display_scope
    if binding.reason == "reference_missing":
        # The sensor IS declared; its link to a series is not. That is not an absence, and the
        # authorised wording for it says so in as many words.
        subject = f"The {binding.quantity_label} sensor for {where}"
        return classify_nothing(declared=True, has_reference=False, subject=subject).external
    subject = f"{binding.quantity_label} measurement for {where}"
    outcome = classify_nothing(declared=False, subject=subject)
    text = outcome.external
    if binding.holdings:
        text += f"\n\nWhat {where} does record: {', '.join(binding.holdings)}."
    else:
        text += f"\n\nNo sensors are recorded for {where}."
    return text


# ── the seam with the sparql lane ────────────────────────────────────────────────────


def _has_timeseries_ids(result: Dict[str, Any]) -> bool:
    """Did the retrieval return at least one timeseries id?"""
    uuid_re = re.compile(r"^[a-f0-9]{8}-[a-f0-9]{4}-[a-f0-9]{4}-[a-f0-9]{4}-[a-f0-9]{12}$", re.I)
    envelope = result.get("results") if isinstance(result, dict) else None
    for row in _bindings(envelope):
        for name, cell in row.items():
            if ("uuid" in name.lower() or "id" in name.lower()) and isinstance(cell, dict):
                if uuid_re.match(str(cell.get("value") or "")):
                    return True
    return False


#: Variable names of the result the "list all rooms" template returns: a COUNT of sensors per
#: space. It is what a reading question receives when no place could be resolved from its words.
_TOPOLOGY_COUNT_VARS = frozenset({"sensor_count", "count"})


def retrieval_missed(result: Dict[str, Any]) -> bool:
    """Did the retrieval fail to reach any series in a way a building-wide read can repair?

    Deliberately narrower than "returned no ids". A question this module may not bind to a place
    is otherwise free to be answered by the registers, the capability lane or a decline, and a
    building-wide population handed to any of those would be a wrong-subject answer. What is
    repaired is the measured failure: a reading question that came back as a sensor COUNT per
    space, as an empty result, or as the semantic-RAG prose written in their place.
    """
    if not isinstance(result, dict) or _has_timeseries_ids(result):
        return False
    if result.get("method") == "semantic_rag":
        return True
    rows = _bindings(result.get("results"))
    if not rows:
        return True
    names = {str(n).lower() for row in rows for n in row}
    return bool(names & _TOPOLOGY_COUNT_VARS)


def _default_run() -> RunQuery:
    from orchestrator.services.deliberation.live import sparql_exec

    return sparql_exec


def _namespace_for(state: Any) -> str:
    try:
        from orchestrator.services.building_context import resolve_building_context

        ns = resolve_building_context(getattr(state, "building_id", None)).namespace
        if ns:
            return str(ns)
    except Exception:  # pragma: no cover - the settings value is the same building
        pass
    from shared.config import settings

    return str(getattr(settings, "BUILDING_NAMESPACE", "") or "")


#: Results the sparql lane produced on PURPOSE and must keep: an absence its floor-scoped
#: resolver established, a whole register, an instrument's declared calibration. Only an
#: ordinary retrieval (no method) or the semantic-RAG fallback, which is the failure being
#: repaired, may be replaced.
_DETERMINISTIC_METHODS = frozenset(
    {"typed_absence", "whole_register", "whole_register_unavailable", "instrument_metrology"}
)


async def apply_to_result(
    state: Any,
    result: Dict[str, Any],
    question: str,
    run: Optional[RunQuery] = None,
    namespace: Optional[str] = None,
) -> Dict[str, Any]:
    """The sparql lane's result, replaced when this module can bind or can establish an absence.

    Returns `result` unchanged unless it decides something, so every question this module does
    not recognise takes exactly the path it took before. Writes the account of the decision to
    `state.intermediate_results["sensor_binding"]`, and the resolved place to
    `["binder_scope"]` so the spatial-adequacy grade can use it instead of guessing again.
    """
    try:
        bus = state.intermediate_results
        intent = str(getattr(state, "current_intent", "") or bus.get("intent") or "")
        if intent not in BINDER_INTENTS or not isinstance(result, dict):
            return result
        if result.get("method") in _DETERMINISTIC_METHODS:
            return result  # a deterministic path already answered this exact question shape
        entities = [e for e in (bus.get("entities") or []) if isinstance(e, str)]
        binding = await bind_sensors(
            question,
            entities,
            bus.get("concepts") or [],
            run or _default_run(),
            namespace or _namespace_for(state),
            getattr(state, "building_id", None) or None,
            # A building-wide population replaces only the measured failure (a sensor COUNT, an
            # empty result, the semantic fallback), never a retrieval that reached series.
            allow_population=retrieval_missed(result),
        )
        bus["sensor_binding"] = binding.to_record()
        if binding.status == STATUS_NOT_APPLICABLE:
            if binding.reason not in ("no_quantity", "no_scope", "no_namespace"):
                logger.info(f"[sensor_binder] not applied: {binding.reason}")
            return result
        return _replace(state, result, binding, question)
    except Exception as exc:  # the seam must never cost the answer
        logger.warning(f"[sensor_binder] seam skipped ({type(exc).__name__}): {exc}")
        return result


def _standardized(binding: Binding, question: str, query: Optional[str]) -> Dict[str, Any]:
    """The `standardized` block every downstream reader of a sparql result expects."""
    rows = [
        {
            "sensor": s.iri,
            "label": s.label,
            "type": s.type_iri,
            "uuid": s.uuid,
            "storage": s.storage,
            "location": s.location,
        }
        for s in binding.sensors
    ]
    return {"question": question, "query": query, "results": rows}


def _replace(
    state: Any, result: Dict[str, Any], binding: Binding, question: str = ""
) -> Dict[str, Any]:
    bus = state.intermediate_results
    query = binding.queries[-1] if binding.queries else None
    # Only a SPACE is graded for spatial adequacy: a point of a heat pump is not "in" a room, and
    # grading it against the pump would print a spatial caveat about the wrong kind of thing.
    if binding.scope_iri and binding.scope_kind == SCOPE_SPACE:
        bus["binder_scope"] = {
            "iri": binding.scope_iri,
            "label": binding.scope_label,
            "basis": binding.basis,
            "kind": binding.scope_kind,
        }
    if binding.status == STATUS_ABSENT:
        text = absence_text(binding)
        logger.info(
            f"[sensor_binder] {binding.quantity_label} in {binding.scope_label}: none recorded "
            f"-> typed absence (holds: {binding.holdings or 'nothing'})"
        )
        return {
            "success": True,
            "query": query,
            "results": {"head": {"vars": []}, "results": {"bindings": []}},
            "formatted_response": text,
            "standardized": [],
            "context": [],
            "analytics_required": False,
            "llm_reasoning": "Deterministic sensor binding found no such sensor in the place",
            "method": "typed_absence",
            "retrieval_outcome": {
                "outcome": (
                    "reference_missing" if binding.reason == "reference_missing" else "not_declared"
                ),
                "subject": f"{binding.quantity_label} measurement for {binding.scope_label}",
                "classes": list(binding.classes),
                "holdings": list(binding.holdings),
            },
            "binder": binding.to_record(),
        }
    prior = {u for u in _uuids_of(result)}
    now = {s.uuid for s in binding.sensors}
    if prior == now:
        logger.info(f"[sensor_binder] retrieval already had the {len(now)} bound sensor(s)")
    else:
        logger.info(
            f"[sensor_binder] {binding.basis} bind for {binding.scope_label or 'the building'}: "
            f"{len(prior)} retrieved -> {len(now)} bound ({binding.quantity_label})"
        )
    out = dict(result)
    out.update(
        {
            "success": True,
            "query": query,
            "results": binding.envelope(),
            "formatted_response": binding.summary(),
            "standardized": _standardized(binding, question, query),
            "analytics_required": True,
            "method": "sensor_binder",
            "binder": binding.to_record(),
        }
    )
    return out


def _uuids_of(result: Dict[str, Any]) -> List[str]:
    envelope = result.get("results") if isinstance(result, dict) else None
    out: List[str] = []
    for row in _bindings(envelope):
        for name, cell in row.items():
            if "uuid" in name.lower() and isinstance(cell, dict) and cell.get("value"):
                out.append(str(cell["value"]))
    return out


# ── the forecast lane's window ───────────────────────────────────────────────────────

_FORECAST_ASK_RE = re.compile(
    r"\b(?:predict\w*|forecast\w*|project(?:ed|ion)\w*|what\s+(?:will|would)|"
    r"(?:expected|likely)\s+to\s+be|tomorrow|next\s+(?:hour|few\s+hours|day|week|month)|"
    r"in\s+the\s+next|over\s+the\s+next)\b",
    re.IGNORECASE,
)


def _parse_stamp(value: Any) -> Optional[datetime]:
    """A naive datetime from a window bound, or None when it is not a date ('now-1d', '')."""
    text = str(value or "").strip()
    if not text or text.lower() in ("none", "null"):
        return None
    for fmt, size in (
        ("%Y-%m-%d %H:%M:%S", 19),
        ("%Y-%m-%dT%H:%M:%S", 19),
        ("%Y-%m-%d %H:%M", 16),
        ("%Y-%m-%d", 10),
    ):
        try:
            return datetime.strptime(text[:size], fmt)
        except ValueError:
            continue
    return None


def history_window(
    question: str,
    intent: str,
    start: Optional[str],
    end: Optional[str],
    now: Optional[datetime] = None,
) -> Tuple[Optional[str], Optional[str]]:
    """A forecast reads the PAST: a window the dialogue stage placed in the future is dropped.

    "What will the temperature be tomorrow in Room 2.01?" can come out of the classifier with a
    time range of tomorrow. The horizon is what "tomorrow" means to a forecast; used as the DATA
    window it selects rows that do not exist yet, the fetch returns nothing, and the lane says
    "no sensor data available for forecasting". That fits B38 (one run refused, the next
    forecast the same room) and is the one cause of it that this code can rule out on its own;
    the sensor binding above removes the other. (None, None) lets the lane read its ordinary
    recent history.
    """
    if intent not in ("trend", "forecast") or not _FORECAST_ASK_RE.search(question or ""):
        return start, end
    if now is None:
        try:
            from orchestrator.services.requested_interval import building_local_now

            now = building_local_now()
        except Exception:  # pragma: no cover - no clock is no guard
            return start, end
    s, e = _parse_stamp(start), _parse_stamp(end)
    if (s is not None and s >= now - timedelta(minutes=1)) or (
        e is not None and e > now + timedelta(minutes=5)
    ):
        logger.info(
            f"[sensor_binder] forecast window {start!r}..{end!r} lies in the future -- "
            "reading recent history instead"
        )
        return None, None
    return start, end
