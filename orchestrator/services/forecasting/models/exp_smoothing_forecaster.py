"""
Exponential Smoothing Forecaster — Holt-Winters via statsmodels.

Handles level + trend + optional seasonality.
Automatically chooses between:
  - Simple Exponential Smoothing (no trend, no seasonality)
  - Holt's method (trend, no seasonality)
  - Holt-Winters (trend + seasonal) when seasonal_periods is provided

Prediction intervals are bootstrapped from in-sample residuals.
"""

from __future__ import annotations

from typing import Optional, Tuple

import numpy as np
import pandas as pd

from orchestrator.services.forecasting.metrics import ForecastMetrics, compute_metrics
from shared.utils import get_logger

logger = get_logger(__name__)


class ExpSmoothingForecaster:
    """Holt-Winters Exponential Smoothing with bootstrap confidence intervals."""

    name = "Holt-Winters Exponential Smoothing"

    def __init__(self, seasonal_periods: Optional[int] = None) -> None:
        self.seasonal_periods = seasonal_periods
        self._model_fit = None
        self._residual_std: float = 0.0

    # ── Public API ────────────────────────────────────────────────────────────

    def fit_predict(
        self,
        series: pd.Series,
        n_steps: int,
        ci_levels: Tuple[float, ...] = (0.80, 0.95),
        test_fraction: float = 0.20,
    ) -> dict:
        """Fit, validate, forecast."""
        from statsmodels.tsa.holtwinters import ExponentialSmoothing

        values = series.values.astype(float)
        n = len(values)
        n_test = max(1, int(n * test_fraction))
        n_train = n - n_test

        train_series = series.iloc[:n_train]
        test_values = values[n_train:]

        # Build model with appropriate complexity
        kwargs = dict(initialization_method="estimated")
        use_seasonal = self.seasonal_periods is not None and n_train >= 2 * self.seasonal_periods
        if use_seasonal:
            model = ExponentialSmoothing(
                train_series,
                trend="add",
                seasonal="add",
                seasonal_periods=self.seasonal_periods,
                **kwargs,
            )
            self.name = f"Holt-Winters (seasonal={self.seasonal_periods})"
        elif n_train >= 10:
            model = ExponentialSmoothing(train_series, trend="add", **kwargs)
            self.name = "Holt's Linear Trend"
        else:
            model = ExponentialSmoothing(train_series, **kwargs)
            self.name = "Simple Exponential Smoothing"

        try:
            self._model_fit = model.fit(optimized=True)
        except Exception as e:
            raise RuntimeError(f"ExponentialSmoothing fit failed: {e}") from e

        # Validate on hold-out
        test_pred = self._model_fit.forecast(n_test)
        metrics = compute_metrics(test_values, test_pred.values, self.name)

        # Collect in-sample residuals for bootstrap CI
        in_sample_pred = self._model_fit.fittedvalues
        residuals = train_series.values - in_sample_pred.values
        self._residual_std = float(np.std(residuals, ddof=1))

        # Forecast future
        forecast_series = self._model_fit.forecast(n_steps)
        future_index = [str(ts) for ts in forecast_series.index]
        forecast = forecast_series.values.tolist()

        intervals = self._bootstrap_intervals(forecast_series.values, n_steps, ci_levels)

        return {
            "model": self.name,
            "forecast": forecast,
            "future_index": future_index,
            "metrics": metrics,
            **intervals,
        }

    # ── Private helpers ───────────────────────────────────────────────────────

    def _bootstrap_intervals(
        self,
        point_forecast: np.ndarray,
        n_steps: int,
        ci_levels: Tuple[float, ...],
    ) -> dict:
        """
        Parametric prediction intervals from residual std, widening with horizon.
        Interval width grows as sqrt(h) where h is the step ahead.
        """
        result = {}
        h = np.arange(1, n_steps + 1)
        se = self._residual_std * np.sqrt(h)  # uncertainty grows with horizon

        for alpha in ci_levels:
            from scipy import stats as _stats

            z = float(_stats.norm.ppf((1 + alpha) / 2))
            pct = int(alpha * 100)
            result[f"lower_{pct}"] = (point_forecast - z * se).tolist()
            result[f"upper_{pct}"] = (point_forecast + z * se).tolist()
        return result
