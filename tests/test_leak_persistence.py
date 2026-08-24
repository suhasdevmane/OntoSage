# -*- coding: utf-8 -*-
"""Slow-leak detection by persistence, and the water modality split (V6-T44).

The defect this replaces is specific and was verified before the work started: the existing
``schedule_violation`` detector flags out-of-hours flow above **half the in-hours median**, so
on a main whose daytime median is 12 L/min a leak must reach 6 L/min before anything notices.
A real slow leak is 0.3 L/min. It is invisible by magnitude and obvious by persistence, and no
amount of threshold tuning bridges that -- which is why this is a new detector rather than a
new constant.

The control cases matter as much as the detection. A leak detector that also fires on a
building with a legitimate continuous overnight draw will be switched off within a week, and
then it detects nothing at all. So the tests below spend more effort on what must NOT fire.
"""

from datetime import datetime, timedelta

import pytest
import yaml

from orchestrator.services.anomaly.detectors import (
    FLOW_MODALITIES,
    minimum_flow_persistence,
)

pytestmark = pytest.mark.unit

BASE = datetime(2026, 8, 1, 0, 0)


def meter(days=10, leak_from=None, leak=0.3, day_flow=12.0, night_idle=0.0, step_min=10):
    """A water main: `day_flow` in hours, `night_idle` overnight, optional leak from day N."""
    out = []
    for d in range(days):
        for m in range(0, 24 * 60, step_min):
            t = BASE + timedelta(days=d, minutes=m)
            v = night_idle if 1 <= t.hour < 5 else day_flow
            if leak_from is not None and d >= leak_from:
                v += leak
            out.append((t, v))
    return out


# -- it must fire on the case that motivated it ------------------------------


def test_a_slow_leak_far_below_any_daytime_threshold_is_detected():
    """0.3 L/min on a 12 L/min main -- 2.5% of normal flow.

    The existing schedule_violation rule would need 6 L/min. This is the whole point.
    """
    found = minimum_flow_persistence(meter(leak_from=6), "w1", "water_flow")
    assert len(found) == 1
    assert found[0].detector == "minimum_flow_persistence"


def test_the_finding_states_the_excess_over_idle_not_the_raw_flow():
    """ "0.3 L/min above idle" is actionable; "0.3 L/min" alone is not, on a meter whose idle
    level might legitimately be 4."""
    f = minimum_flow_persistence(meter(leak_from=6), "w1", "water_flow")[0]
    assert f.evidence["persistent_excess"] == pytest.approx(0.3, abs=0.05)
    assert f.baseline == pytest.approx(0.0, abs=0.01)


def test_the_finding_counts_the_consecutive_nights():
    f = minimum_flow_persistence(meter(leak_from=6), "w1", "water_flow")[0]
    assert f.evidence["consecutive_nights"] >= 3


def test_the_nightly_minima_are_carried_as_evidence():
    """So a person can see the pattern rather than being asked to trust the verdict."""
    f = minimum_flow_persistence(meter(leak_from=6), "w1", "water_flow")[0]
    assert len(f.evidence["nightly_minima"]) >= 3


def test_a_leak_on_top_of_a_legitimate_continuous_draw_is_still_found():
    """The hard case, and the one a fixed threshold cannot do.

    This building genuinely draws 4 L/min all night. A rule with any absolute floor either
    misses the 0.3 leak on top of it or condemns the building for its own baseline.
    """
    found = minimum_flow_persistence(meter(night_idle=4.0, leak_from=6), "w1", "water_flow")
    assert len(found) == 1
    assert found[0].evidence["persistent_excess"] == pytest.approx(0.3, abs=0.05)


# -- and it must stay silent on everything else ------------------------------


def test_a_clean_meter_is_not_flagged():
    assert minimum_flow_persistence(meter(), "w1", "water_flow") == []


def test_a_building_with_a_continuous_overnight_draw_is_not_flagged():
    """Its idle level IS 4 L/min. Flagging it would be flagging it for existing."""
    assert minimum_flow_persistence(meter(night_idle=4.0), "w1", "water_flow") == []


def test_one_late_night_is_not_a_leak():
    """Persistence is the whole discriminator. Without it this is the old broken check."""
    samples = [(t, v + 2.0) if (t.day == 5 and 1 <= t.hour < 5) else (t, v) for t, v in meter()]
    assert minimum_flow_persistence(samples, "w1", "water_flow") == []


def test_two_nights_do_not_meet_a_three_night_rule():
    found = minimum_flow_persistence(meter(days=10, leak_from=8), "w1", "water_flow")
    assert found == []


def test_a_leak_that_was_fixed_is_not_reported_as_current():
    """Trailing run, not longest-anywhere.

    Reporting last month's repaired leak would send someone looking for water that is no
    longer running -- and would keep doing so forever.
    """
    samples = [(t, v + 0.3) if 3 <= (t - BASE).days <= 5 else (t, v) for t, v in meter(days=12)]
    assert minimum_flow_persistence(samples, "w1", "water_flow") == []


def test_a_brand_new_meter_is_not_flagged_on_its_first_nights():
    """With only the run itself observed, "every night is above idle" is trivially true."""
    assert minimum_flow_persistence(meter(days=3, leak_from=0), "w1", "water_flow") == []


def test_a_perfectly_flat_meter_yields_no_finding():
    """Zero variance gives no room to distinguish a leak from the reading itself."""
    flat = [(BASE + timedelta(minutes=10 * i), 5.0) for i in range(24 * 6 * 10)]
    assert minimum_flow_persistence(flat, "w1", "water_flow") == []


def test_too_little_history_returns_nothing_rather_than_guessing():
    assert minimum_flow_persistence(meter(days=1), "w1", "water_flow") == []
    assert minimum_flow_persistence([], "w1", "water_flow") == []


# -- localisation honesty ----------------------------------------------------


def test_a_single_metered_building_says_it_cannot_localise():
    """It can tell you that it is leaking and not where. Omitting that sends someone to the
    wrong floor with a torch."""
    f = minimum_flow_persistence(meter(leak_from=6), "w1", "water_flow", meters_on_this_stream=1)
    assert f[0].evidence["localisable"] is False


def test_a_multi_metered_building_can():
    f = minimum_flow_persistence(meter(leak_from=6), "w1", "water_flow", meters_on_this_stream=4)
    assert f[0].evidence["localisable"] is True


# -- the night window --------------------------------------------------------


def test_a_night_window_crossing_midnight_is_one_night_not_two():
    """Bucketing by calendar date halves every night's apparent minimum, which breaks the
    persistence count by turning one steady leak into two shallower ones."""
    found = minimum_flow_persistence(
        meter(leak_from=6), "w1", "water_flow", night_start_hour=22, night_end_hour=6
    )
    assert len(found) == 1


# -- the modality split ------------------------------------------------------


def test_flow_modalities_cover_the_split():
    assert "water_flow" in FLOW_MODALITIES
    assert "water_flow_hot" in FLOW_MODALITIES
    assert "water_flow_chilled" in FLOW_MODALITIES


def test_the_split_uses_real_brick_classes_only():
    """Brick 1.4 has Hot_Water_* and Chilled_Water_* but NO domestic-cold sensor class.

    Declaring a generic Water_Meter to be "cold" would assert something about what that meter
    measures that nothing in the graph supports. So there is deliberately no cold entry, and
    this test exists to stop one being added by analogy.
    """
    from pathlib import Path

    cfg = yaml.safe_load(
        (
            Path(__file__).resolve().parent.parent / "config" / "saturation_modalities.yaml"
        ).read_text(encoding="utf-8")
    )["modalities"]
    assert "water_flow_hot" in cfg and "water_flow_chilled" in cfg
    assert "water_flow_cold" not in cfg
    assert "Hot_Water_Meter" in cfg["water_flow_hot"]["brick_classes"]


def test_the_new_modalities_are_challengeable_by_the_absence_guard():
    """ "This building has no hot water sensors" is a different false claim from "no water
    sensors", and a guard that only knew the umbrella term would let the narrower one pass."""
    from orchestrator.services.absence_guard import _MODALITY_ALIASES

    assert "water_flow_hot" in _MODALITY_ALIASES
    assert "water_flow_chilled" in _MODALITY_ALIASES


def test_the_scanner_runs_both_water_detectors():
    """They see different failures: a burst rivalling daytime demand, and a trickle that never
    stops. Dropping either leaves a real gap."""
    from orchestrator.services.anomaly.scanner import ACTIVITY_MODALITIES
    from orchestrator.services.anomaly.scanner import FLOW_MODALITIES as SFM

    assert "water_flow" in ACTIVITY_MODALITIES
    assert "water_flow" in SFM
