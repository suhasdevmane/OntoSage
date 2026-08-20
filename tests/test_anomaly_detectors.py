# -*- coding: utf-8 -*-
"""V5-T18: deterministic detector suite — positives AND the mandated negatives
(a normal daily cycle must never be flagged)."""

from __future__ import annotations

from datetime import datetime, timedelta

import pytest

from orchestrator.services.anomaly.detectors import (
    cross_modality_inconsistency,
    drift_vs_peers,
    dropout,
    schedule_violation,
    seasonal_residual,
    spike,
    stuck,
)

pytestmark = pytest.mark.unit

T0 = datetime(2026, 8, 3, 0, 0, 0)  # a Monday
UID = "u-test"


def _daily_cycle(days=4, step_min=60, day_val=800.0, night_val=420.0, jitter=None):
    out = []
    for i in range(days * 24 * 60 // step_min):
        ts = T0 + timedelta(minutes=step_min * i)
        v = day_val if 9 <= ts.hour < 18 else night_val
        if jitter:
            v += jitter * ((i % 7) - 3) / 3.0  # deterministic wobble
        out.append((ts, v))
    return out


# ── seasonal residual ────────────────────────────────────────────────────────


def test_clean_daily_cycle_is_not_flagged():
    assert seasonal_residual(_daily_cycle(days=4, jitter=5.0), UID, "co2") == []


def test_seasonal_residual_flags_a_shifted_tail():
    series = _daily_cycle(days=5, jitter=5.0)
    # corrupt the final 6 hours: +500 over profile
    series = [
        (t, v + 500.0) if t >= series[-1][0] - timedelta(hours=6) else (t, v) for t, v in series
    ]
    found = seasonal_residual(series, UID, "co2")
    assert len(found) == 1
    f = found[0]
    assert f.detector == "seasonal_residual" and f.score > 1.0
    assert (f.end - f.start) >= timedelta(hours=5)
    assert f.severity in ("medium", "high")


# ── stuck ────────────────────────────────────────────────────────────────────


def test_stuck_flags_a_flat_tail_on_a_moving_signal():
    series = _daily_cycle(days=3)
    freeze_from = series[-1][0] - timedelta(hours=8)
    series = [(t, 613.0) if t >= freeze_from else (t, v) for t, v in series]
    found = stuck(series, UID, "co2")
    assert len(found) == 1
    assert found[0].evidence["stuck_hours"] >= 7.5
    assert found[0].baseline == 613.0


def test_naturally_constant_signal_is_not_stuck():
    series = [(T0 + timedelta(hours=i), 1.0) for i in range(72)]
    assert stuck(series, UID, "contact") == []


# ── dropout ──────────────────────────────────────────────────────────────────


def test_dropout_flags_a_reporting_hole():
    series = [(T0 + timedelta(minutes=10 * i), 5.0) for i in range(144)]
    hole_start = series[60][0]
    series = [s for s in series if not (hole_start < s[0] < hole_start + timedelta(hours=3))]
    found = dropout(series, UID, "noise")
    assert len(found) == 1
    assert found[0].evidence["gap_minutes"] == pytest.approx(180.0, abs=15)


def test_regular_cadence_has_no_dropout():
    series = [(T0 + timedelta(minutes=10 * i), 5.0) for i in range(144)]
    assert dropout(series, UID, "noise") == []


# ── drift vs peers ───────────────────────────────────────────────────────────


def _flat(val, hours=12):
    return [(T0 + timedelta(hours=i), val + 0.05 * ((i % 5) - 2)) for i in range(hours)]


def test_drift_flags_the_outlier_room():
    peers = {f"p{i}": _flat(22.0 + 0.1 * i) for i in range(5)}
    found = drift_vs_peers(_flat(30.0), peers, UID, "temperature")
    assert len(found) == 1
    assert found[0].evidence["n_peers"] == 5
    assert found[0].baseline == pytest.approx(22.2, abs=0.3)


def test_a_room_tracking_its_peers_is_not_drifting():
    peers = {f"p{i}": _flat(22.0 + 0.1 * i) for i in range(5)}
    assert drift_vs_peers(_flat(22.3), peers, UID, "temperature") == []


def test_two_peers_are_not_enough_to_judge():
    peers = {"p1": _flat(22.0), "p2": _flat(22.1)}
    assert drift_vs_peers(_flat(30.0), peers, UID, "temperature") == []


# ── schedule violation ───────────────────────────────────────────────────────


def _occupancy(days=7, weekend_activity=False):
    out = []
    for i in range(days * 24):
        ts = T0 + timedelta(hours=i)
        weekday = ts.weekday() < 5
        active = weekday and 8 <= ts.hour < 18
        v = 6.0 if active else 0.0
        if weekend_activity and ts.weekday() == 5 and 1 <= ts.hour < 4:
            v = 5.0
        out.append((ts, v))
    return out


def test_in_hours_activity_is_normal():
    assert schedule_violation(_occupancy(), UID, "occupancy") == []


def test_saturday_3am_activity_is_flagged():
    found = schedule_violation(_occupancy(weekend_activity=True), UID, "occupancy")
    assert len(found) == 1
    assert found[0].start.weekday() == 5 and found[0].start.hour == 1
    assert found[0].baseline == pytest.approx(6.0)


# ── spike ────────────────────────────────────────────────────────────────────


def test_spike_flags_a_single_burst():
    series = [(T0 + timedelta(minutes=10 * i), 40.0 + (i % 3)) for i in range(100)]
    series[70] = (series[70][0], 400.0)
    found = spike(series, UID, "noise")
    assert len(found) == 1 and found[0].start == series[70][0]


def test_smooth_series_has_no_spikes():
    series = [(T0 + timedelta(minutes=10 * i), 40.0 + (i % 3)) for i in range(100)]
    assert spike(series, UID, "noise") == []


# ── cross-modality ───────────────────────────────────────────────────────────


def _pair(occupied: bool, co2_rising: bool):
    occ, co2 = [], []
    for i in range(48):
        ts = T0 + timedelta(minutes=10 * i)
        occ.append((ts, 5.0 if (occupied or i < 24) else 0.0))
        base = 420.0 + (i * 8.0 if co2_rising else 0.0)
        co2.append((ts, base))
    return occ, co2


def test_co2_rising_in_an_empty_room_is_inconsistent():
    occ, co2 = _pair(occupied=False, co2_rising=True)
    found = cross_modality_inconsistency(occ, co2, UID, "co2")
    assert len(found) == 1
    assert found[0].detector == "cross_modality" and found[0].score > 1.0


def test_co2_rising_in_an_occupied_room_is_expected():
    occ, co2 = _pair(occupied=True, co2_rising=True)
    assert cross_modality_inconsistency(occ, co2, UID, "co2") == []


def test_flat_co2_in_an_empty_room_is_fine():
    occ, co2 = _pair(occupied=False, co2_rising=False)
    assert cross_modality_inconsistency(occ, co2, UID, "co2") == []


def test_overnight_zero_occupancy_is_resting_not_stuck():
    """Occupancy sits flat at ZERO all night — that is its modal resting level."""
    series = []
    for i in range(72):
        ts = T0 + timedelta(hours=i)
        series.append((ts, 6.0 if (ts.weekday() < 5 and 8 <= ts.hour < 18) else 0.0))
    # series ends mid-night: a long flat-at-zero tail
    assert series[-1][1] == 0.0
    assert stuck(series, UID, "occupancy") == []


def test_identical_peers_do_not_blow_up_drift_scores():
    """Live shakedown: identical synthetic peers made the MAD collapse and a
    hair of difference scored 11,111,111. Scores must stay on a sane scale."""
    peers = {f"p{i}": [(T0 + timedelta(hours=h), 22.0) for h in range(12)] for i in range(4)}
    target = [(T0 + timedelta(hours=h), 22.0) for h in range(12)]
    assert drift_vs_peers(target, peers, UID, "temperature") == []
    outlier = [(T0 + timedelta(hours=h), 30.0) for h in range(12)]
    found = drift_vs_peers(outlier, peers, UID, "temperature")
    assert found and found[0].score < 100
