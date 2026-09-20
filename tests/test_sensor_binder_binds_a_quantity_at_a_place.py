# -*- coding: utf-8 -*-
"""2D-05: a measured quantity at a named place binds to that place's own series.

The failures this prevents, all measured on the unscripted tails (BUG-825/826/831/809):

* "How stuffy is Room 1.06 at the moment?" and "Which rooms are occupied at the moment?" were
  answered "the building only records how many sensors are installed in each space", because
  with no entity IRI the "list all rooms" template claims any question containing "room" and
  returns `?space (COUNT(?sensor))` -- rows with no timeseries id at all;
* "the CO2 level in the atrium" matched no space, and a zone sensor on another floor answered;
* "the temperature tomorrow in Room 2.01" forecast in one run and was refused in the next.

The graph is faked here: a building's own data must never decide whether these hold, and a
unit test must not assume which building is active.
"""

from __future__ import annotations

from datetime import datetime
from types import SimpleNamespace
from typing import Any, Dict, List

import pytest

from orchestrator.services import sensor_binder as sb
from orchestrator.services.deliberation.coverage_audit import ModalitySpec

pytestmark = pytest.mark.unit

NS = "http://example.org/b#"
BRICK = "https://brickschema.org/schema/Brick#"

U_CO2 = "11111111-1111-4111-8111-111111111111"
U_TEMP = "22222222-2222-4222-8222-222222222222"
U_OCC = "33333333-3333-4333-8333-333333333333"
U_ZONE_CO2 = "44444444-4444-4444-8444-444444444444"
U_SIM_TEMP = "55555555-5555-4555-8555-555555555555"
U_HP_IN = "66666666-6666-4666-8666-666666666666"
U_HP_OUT = "77777777-7777-4777-8777-777777777777"
U_STATUS = "88888888-8888-4888-8888-888888888888"


@pytest.fixture(autouse=True)
def _catalogue(monkeypatch):
    """A building-agnostic modality catalogue, so no test reads the active building's overlay."""
    specs = [
        ModalitySpec("co2", ["CO2_Level_Sensor", "CO2_Sensor"]),
        ModalitySpec("temperature", ["Air_Temperature_Sensor", "Temperature_Sensor"]),
        ModalitySpec("occupancy", ["Occupancy_Count_Sensor", "Occupancy_Sensor"]),
        ModalitySpec("occupancy_status", ["Occupancy_Status"]),
        ModalitySpec("noise", ["Sound_Level_Sensor"]),
        ModalitySpec("parking_free", ["Occupancy_Count_Sensor"], label_contains=["parking"]),
    ]
    monkeypatch.setattr(sb, "load_modalities", lambda building_id=None: specs)


def _cell(value: str, kind: str = "literal") -> Dict[str, str]:
    return {"type": kind, "value": value}


def _sensor_rows(iri: str, label: str, uuid: str, classes: List[str], **extra) -> List[dict]:
    """One row per class, the way the store returns a sensor through rdf:type/subClassOf*."""
    rows = []
    for cls in classes + ["Point", "Sensor"]:
        row = {
            "sensor": _cell(NS + iri, "uri"),
            "label": _cell(label),
            "uuid": _cell(uuid),
            "storage": _cell(NS + "store_a", "uri"),
            "cls": _cell(BRICK + cls, "uri"),
        }
        for key, val in extra.items():
            row[key] = _cell(val)
        rows.append(row)
    return rows


def _place_row(iri: str, label: str, zone: bool = False, room: bool = True) -> dict:
    row = {"s": _cell(NS + iri, "uri"), "label": _cell(label)}
    if zone:
        row["zone"] = _cell("true")
    if room:
        row["room"] = _cell("true")
    return row


class FakeGraph:
    """Answers each query shape the binder sends, and records every query it was sent."""

    def __init__(
        self,
        places=None,
        own=None,
        zone=None,
        equipment=None,
        equip_points=None,
        population=None,
        fail=False,
        declared=None,
    ):
        self.places = places or {}  # "1.06" or "atrium" -> [place rows]
        self.own = own or {}  # place iri local -> [sensor rows]
        # What the graph DECLARES at a place, with or without a series; defaults to `own`.
        self.declared = declared
        self.zone = zone or {}
        self.equipment = equipment or []
        self.equip_points = equip_points or []
        self.population = population or []
        self.fail = fail
        self.queries: List[str] = []

    async def __call__(self, query: str) -> Dict[str, Any]:
        self.queries.append(query)
        if self.fail:
            raise RuntimeError("graph down")
        rows: List[dict] = []
        if "brick:Equipment ." in query and "SELECT DISTINCT ?s ?label WHERE" in query:
            rows = self.equipment
        elif "brick:isPointOf|^brick:hasPoint" in query:
            rows = self.equip_points
        elif "brick:hasPart|brick:feeds" in query:
            rows = self._by_iri(self.zone, query)
        elif "SELECT DISTINCT ?sensor ?label ?uuid ?cls WHERE" in query:
            rows = self._by_iri(self.declared if self.declared is not None else self.own, query)
        elif "brick:hasLocation|^brick:isLocationOf) <" in query:
            rows = self._by_iri(self.own, query)
        elif "VALUES ?local" in query and "?sensor a ?cls" in query:
            rows = self.population
        elif "brick:Location" in query:
            for key, found in self.places.items():
                if f'"{key}"' in query:
                    rows = found
                    break
        return {"head": {"vars": []}, "results": {"bindings": rows}}

    @staticmethod
    def _by_iri(table: Dict[str, List[dict]], query: str) -> List[dict]:
        for local, found in table.items():
            if f"<{NS}{local}>" in query:
                return found
        return []

    def ran(self, fragment: str) -> bool:
        return any(fragment in q for q in self.queries)


def _room_graph(**overrides) -> FakeGraph:
    own_106 = (
        _sensor_rows("CO2_106", "CO2 Level Sensor installed-node 1.06", U_CO2, ["CO2_Level_Sensor"])
        + _sensor_rows(
            "T_106",
            "Air Temperature Sensor installed-node 1.06",
            U_TEMP,
            ["Air_Temperature_Sensor", "Temperature_Sensor"],
        )
        + _sensor_rows(
            "Occ_106",
            "Room 1.06 occupancy [persons]",
            U_OCC,
            ["Occupancy_Count_Sensor"],
            sim="true",
        )
    )
    graph = dict(
        places={"1.06": [_place_row("Room1.06", "Room 1.06 — Computer Laboratory")]},
        own={"Room1.06": own_106},
    )
    graph.update(overrides)
    return FakeGraph(**graph)


STUFFY = [
    {"concept_id": "stuffiness", "brick_classes": ["brick:CO2_Level_Sensor", "brick:CO2_Sensor"]}
]
PEOPLE = [{"concept_id": "busy", "brick_classes": ["brick:Occupancy_Count_Sensor"]}]
TEMPERATURE = [{"concept_id": "temperature_reading", "brick_classes": ["brick:Temperature_Sensor"]}]


async def _bind(question, graph, concepts=None, entities=None, population=True):
    return await sb.bind_sensors(
        question, entities or [], concepts or [], graph, NS, "b1", allow_population=population
    )


# ── the named room's own sensor ──────────────────────────────────────────────────────


async def test_stuffy_in_a_named_room_binds_that_rooms_own_co2_sensor():
    graph = _room_graph()
    binding = await _bind("How stuffy is Room 1.06 at the moment?", graph, STUFFY)

    assert binding.status == sb.STATUS_BOUND and binding.basis == sb.BASIS_OWN
    assert [s.uuid for s in binding.sensors] == [U_CO2]  # not the temperature or occupancy points
    assert binding.scope_label == "Room 1.06"
    # It carries the routing the SQL lane needs, unchanged: uuid and where it is stored.
    row = binding.envelope()["results"]["bindings"][0]
    assert row["uuid"]["value"] == U_CO2 and row["storage"]["value"] == NS + "store_a"
    # ...and it never asked the "sensor count per space" question that caused the defect.
    assert not any("COUNT(" in q for q in graph.queries)


async def test_the_entity_iri_the_dialogue_stage_supplies_gives_the_same_binding():
    graph = _room_graph()
    binding = await _bind("How stuffy is it there?", graph, STUFFY, entities=["bldg:Room1.06"])
    assert [s.uuid for s in binding.sensors] == [U_CO2]


async def test_how_many_people_binds_the_count_sensor_only():
    binding = await _bind("How many people are in Room 1.06 right now?", _room_graph(), PEOPLE)
    assert [s.uuid for s in binding.sensors] == [U_OCC]


async def test_a_word_the_catalogue_knows_binds_without_a_concept():
    """'Which rooms are occupied' resolves no HBCO concept; the catalogue's words still do."""
    graph = _room_graph(
        own={
            "Room1.06": _sensor_rows(
                "St_106", "Room 1.06 occupancy_status", U_STATUS, ["Occupancy_Status"]
            )
        }
    )
    binding = await _bind("Is anyone in Room 1.06?", graph)
    assert [s.uuid for s in binding.sensors] == [U_STATUS]


# ── never widened, never guessed ─────────────────────────────────────────────────────


async def test_a_room_without_the_sensor_is_a_typed_absence_naming_what_it_records():
    graph = _room_graph(
        own={
            "Room1.06": _sensor_rows(
                "T_106",
                "Air Temperature Sensor 1.06",
                U_TEMP,
                ["Air_Temperature_Sensor", "Temperature_Sensor"],
            )
        }
    )
    binding = await _bind(
        "What is the noise level in Room 1.06?",
        graph,
        [{"concept_id": "noisy", "brick_classes": ["ontosage:Sound_Level_Sensor"]}],
    )
    assert binding.status == sb.STATUS_ABSENT
    text = sb.absence_text(binding)
    assert "no noise measurement for Room 1.06" in text
    assert "does record: temperature" in text  # names what the room DOES measure


async def test_a_room_scoped_ask_is_never_widened_to_the_building():
    graph = _room_graph(
        own={"Room1.06": []},
        population=_sensor_rows("Other", "Room 9.01 CO2", U_ZONE_CO2, ["CO2_Level_Sensor"]),
    )
    binding = await _bind("How stuffy is Room 1.06 at the moment?", graph, STUFFY)
    assert binding.status == sb.STATUS_ABSENT
    assert not graph.ran("VALUES ?local"), "the building-wide population query must not run"


async def test_a_room_the_graph_does_not_hold_is_left_to_the_referent_gate():
    graph = FakeGraph(places={"9.99": []})
    binding = await _bind("What is the CO2 in Room 9.99?", graph, STUFFY)
    assert binding.status == sb.STATUS_NOT_APPLICABLE and binding.reason == "scope_unresolved"
    assert not graph.ran("VALUES ?local")


async def test_an_unplaceable_phrase_blocks_the_building_wide_fallback():
    graph = FakeGraph(places={"pantry": []})
    binding = await _bind("What is the temperature in the pantry?", graph, TEMPERATURE)
    assert binding.status == sb.STATUS_NOT_APPLICABLE
    assert not graph.ran("VALUES ?local")


async def test_two_named_places_are_a_comparison_and_left_alone():
    graph = _room_graph()
    binding = await _bind("Compare the CO2 in Room 1.06 and Room 1.07", graph, STUFFY)
    assert binding.status == sb.STATUS_NOT_APPLICABLE and binding.reason == "several_places"
    assert graph.queries == []


async def test_a_floor_is_left_to_the_floor_scoped_resolver():
    graph = _room_graph()
    binding = await _bind("What is the CO2 level on floor 3?", graph, STUFFY)
    assert binding.status == sb.STATUS_NOT_APPLICABLE and binding.reason == "floor_scope"
    assert graph.queries == []


async def test_a_question_about_sensors_is_not_a_reading():
    graph = _room_graph()
    for question in ("How many sensors are in each room?", "What sensors are in Room 1.06?"):
        binding = await _bind(question, graph, STUFFY)
        assert binding.status == sb.STATUS_NOT_APPLICABLE
    assert graph.queries == []


async def test_a_threshold_number_is_not_mistaken_for_a_room():
    ask = sb.extract_scope_ask("Is Room 1.06 above 26.5 degrees?", ["26.5", "bldg:Room1.06"])
    assert ask.id_token == "1.06" and not ask.multiple


async def test_the_graph_failing_never_becomes_an_absence():
    graph = _room_graph(fail=True)
    binding = await _bind("How stuffy is Room 1.06 at the moment?", graph, STUFFY)
    assert binding.status == sb.STATUS_NOT_APPLICABLE and binding.reason == "graph_unavailable"


async def test_an_ambiguous_named_space_is_not_guessed():
    two = [
        _place_row("Room2.01", "Room 2.01 — Kitchen"),
        _place_row("Room3.01", "Room 3.01 — Kitchen"),
    ]
    graph = FakeGraph(places={"kitchen": two})
    binding = await _bind("What is the CO2 in the kitchen?", graph, STUFFY)
    assert binding.status == sb.STATUS_NOT_APPLICABLE and binding.reason == "scope_ambiguous"
    assert len(binding.candidates) == 2


# ── a named space, and the zone that stands in ───────────────────────────────────────


async def test_the_atrium_resolves_by_label_and_binds_its_own_sensor():
    graph = FakeGraph(
        places={"atrium": [_place_row("Room1.04", "Room 1.04 — Common Area / Atrium")]},
        own={
            "Room1.04": _sensor_rows(
                "CO2_104", "CO2 Level Sensor installed-node 1.04", U_CO2, ["CO2_Level_Sensor"]
            )
        },
    )
    binding = await _bind("What is the CO2 level in the atrium right now?", graph, STUFFY)

    assert binding.status == sb.STATUS_BOUND and binding.basis == sb.BASIS_OWN
    assert binding.display_scope == "the atrium (Room 1.04)"
    assert [s.uuid for s in binding.sensors] == [U_CO2]


async def test_a_zone_stands_in_only_when_the_room_has_none_and_says_so():
    zone_rows = _sensor_rows(
        "CO2_Z",
        "CO2 Level Sensor installed-node 5.01",
        U_ZONE_CO2,
        ["CO2_Level_Sensor"],
        zone=NS + "Zone_5.01",
        zlabel="HVAC Zone 5.01",
    )
    graph = _room_graph(
        places={"5.01": [_place_row("Room5.01", "Room 5.01 — Research Laboratory")]},
        own={"Room5.01": []},
        zone={"Room5.01": zone_rows},
    )
    binding = await _bind("How stuffy is Room 5.01?", graph, STUFFY)

    assert binding.basis == sb.BASIS_ZONE and [s.uuid for s in binding.sensors] == [U_ZONE_CO2]
    assert "comes from HVAC Zone 5.01, the zone that covers it" in binding.summary()


async def test_a_stand_in_in_the_room_does_not_outrank_the_zones_real_instrument():
    """The demo's room 5.01: the physical CO2 sensor is attached to the HVAC zone, the room only
    carries a generated stand-in. Answering from the stand-in changed a rehearsed answer and
    preferred a placeholder to the instrument."""
    stand_in = _sensor_rows(
        "CO2_sat", "Room 5.01 co2 [ppm]", U_SIM_TEMP, ["CO2_Level_Sensor"], sim="true"
    )
    zone_rows = _sensor_rows(
        "CO2_Z",
        "CO2 Level Sensor installed-node 5.01",
        U_ZONE_CO2,
        ["CO2_Level_Sensor"],
        zone=NS + "Zone_5.01",
        zlabel="HVAC Zone 5.01",
    )
    graph = _room_graph(
        places={"5.01": [_place_row("Room5.01", "Room 5.01 — Research Laboratory")]},
        own={"Room5.01": stand_in},
        zone={"Room5.01": zone_rows},
    )
    binding = await _bind("What is the CO2 level in room 5.01 right now?", graph, STUFFY)

    assert binding.basis == sb.BASIS_ZONE
    assert [s.uuid for s in binding.sensors] == [U_ZONE_CO2]  # said as a zone basis, not hidden


async def test_a_stand_in_alone_is_still_answered_from_when_the_zone_has_nothing_better():
    stand_in = _sensor_rows(
        "CO2_sat", "Room 5.01 co2 [ppm]", U_SIM_TEMP, ["CO2_Level_Sensor"], sim="true"
    )
    graph = _room_graph(
        places={"5.01": [_place_row("Room5.01", "Room 5.01 — Research Laboratory")]},
        own={"Room5.01": stand_in},
    )
    binding = await _bind("What is the CO2 level in room 5.01 right now?", graph, STUFFY)
    assert binding.basis == sb.BASIS_OWN and [s.uuid for s in binding.sensors] == [U_SIM_TEMP]


async def test_the_zone_is_not_consulted_when_the_room_has_the_sensor():
    graph = _room_graph()
    await _bind("How stuffy is Room 1.06 at the moment?", graph, STUFFY)
    assert not graph.ran("brick:hasPart|brick:feeds")


def test_a_room_and_its_zone_share_an_id_and_the_word_used_decides():
    said_room = sb.extract_scope_ask("temperature in room 5.01", [])
    said_zone = sb.extract_scope_ask("temperature in zone 5.01", [])
    hits = [
        sb.ScopeHit(NS + "Room5.01", "Room 5.01", is_room=True),
        sb.ScopeHit(NS + "Zone_5.01", "HVAC Zone 5.01", is_zone=True),
    ]
    assert sb.choose_place(said_room, hits)[0].iri == NS + "Room5.01"
    assert sb.choose_place(said_zone, hits)[0].iri == NS + "Zone_5.01"


async def test_a_measured_sensor_beats_a_stand_in_for_the_same_quantity():
    rows = _sensor_rows(
        "T_real",
        "Air Temperature Sensor 2.01",
        U_TEMP,
        ["Air_Temperature_Sensor", "Temperature_Sensor"],
    ) + _sensor_rows(
        "T_sim", "Room 2.01 temperature", U_SIM_TEMP, ["Air_Temperature_Sensor"], sim="true"
    )
    graph = _room_graph(
        places={"2.01": [_place_row("Room2.01", "Room 2.01 — Research Laboratory")]},
        own={"Room2.01": rows},
    )
    binding = await _bind("What is the temperature in Room 2.01?", graph, TEMPERATURE)
    assert [s.uuid for s in binding.sensors] == [U_TEMP]


async def test_only_a_stand_in_is_still_answered_from():
    """Silence would be a false absence: a placeholder is data the building holds."""
    binding = await _bind("How many people are in Room 1.06?", _room_graph(), PEOPLE)
    assert [s.simulated for s in binding.sensors] == [True]


# ── plant ────────────────────────────────────────────────────────────────────────────


async def test_the_heat_pump_loop_temperature_binds_both_water_points():
    graph = FakeGraph(
        equipment=[{"s": _cell(NS + "Heat_Pump_1", "uri"), "label": _cell("Heat Pump 1 — Plant")}],
        equip_points=_sensor_rows(
            "HP_in",
            "Heat Pump 1 entering water temperature",
            U_HP_IN,
            ["Entering_Water_Temperature_Sensor", "Temperature_Sensor"],
        )
        + _sensor_rows(
            "HP_out",
            "Heat Pump 1 leaving water temperature",
            U_HP_OUT,
            ["Leaving_Water_Temperature_Sensor", "Temperature_Sensor"],
        ),
    )
    binding = await _bind(
        "What is the current temperature of the heat pump water loop?", graph, TEMPERATURE
    )
    assert binding.basis == sb.BASIS_EQUIPMENT
    assert {s.uuid for s in binding.sensors} == {U_HP_IN, U_HP_OUT}
    assert binding.scope_label == "Heat Pump 1"


# ── the sparql-lane seam ─────────────────────────────────────────────────────────────


def _state(intent: str, concepts=None, entities=None):
    return SimpleNamespace(
        current_intent=intent,
        building_id="b1",
        intermediate_results={
            "intent": intent,
            "concepts": concepts or [],
            "entities": entities or [],
        },
    )


COUNT_RESULT = {
    "success": True,
    "results": {
        "head": {"vars": ["space", "sensor_count"]},
        "results": {
            "bindings": [{"space": _cell(NS + "Room1.06", "uri"), "sensor_count": _cell("9")}]
        },
    },
    "analytics_required": False,
    "formatted_response": "1.06 has 9 sensors",
}


async def test_a_sensor_count_result_is_replaced_by_the_bound_series():
    state = _state("sensor_data", STUFFY)
    out = await sb.apply_to_result(
        state,
        COUNT_RESULT,
        "How stuffy is Room 1.06 at the moment?",
        run=_room_graph(),
        namespace=NS,
    )
    assert out["method"] == "sensor_binder" and out["analytics_required"] is True
    bound = out["results"]["results"]["bindings"]
    assert [r["uuid"]["value"] for r in bound] == [U_CO2]
    assert state.intermediate_results["binder_scope"]["iri"] == NS + "Room1.06"
    assert state.intermediate_results["sensor_binding"]["basis"] == "own"


async def test_an_absence_takes_the_shape_the_typed_absence_readers_expect():
    state = _state(
        "sensor_data", [{"concept_id": "noisy", "brick_classes": ["ontosage:Sound_Level_Sensor"]}]
    )
    out = await sb.apply_to_result(
        state,
        COUNT_RESULT,
        "What is the noise level in Room 1.06?",
        run=_room_graph(),
        namespace=NS,
    )
    assert out["method"] == "typed_absence" and out["success"] is True
    assert out["analytics_required"] is False
    assert out["results"]["results"]["bindings"] == []  # a real, empty envelope, not a failure
    assert "no noise measurement for Room 1.06" in out["formatted_response"]


@pytest.mark.parametrize("intent", ["metadata", "discovery", "compare", "floor_plan", "general"])
async def test_intents_that_are_not_readings_are_left_alone(intent):
    graph = _room_graph()
    out = await sb.apply_to_result(
        _state(intent, STUFFY), COUNT_RESULT, "How stuffy is Room 1.06?", run=graph, namespace=NS
    )
    assert out is COUNT_RESULT and graph.queries == []


@pytest.mark.parametrize(
    "method",
    ["typed_absence", "whole_register", "whole_register_unavailable", "instrument_metrology"],
)
async def test_a_deterministic_answer_already_given_upstream_is_not_reopened(method):
    """A calibration date, a register or an absence the floor resolver proved are kept whole."""
    already = dict(COUNT_RESULT, method=method)
    graph = _room_graph()
    out = await sb.apply_to_result(
        _state("sensor_data", STUFFY), already, "How stuffy is Room 1.06?", run=graph, namespace=NS
    )
    assert out is already and graph.queries == []


async def test_the_semantic_fallback_is_what_gets_replaced():
    """It is the failure being repaired: prose over retrieved text, with no series behind it."""
    fallback = {"success": True, "method": "semantic_rag", "results": [{"answer": "..."}]}
    out = await sb.apply_to_result(
        _state("sensor_data", STUFFY),
        fallback,
        "How stuffy is Room 1.06 at the moment?",
        run=_room_graph(),
        namespace=NS,
    )
    assert out["method"] == "sensor_binder"


async def test_the_building_wide_population_replaces_only_a_result_with_no_ids():
    population = _sensor_rows(
        "R1", "Room 0.01 occupancy [persons]", U_OCC, ["Occupancy_Count_Sensor"]
    )
    question = "Which rooms are occupied at the moment?"

    out = await sb.apply_to_result(
        _state("analytics"),
        COUNT_RESULT,
        question,
        run=FakeGraph(population=population),
        namespace=NS,
    )
    assert out["method"] == "sensor_binder" and out["binder"]["basis"] == "population"

    with_ids = {
        "success": True,
        "results": {"results": {"bindings": [{"uuid": _cell(U_CO2), "label": _cell("x")}]}},
    }
    graph = FakeGraph(population=population)
    kept = await sb.apply_to_result(
        _state("analytics"), with_ids, question, run=graph, namespace=NS
    )
    assert kept is with_ids and not graph.ran("VALUES ?local")


async def test_a_sensor_declared_without_a_series_is_not_reported_as_absent():
    """BUG-475's shape: the room HAS the sensor; only the link to its readings is missing."""
    unlinked = [
        {
            "sensor": _cell(NS + "CO2_106", "uri"),
            "label": _cell("CO2 Level Sensor installed-node 1.06"),
            "cls": _cell(BRICK + "CO2_Level_Sensor", "uri"),
        }
    ]
    graph = _room_graph(own={"Room1.06": []}, declared={"Room1.06": unlinked})
    binding = await _bind("How stuffy is Room 1.06 at the moment?", graph, STUFFY)

    assert binding.status == sb.STATUS_ABSENT and binding.reason == "reference_missing"
    text = sb.absence_text(binding)
    assert "NOT telling you the sensor is absent" in text
    assert "no CO2" not in text and "nothing to read" not in text


async def test_a_quantity_the_catalogue_does_not_name_is_never_an_absence():
    """A concept class such as a fire alarm missing from a room is not a gap in the room."""
    fire = [{"concept_id": "fire_alarm", "brick_classes": ["brick:Fire_Alarm"]}]
    graph = _room_graph()
    binding = await _bind("Where is the fire alarm nearest Room 1.06?", graph, fire)
    assert binding.status == sb.STATUS_NOT_APPLICABLE
    assert binding.reason == "uncatalogued_quantity"


async def test_plant_with_no_matching_point_steps_aside_rather_than_claiming_absence():
    graph = FakeGraph(
        equipment=[{"s": _cell(NS + "Chiller_1", "uri"), "label": _cell("Chiller 1")}],
        equip_points=[],
    )
    binding = await _bind(
        "What is the noise level of the chiller?",
        graph,
        [{"concept_id": "noisy", "brick_classes": ["ontosage:Sound_Level_Sensor"]}],
    )
    assert binding.status == sb.STATUS_NOT_APPLICABLE and binding.reason == "equipment_no_match"


async def test_a_question_that_names_a_sensor_by_its_own_id_is_left_alone():
    """The number in "CO2_Level_Sensor_5.01" is a device's, not a room's."""
    graph = _room_graph()
    for question, entities in (
        ("What does CO2_Level_Sensor_5.01 read?", []),
        ("What is the reading?", ["bldg:CO2_Level_Sensor_5.01"]),
        ("What is the Air Temperature Sensor installed-node 5.01 reading?", []),
    ):
        binding = await _bind(question, graph, STUFFY, entities=entities)
        assert binding.status == sb.STATUS_NOT_APPLICABLE and binding.reason == "sensor_scope"
    assert graph.queries == []


@pytest.mark.parametrize(
    "result,expected",
    [
        ({"method": "semantic_rag", "results": [{"answer": "x"}]}, True),
        ({"results": {"results": {"bindings": []}}}, True),
        (COUNT_RESULT, True),
        (
            {"results": {"results": {"bindings": [{"label": _cell("a"), "type": _cell("b")}]}}},
            False,
        ),
        ({"results": {"results": {"bindings": [{"uuid": _cell(U_CO2)}]}}}, False),
    ],
)
def test_only_the_measured_retrieval_failures_may_be_repaired_building_wide(result, expected):
    """A count per space, nothing at all, or the semantic prose; never a label listing."""
    assert sb.retrieval_missed(result) is expected


async def test_a_building_wide_read_does_not_replace_a_result_that_is_merely_not_a_series():
    listing = {"results": {"results": {"bindings": [{"label": _cell("a"), "type": _cell("b")}]}}}
    graph = FakeGraph(
        population=_sensor_rows("R1", "Room 0.01 occupancy", U_OCC, ["Occupancy_Count_Sensor"])
    )
    out = await sb.apply_to_result(
        _state("analytics"),
        listing,
        "Which rooms are occupied at the moment?",
        run=graph,
        namespace=NS,
    )
    assert out is listing and not graph.ran("VALUES ?local")


async def test_the_rooms_only_population_query_asks_for_room_locations():
    graph = FakeGraph(
        population=_sensor_rows("R1", "Room 0.01 occupancy", U_OCC, ["Occupancy_Count_Sensor"])
    )
    await _bind("Which rooms are occupied at the moment?", graph)
    assert graph.ran("brick:hasLocation ?loc .\n  ?loc rdf:type/rdfs:subClassOf* brick:Room")

    graph = FakeGraph(population=_sensor_rows("R1", "Entry 1", U_OCC, ["Occupancy_Count_Sensor"]))
    await _bind("How many people are in the building at the moment?", graph, PEOPLE)
    assert not graph.ran("?loc rdf:type/rdfs:subClassOf* brick:Room")


async def test_sibling_modalities_split_by_label_are_not_taken_whole():
    """occupancy and parking_free share a class; the parking sensors must not be 'occupancy'."""
    rows = _sensor_rows("P1", "Parking bay 1", U_OCC, ["Occupancy_Count_Sensor"]) + _sensor_rows(
        "R1", "Room 1.06 occupancy [persons]", U_TEMP, ["Occupancy_Count_Sensor"]
    )
    binding = await _bind("Which rooms are occupied at the moment?", FakeGraph(population=rows))
    assert [s.uuid for s in binding.sensors] == [U_TEMP]


# ── scope extraction ─────────────────────────────────────────────────────────────────


@pytest.mark.parametrize(
    "question,kind,token",
    [
        ("How stuffy is Room 1.06 at the moment?", "space", "1.06"),
        ("temperature in room1.06.", "space", "1.06"),
        ("What is the CO2 level in the atrium right now?", "space", ""),
        ("What is the current temperature of the heat pump water loop?", "equipment", ""),
        ("What is the CO2 on floor 3?", "floor", ""),
        ("Which rooms are occupied at the moment?", "none", ""),
        ("How many people are in the building at the moment?", "none", ""),
        ("What was the CO2 in the last hour?", "none", ""),
    ],
)
def test_the_place_a_question_names_is_read_by_english_structure(question, kind, token):
    ask = sb.extract_scope_ask(question, [])
    assert ask.kind == kind and ask.id_token == token


def test_a_place_query_cannot_be_broken_out_of():
    query = sb._place_terms_query('atrium" } DROP', NS)
    assert '\\"' in query and 'atrium" }' not in query


# ── the forecast lane's history window ───────────────────────────────────────────────

NOW = datetime(2026, 9, 19, 0, 0, 0)


def test_a_forecast_window_in_the_future_is_dropped_so_history_can_be_read():
    got = sb.history_window(
        "What will the temperature be tomorrow in Room 2.01?",
        "trend",
        "2026-09-20 00:00:00",
        "2026-09-21 00:00:00",
        now=NOW,
    )
    assert got == (None, None)


def test_a_forecast_asked_over_a_past_window_keeps_it():
    got = sb.history_window(
        "Based on last week, predict tomorrow's temperature",
        "trend",
        "2026-09-12 00:00:00",
        "2026-09-19 00:00:00",
        now=NOW,
    )
    assert got == ("2026-09-12 00:00:00", "2026-09-19 00:00:00")


@pytest.mark.parametrize(
    "question,intent",
    [
        ("What was the temperature yesterday?", "trend"),
        ("What will the temperature be tomorrow?", "sensor_data"),
    ],
)
def test_only_a_forecast_question_has_its_window_rewritten(question, intent):
    window = ("2026-09-20 00:00:00", "2026-09-21 00:00:00")
    assert sb.history_window(question, intent, *window, now=NOW) == window
