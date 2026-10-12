"""CAVEAT-1617: "free tomorrow morning" is checked for tomorrow morning, not the next hour.

The deliberation lane's availability check took a window in hours from now; a named period was
answered "free for the next 1 h". The events lane's own calendar parser now supplies the period,
converted to the stores' clock at compile time. Booking times are shown in local time.
"""

from __future__ import annotations

from datetime import datetime

import pytest

from orchestrator.services.deliberation import compiler as cp
from orchestrator.services.deliberation import plan_executor as pe

pytestmark = pytest.mark.unit

TZ = "Europe/London"  # BST in October 2026 (until the 25th): local = UTC + 1
SUNDAY_10 = datetime(2026, 10, 11, 10, 0)


def test_tomorrow_morning_is_tomorrow_morning_on_the_store_clock():
    ec = cp._named_free_window("Which meeting room is free tomorrow morning?", SUNDAY_10, TZ)
    assert (ec.start, ec.end) == ("2026-10-12 05:00:00", "2026-10-12 11:00:00")
    assert ec.period == "tomorrow morning" and ec.hours == 6.0


def test_a_period_already_begun_starts_now():
    ec = cp._named_free_window(
        "Is there a quiet room available this afternoon?", datetime(2026, 10, 11, 14, 0), TZ
    )
    assert (ec.start, ec.end) == ("2026-10-11 13:00:00", "2026-10-11 17:00:00")


def test_a_named_weekday_resolves_forward():
    ec = cp._named_free_window("Which seminar room is free on Wednesday?", SUNDAY_10, TZ)
    assert ec.start.startswith("2026-10-13 23:00") and ec.period == "Wednesday"


@pytest.mark.parametrize(
    "q, now",
    [
        ("Which room was free yesterday morning?", SUNDAY_10),
        ("Which room is free this morning?", datetime(2026, 10, 11, 13, 0)),
        ("Which room is the quietest tomorrow?", SUNDAY_10),
        ("Which room is free right now?", SUNDAY_10),
    ],
)
def test_no_named_window_otherwise(q, now):
    assert cp._named_free_window(q, now, TZ) is None


def test_a_window_from_now_is_unchanged():
    (ec,) = cp._fold_event_criteria("Which room is free for the next 2 hours?")
    assert ec.hours == 2.0 and ec.start is None and ec.period == ""


def test_the_phrase_names_the_period_or_the_hours():
    named = pe.EventCheck(
        space_iri="x", kind="free_window", window_hours=6, period="tomorrow morning"
    )
    from_now = pe.EventCheck(space_iri="x", kind="free_window", window_hours=2)
    assert pe.free_phrase(named) == "free tomorrow morning"
    assert pe.free_phrase(from_now) == "free for the next 2 h"


def test_a_booking_time_is_shown_in_local_time(monkeypatch):
    from orchestrator.services import requested_interval as ri

    monkeypatch.setattr(ri, "building_tz", lambda building_id=None: TZ)
    assert pe._local_hhmm(datetime(2026, 10, 12, 8, 0)) == "09:00"
    assert pe._local_hhmm("2026-10-12 13:30:00") == "14:30"
