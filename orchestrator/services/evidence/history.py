# -*- coding: utf-8 -*-
"""Interpret a reading against the configuration in force when it was taken (V6-T07).

Master 14.1 acceptance scenario 3: *"move a sensor in metadata -> historical observations
remain linked to the correct prior location."*

The failure this prevents is one of the most convincing kinds of wrong answer available. A
sensor that is relocated, recalibrated or replaced produces a **step change in its series**,
and a step change is exactly what a real event in the building looks like. Report it as a
trend and the answer is confident, specific, and about nothing that happened.

Two rules, and the second is the one that keeps this useful rather than merely safe:

1. **Resolve as-of, never as-of-now.** A reading from March belongs to the room the sensor
   was in during March. Overwriting a location on relocation destroys that, which is why the
   TBox models validity as an interval (``ontosage:ConfigurationPeriod``) instead.

2. **A window that spans a change is FLAGGED, not refused.** Refusing every trend that
   crosses a recalibration would discard most long-horizon questions on a well-maintained
   building -- the ones the PhD and Research Staff catalogues care most about. The honest
   move is to name the discontinuity and, where the segments are long enough, report either
   side of it separately.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from typing import List, Optional, Sequence, Tuple

from shared.utils import get_logger

logger = get_logger(__name__)

#: A segment shorter than this is too small to characterise on its own; the split is reported
#: but not presented as two comparable trends. Two days is the shortest span over which a
#: daily-cycling environmental variable shows a shape rather than a fragment of one.
MIN_SEGMENT_HOURS = 48.0


@dataclass(frozen=True)
class ConfigurationPeriod:
    """One interval during which a point's location and configuration were stable."""

    effective_from: datetime
    #: None means STILL IN FORCE. The open interval is the normal case; a far-future sentinel
    #: date would silently expire and start mis-attributing readings on an arbitrary day.
    effective_to: Optional[datetime] = None
    location: Optional[str] = None
    change: str = ""  # relocation | recalibration | replacement | firmware | commissioning
    #: The point this period describes. Added when the bus reader was found constructing
    #: `ConfigurationPeriod(subject=...)` against a dataclass that had no such field — a
    #: TypeError that would have been swallowed by the reader's broad `except` and returned an
    #: empty list, the moment anybody supplied data. Nobody ever had, so it sat latent.
    #: A period also genuinely needs to know whose it is: several points' histories arrive in
    #: one query and are worthless once mixed together.
    subject: str = ""

    def covers(self, when: datetime) -> bool:
        if when < self.effective_from:
            return False
        return self.effective_to is None or when < self.effective_to


@dataclass
class WindowIntegrity:
    """Whether a time window sits inside one configuration, or crosses a boundary."""

    boundaries: List[Tuple[datetime, str]] = field(default_factory=list)
    segments: List[Tuple[datetime, datetime, Optional[str]]] = field(default_factory=list)

    @property
    def is_continuous(self) -> bool:
        return not self.boundaries

    @property
    def comparable_segments(self) -> List[Tuple[datetime, datetime, Optional[str]]]:
        """Segments long enough to characterise separately."""
        return [
            s for s in self.segments if (s[1] - s[0]).total_seconds() / 3600.0 >= MIN_SEGMENT_HOURS
        ]

    def caveat(self) -> str:
        """The sentence an answer must carry when the window crosses a change."""
        if self.is_continuous:
            return ""
        what = ", ".join(sorted({c for _, c in self.boundaries if c}) or ["a configuration change"])
        when = ", ".join(f"{t:%Y-%m-%d}" for t, _ in self.boundaries)
        base = (
            f"This window spans {what} on {when}. A change of that kind produces a step in the "
            "series that is indistinguishable from a real change in the building, so the trend "
            "across it cannot be attributed to the building alone"
        )
        n = len(self.comparable_segments)
        if n >= 2:
            return base + f"; {n} segments either side are long enough to compare separately."
        return base + "; no segment either side is long enough to characterise on its own."


def location_as_of(periods: Sequence[ConfigurationPeriod], when: datetime) -> Optional[str]:
    """Where the point was at a given instant.

    Returns None when no period covers the instant -- honest, and distinct from "we know it
    was somewhere". A reading from before any declared period cannot be attributed to a
    location just because that location is current.
    """
    for p in sorted(periods, key=lambda x: x.effective_from):
        if p.covers(when):
            return p.location
    return None


def check_window(
    periods: Sequence[ConfigurationPeriod], start: datetime, end: datetime
) -> WindowIntegrity:
    """Find configuration changes inside a window and split it around them."""
    integrity = WindowIntegrity()
    if end <= start:
        return integrity

    ordered = sorted(periods, key=lambda p: p.effective_from)
    # A boundary counts only when it falls strictly INSIDE the window. A period beginning
    # exactly at the start is the window's own configuration, not a discontinuity within it.
    cuts = [
        (p.effective_from, p.change or "a configuration change")
        for p in ordered
        if start < p.effective_from < end
    ]
    integrity.boundaries = cuts

    marks = [start] + [t for t, _ in cuts] + [end]
    for a, b in zip(marks, marks[1:]):
        if b > a:
            integrity.segments.append((a, b, location_as_of(ordered, a)))
    return integrity


def attribute_readings(
    readings: Sequence[Tuple[datetime, float]], periods: Sequence[ConfigurationPeriod]
) -> List[Tuple[datetime, float, Optional[str]]]:
    """Tag each reading with the location in force when it was taken.

    The literal content of acceptance scenario 3: move the sensor and March's readings must
    still say March's room.
    """
    ordered = sorted(periods, key=lambda p: p.effective_from)
    return [(t, v, location_as_of(ordered, t)) for t, v in readings]


# ══════════════════════════════════════════════════════════════════════════════
# Loading periods from the graph (V6-T07 wiring)
#
# The logic above was correct and unreachable for three days: nothing loaded a
# ConfigurationPeriod, so no lane could consult it. A guard nothing calls is untested in
# production however green its unit tests are (lesson #60), and this is the half that makes
# the other half true.
# ══════════════════════════════════════════════════════════════════════════════

ONTOSAGE_NS = "http://ontosage.org/capabilities#"

_PERIOD_PREFIXES = (
    "PREFIX rdfs: <http://www.w3.org/2000/01/rdf-schema#>\n"
    "PREFIX xsd: <http://www.w3.org/2001/XMLSchema#>\n"
    "PREFIX ref: <https://brickschema.org/schema/Brick/ref#>\n"
    f"PREFIX ontosage: <{ONTOSAGE_NS}>\n"
)


def periods_query(namespace: str) -> str:
    """Every declared configuration period in the building, with the point it belongs to.

    One query for the whole building rather than one per answer: the history is small (one or
    two periods per point) and changes only when a TTL is uploaded or a sensor is moved.

    The point's timeseries uuid is projected too, because that is the key an ANSWER carries --
    a period reachable only by IRI would be correct and never matched, which is the
    present-but-invisible failure this codebase keeps paying for.
    """
    return (
        _PERIOD_PREFIXES + "SELECT DISTINCT ?point ?uuid ?from ?to ?location ?change WHERE {\n"
        "  ?period a ontosage:ConfigurationPeriod ;\n"
        "          ontosage:configurationOf ?point ;\n"
        "          ontosage:effectiveFrom ?from .\n"
        "  OPTIONAL { ?period ontosage:effectiveTo ?to }\n"
        "  OPTIONAL { ?period ontosage:configLocation ?location }\n"
        "  OPTIONAL { ?period ontosage:changeKind ?change }\n"
        "  OPTIONAL { ?point ref:hasExternalReference ?r . ?r ref:hasTimeseriesId ?uuid }\n"
        f'  FILTER(STRSTARTS(STR(?point), "{namespace}"))\n'
        "}"
    )


def _parse_dt(raw: str) -> Optional[datetime]:
    """A declared instant, or None. Never a guess.

    An unparseable date must not become "now" or "the epoch": either would silently place a
    reading in the wrong configuration, which is the exact error this module exists to stop.
    """
    text = str(raw or "").strip()
    if not text:
        return None
    text = text.replace("Z", "+00:00")
    for candidate in (text, text.split("+")[0], text.replace("T", " ")):
        try:
            parsed = datetime.fromisoformat(candidate)
            return parsed.replace(tzinfo=None) if parsed.tzinfo else parsed
        except ValueError:
            continue
    logger.debug(f"[history] unparseable effective date {raw!r} — period ignored")
    return None


def periods_from_rows(rows: object) -> "dict":
    """``{point_iri: [ConfigurationPeriod]}`` and ``{uuid: point_iri}`` from either SPARQL shape.

    Returns a dict with both, because a caller has the uuid and needs the periods, and keeping
    the mapping here means one place knows how the two relate.
    """
    from orchestrator.services.evidence.plant_state import rows_of

    by_point: dict = {}
    uuid_to_point: dict = {}
    for row in rows_of(rows):
        point = str(row.get("point") or "")
        start = _parse_dt(row.get("from"))
        if not point or start is None:
            continue
        by_point.setdefault(point, []).append(
            ConfigurationPeriod(
                effective_from=start,
                effective_to=_parse_dt(row.get("to")),
                location=str(row.get("location") or "") or None,
                change=str(row.get("change") or ""),
                subject=point,
            )
        )
        uuid = str(row.get("uuid") or "")
        if uuid:
            uuid_to_point[uuid] = point
    for periods in by_point.values():
        periods.sort(key=lambda p: p.effective_from)
    return {"by_point": by_point, "uuid_to_point": uuid_to_point}


async def for_building(namespace: str, run_select) -> "dict":
    """Load the building's configuration history. Never raises.

    An answer without a discontinuity caveat is worse than one with it, but an answer that
    failed outright because the history lookup broke is worse than both.
    """
    empty = {"by_point": {}, "uuid_to_point": {}}
    if not namespace or run_select is None:
        return empty
    try:
        return periods_from_rows(await run_select(periods_query(namespace) + "\nLIMIT 2000"))
    except Exception as exc:
        logger.debug(f"[history] period lookup failed: {exc}")
        return empty


def caveat_for_uuids(history: "dict", uuids: Sequence[str], start: datetime, end: datetime) -> str:
    """The discontinuity caveat for the points behind an answer, or "" when there is none.

    Silent when nothing crosses a change — a caveat that appears on every answer is furniture,
    and furniture is not read.
    """
    if not history or not uuids:
        return ""
    seen: List[str] = []
    parts: List[str] = []
    for uuid in uuids:
        point = (history.get("uuid_to_point") or {}).get(str(uuid))
        if not point or point in seen:
            continue
        seen.append(point)
        integrity = check_window((history.get("by_point") or {}).get(point) or [], start, end)
        if integrity.is_continuous:
            continue
        name = point.rsplit("#", 1)[-1].rsplit("/", 1)[-1]
        parts.append(f"**{name}:** {integrity.caveat()}")
    return "\n\n".join(parts)
