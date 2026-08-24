# -*- coding: utf-8 -*-
"""Wave A: the ten audit-flagged modules must be REACHABLE, not merely present.

The 2026-08-23 audit (tasks/V6_AUDIT_2026_08_23.md) found ten V6 turns marked done whose
modules nothing imported. Every one had passing unit tests, which is precisely why the gap
survived: existence was tested, reachability was not. This file tests reachability and the
first observable behaviour of each wiring — and it does so through `build_evidence_record`
or the source of the live call site, never through the module alone.

Advisory discipline holds throughout: none of these wirings may change an answer's status.
"""

from datetime import datetime, timezone
from pathlib import Path

import pytest

from orchestrator.services.evidence.assemble import build_evidence_record
from shared.models import AnswerStatus

pytestmark = pytest.mark.unit

REPO = Path(__file__).resolve().parent.parent
NOW = datetime(2026, 8, 23, 12, 0, 0, tzinfo=timezone.utc)


# ── T18: conflicting sensors are reported, never averaged away ───────────────


def _two_sensor_results(v1, v2, kind="temperature", same_space=True):
    """Two sensors, same modality, and — decisive for T18 — the SAME evidence space.

    The first wiring grouped by modality alone and reported 90 different rooms' thermometers
    as one 9.53-degree "conflict": the building's ordinary spatial variation dressed up as a
    sensor fault. Comparability requires an assertion the sensors measure the same thing, and
    the only such assertion on the bus is the spatial grades' evidence_space.
    """
    space = "http://x#Room1"
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
            "s-1": {"label": "A", "kind": kind, "unit": "degC"},
            "s-2": {"label": "B", "kind": kind, "unit": "degC"},
        },
        "_spatial_grades": {
            "s-1": {"grade": "in_room", "reason": "", "evidence_space": space},
            "s-2": {
                "grade": "in_room",
                "reason": "",
                "evidence_space": space if same_space else "http://x#Room2",
            },
        },
        "entities": ["Room 1"],
    }


def test_disagreeing_sensors_land_on_the_record():
    """Scenario 4. Policy tolerance for temperature is 1.5 degC; a 6-degree spread is a
    conflict, and the record must carry it rather than an average."""
    rec = build_evidence_record(_two_sensor_results(19.0, 25.0), now=NOW)
    assert rec.conflicts, "a 6-degree spread between comparable sensors raised nothing"
    assert (
        "19" in rec.conflicts[0] and "25" in rec.conflicts[0]
    ), "the conflict must show BOTH values — averaging them away is the defect"


def test_agreeing_sensors_raise_nothing():
    rec = build_evidence_record(_two_sensor_results(21.0, 21.4), now=NOW)
    assert not rec.conflicts


def test_sensors_in_different_rooms_are_never_a_conflict():
    """A 6-degree difference between two ROOMS is a building, not a fault. The live probe
    caught the first wiring reporting exactly that across 90 sensors."""
    rec = build_evidence_record(_two_sensor_results(19.0, 25.0, same_space=False), now=NOW)
    assert not rec.conflicts, "different spaces were compared as though they measured one thing"


def test_an_unjudged_set_is_not_reported_as_agreement():
    """No declared tolerance for an unknown modality → unjudged, and unjudged is silence,
    not a clean bill (ConflictReport.judged exists for exactly this)."""
    rec = build_evidence_record(_two_sensor_results(1.0, 99.0, kind="unknowable_modality"), now=NOW)
    assert not rec.conflicts


def test_conflict_is_advisory_and_changes_no_answer():
    rec = build_evidence_record(_two_sensor_results(19.0, 25.0), now=NOW)
    assert rec.status == AnswerStatus.OBSERVED


# ── T28: the record states the tier that answered ────────────────────────────


def test_the_access_tier_is_stamped_from_the_role():
    rec = build_evidence_record({**_two_sensor_results(21.0, 21.2), "user_role": "admin"}, now=NOW)
    assert rec.access_tier, "user_role was on the bus and no tier was recorded"


def test_no_role_means_no_tier_claim():
    rec = build_evidence_record(_two_sensor_results(21.0, 21.2), now=NOW)
    assert rec.access_tier == "", "a tier was invented for an absent role"


# ── T33: a causal diagnosis needs support ────────────────────────────────────


def test_an_unlicensed_causal_claim_is_flagged_on_a_diagnosis():
    rec = build_evidence_record(
        {
            "diagnosis_result": {"response": "The corridor is hot because the AHU damper failed."},
            "sensor_metadata": {"s-1": {"kind": "temperature"}},
        },
        now=NOW,
    )
    hits = [g for g in rec.gates_advisory if "causal" in g.lower()]
    assert hits, "a 'because' claim on correlational evidence raised no causal verdict"


def test_a_non_diagnosis_answer_is_never_causally_judged():
    """The guard runs on the diagnosis lane only — its OUTPUT is the causal claim. Prose on
    other lanes saying 'because' is explanation, not diagnosis."""
    rec = build_evidence_record(
        {"capability_result": {"answer": "Bins are emptied daily because of the contract."}},
        now=NOW,
    )
    assert not [g for g in rec.gates_advisory if "causal" in g.lower()]


# ── T39: what a ranking left out reaches the record ──────────────────────────


def test_dossier_exclusions_become_omitted_criteria():
    rec = build_evidence_record(
        {
            "deliberate_result": {"answer": "Room 2.14 is the best option."},
            "evidence_dossier": {
                "coverage_excluded": [
                    {"space": "Room 3.01", "reason": "no data for co2"},
                    {"space": "Room 3.02", "reason": "restricted for this role"},
                ]
            },
        },
        now=NOW,
    )
    assert len(rec.omitted_criteria) == 2
    reasons = {o.reason.value for o in rec.omitted_criteria}
    assert "missing" in reasons and "restricted" in reasons, reasons


# ── T40 / T14 / T08 / T19 / T42: the live call sites exist ───────────────────


def test_the_sql_lane_detects_and_applies_recurring_windows():
    src = (REPO / "orchestrator" / "agents" / "sql_agent.py").read_text(encoding="utf-8")
    assert "detect_mask" in src, "T40: the sql lane never consults time_windows"
    assert "hour_predicate" in src, "T40: the union query takes no hour predicate"
    assert "_hour_mask.covers(" in src, "T40: rows are not re-filtered in Python"
    assert '"window_mask"' in src, "T40: the applied window is not reported on the result"


def test_the_window_reaches_the_evidence_record():
    rec = build_evidence_record(
        {
            "sql_result": {
                "results": {"data": [{"uuid": "u", "datetime": NOW.isoformat(), "value": 1}]},
                "window_mask": "overnight",
            },
            "time_range": {"start": "2026-08-01", "end": "2026-08-22"},
        },
        now=NOW,
    )
    assert "overnight" in rec.requested_period


def test_the_answer_names_its_proxy():
    src = (REPO / "orchestrator" / "workflow" / "_orchestrator.py").read_text(encoding="utf-8")
    assert "_append_spatial_basis" in src, "T14: no spatial-basis note on the response path"
    assert "adequacy_note" in src, "T14: narration is still uncalled"


def test_sensor_health_has_an_endpoint():
    src = (REPO / "orchestrator" / "main.py").read_text(encoding="utf-8")
    assert "/api/v1/admin/sensors/health" in src, "T08: no health endpoint"
    assert "assess_sensor" in src, "T08: the endpoint does not use the sensor_health module"
    assert (
        "not probed per sensor" in src
    ), "T08: the wide store must be declared not-probed, never silently guessed"


def test_analytics_states_its_observational_basis():
    src = (REPO / "orchestrator" / "services" / "analytics_engine.py").read_text(encoding="utf-8")
    assert "_attach_observational_basis" in src, "T19: no basis attachment at the dispatch"
    assert (
        "unknown (no declared cadence" in src
    ), "T19: unknown coverage must be SAID, not implied as full"


def test_forecasts_consult_configuration_history():
    src = (REPO / "orchestrator" / "services" / "evidence" / "assemble.py").read_text(
        encoding="utf-8"
    )
    assert (
        "_trend_integrity_verdict" in src and "assess_trend" in src
    ), "T42/T07: trends never consult configuration history"
