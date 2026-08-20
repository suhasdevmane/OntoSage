"""
Forecast validation metrics — RMSE, MAE, MAPE, sMAPE, MASE, R².

All functions accept numpy arrays of equal length.

WHY MAPE IS NOT ENOUGH (CAVEAT-149). MAPE divides by the actual value, so it is
undefined at zero and is computed here over a nonzero mask. Occupancy at night
and a quiet room's noise floor are mostly zeros, so the mask throws away most of
the series and what survives is dominated by the few small values — an unstable
number that looks like a quality score. MAE avoids that but is scale-dependent,
so it cannot rank a CO2 forecast against a temperature one.

Two scale-free companions fix both problems:

* **sMAPE** is symmetric and defined when the actual is zero (a zero actual and a
  zero prediction contribute 0, not infinity), so no points are discarded.
* **MASE** divides MAE by the naive one-step error of the same series, so 1.0
  means "no better than predicting the last value" — comparable across
  modalities and immune to scale.

Use sMAPE/MASE for any cross-candidate or cross-modality comparison; MAPE stays
for continuity with legacy single-series reports.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Optional

import numpy as np


@dataclass
class ForecastMetrics:
    """Validation metrics computed on a hold-out test set."""

    rmse: float  # Root Mean Squared Error (same units as the measurement)
    mae: float  # Mean Absolute Error
    mape: float  # Mean Absolute Percentage Error (%) — unreliable on zero-heavy series
    r2: float  # Coefficient of determination R²
    n_test: int  # Number of hold-out points used
    model_name: str  # Which model these metrics belong to
    #: Symmetric MAPE (%), 0-200, defined at zero — the cross-candidate metric
    smape: float = float("nan")
    #: MAE / naive-one-step MAE. 1.0 = no better than "same as last value".
    #: NaN when the series never changes, where a naive baseline is undefined.
    mase: float = float("nan")

    def summary(self) -> str:
        """One-line human-readable summary."""
        return (
            f"RMSE={self.rmse:.3f} | MAE={self.mae:.3f} | "
            f"MAPE={self.mape:.1f}% | sMAPE={self.smape:.1f}% | "
            f"MASE={self.mase:.2f} | R²={self.r2:.3f} (n={self.n_test})"
        )

    def to_dict(self) -> dict:
        return {
            "rmse": round(self.rmse, 4),
            "mae": round(self.mae, 4),
            "mape": round(self.mape, 2),
            "smape": round(self.smape, 2),
            "mase": round(self.mase, 4),
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
        return ForecastMetrics(
            rmse=float("inf"),
            mae=float("inf"),
            mape=float("inf"),
            smape=float("inf"),
            mase=float("inf"),
            r2=float("-inf"),
            n_test=0,
            model_name=model_name,
        )

    residuals = actual - predicted
    rmse = float(np.sqrt(np.mean(residuals**2)))
    mae = float(np.mean(np.abs(residuals)))

    # MAPE — avoid division by zero
    nonzero = actual != 0
    mape = (
        float(np.mean(np.abs(residuals[nonzero] / actual[nonzero])) * 100)
        if nonzero.any()
        else float("inf")
    )

    # sMAPE — symmetric, and DEFINED where the actual is zero, so a night-time
    # occupancy series keeps every point instead of being masked down to a handful.
    denom = np.abs(actual) + np.abs(predicted)
    ratio = np.zeros_like(denom, dtype=float)
    nz = denom != 0  # actual == predicted == 0 is a perfect point, not a gap
    ratio[nz] = 2.0 * np.abs(residuals[nz]) / denom[nz]
    smape = float(np.mean(ratio) * 100)

    # MASE — MAE relative to the naive "same as last value" forecast on this
    # series. Scale-free, so a CO2 model and a temperature model are comparable.
    if n > 1:
        naive = float(np.mean(np.abs(np.diff(actual))))
        mase = float(mae / naive) if naive > 0 else float("nan")
    else:
        mase = float("nan")

    # R² — 1 - SS_res / SS_tot
    ss_tot = np.sum((actual - actual.mean()) ** 2)
    ss_res = np.sum(residuals**2)
    r2 = float(1 - ss_res / ss_tot) if ss_tot > 0 else float("-inf")

    return ForecastMetrics(
        rmse=rmse,
        mae=mae,
        mape=mape,
        smape=smape,
        mase=mase,
        r2=r2,
        n_test=n,
        model_name=model_name,
    )
