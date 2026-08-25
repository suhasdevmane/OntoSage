# -*- coding: utf-8 -*-
"""The institutional event layer: a calendar that includes the future (2026-08-25).

The events store held nothing but anomaly episodes on this building — no bookings, no
work orders, no access events — even though the generator for all three existed and a
seeding script was written to run it. Every institutional question could therefore only
ever produce an honest decline.

Seeding it exposed two further defects, both recorded here as tests:

* **A calendar with no future.** The backfill ran from N weeks ago up to *now* and
  stopped, so "which rooms are free tomorrow?" had nothing to read. Bookings are the one
  event type that legitimately lives ahead of now — that is what a room calendar is for —
  while access events and work orders are not: nobody has walked through a door tomorrow,
  and a work order cannot already be finished on a date that has not arrived.

* **A status that ignored time.** Bookings were hardcoded ``done``, so a reservation for
  next Tuesday claimed to have already happened. "Was this room actually used?" would have
  answered yes about a meeting nobody has attended.
"""

from datetime import datetime, timedelta

import pytest

from orchestrator.services.deliberation.synthetic_events import (
    _booking_status,
    bookings_for_building_day,
    bookings_for_room_day,
    generate_building_day,
)

pytestmark = pytest.mark.unit

_BID = "fixture_bldg"
_ROOMS = ["RoomA", "RoomB", "RoomC"]


def _day(offset_days: int) -> datetime:
    base = datetime(2026, 8, 25, 0, 0, 0)
    return base + timedelta(days=offset_days)


# ── booking status follows the clock ─────────────────────────────────────────
def test_future_booking_is_confirmed_not_done():
    now = datetime(2026, 8, 25, 12, 0, 0)
    assert _booking_status(datetime(2026, 8, 26, 9, 0), now) == "confirmed"


def test_past_booking_is_done():
    now = datetime(2026, 8, 25, 12, 0, 0)
    assert _booking_status(datetime(2026, 8, 24, 9, 0), now) == "done"


def test_status_without_a_clock_is_unchanged():
    """Callers that pass no `now` keep the historical behaviour exactly."""
    assert _booking_status(datetime(2030, 1, 1, 9, 0), None) == "done"


def test_no_booking_in_the_future_claims_to_have_happened():
    now = datetime(2026, 8, 25, 12, 0, 0)
    future = _day(3)
    events = bookings_for_building_day(_BID, _ROOMS, future, now)
    assert events, "the fixture day produced no bookings to check"
    for e in events:
        assert e["start_dt"] > now
        assert e["status"] == "confirmed", e


# ── only bookings may be generated ahead of now ──────────────────────────────
def test_forward_day_generates_bookings_only():
    """Access events and work orders must never be minted for a future date."""
    now = datetime(2026, 8, 25, 12, 0, 0)
    kinds = {e["event_type"] for e in bookings_for_building_day(_BID, _ROOMS, _day(2), now)}
    assert kinds == {"booking"}, kinds


def test_historical_day_still_generates_every_type():
    now = datetime(2026, 8, 25, 12, 0, 0)
    kinds = {e["event_type"] for e in generate_building_day(_BID, _ROOMS, _day(-10), now)}
    assert "booking" in kinds
    assert "access" in kinds or "workorder" in kinds, kinds


# ── determinism, because re-runs must be no-ops ──────────────────────────────
def test_forward_generation_is_deterministic():
    """event_id is a uuid5 over (building, type, subject, start): re-running the
    backfill must INSERT IGNORE into nothing, not accumulate duplicates."""
    now = datetime(2026, 8, 25, 12, 0, 0)
    a = bookings_for_building_day(_BID, _ROOMS, _day(1), now)
    b = bookings_for_building_day(_BID, _ROOMS, _day(1), now)
    assert [e["event_id"] for e in a] == [e["event_id"] for e in b]
    assert [e["status"] for e in a] == [e["status"] for e in b]


def test_room_day_signature_is_backward_compatible():
    """`now` is keyword-only in practice — existing positional calls must survive."""
    events = bookings_for_room_day(_BID, "RoomA", _day(-3))
    for e in events:
        assert e["status"] == "done"


# ── the bookings_list answer must carry the evidence it narrates ─────────────
def test_bookings_list_returns_the_lines_it_prints():
    """The numeric guard suppressed a correct answer because this branch printed ten
    booking times and reported only a count, so thirteen figures in the narration had
    nothing in the payload to account for. The guard was right; the payload was thin."""
    import inspect

    from orchestrator.services import event_query_service

    src = inspect.getsource(event_query_service)
    idx = src.index('"kind": "bookings_list"')
    window = src[idx : idx + 900]
    assert '"bookings": lines' in window, (
        "bookings_list must carry the rendered lines, the way availability_check "
        "carries its clashes"
    )


# ── the provisioner may not advertise what it cannot do ──────────────────────
def test_advertised_families_match_the_implemented_generators():
    """FAMILIES named 'closures' and 'timetable'; neither had a generator, so the
    constant documented capability the script does not have."""
    import importlib.util
    from pathlib import Path

    path = Path(__file__).resolve().parents[1] / "scripts" / "provision_synthetic_sources.py"
    spec = importlib.util.spec_from_file_location("_prov", str(path))
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    assert tuple(sorted(mod.FAMILIES)) == tuple(sorted(mod.GENERATORS))


def test_unknown_family_is_refused_rather_than_skipped():
    """It printed a note and exited 0, so provisioning nothing looked like success."""
    import importlib.util
    import inspect
    from pathlib import Path

    path = Path(__file__).resolve().parents[1] / "scripts" / "provision_synthetic_sources.py"
    spec = importlib.util.spec_from_file_location("_prov2", str(path))
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    src = inspect.getsource(mod.main)
    assert "return 2" in src, "an unrecognised family must fail, not continue"
