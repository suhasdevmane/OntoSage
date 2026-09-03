# -*- coding: utf-8 -*-
"""A stored reading is naive UTC; a human's time is building-local (BUG-403, reader half).

Two wrongs were cancelling, and correcting one of them exposed the other.

The publisher stamped narrow rows with SQL ``NOW()`` on a BST session, so rows landed an
hour ahead. Evidence assembly then read those naive stamps as building-local (BST), which
shifted them back an hour. Net error zero, and invisible — until the writer was pinned to
UTC. Measured live on bldg1 immediately after that fix, a co2 reading taken three minutes
earlier came back as ``2026-09-03T11:49:35+01:00`` and the freshness gate — ENFORCING, with
a 5-minute limit for co2 — downgraded a genuinely current answer to INFERRED.

Fixing a clock at one end and not the other is worse than leaving both wrong. These tests
pin both halves so neither can be corrected alone again.

The split is deliberate and is not a default that could simply be flipped: *"between 9 and
5"* means nine and five **in the building**, while a row in ``sensor_data`` means UTC. One
function per meaning.
"""

from datetime import datetime, timedelta, timezone

import pytest

from orchestrator.services.evidence.assemble import _as_datetime, _as_observation_time

pytestmark = pytest.mark.unit


# ── stored readings ────────────────────────────────────────────────────────────────────


def test_a_naive_reading_is_utc():
    dt = _as_observation_time("2026-09-03 11:49:35")
    assert dt is not None and dt.tzinfo is not None
    assert dt.utcoffset() == timedelta(0)
    assert dt.hour == 11, "an hour was added or removed on the way in"


def test_a_naive_datetime_object_is_utc_too():
    """MySQL hands back datetime objects, not strings — the common path."""
    dt = _as_observation_time(datetime(2026, 9, 3, 11, 49, 35))
    assert dt.utcoffset() == timedelta(0) and dt.hour == 11


def test_an_explicit_offset_is_respected_not_overwritten():
    dt = _as_observation_time("2026-09-03T11:49:35+02:00")
    assert dt.utcoffset() == timedelta(hours=2)


def test_a_z_suffix_is_respected():
    dt = _as_observation_time("2026-09-03T11:49:35Z")
    assert dt.utcoffset() == timedelta(0) and dt.hour == 11


def test_an_aware_datetime_object_is_respected():
    aware = datetime(2026, 9, 3, 11, 49, 35, tzinfo=timezone(timedelta(hours=5)))
    assert _as_observation_time(aware).utcoffset() == timedelta(hours=5)


def test_nonsense_is_none_not_an_exception():
    for value in ("not a time", "", None, 12345, "2026-13-45 99:99:99"):
        assert _as_observation_time(value) is None


def test_a_reading_three_minutes_old_is_not_an_hour_old():
    """The exact live failure: a 5-minute policy saw 63 minutes and downgraded the answer."""
    now = datetime.now(timezone.utc)
    observed = _as_observation_time((now - timedelta(minutes=3)).strftime("%Y-%m-%d %H:%M:%S"))
    age_minutes = (now - observed).total_seconds() / 60.0
    assert 2.0 <= age_minutes <= 4.0, f"age came out {age_minutes:.0f} min, not ~3"


# ── human / ontology times keep building-local ─────────────────────────────────────────


def test_a_human_expressed_time_stays_building_local():
    """ "Between 9 and 5" means nine and five THERE; this must not become UTC.

    Asserted as an offset rather than a specific zone so a building elsewhere still passes.
    """
    from zoneinfo import ZoneInfo

    from shared.config import settings

    naive = "2026-09-03 09:00:00"
    expected = datetime(2026, 9, 3, 9, 0).replace(tzinfo=ZoneInfo(settings.BUILDING_TIMEZONE))
    assert _as_datetime(naive).utcoffset() == expected.utcoffset()


def test_the_two_readers_are_separate_functions():
    """A single default could be flipped by someone who only had one case in mind."""
    assert _as_datetime is not _as_observation_time


def test_only_row_timestamps_use_the_utc_reader():
    """Pinned against the source: the observation reader belongs to the data lanes only."""
    import inspect

    from orchestrator.services.evidence import assemble

    src = inspect.getsource(assemble)
    # Every use sits inside a loop over sql_result / analytics_result rows.
    assert src.count("_as_observation_time(value)") == 3, (
        "a call site was added or removed; confirm it reads a STORED reading and not a "
        "time a human or the ontology expressed"
    )
