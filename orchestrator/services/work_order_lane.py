# -*- coding: utf-8 -*-
"""Which store answers a WORK-ORDER question, decided by the question and not by the classifier.

The failure this prevents (dev tail C, wave-1 verification, 2026-09-19). *"How many open work
orders are there, and which are overdue?"* was answered from two different stores depending on which
lane the model happened to pick:

* the maintenance-log REGISTER (24 records: "3 open ... overdue is not recorded"), which is what the
  first three demo rehearsals said; or
* the live EVENTS store (517 work orders: 65 open, 62 of them for more than a week), which is what
  the routing contract sends an interrogative work-order question to (BUG-166).

Both are the building's records and they do not agree, so a supervisor who asks twice can get two
answers. The choice is now made here, by shape, and both consumers (the routing contract and the
events lane) read this one definition:

* a BACKLOG shape -- open, overdue, outstanding, unresolved, pending, "older than", a ticket -- or a
  work order asked about by WHEN it was raised (this week, today, new) is the events store's
  question. It holds a status, a start time and a trade for every work order, and no due date;
* everything else about work orders -- who did it, which asset, what the comment says, a work-order
  number, how many are COMPLETED, which trade -- is the register's question. Only the register
  carries those fields, and answering them from the events store gave a count of a different thing.

Pure and building-agnostic: English only, no store, room or trade names.
"""

from __future__ import annotations

import re
from datetime import datetime
from typing import Any, Dict, List, Mapping, Optional, Sequence

WORK_ORDER_RE = re.compile(r"\bwork[\s-]?orders?\b", re.IGNORECASE)

#: A ticket is only ever an events-store thing: no register holds "tickets".
TICKET_RE = re.compile(
    r"\btickets?\b|\bmaintenance\s+(?:backlog|jobs|requests)\b|\brepair\s+(?:jobs|requests)\b",
    re.IGNORECASE,
)

#: The backlog vocabulary: what is not finished, and for how long.
BACKLOG_RE = re.compile(
    r"\b(?:open|overdue|outstanding|backlog|unresolved|pending|awaiting|unassigned|stale|aged|"
    r"older\s+than|still\s+open|late|behind|not\s+(?:yet\s+)?(?:closed|done|finished))\b",
    re.IGNORECASE,
)

#: Asked about by WHEN it was raised: the events store holds a start time, the register does not
#: mean it the same way.
RAISED_WINDOW_RE = re.compile(
    r"\b(?:raised|created|logged|opened|new|newest|latest|recent(?:ly)?)\b[^?.!]{0,30}"
    r"\b(?:today|yesterday|this\s+(?:week|month)|last\s+(?:week|month)|past\s+\d+\s+days?)\b"
    r"|\b(?:today|yesterday|this\s+(?:week|month)|last\s+(?:week|month))\b[^?.!]{0,30}"
    r"\b(?:raised|created|logged|opened|new)\b",
    re.IGNORECASE,
)

#: What only the REGISTER records about a work order. A question naming one of these is about a
#: particular record's content, and the events store cannot answer it.
REGISTER_ATTRIBUTE_RE = re.compile(
    r"\bWO[-\s]?\d{2,4}\b"
    r"|\b(?:trade|technician|contractor|engineer|electrician|plumber|fitter|carried\s+out|"
    r"completed\s+by|responsible|owner|comment|evidence|outcome|test\s+result|schedule\s+kind|"
    r"planned\s+or|reactive|routine)\b"
    r"|\b(?:completed|complete|closed|finished|resolved|in[-\s]progress)\b"
    r"|\b(?:asset|equipment|air\s+handling|ahu|chiller|boiler|lift|fan\s+coil|breaker|panel)\b",
    re.IGNORECASE,
)


def mentions_work_orders(question: str) -> bool:
    """True when the question names work orders (or tickets, the events store's own word)."""
    q = question or ""
    return bool(WORK_ORDER_RE.search(q) or TICKET_RE.search(q))


def asks_work_order_backlog(question: str) -> bool:
    """True when a work-order question is about what is UNFINISHED, and so the events store's.

    A ticket is always the events store's. A work order is its question only when the shape is a
    backlog (open, overdue, outstanding ...) or a raised-in-a-window one, AND it names no field that
    only the register holds -- "which open work orders are for the lift?" is a register question.
    """
    q = question or ""
    if TICKET_RE.search(q):
        return True
    if not WORK_ORDER_RE.search(q):
        return False
    if REGISTER_ATTRIBUTE_RE.search(q):
        return False
    return bool(BACKLOG_RE.search(q) or RAISED_WINDOW_RE.search(q))


def asks_work_order_register(question: str) -> bool:
    """True when a work-order question is the REGISTER's: it names work orders, and is not a backlog."""
    q = question or ""
    return bool(WORK_ORDER_RE.search(q)) and not asks_work_order_backlog(q)


# ── the events-lane answer ───────────────────────────────────────────────────

SOURCE_PHRASE = "work orders in the live events store"

#: How many of the oldest open work orders are named. The rest are counted.
LISTED = 5

#: Statuses that mean a work order is finished with.
_FINISHED = frozenset({"done", "complete", "completed", "closed", "resolved", "cancelled", "canceled"})


def _plural(n: int, one: str, many: Optional[str] = None) -> str:
    return one if n == 1 else (many or one + "s")


def _stamp(value: Any, local: Any = None) -> str:
    """The day a work order was opened, as '23 Jul' (the building's calendar when `local` is given)."""
    when = value
    if not isinstance(when, datetime):
        try:
            when = datetime.strptime(str(value)[:19], "%Y-%m-%d %H:%M:%S")
        except ValueError:
            return str(value)[:10]
    if local is not None:
        when = local(when)
    return f"{when.day} {when.strftime('%b')}"


def _describe(row: Mapping[str, Any], local: Any = None) -> str:
    """One work order in a line: trade, priority and when it was opened. Nothing personal is held."""
    bits: List[str] = []
    for key in ("trade", "priority"):
        value = str(row.get(key) or "").strip()
        if value:
            bits.append(re.sub(r"[|`*_<>\r\n]+", " ", value)[:24])
    bits.append(f"opened {_stamp(row.get('start'), local)}")
    return " · ".join(bits)


def compose_answer(
    counts: Mapping[str, int],
    *,
    aged: int,
    aged_days: int,
    oldest: Sequence[Mapping[str, Any]] = (),
    asked_overdue: bool = False,
    local: Any = None,
) -> Dict[str, Any]:
    """The events-lane answer to a work-order BACKLOG question. Pure: numbers in, payload out.

    It names its source, says how many are open, and answers "which are overdue" honestly: the
    store records a start time and a status and no due date, so "overdue" is stated as what was
    measured (open for more than ``aged_days`` days) and never as a due-date fact.
    """
    total = sum(int(v) for v in counts.values())
    open_n = int(counts.get("open", 0))
    breakdown = ", ".join(
        f"{int(n)} {status}" for status, n in sorted(counts.items(), key=lambda kv: -int(kv[1]))
    )
    if total == 0:
        text = (
            f"**No {SOURCE_PHRASE} are on record.** Nothing has been raised, or nothing is being "
            "kept there."
        )
        return {
            "counts": dict(counts),
            "total": 0,
            "open": 0,
            "aged_open": 0,
            "aged_filter_days": aged_days,
            "source": "events_data",
            "formatted_response": text,
        }

    verb = "is" if open_n == 1 else "are"
    parts = [
        f"**{open_n} {_plural(open_n, 'work order')} {verb} open** ({SOURCE_PHRASE}; {total} in all: "
        f"{breakdown})."
    ]
    if aged:
        parts.append(
            f"**{aged} of the open {_plural(aged, 'one')} {'has' if aged == 1 else 'have'} been open "
            f"for more than {aged_days} days.**"
        )
    else:
        parts.append(f"None of the open ones has been open for more than {aged_days} days.")
    if asked_overdue or aged:
        parts.append(
            f"The store records when each was opened and no due date, so \"overdue\" here means open "
            f"for more than {aged_days} days."
        )
    lines = [f"- {_describe(r, local)}" for r in list(oldest)[:LISTED]]
    if lines:
        parts.append("Oldest still open:\n" + "\n".join(lines))
    parts.append(
        "_Work orders in the maintenance-log register (with their trade, asset and comments) are "
        "answered separately: ask about one by number, asset or trade._"
    )
    return {
        "counts": dict(counts),
        "total": total,
        "open": open_n,
        "aged_open": int(aged),
        "aged_filter_days": aged_days,
        "listed": len(lines),
        "oldest": lines,
        "source": "events_data",
        "formatted_response": "\n\n".join(parts),
    }


def oldest_open(rows: Sequence[Mapping[str, Any]], limit: int = LISTED) -> List[Dict[str, Any]]:
    """The oldest still-open work orders from event rows (dicts with status, start, attrs)."""
    import json

    open_rows: List[Dict[str, Any]] = []
    for r in rows:
        status = str(r.get("status") or "").lower()
        if status in _FINISHED or status != "open":
            continue
        attrs = r.get("attrs")
        if isinstance(attrs, str):
            try:
                attrs = json.loads(attrs)
            except ValueError:
                attrs = {}
        attrs = attrs if isinstance(attrs, dict) else {}
        open_rows.append(
            {"start": r.get("start"), "trade": attrs.get("trade"), "priority": attrs.get("priority")}
        )
    open_rows.sort(key=lambda r: str(r.get("start") or ""))
    return open_rows[:limit]
