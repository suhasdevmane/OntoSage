# -*- coding: utf-8 -*-
"""A report with no place is a report that can never show recurrence (CAVEAT-380).

The recurrence lane groups reports by (place, category) to answer "is this the same problem
in the same place again?". 113 of bldg1's 203 reports carry neither a `location` nor a
`space_iri`, so that question is answered over 44% of the intake data. Those 113 cannot be
retrofitted — nobody can say afterwards where a report came from — which makes the moment of
filing the only point at which the gap can be closed, while the reporter is still there and
still knows.

So the acknowledgment asks. It does not demand: refusing a report for want of a location
would lose it altogether, and a placeless safety report is worth far more than no report.
"""

import pytest

from orchestrator.services.report_intake_service import ReportIntakeService

pytestmark = pytest.mark.unit


def _ack(location=None, device=None, space_iri=None, category="maintenance", priority="NORMAL"):
    return ReportIntakeService._acknowledgment(
        "REP-ABC123", category, priority, location, device, space_iri
    )


def test_a_placeless_report_asks_where_it_is():
    text = _ack()
    assert "couldn't tell **where**" in text
    assert "room, floor or area" in text


def test_it_says_why_the_place_matters():
    """A prompt with no reason reads as bureaucracy and gets ignored."""
    assert "keeps coming back in the same place" in _ack()


def test_a_report_with_a_location_is_not_asked_again():
    text = _ack(location="Room 5.15")
    assert "couldn't tell" not in text
    assert "- **Location:** Room 5.15" in text


def test_a_resolved_space_counts_as_a_place_even_with_no_free_text_location():
    """`_resolve_space` can resolve a space from the description alone; that is enough."""
    text = _ack(location=None, space_iri="http://example.org/bldg1#Room_5_15")
    assert "couldn't tell" not in text


def test_the_report_is_still_logged_without_a_place():
    """The prompt must never read as a rejection."""
    text = _ack()
    assert "has been logged as **REP-ABC123**" in text
    assert "- **Status:** OPEN" in text


def test_an_urgent_placeless_report_still_gets_its_emergency_notice():
    """The place prompt must not displace the safety message."""
    text = _ack(category="safety", priority="URGENT")
    assert "couldn't tell **where**" in text
    assert "emergency line immediately" in text
