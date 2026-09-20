# -*- coding: utf-8 -*-
"""Three amenity/spatial answers that ignored what was actually asked (wave 9).

    "Is the parking free or is there a fee?"
        -> a Transport Parking passage: train and bus directions.
    "Are the steps closer to the elevators?"
        -> "No **lift** spaces found."
    "Where is the nearest public toilet on my route, and is it currently in service?"
        -> the nearest toilet, with the second half of the question dropped.

1. A fee, opening hours or a capacity is a FIELD on an amenity's record. The record answers it, or the
   answer names what IS recorded and says the field is not. An empty field is never turned into
   "free": not recorded and free are different facts.
2. Which of two KINDS is closer needs a starting point the question does not give. The lane says what
   it CAN do once, instead of a bare "not found".
3. "Is it in service?" is answered from the building's recorded state, and an amenity with no record
   is not assumed to work.
"""

import pytest

from orchestrator.services import amenity_attribute_answer as attr

pytestmark = pytest.mark.unit

_NS = "http://ontosage.org/capabilities#"
_B = "http://example.org/b#"


def _row(iri, label, cls, cls_label="", answer="", hours="", fee=""):
    r = {"a": {"value": f"{_B}{iri}"}, "cls": {"value": f"{_NS}{cls}"}}
    if label:
        r["l"] = {"value": label}
    if cls_label:
        r["cl"] = {"value": cls_label}
    if answer:
        r["ans"] = {"value": answer}
    if hours:
        r["hours"] = {"value": hours}
    if fee:
        r["fee"] = {"value": fee}
    return r


_PARKING = (
    "The building records a ground-level parking area with six electric-vehicle charging stations. "
    "How many bays are free is measured separately."
)


def _rows(**over):
    rows = [
        _row("Park", "Ground Level Parking", "ParkingArea", "Parking area", _PARKING),
        _row("Park", "Ground Level Parking", "Capability"),  # a reasoner's class names no kind
        _row(
            "Cafe",
            "Cafe — Abacws Cafe",
            "Cafe",
            "Café / catering",
            hours="Monday–Friday 08:00–16:30",
        ),
        _row("T1", "Toilet facility — Room 1.07", "ToiletFacility", "Toilet facility"),
        _row("T2", "Toilet facility — Room 2.35", "ToiletFacility", "Toilet facility"),
        _row("T3", "Toilet facility — Room 3.36", "ToiletFacility", "Toilet facility"),
        _row(
            "Shower",
            "Shower facilities — Floor 1",
            "ShowerFacility",
            "Shower facility",
            fee="free for card holders",
        ),
    ]
    rows.extend(over.get("extra", []))
    return rows


async def _exec(_q, rows=None):
    return {"results": {"bindings": rows if rows is not None else _rows()}}


async def _ask(question, rows=None):
    async def run(q):
        return await _exec(q, rows)

    return await attr.answer(question, run)


# -- 1. the attribute of a kind -----------------------------------------------------------------
@pytest.mark.asyncio
async def test_a_fee_question_names_what_is_recorded_and_says_the_fee_is_not():
    text = await _ask("Is the parking free or is there a fee?")
    assert text.startswith(
        "**The building records a ground-level parking area with six electric-vehicle charging "
        "stations; it does not record whether there is a fee.**"
    )


@pytest.mark.asyncio
async def test_an_empty_fee_field_is_never_read_as_free_or_as_charged():
    text = (await _ask("Is there a fee for the parking?")).lower()
    assert "does not record" in text
    assert "is free" not in text and "no fee" not in text and "not free" not in text


@pytest.mark.asyncio
async def test_a_recorded_fee_is_reported_as_recorded():
    text = await _ask("Is there a charge for the showers?")
    assert "The recorded charge is free for card holders." in text
    assert "does not record" not in text


@pytest.mark.asyncio
async def test_opening_hours_come_from_the_record():
    text = await _ask("What are the cafe opening hours?")
    assert "Recorded opening hours: Monday–Friday 08:00–16:30." in text


@pytest.mark.asyncio
async def test_a_kind_with_many_records_is_not_described_by_one_of_them():
    text = await _ask("How much does it cost to use the toilets?")
    assert "toilet facility locations" in text and "Room 1.07" not in text
    assert "does not record whether there is a fee" in text


@pytest.mark.asyncio
async def test_a_missing_attribute_of_a_kind_that_has_other_fields_still_says_it_is_missing():
    text = await _ask("What are the parking opening hours?")
    assert "does not record its opening hours" in text


# -- what must be left alone -----------------------------------------------------------------------
@pytest.mark.asyncio
@pytest.mark.parametrize(
    "question",
    [
        "Are there free parking spaces available now?",  # availability is a live measurement
        "Where can I park?",
        "Is there a fee for the swimming pool?",  # no such kind in this building
        "Is the parking near the station free or is there a fee?",  # more than the attribute
        "What is the cost of electricity on floor 3?",
        "How much did the parking sensor cost?",
    ],
)
async def test_a_question_that_is_not_an_attribute_of_a_recorded_kind_is_left_alone(question):
    assert await _ask(question) is None


@pytest.mark.asyncio
async def test_nothing_is_answered_when_the_graph_cannot_be_read():
    async def broken(_q):
        raise RuntimeError("down")

    assert await attr.answer("Is the parking free or is there a fee?", broken) is None


def test_a_class_is_asked_about_by_its_distinctive_words():
    assert attr.class_words("ParkingArea") == frozenset({"parking"})
    assert attr.class_words("DrinkingWater") == frozenset({"drinking", "water"})
    assert attr.class_words("ToiletFacility") == frozenset({"toilet"})


# -- 2. which kind is closer -----------------------------------------------------------------------
@pytest.mark.asyncio
@pytest.mark.parametrize(
    "question",
    [
        "Are the steps closer to the elevators?",
        "Are the stairs nearer than the lifts?",
        "Is the toilet farther than the lift?",
    ],
)
async def test_a_distance_comparison_between_two_kinds_says_what_the_lane_can_do(question):
    from orchestrator.agents.spatial_agent import SpatialAgent

    text = await SpatialAgent()._answer(question, [])
    assert "not which is closer overall" in text
    assert "No **" not in text and "spaces found" not in text
    first = text.splitlines()[0]
    assert first.count("nearest") == 2, "said once, naming both kinds"


@pytest.mark.asyncio
async def test_a_comparison_with_one_kind_is_not_intercepted():
    from orchestrator.agents.spatial_agent import SpatialAgent, kinds_named

    assert sorted(kinds_named("Are the steps closer to the elevators?")) == ["lift", "staircase"]
    assert kinds_named("Is a lift closer to room 3.01?") == ["lift"]
    text = await SpatialAgent()._answer("Is a lift closer to room 3.01?", [])
    assert "not which is closer overall" not in text


def test_steps_are_stairs_and_a_staircase_is_a_nearest_target():
    from orchestrator.agents.spatial_agent import kind_words_for_target

    assert "staircase" in kind_words_for_target("Are the steps closer?")
    assert "staircase" in kind_words_for_target("Where is the nearest staircase to Room 3.10?")


# -- 3. is it in service ---------------------------------------------------------------------------
def _hit(label, status=""):
    from orchestrator.services.amenity_proximity import AmenityHit

    return AmenityHit(iri=f"x#{label}", label=label, floor="Floor1", status=status)


def _render(hits, asked):
    from orchestrator.services.amenity_proximity import render

    return render(hits, "toilet", "Room 1.01", 1, False, asked_service=asked)


@pytest.mark.parametrize(
    "asked_service, status, expected",
    [
        (True, "operational", "Toilet A is recorded as in service"),
        (True, "", "the building records no service state for Toilet A, so I cannot say"),
        (True, "under_maintenance", "Toilet A is recorded as under maintenance"),
    ],
)
def test_is_it_in_service_is_answered_from_the_recorded_state(asked_service, status, expected):
    assert f"**Service state:** {expected}" in _render([_hit("Toilet A", status)], asked_service)


def test_an_amenity_with_no_recorded_state_is_never_assumed_to_work():
    assert (
        "in service"
        not in _render([_hit("Toilet A")], True).split("Service state:")[1].split("\n")[0]
    )


def test_the_service_line_is_absent_unless_the_question_asked():
    assert "Service state" not in _render([_hit("Toilet A", "operational")], False)


def test_the_out_of_service_one_is_named_and_the_working_one_is_the_one_reported():
    text = _render([_hit("Toilet A", "operational"), _hit("Toilet B", "out_of_service")], True)
    assert "Toilet A is recorded as in service" in text
    assert "Currently out of service: Toilet B" in text


def test_the_spatial_lane_recognises_a_service_question():
    from orchestrator.agents.spatial_agent import _SERVICE_RE

    for q in (
        "Where is the nearest public toilet on my route, and is it currently in service?",
        "is the nearest lift working?",
        "is the nearest toilet out of service",
    ):
        assert _SERVICE_RE.search(q), q
    for q in (
        "Where is the nearest toilet?",
        "nearest lift to room 3.01",
        "Where is the nearest service lift?",
    ):
        assert not _SERVICE_RE.search(q), q
