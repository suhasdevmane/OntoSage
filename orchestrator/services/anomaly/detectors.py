# -*- coding: utf-8 -*-
"""
detectors.py — deterministic, building-physics-aware anomaly detectors (V5-T18).

Replaces the global z-score with a library that knows what building signals
look like (kills D2/D5): a daily occupancy cycle is NORMAL, a value pinned
flat for hours is not; a room drifting away from every peer on its floor is
suspicious even when its absolute value is unremarkable.

Contracts shared by every detector:
- input series use the fetch shape [(timestamp, value), ...] oldest-first or
  newest-last (they are sorted internally); timestamps may be datetimes or
  strings (adapter reality).
- output is List[AnomalyFinding]; ``score`` is normalized so 1.0 == the
  detection threshold (severity bands derive from it uniformly).
- pure python + ``statistics`` only — no numpy/pandas, so the scanner can
  sweep hundreds of points cheaply; profiles are learned from each building's
  OWN history (nothing building-specific in code).
- detectors flag EPISODES (contiguous windows), not single samples, so one
  incident produces one finding with a stable window.
"""

from __future__ import annotations

import statistics
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from typing import Dict, List, Optional, Sequence, Tuple

from orchestrator.services.forecasting.models.seasonal_naive_forecaster import (
    _parse_ts,
    build_profile,
)
from shared.utils import get_logger

logger = get_logger(__name__)

Sample = Tuple[datetime, float]


@dataclass
class AnomalyFinding:
    detector: str
    subject_uuid: str
    modality: str
    start: datetime
    end: datetime
    score: float  # 1.0 == at threshold; higher = more severe
    baseline: Optional[float]
    evidence: Dict[str, object] = field(default_factory=dict)

    @property
    def severity(self) -> str:
        if self.score >= 2.0:
            return "high"
        if self.score >= 1.3:
            return "medium"
        return "low"


def _clean(series: Sequence[Tuple[object, object]]) -> List[Sample]:
    """Parse, drop junk, sort oldest-first."""
    out: List[Sample] = []
    for raw_ts, raw_v in series:
        ts = _parse_ts(raw_ts)
        if ts is None:
            continue
        try:
            out.append((ts, float(raw_v)))
        except (TypeError, ValueError):
            continue
    out.sort(key=lambda s: s[0])
    return out


def _cadence_seconds(samples: List[Sample]) -> float:
    gaps = sorted(
        (b[0] - a[0]).total_seconds()
        for a, b in zip(samples, samples[1:])
        if (b[0] - a[0]).total_seconds() > 0
    )
    return gaps[len(gaps) // 2] if gaps else 600.0


def _episodes(
    flagged: List[Tuple[Sample, float]], max_gap_s: float
) -> List[Tuple[datetime, datetime, float]]:
    """Group flagged (sample, score) points into contiguous episodes."""
    if not flagged:
        return []
    episodes = []
    start = prev = flagged[0][0][0]
    peak = flagged[0][1]
    for (ts, _v), score in flagged[1:]:
        if (ts - prev).total_seconds() > max_gap_s:
            episodes.append((start, prev, peak))
            start, peak = ts, score
        else:
            peak = max(peak, score)
        prev = ts
    episodes.append((start, prev, peak))
    return episodes


# ── 1. seasonal residual ─────────────────────────────────────────────────────


def seasonal_residual(
    series: Sequence[Tuple[object, object]],
    subject_uuid: str,
    modality: str = "",
    k: float = 3.0,
    min_history_hours: float = 48.0,
) -> List[AnomalyFinding]:
    """Values far outside this signal's own hour-of-week envelope.

    The profile is the seasonal-naive one (same builder the forecaster uses);
    sigma is the global residual std vs that profile, so a clean daily cycle
    has small residuals everywhere and is never flagged.
    """
    samples = _clean(series)
    if len(samples) < 24:
        return []
    span_h = (samples[-1][0] - samples[0][0]).total_seconds() / 3600.0
    if span_h < min_history_hours:
        return []
    # profile from the leading 80% — the tail is what we inspect. min_obs=2:
    # single-observation bins would memorize their own history (sigma 0).
    n_train = max(12, int(len(samples) * 0.8))
    profile = build_profile([t for t, _ in samples[:n_train]], [v for _, v in samples[:n_train]])
    residuals = [v - profile.value_at(t, min_obs=2) for t, v in samples[:n_train]]
    sigma = statistics.pstdev(residuals) if len(residuals) > 1 else 0.0
    hist_values = [v for _, v in samples]
    hist_range = max(hist_values) - min(hist_values)
    if hist_range <= 1e-12:
        return []  # flat signal — the stuck detector owns it
    # noise floor: a near-perfectly-regular history makes sigma collapse and
    # ordinary wiggle score as anomalous (live shakedown: 971 findings on one
    # building). Residuals must clear BOTH k*sigma and 2% of the signal's range.
    sigma = max(sigma, 0.02 * hist_range)
    cadence = _cadence_seconds(samples)
    flagged = []
    for t, v in samples[n_train:]:
        resid = abs(v - profile.value_at(t, min_obs=2))
        if resid > k * sigma:
            flagged.append(((t, v), resid / (k * sigma)))
    findings = []
    for start, end, peak in _episodes(flagged, max_gap_s=2 * cadence):
        findings.append(
            AnomalyFinding(
                detector="seasonal_residual",
                subject_uuid=subject_uuid,
                modality=modality,
                start=start,
                end=end,
                score=round(peak, 3),
                baseline=round(profile.value_at(start, min_obs=2), 3),
                evidence={"sigma": round(sigma, 4), "k": k, "profile": "hour-of-week"},
            )
        )
    return findings


# ── 2. stuck / flatline ──────────────────────────────────────────────────────


def stuck(
    series: Sequence[Tuple[object, object]],
    subject_uuid: str,
    modality: str = "",
    min_hours: float = 6.0,
    rel_epsilon: float = 0.001,
) -> List[AnomalyFinding]:
    """The trailing window is pinned to one value while history actually moves.

    A signal that is constant over its WHOLE history (a spare input, a closed
    contact) is not an anomaly — the historical range gate keeps those out.
    One more physics gate (live shakedown): a signal parked at its MODAL
    value (occupancy at overnight zero, a contact at closed) is RESTING, not
    stuck — a sensor pinned exactly at its usual resting level goes
    undetected by design; the seasonal/cross-modality detectors own that
    case. A freeze at any NON-modal level (613 ppm mid-scale, a door held
    open for hours) still flags.
    """
    samples = _clean(series)
    if len(samples) < 12:
        return []
    hist_values = [v for _, v in samples]
    hist_range = max(hist_values) - min(hist_values)
    epsilon = max(1e-9, rel_epsilon * hist_range)
    if hist_range <= 10 * epsilon:
        return []  # flat by nature, not by fault
    # walk back from the newest sample while values stay within epsilon
    end_ts, end_v = samples[-1]
    start_ts = end_ts
    tail_start = len(samples) - 1
    lo = hi = end_v
    for i in range(len(samples) - 2, -1, -1):
        t, v = samples[i]
        lo, hi = min(lo, v), max(hi, v)
        if hi - lo > epsilon:
            break
        start_ts, tail_start = t, i
    stuck_hours = (end_ts - start_ts).total_seconds() / 3600.0
    if stuck_hours < min_hours:
        return []
    # resting-level gate over the PRE-tail history only: a long-enough freeze
    # makes the stuck value the whole-history mode (live shakedown: a 27 h
    # injected freeze excluded itself), so the tail must not vote for itself.
    pre_tail = hist_values[:tail_start]
    if pre_tail:
        counts: Dict[float, int] = {}
        for v in pre_tail:
            counts[v] = counts.get(v, 0) + 1
        modal_value = max(counts, key=lambda x: counts[x])
        if counts[modal_value] >= max(3, len(pre_tail) // 10) and (
            abs(end_v - modal_value) <= epsilon
        ):
            return []  # resting at its usual level (overnight zero) is not a fault
    return [
        AnomalyFinding(
            detector="stuck",
            subject_uuid=subject_uuid,
            modality=modality,
            start=start_ts,
            end=end_ts,
            score=round(stuck_hours / min_hours, 3),
            baseline=round(end_v, 3),
            evidence={
                "stuck_hours": round(stuck_hours, 1),
                "historical_range": round(hist_range, 3),
            },
        )
    ]


# ── 3. dropout / gap ─────────────────────────────────────────────────────────


def dropout(
    series: Sequence[Tuple[object, object]],
    subject_uuid: str,
    modality: str = "",
    gap_factor: float = 4.0,
    min_gap_minutes: float = 30.0,
) -> List[AnomalyFinding]:
    """Reporting gaps far beyond the signal's own cadence."""
    samples = _clean(series)
    if len(samples) < 6:
        return []
    cadence = _cadence_seconds(samples)
    threshold_s = max(gap_factor * cadence, min_gap_minutes * 60.0)
    findings = []
    for a, b in zip(samples, samples[1:]):
        gap_s = (b[0] - a[0]).total_seconds()
        if gap_s > threshold_s:
            findings.append(
                AnomalyFinding(
                    detector="dropout",
                    subject_uuid=subject_uuid,
                    modality=modality,
                    start=a[0],
                    end=b[0],
                    score=round(gap_s / threshold_s, 3),
                    baseline=None,
                    evidence={
                        "gap_minutes": round(gap_s / 60.0, 1),
                        "cadence_minutes": round(cadence / 60.0, 1),
                    },
                )
            )
    return findings


# ── 4. drift vs peer group ───────────────────────────────────────────────────


def drift_vs_peers(
    series: Sequence[Tuple[object, object]],
    peers: Dict[str, Sequence[Tuple[object, object]]],
    subject_uuid: str,
    modality: str = "",
    k: float = 3.0,
    window_hours: float = 6.0,
) -> List[AnomalyFinding]:
    """This point's recent mean vs the median of its peers' recent means.

    Peers are same-modality points (same floor/building — the caller chooses
    the group); spread is MAD-based so one other broken sensor cannot hide
    the drift. Needs >=3 peers to say anything.
    """
    samples = _clean(series)
    if not samples or len(peers) < 3:
        return []
    cutoff = samples[-1][0] - timedelta(hours=window_hours)

    def _recent_mean(raw) -> Optional[float]:
        pts = [v for t, v in _clean(raw) if t >= cutoff]
        return (sum(pts) / len(pts)) if pts else None

    target = _recent_mean(samples)
    peer_means = [m for m in (_recent_mean(p) for p in peers.values()) if m is not None]
    if target is None or len(peer_means) < 3:
        return []
    med = statistics.median(peer_means)
    mad = statistics.median([abs(m - med) for m in peer_means])
    # materiality gate (live shakedown): synthetic peers can be IDENTICAL, so
    # the MAD collapses and a 0.01-unit difference scored astronomically. The
    # drift must be material on the target's own scale before spread math runs.
    hist_values = [v for _, v in samples]
    hist_range = max(hist_values) - min(hist_values)
    if abs(target - med) <= max(0.05 * hist_range, 1e-9):
        return []
    spread = max(1.349 * mad, 0.02 * max(hist_range, abs(med)), 1e-9)
    dev = abs(target - med) / (k * spread)
    if dev <= 1.0:
        return []
    return [
        AnomalyFinding(
            detector="drift_vs_peers",
            subject_uuid=subject_uuid,
            modality=modality,
            start=cutoff,
            end=samples[-1][0],
            score=round(dev, 3),
            baseline=round(med, 3),
            evidence={
                "target_mean": round(target, 3),
                "peer_median": round(med, 3),
                "mad": round(mad, 4),
                "n_peers": len(peer_means),
            },
        )
    ]


# ── 5. schedule violation ────────────────────────────────────────────────────


def schedule_violation(
    series: Sequence[Tuple[object, object]],
    subject_uuid: str,
    modality: str = "",
    occupied_start_hour: int = 8,
    occupied_end_hour: int = 18,
    weekdays_only: bool = True,
    min_episode_minutes: float = 60.0,
) -> List[AnomalyFinding]:
    """Sustained activity when the schedule says the building is empty.

    For activity-like signals (occupancy, illuminance, energy): out-of-hours
    values exceeding half the in-hours median for a sustained episode. The
    thresholds derive from the signal's OWN in-hours level — nothing absolute.
    """
    samples = _clean(series)
    if len(samples) < 24:
        return []

    def _in_hours(t: datetime) -> bool:
        if weekdays_only and t.weekday() >= 5:
            return False
        return occupied_start_hour <= t.hour < occupied_end_hour

    in_vals = [v for t, v in samples if _in_hours(t)]
    if len(in_vals) < 6:
        return []
    in_median = statistics.median(in_vals)
    if in_median <= 1e-9:
        return []  # no in-hours activity baseline to compare against
    threshold = 0.5 * in_median
    cadence = _cadence_seconds(samples)
    flagged = [
        ((t, v), v / max(threshold, 1e-9)) for t, v in samples if not _in_hours(t) and v > threshold
    ]
    findings = []
    for start, end, peak in _episodes(flagged, max_gap_s=2 * cadence):
        if (end - start).total_seconds() < min_episode_minutes * 60.0:
            continue
        findings.append(
            AnomalyFinding(
                detector="schedule_violation",
                subject_uuid=subject_uuid,
                modality=modality,
                start=start,
                end=end,
                score=round(peak, 3),
                baseline=round(in_median, 3),
                evidence={
                    "in_hours_median": round(in_median, 3),
                    "schedule": f"{occupied_start_hour:02d}-{occupied_end_hour:02d} "
                    + ("weekdays" if weekdays_only else "all days"),
                },
            )
        )
    return findings


# ── 6. spike (robust, local) ─────────────────────────────────────────────────


def spike(
    series: Sequence[Tuple[object, object]],
    subject_uuid: str,
    modality: str = "",
    k: float = 6.0,
    window: int = 12,
) -> List[AnomalyFinding]:
    """Point deviations vs a rolling local median (MAD-scaled).

    The spread has a range-relative floor: on locally-quiet stretches the MAD
    collapses toward zero and every ordinary wiggle scores as a spike (live
    shakedown: 2,411 findings on one building). A spike must clear BOTH
    k*MAD and 5% of the signal's historical range.
    """
    samples = _clean(series)
    if len(samples) < window * 2:
        return []
    values = [v for _, v in samples]
    hist_range = max(values) - min(values)
    if hist_range <= 1e-12:
        return []
    cadence = _cadence_seconds(samples)
    flagged = []
    for i in range(window, len(samples)):
        local = values[i - window : i]
        med = statistics.median(local)
        mad = statistics.median([abs(x - med) for x in local])
        spread = max(1.349 * mad, 0.05 * hist_range / k, 1e-9)
        dev = abs(values[i] - med) / (k * spread)
        if dev > 1.0:
            flagged.append(((samples[i][0], values[i]), dev))
    findings = []
    for start, end, peak in _episodes(flagged, max_gap_s=2 * cadence):
        findings.append(
            AnomalyFinding(
                detector="spike",
                subject_uuid=subject_uuid,
                modality=modality,
                start=start,
                end=end,
                score=round(min(peak, 99.0), 3),
                baseline=None,
                evidence={"k": k, "window": window},
            )
        )
    return findings


# ── 7. cross-modality consistency ────────────────────────────────────────────


def cross_modality_inconsistency(
    driver_series: Sequence[Tuple[object, object]],
    response_series: Sequence[Tuple[object, object]],
    subject_uuid: str,
    modality: str = "",
    window_hours: float = 3.0,
    driver_quiet_frac: float = 0.1,
    min_response_rise_frac: float = 0.15,
) -> List[AnomalyFinding]:
    """The driver says 'nobody here' while the response keeps climbing.

    Generic pair contract (occupancy→CO2 is the canonical instance): over the
    trailing window the driver stays below ``driver_quiet_frac`` of its own
    historical peak while the response RISES by more than
    ``min_response_rise_frac`` of its historical range.
    """
    d = _clean(driver_series)
    r = _clean(response_series)
    if len(d) < 12 or len(r) < 12:
        return []
    cutoff = min(d[-1][0], r[-1][0]) - timedelta(hours=window_hours)
    d_win = [v for t, v in d if t >= cutoff]
    r_win = [(t, v) for t, v in r if t >= cutoff]
    if len(d_win) < 3 or len(r_win) < 3:
        return []
    d_peak = max(v for _, v in d) or 1.0
    if max(d_win) > driver_quiet_frac * d_peak:
        return []  # driver was active — nothing inconsistent
    r_values = [v for _, v in r]
    r_range = max(r_values) - min(r_values)
    if r_range <= 1e-9:
        return []
    rise = r_win[-1][1] - r_win[0][1]
    rise_frac = rise / r_range
    if rise_frac <= min_response_rise_frac:
        return []
    return [
        AnomalyFinding(
            detector="cross_modality",
            subject_uuid=subject_uuid,
            modality=modality,
            start=r_win[0][0],
            end=r_win[-1][0],
            score=round(rise_frac / min_response_rise_frac, 3),
            baseline=round(r_win[0][1], 3),
            evidence={
                "driver_max_in_window": round(max(d_win), 3),
                "driver_quiet_threshold": round(driver_quiet_frac * d_peak, 3),
                "response_rise": round(rise, 3),
                "response_range": round(r_range, 3),
            },
        )
    ]
