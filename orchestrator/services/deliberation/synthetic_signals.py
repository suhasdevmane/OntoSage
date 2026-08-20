"""
synthetic_signals.py — correlated physics-lite signal model for SATURATE (V4-T10).

One latent per-room OCCUPANCY process drives every other modality — that shared
driver IS the cross-modal correlation the plan requires (CO2 lags occupancy,
noise rides it, lights follow it, door events fire at its transitions). Signals
are deterministic per (building, space, date): the same seed always reproduces
the same series, which is what makes the L7 grader's independent ground truth
exact rather than statistical.

Claim scope (thesis framing): internal consistency for grading and demo
coherence — NOT fidelity to real buildings. SmartBuildSim-class realism is
explicitly out of scope.

Pure stdlib, no I/O: callers (backfill script, live publisher) supply timestamps
and write rows.
"""

from __future__ import annotations

import math
import random
from datetime import datetime, timedelta
from typing import Dict, List

STEP_MINUTES = 10  # sample cadence for all modalities

# modality name -> generator dispatch key (config `sat.table` stays authoritative
# for storage; this maps the *signal shape*)
CONTINUOUS_MODALITIES = (
    "temperature",
    "humidity",
    "co2",
    "occupancy",
    "noise",
    "illuminance",
)
BINARY_MODALITIES = ("door_contact", "window_contact")


def _room_rng(building_id: str, space_local: str, salt: str) -> random.Random:
    return random.Random(f"{building_id}:{space_local}:{salt}")


class RoomProfile:
    """Static per-room character (seeded once, stable across days)."""

    def __init__(self, building_id: str, space_local: str):
        rng = _room_rng(building_id, space_local, "profile")
        self.peak_occupants = rng.randint(2, 8)
        self.arrival_min = 8 * 60 + rng.randint(-30, 45)  # ~07:30-08:45
        self.departure_min = 17 * 60 + rng.randint(-30, 90)  # ~16:30-18:30
        self.lunch_dip = 0.4 + rng.random() * 0.3  # fraction remaining at lunch
        self.temp_setpoint = 20.5 + rng.random() * 1.5
        self.humidity_base = 40.0 + rng.random() * 10.0
        self.noise_floor = 31.0 + rng.random() * 4.0
        self.daylight_factor = 0.5 + rng.random()  # window size proxy


def occupancy_series(building_id: str, space_local: str, day: datetime, steps: int) -> List[float]:
    """The latent driver: occupant count per STEP for one day (deterministic)."""
    profile = RoomProfile(building_id, space_local)
    rng = _room_rng(building_id, space_local, day.strftime("%Y-%m-%d"))
    weekend = day.weekday() >= 5
    series: List[float] = []
    for i in range(steps):
        minute = (i * STEP_MINUTES) % (24 * 60)
        if weekend:
            occ = 1.0 if rng.random() < 0.02 else 0.0  # rare weekend visitor
            series.append(occ)
            continue
        if minute < profile.arrival_min or minute > profile.departure_min:
            base = 0.0
        else:
            ramp_in = min(1.0, (minute - profile.arrival_min) / 90.0)
            ramp_out = min(1.0, (profile.departure_min - minute) / 90.0)
            base = profile.peak_occupants * min(ramp_in, ramp_out, 1.0)
            if 12 * 60 <= minute <= 13 * 60 + 30:  # lunch dip
                base *= profile.lunch_dip
        jitter = rng.uniform(-0.8, 0.8)
        val = max(0.0, round(base + jitter))
        if base >= 0.5:
            # a scheduled-occupied room never flickers to empty on jitter — keeps
            # the occupied<->empty boundary meaningful for door-event generation
            val = max(1.0, val)
        series.append(val)
    return series


def modality_series(
    modality: str,
    building_id: str,
    space_local: str,
    day: datetime,
    occupancy: List[float],
) -> List[float]:
    """One modality's values for one day, driven by the room's occupancy series."""
    profile = RoomProfile(building_id, space_local)
    rng = _room_rng(building_id, space_local, f"{day.strftime('%Y-%m-%d')}:{modality}")
    steps = len(occupancy)
    out: List[float] = []

    if modality == "occupancy":
        return [float(v) for v in occupancy]

    if modality == "co2":
        co2 = 420.0
        alpha = 0.15  # first-order lag toward equilibrium per step
        for occ in occupancy:
            target = 420.0 + occ * 250.0
            co2 += alpha * (target - co2) + rng.uniform(-8, 8)
            out.append(round(max(400.0, co2), 1))
        return out

    if modality == "door_contact":
        # Debounced occupied-state: ramp-edge jitter flickers raw occupancy 0<->1
        # for several steps, which is not people walking through doors. A state
        # change only counts when it persists >=3 steps (30 min); events fire at
        # those true session boundaries plus rare mid-session churn.
        n = len(occupancy)
        occupied = [v > 0 for v in occupancy]
        stable: List[bool] = []
        state = False
        for idx in range(n):
            if occupied[idx] != state and all(
                occupied[j] == occupied[idx] for j in range(idx, min(n, idx + 3))
            ):
                state = occupied[idx]
            stable.append(state)
        prev = False
        for idx in range(n):
            boundary = stable[idx] != prev
            prev = stable[idx]
            fires = boundary or (stable[idx] and rng.random() < 0.03)
            out.append(1.0 if fires else 0.0)
        return out

    for i in range(steps):
        occ = occupancy[i]
        minute = (i * STEP_MINUTES) % (24 * 60)
        hour = minute / 60.0
        daylight = max(0.0, math.sin((hour - 6.0) / 14.0 * math.pi)) if 6 <= hour <= 20 else 0.0

        if modality == "temperature":
            diurnal = 1.2 * math.sin((hour - 14.0) / 24.0 * 2 * math.pi)
            v = profile.temp_setpoint + diurnal + occ * 0.15 + rng.uniform(-0.2, 0.2)
            out.append(round(min(27.0, max(17.5, v)), 2))
        elif modality == "humidity":
            diurnal = 6.0 * math.sin((hour - 5.0) / 24.0 * 2 * math.pi)
            v = profile.humidity_base + diurnal + occ * 0.4 + rng.uniform(-1.5, 1.5)
            out.append(round(min(70.0, max(28.0, v)), 1))
        elif modality == "noise":
            transient = rng.uniform(8, 15) if (occ > 0 and rng.random() < 0.05) else 0.0
            v = profile.noise_floor + occ * 2.5 + transient + rng.uniform(-1.0, 1.0)
            out.append(round(max(28.0, v), 1))
        elif modality == "illuminance":
            natural = daylight * 180.0 * profile.daylight_factor
            lights = 320.0 if occ > 0 else 0.0
            out.append(round(max(0.0, natural + lights + rng.uniform(-15, 15)), 0))
        elif modality == "window_contact":
            warm_afternoon = 13 <= hour <= 17
            fires = occ > 0 and warm_afternoon and rng.random() < 0.06
            out.append(1.0 if fires else 0.0)
        # ── V5-T09 kinds ────────────────────────────────────────────────────
        elif modality == "pm25":
            # outdoor baseline diurnal (traffic peaks) + occupancy resuspension
            outdoor = 8.0 + 4.0 * math.sin((hour - 8.0) / 24.0 * 2 * math.pi)
            v = outdoor * profile.daylight_factor * 0.9 + occ * 0.8 + rng.uniform(-1.0, 1.0)
            out.append(round(max(2.0, v), 1))
        elif modality == "energy_submeter":
            # kWh per 10-min interval for a FLOOR: base load + occupancy-driven
            # plug/HVAC load (the anchor's own occupancy driver, scaled up)
            scale = 12.0 + (profile.noise_floor - 30.0)  # deterministic per anchor
            base = 1.8 + 0.6 * daylight
            v = base + occ * 0.35 * scale / 12.0 + rng.uniform(-0.15, 0.15)
            out.append(round(max(0.5, v), 3))
        elif modality == "water_flow":
            # litres per 10-min for a FLOOR: kettle/toilet spikes when occupied
            spike = rng.uniform(20, 60) if (occ > 0 and rng.random() < 0.25) else 0.0
            v = 2.0 + occ * 1.5 + spike + rng.uniform(-0.5, 0.5)
            out.append(round(max(0.0, v), 1))
        elif modality == "parking_free":
            # free bays for the BUILDING: capacity minus occupancy-shaped demand
            capacity = 60.0
            demand = min(capacity, occ * 9.0 + (10.0 if 9 <= hour <= 17 else 2.0))
            out.append(round(max(0.0, capacity - demand + rng.uniform(-2, 2)), 0))
        else:  # unknown modality: neutral zero signal, never invented physics
            out.append(0.0)
    return out


def day_timestamps(day: datetime) -> List[datetime]:
    """The STEP_MINUTES-grid timestamps for one day (naive UTC, second=0)."""
    start = day.replace(hour=0, minute=0, second=0, microsecond=0)
    steps = (24 * 60) // STEP_MINUTES
    return [start + timedelta(minutes=STEP_MINUTES * i) for i in range(steps)]


def generate_room_day(
    building_id: str,
    space_local: str,
    modalities: List[str],
    day: datetime,
) -> Dict[str, List[float]]:
    """All requested modalities for one room-day, sharing ONE occupancy driver."""
    steps = (24 * 60) // STEP_MINUTES
    occ = occupancy_series(building_id, space_local, day, steps)
    return {m: modality_series(m, building_id, space_local, day, occ) for m in modalities}
