# -*- coding: utf-8 -*-
"""Is a room busy? Read the building's own timetable and expand it over the asked window.

WHY THIS EXISTS. "Is Room 1.06 free for the next two hours?" used to be answered from ad-hoc booking
EVENTS alone. A teaching building's rooms are mostly occupied by a RECURRING timetable, so a room
with a lecture every Tuesday reported itself free. The timetable was already in the graph as 675
``ontosage:TimetabledSession`` records across 44 rooms; nothing read it. This module does.

IT USES THE VOCABULARY THAT IS ALREADY THERE — ``ontosage:timeProfile`` (the weekday),
``ontosage:startsAt`` and ``ontosage:endsAt`` (local wall-clock), ``ontosage:locationText`` (the
room). A first version of this file invented parallel names for all four, which would have left the
675 existing sessions unreadable by the very query written to find them.

THREE ANSWERS, NOT TWO. A caller must be able to tell these apart:
  * BUSY      — a session covers part of the asked window; the sessions are returned.
  * FREE      — a timetable exists for this building and nothing covers the window.
  * UNKNOWN   — no timetable is recorded at all. Saying "free" here would be a guess dressed as a
                fact, and it is the failure this module exists to prevent.
``ScheduleAnswer.timetable_loaded`` carries that distinction.

CLOCKS. Sessions are the building's LOCAL wall-clock times, because a published timetable is written
in local time and does not move when the clocks change. Callers pass a LOCAL window; converting from
the UTC store is the caller's job, at its own edge (BUG-403).

Nothing here names a building, a room or a term.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from datetime import date, datetime, time, timedelta
from typing import Any, Awaitable, Callable, Dict, List, Optional

from shared.utils import get_logger

logger = get_logger(__name__)

SparqlExec = Callable[[str], Awaitable[Dict[str, Any]]]

_NS = "http://ontosage.org/capabilities#"

# Weekday NAMES, not numbers: a number is ambiguous across conventions (ISO makes Monday 1, other
# systems make Sunday 0) and a maintainer editing the TTL by hand should not have to know which.
_DAYS = ["monday", "tuesday", "wednesday", "thursday", "friday", "saturday", "sunday"]

_SESSIONS_SPARQL = """
PREFIX o: <{ns}>
PREFIX rdfs: <http://www.w3.org/2000/01/rdf-schema#>
SELECT ?s ?space ?spaceName ?day ?start ?end ?title ?kind ?from ?to WHERE {{
  ?s a o:TimetabledSession ;
     o:timeProfile ?day ; o:startsAt ?start ; o:endsAt ?end .
  OPTIONAL {{ ?s o:locationText ?spaceName }}
  OPTIONAL {{ ?s rdfs:label ?title }}
  OPTIONAL {{ ?s o:sessionKind ?kind }}
  OPTIONAL {{ ?s o:effectiveFrom ?from }}
  OPTIONAL {{ ?s o:reviewDue ?to }}
}}
"""


@dataclass(frozen=True)
class Session:
    """One weekly pattern, exactly as the graph states it."""

    iri: str
    space_iri: str
    space_name: str
    day: str
    start: time
    end: time
    title: str
    kind: str
    effective_from: Optional[date]
    effective_to: Optional[date]

    def runs_on(self, when: date) -> bool:
        """True when this pattern is in force on a given date (term bounds are inclusive)."""
        if _DAYS[when.weekday()] != self.day.strip().lower():
            return False
        if self.effective_from and when < self.effective_from:
            return False
        if self.effective_to and when > self.effective_to:
            return False
        return True


@dataclass(frozen=True)
class Occupancy:
    """One concrete occupied window, after the weekly pattern is expanded onto a date."""

    start: datetime
    end: datetime
    title: str
    kind: str
    space_name: str


@dataclass
class ScheduleAnswer:
    """Busy windows overlapping the asked range, and whether a timetable existed to consult."""

    occupied: List[Occupancy] = field(default_factory=list)
    timetable_loaded: bool = False
    rooms_with_sessions: int = 0

    @property
    def is_busy(self) -> bool:
        return bool(self.occupied)


def _local(binding: Dict[str, Any], key: str) -> str:
    return str((binding.get(key) or {}).get("value", "") or "")


def _parse_time(raw: str) -> Optional[time]:
    """xsd:time as the store writes it. Returns None rather than guessing at an unreadable value."""
    text = raw.strip()
    for cut in ("Z", "+"):                       # a zone on a wall-clock time is meaningless here
        if cut in text[3:]:
            text = text[: text.index(cut, 3)]
    for fmt in ("%H:%M:%S", "%H:%M"):
        try:
            return datetime.strptime(text, fmt).time()
        except ValueError:
            continue
    return None


def _parse_date(raw: str) -> Optional[date]:
    text = (raw or "").strip()[:10]
    try:
        return datetime.strptime(text, "%Y-%m-%d").date() if text else None
    except ValueError:
        return None


def parse_sessions(rows: List[Dict[str, Any]]) -> List[Session]:
    """Graph rows -> sessions, skipping any row whose day or times cannot be read."""
    out: List[Session] = []
    for b in rows:
        day = _local(b, "day").strip().lower()
        start, end = _parse_time(_local(b, "start")), _parse_time(_local(b, "end"))
        if day not in _DAYS or start is None or end is None:
            logger.warning("[room_schedule] unreadable session skipped: %s", _local(b, "s"))
            continue
        out.append(
            Session(
                iri=_local(b, "s"),
                space_iri=_local(b, "space"),
                space_name=_local(b, "spaceName"),
                day=day,
                start=start,
                end=end,
                title=_local(b, "title"),
                kind=_local(b, "kind"),
                effective_from=_parse_date(_local(b, "from")),
                effective_to=_parse_date(_local(b, "to")),
            )
        )
    return out


def _key(text: str) -> str:
    """Compare room names the way people write them: 'Room 1.06', 'room1.06' and '1.06' all match."""
    return "".join(c for c in str(text or "").lower() if c.isalnum())


def _room_candidates(text: str) -> List[str]:
    """The room identifiers hidden in a timetable's location wording.

    A session records its room as prose -- "Room 2.15 - Seminar Room" -- so comparing the whole
    string against the model's "Room2.15" never matches. Take the part before the first dash or
    comma, plus any number-shaped token, and let any of them match. The number pattern is a bonus,
    not a requirement: a building whose rooms are named "West Wing Studio" still matches on the
    leading segment, so nothing here assumes a numbering convention.
    """
    raw = str(text or "").strip()
    if not raw:
        return []
    out = [raw]
    for sep in ("—", "–", " - ", ",", "("):
        if sep in raw:
            out.append(raw.split(sep)[0])
    out.extend(re.findall(r"\d{1,3}[.\-]\d{1,3}", raw))
    return out


def matches_room(session: Session, room_local: str) -> bool:
    """True when a session belongs to the given room.

    The IRI is checked first because a name can match two rooms and an IRI cannot; the prose name
    is the fallback, and is what the existing 675 sessions actually carry.
    """
    want = _key(room_local)
    if not want:
        return False
    iri_local = session.space_iri.rsplit("#", 1)[-1].rsplit("/", 1)[-1]
    if iri_local and _key(iri_local) == want:
        return True
    for cand in _room_candidates(session.space_name):
        got = _key(cand)
        if got and (got == want or want.endswith(got) or got.endswith(want)):
            return True
    return False


def expand(sessions: List[Session], start: datetime, end: datetime) -> List[Occupancy]:
    """Every concrete occupied window overlapping [start, end).

    Walks each date the window touches rather than doing weekday arithmetic, so a window spanning
    midnight, a weekend or a term boundary needs no special case.
    """
    if end <= start:
        return []
    out: List[Occupancy] = []
    # The register keeps one record per dated occurrence, so a weekly slot appears many times over a
    # term. Collapsed onto a weekday those become identical windows, and the answer listed the same
    # lecture four times. Identical (start, end, title) is ONE occupation of the room.
    seen = set()
    day = start.date()
    while day <= end.date():
        for s in sessions:
            if not s.runs_on(day):
                continue
            s_start = datetime.combine(day, s.start)
            s_end = datetime.combine(day, s.end)
            if s_end > start and s_start < end:          # end is exclusive on both sides
                key = (s_start, s_end, s.title.strip().lower())
                if key in seen:
                    continue
                seen.add(key)
                out.append(
                    Occupancy(start=s_start, end=s_end, title=s.title, kind=s.kind,
                              space_name=s.space_name or s.space_iri.rsplit("#", 1)[-1])
                )
        day += timedelta(days=1)
    return sorted(out, key=lambda o: o.start)


async def load_sessions(sparql_exec: SparqlExec) -> List[Session]:
    """Every timetabled session in the graph. An empty list means no timetable is recorded."""
    try:
        data = await sparql_exec(_SESSIONS_SPARQL.format(ns=_NS))
    except Exception as exc:
        logger.warning("[room_schedule] could not read the timetable: %s", exc)
        return []
    rows = ((data or {}).get("results") or {}).get("bindings") or []
    return parse_sessions(rows)


async def check(
    sparql_exec: SparqlExec, room_local: str, local_start: datetime, local_end: datetime
) -> ScheduleAnswer:
    """Busy windows for one room over a LOCAL window, plus whether a timetable existed at all."""
    sessions = await load_sessions(sparql_exec)
    if not sessions:
        return ScheduleAnswer(occupied=[], timetable_loaded=False, rooms_with_sessions=0)
    rooms = {s.space_iri or s.space_name for s in sessions}
    mine = [s for s in sessions if matches_room(s, room_local)]
    return ScheduleAnswer(
        occupied=expand(mine, local_start, local_end),
        timetable_loaded=True,
        rooms_with_sessions=len(rooms),
    )
