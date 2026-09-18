# -*- coding: utf-8 -*-
"""A question too broad to read is declined, not timed out (V7-T24).

Measured 2026-08-31: "show me live setpoints versus measured temperature for all zones on
floor 5" enumerated the whole building — 522 series across 8 tables — and died on the
120 s workflow timeout, 121 s after the user asked. Sixteen of the 1,580 baseline
questions end that way.

The cap declines rather than truncating. A "which rooms" answer computed over an arbitrary
slice of the candidates is wrong in a way that looks right, and the reader cannot tell.
"""

from __future__ import annotations

import inspect

import pytest

from orchestrator.services.deliberation import plan_executor as px

pytestmark = pytest.mark.unit


def test_a_fetch_budget_exists_and_is_a_number():
    assert isinstance(px.MAX_FETCH_CANDIDATES, int)
    assert px.MAX_FETCH_CANDIDATES > 0


def test_the_budget_sits_above_a_floor_and_below_a_building():
    """A floor-scoped question must stay untouched; a whole building must not."""
    assert 60 < px.MAX_FETCH_CANDIDATES < 500


def test_the_check_runs_before_the_fetch():
    """Declining after paying for the fetch would save nothing at all."""
    source = inspect.getsource(px.execute)
    cap = source.index("MAX_FETCH_ROWS")  # WB-04: the budget is in rows now
    fetch = source.index("await fetch_series(")
    assert cap < fetch, "the budget check must precede fetch_series"


def test_it_declines_rather_than_truncating():
    """No slicing of the candidate list — the whole point is not to answer partially."""
    source = inspect.getsource(px.execute)
    window = source[source.index("MAX_FETCH_ROWS") : source.index("await fetch_series(")]
    assert "candidates[:" not in window, "truncating would answer over an unnamed subset"
    assert "return ExecutionOutcome(" in window


def test_the_decline_names_the_narrowing_that_would_work():
    """A refusal that does not say what to ask instead costs the user a second guess."""
    source = inspect.getsource(px.execute)
    assert "Narrow it to a floor" in source


def test_no_building_literal_reaches_this_module():
    """Deliberation modules carry zero building names — comments included.

    The first version of this comment cited a building by name and the coverage audit
    caught it, which is exactly what that audit is for.
    """
    source = inspect.getsource(px)
    for literal in ("bldg1", "bldg2", "bldg3", "abacws", "Abacws"):
        assert literal not in source, literal


# ── the SQL lane needs the same budget ────────────────────────────────────────
#
# Capping the deliberation lane alone simply moved the question: the same query then
# reached the SQL lane with 288 uuids, fetched all of them, and narrated ONE sensor — on
# a different floor from the one asked about. Faster and wrong is worse than slow.


def test_the_sql_lane_has_its_own_budget():
    from orchestrator.agents import sql_agent

    assert isinstance(sql_agent.MAX_FETCH_UUIDS, int)
    assert sql_agent.MAX_FETCH_UUIDS > px.MAX_FETCH_CANDIDATES, (
        "this counts SENSORS while the deliberation budget counts SPACES, and a space "
        "holds several sensors — a smaller sensor budget would decline floor questions "
        "the space budget lets through"
    )


def test_the_sql_budget_declines_before_fetching():
    from orchestrator.agents import sql_agent

    source = inspect.getsource(sql_agent.SQLAgent)
    cap = source.index("MAX_FETCH_UUIDS")
    assert "too_broad" in source[cap : cap + 2000]
    assert "uuids[:" not in source[cap : cap + 2000], "truncating hides which part answered"


def test_the_sql_decline_says_what_to_ask_instead():
    from orchestrator.agents import sql_agent

    source = inspect.getsource(sql_agent.SQLAgent)
    for hint in ("One floor, one room", "as a comparison"):
        assert hint in source


def test_the_sql_decline_does_not_tell_the_reader_to_drop_a_measurement():
    """Rows 0/16/17/25 of the 2026-09-17 stakeholder read.

    Every one of them asked about several measurements at once — "the best balance of
    temperature, ventilation, light and quiet" — and every one was answered with "one
    measurement at a time (temperature, or CO2 — not both)". That is advice to ask a
    different question, and it misdescribes the system: the comparison lane ranks spaces on
    several measurements at once across the whole building. The budget is real; this
    narrowing was not.
    """
    from orchestrator.agents import sql_agent

    source = inspect.getsource(sql_agent.SQLAgent)
    assert "one measurement at a time" not in source
    assert "not both" not in source


def test_a_deliberate_decline_is_not_re_explained_as_missing_data():
    """The lane that refused must be the lane the user hears.

    Measured: a 288-sensor question was declined correctly by the SQL lane, and the
    analytics lane — seeing zero rows — replaced the message with "the sensor might not
    be actively transmitting". That blames the building for a choice the system made and
    sends the reader to fix the wrong thing.
    """
    from orchestrator.agents import analytics_agent

    source = inspect.getsource(analytics_agent)
    # Anchored on CODE, not on the prose: the first attempt searched for the message
    # text and matched the comment explaining the fix, which sits above the check.
    passthrough = source.index('sql_result.get("too_broad")')
    generic = source.index('"no_data_available"')
    assert passthrough < generic, "the too_broad passthrough must come first"
    assert '"error": "question_too_broad"' in source


# ── WB-04: the budget is in rows, and "right now" reads only recent rows ─────────────


def test_a_building_wide_right_now_ranking_fits_the_row_budget():
    """234 spaces x 4 modalities was declined by the space cap while every floor was live."""
    hours, limit, rows = px.fetch_plan(px.TimeBasis.NOW, None, 234, 4)
    assert hours <= 3.0 and limit <= 90 and rows <= px.MAX_FETCH_ROWS


def test_a_building_wide_multi_day_window_still_declines():
    _h, _l, rows = px.fetch_plan(px.TimeBasis.WINDOW, 72.0, 800, 6)
    assert rows > px.MAX_FETCH_ROWS  # a larger building over many criteria still declines


def test_the_fetch_uses_the_plan_the_budget_checked():
    source = inspect.getsource(px.execute)
    assert "per_uuid_limit=_plan_limit" in source and "fetch_window = _plan_hours" in source


def test_the_sql_lane_budget_is_in_rows_and_right_now_is_cheap():
    from orchestrator.agents import sql_agent

    assert sql_agent.rows_per_uuid_for("what is the temperature on each floor right now?") == 60
    assert sql_agent.rows_per_uuid_for("average temperature on each floor last week") == 1000
    # 288 temperature sensors building-wide, right now: inside the budget
    assert 288 * sql_agent.rows_per_uuid_for("temperature right now") <= sql_agent.MAX_FETCH_ROWS
    # the same sensors over a week: declined
    assert 288 * sql_agent.rows_per_uuid_for("temperature over the last week") > sql_agent.MAX_FETCH_ROWS


def test_a_building_wide_afternoon_window_is_read_whole():
    """WB-12: never shrink the sample to fit — the latest-n fetch would relabel a window mean."""
    hours, limit, rows = px.fetch_plan(px.TimeBasis.WINDOW, 6.0, 234, 4)
    assert limit == 360 and rows <= px.MAX_FETCH_ROWS


# ── CAVEAT-578: a window mean covers its window, or says what it covered ─────────


def test_a_floor_scoped_day_is_read_whole():
    hours, limit, rows = px.fetch_plan(px.TimeBasis.WINDOW, 24.0, 40, 2)
    assert limit == 1440 and rows <= px.MAX_FETCH_ROWS  # was 500: the newest ~8.3 h


def test_a_day_too_wide_to_read_whole_falls_back_to_the_bounded_read():
    _h, limit, rows = px.fetch_plan(px.TimeBasis.WINDOW, 24.0, 234, 4)
    assert limit == px.DEFAULT_PER_UUID_LIMIT and rows <= px.MAX_FETCH_ROWS


def test_a_cut_series_is_disclosed_and_a_whole_one_is_not():
    whole = [(f"2026-09-14 {h:02}:00:00", 1.0) for h in range(24)]
    cut = [(f"2026-09-14 {h:02}:00:00", 1.0) for h in range(16, 24)]
    assert px.window_coverage_note({"a": whole}, 24, "2026-09-14 00:00:00", 24.0) is None
    note = px.window_coverage_note({"a": whole, "b": cut}, 8, "2026-09-14 00:00:00", 24.0)
    assert note and "1 of 2" in note and "newest 8 readings" in note
    # a short series that simply has few readings was not cut by the read
    assert px.window_coverage_note({"b": cut}, 500, "2026-09-14 00:00:00", 24.0) is None


def test_the_executor_attaches_the_coverage_note():
    source = inspect.getsource(px.execute)
    assert "window_coverage_note(" in source and "_coverage_note" in source
