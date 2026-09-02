# -*- coding: utf-8 -*-
"""The freshness gate has to be CALLED, and calling it must change nothing yet (V6-T16/T55).

`gates.py` implements four gates — freshness, completeness, spatial adequacy, calibration —
each unit-tested against fixtures. Not one of them was ever invoked. The chokepoint reads
`results["gate_verdicts"]` and no lane writes it, so three V6 turns stood marked done with
acceptance criteria about the live system ("a stale series never returns Observed; the age and
the remedy appear in the answer") that could not be true of a function nothing calls. The gap
between "the decision logic exists" and "the system does this" is the whole subject here.

Only freshness is wired, because only freshness has an input. The other three would judge a
field nothing populates and return the SAME failure for every answer in the system — coverage
is always None, every source's spatial grade defaults to NONE, no source declares a
calibration state. Four gates failing on every answer would look like far more caution and be
worth less than nothing, so those are recorded as not-evaluated with the input each awaits.

The load-bearing test in this file is the advisory one. A gate that quietly starts downgrading
answers the moment it is wired is not shadow mode, and the regression gate would report the
resulting wall of changes as breakage.
"""

from datetime import datetime, timedelta, timezone

import pytest

from orchestrator.services.evidence.assemble import build_evidence_record
from shared.models import AnswerStatus, Operation


def _advisory_policy():
    """A policy with freshness explicitly ADVISORY, for tests about the mechanism itself."""
    import tempfile
    from pathlib import Path

    import yaml as _yaml

    from orchestrator.services.evidence import load_policy as _load

    d = Path(tempfile.mkdtemp())
    (d / "evidence_policy.yaml").write_text(
        _yaml.safe_dump({"gates": {"freshness": {"mode": "advisory"}}}), encoding="utf-8"
    )
    return _load("bldgAdvisory", input_dir=d)


def _fired(rec):
    """Gate verdicts recorded on a record, whichever bucket they landed in.

    A gate's verdict goes to `gates_advisory` while it only observes and to `gates_applied`
    once it acts. These tests are about whether the gate RAN, so they must read both — they
    asserted on `gates_advisory` alone and broke the moment freshness began enforcing
    (CAVEAT-361), reporting "the gate is still not being called" about a gate that had just
    downgraded the answer.
    """
    return list(getattr(rec, "gates_applied", []) or []) + list(
        getattr(rec, "gates_advisory", []) or []
    )


pytestmark = pytest.mark.unit

NOW = datetime(2026, 8, 22, 12, 0, 0, tzinfo=timezone.utc)


def _observation(age_minutes: int, **extra):
    when = (NOW - timedelta(minutes=age_minutes)).isoformat()
    results = {
        "sql_result": {"results": {"data": [{"datetime": when, "value": 812.0}]}},
        "uuids": ["u-1"],
        # A resolved MEASURAND. Freshness judges readings, and an observation with no
        # measurand is geometry — a corridor's width does not go stale. Six live wayfinding
        # answers were being flagged "no observation is available for this space" before that
        # scope was tightened, so these fixtures must carry a concept or they test a path the
        # system no longer takes.
        "concepts": [{"brick_classes": ["brick:Air_Temperature_Sensor"]}],
        **extra,
    }
    return build_evidence_record(results, now=NOW)


def test_the_gate_actually_runs_now():
    """The defect this file exists for: the gate was never invoked at all."""
    rec = _observation(60 * 24 * 40)  # forty days old
    assert _fired(rec), (
        "no advisory verdict was recorded for a forty-day-old reading — the freshness gate is "
        "still not being called"
    )
    assert any("freshness" in g for g in _fired(rec))


def test_a_stale_reading_is_named_with_its_age():
    rec = _observation(60 * 24 * 40)
    text = " ".join(_fired(rec))
    assert "freshness" in text
    assert "minutes old" in text, f"the verdict does not state the age: {text!r}"


def test_a_fresh_reading_raises_nothing():
    rec = _observation(2)
    assert not _fired(rec), _fired(rec)


def test_an_advisory_gate_changes_no_answer():
    """The MECHANISM: an advisory verdict must not move the status, however badly it failed.

    Built on an explicitly advisory policy rather than the shipped one. It used the live
    config and so broke the moment freshness was switched to enforcing (CAVEAT-361) — but
    this test was never about freshness's posture, it is about what "advisory" means, and it
    must keep holding whichever gates happen to be enforcing today.
    """
    from orchestrator.services.evidence.gates import apply as apply_gates
    from orchestrator.services.evidence.gates import freshness_gate

    advisory = _advisory_policy()
    verdict = freshness_gate(advisory, "co2", NOW - timedelta(days=400), NOW)
    assert verdict.passed is False
    assert verdict.blocks is False
    assert apply_gates([verdict], AnswerStatus.OBSERVED) is AnswerStatus.OBSERVED


def test_the_enforced_gate_does_move_the_answer():
    """The other half, so the pair documents both postures rather than only the old one."""
    stale = _observation(60 * 24 * 400)
    assert stale.status is AnswerStatus.INFERRED
    assert stale.operation is Operation.OBSERVATION


def test_a_historical_question_is_not_stale_for_being_historical():
    """ "What was the CO2 last March?" is not stale because March was a while ago. The signal is
    the time range the dialogue lane already extracted, not a phrase list."""
    rec = _observation(60 * 24 * 40, time_range={"start": "2026-03-01", "end": "2026-03-31"})
    assert not _fired(rec), _fired(rec)


def test_a_documentary_answer_is_not_judged_on_freshness():
    """A passage from a manual has no observation time and is not a current-status claim.
    Gating it would produce 'no observation is available' on every policy question."""
    rec = build_evidence_record({"capability_result": {"answer": "the policy says ..."}}, now=NOW)
    assert not _fired(rec), _fired(rec)


def test_no_gate_is_left_silently_unrunnable():
    """The awaiting-input list is now EMPTY — every gate has a real input.

    It tracked the shrinking gap as each arrived: spatial_adequacy left when V6-T13's fetcher
    landed, completeness when Wave B wired the cadence path, calibration when V6-T34 fetched
    calibration dates. The mechanism is kept rather than deleted, because a gate added later
    without its input must be RECORDED here rather than left silently absent — that silence is
    exactly how T13/T16/T17 came to be marked done while nothing invoked them (BUG-237).

    So this asserts the list is empty AND that the machinery still exists to populate it.
    """
    from pathlib import Path as _P

    rec = _observation(5)
    assert rec.gates_not_evaluated == [], (
        f"a gate is awaiting an input again: {rec.gates_not_evaluated} — that is fine, but it "
        "must be a deliberate entry with the missing fact named, not a silent absence"
    )
    src = _P("orchestrator/services/evidence/assemble.py").read_text(encoding="utf-8")
    assert "_GATES_AWAITING_INPUT" in src, (
        "the declare-what-cannot-run mechanism was deleted; the next gate without an input "
        "will be indistinguishable from one that passed"
    )
    assert "gates_not_evaluated" in src


def test_the_modality_is_resolved_from_config_not_hardcoded():
    """Per-modality age limits only mean anything if the modality is derived from the
    building's own configuration. A hardcoded map would route bldg1 and nothing else."""
    from pathlib import Path

    src = Path("orchestrator/services/evidence/assemble.py").read_text(encoding="utf-8")
    body = src[src.index("def _modality_of(") : src.index("def _is_current_status_question(")]
    assert "load_modalities" in body, "modality must come from the building's modality config"
    for literal in ("co2", "temperature", "humidity", "occupancy"):
        assert f'"{literal}"' not in body, f"hardcoded modality name {literal!r} in the resolver"


def test_a_gate_failure_cannot_break_the_record():
    """The record describes the answer; a describer that can take down the thing it describes
    is worse than none."""
    import orchestrator.services.evidence.assemble as asm

    original = asm._modality_of
    asm._modality_of = lambda _r: (_ for _ in ()).throw(RuntimeError("boom"))
    try:
        rec = _observation(5)
    finally:
        asm._modality_of = original
    assert rec.status == AnswerStatus.OBSERVED


def test_the_gate_works_with_the_provenance_shape_production_actually_uses():
    """The first version of the attribution fix did nothing in production, and passed its own
    tests while doing it.

    Those tests tagged sources by sensor uuid. The lanes tag them by STORE — a live record
    carries `store:co2_data`, `store:database1`, `ontology` — so the gate found no sensor
    source with a time, fell through to `latest_evidence_at`, and judged the maximum again:
    exactly the behaviour the fix was written to replace. Only a live probe showed it. The
    lesson is in the assertion: attribution must be read from where it exists (the rows), not
    from the shape the record was assumed to have.
    """
    rec = build_evidence_record(
        {
            "sql_result": {
                "results": {
                    "data": [
                        {"uuid": "co2-a", "datetime": "2026-06-01T00:00:00+00:00", "value": 900.0},
                        {"uuid": "temp-b", "datetime": "2026-08-22T11:59:00+00:00", "value": 21.0},
                    ]
                }
            },
            "concepts": [{"brick_classes": ["brick:Air_Temperature_Sensor"]}],
            # Store-level provenance, as the lanes really emit it — no uuid sources at all.
            "_prov_stores": [
                {"source_id": "store:co2_data", "kind": "sensor", "store": "co2_data"},
                {"source_id": "store:database1", "kind": "sensor", "store": "database1"},
            ],
        },
        now=NOW,
    )
    assert _fired(rec), (
        "with store-level provenance the gate saw no per-sensor time and judged the newest "
        "reading — a nearly-three-month-old contributing observation raised nothing"
    )
    assert any("freshness" in g for g in _fired(rec))


def test_the_modality_matches_however_the_class_is_notated():
    """The same Brick class reaches this code in three notations: the HBCO mapping stores full
    IRIs, the concept resolver hands them on as CURIEs (`brick:CO2_Level_Sensor`), and the
    modality config declares bare local names. Handling only IRIs meant nothing ever matched,
    so every modality silently used the DEFAULT age limit — CO2 judged at 15 minutes when its
    configured limit is 5. A per-modality policy that never selects a modality is not a policy.
    """
    from orchestrator.services.evidence.assemble import _modality_of

    for notation in (
        "https://brickschema.org/schema/Brick#CO2_Level_Sensor",
        "brick:CO2_Level_Sensor",
        "CO2_Level_Sensor",
    ):
        got = _modality_of({"concepts": [{"brick_classes": [notation]}]})
        assert got == "co2", f"{notation!r} resolved to {got!r}"


def test_an_observation_with_no_measurand_is_not_judged_on_freshness():
    """Geometry is observed and does not go stale.

    Wayfinding and floor-plan answers have operation=OBSERVATION but read no sensor, so the
    gate produced "no  observation is available for this space" — a verdict with an empty
    modality, which was the tell. Six of the first 41 live advisories were this, and enforcing
    them would have refused "how do I get to the seminar room" for insufficient freshness.
    A corridor's width is not perishable.
    """
    rec = build_evidence_record(
        {
            "spatial_result": {"answer": "Take the lift to level 3; the seminar room is left."},
            "entities": ["seminar room"],
        },
        now=NOW,
    )
    assert not [g for g in _fired(rec) if "freshness" in g], _fired(rec)
