# -*- coding: utf-8 -*-
"""
provision_event_and_capacity_data.py -- placeholder alarm / door-access / anomaly records and
derived room capacities, discovered from the active building's graph.

WHICH PATH THE READERS USE (read before loading anything)
---------------------------------------------------------
Two readers answer these kinds of question today, and they read different stores:

1. The REGISTER lane decides whether a building "holds" a record class by counting graph
   instances (`record_registry.record_classes`). A held class is claimed by the dialogue
   short-circuit and answered by SPARQL over its triples; an unheld class is declined as
   "holds no <class> records" by the capability lane. AlarmEvent / AccessEvent /
   AnomalyEvent hold zero graph instances, which is what the stakeholder sweep measured.
2. The EVENTS lane (`event_query_service`) reads the `events_data` store. It answers anomaly
   summaries from the scanner's persisted `anomaly:*` rows, entrance FOOTFALL from aggregate
   `access` rows, bookings and work orders. It has no alarm kind and no door-level access
   kind at all.

So alarms and door-level access events are answerable ONLY through the register lane, and
this script emits them as graph instances. Anomalies are different: the events store already
holds the scanner's episodes, and a held AnomalyEvent graph class would be claimed by the
register short-circuit BEFORE the routing rule that sends "any anomalies this week?" to the
events lane -- replacing the scanner's findings with placeholder triples. Anomaly records are
therefore emitted only with --include-anomaly, and never by default.

WHAT IT WRITES (to --out-dir, default input/)
---------------------------------------------
  <id>_alarm_events.ttl        ontosage:AlarmEvent on alarm-capable equipment
  <id>_door_access_events.ttl  ontosage:AccessEvent at controlled openings, by ROLE TEMPLATE
  <id>_room_capacity.ttl       hbco:roomCapacity: the drawing's own person count, else
                               floor-plan area x stated density (see capacity_estimates)
  <id>_anomaly_events.ttl      ONLY with --include-anomaly (see above)

Every event record declares ontosage:isSimulated true. Capacity is DERIVED, not simulated,
and is declared with ontosage:capacityBasis instead: marking a real room simulated would
mislabel everything else said about that room.

File names avoid the uploader's schema tokens (brick / rec / s223 / schema): a name containing
one is loaded as a SHARED schema, not as this building's data.

Determinism: record ids are uuid5 of (building, kind, subject, start); every random draw is
seeded per (building, kind, subject, day). The same --anchor produces byte-identical files,
and a later anchor keeps the ids of every record an earlier one produced.

RUN (host-side; READ-ONLY against GraphDB):
  python -X utf8 scripts/provision_event_and_capacity_data.py --dry-run
  python -X utf8 scripts/provision_event_and_capacity_data.py --anchor 2026-09-17T18:00
"""

from __future__ import annotations

import argparse
import asyncio
import glob
import hashlib
import json
import math
import random
import re
import sys
import uuid as uuidlib
from collections import Counter
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any, Dict, FrozenSet, Iterable, List, Optional, Sequence, Tuple

_REPO_ROOT = Path(__file__).resolve().parents[1]
if str(_REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(_REPO_ROOT))

GENERATOR = "scripts/provision_event_and_capacity_data.py"

BRICK = "https://brickschema.org/schema/Brick#"
ONTOSAGE = "http://ontosage.org/capabilities#"
HBCO = "http://ontosage.org/hbco#"

#: Default history. Ten weeks covers "this week vs last week", "last month" and a month-on-month
#: comparison with room to spare, without making the register larger than it needs to be.
DEFAULT_WEEKS = 10

#: Opening hours used only when the building declares none. Generic office hours, stated as an
#: assumption -- the same discipline as synthetic_events.BOOKABLE_FROM_HOUR.
FALLBACK_OPEN = {d: (8.0, 18.0) for d in range(5)}

_PN_LOCAL_RE = re.compile(r"^[A-Za-z_][A-Za-z0-9_\-.]*[A-Za-z0-9_\-]$|^[A-Za-z_]$")

#: Words that must never appear in a loaded, user-visible literal.
FORBIDDEN_VISIBLE_WORDS = ("synthetic", "simulated", "fake")


# ── deterministic primitives ────────────────────────────────────────────────────────────────


def _rng(building_id: str, key: str) -> random.Random:
    seed = int(hashlib.sha256(f"{building_id}:{key}".encode("utf-8")).hexdigest()[:16], 16)
    return random.Random(seed)


def stable_uuid(building_id: str, kind: str, subject: str, start: datetime) -> str:
    """uuid5 of the record's identity -- the same record always gets the same id."""
    name = f"{building_id}:{kind}:{subject}:{start.strftime('%Y-%m-%dT%H:%M:%S')}"
    return str(uuidlib.uuid5(uuidlib.NAMESPACE_URL, name))


def _poisson(rng: random.Random, lam: float) -> int:
    """Knuth's sampler; lam is small here, so this is exact and cheap."""
    if lam <= 0:
        return 0
    limit, k, p = math.exp(-lam), 0, 1.0
    while True:
        p *= rng.random()
        if p <= limit:
            return k
        k += 1


def _local(iri: str) -> str:
    return iri.rsplit("#", 1)[-1].rsplit("/", 1)[-1]


# ── discovered inputs ───────────────────────────────────────────────────────────────────────


@dataclass(frozen=True)
class Equipment:
    """An equipment instance with every class it carries (inferred ancestors included)."""

    iri: str
    label: str
    classes: FrozenSet[str]
    space_iri: Optional[str] = None


@dataclass(frozen=True)
class Room:
    iri: str
    classes: FrozenSet[str]
    area_m2: Optional[float]
    has_capacity: bool
    area_ambiguous: bool = False
    #: The text the architect's drawing writes inside this room's own outline, or None when no
    #: drawing record covers the room. When present it outranks the graph's room type (see
    #: capacity_estimates).
    drawing_label: Optional[str] = None


@dataclass(frozen=True)
class BandedPoint:
    iri: str
    label: str
    quantity: str
    typical_lo: float
    typical_hi: float
    physical_lo: Optional[float]
    physical_hi: Optional[float]
    space_iri: Optional[str] = None


@dataclass
class Discovery:
    building_id: str
    namespace: str
    equipment: List[Equipment] = field(default_factory=list)
    rooms: List[Room] = field(default_factory=list)
    role_grants: Dict[str, int] = field(default_factory=dict)
    opening_hours: Optional[str] = None
    points: List[BandedPoint] = field(default_factory=list)


# ── opening hours ───────────────────────────────────────────────────────────────────────────

_DAY_NAMES = ("mon", "tue", "wed", "thu", "fri", "sat", "sun")


def parse_opening_hours(text: Optional[str]) -> Dict[int, Tuple[float, float]]:
    """{weekday: (open_hour, close_hour)} from "Mon-Fri 07:00-21:00; Sat 09:00-17:00; Sun closed".

    Anything it cannot read yields the stated fallback rather than a guess at the grammar.
    """
    if not text:
        return dict(FALLBACK_OPEN)
    out: Dict[int, Tuple[float, float]] = {}
    for clause in re.split(r"[;,]", text):
        m = re.match(
            r"\s*([A-Za-z]{3})[a-z]*(?:\s*-\s*([A-Za-z]{3})[a-z]*)?\s+"
            r"(\d{1,2}):(\d{2})\s*-\s*(\d{1,2}):(\d{2})\s*$",
            clause,
        )
        if not m:
            continue
        a, b = m.group(1).lower(), (m.group(2) or m.group(1)).lower()
        if a not in _DAY_NAMES or b not in _DAY_NAMES:
            continue
        lo = int(m.group(3)) + int(m.group(4)) / 60.0
        hi = int(m.group(5)) + int(m.group(6)) / 60.0
        if hi <= lo:
            continue
        for d in range(_DAY_NAMES.index(a), _DAY_NAMES.index(b) + 1):
            out[d] = (lo, hi)
    return out or dict(FALLBACK_OPEN)


def _is_open(hours: Dict[int, Tuple[float, float]], when: datetime) -> bool:
    window = hours.get(when.weekday())
    if not window:
        return False
    h = when.hour + when.minute / 60.0
    return window[0] <= h < window[1]


def _pick_time(
    rng: random.Random,
    day0: datetime,
    hours: Dict[int, Tuple[float, float]],
    open_share: float,
) -> datetime:
    """A time on `day0`, inside opening hours with probability `open_share` when the day opens."""
    window = hours.get(day0.weekday())
    if window and rng.random() < open_share:
        minutes = rng.uniform(window[0] * 60, window[1] * 60 - 1)
    else:
        minutes = rng.uniform(0, 24 * 60 - 1)
    return (day0 + timedelta(minutes=minutes)).replace(microsecond=0)


# ── alarm events ────────────────────────────────────────────────────────────────────────────


@dataclass(frozen=True)
class AlarmFamily:
    """Alarm behaviour for a Brick (or OCBV) equipment family -- class vocabulary, not names."""

    classes: Tuple[str, ...]
    conditions: Tuple[Tuple[str, str, Tuple[int, int]], ...]  # (condition, priority, clear min)
    responsible_role: str
    daily_rate: float


#: Most specific family first; the first family whose classes an equipment carries wins.
ALARM_FAMILIES: Tuple[AlarmFamily, ...] = (
    AlarmFamily(
        ("Fire_Alarm_Control_Panel",),
        (
            ("Panel fault", "HIGH", (20, 240)),
            ("Earth fault", "HIGH", (60, 480)),
            ("Mains power failure", "URGENT", (5, 60)),
        ),
        "Fire safety officer",
        0.05,
    ),
    AlarmFamily(
        ("Fire_Alarm", "Smoke_Detector", "Heat_Detector"),
        (
            ("Detector fault", "HIGH", (30, 360)),
            ("Detector contamination warning", "MEDIUM", (240, 2880)),
            ("Fire alarm activation", "URGENT", (10, 45)),
        ),
        "Fire safety officer",
        0.03,
    ),
    AlarmFamily(
        ("Air_Handling_Unit", "AHU"),
        (
            ("Filter differential pressure high", "MEDIUM", (240, 2880)),
            ("Supply fan failure", "HIGH", (30, 240)),
            ("Supply air temperature high", "MEDIUM", (20, 180)),
            ("Frost protection trip", "HIGH", (30, 120)),
        ),
        "Mechanical technician",
        0.06,
    ),
    AlarmFamily(
        ("Boiler",),
        (
            ("Burner lockout", "HIGH", (20, 180)),
            ("Low system water pressure", "HIGH", (60, 480)),
            ("Flue gas temperature high", "MEDIUM", (30, 240)),
        ),
        "Mechanical technician",
        0.08,
    ),
    AlarmFamily(
        ("Chiller",),
        (
            ("High refrigerant pressure trip", "HIGH", (30, 240)),
            ("Low evaporator temperature", "MEDIUM", (20, 120)),
            ("Compressor fault", "HIGH", (60, 600)),
        ),
        "Mechanical technician",
        0.08,
    ),
    AlarmFamily(
        ("Heat_Pump",),
        (
            ("Defrost cycle fault", "MEDIUM", (30, 240)),
            ("High pressure trip", "HIGH", (30, 240)),
        ),
        "Mechanical technician",
        0.06,
    ),
    AlarmFamily(
        ("Cooling_Tower",),
        (
            ("Basin water level low", "MEDIUM", (60, 480)),
            ("Fan vibration high", "MEDIUM", (60, 600)),
        ),
        "Mechanical technician",
        0.05,
    ),
    AlarmFamily(
        ("Pump",),
        (
            ("Pump run failure", "HIGH", (20, 240)),
            ("Vibration high", "MEDIUM", (120, 1440)),
            ("Mechanical seal leak", "MEDIUM", (240, 2880)),
        ),
        "Mechanical technician",
        0.05,
    ),
    AlarmFamily(
        ("Elevator",),
        (
            ("Door operator fault", "MEDIUM", (30, 240)),
            ("Lift out of service", "HIGH", (60, 480)),
            ("Emergency alarm button pressed", "URGENT", (5, 30)),
        ),
        "Lift engineer",
        0.07,
    ),
    AlarmFamily(
        ("Leak_Detector_Equipment",),
        (("Water detected", "URGENT", (30, 240)),),
        "Mechanical technician",
        0.02,
    ),
    AlarmFamily(
        ("Emergency_Generator", "Generator"),
        (
            ("Failed to start on test", "HIGH", (60, 1440)),
            ("Fuel level low", "MEDIUM", (240, 2880)),
        ),
        "Electrical technician",
        0.02,
    ),
    AlarmFamily(
        ("Energy_Storage", "Battery"),
        (
            ("Battery temperature high", "HIGH", (30, 240)),
            ("Cell voltage imbalance", "MEDIUM", (120, 1440)),
        ),
        "Electrical technician",
        0.03,
    ),
    AlarmFamily(
        ("Inverter",),
        (
            ("Grid fault", "MEDIUM", (5, 90)),
            ("Insulation resistance low", "MEDIUM", (60, 600)),
        ),
        "Electrical technician",
        0.04,
    ),
    AlarmFamily(
        ("Breaker_Panel",),
        (("Circuit breaker trip", "HIGH", (15, 180)),),
        "Electrical technician",
        0.02,
    ),
    AlarmFamily(
        ("Electric_Vehicle_Charging_Station",),
        (
            ("Charger fault", "LOW", (60, 1440)),
            ("Earth leakage trip", "MEDIUM", (30, 240)),
        ),
        "Electrical technician",
        0.03,
    ),
    AlarmFamily(
        ("VAV",),
        (("Damper position not reached", "LOW", (60, 1440)),),
        "Mechanical technician",
        0.02,
    ),
    AlarmFamily(
        ("Fan",),
        (("Fan run failure", "HIGH", (30, 240)),),
        "Mechanical technician",
        0.03,
    ),
    AlarmFamily(
        ("Camera",),
        (("Video signal lost", "MEDIUM", (10, 240)),),
        "Security officer",
        0.02,
    ),
    AlarmFamily(
        ("Meter",),
        (("Meter communication lost", "LOW", (30, 720)),),
        "Energy manager",
        0.01,
    ),
)

#: Classes that never raise alarms of their own here. Controlled openings are excluded because
#: their events are ACCESS events, written to their own file with their own privacy rules.
ALARM_EXCLUDED_CLASSES = frozenset({"Access_Control_Equipment"})


def alarm_family(eq: Equipment) -> Optional[AlarmFamily]:
    if eq.classes & ALARM_EXCLUDED_CLASSES:
        return None
    for fam in ALARM_FAMILIES:
        if eq.classes.intersection(fam.classes):
            return fam
    return None


def _window_days(window_start: datetime, anchor: datetime) -> Iterable[datetime]:
    day = window_start.replace(hour=0, minute=0, second=0, microsecond=0)
    while day <= anchor:
        yield day
        day += timedelta(days=1)


def alarm_events(
    building_id: str,
    equipment: Sequence[Equipment],
    anchor: datetime,
    weeks: int,
    hours: Dict[int, Tuple[float, float]],
) -> List[Dict[str, Any]]:
    """Alarm activation episodes that CLUSTER: a few chatty assets and a dominant condition each.

    Times are building-local wall clock (see the file header). Lifecycle, relative to `anchor`:
    raised -> acknowledged -> cleared, with acknowledgement slower outside staffed hours, and a
    tail of recent alarms never acknowledged. Status uses the TBox lifecycle vocabulary:
    detected (active, unacknowledged) | open (acknowledged, still active) | resolved (cleared).
    """
    window_start = anchor - timedelta(weeks=weeks)
    out: List[Dict[str, Any]] = []
    for eq in sorted(equipment, key=lambda e: e.iri):
        fam = alarm_family(eq)
        if fam is None:
            continue
        local = _local(eq.iri)
        persona = _rng(building_id, f"alarm-asset:{local}")
        # Heavy-tailed chattiness: most assets are quiet, a few generate most of the alarms.
        chatty = min(8.0, max(0.2, math.exp(persona.gauss(0.0, 1.0))))
        dominant = persona.randrange(len(fam.conditions))
        for day0 in _window_days(window_start, anchor):
            rng = _rng(building_id, f"alarm:{local}:{day0.strftime('%Y-%m-%d')}")
            lam = fam.daily_rate * chatty * (1.0 if day0.weekday() < 5 else 0.8)
            for _ in range(_poisson(rng, lam)):
                raised = _pick_time(rng, day0, hours, open_share=0.55)
                if raised < window_start or raised > anchor:
                    continue
                idx = dominant if rng.random() < 0.7 else rng.randrange(len(fam.conditions))
                condition, priority, clear_range = fam.conditions[idx]
                staffed = _is_open(hours, raised)
                median = 4.0 if staffed else 30.0
                if priority == "URGENT":
                    median /= 2.0
                ack_minutes = min(720.0, max(0.5, rng.lognormvariate(math.log(median), 0.8)))
                acknowledged = raised + timedelta(minutes=ack_minutes)
                cleared = acknowledged + timedelta(minutes=rng.uniform(*clear_range))
                # A standing tail: recent alarms nobody has acknowledged, plus the odd old one.
                recent = (anchor - raised) <= timedelta(hours=72)
                left_unacked = rng.random() < (0.35 if recent else 0.02)
                ack_at: Optional[datetime] = acknowledged.replace(microsecond=0)
                clear_at: Optional[datetime] = cleared.replace(microsecond=0)
                if left_unacked or ack_at > anchor:
                    ack_at, clear_at, status = None, None, "detected"
                elif clear_at > anchor:
                    clear_at, status = None, "open"
                else:
                    status = "resolved"
                rid = stable_uuid(building_id, "alarm", local, raised)
                out.append(
                    {
                        "kind": "alarm",
                        "uuid": rid,
                        "record_id": "ALM-" + rid.replace("-", "")[:8].upper(),
                        "label": f"{condition} - {eq.label}",
                        "condition": condition,
                        "priority": priority,
                        "responsible_role": fam.responsible_role,
                        "equipment_iri": eq.iri,
                        "space_iri": eq.space_iri,
                        "raised_at": raised,
                        "acknowledged_at": ack_at,
                        "cleared_at": clear_at,
                        "status": status,
                    }
                )
    return sorted(out, key=lambda e: (e["raised_at"], e["uuid"]))


# ── door access events (role template level only) ───────────────────────────────────────────

ACCESS_KINDS = ("access_denied", "held_open", "forced_door")

_DENIAL_REASONS = (
    ("Outside the role's time profile", 0.40),
    ("No grant for this opening", 0.30),
    ("Credential expired", 0.20),
    ("Credential suspended", 0.10),
)

_ACCESS_LABELS = {
    "access_denied": "Access denied",
    "held_open": "Door held open",
    "forced_door": "Door forced open",
}


def _weighted(rng: random.Random, items: Sequence[Tuple[str, float]]) -> str:
    total = sum(w for _, w in items)
    x = rng.uniform(0, total)
    for value, w in items:
        x -= w
        if x <= 0:
            return value
    return items[-1][0]


def access_events(
    building_id: str,
    openings: Sequence[Equipment],
    role_grants: Dict[str, int],
    anchor: datetime,
    weeks: int,
    hours: Dict[int, Tuple[float, float]],
) -> List[Dict[str, Any]]:
    """Forced-door, held-open and access-denied events at controlled openings.

    NO INDIVIDUAL IS MODELLED. A credential is represented by its ROLE TEMPLATE only (the
    `grantedToRole` values the building's own access-permission register declares), and no
    card number, badge id or name exists anywhere in the record. A forced door carries no role
    at all, because no credential was presented.

    Role weights come from the register: roles holding FEWER grants are denied more often
    (they reach fewer openings), roles holding MORE grants hold more doors open (they pass
    through more of them).
    """
    window_start = anchor - timedelta(weeks=weeks)
    roles = sorted(role_grants)
    denied_weights = [(r, 1.0 / (1.0 + role_grants[r])) for r in roles]
    held_weights = [(r, float(role_grants[r])) for r in roles]
    out: List[Dict[str, Any]] = []
    for op in sorted(openings, key=lambda e: e.iri):
        local = _local(op.iri)
        weight = min(4.0, max(0.25, math.exp(_rng(building_id, f"door:{local}").gauss(0.0, 0.6))))
        for day0 in _window_days(window_start, anchor):
            rng = _rng(building_id, f"access:{local}:{day0.strftime('%Y-%m-%d')}")
            open_day = bool(hours.get(day0.weekday()))
            scale = weight * (1.0 if open_day else 0.15)
            plan = (
                ("access_denied", _poisson(rng, 1.2 * scale), 0.85),
                ("held_open", _poisson(rng, 0.5 * scale), 0.85),
                ("forced_door", _poisson(rng, 0.04 * weight), 0.40),
            )
            for kind, n, open_share in plan:
                for _ in range(n):
                    start = _pick_time(rng, day0, hours, open_share=open_share)
                    if start < window_start or start > anchor:
                        continue
                    role: Optional[str] = None
                    reason: Optional[str] = None
                    if kind == "access_denied":
                        end = start
                        role = _weighted(rng, denied_weights) if roles else None
                        reason = _weighted(rng, _DENIAL_REASONS)
                    elif kind == "held_open":
                        secs = min(1800.0, max(35.0, rng.lognormvariate(math.log(120.0), 0.7)))
                        end = start + timedelta(seconds=int(secs))
                        role = _weighted(rng, held_weights) if roles else None
                    else:
                        end = start + timedelta(minutes=rng.uniform(1.0, 20.0))
                    end = end.replace(microsecond=0)
                    if end > anchor:
                        end = anchor
                    # Recent forced doors await review; everything else has been reviewed.
                    status = (
                        "detected"
                        if kind == "forced_door" and (anchor - start) <= timedelta(hours=48)
                        else "resolved"
                    )
                    rid = stable_uuid(building_id, f"access:{kind}", local, start)
                    out.append(
                        {
                            "kind": kind,
                            "uuid": rid,
                            "record_id": "ACC-" + rid.replace("-", "")[:8].upper(),
                            "label": f"{_ACCESS_LABELS[kind]} - {op.label}",
                            "opening_iri": op.iri,
                            "space_iri": op.space_iri,
                            "role": role,
                            "reason": reason,
                            "start": start,
                            "end": end,
                            "status": status,
                        }
                    )
    return sorted(out, key=lambda e: (e["start"], e["uuid"]))


# ── room capacity ───────────────────────────────────────────────────────────────────────────


@dataclass(frozen=True)
class DensityRule:
    classes: Tuple[str, ...]
    m2_per_person: float
    basis: str


#: Occupancy densities by room TYPE, each with its basis stated. Order matters: a room carrying
#: several types takes the first rule that matches, most people-dense first.
DENSITY_RULES: Tuple[DensityRule, ...] = (
    DensityRule(
        ("Conference_Room", "Classroom", "Lecture_Hall", "Auditorium"),
        2.0,
        "seated meeting or teaching layout at 2.0 m2 per person, in line with UK Building "
        "Bulletin 103 teaching-room areas; Approved Document B's 1.0 m2 per person for "
        "meeting rooms is the means-of-escape maximum, not a seated layout",
    ),
    DensityRule(
        ("Break_Room", "Breakroom", "Office_Kitchen"),
        2.0,
        "seated break-out use at 2.0 m2 per person; Approved Document B's 1.0 m2 per person "
        "for staff and common rooms is the means-of-escape maximum, not a seated layout",
    ),
    DensityRule(
        ("Office", "Enclosed_Office", "Open_Office"),
        10.0,
        "10 m2 per workplace, within the 8-13 m2 per workplace range the British Council for "
        "Offices gives for office design occupancy",
    ),
    DensityRule(
        ("Laboratory",),
        10.0,
        "10 m2 per workplace, the office workplace density applied to bench and desk "
        "workplaces; no published planning norm for laboratories is held",
    ),
)

#: Room types that are not laid out for people to occupy; a capacity for them would mislead.
NON_OCCUPIABLE = frozenset(
    {
        "Storage_Room",
        "Mechanical_Room",
        "Service_Room",
        "Telecom_Room",
        "Server_Room",
        "Rest_Room",
        "Restroom",
        "Staircase",
        "Vertical_Space",
        "Electrical_Room",
        "Janitor_Room",
        "Shaft",
    }
)


#: The densest planning figure Approved Document B gives for any occupied room. A capacity
#: implying less floor than this per person is impossible, not generous (BUG-671).
MIN_M2_PER_PERSON = 1.0

# ── what the DRAWING says (BUG-671) ──────────────────────────────────────────────────────────
#
# Measured on one building: the graph typed 10 m2 cellular offices as conference rooms and
# computer laboratories, so density-by-graph-type gave five people to a one-person office and
# six to a gas-meter room, while the architect's drawing wrote "Office" and "Gas Meter & Tank"
# inside those very outlines. The drawing is the authority on what a room is, so where a
# drawing record covers the room it decides; the graph type is used only where none does.
# The vocabulary below is generic architectural room naming, not any one building's.

#: A person count written at the START of a room label: "8P PHD Research", "30 P Seminar",
#: "120 Person Lecture Theatre", "120S Lecture Theatre", "16-20P Meeting", "8-12 Exec Meeting".
_DRAWING_COUNT_RE = re.compile(
    r"^\s*(\d{1,4})(?:\s*-\s*(\d{1,4}))?\s*(?:P\b|S\b|Persons?\b|People\b|(?=\s+[A-Za-z]))",
    re.IGNORECASE,
)

#: Rooms a drawing names as plant, IT, distribution, metering, storage or sanitary space.
_DRAWING_UNOCCUPIED_RE = re.compile(
    r"\b(stores?|storage|db\s+room|lan|riser|plant|meters?|switch\s+room|ups|server|comms|"
    r"cupboard|cupd|cleaners?|refuse|wc|toilets?|showers?|lift|stairs?|shaft)\b",
    re.IGNORECASE,
)

_DRAWING_SEATED_RE = re.compile(
    r"\b(meeting|meet|seminar|lecture|teaching|classroom|conference|boardroom|theatre)\b",
    re.IGNORECASE,
)
_DRAWING_BREAKOUT_RE = re.compile(
    r"\b(staff\s+room|common\s+room|break\s*-?\s*out|kitchen)\b", re.I
)
_DRAWING_LAB_RE = re.compile(r"\b(lab|laboratory|workshop|maker)\b", re.IGNORECASE)


def drawing_person_count(label: Optional[str]) -> Optional[Tuple[int, bool]]:
    """(persons, was_a_range) the drawing states for a room, or None. A range gives its top."""
    m = _DRAWING_COUNT_RE.match(label or "")
    if not m:
        return None
    return int(m.group(2) or m.group(1)), m.group(2) is not None


def drawing_says_unoccupied(label: Optional[str]) -> bool:
    """True when the drawing names the room as a space nobody is laid out to occupy."""
    return bool(label and _DRAWING_UNOCCUPIED_RE.search(label))


def _drawing_density(label: str) -> DensityRule:
    """The density for a room the drawing names but gives no person count for."""
    if _DRAWING_SEATED_RE.search(label):
        return DENSITY_RULES[0]
    if _DRAWING_BREAKOUT_RE.search(label):
        return DENSITY_RULES[1]
    if _DRAWING_LAB_RE.search(label):
        return DENSITY_RULES[3]
    return DENSITY_RULES[2]


def capacity_estimates(rooms: Sequence[Room]) -> Tuple[List[Dict[str, Any]], Counter]:
    """(estimates, skipped-by-reason). Only rooms WITHOUT a capacity get one, in this order of
    authority: the person count the drawing writes in the room's outline; else, for a room the
    drawing names, a density chosen from that name; else, with no drawing record, a density
    chosen from the graph's room type. Every other room is counted under the reason it was left
    alone."""
    out: List[Dict[str, Any]] = []
    skipped: Counter = Counter()
    for room in sorted(rooms, key=lambda r: r.iri):
        if room.has_capacity:
            skipped["already has a capacity"] += 1
            continue
        label = (room.drawing_label or "").strip()
        if label:
            estimate = _drawing_estimate(room, label, skipped)
            if estimate is not None:
                out.append(estimate)
            continue
        if room.area_ambiguous:
            skipped["floor plans disagree on its area"] += 1
            continue
        if room.area_m2 is None or room.area_m2 <= 0:
            skipped["no floor-plan area"] += 1
            continue
        if room.classes & NON_OCCUPIABLE:
            skipped["type not laid out for occupants"] += 1
            continue
        rule = next((r for r in DENSITY_RULES if room.classes.intersection(r.classes)), None)
        if rule is None:
            skipped["no density basis for its type"] += 1
            continue
        if room.area_m2 < rule.m2_per_person * 0.5:
            skipped["too small for one person at the stated density"] += 1
            continue
        persons = max(1, int(room.area_m2 // rule.m2_per_person))
        out.append(
            {
                "room_iri": room.iri,
                "capacity": persons,
                "area_m2": round(room.area_m2, 2),
                "m2_per_person": rule.m2_per_person,
                "basis": (
                    f"Estimated, not certified: {round(room.area_m2, 1)} m2 floor-plan area "
                    f"at {rule.basis}."
                ),
            }
        )
    return out, skipped


def _drawing_estimate(room: Room, label: str, skipped: Counter) -> Optional[Dict[str, Any]]:
    """The estimate for a room a drawing record names, or None with the skip reason counted."""
    area = room.area_m2 if room.area_m2 and room.area_m2 > 0 else None
    if drawing_says_unoccupied(label):
        skipped["drawing shows a room not laid out for occupants"] += 1
        return None
    stated = drawing_person_count(label)
    if stated is not None:
        persons, was_range = stated
        if persons < 1:
            skipped["drawing states no occupants"] += 1
            return None
        if area is not None and area / persons < MIN_M2_PER_PERSON:
            # The outline is smaller than the room the label describes ("120S Lecture Theatre"
            # inside 27 m2): the count is not in doubt, the outline is, so neither is used.
            skipped["drawing count does not fit its outline"] += 1
            return None
        where = f" inside its own {round(area, 1)} m2 outline" if area is not None else ""
        which = "the upper figure of the range" if was_range else "the figure"
        return {
            "room_iri": room.iri,
            "capacity": persons,
            "area_m2": round(area, 2) if area is not None else None,
            "m2_per_person": round(area / persons, 2) if area is not None else None,
            "basis": (
                f"From the floor plan, not certified: the architect's drawing labels this room "
                f"'{label}'{where}, and this capacity is {which} that label states."
            ),
        }
    if area is None:
        skipped["no floor-plan area"] += 1
        return None
    rule = _drawing_density(label)
    if area < rule.m2_per_person * 0.5:
        skipped["too small for one person at the stated density"] += 1
        return None
    return {
        "room_iri": room.iri,
        "capacity": max(1, int(area // rule.m2_per_person)),
        "area_m2": round(area, 2),
        "m2_per_person": rule.m2_per_person,
        "basis": (
            f"Estimated, not certified: {round(area, 1)} m2 floor-plan area at {rule.basis}. "
            f"The floor plan labels this room '{label}' and states no person count."
        ),
    }


def load_drawing_rooms(path: Path, namespace: str) -> Dict[str, Tuple[Optional[float], str]]:
    """{room_iri: (area_m2, label)} from a measured drawing-rooms file; {} when absent."""
    try:
        data = json.loads(Path(path).read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}
    out: Dict[str, Tuple[Optional[float], str]] = {}
    for row in data.get("rooms") or []:
        iri = row.get("ontology_iri")
        if not iri or not str(iri).startswith(namespace):
            continue
        area = row.get("area_m2")
        out[str(iri)] = (float(area) if area is not None else None, str(row.get("label") or ""))
    return out


# ── anomaly episodes (opt-in; see the module docstring) ─────────────────────────────────────

ANOMALY_DETECTORS = ("spike", "seasonal_residual", "stuck")


def anomaly_events(
    building_id: str,
    points: Sequence[BandedPoint],
    anchor: datetime,
    weeks: int,
    max_points: int = 40,
) -> List[Dict[str, Any]]:
    """Episodes whose observed value is consistent with the point's DECLARED band.

    Out-of-band detectors put the observed value beyond the typical band but inside the
    physical band; `stuck` holds a value inside the typical band. Baseline is the typical
    band's midpoint -- the declared ordinary range, never an invented one.
    """
    window_start = anchor - timedelta(weeks=weeks)
    chosen = sorted(points, key=lambda p: hashlib.sha256(p.iri.encode()).hexdigest())[:max_points]
    out: List[Dict[str, Any]] = []
    for pt in sorted(chosen, key=lambda p: p.iri):
        local = _local(pt.iri)
        span = pt.typical_hi - pt.typical_lo
        if span <= 0:
            continue
        phys_lo = pt.physical_lo if pt.physical_lo is not None else pt.typical_lo - span
        phys_hi = pt.physical_hi if pt.physical_hi is not None else pt.typical_hi + span
        baseline = round((pt.typical_lo + pt.typical_hi) / 2.0, 3)
        for day0 in _window_days(window_start, anchor):
            rng = _rng(building_id, f"anomaly:{local}:{day0.strftime('%Y-%m-%d')}")
            if rng.random() >= 0.06:
                continue
            start = day0 + timedelta(minutes=rng.uniform(0, 24 * 60 - 1))
            start = start.replace(microsecond=0)
            if start > anchor:
                continue
            detector = rng.choice(ANOMALY_DETECTORS)
            if detector == "stuck":
                observed = rng.uniform(pt.typical_lo, pt.typical_hi)
            elif pt.typical_lo > phys_lo and rng.random() < 0.3:
                observed = max(phys_lo, pt.typical_lo - span * rng.uniform(0.1, 0.4))
            else:
                observed = min(phys_hi, pt.typical_hi + span * rng.uniform(0.1, 0.6))
            if detector != "stuck" and pt.typical_lo <= observed <= pt.typical_hi:
                continue  # the physical band leaves no room outside the typical one
            end = start + timedelta(hours=rng.choice((1, 2, 4, 8, 26)))
            end_at: Optional[datetime] = end if end <= anchor else None
            rid = stable_uuid(building_id, f"anomaly:{detector}", local, start)
            out.append(
                {
                    "kind": "anomaly",
                    "uuid": rid,
                    "record_id": "ANM-" + rid.replace("-", "")[:8].upper(),
                    "label": f"Unusual {pt.quantity} reading - {pt.label}",
                    "detector": detector,
                    "point_iri": pt.iri,
                    "space_iri": pt.space_iri,
                    "quantity": pt.quantity,
                    "observed": round(observed, 3),
                    "baseline": baseline,
                    "typical_lo": pt.typical_lo,
                    "typical_hi": pt.typical_hi,
                    "physical_lo": phys_lo,
                    "physical_hi": phys_hi,
                    "start": start,
                    "end": end_at,
                    "status": "resolved" if end_at else "open",
                }
            )
    return sorted(out, key=lambda e: (e["start"], e["uuid"]))


# ── Turtle rendering ────────────────────────────────────────────────────────────────────────


def _lit(text: str) -> str:
    s = str(text).replace("\\", "\\\\").replace('"', '\\"').replace("\n", " ").replace("\r", " ")
    return f'"{s}"'


def _dt(value: datetime) -> str:
    return f'"{value.strftime("%Y-%m-%dT%H:%M:%S")}"^^xsd:dateTime'


def _iri(iri: str, namespace: str) -> str:
    """`bldg:local` when the local name is a valid prefixed name, else `<iri>`.

    Prefixed form matters beyond style: the input validator's dangling-reference check reads
    prefixed names only, so a reference written as a full IRI would escape it.
    """
    if iri.startswith(namespace):
        local = iri[len(namespace) :]
        if _PN_LOCAL_RE.match(local):
            return f"bldg:{local}"
    return f"<{iri}>"


def _header(title: str, lines: Sequence[str], namespace: str, anchor: datetime, extra_prefixes=()):
    out = [
        f"# {title}",
        f"# GENERATED by {GENERATOR} -- do not hand-edit; re-run the script instead.",
        f"# Anchor (history ends at): {anchor.strftime('%Y-%m-%dT%H:%M')} building-local time.",
        "#",
    ]
    out += [f"# {line}" if line else "#" for line in lines]
    out += [
        "",
        f"@prefix bldg: <{namespace}> .",
        "@prefix rdfs: <http://www.w3.org/2000/01/rdf-schema#> .",
        "@prefix xsd: <http://www.w3.org/2001/XMLSchema#> .",
        f"@prefix ontosage: <{ONTOSAGE}> .",
    ]
    out += list(extra_prefixes)
    out.append("")
    return out


_EVENT_PROVENANCE = (
    "EVERY record here declares ontosage:isSimulated true: these are placeholder records",
    "standing in for a system of record this building does not yet export. Answers resting",
    "on them must say so. Replace them by lifting the real export into the same shape.",
    "",
    "Times are building-local wall clock, the convention of the lifted registers.",
)


def render_alarm_ttl(events: Sequence[Dict[str, Any]], namespace: str, anchor: datetime) -> str:
    lines = _header(
        "Alarm activation episodes",
        (
            "Alarms cluster on a few assets with a dominant condition each; acknowledgement is",
            "slower outside opening hours; recent alarms may still be unacknowledged.",
            "effectiveFrom = raised, ontosage:acknowledgedAt = acknowledged, effectiveTo =",
            "cleared (ABSENT means still active). recordStatus: detected (unacknowledged) |",
            "open (acknowledged, active) | resolved (cleared).",
            "",
            *_EVENT_PROVENANCE,
        ),
        namespace,
        anchor,
    )
    for e in events:
        body = [
            f"bldg:AlarmEvent_{e['uuid'].replace('-', '')} a ontosage:AlarmEvent ;",
            f"    rdfs:label {_lit(e['label'])}@en ;",
            f"    ontosage:recordId {_lit(e['record_id'])} ;",
            f"    ontosage:alarmCondition {_lit(e['condition'])} ;",
            # alarmPriority, NOT ontosage:priority (BUG-695): priority's rdfs:domain is
            # MaintenanceIssue, so under the repository's RDFS reasoning every alarm carrying it
            # would be inferred a MaintenanceIssue -> KnowledgeTopic -> Capability and surface in
            # amenity answers. A domain axiom is an inference rule, not a validation check.
            f"    ontosage:alarmPriority {_lit(e['priority'])} ;",
            f"    ontosage:responsibleRole {_lit(e['responsible_role'])} ;",
            f"    ontosage:aboutEquipment {_iri(e['equipment_iri'], namespace)} ;",
        ]
        if e.get("space_iri"):
            body.append(f"    ontosage:aboutSpace {_iri(e['space_iri'], namespace)} ;")
        body.append(f"    ontosage:effectiveFrom {_dt(e['raised_at'])} ;")
        if e.get("acknowledged_at"):
            body.append(f"    ontosage:acknowledgedAt {_dt(e['acknowledged_at'])} ;")
        if e.get("cleared_at"):
            body.append(f"    ontosage:effectiveTo {_dt(e['cleared_at'])} ;")
        body += [
            f"    ontosage:recordStatus {_lit(e['status'])} ;",
            "    ontosage:isSimulated true .",
            "",
        ]
        lines += body
    return "\n".join(lines)


def render_access_ttl(events: Sequence[Dict[str, Any]], namespace: str, anchor: datetime) -> str:
    lines = _header(
        "Door access events at controlled openings",
        (
            "ROLE TEMPLATE LEVEL ONLY. No person, card number or badge id is recorded; a",
            "credential appears only as the role template the access-permission register grants",
            "to, and a forced door carries no role because no credential was presented.",
            "ontosage:accessEventKind: access_denied | held_open | forced_door.",
            "effectiveFrom = event start, effectiveTo = door closed/secured (equal for a denial).",
            "",
            *_EVENT_PROVENANCE,
        ),
        namespace,
        anchor,
    )
    for e in events:
        body = [
            f"bldg:AccessEvent_{e['uuid'].replace('-', '')} a ontosage:AccessEvent ;",
            f"    rdfs:label {_lit(e['label'])}@en ;",
            f"    ontosage:recordId {_lit(e['record_id'])} ;",
            f"    ontosage:accessEventKind {_lit(e['kind'])} ;",
            f"    ontosage:aboutEquipment {_iri(e['opening_iri'], namespace)} ;",
        ]
        if e.get("space_iri"):
            body.append(f"    ontosage:aboutSpace {_iri(e['space_iri'], namespace)} ;")
        if e.get("role"):
            body.append(f"    ontosage:presentedRole {_lit(e['role'])} ;")
        if e.get("reason"):
            body.append(f"    ontosage:denialReason {_lit(e['reason'])} ;")
        body += [
            f"    ontosage:effectiveFrom {_dt(e['start'])} ;",
            f"    ontosage:effectiveTo {_dt(e['end'])} ;",
            f"    ontosage:recordStatus {_lit(e['status'])} ;",
            "    ontosage:isSimulated true .",
            "",
        ]
        lines += body
    return "\n".join(lines)


def render_anomaly_ttl(events: Sequence[Dict[str, Any]], namespace: str, anchor: datetime) -> str:
    lines = _header(
        "Anomaly episodes",
        (
            "OPT-IN ONLY. The events store already holds the anomaly scanner's episodes, and a",
            "held AnomalyEvent graph class takes anomaly questions away from them. Do not load",
            "this file unless that routing has been changed.",
            "",
            *_EVENT_PROVENANCE,
        ),
        namespace,
        anchor,
    )
    for e in events:
        body = [
            f"bldg:AnomalyEvent_{e['uuid'].replace('-', '')} a ontosage:AnomalyEvent ;",
            f"    rdfs:label {_lit(e['label'])}@en ;",
            f"    ontosage:recordId {_lit(e['record_id'])} ;",
            f"    ontosage:detectedBy {_lit(e['detector'])} ;",
            f"    ontosage:aboutPoint {_iri(e['point_iri'], namespace)} ;",
        ]
        if e.get("space_iri"):
            body.append(f"    ontosage:aboutSpace {_iri(e['space_iri'], namespace)} ;")
        body += [
            f"    ontosage:observedValue \"{e['observed']}\"^^xsd:double ;",
            f"    ontosage:baselineValue \"{e['baseline']}\"^^xsd:double ;",
            f"    ontosage:effectiveFrom {_dt(e['start'])} ;",
        ]
        if e.get("end"):
            body.append(f"    ontosage:effectiveTo {_dt(e['end'])} ;")
        body += [
            f"    ontosage:recordStatus {_lit(e['status'])} ;",
            "    ontosage:isSimulated true .",
            "",
        ]
        lines += body
    return "\n".join(lines)


def render_capacity_ttl(
    estimates: Sequence[Dict[str, Any]], skipped: Counter, namespace: str, anchor: datetime
) -> str:
    skipped_lines = [f"  {n:>4}  {reason}" for reason, n in sorted(skipped.items())]
    lines = _header(
        "Room capacity derived from the floor plan",
        (
            "DERIVED, not simulated and not certified. In order of authority: the person count",
            "the architect's drawing writes inside the room's outline; else floor(area / density),",
            "at least 1, with the density chosen from the drawing's name for the room; else, where",
            "no drawing record covers the room, from the graph's room type. Each room states which",
            "in ontosage:capacityBasis. Rooms that already carry hbco:roomCapacity are left",
            "untouched. No room is marked isSimulated, because the room itself is real.",
            "",
            "Rooms left without an estimate, by reason:",
            *skipped_lines,
        ),
        namespace,
        anchor,
        extra_prefixes=(f"@prefix hbco: <{HBCO}> .",),
    )
    for e in estimates:
        lines += [
            f"{_iri(e['room_iri'], namespace)} hbco:roomCapacity {int(e['capacity'])} ;",
            f"    ontosage:capacityBasis {_lit(e['basis'])} .",
            "",
        ]
    return "\n".join(lines)


# ── discovery (READ-ONLY SPARQL) ────────────────────────────────────────────────────────────

_PREFIXES = f"""
PREFIX rdf: <http://www.w3.org/1999/02/22-rdf-syntax-ns#>
PREFIX rdfs: <http://www.w3.org/2000/01/rdf-schema#>
PREFIX brick: <{BRICK}>
PREFIX o: <{ONTOSAGE}>
PREFIX hbco: <{HBCO}>
PREFIX ref: <https://brickschema.org/schema/Brick/ref#>
"""

_EQUIPMENT_Q = (
    _PREFIXES
    + """
SELECT ?e ?t ?label ?loc ?rank WHERE {
  ?e a ?t . ?t rdfs:subClassOf* brick:Equipment .
  FILTER(STRSTARTS(STR(?e), "%(ns)s"))
  OPTIONAL { ?e rdfs:label ?label }
  OPTIONAL {
    ?e brick:hasLocation|brick:isPartOf ?loc . ?loc a brick:Location .
    OPTIONAL {
      VALUES (?lt ?rank) { (brick:Room 1) (brick:Space 2) (brick:Floor 3) (brick:Building 5) }
      ?loc a ?lt .
    }
  }
}"""
)

#: A location nobody ranked (a site, an outdoor area) sorts after a floor but before the
#: building as a whole, which says the least about where an alarm happened.
_UNRANKED_LOCATION = 4

_ROOMS_Q = (
    _PREFIXES
    + """
SELECT ?r ?t ?cap WHERE {
  ?r a brick:Room . FILTER(STRSTARTS(STR(?r), "%(ns)s"))
  ?r a ?t .
  OPTIONAL { ?r hbco:roomCapacity ?cap }
}"""
)

_ROLES_Q = (
    _PREFIXES
    + """
SELECT ?role (COUNT(DISTINCT ?g) AS ?grants) WHERE {
  ?g a o:AccessPermission ; o:grantedToRole ?role .
  FILTER(STRSTARTS(STR(?g), "%(ns)s"))
} GROUP BY ?role"""
)

_HOURS_Q = (
    _PREFIXES
    + """
SELECT ?h WHERE {
  ?b a brick:Building ; o:openingHours ?h . FILTER(STRSTARTS(STR(?b), "%(ns)s"))
} ORDER BY ?h LIMIT 1"""
)

#: Same shape as publisher_map._BANDS_QUERY: the deepest declaring class wins.
_BANDS_Q = (
    _PREFIXES
    + """
SELECT ?s ?label ?m ?lo ?hi ?plo ?phi ?loc (COUNT(DISTINCT ?anc) AS ?depth) WHERE {
  ?s ref:hasExternalReference ?r . ?r ref:hasTimeseriesId ?uuid .
  FILTER(STRSTARTS(STR(?s), "%(ns)s"))
  ?s a ?cls . ?cls o:measuresQuantityKind ?m .
  ?m o:typicalMin ?lo ; o:typicalMax ?hi .
  OPTIONAL { ?m o:physicalMin ?plo } OPTIONAL { ?m o:physicalMax ?phi }
  OPTIONAL { ?s rdfs:label ?label }
  OPTIONAL { ?s brick:hasLocation ?loc . ?loc a brick:Location . }
  OPTIONAL { ?cls rdfs:subClassOf* ?anc }
} GROUP BY ?s ?label ?m ?lo ?hi ?plo ?phi ?loc ORDER BY ?s DESC(?depth)"""
)


def _bindings(result: Dict[str, Any]) -> List[Dict[str, str]]:
    rows = []
    for b in (result or {}).get("results", {}).get("bindings", []):
        rows.append({k: v.get("value", "") for k, v in b.items()})
    return rows


def manifest_areas(paths: Iterable[str], namespace: str) -> Tuple[Dict[str, float], set]:
    """{room_iri: area_m2} from floor-plan manifests, and the IRIs whose areas disagree."""
    seen: Dict[str, set] = {}
    for path in sorted(paths):
        try:
            data = json.loads(Path(path).read_text(encoding="utf-8"))
        except (OSError, ValueError):
            continue
        for space in data.get("spaces") or []:
            iri = space.get("ontology_iri")
            area = space.get("area_m2")
            if not iri or not str(iri).startswith(namespace) or area is None:
                continue
            seen.setdefault(iri, set()).add(round(float(area), 2))
    areas = {iri: next(iter(v)) for iri, v in seen.items() if len(v) == 1}
    ambiguous = {iri for iri, v in seen.items() if len(v) > 1}
    return areas, ambiguous


async def discover(
    sparql_exec,
    building_id: str,
    namespace: str,
    manifest_glob: str,
    want_points: bool,
    drawing_rooms_path: Optional[str] = None,
) -> Discovery:
    """Everything the generators need, read from the live graph, the manifests and (when
    given) the measured drawing-rooms file."""
    found = Discovery(building_id=building_id, namespace=namespace)
    ns = {"ns": namespace}

    eq_classes: Dict[str, set] = {}
    eq_label: Dict[str, str] = {}
    eq_loc: Dict[str, Dict[str, int]] = {}
    for row in _bindings(await sparql_exec(_EQUIPMENT_Q % ns)):
        iri = row["e"]
        eq_classes.setdefault(iri, set()).add(_local(row["t"]))
        if row.get("label"):
            eq_label.setdefault(iri, row["label"])
        if row.get("loc"):
            rank = int(float(row["rank"])) if row.get("rank") else _UNRANKED_LOCATION
            ranks = eq_loc.setdefault(iri, {})
            ranks[row["loc"]] = min(rank, ranks.get(row["loc"], rank))
    for iri in sorted(eq_classes):
        # The MOST SPECIFIC location: a room says more than a floor, a floor more than the
        # building. Ties break on the IRI so the choice is stable between runs.
        locs = [
            loc for loc, _ in sorted(eq_loc.get(iri, {}).items(), key=lambda kv: (kv[1], kv[0]))
        ]
        found.equipment.append(
            Equipment(
                iri=iri,
                label=eq_label.get(iri) or _local(iri).replace("_", " "),
                classes=frozenset(eq_classes[iri]),
                space_iri=locs[0] if locs else None,
            )
        )

    areas, ambiguous = manifest_areas(glob.glob(manifest_glob, recursive=True), namespace)
    room_classes: Dict[str, set] = {}
    room_cap: Dict[str, bool] = {}
    for row in _bindings(await sparql_exec(_ROOMS_Q % ns)):
        room_classes.setdefault(row["r"], set()).add(_local(row["t"]))
        room_cap[row["r"]] = room_cap.get(row["r"], False) or bool(row.get("cap"))
    drawing = load_drawing_rooms(Path(drawing_rooms_path), namespace) if drawing_rooms_path else {}
    for iri in sorted(room_classes):
        drawn_area, drawn_label = drawing.get(iri, (None, ""))
        found.rooms.append(
            Room(
                iri=iri,
                classes=frozenset(room_classes[iri]),
                # The drawing's own outline wins over a manifest area: it is the measurement the
                # manifest was made from, and it cannot be one of the manifest's duplicates.
                area_m2=drawn_area if drawn_area is not None else areas.get(iri),
                has_capacity=room_cap.get(iri, False),
                area_ambiguous=(iri in ambiguous) and drawn_area is None,
                drawing_label=drawn_label or None,
            )
        )

    for row in _bindings(await sparql_exec(_ROLES_Q % ns)):
        found.role_grants[row["role"]] = int(float(row.get("grants") or 0))
    hours = _bindings(await sparql_exec(_HOURS_Q % ns))
    found.opening_hours = hours[0]["h"] if hours else None

    if want_points:
        taken = set()
        for row in _bindings(await sparql_exec(_BANDS_Q % ns)):
            if row["s"] in taken:
                continue  # rows arrive deepest class first; the first is the declaration
            taken.add(row["s"])
            found.points.append(
                BandedPoint(
                    iri=row["s"],
                    label=row.get("label") or _local(row["s"]),
                    quantity=_local(row["m"]),
                    typical_lo=float(row["lo"]),
                    typical_hi=float(row["hi"]),
                    physical_lo=float(row["plo"]) if row.get("plo") else None,
                    physical_hi=float(row["phi"]) if row.get("phi") else None,
                    space_iri=row.get("loc") or None,
                )
            )
    return found


def referenced_iris(*event_lists: Sequence[Dict[str, Any]], capacity=()) -> set:
    keys = ("equipment_iri", "opening_iri", "point_iri", "space_iri")
    out = {e[k] for events in event_lists for e in events for k in keys if e.get(k)}
    out |= {c["room_iri"] for c in capacity}
    return out


async def missing_in_graph(sparql_exec, iris: Iterable[str]) -> List[str]:
    """IRIs that have no triple as a subject in the live graph (read-only check)."""
    wanted = sorted(set(iris))
    present: set = set()
    for i in range(0, len(wanted), 200):
        chunk = wanted[i : i + 200]
        values = " ".join(f"<{iri}>" for iri in chunk)
        q = f"SELECT DISTINCT ?s WHERE {{ VALUES ?s {{ {values} }} ?s ?p ?o }}"
        present |= {row["s"] for row in _bindings(await sparql_exec(q))}
    return [iri for iri in wanted if iri not in present]


def _building_tz_name(building_id: str) -> Optional[str]:
    try:
        from orchestrator.services.requested_interval import building_tz

        return building_tz(building_id)
    except Exception:
        return None


def _local_now(tz_name: Optional[str]) -> datetime:
    from datetime import timezone

    now = datetime.now(timezone.utc)
    if tz_name:
        try:
            from zoneinfo import ZoneInfo

            now = now.astimezone(ZoneInfo(tz_name))
        except Exception:
            pass
    return now.replace(tzinfo=None, minute=0, second=0, microsecond=0)


def _visible_word_violations(text: str) -> List[str]:
    """Loaded literals (not Turtle comments) that call the data synthetic/simulated/fake."""
    bad = []
    for line in text.splitlines():
        if line.lstrip().startswith("#"):
            continue
        for m in re.finditer(r'"((?:[^"\\]|\\.)*)"', line):
            low = m.group(1).lower()
            if any(w in low for w in FORBIDDEN_VISIBLE_WORDS):
                bad.append(line.strip())
    return bad


def output_names(building_id: str, include_anomaly: bool) -> Dict[str, str]:
    """{kind: file name}. Anomaly appears ONLY when asked for (module docstring)."""
    names = {
        "alarm": f"{building_id}_alarm_events.ttl",
        "access": f"{building_id}_door_access_events.ttl",
        "capacity": f"{building_id}_room_capacity.ttl",
    }
    if include_anomaly:
        names["anomaly"] = f"{building_id}_anomaly_events.ttl"
    return names


def build_parser() -> argparse.ArgumentParser:
    ap = argparse.ArgumentParser(description=(__doc__ or "").split("\n\n", 1)[0])
    ap.add_argument(
        "--anchor",
        help="history end, building-local 'YYYY-MM-DDTHH:MM' "
        "(default: now, floored to the hour)",
    )
    ap.add_argument("--weeks", type=int, default=DEFAULT_WEEKS)
    ap.add_argument("--out-dir", default=str(_REPO_ROOT / "input"))
    ap.add_argument(
        "--manifests",
        help="glob for floor-plan manifests (default volumes/<building_id>/floor-plans/**/"
        "*.manifest.json)",
    )
    ap.add_argument(
        "--drawing-rooms",
        help="measured drawing-rooms JSON (default tests/fixtures/floor_plans/"
        "<building_id>_drawing_rooms.json; absent = graph room types only)",
    )
    ap.add_argument(
        "--include-anomaly",
        action="store_true",
        help="also write anomaly episodes -- read the module docstring first",
    )
    ap.add_argument("--dry-run", action="store_true", help="discover and count; write nothing")
    ap.add_argument(
        "--no-live-check",
        action="store_true",
        help="skip the read-only check that every referenced IRI exists",
    )
    return ap


async def main(argv: Optional[Sequence[str]] = None) -> int:
    args = build_parser().parse_args(argv)

    from orchestrator.services.deliberation.live import active_identity, sparql_exec

    identity = active_identity()
    building_id = identity["BUILDING_ID"]
    namespace = identity["BUILDING_NAMESPACE"]
    tz_name = _building_tz_name(building_id)
    anchor = (
        datetime.strptime(args.anchor, "%Y-%m-%dT%H:%M") if args.anchor else _local_now(tz_name)
    )
    manifest_glob = args.manifests or str(
        _REPO_ROOT / "volumes" / building_id / "floor-plans" / "**" / "*.manifest.json"
    )
    drawing_rooms = args.drawing_rooms or str(
        _REPO_ROOT / "tests" / "fixtures" / "floor_plans" / f"{building_id}_drawing_rooms.json"
    )
    if not Path(drawing_rooms).exists():
        print(f"[provision] no drawing-rooms file at {drawing_rooms}; graph room types only")
        drawing_rooms = None
    print(f"[provision] building={building_id} tz={tz_name} anchor={anchor} weeks={args.weeks}")

    found = await discover(
        sparql_exec, building_id, namespace, manifest_glob, args.include_anomaly, drawing_rooms
    )
    hours = parse_opening_hours(found.opening_hours)
    alarm_capable = [e for e in found.equipment if alarm_family(e)]
    openings = [e for e in found.equipment if "Access_Control_Equipment" in e.classes]
    print(
        f"[provision] discovered equipment={len(found.equipment)} alarm-capable="
        f"{len(alarm_capable)} openings={len(openings)} rooms={len(found.rooms)} "
        f"role-templates={len(found.role_grants)} hours={found.opening_hours!r}"
    )

    alarms = alarm_events(building_id, alarm_capable, anchor, args.weeks, hours)
    access = access_events(building_id, openings, found.role_grants, anchor, args.weeks, hours)
    capacity, skipped = capacity_estimates(found.rooms)
    anomalies = (
        anomaly_events(building_id, found.points, anchor, args.weeks)
        if args.include_anomaly
        else []
    )

    summary = {
        "alarms": len(alarms),
        "alarms_by_status": dict(Counter(e["status"] for e in alarms)),
        "alarms_top_assets": Counter(_local(e["equipment_iri"]) for e in alarms).most_common(5),
        "access": len(access),
        "access_by_kind": dict(Counter(e["kind"] for e in access)),
        "capacity_estimates": len(capacity),
        "capacity_skipped": dict(skipped),
        "anomalies": len(anomalies),
    }
    print("[provision] " + json.dumps(summary, default=str))

    if not args.no_live_check:
        missing = await missing_in_graph(
            sparql_exec, referenced_iris(alarms, access, anomalies, capacity=capacity)
        )
        if missing:
            print(f"[provision] REFUSING: {len(missing)} referenced IRI(s) absent: {missing[:8]}")
            return 2
        print("[provision] every referenced IRI exists in the live graph")

    if args.dry_run:
        return 0

    names = output_names(building_id, args.include_anomaly)
    outputs = {
        names["alarm"]: render_alarm_ttl(alarms, namespace, anchor),
        names["access"]: render_access_ttl(access, namespace, anchor),
        names["capacity"]: render_capacity_ttl(capacity, skipped, namespace, anchor),
    }
    if "anomaly" in names:
        outputs[names["anomaly"]] = render_anomaly_ttl(anomalies, namespace, anchor)
    out_dir = Path(args.out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    for name, text in outputs.items():
        bad = _visible_word_violations(text)
        if bad:
            print(f"[provision] REFUSING {name}: user-visible text names the data kind: {bad[:3]}")
            return 3
        # newline="\n": the same anchor must give the same BYTES on every platform, and text
        # mode on Windows would otherwise turn every line ending into CRLF.
        with open(out_dir / name, "w", encoding="utf-8", newline="\n") as fh:
            fh.write(text)
        print(f"[provision] wrote {out_dir / name} ({len(text.encode('utf-8'))} bytes)")
    return 0


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
