"""The ranking lane must rank the thing that was asked about, and show nothing internal.

Every case here is a QUESTION A PERSON ACTUALLY ASKED, taken from the hand read of 147 live
answers on 2026-09-17 (docs/phase0/phase0_rerun_read.md, class C13 — the most demo-visible
defect in the read, and wrong on all four of its rows). The row number is named on each test
so the answer that motivated it can be found and re-read.

  row 117  a question whose every room this lane can rank came back "I couldn't map part of
           your request (coolest place to work today; pregnant)"
  row  61  a step-free ROUTE question was answered "**Best match: Room 5.22 — Academic
           Office**", with "'step-free route' isn't a sensed modality here — ignored"
  row  58  three rooms offered as a ranking, all at "score 0", every one reading about 24
           against the 0-8 band the same answer quoted
  row  99  an evidence table whose every row began with an IRI, and a privacy line naming a
           policy identifier and a sampling clamp
"""

from __future__ import annotations

import asyncio
import json

import pytest

from orchestrator.services.deliberation.candidates import CoverageLedger
from orchestrator.services.deliberation.capability_schema import AdmissionResult
from orchestrator.services.deliberation.clarify_policy import ClarifyDecision, absorb_unmapped
from orchestrator.services.deliberation.compiler import compile_query
from orchestrator.services.deliberation.coverage_audit import ModalitySpec
from orchestrator.services.deliberation.cqir import (
    CQIR,
    Constraint,
    DecisionKind,
    Direction,
)
from orchestrator.services.deliberation.dossier import (
    build_dossier,
    numeric_guard,
    render_answer,
    render_dossier_details,
)
from orchestrator.services.deliberation.plan_executor import (
    EvidenceCell,
    ExecutionOutcome,
    execute,
    route_question,
)
from orchestrator.services.deliberation.scorer import (
    CriterionScore,
    ScoredCandidate,
    ScoreResult,
)

pytestmark = pytest.mark.unit

MODALITIES = [
    ModalitySpec("noise", ["Sound_Level_Sensor"]),
    ModalitySpec("co2", ["CO2_Level_Sensor"]),
    ModalitySpec("occupancy", ["Occupancy_Count_Sensor"]),
    ModalitySpec("temperature", ["Temperature_Sensor"]),
]

ROW_117 = "I'm pregnant and overheating - where's the coolest place to work today?"
ROW_61 = (
    "I need a step-free route to supervision that avoids the busiest and noisiest areas "
    "around class changeover. Which verified route should I take?"
)
ROW_58 = (
    "I may need to stand, move or take short breaks. Which authorised seating area lets me "
    "do that without blocking circulation?"
)


def _compile(payload, query):
    async def call(prompt: str) -> str:
        return json.dumps(payload)

    return asyncio.run(compile_query(query, MODALITIES, llm_call=call, use_cache=False))


# ── row 117: an unmapped phrase must not block a question that names a modality ──────────


def test_row_117_a_lay_word_inside_an_unmapped_phrase_is_mapped_not_refused():
    """The compile put the whole request in `unmapped`; one of its words names temperature."""
    ir = _compile(
        {
            "decision": "select_one",
            "constraints": [],
            "spatial": [],
            "time": {"basis": "now", "phrase": "today"},
            "time_phrase_unclear": "",
            "unmapped": ["coolest place to work today", "pregnant"],
        },
        ROW_117,
    )
    assert [(c.modality, c.direction) for c in ir.constraints] == [
        ("temperature", Direction.MINIMIZE)
    ], "'coolest' names the low end of temperature — it is not a term this building cannot sense"
    assert ir.is_executable() is False, "'pregnant' is still unmapped at this point"

    # and the drop-and-declare policy then lets the question through, naming what it ignored
    ir, dropped, must_decline = absorb_unmapped(ir)
    assert must_decline is False
    assert dropped == ["pregnant"]
    assert ir.is_executable()


def test_row_117_the_salvaged_phrase_is_what_the_reader_wrote():
    ir = _compile(
        {
            "decision": "select_one",
            "constraints": [],
            "spatial": [],
            "time": {"basis": "now", "phrase": ""},
            "time_phrase_unclear": "",
            "unmapped": ["coolest place to work today"],
        },
        ROW_117,
    )
    assert ir.constraints[0].source_phrase == "coolest place to work today"


def test_a_phrase_asking_to_AVOID_something_is_left_unmapped():
    """ "avoids the noisiest areas" and "the noisiest areas" name the same modality and
    opposite ends of it. Guessing which was meant is how a ranking recommends the worst
    room, so a phrase worded as an avoidance is not salvaged at all."""
    ir = _compile(
        {
            "decision": "select_one",
            "constraints": [],
            "spatial": [],
            "time": {"basis": "now", "phrase": ""},
            "time_phrase_unclear": "",
            "unmapped": ["avoids the noisiest areas"],
        },
        "somewhere that avoids the noisiest areas",
    )
    assert ir.constraints == []
    assert [s.phrase for s in ir.signals] == ["avoids the noisiest areas"]


def test_a_working_ranking_does_not_silently_gain_a_criterion():
    """The salvage runs ONLY when nothing mapped. When something did, the unmapped extras
    are dropped and declared as before — a ranking that works today must not quietly start
    scoring on a word the compiler had set aside."""
    ir = _compile(
        {
            "decision": "select_one",
            "constraints": [
                {"phrase": "quiet", "modality": "noise", "direction": "minimize"},
            ],
            "spatial": [],
            "time": {"basis": "now", "phrase": ""},
            "time_phrase_unclear": "",
            "unmapped": ["somewhere cool"],
        },
        "a quiet, cool room",
    )
    assert [c.modality for c in ir.constraints] == ["noise"]
    assert [s.phrase for s in ir.signals] == ["somewhere cool"]


# ── row 61: a route is not a space ───────────────────────────────────────────────────────


def test_row_61_a_route_question_is_recognised():
    assert route_question(ROW_61)
    assert route_question("Which verified route should I take?")
    assert route_question("How do I get to the lecture theatre?")


def test_a_question_about_a_place_is_not_mistaken_for_a_route():
    for question in (
        ROW_117,
        "Which space has the best conditions for focused work this afternoon?",
        "How long does it take to get from Level 1 to Level 5?",
        "Where's the quietest room right now?",
    ):
        assert not route_question(question), question


def _schema():
    from orchestrator.services.deliberation.capability_schema import (
        STATUS_PRESENT,
        BuildingCapabilitySchema,
        SpaceCoverage,
    )

    space = SpaceCoverage(space_iri="ns#Room0.18", label="Room 0.18", floor="Floor0")
    space.modalities = {
        "noise": {
            "status": STATUS_PRESENT,
            "sensor": "",
            "uuid": "u-1",
            "stored_at": "noise_data",
        }
    }
    return BuildingCapabilitySchema(
        building_id="anybldg", namespace="ns#", spaces=[space], amenities=[]
    )


def test_row_61_the_route_question_declines_without_fetching_anything():
    ir = CQIR(
        decision=DecisionKind.SELECT_ONE,
        constraints=[Constraint(modality="noise", direction=Direction.MINIMIZE)],
        raw_query=ROW_61,
    )

    def _no_adapters(*args, **kwargs):  # pragma: no cover - must never be called
        raise AssertionError("a route question must not reach the data fetch")

    outcome = asyncio.run(
        execute(ir, AdmissionResult(verdict="admit"), _schema(), adapter_getter=_no_adapters)
    )
    assert outcome.score.ranked == [] and outcome.evidence == []
    text = render_answer(_dossier_from(ir, outcome))
    assert "Best match" not in text
    assert "route" in text.lower()
    assert "step-free" in text, "the decline names what the building does hold about routes"
    assert "Name the two places" in text
    for internal in ("modality", "score", "IRI", "policy_"):
        assert internal not in text


def test_the_route_decline_is_the_whole_answer():
    """No empty evidence table under a heading promising working-out."""
    ir = CQIR(decision=DecisionKind.SELECT_ONE, raw_query=ROW_61)
    outcome = ExecutionOutcome(
        score=ScoreResult(ranked=[], excluded=[]),
        ledger=CoverageLedger(),
        candidates=[],
        refusal="no ranking answers a route question",
    )
    doss = _dossier_from(ir, outcome)
    assert render_answer(doss) == "no ranking answers a route question"
    assert render_dossier_details(doss) == ""


# ── row 58: a ranking nobody can act on is not a ranking ─────────────────────────────────


def _flat_outcome():
    """Row 58 as it was served: three rooms, every score 0, every reading ~24 against 0-8."""
    ranked = [
        ScoredCandidate(
            space_iri=f"ns#{label}",
            label=label,
            floor="Floor0",
            total=0.0,
            rank=i,
            criteria=[
                CriterionScore("occupancy", value, 0.0, 1.0, "relative occupancy band (0 = empty)")
            ],
        )
        for i, (label, value) in enumerate(
            [("Room 0.18", 23.933), ("Room 5.57", 23.933), ("Room 4.05", 24.0)], start=1
        )
    ]
    return ExecutionOutcome(
        score=ScoreResult(ranked=ranked, excluded=[]),
        ledger=CoverageLedger(in_scope=234, considered=195, instrumented={"occupancy": 194}),
        candidates=[],
    )


def _dossier_from(ir, outcome, applied_policies=None):
    return build_dossier(
        ir,
        ClarifyDecision(action="proceed"),
        outcome,
        "anybldg",
        applied_policies=applied_policies,
    )


def test_row_58_all_zero_scores_are_not_presented_as_a_recommendation():
    ir = CQIR(
        decision=DecisionKind.SELECT_ONE,
        constraints=[Constraint(modality="occupancy", direction=Direction.MINIMIZE)],
        raw_query=ROW_58,
    )
    doss = _dossier_from(ir, _flat_outcome())
    text = render_answer(doss)
    assert "Best match" not in text
    assert "don't separate these spaces" in text
    assert "23.933" in text, "the readings themselves are still shown"
    assert "score 0" not in text
    assert numeric_guard(text, doss) == []


def test_a_real_ranking_still_names_its_best_match():
    ir = CQIR(
        decision=DecisionKind.SELECT_ONE,
        constraints=[Constraint(modality="noise", direction=Direction.MINIMIZE)],
        raw_query="quietest room?",
    )
    out = _flat_outcome()
    out.score.ranked[0].total = 0.82
    out.score.ranked[1].total = 0.41
    doss = _dossier_from(ir, out)
    text = render_answer(doss)
    assert text.startswith("**Best match: Room 0.18**")
    assert numeric_guard(text, doss) == []


def test_a_score_never_appears_without_its_meaning():
    """ "score 0" told row 58's reader nothing: not the scale, not which end is good."""
    ir = CQIR(
        decision=DecisionKind.SELECT_ONE,
        constraints=[Constraint(modality="noise", direction=Direction.MINIMIZE)],
        raw_query="quietest room?",
    )
    out = _flat_outcome()
    out.score.ranked[0].total = 0.82
    doss = _dossier_from(ir, out)
    text = render_answer(doss)
    assert "out of 1, where 1 fits everything you asked for" in text


# ── row 99: nothing internal reaches the reader ──────────────────────────────────────────


def test_row_99_an_iri_never_reaches_the_evidence_table():
    ir = CQIR(decision=DecisionKind.SELECT_ONE, raw_query="where should I work?")
    out = _flat_outcome()
    out.evidence = [
        EvidenceCell(
            "http://example.org/anybuilding#Room0.01",
            "noise",
            54.877,
            "forecast",
            3.0,
            500,
            "u-1",
            "noise_data",
        )
    ]
    doss = _dossier_from(ir, out)
    assert doss.evidence[0].space == "Room0.01"
    assert "http" not in render_dossier_details(doss)


def test_the_privacy_line_names_no_policy_and_no_clamp():
    ir = CQIR(
        decision=DecisionKind.SELECT_ONE,
        constraints=[Constraint(modality="noise", direction=Direction.MINIMIZE)],
        raw_query="quietest room?",
    )
    out = _flat_outcome()
    out.score.ranked[0].total = 0.82
    doss = _dossier_from(
        ir,
        out,
        applied_policies=[
            "policy_facility_manager_any: resolution clamped to 5s for data 0 min old"
        ],
    )
    text = render_answer(doss)
    assert "Privacy:" in text
    for internal in ("policy_facility_manager_any", "clamped", "resolution"):
        assert internal not in text
    assert doss.applied_policies, "the rule itself stays in the payload, for audit"


def test_bug_868_a_tie_at_the_TOP_of_the_band_is_disclosed_like_a_tie_at_the_bottom():
    """The mirror image of row 58, and the commoner one.

    Measured live 2026-09-23: "Which rooms are both warm and stuffy right now?" compiles as
    list_matching with direction `above` and NO threshold, so the scorer falls back to the band
    edge and every room above it lands at exactly 1.0. The answer read "Best match: Room 2.24 —
    score 1 out of 1, where 1 fits everything you asked for" for a room at 22.675 C in a 20-26
    band. The guard caught `total <= 0` only, so the identical failure at the other end of the
    range walked straight past it and came out sounding like a confident recommendation.
    """
    ir = CQIR(
        decision=DecisionKind.LIST_MATCHING,
        constraints=[Constraint(modality="temperature", direction=Direction.ABOVE)],
        raw_query="which rooms are both warm and stuffy right now?",
    )
    out = _flat_outcome()
    for s in out.score.ranked:
        s.total = 1.0
    doss = _dossier_from(ir, out)
    text = render_answer(doss)
    assert "Best match" not in text, "a tie at 1.0 is not a recommendation"
    assert "don't separate these spaces" in text
    assert "23.933" in text, "the readings themselves are still shown"
    assert numeric_guard(text, doss) == []


def test_a_partial_tie_is_still_a_ranking():
    """The guard must fire on a TIE, not on a high score.

    A ranking whose leader shares its total with nobody is a real recommendation however close
    the field is, and suppressing "Best match" there would throw away a correct answer.
    """
    ir = CQIR(
        decision=DecisionKind.LIST_MATCHING,
        constraints=[Constraint(modality="temperature", direction=Direction.ABOVE)],
        raw_query="which rooms are warm?",
    )
    out = _flat_outcome()
    out.score.ranked[0].total = 1.0
    out.score.ranked[1].total = 0.999
    doss = _dossier_from(ir, out)
    text = render_answer(doss)
    assert text.startswith("**Best match:")
    assert numeric_guard(text, doss) == []
