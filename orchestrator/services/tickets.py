# -*- coding: utf-8 -*-
"""One ticket universe: user reports and work orders as a single population (V6-T24).

Verified before building: they are two disjoint stores that never join. A person files
"the radiator in 5.16 is banging", it lands in `user_reports` in Postgres; the estate's work
orders live as `event_type='workorder'` rows in the MySQL events store. Nothing connects them,
so **"is my report being dealt with?" is unanswerable**, and a work-order count never reflects
a single thing a human actually reported.

**Why a shared model rather than querying both at answer time.** Two stores queried
independently double-count the moment anyone links them — a report that becomes a work order
would appear twice in "how many open issues are there", which is worse than the current
undercount because it looks authoritative. And with no shared status vocabulary, `OPEN` in one
store and `open` in the other cannot be compared at all. So this defines the vocabulary once
and deduplicates explicitly.

**Canonical status, mapped from both.** Neither store's vocabulary wins: they map onto a
shared ladder, and an unrecognised value becomes UNKNOWN rather than being guessed into the
nearest bucket. A ticket whose status nobody can interpret must not be silently counted as
resolved.

**The link is explicit, never inferred.** A report and a work order in the same room on the
same day are not necessarily the same issue, and treating them as one would merge two people's
problems. Only a recorded `work_order_id` joins them — the same discipline that keeps
`spatial_facts` free of distance.

Pure and I/O-free below the fetchers: the merge is testable without either database.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from enum import Enum
from typing import Any, Dict, List, Optional, Sequence

from shared.utils import get_logger

logger = get_logger(__name__)


class TicketStatus(str, Enum):
    """The shared ladder. UNKNOWN is a real state, not a failure to parse."""

    OPEN = "open"
    ACKNOWLEDGED = "acknowledged"
    IN_PROGRESS = "in_progress"
    RESOLVED = "resolved"
    CLOSED = "closed"
    CANCELLED = "cancelled"
    #: The store used a word this model does not know. Reported as unknown rather than
    #: bucketed — a ticket nobody can interpret must not be counted as dealt with.
    UNKNOWN = "unknown"


#: Each store's own vocabulary. Neither wins; both map onto the ladder. Extend the map when a
#: store adds a word, never by widening a bucket to swallow it.
_STATUS_ALIASES: Dict[str, TicketStatus] = {
    # user_reports (Postgres)
    "open": TicketStatus.OPEN,
    "new": TicketStatus.OPEN,
    "triaged": TicketStatus.ACKNOWLEDGED,
    "acknowledged": TicketStatus.ACKNOWLEDGED,
    "assigned": TicketStatus.IN_PROGRESS,
    "in_progress": TicketStatus.IN_PROGRESS,
    "in progress": TicketStatus.IN_PROGRESS,
    "resolved": TicketStatus.RESOLVED,
    "done": TicketStatus.RESOLVED,
    "complete": TicketStatus.RESOLVED,
    "completed": TicketStatus.RESOLVED,
    "closed": TicketStatus.CLOSED,
    "cancelled": TicketStatus.CANCELLED,
    "canceled": TicketStatus.CANCELLED,
    # events store (MySQL) — workorder rows
    "scheduled": TicketStatus.ACKNOWLEDGED,
    "dispatched": TicketStatus.IN_PROGRESS,
    "active": TicketStatus.IN_PROGRESS,
}

#: Statuses that mean "still someone's problem". Used for counts, so the definition lives in
#: one place rather than being re-derived per caller.
OPEN_STATES = (TicketStatus.OPEN, TicketStatus.ACKNOWLEDGED, TicketStatus.IN_PROGRESS)


def canonical_status(raw: str) -> TicketStatus:
    """Map a store's word onto the ladder. Unrecognised becomes UNKNOWN, never a guess."""
    return _STATUS_ALIASES.get((raw or "").strip().lower(), TicketStatus.UNKNOWN)


@dataclass
class Ticket:
    """One issue, whoever raised it and wherever it is stored."""

    ticket_id: str
    origin: str  # 'user_report' | 'work_order'
    status: TicketStatus = TicketStatus.UNKNOWN
    raw_status: str = ""
    title: str = ""
    space_iri: str = ""
    opened_at: Optional[datetime] = None
    #: The work order a user report was linked to, when someone recorded the link.
    linked_id: str = ""
    #: Set when this ticket absorbed another — the pair counts once.
    absorbed: List[str] = field(default_factory=list)

    @property
    def is_open(self) -> bool:
        return self.status in OPEN_STATES

    def describe(self) -> str:
        where = self.space_iri.rsplit("#", 1)[-1].rsplit("/", 1)[-1] if self.space_iri else ""
        loc = f" in {where}" if where else ""
        origin = (
            "reported by a person" if self.origin == "user_report" else "raised as a work order"
        )
        tail = f" (linked to work order {self.linked_id})" if self.linked_id else ""
        return f"{self.ticket_id}{loc} — {self.status.value}, {origin}{tail}"


def merge(reports: Sequence[Ticket], work_orders: Sequence[Ticket]) -> List[Ticket]:
    """One population from two stores, counting a linked pair ONCE.

    The work order wins the merged row when a link exists: it is the estate's record of what
    is actually being done, and its status is the one that answers "is this being dealt
    with". The report's id is kept in `absorbed` so the person who filed it can still find
    their own reference — dropping it would answer the count correctly and the human question
    not at all.
    """
    by_wo = {w.ticket_id: w for w in work_orders}
    out: List[Ticket] = []
    absorbed: set = set()

    for r in reports:
        wo = by_wo.get(r.linked_id) if r.linked_id else None
        if wo is None:
            out.append(r)
            continue
        wo.absorbed.append(r.ticket_id)
        # Carry the report's space when the work order has none: the person named the room,
        # and losing that on merge would make the joined view less locatable than either
        # store alone.
        if not wo.space_iri and r.space_iri:
            wo.space_iri = r.space_iri
        absorbed.add(r.ticket_id)

    out.extend(work_orders)
    return out


def counts(tickets: Sequence[Ticket]) -> Dict[str, int]:
    """Counts by canonical status, plus the reconciliation figures.

    `linked` is reported explicitly because it is the difference between the naive sum of two
    stores and the true number of issues — the figure that shows the count reconciles.
    """
    by_status: Dict[str, int] = {}
    for t in tickets:
        by_status[t.status.value] = by_status.get(t.status.value, 0) + 1
    linked = sum(len(t.absorbed) for t in tickets)
    return {
        **by_status,
        "total": len(tickets),
        "open_total": sum(1 for t in tickets if t.is_open),
        "linked": linked,
        "from_reports": sum(1 for t in tickets if t.origin == "user_report"),
        "from_work_orders": sum(1 for t in tickets if t.origin == "work_order"),
    }


def reconciliation_note(n_reports: int, n_work_orders: int, merged: Sequence[Ticket]) -> str:
    """State how the joined figure relates to the two raw ones.

    Without this a reader who knows one store's number cannot tell whether the joined total is
    a correction or a contradiction.
    """
    linked = sum(len(t.absorbed) for t in merged)
    if not linked:
        return (
            f"{len(merged)} issue(s): {n_reports} reported by people and {n_work_orders} raised "
            f"as work orders, with none linked to each other yet."
        )
    return (
        f"{len(merged)} distinct issue(s) from {n_reports} report(s) and {n_work_orders} work "
        f"order(s) — {linked} report(s) are linked to a work order and counted once, not twice."
    )


def ticket_from_report(row: Dict[str, Any]) -> Ticket:
    """One `user_reports` row as a ticket."""
    return Ticket(
        ticket_id=str(row.get("id") or ""),
        origin="user_report",
        status=canonical_status(str(row.get("status") or "")),
        raw_status=str(row.get("status") or ""),
        title=str(row.get("title") or ""),
        space_iri=str(row.get("space_iri") or ""),
        opened_at=row.get("created_at"),
        linked_id=str(row.get("work_order_id") or ""),
    )


def ticket_from_event(row: Dict[str, Any]) -> Ticket:
    """One `events` row of type `workorder` as a ticket."""
    attrs = row.get("attrs")
    if isinstance(attrs, str):
        try:
            import json

            attrs = json.loads(attrs)
        except Exception:
            attrs = {}
    attrs = attrs if isinstance(attrs, dict) else {}
    return Ticket(
        ticket_id=str(row.get("event_id") or ""),
        origin="work_order",
        status=canonical_status(str(row.get("status") or "")),
        raw_status=str(row.get("status") or ""),
        title=str(attrs.get("summary") or attrs.get("title") or "work order"),
        space_iri=str(attrs.get("space_iri") or ""),
        opened_at=row.get("start_dt"),
    )


__all__ = [
    "OPEN_STATES",
    "Ticket",
    "TicketStatus",
    "canonical_status",
    "counts",
    "merge",
    "reconciliation_note",
    "ticket_from_event",
    "ticket_from_report",
]
