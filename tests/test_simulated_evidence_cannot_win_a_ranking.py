# -*- coding: utf-8 -*-
"""Simulated evidence must not win an operational ranking (V12-04 part 3, R4, case B06).

    B06 — "Simulated candidate scores best; also transform its data and measured data.
           Exclude simulated lineage in operational mode; allow approved measured-data
           summaries."

WHAT THE CODE LOOKED LIKE BEFORE
--------------------------------
`scorer.py`, 392 lines, contained ZERO occurrences of `simulated`, `provenance`,
`admissible` or `eligible`. The ranker could not exclude a simulated candidate. Its origin
was *displayed* in the dossier's evidence table — rendered `yes` / `no` / `undeclared` —
and never acted on. So an attractive simulated room won, and the reader learned otherwise
only by reading a table underneath.

Worse, the flag shown there was resolved per STORE, from a file that has no entry for the
wide `sensor_data` table at all, so in practice it rendered `undeclared`.

WHY EXCLUSION MUST PRECEDE SCORING
----------------------------------
The acceptance says "excluded BEFORE ranking", not annotated after. A candidate that is
scored and then labelled has still won: the annotation only works if someone reads it, and
BUG-475 is what happens when a caveat depends on being read.
"""

from __future__ import annotations

import pytest

pytestmark = pytest.mark.unit

from orchestrator.services.deliberation.candidates import Candidate  # noqa: E402
from orchestrator.services.deliberation.cqir import (  # noqa: E402
    CQIR,
    Constraint,
    DecisionKind,
    Direction,
    Hardness,
)
from orchestrator.services.deliberation.scorer import score_candidates  # noqa: E402
from orchestrator.services.observation_provenance import Origin, ProvenanceVerdict  # noqa: E402

MEASURED = ProvenanceVerdict(Origin.MEASURED, "observation", "before the boundary")
SIMULATED = ProvenanceVerdict(Origin.SIMULATED, "observation", "after the boundary")
UNKNOWN = ProvenanceVerdict(Origin.UNKNOWN, "undeclared", "nothing declares an origin")


def _cqir():
    return CQIR(
        decision=DecisionKind.RANK_ALL,
        constraints=[
            Constraint(
                modality="noise",
                direction=Direction.MINIMIZE,
                hardness=Hardness.SOFT,
                weight=1.0,
            )
        ],
    )


def _cands():
    return [
        Candidate(space_iri="urn:a", label="Room A", floor="3"),
        Candidate(space_iri="urn:b", label="Room B", floor="3"),
    ]


#: Room A is quieter, so it wins on the numbers alone. Every test below turns on whether
#: its evidence is admissible — never on the arithmetic.
VALUES = {"urn:a": {"noise": 35.0}, "urn:b": {"noise": 55.0}}


# ── the thing B06 asks for ───────────────────────────────────────────────────


def test_the_best_scoring_candidate_is_excluded_when_its_evidence_is_simulated():
    r = score_candidates(
        _cqir(), _cands(), VALUES,
        provenance={"urn:a": {"noise": SIMULATED}, "urn:b": {"noise": MEASURED}},
    )
    assert [c.label for c in r.ranked] == ["Room B"], (
        "the simulated candidate won the ranking — this is B06 exactly"
    )
    assert r.excluded_for_provenance == 1


def test_the_exclusion_is_stated_not_silent():
    """A reader must be able to see why the room they expected is missing."""
    r = score_candidates(
        _cqir(), _cands(), VALUES,
        provenance={"urn:a": {"noise": SIMULATED}, "urn:b": {"noise": MEASURED}},
    )
    dropped = next(c for c in r.excluded if c.label == "Room A")
    assert "not admissible" in (dropped.excluded_reason or "")
    assert "noise" in dropped.excluded_reason


def test_it_survives_the_values_being_transformed():
    """B06 says "also transform its data". A conversion or an average does not launder
    origin — the verdict travels with the observation, not with the number."""
    scaled = {"urn:a": {"noise": 35.0 * 0.001}, "urn:b": {"noise": 55.0}}
    r = score_candidates(
        _cqir(), _cands(), scaled,
        provenance={"urn:a": {"noise": SIMULATED}, "urn:b": {"noise": MEASURED}},
    )
    assert [c.label for c in r.ranked] == ["Room B"]


def test_an_undeclared_origin_still_ranks_but_is_not_counted_as_measured():
    """CHANGED DELIBERATELY 2026-09-11, after measuring what the strict reading cost.

    The first version excluded anything not MEASURED, so an UNKNOWN origin was dropped.
    Run against the real executor that produced "ranked 0, excluded 2 (2 for provenance)"
    — every candidate gone, because test fixtures and any building that has not finished
    labelling its points declare nothing.

    That is the wrong trade. R4's concern is that an attractive SIMULATED candidate wins a
    recommendation about the real building. It is not that an undeclared one must be
    erased, and a check that deletes most rankings is a check people switch off.

    So an unknown still ranks — but it is NOT counted as measured coverage, so nothing
    here claims it is a measurement.
    """
    r = score_candidates(
        _cqir(), _cands(), VALUES,
        provenance={"urn:a": {"noise": UNKNOWN}, "urn:b": {"noise": MEASURED}},
    )
    assert [c.label for c in r.ranked] == ["Room A", "Room B"]
    assert r.excluded_for_provenance == 0
    assert r.measured_candidates == 1, (
        "an undeclared origin was counted as measured coverage — silence is not evidence"
    )


# ── and the things it must not break ─────────────────────────────────────────


def test_measured_evidence_ranks_normally():
    r = score_candidates(
        _cqir(), _cands(), VALUES,
        provenance={"urn:a": {"noise": MEASURED}, "urn:b": {"noise": MEASURED}},
    )
    assert [c.label for c in r.ranked] == ["Room A", "Room B"]
    assert r.excluded_for_provenance == 0
    assert r.measured_candidates == 2


def test_scenario_mode_admits_simulated_and_says_so():
    """The review allows an explicit scenario mode, with labelling. It exists so a
    development building can still be demonstrated — but never by default."""
    r = score_candidates(
        _cqir(), _cands(), VALUES,
        provenance={"urn:a": {"noise": SIMULATED}, "urn:b": {"noise": MEASURED}},
        evidence_mode="scenario",
    )
    assert [c.label for c in r.ranked] == ["Room A", "Room B"]
    assert r.evidence_mode == "scenario"


def test_operational_is_the_default():
    """The safe reading must be the one you get without thinking about it."""
    r = score_candidates(_cqir(), _cands(), VALUES)
    assert r.evidence_mode == "operational"


def test_omitting_provenance_changes_nothing():
    """This must not become a guard that excludes everything the moment a caller forgets
    an argument — that would take out every ranking in the system at once."""
    r = score_candidates(_cqir(), _cands(), VALUES, provenance=None)
    assert [c.label for c in r.ranked] == ["Room A", "Room B"]
    assert r.excluded_for_provenance == 0


def test_measured_coverage_is_not_inflated_by_simulated_points():
    """The acceptance's second half. `measured_candidates` counts admissible evidence, so
    a ranking cannot report broad coverage that is mostly generated."""
    r = score_candidates(
        _cqir(), _cands(), VALUES,
        provenance={"urn:a": {"noise": SIMULATED}, "urn:b": {"noise": MEASURED}},
    )
    assert r.measured_candidates == 1, "simulated evidence was counted as measured coverage"


def test_a_modality_nobody_asked_about_does_not_exclude():
    """Only the criteria this question actually uses can make a candidate inadmissible.
    Judging on an irrelevant modality would drop rooms for no reason the reader can see."""
    r = score_candidates(
        _cqir(), _cands(), VALUES,
        provenance={
            "urn:a": {"noise": MEASURED, "co2": SIMULATED},
            "urn:b": {"noise": MEASURED},
        },
    )
    assert [c.label for c in r.ranked] == ["Room A", "Room B"]
