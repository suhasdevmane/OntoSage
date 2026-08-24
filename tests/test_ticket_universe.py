# -*- coding: utf-8 -*-
"""One ticket universe (V6-T24): reports and work orders as a single population.

Verified before building: two disjoint stores that never join. A person's report lands in
`user_reports` (Postgres); the estate's work orders are `event_type='workorder'` rows in the
MySQL events store. Nothing connects them, so **"is my report being dealt with?" cannot be
answered**, and a work-order count never reflects anything a human actually reported.

The three properties that make the join worth having, each easy to lose in a refactor:

1. **A linked pair counts ONCE.** Querying both stores and adding them is worse than the
   current undercount, because it double-counts while looking authoritative.
2. **The link is explicit.** A report and a work order in the same room on the same day are
   not necessarily the same issue; merging on proximity combines two people's problems. Only
   a recorded `work_order_id` joins them — the same discipline that keeps distance out of
   `spatial_facts`.
3. **An unknown status stays UNKNOWN.** Bucketing a word nobody mapped into the nearest
   neighbour would let a ticket in an uninterpretable state be counted as dealt with.
"""

from datetime import datetime, timezone

import pytest

from orchestrator.services.tickets import (
    Ticket,
    TicketStatus,
    canonical_status,
    counts,
    merge,
    reconciliation_note,
    ticket_from_event,
    ticket_from_report,
)

pytestmark = pytest.mark.unit

NOW = datetime(2026, 8, 24, 12, 0, tzinfo=timezone.utc)


def _report(rid, status="OPEN", wo="", space=""):
    return Ticket(
        ticket_id=rid,
        origin="user_report",
        status=canonical_status(status),
        raw_status=status,
        space_iri=space,
        linked_id=wo,
    )


def _wo(wid, status="open", space=""):
    return Ticket(
        ticket_id=wid, origin="work_order", status=canonical_status(status), space_iri=space
    )


# ── the counting property ────────────────────────────────────────────────────


def test_a_linked_pair_counts_once():
    merged = merge([_report("REP-1", wo="WO-9")], [_wo("WO-9")])
    assert len(merged) == 1, "the same issue was counted in both stores"
    assert merged[0].ticket_id == "WO-9"
    assert "REP-1" in merged[0].absorbed, (
        "the reporter's own reference was dropped — the count would be right and their "
        "question 'what happened to MY report' unanswerable"
    )


def test_an_unlinked_report_is_still_counted():
    """The undercount this turn exists to fix: a filed report nobody has actioned is a real
    open issue and must appear."""
    merged = merge([_report("REP-1")], [_wo("WO-9")])
    assert len(merged) == 2
    assert {t.ticket_id for t in merged} == {"REP-1", "WO-9"}


def test_the_work_order_status_wins_a_linked_pair():
    """It is the estate's record of what is actually being done — the status that answers
    'is this being dealt with'."""
    merged = merge([_report("REP-1", status="OPEN", wo="WO-9")], [_wo("WO-9", status="dispatched")])
    assert merged[0].status is TicketStatus.IN_PROGRESS


def test_a_merged_row_keeps_the_space_the_person_named():
    """The reporter said which room; a work order often does not. Losing it on merge would
    make the joined view less locatable than either store alone."""
    merged = merge(
        [_report("REP-1", wo="WO-9", space="http://x#Room5.16")], [_wo("WO-9", space="")]
    )
    assert merged[0].space_iri == "http://x#Room5.16"


def test_proximity_never_links_anything():
    """Same room, same day, no recorded link — two different problems."""
    merged = merge(
        [_report("REP-1", space="http://x#Room5.16")], [_wo("WO-9", space="http://x#Room5.16")]
    )
    assert len(merged) == 2, "two tickets were merged on location alone"


# ── the status ladder ────────────────────────────────────────────────────────


@pytest.mark.parametrize(
    "raw,expected",
    [
        ("OPEN", TicketStatus.OPEN),
        ("in_progress", TicketStatus.IN_PROGRESS),
        ("dispatched", TicketStatus.IN_PROGRESS),
        ("scheduled", TicketStatus.ACKNOWLEDGED),
        ("Resolved", TicketStatus.RESOLVED),
        ("closed", TicketStatus.CLOSED),
    ],
)
def test_both_stores_vocabularies_map_onto_one_ladder(raw, expected):
    assert canonical_status(raw) is expected


def test_an_unmapped_status_is_unknown_not_guessed():
    assert canonical_status("awaiting_parts_from_supplier") is TicketStatus.UNKNOWN
    assert canonical_status("") is TicketStatus.UNKNOWN


def test_an_unknown_status_is_not_counted_as_open_or_resolved():
    """It must land in neither bucket: counting it open overstates the backlog, counting it
    resolved hides work nobody is doing."""
    t = Ticket("X-1", "work_order", canonical_status("awaiting_parts"))
    assert not t.is_open
    c = counts([t])
    assert c["open_total"] == 0
    assert c["unknown"] == 1


# ── reconciliation ───────────────────────────────────────────────────────────


def test_the_counts_expose_the_linked_figure():
    """`linked` is the difference between the naive sum of two stores and the true number of
    issues — the figure that demonstrates the count reconciles."""
    merged = merge([_report("REP-1", wo="WO-9"), _report("REP-2")], [_wo("WO-9"), _wo("WO-8")])
    c = counts(merged)
    assert c["total"] == 3, c
    assert c["linked"] == 1
    assert c["from_reports"] == 1 and c["from_work_orders"] == 2


def test_the_note_explains_the_join_rather_than_asserting_a_number():
    merged = merge([_report("REP-1", wo="WO-9"), _report("REP-2")], [_wo("WO-9")])
    note = reconciliation_note(2, 1, merged)
    assert "counted once, not twice" in note
    assert "2" in note and "1" in note, "the raw store figures must both appear"


def test_the_note_says_so_when_nothing_is_linked_yet():
    """Honest about the current state of every building here: the stores exist and nobody has
    connected a single pair."""
    merged = merge([_report("REP-1")], [_wo("WO-9")])
    assert "none linked" in reconciliation_note(1, 1, merged)


# ── row adapters ─────────────────────────────────────────────────────────────


def test_a_report_row_becomes_a_ticket():
    t = ticket_from_report(
        {
            "id": "REP-ABC",
            "status": "OPEN",
            "title": "radiator banging",
            "space_iri": "http://x#Room5.16",
            "created_at": NOW,
            "work_order_id": None,
        }
    )
    assert t.origin == "user_report" and t.status is TicketStatus.OPEN
    assert t.linked_id == "", "a NULL link must not become the string 'None'"


def test_an_event_row_becomes_a_ticket_with_json_attrs():
    t = ticket_from_event(
        {
            "event_id": "WO-1",
            "status": "open",
            "start_dt": NOW,
            "attrs": '{"summary": "replace valve", "space_iri": "http://x#Room2.14"}',
        }
    )
    assert t.origin == "work_order"
    assert t.title == "replace valve"
    assert t.space_iri == "http://x#Room2.14"


def test_malformed_attrs_do_not_break_the_row():
    t = ticket_from_event({"event_id": "WO-2", "status": "open", "attrs": "not json{"})
    assert t.ticket_id == "WO-2" and t.title == "work order"


def test_the_joined_note_degrades_rather_than_breaking_the_answer():
    """A building with no intake store keeps its events-only behaviour — the join is additive
    where both stores exist, which is the portability contract."""
    from pathlib import Path

    src = Path("orchestrator/services/event_query_service.py").read_text(encoding="utf-8")
    body = src[src.index("async def _joined_ticket_note") :][:2600]
    assert "if not reports:" in body and 'return ""' in body
    assert "except Exception" in body, "the note must never break the work-order answer"


def test_event_questions_bypass_the_pre_llm_capability_probe():
    """"How many work orders are open?" matched the building-hours document on the word
    "open" and was answered from prose in 250ms — the routing contract sends it to the events
    lane and never got a say.

    Third member of this family after BUG-231's wayfinding and deliberation cases. The bypass
    reuses the contract's own EVENTS_RE rather than a second pattern, because two definitions
    of "is this an event question" is the drift this codebase keeps paying for.
    """
    from pathlib import Path

    src = Path("orchestrator/agents/dialogue_agent.py").read_text(encoding="utf-8")
    assert "EVENTS_RE as _EVENTS_RE" in src, "the probe does not import the contract's pattern"
    assert "not _EVENTS_RE.search(user_query)" in src, (
        "event questions still have no bypass; they will be answered from a document before "
        "the router sees them"
    )


def test_the_contract_itself_routes_work_order_questions_to_events():
    """The half that already worked — pinned so a regression here is distinguishable from a
    regression in the bypass above."""
    from orchestrator.services.routing_contract import apply_contract

    for q in ("How many work orders are open?", "Show me the maintenance backlog"):
        st = {"intent": "capability", "concepts": [], "entities": []}
        apply_contract(q, st, stage="parse")
        apply_contract(q, st, stage="post")
        assert st["intent"] == "events", f"{q!r} routed to {st['intent']}"


def test_the_intake_singleton_does_not_depend_on_call_order():
    """The joined view read [] because the singleton is only handed a Postgres connection by
    the report-intake node — any other caller got a service that silently returned nothing
    unless somebody had filed a report in that process first.

    A read that returns empty because of initialisation order is indistinguishable from a
    building with no reports, which is the wrong thing to be ambiguous about in a count whose
    entire purpose is to reconcile two stores.
    """
    from pathlib import Path

    src = Path("orchestrator/services/report_intake_service.py").read_text(encoding="utf-8")
    body = src[src.index("def get_report_intake_service") :]
    assert "postgres_manager" in body and "_main" in body, (
        "the singleton still cannot obtain a connection on its own"
    )
