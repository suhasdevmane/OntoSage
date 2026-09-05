# -*- coding: utf-8 -*-
"""A readiness check must be dated, honest about gaps, and building-agnostic.

Lecturers asked for this in the stakeholder capture: "one concise, source-timestamped
readiness check 30 minutes before each class". Every ingredient existed — the timetable
knows when and where, the AV register whether the technology was last proved to work, the
workspace register the network and the setup allowance — and nothing joined them.

The three properties that make it a readiness check rather than a status dump are the three
this file guards:

  1. EVERY FACT CARRIES A SOURCE AND A DATE. "The projector works" is worthless without
     "checked 2026-08-28". A line whose age cannot be established must say so rather than
     read as current.

  2. THE UNKNOWNS ARE AS PROMINENT AS THE FACTS. A room with no AV record is not a room
     with working AV, and a check that silently omits what it could not assess invites
     exactly that reading. Contract 4 applies to a notification as much as to an answer.

  3. THERE ARE THREE VERDICTS, NOT TWO. "Ready" and "not ready" cannot express the common
     case — nothing broken, nothing checked either. A room reported ready on no evidence is
     the failure the whole module exists to avoid.
"""

from datetime import date, datetime

import pytest

pytestmark = pytest.mark.unit

from orchestrator.services.readiness_check import (  # noqa: E402
    ReadinessCheck,
    ReadinessFact,
    _combine,
    _identifier,
    _same_room,
    render,
)


# ── property 1: a source and a date on every line ──────────────────────────────────────


def test_a_fact_renders_its_source_and_date():
    fact = ReadinessFact("Projector", "ready", "AV readiness register", "2026-08-28")
    out = fact.render()
    assert "AV readiness register" in out
    assert "2026-08-28" in out


def test_a_fact_with_no_date_says_so_rather_than_reading_as_current():
    fact = ReadinessFact("Hearing loop", "unevidenced", "AV readiness register", "")
    assert "date not recorded" in fact.render(), (
        "an undated line must announce that it is undated; rendered bare it reads as a "
        "check performed today"
    )


# ── property 2: the unknowns are reported ──────────────────────────────────────────────


def test_unknowns_appear_in_the_rendered_check():
    check = ReadinessCheck(room="Room 3.13", generated_at="2026-09-05T09:00")
    check.facts.append(ReadinessFact("Network", "strong", "workspace profile", "2026-09-01"))
    check.unknowns.append("No AV readiness record names Room 3.13.")
    out = render(check)
    assert "Not known" in out
    assert "No AV readiness record" in out


def test_a_room_with_nothing_recorded_is_not_reported_ready():
    """The load-bearing case. Silence is not a pass."""
    check = ReadinessCheck(room="Room 9.99")
    assert check.verdict == "nothing recorded"
    assert "ready" != check.verdict


# ── property 3: three verdicts ─────────────────────────────────────────────────────────


def test_a_blocker_makes_the_verdict_not_ready():
    check = ReadinessCheck(room="Room 1.06")
    check.facts.append(ReadinessFact("Projector", "ready", "AV", "2026-08-28"))
    check.facts.append(
        ReadinessFact("Hearing loop", "unevidenced", "AV", "", blocking=True)
    )
    assert check.verdict == "not ready"
    assert [f.label for f in check.blockers] == ["Hearing loop"]


def test_facts_with_gaps_are_distinguished_from_a_clean_check():
    clean = ReadinessCheck(room="A")
    clean.facts.append(ReadinessFact("Projector", "ready", "AV", "2026-08-28"))
    assert clean.verdict == "ready"

    gappy = ReadinessCheck(room="B")
    gappy.facts.append(ReadinessFact("Projector", "ready", "AV", "2026-08-28"))
    gappy.unknowns.append("No workspace profile names B.")
    assert gappy.verdict == "no blockers found, with gaps", (
        "a check with an unassessed half must not read the same as one with none"
    )


def test_blockers_are_rendered_before_the_things_that_are_fine():
    check = ReadinessCheck(room="Room 1.06", generated_at="2026-09-05T09:00")
    check.facts.append(ReadinessFact("Projector", "ready", "AV", "2026-08-28"))
    check.facts.append(ReadinessFact("Hearing loop", "unevidenced", "AV", "", blocking=True))
    out = render(check)
    assert out.index("Needs attention") < out.index("Checked and in order")


# ── building-agnostic ──────────────────────────────────────────────────────────────────


def test_no_building_vocabulary_appears_in_the_module():
    """The check must work for a building this repo has never seen."""
    import inspect

    from orchestrator.services import readiness_check as module

    src = inspect.getsource(module).lower()
    for literal in ("abacws", "cardiff", "senghennydd", "bldg1", "room 1.06"):
        assert literal not in src, (
            f"{literal!r} appears in the readiness module; it would not survive a swap to "
            f"another building"
        )


@pytest.mark.parametrize(
    "a, b, same",
    [
        ("Room 1.06 - Computer Laboratory", "Room_1.06", True),
        ("Room 1.06", "room 1.06 — anything", True),
        ("Room 1.06", "Room 1.07", False),
        # A building that names rooms in words rather than numbers still matches.
        ("Atrium", "atrium", True),
        ("Atrium", "Foyer", False),
    ],
)
def test_rooms_match_on_the_identifier_the_building_itself_uses(a, b, same):
    assert _same_room(a, b) is same


def test_identifier_falls_back_to_the_whole_name():
    assert _identifier("Atrium") == "atrium"
    assert _identifier("Room 5.01 — Lab") == "5.01"


# ── the timetable join ─────────────────────────────────────────────────────────────────


def test_a_session_time_combines_with_the_date():
    got = _combine(date(2026, 9, 5), "09:00")
    assert got == datetime(2026, 9, 5, 9, 0)


def test_an_unparseable_session_time_is_dropped_not_guessed():
    """A register with a malformed time must not produce a check for the wrong moment."""
    assert _combine(date(2026, 9, 5), "") is None
    assert _combine(date(2026, 9, 5), "soon") is None
    assert _combine(date(2026, 9, 5), "99:99") is None


# ── the schedule is opt-in ─────────────────────────────────────────────────────────────


def test_the_scheduled_dispatch_is_off_by_default():
    """A building that upgrades must not start receiving unsolicited messages."""
    from shared.config import Settings

    assert Settings.model_fields["READINESS_CHECK_INTERVAL_SECS"].default == 0
    assert Settings.model_fields["READINESS_LEAD_MINUTES"].default == 30


def test_the_lane_is_collected_by_the_response_node():
    """Step 3 of the three-step checklist — the one this codebase keeps forgetting.

    A node that computes an answer nothing collects produces "I processed your request,
    but couldn't generate a response", and its own tests pass the whole time.
    """
    import inspect

    from orchestrator.workflow import _orchestrator

    src = inspect.getsource(_orchestrator)
    assert "_readiness_result" in src
    assert 'get("readiness_result")' in src, "the dispatch never reads the lane's key"
    assert '_readiness_result["formatted_response"]' in src, (
        "the lane computes an answer that the response node never collects"
    )
