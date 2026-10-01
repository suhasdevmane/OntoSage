# -*- coding: utf-8 -*-
"""BUG-1252 — the three lanes `_grounded_evidence_behind` does not recognise, pinned as a GAP.

THIS FILE PINS BEHAVIOUR THAT IS WRONG. It exists so the gap is countable rather than
rediscovered by hand-reading another sixty answers, and every assertion here must be INVERTED
and this file deleted when BUG-1252 is closed. Read that row before changing anything here.

WHAT WAS MEASURED, live, 2026-09-30, four consecutive turns in one container log
--------------------------------------------------------------------------------
Four of the eight false declines in the tail-N read (docs/phase0/tail_N_2026-09-30_read.md)
were produced this way: the question routed correctly, its lane fetched real readings, an
answer was produced, and the gate replaced it with `_unanswered_response` — whose opening
sentence, "I couldn't answer that from Abacws Building's records", is false on a turn that has
just read them.

    [response] relevance gate replaced a sensor_data answer: OFF_TOPIC
        (Does not address change, only gives current values.)          <- 275 humidity UUIDs
    [response] relevance gate replaced a sensor_data answer: OFF_TOPIC
        (Does not provide return air temperature, gives unrelated
         building averages.)                                           <- 6 AHU points
    [response] relevance gate replaced a analytics answer: OFF_TOPIC
        (Provides data, not explanation of monitoring method.)         <- 1,000 water rows
    [response] relevance gate replaced a events answer: OFF_TOPIC
        (does not address reserved spaces question.)                   <- the events lane

BUG-873 established the rule in `_relevance_gated`'s own comment — "when a lane has just
answered FROM THOSE RECORDS, that sentence is not a cautious decline, it is a false statement
about the building" — and its guard lists four bus keys: `evidence_dossier`,
`aggregate_result`, `comparison`, `forecast_result`. The principal data path writes
`sql_result` and `analytics_result`; the events lane writes `events_result`. None is listed.
The forecast lane was missed by the FIRST version of that same guard and added after a live
failure; this is the same omission twice more.

WHY IT IS NOT SIMPLY ADDED HERE
-------------------------------
Adding those three keys would stop the gate replacing on essentially every data turn, and the
data lanes are where the gate measures BEST — its own docstring reports sensor_data 17/30 weird
flagged with 0/10 good replaced, events 8/9. Disabling its action on its strongest lanes on the
evidence of four hand-read instances is the trade CAVEAT-972 and BUG-1073 both refused. The
return-air-temperature turn is the case that proves it: there the answer really was about
something else and suppressing it was protective.

The fix BUG-1252 recommends is therefore to change what the replacement SAYS, not whether it
happens — which cannot restore a wrong answer and cannot lose a right one.
"""

from __future__ import annotations

import pytest

from orchestrator.workflow._orchestrator import _grounded_evidence_behind

pytestmark = pytest.mark.unit


class _State:
    def __init__(self, results):
        self.intermediate_results = results


#: What each of the four turns left on the bus, in the shape the lane writes it.
@pytest.mark.parametrize(
    "lane, results",
    [
        (
            "sensor_data (#23 humidity, 275 series fetched)",
            {"sql_result": {"results": {"data": [{"value": 41.2}] * 275}, "success": True}},
        ),
        (
            "sensor_data (#43 return air temperature, 6 AHU points)",
            {"sql_result": {"results": {"data": [{"value": 21.8}] * 6}, "success": True}},
        ),
        (
            "analytics (#45 water, 1,000 rows narrated)",
            {"analytics_result": {"success": True, "formatted_response": "305.0 litres/day ..."}},
        ),
        (
            "events (#46 reserved spaces)",
            {"events_result": {"success": True, "rows": [{"room": "5.01"}]}},
        ),
    ],
    ids=["sql_humidity", "sql_return_air", "analytics_water", "events_bookings"],
)
def test_the_gap_bug_1252_records(lane, results):
    """CURRENT behaviour, and it is the defect. Invert this when BUG-1252 is closed.

    `_grounded_evidence_behind` reports "" — no evidence visible — for a turn that fetched
    hundreds of readings, so `_relevance_gated` is free to replace the answer with a decline
    that says the building's records could not answer.
    """
    assert _grounded_evidence_behind(_State(results)) == "", lane


def test_the_four_keys_the_guard_does_recognise_still_work():
    """So a future edit cannot close the gap by breaking what BUG-873 fixed.

    These four are the whole of the guard today. If one of them stops returning evidence, the
    lane it protects goes back to having its answers deleted, which is what BUG-873 was.
    """
    assert _grounded_evidence_behind(
        _State({"evidence_dossier": {"ranked": [{}] * 195, "evidence": [{}] * 400}})
    )
    assert _grounded_evidence_behind(_State({"aggregate_result": {"figures": {"mean": 750.0}}}))
    assert _grounded_evidence_behind(_State({"comparison": {"baseline": {"mean": 1.0}}}))
    assert _grounded_evidence_behind(
        _State({"forecast_result": {"success": True, "model": "SeasonalNaive", "forecast": [1.0]}})
    )


def test_the_guard_is_still_a_whitelist_of_exactly_those_four_keys():
    """Read from the source, so the count cannot drift without this test noticing.

    A fifth key appearing here means either BUG-1252 was fixed (delete this file) or a lane was
    added without the reasoning above being read.
    """
    import inspect

    from orchestrator.workflow import _orchestrator

    src = inspect.getsource(_orchestrator._grounded_evidence_behind)
    for key in ("evidence_dossier", "aggregate_result", "comparison", "forecast_result"):
        assert key in src, key
    for absent in ("sql_result", "analytics_result", "events_result"):
        assert absent not in src, (
            f"{absent} is now recognised as evidence — BUG-1252 may be fixed; "
            "invert the parametrized test above and delete this file"
        )
