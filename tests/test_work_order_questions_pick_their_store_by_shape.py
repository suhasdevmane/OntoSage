# -*- coding: utf-8 -*-
"""Wave 2 (2D-07): a work-order question is answered from ONE store, chosen by its shape.

"How many open work orders are there, and which are overdue?" was answered from the maintenance-log
register ("24 records, 3 open") in three demo rehearsals and from the live events store ("62 work
orders open for more than 7 days") once the routing contract owned it: two stores, two answers, and
which one a supervisor got depended on what the classifier felt like. The shape test below is the one
definition both consumers read. The answer text is pinned too: it names its source, answers both
halves of the question, and says plainly that no due date is recorded.

The negatives matter as much: the register questions the oracle asks ("how many work orders are
completed?", "with trade Controls technician") must keep the register, whose fields the events store
does not hold.
"""

from datetime import datetime

import pytest

from orchestrator.services import work_order_lane as wo
from orchestrator.services.numeric_guard import SUPPRESSION_TEXT, guard_payload

pytestmark = pytest.mark.unit

BACKLOG = [
    "How many open work orders are there, and which are overdue?",  # the failing question
    "How many open work orders are there?",
    "Any overdue tickets?",
    "Are there any outstanding work orders?",
    "What is the work order backlog?",
    "Which work orders are older than a month?",
    "How many work orders were raised this week?",
    "Show me the unresolved tickets",
    "How many work orders are still open?",
]

REGISTER = [
    "How many work orders are completed?",  # the oracle's RO-0096
    "Briefly: Are any work orders with trade Controls technician completed?",  # RO-0035
    "Briefly: Which work orders have no completed recorded?",  # RO-0042
    "What does work order WO-016 say about the lift?",
    "Which work orders are for the air handling unit on floor 3?",
    "Who is responsible for the open work orders on the chiller?",  # an attribute, not the backlog
    "Which work orders are in progress?",
    "How many work orders are there?",  # no shape: the register, as before the events lane owned it
]

NOT_WORK_ORDERS = [
    "How many people entered today?",
    "Which rooms are booked this afternoon?",
    "Are there any anomalies this week?",
]


@pytest.mark.parametrize("question", BACKLOG)
def test_an_unfinished_work_order_question_is_the_events_stores(question):
    assert wo.asks_work_order_backlog(question), question
    assert not wo.asks_work_order_register(question)


@pytest.mark.parametrize("question", REGISTER)
def test_a_question_about_a_work_orders_content_is_the_registers(question):
    assert wo.asks_work_order_register(question), question
    assert not wo.asks_work_order_backlog(question)


@pytest.mark.parametrize("question", NOT_WORK_ORDERS)
def test_a_question_that_names_no_work_order_is_neither(question):
    assert not wo.asks_work_order_backlog(question)
    assert not wo.asks_work_order_register(question)
    assert not wo.mentions_work_orders(question)


def test_a_ticket_is_always_the_events_stores_because_no_register_holds_tickets():
    assert wo.asks_work_order_backlog("How many tickets are there?")
    assert not wo.asks_work_order_register("How many tickets are there?")


# ── the events-lane answer ──────────────────────────────────────────────────

COUNTS = {"done": 402, "open": 65, "assigned": 50}
OLDEST = [
    {"start": datetime(2026, 7, 23, 12, 12), "trade": "fabric", "priority": "medium"},
    {"start": datetime(2026, 7, 30, 13, 46), "trade": "cleaning", "priority": "medium"},
    {"start": datetime(2026, 7, 31, 9, 45), "trade": "fabric", "priority": "high"},
]


def _answer(**kw):
    args = dict(counts=COUNTS, aged=62, aged_days=7, oldest=OLDEST, asked_overdue=True)
    args.update(kw)
    return wo.compose_answer(**args)


def test_the_answer_names_its_source_and_both_counts():
    out = _answer()
    text = out["formatted_response"]
    assert "**65 work orders are open**" in text
    assert "work orders in the live events store" in text
    assert "517 in all" in text and "402 done" in text
    assert "**62 of the open ones have been open for more than 7 days.**" in text
    assert out["open"] == 65 and out["aged_open"] == 62 and out["total"] == 517


def test_overdue_is_said_to_be_a_measured_age_because_no_due_date_is_recorded():
    text = _answer()["formatted_response"]
    assert "no due date" in text
    assert 'means open for more than 7 days' in text


def test_the_oldest_open_ones_are_named_by_trade_priority_and_date_and_nobody_is_named():
    text = _answer()["formatted_response"]
    assert "Oldest still open:" in text
    assert "- fabric · medium · opened 23 Jul" in text
    assert "- fabric · high · opened 31 Jul" in text


def test_the_answer_points_at_the_register_without_quoting_its_numbers():
    text = _answer()["formatted_response"]
    assert "maintenance-log register" in text and "ask about one by number, asset or trade" in text


def test_a_backlog_that_is_not_ageing_says_so():
    text = _answer(aged=0, asked_overdue=True, oldest=[])["formatted_response"]
    assert "None of the open ones has been open for more than 7 days." in text
    assert "Oldest still open" not in text


def test_no_work_orders_at_all_is_a_plain_statement_not_a_zero_table():
    out = _answer(counts={}, aged=0, oldest=[])
    assert out["total"] == 0
    assert out["formatted_response"].startswith("**No work orders in the live events store")


def test_one_open_work_order_is_grammatical():
    text = _answer(counts={"open": 1, "done": 3}, aged=1, oldest=OLDEST[:1])["formatted_response"]
    assert "**1 work order is open**" in text
    assert "of the open one has been open" in text


def test_a_free_text_trade_cannot_carry_markup_into_the_answer():
    rows = [{"start": datetime(2026, 7, 1), "trade": "fab|ric`*", "priority": None}]
    text = _answer(oldest=rows)["formatted_response"]
    assert "|" not in text.split("Oldest still open:")[1].split("_Work orders")[0]
    assert "`" not in text


def test_every_number_in_the_answer_is_backed_by_its_own_payload():
    out = _answer()
    assert guard_payload(out, "events")["formatted_response"] != SUPPRESSION_TEXT


def test_oldest_open_reads_event_rows_and_ignores_finished_and_assigned_ones():
    rows = [
        {"status": "done", "start": "2026-07-01 08:00:00", "attrs": '{"trade": "x"}'},
        {"status": "open", "start": "2026-08-01 08:00:00", "attrs": '{"trade": "later", "priority": "low"}'},
        {"status": "open", "start": "2026-07-02 08:00:00", "attrs": '{"trade": "earlier"}'},
        {"status": "assigned", "start": "2026-06-01 08:00:00", "attrs": "{}"},
    ]
    out = wo.oldest_open(rows, limit=5)
    assert [r["trade"] for r in out] == ["earlier", "later"]
    assert wo.oldest_open(rows, limit=1)[0]["trade"] == "earlier"


# ── through the events lane, which keeps ticket AGING after the register took work orders ────


class _Result:
    def __init__(self, rows):
        self.rows, self.success = rows, True


class _Adapter:
    """Answers the three shapes `_workorder_summary` asks for, by inspecting the SQL."""

    def __init__(self, by_status, aged, rows):
        self.by_status, self.aged, self.rows = by_status, aged, rows
        self.queries = []

    def build_count_by_status(self, event_type, since=None, open_older_than=None):
        return f"COUNT {event_type} aged={open_older_than}"

    def build_overlap_window(self, event_type, start, end, subject_uuids=None, limit=1000):
        return f"WINDOW {event_type}"

    async def execute_query(self, sql):
        self.queries.append(sql)
        if sql.startswith("WINDOW"):
            return _Result(self.rows)
        return _Result(self.aged if "aged=None" not in sql else self.by_status)


async def test_an_overdue_ticket_question_names_its_source_and_says_no_due_date_is_recorded():
    from orchestrator.services.event_query_service import EventQueryService

    adapter = _Adapter(
        by_status=[("done", 402), ("open", 65), ("assigned", 50)],
        aged=[("open", 62)],
        rows=[
            {"status": "open", "start": datetime(2026, 7, 23, 12, 12), "attrs": '{"trade": "fabric"}'}
        ],
    )
    svc = EventQueryService("tb", adapter, [])
    out = await svc.answer("Any overdue tickets?", now=datetime(2026, 9, 19, 13, 0))
    text = out["formatted_response"]
    assert out["kind"] == "workorder_summary"
    assert "**65 work orders are open**" in text  # the open count survives the aged read
    assert "62 of the open ones have been open for more than 7 days" in text
    assert "work orders in the live events store" in text
    assert "no due date" in text
    assert out["aged_filter_days"] == 7 and out["open"] == 65 and out["aged_open"] == 62


async def test_the_answer_is_guard_clean_with_the_joined_report_note():
    from orchestrator.services.event_query_service import EventQueryService

    adapter = _Adapter(by_status=[("open", 3)], aged=[], rows=[])
    svc = EventQueryService("tb", adapter, [])
    out = await svc.answer("How many tickets are open?", now=datetime(2026, 9, 19, 13, 0))
    assert guard_payload(out, "events")["formatted_response"] != SUPPRESSION_TEXT
