# -*- coding: utf-8 -*-
"""A plant question is answered by a plant point, or honestly not at all (BUG-667, CAVEAT-654).

WHAT WENT WRONG, MEASURED LIVE 2026-09-17
-----------------------------------------
* "What is the outside air damper position on floor 3 right now?" found nothing. The damper
  point is `isPointOf` a damper that `isPartOf` the air handler, and the air handler `feeds`
  the floor's HVAC zone from a plant room. The floor-scoped resolver only walked
  sensor -> hasLocation -> floor, and nothing on that chain has a location.
* "What is the supply air temperature on floor 3 right now?" answered 24.1 °C from a ROOM
  sensor. The temperature concept's classes (Temperature_Sensor, Zone_Air_Temperature_Sensor,
  Outside_Air_Temperature_Sensor) replaced the supply-air class, and the plant-side exclusion
  removed the one point that actually answers.
* On zero rows every data question fell into the semantic-RAG fallback: LLM prose with no
  bindings behind it, for a question asking for a reading.

WHY THE QUERIES ARE EXECUTED, NOT READ
--------------------------------------
BUG-481's second layer survived a test that asserted on the query TEXT. So the floor-scoped
query here is run by rdflib against a graph shaped like the real one. Superclass types are
materialised first, as the live store's RDFS inference does — the query relies on that exactly
as the plant fallback's `?sensor a brick:Point` already does.

Nothing here names a real building: the fixture namespace is example.org.
"""

import asyncio
from typing import Any, Dict, List, Optional, Set

import pytest
from rdflib import RDF, RDFS, Graph

from orchestrator.agents import verifier_agent as va
from orchestrator.agents.sparql_agent import SPARQLAgent
from shared.models import ConversationState, Message

pytestmark = pytest.mark.unit

NS = "http://example.org/bldgx#"

_TTL = """
@prefix brick: <https://brickschema.org/schema/Brick#> .
@prefix rdfs:  <http://www.w3.org/2000/01/rdf-schema#> .
@prefix ref:   <https://brickschema.org/schema/Brick/ref#> .
@prefix x:     <http://example.org/bldgx#> .
@prefix ontosage: <http://ontosage.org/capabilities#> .

# ── TBox slice (Brick 1.4 shape) ─────────────────────────────────────────────
brick:Sensor rdfs:subClassOf brick:Point .
brick:Command rdfs:subClassOf brick:Point .
brick:Temperature_Sensor rdfs:subClassOf brick:Sensor .
brick:Air_Temperature_Sensor rdfs:subClassOf brick:Temperature_Sensor .
brick:Zone_Air_Temperature_Sensor rdfs:subClassOf brick:Air_Temperature_Sensor .
brick:Outside_Air_Temperature_Sensor rdfs:subClassOf brick:Air_Temperature_Sensor .
brick:Supply_Air_Temperature_Sensor rdfs:subClassOf brick:Air_Temperature_Sensor .
brick:Water_Temperature_Sensor rdfs:subClassOf brick:Temperature_Sensor .
brick:Leaving_Water_Temperature_Sensor rdfs:subClassOf brick:Water_Temperature_Sensor .
brick:Damper_Position_Sensor rdfs:subClassOf brick:Sensor .
brick:Damper_Position_Command rdfs:subClassOf brick:Command .
brick:CO2_Sensor rdfs:subClassOf brick:Sensor .
brick:HVAC_Equipment rdfs:subClassOf brick:Equipment .
brick:Air_Handling_Unit rdfs:subClassOf brick:HVAC_Equipment .
brick:Damper rdfs:subClassOf brick:HVAC_Equipment .
brick:Outside_Damper rdfs:subClassOf brick:Damper .
brick:Boiler rdfs:subClassOf brick:HVAC_Equipment .
brick:HVAC_System rdfs:subClassOf brick:System .
brick:Space rdfs:subClassOf brick:Location .
brick:Room rdfs:subClassOf brick:Space .
brick:Floor rdfs:subClassOf brick:Location .
brick:Zone rdfs:subClassOf brick:Location .
brick:HVAC_Zone rdfs:subClassOf brick:Zone .
ontosage:Sound_Level_Sensor rdfs:subClassOf brick:Sensor .
# A class minted in ONE building's namespace, as the keyword map used to name.
x:Noise_Level_Sensor rdfs:subClassOf brick:Sensor .

# ── Floors ───────────────────────────────────────────────────────────────────
x:Floor2 a brick:Floor .
x:Floor3 a brick:Floor .
x:Floor4 a brick:Floor .

# ── Floor 3: a room sensor LOCATED on the floor (the existing path) ─────────
x:Room_3_01 a brick:Room ; brick:isPartOf x:Floor3 .
x:T_3_01 a brick:Air_Temperature_Sensor ;
    rdfs:label "Air Temperature Sensor 3.01" ;
    brick:hasLocation x:Room_3_01 ;
    ref:hasExternalReference [ ref:hasTimeseriesId "u-t301" ; ref:storedAt x:db ] .

# ── Floor 3: an air handler that SERVES the floor, forward relationships ────
# Its own isPartOf the floor mirrors the live graph; the points still have no location.
x:AHU_3 a brick:Air_Handling_Unit ;
    brick:feeds x:Zone_3 ;
    brick:isPartOf x:Floor3 .
x:Zone_3 a brick:HVAC_Zone ; brick:isPartOf x:Floor3 .
x:AHU_3_Damper a brick:Outside_Damper ; brick:isPartOf x:AHU_3 .
x:AHU_3_Damper_Position a brick:Damper_Position_Sensor ;
    rdfs:label "Air Handler 3 outside air damper position" ;
    brick:isPointOf x:AHU_3_Damper ;
    ref:hasExternalReference [ ref:hasTimeseriesId "u-dp3" ; ref:storedAt x:db ] .
x:AHU_3_SAT a brick:Supply_Air_Temperature_Sensor ;
    rdfs:label "Air Handler 3 supply air temperature" ;
    brick:isPointOf x:AHU_3 ;
    ref:hasExternalReference [ ref:hasTimeseriesId "u-sat3" ; ref:storedAt x:db ] .

# A boiler FEEDING the air handler is not on floor 3: the handler is equipment, not a place.
x:Boiler_1 a brick:Boiler ; brick:feeds x:AHU_3 .
x:Boiler_1_LWT a brick:Leaving_Water_Temperature_Sensor ;
    rdfs:label "Boiler 1 leaving water temperature" ;
    brick:isPointOf x:Boiler_1 ;
    ref:hasExternalReference [ ref:hasTimeseriesId "u-lwt1" ; ref:storedAt x:db ] .

# ── Floor 4: two sound-level points in rooms, and one legacy building-namespace noise point
x:Room_4_01 a brick:Room ; brick:isPartOf x:Floor4 .
x:S_4_01 a ontosage:Sound_Level_Sensor ;
    rdfs:label "Sound Level Sensor 4.01" ;
    brick:hasLocation x:Room_4_01 ;
    ref:hasExternalReference [ ref:hasTimeseriesId "u-s401" ; ref:storedAt x:db ] .
x:S_4_02 a ontosage:Sound_Level_Sensor ;
    rdfs:label "Sound Level Sensor 4.02" ;
    brick:hasLocation x:Room_4_01 ;
    ref:hasExternalReference [ ref:hasTimeseriesId "u-s402" ; ref:storedAt x:db ] .
x:N_4_legacy a x:Noise_Level_Sensor ;
    rdfs:label "Noise level 4 (legacy class)" ;
    brick:hasLocation x:Room_4_01 ;
    ref:hasExternalReference [ ref:hasTimeseriesId "u-n4" ; ref:storedAt x:db ] .

# ── Floor 4: the same shape through the INVERSE relationships ───────────────
x:AHU_4 a brick:Air_Handling_Unit ;
    brick:hasPoint x:AHU_4_SAT ;
    brick:hasPart x:AHU_4_Damper .
x:Zone_4 a brick:HVAC_Zone ; brick:isFedBy x:AHU_4 .
x:Floor4 brick:hasPart x:Zone_4 .
x:AHU_4_Damper a brick:Outside_Damper ; brick:hasPoint x:AHU_4_Damper_Position .
x:AHU_4_Damper_Position a brick:Damper_Position_Sensor ;
    rdfs:label "Air Handler 4 outside air damper position" ;
    ref:hasExternalReference [ ref:hasTimeseriesId "u-dp4" ; ref:storedAt x:db ] .
x:AHU_4_SAT a brick:Supply_Air_Temperature_Sensor ;
    rdfs:label "Air Handler 4 supply air temperature" ;
    ref:hasExternalReference [ ref:hasTimeseriesId "u-sat4" ; ref:storedAt x:db ] .

# ── Floor 2: neither kind of point. A SYSTEM feeds its zone; the system is not equipment,
#    so the points of a unit inside it do not land on floor 2. ────────────────
x:Room_2_01 a brick:Room ; brick:isPartOf x:Floor2 .
x:C_2_01 a brick:CO2_Sensor ;
    rdfs:label "CO2 Sensor 2.01" ;
    brick:hasLocation x:Room_2_01 ;
    ref:hasExternalReference [ ref:hasTimeseriesId "u-c201" ; ref:storedAt x:db ] .
x:Zone_2 a brick:HVAC_Zone ; brick:isPartOf x:Floor2 .
x:Central_System a brick:HVAC_System ; brick:hasPart x:AHU_9 ; brick:feeds x:Zone_2 .
x:AHU_9 a brick:Air_Handling_Unit .
x:AHU_9_SAT a brick:Supply_Air_Temperature_Sensor ;
    rdfs:label "Air Handler 9 supply air temperature" ;
    brick:isPointOf x:AHU_9 ;
    ref:hasExternalReference [ ref:hasTimeseriesId "u-sat9" ; ref:storedAt x:db ] .
"""

TEMPERATURE_CONCEPT = [
    "brick:Outside_Air_Temperature_Sensor",
    "brick:Temperature_Sensor",
    "brick:Zone_Air_Temperature_Sensor",
]
DAMPER_CONCEPT = ["brick:Damper_Position_Command", "brick:Damper_Position_Sensor"]


@pytest.fixture(scope="module")
def graph() -> Graph:
    g = Graph()
    g.parse(data=_TTL, format="turtle")
    # Materialise rdf:type over rdfs:subClassOf, as the live store's inference does.
    changed = True
    while changed:
        changed = False
        for s, cls in list(g.subject_objects(RDF.type)):
            for sup in g.objects(cls, RDFS.subClassOf):
                if (s, RDF.type, sup) not in g:
                    g.add((s, RDF.type, sup))
                    changed = True
    return g


def _agent() -> SPARQLAgent:
    return SPARQLAgent.__new__(SPARQLAgent)


def _run(
    graph: Graph,
    question: str,
    concept: Optional[List[str]] = None,
    populated: Optional[bool] = None,
    agent: Optional[SPARQLAgent] = None,
) -> Set[str]:
    """Build the floor-scoped query for a question and EXECUTE it; return local sensor names."""
    agent = agent or _agent()
    target = concept[0] if concept else None
    query = agent._floor_scoped_sparql(
        question, target, class_targets=concept, concept_populated=populated
    )
    assert query is not None, f"no floor-scoped query for {question!r}"
    rows = graph.query(query)
    out = set()
    for row in rows:
        iri = str(row.sensor)
        assert iri.startswith(NS)
        out.add(iri[len(NS) :])
    return out


# ── BUG-667: equipment that serves a floor is in scope for that floor ─────────


def test_a_damper_point_on_an_air_handler_serving_the_floor_is_found(graph):
    assert _run(
        graph, "What is the outside air damper position on floor 3 right now?", DAMPER_CONCEPT
    ) == {"AHU_3_Damper_Position"}


def test_supply_air_temperature_comes_from_the_air_handler_not_the_room(graph):
    """The substitution itself: the temperature concept must not let a room sensor answer."""
    found = _run(
        graph, "What is the supply air temperature on floor 3 right now?", TEMPERATURE_CONCEPT
    )
    assert found == {"AHU_3_SAT"}
    assert "T_3_01" not in found


def test_supply_air_temperature_without_a_concept_also_stays_plant_side(graph):
    assert _run(graph, "What is the supply air temperature on floor 3?") == {"AHU_3_SAT"}


@pytest.mark.parametrize(
    "question,concept,expected",
    [
        ("What is the damper position on floor 4?", DAMPER_CONCEPT, {"AHU_4_Damper_Position"}),
        ("What is the supply air temperature on floor 4?", TEMPERATURE_CONCEPT, {"AHU_4_SAT"}),
    ],
)
def test_the_inverse_relationships_reach_the_floor_too(graph, question, concept, expected):
    """hasPoint / hasPart / isFedBy / Floor hasPart Zone — the file supports both directions."""
    assert _run(graph, question, concept) == expected


def test_the_located_room_sensor_case_is_unchanged(graph):
    """A ROOM question on a floor still gets the room sensor, and still not the AHU's supply
    air, which WB-14 keeps out of a floor's temperature."""
    assert _run(graph, "What is the temperature on floor 3?", TEMPERATURE_CONCEPT) == {"T_3_01"}


@pytest.mark.parametrize(
    "question,concept",
    [
        ("What is the supply air temperature on floor 2?", TEMPERATURE_CONCEPT),
        ("What is the damper position on floor 2?", DAMPER_CONCEPT),
    ],
)
def test_a_floor_with_neither_returns_nothing(graph, question, concept):
    """Floor 2 has a room CO2 sensor and a zone fed by a SYSTEM whose unit has a supply-air
    point. Neither may answer: the honest result is empty."""
    assert _run(graph, question, concept) == set()


def test_a_boiler_feeding_an_air_handler_is_not_on_the_handlers_floor(graph):
    assert _run(graph, "What is the leaving water temperature on floor 3?") == set()


def test_across_floors_a_plant_quantity_lists_only_plant_points(graph):
    assert _run(
        graph, "Which floor has the highest supply air temperature?", TEMPERATURE_CONCEPT
    ) == {"AHU_3_SAT", "AHU_4_SAT"}


def test_the_plant_query_drops_only_the_room_exclusion():
    """Asserted on text only as a companion to the executed tests above: the exclusion is
    still present for a room question and absent for a plant one."""
    agent = _agent()
    room = agent._floor_scoped_sparql("which floor is the warmest right now", None)
    plant = agent._floor_scoped_sparql("supply air temperature on floor 3", None)
    assert "FILTER NOT EXISTS" in room
    assert "FILTER NOT EXISTS" not in plant
    assert "subClassOf* brick:Supply_Air_Temperature_Sensor" in plant


# ── a populated concept outranks the static keyword map ───────────────────────

SOUND_CONCEPT = ["ontosage:Sound_Level_Sensor"]


def _agent_with_legacy_noise_map() -> SPARQLAgent:
    """An agent whose keyword map still names a building-namespace noise class."""
    agent = _agent()
    agent._get_extended_class_map = lambda: {
        "noise": "x:Noise_Level_Sensor",
        "co2": "brick:CO2_Sensor",
        "temperature": "brick:Temperature_Sensor",
    }
    return agent


def test_noise_on_a_floor_targets_the_concepts_sound_class_and_returns_its_points(graph):
    """The keyword map (here the old one) and the concept disagree; the concept is populated,
    so it wins, and the floor's sound points come back — not the legacy class's point."""
    found = _run(
        graph,
        "What is the noise on floor 4?",
        SOUND_CONCEPT,
        populated=True,
        agent=_agent_with_legacy_noise_map(),
    )
    assert found == {"S_4_01", "S_4_02"}


def test_the_legacy_map_would_have_missed_them(graph):
    """The same agent without the population fact: the map decides, the query selects the
    building-namespace class, and the two sound points are not in the answer."""
    agent = _agent_with_legacy_noise_map()
    query = agent._floor_scoped_sparql(
        "What is the noise on floor 4?", SOUND_CONCEPT[0], class_targets=SOUND_CONCEPT
    )
    assert "x:Noise_Level_Sensor" in query and "ontosage:Sound_Level_Sensor" not in query


@pytest.mark.parametrize("populated", [None, False])
def test_without_a_populated_concept_the_keyword_map_still_decides(graph, populated):
    assert _run(graph, "What is the CO2 on floor 2?") == {"C_2_01"}
    assert _run(
        graph, "What is the CO2 on floor 2?", ["brick:Nonexistent_CO2_Sensor"], populated=populated
    ) == {"C_2_01"}


def test_noise_with_no_concept_uses_the_corrected_keyword_map(graph):
    assert _run(graph, "What is the noise on floor 4?") == {"S_4_01", "S_4_02"}


def test_the_keyword_map_names_no_class_in_the_buildings_own_namespace(monkeypatch):
    """Design contract 3: core code must not steer a question to one building's classes."""
    from orchestrator.agents import sparql_agent as sa

    monkeypatch.setattr(sa.ontology_introspector, "is_ready", lambda: False)
    class_map = _agent()._get_extended_class_map()
    building_prefix = sa._active_prefix() + ":"
    assert not [v for v in class_map.values() if v.startswith(building_prefix)]
    for word in ("noise", "sound", "acoustic"):
        assert class_map[word] == "ontosage:Sound_Level_Sensor"
    assert "vibration" not in class_map


def test_populated_classes_reads_the_graph_within_the_active_building(graph, monkeypatch):
    from orchestrator.agents import sparql_agent as sa

    monkeypatch.setattr(sa, "_active_namespace", lambda: NS)
    agent = _agent()

    async def _exec(query: str) -> Dict[str, Any]:
        rows = graph.query(query)
        return {
            "results": {
                "bindings": [
                    {str(k): {"value": str(v)} for k, v in row.asdict().items()} for row in rows
                ]
            }
        }

    agent._execute_query = _exec
    held = asyncio.run(
        agent._populated_classes(
            ["ontosage:Sound_Level_Sensor", "brick:CO2_Sensor", "brick:Nonexistent_Sensor"]
        )
    )
    assert held == {"ontosage:Sound_Level_Sensor", "brick:CO2_Sensor"}

    monkeypatch.setattr(sa, "_active_namespace", lambda: "http://example.org/other#")
    other = _agent()
    other._execute_query = _exec
    assert asyncio.run(other._populated_classes(["brick:CO2_Sensor"])) == set()


def test_populated_classes_says_unknown_rather_than_guessing():
    agent = _agent()
    assert asyncio.run(agent._populated_classes(["nosuchprefix:X"])) is None

    async def _down(query: str) -> Dict[str, Any]:
        raise ConnectionError("graph down")

    agent._execute_query = _down
    assert asyncio.run(agent._populated_classes(["brick:CO2_Sensor"])) is None


# ── the most specific declaring class wins, from the TBox and not the alphabet ─


def _relations(graph: Graph, candidates: List[str]):
    """What `_class_relations` reads from the store, read from the fixture graph instead."""

    async def _exec(query: str) -> Dict[str, Any]:
        rows = graph.query(query)
        bindings = []
        for row in rows:
            bindings.append({str(k): {"value": str(v)} for k, v in row.asdict().items()})
        return {"results": {"bindings": bindings}}

    agent = _agent()
    agent._execute_query = _exec
    agent._prefix_block = lambda building_id=None: (
        "PREFIX brick: <https://brickschema.org/schema/Brick#>\n"
        "PREFIX ontosage: <http://ontosage.org/capabilities#>"
    )
    return asyncio.run(agent._class_relations(candidates))


def test_an_indoor_temperature_concept_does_not_pick_the_outside_class_by_alphabet(graph):
    """The resolver SORTS classes, so 'first' was Outside_Air_Temperature_Sensor. The two
    leaves are siblings; the concept's own parent covers both and is the honest target."""
    anc, inst = _relations(graph, TEMPERATURE_CONCEPT)
    assert SPARQLAgent._most_specific_class(TEMPERATURE_CONCEPT) == (
        "brick:Outside_Air_Temperature_Sensor"
    ), "the old rule, kept only for when the graph cannot be asked"
    assert SPARQLAgent._most_specific_class(TEMPERATURE_CONCEPT, anc, inst) == (
        "brick:Temperature_Sensor"
    )


def test_a_genuinely_more_specific_class_wins(graph):
    pair = ["brick:Temperature_Sensor", "brick:Zone_Air_Temperature_Sensor"]
    anc, inst = _relations(graph, pair)
    assert SPARQLAgent._most_specific_class(pair, anc, inst) == "brick:Zone_Air_Temperature_Sensor"
    assert SPARQLAgent._most_specific_class(list(reversed(pair)), anc, inst) == (
        "brick:Zone_Air_Temperature_Sensor"
    )


def test_incomparable_classes_prefer_the_one_the_building_has(graph):
    """Pure depth would take Damper_Position_Command (deeper, no instances here)."""
    anc, inst = _relations(graph, DAMPER_CONCEPT)
    assert SPARQLAgent._most_specific_class(DAMPER_CONCEPT, anc, inst) == (
        "brick:Damper_Position_Sensor"
    )


@pytest.mark.parametrize(
    "candidates",
    [
        ["ontosage:Sound_Level_Sensor", "brick:Sensor"],
        ["brick:Sensor", "ontosage:Sound_Level_Sensor"],
    ],
)
def test_an_ontosage_class_is_kept_and_wins_as_the_descendant(candidates):
    ancestors = {"ontosage:Sound_Level_Sensor": {"brick:Sensor"}, "brick:Sensor": set()}
    assert SPARQLAgent._most_specific_class(candidates, ancestors, {}) == (
        "ontosage:Sound_Level_Sensor"
    )
    assert SPARQLAgent._most_specific_class(candidates) == "ontosage:Sound_Level_Sensor"


def test_an_ontosage_class_survives_the_plant_and_composite_rules():
    """The floor-scoped selector must not drop an OCBV class a concept resolved to."""
    agent = _agent()
    q = agent._floor_scoped_sparql(
        "how loud is it on floor 3",
        "ontosage:Sound_Level_Sensor",
        class_targets=["ontosage:Sound_Level_Sensor", "brick:Sound_Pressure_Sensor"],
    )
    assert q is not None and "ontosage:Sound_Level_Sensor" in q


def test_class_relations_refuses_a_class_it_cannot_expand():
    agent = _agent()
    anc, inst = asyncio.run(agent._class_relations(["nosuchprefix:X", "brick:Y"]))
    assert anc is None and inst is None


# ── CAVEAT-654: an empty DATA lookup is a typed absence, not RAG prose ──────────

_EMPTY_ENVELOPE = {"head": {"vars": ["sensor"]}, "results": {"bindings": []}}
_ROWS_ENVELOPE = {
    "head": {"vars": ["sensor", "label", "floorNum", "uuid"]},
    "results": {
        "bindings": [
            {
                "sensor": {"value": NS + "AHU_3_SAT"},
                "label": {"value": "Air Handler 3 supply air temperature"},
                "floorNum": {"value": "3"},
                "uuid": {"value": "11111111-1111-1111-1111-111111111111"},
            }
        ]
    },
}


class _Engine:
    def __init__(self, result: Dict[str, Any]):
        self.result = result
        self.query: Optional[str] = None

    async def execute_with_correction(self, query, execute_fn, context):
        self.query = query
        return dict(self.result)


def _pipeline_agent(result: Dict[str, Any], populated: Optional[Set[str]] = None):
    """`populated` is what `_populated_classes` reports; None = the graph could not say."""
    agent = _agent()
    calls = {"semantic": 0}

    async def _none(*a, **k):
        return None

    async def _empty(*a, **k):
        return []

    async def _no_relations(*a, **k):
        return None, None

    async def _populated(classes):
        return None if populated is None else {c for c in classes if c in populated}

    async def _semantic(state, user_query, context=None):
        calls["semantic"] += 1
        return {"success": True, "method": "semantic_rag", "results": [{"answer": "prose"}]}

    async def _formatted(*a, **k):
        return "formatted from rows"

    agent._whole_register = _none
    agent._instrument_metrology = _none
    agent._retrieve_context = _empty
    agent._plant_instances = _empty
    agent._resolve_entities_by_label = _empty
    agent._filter_existing = _empty
    agent._get_instances_for_class = _empty
    agent._pattern_instance_search = _empty
    agent._class_relations = _no_relations
    agent._populated_classes = _populated
    agent._format_results = _formatted
    agent._standardize_results = lambda *a, **k: []
    agent.answer_semantically = _semantic
    agent._correction_engine = _Engine(result)
    return agent, calls


def _state(question: str, intent: str, concept: Optional[List[str]] = None) -> ConversationState:
    s = ConversationState(
        conversation_id="c-654",
        user_id="u",
        user_message=question,
        building_id="bldgX",
        current_intent=intent,
        messages=[Message(role="user", content=question)],
    )
    s.intermediate_results["intent"] = intent
    if concept:
        s.intermediate_results["concepts"] = [{"concept_id": "c", "brick_classes": list(concept)}]
    return s


_EMPTY_RAN = {"success": False, "results": _EMPTY_ENVELOPE, "error": "Empty results"}


def test_a_data_intent_with_zero_rows_gets_a_typed_absence_not_prose():
    agent, calls = _pipeline_agent(_EMPTY_RAN)
    q = "What is the supply air temperature on floor 2 right now?"
    out = asyncio.run(agent.generate_query(_state(q, "sensor_data", TEMPERATURE_CONCEPT), q))
    assert calls["semantic"] == 0
    assert out["method"] == "typed_absence"
    assert out["success"] is True and out["analytics_required"] is False
    assert out["retrieval_outcome"]["outcome"] == "not_declared"
    assert out["retrieval_outcome"]["floors"] == ["2"]
    assert "supply air temperature" in out["formatted_response"]
    assert "floor 2" in out["formatted_response"]
    # The remedy is for administrators; it is carried, never shown.
    assert out["retrieval_outcome"]["remedy"]
    assert out["retrieval_outcome"]["remedy"] not in out["formatted_response"]


def test_the_typed_absence_is_read_as_ungrounded_by_the_verifier_without_crashing():
    """BUG-643 must keep working: the envelope is real and empty, so no bindings, no ids."""
    agent, _ = _pipeline_agent(_EMPTY_RAN)
    q = "What is the damper position on floor 2?"
    out = asyncio.run(agent.generate_query(_state(q, "sensor_data", DAMPER_CONCEPT), q))
    assert va._bindings(out) == []
    assert va._sparql_returned_data(out) is False
    assert va._extract_sensor_ids(out) == []


def test_the_absence_wording_trips_neither_the_absence_guard_nor_the_meta_guard():
    from orchestrator.services.absence_guard import detect_absence_claim
    from orchestrator.services.grounding_guard import meta_answer_reason

    agent, _ = _pipeline_agent(_EMPTY_RAN)
    for q, concept in [
        ("What is the temperature on floor 2?", TEMPERATURE_CONCEPT),
        ("What is the supply air temperature on floor 2?", TEMPERATURE_CONCEPT),
        ("What is the damper position on floor 2?", DAMPER_CONCEPT),
    ]:
        out = asyncio.run(agent.generate_query(_state(q, "analytics", concept), q))
        assert out["method"] == "typed_absence"
        assert detect_absence_claim(out["formatted_response"]) is None
        assert meta_answer_reason(out["formatted_response"]) is None


@pytest.mark.parametrize("intent", ["metadata", "discovery", "general"])
def test_a_metadata_intent_with_zero_rows_still_uses_the_semantic_fallback(intent):
    agent, calls = _pipeline_agent(_EMPTY_RAN)
    q = "What is the supply air temperature on floor 2?"
    out = asyncio.run(agent.generate_query(_state(q, intent, TEMPERATURE_CONCEPT), q))
    assert calls["semantic"] == 1
    assert out["method"] == "semantic_rag"


def test_an_empty_query_that_did_not_ask_for_the_concepts_classes_is_not_an_absence():
    """The graph could not say whether the concept is populated, so the keyword map chose —
    here a map that disagrees with the concept, as it did before it was corrected. Zero rows
    for the map's class says nothing about the concept's."""
    agent, calls = _pipeline_agent(_EMPTY_RAN, populated=None)
    agent._get_extended_class_map = lambda: {"noise": "x:Noise_Level_Sensor"}
    q = "What is the noise on floor 4?"
    out = asyncio.run(
        agent.generate_query(_state(q, "sensor_data", ["ontosage:Sound_Level_Sensor"]), q)
    )
    assert "x:Noise_Level_Sensor" in agent._correction_engine.query
    assert calls["semantic"] == 1
    assert out.get("method") != "typed_absence"


def test_an_unpopulated_concept_falls_back_to_the_map_and_still_declares_no_absence():
    """A concept whose classes have no instances hands the choice to the keyword map; the
    map's class covers none of the concept's, so emptiness proves nothing about it."""
    agent, calls = _pipeline_agent(_EMPTY_RAN, populated=set())
    q = "What is the noise on floor 4?"
    out = asyncio.run(
        agent.generate_query(_state(q, "sensor_data", ["brick:Acoustic_Test_Sensor"]), q)
    )
    assert "ontosage:Sound_Level_Sensor" in agent._correction_engine.query
    assert "brick:Acoustic_Test_Sensor" not in agent._correction_engine.query
    assert calls["semantic"] == 1
    assert out.get("method") != "typed_absence"


def test_a_populated_concept_that_the_query_covered_may_declare_absence():
    """The positive half of the guard: the concept won, the query asked for exactly its
    classes, and the floor holds none — that emptiness IS a fact about the graph."""
    agent, calls = _pipeline_agent(_EMPTY_RAN, populated={"ontosage:Sound_Level_Sensor"})
    agent._get_extended_class_map = lambda: {"noise": "x:Noise_Level_Sensor"}
    q = "What is the noise on floor 2?"
    out = asyncio.run(
        agent.generate_query(_state(q, "sensor_data", ["ontosage:Sound_Level_Sensor"]), q)
    )
    assert "ontosage:Sound_Level_Sensor" in agent._correction_engine.query
    assert "x:Noise_Level_Sensor" not in agent._correction_engine.query
    assert calls["semantic"] == 0
    assert out["method"] == "typed_absence"


def test_a_query_that_failed_is_not_reported_as_an_absence():
    """No envelope at all means the store never answered — not a fact about the building."""
    agent, calls = _pipeline_agent({"success": False, "results": {}, "error": "timeout"})
    q = "What is the supply air temperature on floor 2?"
    out = asyncio.run(agent.generate_query(_state(q, "sensor_data", TEMPERATURE_CONCEPT), q))
    assert calls["semantic"] == 1
    assert out.get("method") != "typed_absence"


def test_an_empty_query_the_resolver_did_not_build_keeps_the_fallback():
    """No floor named -> no deterministic floor-scoped query -> the empty result proves
    nothing, so it must not be announced as a building-level absence."""
    agent, calls = _pipeline_agent(_EMPTY_RAN)
    agent._template_sparql = lambda *a, **k: "SELECT ?s WHERE { ?s ?p ?o } LIMIT 1"
    q = "What is the supply air temperature right now?"
    out = asyncio.run(agent.generate_query(_state(q, "sensor_data"), q))
    assert calls["semantic"] == 1
    assert out.get("method") != "typed_absence"


def test_a_result_with_bindings_is_unchanged():
    agent, calls = _pipeline_agent({"success": True, "results": _ROWS_ENVELOPE, "error": None})
    q = "What is the supply air temperature on floor 3 right now?"
    out = asyncio.run(agent.generate_query(_state(q, "sensor_data", TEMPERATURE_CONCEPT), q))
    assert calls["semantic"] == 0
    assert out.get("method") is None
    assert out["results"] is _ROWS_ENVELOPE or out["results"] == _ROWS_ENVELOPE
    assert out["formatted_response"] == "formatted from rows"
    assert "subClassOf* brick:Supply_Air_Temperature_Sensor" in out["query"]
