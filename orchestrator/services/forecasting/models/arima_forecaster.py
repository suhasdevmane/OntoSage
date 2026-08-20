"""
ARIMA / SARIMA Forecaster via pmdarima (auto_arima).

auto_arima automatically selects (p, d, q) and (P, D, Q, m) orders by
minimising AIC, so no manual hyperparameter tuning is required.

Prediction intervals come from the ARIMA model's built-in forecast method
(based on the theoretical variance of the innovations process).
"""

from __future__ import annotations

from typing import Optional, Tuple

import numpy as np
import pandas as pd

from orchestrator.services.forecasting.metrics import ForecastMetrics, compute_metrics
from shared.utils import get_logger

logger = get_logger(__name__)


class ARIMAForecaster:
    """Auto-ARIMA / SARIMA using pmdarima with built-in prediction intervals."""

    def __init__(self, seasonal_periods: Optional[int] = None) -> None:
        self.seasonal_periods = seasonal_periods
        self._model = None
        self.name = "ARIMA"

    # ── Public API ────────────────────────────────────────────────────────────

    def fit_predict(
        self,
        series: pd.Series,
        n_steps: int,
        ci_levels: Tuple[float, ...] = (0.80, 0.95),
        test_fraction: float = 0.20,
    ) -> dict:
        """Fit auto-ARIMA, validate on hold-out, return structured forecast."""
        try:
            import pmdarima as pm
        except ImportError as e:
            raise RuntimeError("pmdarima not installed — run: pip install pmdarima") from e

        values = series.values.astype(float)
        n = len(values)
        n_test = max(1, int(n * test_fraction))
        n_train = n - n_test

        train = series.iloc[:n_train]
        test_values = values[n_train:]

        # auto_arima with optional seasonal component
        use_seasonal = (
            self.seasonal_periods is not None and n_train >= 2 * self.seasonal_periods + 10
        )
        try:
            model = pm.auto_arima(
                train,
                seasonal=use_seasonal,
                m=self.seasonal_periods if use_seasonal else 1,
                stepwise=True,  # stepwise search (fast)
                information_criterion="aic",
                max_p=3,
                max_q=3,
                max_P=1,
                max_Q=1,
                d=None,  # auto-differencing
                D=None,  # auto-seasonal-differencing
                error_action="ignore",
                suppress_warnings=True,
                n_jobs=1,
            )
        except Exception as e:
            raise RuntimeError(f"auto_arima failed: {e}") from e

        # Build a human-readable model name
        order = model.order
        seasonal_order = model.seasonal_order if use_seasonal else None
        if seasonal_order and any(v != 0 for v in seasonal_order[:3]):
            self.name = f"SARIMA{order}×{seasonal_order[:3]}[{self.seasonal_periods}]"
        else:
            self.name = f"ARIMA{order}"

        logger.info(f"[arima] selected model: {self.name} (AIC={model.aic():.1f})")
        self._model = model

        # Validate on hold-out
        test_pred = model.predict(n_periods=n_test)
        metrics = compute_metrics(test_values, test_pred, self.name)

        # Forecast future with 95% CI (we'll compute the others manually)
        fc, ci_95 = model.predict(
            n_periods=n_steps,
            return_conf_int=True,
            alpha=0.05,  # 95% CI
        )
        _, ci_80 = model.predict(
            n_periods=n_steps,
            return_conf_int=True,
            alpha=0.20,  # 80% CI
        )

        future_index = self._build_future_index(series, n_steps)

        return {
            "model": self.name,
            "aic": round(model.aic(), 2),
            "order": list(order),
            "seasonal_order": list(seasonal_order) if seasonal_order else None,
            "forecast": fc.tolist(),
            "future_index": [str(ts) for ts in future_index],
            "lower_80": ci_80[:, 0].tolist(),
            "upper_80": ci_80[:, 1].tolist(),
            "lower_95": ci_95[:, 0].tolist(),
            "upper_95": ci_95[:, 1].tolist(),
            "metrics": metrics,
        }

    # ── Private helpers ───────────────────────────────────────────────────────

    @staticmethod
    def _build_future_index(series: pd.Series, n_steps: int) -> pd.DatetimeIndex:
        freq = pd.infer_freq(series.index) or "1h"
        last = series.index[-1]
        return pd.date_range(start=last, periods=n_steps + 1, freq=freq)[1:]
