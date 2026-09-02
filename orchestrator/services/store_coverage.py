# -*- coding: utf-8 -*-
"""Which stores can actually answer about a window, and which cannot (BUG-378 / CAVEAT-361).

A point is registered to exactly one store via ``ref:storedAt``, and the design contract is
that it reads from the store it is registered to. That contract is right, and it is not the
problem. The problem is CHOOSING a point whose store stopped receiving data before the window
the question asks about.

Measured on bldg1. Room 5.04 has two temperature points:

* ``Air_Temperature_Sensor_5.04`` -> ``database1`` — 585,002 readings, 1,045 of them on the
  requested date, current to today;
* ``Room5.04_sat_temperature`` -> ``temperature_data`` — a narrow table frozen at
  2026-08-26 13:36.

The lane resolved the second and answered "No data found" while the first sat there holding
the answer. That is not a data gap; it is a selection defect, and it is broad: 665 of the 728
points bound to the eight frozen stores are ``_sat_`` synthetic-overlay points shadowing live
real sensors (contact 466, co2 66, humidity 66, temperature 66, parking 1).

This module answers one question — *can this store say anything about this window?* — so the
lanes can prefer a point that can over one that cannot, and can say so plainly when none can.

BUILDING-AGNOSTIC: every fact here is read from the live adapters at runtime. No store names,
no modalities, no building literals. A building whose stores are all current gets the same
answers with nothing to skip.
"""

from __future__ import annotations

import time
from datetime import datetime, timedelta
from typing import Any, Dict, List, Optional, Sequence, Tuple

from shared.utils import get_logger

logger = get_logger(__name__)

#: How long a store's observed latest-timestamp is trusted before it is re-read. The value
#: only has to be short relative to how fast staleness matters and long enough that a replay
#: does not re-probe every store on every question.
_TTL_SECONDS = 300.0

#: store key -> (latest_observation, monotonic time it was read)
_CACHE: Dict[str, Tuple[Optional[datetime], float]] = {}


def reset_cache() -> None:
    """Drop the cached latest-timestamps. Used by tests and after a store is repointed."""
    _CACHE.clear()


def _store_key(storage: Optional[str]) -> str:
    """The adapter-registry key for a ``ref:storedAt`` value.

    The graph carries a full IRI (``http://...abacws#temperature_data``) while the registry is
    keyed by the bare name. Splitting on both separators keeps this working whether the lane
    passes an IRI, a prefixed name (``bldg:temperature_data``) or an already-bare key.
    """
    text = str(storage or "").strip()
    if not text:
        return ""
    for sep in ("#", "/", ":"):
        if sep in text:
            text = text.rsplit(sep, 1)[-1]
    return text


async def latest_observation(store: str, adapter: Any) -> Optional[datetime]:
    """Newest timestamp the store holds, or None when it holds nothing / cannot say.

    None is returned for BOTH "the store is empty" and "the store could not be asked". The
    caller must therefore treat None as *unknown*, never as *stale*: refusing to read a store
    because a health probe failed would turn a transient adapter error into a wrong answer,
    which is a worse failure than the one this module exists to prevent.
    """
    key = _store_key(store)
    if not key:
        return None
    hit = _CACHE.get(key)
    if hit is not None and (time.monotonic() - hit[1]) < _TTL_SECONDS:
        return hit[0]

    latest: Optional[datetime] = None
    try:
        probe = getattr(adapter, "latest_timestamp", None)
        if probe is not None:
            latest = await probe(key)
    except Exception as exc:  # pragma: no cover - adapter-specific failures
        logger.warning(f"[store_coverage] could not read latest timestamp for {key}: {exc}")
        latest = None
    _CACHE[key] = (latest, time.monotonic())
    return latest


def covers(
    latest: Optional[datetime],
    window_start: Optional[datetime],
    grace: timedelta = timedelta(hours=1),
) -> Optional[bool]:
    """Can a store whose newest reading is `latest` say anything about a window?

    Tri-state on purpose:

    * ``True``  — the newest reading is at or after the window opens, so there is something;
    * ``False`` — the newest reading predates the window entirely, so there is provably
      nothing to find and reading it can only ever return "no data";
    * ``None``  — not known (no probe, empty store, unbounded window). Never treated as False.

    Only the START of the window is compared. A store that stops mid-window still holds part
    of the answer, and excluding it would discard real evidence to avoid a partial one.
    """
    if latest is None or window_start is None:
        return None
    return latest >= (window_start - grace)


def partition_by_coverage(
    uuids: Sequence[str],
    storage_map: Optional[Dict[str, str]],
    latest_by_store: Dict[str, Optional[datetime]],
    window_start: Optional[datetime],
    latest_by_uuid: Optional[Dict[str, Optional[datetime]]] = None,
) -> Tuple[List[str], List[str], Dict[str, str]]:
    """Split uuids into (can-cover, provably-cannot, why-not per skipped uuid).

    `latest_by_uuid` wins over `latest_by_store` wherever it has an entry, because a store's
    newest row is not a statement about any particular sensor in it. Measured on bldg1:
    noise_data holds 236 sensors and ONE has written in the last 24 hours, so store-level
    freshness calls it current while 235 of its points are eight days dead.

    A uuid whose coverage is UNKNOWN is kept. The bar for setting a point aside is PROOF that
    it holds nothing in the window, never mere suspicion — an unknown store that is actually
    fine must still be read.
    """
    per_uuid = latest_by_uuid or {}
    usable: List[str] = []
    skipped: List[str] = []
    reasons: Dict[str, str] = {}
    for uid in uuids:
        store = _store_key((storage_map or {}).get(uid))
        # A uuid PRESENT in per_uuid was looked up. A None value there is therefore proof
        # that the sensor has no rows at all -- not the "unknown" that a missing key means.
        # The adapter must return an EMPTY map rather than all-None when its query fails,
        # or a transient database error would read as every sensor being dead.
        known_empty = uid in per_uuid and per_uuid[uid] is None
        if uid in per_uuid:
            latest, scope = per_uuid[uid], "this sensor"
        else:
            latest, scope = latest_by_store.get(store), store
        if known_empty or covers(latest, window_start) is False:
            skipped.append(uid)
            reasons[uid] = (
                f"{scope} has nothing after {latest:%Y-%m-%d %H:%M}"
                if latest
                else f"{scope} has no readings at all"
            )
        else:
            usable.append(uid)
    return usable, skipped, reasons


def describe_skipped(
    reasons: Dict[str, str], sensor_metadata: Optional[Dict[str, Dict[str, str]]] = None
) -> str:
    """One honest sentence about points that were set aside, or "" when none were.

    Silence here would be its own defect: a lane that quietly drops a point the user's
    question named, and then answers from the rest, has changed the question without saying
    so. Naming the point and the store is what makes the omission checkable.
    """
    if not reasons:
        return ""
    named = []
    for uid, why in list(reasons.items())[:3]:
        label = ((sensor_metadata or {}).get(uid) or {}).get("label") or uid[:8]
        named.append(f"{label} ({why})")
    more = "" if len(reasons) <= 3 else f", and {len(reasons) - 3} more"
    return f"Not read, because their store cannot cover the period asked about: {'; '.join(named)}{more}."
