# -*- coding: utf-8 -*-
"""BUG-1444 -- "the data is complete" must rest on measured gaps, not on a count share.

Case 32 of the 2026-10-06 gate asked how complete the floor-3 CO2 data was for the month. Both
providers answered "complete" while the same answer's evidence record measured 2% of the window
observed, and every floor-3 sensor had silences longer than ten minutes, the longest about 42
hours.

The defect has two halves, and both are pinned here:

* A COUNT share is the wrong measure of completeness. A 42-hour hole is about 2% of a month,
  so a count-based floor of 90% passes it. The gap itself must fail the gate.
* PROSE that claims completeness is not checked against the record. The answer carried the
  claim and the measurement side by side, and nothing connected them.

Runs in the parked state: no stack, no graph.
"""

from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest

from orchestrator.services.evidence.assemble import build_evidence_record
from orchestrator.services.evidence.completeness import (
    assess,
    asserts_completeness,
    completeness_disclosure,
)
from orchestrator.services.evidence.gates import completeness_gate
from orchestrator.services.evidence.policy import load_policy

pytestmark = pytest.mark.unit

START = datetime(2026, 9, 6, 0, 0, 0)
END = START + timedelta(days=30)
HOUR = 3600
HOLE = range(200, 242)  # 42 consecutive hourly samples missing: a 42-hour silence


def _hourly_with_hole(skip=HOLE):
    return [START + timedelta(hours=i) for i in range(720) if i not in skip]


# ── the count-versus-gap defect ───────────────────────────────────────────────


def test_a_42_hour_silence_passes_the_count_floor_but_is_not_complete():
    """The measured failure: the share clears 90%, and a 42-hour silence is still in it."""
    report = assess(_hourly_with_hole(), START, END, HOUR)
    assert report.passes(0.9), f"the count share should pass: {report.coverage}"
    assert report.gaps, "the 42-hour silence was not measured as a gap"
    longest = max(report.gaps, key=lambda g: g.minutes)
    assert longest.minutes >= 42 * 60, longest.minutes


def test_a_series_with_no_silence_has_no_gap_to_report():
    report = assess(_hourly_with_hole(skip=()), START, END, HOUR)
    assert report.coverage == pytest.approx(1.0)
    assert report.gaps == []


def test_the_gate_fails_on_the_gap_even_when_the_share_clears_the_floor():
    """Remove the gap detail and the same share passes; with it, the gate fails. The second
    half is the one that makes the completeness claim conditional on measured silence."""
    policy = load_policy()
    share = assess(_hourly_with_hole(), START, END, HOUR).coverage
    assert completeness_gate(policy, share).passed is True
    verdict = completeness_gate(
        policy, share, gap_detail="the longest silence is 42 hours, from 2026-09-14 08:00"
    )
    assert verdict.passed is False
    assert "42 hours" in verdict.reason


# ── the evidence record carries the measured gap, not just the share ─────────


#: The evidence assembler compares against an aware clock; the arithmetic tests above are naive.
UTC_START = START.replace(tzinfo=timezone.utc)
UTC_END = END.replace(tzinfo=timezone.utc)


def _windowed(rows):
    return {
        "sql_result": {"results": {"data": rows}},
        "time_range": {"start": UTC_START.isoformat(), "end": UTC_END.isoformat()},
        "_cadences": {"s-1": HOUR},
        "sensor_metadata": {"s-1": {"label": "Floor 3 CO2 sensor", "kind": "co2"}},
    }


def _rows(stamps):
    return [
        {"uuid": "s-1", "datetime": t.replace(tzinfo=timezone.utc).isoformat(), "value": 600.0}
        for t in stamps
    ]


def test_the_record_states_the_longest_silence_by_label_and_length():
    rec = build_evidence_record(_windowed(_rows(_hourly_with_hole())), now=UTC_END)
    assert rec.completeness is not None and rec.completeness >= 0.9, rec.completeness
    assert "42 hours" in rec.completeness_gap or "43 hours" in rec.completeness_gap
    assert "Floor 3 CO2 sensor" in rec.completeness_gap
    assert "s-1" not in rec.completeness_gap, "a stream is named by its label, never its UUID"
    assert any("completeness" in g for g in rec.gates_advisory), rec.gates_advisory


def test_a_gapless_record_states_no_gap_and_raises_no_verdict():
    """The control. Without it the gap sentence could be wired to always say something."""
    rec = build_evidence_record(_windowed(_rows(_hourly_with_hole(skip=()))), now=UTC_END)
    assert rec.completeness_gap == ""
    assert not [g for g in rec.gates_advisory if "completeness" in g], rec.gates_advisory


# ── prose that claims completeness is checked against the record ─────────────


@pytest.mark.parametrize(
    "text",
    [
        "The CO2 data for floor 3 is complete for six sensors.",
        "The series are fully observed across the month.",
        "There are no gaps in the floor-3 readings.",
        "Coverage was 100 % complete for the window.",
    ],
)
def test_completeness_claims_are_recognised(text):
    assert asserts_completeness(text) is True


@pytest.mark.parametrize(
    "text",
    [
        "Use the form to complete the booking.",
        "Here is a complete list of the meeting rooms.",
        "The room is quiet at the moment.",
        "",
    ],
)
def test_other_uses_of_complete_are_not_claims(text):
    assert asserts_completeness(text) is False


def test_a_completeness_claim_gets_the_measured_gap_appended():
    text = "The CO2 data for floor 3 is complete for six sensors."
    record = {"completeness": 0.942, "completeness_gap": "the longest silence is 42 hours"}
    note = completeness_disclosure(text, record, floor=0.9)
    assert "42 hours" in note
    assert "not assumed" in note


def test_a_share_below_the_floor_is_disclosed_as_a_share():
    text = "The CO2 data for floor 3 is complete for six sensors."
    note = completeness_disclosure(text, {"completeness": 0.02, "completeness_gap": ""}, floor=0.9)
    assert "2%" in note


def test_a_supported_claim_is_left_alone():
    text = "The CO2 data for floor 3 is complete."
    assert completeness_disclosure(text, {"completeness": 0.99, "completeness_gap": ""}, 0.9) == ""


def test_a_gap_is_not_disclosed_against_prose_that_claims_nothing():
    record = {"completeness": 0.94, "completeness_gap": "the longest silence is 42 hours"}
    assert completeness_disclosure("The average was 601 ppm.", record, floor=0.9) == ""


def test_a_missing_record_discloses_nothing_and_never_raises():
    assert completeness_disclosure("It is complete.", None, 0.9) == ""
    assert completeness_disclosure("It is complete.", {"completeness": "not a number"}, 0.9) == ""


def test_the_response_node_applies_the_disclosure():
    """The response node is where the record and the prose meet. Pinned by source because
    driving the whole node needs a live graph; the behaviour itself is pinned above."""
    src = Path("orchestrator/workflow/_orchestrator.py").read_text(encoding="utf-8")
    assert "completeness_disclosure as _completeness_disclosure" in src
    assert "_completeness_disclosure(" in src
