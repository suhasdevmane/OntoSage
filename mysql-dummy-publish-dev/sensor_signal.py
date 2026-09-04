# -*- coding: utf-8 -*-
"""Generated readings that look like a building rather than a random number generator.

WHY THIS EXISTS (CAVEAT-405)
----------------------------
Every value this publisher wrote was an independent uniform draw across the modality's
range. That is white noise, and a detector keyed on deviation-from-recent-behaviour fires
almost everywhere on white noise. Measured on bldg1 across five anomaly sweeps, stable and
unaffected by the BUG-403 clock fix:

    findings 128,230-131,022 per sweep
    spike    119,579-124,442 of them, on 1,859 points -- about 64 per point
    organic context: 8,289 episodes on 1,835 sensors in a single hour

Injected faults were still found 2/2 with precision 1.0 against the labels, so the graded
scorecard was never wrong. But those same episodes are persisted and feed the anomaly and
events lanes, so a user asking "any anomalies this week" got a number assembled from noise.
A building whose every sensor is anomalous every minute is not a building.

WHAT MAKES A READING PLAUSIBLE
------------------------------
Three properties, and the old generator had none of them:

1. **Persistence.** A room's temperature at 10:00:30 is close to what it was at 10:00:00.
   Modelled as first-order mean reversion toward a moving centre, which is what makes a
   genuine spike stand out from ordinary movement.
2. **A daily cycle.** Occupancy, CO2 and light track the working day; temperature drifts
   mildly; a door contact does not follow a sine wave at all.
3. **A per-sensor offset.** Two rooms on the same floor must not be identical, or
   ``drift_vs_peers`` has no peer group worth comparing against. Derived from the uuid so
   it is stable across restarts rather than re-randomised each boot.

CADENCE
-------
Per modality, not one global tick -- the user's explicit choice (CAVEAT-233): "i dont mind
having different time intervals for different sensors". A CO2 sensor reporting every minute
and an energy meter every fifteen is what real buildings do, and it also cuts write volume
by roughly 80% against writing all 2,156 points every 30 seconds.

Cadence and detector windows are COUPLED, and that coupling has bitten this project twice
(CAVEAT-401, and again in the injector). Any modality's cadence must stay short enough that
the longest detector window still contains enough samples to judge: at 900s, six hours is
24 samples, above the 12-sample floor the detectors apply. Lengthening these further needs
that arithmetic redone.
"""

from __future__ import annotations

import hashlib
import math
import random
from datetime import datetime
from typing import Dict, Optional, Tuple

#: Seconds between writes, per value_col. Absent -> _DEFAULT_CADENCE_S.
CADENCE_S: Dict[str, int] = {
    "co2_ppm": 60,
    "occupancy": 60,
    "noise_db": 60,
    "voc": 120,
    "lux": 120,
    "temp_c": 300,
    "rh_pct": 300,
    "flow_lpm": 300,
    "vib_mm_s": 300,
    "pm25": 300,
    "contact": 300,
    "runtime_h": 600,
    "kwh": 900,
    "generic": 300,
}
_DEFAULT_CADENCE_S = 300

#: How strongly each modality follows the working day. 0 = flat, 1 = full swing.
DIURNAL: Dict[str, float] = {
    "occupancy": 0.9,
    "lux": 0.8,
    "co2_ppm": 0.7,
    "noise_db": 0.5,
    "kwh": 0.5,
    "voc": 0.4,
    "temp_c": 0.3,
    "rh_pct": 0.3,
    "flow_lpm": 0.3,
    "contact": 0.0,
}
_DEFAULT_DIURNAL = 0.2

#: Fraction of the gap to the centre closed each step. Small = sticky, 1.0 = memoryless.
#: 0.15 gives a series that moves visibly within an hour and never jumps a third of its
#: range between consecutive samples, which is what the old generator did on every write.
_REVERSION = 0.15

#: Noise as a fraction of the range, applied per step.
_STEP_NOISE = 0.012

#: Probability a binary point flips state on any given write. A door that opens and shuts
#: every 30 seconds is not a door; roughly one change an hour at a 300s cadence.
_FLIP_P = 0.08

#: uuid -> last value written. In-memory: a restart re-seeds from the diurnal centre, which
#: is a plausible reading rather than a discontinuity.
_LAST_VALUE: Dict[str, float] = {}

#: uuid -> monotonic seconds at last write, so each point keeps its own cadence.
_LAST_WRITE: Dict[str, float] = {}


def reset_state() -> None:
    """Forget all per-sensor state. For tests."""
    _LAST_VALUE.clear()
    _LAST_WRITE.clear()


def cadence_for(value_col: str) -> int:
    return CADENCE_S.get(value_col, _DEFAULT_CADENCE_S)


def due(uuid: str, value_col: str, now_s: float) -> bool:
    """Has this point's own interval elapsed? A point never written is always due."""
    last = _LAST_WRITE.get(uuid)
    return last is None or (now_s - last) >= cadence_for(value_col)


def mark_written(uuid: str, now_s: float) -> None:
    _LAST_WRITE[uuid] = now_s


def _phase(uuid: str) -> float:
    """A stable -0.5..0.5 offset per sensor, so peers differ but do not wander."""
    digest = hashlib.sha256(uuid.encode("utf-8")).digest()
    return (digest[0] / 255.0) - 0.5


def centre(value_col: str, lo: float, hi: float, when: datetime, phase: float) -> float:
    """Where this signal should sit right now, before noise."""
    swing = DIURNAL.get(value_col, _DEFAULT_DIURNAL)
    hours = when.hour + when.minute / 60.0
    # Trough overnight, peak around 13:00.
    cycle = (math.sin((hours - 7.0) / 24.0 * 2 * math.pi) + 1) / 2
    base = lo + (hi - lo) * (0.5 * (1 - swing) + swing * cycle)
    return base + (hi - lo) * 0.08 * phase


def next_value(
    uuid: str,
    value_col: str,
    lo: float,
    hi: float,
    dec: int,
    when: Optional[datetime] = None,
) -> Tuple[float, float]:
    """The next reading for this point, and the raw float behind it.

    Binary points (a 0/1 contact) hold their state and flip occasionally; everything else
    mean-reverts toward its diurnal centre with bounded per-step noise.
    """
    when = when or datetime.utcnow()
    phase = _phase(uuid)
    span = float(hi) - float(lo)

    if dec == 0 and span <= 1.0:
        prev = _LAST_VALUE.get(uuid)
        if prev is None:
            state = 1.0 if random.random() < 0.25 else 0.0  # nosec B311 - synthetic data
        elif random.random() < _FLIP_P:  # nosec B311 - synthetic data
            state = 0.0 if prev >= 0.5 else 1.0
        else:
            state = prev
        _LAST_VALUE[uuid] = state
        return int(state), state

    target = centre(value_col, float(lo), float(hi), when, phase)
    prev = _LAST_VALUE.get(uuid)
    if prev is None:
        value = target + random.gauss(0, span * _STEP_NOISE)  # nosec B311 - synthetic data
    else:
        value = prev + _REVERSION * (target - prev)
        value += random.gauss(0, span * _STEP_NOISE)  # nosec B311 - synthetic data
    value = max(float(lo), min(float(hi), value))
    _LAST_VALUE[uuid] = value
    return (int(round(value)) if dec == 0 else round(value, dec)), value
