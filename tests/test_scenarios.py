# -*- coding: utf-8 -*-
"""V5-T15/T28: what-ifs answer from MEASURED sensitivity or decline honestly."""

from __future__ import annotations

import pytest

from orchestrator.services.deliberation.scenarios import (
    MIN_R2,
    ScenarioSpec,
    apply_scenario,
    decline_reason,
    measure_sensitivity,
    parse_scenario,
    render_scenario_answer,
)

pytestmark = pytest.mark.unit


def _paired(n=48, slope=8.0, base=420.0, occ_pattern=None, noise=0.0):
    """Occupancy + response series sharing timestamps; response = base+slope*occ."""
    occ, resp = [], []
    for i in range(n):
        ts = f"2026-08-18 {i // 6:02d}:{(i % 6) * 10:02d}"
        o = occ_pattern[i % len(occ_pattern)] if occ_pattern else (i % 12)
        occ.append((ts, float(o)))
        resp.append((ts, base + slope * o + (noise * ((i % 5) - 2))))
    return occ, resp


# ── parsing ──────────────────────────────────────────────────────────────────


def test_scenario_overrides_are_parsed():
    s = parse_scenario("Will RM101 be uncomfortable with 200 people at 2pm?")
    assert s.occupancy == 200 and s.hour == 14
    s = parse_scenario("what if there are 45 students in the lecture theatre")
    assert s.occupancy == 45
    s = parse_scenario("CO2 for 30 attendees")
    assert s.occupancy == 30


def test_questions_without_a_counterfactual_yield_an_empty_spec():
    assert parse_scenario("What is the CO2 in RM101?").is_empty()
    assert parse_scenario("Which room is quietest?").is_empty()


# ── measurement ──────────────────────────────────────────────────────────────


def test_sensitivity_is_measured_from_paired_history():
    occ, resp = _paired(slope=8.0, base=420.0)
    sens = measure_sensitivity(occ, resp)
    assert sens is not None and sens.usable()
    assert sens.slope == pytest.approx(8.0, abs=0.01)
    assert sens.r2 > 0.99 and sens.occ_max == 11


def test_no_occupancy_variation_cannot_be_measured():
    occ, resp = _paired(occ_pattern=[5])  # constant occupancy
    assert measure_sensitivity(occ, resp) is None


def test_too_few_paired_points_is_refused():
    occ, resp = _paired(n=6)
    assert measure_sensitivity(occ, resp) is None


def test_unrelated_series_produce_an_unusable_fit():
    occ, _ = _paired()
    _, noise_resp = _paired(slope=0.0, base=500.0, noise=50.0)
    sens = measure_sensitivity(occ, noise_resp)
    assert sens is None or not sens.usable() or sens.r2 < MIN_R2


# ── application ──────────────────────────────────────────────────────────────


def test_scenario_applies_the_measured_slope():
    occ, resp = _paired(slope=8.0, base=420.0)
    sens = measure_sensitivity(occ, resp)
    out = apply_scenario(
        baseline_value=460.0, baseline_occupancy=5, spec=ScenarioSpec(occupancy=15), sens=sens
    )
    assert out["delta_people"] == 10
    assert out["scenario"] == pytest.approx(460 + 80, abs=1.0)
    assert out["extrapolation_factor"] > 0  # 15 exceeds the observed max of 11


def test_within_range_scenarios_are_not_flagged_as_extrapolation():
    occ, resp = _paired(slope=8.0)
    sens = measure_sensitivity(occ, resp)
    out = apply_scenario(500.0, 5, ScenarioSpec(occupancy=9), sens)
    assert out["extrapolation_factor"] == 0.0


def test_narration_declares_method_and_extrapolation():
    occ, resp = _paired(slope=8.0)
    sens = measure_sensitivity(occ, resp)
    out = apply_scenario(460.0, 5, ScenarioSpec(occupancy=200), sens)
    text = render_scenario_answer("co2", " ppm", "RM101", ScenarioSpec(occupancy=200, hour=14), out)
    assert "measured on this building, not assumed" in text
    assert "per person" in text and "R²" in text
    assert "extrapolation" in text.lower()
    assert "200 people at 14:00" in text


def test_every_narrated_number_exists_in_the_payload():
    from orchestrator.services.numeric_guard import collect, find_unbacked

    occ, resp = _paired(slope=8.0)
    sens = measure_sensitivity(occ, resp)
    spec = ScenarioSpec(occupancy=15, hour=14)
    out = apply_scenario(460.0, 5, spec, sens)
    text = render_scenario_answer("co2", " ppm", "RM101", spec, out)
    allowed, blobs = set(), []
    # the payload a lane stores: result + the scenario spec + the space label
    collect(
        {**out, "occupancy": spec.occupancy, "hour": spec.hour, "space": "RM101"},
        allowed,
        blobs,
    )
    assert find_unbacked(text, allowed, blobs) == []


# ── honest declines ──────────────────────────────────────────────────────────


def test_decline_for_modality_with_no_occupancy_relationship():
    text = decline_reason("illuminance", None)
    assert "no measured relationship" in text and "invent" in text


def test_decline_when_no_paired_history_exists():
    text = decline_reason("co2", None)
    assert "no paired" in text and "textbook constant" in text


def test_decline_when_the_fit_is_too_weak():
    from orchestrator.services.deliberation.scenarios import Sensitivity

    weak = Sensitivity(slope=0.2, intercept=400, r2=0.02, n_points=40, occ_min=0, occ_max=10)
    text = decline_reason("co2", weak)
    assert "too weak" in text and "false precision" in text
