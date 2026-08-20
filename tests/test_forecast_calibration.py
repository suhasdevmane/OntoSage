# -*- coding: utf-8 -*-
"""V5-T14: registry-driven CI calibration — factors, widening, honest fallbacks."""

from __future__ import annotations

import json

import pytest

from orchestrator.services.forecasting.calibration import (
    band_factors,
    calibrate_band,
    load_registry,
    reset_cache_for_tests,
)

pytestmark = pytest.mark.unit


@pytest.fixture(autouse=True)
def _fresh_cache():
    reset_cache_for_tests()
    yield
    reset_cache_for_tests()


def _write_registry(tmp_path, building, payload):
    p = tmp_path / "volumes" / building / "artifacts" / "forecast_skill.json"
    p.parent.mkdir(parents=True)
    p.write_text(json.dumps(payload), encoding="utf-8")
    return tmp_path


def test_measured_undercoverage_widens_bands(tmp_path):
    root = _write_registry(
        tmp_path, "tb", {"co2": {"24h": {"ci80_coverage": 0.48, "ci95_coverage": 0.59}}}
    )
    f80, f95 = band_factors("tb", "co2", 24, repo_root=root)
    # z(0.80)/z(0.48) ≈ 1.28/0.64 ≈ 2 — the measured 2x over-confidence
    assert 1.8 <= f80 <= 2.2
    assert 1.5 <= f95 <= 3.0
    band = calibrate_band((400.0, 450.0), 425.0, f80)
    assert band[0] < 400.0 and band[1] > 450.0
    # symmetric widening around the value
    assert band[1] - 425.0 == pytest.approx(425.0 - band[0], abs=0.01)


def test_covering_bands_are_never_narrowed(tmp_path):
    root = _write_registry(
        tmp_path, "tb", {"noise": {"1h": {"ci80_coverage": 0.9, "ci95_coverage": 0.97}}}
    )
    assert band_factors("tb", "noise", 1, repo_root=root) == (1.0, 1.0)
    assert calibrate_band((30.0, 34.0), 32.0, 1.0) == (30.0, 34.0)


def test_unknown_modality_or_building_is_uncalibrated(tmp_path):
    root = _write_registry(tmp_path, "tb", {"co2": {"24h": {"ci80_coverage": 0.5}}})
    assert band_factors("tb", "krypton", 24, repo_root=root) == (1.0, 1.0)
    assert band_factors("other_building", "co2", 24, repo_root=root) == (1.0, 1.0)
    assert load_registry("missing", repo_root=tmp_path) == {}


def test_nearest_horizon_is_used(tmp_path):
    root = _write_registry(
        tmp_path, "tb", {"co2": {"6h": {"ci80_coverage": 0.4}, "24h": {"ci80_coverage": 0.75}}}
    )
    f80_5h, _ = band_factors("tb", "co2", 5, repo_root=root)  # nearest = 6h (0.4)
    f80_20h, _ = band_factors("tb", "co2", 20, repo_root=root)  # nearest = 24h (0.75)
    assert f80_5h > f80_20h > 1.0


def test_factor_cap_prevents_explosions(tmp_path):
    root = _write_registry(tmp_path, "tb", {"co2": {"24h": {"ci80_coverage": 0.05}}})
    f80, _ = band_factors("tb", "co2", 24, repo_root=root)
    assert f80 == 4.0
