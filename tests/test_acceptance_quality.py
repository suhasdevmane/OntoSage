# -*- coding: utf-8 -*-
"""Master Report acceptance scenarios 2 and 4, through the live record (V6-T20).

    Scenario 2 — "Introduce missing intervals → duration and average calculations change
                  appropriately."
    Scenario 4 — "Create conflicting sensors → the answer reports the disagreement rather
                  than averaging it away."

**Asserted through `build_evidence_record`, not against the modules.** T15 and T29 were marked
done while importing pure functions with an "end to end" docstring, and the 2026-08-23 audit
found ten more turns whose modules the pipeline never called. A scenario test that exercises
`completeness.assess` proves the arithmetic and nothing about the system; these go through the
chokepoint the answer path actually uses.

**Each scenario also asserts the negative** — remove the defect and the verdict disappears.
A test that only checks the alarm fires cannot tell a working gate from one wired to `True`,
which is the failure mode that let a whole phase look finished.

Runs in the parked state: no stack, no graph, no building active.
"""

from datetime import datetime, timedelta, timezone

import pytest

from orchestrator.services.evidence.assemble import build_evidence_record
from shared.models import AnswerStatus

pytestmark = pytest.mark.unit

NOW = datetime(2026, 8, 23, 12, 0, 0, tzinfo=timezone.utc)
START = NOW - timedelta(hours=12)
CADENCE = 600  # 10 minutes, matching what bldg1's streams actually declare


def _series(start, end, step_s, uuid="s-1"):
    """A complete series at the declared cadence."""
    out, t = [], start
    while t <= end:
        out.append({"uuid": uuid, "datetime": t.isoformat(), "value": 21.0})
        t += timedelta(seconds=step_s)
    return out


def _windowed(rows, cadences=None):
    return {
        "sql_result": {"results": {"data": rows}},
        "time_range": {"start": START.isoformat(), "end": NOW.isoformat()},
        "_cadences": cadences if cadences is not None else {"s-1": CADENCE},
        "sensor_metadata": {"s-1": {"label": "A", "kind": "temperature", "unit": "degC"}},
    }


# ── Scenario 2: missing intervals change the calculation's standing ──────────


def test_scenario2_a_complete_window_passes_completeness():
    """The control. Without it, a gate that always fires would satisfy the next test."""
    rec = build_evidence_record(_windowed(_series(START, NOW, CADENCE)), now=NOW)
    assert rec.completeness is not None and rec.completeness > 0.9, rec.completeness
    assert not [g for g in rec.gates_advisory if "completeness" in g], rec.gates_advisory


def test_scenario2_punching_a_hole_is_detected_and_quantified():
    """Remove the middle third of the window; coverage must fall and say by how much."""
    rows = _series(START, NOW, CADENCE)
    keep = [r for i, r in enumerate(rows) if not (len(rows) // 3 <= i < 2 * len(rows) // 3)]
    rec = build_evidence_record(_windowed(keep), now=NOW)
    assert rec.completeness is not None
    assert rec.completeness < 0.75, f"a third of the window is missing: {rec.completeness}"
    hits = [g for g in rec.gates_advisory if "completeness" in g]
    assert hits, "a window with a third punched out raised no completeness verdict"
    assert "%" in hits[0], f"the verdict must quantify the gap, not just flag it: {hits[0]}"


def test_scenario2_an_undeclared_cadence_is_unknown_not_complete():
    """The honest third state. Without a declared cadence, coverage cannot be computed — and
    reporting that as complete is how a 40%-covered mean gets presented as a full one."""
    rec = build_evidence_record(_windowed(_series(START, NOW, CADENCE), cadences={}), now=NOW)
    assert rec.completeness is None, "coverage was invented without a declared cadence"


def test_scenario2_the_gate_is_advisory_and_moves_no_answer():
    rows = _series(START, NOW, CADENCE)[:5]
    rec = build_evidence_record(_windowed(rows), now=NOW)
    assert rec.status in (AnswerStatus.OBSERVED, AnswerStatus.CALCULATED)


# ── Scenario 4: disagreement is reported, never averaged ─────────────────────


def _two_in_one_space(v1, v2):
    space = "http://example.org/b#Room1"
    return {
        "sql_result": {
            "results": {
                "data": [
                    {"uuid": "s-1", "datetime": NOW.isoformat(), "value": v1},
                    {"uuid": "s-2", "datetime": NOW.isoformat(), "value": v2},
                ]
            }
        },
        "sensor_metadata": {
            "s-1": {"label": "North", "kind": "temperature", "unit": "degC"},
            "s-2": {"label": "South", "kind": "temperature", "unit": "degC"},
        },
        "_spatial_grades": {
            u: {"grade": "in_room", "reason": "", "evidence_space": space} for u in ("s-1", "s-2")
        },
        "_prov_stores": [{"source_id": u, "kind": "sensor"} for u in ("s-1", "s-2")],
    }


def test_scenario4_agreeing_sensors_are_not_reported_as_conflict():
    """The control, and the reason the tolerance is policy rather than a constant."""
    rec = build_evidence_record(_two_in_one_space(21.0, 21.3), now=NOW)
    assert not rec.conflicts, rec.conflicts


def test_scenario4_disagreement_is_reported_with_both_values():
    """The literal scenario: two sensors in one room, well outside tolerance."""
    rec = build_evidence_record(_two_in_one_space(18.0, 26.0), now=NOW)
    assert rec.conflicts, "two sensors 8 degrees apart in one room raised nothing"
    text = rec.conflicts[0]
    assert "18" in text and "26" in text, f"both values must appear: {text}"
    assert "averaging" in text.lower(), (
        "the answer must say why no single number is given — otherwise a reader assumes one "
        "was withheld arbitrarily"
    )


def test_scenario4_no_average_is_offered_for_a_conflicting_pair():
    """22.0 is the mean of 18 and 26 and is a number neither sensor measured. It must not
    appear as the reported value."""
    from orchestrator.services.evidence.conflict import Reading, detect

    report = detect("Room1", "temperature", [Reading("s-1", 18.0), Reading("s-2", 26.0)], 1.5)
    assert report.conflicting
    assert report.representative() is None, (
        "a representative value was offered for a conflicting pair — averaging a disagreement "
        "produces a figure neither sensor measured"
    )


def test_scenario4_an_agreeing_pair_still_yields_one_value():
    """The counterpart: agreement must remain usable, or the gate costs every multi-sensor
    answer its number."""
    from orchestrator.services.evidence.conflict import Reading, detect

    report = detect("Room1", "temperature", [Reading("s-1", 21.0), Reading("s-2", 21.2)], 1.5)
    assert not report.conflicting
    assert report.representative() == pytest.approx(21.1, abs=0.01)


def test_scenario4_is_advisory_and_moves_no_answer():
    rec = build_evidence_record(_two_in_one_space(18.0, 26.0), now=NOW)
    assert rec.status == AnswerStatus.OBSERVED
