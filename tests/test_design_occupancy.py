# -*- coding: utf-8 -*-
"""W3-04 — observed occupancy against the occupancy a space was designed for.

The row asked for a new ``ontosage:designOccupancy`` property. The building already declares
design occupancy under two property names, and for three spaces the two DISAGREE, so the work
was to READ what is there and to report the disagreement rather than to author a third term.
The numbers pinned below are the live graph's, read 2026-09-29.
"""

from __future__ import annotations

import pytest

from orchestrator.services.design_occupancy import (
    DESIGN_OCCUPANCY_TERMS,
    DesignOccupancy,
    compare_observed_with_design,
    declared_design_occupancy,
    describe_design,
    is_design_occupancy_predicate,
    is_design_occupancy_question,
    match_space,
)

pytestmark = pytest.mark.unit

NS = "http://example.org/building#"
HBCO = "http://ontosage.org/hbco#"


def _payload(rows):
    return {
        "results": {
            "bindings": [
                {
                    "space": {"value": iri},
                    "label": {"value": label},
                    "p": {"value": pred},
                    "v": {"value": str(val)},
                }
                for iri, label, pred, val in rows
            ]
        }
    }


def _exec(payload):
    async def run(_query):
        return payload

    return run


# ── the property is discovered, never named ──────────────────────────────────


@pytest.mark.parametrize(
    "iri",
    [
        f"{NS}designOccupancy",
        f"{NS}maxOccupancy",
        f"{NS}maximum_occupancy",
        f"{HBCO}roomCapacity",
        "https://w3id.org/rec#capacity",
        f"{NS}seatingCapacity",
    ],
)
def test_a_design_occupancy_property_is_recognised_whatever_its_namespace(iri):
    assert is_design_occupancy_predicate(iri)


@pytest.mark.parametrize(
    "iri",
    [
        # A bin's volume. A substring match on "capacity" would report 1,100 litres as 1,100
        # people; the live graph carries 24 of these.
        "http://ontosage.org/capabilities#capacityLitres",
        # A continuity note ("Floors 1-3 only"), not a count of people.
        "http://ontosage.org/capabilities#alternativeCapacity",
        "http://ontosage.org/capabilities#buildingOccupancyType",
        f"{NS}floorArea",
        f"{NS}occupancySensor",
    ],
)
def test_a_property_that_is_not_about_people_is_not_a_design_occupancy(iri):
    assert not is_design_occupancy_predicate(iri)


def test_the_term_list_carries_no_namespace():
    """Design contract rule 3: a building's own vocabulary may not be baked in here."""
    for term in DESIGN_OCCUPANCY_TERMS:
        assert ":" not in term and "/" not in term and "#" not in term
        assert term == term.lower()


# ── reading the graph ────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_every_declaration_is_kept_not_the_first_one():
    declared = await declared_design_occupancy(
        _exec(
            _payload(
                [
                    (f"{NS}Room1.04", "Room 1.04", f"{NS}maxOccupancy", 50),
                    (f"{NS}Room1.04", "Room 1.04", f"{HBCO}roomCapacity", 25),
                ]
            )
        )
    )
    entry = declared[f"{NS}Room1.04"]
    assert entry.declarations == {f"{NS}maxOccupancy": 50, f"{HBCO}roomCapacity": 25}
    assert entry.conflicted
    assert entry.value is None  # no single figure, so none is offered


@pytest.mark.asyncio
async def test_two_declarations_that_agree_are_not_a_conflict():
    declared = await declared_design_occupancy(
        _exec(
            _payload(
                [
                    (f"{NS}Room2.01", "Room 2.01", f"{NS}maxOccupancy", 25),
                    (f"{NS}Room2.01", "Room 2.01", f"{HBCO}roomCapacity", 25),
                ]
            )
        )
    )
    entry = declared[f"{NS}Room2.01"]
    assert not entry.conflicted and entry.value == 25


@pytest.mark.asyncio
async def test_a_failed_graph_query_is_not_a_building_with_no_capacities():
    async def boom(_q):
        raise RuntimeError("graphdb down")

    assert await declared_design_occupancy(boom) == {}


# ── naming a space ───────────────────────────────────────────────────────────


def test_a_question_matches_a_space_by_its_number_not_its_full_label():
    declared = {
        f"{NS}Room1.25": DesignOccupancy(
            space_iri=f"{NS}Room1.25",
            label="Room 1.25 — Conference/Seminar Room",
            declarations={f"{NS}maxOccupancy": 20},
        )
    }
    for named in ("room 1.25", "Room1.25", "is 1.25 over its design occupancy?"):
        assert match_space(named, declared) is not None


def test_a_space_the_building_does_not_declare_matches_nothing():
    declared = {
        f"{NS}Room1.25": DesignOccupancy(
            space_iri=f"{NS}Room1.25", label="Room 1.25", declarations={f"{NS}maxOccupancy": 20}
        )
    }
    assert match_space("room 9.99", declared) is None
    assert match_space("the lobby", declared) is None


@pytest.mark.parametrize(
    "question",
    [
        "How does observed occupancy compare with the design occupancy of room 1.25?",
        "Is room 2.15 over its design occupancy?",
        "How many people can room 3.13 hold?",
        "Is 1.04 over capacity right now?",
    ],
)
def test_design_occupancy_questions_are_recognised(question):
    assert is_design_occupancy_question(question)


@pytest.mark.parametrize(
    "question",
    [
        "How busy is the building?",  # no space, so no single declared figure applies
        "What is the temperature in room 5.01?",
        "Which sensors have stopped reporting?",
    ],
)
def test_other_questions_are_not_design_occupancy_questions(question):
    assert not is_design_occupancy_question(question)


# ── the comparison ───────────────────────────────────────────────────────────


def _single(value=20, label="Room 1.25 — Conference/Seminar Room"):
    return DesignOccupancy(
        space_iri=f"{NS}Room1.25", label=label, declarations={f"{NS}maxOccupancy": value}
    )


def _conflicted():
    return DesignOccupancy(
        space_iri=f"{NS}Room1.04",
        label="Room 1.04 — Common Area / Atrium",
        declarations={f"{NS}maxOccupancy": 50, f"{HBCO}roomCapacity": 25},
    )


def test_the_answer_carries_both_numbers():
    """The acceptance: observed AND design, in one sentence.

    27.0 is the count the live system reported for room 1.25 on 2026-09-29, in the same answer
    that said "The design occupancy for room 1.25 is not provided in the data". The graph
    declares 20.
    """
    text = compare_observed_with_design(27.0, _single(20))
    assert "27" in text and "20" in text
    assert "Over its design occupancy" in text
    assert "135%" in text


def test_a_count_within_the_design_figure_is_not_reported_as_over():
    text = compare_observed_with_design(12.0, _single(20))
    assert "Within its design occupancy" in text
    assert "12" in text and "20" in text


def test_a_conflict_is_reported_rather_than_resolved():
    """Nothing in the graph says which figure is authoritative, so nothing here picks one."""
    text = compare_observed_with_design(30.0, _conflicted())
    assert "50" in text and "25" in text
    assert "maxOccupancy" in text and "roomCapacity" in text
    assert "will not choose" in text
    # A conflicted space must never produce a single-figure verdict.
    assert "Over its design occupancy" not in text


def test_a_conflict_still_says_where_the_count_falls():
    over_both = compare_observed_with_design(60.0, _conflicted())
    assert "over every figure on record" in over_both
    under_both = compare_observed_with_design(10.0, _conflicted())
    assert "within every figure on record" in under_both


def test_no_declared_figure_is_a_gap_in_the_model_not_a_zero():
    text = compare_observed_with_design(27.0, None)
    assert "not a count of zero" in text


def test_no_reading_still_states_the_declared_figure():
    text = compare_observed_with_design(None, _single(20))
    assert "20 people" in text
    assert "no occupancy reading" in text


def test_describe_design_names_both_properties_when_they_disagree():
    text = describe_design(_conflicted())
    assert "50 under maxOccupancy" in text and "25 under roomCapacity" in text
