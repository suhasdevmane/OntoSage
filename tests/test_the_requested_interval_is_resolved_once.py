# -*- coding: utf-8 -*-
"""V12-08 — the requested interval is resolved ONCE, and nothing downstream re-derives it.

    "Resolve the requested interval once, and forbid every downstream re-derivation."
                                                   — architecture review, T05

WHAT WAS ACTUALLY WRONG, MEASURED 2026-09-12
--------------------------------------------
BUG-480 fixed "yesterday" in `dialogue_agent` in September. The fix was correct and it was a
POINT REPAIR: two other lanes kept their own answer to the same question, and both had the
error the fix exists to remove.

  sql_agent   `yesterday = now - timedelta(days=1)` in the prompt hint — a duration, so a
              question asked at 16:00 named "yesterday at 16:00"
  ARBITER     `_PAST_WINDOW_HOURS` mapped BOTH "yesterday" and "today" to 24.0 hours, and
              `fetch.py` turned either into `utcnow() - 24h` with NO upper bound

The ARBITER pair is the sharper failure. The two commonest time words in the 6,117-question
corpus named the SAME interval, so a deliberation about yesterday was computed over a
rolling window ending now — half of it today — in UTC rather than the building's zone.
Every figure in such an answer is real and internally consistent, which is why a test suite
of 5,556 passing tests never noticed.

WHAT THESE TESTS PIN
--------------------
  A07  the clock is frozen, "yesterday" and "today" are seeded to DIFFERENT values, and the
       expectation is built here from plain date arithmetic — never by calling the
       production resolver, which would let a wrong resolver certify itself
  A08  midnight and a real DST transition, in the configured zone, proving the answer is
       not a 24-hour subtraction
  the guard  the formatting layer constructs no window at all, and no module anywhere maps
       a named day to a number of hours
"""

from __future__ import annotations

import ast
import asyncio
import re
from datetime import date, datetime, timedelta
from pathlib import Path
from typing import Any, Dict, List, Optional

import pytest

pytestmark = pytest.mark.unit

from orchestrator.services.deliberation.candidates import Candidate  # noqa: E402
from orchestrator.services.deliberation.compiler import (  # noqa: E402
    _fold_named_calendar_day,
    match_past_window,
)
from orchestrator.services.deliberation.cqir import TimeBasis, TimeSpec  # noqa: E402
from orchestrator.services.deliberation.fetch import fetch_series  # noqa: E402
from orchestrator.services.requested_interval import (  # noqa: E402
    calendar_day_bounds,
    interval_hours,
    local_now,
)

REPO = Path(__file__).resolve().parent.parent

#: A Saturday afternoon. Chosen so "yesterday" is a different DATE from "today" and neither
#: is a month or year boundary — the boundaries get their own cases below.
FROZEN = datetime(2026, 9, 12, 16, 0, 0)


# ── a store that answers with the day it was asked about ─────────────────────


class _RecordingAdapter:
    """Returns one row per day covered by the window, so a wrong window shows as a wrong
    value rather than as no data. Also keeps every (start, end) it was handed."""

    def __init__(self) -> None:
        self.calls: List[Dict[str, Optional[str]]] = []

    def build_timeseries_query(self, uuids, column, start, end, limit=None):
        self.calls.append({"start": start, "end": end, "uuids": list(uuids)})
        return {"start": start, "end": end, "uuids": list(uuids)}

    async def execute_query(self, sql):
        start = datetime.strptime(str(sql["start"])[:19], "%Y-%m-%d %H:%M:%S")
        end = (
            datetime.strptime(str(sql["end"])[:19], "%Y-%m-%d %H:%M:%S")
            if sql["end"]
            else FROZEN
        )
        # one reading at noon on every day the window touches; its VALUE encodes the date,
        # so a window covering the wrong day cannot produce the right number by luck
        rows = []
        day = start.date()
        while day <= end.date():
            noon = datetime(day.year, day.month, day.day, 12, 0, 0)
            if start <= noon <= end:
                for u in sql["uuids"]:
                    rows.append(
                        {
                            "uuid": u,
                            "timestamp": noon.strftime("%Y-%m-%d %H:%M:%S"),
                            "value": float(day.toordinal()),
                        }
                    )
            day += timedelta(days=1)
        return type("R", (), {"success": True, "data": rows, "error": None})()


def _one_candidate() -> List[Candidate]:
    return [
        Candidate(
            space_iri="bldg:RoomA",
            label="Room A",
            floor="5",
            sensors={"co2": {"uuid": "uuid-a", "stored_at": "bldg:sensor_data"}},
        )
    ]


def _fetch(spec: TimeSpec, adapter: _RecordingAdapter):
    # `asyncio.run`, not `get_event_loop().run_until_complete`. The latter passed when this
    # file ran alone and raised "there is no current event loop" inside the full suite,
    # where something else had already closed it — a test that only works in the context it
    # was written in is the measurement apparatus being wrong again.
    return asyncio.run(
        fetch_series(
            _one_candidate(),
            ["co2"],
            window_hours=float(spec.window_hours or 24.0),
            adapter_getter=lambda _table: adapter,
            start=spec.resolved_start,
            end=spec.resolved_end,
            now=FROZEN,
        )
    )


# ── A07: the clock is frozen and the two days are seeded differently ─────────


def test_A07_yesterday_and_today_are_different_intervals():
    """The defect in one assertion: both compiled to 24.0 hours, so they were the same."""
    y, t = TimeSpec(), TimeSpec()
    assert _fold_named_calendar_day(y, "occupancy yesterday", now=FROZEN) is True
    assert _fold_named_calendar_day(t, "occupancy today", now=FROZEN) is True
    assert (y.resolved_start, y.resolved_end) != (t.resolved_start, t.resolved_end)


def test_A07_the_bounds_match_an_expectation_computed_here():
    """The expectation is built from `date` arithmetic in this test, NOT by calling the
    production resolver. A resolver asked to confirm itself agrees with itself."""
    spec = TimeSpec()
    _fold_named_calendar_day(spec, "which rooms were busiest yesterday", now=FROZEN)

    expected_day = date(2026, 9, 11)  # the day before FROZEN, written out
    assert spec.resolved_start == f"{expected_day:%Y-%m-%d} 00:00:00"
    assert spec.resolved_end == f"{expected_day:%Y-%m-%d} 23:59:59"


def test_A07_the_two_days_retrieve_different_readings():
    """End to end through the fetch layer: the values are date-encoded, so a window over
    the wrong day yields the wrong number rather than nothing."""
    y, t = TimeSpec(), TimeSpec()
    _fold_named_calendar_day(y, "co2 yesterday", now=FROZEN)
    _fold_named_calendar_day(t, "co2 today", now=FROZEN)

    adapter = _RecordingAdapter()
    y_series = _fetch(y, adapter)["uuid-a"]
    t_series = _fetch(t, adapter)["uuid-a"]

    assert [v for _, v in y_series] == [float(date(2026, 9, 11).toordinal())]
    assert [v for _, v in t_series] == [float(date(2026, 9, 12).toordinal())]
    assert y_series != t_series, "two different days returned the same readings"


def test_A07_the_window_handed_to_the_store_has_BOTH_ends():
    """`fetch.py` passed `None` as the end bound, so every window ran to the present.

    A "yesterday" query with no upper bound is not a narrower version of the right answer;
    it is a different question that happens to contain it.
    """
    spec = TimeSpec()
    _fold_named_calendar_day(spec, "co2 yesterday", now=FROZEN)
    adapter = _RecordingAdapter()
    _fetch(spec, adapter)

    call = adapter.calls[-1]
    assert call["end"] is not None, "the store was asked for everything since the start"
    assert call["start"] == "2026-09-11 00:00:00"
    assert call["end"] == "2026-09-11 23:59:59"


def test_A07_the_interval_reaches_the_plan_fingerprint():
    """Two questions naming different days reasoned over different evidence. A fingerprint
    that cannot tell them apart would certify them identical — which is what it did."""
    from orchestrator.services.deliberation.cqir import CQIR, DecisionKind

    def _ir(word):
        ir = CQIR(decision=DecisionKind.RANK_ALL, raw_query=f"co2 {word}")
        _fold_named_calendar_day(ir.time, f"co2 {word}", now=FROZEN)
        return ir

    assert _ir("yesterday").plan_fingerprint() != _ir("today").plan_fingerprint()


def test_A07_the_same_question_twice_fingerprints_identically():
    """The other half of the same property: adding the interval must not make a repeat of
    one question look like a different plan."""
    from orchestrator.services.deliberation.cqir import CQIR, DecisionKind

    def _ir():
        ir = CQIR(decision=DecisionKind.RANK_ALL, raw_query="co2 yesterday")
        _fold_named_calendar_day(ir.time, "co2 yesterday", now=FROZEN)
        return ir

    assert _ir().plan_fingerprint() == _ir().plan_fingerprint()


# ── A08: midnight, and a real DST transition, in the configured zone ─────────


def test_A08_just_after_midnight_yesterday_is_still_the_whole_previous_day():
    """00:30 is where a duration and a date disagree most visibly: `now - 24h` names
    yesterday at 00:30 and covers 23.5 hours of a day that has barely started."""
    just_after_midnight = datetime(2026, 9, 12, 0, 30, 0)
    spec = TimeSpec()
    _fold_named_calendar_day(spec, "co2 yesterday", now=just_after_midnight)

    assert spec.resolved_start == "2026-09-11 00:00:00"
    assert spec.resolved_end == "2026-09-11 23:59:59"

    rolling = (just_after_midnight - timedelta(hours=24)).strftime("%Y-%m-%d %H:%M:%S")
    assert spec.resolved_start != rolling, "this is the 24-hour subtraction, not a date"


@pytest.mark.parametrize(
    "asked_at, previous_day, real_hours",
    [
        # Europe/London falls back at 02:00 on 2026-10-25 — a 25-hour day
        (datetime(2026, 10, 26, 10, 0, 0), date(2026, 10, 25), 25),
        # ...and springs forward at 01:00 on 2027-03-28 — a 23-hour day
        (datetime(2027, 3, 29, 10, 0, 0), date(2027, 3, 28), 23),
    ],
)
def test_A08_a_dst_day_is_still_that_whole_day(asked_at, previous_day, real_hours):
    """A DST day is not 24 hours long, so a 24-hour subtraction cannot name one.

    The DAY is the building's local day; its bounds are then converted to the stores'
    clock, which is UTC (corrected 2026-09-15 — this test asserted local wall-clock strings
    on the false premise that the stores were local). So the span between the two UTC
    bounds is the day's REAL length: 25 hours on the fall-back day, 23 on spring-forward.

    The expectation is built here with zoneinfo directly, not by calling the resolver.
    """
    from zoneinfo import ZoneInfo

    spec = TimeSpec()
    _fold_named_calendar_day(spec, "co2 yesterday", tz_name="Europe/London", now=asked_at)

    zone, utc = ZoneInfo("Europe/London"), ZoneInfo("UTC")
    exp_start = datetime(previous_day.year, previous_day.month, previous_day.day, tzinfo=zone)
    exp_end = datetime(
        previous_day.year, previous_day.month, previous_day.day, 23, 59, 59, tzinfo=zone
    )
    fmt = "%Y-%m-%d %H:%M:%S"
    assert spec.resolved_start == exp_start.astimezone(utc).strftime(fmt)
    assert spec.resolved_end == exp_end.astimezone(utc).strftime(fmt)

    rolling = (asked_at - timedelta(hours=24)).strftime(fmt)
    assert spec.resolved_start != rolling
    # one second short of the real day length, because the end bound is inclusive
    assert abs(interval_hours(spec.resolved_start, spec.resolved_end) - real_hours) < 0.01


def test_A08_the_zone_is_the_configured_one_not_the_hosts():
    """`calendar_day_bounds` reads the building's zone. Two zones far enough apart name
    different dates for the same instant, which is the whole reason the zone is a parameter.

    Asked at 22:00 UTC, it is already tomorrow in Tokyo — so "yesterday" is a different
    date depending on where the building is.
    """
    instant_utc = datetime(2026, 9, 12, 22, 0, 0)

    from zoneinfo import ZoneInfo

    in_utc = instant_utc.replace(tzinfo=ZoneInfo("UTC"))
    tokyo = in_utc.astimezone(ZoneInfo("Asia/Tokyo")).replace(tzinfo=None)
    london = in_utc.astimezone(ZoneInfo("Europe/London")).replace(tzinfo=None)

    assert calendar_day_bounds("yesterday", now=tokyo)[0] == "2026-09-12 00:00:00"
    assert calendar_day_bounds("yesterday", now=london)[0] == "2026-09-11 00:00:00"


def test_A08_local_now_is_local_and_not_utc():
    """The `utcnow()` this replaces was compared against LOCAL stamps from the stores."""
    utc = local_now("UTC")
    tokyo = local_now("Asia/Tokyo")
    assert abs((tokyo - utc).total_seconds() / 3600.0 - 9.0) < 0.1
    assert utc.tzinfo is None and tokyo.tzinfo is None, "naive, like the stamps in the stores"


def test_A08_an_unknown_zone_falls_back_instead_of_raising():
    """The zone comes from per-building config and may be anything."""
    assert local_now("Not/AZone") is not None
    assert calendar_day_bounds("yesterday", tz_name="Not/AZone") is not None


# ── the guard the acceptance asks for ────────────────────────────────────────

#: Where an answer is turned into words. Nothing here may construct a time window: by the
#: time these run the interval has been resolved, fetched against and recorded, and a
#: second opinion about it can only disagree.
_FORMATTER_MODULES = (
    "orchestrator/workflow/_orchestrator.py",
    "orchestrator/agents/report_agent.py",
    "orchestrator/services/deliberation/dossier.py",
    "orchestrator/services/evidence/assemble.py",
)

_DAY_WORD = re.compile(r"\b(yesterday|today)\b", re.IGNORECASE)


def _functions(path: Path):
    tree = ast.parse(path.read_text(encoding="utf-8"))
    for node in ast.walk(tree):
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            yield node


@pytest.mark.parametrize("module", _FORMATTER_MODULES)
def test_no_formatter_constructs_a_time_window(module):
    """BUG-478 in one rule: a report headed "Yesterday" described today because the
    formatter re-derived the window the retriever had already resolved.

    `timedelta` is the tell. A window cannot be built without a duration, and a formatter
    has no business holding one — it reads `time_range`, `resolved_start`/`resolved_end`,
    or the timestamp on the evidence row.
    """
    offenders = []
    for fn in _functions(REPO / module):
        for sub in ast.walk(fn):
            if isinstance(sub, ast.Call) and getattr(sub.func, "id", None) == "timedelta":
                offenders.append(f"{module}:{sub.lineno} in {fn.name}()")
    assert not offenders, "a formatter is building its own window: " + "; ".join(offenders)


@pytest.mark.parametrize("module", _FORMATTER_MODULES)
def test_no_formatter_reads_a_clock_next_to_a_named_day(module):
    """The other shape of the same defect: a function that knows the word "yesterday" and
    also knows what time it is will eventually be asked to reconcile them."""
    offenders = []
    for fn in _functions(REPO / module):
        says_day = any(
            isinstance(s, ast.Constant) and isinstance(s.value, str) and _DAY_WORD.search(s.value)
            for s in ast.walk(fn)
        )
        if not says_day:
            continue
        reads_clock = any(
            isinstance(s, ast.Call) and getattr(s.func, "attr", "") in ("now", "utcnow", "today")
            for s in ast.walk(fn)
        )
        if reads_clock:
            offenders.append(f"{module}:{fn.lineno} {fn.name}()")
    assert not offenders, "a formatter is re-deriving a named day: " + "; ".join(offenders)


def test_no_module_maps_a_named_day_to_a_number_of_hours():
    """The ARBITER defect, stated as a rule that cannot be satisfied by accident.

    `(r"\\byesterday\\b", 24.0)` and `(r"\\btoday\\b", 24.0)` sat in a tuple of
    (pattern, hours) pairs. A DATE has no hours-of-history answer, and giving both the same
    one meant the lane could not distinguish the two most common time words in the corpus.
    """
    offenders = []
    for path in sorted((REPO / "orchestrator").rglob("*.py")):
        if path.name == "requested_interval.py":
            continue
        try:
            tree = ast.parse(path.read_text(encoding="utf-8"))
        except SyntaxError:  # pragma: no cover - a broken file is another test's problem
            continue
        for node in ast.walk(tree):
            if not isinstance(node, (ast.Tuple, ast.List)):
                continue
            elts = node.elts
            if len(elts) != 2:
                continue
            first, second = elts
            names_day = (
                isinstance(first, ast.Constant)
                and isinstance(first.value, str)
                and _DAY_WORD.search(first.value)
            )
            is_number = isinstance(second, ast.Constant) and isinstance(
                second.value, (int, float)
            )
            if names_day and is_number:
                offenders.append(
                    f"{path.relative_to(REPO)}:{node.lineno} maps a named day to {second.value}"
                )
    assert not offenders, "; ".join(offenders)


def test_the_hours_table_itself_refuses_a_named_day():
    """Belt and braces on the rule above, at the behaviour rather than the source."""
    assert match_past_window("occupancy yesterday") is None
    assert match_past_window("occupancy today") is None
    assert match_past_window("occupancy over the past 6 hours") == 6.0


def test_the_fetch_layer_compares_with_the_stores_clock():
    """The stores are UTC (BUG-403; re-measured 2026-09-15 from a +00:00 session).

    This test used to assert the OPPOSITE — that fetch.py read the building's local clock —
    because it was written on a measurement taken through a SYSTEM-zone session, in which a
    TIMESTAMP column is converted to local time on read. Every window built that way started
    an hour late under BST. The fetch fallback must use `store_now()` and never a local clock.
    """
    path = REPO / "orchestrator/services/deliberation/fetch.py"
    tree = ast.parse(path.read_text(encoding="utf-8"))
    called = {
        (getattr(n.func, "id", "") or getattr(n.func, "attr", ""))
        for n in ast.walk(tree)
        if isinstance(n, ast.Call)
    }
    assert "store_now" in called, "the duration fallback no longer uses the stores' clock"
    for local in ("local_now", "building_local_now"):
        assert local not in called, f"fetch.py compares stored rows with {local}()"


def test_store_comparisons_never_use_the_local_clock():
    """The three sites moved to local time on 2026-09-12 (booking overlap, PDP data age,
    recheck freshness) all compare against stored rows. `building_local_now` is for display."""
    for rel in (
        "orchestrator/services/deliberation/plan_executor.py",
        "orchestrator/workflow/_orchestrator.py",
    ):
        tree = ast.parse((REPO / rel).read_text(encoding="utf-8"))
        calls = [
            n.lineno
            for n in ast.walk(tree)
            if isinstance(n, ast.Call)
            and (getattr(n.func, "id", "") or getattr(n.func, "attr", "")) == "building_local_now"
        ]
        assert not calls, f"{rel} compares stored data with the local clock at lines {calls}"


def test_the_resolved_interval_is_carried_on_the_spec_not_recomputed():
    """The acceptance's first clause: it is CARRIED, so a consumer can read it."""
    spec = TimeSpec(basis=TimeBasis.NOW)
    assert spec.is_resolved_interval is False
    _fold_named_calendar_day(spec, "co2 yesterday", now=FROZEN)
    assert spec.is_resolved_interval is True
    assert spec.resolved_start and spec.resolved_end


def test_the_executor_passes_the_resolved_interval_through_to_the_fetch():
    """A resolved interval nothing reads is the V6-T10 failure one layer down."""
    import inspect

    from orchestrator.services.deliberation import plan_executor

    src = inspect.getsource(plan_executor.execute)
    assert "is_resolved_interval" in src, "the executor never checks for a resolved interval"
    assert "start=fetch_start" in src and "end=fetch_end" in src, (
        "the resolved interval is computed and then not handed to the store"
    )


def test_every_lane_answers_when_is_yesterday_from_the_same_function():
    """Three lanes had three answers. Two of them were the answer the third was fixed to
    stop giving, and nothing in the suite could see the disagreement."""
    import inspect

    from orchestrator.agents import dialogue_agent, sql_agent
    from orchestrator.services.deliberation import compiler

    for module in (dialogue_agent, sql_agent, compiler):
        src = inspect.getsource(module)
        assert "requested_interval" in src or "calendar_day_bounds" in src, (
            f"{module.__name__} does not use the shared resolver"
        )


def test_the_bus_carries_one_interval_under_three_names_and_they_agree():
    """`start_date`, `end_date` and `time_range` all travel on the bus and all describe the
    same fact. That is a duplication rather than a re-derivation — but it is the shape a
    re-derivation hides in, so it is pinned: whatever the compile produced, the named-day
    override must update ALL THREE or a downstream reader gets the pre-override window.
    """
    import json

    from orchestrator.agents.dialogue_agent import DialogueAgent

    agent = DialogueAgent.__new__(DialogueAgent)
    payload = json.dumps(
        {
            "intent": "sensor_data",
            "entities": [],
            "required_analytics": [],
            "explanation": "test",
            # what a compiler wobble looks like: a rolling window against a named day
            "time_range": {"start": "now-24h", "end": None},
        }
    )
    out = agent._parse_llm_response(payload, "what was the CO2 in room 5.01 yesterday", None)

    assert out["time_range"]["start"] == out["start_date"]
    assert out["time_range"]["end"] == out["end_date"]
    # A whole day, whatever zone the test machine's building is in: the bounds are the local
    # day converted to UTC, so they need not END in midnight strings — but they must be
    # exactly one day minus one second apart, which a rolling `now-24h` compile never is.
    span = interval_hours(out["start_date"], out["end_date"])
    assert span is not None and abs(span - (24 - 1 / 3600)) < 1.01, (
        "the rolling compile survived the override"
    )
    assert out["end_date"] != "None" and out["start_date"][11:] != out["end_date"][11:]


def test_the_resolver_names_no_building():
    """The day boundary comes from the building's own timezone, never a literal."""
    src = (REPO / "orchestrator/services/requested_interval.py").read_text(encoding="utf-8")
    for literal in ("bldg1", "bldg2", "bldg3", "abacws", "Europe/London"):
        assert literal.lower() not in src.lower(), f"{literal} is hardcoded in the resolver"


def _unused(_: Any) -> None:  # pragma: no cover - keeps the Any import honest
    return None
