"""
Linear Trend Forecaster — polynomial regression extrapolation via scikit-learn.

Used as:
  - Fast baseline (always runs, even with few data points)
  - Fallback when ARIMA / ExponentialSmoothing fail
  - Degree-1 = linear, degree-2 = quadratic (auto-selected by AIC-like score)

Confidence intervals are computed from the regression residuals using
a t-distribution (parametric) approach.
"""

from __future__ import annotations

from typing import Optional, Tuple

import numpy as np
import pandas as pd
from scipy import stats

from orchestrator.services.forecasting.metrics import ForecastMetrics, compute_metrics
from shared.utils import get_logger

logger = get_logger(__name__)


class LinearTrendForecaster:
    """Polynomial regression extrapolation with parametric confidence intervals."""

    name = "Linear Trend (sklearn)"

    def __init__(self, degree: int = 1) -> None:
        self.degree = degree
        self._coeffs: Optional[np.ndarray] = None
        self._residual_std: float = 0.0
        self._n_train: int = 0

    # ── Public API ────────────────────────────────────────────────────────────

    def fit_predict(
        self,
        series: pd.Series,
        n_steps: int,
        ci_levels: Tuple[float, ...] = (0.80, 0.95),
        test_fraction: float = 0.20,
    ) -> dict:
        """
        Fit on the training portion, validate on the test portion,
        then forecast n_steps into the future.

        Returns a dict with keys:
          forecast, lower_80, upper_80, lower_95, upper_95,
          metrics, future_index
        """
        values = series.values.astype(float)
        n = len(values)
        n_test = max(1, int(n * test_fraction))
        n_train = n - n_test

        train, test = values[:n_train], values[n_train:]
        x_train = np.arange(n_train)
        x_test = np.arange(n_train, n_train + n_test)

        # Fit polynomial
        self._coeffs = np.polyfit(x_train, train, self.degree)
        self._n_train = n_train
        train_pred = np.polyval(self._coeffs, x_train)
        self._residual_std = float(np.std(train - train_pred, ddof=self.degree + 1))

        # Validate on hold-out
        test_pred = np.polyval(self._coeffs, x_test)
        metrics = compute_metrics(test, test_pred, self.name)

        # Forecast future
        x_future = np.arange(n, n + n_steps)
        forecast = np.polyval(self._coeffs, x_future)

        future_index = self._build_future_index(series, n_steps)
        intervals = self._confidence_intervals(x_future, n_train, ci_levels)

        return {
            "model": self.name,
            "degree": self.degree,
            "forecast": forecast.tolist(),
            "future_index": [str(ts) for ts in future_index],
            "metrics": metrics,
            **intervals,
        }

    # ── Private helpers ───────────────────────────────────────────────────────

    def _confidence_intervals(
        self,
        x_future: np.ndarray,
        n_train: int,
        ci_levels: Tuple[float, ...],
    ) -> dict:
        """Parametric confidence intervals from regression standard error."""
        result = {}
        x_mean = np.mean(np.arange(n_train))
        ssx = np.sum((np.arange(n_train) - x_mean) ** 2)

        for alpha in ci_levels:
            t_crit = float(stats.t.ppf((1 + alpha) / 2, df=max(1, n_train - self.degree - 1)))
            se = self._residual_std * np.sqrt(
                1 + 1 / n_train + (x_future - x_mean) ** 2 / ssx
            )
            margin = t_crit * se
            pct = int(alpha * 100)
            forecast = np.polyval(self._coeffs, x_future)
            result[f"lower_{pct}"] = (forecast - margin).tolist()
            result[f"upper_{pct}"] = (forecast + margin).tolist()
        return result

    @staticmethod
    def _build_future_index(series: pd.Series, n_steps: int) -> pd.DatetimeIndex:
        freq = pd.infer_freq(series.index) or "1h"
        last = series.index[-1]
        return pd.date_range(start=last, periods=n_steps + 1, freq=freq)[1:]
