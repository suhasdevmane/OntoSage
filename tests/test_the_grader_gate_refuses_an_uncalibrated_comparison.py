# -*- coding: utf-8 -*-
"""A grader that scores SHAPE may not gate a wave that changed the shape.

WHAT WENT WRONG
---------------
``scripts/grade_answers_rubric.py --gate`` exits non-zero when the weird share rises. On
the sixth recorded run of the 147-question bank it reported the share FALLING, 29.9% to
27.9%, and named run 6 the best of the six. A hand read of the same 147 answers measured
that run REGRESSING, 61.2% to 65.3% weird (BUG-787). The gate would have passed a
regression, and it is the only one of the five consecutive deltas where the grader's
direction was wrong.

The cause is stated in CAVEAT-784: this grader scores the SHAPE of an answer, and between
those runs the system changed the wording of its declines. The register-census sentence
"the register does not record X" matches the first entry of ``_DECLINE_PATTERNS``, so the
GOOD_DECLINE bucket absorbed rows a reader calls weird -- 42 to 75 in one night -- and the
weird share fell without the answers improving.

So the gate now detects that condition. When a decline pattern's firing rate moves
materially between the two runs, the comparison is NOT CALIBRATED and the gate does not
pass, whatever the share did.

This file pins that, in both directions: the shift must be detected where it happened, and
must NOT be claimed where the wording was stable. A detector that fires on everything is
the same failure one step along.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import List

import pytest

import scripts.grade_answers_rubric as G

pytestmark = pytest.mark.unit

REPO = Path(__file__).resolve().parent.parent
P0 = REPO / "docs" / "phase0"

#: The recorded runs, and whether the wording of the declines moved from the previous one.
#: Measured 2026-09-30 by ``scripts/audit_grader_calibration.py``. run4 -> run5 introduced
#: the register census; run5 -> run6 halved it, and that is the delta the gate used to pass.
RUN_FILES = {
    "run2": "phase0_rerun.md.jsonl",
    "run3": "phase0_run3.md.jsonl",
    "run4": "phase0_run4.md.jsonl",
    "run5": "phase0_run5.md.jsonl",
    "run6": "phase0_run6.md.jsonl",
}
EXPECT_SHIFT = {
    ("run2", "run3"): False,
    ("run3", "run4"): False,
    ("run4", "run5"): True,
    ("run5", "run6"): True,
}


def _answers(name: str) -> List[dict]:
    path = P0 / RUN_FILES[name]
    if not path.is_file():
        pytest.skip(f"{path.name} not present")
    return [
        json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line.strip()
    ]


# ── the detector, on the real runs ────────────────────────────────────────────────────


@pytest.mark.parametrize("pair,expected", sorted(EXPECT_SHIFT.items()))
def test_a_wording_shift_is_detected_exactly_where_it_happened(pair, expected):
    old, new = pair
    moved = G.wording_shift(_answers(old), _answers(new))
    assert bool(moved) is expected, f"{old}->{new}: {moved}"


def test_the_shift_that_matters_is_the_census_pattern():
    """Naming the pattern, not just the count, so a future change is legible."""
    moved = G.wording_shift(_answers("run4"), _answers("run5"))
    assert len(moved) == 1, moved
    pattern, old_n, new_n = moved[0]
    assert pattern == G._DECLINE_PATTERNS[0], pattern
    assert (old_n, new_n) == (47, 81), (old_n, new_n)


# ── the gate's own contract ───────────────────────────────────────────────────────────


def test_the_gate_does_not_pass_an_uncalibrated_comparison_even_when_the_share_falls():
    """The exact case the gate got wrong: share down, answers worse."""
    judge = G.DeterministicJudge()
    from datetime import date

    asof = date(2026, 9, 18)
    bank = P0 / "phase0_bank.jsonl"
    new_graded = G.grade_run(P0 / RUN_FILES["run6"], judge, bank=bank, asof=asof)
    old_graded = G.grade_run(P0 / RUN_FILES["run5"], judge, bank=bank, asof=asof)
    shift = G.wording_shift(_answers("run5"), _answers("run6"))
    ok, detail = G.gate(new_graded, old_graded, shift=shift)
    assert detail["delta"] < 0, "the weird share did fall; that is the point"
    assert detail["calibrated"] is False
    assert ok is False, detail["delta"]


def test_a_calibrated_comparison_with_a_falling_share_still_passes():
    """The detector must not simply switch the gate off."""
    judge = G.DeterministicJudge()
    from datetime import date

    asof = date(2026, 9, 18)
    bank = P0 / "phase0_bank.jsonl"
    new_graded = G.grade_run(P0 / RUN_FILES["run4"], judge, bank=bank, asof=asof)
    old_graded = G.grade_run(P0 / RUN_FILES["run3"], judge, bank=bank, asof=asof)
    shift = G.wording_shift(_answers("run3"), _answers("run4"))
    ok, detail = G.gate(new_graded, old_graded, shift=shift)
    assert detail["calibrated"] is True, detail["wording_shift"]
    assert ok is True, detail["delta"]


def test_gate_reports_calibration_state_even_when_no_shift_is_passed():
    """A caller that does not compute the shift must not be told it is calibrated by luck."""
    rows = [{"question": "q", "verdict": G.GOOD_ANSWER, "reason": ""}]
    ok, detail = G.gate(rows, rows)
    assert ok is True
    assert "calibrated" in detail and "wording_shift" in detail


def test_the_limits_note_points_at_the_audit_rather_than_quoting_a_number():
    """Every hand-maintained figure in this project went stale. This one is a pointer."""
    note = G.BUCKET_LIMITS_NOTE
    assert "audit_grader_calibration.py" in note
    assert "LOWER BOUND" in note
    assert "GOOD_DECLINE" in note
    # No percentage or bucket count baked in, or it will be wrong within the month.
    assert "%" not in note, note


def test_the_shift_thresholds_are_named_constants_not_literals():
    assert G.SHIFT_MIN_ROWS == 8
    assert G.SHIFT_MIN_RELATIVE == pytest.approx(0.10)


def test_the_detector_makes_no_network_call(monkeypatch):
    import urllib.request

    def boom(*_a, **_k):
        raise AssertionError("the shift detector must be offline")

    monkeypatch.setattr(urllib.request, "urlopen", boom)
    G.wording_shift(_answers("run5"), _answers("run6"))
