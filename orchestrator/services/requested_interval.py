# -*- coding: utf-8 -*-
"""The ONE place a requested time interval is resolved (V12-08, review T05).

    "Resolve the requested interval once, and forbid every downstream re-derivation."

WHY THIS MODULE EXISTS RATHER THAN A CONVENTION
-----------------------------------------------
BUG-480 was fixed in `dialogue_agent` in September: a named calendar day stopped being a
rolling 24 hours and became local midnight-to-midnight. The fix was correct and it was a
POINT REPAIR — it corrected the lane that was measured, and the other lanes kept their own
answers to the same question. Measured on 2026-09-12, three lanes disagreed about what
"yesterday" IS:

  dialogue_agent   calendar bounds, local, from the building's timezone        (correct)
  sql_agent        `now - timedelta(days=1)`, a duration, in the prompt hint   (wrong in kind)
  ARBITER          `_PAST_WINDOW_HOURS` mapped "yesterday" -> 24.0 hours, and
                   `fetch.py` turned that into `utcnow() - 24h` with NO upper
                   bound — so the window ran from 24 hours ago to NOW, half of
                   it today, in the wrong zone                                 (wrong twice)

In that table "yesterday" and "today" both mapped to 24.0 hours: the two most common time
words in the corpus named the SAME interval. An answer about one day was computed over
another, and every figure in it was real — which is what makes this class of defect hard to
see and worth a structural fix rather than a third point repair.

So the resolution lives here, once, and the lanes import it. A comment saying "use the
resolver" is not enforceable; an import is.

WHAT THIS DELIBERATELY DOES NOT DO
----------------------------------
It does not take over time parsing. The review warns against replacing a working path with
a parallel framework, and most time expressions are compiled perfectly well upstream. This
resolves the narrow set whose boundaries are NOT in dispute and returns None for everything
else, leaving the compiled range alone. "last night" spans two dates, "this morning" is a
part-day, "the weekend" is two days and which two depends on where you are — a wrong window
is not better than no window.
"""

from __future__ import annotations

import re
from datetime import datetime, timedelta
from typing import Optional, Tuple

#: The wire format every store, builder and formatter in this system speaks.
STAMP = "%Y-%m-%d %H:%M:%S"


#: Words that name a WHOLE CALENDAR DAY, and how many days back it starts.
#:
#: Only terms whose day boundaries are not in dispute. "last night" spans two dates,
#: "this morning" is a part-day, "the weekend" is two days and which two depends on where
#: you are — none of those belong here, and guessing at them would trade one wrong window
#: for another.
_CALENDAR_DAYS = {
    "yesterday": 1,
    "today": 0,
}


#: THE STORES ARE UTC. Every one of them, and every reader sees them that way (BUG-403).
#:
#: This module said the opposite from 2026-09-12 to 2026-09-15 — "the stores hold LOCAL
#: stamps" — and three changes were built on it (BUG-518, BUG-519 and the fetch fallback in
#: BUG-517), each moving a comparison against stored data from UTC to local time and so
#: shifting it an hour the wrong way under BST. The premise came from measuring the wide
#: table through a MySQL session in the server's SYSTEM zone: its column is TIMESTAMP, which
#: MySQL converts into the SESSION zone on read, so it looked local. The orchestrator's
#: adapters pin every session to +00:00 (mysql_adapter, and mysql_events_adapter through
#: it), and read that way on 2026-09-15 at 00:34 UTC the newest rows were: sensor_data
#: 00:34 (TIMESTAMP), co2_data / occupancy_data 00:33 and sensor_data_synth 00:32 (DATETIME,
#: written by the publisher on a +00:00 session), and events are generated from utcnow().
#:
#: So: compare against stored data with `store_now()`. Use the building's zone only to
#: decide WHICH local day a word names, and to SHOW a stored time to a person.


def store_now() -> datetime:
    """Now, on the stores' clock: naive UTC. The reference for any comparison with stored rows."""
    return datetime.utcnow()


def to_store(local_wall: datetime, tz_name: Optional[str]) -> datetime:
    """A naive building-local wall-clock time, as a naive store (UTC) time.

    DST is handled by zoneinfo, so a local day that is 23 or 25 hours long converts to the
    right span. With no usable zone the value is returned unchanged — the same answer the
    system gave before a zone was known, rather than a guess.
    """
    if local_wall.tzinfo is not None:
        local_wall = local_wall.replace(tzinfo=None)
    if not tz_name:
        return local_wall
    try:
        from zoneinfo import ZoneInfo

        return (
            local_wall.replace(tzinfo=ZoneInfo(tz_name))
            .astimezone(ZoneInfo("UTC"))
            .replace(tzinfo=None)
        )
    except Exception:  # pragma: no cover - an unknown zone must not break the turn
        return local_wall


def to_local(store_time: datetime, tz_name: Optional[str]) -> datetime:
    """A naive store (UTC) time, as naive building-local wall-clock time — for SHOWING it."""
    if store_time.tzinfo is not None:
        store_time = store_time.replace(tzinfo=None)
    if not tz_name:
        return store_time
    try:
        from zoneinfo import ZoneInfo

        return (
            store_time.replace(tzinfo=ZoneInfo("UTC"))
            .astimezone(ZoneInfo(tz_name))
            .replace(tzinfo=None)
        )
    except Exception:  # pragma: no cover
        return store_time


def local_now(tz_name: Optional[str] = None) -> datetime:
    """Now, as the building's wall clock shows it (naive).

    For deciding which local day "today" is and for labelling — NOT for comparing with
    stored rows, which are UTC (see the note above `store_now`).
    """
    if tz_name:
        try:
            from zoneinfo import ZoneInfo

            return datetime.now(ZoneInfo(tz_name)).replace(tzinfo=None)
        except Exception:  # pragma: no cover - an unknown zone must not break the turn
            pass
    return datetime.now()


def building_tz(building_id: Optional[str] = None) -> Optional[str]:
    """The active building's IANA zone name, or None when it declares none."""
    try:
        from orchestrator.services.building_context import resolve_building_context

        return getattr(resolve_building_context(building_id), "timezone", None) or None
    except Exception:  # pragma: no cover - no zone is a sane fallback
        return None


def local_stamp(fmt: str = "%Y-%m-%d %H:%M", building_id: Optional[str] = None) -> str:
    """'Now' as a person reads it on site: building-local, labelled (WB-06)."""
    return f"{building_local_now(building_id).strftime(fmt)} (building time)"


def building_local_now(building_id: Optional[str] = None) -> datetime:
    """`local_now` for the active building, resolving its zone for you. Display use only."""
    return local_now(building_tz(building_id))


def calendar_day_bounds(
    text: str, tz_name: Optional[str] = None, now: Optional[datetime] = None
) -> Optional[Tuple[str, str]]:
    """Local midnight-to-midnight bounds when a question names a calendar day (BUG-480).

    "Give me a report on the CO2 in room 5.01 yesterday" compiled to a bound of `now-24h`,
    which the resolver dutifully turned into a stamp 24 hours old. The query then covered
    17:16 on the 6th to 17:16 on the 7th — a rolling day, HALF OF IT TODAY — under a report
    headed "Yesterday". Every figure in it was real, which is what made it hard to see.

    "Yesterday" in plain English is a date, not a duration. A reader comparing two days
    cannot use a window that slides with the clock, and a report about it that silently
    includes this afternoon is wrong in a way no amount of correct arithmetic fixes.

    Returns None when no calendar day is named, leaving the compiled range alone: this
    narrows a specific, checkable case rather than taking over time parsing.

    The DAY is chosen in the building's zone — a day is the occupants' Tuesday, not UTC's —
    and its bounds are then CONVERTED to the stores' clock (UTC), because that is what the
    SQL builders compare them against. `now`, when passed, is building-local wall time.
    Without a zone no conversion happens, which is also what the tests without one expect.
    """
    low = (text or "").lower()
    days_back = None
    for word, back in _CALENDAR_DAYS.items():
        if re.search(rf"\b{re.escape(word)}\b", low):
            days_back = back
            break
    if days_back is None:
        return None

    if now is None:
        now = local_now(tz_name)

    day = (now - timedelta(days=days_back)).date()
    start = datetime(day.year, day.month, day.day, 0, 0, 0)
    # INCLUSIVE END, because the SQL builders emit `<=`. Using the next midnight would
    # pull in the first instant of the following day, which for "yesterday" means a
    # reading from today appearing in a report about a day that has ended.
    end = datetime(day.year, day.month, day.day, 23, 59, 59)
    return to_store(start, tz_name).strftime(STAMP), to_store(end, tz_name).strftime(STAMP)


def named_day(text: str) -> Optional[str]:
    """Which calendar day the text names, or None. Used to LABEL a resolved interval."""
    low = (text or "").lower()
    for word in _CALENDAR_DAYS:
        if re.search(rf"\b{re.escape(word)}\b", low):
            return word
    return None


def interval_hours(start: str, end: str) -> Optional[float]:
    """Span of a resolved interval in hours, for the consumers that report a window size.

    The span is DERIVED from the resolved bounds rather than asserted alongside them. A
    duration carried next to an interval is a second source of truth about the same fact,
    and the two drift — which is the whole failure this module exists to end.
    """
    try:
        a = datetime.strptime(str(start)[:19], STAMP)
        b = datetime.strptime(str(end)[:19], STAMP)
    except (TypeError, ValueError):
        return None
    return (b - a).total_seconds() / 3600.0
