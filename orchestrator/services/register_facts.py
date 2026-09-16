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

#: Fields the lifter stamps on every record — provenance, not content anyone asks about.
_PROVENANCE_FIELDS = frozenset(
    {
        "recordId", "recordOwner", "recordVersion", "owningAuthority", "retrievedAt",
        "derivedFromDocument", "liftedByMapping", "isSimulated", "effectiveFrom", "label",
        "comment", "type",
    }
)


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


#: A question about the ABSENCE of something: "which have no X", "without X", "lack X".
_ASKS_ABSENCE_RE = re.compile(
    r"\b(?:no|without|lack|lacks|lacking|missing|absent|none|not\s+(?:have|covered|provided))\b",
    re.IGNORECASE,
)

#: A recorded value that SAYS the thing is absent. "No cover, next working day" is a real
#: answer to "what happens out of hours", and it means there is none.
_NONE_LIKE_RE = re.compile(
    r"^\s*(?:no\b|none\b|nil\b|n/?a\b|not\s+(?:available|provided|recorded|applicable)"
    r"|without\b|-{1,2}$)",
    re.IGNORECASE,
)


def _absence_lines(rows, col, question):
    """Records whose value for ``col`` SAYS there is none, when the question asks for those."""
    if not _ASKS_ABSENCE_RE.search(question or ""):
        return []
    absent = [r for r in rows if _NONE_LIKE_RE.match(_value(r, col))]
    if not absent:
        return []
    ids = sorted(_ident(r) for r in absent)
    shown = ", ".join(ids[:MAX_IDS_LISTED])
    return [
        f"  - of those, {len(absent)} record(s) state that there is NONE (a value such as "
        f'"{_value(absent[0], col)[:40]}"): {shown}. A recorded value can say the thing is '
        f"absent; those records are the answer to a question asking which have no {col}."
    ]


#: "how long since", "longest blind interval", "rarely visited", "overdue for a visit".
_ELAPSED_RE = re.compile(
    r"\b(?:longest|rarely|seldom|blind|how\s+long\s+since|since\s+(?:it|they)\s+(?:was|were)"
    r"|not\s+been\s+(?:visited|inspected|checked)|unvisited|uninspected)\b",
    re.IGNORECASE,
)

#: A date column recording when something last happened, and an interval column saying how
#: often it should. Registers record the pair instead of a due date about as often as not.
_LAST_COLUMN_RE = re.compile(r"^last[A-Z_]|lastvisited|lastcompleted|lasttested", re.IGNORECASE)
_INTERVAL_COLUMN_RE = re.compile(r"interval", re.IGNORECASE)


def _elapsed_lines(rows, columns, question, today):
    """How long since each record was last seen, and by how far that passes its interval.

    A register that records `last_visited` + `inspection_interval_days` states the answer to
    "which rarely visited areas have the longest blind interval" only after a subtraction, and
    the narration did the wrong one: it ranked by the interval VALUE (365 days) and named a
    meter that is not yet due, over an exhaust fan 369 days unseen against a 180-day interval.
    """
    if today is None or not _ELAPSED_RE.search(question or ""):
        return []
    last_cols = [c for c in columns if _LAST_COLUMN_RE.search(c)]
    interval_cols = [c for c in columns if _INTERVAL_COLUMN_RE.search(c)]
    if not last_cols:
        return []
    col = last_cols[0]
    interval_col = interval_cols[0] if interval_cols else ""
    scored = []
    for r in rows:
        raw = _value(r, col)[:10]
        try:
            elapsed = (today - date.fromisoformat(raw)).days
        except ValueError:
            continue
        over = None
        if interval_col:
            try:
                over = elapsed - int(float(_value(r, interval_col)))
            except (TypeError, ValueError):
                over = None
        scored.append((elapsed, over, _ident(r), raw))
    if not scored:
        return []
    scored.sort(key=lambda t: -t[0])
    out = [
        f"- Days since {col} on {today.isoformat()} (computed by the system; longest first): "
        + "; ".join(
            f"{ident} {elapsed}d"
            + (f" ({over:+d}d against its {interval_col})" if over is not None else "")
            for elapsed, over, ident, _raw in scored[:8]
        )
        + "."
    ]
    if interval_col:
        beyond = sorted(
            (t for t in scored if t[1] is not None and t[1] > 0), key=lambda t: -t[1]
        )
        if beyond:
            out.append(
                f"- PAST its {interval_col}: "
                + "; ".join(f"{ident} by {over}d" for _e, over, ident, _r in beyond[:8])
                + ". 'Longest unseen' means this, not the largest interval VALUE: a record with a "
                "long interval that is still within it is not overdue."
            )
    return out


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

    # A FIELD THE QUESTION NAMES, COUNTED (BUG-605). "Which HVAC systems run outside normal
    # hours, and is each exception approved?" answered four, six and seven across three runs of
    # a register holding approvedException on exactly 7 of 10 records. A field present on SOME
    # records is exactly the filter a language model gets wrong, so where the question names one
    # the system counts it and lists the records.
    asked = set(re.findall(r"[a-z]+", (question or "").lower()))
    for col in columns:
        if col == STATUS or col in _PROVENANCE_FIELDS:
            continue
        col_words = {w.lower() for w in re.findall(r"[A-Za-z][a-z]+", col)}
        if not (asked & col_words):
            continue
        filled = [r for r in rows if _value(r, col)]
        if not filled:
            continue  # nothing recorded at all: no filter to get wrong
        if len(filled) != len(rows):
            ids = sorted(_ident(r) for r in filled)
            line = f"- {col} is recorded for {len(filled)} of {len(rows)} records"
            if len(ids) <= MAX_IDS_LISTED:
                line += f": {', '.join(ids)}"
            lines.append(line + ". State that count; do not recount from the rows.")
        # Checked even when the column is filled everywhere: a present value can still SAY
        # there is none, which is the department case (BUG-613).
        lines.extend(_absence_lines(rows, col, question))

    # A QUESTION ASKING WHICH RECORDS HAVE **NO** X (BUG-613). "Which departments have no
    # out-of-hours route?" was answered "every department has an out-of-hours route value
    # recorded" — true of the FIELD and false of the building: nine of the twenty say "No
    # cover, next working day". A field that is present can still say the thing is absent, and
    # the words that say so are the ordinary English ones.
    # A QUESTION WORD THAT IS ALSO A RECORDED STATUS (CAVEAT-604). "Which teaching sessions are
    # scheduled in Room 1.06?" answered six — the records whose recordStatus is "scheduled" —
    # of the 23 the room holds. Both readings are defensible, which is exactly why the answer
    # has to carry the total AND the split rather than silently pick one.
    statuses = {_value(r, STATUS).lower() for r in rows if _value(r, STATUS)}
    overlap = sorted(statuses & asked)
    if overlap:
        lines.append(
            f"- CAREFUL: {', '.join(repr(w) for w in overlap)} is also a recorded STATUS here. "
            f"The rows in scope are {len(rows)} in total ({_split(rows)}). If the question's "
            f"word describes the records themselves rather than their status, answer with the "
            f"total and give the split; never report the status count alone as the total."
        )

    lines.extend(_elapsed_lines(rows, columns, question, today))

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


def passed_due_not_marked(rows: List[Dict], question: str, today: Optional[date]) -> List[str]:
    """Records past a ``…Due`` date whose recorded status is not 'overdue', for an overdue question.

    BUG-589: with these listed in the facts, the narration still reported only the two
    records MARKED overdue in 4 of 4 runs. The answer's own completeness is not left to it.
    """
    if today is None or not rows or not _OVERDUE_RE.search(question or ""):
        return []
    columns = sorted({k for r in rows for k in r.keys()})
    out: List[str] = []
    for col in (c for c in columns if _DUE_COLUMN_RE.search(c)):
        for r in rows:
            status = _value(r, STATUS).lower()
            if status in _CLOSED_STATUSES or "overdue" in status:
                continue
            raw = _value(r, col)[:10]
            try:
                if date.fromisoformat(raw) < today:
                    out.append(f"{_ident(r)} ({col} {raw}, recorded {status or 'no status'})")
            except ValueError:
                continue
    return sorted(set(out))


def completeness_line(narration: str, missing: List[str]) -> str:
    """A system-written line naming past-due records the narration did not mention, or ""."""
    unmentioned = [m for m in missing if m.split(" (")[0] not in (narration or "")]
    if not unmentioned:
        return ""
    return (
        "\n\n**Also past their due date, though not recorded as overdue** (stated by the "
        "system from the register): " + "; ".join(unmentioned[:MAX_IDS_LISTED]) + "."
    )


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
