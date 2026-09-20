"""The referent gate names a place or a quantity only when the words name one.

Measured 2026-09-19 over the 10,339-question pool (docs/REACH_2026-09-19.md section 3.3), the gate
"found" things nobody had named:

* ``building a green roof`` and ``the building I can keep on my phone`` read as sites called A and
  I, and were declined as buildings this instance is not connected to;
* ``classes on Levels 1 and 3`` read as a measurand called "on" (the graph "has" it: it is inside
  "carbon"), and ``at what level of VOC`` as one called "what";
* ``this room IS warm`` read as a place called "is", ~3% of the pool, each costing two graph lookups;
* ``a busy corridor`` read as a place called "busy corridor", so a building with corridors was told
  it had none; and
* ``pollutant levels`` / ``decibel level`` were declined as quantities "no sensor measures", by a
  building with 835 air-quality sensors and a noise concept for exactly that word.

What must not move: Room 9.99, floor 3, room 5.01, the swimming pool, Building 47, Block C, radiation.
"""

from typing import List

import pytest

from orchestrator.services import referent_resolver as rr

pytestmark = pytest.mark.unit


@pytest.fixture(autouse=True)
def _no_published_vocabulary():
    rr.register_concept_terms([])
    yield
    rr.register_concept_terms([])


def _resolver(exists: bool = False, seen: List[str] = None):
    async def _exec(query):
        if seen is not None:
            seen.append(query)
        return {"results": {"bindings": [{"s": {"value": "x"}}] if exists else []}}

    return rr.ReferentResolver(_exec)


# ── "building a green roof" is not a building called A ──────────────────────────────────────


@pytest.mark.parametrize(
    "query",
    [
        "How should we go about building a green roof for our building?",
        "Is the building a green building?",
        "Is there a map of the building I can keep on my phone?",
        "Tell me one thing about this building I probably don't know.",
    ],
)
def test_an_article_or_a_pronoun_after_building_is_not_a_building_name(query):
    typed = rr.detect_typed_referent(query)
    assert typed is None or typed.kind != rr.KIND_LOCATION, typed


@pytest.mark.parametrize(
    "query,phrase",
    [
        ("What is the temperature in Building 47?", "building 47"),
        ("Is block C warmer than block D?", "block c"),
        ("The extract fan in toilet block B is loud", "block b"),
        ("How is Building A doing?", "building a"),
        ("What is the temperature in Tower 2?", "tower 2"),
        ("Which floor is warmest in Building I?", "building i"),
        ("is block c warmer", "block c"),
    ],
)
def test_a_named_other_building_is_still_detected(query, phrase):
    typed = rr.detect_typed_referent(query)
    assert typed is not None and typed.kind == rr.KIND_LOCATION
    assert typed.phrase.lower() == phrase


# ── "classes on Levels 1 and 3" is not a quantity called "on" ───────────────────────────────


@pytest.mark.parametrize(
    "query",
    [
        "I have classes on Levels 1, 3 and 5 tomorrow. Where should I study between them?",
        "The lift says out of service - how do I get to level 5 with my luggage?",
        "At what level of VOC do you boost ventilation?",
        "Who decides the appropriate level of humidity?",
        "Can you choose an authorised route with fewer level changes?",
        "What verified levels, slopes and floor-to-floor heights constrain the project?",
        "After the move, update who to notify for alarms from level 5.",
        "Is the VOC boost activated on building-wide levels or wide levels only?",
        "Show the daily levels for the whole building.",
    ],
)
def test_a_function_word_or_a_modifier_before_level_is_not_a_measured_quantity(query):
    assert rr.detect_typed_referent(query) is None, query


@pytest.mark.parametrize(
    "query,quantity",
    [
        ("At what level is the methane concentration?", "methane"),
        ("Is ozone level normal?", "ozone"),
        ("what is the current voltage level?", "voltage"),
        ("Are radiation levels safe?", "radiation"),
        ("Are CO2 levels high?", "co2"),
        # the first "<word> Levels" is a preposition; the quantity is the second
        ("I have classes on Levels 1 and 3. Are the CO2 levels high there?", "co2"),
    ],
)
def test_a_real_quantity_before_level_is_still_detected(query, quantity):
    typed = rr.detect_typed_referent(query)
    assert typed is not None and typed.kind == rr.KIND_MEASURAND and typed.token == quantity


# ── "this room is warm" is not a place called "is" ──────────────────────────────────────────


@pytest.mark.parametrize(
    "query",
    [
        "This room is too cold",
        "Which room has the most daylight?",
        "Is there a room for two people?",
        "Which room or lift is available?",
        "Which room with a window is free?",
        "Is a room in use to the left?",
    ],
)
def test_a_function_word_after_room_is_not_a_place(query):
    assert rr.detect_referent(query, []) is None, query


@pytest.mark.parametrize(
    "query,token",
    [
        ("What is the temperature in Room 9.99?", "9.99"),
        ("What is the temperature in room 5.01?", "5.01"),
        ("humidity in zone 3.10", "3.10"),
        ("What is the temperature in room Atrium?", "Atrium"),
        ("room is warm but room 5.16 is cold", "5.16"),  # the function word is skipped, not fatal
    ],
)
def test_a_room_id_or_a_named_space_is_still_a_referent(query, token):
    assert rr.detect_referent(query, []) == token


def test_a_function_word_in_an_isolated_entity_is_not_a_place_either():
    assert rr.detect_referent("", ["room is"]) is None
    assert rr.detect_referent("", ["room 5.01"]) == "5.01"


# ── "a busy corridor" is a corridor in a state, not a place called "busy corridor" ──────────


@pytest.mark.parametrize(
    "query",
    [
        "When is the least disruptive window for cleaning a busy corridor?",
        "A student wants to avoid the busiest corridor.",
        "Where is the quietest hallway right now?",
    ],
)
def test_a_state_adjective_is_not_part_of_a_place_name(query):
    assert rr.detect_typed_referent(query) is None, query


@pytest.mark.parametrize(
    "query,phrase",
    [
        ("Is the main corridor warm?", "main corridor"),
        ("Is the swimming pool open?", "swimming pool"),
        ("Is there anyone in the rooftop garden?", "rooftop garden"),
        ("How busy is the west wing?", "west wing"),
        ("How many sensors are in the gym?", "gym"),
    ],
)
def test_a_real_named_space_is_still_detected(query, phrase):
    typed = rr.detect_typed_referent(query)
    assert typed is not None and typed.kind == rr.KIND_SPACE and typed.phrase == phrase


# ── a quantity the lay vocabulary explains is not looked up by name ─────────────────────────


@pytest.mark.asyncio
async def test_a_quantity_the_lay_vocabulary_explains_is_not_declined_as_unmeasured():
    rr.register_concept_terms(["pollutant", "noise level", "brightness", "occupancy"])
    seen: List[str] = []
    for query in (
        "are air purifiers adjusted automatically based on pollutant levels?",
        "Can the building monitor sound noise levels?",
        "Is the brightness level comfortable for reading?",
        "are ventilation systems adjusting based on occupany levels?",  # a slip of "occupancy"
    ):
        res = await _resolver(exists=False, seen=seen).resolve(query, [], "http://x#", "B")
        assert res.status == rr.RESOLVED, (query, res)
    assert seen == [], "a quantity the vocabulary explains needs no graph lookup"


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "query",
    ["Is ozone level normal?", "what is the current voltage level?", "Are radiation levels safe?"],
)
async def test_a_quantity_the_vocabulary_does_not_explain_is_still_declined(query):
    # "solar radiation" is a lay term, but only as a whole: it must not make radiation measured.
    rr.register_concept_terms(["solar radiation", "noise level", "pollutant"])
    res = await _resolver(exists=False).resolve(query, [], "http://x#", "B")
    assert res.status == rr.NOT_FOUND, (query, res)
    assert "no sensor measuring" in res.message


@pytest.mark.asyncio
async def test_without_a_published_vocabulary_the_gate_behaves_as_before():
    res = await _resolver(exists=False).resolve("pollutant levels?", [], "http://x#", "B")
    assert res.status == rr.NOT_FOUND


# ── a four-letter quantity must stand as a whole word ───────────────────────────────────────


@pytest.mark.asyncio
async def test_a_short_quantity_is_looked_up_as_a_whole_word_and_a_long_one_as_a_substring():
    short: List[str] = []
    await _resolver(exists=False, seen=short).resolve("Are CO levels high?", [], "http://x#", "B")
    assert any("REGEX" in q and "(^|[^a-z0-9])co([^a-z0-9]|$)" in q for q in short), short
    assert not any("CONTAINS(" in q and '"co"' in q for q in short)

    long_: List[str] = []
    await _resolver(exists=False, seen=long_).resolve(
        "Are methane levels high?", [], "http://x#", "B"
    )
    assert any("CONTAINS(" in q and '"methane"' in q for q in long_), long_
    assert not any("REGEX" in q for q in long_)


# ── the gate's core behaviour did not move ──────────────────────────────────────────────────


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "query,phrase",
    [
        ("What is the temperature in Room 9.99?", "9.99"),
        ("How busy is floor 42?", "floor 42"),
        ("Is there anyone in the swimming pool?", "swimming pool"),
        ("What is the temperature in Building 47?", "building 47"),
    ],
)
async def test_a_referent_the_building_does_not_hold_is_still_declined(query, phrase):
    res = await _resolver(exists=False).resolve(query, [], "http://x#/abacws#", "B")
    assert res.status == rr.NOT_FOUND and res.referent == phrase, res


@pytest.mark.asyncio
async def test_a_referent_the_building_holds_still_resolves():
    for query in ("What is the temperature in room 5.01?", "How busy is floor 3?"):
        res = await _resolver(exists=True).resolve(query, [], "http://x#", "B")
        assert res.status in (rr.RESOLVED, rr.AMBIGUOUS), (query, res)
