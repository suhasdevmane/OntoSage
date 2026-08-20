"""
ForecasterAdapter — bridges the deliberation executor to the forecasting stack.

V5-T12 (kills deficiency D1): ARBITER's plan executor previously forecast with
a bare least-squares line — no confidence intervals, no hold-out validation,
no model choice. This adapter feeds the executor's fetched series through the
same preprocessor + ModelSelector the trend lane uses (hold-out MAE picks the
winner among linear / exponential-smoothing / ARIMA / seasonal-naive), so a
deliberative forecast answer carries model name, 80/95 % CIs and backtest MAE.

Contract with the executor: input is the deliberation ``Series`` shape
[(timestamp, value), ...] newest-last plus a horizon in hours; output is a
plain dict (no cross-imports → no cycle):

    {"value", "model", "ci80", "ci95", "backtest_mae", "n_train"}

``value`` is the MEAN of the forecast path over the horizon — a ranking
figure, consistent with the tier-1 seasonal-naive point. Any failure returns
None and the executor falls back to its cheap deterministic ladder.

Everything here is building-agnostic: cadence is inferred from the series
itself (median inter-sample gap snapped to a standard grid), never assumed.
"""

from __future__ import annotations

import asyncio
from typing import Optional, Sequence, Tuple

from shared.utils import get_logger

logger = get_logger(__name__)

#: candidate resample grids (seconds) — nearest to the observed median gap wins
_GRID_STEPS = (300, 600, 900, 1800, 3600)

#: never ask a model for more than this many future steps
_MAX_STEPS = 500


def infer_grid_seconds(timestamps: Sequence) -> int:
    """Median inter-sample gap snapped to the nearest standard grid step."""
    from orchestrator.services.forecasting.models.seasonal_naive_forecaster import (
        _parse_ts,
    )

    parsed = [t for t in (_parse_ts(ts) for ts in timestamps) if t is not None]
    if len(parsed) < 3:
        return 3600
    gaps = sorted(
        (b - a).total_seconds() for a, b in zip(parsed, parsed[1:]) if (b - a).total_seconds() > 0
    )
    if not gaps:
        return 3600
    median = gaps[len(gaps) // 2]
    return min(_GRID_STEPS, key=lambda g: abs(g - median))


async def model_selector_forecast(
    series: Sequence[Tuple[object, float]], horizon_hours: float
) -> Optional[dict]:
    """Preprocess → ModelSelector (in a worker thread) → ranking dict."""
    try:
        records = [{"timestamp": ts, "uuid": "series", "value": v} for ts, v in series]
        if len(records) < 8:
            return None
        grid_s = infer_grid_seconds([ts for ts, _ in series])
        freq = f"{grid_s // 60}min" if grid_s < 3600 else "1h"

        def _run() -> Optional[dict]:
            from orchestrator.services.forecasting.model_selector import ModelSelector
            from orchestrator.services.forecasting.preprocessor import preprocess_series

            pp, info = preprocess_series(records, resample_freq=freq)
            if pp is None or len(pp) < 8:
                logger.info(f"[forecast-adapter] preprocess rejected series: {info.get('error')}")
                return None
            steps_per_day = max(1, 86400 // grid_s)
            seasonal = steps_per_day if len(pp) >= 2 * steps_per_day else None
            n_steps = max(1, min(_MAX_STEPS, int(round(horizon_hours * 3600 / grid_s))))
            sel = ModelSelector().select_and_forecast(
                pp, n_steps=n_steps, seasonal_periods=seasonal
            )
            path = [float(v) for v in sel.get("forecast", [])]
            if not path:
                return None
            metrics = sel.get("metrics")

            def _band(tag: str) -> Optional[Tuple[float, float]]:
                lo, hi = sel.get(f"lower_{tag}") or [], sel.get(f"upper_{tag}") or []
                if not lo or not hi:
                    return None
                return (
                    round(sum(map(float, lo)) / len(lo), 3),
                    round(sum(map(float, hi)) / len(hi), 3),
                )

            return {
                "value": sum(path) / len(path),
                "model": str(sel.get("winner", "model-selector")),
                "ci80": _band("80"),
                "ci95": _band("95"),
                "backtest_mae": round(float(metrics.mae), 4) if metrics else None,
                "n_train": len(pp) - (metrics.n_test if metrics else 0),
            }

        return await asyncio.get_event_loop().run_in_executor(None, _run)
    except Exception as exc:
        logger.warning(f"[forecast-adapter] falling back, ModelSelector path failed: {exc}")
        return None
