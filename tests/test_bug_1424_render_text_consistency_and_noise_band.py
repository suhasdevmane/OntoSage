# -*- coding: utf-8 -*-
"""BUG-1424 follow-up: the RENDERED TEXT must never contradict itself, and the WHO noise
band must never be mistaken for a code defect that calls 60 dB "quiet".

BUG-1424 was reported from a live answer that read (abbreviated):
    "(noise: 60.342, occupancy_status: 0.776) (no data: occupancy_status)"
-- a value AND a "no data" marker for the SAME modality in one row.

`tests/test_g5_dossier_row_does_not_contradict_itself.py` (G5, 2026-10-04) already pins the
fix at the STRUCTURE level: `build_dossier`'s `DossierRanked.criteria` / `.data_gaps` can no
longer disagree about one modality. This file closes the gap between that structural fix and
what a reader actually sees by exercising `render_answer()` itself -- the function whose
f-string literally produces the `(no data: ...)` clause (dossier.py, `gaps = f" (no data:
{...})"`) -- end to end, and by checking the *second* half of BUG-1424's report: that calling
a 60 dB reading "quiet" is not something any code path here does.

Investigated and NOT separately fixed: there is no adjective-generating code anywhere in
`render_answer`/`render_dossier_details` that labels a SPECIFIC reading "quiet", "loud" or
"comfortable" -- grep confirms it. The word "quiet" does appear in the rendered answer, but
only once, inside the Assumptions clause that `clarify_policy.build_assumptions` writes to
disclose how the user's own lay term was interpreted ("'quiet' scored as minimize noise
against the 30-70 band") -- that is deliberate honesty, not a verdict on any one room's
reading, and it is what the bug report's paraphrase ("a 30-70 band that calls 60 dB quiet")
was actually describing. The band itself, `DEFAULT_ANCHORS["noise"]` in scorer.py, is a
cited WHO guideline (30-70 dB(A) indoor); `_utility()` under MINIMIZE direction scores
60.342 dB at (70-60.342)/40 = 0.24 -- a LOW utility, i.e. the scorer already treats 60 dB as
closer to the bad end of the band than the good one, never as "quiet". Nothing here is a
threshold to move to the TTL or StandardsEngine -- StandardsEngine carries no noise/sound
parameter at all (checked), and the WHO citation is a real, defensible standard already
pinned by `tests/test_scorer_unanchored.py::test_comfort_modalities_are_anchored_and_cited`.
"""
from __future__ import annotations

import re

import pytest

from orchestrator.services.deliberation.candidates import Candidate, CoverageLedger
from orchestrator.services.deliberation.capability_schema import AdmissionResult
from orchestrator.services.deliberation.clarify_policy import decide
from orchestrator.services.deliberation.cqir import CQIR, Constraint, DecisionKind, Direction
from orchestrator.services.deliberation.dossier import build_dossier, render_answer
from orchestrator.services.deliberation.plan_executor import ExecutionOutcome
from orchestrator.services.deliberation.scorer import (
    DEFAULT_ANCHORS,
    CriterionScore,
    ScoredCandidate,
    ScoreResult,
    _utility,
)

pytestmark = pytest.mark.unit

NS = "ns#"


def _outcome_with_duplicate_constraint():
    """The exact live shape: occupancy_status appears twice in one candidate's criteria
    list -- once resolved to a real value, once to None -- and data_gaps records the None
    pass. Values match the live report verbatim (60.342, 0.776)."""
    ranked = [
        ScoredCandidate(
            space_iri=f"{NS}A",
            label="Room 3.46 — Academic Office",
            floor="floor3",
            total=0.78,
            rank=1,
            criteria=[
                CriterionScore("noise", 60.342, 0.24, 1.0, "WHO guideline band 30-70 dB(A) indoor"),
                CriterionScore("occupancy_status", 0.776, 0.9, 1.0, "relative occupancy band"),
                CriterionScore("occupancy_status", None, None, 1.0, "", "no data"),
            ],
            data_gaps=["occupancy_status"],
        ),
    ]
    score = ScoreResult(ranked=ranked, excluded=[], top1_stable_under_weight_perturbation=True)
    ledger = CoverageLedger(in_scope=1, considered=1, instrumented={"noise": 1})
    cands = [Candidate(space_iri=f"{NS}A", label="Room 3.46 — Academic Office", floor="floor3")]
    return ExecutionOutcome(
        score=score, ledger=ledger, candidates=cands, evidence=[], forecasts=[], plan_hash="x"
    )


def _dossier():
    ir = CQIR(
        decision=DecisionKind.LIST_MATCHING,
        constraints=[
            Constraint(modality="noise", direction=Direction.MINIMIZE, source_phrase="quiet"),
            Constraint(
                modality="occupancy_status", direction=Direction.MINIMIZE, source_phrase="free"
            ),
        ],
        raw_query="quiet rooms that are free?",
    )
    d = decide(ir, AdmissionResult(verdict="admit"))
    return build_dossier(ir, d, _outcome_with_duplicate_constraint(), "anybldg")


class TestTheRenderedTextNeverContradictsItself:
    """The structural fix (G5) is necessary but not sufficient -- this exercises the
    actual f-string that produced the live defect."""

    def test_no_row_names_a_modality_as_both_a_value_and_a_gap(self):
        doss = _dossier()
        text = render_answer(doss)
        # "occupancy_status" must appear with its value (0.776) ...
        assert "occupancy_status: 0.776" in text or "occupancy_status" in text
        # ... and must NEVER also be listed in a "no data: ..." clause in the same answer.
        for gap_clause in re.findall(r"no data: ([^)]*)", text):
            gap_modalities = {m.strip() for m in gap_clause.split(",")}
            assert "occupancy_status" not in gap_modalities, (
                "occupancy_status carries a real value (0.776) and must not also be "
                f"reported as a data gap. Full text:\n{text}"
            )

    def test_a_modality_with_no_value_anywhere_still_renders_as_a_gap(self):
        """The fix must not swallow a REAL gap -- only a contradicted one."""
        out = _outcome_with_duplicate_constraint()
        out.score.ranked[0].criteria = [
            CriterionScore("noise", 60.342, 0.24, 1.0, "WHO guideline band 30-70 dB(A) indoor"),
            CriterionScore("co2", None, None, 1.0, "", "no data"),
        ]
        out.score.ranked[0].data_gaps = ["co2"]
        ir = CQIR(decision=DecisionKind.LIST_MATCHING, constraints=[], raw_query="x")
        d = decide(ir, AdmissionResult(verdict="admit"))
        doss = build_dossier(ir, d, out, "anybldg")
        text = render_answer(doss)
        assert "no data: co2" in text


class TestTheNoiseBandDoesNotCallSixtyDecibelsQuiet:
    """BUG-1424's report also claimed "'quiet' scored against a 30-70 band that calls 60 dB
    quiet". Investigated: no code path attaches the word "quiet" to a reading, and the WHO
    band itself scores 60 dB as poor (low utility), not good."""

    def test_sixty_db_scores_closer_to_the_bad_end_than_the_good_one(self):
        anchor = DEFAULT_ANCHORS["noise"]
        constraint = Constraint(modality="noise", direction=Direction.MINIMIZE)
        utility = _utility(constraint, 60.342, anchor)
        # 60.342 is most of the way from 30 (best) to 70 (worst): (70-60.342)/40 = 0.241.
        assert utility == pytest.approx(0.2415, abs=1e-3)
        assert utility < 0.5, "60 dB must not score as closer to quiet than to loud"

    def test_the_rendered_answer_never_calls_a_reading_quiet(self):
        """ "quiet" DOES appear in the rendered text -- in the Assumptions clause, which
        discloses how the user's own word was interpreted ("'quiet' scored as minimize
        noise against the 30-70 band"). That disclosure is deliberate honesty (clarify_
        policy.build_assumptions) and is not the defect BUG-1424 reported. What must never
        happen is "quiet" being used as a VERDICT attached to this specific reading --
        e.g. a per-space row reading "60.342 (quiet)" or "quiet: 60.342"."""
        doss = _dossier()
        text = render_answer(doss)
        assert (
            "scored as" in text and "quiet" in text
        ), "the honest disclosure of how 'quiet' was interpreted should still be present"
        # the per-row list must show the bare value, never the word "quiet" stapled to it
        row_lines = [ln for ln in text.splitlines() if "noise: 60.342" in ln]
        assert row_lines, f"expected a per-row noise value line in:\n{text}"
        for ln in row_lines:
            assert "quiet" not in ln.lower(), f"a per-row value must not carry a verdict: {ln}"

    def test_the_band_is_a_cited_real_standard_not_a_bare_number(self):
        """Nothing here is a magic number to move: the band carries its citation, same as
        every other comfort modality (pinned by test_scorer_unanchored.py)."""
        anchor = DEFAULT_ANCHORS["noise"]
        assert "WHO" in anchor.citation
        assert anchor.lo == 30.0 and anchor.hi == 70.0
