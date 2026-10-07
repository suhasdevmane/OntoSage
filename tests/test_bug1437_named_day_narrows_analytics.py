"""BUG-1437: a named calendar day must bound the rows analytics reads.

"yesterday" and "the day before yesterday" returned a byte-identical analytics answer, because
(1) the resolver matched the bare word "yesterday" inside "the day before yesterday" and
resolved it one day back, and (2) the analytics lane computed over whatever rows it was handed
with no regard to the day the question named. These tests pin the resolver fix and the row
narrowing, offline, and show the two named days resolve to different store windows.
"""

from datetime import datetime, timedelta, timezone
from types import SimpleNamespace

import pytest

from orchestrator.services import requested_interval as ri

pytestmark = pytest.mark.unit

# Tuesday 2026-10-07 09:00, building wall clock. No zone, so local == store clock.
NOW = datetime(2026, 10, 7, 9, 0, 0)
YESTERDAY = ("2026-10-06 00:00:00", "2026-10-06 23:59:59")
DAY_BEFORE = ("2026-10-05 00:00:00", "2026-10-05 23:59:59")


@pytest.fixture(autouse=True)
def _no_building_zone(monkeypatch):
    """Pin the building zone to None so these tests do not depend on the active building."""
    monkeypatch.setattr(ri, "building_tz", lambda building_id=None: None)


def test_yesterday_resolves_to_the_previous_calendar_day():
    assert ri.calendar_day_bounds("energy use yesterday", None, now=NOW) == YESTERDAY


def test_the_day_before_yesterday_resolves_two_days_back_not_one():
    # Before the fix this returned YESTERDAY: the bare word matched inside the longer phrase.
    got = ri.calendar_day_bounds("energy use the day before yesterday", None, now=NOW)
    assert got == DAY_BEFORE


def test_the_two_named_days_resolve_to_different_store_windows():
    a = ri.calendar_day_bounds("How much energy did the building use yesterday?", None, now=NOW)
    b = ri.calendar_day_bounds(
        "How much energy did the building use the day before yesterday?", None, now=NOW
    )
    assert a is not None and b is not None
    assert a != b


def test_named_day_reports_the_longest_phrase_it_contains():
    # Label is the G7 key ("the day before yesterday"), which context_switch substitutes.
    assert ri.named_day("energy the day before yesterday") == "the day before yesterday"
    assert ri.named_day("energy yesterday") == "yesterday"
    assert ri.named_day("energy today") == "today"
    assert ri.named_day("energy last week") is None


def test_longer_phrase_does_not_leak_into_period_resolution():
    # named_period refuses any question that names a calendar day; the new phrase must not
    # make "the day before yesterday" look like a period.
    assert ri.named_period("energy the day before yesterday") is None


def _row(stamp, value=1.0):
    return {"timestamp": stamp, "value": value}


def test_rows_in_window_keeps_only_the_named_day():
    rows = [
        _row("2026-10-05 12:00:00", 5.0),  # day before yesterday
        _row("2026-10-06 12:00:00", 6.0),  # yesterday
        _row("2026-10-07 08:00:00", 7.0),  # today
    ]
    yesterday_only = ri.rows_in_window(rows, *YESTERDAY)
    assert [r["value"] for r in yesterday_only] == [6.0]
    day_before_only = ri.rows_in_window(rows, *DAY_BEFORE)
    assert [r["value"] for r in day_before_only] == [5.0]


def test_rows_in_window_is_inclusive_at_both_ends():
    rows = [_row("2026-10-06 00:00:00"), _row("2026-10-06 23:59:59"), _row("2026-10-07 00:00:00")]
    kept = ri.rows_in_window(rows, *YESTERDAY)
    assert len(kept) == 2


def test_rows_in_window_converts_aware_timestamps_to_utc_before_comparing():
    # 2026-10-06 23:30 at +01:00 is 22:30 UTC: still yesterday on the store clock.
    aware = datetime(2026, 10, 6, 23, 30, tzinfo=timezone(timedelta(hours=1)))
    kept = ri.rows_in_window([{"timestamp": aware, "value": 1}], *YESTERDAY)
    assert len(kept) == 1


def test_rows_in_window_returns_none_when_no_row_has_a_readable_time():
    rows = [{"value": 1}, {"timestamp": "not a time", "value": 2}]
    assert ri.rows_in_window(rows, *YESTERDAY) is None


def test_restrict_leaves_data_alone_when_no_day_is_named():
    data = {"data": [_row("2026-10-01 12:00:00")]}
    out, bounds, checked = ri.restrict_to_named_day(data, "energy this building uses", None, NOW)
    assert out is data and bounds is None and checked is True


def test_restrict_narrows_a_dict_payload_and_reports_the_window():
    data = {"data": [_row("2026-10-05 12:00:00"), _row("2026-10-06 12:00:00")], "metadata": {}}
    out, bounds, checked = ri.restrict_to_named_day(data, "yesterday", None, NOW)
    assert bounds == YESTERDAY and checked is True
    assert len(out["data"]) == 1 and out["metadata"] == {}


def test_restrict_fails_open_and_says_so_when_rows_cannot_be_timed():
    data = {"data": [{"value": 1}]}
    out, bounds, checked = ri.restrict_to_named_day(data, "yesterday", None, NOW)
    assert out is data and bounds == YESTERDAY and checked is False


def test_restrict_accepts_a_bare_row_list():
    rows = [_row("2026-10-06 01:00:00"), _row("2026-10-05 01:00:00")]
    out, _, _ = ri.restrict_to_named_day(rows, "the day before yesterday", None, NOW)
    assert [r["timestamp"] for r in out] == ["2026-10-05 01:00:00"]


def _analytics_agent(monkeypatch):
    """An AnalyticsAgent with the bus-file write stubbed out, so no file is created."""
    from orchestrator.agents import analytics_agent as aa

    monkeypatch.setattr(aa.AnalyticsAgent, "_write_turn_data", staticmethod(lambda *a, **k: True))
    return aa.AnalyticsAgent()


@pytest.mark.asyncio
async def test_analytics_no_data_names_the_day_asked_about(monkeypatch):
    """The rows exist only for yesterday; asked about the day before, analytics must not
    compute over yesterday's rows. It declines and names the day it was asked about."""
    agent = _analytics_agent(monkeypatch)
    # The SQL lane succeeded and returned rows; the narrowing is what leaves none for the day.
    state = SimpleNamespace(
        building_id=None, intermediate_results={"sql_result": {"success": True}}
    )
    data = {"data": [_row("2026-10-06 12:00:00", 42.0)]}

    # The named day is resolved against the pinned NOW, not the wall clock.
    real = ri.calendar_day_bounds
    monkeypatch.setattr(
        ri,
        "calendar_day_bounds",
        lambda text, tz=None, now=None: real(text, tz, now=NOW),
    )

    result = await agent.analyze(
        state,
        "How much energy did the building use the day before yesterday?",
        data,
        {},
        "unit_test_data.json",
    )
    assert result["success"] is False
    assert result["error"] == "no_data_available"
    assert "05 Oct 2026" in result["formatted_response"]
    assert "42" not in result["formatted_response"]


def test_the_analytics_node_and_agent_both_import_the_one_narrowing_function():
    """A comment saying 'use the resolver' is not enforceable; an import is."""
    from pathlib import Path

    agent_src = Path("orchestrator/agents/analytics_agent.py").read_text(encoding="utf-8")
    node_src = Path("orchestrator/workflow/_orchestrator.py").read_text(encoding="utf-8")
    assert "restrict_to_named_day" in agent_src
    assert "restrict_to_named_day" in node_src
    assert node_src.index("restrict_to_named_day(") < node_src.index(
        "self.analytics_agent.analyze("
    ), "the node must narrow the rows before the analysis reads them"
