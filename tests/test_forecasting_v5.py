# -*- coding: utf-8 -*-
"""V5-T12/T13: seasonal-naive tier, ModelSelector adapter, horizon authority."""

from __future__ import annotations

import asyncio
import math
from datetime import datetime, timedelta

import pytest

from orchestrator.services.deliberation.cqir import TimeBasis, TimeSpec
from orchestrator.services.forecasting.adapter import (
    infer_grid_seconds,
    model_selector_forecast,
)
from orchestrator.services.forecasting.horizon_parser import (
    match_horizon,
    parse_horizon,
)
from orchestrator.services.forecasting.models.seasonal_naive_forecaster import (
    SeasonalNaiveForecaster,
    build_profile,
    seasonal_naive_point,
)

pytestmark = pytest.mark.unit

T0 = datetime(2026, 8, 3, 0, 0, 0)  # a Monday


def _cyclic_series(days: int, day_val: float = 60.0, night_val: float = 20.0, end_hour: int = 23):
    """Hourly [(iso, value)] with a hard day/night square wave, newest-last."""
    out = []
    hours = days * 24 - (23 - end_hour)
    for i in range(hours):
        ts = T0 + timedelta(hours=i)
        v = day_val if 12 <= ts.hour <= 23 else night_val
        out.append((ts.strftime("%Y-%m-%d %H:%M:%S"), v))
    return out


# ── seasonal-naive core (pure python, T13) ───────────────────────────────────


def test_seasonal_point_tracks_the_coming_phase_not_the_history_mean():
    # history ends at 11:00 — the next 12 hours are the LOUD phase (60),
    # while the history mean is 40: the profile must predict ~60.
    series = _cyclic_series(days=3, end_hour=11)
    value, model = seasonal_naive_point(series, horizon_hours=12)
    assert value == pytest.approx(60.0, abs=1.0)
    assert model.startswith("seasonal-naive")
    # deterministic
    assert seasonal_naive_point(series, 12) == (value, model)


def test_seasonal_point_uses_weekday_bins_with_long_history():
    series = _cyclic_series(days=15)
    _, model = seasonal_naive_point(series, horizon_hours=24)
    assert "hour-of-week" in model


def test_seasonal_point_declines_tiny_series():
    assert seasonal_naive_point([("2026-08-03 10:00:00", 1.0)] * 3, 24) is None


def test_profile_fallback_ladder():
    times = [T0 + timedelta(hours=i) for i in range(24)]  # Monday only
    values = [float(i) for i in range(24)]
    p = build_profile(times, values)
    # same weekday+hour → exact bin
    assert p.value_at(T0 + timedelta(days=7, hours=5)) == pytest.approx(5.0)
    # other weekday, known hour → hour bin
    assert p.value_at(T0 + timedelta(days=1, hours=5)) == pytest.approx(5.0)


# ── ModelSelector integration (T13) ──────────────────────────────────────────


def _pd_series(n_hours: int):
    pd = pytest.importorskip("pandas")
    idx = pd.date_range("2026-08-03", periods=n_hours, freq="1h")
    vals = [60.0 if 12 <= t.hour <= 23 else 20.0 for t in idx]
    return pd.Series(vals, index=idx)


def test_seasonal_naive_beats_linear_on_daily_cycle():
    from orchestrator.services.forecasting.models.linear_forecaster import (
        LinearTrendForecaster,
    )

    series = _pd_series(96)
    sn = SeasonalNaiveForecaster().fit_predict(series, n_steps=12)
    lin = LinearTrendForecaster(degree=1).fit_predict(series, n_steps=12)
    assert sn["metrics"].mae < lin["metrics"].mae


def test_model_selector_lets_seasonal_naive_win_on_cyclic_data():
    from orchestrator.services.forecasting.model_selector import ModelSelector

    result = ModelSelector().select_and_forecast(_pd_series(96), n_steps=12)
    assert "SeasonalNaive" in result["all_metrics"]
    winner_mae = result["all_metrics"][result["winner"]].mae
    for m in result["all_metrics"].values():
        assert m.mae >= winner_mae - 1e-9


# ── adapter (T12) ────────────────────────────────────────────────────────────


def test_infer_grid_snaps_to_standard_steps():
    ten_min = [(T0 + timedelta(minutes=10 * i)).isoformat() for i in range(20)]
    hourly = [(T0 + timedelta(hours=i)).isoformat() for i in range(20)]
    assert infer_grid_seconds(ten_min) == 600
    assert infer_grid_seconds(hourly) == 3600


def test_adapter_returns_model_ci_and_backtest_fields():
    pytest.importorskip("pandas")
    series = _cyclic_series(days=4)
    rich = asyncio.run(model_selector_forecast(series, horizon_hours=24))
    assert rich is not None
    assert rich["model"]
    assert rich["backtest_mae"] is not None and rich["backtest_mae"] >= 0
    assert rich["n_train"] > 0
    assert rich["ci95"] is None or rich["ci95"][0] <= rich["ci95"][1]
    assert not math.isnan(rich["value"])


def test_adapter_declines_thin_series():
    assert asyncio.run(model_selector_forecast([("2026-08-03 10:00:00", 1.0)] * 4, 24)) is None


# ── horizon authority (T12) ──────────────────────────────────────────────────


def test_match_horizon_recognizes_and_declines():
    assert match_horizon("predict CO2 for tomorrow").total == timedelta(hours=24)
    assert match_horizon("what will it be like eventually") is None
    # parse_horizon keeps its defaulting contract
    assert parse_horizon("no phrase here").label == "next 24 hours"


def test_compiler_fold_makes_the_rule_table_the_authority():
    from orchestrator.services.deliberation.compiler import _fold_deterministic_horizon

    # recognized phrase overrides the LLM's guess
    spec = TimeSpec(basis=TimeBasis.FORECAST, horizon_hours=3.0)
    _fold_deterministic_horizon(spec, "which room will be coolest next week?")
    assert spec.horizon_hours == pytest.approx(168.0)
    # unrecognized phrase keeps the LLM's number
    spec = TimeSpec(basis=TimeBasis.FORECAST, horizon_hours=3.0)
    _fold_deterministic_horizon(spec, "later on")
    assert spec.horizon_hours == pytest.approx(3.0)
    # nothing at all defaults to 24h
    spec = TimeSpec(basis=TimeBasis.FORECAST, horizon_hours=None)
    _fold_deterministic_horizon(spec, "sometime soon-ish")
    assert spec.horizon_hours == pytest.approx(24.0)
    # non-forecast bases are untouched
    spec = TimeSpec(basis=TimeBasis.NOW, horizon_hours=None)
    _fold_deterministic_horizon(spec, "tomorrow")
    assert spec.horizon_hours is None


def test_trend_lane_and_cqir_agree_on_identical_phrases():
    phrase = "forecast the temperature for next week"
    spec = TimeSpec(basis=TimeBasis.FORECAST, horizon_hours=999.0)
    from orchestrator.services.deliberation.compiler import _fold_deterministic_horizon

    _fold_deterministic_horizon(spec, phrase)
    trend = parse_horizon(phrase)
    assert spec.horizon_hours == pytest.approx(trend.total.total_seconds() / 3600.0)
