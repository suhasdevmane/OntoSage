"""
Tests for the OntoSage real forecasting pipeline.

Covers:
  - Horizon parser: all supported phrases
  - Metrics: RMSE, MAE, MAPE, R² correctness
  - Preprocessor: gap filling, outlier clipping, resampling
  - Linear forecaster: shape and CI coverage
  - ExpSmoothing forecaster: shape and CI coverage
  - ARIMA forecaster: shape and CI coverage (skipped if pmdarima unavailable)
  - ModelSelector: winner selection logic
  - ForecastAgent integration: structured output with synthetic data
"""

from __future__ import annotations

import math
from datetime import datetime, timedelta, timezone

import numpy as np
import pandas as pd
import pytest


# ─────────────────────────────────────────────────────────────────────────────
# Fixtures
# ─────────────────────────────────────────────────────────────────────────────


def _make_series(n: int = 72, freq: str = "1h", noise: float = 0.5) -> pd.Series:
    """Synthetic hourly temperature series with daily seasonality."""
    rng = np.random.default_rng(42)
    t = np.arange(n)
    # Sinusoidal daily pattern (24h period) + linear upward drift + noise
    values = 20.0 + 2.0 * np.sin(2 * math.pi * t / 24) + 0.02 * t + rng.normal(0, noise, n)
    idx = pd.date_range(
        start=datetime(2026, 5, 1, tzinfo=timezone.utc), periods=n, freq=freq
    )
    return pd.Series(values, index=idx, name="temperature")


def _make_records(n: int = 72, sensor_uuid: str = "uuid-temp-001") -> list[dict]:
    """Synthetic sensor records as would come from the SQL agent."""
    rng = np.random.default_rng(42)
    t = np.arange(n)
    values = 20.0 + 2.0 * np.sin(2 * math.pi * t / 24) + rng.normal(0, 0.5, n)
    start = datetime(2026, 5, 1, tzinfo=timezone.utc)
    return [
        {
            "uuid": sensor_uuid,
            "timestamp": (start + timedelta(hours=i)).isoformat(),
            "value": float(v),
        }
        for i, v in enumerate(values)
    ]


# ─────────────────────────────────────────────────────────────────────────────
# Horizon parser
# ─────────────────────────────────────────────────────────────────────────────


@pytest.mark.unit
def test_horizon_tomorrow():
    from orchestrator.services.forecasting.horizon_parser import parse_horizon
    h = parse_horizon("Predict temperature for tomorrow")
    assert h.total == timedelta(hours=24)
    assert h.n_steps == 24
    assert "24 hours" in h.label


@pytest.mark.unit
def test_horizon_next_week():
    from orchestrator.services.forecasting.horizon_parser import parse_horizon
    h = parse_horizon("Forecast CO2 next week")
    assert h.total == timedelta(days=7)
    assert h.n_steps > 0


@pytest.mark.unit
def test_horizon_next_hour():
    from orchestrator.services.forecasting.horizon_parser import parse_horizon
    h = parse_horizon("What will humidity be next hour?")
    assert h.total == timedelta(hours=1)
    assert h.n_steps > 0


@pytest.mark.unit
def test_horizon_next_month():
    from orchestrator.services.forecasting.horizon_parser import parse_horizon
    h = parse_horizon("Predict energy for next month")
    assert h.total == timedelta(days=30)


@pytest.mark.unit
def test_horizon_default():
    """Queries with no recognized horizon keyword get 24h default."""
    from orchestrator.services.forecasting.horizon_parser import parse_horizon
    h = parse_horizon("Tell me the future temperature")
    assert h.total == timedelta(hours=24)


# ─────────────────────────────────────────────────────────────────────────────
# Metrics
# ─────────────────────────────────────────────────────────────────────────────


@pytest.mark.unit
def test_metrics_perfect_prediction():
    from orchestrator.services.forecasting.metrics import compute_metrics
    actual = np.array([10.0, 20.0, 30.0])
    predicted = np.array([10.0, 20.0, 30.0])
    m = compute_metrics(actual, predicted, "test")
    assert m.rmse == pytest.approx(0.0, abs=1e-10)
    assert m.mae == pytest.approx(0.0, abs=1e-10)
    assert m.r2 == pytest.approx(1.0, abs=1e-6)


@pytest.mark.unit
def test_metrics_known_values():
    from orchestrator.services.forecasting.metrics import compute_metrics
    actual = np.array([1.0, 2.0, 3.0, 4.0])
    predicted = np.array([1.5, 2.5, 3.5, 4.5])
    m = compute_metrics(actual, predicted, "test")
    assert m.mae == pytest.approx(0.5, abs=1e-6)
    assert m.rmse == pytest.approx(0.5, abs=1e-6)
    # MAPE = mean(|err/actual|*100) = mean([50%, 25%, 16.67%, 12.5%]) = 26.04%
    assert m.mape == pytest.approx(26.04, abs=0.1)


@pytest.mark.unit
def test_metrics_empty_returns_inf():
    from orchestrator.services.forecasting.metrics import compute_metrics
    m = compute_metrics(np.array([]), np.array([]), "test")
    assert math.isinf(m.rmse)
    assert m.n_test == 0


# ─────────────────────────────────────────────────────────────────────────────
# Preprocessor
# ─────────────────────────────────────────────────────────────────────────────


@pytest.mark.unit
def test_preprocess_clean_records():
    from orchestrator.services.forecasting.preprocessor import preprocess_series
    records = _make_records(n=48)
    series, info = preprocess_series(records, sensor_uuid="uuid-temp-001", resample_freq="1h")
    assert series is not None
    assert len(series) > 0
    assert info["n_raw"] == 48


@pytest.mark.unit
def test_preprocess_empty_records():
    from orchestrator.services.forecasting.preprocessor import preprocess_series
    series, info = preprocess_series([], sensor_uuid=None)
    assert series is None
    assert "error" in info


@pytest.mark.unit
def test_preprocess_fills_gaps():
    from orchestrator.services.forecasting.preprocessor import preprocess_series
    records = _make_records(n=48)
    # Remove 3 records to create gaps
    records = [r for i, r in enumerate(records) if i not in (10, 11, 12)]
    series, info = preprocess_series(records, sensor_uuid="uuid-temp-001", resample_freq="1h")
    assert series is not None
    assert info["gaps_filled"] > 0


@pytest.mark.unit
def test_preprocess_clips_outliers():
    from orchestrator.services.forecasting.preprocessor import preprocess_series
    records = _make_records(n=48)
    # Inject an extreme outlier — 3-sigma rule clips to mean ± 3σ
    records[20]["value"] = 9999.0
    series, info = preprocess_series(records, sensor_uuid="uuid-temp-001", resample_freq="1h")
    assert series is not None
    # With one extreme outlier, the clipped value is mean+3σ which may be
    # several hundred. Just verify the 9999 was removed.
    assert series.max() < 9999.0, "Outlier value should have been clipped"
    assert "clipped" in " ".join(info.get("warnings", []))


# ─────────────────────────────────────────────────────────────────────────────
# Linear Forecaster
# ─────────────────────────────────────────────────────────────────────────────


@pytest.mark.unit
def test_linear_forecaster_output_shape():
    from orchestrator.services.forecasting.models.linear_forecaster import LinearTrendForecaster
    series = _make_series(n=48)
    forecaster = LinearTrendForecaster(degree=1)
    result = forecaster.fit_predict(series, n_steps=12)

    assert len(result["forecast"]) == 12
    assert len(result["lower_80"]) == 12
    assert len(result["upper_80"]) == 12
    assert len(result["lower_95"]) == 12
    assert len(result["upper_95"]) == 12


@pytest.mark.unit
def test_linear_forecaster_ci_ordering():
    """95% CI must be wider than 80% CI."""
    from orchestrator.services.forecasting.models.linear_forecaster import LinearTrendForecaster
    series = _make_series(n=48)
    result = LinearTrendForecaster().fit_predict(series, n_steps=10)

    for i in range(10):
        assert result["lower_95"][i] <= result["lower_80"][i], f"95% lower exceeds 80% lower at step {i}"
        assert result["upper_95"][i] >= result["upper_80"][i], f"95% upper below 80% upper at step {i}"


@pytest.mark.unit
def test_linear_forecaster_metrics_finite():
    from orchestrator.services.forecasting.models.linear_forecaster import LinearTrendForecaster
    series = _make_series(n=60)
    result = LinearTrendForecaster().fit_predict(series, n_steps=12)
    m = result["metrics"]
    assert math.isfinite(m.rmse) and m.rmse >= 0
    assert math.isfinite(m.mae) and m.mae >= 0
    assert math.isfinite(m.mape) and m.mape >= 0


# ─────────────────────────────────────────────────────────────────────────────
# Exponential Smoothing Forecaster
# ─────────────────────────────────────────────────────────────────────────────


@pytest.mark.unit
def test_exp_smoothing_output_shape():
    from orchestrator.services.forecasting.models.exp_smoothing_forecaster import ExpSmoothingForecaster
    series = _make_series(n=72)
    result = ExpSmoothingForecaster().fit_predict(series, n_steps=24)
    assert len(result["forecast"]) == 24
    assert len(result["lower_80"]) == 24
    assert len(result["upper_95"]) == 24


@pytest.mark.unit
def test_exp_smoothing_seasonal():
    from orchestrator.services.forecasting.models.exp_smoothing_forecaster import ExpSmoothingForecaster
    series = _make_series(n=72)
    result = ExpSmoothingForecaster(seasonal_periods=24).fit_predict(series, n_steps=12)
    assert result["metrics"].rmse >= 0
    assert "Holt-Winters" in result["model"] or "Holt" in result["model"]


# ─────────────────────────────────────────────────────────────────────────────
# ARIMA Forecaster
# ─────────────────────────────────────────────────────────────────────────────


@pytest.mark.unit
def test_arima_forecaster_output_shape():
    pytest.importorskip("pmdarima")
    from orchestrator.services.forecasting.models.arima_forecaster import ARIMAForecaster
    series = _make_series(n=72)
    result = ARIMAForecaster().fit_predict(series, n_steps=12)
    assert len(result["forecast"]) == 12
    assert len(result["lower_95"]) == 12
    assert "ARIMA" in result["model"]


@pytest.mark.unit
def test_arima_forecaster_metrics_finite():
    pytest.importorskip("pmdarima")
    from orchestrator.services.forecasting.models.arima_forecaster import ARIMAForecaster
    series = _make_series(n=60)
    result = ARIMAForecaster().fit_predict(series, n_steps=6)
    m = result["metrics"]
    assert math.isfinite(m.rmse)
    assert math.isfinite(m.mae)


# ─────────────────────────────────────────────────────────────────────────────
# Model Selector
# ─────────────────────────────────────────────────────────────────────────────


@pytest.mark.unit
def test_model_selector_returns_winner():
    from orchestrator.services.forecasting.model_selector import ModelSelector
    series = _make_series(n=72)
    selector = ModelSelector()
    result = selector.select_and_forecast(series, n_steps=12)

    assert "winner" in result
    assert result["winner"] in result["all_metrics"]
    assert len(result["forecast"]) == 12
    assert len(result["lower_80"]) == 12
    assert len(result["upper_95"]) == 12


@pytest.mark.unit
def test_model_selector_with_few_points():
    """With < 10 points, only LinearTrend should run."""
    from orchestrator.services.forecasting.model_selector import ModelSelector
    series = _make_series(n=8)
    selector = ModelSelector()
    result = selector.select_and_forecast(series, n_steps=3)
    assert result["winner"] is not None
    # Only linear trend should have run
    assert len(result["all_metrics"]) == 1


@pytest.mark.unit
def test_model_selector_winner_has_lowest_mae():
    """The declared winner must have the lowest MAE among all candidates."""
    from orchestrator.services.forecasting.model_selector import ModelSelector
    series = _make_series(n=72)
    result = ModelSelector().select_and_forecast(series, n_steps=12)

    winner_mae = result["all_metrics"][result["winner"]].mae
    for name, m in result["all_metrics"].items():
        assert m.mae >= winner_mae - 1e-9, (
            f"Model {name} (MAE={m.mae}) beats winner {result['winner']} "
            f"(MAE={winner_mae}) — selection logic is wrong"
        )


# ─────────────────────────────────────────────────────────────────────────────
# ForecastAgent integration
# ─────────────────────────────────────────────────────────────────────────────


@pytest.mark.asyncio
@pytest.mark.unit
async def test_forecast_agent_success():
    from orchestrator.agents.forecast_agent import ForecastAgent
    from shared.models import ConversationState, Message
    from datetime import datetime as dt

    state = ConversationState(
        conversation_id="test-fc-001",
        user_message="predict temperature tomorrow",
        messages=[Message(role="user", content="predict temperature tomorrow", timestamp=dt.now())],
        building_id="bldg1",
    )
    records = _make_records(n=72)
    sql_data = {"data": records}
    sensor_metadata = {"uuid-temp-001": {"label": "Zone 3 Temperature Sensor"}}

    agent = ForecastAgent()
    result = await agent.predict(state, "predict temperature tomorrow", sql_data, sensor_metadata)

    assert result["success"] is True
    assert len(result["forecast"]) == 24   # 24 steps for "tomorrow"
    assert len(result["lower_80"]) == 24
    assert len(result["upper_95"]) == 24
    assert result["metrics"] is not None
    assert "RMSE" in result["formatted_response"]
    assert "Predicted" in result["formatted_response"]
    assert "Confidence" in result["formatted_response"]


@pytest.mark.asyncio
@pytest.mark.unit
async def test_forecast_agent_no_data():
    from orchestrator.agents.forecast_agent import ForecastAgent
    from shared.models import ConversationState, Message
    from datetime import datetime as dt

    state = ConversationState(
        conversation_id="test-fc-002",
        user_message="predict co2 tomorrow",
        messages=[Message(role="user", content="predict co2 tomorrow", timestamp=dt.now())],
        building_id="bldg1",
    )
    agent = ForecastAgent()
    result = await agent.predict(state, "predict co2 tomorrow", {}, {})

    assert result["success"] is False
    assert "formatted_response" in result
    assert "not available" in result["formatted_response"].lower() or "no sensor" in result["formatted_response"].lower()


@pytest.mark.asyncio
@pytest.mark.unit
async def test_forecast_agent_response_contains_table():
    """The formatted response must contain the markdown prediction table."""
    from orchestrator.agents.forecast_agent import ForecastAgent
    from shared.models import ConversationState, Message
    from datetime import datetime as dt

    state = ConversationState(
        conversation_id="test-fc-003",
        user_message="forecast temperature next 6 hours",
        messages=[Message(role="user", content="forecast temperature next 6 hours", timestamp=dt.now())],
        building_id="bldg1",
    )
    records = _make_records(n=72)
    agent = ForecastAgent()
    result = await agent.predict(
        state, "forecast temperature next 6 hours",
        {"data": records}, {"uuid-temp-001": {"label": "Temperature"}}
    )

    assert result["success"] is True
    resp = result["formatted_response"]
    assert "| Time |" in resp, "Expected markdown table header"
    assert "Model Selection" in resp
    assert "Reliability" in resp
