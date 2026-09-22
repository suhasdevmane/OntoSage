"""A room is busy when its timetable says so — and 'no timetable' is not 'free'.

The bug this guards: availability was answered from ad-hoc bookings alone, so a room with a weekly
lecture in it reported itself free.
"""

from datetime import date, datetime, time

import pytest

from orchestrator.services import room_schedule as rs

pytestmark = pytest.mark.unit


def _row(**kw):
    """One SPARQL binding, in the shape GraphDB returns."""
    return {k: {"value": v} for k, v in kw.items()}


def _session(day="tuesday", start=time(14, 0), end=time(16, 0), name="1.06", **kw):
    base = dict(
        iri="urn:s", space_iri="http://x#Room1.06", space_name=name, day=day,
        start=start, end=end, title="CM2103 Databases", kind="lecture",
        effective_from=None, effective_to=None,
    )
    base.update(kw)
    return rs.Session(**base)


# ── reading the graph ──────────────────────────────────────────────────────────────────────────

def test_a_session_is_read_from_the_graph():
    rows = [_row(s="urn:a", space="http://x#Room1.06", spaceName="1.06", day="Tuesday",
                 start="14:00:00", end="16:00:00", title="Databases", kind="lecture")]
    got = rs.parse_sessions(rows)
    assert len(got) == 1 and got[0].day == "tuesday"
    assert got[0].start == time(14, 0) and got[0].end == time(16, 0)


@pytest.mark.parametrize("day,start", [("Notaday", "14:00:00"), ("Tuesday", "half past two")])
def test_an_unreadable_session_is_skipped_not_guessed(day, start):
    assert rs.parse_sessions([_row(s="urn:a", day=day, start=start, end="16:00:00")]) == []


def test_weekday_names_are_case_insensitive():
    rows = [_row(s="urn:a", day="TUESDAY", start="14:00", end="16:00")]
    assert rs.parse_sessions(rows)[0].day == "tuesday"


# ── matching a session to a room ───────────────────────────────────────────────────────────────

@pytest.mark.parametrize("room", ["Room1.06", "room 1.06", "1.06"])
def test_a_session_matches_its_room_however_the_name_is_written(room):
    assert rs.matches_room(_session(), room) is True


def test_a_session_does_not_match_a_different_room():
    assert rs.matches_room(_session(), "Room2.13") is False


def test_the_iri_wins_over_a_name_that_does_not_match():
    """The IRI is authoritative; a name is only a fallback."""
    s = _session(name="")
    assert rs.matches_room(s, "Room1.06") is True


@pytest.mark.parametrize(
    "recorded,room",
    [
        ("Room 2.15 — Seminar Room", "Room2.15"),          # the real recorded shape
        ("Room 1.06 — Computer Laboratory", "Room1.06"),
        ("Room 5.61 - Research Laboratory", "Room5.61"),
        ("Room 1.26 — Conference/Seminar Room", "Room1.26"),
    ],
)
def test_a_room_recorded_as_prose_still_matches(recorded, room):
    """The 675 existing sessions name their room as prose, not as a bare id."""
    assert rs.matches_room(_session(space_iri="", name=recorded), room) is True


def test_prose_matching_does_not_collide_with_a_different_room():
    s = _session(space_iri="", name="Room 2.15 — Seminar Room")
    assert rs.matches_room(s, "Room5.61") is False


def test_a_room_with_no_number_matches_on_its_leading_segment():
    """Nothing assumes a numbering convention: another building may name rooms in words."""
    s = _session(space_iri="", name="West Wing Studio — Media Lab")
    assert rs.matches_room(s, "West Wing Studio") is True


# ── expanding the weekly pattern ───────────────────────────────────────────────────────────────

def test_a_session_makes_the_room_busy_on_its_weekday():
    # 2026-09-22 is a Tuesday.
    got = rs.expand([_session()], datetime(2026, 9, 22, 13, 0), datetime(2026, 9, 22, 15, 0))
    assert len(got) == 1 and got[0].title == "CM2103 Databases"


def test_the_same_pattern_leaves_another_weekday_free():
    got = rs.expand([_session()], datetime(2026, 9, 23, 13, 0), datetime(2026, 9, 23, 15, 0))
    assert got == []


def test_a_window_that_ends_when_a_session_starts_does_not_clash():
    """endTime is exclusive: a window ending at 14:00 does not collide with a 14:00 start."""
    got = rs.expand([_session()], datetime(2026, 9, 22, 12, 0), datetime(2026, 9, 22, 14, 0))
    assert got == []


def test_a_window_that_starts_when_a_session_ends_does_not_clash():
    got = rs.expand([_session()], datetime(2026, 9, 22, 16, 0), datetime(2026, 9, 22, 17, 0))
    assert got == []


def test_a_window_spanning_several_days_catches_each_occurrence():
    weekly = _session(day="tuesday")
    got = rs.expand([weekly], datetime(2026, 9, 21, 0, 0), datetime(2026, 10, 6, 0, 0))
    assert len(got) == 2                      # 22 Sep and 29 Sep


def test_a_session_outside_its_term_never_makes_a_room_busy():
    ended = _session(effective_to=date(2026, 9, 1))
    assert rs.expand([ended], datetime(2026, 9, 22, 13, 0), datetime(2026, 9, 22, 15, 0)) == []


def test_a_session_before_its_term_starts_does_not_apply():
    later = _session(effective_from=date(2026, 10, 1))
    assert rs.expand([later], datetime(2026, 9, 22, 13, 0), datetime(2026, 9, 22, 15, 0)) == []


def test_the_same_slot_recorded_many_times_is_reported_once():
    """The register holds one record per dated occurrence, so a weekly slot repeats.

    Collapsed onto a weekday those are identical windows; the answer once listed the same
    lecture four times.
    """
    same = [_session(), _session(), _session(), _session()]
    got = rs.expand(same, datetime(2026, 9, 22, 13, 0), datetime(2026, 9, 22, 15, 0))
    assert len(got) == 1


def test_two_different_sessions_in_one_window_are_both_reported():
    pair = [_session(title="Databases"), _session(start=time(15, 0), end=time(17, 0), title="HCI")]
    got = rs.expand(pair, datetime(2026, 9, 22, 13, 0), datetime(2026, 9, 22, 18, 0))
    assert len(got) == 2


def test_an_empty_window_is_never_busy():
    assert rs.expand([_session()], datetime(2026, 9, 22, 14, 0), datetime(2026, 9, 22, 14, 0)) == []


# ── the distinction that matters ───────────────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_no_timetable_is_reported_as_unknown_not_as_free():
    """An empty graph must not be answered as 'the room is free' — that is a guess, not a fact."""

    async def empty(_q):
        return {"results": {"bindings": []}}

    ans = await rs.check(empty, "Room1.06", datetime(2026, 9, 22, 13, 0), datetime(2026, 9, 22, 15, 0))
    assert ans.timetable_loaded is False
    assert ans.is_busy is False


@pytest.mark.asyncio
async def test_a_loaded_timetable_with_no_clash_is_genuinely_free():
    async def one(_q):
        return {"results": {"bindings": [
            _row(s="urn:a", space="http://x#Room1.06", spaceName="1.06", day="Tuesday",
                 start="14:00:00", end="16:00:00", title="Databases", kind="lecture")]}}

    ans = await rs.check(one, "Room1.06", datetime(2026, 9, 23, 13, 0), datetime(2026, 9, 23, 15, 0))
    assert ans.timetable_loaded is True and ans.is_busy is False


@pytest.mark.asyncio
async def test_a_clash_is_reported_busy_with_its_title():
    async def one(_q):
        return {"results": {"bindings": [
            _row(s="urn:a", space="http://x#Room1.06", spaceName="1.06", day="Tuesday",
                 start="14:00:00", end="16:00:00", title="Databases", kind="lecture")]}}

    ans = await rs.check(one, "Room1.06", datetime(2026, 9, 22, 13, 0), datetime(2026, 9, 22, 15, 0))
    assert ans.is_busy is True and ans.occupied[0].title == "Databases"


@pytest.mark.asyncio
async def test_a_graph_that_errors_does_not_crash_the_answer():
    async def boom(_q):
        raise RuntimeError("graph down")

    ans = await rs.check(boom, "Room1.06", datetime(2026, 9, 22, 13, 0), datetime(2026, 9, 22, 15, 0))
    assert ans.timetable_loaded is False and ans.is_busy is False
