# -*- coding: utf-8 -*-
"""H6 (QA-trial plan, 2026-10-04): discharging the owed live check on
/api/v1/admin/sensors/health found a genuine bug, not a clean pass.

Called live as admin: ALL 2,860 assessed sensors came back "stale", every one at
EXACTLY 60.0 minutes old. The data was not stale -- MAX(datetime) for one of them,
checked directly against MySQL, was about 1 minute old in UTC. Root cause: the
endpoint computed age from `local_now.replace(tzinfo=None)` (the BUILDING's local zone,
BST = UTC+1 at the time) against `stamps`, which are naive UTC (every store is UTC,
BUG-403) -- comparing UTC-stored data against LOCAL wall-clock time produces exactly a
systematic ~60-minute offset. `now` (already UTC) was computed two lines earlier in the
same function and simply never used for this comparison.
"""
from datetime import datetime, timedelta

import pytest

from orchestrator.services.evidence.sensor_health import HealthState, assess_sensor

pytestmark = pytest.mark.unit


class TestAssessSensorItself:
    def test_a_reading_one_minute_old_in_utc_is_not_stale(self):
        """The exact live shape: a naive-UTC timestamp close to a naive-UTC now. Without
        expected_samples this call shape reports UNKNOWN rather than HEALTHY (correct --
        "not enough information to judge" cadence), but it must NOT be STALE, which is
        the state the timezone bug this row found actually produced."""
        now = datetime(2026, 10, 4, 7, 24, 38)
        latest = datetime(2026, 10, 4, 7, 23, 52)
        health = assess_sensor("s1", [latest], now, max_age_minutes=5.0)
        assert health.state != HealthState.STALE
        assert health.age_minutes == pytest.approx(0.8, abs=0.1)

    def test_comparing_utc_data_against_a_one_hour_ahead_clock_reproduces_the_live_bug(self):
        """Demonstrates the BUG, not the fix: this is what local_now.replace(tzinfo=None)
        actually did when the session's timezone is UTC+1 -- kept here so the shape of
        the defect this row found stays on record even though the endpoint no longer
        does it."""
        utc_latest = datetime(2026, 10, 4, 7, 23, 52)
        bst_now_made_naive = datetime(2026, 10, 4, 8, 24, 38)  # UTC+1, tzinfo stripped
        health = assess_sensor("s1", [utc_latest], bst_now_made_naive, max_age_minutes=5.0)
        assert health.state == HealthState.STALE
        assert health.age_minutes == pytest.approx(60.8, abs=0.2)


class TestTheEndpointUsesUtcNotLocal:
    def test_the_endpoint_passes_now_not_local_now_to_assess_sensor(self):
        import inspect

        from orchestrator import main

        src = inspect.getsource(main.sensors_health)
        assert "assess_sensor(u, stamps, now.replace(tzinfo=None), max_age)" in src
        assert "local_now.replace(tzinfo=None)" not in src
