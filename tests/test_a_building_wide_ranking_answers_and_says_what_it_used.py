# -*- coding: utf-8 -*-
"""WB-05: a ranking on simulated-only evidence answers, and says so in its first lines."""

import inspect

import pytest

from orchestrator.services.deliberation import dossier as ds
from orchestrator.services.deliberation import plan_executor as px

pytestmark = pytest.mark.unit


def test_scenario_mode_is_a_fallback_only_when_provenance_emptied_the_ranking():
    src = inspect.getsource(px.execute)
    i = src.index('evidence_mode="scenario"')
    guard = src[src.rindex("if not score.ranked", 0, i) : i]
    assert "score.excluded_for_provenance" in guard
    # The basis is stated, and never in words the owner has ruled out for user-visible text.
    assert "**Ranking basis.**" in src
    note = src[src.index("**Ranking basis.**") : src.index("] + list(event_notes)")]
    for banned in ("simulated", "synthetic", "fake"):
        assert banned not in note.lower()


def test_a_successful_ranking_prints_its_guidance_notes():
    src = inspect.getsource(ds)
    best = src.index("**Best match:")
    assert "dossier.guidance_notes" in src[best : best + 600]


@pytest.mark.parametrize("anchor", ["None", "Room", "the building", ""])
def test_a_whole_building_anchor_is_not_a_space_to_find(anchor):
    """WB-11: 'coolest place in the building' asked the user which room they meant."""
    from orchestrator.services.deliberation import capability_schema as cs

    assert anchor.strip().lower() in cs._WHOLE_BUILDING_ANCHORS
    src = inspect.getsource(cs)
    assert "not in _WHOLE_BUILDING_ANCHORS" in src


def test_equal_totals_break_on_the_raw_value_in_the_direction_asked():
    """WB-13: 'highest PM2.5' listed clamped rooms alphabetically, not by reading."""
    from orchestrator.services.deliberation import scorer as sc

    src = inspect.getsource(sc.score_candidates)
    assert "_raw_key(s)" in src and "Direction.MAXIMIZE" in src


def test_air_quality_ranks_on_co2_and_pm25():
    """WB-16: the unit-mixed air_quality modality could not be scored at all."""
    from orchestrator.services.deliberation import compiler as cp
    from orchestrator.services.deliberation.cqir import Constraint, Direction, Hardness

    c = Constraint(modality="air_quality", direction=Direction.MAXIMIZE, hardness=Hardness.SOFT)
    folded = cp._fold_air_quality([c])
    assert {x.modality for x in folded} == {"co2", "pm25"}
    assert all(x.direction == Direction.MINIMIZE for x in folded)


def test_a_place_to_work_excludes_restrooms_and_plant():
    """WB-17: 'coolest place to work in the building' ranked a male restroom first."""
    from types import SimpleNamespace

    from orchestrator.services.deliberation.candidates import enumerate_candidates
    from orchestrator.services.deliberation.coverage_audit import SpaceCoverage

    temp = {"temperature": {"status": "present", "uuid": "u", "stored_at": "t"}}
    wc = SpaceCoverage("x#WC", "Restroom", "Floor5", dict(temp), {"Restroom", "Room"})
    office = SpaceCoverage("x#Office", "Office", "Floor5", dict(temp), {"Office", "Room"})
    schema = SimpleNamespace(spaces=[wc, office], amenities=[])
    admission = SimpleNamespace(floor_anchor=None, space_anchor=None, amenity_anchor=None)
    cqir = SimpleNamespace(constraints=[], raw_query="Where's the coolest place to work?")
    cands, ledger = enumerate_candidates(cqir, admission, schema)
    assert [c.label for c in cands] == ["Office"]
    assert any("not a place to work" in e.reason for e in ledger.excluded)
    # F-02: purpose-scoped in general — a comfort ranking is about places for people even
    # when the question does not say "work", and the exclusion says how to undo it
    cqir.raw_query = "Which room has the best air quality right now?"
    cands, ledger = enumerate_candidates(cqir, admission, schema)
    assert [c.label for c in cands] == ["Office"]
    assert any("ask about it by name to include it" in e.reason for e in ledger.excluded)
    # BUG-716: the reason is printed to the reader — under a ranking and as the whole
    # "Why:" of a decline — so it may not carry the name of a class in a schema.
    assert not any("_" in e.reason for e in ledger.excluded)
    # naming the kind asks about exactly those spaces
    cqir.raw_query = "Which restroom has the highest temperature?"
    cands, _ = enumerate_candidates(cqir, admission, schema)
    assert {c.label for c in cands} == {"Office", "Restroom"}


@pytest.mark.parametrize(
    "q,occupant",
    [
        ("Which rooms in the building are the stuffiest right now?", True),
        ("Where is the quietest room?", True),
        ("Is the server room too hot?", False),
        ("Which plant room is the warmest?", False),
        ("Which toilets have the highest humidity?", False),
    ],
)
def test_the_purpose_is_occupant_unless_a_non_occupied_space_is_named(q, occupant):
    from orchestrator.services.deliberation.candidates import purpose_is_occupant

    assert purpose_is_occupant(q) is occupant


def test_a_count_of_readings_is_not_an_implausible_reading():
    """WB-22: '1,020 readings' was flagged as an impossible humidity value."""
    from orchestrator.services.plausibility import implausibility_note

    draft = ("Floor 0 has the lowest humidity, a mean of 50.5 % across 17 sensors and 1,020 "
             "readings. This falls comfortably within the recommended band.")
    assert implausibility_note("Which floor has the lowest humidity?", draft) is None
    bad = "The humidity is 1020, which is high."
    assert implausibility_note("what is the humidity?", bad) is not None
