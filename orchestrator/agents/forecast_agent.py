"""
ForecastAgent — PhD-grade time-series prediction for OntoSage.

Orchestrates the full forecasting pipeline:
  1. Parse forecast horizon from the user query
  2. Select the best sensor UUID from available data
  3. Preprocess the time series (resample, fill gaps, clip outliers)
  4. Run auto-model selection across:
       - Linear Trend Regression   (sklearn — always runs)
       - Holt-Winters ES           (statsmodels — if ≥ 10 pts)
       - ARIMA / SARIMA            (pmdarima   — if ≥ 30 pts)
  5. Validate each model on a 20% hold-out set
  6. Return the winner's forecast with:
       - Point predictions
       - 80% and 95% confidence intervals
       - RMSE, MAE, MAPE, R² on the hold-out set
       - Comparison table of all candidate models

Usage (from analytics node):
    agent = ForecastAgent()
    result = await agent.predict(state, user_query, sql_data, sensor_metadata)
    # result["formatted_response"] is markdown-ready
"""

from __future__ import annotations

import asyncio
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional

import pandas as pd

from orchestrator.services.forecasting.horizon_parser import ForecastHorizon, parse_horizon
from orchestrator.services.forecasting.model_selector import ModelSelector
from orchestrator.services.forecasting.preprocessor import detect_seasonality, preprocess_series
from shared.models import ConversationState
from shared.utils import get_logger

logger = get_logger(__name__)


@dataclass
class ForecastResult:
    """Structured output from ForecastAgent.predict()."""

    success: bool
    sensor_label: str
    sensor_uuid: str
    horizon: ForecastHorizon
    model_name: str
    forecast: List[float]
    future_index: List[str]
    lower_80: List[float]
    upper_80: List[float]
    lower_95: List[float]
    upper_95: List[float]
    metrics: Any                         # ForecastMetrics instance
    all_metrics: Dict[str, Any]          # name → ForecastMetrics for all candidates
    n_history_points: int
    data_freq: str
    formatted_response: str = field(default="", repr=False)
    error: Optional[str] = None


class ForecastAgent:
    """Multi-model time-series forecasting agent."""

    # Sensor physics bounds for unit labelling
    _UNIT_MAP = {
        "temperature": "°C", "temp": "°C",
        "co2": "ppm", "carbon": "ppm",
        "humidity": "%RH",
        "energy": "kWh", "power": "kW", "electric": "kWh",
        "occupancy": "persons",
        "noise": "dB",
        "pressure": "Pa",
        "light": "lux",
    }

    def __init__(self) -> None:
        self._selector = ModelSelector()

    # ── Public API ────────────────────────────────────────────────────────────

    async def predict(
        self,
        state: ConversationState,
        user_query: str,
        sql_data: Optional[Dict[str, Any]] = None,
        sensor_metadata: Optional[Dict[str, Dict[str, str]]] = None,
    ) -> Dict[str, Any]:
        """
        Main entry point. Runs the full forecasting pipeline asynchronously
        (CPU-bound fitting is offloaded to a thread executor).
        """
        logger.info("[forecast_agent] Starting prediction pipeline")
        logger.info(f"[forecast_agent] Query: {user_query}")

        # Parse horizon from user query
        horizon = parse_horizon(user_query)
        logger.info(f"[forecast_agent] Horizon: {horizon.label} ({horizon.n_steps} steps @ {horizon.freq})")

        # Extract raw sensor records
        records = self._extract_records(sql_data)
        if not records:
            return self._error_response(
                "No sensor data available for forecasting. "
                "The system needs recent historical readings to make predictions. "
                "Try asking for a sensor that has recent data (e.g. temperature or CO2).",
                horizon=horizon,
            )

        # Select the primary sensor UUID and label
        uuid, label = self._select_primary_sensor(records, sensor_metadata, user_query)
        logger.info(f"[forecast_agent] Sensor: {label} ({uuid[:20]}...)")

        # Determine unit
        unit = self._infer_unit(label, user_query)

        # Preprocess into a clean time series at the target frequency
        series, prep_info = preprocess_series(records, sensor_uuid=uuid, resample_freq=horizon.freq)
        if series is None:
            return self._error_response(
                f"Could not build a clean time series for '{label}': "
                f"{prep_info.get('error', 'unknown preprocessing error')}. "
                "Try a larger time window (e.g. 'last 48 hours') or a different sensor.",
                horizon=horizon,
            )

        n_pts = len(series)
        logger.info(f"[forecast_agent] Series ready: {n_pts} points")

        # Detect seasonality
        seasonal_periods = detect_seasonality(series, freq=horizon.freq)
        if seasonal_periods:
            logger.info(f"[forecast_agent] Seasonality detected: period={seasonal_periods}")

        # Run model selection in a thread (CPU-bound)
        try:
            selection = await asyncio.get_event_loop().run_in_executor(
                None,
                lambda: self._selector.select_and_forecast(
                    series,
                    n_steps=horizon.n_steps,
                    seasonal_periods=seasonal_periods,
                    ci_levels=(0.80, 0.95),
                    test_fraction=0.20,
                ),
            )
        except Exception as e:
            logger.error(f"[forecast_agent] Model selection failed: {e}", exc_info=True)
            return self._error_response(
                f"Forecasting failed during model fitting: {e}. "
                "This can happen when the sensor data is too irregular or too short. "
                "Try asking about a longer historical period.",
                horizon=horizon,
            )

        # Build result
        result = ForecastResult(
            success=True,
            sensor_label=label,
            sensor_uuid=uuid,
            horizon=horizon,
            model_name=selection["winner"],
            forecast=selection["forecast"],
            future_index=selection["future_index"],
            lower_80=selection["lower_80"],
            upper_80=selection["upper_80"],
            lower_95=selection["lower_95"],
            upper_95=selection["upper_95"],
            metrics=selection["metrics"],
            all_metrics=selection["all_metrics"],
            n_history_points=n_pts,
            data_freq=horizon.freq,
        )

        result.formatted_response = self._format_response(result, unit, prep_info)

        logger.info(
            f"[forecast_agent] Done. Model={result.model_name} "
            f"MAE={result.metrics.mae:.3f}{unit} "
            f"RMSE={result.metrics.rmse:.3f}{unit}"
        )

        return {
            "success": True,
            "model": result.model_name,
            "sensor_label": label,
            "sensor_uuid": uuid,
            "unit": unit,
            "horizon": horizon.label,
            "n_history": n_pts,
            "metrics": result.metrics.to_dict(),
            "all_metrics": {k: v.to_dict() for k, v in result.all_metrics.items()},
            "forecast": result.forecast,
            "future_index": result.future_index,
            "lower_80": result.lower_80,
            "upper_80": result.upper_80,
            "lower_95": result.lower_95,
            "upper_95": result.upper_95,
            "formatted_response": result.formatted_response,
        }

    # ── Private helpers ───────────────────────────────────────────────────────

    def _extract_records(self, sql_data: Optional[Dict[str, Any]]) -> List[dict]:
        """Pull the flat record list out of the SQL agent result dict."""
        if not sql_data:
            return []
        if isinstance(sql_data, dict):
            for key in ("data", "rows", "results"):
                val = sql_data.get(key)
                if isinstance(val, list) and val:
                    if isinstance(val[0], dict):
                        return val
                    # results.data pattern
                    if isinstance(val[0], dict) and "data" in val[0]:
                        return val[0]["data"]
                # results = {"data": [...]}
                if isinstance(val, dict):
                    inner = val.get("data", [])
                    if isinstance(inner, list) and inner:
                        return inner
        if isinstance(sql_data, list):
            return [r for r in sql_data if isinstance(r, dict)]
        return []

    def _select_primary_sensor(
        self,
        records: List[dict],
        sensor_metadata: Optional[Dict[str, Dict[str, str]]],
        query: str,
    ) -> tuple[str, str]:
        """
        Pick the single sensor UUID most relevant to the query.

        Priority:
          1. Sensor whose label contains a keyword from the query
          2. First UUID with the most records
        """
        # Collect available UUIDs
        uuid_col = "uuid" if records and "uuid" in records[0] else "sensor_uuid"
        from collections import Counter
        counts = Counter(r.get(uuid_col, "") for r in records)

        q_lower = query.lower()

        # Try keyword match
        if sensor_metadata:
            for uuid, meta in sensor_metadata.items():
                label = meta.get("label", "").lower()
                if any(kw in label for kw in q_lower.split() if len(kw) > 3):
                    return uuid, meta.get("label", uuid[:12])

        # Fallback: most-frequent UUID
        if counts:
            best_uuid = counts.most_common(1)[0][0]
            if sensor_metadata and best_uuid in sensor_metadata:
                label = sensor_metadata[best_uuid].get("label") or f"Sensor {best_uuid[:8]}..."
            else:
                label = f"Sensor {best_uuid[:8]}..." if best_uuid else "Unknown Sensor"
            return best_uuid, label

        return "", "Unknown Sensor"

    def _infer_unit(self, label: str, query: str) -> str:
        """Derive measurement unit from sensor label or query keywords."""
        combined = (label + " " + query).lower()
        for keyword, unit in self._UNIT_MAP.items():
            if keyword in combined:
                return unit
        return ""

    def _format_response(
        self,
        result: ForecastResult,
        unit: str,
        prep_info: dict,
    ) -> str:
        """Render the forecast as markdown with confidence intervals table."""
        now_str = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M UTC")
        m = result.metrics

        # ── Header ────────────────────────────────────────────────────────────
        lines = [
            f"## Forecast: {result.sensor_label}",
            f"",
            f"**Horizon:** {result.horizon.label}  |  "
            f"**As of:** {now_str}  |  "
            f"**History used:** {result.n_history_points} data points",
            f"",
        ]

        # ── Model selection ───────────────────────────────────────────────────
        lines += [
            f"### Model Selection",
            f"",
            f"| Model | RMSE | MAE | MAPE | R² | Selected |",
            f"|-------|------|-----|------|----|----------|",
        ]
        for name, met in result.all_metrics.items():
            selected = "✅ **Winner**" if name == result.model_name else ""
            lines.append(
                f"| {name} | {met.rmse:.3f}{unit} | {met.mae:.3f}{unit} "
                f"| {met.mape:.1f}% | {met.r2:.3f} | {selected} |"
            )
        lines += [
            f"",
            f"> Model evaluated on the most recent **20% hold-out** portion of the historical data.",
            f"> Lower MAE = better. Winner selected automatically by lowest MAE.",
            f"",
        ]

        # ── Forecast table ────────────────────────────────────────────────────
        lines += [
            f"### Predictions — {result.horizon.label}",
            f"",
            f"| Time | Predicted | 80% CI | 95% CI |",
            f"|------|-----------|--------|--------|",
        ]

        # Show at most 24 rows (truncate with summary for long horizons)
        n_show = min(len(result.forecast), 24)
        for i in range(n_show):
            ts = result.future_index[i] if i < len(result.future_index) else "—"
            # Format timestamp to just date+hour for readability
            try:
                ts_dt = pd.Timestamp(ts)
                ts_str = ts_dt.strftime("%Y-%m-%d %H:%M")
            except Exception:
                ts_str = str(ts)[:16]

            fc = result.forecast[i]
            lo80 = result.lower_80[i] if i < len(result.lower_80) else fc
            hi80 = result.upper_80[i] if i < len(result.upper_80) else fc
            lo95 = result.lower_95[i] if i < len(result.lower_95) else fc
            hi95 = result.upper_95[i] if i < len(result.upper_95) else fc

            lines.append(
                f"| {ts_str} | **{fc:.2f}{unit}** "
                f"| [{lo80:.2f}, {hi80:.2f}]{unit} "
                f"| [{lo95:.2f}, {hi95:.2f}]{unit} |"
            )

        if len(result.forecast) > n_show:
            lines.append(
                f"| … ({len(result.forecast) - n_show} more rows) | … | … | … |"
            )

        # ── Trend insight ─────────────────────────────────────────────────────
        if result.forecast:
            delta = result.forecast[-1] - result.forecast[0]
            direction = "📈 increasing" if delta > 0.1 else "📉 decreasing" if delta < -0.1 else "➡️ stable"
            abs_delta = abs(delta)
            lines += [
                f"",
                f"**Overall trend:** {direction} "
                f"(Δ {abs_delta:.2f}{unit} over {result.horizon.label})",
            ]

        # ── Accuracy & reliability ────────────────────────────────────────────
        reliability = (
            "High" if m.mape < 5 else
            "Moderate" if m.mape < 15 else
            "Low"
        )
        lines += [
            f"",
            f"### Forecast Reliability",
            f"",
            f"- **Winner model:** {result.model_name}",
            f"- **Hold-out RMSE:** {m.rmse:.3f}{unit}",
            f"- **Hold-out MAE:** {m.mae:.3f}{unit}",
            f"- **MAPE:** {m.mape:.1f}% → **{reliability} reliability**",
            f"- **R²:** {m.r2:.3f}"
            + (" *(< 0: near-stationary series — mean is a competitive baseline)*" if m.r2 < 0 else ""),
            f"- **Confidence intervals:** 80% and 95% (wider = more uncertainty at longer horizon)",
        ]

        if prep_info.get("gaps_filled"):
            lines.append(
                f"- **Data gaps filled:** {prep_info['gaps_filled']} "
                f"(linear interpolation, max 6 consecutive)"
            )
        if prep_info.get("warnings"):
            for w in prep_info["warnings"]:
                lines.append(f"- ⚠️ {w}")

        lines += [
            f"",
            f"> ⚠️ Forecasts are statistical estimates based on historical patterns. "
            f"Actual values may differ due to unmodelled events (occupancy changes, HVAC overrides, etc.).",
        ]

        return "\n".join(lines)

    @staticmethod
    def _error_response(message: str, horizon: Optional[ForecastHorizon] = None) -> Dict[str, Any]:
        return {
            "success": False,
            "error": message,
            "formatted_response": (
                f"**Forecast not available**\n\n{message}"
            ),
            "forecast": [],
            "metrics": None,
        }
