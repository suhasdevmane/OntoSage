# -*- coding: utf-8 -*-
"""CAVEAT-149: MAPE is unusable on zero-heavy series; sMAPE and MASE are not.

Night-time occupancy and a quiet room's noise floor are mostly zeros. MAPE
divides by the actual, so it is computed over a nonzero mask — most of the series
is discarded and the survivors (small values) dominate, producing an unstable
number that still looks like a quality score. MAE is stable but scale-dependent,
so it cannot rank a CO2 forecast against a temperature one.
"""

from __future__ import annotations

import math

import numpy as np
import pytest

from orchestrator.services.forecasting.metrics import compute_metrics

pytestmark = pytest.mark.unit


def test_a_perfect_forecast_scores_zero_error_on_every_metric():
    a = np.array([1.0, 2.0, 3.0, 4.0])
    m = compute_metrics(a, a.copy(), "perfect")
    assert m.rmse == 0 and m.mae == 0
    assert m.smape == pytest.approx(0.0)
    assert m.mase == pytest.approx(0.0)


def test_zeros_are_kept_by_smape_but_dropped_by_mape():
    """The CAVEAT-149 case: a mostly-zero series."""
    actual = np.array([0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 2.0])
    predicted = np.array([0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 1.0])
    m = compute_metrics(actual, predicted, "night-occupancy")
    # MAPE sees ONE point (the single nonzero actual) and calls it 50% error
    assert m.mape == pytest.approx(50.0)
    # sMAPE sees all eight: seven perfect zeros and one 2-vs-1
    assert 0 < m.smape < 20, f"sMAPE should reflect the whole series, got {m.smape}"


def test_a_matched_zero_is_a_perfect_point_not_a_gap():
    m = compute_metrics(np.zeros(5), np.zeros(5), "all-zero")
    assert m.smape == pytest.approx(0.0)
    assert not math.isinf(m.smape)


def test_smape_is_symmetric():
    a = np.array([10.0, 20.0])
    over = compute_metrics(a, a * 1.5, "over").smape
    under = compute_metrics(a * 1.5, a, "under").smape
    assert over == pytest.approx(under)


def test_mase_of_one_means_no_better_than_the_naive_forecast():
    """Predicting 'same as last value' must score ~1.0 by construction."""
    actual = np.array([1.0, 2.0, 3.0, 4.0, 5.0])
    naive = np.array([1.0, 1.0, 2.0, 3.0, 4.0])  # previous value each step
    assert compute_metrics(actual, naive, "naive").mase == pytest.approx(1.0, rel=0.35)


def test_mase_is_scale_free_so_modalities_are_comparable():
    """The same relative error on CO2-sized and temperature-sized data scores alike."""
    small = np.array([20.0, 21.0, 22.0, 23.0])
    big = small * 50
    m_small = compute_metrics(small, small + 0.5, "temp")
    m_big = compute_metrics(big, big + 25.0, "co2")
    assert m_small.mase == pytest.approx(m_big.mase, rel=1e-6)
    assert m_small.mae != pytest.approx(m_big.mae)  # MAE cannot do this


def test_a_constant_series_has_no_naive_baseline():
    m = compute_metrics(np.array([5.0, 5.0, 5.0]), np.array([5.0, 5.1, 4.9]), "flat")
    assert math.isnan(m.mase)


def test_empty_input_is_infinite_not_a_crash():
    m = compute_metrics(np.array([]), np.array([]), "empty")
    assert math.isinf(m.smape) and math.isinf(m.mase) and m.n_test == 0


def test_the_new_metrics_are_reported():
    m = compute_metrics(np.array([1.0, 2.0]), np.array([1.1, 2.1]), "x")
    d = m.to_dict()
    assert "smape" in d and "mase" in d
    assert "sMAPE" in m.summary() and "MASE" in m.summary()
