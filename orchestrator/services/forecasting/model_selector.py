"""
Model Selector — runs all available forecasters, picks the best by hold-out MAE.

Strategy:
  1. Always run LinearTrendForecaster (fast baseline, works with few points)
  2. If ≥ 24 points → also run ExpSmoothingForecaster
  3. If ≥ 30 points → also run ARIMAForecaster
  4. Select model with lowest MAE on the hold-out set
  5. Return the winner's forecast + all candidates' metrics for transparency

All models run synchronously in the calling thread (pmdarima's auto_arima
is CPU-bound; running it in an executor is optional but not done here for
simplicity — typical fit time is < 5s on 100-200 sensor readings).
"""

from __future__ import annotations

from typing import Dict, List, Optional

import pandas as pd

from orchestrator.services.forecasting.metrics import ForecastMetrics
from orchestrator.services.forecasting.models.arima_forecaster import ARIMAForecaster
from orchestrator.services.forecasting.models.exp_smoothing_forecaster import ExpSmoothingForecaster
from orchestrator.services.forecasting.models.linear_forecaster import LinearTrendForecaster
from orchestrator.services.forecasting.preprocessor import MIN_POINTS_FOR_ARIMA
from shared.utils import get_logger

logger = get_logger(__name__)

MIN_POINTS_FOR_EXP = 10
MIN_POINTS_FOR_ARIMA_SELECTOR = max(MIN_POINTS_FOR_ARIMA, 30)


class ModelSelector:
    """Run all eligible forecasters and pick the one with the best MAE."""

    def select_and_forecast(
        self,
        series: pd.Series,
        n_steps: int,
        seasonal_periods: Optional[int] = None,
        ci_levels: tuple = (0.80, 0.95),
        test_fraction: float = 0.20,
    ) -> dict:
        """
        Run all eligible models and return the best result.

        Returns:
          {
            "winner": <model_name>,
            "forecast": [...],
            "future_index": [...],
            "lower_80": [...], "upper_80": [...],
            "lower_95": [...], "upper_95": [...],
            "metrics": ForecastMetrics,          # winner's metrics
            "all_metrics": {name: ForecastMetrics, ...},  # all candidates
          }
        """
        n = len(series)
        candidates: List[dict] = []

        # ── Linear Trend (always runs) ──────────────────────────────────────
        try:
            linear = LinearTrendForecaster(degree=1)
            result = linear.fit_predict(series, n_steps, ci_levels, test_fraction)
            candidates.append(result)
            logger.info(f"[model_selector] Linear: {result['metrics'].summary()}")
        except Exception as e:
            logger.warning(f"[model_selector] LinearTrend failed: {e}")

        # ── Exponential Smoothing (≥10 points) ─────────────────────────────
        if n >= MIN_POINTS_FOR_EXP:
            try:
                es = ExpSmoothingForecaster(seasonal_periods=seasonal_periods)
                result = es.fit_predict(series, n_steps, ci_levels, test_fraction)
                candidates.append(result)
                logger.info(f"[model_selector] ExpSmoothing: {result['metrics'].summary()}")
            except Exception as e:
                logger.warning(f"[model_selector] ExpSmoothing failed: {e}")

        # ── ARIMA / SARIMA (≥30 points) ─────────────────────────────────────
        if n >= MIN_POINTS_FOR_ARIMA_SELECTOR:
            try:
                arima = ARIMAForecaster(seasonal_periods=seasonal_periods)
                result = arima.fit_predict(series, n_steps, ci_levels, test_fraction)
                candidates.append(result)
                logger.info(f"[model_selector] ARIMA: {result['metrics'].summary()}")
            except Exception as e:
                logger.warning(f"[model_selector] ARIMA failed: {e}")

        if not candidates:
            raise RuntimeError("All forecasting models failed. Check data quality.")

        # ── Pick winner by MAE ──────────────────────────────────────────────
        winner = min(candidates, key=lambda c: c["metrics"].mae)
        all_metrics: Dict[str, ForecastMetrics] = {
            c["model"]: c["metrics"] for c in candidates
        }

        logger.info(
            f"[model_selector] Winner: {winner['model']} "
            f"(MAE={winner['metrics'].mae:.4f})"
        )

        return {
            "winner": winner["model"],
            "forecast": winner["forecast"],
            "future_index": winner["future_index"],
            "lower_80": winner.get("lower_80", []),
            "upper_80": winner.get("upper_80", []),
            "lower_95": winner.get("lower_95", []),
            "upper_95": winner.get("upper_95", []),
            "metrics": winner["metrics"],
            "all_metrics": all_metrics,
            "aic": winner.get("aic"),
            "order": winner.get("order"),
        }
