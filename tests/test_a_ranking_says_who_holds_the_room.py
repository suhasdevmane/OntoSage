# -*- coding: utf-8 -*-
"""BUG-716 — a ranking that is usable, in the reader's words.

Three separate ways the ranking lane offered a room nobody could act on, all measured on
the 2026-09-17 stakeholder read and all reproduced here with the questions as asked:

* **row 99** answered an undergraduate looking for "a calm, relatively quiet place" with
  three research laboratories, and **row 58** answered "which authorised seating area" with
  an academic office. Every figure was real. Neither room is one the asker may walk into,
  and the answers said nothing either way.
* **row 58** also printed occupancy readings of about 24 beside its own stated "0-8 band".
  The utilities had all saturated at the end of the band, so the order came from a
  tie-break and meant nothing — and the answer presented it as a recommendation.
* **row 119** told its reader "not an occupied space — name it to include it
  (Mechanical_Room)". `Mechanical_Room` is the name of a class in a schema; it tells a
  person what the system is made of, not what the building is like.

And one more, from the same lane's time handling: **row 99** asked about "next Wednesday
after 2 p.m." and was told the ranking was "forecast 24h ahead from recent history" — a
sentence that reads as though next Wednesday had been projected.
"""

from __future__ import annotations

import pytest

from orchestrator.services.deliberation.candidates import (
    Candidate,
    CoverageLedger,
    access_word,
    asks_where_i_may_go,
    enumerate_candidates,
)
from orchestrator.services.deliberation.capability_schema import AdmissionResult
from orchestrator.services.deliberation.clarify_policy import decide
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
)
from orchestrator.services.deliberation.plan_executor import (
    EvidenceCell,
    ExecutionOutcome,
    _out_of_band_notes,
)
from orchestrator.services.deliberation.scorer import (
    DEFAULT_ANCHORS,
    CriterionScore,
    ScoredCandidate,
    ScoreResult,
)

pytestmark = pytest.mark.unit

NS = "ns#"

CALM_PLACE = (
    "I'm coming to Abacws next Wednesday after 2 p.m. for about 90 minutes. Where am I "
    "most likely to find a calm, relatively quiet place with low foot traffic and "
    "reasonable measured temperature and air-quality indicators, close to my 4 p.m. class?"
)
SEATING_AREA = (
    "I may need to stand, move or take short breaks. Which authorised seating area lets "
    "me do that without blocking circulation?"
)
SURVEY = "Which space has the best conditions for focused work this afternoon?"


def _outcome(query: str, modality: str, values, kinds):
    """A ranking over three spaces, each with one criterion and its own Brick classes."""
    anchor = DEFAULT_ANCHORS[modality]
    ranked = [
        ScoredCandidate(
            space_iri=f"{NS}{i}",
            label=f"Room {i}",
            floor="Floor4",
            total=round(0.9 - 0.01 * i, 4),
            rank=i + 1,
            criteria=[CriterionScore(modality, v, 0.5, 1.0, anchor.citation)],
        )
        for i, v in enumerate(values)
    ]
    cands = [
        Candidate(space_iri=f"{NS}{i}", label=f"Room {i}", floor="Floor4", kinds=tuple(k))
        for i, k in enumerate(kinds)
    ]
    evidence = [
        EvidenceCell(f"{NS}{i}", modality, v, "recent mean", 24.0, 12, f"u{i}", "t")
        for i, v in enumerate(values)
    ]
    return ExecutionOutcome(
        score=ScoreResult(ranked=ranked, excluded=[]),
        ledger=CoverageLedger(in_scope=3, considered=3, instrumented={modality: 3}),
        candidates=cands,
        evidence=evidence,
        band_notes=_out_of_band_notes(ScoreResult(ranked=ranked, excluded=[]), DEFAULT_ANCHORS),
        plan_hash="h",
    )


def _render(query: str, modality: str, values, kinds) -> tuple:
    ir = CQIR(
        decision=DecisionKind.SELECT_ONE,
        constraints=[Constraint(modality=modality, direction=Direction.MINIMIZE)],
        raw_query=query,
    )
    outcome = _outcome(query, modality, values, kinds)
    doss = build_dossier(ir, decide(ir, AdmissionResult(verdict="admit")), outcome, "anybldg")
    return render_answer(doss), doss


# ── a room somebody holds is named as one ────────────────────────────────────────────


def test_a_laboratory_offered_to_someone_looking_for_a_calm_place_says_so():
    text, doss = _render(CALM_PLACE, "noise", [31.0, 33.0, 35.0], [("Laboratory",)] * 3)
    assert "Check you can use it first" in text
    assert "a laboratory someone else holds" in text
    assert "Room 0" in text and "Room 1" in text
    # the reader's word, never the schema's
    assert "Laboratory" not in text.replace("laboratory", "")
    assert numeric_guard(text, doss) == []


def test_an_office_offered_as_an_authorised_seating_area_says_so():
    text, _ = _render(SEATING_AREA, "occupancy", [3.4, 3.8, 3.9], [("Office",)] * 3)
    assert "Check you can use it first" in text and "an office someone else holds" in text


def test_a_survey_of_the_building_keeps_its_plain_ranking():
    """An office is a perfectly good answer to "which space reads best" — that question
    is about the building, not about where its asker may sit."""
    text, _ = _render(SURVEY, "noise", [31.0, 33.0, 35.0], [("Office",)] * 3)
    assert "Check you can use it first" not in text
    assert "Best match: Room 0" in text


def test_an_open_space_carries_no_access_line():
    text, _ = _render(CALM_PLACE, "noise", [31.0, 33.0, 35.0], [("Common_Area",)] * 3)
    assert "Check you can use it first" not in text


def test_only_the_rooms_that_are_held_are_named():
    text, _ = _render(
        CALM_PLACE, "noise", [31.0, 33.0, 35.0], [("Laboratory",), ("Common_Area",), ("Office",)]
    )
    assert "Room 0 and Room 2" in text
    assert "a laboratory or an office" in text


@pytest.mark.parametrize(
    "query,expected",
    [
        (CALM_PLACE, True),
        (SEATING_AREA, True),
        ("I'm pregnant and overheating - where's the coolest place to work today?", True),
        ("Where can I work for three hours with power, good Wi-Fi and a low risk of noise?", True),
        (SURVEY, False),
        ("Which rooms are the stuffiest right now?", False),
        ("Which space on Floor 3 has the best conditions for focused work this afternoon?", False),
    ],
)
def test_asks_where_i_may_go_separates_a_request_from_a_survey(query, expected):
    assert asks_where_i_may_go(query) is expected


def test_access_word_is_the_readers_word_and_empty_for_an_open_space():
    assert access_word(("Laboratory", "Room")) == "laboratory"
    assert access_word(("Office",)) == "office"
    assert access_word(("Common_Area", "Room")) == ""
    assert access_word(()) == ""


# ── a reading past the end of its band is said to be past it ─────────────────────────


def test_occupancy_past_the_band_it_is_scored_against_is_declared():
    text, doss = _render(SEATING_AREA, "occupancy", [24.1, 23.8, 25.0], [("Common_Area",)] * 3)
    assert "sits above the 0 to 8 range used to weigh it" in text
    assert "the order between them is not something these readings support" in text
    # the answer quotes the band's edges; the guard must not reject its own honesty
    assert numeric_guard(text, doss) == []


def test_readings_inside_the_band_get_no_note():
    text, _ = _render(SEATING_AREA, "occupancy", [3.4, 3.8, 3.9], [("Common_Area",)] * 3)
    assert "range used to weigh it" not in text


def test_one_reading_inside_the_band_is_enough_to_suppress_the_note():
    """The note says the criterion cannot separate THESE spaces. One in-band value means
    it can, so the claim would be false."""
    text, _ = _render(SEATING_AREA, "occupancy", [24.1, 3.8, 25.0], [("Common_Area",)] * 3)
    assert "range used to weigh it" not in text


# ── the exclusion reason is English, not a class name ────────────────────────────────


def test_an_excluded_space_is_not_described_by_its_schema_class():
    from types import SimpleNamespace

    from orchestrator.services.deliberation.coverage_audit import SpaceCoverage

    temp = {"temperature": {"status": "present", "uuid": "u", "stored_at": "t"}}
    plant = SpaceCoverage("x#P", "Plant Room", "Floor0", dict(temp), {"Mechanical_Room", "Room"})
    store = SpaceCoverage("x#S", "Store", "Floor0", dict(temp), {"Storage_Room", "Room"})
    office = SpaceCoverage("x#O", "Office", "Floor0", dict(temp), {"Office", "Room"})
    schema = SimpleNamespace(spaces=[plant, store, office], amenities=[])
    admission = SimpleNamespace(floor_anchor=None, space_anchor=None, amenity_anchor=None)
    cqir = SimpleNamespace(
        constraints=[], raw_query="Whats the best empty room to convert into two phone booths?"
    )
    _cands, ledger = enumerate_candidates(cqir, admission, schema)
    reasons = " ".join(e.reason for e in ledger.excluded)
    assert reasons  # something was excluded, so there is something to word
    for token in ("Mechanical_Room", "Storage_Room", "Telecom_Room", "_"):
        assert token not in reasons
    assert "not a space people occupy" in reasons


def test_the_candidate_still_carries_its_classes_for_the_record():
    from types import SimpleNamespace

    from orchestrator.services.deliberation.coverage_audit import SpaceCoverage

    temp = {"temperature": {"status": "present", "uuid": "u", "stored_at": "t"}}
    lab = SpaceCoverage("x#L", "Lab", "Floor2", dict(temp), {"Laboratory", "Room"})
    schema = SimpleNamespace(spaces=[lab], amenities=[])
    admission = SimpleNamespace(floor_anchor=None, space_anchor=None, amenity_anchor=None)
    cqir = SimpleNamespace(constraints=[], raw_query="Where can I sit quietly?")
    cands, _ledger = enumerate_candidates(cqir, admission, schema)
    assert cands and cands[0].kinds == ("Laboratory", "Room")


# ── a time the lane could not parse is not reported as one it projected ──────────────


def test_a_named_weekday_is_not_reported_as_a_projection_of_that_day():
    from orchestrator.services.deliberation.compiler import _fold_deterministic_horizon
    from orchestrator.services.deliberation.cqir import TimeBasis, TimeSpec

    spec = TimeSpec(basis=TimeBasis.FORECAST, source_phrase="next Wednesday after 2 p.m.")
    _fold_deterministic_horizon(spec, CALM_PLACE)
    assert spec.horizon_hours is None, "an unparsed phrase must not be filled in with a default"

    ir = CQIR(
        decision=DecisionKind.SELECT_ONE,
        constraints=[Constraint(modality="noise", direction=Direction.MINIMIZE)],
        raw_query=CALM_PLACE,
        time=spec,
    )
    texts = " ".join(a.text for a in decide(ir, AdmissionResult(verdict="admit")).assumptions)
    assert "it does not describe that time specifically" in texts
    assert "forecast 24h ahead" not in texts


def test_a_phrase_the_table_knows_still_resolves():
    from orchestrator.services.deliberation.compiler import _fold_deterministic_horizon
    from orchestrator.services.deliberation.cqir import TimeBasis, TimeSpec

    spec = TimeSpec(basis=TimeBasis.FORECAST, source_phrase="tomorrow")
    _fold_deterministic_horizon(spec, "will it be quiet tomorrow?")
    assert spec.horizon_hours == 24.0
