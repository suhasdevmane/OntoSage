"""
Time-series forecasting services for OntoSage.

Implements PhD-grade multi-model forecasting with:
  - ARIMA / SARIMA  (statsmodels / pmdarima)
  - Holt-Winters Exponential Smoothing (statsmodels)
  - Linear Trend Regression (scikit-learn)
  - Auto model selection by hold-out MAE
  - Confidence intervals (80% and 95%)
  - Validation metrics: RMSE, MAE, MAPE, R²
"""

from orchestrator.services.forecasting.horizon_parser import parse_horizon, ForecastHorizon
from orchestrator.services.forecasting.preprocessor import preprocess_series
from orchestrator.services.forecasting.metrics import ForecastMetrics, compute_metrics
from orchestrator.services.forecasting.model_selector import ModelSelector

__all__ = [
    "parse_horizon",
    "ForecastHorizon",
    "preprocess_series",
    "ForecastMetrics",
    "compute_metrics",
    "ModelSelector",
]
