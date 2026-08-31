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
    cap = source.index("MAX_FETCH_CANDIDATES")
    fetch = source.index("await fetch_series(")
    assert cap < fetch, "the budget check must precede fetch_series"


def test_it_declines_rather_than_truncating():
    """No slicing of the candidate list — the whole point is not to answer partially."""
    source = inspect.getsource(px.execute)
    window = source[source.index("MAX_FETCH_CANDIDATES") : source.index("await fetch_series(")]
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
    for hint in ("one floor, or one room", "one measurement at a time"):
        assert hint in source


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
