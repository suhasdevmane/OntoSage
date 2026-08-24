# -*- coding: utf-8 -*-
"""The single evidence chokepoint, and the drift that made it silently useless (V6-T02).

T02's objective: sparql, sql, analytics, forecast, deliberate, events, register, capability,
spatial and floor_plan all produce one `EvidenceRecord`, assembled once at the end of the
pipeline rather than ten times in ten lanes.

**Why this file exists in the shape it does.** The chokepoint shipped, was deployed, and did
not work for three of its ten lanes -- and nothing failed. `_LANE_SEMANTICS` was written from
CLAUDE.md's reserved-key list, which documented `sparql_results` and `sql_data`; the pipeline
writes `sparql_result` and `sql_result`. The two most important data lanes could therefore
never be inferred, and every sensor-reading answer was recorded as NOT_ASSESSABLE, "no lane
produced evidence for this answer" -- a confident, wrong statement about the system's own
grounding, produced by the component whose entire job is to describe grounding honestly.

The irony is the lesson. `assemble.py`'s own docstring says it exists because BUG-210 was two
copies of one step drifting apart; T02 then shipped a second copy of the lane list that had
already drifted from the one in `_response_node`. So the load-bearing test here is not that
the record is produced -- it is that **every key in the table is a key the code actually
writes.** A table of names checked against documentation is checked against nothing.
"""

import re
from pathlib import Path

import pytest

from orchestrator.services.evidence.assemble import (
    _LANE_SEMANTICS,
    T02_LANES,
    build_evidence_record,
    infer_lane,
    record_for_response,
)
from shared.models import AnswerStatus, Operation

pytestmark = pytest.mark.unit

REPO = Path(__file__).resolve().parent.parent
ORCH = REPO / "orchestrator"


# ── the drift guard: names must match the code, not the docs ─────────────────


def _keys_written_anywhere() -> set:
    """Every `intermediate_results["x"] = ...` key assigned in the orchestrator."""
    written = set()
    pattern = re.compile(r'intermediate_results\[\s*["\']([a-z_0-9]+)["\']\s*\]\s*=')
    for path in ORCH.rglob("*.py"):
        if "test" in path.parts:
            continue
        written |= set(pattern.findall(path.read_text(encoding="utf-8", errors="ignore")))
    return written


def test_every_lane_key_is_actually_written():
    """THE test. A lane key nothing writes is a lane that can never be identified.

    This is what was wrong: `sql_data` and `sparql_results` appear nowhere in the pipeline,
    so the sql and sparql lanes fell through to "no lane produced evidence" on every turn,
    silently, while the chokepoint reported itself as working.
    """
    written = _keys_written_anywhere()
    missing = [k for k in T02_LANES if k not in written]
    assert not missing, (
        f"lane keys nothing in orchestrator/ ever writes: {missing}. "
        "Grep for the key the lane actually sets and correct the table — do NOT take the "
        "name from CLAUDE.md, which is how this broke the first time."
    )


def test_the_semantics_table_covers_every_declared_lane():
    """A lane added to T02_LANES but not to _LANE_SEMANTICS infers as nothing."""
    graded = {k for k, _op, _st in _LANE_SEMANTICS}
    assert set(T02_LANES) <= graded


def test_all_ten_lanes_are_declared():
    """T02 names ten. Fewer means one was dropped; more means the objective moved."""
    assert len(T02_LANES) == 10
    for lane in ("sparql", "sql", "analytics", "forecast", "deliberate"):
        assert any(k.startswith(lane) for k in T02_LANES), lane


# ── each lane infers, and infers as the right KIND of act ────────────────────


@pytest.mark.parametrize("lane", list(T02_LANES))
def test_each_lane_is_inferred_from_its_own_key(lane):
    assert infer_lane({lane: {"something": 1}}) == lane


def test_a_measurement_is_observed_and_a_forecast_is_predicted():
    """Status is a claim about what the answer IS; blurring these is the whole risk."""
    assert build_evidence_record({"sql_result": [1]}).status is AnswerStatus.OBSERVED
    assert build_evidence_record({"forecast_result": {"v": 1}}).status is AnswerStatus.PREDICTED


def test_a_register_lookup_is_not_a_measurement():
    """A booking or a compliance date is looked up, not measured."""
    rec = build_evidence_record({"register_result": {"x": 1}})
    assert rec.operation is Operation.AUTHORITATIVE_LOOKUP


def test_a_calculation_says_so():
    assert build_evidence_record({"analytics_result": {"v": 2}}).status is AnswerStatus.CALCULATED


def test_the_most_derived_lane_wins():
    """A forecast built on an aggregate is a forecast, not a calculation."""
    rec = build_evidence_record({"analytics_result": {"a": 1}, "forecast_result": {"f": 1}})
    assert rec.status is AnswerStatus.PREDICTED


def test_spatial_is_not_reported_as_a_floor_plan_lookup():
    """The spatial lane used to write floor_plan_result, so geometry it COMPUTED was
    recorded as a drawing it looked at."""
    rec = build_evidence_record({"spatial_result": "3 rooms", "floor_plan_result": "3 rooms"})
    assert rec.operation is Operation.OBSERVATION
    assert infer_lane({"spatial_result": "x", "floor_plan_result": "x"}) == "spatial_result"


# ── failing closed ───────────────────────────────────────────────────────────


def test_a_lane_that_emits_nothing_fails_closed():
    """Silence must never read as success — the acceptance criterion, verbatim."""
    rec = build_evidence_record({})
    assert rec.status is AnswerStatus.NOT_ASSESSABLE
    assert rec.not_assessable_reason


def test_the_reason_says_what_was_missing():
    """ "Not assessable" with no reason is not an answer either."""
    rec = build_evidence_record({})
    assert "no lane" in rec.not_assessable_reason.lower()


def test_a_refusal_lane_is_a_correct_outcome_not_a_gap():
    """Declining on privacy grounds is the system working, and must not read as a failure."""
    rec = build_evidence_record({"privacy_refusal_result": {"reason": "policy"}})
    assert rec.status is AnswerStatus.NOT_ASSESSABLE
    assert "declined by policy" in (rec.not_assessable_reason or "")


def test_assembly_never_raises():
    """A describer that can take down the thing it describes is worse than none."""
    for junk in ({}, {"sql_result": object()}, {"evidence": "not-a-dict"}, {"entities": 5}):
        out = record_for_response(junk)
        assert isinstance(out, dict) and out.get("status")


# ── reserved-key discipline (acceptance criterion 4) ─────────────────────────


def test_no_lane_writes_another_lanes_reserved_key():
    """Each lane key must be written by at most one node function.

    `_spatial_query_node` wrote `floor_plan_result`, which is how a geometry computation came
    to be attributed to the floor-plan lane. Scanned rather than asserted by hand so a future
    shortcut through another lane's channel fails here instead of in an evidence record
    nobody reads.
    """
    src = (ORCH / "workflow" / "_orchestrator.py").read_text(encoding="utf-8")
    # Map each lane key to the node functions that assign it.
    node_re = re.compile(r"^    async def (_[a-z_0-9]+)\(", re.MULTILINE)
    bounds = [(m.group(1), m.start()) for m in node_re.finditer(src)]
    bounds.append(("<eof>", len(src)))
    offenders = []
    for lane in ("floor_plan_result", "spatial_result", "capability_result", "sql_result"):
        assign = re.compile(rf'intermediate_results\[\s*["\']{lane}["\']\s*\]\s*=')
        writers = set()
        for (name, start), (_n2, end) in zip(bounds, bounds[1:]):
            if assign.search(src[start:end]):
                writers.add(name)
        if len(writers) > 1:
            offenders.append(f"{lane} written by {sorted(writers)}")
    assert not offenders, "lanes writing each other's reserved keys: " + "; ".join(offenders)


def test_spatial_result_is_cleared_at_the_end_of_the_turn():
    """Rendered keys must not survive the turn, or a later question is answered with stale
    geometry. floor_plan_result was already in the cleanup list; its sibling must be too."""
    src = (ORCH / "workflow" / "_orchestrator.py").read_text(encoding="utf-8")
    cleanup = src[src.index("_bulky_keys = [") : src.index("_bulky_keys = [") + 1400]
    assert '"spatial_result"' in cleanup


# ── the record reaches the caller (acceptance criterion 3) ───────────────────


def test_the_record_is_exposed_on_both_endpoints():
    """It was on /chat and the websocket but NOT on /v1/chat/completions -- the endpoint
    Open WebUI and every OpenAI-compatible client actually use."""
    main = (ORCH / "main.py").read_text(encoding="utf-8")
    assert '"evidence_record": updated_state.intermediate_results.get("evidence_record")' in main
    assert "ontosage_evidence_record" in main


def test_the_chokepoint_is_wired_into_the_response_node():
    src = (ORCH / "workflow" / "_orchestrator.py").read_text(encoding="utf-8")
    chokepoint = src.index("V6-T02: THE evidence chokepoint")
    response_node = src.index("async def _response_node")
    assert chokepoint > response_node
    assert "record_for_response(" in src


# ── CAVEAT-226: a threshold must name itself ─────────────────────────────────


def test_a_lane_declared_gate_survives_assembly():
    """The regression gate's central rule is that a worsening is a TIGHTENING when a gate
    fired and a REGRESSION when none did. `document_score_floor` is config, not a gate, so a
    suppression it caused named nothing -- raising it from 0.45 to 0.50 produced five
    REGRESSION verdicts that had to be hand-classified, of which three were actually wins.

    The lane now declares `retrieval_floor` on the evidence partial. Assembly must UNION that
    with any gates that fired, not overwrite it, or the record is back to being unable to
    explain its own change.
    """
    rec = build_evidence_record(
        {"capability_result": {"x": 1}, "evidence": {"gates_applied": ["retrieval_floor"]}}
    )
    assert "retrieval_floor" in rec.gates_applied


def test_a_lane_declared_gate_survives_alongside_a_fired_gate():
    from orchestrator.services.evidence.gates import GateVerdict
    from orchestrator.services.evidence.policy import GateMode

    fired = GateVerdict(gate="freshness", passed=False, mode=GateMode.ENFORCING)
    rec = build_evidence_record(
        {"capability_result": {"x": 1}, "evidence": {"gates_applied": ["retrieval_floor"]}},
        gate_verdicts=[fired],
    )
    assert set(rec.gates_applied) >= {"retrieval_floor", "freshness"}


def test_the_retrieval_floor_is_applied_where_the_suppression_can_be_seen():
    """Qdrant applies a server-side threshold and returns only survivors, so "nothing was
    retrieved" and "everything fell below the floor" look identical. The floor is applied in
    Python for exactly that reason -- same query, same top_k, no extra cost."""
    from pathlib import Path

    src = (
        Path(__file__).resolve().parent.parent / "orchestrator" / "agents" / "capability_agent.py"
    ).read_text(encoding="utf-8")
    assert "score_threshold=0.0" in src
    assert "stats.update" in src
    assert '"retrieval_floor"' in src
