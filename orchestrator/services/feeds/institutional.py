# -*- coding: utf-8 -*-
"""Institutional-context sources: timetable, booking, room allocation (V6-T25).

**This is the R2 unlock.** 303 of the supervisors' 480 questions are integration-dependent,
and timetable/booking is the most frequently named. Sensors already have a declare-and-connect
contract — drop a TTL, register the database, load rows, and dozens of questions light up with
no code change. Institutional data had no such contract, so every "is this room booked", "when
is the lecture", "who has this space" question was blocked on a bespoke integration nobody
would write per building.

This gives that data the same contract. A building declares a source in `feeds.yaml`:

    - id: timetable_2026
      type: timetable          # or: booking_export
      path: institutional/timetable.csv
      space_field: room
      start_field: start
      end_field: end
      title_field: module

and its records become `IntervalRecord`s in the events store — the same table bookings,
work orders and access events already share. Nothing downstream changes: the events lane, the
availability primitive and the precedence contract all treat them as the authoritative source
they are.

**Why records land in the events store rather than a new table.** A parallel booking table
would need its own query path, its own availability logic and its own status vocabulary, and
would drift from the one the events lane already uses — the BUG-210 shape. `events` was built
generic for exactly this.

**Authoritative by construction.** A timetable IS the system of record for what is scheduled;
`precedence.py` puts it in the authoritative tier, above any occupancy sensor. That is rule
R-7, and it is why connecting this source does more than add data: it is the only thing that
can satisfy the entitlement claims `permission_guard` currently refuses.

**Space resolution is strict.** A row naming a room the building does not have is REPORTED
and skipped, never guessed into the nearest match. A timetable that silently binds "LT-2" to
whatever matched best would put confident wrong answers into the availability lane.
"""

from __future__ import annotations

import csv
import json
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List, Optional, Sequence

from shared.utils import get_logger

logger = get_logger(__name__)

#: The source kinds this module handles, and the event_type each produces in the events store.
#: Both are authoritative systems of record — see `precedence.py`.
SOURCE_KINDS: Dict[str, str] = {
    "timetable": "booking",
    "booking_export": "booking",
    "room_allocation": "booking",
}

#: Column names tried when the spec does not declare one. Deliberately short: guessing widely
#: is how a column called "notes" becomes a room name.
_DEFAULT_FIELDS = {
    "space": ("room", "space", "location", "room_code"),
    "start": ("start", "start_time", "begins", "from"),
    "end": ("end", "end_time", "ends", "until"),
    "title": ("title", "module", "subject", "description", "event"),
}


@dataclass
class InstitutionalRecord:
    """One scheduled interval, ready for the events store."""

    space_local: str
    start: datetime
    end: Optional[datetime]
    title: str = ""
    source_id: str = ""
    attrs: Dict[str, Any] = field(default_factory=dict)

    def as_event(self, building_id: str, event_type: str = "booking") -> Dict[str, Any]:
        """The events-store row. `subject_uuid` uses the SAME derivation the rest of the
        event framework uses, so a timetable row joins to a space exactly as a booking does."""
        # uuid5, NOT a readable string. The events table declares event_id CHAR(36) and
        # every other producer mints a uuid5, which is exactly 36 characters. This built
        # "synthetic_timetable:Room1.06:20260727T0900" — 42 — and MySQL silently
        # TRUNCATED it to "synthetic_timetable:Room1.06:2026073", discarding the day
        # digit and the whole time. Every session in one room within the same ten-day
        # window then collapsed onto one primary key and INSERT IGNORE dropped the rest:
        # 675 parsed records became 441 stored ones, with no error anywhere (measured
        # 2026-08-25). The uuid5 recipe keeps the property that mattered — the same row
        # ingested twice is the same id, so re-ingest stays a no-op — while fitting the
        # column the rest of the framework already respects.
        import uuid as _uuidlib

        from orchestrator.services.datasource_registry import derive_point_uuid

        _name = (
            f"{building_id}:{event_type}:{self.source_id}:"
            f"{self.space_local}:{self.start:%Y-%m-%dT%H:%M}"
        )
        return {
            "event_id": str(_uuidlib.uuid5(_uuidlib.NAMESPACE_URL, _name)),
            "event_type": event_type,
            "subject_uuid": derive_point_uuid(building_id, "evt_subject", self.space_local),
            "start_dt": self.start,
            "end_dt": self.end,
            "status": "scheduled",
            "attrs": json.dumps(
                {
                    "title": self.title,
                    "source": self.source_id,
                    # Declared provenance, always. A synthetic timetable must never read as a
                    # real one (plan D-10) and the reader can only tell if the row says so.
                    **self.attrs,
                }
            ),
        }


@dataclass
class IngestReport:
    """What an ingest actually did — including what it refused."""

    source_id: str
    parsed: int = 0
    unresolved_spaces: List[str] = field(default_factory=list)
    bad_rows: int = 0

    @property
    def usable(self) -> int:
        return self.parsed

    def describe(self) -> str:
        parts = [f"{self.parsed} record(s) parsed from {self.source_id}"]
        if self.unresolved_spaces:
            uniq = sorted(set(self.unresolved_spaces))
            parts.append(
                f"{len(self.unresolved_spaces)} row(s) name spaces this building does not "
                f"have and were SKIPPED, not guessed: {', '.join(uniq[:6])}"
                + ("…" if len(uniq) > 6 else "")
            )
        if self.bad_rows:
            parts.append(f"{self.bad_rows} row(s) had an unparseable time and were skipped")
        return "; ".join(parts)


def _pick(row: Dict[str, str], declared: Optional[str], kind: str) -> str:
    """The value for one logical field — declared name first, then a short default list."""
    if declared and declared in row:
        return str(row.get(declared) or "").strip()
    for candidate in _DEFAULT_FIELDS[kind]:
        if candidate in row and row[candidate]:
            return str(row[candidate]).strip()
    return ""


def _parse_dt(raw: str) -> Optional[datetime]:
    if not raw:
        return None
    text = raw.strip().replace("Z", "+00:00")
    for fmt in (None, "%Y-%m-%d %H:%M", "%Y-%m-%d %H:%M:%S", "%d/%m/%Y %H:%M"):
        try:
            return datetime.fromisoformat(text) if fmt is None else datetime.strptime(text, fmt)
        except ValueError:
            continue
    return None


def parse_csv(
    text: str,
    source_id: str,
    known_spaces: Sequence[str],
    *,
    space_field: str = "",
    start_field: str = "",
    end_field: str = "",
    title_field: str = "",
) -> tuple:
    """Parse a timetable/booking export into records. Returns (records, report).

    ``known_spaces`` are the building's own space local-names. A row naming anything else is
    collected into the report and dropped — a timetable that silently bound an unknown room to
    the nearest match would put confident wrong answers into the availability lane, and
    availability is one of the four entitlement claims that must never be inferred.
    """
    report = IngestReport(source_id=source_id)
    out: List[InstitutionalRecord] = []
    known = {s.lower(): s for s in known_spaces}

    for row in csv.DictReader(text.splitlines()):
        row = {(k or "").strip().lower(): v for k, v in row.items()}
        raw_space = _pick(row, space_field.lower(), "space")
        start = _parse_dt(_pick(row, start_field.lower(), "start"))
        if not raw_space or start is None:
            report.bad_rows += 1
            continue
        resolved = known.get(raw_space.lower())
        if resolved is None:
            report.unresolved_spaces.append(raw_space)
            continue
        out.append(
            InstitutionalRecord(
                space_local=resolved,
                start=start,
                end=_parse_dt(_pick(row, end_field.lower(), "end")),
                title=_pick(row, title_field.lower(), "title"),
                source_id=source_id,
            )
        )
    report.parsed = len(out)
    return out, report


class InstitutionalFeedAdapter:
    """Reads an institutional export and yields events-store rows.

    Deliberately shaped like the other feed adapters (a spec in, records out) so the registry
    dispatches it identically and a building declares it the same way it declares any feed.
    """

    def __init__(self, spec, input_root: str = "input"):
        self.spec = spec
        self._root = Path(input_root)

    @property
    def event_type(self) -> str:
        return SOURCE_KINDS.get(getattr(self.spec, "type", ""), "booking")

    def read(self, known_spaces: Sequence[str]) -> tuple:
        """(records, report). Missing file is an empty read with a stated reason, not a raise:
        a building that declared a source it has not yet dropped should decline honestly, not
        fail to boot."""
        path = getattr(self.spec, "path", "") or ""
        if not path:
            return [], IngestReport(source_id=self.spec.id, bad_rows=0)
        full = self._root / path
        if not full.exists():
            logger.info(f"[institutional] {self.spec.id}: {full} not present yet")
            return [], IngestReport(source_id=self.spec.id)
        return parse_csv(
            full.read_text(encoding="utf-8"),
            self.spec.id,
            known_spaces,
            space_field=getattr(self.spec, "space_field", "") or "",
            start_field=getattr(self.spec, "start_field", "") or "",
            end_field=getattr(self.spec, "end_field", "") or "",
            title_field=getattr(self.spec, "title_field", "") or "",
        )


def declared_systems(feed_specs: Sequence[Any]) -> List[str]:
    """The non-sensor systems this building has actually declared (V6-T09 / T25).

    The observability matrix reports "no booking system is connected" as a concrete R2 gap.
    That statement must come from the building's own config, not from a constant — otherwise
    it stays true in the report on the day someone connects one.
    """
    out: List[str] = []
    for spec in feed_specs or []:
        kind = getattr(spec, "type", "")
        if kind in SOURCE_KINDS and getattr(spec, "enabled", True):
            out.append("booking system")
    return sorted(set(out))


__all__ = [
    "SOURCE_KINDS",
    "IngestReport",
    "InstitutionalFeedAdapter",
    "InstitutionalRecord",
    "declared_systems",
    "parse_csv",
]
