#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Roll a building's record dates forward to the day the building is being asked about.

WHY THIS EXISTS
---------------
A register is authored once and then read for weeks. Every date in it ages while the
building it describes does not: measured 2026-09-17, the cleaning register said a
**twice-daily** washroom task was last completed 2026-09-03 and next due 2026-09-04.
Both halves are internally consistent and the lane answered from the right register —
but a reader sees a fortnight-old "next due" on a twice-daily task and concludes the
system is broken. The routing was never the defect; the clock was.

WHAT "STALE" MEANS HERE
-----------------------
Stale is **relative to the record's own cadence**, never to the calendar:

* a twice-daily cleaning task last completed 13 days ago is stale — 26 visits are missing;
* a five-yearly fixed-wiring inspection completed in 2024 is **not** stale, and moving it
  would be inventing an inspection that did not happen.

So every roll-forward is driven by the record's own frequency/interval field
(``serviceFrequency``, ``inspectionIntervalDays``, …) or, where it has none, by the gap
the record itself declares between its own "last" and "next" columns. A record with
neither is left exactly where it is.

WHAT IS DELIBERATELY NOT REFRESHED
----------------------------------
A register whose every row is current cannot demonstrate the questions it exists to
answer, and a building's open problems are the most-asked thing in it. So:

* **no declared status is ever changed.** The count of overdue / defective / outstanding
  / unverified / unevidenced / expired records per register is asserted identical before
  and after, and the run exits non-zero if it is not;
* an open record **stays as overdue as it already is** — its dates move by whole cadence
  periods anchored on its own DUE date, so it lands still due and still unmet, by the
  same margin it had. Freezing it instead would make it *grow* staler every day the
  register sits unread, which is the defect this tool exists to remove: a twice-daily
  washroom service reported 18 days overdue reads as a broken system, not an open job.
  ``--freeze-held`` leaves open records untouched instead;
* an annual test four months overdue does not move at all under that rule — four months
  is less than one cadence — so long-running open problems stay exactly where they are;
* a record with no cadence is left alone;
* no completion is ever recorded in the future.

Cadence periods are applied in **whole days** (or whole calendar months for month-based
cadences), so a Tuesday 02:10 night-patrol check stays a Tuesday 02:10 night-patrol
check, and the gap a row declares between "last" and "next" is preserved exactly.

SCOPE
-----
Completion / verification / observation predicates and the due dates paired with them.
Validity windows (``effectiveFrom``/``effectiveTo``), one-off event dates, approvals and
surveys are NOT cadenced obligations and are out of scope by construction — see
``EXCLUDED_PREDICATES`` for each one's reason.

    python scripts/refresh_record_dates.py                 # measure only (default)
    python scripts/refresh_record_dates.py --apply         # rewrite the files in place
    python scripts/refresh_record_dates.py --as-of 2026-09-18
"""

from __future__ import annotations

import argparse
import re
import sys
from dataclasses import dataclass, field
from datetime import date, datetime, timedelta
from pathlib import Path
from typing import Dict, List, Optional, Sequence, Tuple

REPO = Path(__file__).resolve().parents[1]
if str(REPO) not in sys.path:
    sys.path.insert(0, str(REPO))

try:
    import yaml
except ImportError:  # pragma: no cover - yaml ships with the stack
    yaml = None  # type: ignore


# ── the ontology's vocabulary (no building literals live in this file) ──────────────

#: Predicates that record *something having been done or seen*. These are what a running
#: building refreshes; everything else in a register is a fact about an agreement.
COMPLETION_PREDICATES = (
    "ontosage:lastCompleted",
    "ontosage:lastTestedOn",
    "ontosage:lastProvedOn",
    "ontosage:lastVisited",
    "ontosage:statusObservedAt",
    "ontosage:completedDate",
)

#: Due dates that belong to a completion predicate in the same record. They move by the
#: SAME number of days, so the interval the record declares survives untouched.
DUE_PREDICATES = (
    "ontosage:nextDue",
    "ontosage:nextTestDue",
    "ontosage:dueDate",
    "ontosage:reviewDue",
)

#: Why each excluded predicate is excluded. Printed by --explain so the omission is a
#: decision on the record rather than an oversight.
EXCLUDED_PREDICATES: Dict[str, str] = {
    "ontosage:calibratedOn": (
        "1-2 year cadence and the newest value is days old: not stale by its own "
        "interval. The overdue instruments among them are a deliberately open state."
    ),
    "ontosage:calibrationDueOn": "paired with calibratedOn, which is not stale.",
    "ontosage:approvedOn": "an approval is an event, not a recurring obligation.",
    "ontosage:evidenceDate": "the date evidence was produced; it does not recur.",
    "ontosage:surveyedOn": "a survey is valid until re-surveyed; it declares no cadence.",
    "ontosage:isolationProvenOn": "proving an isolation is an event with no declared cadence.",
    "ontosage:locationVerifiedOn": "a verified location stays verified; no cadence.",
    "ontosage:effectiveFrom": "a validity window, not a completion.",
    "ontosage:effectiveTo": "a validity window; moving it would renew expired agreements.",
    "ontosage:effectiveDate": "a one-off scheduled occurrence.",
    "ontosage:targetDate": "a target is a commitment to a fixed date.",
}

#: Statuses that mean the record is running normally and may be rolled forward.
CURRENT_STATUSES = frozenset(
    {
        "active",
        "current",
        "scheduled",
        "planned",
        "routine",
        "ready",
        "verified",
        "operational",
        "held",
        "on track",
        "done",
        "completed",
        "signed off",
    }
)

#: Statuses that mean the record is open, failing or unproven. Never moved.
HOLD_STATUSES = frozenset(
    {
        "overdue",
        "due",
        "due review",
        "defective",
        "degraded",
        "outstanding",
        "unverified",
        "unevidenced",
        "no evidence",
        "expired",
        "failed",
        "void",
        "open",
        "pending",
        "in progress",
        "suspended",
        "withdrawn",
        "cancelled",
        "restricted",
        "closed",
        "at risk",
        "monitoring",
        "handed over",
        "added",
        "notice served",
        "exception",
        "moved",
        "out_of_service",
        "out of service",
        "none",
        "",
    }
)

#: Cadence words → (days, months). Exactly one of the two is non-zero. Sub-daily words
#: divide a day evenly, so a whole-day shift keeps the time of day intact.
FREQUENCY_TERMS: Dict[str, Tuple[float, int]] = {
    "continuous": (1 / 24, 0),
    "hourly": (1 / 24, 0),
    "2-hourly": (1 / 12, 0),
    "two hourly": (1 / 12, 0),
    "4-hourly": (1 / 6, 0),
    "four hourly": (1 / 6, 0),
    "twice daily": (0.5, 0),
    "twice a day": (0.5, 0),
    "daily": (1.0, 0),
    "daily, overnight": (1.0, 0),
    "nightly": (1.0, 0),
    "each shift": (1.0, 0),
    "per shift": (1.0, 0),
    "twice weekly": (3.5, 0),
    "weekly": (7.0, 0),
    "fortnightly": (14.0, 0),
    "2 weekly": (14.0, 0),
    "monthly": (0, 1),
    "2 monthly": (0, 2),
    "quarterly": (0, 3),
    "3 monthly": (0, 3),
    "4 monthly": (0, 4),
    "6 monthly": (0, 6),
    "six monthly": (0, 6),
    "biannual": (0, 6),
    "annual": (0, 12),
    "annually": (0, 12),
    "yearly": (0, 12),
    "12 monthly": (0, 12),
    "biennial": (0, 24),
    "2 yearly": (0, 24),
    "5 yearly": (0, 60),
    "quinquennial": (0, 60),
}

#: Cadences that are not periodic at all. A row carrying one is never rolled.
ACADENT_TERMS = frozenset(
    {"event-driven", "event driven", "event only", "on request", "ad hoc", "as required"}
)

#: A status observation with no declared cadence refreshes daily: an estates helpdesk
#: that has not looked at an asset for a fortnight has not observed it. Ontology-level
#: default, not a property of any building.
OBSERVATION_CADENCE_DAYS = 1.0

_FRONT_MATTER = re.compile(r"\A\s*---\s*\n(.*?)\n---\s*\n", re.DOTALL)
_TABLE_ROW = re.compile(r"^\s*\|(.+)\|\s*$")
_TABLE_RULE = re.compile(r"^\s*\|[\s:|-]+\|\s*$")
_DATE = re.compile(r"\b(\d{4})-(\d{2})-(\d{2})(?:T(\d{2}):(\d{2}):(\d{2}))?\b")
_INT = re.compile(r"-?\d+")


# ── cadence arithmetic ─────────────────────────────────────────────────────────────


@dataclass(frozen=True)
class Cadence:
    """How often a record recurs. Days OR months, never both."""

    days: float = 0.0
    months: int = 0
    source: str = ""

    @property
    def is_periodic(self) -> bool:
        return self.days > 0 or self.months > 0

    def approx_days(self) -> float:
        return self.months * 30.44 if self.months else self.days


def parse_frequency(text: str) -> Optional[Cadence]:
    """A declared frequency word or interval phrase → a Cadence, or None.

    A *declared* non-periodic cadence ("event-driven") comes back as a Cadence that is
    not periodic — which is not the same as None. None means the record declared
    nothing, and only then may an interval be inferred from the gap it keeps. A clean
    laid on for one seminar recurs when that seminar recurs, and not on any other day.
    """
    if not text:
        return None
    raw = text.strip().lower()
    if not raw:
        return None
    if raw in ACADENT_TERMS:
        return Cadence(source=raw)
    if raw in FREQUENCY_TERMS:
        days, months = FREQUENCY_TERMS[raw]
        return Cadence(days=days, months=months, source=raw)
    # "every 90 days", "90", "90 days", "18 months"
    number = _INT.search(raw)
    if number:
        value = int(number.group())
        if value > 0:
            if "month" in raw:
                return Cadence(months=value, source=raw)
            if "week" in raw:
                return Cadence(days=value * 7.0, source=raw)
            if "year" in raw:
                return Cadence(months=value * 12, source=raw)
            if "day" in raw or raw.strip().isdigit():
                return Cadence(days=float(value), source=raw)
    # Longest declared term contained in the phrase ("weekly, overnight").
    for term in sorted(FREQUENCY_TERMS, key=len, reverse=True):
        if term in raw:
            days, months = FREQUENCY_TERMS[term]
            return Cadence(days=days, months=months, source=raw)
    return None


def add_months(moment: datetime, months: int) -> datetime:
    """Advance by whole calendar months, keeping the day of month where it exists."""
    total = (moment.year * 12 + moment.month - 1) + months
    year, month = divmod(total, 12)
    month += 1
    day = moment.day
    while day > 1:
        try:
            return moment.replace(year=year, month=month, day=day)
        except ValueError:
            day -= 1
    return moment.replace(year=year, month=month, day=1)


def whole_day_shift(anchor: datetime, cadence: Cadence, as_of: datetime) -> int:
    """Whole days to advance ``anchor`` so it lands inside one cadence of ``as_of``.

    Always a whole number of days, so the time of day, and the weekday for any cadence
    that is a multiple of a week, survive the shift. Never advances past ``as_of``.
    """
    if not cadence.is_periodic or anchor >= as_of:
        return 0
    if cadence.months:
        moved = anchor
        while True:
            nxt = add_months(moved, cadence.months)
            if nxt > as_of:
                break
            moved = nxt
        return (moved.date() - anchor.date()).days
    step = cadence.days
    age_days = (as_of - anchor).total_seconds() / 86400.0
    if age_days <= step:
        return 0
    if step <= 1.0:
        # Sub-daily and daily cadences divide a day evenly: the largest whole-day shift
        # that does not pass as_of is simply the whole days between them.
        return int(age_days)
    periods = int(age_days // step)
    return int((periods * step) // 1)


def is_weekday(moment: datetime) -> bool:
    return moment.weekday() < 5


def keep_working_day(anchor: datetime, shift_days: int, cadence: Cadence) -> int:
    """Pull a shift back to Friday when a weekday record would land on a weekend.

    Only for cadences of a week or more: a daily or twice-daily task genuinely runs at
    the weekend, and a nightly patrol does not care which day it is.
    """
    if shift_days <= 0 or cadence.approx_days() < 7:
        return shift_days
    if not is_weekday(anchor):
        return shift_days
    landed = anchor + timedelta(days=shift_days)
    while not is_weekday(landed) and shift_days > 0:
        shift_days -= 1
        landed = anchor + timedelta(days=shift_days)
    return shift_days


def normalise_status(text: str) -> str:
    return re.sub(r"\s+", " ", (text or "").strip().lower()).strip(".")


def status_is_held(text: str) -> bool:
    """True when the record's own status says it is open, failing or unproven."""
    token = normalise_status(text)
    if token in CURRENT_STATUSES:
        return False
    if token in HOLD_STATUSES:
        return True
    # An unrecognised status is held. A register is allowed to invent a word; silently
    # rolling a record whose state we cannot read is how an open problem disappears.
    for hold in HOLD_STATUSES:
        if hold and hold in token:
            return True
    return True


# ── a rewritable date token ────────────────────────────────────────────────────────


@dataclass
class Change:
    file: Path
    record: str
    predicate: str
    before: str
    after: str
    reason: str


@dataclass
class Report:
    changes: List[Change] = field(default_factory=list)
    held: Dict[str, int] = field(default_factory=dict)
    held_moved: Dict[str, int] = field(default_factory=dict)
    fresh: Dict[str, int] = field(default_factory=dict)
    skipped_no_cadence: Dict[str, int] = field(default_factory=dict)
    status_before: Dict[str, Dict[str, int]] = field(default_factory=dict)
    status_after: Dict[str, Dict[str, int]] = field(default_factory=dict)
    errors: List[str] = field(default_factory=list)

    def bump(self, bucket: Dict[str, int], key: str) -> None:
        bucket[key] = bucket.get(key, 0) + 1


def parse_moment(text: str) -> Optional[datetime]:
    match = _DATE.search(text or "")
    if not match:
        return None
    y, mo, d, hh, mm, ss = match.groups()
    return datetime(int(y), int(mo), int(d), int(hh or 0), int(mm or 0), int(ss or 0))


def render_like(original: str, moment: datetime) -> str:
    """Re-render ``moment`` in the exact shape the original token used."""
    match = _DATE.search(original)
    if not match:
        return original
    token = (
        moment.strftime("%Y-%m-%dT%H:%M:%S")
        if match.group(4) is not None
        else moment.strftime("%Y-%m-%d")
    )
    return original[: match.start()] + token + original[match.end() :]


# ── register documents (markdown tables) ───────────────────────────────────────────


def load_mappings(mappings_dir: Path) -> Dict[str, dict]:
    out: Dict[str, dict] = {}
    if yaml is None or not mappings_dir.is_dir():
        return out
    for path in sorted(mappings_dir.glob("*.yaml")):
        try:
            data = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
        except Exception:
            continue
        record_type = data.get("record_type")
        if record_type:
            out[str(record_type)] = data
    return out


def _column_roles(mapping: dict) -> Tuple[Dict[str, str], Optional[str], Dict[str, str]]:
    """(date column → predicate, status column, cadence column → predicate)."""
    dates: Dict[str, str] = {}
    cadences: Dict[str, str] = {}
    status: Optional[str] = None
    for name, spec in (mapping.get("columns") or {}).items():
        if not isinstance(spec, dict):
            continue
        predicate = str(spec.get("predicate") or "")
        datatype = str(spec.get("datatype") or "")
        if datatype in ("xsd:date", "xsd:dateTime"):
            dates[name] = predicate
        if predicate == "ontosage:recordStatus":
            status = name
        if re.search(r"(Frequency|Interval(Days|Months)?|Cadence)$", predicate):
            cadences[name] = predicate
    return dates, status, cadences


def _split_cells(line: str) -> List[str]:
    """Split a table row into its raw segments, padding and all."""
    return line.split("|")


def _cell(parts: List[str], index: int) -> str:
    slot = index + 1
    return parts[slot].strip() if 0 <= slot < len(parts) else ""


def refresh_register(
    path: Path,
    mappings: Dict[str, dict],
    as_of: datetime,
    report: Report,
    freeze_held: bool = False,
) -> Optional[str]:
    """Roll one record document forward. Returns the new text, or None if unchanged."""
    text = path.read_text(encoding="utf-8")
    head = _FRONT_MATTER.match(text)
    if not head or yaml is None:
        return None
    try:
        front = yaml.safe_load(head.group(1)) or {}
    except Exception:
        return None
    mapping = mappings.get(str(front.get("record_type") or ""))
    if not mapping:
        return None
    date_cols, status_col, cadence_cols = _column_roles(mapping)
    rollable = {
        name: pred
        for name, pred in date_cols.items()
        if pred in COMPLETION_PREDICATES or pred in DUE_PREDICATES
    }
    completion_cols = [n for n, p in rollable.items() if p in COMPLETION_PREDICATES]
    due_cols = [n for n, p in rollable.items() if p in DUE_PREDICATES]
    if not rollable:
        return None

    label = path.name
    lines = text.splitlines(keepends=True)
    changed = False
    header: List[str] = []
    index = 0
    while index < len(lines):
        line = lines[index]
        nxt = lines[index + 1] if index + 1 < len(lines) else ""
        if _TABLE_ROW.match(line) and _TABLE_RULE.match(nxt):
            header = [c.strip() for c in line.strip().strip("|").split("|")]
            index += 2
            continue
        if not header or not _TABLE_ROW.match(line) or _TABLE_RULE.match(line):
            index += 1
            continue
        if not any(col in header for col in rollable):
            index += 1
            continue

        parts = _split_cells(line)
        status_text = _cell(parts, header.index(status_col)) if status_col in header else ""
        report.status_before.setdefault(label, {})
        key = normalise_status(status_text) or "(none)"
        report.status_before[label][key] = report.status_before[label].get(key, 0) + 1

        held = bool(status_col) and status_is_held(status_text)
        if held and freeze_held:
            report.bump(report.held, label)
            index += 1
            continue

        cadence: Optional[Cadence] = None
        for name in cadence_cols:
            if name in header:
                cadence = parse_frequency(_cell(parts, header.index(name)))
                if cadence:
                    break

        anchor_col = next((c for c in completion_cols if c in header), None)
        anchor_raw = _cell(parts, header.index(anchor_col)) if anchor_col else ""
        anchor = parse_moment(anchor_raw)
        due_col = next((c for c in due_cols if c in header), None)
        due_raw = _cell(parts, header.index(due_col)) if due_col else ""
        due = parse_moment(due_raw)

        if cadence is None and anchor and due and due > anchor:
            # The record declares its own interval by the gap it keeps.
            cadence = Cadence(days=(due - anchor).total_seconds() / 86400.0, source="declared gap")
        if cadence is None or not cadence.is_periodic:
            report.bump(report.skipped_no_cadence, label)
            index += 1
            continue

        # What the shift is measured from. A record running normally is anchored on its
        # last completion, so the completion lands inside one cadence of now. An OPEN
        # record is anchored on the date it was DUE, so it lands still due and still
        # unmet — as overdue as it already was, never less, never more. An open record
        # with no due date has nothing to hold its margin against, so it is left alone.
        # A register with only a "next" column (a collection round, say) is anchored on
        # that: the last service is one cadence before the next one it promises.
        if held:
            pivot = due
        elif anchor is not None:
            pivot = anchor
        elif due is not None:
            pivot = due - timedelta(days=cadence.approx_days())
        else:
            pivot = None
        if pivot is None:
            report.bump(report.held if held else report.skipped_no_cadence, label)
            index += 1
            continue

        shift = whole_day_shift(pivot, cadence, as_of)
        shift = keep_working_day(pivot, shift, cadence)
        if shift <= 0:
            report.bump(report.held if held else report.fresh, label)
            index += 1
            continue
        if held:
            report.bump(report.held_moved, label)

        record_id = _cell(parts, 0)
        for column, predicate in rollable.items():
            if column not in header:
                continue
            slot = header.index(column) + 1
            if slot >= len(parts):
                continue
            moment = parse_moment(parts[slot])
            if moment is None:
                continue
            moved = moment + timedelta(days=shift)
            if predicate in COMPLETION_PREDICATES and moved > as_of:
                continue  # never record work as done in the future
            before = parts[slot].strip()
            parts[slot] = render_like(parts[slot], moved)
            report.changes.append(
                Change(
                    file=path,
                    record=record_id,
                    predicate=predicate,
                    before=before,
                    after=parts[slot].strip(),
                    reason=f"{cadence.source or 'declared gap'} +{shift}d",
                )
            )
            changed = True
        lines[index] = "|".join(parts)
        index += 1

    return "".join(lines) if changed else None


# ── TTL records ────────────────────────────────────────────────────────────────────

_TTL_SUBJECT = re.compile(r"^(\S+)\s")


def _ttl_blocks(text: str) -> List[Tuple[int, int, str]]:
    """(start line, end line exclusive, block text) for each top-level subject."""
    lines = text.splitlines(keepends=True)
    blocks: List[Tuple[int, int, str]] = []
    start: Optional[int] = None
    for i, line in enumerate(lines):
        stripped = line.strip()
        if not stripped or stripped.startswith(("#", "@")):
            continue
        if start is None and not line[:1].isspace():
            start = i
        if start is not None and stripped.endswith("."):
            blocks.append((start, i + 1, "".join(lines[start : i + 1])))
            start = None
    return blocks


def _ttl_value(block: str, predicate: str) -> str:
    match = re.search(re.escape(predicate) + r"\s+(\"[^\"]*\"|\S+)", block)
    return match.group(1).strip('"') if match else ""


def _compliance_family(subject: str) -> str:
    return re.sub(r"_(?:\d+|current)$", "", subject)


def refresh_ttl(path: Path, as_of: datetime, report: Report) -> Optional[str]:
    """Roll observation and compliance-cycle dates in one TTL forward."""
    text = path.read_text(encoding="utf-8")
    if not any(p in text for p in COMPLETION_PREDICATES):
        return None
    label = path.name
    lines = text.splitlines(keepends=True)
    blocks = _ttl_blocks(text)

    # A compliance register's rows are cycles of ONE recurring obligation. They move as a
    # series: freezing the open cycle while its own history advances would place a
    # completed cycle after the cycle that is still open, which no register can mean.
    family_shift: Dict[str, int] = {}
    families: Dict[str, List[Tuple[int, int, str]]] = {}
    for start, end, block in blocks:
        if "ontosage:completedDate" not in block and "ontosage:dueDate" not in block:
            continue
        subject = _TTL_SUBJECT.match(block)
        if not subject:
            continue
        families.setdefault(_compliance_family(subject.group(1)), []).append((start, end, block))
    for family, members in families.items():
        dues = sorted(
            m for m in (parse_moment(_ttl_value(b, "ontosage:dueDate")) for _, _, b in members) if m
        )
        completions = [
            m
            for m in (parse_moment(_ttl_value(b, "ontosage:completedDate")) for _, _, b in members)
            if m
        ]
        if len(dues) < 2 or not completions:
            continue
        gaps = sorted((dues[i + 1] - dues[i]).days for i in range(len(dues) - 1))
        step = gaps[len(gaps) // 2]
        if step <= 0:
            continue
        cadence = Cadence(days=float(step), source=f"{step}-day cycle")
        newest = max(completions)
        family_shift[family] = whole_day_shift(newest, cadence, as_of)

    changed = False
    for start, end, block in blocks:
        subject_match = _TTL_SUBJECT.match(block)
        subject = subject_match.group(1) if subject_match else ""
        family = _compliance_family(subject)
        report.status_before.setdefault(label, {})
        state = (
            _ttl_value(block, "ontosage:recordStatus")
            or _ttl_value(block, "ontosage:statusValue")
            or "(none)"
        )
        key = normalise_status(state) or "(none)"
        report.status_before[label][key] = report.status_before[label].get(key, 0) + 1

        shift = 0
        cadence_source = ""
        if family in family_shift:
            shift = family_shift[family]
            cadence_source = "compliance cycle"
        elif "ontosage:statusObservedAt" in block:
            if status_is_held(state):
                report.bump(report.held, label)
                continue
            observed = parse_moment(_ttl_value(block, "ontosage:statusObservedAt"))
            if observed is None:
                continue
            cadence = Cadence(days=OBSERVATION_CADENCE_DAYS, source="daily observation")
            shift = whole_day_shift(observed, cadence, as_of)
            cadence_source = cadence.source
        else:
            report.bump(report.skipped_no_cadence, label)
            continue

        if shift <= 0:
            report.bump(report.fresh, label)
            continue

        for index in range(start, end):
            line = lines[index]
            for predicate in COMPLETION_PREDICATES + DUE_PREDICATES:
                if predicate not in line:
                    continue
                moment = parse_moment(line)
                if moment is None:
                    continue
                moved = moment + timedelta(days=shift)
                if predicate in COMPLETION_PREDICATES and moved > as_of:
                    continue
                before = moment.isoformat()
                lines[index] = render_like(line, moved)
                report.changes.append(
                    Change(
                        file=path,
                        record=subject,
                        predicate=predicate,
                        before=before,
                        after=moved.isoformat(),
                        reason=f"{cadence_source} +{shift}d",
                    )
                )
                changed = True
                break

    return "".join(lines) if changed else None


# ── verification ───────────────────────────────────────────────────────────────────


def count_statuses(path: Path, mappings: Dict[str, dict]) -> Dict[str, int]:
    """Declared statuses in one file, however it stores them."""
    counts: Dict[str, int] = {}
    text = path.read_text(encoding="utf-8")
    if path.suffix == ".ttl":
        for match in re.finditer(r"ontosage:(?:recordStatus|statusValue)\s+\"([^\"]*)\"", text):
            token = normalise_status(match.group(1)) or "(none)"
            counts[token] = counts.get(token, 0) + 1
        return counts
    head = _FRONT_MATTER.match(text)
    if not head or yaml is None:
        return counts
    try:
        front = yaml.safe_load(head.group(1)) or {}
    except Exception:
        return counts
    mapping = mappings.get(str(front.get("record_type") or ""))
    if not mapping:
        return counts
    _, status_col, _ = _column_roles(mapping)
    if not status_col:
        return counts
    lines = text.splitlines()
    header: List[str] = []
    for i, line in enumerate(lines):
        nxt = lines[i + 1] if i + 1 < len(lines) else ""
        if _TABLE_ROW.match(line) and _TABLE_RULE.match(nxt):
            header = [c.strip() for c in line.strip().strip("|").split("|")]
            continue
        if not header or not _TABLE_ROW.match(line) or _TABLE_RULE.match(line):
            continue
        if status_col not in header:
            continue
        token = normalise_status(_cell(_split_cells(line), header.index(status_col))) or "(none)"
        counts[token] = counts.get(token, 0) + 1
    return counts


def open_state_count(counts: Dict[str, int]) -> int:
    return sum(n for token, n in counts.items() if token and status_is_held(token))


# ── driver ─────────────────────────────────────────────────────────────────────────


def resolve_input_dir(explicit: Optional[str]) -> Path:
    """The active building's input directory — from config, never from a literal."""
    if explicit:
        return Path(explicit)
    try:
        from shared.building_paths import resolve_building_dir  # type: ignore
        from shared.config import settings  # type: ignore

        found = resolve_building_dir(settings.BUILDING_ID, "documents", REPO / "input")
        if found:
            return Path(found).parent
    except Exception:
        pass
    return REPO / "input"


def run(
    input_dir: Path,
    mappings_dir: Path,
    as_of: datetime,
    apply: bool,
    freeze_held: bool = False,
) -> Tuple[Report, int]:
    mappings = load_mappings(mappings_dir)
    report = Report()
    targets: List[Tuple[Path, Optional[str]]] = []

    for path in sorted((input_dir / "documents").glob("*.md")):
        before = count_statuses(path, mappings)
        new_text = refresh_register(path, mappings, as_of, report, freeze_held)
        targets.append((path, new_text))
        report.status_before[path.name] = before
    for path in sorted(input_dir.glob("*.ttl")):
        before = count_statuses(path, mappings)
        new_text = refresh_ttl(path, as_of, report)
        targets.append((path, new_text))
        report.status_before[path.name] = before

    written = 0
    for path, new_text in targets:
        if new_text is None:
            continue
        if apply:
            path.write_text(new_text, encoding="utf-8", newline="")
            written += 1
        after = (
            count_statuses(path, mappings) if apply else _counts_of_text(path, new_text, mappings)
        )
        report.status_after[path.name] = after
        before = report.status_before.get(path.name, {})
        if open_state_count(before) != open_state_count(after) or before != after:
            report.errors.append(
                f"{path.name}: declared statuses changed "
                f"{sorted(before.items())} -> {sorted(after.items())}"
            )
    return report, written


def _counts_of_text(path: Path, text: str, mappings: Dict[str, dict]) -> Dict[str, int]:
    """Status counts for a candidate rewrite, without touching the disk."""
    import tempfile

    with tempfile.TemporaryDirectory() as tmp:
        probe = Path(tmp) / path.name
        probe.write_text(text, encoding="utf-8", newline="")
        return count_statuses(probe, mappings)


def _print_report(report: Report, as_of: datetime, apply: bool) -> None:
    by_file: Dict[str, Dict[str, List[Change]]] = {}
    for change in report.changes:
        by_file.setdefault(change.file.name, {}).setdefault(change.predicate, []).append(change)

    print(
        f"\nrecord dates as of {as_of.date().isoformat()} "
        f"({'APPLIED' if apply else 'DRY RUN — pass --apply to write'})\n"
    )
    if not by_file:
        print("  nothing is stale by its own cadence.")
    for name in sorted(by_file):
        counts = report.status_before.get(name, {})
        print(f"  {name}")
        for predicate in sorted(by_file[name]):
            changes = by_file[name][predicate]
            olds = sorted(c.before for c in changes)
            news = sorted(c.after for c in changes)
            reasons = sorted({c.reason for c in changes})
            shown = "; ".join(reasons[:3]) + ("; …" if len(reasons) > 3 else "")
            print(
                f"    {predicate:30s} n={len({c.record for c in changes}):4d} "
                f"records  {olds[0][:10]}..{olds[-1][:10]}  ->  "
                f"{news[0][:10]}..{news[-1][:10]}"
            )
            print(f"    {'':30s} by: {shown}")
        held = report.held.get(name, 0)
        held_moved = report.held_moved.get(name, 0)
        fresh = report.fresh.get(name, 0)
        nocad = report.skipped_no_cadence.get(name, 0)
        print(
            f"    open records: {held + held_moved} "
            f"({held_moved} kept at the same overdue margin, {held} left exactly as they are)"
            f"   already fresh: {fresh}   no cadence: {nocad}"
        )
        print(f"    declared statuses: {dict(sorted(counts.items()))}")
        after = report.status_after.get(name)
        if after is not None:
            same = "unchanged" if after == counts else "CHANGED"
            print(f"    after              : {dict(sorted(after.items()))}  [{same}]")
        print()

    print(f"  {len(report.changes)} date literals across {len(by_file)} files")
    if report.errors:
        print("\n  FAILED — a declared status moved, which this tool must never do:")
        for line in report.errors:
            print(f"    {line}")


def main(argv: Optional[Sequence[str]] = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--apply", action="store_true", help="write the files (default: measure)")
    parser.add_argument("--dry-run", action="store_true", default=True, help=argparse.SUPPRESS)
    parser.add_argument("--as-of", default=None, help="reference date (default: today)")
    parser.add_argument("--input-dir", default=None, help="the active building's input directory")
    parser.add_argument(
        "--mappings",
        default=str(REPO / "ontology" / "record_documents"),
        help="record-document mappings directory",
    )
    parser.add_argument(
        "--explain", action="store_true", help="print why each excluded predicate is excluded"
    )
    parser.add_argument(
        "--freeze-held",
        action="store_true",
        help="leave open/overdue records untouched instead of keeping their overdue margin",
    )
    args = parser.parse_args(argv)

    if args.explain:
        print("\npredicates deliberately NOT rolled forward:\n")
        for predicate, reason in sorted(EXCLUDED_PREDICATES.items()):
            print(f"  {predicate:32s} {reason}")
        print()

    as_of = (
        datetime.combine(date.fromisoformat(args.as_of), datetime.min.time())
        if args.as_of
        else datetime.combine(date.today(), datetime.min.time())
    ) + timedelta(hours=23, minutes=59, seconds=59)

    input_dir = resolve_input_dir(args.input_dir)
    if not input_dir.is_dir():
        print(f"no input directory at {input_dir}; activate a building first")
        return 2

    report, written = run(input_dir, Path(args.mappings), as_of, args.apply, args.freeze_held)
    _print_report(report, as_of, args.apply)
    if report.errors:
        return 1
    if args.apply:
        print(f"\n  {written} files rewritten. Re-lift the registers and re-upload the TTLs.")
    return 0


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
