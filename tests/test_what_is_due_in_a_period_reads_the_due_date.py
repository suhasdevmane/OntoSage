""""Which checks are DUE this month?" filters on the due date, not on when a check was done.

2026-10-11 battery: the question was answered "No record matches (completed date: this month)",
because the period rule reads the date a record HAPPENED and excludes due/next dates on purpose.
A question that says "due" asks about the obligation date. Records here are synthetic and name no
building.
"""

from datetime import date

import pytest

from orchestrator.services.register_projection import _restated_period_spans, resolve

pytestmark = pytest.mark.unit

TODAY = date(2026, 10, 10)


def _checks():
    rows = [
        ("Emergency lighting", "2026-09-04", "2026-10-04"),
        ("Water hygiene", "2026-04-20", "2026-10-20"),
        ("Lifting equipment", "2026-06-01", "2026-12-01"),
        ("Fire doors", "2026-10-02", "2027-04-02"),
    ]
    return [
        {
            "recordId": f"CHK-{i}",
            "label": name,
            "completedDate": done,
            "nextDueDate": due,
            "recordStatus": "active",
        }
        for i, (name, done, due) in enumerate(rows, 1)
    ]


def test_due_this_month_reads_the_due_date():
    res = resolve(_checks(), "Which compliance checks are due this month?", "Check", today=TODAY)
    assert any(f.startswith("next due date:") for f in res.other_filters)
    labels = {res.rows[i]["label"] for i in res.selected}
    assert labels == {"Emergency lighting", "Water hygiene"}


def test_done_this_month_still_reads_the_completion_date():
    res = resolve(_checks(), "Which checks were completed this month?", "Check", today=TODAY)
    assert any(f.startswith("completed date:") for f in res.other_filters)


def test_a_rewrite_that_restates_the_period_leaves_no_unmatched_month():
    q = "Who owns the compliance checks due this month (1 October 2026 to 31 October 2026)?"
    res = resolve(_checks(), q, "Check", today=TODAY)
    assert any(f.startswith("next due date:") for f in res.other_filters)
    assert not any("october" in w.lower() for w in res.unresolved)


def test_a_month_outside_the_period_is_not_consumed():
    october = (date(2026, 10, 1), date(2026, 10, 31))
    text = "due this month (1 October 2026 to 31 October 2026) and in December"
    spans = _restated_period_spans(text, *october, [])
    consumed = " ".join(text[a:b] for a, b in spans)
    assert "October" in consumed and "December" not in consumed


def test_overdue_is_not_read_as_due():
    res = resolve(_checks(), "Which checks are overdue?", "Check", today=TODAY)
    assert not any(f.startswith("next due date:") for f in res.other_filters)
