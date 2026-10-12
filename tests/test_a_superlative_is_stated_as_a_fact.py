"""BUG-1507: "which room had the highest X" is answered with the reading, not a preference score.

Measured 2026-10-10 through the Open WebUI endpoint: "Which room had the highest noise level
yesterday?" came back "Best match: Room 3.57 (score 0.5438 out of 1, where 1 fits everything you
asked for)", no unit. One measured criterion, maximised or minimised, and no record criterion is a
superlative, and its answer is the extreme reading with its unit and period.
"""

from __future__ import annotations

import pytest

from orchestrator.services.deliberation.dossier import (
    DossierConstraint,
    DossierEvidenceRow,
    DossierRanked,
    EvidenceDossier,
    _superlative_lead,
    render_answer,
)

pytestmark = pytest.mark.unit


def _dossier(cons, basis="mean over 2026-10-09"):
    ranked = [
        DossierRanked(
            rank=1, space="Room 3.57", floor="Floor3", total=0.54, criteria={"noise": 51.752}
        ),
        DossierRanked(
            rank=2, space="Room 5.23", floor="Floor5", total=0.53, criteria={"noise": 51.665}
        ),
        DossierRanked(
            rank=3, space="Room 5.10", floor="Floor5", total=0.52, criteria={"noise": 51.628}
        ),
    ]
    evidence = [
        DossierEvidenceRow(
            space=r.space,
            modality="noise",
            value=r.criteria["noise"],
            basis=basis,
            window_hours=24,
            n_points=1439,
            sensor_uuid="u",
            stored_at="noise_data",
        )
        for r in ranked
    ]
    return EvidenceDossier(
        building_id="bx",
        raw_query="q",
        decision="select_one",
        constraints=cons,
        evidence=evidence,
        ranked=ranked,
        coverage_summary="3 of 3",
    )


NOISE_MAX = [DossierConstraint(modality="noise", direction="maximize", hardness="soft")]


def test_a_superlative_over_one_quantity_leads_with_the_reading():
    lead = _superlative_lead(_dossier(NOISE_MAX))
    assert lead.startswith("**Room 3.57 had the highest average noise: 51.752")
    assert "(mean over 2026-10-09)" in lead and "Next: Room 5.23" in lead
    assert "Best match" not in render_answer(_dossier(NOISE_MAX)).splitlines()[0]


def test_a_current_reading_says_has_not_had():
    lead = _superlative_lead(_dossier(NOISE_MAX, basis="recent mean (last readings)"))
    assert "has the highest noise" in lead


@pytest.mark.parametrize(
    "cons",
    [
        [
            DossierConstraint(modality="noise", direction="maximize", hardness="soft"),
            DossierConstraint(modality="co2", direction="minimize", hardness="soft"),
        ],  # two criteria
        [
            DossierConstraint(modality="noise", direction="below", hardness="soft", threshold=50)
        ],  # a filter
    ],
)
def test_a_trade_off_or_a_filter_keeps_the_best_match_wording(cons):
    assert _superlative_lead(_dossier(cons)) == ""
