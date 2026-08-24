# -*- coding: utf-8 -*-
"""What the readings themselves say about a sensor's condition (V6-T08).

Master 10.1 asks for automated drift detection against comparable sensors, and for explicit
missingness in every analysis. Authored metadata (V6-T06) cannot supply either: a calibration
certificate does not know the sensor died last Tuesday, and a `qualityFlag` set by an operator
in March does not know about this week's drift.

So health is COMPUTED from the data, and kept deliberately separate from the authored
metadata rather than merged into one "is it good" verdict. The two disagree in useful ways:
an operator may know a sensor is faulty before the data shows it, and may know a
plausible-looking series is wrong. Collapsing them would lose whichever is right.

**Drift is judged against a sensor's PEERS, never against an absolute band.** An absolute band
cannot distinguish a drifting sensor from a genuinely warm room, which is the whole
difficulty. Peers are sensors of the same class in the same space or served zone -- a
relationship the graph already asserts.

**Too few peers means "cannot judge", not "no drift".** Drift measured against one other
sensor is not evidence: with n=1 there is no way to tell which of the two moved. The minimum
is declared in config, and below it the verdict is UNKNOWN, which the gates treat as a reason
to qualify rather than as a clean bill of health.
"""

from __future__ import annotations

import statistics
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from enum import Enum
from typing import Dict, List, Optional, Sequence

from shared.utils import get_logger

logger = get_logger(__name__)

#: Fewest peers needed before a drift verdict means anything. With one peer a disagreement
#: is symmetric -- nothing says which sensor moved -- so two is the floor at which a median
#: can outvote a single outlier.
MIN_PEERS_FOR_DRIFT = 2


class HealthState(str, Enum):
    """Computed condition. UNKNOWN is a real state, never a synonym for healthy."""

    HEALTHY = "healthy"
    STALE = "stale"  # reporting stopped
    DRIFTING = "drifting"  # disagrees persistently with its peers
    NO_DATA = "no_data"  # nothing ever arrived
    UNKNOWN = "unknown"  # not enough information to judge


@dataclass
class DriftVerdict:
    """Whether a sensor sits apart from its peers, and how confidently we can say so."""

    deviation: Optional[float] = None
    peer_median: Optional[float] = None
    n_peers: int = 0
    tolerance: Optional[float] = None
    is_drifting: bool = False
    reason: str = ""

    @property
    def judged(self) -> bool:
        return self.n_peers >= MIN_PEERS_FOR_DRIFT and self.tolerance is not None


@dataclass
class SensorHealth:
    """Computed condition of one point, with everything needed to explain it."""

    sensor_id: str
    state: HealthState = HealthState.UNKNOWN
    latest_observation: Optional[datetime] = None
    age_minutes: Optional[float] = None
    observed: int = 0
    expected: Optional[int] = None
    drift: DriftVerdict = field(default_factory=DriftVerdict)
    detail: str = ""

    @property
    def missing_rate(self) -> Optional[float]:
        if not self.expected:
            return None
        return max(0.0, 1.0 - (self.observed / self.expected))

    @property
    def usable(self) -> bool:
        """Whether an answer may rest on this sensor without qualification.

        UNKNOWN is deliberately NOT usable. A sensor we cannot assess is not thereby fine,
        and treating it as fine is how an unassessed stream ends up carrying a confident
        number.
        """
        return self.state is HealthState.HEALTHY


def assess_drift(
    value: Optional[float],
    peer_values: Sequence[float],
    tolerance: Optional[float],
) -> DriftVerdict:
    """Compare one reading against its peers' median.

    Median rather than mean: with three or four peers a single failed sensor reading zero or
    a rail value would drag a mean far enough to make the healthy sensors look like the
    outliers.
    """
    peers = [p for p in peer_values if p is not None]
    if value is None:
        return DriftVerdict(n_peers=len(peers), tolerance=tolerance, reason="no current reading")
    if len(peers) < MIN_PEERS_FOR_DRIFT:
        return DriftVerdict(
            n_peers=len(peers),
            tolerance=tolerance,
            reason=(
                f"only {len(peers)} comparable sensor(s); at least {MIN_PEERS_FOR_DRIFT} are "
                "needed before a disagreement says which sensor moved"
            ),
        )
    if tolerance is None:
        return DriftVerdict(
            n_peers=len(peers),
            reason="no agreement tolerance declared for this modality, so drift cannot be judged",
        )
    med = statistics.median(peers)
    dev = abs(value - med)
    drifting = dev > tolerance
    return DriftVerdict(
        deviation=round(dev, 3),
        peer_median=round(med, 3),
        n_peers=len(peers),
        tolerance=tolerance,
        is_drifting=drifting,
        reason=(
            f"reads {dev:.2f} from the median of {len(peers)} comparable sensor(s), "
            f"{'beyond' if drifting else 'within'} the {tolerance} tolerance"
        ),
    )


def assess_sensor(
    sensor_id: str,
    timestamps: Sequence[datetime],
    now: datetime,
    max_age_minutes: float,
    latest_value: Optional[float] = None,
    peer_values: Sequence[float] = (),
    agreement_tolerance: Optional[float] = None,
    expected_samples: Optional[int] = None,
) -> SensorHealth:
    """Full condition of one sensor.

    Precedence is worth stating: NO_DATA, then STALE, then DRIFTING. A stale sensor's last
    reading may well disagree with its peers, but reporting that as drift would send someone
    to recalibrate an instrument whose actual problem is that it stopped reporting.
    """
    health = SensorHealth(sensor_id=sensor_id, observed=len(timestamps), expected=expected_samples)

    if not timestamps:
        health.state = HealthState.NO_DATA
        health.detail = "no observations at all in the requested window"
        return health

    latest = max(timestamps)
    health.latest_observation = latest
    health.age_minutes = round((now - latest).total_seconds() / 60.0, 1)

    if health.age_minutes > max_age_minutes:
        health.state = HealthState.STALE
        health.detail = (
            f"newest observation is {health.age_minutes:.0f} minutes old, beyond the "
            f"{max_age_minutes:.0f}-minute limit for this modality"
        )
        return health

    health.drift = assess_drift(latest_value, peer_values, agreement_tolerance)
    if health.drift.is_drifting:
        health.state = HealthState.DRIFTING
        health.detail = health.drift.reason
    elif health.drift.judged:
        health.state = HealthState.HEALTHY
        health.detail = "reporting on time and in agreement with comparable sensors"
    else:
        # Fresh, but nothing to compare it with. Not a fault, and not a clean bill either.
        health.state = HealthState.UNKNOWN
        health.detail = f"reporting on time, but {health.drift.reason}"
    return health


def summarise(healths: Sequence[SensorHealth]) -> Dict[str, int]:
    """Counts per state, for the observability matrix and the admin view."""
    out: Dict[str, int] = {s.value: 0 for s in HealthState}
    for h in healths:
        out[h.state.value] += 1
    return out
