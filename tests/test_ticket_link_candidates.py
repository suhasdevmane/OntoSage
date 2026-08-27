# -*- coding: utf-8 -*-
""""Is my report being dealt with?" (CAVEAT-317, 2026-08-27).

``user_reports.work_order_id`` existed, ``link_to_work_order()`` existed,
``tickets.py`` read the column — and **nothing ever called the linker**. So every
reconciliation said "163 reported by people and 217 raised as work orders, with
none linked to each other yet", and the question was unanswerable by construction.
Fourth instance found that day of a capability that exists with no invoker.

The rule here is same space + overlapping window + compatible category, chosen by
the project owner. It deliberately does **not** create the explicit link, because
``tickets.py`` opens with an argument that still holds: two tickets in one room on
one day are not necessarily one issue, and merging two people's problems is worse
than leaving them apart. An inferred merge would also double-count in a way that
looks authoritative — worse than the undercount it replaces.

So a candidate is a suggestion carrying its own basis. The merge stays
explicit-only. An answer can say "this may be the same issue" and never that it is.
"""

from datetime import datetime, timedelta

import pytest

from orchestrator.services.tickets import (
    LINK_WINDOW_HOURS,
    Ticket,
    TicketStatus,
    candidates_for,
    category_of,
    merge,
    progress_note,
    propose_links,
)

pytestmark = pytest.mark.unit

_T0 = datetime(2026, 8, 20, 9, 0)
_ROOM = "ns#Room_5.16"
_OTHER = "ns#Room_5.20"


def _report(tid, title, *, space=_ROOM, at=_T0, linked=""):
    return Ticket(
        ticket_id=tid,
        origin="user_report",
        status=TicketStatus.OPEN,
        title=title,
        space_iri=space,
        opened_at=at,
        linked_id=linked,
    )


def _wo(tid, title, *, space=_ROOM, hours=4, status=TicketStatus.IN_PROGRESS):
    return Ticket(
        ticket_id=tid,
        origin="work_order",
        status=status,
        title=title,
        space_iri=space,
        opened_at=_T0 + timedelta(hours=hours),
    )


# ── the pairing the owner asked for ──────────────────────────────────────────
def test_same_space_soon_after_and_same_trade_is_a_candidate():
    r = _report("R1", "The tap in 5.16 is dripping")
    w = _wo("W1", "Repair leaking basin tap")
    (c,) = propose_links([r], [w])
    assert c.report_id == "R1" and c.work_order_id == "W1"
    assert c.category == "plumbing"
    assert "same space" in c.basis and "4h after" in c.basis


def test_a_different_trade_in_the_same_room_is_not_a_candidate():
    """A flickering light and a leaking tap in one room are two issues, however
    close together they were raised."""
    assert (
        propose_links([_report("R2", "Light flickering in 5.16")], [_wo("W1", "Leaking tap")]) == []
    )


def test_a_different_space_is_not_a_candidate():
    """Same space, not nearby. Proximity inference is what produced BUG-189."""
    r = _report("R1", "Dripping tap")
    assert propose_links([r], [_wo("W1", "Leaking tap", space=_OTHER)]) == []


def test_a_work_order_raised_before_the_report_is_not_a_candidate():
    """It cannot have been raised because of a report that did not exist yet."""
    r = _report("R1", "Dripping tap")
    assert propose_links([r], [_wo("W1", "Leaking tap", hours=-3)]) == []


def test_a_work_order_outside_the_window_is_not_a_candidate():
    r = _report("R1", "Dripping tap")
    late = _wo("W1", "Leaking tap", hours=LINK_WINDOW_HOURS + 1)
    assert propose_links([r], [late]) == []


def test_an_unreadable_category_does_not_block_a_pairing():
    """A trade that cannot be told is not evidence either way, so the other two
    tests decide. Guessing it into a bucket would be the fabrication."""
    r = _report("R1", "Something is wrong in here")
    (c,) = propose_links([r], [_wo("W1", "Attend room")])
    assert c.category == ""
    assert "look like" not in c.basis


# ── a recorded fact always beats a guess ─────────────────────────────────────
def test_a_report_with_an_explicit_link_gets_no_candidates():
    r = _report("R1", "Dripping tap", linked="W9")
    assert propose_links([r], [_wo("W1", "Leaking tap")]) == []


def test_a_work_order_already_claimed_by_a_link_is_off_the_table():
    """Otherwise one work order would be offered to two different people."""
    claimed = _report("R0", "Dripping tap", linked="W1")
    other = _report("R1", "Leaking tap", at=_T0)
    assert propose_links([claimed, other], [_wo("W1", "Leaking tap")]) == []


# ── suggestions must not become the population ───────────────────────────────
def test_a_candidate_does_not_merge_the_two_tickets():
    """An inferred merge would double-count in a way that looks authoritative —
    worse than the undercount it replaces."""
    r = _report("R1", "Dripping tap")
    w = _wo("W1", "Leaking tap")
    assert propose_links([r], [w])
    merged = merge([r], [w])
    assert {t.ticket_id for t in merged} == {"R1", "W1"}
    assert merged[0].absorbed == [] or merged[1].absorbed == []


def test_an_explicit_link_still_merges():
    r = _report("R1", "Dripping tap", linked="W1")
    w = _wo("W1", "Leaking tap")
    merged = merge([r], [w])
    assert [t.ticket_id for t in merged] == ["W1"]
    assert merged[0].absorbed == ["R1"]


# ── the three answers a person can get, all different ────────────────────────
def test_a_recorded_link_is_answered_as_a_fact():
    r = _report("R1", "Dripping tap", linked="W1")
    r.status = TicketStatus.IN_PROGRESS
    out = progress_note(r, [])
    assert out.startswith("Yes")
    assert "W1" in out and "in_progress" in out


def test_a_candidate_is_answered_as_a_lead_not_an_answer():
    r = _report("R1", "The tap is dripping")
    cands = propose_links([r], [_wo("W1", "Leaking tap")])
    out = progress_note(r, cands)
    assert "may be related" in out
    assert "Nobody has confirmed" in out
    assert not out.startswith("Yes")


def test_nothing_at_all_is_answered_as_nothing_at_all():
    r = _report("R1", "The tap is dripping")
    out = progress_note(r, [])
    assert "none was raised in the same space" in out


# ── ordering and lookup ──────────────────────────────────────────────────────
def test_the_closest_work_order_in_time_is_offered_first():
    r = _report("R1", "Dripping tap")
    cands = propose_links(
        [r], [_wo("W_far", "Leaking tap", hours=30), _wo("W_near", "Leaking tap", hours=2)]
    )
    assert [c.work_order_id for c in cands] == ["W_near", "W_far"]
    assert candidates_for("R1", cands)[0].work_order_id == "W_near"


@pytest.mark.parametrize(
    "text,expected",
    [
        ("The tap is leaking", "plumbing"),
        ("Light bulb has gone", "electrical"),
        ("The lift is stuck", "lift"),
        ("It is freezing in here, radiator is off", "hvac"),
        ("Something is wrong", ""),
        # two trades in one sentence is ambiguous, and an ambiguous category must
        # not be used to justify a pairing
        ("The light above the leaking tap is out", ""),
    ],
)
def test_category_reading(text, expected):
    assert category_of(text) == expected


# ── and it is actually called ────────────────────────────────────────────────
def test_the_joined_ticket_lane_calls_it():
    """The defect being fixed IS an uncalled function. Adding a second one would be
    the joke telling itself."""
    import inspect

    from orchestrator.services import event_query_service

    src = inspect.getsource(event_query_service)
    assert "propose_links(reports, wos)" in src
