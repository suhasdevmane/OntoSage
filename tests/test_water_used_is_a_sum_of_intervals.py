"""Water used over a period is the SUM of the meter's interval volumes (2026-10-11).

"How much water did the building use yesterday?" was answered "The building used 8.90 L" -- the
meter's LATEST quarter-hour, stated as the day's total, the BUG-1437 failure that interval energy
was protected from and interval volume was not.
"""

from __future__ import annotations

import pytest

from orchestrator.services import aggregate_lane as al
from orchestrator.services import series_summary as ss

pytestmark = pytest.mark.unit

U = "ec82da0d-dd27-5565-9851-e950bade85e8"


def test_the_lane_claims_a_volume_total_over_a_named_period_only():
    q = "How much water did the building use yesterday?"
    assert al.wants_lane(q, 1, False, False, ["volume"]).stat == "total"
    assert (
        al.wants_lane("How much water is it using right now?", 1, False, False, ["volume"]) is None
    )


def test_the_narrated_total_is_the_sum_never_the_latest_reading():
    rows = [
        {"uuid": U, "timestamp": "2026-10-10T08:00:00", "value": 100.0},
        {"uuid": U, "timestamp": "2026-10-10T08:15:00", "value": 120.0},
        {"uuid": U, "timestamp": "2026-10-10T08:30:00", "value": 8.9},
    ]
    meta = {U: {"label": "Building-Level Water Meter", "unit": "L"}}
    text = ss.summarise_energy_totals(rows, meta)
    assert "229 L across 1 series" in text  # 100 + 120 + 8.9, never the latest 8.9
    assert "Each reading is the volume drawn in its own interval" in text


def test_a_mixed_volume_and_energy_set_is_never_added_up():
    rows = [
        {"uuid": "a", "timestamp": "2026-10-10T08:00:00", "value": 100.0},
        {"uuid": "b", "timestamp": "2026-10-10T08:00:00", "value": 5.0},
    ]
    meta = {"a": {"label": "water", "unit": "L"}, "b": {"label": "energy meter", "unit": "kWh"}}
    assert ss.summarise_energy_totals(rows, meta) is None
