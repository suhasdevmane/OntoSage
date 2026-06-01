"""
Forecast validation metrics — RMSE, MAE, MAPE, R².

All functions accept numpy arrays of equal length.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Optional

import numpy as np


@dataclass
class ForecastMetrics:
    """Validation metrics computed on a hold-out test set."""

    rmse: float          # Root Mean Squared Error (same units as the measurement)
    mae: float           # Mean Absolute Error
    mape: float          # Mean Absolute Percentage Error (%)
    r2: float            # Coefficient of determination R²
    n_test: int          # Number of hold-out points used
    model_name: str      # Which model these metrics belong to

    def summary(self) -> str:
        """One-line human-readable summary."""
        return (
            f"RMSE={self.rmse:.3f} | MAE={self.mae:.3f} | "
            f"MAPE={self.mape:.1f}% | R²={self.r2:.3f} (n={self.n_test})"
        )

    def to_dict(self) -> dict:
        return {
            "rmse": round(self.rmse, 4),
            "mae": round(self.mae, 4),
            "mape": round(self.mape, 2),
            "r2": round(self.r2, 4),
            "n_test": self.n_test,
            "model_name": self.model_name,
        }


def compute_metrics(
    actual: np.ndarray,
    predicted: np.ndarray,
    model_name: str = "unknown",
) -> ForecastMetrics:
    """Compute all validation metrics for a set of actual vs. predicted values."""
    actual = np.asarray(actual, dtype=float)
    predicted = np.asarray(predicted, dtype=float)

    mask = np.isfinite(actual) & np.isfinite(predicted)
    actual, predicted = actual[mask], predicted[mask]
    n = len(actual)

    if n == 0:
        return ForecastMetrics(rmse=float("inf"), mae=float("inf"),
                               mape=float("inf"), r2=float("-inf"),
                               n_test=0, model_name=model_name)

    residuals = actual - predicted
    rmse = float(np.sqrt(np.mean(residuals ** 2)))
    mae = float(np.mean(np.abs(residuals)))

    # MAPE — avoid division by zero
    nonzero = actual != 0
    mape = float(np.mean(np.abs(residuals[nonzero] / actual[nonzero])) * 100) if nonzero.any() else float("inf")

    # R² — 1 - SS_res / SS_tot
    ss_tot = np.sum((actual - actual.mean()) ** 2)
    ss_res = np.sum(residuals ** 2)
    r2 = float(1 - ss_res / ss_tot) if ss_tot > 0 else float("-inf")

    return ForecastMetrics(rmse=rmse, mae=mae, mape=mape, r2=r2,
                           n_test=n, model_name=model_name)
