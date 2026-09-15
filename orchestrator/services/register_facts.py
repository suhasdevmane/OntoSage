"""Facts about a register, counted in code, handed to the narration verbatim (BUG-581).

The whole-register handover gives the model every row and tells it not to re-derive a status
from dates. Rehearsed three times through Open WebUI on 2026-09-15, the same question over the
same 24 work orders produced three answers — "9 open, all 9 overdue" (the register records no
due date at all), "the records do not say", and "3 open" — and a refuge-point question listed
an evacuation CHAIR as a defective refuge point one run in three. The rows were right each
time; the counting and the filtering were the model's, and an instruction does not make a
language model count.

So the bookkeeping is done here, from every row, and the narration is told to use it:
  * how many records hold each recorded status;
  * for every ``…Kind`` column, the same split within each kind, with record ids — so
    "which refuge points are defective" is a lookup, not a filter the model performs;
  * when the question asks what is OVERDUE: either the dates a ``…Due`` column holds that have
    passed, or a plain statement that nothing in the register records a due date.

Nothing here knows a register, a class or a building: columns are recognised by the shape of
their names (``recordStatus``, a ``Kind`` suffix, a ``Due`` suffix or ``deadline``), which is
how the record-document lifter names them for every register it lifts.
"""

from __future__ import annotations

import re
from collections import Counter, defaultdict
from datetime import date
from typing import Dict, List, Optional

STATUS = "recordStatus"
ID_FIELDS = ("recordId", "label")
MAX_KIND_VALUES = 12
MAX_IDS_LISTED = 15

_OVERDUE_RE = re.compile(r"\b(overdue|past\s+due|late|behind\s+schedule|out\s+of\s+date|lapsed)\b", re.I)
_DUE_COLUMN_RE = re.compile(r"(due|deadline)$", re.I)
_CLOSED_STATUSES = {"completed", "closed", "void", "cancelled", "canceled", "withdrawn", "retired"}


def _value(row: Dict, field: str) -> str:
    cell = row.get(field)
    if isinstance(cell, dict):
        cell = cell.get("value")
    return str(cell).strip() if cell not in (None, "") else ""


def _ident(row: Dict) -> str:
    for field in ID_FIELDS:
        v = _value(row, field)
        if v:
            return v
    return "?"


def _split(rows: List[Dict]) -> str:
    counts = Counter(_value(r, STATUS) or "(no status)" for r in rows)
    ordered = sorted(counts.items(), key=lambda kv: (-kv[1], kv[0]))
    largest = ordered[0][0] if ordered else ""
    parts = []
    for status, n in ordered:
        part = f"{status} {n}"
        if status != largest and n <= MAX_IDS_LISTED:
            ids = sorted(_ident(r) for r in rows if (_value(r, STATUS) or "(no status)") == status)
            part += f" ({', '.join(ids)})"
        parts.append(part)
    return ", ".join(parts)


def register_facts(rows: List[Dict], question: str, today: Optional[date] = None) -> str:
    """A short block of counted facts, or "" when the rows carry no recorded status."""
    if not rows or not any(_value(r, STATUS) for r in rows):
        return ""
    columns = sorted({k for r in rows for k in r.keys()})
    lines = [f"- Records held: {len(rows)}.", f"- By recorded status: {_split(rows)}."]

    for col in columns:
        if not col.lower().endswith("kind"):
            continue
        groups: Dict[str, List[Dict]] = defaultdict(list)
        for r in rows:
            groups[_value(r, col) or "(none)"].append(r)
        if len(groups) < 2 or len(groups) > MAX_KIND_VALUES:
            continue
        lines.append(f"- By {col}, then recorded status (a record of one kind is NOT another):")
        for kind in sorted(groups):
            lines.append(f"  - {kind}: {_split(groups[kind])}")

    if _OVERDUE_RE.search(question or ""):
        due_cols = [c for c in columns if _DUE_COLUMN_RE.search(c)]
        overdue_status = any("overdue" in _value(r, STATUS).lower() for r in rows)
        if not due_cols and not overdue_status:
            lines.append(
                "- OVERDUE IS NOT RECORDED: no status is 'overdue' and no field holds a due date. "
                "Say so in the first sentence; do not treat an effective, start or created date "
                "as a deadline."
            )
        elif due_cols and today is not None:
            for col in due_cols:
                past = []
                for r in rows:
                    raw = _value(r, col)[:10]
                    if _value(r, STATUS).lower() in _CLOSED_STATUSES:
                        continue
                    try:
                        if date.fromisoformat(raw) < today:
                            past.append(f"{_ident(r)} ({raw})")
                    except ValueError:
                        continue
                recorded = sorted(
                    _ident(r) for r in rows if "overdue" in _value(r, STATUS).lower()
                )
                not_marked = [p for p in sorted(past) if p.split(" (")[0] not in recorded]
                lines.append(
                    f"- {col} already passed on {today.isoformat()} for {len(past)} record(s) not "
                    f"closed" + (f": {', '.join(sorted(past)[:MAX_IDS_LISTED])}." if past else ".")
                )
                if not_marked:
                    # Fire exits whose test date was yesterday, still recorded "active": the
                    # narration reported only the two marked overdue and called the rest "not
                    # overdue". Both facts are true and the reader needs both.
                    lines.append(
                        f"- STATE BOTH: {len(recorded)} record(s) have the recorded status "
                        f"'overdue'; {len(not_marked)} more are past their {col} while their "
                        f"recorded status is not 'overdue' ({', '.join(not_marked[:MAX_IDS_LISTED])}). "
                        "Never call those 'not overdue'."
                    )
    return "\n".join(lines)


_CODE_ONLY_LINE = re.compile(r"^\s*\**\s*[A-Z]{1,8}-\d[\w.-]*(\s*,\s*[\w.-]+)*\s*\**\s*$")


def strip_leaked_code_line(text: str) -> str:
    """Drop a first line that is nothing but record codes ("EV-003, 3", "**EV-003, EV-007**").

    The narration sometimes opens with a bare list of the ids it is about to discuss — a
    scratch line, not a sentence — and it reached the user as the answer's headline.
    """
    lines = (text or "").split("\n")
    for i, line in enumerate(lines):
        if not line.strip():
            continue
        if _CODE_ONLY_LINE.match(line):
            return "\n".join(lines[:i] + lines[i + 1 :]).lstrip("\n")
        break
    return text
