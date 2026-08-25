# -*- coding: utf-8 -*-
"""
synthetic_events.py — deterministic S2 event generation (V5-T08).

Fills the generic events store with plausible interval records, the same
discipline as synthetic_signals.py: seeded per building:subject:day, so
re-runs are byte-identical and cross-shape CONSISTENCY holds — bookings that
"happened" overlap occupancy>0 stretches of the same room's occupancy driver,
ghost bookings sit where occupancy stayed 0, and access events track the
building-wide arrival curve. That coupling is what makes DETECT's
cross-modality checks and the event grader testable.

Event identity: event_id = uuid5(building:type:subject:start) — deterministic,
so backfill and live ticks are idempotent via INSERT IGNORE on the PK.
Subject join key: subject_uuid = derive_point_uuid(building, "evt_subject",
subject_local); the event query lane (T24) derives the same way.

Compliance checks are NOT duplicated here — they live as dated triples (T05).
"""

from __future__ import annotations

import hashlib
import json
import random
import uuid as uuidlib
from datetime import datetime, timedelta
from typing import Dict, List, Optional

from orchestrator.services.datasource_registry import derive_point_uuid
from orchestrator.services.deliberation.synthetic_signals import (
    STEP_MINUTES,
    occupancy_series,
)

_TRADES = ("hvac", "electrical", "plumbing", "fabric", "cleaning")
_ROLES = ("occupant", "facility_manager", "operator")


def _rng(building_id: str, key: str) -> random.Random:
    seed = int(hashlib.sha256(f"{building_id}:{key}".encode()).hexdigest()[:12], 16)
    return random.Random(seed)


def event_id(building_id: str, event_type: str, subject_local: str, start: datetime) -> str:
    name = f"{building_id}:{event_type}:{subject_local}:{start.strftime('%Y-%m-%dT%H:%M')}"
    return str(uuidlib.uuid5(uuidlib.NAMESPACE_URL, name))


def subject_uuid(building_id: str, subject_local: str) -> str:
    return derive_point_uuid(building_id, "evt_subject", subject_local)


def _occupied_blocks(occ: List[float]) -> List[tuple]:
    """Contiguous (start_step, end_step) stretches with occupancy > 0."""
    blocks, start = [], None
    for i, v in enumerate(occ):
        if v > 0 and start is None:
            start = i
        elif v == 0 and start is not None:
            blocks.append((start, i))
            start = None
    if start is not None:
        blocks.append((start, len(occ)))
    return blocks


def _booking_status(start: datetime, now: Optional[datetime]) -> str:
    """'confirmed' for a reservation that has not started yet, else 'done'."""
    return "confirmed" if now is not None and start > now else "done"


def bookings_for_room_day(
    building_id: str,
    room_local: str,
    day: datetime,
    capacity: int = 8,
    now: Optional[datetime] = None,
) -> List[Dict]:
    """Bookings consistent with the room's occupancy driver.

    Real bookings cover (a subset of) occupied stretches; ~15% of rooms get an
    additional GHOST booking placed in a stretch where occupancy stayed 0.

    ``now`` decides the STATUS rather than whether the booking exists. A booking is
    the one event type that legitimately lives in the future — that is what a room
    calendar is for — but a reservation that has not happened yet is "confirmed",
    not "done". Marking it done would answer "was this room actually used?" with a
    yes about a meeting nobody has attended. Left as None, every booking is
    historical and the behaviour is unchanged.
    """
    steps = (24 * 60) // STEP_MINUTES
    occ = occupancy_series(building_id, room_local, day, steps)
    rng = _rng(building_id, f"book:{room_local}:{day.strftime('%Y-%m-%d')}")
    day0 = day.replace(hour=0, minute=0, second=0, microsecond=0)
    out: List[Dict] = []

    for start_step, end_step in _occupied_blocks(occ):
        if (end_step - start_step) * STEP_MINUTES < 30:
            continue  # too short to have been a booked meeting
        if rng.random() < 0.35:
            continue  # walk-in usage, never booked — bookings ≠ occupancy 1:1
        start = day0 + timedelta(minutes=start_step * STEP_MINUTES)
        end = day0 + timedelta(minutes=end_step * STEP_MINUTES)
        peak = max(occ[start_step:end_step] or [1])
        out.append(
            {
                "event_id": event_id(building_id, "booking", room_local, start),
                "event_type": "booking",
                "subject_uuid": subject_uuid(building_id, room_local),
                "start_dt": start,
                "end_dt": end,
                "status": _booking_status(start, now),
                "attrs": {
                    "organizer_role": rng.choice(_ROLES),
                    "attendees": int(min(capacity, max(1, round(peak)))),
                    "recurring": rng.random() < 0.3,
                    "ghost": False,
                },
            }
        )

    # ghost booking: reserved, nobody came (occupancy stayed 0 in the slot)
    if rng.random() < 0.15:
        free_steps = [i for i, v in enumerate(occ) if v == 0 and 9 * 6 <= i <= 16 * 6]
        if len(free_steps) >= 6:
            s = rng.choice(free_steps[: max(1, len(free_steps) - 6)])
            start = day0 + timedelta(minutes=s * STEP_MINUTES)
            end = start + timedelta(hours=1)
            out.append(
                {
                    "event_id": event_id(building_id, "booking", room_local, start),
                    "event_type": "booking",
                    "subject_uuid": subject_uuid(building_id, room_local),
                    "start_dt": start,
                    "end_dt": end,
                    "status": _booking_status(start, now),
                    "attrs": {
                        "organizer_role": rng.choice(_ROLES),
                        "attendees": rng.randint(2, capacity),
                        "recurring": False,
                        "ghost": True,
                    },
                }
            )
    return out


def workorders_for_day(
    building_id: str, room_locals: List[str], day: datetime, now: datetime
) -> List[Dict]:
    """New work orders raised on `day`, with deterministic lifecycles.

    status at generation time depends on how far `now` is past the milestones:
    open -> assigned (+0..2d) -> done (+1..10d); ~10% become the aging tail
    (never done within the horizon).
    """
    rng = _rng(building_id, f"wo:{day.strftime('%Y-%m-%d')}")
    n = rng.randint(0, max(1, len(room_locals) // 18))  # ~0-3/day for 50 rooms
    out: List[Dict] = []
    for k in range(n):
        room = rng.choice(room_locals)
        start = day.replace(hour=0, minute=0, second=0, microsecond=0) + timedelta(
            minutes=rng.randint(7 * 60, 19 * 60)
        )
        assigned_at = start + timedelta(hours=rng.randint(2, 48))
        done_at = assigned_at + timedelta(hours=rng.randint(12, 240))
        aging = rng.random() < 0.10
        if aging or now < assigned_at:
            status, end = "open", None
        elif now < done_at:
            status, end = "assigned", None
        else:
            status, end = "done", done_at
        out.append(
            {
                "event_id": event_id(building_id, "workorder", room, start),
                "event_type": "workorder",
                "subject_uuid": subject_uuid(building_id, room),
                "start_dt": start,
                "end_dt": end,
                "status": status,
                "attrs": {
                    "trade": rng.choice(_TRADES),
                    "priority": rng.choice(["low", "medium", "medium", "high"]),
                    "affected_count": rng.randint(1, 12),
                },
            }
        )
    return out


def access_events_for_day(building_id: str, room_locals: List[str], day: datetime) -> List[Dict]:
    """Aggregate entrance events tracking the building-wide arrival curve.

    Subject = the building pseudo-entrance ('entrance_main'); one event per
    estimated arrival step-bucket (count carried in attrs — aggregate by
    design: no per-person records exist anywhere, matching the privacy model).
    """
    steps = (24 * 60) // STEP_MINUTES
    # building occupancy proxy: a sample of rooms' drivers summed
    sample = room_locals[:: max(1, len(room_locals) // 12)][:12]
    total = [0.0] * steps
    for r in sample:
        for i, v in enumerate(occupancy_series(building_id, r, day, steps)):
            total[i] += v
    scale = max(1.0, len(room_locals) / max(1, len(sample)))
    day0 = day.replace(hour=0, minute=0, second=0, microsecond=0)
    rng = _rng(building_id, f"access:{day.strftime('%Y-%m-%d')}")
    out: List[Dict] = []
    prev = 0.0
    for i in range(steps):
        arrivals = max(0.0, (total[i] - prev)) * scale
        prev = total[i]
        count = int(round(arrivals + rng.uniform(-0.4, 0.4)))
        if count <= 0:
            continue
        start = day0 + timedelta(minutes=i * STEP_MINUTES)
        out.append(
            {
                "event_id": event_id(building_id, "access", "entrance_main", start),
                "event_type": "access",
                "subject_uuid": subject_uuid(building_id, "entrance_main"),
                "start_dt": start,
                "end_dt": start + timedelta(minutes=STEP_MINUTES),
                "status": "done",
                "attrs": {"entrance": "main", "direction": "in", "count": count},
            }
        )
    return out


def generate_building_day(
    building_id: str, room_locals: List[str], day: datetime, now: datetime
) -> List[Dict]:
    """All event types for one building-day (bookings per room + WOs + access)."""
    out: List[Dict] = []
    for room in room_locals:
        out.extend(bookings_for_room_day(building_id, room, day, now=now))
    out.extend(workorders_for_day(building_id, room_locals, day, now))
    out.extend(access_events_for_day(building_id, room_locals, day))
    return out


def bookings_for_building_day(
    building_id: str, room_locals: List[str], day: datetime, now: datetime
) -> List[Dict]:
    """Bookings ONLY, for one building-day.

    Used to extend the calendar past today. Bookings are the one event type that
    may legitimately exist in the future: a room calendar without future entries
    cannot answer "is this room free tomorrow?", which is most of what anyone asks
    a booking system. Access events and work orders are deliberately excluded —
    nobody has walked through a door tomorrow, and a work order cannot already be
    finished on a date that has not arrived.
    """
    out: List[Dict] = []
    for room in room_locals:
        out.extend(bookings_for_room_day(building_id, room, day, now=now))
    return out


def to_row(e: Dict) -> tuple:
    """Event dict -> parameterized INSERT row (attrs JSON-encoded)."""
    return (
        e["event_id"],
        e["event_type"],
        e["subject_uuid"],
        e["start_dt"].strftime("%Y-%m-%d %H:%M:%S"),
        e["end_dt"].strftime("%Y-%m-%d %H:%M:%S") if e["end_dt"] else None,
        e["status"],
        json.dumps(e["attrs"], separators=(",", ":")),
    )
