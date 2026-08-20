"""
Seasonal-Naive Forecaster — same weekday + hour-of-day profile, no fitting.

Building data is dominated by daily and weekly cycles (occupancy schedules,
HVAC programs, daylight). The cheapest honest forecast is therefore "the value
this signal usually has at that time of week": the mean of the same
(weekday, hour) observations in the history. Deterministic, no fitted
parameters, O(n) — cheap enough to run for EVERY candidate in a
whole-building predictive ranking (V5-T13 tier-1), and exposed with the same
``fit_predict`` contract as the other models so ModelSelector can let it
compete for the tier-2 win.

Per-bin fallback ladder when history is short (a 72 h fetch window covers only
three weekdays, so "tomorrow" often has no same-weekday bin):
  (weekday, hour) profile  →  hour-of-day profile (any weekday)  →  global mean

The pure-python half (``build_profile`` / ``seasonal_naive_point``) has NO
pandas/numpy dependency so the deliberation executor can rank hundreds of
candidates without touching the scientific stack; pandas is imported lazily
inside the ModelSelector-facing class only.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timedelta
from typing import Dict, List, Optional, Sequence, Tuple

from shared.utils import get_logger

logger = get_logger(__name__)

#: forecasts never extrapolate the profile further than one full week ahead
MAX_HORIZON_STEPS = 24 * 7


def _parse_ts(raw: object) -> Optional[datetime]:
    """Parse a timestamp as stored in adapter rows ('YYYY-MM-DD HH:MM:SS' / ISO)."""
    if isinstance(raw, datetime):
        return raw.replace(tzinfo=None)
    s = str(raw).strip().replace("Z", "+00:00")
    try:
        dt = datetime.fromisoformat(s)
    except ValueError:
        for fmt in ("%Y-%m-%d %H:%M:%S", "%Y-%m-%dT%H:%M:%S", "%Y-%m-%d %H:%M"):
            try:
                return datetime.strptime(s[: len(fmt) + 2], fmt)
            except ValueError:
                continue
        return None
    return dt.replace(tzinfo=None)


@dataclass
class SeasonalProfile:
    """Hour-of-week mean profile with per-bin fallbacks."""

    by_weekday_hour: Dict[Tuple[int, int], float] = field(default_factory=dict)
    by_hour: Dict[int, float] = field(default_factory=dict)
    global_mean: float = 0.0
    n_points: int = 0
    span_hours: float = 0.0
    bin_counts: Dict[Tuple[int, int], int] = field(default_factory=dict)

    def value_at(self, when: datetime, min_obs: int = 1) -> float:
        """Profile value; bins thinner than ``min_obs`` fall back a level.

        ``min_obs=2`` matters to the anomaly detectors: with exactly one week
        of history every (weekday, hour) bin holds a single observation, so
        residuals against the bin are identically zero — the profile has
        memorized its own history. Falling back to the hour-of-day mean keeps
        the envelope honest.
        """
        key = (when.weekday(), when.hour)
        if key in self.by_weekday_hour and self.bin_counts.get(key, 0) >= min_obs:
            return self.by_weekday_hour[key]
        return self.by_hour.get(when.hour, self.global_mean)


def build_profile(times: Sequence[datetime], values: Sequence[float]) -> SeasonalProfile:
    """Aggregate a history into an hour-of-week mean profile (pure python)."""
    sums_wh: Dict[Tuple[int, int], List[float]] = {}
    sums_h: Dict[int, List[float]] = {}
    for t, v in zip(times, values):
        sums_wh.setdefault((t.weekday(), t.hour), []).append(v)
        sums_h.setdefault(t.hour, []).append(v)
    n = len(values)
    profile = SeasonalProfile(
        by_weekday_hour={k: sum(vs) / len(vs) for k, vs in sums_wh.items()},
        by_hour={k: sum(vs) / len(vs) for k, vs in sums_h.items()},
        global_mean=(sum(values) / n) if n else 0.0,
        n_points=n,
        span_hours=((max(times) - min(times)).total_seconds() / 3600.0) if times else 0.0,
        bin_counts={k: len(vs) for k, vs in sums_wh.items()},
    )
    return profile


def seasonal_naive_point(
    series: Sequence[Tuple[object, float]], horizon_hours: float
) -> Optional[Tuple[float, str]]:
    """Mean profile value over the coming horizon — the tier-1 ranking figure.

    ``series`` is the deliberation fetch shape: [(timestamp, value), ...]
    newest-last. "Now" is the last observed timestamp (deterministic — no wall
    clock), and the returned value is the profile mean over
    (now, now + horizon], hourly steps, capped at one week.
    Returns None when nothing parses (caller falls back to linear).
    """
    times: List[datetime] = []
    values: List[float] = []
    for raw_ts, v in series:
        dt = _parse_ts(raw_ts)
        if dt is not None:
            times.append(dt)
            try:
                values.append(float(v))
            except (TypeError, ValueError):
                times.pop()
    if len(values) < 4:
        return None
    profile = build_profile(times, values)
    now = max(times)
    steps = max(1, min(MAX_HORIZON_STEPS, int(round(horizon_hours))))
    total = 0.0
    for i in range(1, steps + 1):
        total += profile.value_at(now + timedelta(hours=i))
    label = (
        "seasonal-naive (hour-of-week)"
        if profile.span_hours >= 6.5 * 24
        else "seasonal-naive (hour-of-day)"
    )
    return total / steps, label


class SeasonalNaiveForecaster:
    """ModelSelector-facing wrapper with the shared ``fit_predict`` contract.

    Metrics are computed honestly on a hold-out split (profile built from the
    train portion, evaluated on the test portion); the future path is then
    forecast from a profile over the FULL series. Confidence intervals are
    empirical: quantiles of the absolute hold-out residuals.
    """

    name = "SeasonalNaive"

    def fit_predict(
        self,
        series,  # pd.Series indexed by datetime
        n_steps: int,
        ci_levels: Tuple[float, ...] = (0.80, 0.95),
        test_fraction: float = 0.20,
    ) -> dict:
        import numpy as np  # lazy — the pure tier-1 path must not need these
        import pandas as pd

        from orchestrator.services.forecasting.metrics import compute_metrics

        n = len(series)
        if n < 8:
            raise ValueError(f"seasonal-naive needs >=8 points, got {n}")
        n_test = max(1, int(n * test_fraction))
        n_train = n - n_test

        idx = [ts.to_pydatetime().replace(tzinfo=None) for ts in pd.DatetimeIndex(series.index)]
        vals = [float(v) for v in series.values]

        train_profile = build_profile(idx[:n_train], vals[:n_train])
        test_pred = np.array([train_profile.value_at(t) for t in idx[n_train:]])
        test_actual = np.array(vals[n_train:], dtype=float)
        metrics = compute_metrics(test_actual, test_pred, self.name)

        residuals = np.abs(test_actual - test_pred)

        full_profile = build_profile(idx, vals)
        delta = (idx[-1] - idx[-2]) if n >= 2 else timedelta(hours=1)
        if delta.total_seconds() <= 0:
            delta = timedelta(hours=1)
        future_index = [idx[-1] + delta * (i + 1) for i in range(n_steps)]
        forecast = np.array([full_profile.value_at(t) for t in future_index])

        result: dict = {
            "model": self.name,
            "forecast": forecast.tolist(),
            "future_index": [pd.Timestamp(t) for t in future_index],
            "metrics": metrics,
        }
        for level in ci_levels:
            half = float(np.quantile(residuals, level)) if len(residuals) else 0.0
            tag = str(int(round(level * 100)))
            result[f"lower_{tag}"] = (forecast - half).tolist()
            result[f"upper_{tag}"] = (forecast + half).tolist()
        return result
