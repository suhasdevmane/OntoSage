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


# -- 8. minimum-flow persistence (slow leaks) --------------------------------


#: Modalities whose night minimum is meaningful. A flow meter should read its idle value when
#: the building is empty; a temperature sensor should not, so running this on one would flag
#: every heated building overnight.
FLOW_MODALITIES = ("water_flow", "water_flow_hot", "water_flow_chilled")


def minimum_flow_persistence(
    series: Sequence[Tuple[object, object]],
    subject_uuid: str,
    modality: str = "",
    night_start_hour: int = 1,
    night_end_hour: int = 5,
    min_nights: int = 3,
    noise_multiple: float = 3.0,
    relative_floor: float = 0.005,
    meters_on_this_stream: int = 1,
) -> List[AnomalyFinding]:
    """A flow that never returns to idle overnight, for several nights running (V6-T44).

    The standard slow-leak test, and the one the existing checks cannot perform. A 0.3 L/min
    leak on a main whose daytime median is 12 L/min is 2.5% of normal flow: it sits far below
    any sensible daytime threshold, and ``schedule_violation``'s 0.5x-in-hours-median rule
    would need the leak to reach 6 L/min before noticing. The leak is invisible by magnitude
    and obvious by PERSISTENCE, which is what this measures instead.

    Two things separate a leak from legitimate low flow, and both are required:

    * the night minimum sits above the meter's OWN idle level -- not above a fixed number, so
      a building with a genuine continuous draw has a high idle level and is not flagged for
      having one;
    * it does so on ``min_nights`` CONSECUTIVE nights. One night of late working is not a
      leak, and a rule without persistence cannot tell the two apart -- which is precisely
      why the previous single-reading check was useless.

    The floor above idle is the larger of the meter's own overnight noise (``noise_multiple``
    x median absolute deviation of the night minima) and a small fraction of its daytime
    median (``relative_floor``). Both are derived from this meter's history, so nothing here
    is building-specific: a 2 L/min trickle meter and a 200 L/min main each get their own.

    ``meters_on_this_stream`` is recorded, not used. A single-metered building can detect that
    it is leaking and cannot say WHERE, and an answer that quietly omits that limitation
    invites someone to go looking in the wrong place.
    """
    samples = _clean(series)
    if len(samples) < 24:
        return []

    nights = _night_minima(samples, night_start_hour, night_end_hour)
    if len(nights) < min_nights + 1:
        # Needs at least one night beyond the run being tested, or "every night observed is
        # above idle" is trivially true and every new meter reads as leaking on day one.
        return []

    minima = [v for _, v in nights]
    idle = min(minima)
    day_median = _daytime_median(samples, night_start_hour, night_end_hour)
    noise = _mad(minima)
    floor = idle + max(noise_multiple * noise, relative_floor * day_median)
    if floor <= idle:
        return []  # a perfectly flat meter gives no room to distinguish anything

    run = _trailing_run_above(nights, floor)
    if len(run) < min_nights:
        return []

    lowest_in_run = min(v for _, v in run)
    excess = lowest_in_run - idle
    margin = max(floor - idle, 1e-9)
    start = _night_start(run[0][0], night_start_hour)
    end = _night_start(run[-1][0], night_start_hour) + timedelta(hours=night_end_hour + 24)

    return [
        AnomalyFinding(
            detector="minimum_flow_persistence",
            subject_uuid=subject_uuid,
            modality=modality,
            start=start,
            end=end,
            score=round(excess / margin, 3),
            baseline=round(idle, 4),
            evidence={
                "consecutive_nights": len(run),
                "night_window": f"{night_start_hour:02d}-{night_end_hour:02d}",
                "idle_level": round(idle, 4),
                "floor_above_idle": round(floor, 4),
                "lowest_night_minimum_in_run": round(lowest_in_run, 4),
                "persistent_excess": round(excess, 4),
                "daytime_median": round(day_median, 4),
                "nightly_minima": [(n, round(v, 4)) for n, v in nights[-8:]],
                # Reported so an answer can state the limit rather than implying a location.
                "meters_on_this_stream": meters_on_this_stream,
                "localisable": meters_on_this_stream > 1,
            },
        )
    ]


def _night_start(night_key: str, night_start_hour: int) -> datetime:
    d = datetime.fromisoformat(night_key)
    return d.replace(hour=night_start_hour, minute=0, second=0, microsecond=0)


def _night_minima(
    samples: List[Sample], night_start_hour: int, night_end_hour: int
) -> List[Tuple[str, float]]:
    """Minimum per night, keyed by the date the night STARTED.

    Bucketing by calendar date would split a window that crosses midnight into two half
    nights and halve the apparent minimum of each -- turning a steady leak into two shallower
    ones and defeating the persistence count.
    """
    wraps = night_start_hour > night_end_hour
    per_night: Dict[str, float] = {}
    for t, v in samples:
        inside = (
            (t.hour >= night_start_hour or t.hour < night_end_hour)
            if wraps
            else (night_start_hour <= t.hour < night_end_hour)
        )
        if not inside:
            continue
        key = t.date()
        if wraps and t.hour < night_start_hour:
            key = (t - timedelta(days=1)).date()
        k = key.isoformat()
        per_night[k] = min(per_night.get(k, v), v)
    return sorted(per_night.items())


def _daytime_median(samples: List[Sample], night_start_hour: int, night_end_hour: int) -> float:
    wraps = night_start_hour > night_end_hour
    day = [
        v
        for t, v in samples
        if not (
            (t.hour >= night_start_hour or t.hour < night_end_hour)
            if wraps
            else (night_start_hour <= t.hour < night_end_hour)
        )
    ]
    return statistics.median(day) if day else 0.0


def _mad(values: Sequence[float]) -> float:
    """Median absolute deviation -- robust, so one leaking night does not inflate the noise
    estimate that is supposed to detect it."""
    if len(values) < 2:
        return 0.0
    med = statistics.median(values)
    return statistics.median([abs(v - med) for v in values])


def _trailing_run_above(
    nights: Sequence[Tuple[str, float]], floor: float
) -> List[Tuple[str, float]]:
    """The unbroken run of most-recent nights whose minimum exceeds `floor`.

    Trailing rather than longest-anywhere: a leak that was fixed last month is history, and
    reporting it as current would send someone to look for water that is no longer running.
    """
    run: List[Tuple[str, float]] = []
    for night in reversed(nights):
        if night[1] > floor:
            run.append(night)
        else:
            break
    return list(reversed(run))
