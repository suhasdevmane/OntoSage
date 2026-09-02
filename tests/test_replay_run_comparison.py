# -*- coding: utf-8 -*-
"""A replay score is meaningless without why it moved, and how loaded the machine was.

CAVEAT-381. The probe counted grades and nothing else, so a confidently wrong answer and a
correct one scored identically — and removing wrong answers looked exactly like losing good
ones. Run on the two real V7 probes, the headline said 43.2% -> 36.0%, a seven-point drop.
The actual composition of that "drop":

    15 tightened   — stopped answering, plausibly correctly
    12 re-graded   — passages that used to be counted as computations (BUG-370)
    20 gained      — now computes an answer it did not before
     1 lost        — the only candidate regression in the whole run

These tests pin each of those distinctions, because collapsing any of them back into a
single number is what made the original reading wrong.
"""

import importlib.util
from pathlib import Path

import pytest

pytestmark = pytest.mark.unit

_SCRIPT = Path(__file__).resolve().parent.parent / "scripts" / "corpus_replay.py"


def _load():
    spec = importlib.util.spec_from_file_location("corpus_replay", _SCRIPT)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)  # type: ignore[union-attr]
    return mod


replay = _load()


def _row(grade, status="OK", elapsed="5.0"):
    return {"grade": grade, "status": status, "elapsed_s": elapsed, "question": "q"}


# ── why a grade changed ────────────────────────────────────────────────────────────────


def test_a_timeout_is_machine_load_not_a_capability_change():
    verdict, reason = replay.classify_grade_change(
        _row("answered-with-data"), _row("invalid-no-response", status="TIMEOUT")
    )
    assert verdict == "broke"
    assert "re-ask" in reason.lower()


def test_an_honest_decline_is_a_tightening_not_a_loss():
    """Five such answers had been served FROM THE WRONG SOURCE. Declining is the fix."""
    verdict, _ = replay.classify_grade_change(
        _row("answered-with-data"), _row("honest-capability-answer")
    )
    assert verdict == "tightened"


def test_a_passage_recognised_as_a_passage_is_not_a_loss():
    """BUG-370: `document-quoted` exists because quotes were counted as computations."""
    verdict, reason = replay.classify_grade_change(
        _row("answered-with-data"), _row("document-quoted")
    )
    assert verdict == "requoted"
    assert "quotation" in reason


def test_a_genuine_loss_is_still_reported_as_one():
    """The point is not to explain every drop away."""
    verdict, _ = replay.classify_grade_change(_row("answered-with-data"), _row("deflected"))
    assert verdict == "lost"


def test_a_new_computed_answer_is_a_gain():
    verdict, _ = replay.classify_grade_change(
        _row("invalid-no-response"), _row("answered-with-data")
    )
    assert verdict == "gained"


def test_an_unchanged_grade_is_not_reported():
    verdict, _ = replay.classify_grade_change(
        _row("answered-with-data"), _row("answered-with-data")
    )
    assert verdict == "unchanged"


# ── run health ─────────────────────────────────────────────────────────────────────────


def test_a_clean_run_is_fit_to_compare():
    health = replay.run_health([_row("answered-with-data", elapsed=str(4 + i)) for i in range(20)])
    assert health["comparable"] is True
    assert health["warnings"] == []


def test_timeouts_make_a_run_unfit_to_compare():
    rows = [_row("answered-with-data") for _ in range(20)]
    rows[0] = _row("invalid-no-response", status="TIMEOUT", elapsed="240.0")
    health = replay.run_health(rows)
    assert health["timeouts"] == 1
    assert health["comparable"] is False
    assert any("TIMED OUT" in w for w in health["warnings"])


def test_a_contended_run_is_flagged_by_its_latency_tail():
    """p90 doubling from 35s to 83s is what made a healthy run look like a regression."""
    rows = [_row("answered-with-data", elapsed="1.0") for _ in range(18)]
    rows += [_row("answered-with-data", elapsed="90.0") for _ in range(2)]
    health = replay.run_health(rows)
    assert health["comparable"] is False
    assert any("p90" in w for w in health["warnings"])


def test_health_survives_rows_with_no_timing():
    """A run whose rows carry no elapsed_s must not crash the report."""
    health = replay.run_health([{"grade": "answered-with-data", "status": "OK"}])
    assert health["n"] == 0 and health["p50"] == 0.0


# ── the whole report ───────────────────────────────────────────────────────────────────


def test_comparison_report_separates_the_causes(tmp_path):
    import csv

    def write(path, rows):
        with open(path, "w", newline="", encoding="utf-8") as fh:
            w = csv.DictWriter(fh, fieldnames=["qid", "question", "grade", "status", "elapsed_s"])
            w.writeheader()
            w.writerows(rows)

    before = tmp_path / "before.csv"
    after = tmp_path / "after.csv"
    write(
        before,
        [
            {
                "qid": "A1",
                "question": "q1",
                "grade": "answered-with-data",
                "status": "OK",
                "elapsed_s": "5",
            },
            {
                "qid": "A2",
                "question": "q2",
                "grade": "answered-with-data",
                "status": "OK",
                "elapsed_s": "5",
            },
            {
                "qid": "A3",
                "question": "q3",
                "grade": "answered-with-data",
                "status": "OK",
                "elapsed_s": "5",
            },
            {"qid": "A4", "question": "q4", "grade": "deflected", "status": "OK", "elapsed_s": "5"},
        ],
    )
    write(
        after,
        [
            {
                "qid": "A1",
                "question": "q1",
                "grade": "honest-capability-answer",
                "status": "OK",
                "elapsed_s": "5",
            },
            {
                "qid": "A2",
                "question": "q2",
                "grade": "document-quoted",
                "status": "OK",
                "elapsed_s": "5",
            },
            {
                "qid": "A3",
                "question": "q3",
                "grade": "invalid-no-response",
                "status": "TIMEOUT",
                "elapsed_s": "240",
            },
            {
                "qid": "A4",
                "question": "q4",
                "grade": "answered-with-data",
                "status": "OK",
                "elapsed_s": "5",
            },
        ],
    )

    report = replay.compare_runs(before, after)
    assert "Tightened" in report and "A1" in report
    assert "Re-graded as a quotation" in report and "A2" in report
    assert "Broke" in report and "A3" in report
    assert "Gained" in report and "A4" in report
    # A run containing a timeout must say it is not straightforwardly comparable.
    assert "not straightforwardly comparable" in report
