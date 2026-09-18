"""CAVEAT-500: one typical latency figure cannot describe a 10x spread.

"Which teaching sessions are scheduled in Room 1.06?" was re-asked three times with the cache
flushed before each and came back in 10.7 s, 61.1 s and 13.3 s — all correct, all the same
question — having already exceeded the client timeout once on the run before. The orientation
note's "typical answer 14 s" is true of none of that, and with only a mean to go on a TIMEOUT
row is indistinguishable from a defect. The review (Gate B, p. 22) asks for workload-specific
percentiles per lane instead.

These tests pin the four properties that make the report worth having:

1. every printed figure is an OBSERVED request time, never interpolated or averaged, so it
   can be traced back to the case that produced it;
2. the n is always stated, because a percentile over three samples is a number and not a
   distribution;
3. a lane too small for a p95 does not get one, and one that is merely the slowest case says
   so rather than posing as a tail;
4. the run summary line keeps its exact shape — other tooling and several docs quote it.
"""

import importlib.util
import inspect
import sys
from pathlib import Path

import pytest

pytestmark = pytest.mark.unit

REPO = Path(__file__).resolve().parent.parent


def _probe():
    spec = importlib.util.spec_from_file_location(
        "_probe", REPO / "scripts" / "regression_probe.py"
    )
    mod = importlib.util.module_from_spec(spec)
    sys.modules["_probe"] = mod
    spec.loader.exec_module(mod)
    return mod


def _row(group, seconds, question="q", status="OK"):
    return {
        "group": group,
        "question": question,
        "seconds": seconds,
        "status": status,
        "ok": status == "OK",
        "why": "",
        "intent": "",
        "answer": "",
    }


# The three measured re-asks from the CAVEAT-500 row, plus a fourth that never returned.
_CAVEAT_500_TIMETABLE = [
    _row("timetable", 10.7, "Which teaching sessions are scheduled in Room 1.06?"),
    _row("timetable", 61.1, "Which teaching sessions are scheduled in Room 1.06?"),
    _row("timetable", 13.3, "Which teaching sessions are scheduled in Room 1.06?"),
    _row("timetable", 121.0, "Which teaching sessions are scheduled in Room 1.06?", "TIMEOUT"),
    _row("timetable", 12.0, "Which teaching sessions are scheduled in Room 1.06?"),
]


# ── 1. every figure is a measurement ────────────────────────────────────────────


def test_a_percentile_is_an_observed_value_not_an_interpolation():
    """An interpolated median over an even count reports a wait no request ever had.

    [10.7, 61.1] would interpolate to 35.9 s — a figure that matches no case, so nobody
    can go and look at the case behind it. That is the opposite of what CAVEAT-500 needs.
    """
    p = _probe()._percentile([10.7, 61.1], 0.50)
    assert p in (10.7, 61.1)
    assert p != pytest.approx(35.9)


def test_nearest_rank_is_used_for_both_percentiles():
    probe = _probe()
    values = [1.0, 2.0, 3.0, 4.0, 5.0, 6.0, 7.0, 8.0, 9.0, 10.0]
    assert probe._percentile(values, 0.50) == 5.0  # ceil(0.50 * 10) = 5 -> 5th smallest
    assert probe._percentile(values, 0.95) == 10.0  # ceil(0.95 * 10) = 10 -> the slowest


def test_an_unordered_lane_is_ranked_before_it_is_read():
    assert _probe()._percentile([61.1, 10.7, 13.3], 0.50) == 13.3


def test_no_samples_yields_no_figure_rather_than_a_zero():
    """A lane that ran nothing waited 0.0 s is a false statement; there is no figure."""
    assert _probe()._percentile([], 0.50) is None


def test_the_probe_stores_the_time_the_request_took():
    """Timings must be MEASURED. Dividing the run total by the case count would give every
    case the same number and erase exactly the variance this exists to show."""
    source = inspect.getsource(_probe().main)
    assert 'res.get("elapsed_s")' in source
    assert '"seconds": seconds' in source


# ── 2. the n is always stated ───────────────────────────────────────────────────


def test_every_lane_states_how_many_cases_it_is_summarising():
    stats = _probe()._latency_by_lane(_CAVEAT_500_TIMETABLE + [_row("counts", 4.0)])
    assert stats
    for s in stats:
        assert s["n"] >= 1
    assert {s["lane"]: s["n"] for s in stats}["timetable"] == 5


def test_the_written_table_carries_n_beside_every_percentile():
    lines = _probe()._latency_lines(_CAVEAT_500_TIMETABLE + [_row("counts", 4.0)])
    header = [ln for ln in lines if ln.startswith("| lane |")]
    assert header, lines
    assert "| n |" in header[0]
    assert "p50" in header[0] and "p95" in header[0]


# ── 3. a lane too small for a p95 does not get one ──────────────────────────────


def test_a_lane_below_the_minimum_n_gets_no_p95():
    """Three observations are a list, not a distribution. Printing "p95 = 61.1 s" over them
    repeats the CAVEAT-500 mistake of reading one slow observation as a system property."""
    probe = _probe()
    stat = probe._lane_latency("deliberate", [_row("deliberate", 37.7), _row("deliberate", 22.9)])
    assert stat["n"] == 2
    assert stat["p50"] is not None
    assert stat["p95"] is None
    assert f"n<{probe.P95_MIN_SAMPLES}" in probe._p95_cell(stat)


def test_the_minimum_n_is_the_boundary_it_claims_to_be():
    probe = _probe()
    rows = [_row("lane", float(i)) for i in range(1, probe.P95_MIN_SAMPLES)]
    assert probe._lane_latency("lane", rows)["p95"] is None
    rows.append(_row("lane", float(probe.P95_MIN_SAMPLES)))
    assert probe._lane_latency("lane", rows)["p95"] is not None


def test_a_p95_that_is_only_the_slowest_case_says_so():
    """For any n < 20 the nearest-rank p95 IS the maximum. Unmarked, that reads as a tail of
    a distribution when it is a single case, which is the misreading CAVEAT-500 records."""
    probe = _probe()
    stat = probe._lane_latency("timetable", _CAVEAT_500_TIMETABLE)
    assert stat["p95"] == stat["slowest"]
    assert stat["p95_is_the_slowest"] is True
    assert probe._p95_cell(stat).endswith("*")


def test_a_lane_large_enough_for_a_real_tail_is_not_marked():
    probe = _probe()
    rows = [_row("capability-bypass", float(i)) for i in range(1, 41)]
    stat = probe._lane_latency("capability-bypass", rows)
    assert stat["p95_is_the_slowest"] is False
    assert stat["p95"] == 38.0  # ceil(0.95 * 40) = 38 -> the 38th of 40, below the maximum
    assert stat["slowest"] == 40.0
    assert not probe._p95_cell(stat).endswith("*")


# ── 4. the report makes a slow case visible ─────────────────────────────────────


def test_the_lane_is_the_category_the_case_already_carries():
    """Grouping by anything other than the bracketed group would summarise a workload the
    case list does not name."""
    stats = _probe()._latency_by_lane([_row("w0", 5.0), _row("circulation", 9.0), _row("w0", 7.0)])
    lanes = {s["lane"]: s["n"] for s in stats}
    assert lanes["w0"] == 2
    assert lanes["circulation"] == 1


def test_an_all_lanes_row_covers_every_case_exactly_once():
    rows = _CAVEAT_500_TIMETABLE + [_row("counts", 4.0), _row("counts", 6.0)]
    stats = _probe()._latency_by_lane(rows)
    overall = [s for s in stats if s["lane"] == "ALL LANES"]
    assert len(overall) == 1
    assert overall[0]["n"] == len(rows)


def test_a_single_lane_run_gets_no_redundant_overall_row():
    stats = _probe()._latency_by_lane([_row("w0", 5.0), _row("w0", 7.0)])
    assert [s["lane"] for s in stats] == ["w0"]


def test_the_slow_case_is_named_so_it_can_be_re_asked():
    """ "missing ['...']" without the case is why the first thing anyone did with a probe
    failure was re-ask it by hand. The same applies to a slow one."""
    stat = _probe()._lane_latency("timetable", _CAVEAT_500_TIMETABLE)
    assert stat["slowest"] == 121.0
    assert "Room 1.06" in stat["slowest_question"]


def test_a_timed_out_wait_is_counted_apart_from_an_answered_one():
    """A timeout contributes the wait the client sat through, which is real, and is NOT the
    time the answer would have taken — the exact confusion CAVEAT-500 names."""
    stat = _probe()._lane_latency("timetable", _CAVEAT_500_TIMETABLE)
    assert stat["timed_out"] == 1
    stat_ok = _probe()._lane_latency("counts", [_row("counts", 4.0), _row("counts", 6.0)])
    assert stat_ok["timed_out"] == 0


def test_the_spread_that_caused_caveat_500_is_visible_in_the_report():
    """The whole point: 10.7 s and 121 s in one lane must not collapse into one figure."""
    lines = "\n".join(_probe()._latency_lines(_CAVEAT_500_TIMETABLE))
    assert "| timetable |" in lines
    assert "13.3" in lines  # the p50
    assert "121.0" in lines  # the tail, and the wait that timed out


def test_the_written_report_explains_that_the_figures_are_not_interpolated():
    lines = "\n".join(_probe()._latency_lines(_CAVEAT_500_TIMETABLE))
    assert "nearest rank" in lines
    assert "no " in lines and "interpolation" in lines


def test_an_empty_run_produces_no_latency_section():
    assert _probe()._latency_lines([]) == []


# ── 5. the quoted summary line is unchanged ─────────────────────────────────────


def test_the_pass_summary_line_keeps_its_exact_shape():
    """`59/60 pass in 22.8 min` is quoted by other tooling and by several docs. Latency
    reporting is added around it, never inside it."""
    source = inspect.getsource(_probe().main)
    assert 'print(f"\\n{len(rows) - failed}/{len(rows)} pass in {elapsed / 60:.1f} min")' in source
