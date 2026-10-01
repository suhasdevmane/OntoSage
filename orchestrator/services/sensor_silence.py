# -*- coding: utf-8 -*-
"""Which sensors have stopped reporting, and when each was last seen (W3-05).

WHAT WENT WRONG
---------------
Asked on 2026-09-23 and again on 2026-09-29, the live system gave two different non-answers to
the same question::

    "Which sensors have stopped reporting, and when was each last seen?"
      -> "To determine which sensors have stopped reporting, we would need a complete log that
          shows the most recent timestamp for every sensor ... With the information at hand, I
          can't identify any sensors that have gone silent."

    "Which sensors stopped reporting and when?"
      -> "All of the sensors listed have a reading at the most recent timestamp ... none of
          them appear to have stopped reporting."

The first asks for a log the store IS -- ``MAX(timestamp) GROUP BY sensor`` is one query. The
second is worse than vague: it is a confident all-clear inferred from the rows that happened to
be in front of the model, which says nothing whatever about the sensors that are not in them.
A sensor's silence is invisible in a window of readings BY DEFINITION, so a lane that reasons
from readings can only ever conclude that everything is fine.

WHY IT IS DERIVED AND NEVER AUTHORED
------------------------------------
A last-seen timestamp is a fact about the DATA, not about the building, so it cannot live in a
TTL: the moment it were written down it would be wrong, and it would go on being wrong silently.
This module computes it from whatever stores the building registers, every time it is asked.

WHAT IT IS FOR
--------------
On 2026-09-29 a boot found a five-day hole in every narrow table because the publisher had not
been running (CAVEAT-890). Nothing in the system said so; the hole was found by hand. This is
the instrument that says so.

BUILDING-AGNOSTIC
-----------------
The declared sensors and their stores come from the ACTIVE building's sensor map; each store is
resolved through the adapter registry; staleness limits come from the evidence policy, per
modality. No store name, table name, sensor name or count appears here.

FOUR ANSWERS, NOT TWO
---------------------
``reporting``   wrote inside its modality's freshness limit.
``silent``      has rows, and none recent -- this is the question's subject, and it carries the
                time it was last seen.
``never``       declared in the ontology and holding no rows at all. A data-plumbing gap, not a
                dead instrument, and saying "stopped reporting" of it would be false.
``not probed``  the store could not be asked. Reported as a named gap, never folded into
                "everything is fine" -- an unreachable datasource and a healthy one must not
                render the same.
"""

from __future__ import annotations

import asyncio
import json
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

from shared.utils import get_logger

logger = get_logger(__name__)

#: How many silent sensors are named individually before the rest are counted. A reader cannot
#: act on four hundred lines, and a wall of uuids is how a real outage gets skimmed past.
NAMED_LIMIT = 12

#: Hard ceiling on how long the whole derivation may take. Past this the answer says what it
#: managed to measure and which stores it did not reach, rather than blocking a turn.
DEFAULT_TIMEOUT_S = 25.0


@dataclass
class SensorSilence:
    """One declared sensor and when its store last heard from it."""

    uuid: str
    label: str
    store: str
    last_seen: Optional[datetime] = None  # store time (UTC), None = no rows at all
    limit_minutes: float = 0.0
    #: The moment the sweep ran, so age is a property of the measurement rather than of now().
    #: Read back an hour later the row must still report the age it was measured at.
    measured_at: Optional[datetime] = None

    @property
    def age_minutes(self) -> Optional[float]:
        """Minutes of silence at the moment of measurement, or None when nothing ever arrived."""
        if self.last_seen is None or self.measured_at is None:
            return None
        return round((self.measured_at - self.last_seen).total_seconds() / 60.0, 1)

    @property
    def is_silent(self) -> bool:
        """Has rows, and none inside its modality's freshness limit."""
        age = self.age_minutes
        return age is not None and age > self.limit_minutes


@dataclass
class SilenceReport:
    """What the stores say about every declared sensor, at one moment."""

    measured_at: datetime  # store time (UTC)
    declared: int = 0
    reporting: int = 0
    silent: List[SensorSilence] = field(default_factory=list)
    never: List[SensorSilence] = field(default_factory=list)
    not_probed: List[str] = field(default_factory=list)

    @property
    def probed(self) -> int:
        return self.reporting + len(self.silent) + len(self.never)

    @property
    def complete(self) -> bool:
        """True when every declared sensor was actually asked about."""
        return not self.not_probed and self.probed == self.declared


def _store_modality(store_key: str) -> str:
    """The modality word a store key implies, for the per-modality freshness limit.

    ``temperature_data`` -> ``temperature``. A store whose name implies nothing falls to the
    policy default, which is the honest outcome: guessing a modality would apply the wrong
    limit, and a limit is what decides whether a sensor is called dead.
    """
    text = str(store_key or "").strip().lower()
    for sep in ("#", "/", ":"):
        if sep in text:
            text = text.rsplit(sep, 1)[-1]
    return text[:-5] if text.endswith("_data") else text


def declared_sensors(sensor_map_path: str) -> Tuple[Dict[str, set], Dict[str, str]]:
    """``({store: {uuid}}, {uuid: label})`` from the active building's sensor map.

    The map is keyed several ways over the same entries (IRI, local name, label), so uuids are
    de-duplicated rather than counted.
    """
    by_store: Dict[str, set] = {}
    labels: Dict[str, str] = {}
    try:
        raw = json.loads(Path(sensor_map_path).read_text(encoding="utf-8"))
    except Exception as exc:
        logger.warning(f"[sensor_silence] sensor map unreadable at {sensor_map_path}: {exc}")
        return {}, {}
    for entry in (raw or {}).values():
        if not isinstance(entry, dict):
            continue
        uid, store = entry.get("uuid"), entry.get("storage")
        if not uid or not store:
            continue
        by_store.setdefault(str(store), set()).add(str(uid))
        label = entry.get("label") or entry.get("uri") or ""
        if label and str(uid) not in labels:
            labels[str(uid)] = str(label)
    return by_store, labels


async def _last_seen_for_store(adapter: Any, uuids: List[str]) -> Optional[Dict[str, Any]]:
    """``{uuid: last seen}`` from one adapter, or None when it cannot be asked per sensor.

    Two names are tried, in order. ``latest_by_uuid_exhaustive`` is the one a wide store
    implements: a wide table's sensors are COLUMNS, so an exact answer for a sensor that has
    stopped costs a full scan, and only a caller that is asking about silence should pay for
    it. ``latest_by_uuid`` is the narrow store's, where one ``GROUP BY`` is already exact and
    already cheap. An adapter with neither is reported as a named gap rather than skipped.

    A present key with a ``None`` value means the sensor was looked up and has no rows; an
    ABSENT key means it was not measured, and the two must not collapse.
    """
    for name in ("latest_by_uuid_exhaustive", "latest_by_uuid"):
        probe = getattr(adapter, name, None)
        if probe is None:
            continue
        try:
            return await probe(sorted(uuids))
        except Exception as exc:
            logger.warning(f"[sensor_silence] {name} failed: {exc}")
            return None
    return None


async def derive_silence(
    timeout_s: float = DEFAULT_TIMEOUT_S,
    now: Optional[datetime] = None,
) -> Optional[SilenceReport]:
    """Ask every registered store when it last heard from each declared sensor.

    Returns ``None`` only when the building declares no sensors at all or no adapter is
    available — that is "cannot say", and a caller must not render it as "nothing is silent".
    """
    from shared.config import settings

    by_store, labels = declared_sensors(settings.SENSOR_MAP_PATH)
    if not by_store:
        return None
    try:
        from orchestrator.services.adapters.registry import adapter_registry
    except Exception as exc:
        logger.warning(f"[sensor_silence] adapter registry unavailable: {exc}")
        return None
    if not getattr(adapter_registry, "is_available", False):
        return None

    from orchestrator.services.evidence.policy import load_policy
    from orchestrator.services.requested_interval import store_now

    policy = load_policy()
    measured_at = now or store_now()
    report = SilenceReport(measured_at=measured_at, declared=len(set().union(*by_store.values())))

    async def one_store(store_key: str, uuids: set) -> None:
        adapter = adapter_registry.get(store_key)
        if adapter is None:
            report.not_probed.append(f"{store_key}: no adapter ({len(uuids)} sensors)")
            return
        seen = await _last_seen_for_store(adapter, list(uuids))
        if seen is None:
            report.not_probed.append(
                f"{store_key}: cannot be read per sensor ({len(uuids)} sensors)"
            )
            return
        limit = policy.max_age_minutes(_store_modality(store_key))
        unmeasured = 0
        for uid in sorted(uuids):
            if uid not in seen:
                unmeasured += 1
                continue
            row = SensorSilence(
                uuid=uid,
                label=labels.get(uid, uid),
                store=store_key,
                last_seen=seen[uid],
                limit_minutes=limit,
                measured_at=measured_at,
            )
            if row.last_seen is None:
                report.never.append(row)
            elif row.is_silent:
                report.silent.append(row)
            else:
                report.reporting += 1
        if unmeasured:
            report.not_probed.append(f"{store_key}: {unmeasured} sensor(s) not returned")

    try:
        await asyncio.wait_for(
            asyncio.gather(*(one_store(k, v) for k, v in sorted(by_store.items()))),
            timeout_s,
        )
    except asyncio.TimeoutError:
        report.not_probed.append(f"the sweep was cut off after {timeout_s:.0f}s")
    except Exception as exc:
        logger.error(f"[sensor_silence] sweep failed: {exc}", exc_info=True)
        report.not_probed.append(f"the sweep failed: {type(exc).__name__}")

    report.silent.sort(key=lambda r: r.last_seen or measured_at)
    report.never.sort(key=lambda r: r.label)
    return report


def _describe_age(minutes: Optional[float]) -> str:
    """'3 days' / '7 hours' / '42 minutes'. Units a reader can act on, not raw minutes."""
    if minutes is None:
        return "never"
    if minutes >= 2880:
        return f"{minutes / 1440:.1f} days"
    if minutes >= 120:
        return f"{minutes / 60:.1f} hours"
    return f"{minutes:.0f} minutes"


def format_silence_answer(report: Optional[SilenceReport], tz_name: Optional[str] = None) -> str:
    """The answer, naming each silent sensor and the time it was last seen.

    Every sentence states its denominator. "Three sensors are silent" out of four is an outage;
    out of four thousand it is a Tuesday, and the reader cannot tell which without the total.
    """
    if report is None:
        return (
            "I could not read the stores to check when each sensor last reported, so I cannot "
            "say which have gone silent. That is a gap in the check, not an all-clear."
        )
    from orchestrator.services.requested_interval import to_local

    def stamp(dt: Optional[datetime]) -> str:
        if dt is None:
            return "never"
        try:
            return to_local(dt, tz_name).strftime("%Y-%m-%d %H:%M")
        except Exception:
            return dt.strftime("%Y-%m-%d %H:%M")

    lines: List[str] = []
    n_silent, n_never = len(report.silent), len(report.never)

    if not n_silent and not n_never:
        lines.append(
            f"No declared sensor has gone silent. All {report.probed} of "
            f"{report.declared} sensors I could check wrote to their store within the "
            f"freshness limit for their modality, as of {stamp(report.measured_at)}."
        )
    else:
        head = (
            f"{n_silent} of {report.declared} declared sensors have stopped reporting"
            if n_silent
            else f"No declared sensor has stopped reporting, but {n_never} of "
            f"{report.declared} have never written at all"
        )
        lines.append(f"{head} (checked {stamp(report.measured_at)}).")

    if n_silent:
        lines.append("")
        lines.append("| Sensor | Store | Last seen | Silent for |")
        lines.append("|---|---|---|---|")
        for row in report.silent[:NAMED_LIMIT]:
            lines.append(
                f"| {row.label} | {row.store} | {stamp(row.last_seen)} | "
                f"{_describe_age(row.age_minutes)} |"
            )
        if n_silent > NAMED_LIMIT:
            lines.append("")
            lines.append(
                f"{n_silent - NAMED_LIMIT} further sensors are silent and are not listed here."
            )

    if n_never:
        lines.append("")
        named = ", ".join(r.label for r in report.never[:NAMED_LIMIT])
        more = "" if n_never <= NAMED_LIMIT else f", and {n_never - NAMED_LIMIT} more"
        lines.append(
            f"A further {n_never} sensor(s) are declared in the building model and hold no "
            f"readings at all, so they have never reported rather than stopped: {named}{more}."
        )

    if report.not_probed:
        lines.append("")
        lines.append(
            "Not checked, so these are unknown rather than healthy: "
            + "; ".join(report.not_probed[:6])
            + ("." if len(report.not_probed) <= 6 else f"; and {len(report.not_probed) - 6} more.")
        )

    return "\n".join(lines)
