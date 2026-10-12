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
#: The ARTICLE is what makes it a duration (2026-10-11): "for last week", "during last week" and
#: "in last month" name the calendar period, and "export the CO2 readings for floor 3 for last
#: week" was fetched as the default 30 days. Measured: 3 of 4,060 bank questions move (during
#: last year / during last week / in last month), 0 study texts.
_TRAILING_RE = {
    u: re.compile(
        rf"\bthe\s+(?:last|past|previous|prior)\s+{u}\b" rf"|\bpast\s+{u}\b" rf"|\b\d+\s+{u}s?\b"
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


# ── A DATE THE QUESTION WRITES OUT (BUG-1490) ───────────────────────────────────────────────
#
# "What was the average temperature in room 5.23 in March 2025?" names its period as plainly as
# a question can, and the window still came from the classifier. On two identical asks
# (2026-10-10) it returned 2025-03-01 .. 2025-03-31 once and NOTHING the second time, so the
# second read the last 30 days of 2026 and headed them "March 2025". `calendar_period_bounds`
# resolves only RELATIVE periods ("this week", "last month"); a written-out date was always left
# to the model. A written-out date is arithmetic, not interpretation, so it is computed here.
#
# Narrow on purpose, by this module's rule that a window in dispute gets no window at all:
#   * a YEAR is required. "on 3 April" has two readings and is left to the classifier.
#   * a numeric date other than ISO is refused: 03/04/2025 is April to one reader, March to another.
#   * two dates are ONE SPAN only when the words join them ("from .. to", "between .. and",
#     "6 to 12 October 2025"); two dates otherwise are a comparison and are left alone.
#   * a date after "since", "after", "before", "until" or "as of" is an open interval: refused.
#   * a time of day narrows a SINGLE named day, and only a clock time counts (a colon, am/pm,
#     noon, midday, midnight): "between 20 and 24 °C" is a band, not two o'clock times.
# The end is inclusive because both SQL builders emit `<=`, so it is one second before the named
# end: "from 10:00 to 16:00" reads [10:00, 16:00), exactly what a half-open key computes.

_MON = (
    r"(jan(?:uary)?|feb(?:ruary)?|mar(?:ch)?|apr(?:il)?|may|june?|july?|aug(?:ust)?|"
    r"sep(?:t(?:ember)?)?|oct(?:ober)?|nov(?:ember)?|dec(?:ember)?)\.?"
)
_MONTH_NUM = {
    "jan": 1, "feb": 2, "mar": 3, "apr": 4, "may": 5, "jun": 6,
    "jul": 7, "aug": 8, "sep": 9, "oct": 10, "nov": 11, "dec": 12,
}  # fmt: skip
_YEAR = r"((?:19|20)\d{2})(?!\d|[.:]\d)"  # "2025." ends a sentence; "2025.5" is no year
_ORD = r"(?:st|nd|rd|th)?"
_WEEKDAY = r"(?:(?:mon|tues?|wed(?:nes)?|thu(?:rs)?|fri|sat(?:ur)?|sun)(?:day)?\.?,?\s+)"
_JOIN = r"(?:to|and|until|till|through|thru|-|–|—)"

#: "6 to 12 October 2025", "between 6 and 12 October 2025": a day span sharing one month.
_DAY_SPAN_DF = re.compile(
    rf"\b(\d{{1,2}}){_ORD}\s*{_JOIN}\s*{_WEEKDAY}?(\d{{1,2}}){_ORD}\s+(?:of\s+)?{_MON},?\s+{_YEAR}"
)
#: "October 6-12, 2025".
_DAY_SPAN_MF = re.compile(
    rf"\b{_MON}\s+(\d{{1,2}}){_ORD}\s*{_JOIN}\s*(\d{{1,2}}){_ORD},?\s+{_YEAR}"
)
#: "January to March 2025": a month span sharing one year.
_MONTH_SPAN = re.compile(rf"\b{_MON}\s*{_JOIN}\s*{_MON},?\s+{_YEAR}")
#: "3 April 2025", "3rd of April, 2025".
_DAY_DF = re.compile(rf"(?<![\d.:])\b(\d{{1,2}}){_ORD}\s+(?:of\s+)?{_MON},?\s+{_YEAR}")
#: "January 13, 2025".
_DAY_MF = re.compile(rf"\b{_MON}\s+(\d{{1,2}}){_ORD},?\s+{_YEAR}")
#: "2025-01-13".
_DAY_ISO = re.compile(r"(?<![\d.:])\b((?:19|20)\d{2})-(\d{2})-(\d{2})\b")
#: "March 2025".
_MONTH_YEAR = re.compile(rf"\b{_MON},?\s+{_YEAR}")

#: A clock time: "10:00", "9am", "2.30 pm" is NOT one (a room number looks like it), "noon".
_CLOCK = r"(?:\d{1,2}(?::[0-5]\d)?\s*(?:a\.?m\.?|p\.?m\.?)(?![a-z])|\d{1,2}:[0-5]\d|noon|midday|midnight)"
_TIME_SPAN = re.compile(rf"(?<![\d.:])({_CLOCK})\s*{_JOIN}\s*({_CLOCK})")
_TIME_AT = re.compile(rf"\b(?:at|around|about)\s+({_CLOCK})")
#: An open interval: the date is one end of it, not the period.
_OPEN_BEFORE = re.compile(
    r"\b(?:since|after|before|until|till|by|as\s+of|starting|beginning|from)\s+(?:the\s+)?"
    rf"{_WEEKDAY}?$"
)
#: A date used as a NAME: "use the May 2021 framework", "the 3 March 2025 incident". An article or
#: possessive directly before the date, with no temporal preposition before THAT, makes the date
#: describe a thing, not bound a period. Measured 2026-10-10: the only two of 4,060 bank questions
#: the resolver claimed were both this shape (a dated document); "on the 13th of January" is not.
_ATTRIBUTIVE = re.compile(r"\b(?:the|a|an|its|their|our|his|her|your|my)\s+$")
_TEMPORAL_ARTICLE = re.compile(
    r"\b(?:on|in|during|for|over|throughout|across|of|from|between|to|until|till|through)\s+"
    r"(?:the|a|an|its|their|our|his|her|your|my)\s+$"
)
#: "the week of 8 October 2025": the ISO week holding that day.
_WEEK_OF = re.compile(r"\bweek\s+(of|beginning|starting|commencing)\s+(?:the\s+)?" rf"{_WEEKDAY}?$")
#: What may sit between two dates for them to be one span: a join word and perhaps a weekday.
_SPAN_GAP = re.compile(rf"^\s*{_JOIN}\s*{_WEEKDAY}?(?:the\s+)?$")


def _month_of(token: str) -> int:
    return _MONTH_NUM[token.lower().rstrip(".")[:3]]


def _clock_minutes(token: str, is_end: bool) -> Optional[int]:
    """Minutes after local midnight for one clock token; None when it is not a real time."""
    t = token.lower().replace(".", "").replace(" ", "")
    if t in ("noon", "midday"):
        return 12 * 60
    if t == "midnight":
        return 24 * 60 if is_end else 0
    m = re.fullmatch(r"(\d{1,2})(?::(\d{2}))?(am|pm)?", t)
    if not m:
        return None
    hour, minute, ampm = int(m.group(1)), int(m.group(2) or 0), m.group(3)
    if ampm:
        if not 1 <= hour <= 12:
            return None
        hour = hour % 12 + (12 if ampm == "pm" else 0)
    elif hour > 24 or (hour == 24 and minute):
        return None
    return hour * 60 + minute


def _dated_spans(low: str) -> List[Tuple[int, int, date, date, str]]:
    """Every written-out date or month in the text as (start, end, first day, last day, kind)."""
    found: List[Tuple[int, int, date, date, str]] = []
    taken: List[Tuple[int, int]] = []

    def free(a: int, b: int) -> bool:
        return all(b <= s or a >= e for s, e in taken)

    def add(a: int, b: int, d0: date, d1: date, kind: str) -> None:
        found.append((a, b, d0, d1, kind))
        taken.append((a, b))

    def month_end(y: int, m: int) -> date:
        return _month_start_back(date(y, m, 1), -1) - timedelta(days=1)

    # Spans first, so "6 to 12 October 2025" is not read as the 12th alone.
    for m in _DAY_SPAN_DF.finditer(low):
        y, mo = int(m.group(4)), _month_of(m.group(3))
        add(m.start(), m.end(), date(y, mo, int(m.group(1))), date(y, mo, int(m.group(2))), "span")
    for m in _DAY_SPAN_MF.finditer(low):
        if free(m.start(), m.end()):
            y, mo = int(m.group(4)), _month_of(m.group(1))
            add(
                m.start(),
                m.end(),
                date(y, mo, int(m.group(2))),
                date(y, mo, int(m.group(3))),
                "span",
            )
    for m in _MONTH_SPAN.finditer(low):
        if free(m.start(), m.end()):
            y, m0, m1 = int(m.group(3)), _month_of(m.group(1)), _month_of(m.group(2))
            add(m.start(), m.end(), date(y, m0, 1), month_end(y, m1), "span")
    for rx, order in ((_DAY_DF, "dmy"), (_DAY_MF, "mdy"), (_DAY_ISO, "ymd")):
        for m in rx.finditer(low):
            if not free(m.start(), m.end()):
                continue
            if order == "dmy":
                y, mo, d = int(m.group(3)), _month_of(m.group(2)), int(m.group(1))
            elif order == "mdy":
                y, mo, d = int(m.group(3)), _month_of(m.group(1)), int(m.group(2))
            else:
                y, mo, d = int(m.group(1)), int(m.group(2)), int(m.group(3))
            day = date(y, mo, d)  # raises on 31 February: the caller treats that as no window
            add(m.start(), m.end(), day, day, "day")
    for m in _MONTH_YEAR.finditer(low):
        if free(m.start(), m.end()):
            y, mo = int(m.group(2)), _month_of(m.group(1))
            add(m.start(), m.end(), date(y, mo, 1), month_end(y, mo), "month")
    return sorted(found)


def explicit_date_bounds(
    text: str, tz_name: Optional[str] = None, now: Optional[datetime] = None
) -> Optional[Tuple[str, str]]:
    """Store-clock bounds of the date, day span or month a question WRITES OUT, or None.

    See the block above for what is refused and why. Returns ``(start, end)`` as ``STAMP``
    strings on the stores' UTC clock; the dates themselves are the building's local days.
    A question that names a day WITHOUT a year ("on Wednesday", "8 October") is resolved by
    ``named_date_bounds`` (CAVEAT-1616); ``now`` is the building's local time, for tests.
    """
    low = (text or "").lower()
    if not low:
        return None
    if not re.search(r"(?:19|20)\d{2}", low):
        return named_date_bounds(low, tz_name, now=now)
    try:
        spans = _dated_spans(low)
    except ValueError:  # a date that does not exist names no period
        return None
    if not spans:
        return None
    if len(spans) == 2:
        (a0, a1, d0, _, k0), (b0, b1, _, d1, k1) = spans
        if not _SPAN_GAP.match(low[a1:b0]) or d1 < d0 or ("month" in (k0, k1) and k0 != k1):
            return None  # two dates not joined as one span are a comparison
        spans = [(a0, b1, d0, d1, "span")]
    if len(spans) != 1:
        return None
    start, end, first, last, kind = spans[0]
    before = low[max(0, start - 40) : start]
    week = _WEEK_OF.search(before) if kind == "day" else None
    if week is not None:
        if week.group(1) == "of":
            first = first - timedelta(days=first.isoweekday() - 1)
        last = first + timedelta(days=6)
        kind = "span"
    elif kind != "span" and _OPEN_BEFORE.search(before):
        return None  # a joined span carries its own "from"/"between"; a lone date does not
    elif kind != "span" and _ATTRIBUTIVE.search(before) and not _TEMPORAL_ARTICLE.search(before):
        return None  # the date names a thing ("the May 2021 framework"), not a period
    if last < first:
        return None

    start_local = datetime(first.year, first.month, first.day)
    end_local = datetime(last.year, last.month, last.day) + timedelta(days=1)
    if kind == "day":
        times = _TIME_SPAN.search(low)
        if times is not None:
            t0 = _clock_minutes(times.group(1), is_end=False)
            t1 = _clock_minutes(times.group(2), is_end=True)
            if t0 is None or t1 is None or t1 <= t0:
                return None  # a time span that runs backwards or past midnight is not guessed at
            day0 = start_local
            start_local, end_local = day0 + timedelta(minutes=t0), day0 + timedelta(minutes=t1)
        else:
            at = _TIME_AT.search(low)
            t = _clock_minutes(at.group(1), is_end=False) if at is not None else None
            if t is not None:
                # "at noon": the readings either side of it, never the whole day.
                mid = start_local + timedelta(minutes=t)
                start_local, end_local = mid - timedelta(minutes=30), mid + timedelta(minutes=30)
    end_local -= timedelta(seconds=1)
    return (
        to_store(start_local, tz_name).strftime(STAMP),
        to_store(end_local, tz_name).strftime(STAMP),
    )


# ── A DAY NAMED WITHOUT A YEAR (CAVEAT-1616) ────────────────────────────────────────────────
#
# "How much energy did the solar panels produce on Wednesday?" read ten days of readings and said
# no daily figure exists; "was it higher or lower than on Thursday, 8 October?" resolved no window
# at all. A weekday, or a day and month, said about the PAST names one local day as plainly as
# "yesterday" does: the most recent such day. Every lane prints the window it read, so the reader
# sees which day was taken.
#
#   * the most recent PAST occurrence; "on <weekday>" on that weekday is today, "last <weekday>"
#     is never today;
#   * a weekday AND a day-month ("Monday 13 January") take the most recent year in which that date
#     fell on that weekday -- the reader has said which year without writing it;
#   * refused: a future question (a forecast's to read), a plural or recurring weekday ("on
#     Mondays", "every Monday", a pattern), an open interval ("since Monday"), a date naming a
#     thing ("the Wednesday meeting"), two named days (a comparison: each half resolves alone),
#     "this <weekday>" still ahead this week, and the month "May" without a year (a verb as often).

_WEEKDAY_NUM = {
    "monday": 0, "tuesday": 1, "wednesday": 2, "thursday": 3,
    "friday": 4, "saturday": 5, "sunday": 6,
}  # fmt: skip
_NAMED_WEEKDAY_RE = re.compile(
    r"\b(?:(?P<rel>last|this\s+past|past|this|on|for|from)\s+)?(?:the\s+)?"
    r"(?P<wd>monday|tuesday|wednesday|thursday|friday|saturday|sunday)(?P<plural>s)?\b"
)
_NOYEAR_MON = (
    r"(jan(?:uary)?|feb(?:ruary)?|mar(?:ch)?|apr(?:il)?|june?|july?|aug(?:ust)?|"
    r"sep(?:t(?:ember)?)?|oct(?:ober)?|nov(?:ember)?|dec(?:ember)?)\.?"
)
_NO_YEAR_AFTER = r"(?!,?\s+(?:19|20)\d{2})(?![\d.:])"
_DAY_DF_NOYEAR = re.compile(
    rf"(?<![\d.:])\b(\d{{1,2}}){_ORD}\s+(?:of\s+)?{_NOYEAR_MON}\b{_NO_YEAR_AFTER}"
)
_DAY_MF_NOYEAR = re.compile(rf"\b{_NOYEAR_MON}\s+(\d{{1,2}}){_ORD}\b{_NO_YEAR_AFTER}")
#: Future, and availability: "is room 2.13 free on Monday?" asks about the coming Monday, and the
#: events lane reads its own period for bookings.
_FUTURE_DAY_RE = re.compile(
    r"\b(?:will|going\s+to|tomorrow|next|forecast|predict\w*|expected|upcoming|coming|"
    r"free|available|availability|book|booking|reserve|reservation)\b"
)
_RECURRING_RE = re.compile(r"\b(?:every|each|usually|typically|normally|on\s+average)\b")
_NOYEAR_OPEN_BEFORE = re.compile(
    r"\b(?:since|after|before|until|till|by|as\s+of|starting|beginning)\s+(?:the\s+)?(?:on\s+)?$"
)


def _local_date_bounds(low: str, day: date, tz_name: Optional[str]) -> Optional[Tuple[str, str]]:
    """One local day as store-clock bounds, narrowed by a clock time the text writes out."""
    start_local = datetime(day.year, day.month, day.day)
    end_local = start_local + timedelta(days=1)
    times = _TIME_SPAN.search(low)
    if times is not None:
        t0 = _clock_minutes(times.group(1), is_end=False)
        t1 = _clock_minutes(times.group(2), is_end=True)
        if t0 is None or t1 is None or t1 <= t0:
            return None
        start_local, end_local = (
            start_local + timedelta(minutes=t0),
            start_local + timedelta(minutes=t1),
        )
    else:
        at = _TIME_AT.search(low)
        t = _clock_minutes(at.group(1), is_end=False) if at is not None else None
        if t is not None:
            mid = start_local + timedelta(minutes=t)
            start_local, end_local = mid - timedelta(minutes=30), mid + timedelta(minutes=30)
    end_local -= timedelta(seconds=1)
    return (
        to_store(start_local, tz_name).strftime(STAMP),
        to_store(end_local, tz_name).strftime(STAMP),
    )


def named_date_bounds(
    text: str, tz_name: Optional[str] = None, now: Optional[datetime] = None
) -> Optional[Tuple[str, str]]:
    """Store-clock bounds of a day named without a year ("on Wednesday", "8 October"), or None."""
    low = (text or "").lower()
    if not low or _FUTURE_DAY_RE.search(low) or _RECURRING_RE.search(low):
        return None
    today = (now or local_now(tz_name)).date()

    weekdays = [m for m in _NAMED_WEEKDAY_RE.finditer(low)]
    dated: List[Tuple[int, int, int, int]] = []  # (start, end, day, month)
    taken: List[Tuple[int, int]] = []
    for rx, dm in ((_DAY_DF_NOYEAR, True), (_DAY_MF_NOYEAR, False)):
        for m in rx.finditer(low):
            if any(not (m.end() <= s or m.start() >= e) for s, e in taken):
                continue
            d, mon = (m.group(1), m.group(2)) if dm else (m.group(2), m.group(1))
            day_n = int(d)
            if not 1 <= day_n <= 31:
                continue
            dated.append((m.start(), m.end(), day_n, _month_of(mon)))
            taken.append((m.start(), m.end()))
    if len(dated) > 1 or len(weekdays) > 1:
        return None  # two named days are a comparison: each half resolves on its own
    if any(w.group("plural") for w in weekdays):
        return None  # "on Mondays": a recurring day, not one day
    # On the weekday WORD, so "the Wednesday meeting" shows its article to the attributive test.
    anchor = dated[0][0] if dated else (weekdays[0].start("wd") if weekdays else None)
    if anchor is None:
        return None
    before = low[max(0, anchor - 40) : anchor]
    if _NOYEAR_OPEN_BEFORE.search(before):
        return None  # "since Monday": one end of an open interval
    if _ATTRIBUTIVE.search(before) and not _TEMPORAL_ARTICLE.search(before):
        return None  # "the Wednesday meeting": a date naming a thing

    wd = weekdays[0] if weekdays else None
    wd_num = _WEEKDAY_NUM[wd.group("wd")] if wd else None
    if dated:
        _s, _e, day_n, mon = dated[0]
        for back in range(0, 8):
            y = today.year - back
            try:
                cand = date(y, mon, day_n)
            except ValueError:
                continue  # 29 February in a year that has none
            if cand > today:
                continue
            if wd_num is not None and cand.weekday() != wd_num:
                continue
            return _local_date_bounds(low, cand, tz_name)
        return None
    rel = re.sub(r"\s+", " ", (wd.group("rel") or "")).strip()
    back = (today.weekday() - wd_num) % 7
    if rel == "last" and back == 0:
        back = 7
    if rel == "this" and wd_num > today.weekday():
        return None  # "this Friday" on a Wednesday is still ahead
    return _local_date_bounds(low, today - timedelta(days=back), tz_name)


# ── TWO PERIODS SIDE BY SIDE (v2 compound questions, shape C4) ──────────────────────────────
#
# "This week against last week", "today versus yesterday", "weekdays against weekends". Each is
# TWO intervals, and each is resolved HERE, from the question's own words, by the same arithmetic
# the single-period functions above use -- never by a second parser and never from dates a model
# wrote. A question whose periods are in dispute ("recently", "the busy season") gets no periods.

#: Weekday and weekend, as words. A day-type comparison splits ONE window into its local
#: weekdays and its local weekend days.
_WEEKDAY_RE = re.compile(r"\bweek\s*-?\s*days?\b")
_WEEKEND_RE = re.compile(r"\bweek\s*-?\s*ends?\b")

#: The window a weekday/weekend comparison reads when the question names none: the last two
#: whole weeks of local days ending today. Declared in the answer, never silent.
DEFAULT_DAY_TYPE_DAYS = 14


def day_bounds(
    days_back: int, tz_name: Optional[str] = None, now: Optional[datetime] = None
) -> Tuple[str, str]:
    """Store-clock bounds of the local calendar day ``days_back`` days before today (inclusive)."""
    if now is None:
        now = local_now(tz_name)
    day = (now - timedelta(days=days_back)).date()
    start = datetime(day.year, day.month, day.day, 0, 0, 0)
    end = datetime(day.year, day.month, day.day, 23, 59, 59)
    return to_store(start, tz_name).strftime(STAMP), to_store(end, tz_name).strftime(STAMP)


def period_bounds(
    unit: str, back: int, tz_name: Optional[str] = None, now: Optional[datetime] = None
) -> Tuple[str, str]:
    """Store-clock bounds of ONE calendar period: the ``unit`` ``back`` whole units before the
    one in progress (0 = this week / month / quarter / year). The same arithmetic as
    :func:`calendar_period_bounds`, without its two-period margin -- a period compared with
    another is read whole, each on its own."""
    if now is None:
        now = local_now(tz_name)
    first = _unit_start(now.date(), unit, back)
    last = _unit_end(first, unit)
    start_local = datetime(first.year, first.month, first.day, 0, 0, 0)
    end_local = datetime(last.year, last.month, last.day, 23, 59, 59)
    return (
        to_store(start_local, tz_name).strftime(STAMP),
        to_store(end_local, tz_name).strftime(STAMP),
    )


def named_days(text: str) -> List[str]:
    """Every calendar-day phrase the text names, in the order it names them.

    The longest phrase claims its words first, so "the day before yesterday" is never ALSO read as
    "yesterday" (the shadowing BUG-1437 was). Used to find the two days of "today versus
    yesterday"; one named day is :func:`calendar_day_bounds`' business.
    """
    low = (text or "").lower()
    taken: List[Tuple[int, int]] = []
    found: List[Tuple[int, str]] = []
    for word in sorted(_CALENDAR_DAYS, key=len, reverse=True):
        for match in re.finditer(rf"\b{re.escape(word)}\b", low):
            span = (match.start(), match.end())
            if any(span[0] < end and start < span[1] for start, end in taken):
                continue
            taken.append(span)
            found.append((span[0], word))
    return [word for _, word in sorted(found)]


def local_day_windows(
    start: str, end: str, tz_name: Optional[str] = None
) -> List[Tuple[str, str, int]]:
    """The building-local calendar days a store-clock interval covers.

    One ``(start, end, iso_weekday)`` per local day, its bounds on the stores' clock and clipped to
    the interval, so a weekday/weekend split is decided by the OCCUPANTS' calendar (Monday = 1 ...
    Sunday = 7) and every reading is still compared against UTC stamps.
    """
    try:
        lo = datetime.strptime(str(start)[:19], STAMP)
        hi = datetime.strptime(str(end)[:19], STAMP)
    except (TypeError, ValueError):
        return []
    out: List[Tuple[str, str, int]] = []
    day = to_local(lo, tz_name).date()
    last = to_local(hi, tz_name).date()
    while day <= last:
        day_start = to_store(datetime(day.year, day.month, day.day, 0, 0, 0), tz_name)
        day_end = to_store(datetime(day.year, day.month, day.day, 23, 59, 59), tz_name)
        a, b = max(lo, day_start), min(hi, day_end)
        if a <= b:
            out.append((a.strftime(STAMP), b.strftime(STAMP), day.isoweekday()))
        day += timedelta(days=1)
    return out


def compared_periods(
    text: str, tz_name: Optional[str] = None, now: Optional[datetime] = None
) -> Tuple[List[Dict[str, Any]], str]:
    """The TWO periods a comparison question names: ``([period, period], "")`` or ``([], why)``.

    Each period is ``{"label", "start", "end", "day_type", "partial"}`` with store-clock bounds.
    Calendar periods come back EARLIER FIRST, so a change is always "later minus earlier";
    weekdays come before weekends. Resolved, in this order:

    * weekdays against weekends -- over the one calendar period the question names ("this
      month"), or the last :data:`DEFAULT_DAY_TYPE_DAYS` local days when it names none. The
      weekend is Saturday and Sunday (ISO 8601 days 6 and 7) of the building's own calendar;
    * this and last week / month / quarter / year;
    * two named days ("today versus yesterday").

    Anything else returns a reason instead of a guess.
    """
    low = (text or "").lower()
    if now is None:
        now = local_now(tz_name)
    if _WEEKDAY_RE.search(low) and _WEEKEND_RE.search(low):
        named = named_period(low)
        if named is not None and len(named[1]) == 1:
            unit, (back,) = named
            start, end = period_bounds(unit, back, tz_name, now)
            label = f"{'this' if back == 0 else 'last'} {unit}"
        elif named is not None or named_day(low) is not None:
            return [], "weekdays and weekends need a window of more than one day or period"
        else:
            first = (now - timedelta(days=DEFAULT_DAY_TYPE_DAYS - 1)).date()
            start = to_store(datetime(first.year, first.month, first.day), tz_name).strftime(STAMP)
            end = to_store(now, tz_name).strftime(STAMP)
            label = f"the last {DEFAULT_DAY_TYPE_DAYS} days"
        return [
            {
                "label": f"weekdays ({label})",
                "start": start,
                "end": end,
                "day_type": "weekday",
                "partial": False,
            },
            {
                "label": f"weekends ({label})",
                "start": start,
                "end": end,
                "day_type": "weekend",
                "partial": False,
            },
        ], ""
    named = named_period(low)
    if named is not None and sorted(named[1]) == [0, 1]:
        unit = named[0]
        out: List[Dict[str, Any]] = []
        for back in (1, 0):
            start, end = period_bounds(unit, back, tz_name, now)
            out.append(
                {
                    "label": f"{'this' if back == 0 else 'last'} {unit}",
                    "start": start,
                    "end": end,
                    "day_type": None,
                    # the period in progress has only the readings that exist so far
                    "partial": back == 0,
                }
            )
        return out, ""
    days = list(dict.fromkeys(_CALENDAR_DAYS[word] for word in named_days(low)))
    if len(days) == 2:
        out = []
        for back in sorted(days, reverse=True):
            start, end = day_bounds(back, tz_name, now)
            label = _DAYS_BACK_TO_PHRASE[back]
            out.append(
                {
                    "label": label,
                    "start": start,
                    "end": end,
                    "day_type": None,
                    "partial": back == 0,
                }
            )
        return out, ""
    return [], (
        "the question does not name two periods that can be read exactly -- for example this "
        "week and last week, today and yesterday, or weekdays and weekends"
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
