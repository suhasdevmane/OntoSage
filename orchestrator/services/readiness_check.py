# -*- coding: utf-8 -*-
"""A pre-session readiness check: what is known about a room before it is used.

WHY THIS EXISTS
---------------
Lecturers asked for it in the stakeholder capture, in almost these words:

    "Can I receive one concise, source-timestamped readiness check 30 minutes before
     each class?"

Every ingredient already existed and nothing joined them. The timetable knows when the
session starts and where; the AV register knows whether the room's teaching technology was
last proved to work and when; the workspace register knows the network and the setup time;
the sensors know the conditions. What was missing was the thing that asks all four at a
useful moment and says, in one place, what is known and what is not.

WHAT MAKES IT A READINESS CHECK RATHER THAN A STATUS DUMP
---------------------------------------------------------
**Every fact carries its source and its timestamp.** That is the whole request. "The
projector works" is worthless without "checked 2026-06-16"; a CO2 reading is worthless
without knowing it is four days old. A line whose age cannot be established says so.

**The unknowns are listed as prominently as the facts.** A room with no CO2 sensor is not
a room with acceptable CO2, and a check that silently omits what it could not measure
invites exactly that reading. Contract 4 applies to a notification as much as to an answer.

**A blocker is separated from a note.** An untested hearing loop is a blocker for a session
that needs one; a west-facing glare warning is a note. Collapsing them makes every check
look either alarming or fine.

BUILDING-AGNOSTIC
-----------------
Nothing here names a building, a room or a module. Sessions come from the active building's
own TimetabledSession records, rooms are matched by the identifier the building's own labels
carry, and every register is optional: a building with no AV register gets a check without AV
lines and an explicit note saying so, rather than an error or a silent gap.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from datetime import date, datetime, timedelta
from typing import Any, Callable, Dict, List, Optional, Sequence

from shared.utils import get_logger

logger = get_logger(__name__)

ONTOSAGE = "http://ontosage.org/capabilities#"

#: States that mean "this component will not work", as the AV register records them.
_NOT_READY = {"defective", "faulty", "failed", "out of service", "broken", "unavailable"}
#: States that mean "nobody has checked" — different from broken, and reported differently.
_UNEVIDENCED = {"unevidenced", "not checked", "evidence missing", "unknown"}


@dataclass
class ReadinessFact:
    """One thing that is known, where it came from, and when it was established."""

    label: str
    state: str
    source: str
    observed: str = ""
    blocking: bool = False

    def render(self) -> str:
        when = f" · {self.observed}" if self.observed else " · date not recorded"
        return f"{self.label}: **{self.state}** _({self.source}{when})_"


@dataclass
class ReadinessCheck:
    """What is known about one room before one session."""

    room: str
    starts_at: str = ""
    module: str = ""
    session_ref: str = ""
    lead_minutes: int = 0
    facts: List[ReadinessFact] = field(default_factory=list)
    unknowns: List[str] = field(default_factory=list)
    generated_at: str = ""

    @property
    def blockers(self) -> List[ReadinessFact]:
        return [f for f in self.facts if f.blocking]

    @property
    def verdict(self) -> str:
        """Three states, not two.

        'Ready' and 'not ready' cannot express the common case: nothing is broken and
        nothing has been checked either. A room reported ready on no evidence is the
        failure this whole module exists to avoid.
        """
        if self.blockers:
            return "not ready"
        if not self.facts:
            return "nothing recorded"
        if self.unknowns:
            return "no blockers found, with gaps"
        return "ready"


def _identifier(text: str) -> str:
    """The room identifier a building's own labels carry ('Room 4.02 - Lab' -> '4.02').

    Falls back to the normalised whole string, so a building naming rooms 'Atrium' or
    'Lecture Theatre A' still matches. No building's vocabulary appears here.
    """
    match = re.search(r"\d+\.\d+|\b[A-Za-z]?\d{1,3}[A-Za-z]?\b", text or "")
    if match:
        return match.group(0).lower()
    return re.sub(r"[^a-z0-9]", "", (text or "").lower())


def _same_room(a: str, b: str) -> bool:
    ia, ib = _identifier(a), _identifier(b)
    return bool(ia) and bool(ib) and ia == ib


def _rows(result: Any) -> List[Dict[str, Any]]:
    """Rows from either shape a SPARQL executor in this repo returns."""
    if not result:
        return []
    if isinstance(result, dict) and "rows" in result:
        return list(result.get("rows") or [])
    bindings = (result or {}).get("results", {}).get("bindings", []) if isinstance(result, dict) else []
    return [{k: v.get("value") for k, v in row.items()} for row in bindings]


async def upcoming_sessions(
    namespace: str,
    run_select: Callable[..., Any],
    *,
    lead_minutes: int = 30,
    now: Optional[datetime] = None,
) -> List[Dict[str, str]]:
    """Sessions starting within the lead window, from the building's own timetable.

    Returns [] when the building holds no TimetabledSession records — a building without a
    timetable is not an error, it simply has nothing to check ahead of.
    """
    now = now or datetime.now()
    today = now.date().isoformat()
    query = (
        f"PREFIX o: <{ONTOSAGE}>\n"
        "PREFIX rdfs: <http://www.w3.org/2000/01/rdf-schema#>\n"
        "SELECT ?s ?ref ?module ?room ?starts ?ends ?kind WHERE {\n"
        "  ?s a o:TimetabledSession ;\n"
        "     o:recordId ?ref ;\n"
        "     o:locationText ?room ;\n"
        "     o:startsAt ?starts .\n"
        "  OPTIONAL { ?s rdfs:label ?module }\n"
        "  OPTIONAL { ?s o:endsAt ?ends }\n"
        "  OPTIONAL { ?s o:sessionKind ?kind }\n"
        f'  ?s o:effectiveDate "{today}"^^<http://www.w3.org/2001/XMLSchema#date> .\n'
        "} ORDER BY ?starts LIMIT 200"
    )
    try:
        result = await run_select(query, limit=200)
    except Exception as exc:
        logger.debug(f"[readiness] timetable query failed: {exc}")
        return []

    out: List[Dict[str, str]] = []
    horizon = now + timedelta(minutes=lead_minutes)
    for row in _rows(result):
        starts = str(row.get("starts") or "")
        parsed = _combine(now.date(), starts)
        if parsed is None or not (now <= parsed <= horizon):
            continue
        out.append(
            {
                "ref": str(row.get("ref") or ""),
                "module": str(row.get("module") or ""),
                "room": str(row.get("room") or ""),
                "starts_at": parsed.isoformat(timespec="minutes"),
                "kind": str(row.get("kind") or ""),
            }
        )
    return out


def _combine(day: date, hhmm: str) -> Optional[datetime]:
    """'09:00' on a date -> datetime. None when the register's time is unparseable."""
    match = re.match(r"^\s*(\d{1,2}):(\d{2})", str(hhmm or ""))
    if not match:
        return None
    try:
        return datetime(day.year, day.month, day.day, int(match.group(1)), int(match.group(2)))
    except ValueError:
        return None


async def _register_rows(
    namespace: str, run_select: Callable[..., Any], class_name: str, fields: Sequence[str]
) -> List[Dict[str, Any]]:
    """Every record of one class with the named fields. [] when the class is absent."""
    selects = " ".join(f"?{f}" for f in fields)
    optionals = "\n".join(f"  OPTIONAL {{ ?s o:{f} ?{f} }}" for f in fields)
    query = (
        f"PREFIX o: <{ONTOSAGE}>\n"
        "PREFIX rdfs: <http://www.w3.org/2000/01/rdf-schema#>\n"
        f"SELECT ?s ?label {selects} WHERE {{\n"
        f"  ?s a o:{class_name} .\n"
        "  OPTIONAL { ?s rdfs:label ?label }\n"
        f"{optionals}\n"
        "} LIMIT 400"
    )
    try:
        return _rows(await run_select(query, limit=400))
    except Exception as exc:
        logger.debug(f"[readiness] {class_name} query failed: {exc}")
        return []


async def compose(
    room: str,
    namespace: str,
    run_select: Callable[..., Any],
    *,
    module: str = "",
    starts_at: str = "",
    session_ref: str = "",
    lead_minutes: int = 0,
    now: Optional[datetime] = None,
) -> ReadinessCheck:
    """Everything the building knows about this room's readiness, with provenance."""
    now = now or datetime.now()
    check = ReadinessCheck(
        room=room,
        module=module,
        starts_at=starts_at,
        session_ref=session_ref,
        lead_minutes=lead_minutes,
        generated_at=now.isoformat(timespec="minutes"),
    )

    # ── AV and teaching technology ──────────────────────────────────────────────────
    av = await _register_rows(
        namespace,
        run_select,
        "AVReadiness",
        # lastCompleted, not lastTestedOn: the AV mapping records the check date under the
        # predicate its own columns declare, and querying the plausible-sounding one
        # returned every line as "date not recorded" — a readiness check whose entire
        # point is the timestamp, quietly reporting none.
        ("locationText", "avComponentKind", "recordStatus", "lastCompleted", "evidenceReference"),
    )
    matched_av = [r for r in av if _same_room(str(r.get("locationText") or ""), room)]
    # Show the building's OWN name for the room, not the token the question happened to
    # carry. "Room_4.02" is what entity extraction produces; "Room 4.02 - Computer
    # Laboratory" is what the building calls it, and a check headed by the former reads
    # like a system talking about its internals.
    for row in matched_av:
        label = str(row.get("locationText") or "").strip()
        if label:
            check.room = label
            break
    if not av:
        check.unknowns.append(
            "This building holds no AV readiness records, so nothing here reports on the "
            "room's teaching technology."
        )
    elif not matched_av:
        check.unknowns.append(
            f"No AV readiness record names {room}, so its teaching technology has not been "
            f"assessed — which is not the same as it working."
        )
    for row in matched_av:
        state = str(row.get("recordStatus") or "").strip() or "unknown"
        low = state.lower()
        check.facts.append(
            ReadinessFact(
                label=str(row.get("avComponentKind") or row.get("label") or "AV component"),
                state=state,
                source="AV readiness register",
                observed=str(row.get("lastCompleted") or ""),
                blocking=low in _NOT_READY or low in _UNEVIDENCED,
            )
        )

    # ── What the room is like to work in ────────────────────────────────────────────
    ws = await _register_rows(
        namespace,
        run_select,
        "WorkspaceProfile",
        # effectiveFrom carries the survey's date. A surveyed value with no date reads as
        # "date not recorded" on every line, which is true of the ROW and false of the
        # register: the survey has a date, it just is not per-row.
        ("locationText", "networkRating", "powerAccess", "setupMinutes", "recordStatus",
         "effectiveFrom"),
    )
    for row in (r for r in ws if _same_room(str(r.get("locationText") or ""), room)):
        # The building's own name for the room, from whichever register matched first. A
        # room with no AV record kept the raw entity token ("Room_4.02") in its heading.
        if check.room == room:
            label = str(row.get("locationText") or "").strip()
            if label:
                check.room = label
        network = str(row.get("networkRating") or "").strip()
        if network:
            check.facts.append(
                ReadinessFact(
                    label="Network",
                    state=network,
                    source="workspace profile (surveyed)",
                    observed=str(row.get("effectiveFrom") or ""),
                    blocking=network.lower() == "weak",
                )
            )
        setup = str(row.get("setupMinutes") or "").strip()
        if setup:
            check.facts.append(
                ReadinessFact(
                    label="Setup allowance", state=f"{setup} min",
                    source="workspace profile",
                    observed=str(row.get("effectiveFrom") or ""),
                )
            )
    if ws and not any(_same_room(str(r.get("locationText") or ""), room) for r in ws):
        check.unknowns.append(f"No workspace profile names {room}.")

    return check


def render(check: ReadinessCheck) -> str:
    """One concise, source-timestamped block. Deterministic — no model in this path."""
    when = f" at {check.starts_at[-5:]}" if check.starts_at else ""
    head = f"**{check.room} — {check.verdict}**"
    if check.module:
        head += f"\n{check.module}{when}"
        if check.lead_minutes:
            head += f", starting in about {check.lead_minutes} minutes."
    lines = [head, ""]

    blockers = check.blockers
    if blockers:
        lines.append("**Needs attention before the session:**")
        lines.extend(f"- {f.render()}" for f in blockers)
        lines.append("")

    others = [f for f in check.facts if not f.blocking]
    if others:
        lines.append("**Checked and in order:**")
        lines.extend(f"- {f.render()}" for f in others)
        lines.append("")

    if check.unknowns:
        # As prominent as the facts, deliberately. A room with nothing recorded against it
        # is not a room in good condition, and a check that buries that invites the reading.
        lines.append("**Not known:**")
        lines.extend(f"- {u}" for u in check.unknowns)
        lines.append("")

    lines.append(f"_Compiled {check.generated_at} from the building's own records._")
    return "\n".join(lines).strip()
