# -*- coding: utf-8 -*-
"""event_sources.py -- what the building records as EVENTS, placed in a space and on the clock (v2, C5).

WHY THIS EXISTS
---------------
"Is CO2 higher during timetabled sessions?" and "does noise rise after access events?" relate a
measured series to events the building RECORDS. Nothing in ARBITER knew which of its registers are
events -- things that happened at a time, in a place -- as against registers that describe a room
(a workspace profile) or a schedule (a cleaning rota). This module decides that from the graph, at
run time, for whatever building is loaded. No class of any building is named here.

WHAT QUALIFIES, decided from the data
-------------------------------------
A held record class is an EVENT SOURCE when its records carry BOTH:

* a PLACE: a link to one of the building's spaces -- the lift's ``ontosage:locatedInSpace`` (P1) or
  Module J's ``ontosage:aboutSpace`` ("the room/zone the record concerns") -- reaching a
  ``brick:Space``; a record placed only on a floor, a piece of equipment or the whole building is
  not in a space a reading can be read for, and is counted, never placed; and
* a TIME ON THE CLOCK, read with the ontology's own interval vocabulary (the TBox, never a guess):
  a start INSTANT -- ``ontosage:effectiveFrom`` as an ``xsd:dateTime`` (Module J: "Start of the
  period. Inclusive.") -- or a DAY (``ontosage:effectiveDate``, or ``effectiveFrom`` as an
  ``xsd:date``) with a local wall-clock start (``ontosage:startsAt``, Module S: "local wall-clock
  start, inclusive"). Its end, when recorded: ``ontosage:effectiveTo`` (an instant), the day with
  ``ontosage:endsAt`` (Module S: "local wall-clock end, EXCLUSIVE"), or the start plus
  ``ontosage:expectedMinutes``; a source that records none has INSTANTS (an access denial).

A date-valued predicate that holds the SAME value on every record is a document stamp, not a time:
the lifter writes ``effectiveFrom`` from a register's front matter when no column supplies it, so a
timetable's sessions all carry their document's date there and their own date in
``effectiveDate``. ``register_facts`` applies the same test for the same reason.

A record whose status is cancelled did not happen: it is counted and never placed. A record whose
end is absent where its source records ends is still in force (the TBox's own reading of an absent
``effectiveTo``) and runs to now.

TIMES ARE BUILDING-LOCAL WALL CLOCK -- the convention of the lifted registers (Module S) -- while
every store is UTC (BUG-403). Every event is converted with ``requested_interval.to_store`` before
it is set against a reading, and shown back with ``to_local``.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from typing import Dict, Iterable, List, Mapping, Optional, Sequence, Tuple

from orchestrator.services.record_entity_links import LINK_PREDICATES, LOCATED_IN

_O = "http://ontosage.org/capabilities#"
_RDF_TYPE = "http://www.w3.org/1999/02/22-rdf-syntax-ns#type"
_XSD = "http://www.w3.org/2001/XMLSchema#"

#: The ontology's interval vocabulary (ontology/ontosage_schema.ttl, Modules J and S). Named as the
#: TBox names them: they ship with the ontology, not with a building -- exactly as the lift's link
#: predicates do (record_entity_links.LINK_PREDICATES).
START = _O + "effectiveFrom"
END = _O + "effectiveTo"
DAY = _O + "effectiveDate"
CLOCK_START = _O + "startsAt"
CLOCK_END = _O + "endsAt"
MINUTES = _O + "expectedMinutes"
STATUS = _O + "recordStatus"
RECORD_ID = _O + "recordId"
ABOUT_SPACE = _O + "aboutSpace"

#: The links that place a record in a space.
PLACE_LINKS: Tuple[str, ...] = (LINK_PREDICATES[LOCATED_IN], ABOUT_SPACE)
#: The predicates a record is placed on the clock by.
TIME_PREDICATES: Tuple[str, ...] = (START, END, DAY, CLOCK_START, CLOCK_END, MINUTES)

#: The roles a qualifying source's predicates play, in the order they are stored on its facet.
ROLE_START = "start"  # an instant
ROLE_DAY = "day"  # a date, combined with ROLE_CLOCK_START
ROLE_CLOCK_START = "clock_start"
ROLE_END = "end"  # an instant
ROLE_CLOCK_END = "clock_end"  # a wall-clock end on the record's day (exclusive)
ROLE_MINUTES = "minutes"  # a duration from the start

#: A local wall-clock time as registers write it: "09:00", "9:30", "17:15:00".
_CLOCK_RE = re.compile(r"^\s*(\d{1,2}):(\d{2})(?::(\d{2}))?\s*$")
#: Rows one event read may return. Reaching it is logged: an event beyond it would be missing.
MAX_EVENT_ROWS = 20000
#: Rows the discovery read may return. Reaching it makes the catalogue build record an error, so
#: a cut read is never taken for the building's whole set of events.
MAX_DISCOVERY_ROWS = 200000
#: Distinct values a discovery profile keeps per predicate (enough to see a clock shape).
_SAMPLE_KEEP = 40


def _escape(text: str) -> str:
    return str(text or "").replace("\\", "\\\\").replace('"', '\\"')


_IRI_RE = re.compile(r"[A-Za-z][A-Za-z0-9+.\-]*:[^\s<>\"{}|\\^`]+")


def _iri(text: str) -> str:
    candidate = str(text or "").strip()
    if not _IRI_RE.fullmatch(candidate):
        raise ValueError("an event-source query was handed something that is not an IRI")
    return f"<{candidate}>"


# ── discovery: which held record classes are event sources ──────────────────────────────


def discovery_query(
    class_names: Sequence[str], namespace: str, limit: int = MAX_DISCOVERY_ROWS
) -> str:
    """Every held class's records placed in one of the building's places, with their time values.

    ONE VALUES block (the two place links), the classes in a FILTER: the store starts from the
    link triples, which are few. Rows, not aggregates: which targets are SPACES is decided in Python
    against the space set the catalogue already read, so the store is never asked to walk the class
    hierarchy once per record. Measured offline over one building's graph (rdflib): this form 3.3 s;
    the same read with the links as a UNION, or aggregated with that walk, did not finish in five
    minutes. The ``rdf:type`` row of each record counts records that carry no time at all.
    """
    classes = ", ".join(_iri(_O + n) for n in sorted(set(class_names)))
    links = " ".join(_iri(link) for link in PLACE_LINKS)
    preds = ", ".join(_iri(p) for p in (_RDF_TYPE,) + TIME_PREDICATES)
    return (
        "SELECT ?cls ?r ?space ?p ?v "
        '(IF(isLiteral(?v), STR(DATATYPE(?v)), "iri") AS ?dt) WHERE {\n'
        f"  VALUES ?link {{ {links} }}\n"
        "  ?r ?link ?space .\n"
        f'  FILTER(STRSTARTS(STR(?space), "{_escape(namespace)}"))\n'
        "  ?r a ?cls .\n"
        f"  FILTER(?cls IN ({classes}))\n"
        "  ?r ?p ?v .\n"
        f"  FILTER(?p IN ({preds}))\n"
        f"}} LIMIT {int(limit)}"
    )


@dataclass(frozen=True)
class PredicateProfile:
    """How one time predicate appears on a class's records placed in a space."""

    predicate: str
    #: Placed records carrying it, and the distinct values they hold.
    records: int
    distinct: int
    datatypes: Tuple[str, ...]
    first: str
    last: str
    #: True when EVERY value is a wall-clock time ("09:00").
    clock: bool = False
    #: A few of the values, for a note.
    sample: Tuple[str, ...] = ()

    def family(self) -> str:
        """date | datetime | text | number | "" -- the value type the data holds."""
        names = {d.rsplit("#", 1)[-1] for d in self.datatypes if d and d != "iri"}
        if names == {"dateTime"} or names == {"dateTimeStamp"}:
            return "datetime"
        if names == {"date"}:
            return "date"
        if names and names <= {"integer", "int", "long", "decimal", "double", "float"}:
            return "number"
        return "text" if names else ""

    def is_stamp(self) -> bool:
        """The same value on every record: a document stamp, not a per-record time."""
        return self.records >= 2 and self.distinct == 1

    def is_clock(self) -> bool:
        """Every value is a wall-clock time ("09:00")."""
        return self.clock


@dataclass(frozen=True)
class SourceProfile:
    """One held class's records placed in a space, and its time predicates on them."""

    class_name: str
    records: int
    spaces: int
    predicates: Mapping[str, PredicateProfile]


def profiles_from_rows(
    rows: Iterable[Mapping[str, str]], space_iris: Optional[Iterable[str]] = None
) -> Dict[str, SourceProfile]:
    """{class local name: SourceProfile} from the discovery query's rows.

    Only records placed in one of ``space_iris`` count (every place when None): a record placed
    only on a floor, a piece of equipment or the building is not in a space a reading belongs to.
    Counts are exact distinct counts over the rows.
    """
    allowed = set(space_iris) if space_iris is not None else None
    records: Dict[str, set] = {}
    spaces: Dict[str, set] = {}
    seen: Dict[Tuple[str, str], Dict[str, set]] = {}
    for row in rows:
        cls = str(row.get("cls") or "").rsplit("#", 1)[-1]
        record, space = str(row.get("r") or ""), str(row.get("space") or "")
        predicate = str(row.get("p") or "")
        if not (cls and record and space and predicate):
            continue
        if allowed is not None and space not in allowed:
            continue
        records.setdefault(cls, set()).add(record)
        spaces.setdefault(cls, set()).add(space)
        if predicate == _RDF_TYPE:
            continue
        held = seen.setdefault((cls, predicate), {"records": set(), "values": set(), "dt": set()})
        held["records"].add(record)
        held["values"].add(str(row.get("v") or ""))
        held["dt"].add(str(row.get("dt") or ""))
    out: Dict[str, SourceProfile] = {}
    for cls in records:
        predicates: Dict[str, PredicateProfile] = {}
        for (owner, predicate), held in seen.items():
            if owner != cls:
                continue
            values = sorted(v for v in held["values"] if v.strip())
            predicates[predicate] = PredicateProfile(
                predicate=predicate,
                records=len(held["records"]),
                distinct=len(values),
                datatypes=tuple(sorted(d for d in held["dt"] if d)),
                first=values[0] if values else "",
                last=values[-1] if values else "",
                clock=bool(values) and all(_CLOCK_RE.match(v) for v in values),
                sample=tuple(values[:_SAMPLE_KEEP]),
            )
        out[cls] = SourceProfile(cls, len(records[cls]), len(spaces[cls]), predicates)
    return out


def time_roles(profile: SourceProfile) -> Tuple[Tuple[str, str], ...]:
    """The (role, predicate) pairs that place a class's records on the clock -- or () when none do.

    The start decides: an instant (``effectiveFrom`` holding date-times), else a day with a
    wall-clock start. The end follows the start's kind.

    THE STAMP TEST APPLIES TO ``effectiveFrom`` AS A DATE ONLY, because that is the one field the
    lifter stamps (from a register's front matter, as a date) -- the scope register_facts gives its
    own test. Applied anywhere else it would throw away a register whose events all fall on one day.
    """
    preds = profile.predicates

    def usable(predicate: str, *families: str, stamped: bool = False) -> bool:
        p = preds.get(predicate)
        if p is None or p.family() not in families:
            return False
        return not (stamped and p.is_stamp())

    roles: List[Tuple[str, str]] = []
    if usable(START, "datetime"):
        roles.append((ROLE_START, START))
        if usable(END, "datetime"):
            roles.append((ROLE_END, END))
        elif usable(MINUTES, "number"):
            roles.append((ROLE_MINUTES, MINUTES))
        return tuple(roles)
    if usable(DAY, "date", "datetime"):
        day: Optional[str] = DAY
    elif usable(START, "date", stamped=True):
        day = START
    else:
        day = None
    clock = preds.get(CLOCK_START)
    if day is None or clock is None or not clock.is_clock():
        return ()
    roles += [(ROLE_DAY, day), (ROLE_CLOCK_START, CLOCK_START)]
    end_clock = preds.get(CLOCK_END)
    if end_clock is not None and end_clock.is_clock():
        roles.append((ROLE_CLOCK_END, CLOCK_END))
    elif usable(MINUTES, "number"):
        roles.append((ROLE_MINUTES, MINUTES))
    return tuple(roles)


def time_note(roles: Sequence[Tuple[str, str]]) -> str:
    """How a source's records are placed on the clock, in words (a facet note)."""
    kinds = dict(roles)
    if ROLE_START in kinds:
        start = "a recorded start time"
    else:
        start = "a recorded date and local start time"
    if ROLE_END in kinds or ROLE_CLOCK_END in kinds:
        end = "a recorded end"
    elif ROLE_MINUTES in kinds:
        end = "an end from its planned duration"
    else:
        end = "no duration (each is an instant)"
    return f"placed on the clock by {start} and {end}"


def span_of(profile: SourceProfile, roles: Sequence[Tuple[str, str]]) -> Tuple[str, str]:
    """(first, last) day the source's start predicate holds, as YYYY-MM-DD; ("", "") unknown."""
    kinds = dict(roles)
    key = kinds.get(ROLE_START) or kinds.get(ROLE_DAY)
    p = profile.predicates.get(key or "")
    if p is None:
        return "", ""
    return p.first[:10], p.last[:10]


# ── reading the events of one source, for the spaces a plan reads ────────────────────────

#: The query variable each role's value is read into.
_ROLE_VARS = {
    ROLE_START: "start",
    ROLE_END: "end",
    ROLE_DAY: "day",
    ROLE_CLOCK_START: "cs",
    ROLE_CLOCK_END: "ce",
    ROLE_MINUTES: "mins",
}


def events_query(
    record_class: str,
    roles: Sequence[Tuple[str, str]],
    space_iris: Sequence[str],
    limit: int = MAX_EVENT_ROWS,
) -> str:
    """Every record of one source placed in the given spaces, with its time predicates.

    Built in code from the facet's own metadata; the spaces are IRIs the graph returned, in ONE
    VALUES block. Records are filtered to the window in Python, after the read, because a day and a
    wall-clock string are not a time the store can compare.
    """
    spaces = " ".join(_iri(s) for s in sorted(set(space_iris)))
    links = ", ".join(_iri(link) for link in PLACE_LINKS)
    optional = "".join(
        f"  OPTIONAL {{ ?r {_iri(predicate)} ?{_ROLE_VARS[role]} }}\n"
        for role, predicate in roles
        if role in _ROLE_VARS
    )
    selected = " ".join(f"?{_ROLE_VARS[role]}" for role, _ in roles if role in _ROLE_VARS)
    return (
        f"SELECT ?r ?space ?rid ?status {selected} WHERE {{\n"
        f"  VALUES ?space {{ {spaces} }}\n"
        "  ?r ?link ?space .\n"
        f"  FILTER(?link IN ({links}))\n"
        f"  ?r a {_iri(_O + record_class)} .\n"
        f"  OPTIONAL {{ ?r {_iri(RECORD_ID)} ?rid }}\n"
        f"  OPTIONAL {{ ?r {_iri(STATUS)} ?status }}\n"
        f"{optional}"
        f"}} LIMIT {int(limit)}"
    )


@dataclass(frozen=True)
class RecordedEvent:
    """One recorded event, placed in a space and on the stores' clock (naive UTC)."""

    record: str
    rid: str
    space_iri: str
    start: datetime
    #: Equal to ``start`` for an instant.
    end: datetime
    #: No end recorded where the source records ends: still in force, run to now.
    open_ended: bool = False

    @property
    def instant(self) -> bool:
        """True when the event has no duration."""
        return self.end <= self.start


@dataclass
class EventCounts:
    """What happened to the records read, so the answer can say it."""

    read: int = 0
    cancelled: int = 0
    #: Records whose time could not be read (a missing or unreadable start).
    untimed: int = 0
    open_ended: int = 0


def _as_datetime(text: str, tz_name: Optional[str]) -> Optional[datetime]:
    """A recorded date-time on the stores' clock: an explicit offset converts directly, a local
    (naive) one through the building's zone."""
    from orchestrator.services.requested_interval import to_store

    raw = str(text or "").strip()
    if not raw:
        return None
    try:
        value = datetime.fromisoformat(raw.replace("Z", "+00:00"))
    except ValueError:
        return None
    if value.tzinfo is not None:
        return value.astimezone(timezone.utc).replace(tzinfo=None)
    return to_store(value, tz_name)


def _on_day(day_text: str, clock_text: str, tz_name: Optional[str]) -> Optional[datetime]:
    """A local day and a local wall-clock time, as one instant on the stores' clock."""
    from orchestrator.services.requested_interval import to_store

    match = _CLOCK_RE.match(str(clock_text or ""))
    try:
        day = datetime.strptime(str(day_text or "").strip()[:10], "%Y-%m-%d")
    except ValueError:
        return None
    if not match:
        return None
    hour, minute, second = int(match.group(1)), int(match.group(2)), int(match.group(3) or 0)
    if hour > 23 or minute > 59 or second > 59:
        return None
    return to_store(day.replace(hour=hour, minute=minute, second=second), tz_name)


def _cancelled(status: str) -> bool:
    return str(status or "").strip().lower().startswith("cancel")


def assemble_events(
    rows: Iterable[Mapping[str, str]],
    roles: Sequence[Tuple[str, str]],
    tz_name: Optional[str],
    now: datetime,
) -> Tuple[List[RecordedEvent], EventCounts]:
    """Rows of ``events_query`` -> events on the stores' clock, and what was set aside.

    Pure: ``now`` is the stores' clock (naive UTC), passed in so a test can fix it.
    """
    kinds = dict(roles)
    records: Dict[Tuple[str, str], Mapping[str, str]] = {}
    for row in rows:
        key = (str(row.get("r") or ""), str(row.get("space") or ""))
        if key[0] and key[1] and key not in records:
            records[key] = row
    counts = EventCounts()
    out: List[RecordedEvent] = []
    for (record, space), row in sorted(records.items()):
        counts.read += 1
        if _cancelled(str(row.get("status") or "")):
            counts.cancelled += 1
            continue
        if ROLE_START in kinds:
            start = _as_datetime(str(row.get("start") or ""), tz_name)
        else:
            start = _on_day(str(row.get("day") or ""), str(row.get("cs") or ""), tz_name)
        if start is None:
            counts.untimed += 1
            continue
        end: Optional[datetime] = None
        open_ended = False
        if ROLE_END in kinds:
            end = _as_datetime(str(row.get("end") or ""), tz_name)
            if end is None:
                end, open_ended = max(now, start), True
        elif ROLE_CLOCK_END in kinds:
            end = _on_day(str(row.get("day") or ""), str(row.get("ce") or ""), tz_name)
            if end is not None and end < start:
                end += timedelta(days=1)  # a wall-clock end before the start is past midnight
        elif ROLE_MINUTES in kinds:
            try:
                end = start + timedelta(minutes=float(str(row.get("mins") or "")))
            except ValueError:
                end = None
        if end is None or end < start:
            end = start
        if open_ended:
            counts.open_ended += 1
        out.append(
            RecordedEvent(
                record=record,
                rid=str(row.get("rid") or ""),
                space_iri=space,
                start=start,
                end=end,
                open_ended=open_ended,
            )
        )
    return out, counts


__all__ = [
    "ABOUT_SPACE",
    "EventCounts",
    "MAX_EVENT_ROWS",
    "PLACE_LINKS",
    "PredicateProfile",
    "RecordedEvent",
    "SourceProfile",
    "TIME_PREDICATES",
    "assemble_events",
    "discovery_query",
    "events_query",
    "profiles_from_rows",
    "span_of",
    "time_note",
    "time_roles",
]
