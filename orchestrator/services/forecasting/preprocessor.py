"""
Time-series preprocessor — cleans and resamples raw sensor data for forecasting.

Handles:
  - Timestamp parsing and UTC normalisation
  - Duplicate removal
  - Resampling to regular frequency (mean aggregation)
  - Gap filling (linear interpolation, bounded to 6 gaps max)
  - Outlier clipping (3-sigma rule, sensor-physics-aware)
  - Minimum length validation
"""

from __future__ import annotations

from typing import Optional, Tuple

import numpy as np
import pandas as pd

from shared.utils import get_logger

logger = get_logger(__name__)

MIN_POINTS_FOR_ARIMA = 24  # fewer than this → skip ARIMA
MIN_POINTS_FOR_SARIMA = 72  # fewer than this → skip SARIMA
MIN_POINTS_ABSOLUTE = 5  # fewer than this → abort (not enough history)
MAX_GAP_FILL = 6  # fill up to 6 consecutive NaN gaps


def preprocess_series(
    records: list[dict],
    sensor_uuid: Optional[str] = None,
    resample_freq: str = "1h",
) -> Tuple[Optional[pd.Series], dict]:
    """
    Convert raw sensor records to a clean, regularly-spaced pd.Series.

    Args:
        records: List of {"timestamp": ..., "uuid": ..., "value": ...} dicts
        sensor_uuid: Filter to a single sensor UUID; if None uses all records
        resample_freq: Pandas resample frequency string (e.g. "1h", "30min")

    Returns:
        (series, info) where series is a pd.Series indexed by datetime (UTC),
        and info is a metadata dict with diagnostics.
    """
    info: dict = {"n_raw": 0, "n_after_resample": 0, "gaps_filled": 0, "warnings": []}

    if not records:
        return None, {**info, "error": "no_records"}

    df = pd.DataFrame(records)
    info["n_raw"] = len(df)

    # Normalise column names
    if "sensor_uuid" in df.columns and "uuid" not in df.columns:
        df = df.rename(columns={"sensor_uuid": "uuid"})

    # Filter by sensor UUID
    if sensor_uuid and "uuid" in df.columns:
        df = df[df["uuid"] == sensor_uuid]
        if df.empty:
            return None, {**info, "error": f"uuid_not_found:{sensor_uuid}"}

    # Parse timestamps
    df["timestamp"] = pd.to_datetime(df["timestamp"], utc=True, errors="coerce")
    df = df.dropna(subset=["timestamp"])

    # Parse values
    df["value"] = pd.to_numeric(df["value"], errors="coerce")
    df = df.dropna(subset=["value"])

    if len(df) < MIN_POINTS_ABSOLUTE:
        return None, {**info, "error": "too_few_points", "n_valid": len(df)}

    # Remove duplicates (keep mean of duplicate timestamps)
    df = df.set_index("timestamp").sort_index()
    df = df["value"].groupby(level=0).mean()

    # Resample to regular frequency
    series = df.resample(resample_freq).mean()

    # Fill short gaps by linear interpolation
    n_nan_before = series.isna().sum()
    series = series.interpolate(method="linear", limit=MAX_GAP_FILL)
    info["gaps_filled"] = int(n_nan_before - series.isna().sum())

    # Drop any remaining NaN (long gaps at the edges)
    series = series.dropna()

    if len(series) < MIN_POINTS_ABSOLUTE:
        return None, {**info, "error": "too_sparse_after_resample"}

    # Clip outliers at 3-sigma (preserves dynamics but removes sensor spikes)
    mu, sigma = series.mean(), series.std()
    if sigma > 0:
        lower, upper = mu - 3 * sigma, mu + 3 * sigma
        n_clipped = int(((series < lower) | (series > upper)).sum())
        series = series.clip(lower=lower, upper=upper)
        if n_clipped:
            info["warnings"].append(f"clipped {n_clipped} outlier(s) at ±3σ")

    info["n_after_resample"] = len(series)
    logger.info(
        f"[preprocess] {info['n_raw']} raw → {len(series)} pts "
        f"@ {resample_freq}, gaps_filled={info['gaps_filled']}"
    )
    return series, info


def detect_seasonality(series: pd.Series, freq: str = "1h") -> Optional[int]:
    """
    Return the dominant seasonal period (in steps) or None.

    Uses autocorrelation to detect daily (24h) and weekly (168h) periodicities.
    Only reliable with ≥ 72 points.
    """
    if len(series) < MIN_POINTS_FOR_SARIMA:
        return None

    try:
        from statsmodels.tsa.stattools import acf

        nlags = min(len(series) // 2 - 1, 168)
        acf_vals = acf(series, nlags=nlags, fft=True)

        # Check daily seasonality (24 steps for hourly data)
        if freq in ("1h") and nlags >= 24:
            daily_autocorr = acf_vals[24] if len(acf_vals) > 24 else 0
            if daily_autocorr > 0.4:
                return 24

        # Check 12-hour half-day seasonality
        if freq in ("1h") and nlags >= 12:
            half_day_autocorr = acf_vals[12] if len(acf_vals) > 12 else 0
            if half_day_autocorr > 0.5:
                return 12

    except Exception as e:
        logger.debug(f"[seasonality] detection failed: {e}")

    return None
