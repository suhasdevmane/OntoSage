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
from datetime import date, datetime, timedelta, timezone
from typing import Any, Dict, List, Optional, Tuple

#: The wire format every store, builder and formatter in this system speaks.
STAMP = "%Y-%m-%d %H:%M:%S"


#: Words that name a WHOLE CALENDAR DAY, and how many days back it starts.
#:
#: Only terms whose day boundaries are not in dispute. "last night" spans two dates,
#: "this morning" is a part-day, "the weekend" is two days and which two depends on where
#: you are — none of those belong here, and guessing at them would trade one wrong window
#: for another.
#: G7 (QA-trial plan, 2026-10-04, BUG-1430): checked in INSERTION order, longer phrases
#: FIRST. "the day before yesterday" contains the word "yesterday" as a substring, so if
#: the bare "yesterday" entry were checked first (or this dict were unordered), the
#: compound phrase would match it and resolve to ONE day back instead of two -- exactly
#: the live defect: a follow-up asking for two days back was answered with yesterday's
#: window, narrated as "the day before" over data that was not it.
_CALENDAR_DAYS = {
    "day before yesterday": 2,
    "two days ago": 2,
    "2 days ago": 2,
    "the day before yesterday": 2,
    "yesterday": 1,
    "today": 0,
}

#: The reverse of the map above, for a resolver that must NAME the day it means rather
#: than only measure how far back it is. Builds from _CALENDAR_DAYS so the two can never
#: disagree; "the day before yesterday" is inserted last among the days_back=2 phrases
#: above so it is the one a dict comprehension's last-write-wins picks here -- the most
#: natural phrase to substitute for "yesterday" in a rewritten question.
_DAYS_BACK_TO_PHRASE = {back: phrase for phrase, back in _CALENDAR_DAYS.items()}


def _named_day_word(low: str) -> Optional[str]:
    """The LONGEST calendar-day phrase the lowercased text contains, or None.

    "the day before yesterday" contains "yesterday", so a first-match scan over an unordered
    table resolved it one day back: the two named days produced one window (BUG-1437). The
    longest phrase wins, so a phrase that contains another can never be shadowed by it.
    """
    hits = [word for word in _CALENDAR_DAYS if re.search(rf"\b{re.escape(word)}\b", low)]
    return max(hits, key=len) if hits else None


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
    word = _named_day_word((text or "").lower())
    if word is None:
        return None
    days_back = _CALENDAR_DAYS[word]

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
    return _named_day_word((text or "").lower())


def rows_in_window(
    rows: List[Dict[str, Any]], start: str, end: str
) -> Optional[List[Dict[str, Any]]]:
    """The rows whose timestamp falls inside a resolved window, or None when none can be read.

    `start` and `end` are store-clock STAMP strings, inclusive, as `calendar_day_bounds`
    returns them. Rows are compared on the same clock (a timezone-aware stamp is converted to
    UTC first). A row with no readable timestamp is dropped, because it cannot be shown to lie
    in the named day. When NO row has a readable timestamp the rows are returned unchanged
    and the caller must say it could not check the window, rather than narrate it as checked.
    """
    try:
        lo = datetime.strptime(str(start)[:19], STAMP)
        hi = datetime.strptime(str(end)[:19], STAMP)
    except (TypeError, ValueError):
        return None
    kept, readable = [], 0
    for row in rows:
        if not isinstance(row, dict):
            continue
        ts = row.get("timestamp") or row.get("Datetime") or row.get("datetime")
        if isinstance(ts, str):
            try:
                ts = datetime.fromisoformat(ts.replace("Z", "+00:00"))
            except ValueError:
                ts = None
        if not isinstance(ts, datetime):
            continue
        if ts.tzinfo is not None:
            ts = ts.astimezone(timezone.utc).replace(tzinfo=None)
        readable += 1
        if lo <= ts <= hi:
            kept.append(row)
    if readable == 0:
        return None
    return kept


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


# ── CALENDAR PERIODS LARGER THAN A DAY (BUG-939) ─────────────────────────────
#
# `calendar_day_bounds` above resolves "today" and "yesterday". Nothing resolved a WEEK,
# and the consequence was measured on 2026-09-29: "Compare energy use this week against
# last week" reached the store as
#
#     WHERE datetime >= DATE_SUB(NOW(), INTERVAL 30 DAY) ... ORDER BY datetime DESC
#     LIMIT 1000                                                             -- per uuid
#
# — a fixed 30 days rather than the two weeks named, which the per-sensor row cap then cut
# to roughly the newest 11 days. Both SQL builders DO honour bounds; the bounds were the
# classifier's to supply, and measured directly on 2026-09-30 the classifier gives, for
# questions of exactly this shape:
#
#     "Compare energy use this week against last week."              2026-09-16 .. 2026-09-30
#                                                                    (a rolling 14 days)
#     "How does the temperature in room 5.01 this week compare
#      with last week?"                                              null .. null
#     "Will floor 3 or floor 4 be warmer tomorrow?"                   now .. "now+1d"
#                                                                    (the end unresolvable)
#
# So it is not that the bounds were dropped: the same question shape yields a wrong window,
# no window, or a window in the future, depending on wording. A named calendar period has
# one answer and it is arithmetic, so it is computed here instead of asked for.
#
# THE PERIOD IS CHOSEN IN THE BUILDING'S ZONE AND CONVERTED TO THE STORES' (UTC) CLOCK, for
# the reason written above `store_now`: three changes and a P1 were withdrawn in September
# after a MySQL session in the server's own zone made a TIMESTAMP column look local.

#: Units whose calendar boundaries are not in dispute. A WEEK here is the ISO week, which is
#: not an assumption: `series_summary._bucket_of` labels buckets `<year>-W<iso week>`, so any
#: other choice would put these bounds and the buckets computed inside them out of step.
_PERIOD_UNITS = ("week", "month", "quarter", "year")

#: "this <unit>" — the period in progress.
_THIS_RE = {u: re.compile(rf"\bthis\s+{u}\b") for u in _PERIOD_UNITS}

#: "last|previous|prior <unit>" — the whole period before the one in progress.
_LAST_RE = {u: re.compile(rf"\b(?:last|previous|prior|preceding)\s+{u}\b") for u in _PERIOD_UNITS}

#: A TRAILING DURATION WEARING A CALENDAR WORD, which this resolver must refuse.
#:
#: "over the last week" almost always means the trailing seven days, not ISO week 39; on a
#: Wednesday those two differ by three days at each end. The module's rule is that a window
#: whose boundaries are in dispute gets no window at all, so the compiled range is left
#: alone — which is what the system did before this function existed, rather than a guess.
_TRAILING_RE = {
    u: re.compile(
        rf"\b(?:over|in|during|for|across|within|the)\s+(?:the\s+)?"
        rf"(?:last|past|previous|prior)\s+{u}\b"
        rf"|\bpast\s+{u}\b"
        rf"|\b\d+\s+{u}s?\b"
    )
    for u in _PERIOD_UNITS
}


def _month_start_back(day: date, months: int) -> date:
    """The first of the month `months` whole months before `day`'s month."""
    total = (day.year * 12 + (day.month - 1)) - months
    return date(total // 12, total % 12 + 1, 1)


def _unit_start(day: date, unit: str, back: int) -> date:
    """First DAY of the `unit` that is `back` whole units before the one containing `day`."""
    if unit == "week":
        monday = day - timedelta(days=day.isoweekday() - 1)
        return monday - timedelta(weeks=back)
    if unit == "month":
        return _month_start_back(day, back)
    if unit == "quarter":
        quarter_first = date(day.year, 3 * ((day.month - 1) // 3) + 1, 1)
        return _month_start_back(quarter_first, 3 * back)
    return date(day.year - back, 1, 1)


def _unit_end(start: date, unit: str) -> date:
    """Last DAY of the unit that begins on `start`."""
    if unit == "week":
        return start + timedelta(days=6)
    months = {"month": 1, "quarter": 3, "year": 12}[unit]
    return _month_start_back(start, -months) - timedelta(days=1)


def named_period(text: str) -> Optional[Tuple[str, List[int]]]:
    """The calendar unit the text names and which instances of it, newest first.

    ``("week", [0, 1])`` means "this week and last week"; ``("month", [1])`` means "last
    month". None when nothing resolvable is named, when TWO different units are named ("this
    week against last month" has no single bucket and the comparison lane refuses it too),
    when a calendar DAY is named (``calendar_day_bounds`` is narrower and already right), or
    when the phrase is a trailing duration rather than a calendar period.
    """
    low = (text or "").lower()
    if not low or named_day(low) is not None:
        return None
    found: List[Tuple[str, List[int]]] = []
    for unit in _PERIOD_UNITS:
        if _TRAILING_RE[unit].search(low):
            continue
        offsets = []
        if _THIS_RE[unit].search(low):
            offsets.append(0)
        if _LAST_RE[unit].search(low):
            offsets.append(1)
        if offsets:
            found.append((unit, offsets))
    if len(found) != 1:
        return None
    return found[0]


def calendar_period_bounds(
    text: str, tz_name: Optional[str] = None, now: Optional[datetime] = None
) -> Optional[Tuple[str, str]]:
    """Store-clock bounds covering every calendar period the question names (BUG-939).

    Returns ``(start, end)`` as ``STAMP`` strings on the stores' UTC clock, or None when
    :func:`named_period` finds nothing it will resolve. ``now``, when passed, is
    building-local wall time.

    WHEN TWO PERIODS ARE NAMED THE SPAN REACHES ONE WHOLE UNIT FURTHER BACK, and that is
    deliberate rather than slack. The per-period arithmetic downstream chooses its bucket
    size from the span of the ROWS it is given, and ``series_summary._bucket_size`` needs
    1.5 units before it will bucket by that unit. A fetch of exactly "this week and last
    week" holds rows from last Monday to NOW — 9.2 days when asked on a Wednesday, under
    the 10.5 days that rule requires — so it would be bucketed by DAY and the comparison
    would be between two partial days. That is the 291.7% rise BUG-936's fix exists to
    prevent, and narrowing the window "correctly" would have re-introduced it. The surplus
    period is not analysed as if it were one of the named ones: ``_names_this_against_last``
    takes the two NEWEST buckets. One period named needs no margin and gets none.

    The margin is not a guess at a threshold: reaching one unit further back makes the row
    span at least TWO whole units, and two clears 1.5 for every unit and every day of the
    week — which is why it is applied to all four rather than to the week alone, where the
    shortfall was first measured. A month pair asked on the 1st fails the same way (745
    hours against the 1,008 a month bucket needs), and so do a quarter pair and a year
    pair. The rule is pinned by a test that calls ``_bucket_size`` on the span these bounds
    produce, so the coupling is checked rather than remembered.

    The end is the last second of the newest named period, because both SQL builders emit
    ``<=``; for a period still in progress that bound lies ahead of now, which selects
    exactly the rows that exist so far and keeps the stated window equal to the one named.
    """
    named = named_period(text)
    if named is None:
        return None
    unit, offsets = named
    if now is None:
        now = local_now(tz_name)
    today = now.date()

    newest_start = _unit_start(today, unit, min(offsets))
    margin = 1 if len(offsets) > 1 else 0
    oldest_start = _unit_start(today, unit, max(offsets) + margin)
    start_local = datetime(oldest_start.year, oldest_start.month, oldest_start.day, 0, 0, 0)
    last_day = _unit_end(newest_start, unit)
    end_local = datetime(last_day.year, last_day.month, last_day.day, 23, 59, 59)
    return (
        to_store(start_local, tz_name).strftime(STAMP),
        to_store(end_local, tz_name).strftime(STAMP),
    )


def restrict_to_named_day(
    data: Any, question: str, tz_name: Optional[str] = None, now: Optional[datetime] = None
) -> Tuple[Any, Optional[Tuple[str, str]], bool]:
    """Narrow fetched rows to the calendar day the question names (BUG-1437).

    Returns ``(data, bounds, checked)``. ``bounds`` is None when the question names no day, in
    which case ``data`` is returned untouched. When it names one, ``data`` carries only the rows
    inside that day; ``checked`` is False when the rows had no readable timestamp, so the caller
    can say the window was NOT verified rather than presenting unfiltered rows as the day.

    Only ``dict`` payloads and bare row lists are narrowed; anything else passes through.
    """
    bounds = calendar_day_bounds(question, tz_name, now=now)
    if bounds is None:
        return data, None, True
    if isinstance(data, dict):
        rows = data.get("data") or []
    elif isinstance(data, list):
        rows = data
    else:
        return data, bounds, False
    kept = rows_in_window(rows, bounds[0], bounds[1])
    if kept is None:
        return data, bounds, False
    if isinstance(data, dict):
        return {**data, "data": kept}, bounds, True
    return kept, bounds, True
