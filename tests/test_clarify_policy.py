"""V4-T21 tests — clarify-or-proceed policy, parked-plan binding, and the BUG-146 binder."""

from __future__ import annotations

import pytest

from orchestrator.services.deliberation.capability_schema import (
    ADMIT,
    CLARIFY,
    DECLINE,
    AdmissionResult,
    ClarifyQuestion,
)
from orchestrator.services.deliberation.clarify_policy import (
    bind_answer,
    build_assumptions,
    decide,
)
from orchestrator.services.deliberation.cqir import (
    CQIR,
    Constraint,
    DecisionKind,
    Direction,
    SpatialRelation,
    ThresholdSource,
    TimeBasis,
    TimeSpec,
)
from orchestrator.services.disambiguation_service import DisambiguationService

pytestmark = pytest.mark.unit


def _ir(**kwargs):
    defaults = dict(
        decision=DecisionKind.SELECT_ONE,
        constraints=[
            Constraint(modality="noise", direction=Direction.MINIMIZE, source_phrase="quiet")
        ],
    )
    defaults.update(kwargs)
    return CQIR(**defaults)


# ── decide() ──────────────────────────────────────────────────────────────────


def test_admit_proceeds_with_declared_cited_assumptions():
    d = decide(_ir(), AdmissionResult(verdict=ADMIT))
    assert d.action == "proceed"
    texts = " | ".join(a.text for a in d.assumptions)
    assert "quiet" in texts and "30-70" in texts  # anchor band declared
    assert any("WHO" in a.source for a in d.assumptions)
    assert any("weighted equally" in a.text for a in d.assumptions)


def test_user_threshold_is_not_an_assumption():
    ir = _ir(
        constraints=[
            Constraint(
                modality="co2",
                direction=Direction.BELOW,
                threshold=800,
                threshold_source=ThresholdSource.USER,
            )
        ]
    )
    d = decide(ir, AdmissionResult(verdict=ADMIT))
    assert not any("co2" in a.text for a in d.assumptions)


def test_forecast_default_horizon_declared():
    ir = _ir(time=TimeSpec(basis=TimeBasis.FORECAST, source_phrase="tomorrow"))
    d = decide(ir, AdmissionResult(verdict=ADMIT))
    assert any("24h ahead" in a.text for a in d.assumptions)


def test_clarify_parks_the_plan_with_one_question():
    q = ClarifyQuestion(slot="floor", question="Which floor?", options=["floor0", "floor1"])
    d = decide(_ir(), AdmissionResult(verdict=CLARIFY, question=q, reason="unknown floor"))
    assert d.action == "ask" and d.question is q
    assert d.pending["type"] == "deliberate:floor"
    assert d.pending["options"] == ["floor0", "floor1"]
    assert d.pending["cqir"]["constraints"][0]["modality"] == "noise"


def test_decline_passes_through():
    d = decide(_ir(), AdmissionResult(verdict=DECLINE, reason="no backed sensors"))
    assert d.action == "decline" and "no backed sensors" in d.reason


def test_clarify_off_forces_first_option_bindable(monkeypatch):
    """V4-T29 ablation switch: bindable ask becomes a declared forced bind."""
    monkeypatch.setenv("DELIBERATE_CLARIFY_OFF", "1")
    q = ClarifyQuestion(slot="floor", question="Which floor?", options=["floor0", "floor1"])
    d = decide(_ir(), AdmissionResult(verdict=CLARIFY, question=q, reason="unknown floor"))
    assert d.action == "forced_bind"
    assert "floor0" in d.reason
    assert d.pending["options"] == ["floor0", "floor1"]


def test_clarify_off_declines_unbindable(monkeypatch):
    """Signals-slot asks (no options) can't be guessed — clarify-off declines."""
    monkeypatch.setenv("DELIBERATE_CLARIFY_OFF", "1")
    q = ClarifyQuestion(slot="signals", question="Rephrase?", options=[])
    d = decide(_ir(), AdmissionResult(verdict=CLARIFY, question=q, reason="vague phrase"))
    assert d.action == "decline" and "clarify-off" in d.reason


def test_clarify_off_absent_keeps_ask(monkeypatch):
    monkeypatch.delenv("DELIBERATE_CLARIFY_OFF", raising=False)
    q = ClarifyQuestion(slot="floor", question="Which floor?", options=["floor0"])
    d = decide(_ir(), AdmissionResult(verdict=CLARIFY, question=q, reason="unknown floor"))
    assert d.action == "ask"


# ── bind_answer() ─────────────────────────────────────────────────────────────


def _pending(slot="floor", options=("floor0", "floor1")):
    q = ClarifyQuestion(slot=slot, question="?", options=list(options))
    return decide(_ir(), AdmissionResult(verdict=CLARIFY, question=q)).pending


def test_bind_by_number_text_and_unique_substring():
    assert bind_answer(_pending(), "2").spatial[0].anchor == "floor1"
    assert bind_answer(_pending(), "floor0").spatial[0].anchor == "floor0"
    assert bind_answer(_pending(), "the one on 1 please") is None  # ambiguous digits inside text
    amb = bind_answer(_pending(slot="amenity", options=("DrinkingWater", "StudyArea")), "water")
    assert amb.spatial[0].relation == SpatialRelation.NEAR_AMENITY
    assert amb.spatial[0].anchor == "DrinkingWater"


def test_bound_plan_is_resumable_not_restarted():
    resumed = bind_answer(_pending(), "1")
    assert resumed.constraints[0].modality == "noise"  # original program intact
    assert resumed.is_executable()


def test_unbindable_replies_return_none_never_guess():
    assert bind_answer(_pending(), "9") is None  # out of range
    assert bind_answer(_pending(), "somewhere nice") is None  # matches nothing
    assert bind_answer({"slot": "signals", "options": [], "cqir": {}}, "1") is None


# ── absorb_unmapped (graceful degradation) ───────────────────────────────────


def test_mixed_unmapped_drops_and_declares():
    from orchestrator.services.deliberation.clarify_policy import absorb_unmapped
    from orchestrator.services.deliberation.cqir import AmbiguitySignal

    ir = _ir(signals=[AmbiguitySignal(kind="unmapped_term", phrase="air ionisation")])
    out, dropped, decline = absorb_unmapped(ir)
    assert not decline and dropped == ["air ionisation"]
    assert out.signals == [] and out.is_executable()


def test_pure_unmapped_declines_never_loops():
    from orchestrator.services.deliberation.clarify_policy import absorb_unmapped
    from orchestrator.services.deliberation.cqir import AmbiguitySignal

    ir = _ir(
        constraints=[], signals=[AmbiguitySignal(kind="unmapped_term", phrase="wifi strength")]
    )
    _, dropped, decline = absorb_unmapped(ir)
    assert decline and dropped == ["wifi strength"]


def test_locational_unmapped_phrase_stays_blocking():
    from orchestrator.services.deliberation.clarify_policy import absorb_unmapped
    from orchestrator.services.deliberation.cqir import AmbiguitySignal

    ir = _ir(signals=[AmbiguitySignal(kind="unmapped_term", phrase="near the aquarium")])
    out, dropped, decline = absorb_unmapped(ir)
    assert not decline and dropped == []
    assert out.signals  # kept — dropping a locational requirement would change intent


# ── the BUG-146 binder itself ────────────────────────────────────────────────


def test_extract_clarification_answer_exists_and_parses():
    svc = DisambiguationService()
    out = svc.extract_clarification_answer("2", "sensor_disambiguation")
    assert out == {"selected_option_index": 2}
    out = svc.extract_clarification_answer("floor 1, near zone 5.01", "deliberate:floor")
    assert out["floor"] == "1" and out["zone"] == "5.01"
    assert out["deliberate_reply"] == "floor 1, near zone 5.01"
    assert svc.extract_clarification_answer("", "any") is None
    assert svc.extract_clarification_answer("no numbers here", "sensor_disambiguation") is None
