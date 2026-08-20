# -*- coding: utf-8 -*-
"""BUG-184: separate the reasoning plan from the execution context.

`plan_hash` is `sha256(plan_fingerprint | sorted candidate IRIs | fetch_window |
time basis)`. The candidate set excludes currently-busy rooms, so on a live
building `plan_hash` MUST differ between runs — it identifies what was computed,
not how the system reasoned. Comparing it across runs therefore measures the
building's state, which is exactly the mistake the T44 invariance probe made.

`plan_fingerprint` — the CQ-IR behavioural core — is the determinism anchor, and
it existed in code but was never surfaced. These tests pin that it is exposed and
that the two mean different things.
"""

from __future__ import annotations

import pytest

from orchestrator.services.deliberation.cqir import (
    CQIR,
    Constraint,
    DecisionKind,
    Direction,
    Hardness,
    TimeBasis,
    TimeSpec,
)

pytestmark = pytest.mark.unit


def _ir(modality="noise", basis=TimeBasis.NOW, raw="Which room is quietest right now?"):
    return CQIR(
        decision=DecisionKind.RANK_ALL,
        constraints=[
            Constraint(modality=modality, direction=Direction.MINIMIZE, hardness=Hardness.SOFT)
        ],
        time=TimeSpec(basis=basis),
        raw_query=raw,
    )


# ── the anchor itself ────────────────────────────────────────────────────────


def test_the_same_question_yields_the_same_fingerprint():
    assert _ir().plan_fingerprint() == _ir().plan_fingerprint()


def test_the_fingerprint_ignores_provenance_text():
    """Wording the model wobbles on must not change the plan identity."""
    a = _ir(raw="Which room is quietest right now?")
    b = _ir(raw="which room is the quietest at the moment")
    assert a.plan_fingerprint() == b.plan_fingerprint()


def test_a_different_criterion_is_a_different_plan():
    assert _ir(modality="noise").plan_fingerprint() != _ir(modality="co2").plan_fingerprint()


def test_a_different_time_basis_is_a_different_plan():
    assert (
        _ir(basis=TimeBasis.NOW).plan_fingerprint()
        != _ir(basis=TimeBasis.FORECAST).plan_fingerprint()
    )


# ── exposure ─────────────────────────────────────────────────────────────────


def test_execution_outcome_carries_both_hashes():
    from orchestrator.services.deliberation.plan_executor import ExecutionOutcome

    names = ExecutionOutcome.__dataclass_fields__
    assert "plan_hash" in names, "provenance id must stay"
    assert "plan_fingerprint" in names, "the determinism anchor must be surfaced"


def test_the_dossier_carries_the_fingerprint():
    from orchestrator.services.deliberation.dossier import EvidenceDossier

    fields = getattr(EvidenceDossier, "model_fields", None) or EvidenceDossier.__fields__
    assert "plan_fingerprint" in fields
    assert "plan_hash" in fields


def test_the_plan_trace_publishes_the_fingerprint():
    """A consumer must be able to compare reasoning across runs without the data context."""
    from pathlib import Path

    src = Path(__file__).resolve().parents[1] / "orchestrator" / "workflow" / "_orchestrator.py"
    text = src.read_text(encoding="utf-8")
    assert '"plan_fingerprint": dossier.get("plan_fingerprint")' in text


def test_plan_hash_still_mixes_in_the_execution_context():
    """Pin the distinction: if plan_hash ever became the bare fingerprint, the
    provenance value (what was actually computed) would be silently lost."""
    from pathlib import Path

    src = (
        Path(__file__).resolve().parents[1]
        / "orchestrator"
        / "services"
        / "deliberation"
        / "plan_executor.py"
    )
    text = src.read_text(encoding="utf-8")
    assert "c.space_iri for c in candidates" in text
    assert "cqir.plan_fingerprint()" in text
