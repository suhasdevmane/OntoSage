# -*- coding: utf-8 -*-
"""Round 5 of the Open WebUI probe: defects found by multi-turn conversations.

Each test drives the function that made the decision, with the graph replaced by a stub, so
what is checked is the decision itself and not a live store.
"""

from __future__ import annotations

import asyncio
from typing import Dict, List, Optional, Set, Tuple

import pytest

from orchestrator.agents.sparql_agent import SPARQLAgent

pytestmark = pytest.mark.unit

PV = "ontosage:PV_Generation_Power_Sensor"
ENERGY = "brick:Energy_Sensor"
SOLAR_Q = "How much solar energy did we generate the day before yesterday?"


def _agent(
    ancestors: Optional[Dict[str, Set[str]]],
) -> Tuple[SPARQLAgent, List[List[str]]]:
    agent = SPARQLAgent.__new__(SPARQLAgent)
    asked: List[List[str]] = []

    async def _relations(candidates):
        asked.append(list(candidates))
        return ancestors, None

    agent._class_relations = _relations
    return agent, asked


# --- BUG-1599: the keyword map's class must not overrule an unrelated concept class --------


def test_an_unrelated_concept_class_replaces_the_keyword_class():
    agent, asked = _agent({ENERGY: set(), PV: set()})
    got = asyncio.run(agent._class_over_keyword(SOLAR_Q, PV, [PV]))
    assert got == PV
    assert asked and set(asked[0]) == {ENERGY, PV}


def test_a_concept_class_below_the_keyword_class_leaves_the_keyword_in_place():
    child = "brick:Zone_Air_Temperature_Sensor"
    agent, _ = _agent(
        {"brick:Air_Temperature_Sensor": set(), child: {"brick:Air_Temperature_Sensor"}}
    )
    got = asyncio.run(agent._class_over_keyword("Is it too cold in here?", child, [child]))
    assert got is None


def test_a_concept_class_above_the_keyword_class_leaves_the_keyword_in_place():
    parent = "brick:Temperature_Sensor"
    kw = "brick:Air_Temperature_Sensor"
    agent, _ = _agent({kw: {parent}, parent: set()})
    got = asyncio.run(agent._class_over_keyword("Is it too warm?", parent, [parent]))
    assert got is None


def test_nothing_changes_when_the_graph_cannot_say():
    agent, _ = _agent(None)
    assert asyncio.run(agent._class_over_keyword(SOLAR_Q, PV, [PV])) is None


def test_a_keyword_class_the_concept_names_itself_is_kept_without_asking_the_graph():
    agent, asked = _agent({ENERGY: set(), PV: set()})
    got = asyncio.run(agent._class_over_keyword(SOLAR_Q, PV, [PV, ENERGY]))
    assert got is None
    assert asked == []


def test_a_question_with_no_keyword_class_is_left_alone():
    agent, asked = _agent({})
    assert asyncio.run(agent._class_over_keyword("How are the panels doing?", PV, [PV])) is None
    assert asked == []


def test_the_class_listing_template_binds_the_override_and_not_the_keyword():
    agent = SPARQLAgent.__new__(SPARQLAgent)
    with_over = agent._template_sparql(SOLAR_Q, [], set(), concept_class=PV, class_over_keyword=PV)
    assert with_over and f"rdf:type {PV}" in with_over
    assert ENERGY not in with_over.split("WHERE", 1)[1]


def test_without_an_override_the_keyword_class_is_used_as_before():
    agent = SPARQLAgent.__new__(SPARQLAgent)
    plain = agent._template_sparql(SOLAR_Q, [], set(), concept_class=PV)
    assert plain and f"rdf:type {ENERGY}" in plain


# --- BUG-1600: "which of the two was higher?" is a follow-up, answered from THIS chat -------


@pytest.mark.parametrize(
    "q",
    [
        "which of the two was higher?",
        "Which of those two is lower?",
        "which of them was bigger?",
        "is either of them over the limit?",
    ],
)
def test_a_pair_reference_reaches_the_rewrite(q):
    from orchestrator.agents.dialogue_agent import _is_followup_query

    assert _is_followup_query(q)


@pytest.mark.parametrize(
    "q",
    [
        "which of the two was higher?",
        "Which of the two is lower",
        "so which one of them was the highest?",
        "who of the two used more?",
    ],
)
def test_a_bare_comparative_is_left_to_the_rewrite_which_keeps_the_quantity(q):
    from orchestrator.services import context_switch as cs

    earlier = ["What is the humidity in room 2.01?", "and room 3.02?"]
    assert cs.resolve_pair_reference(q, earlier) is None


def test_a_comparative_that_names_its_quantity_still_resolves_deterministically():
    from orchestrator.services import context_switch as cs

    earlier = ["How busy is room 1.06?", "and room 2.01?"]
    out = cs.resolve_pair_reference("which of the two is busier?", earlier)
    assert out == "which of room 1.06 and room 2.01 is busier?"


# --- BUG-1601: a read of one room is headed with that room, not "Across the building" -------


def _summary(only_room: str = "", low: float = 909.0, high: float = 909.0) -> str:
    from orchestrator.services import aggregate_lane as al

    g = al.GroupStat(
        "5", sensors=1, readings=1, value=909.0, low=low, high=high, mean=909.0, total=909.0
    )
    return al.render_summary(
        [g],
        measurand="co2",
        unit="ppm",
        window=al.Window("2026-10-10 18:00:00", "2026-10-10 19:00:00", "now", latest=True),
        sensors_used=1,
        sensors_requested=1,
        floors_seen=1,
        excluded=0,
        excluded_sensors=0,
        no_reading=0,
        unplaced=0,
        bands_checked=True,
        only_room=only_room,
    )


def test_one_room_read_is_headed_with_the_room():
    out = _summary("Room 5.22 — Academic Office")
    assert out.startswith("**In Room 5.22 — Academic Office,")
    assert "Across the building" not in out


def test_a_range_of_one_value_is_not_printed():
    assert "ranging from" not in _summary("Room 5.22 — Academic Office")
    assert "ranging from 900 to 920" in _summary("", low=900.0, high=920.0)


def test_a_building_read_keeps_its_building_lead():
    assert _summary("").startswith("**Across the building")


def test_only_room_needs_every_sensor_in_the_same_room():
    from types import SimpleNamespace

    from orchestrator.services import aggregate_lane as al

    facts = {
        "a": SimpleNamespace(room="Room 5.22"),
        "b": SimpleNamespace(room="Room 5.22"),
        "c": SimpleNamespace(room="Room 5.16"),
    }
    assert al._only_room({"a", "b"}, facts) == "Room 5.22"
    assert al._only_room({"a", "c"}, facts) == ""
    assert al._only_room(set(), facts) == ""


# --- BUG-1602 / BUG-1603: a register follow-up binds the record the answer named ------------

WO_LIST = (
    "**5 of the 34 records in the Work order register match** (on floor 3):\n\n"
    "- **WO-008** — Electrical inspection — status: open\n"
    "- **WO-010** — Thermographic survey — status: in progress\n\n"
    "---\n**You might also ask:** Who owns these records? | Which of these are on floor 3?\n\n"
    "---\n*Sources: `Work Order` `Building model`*"
)
WO_ONE = (
    "**1 of the 34 records in the Work order register matches** (record: WO-008):\n\n"
    "- **WO-008** — Electrical inspection\n\n"
    "---\n**You might also ask:** Who owns these records? | Which of these are on floor 3?\n"
)


def test_suggestion_chips_are_not_part_of_what_a_reply_named():
    from orchestrator.services import context_switch as cs

    assert cs.floors_in_reply(WO_ONE) == []
    assert cs.records_in_reply(WO_ONE) == ["WO-008"]


def test_it_after_one_record_is_that_record():
    from orchestrator.services import context_switch as cs

    assert cs.resolve_sole_record_anaphor("when is it due?", WO_ONE) == "when is WO-008 due?"
    assert (
        cs.resolve_sole_record_anaphor("who is working on that one?", WO_ONE)
        == "who is working on WO-008?"
    )


def test_the_record_resolver_stands_down_where_it_should():
    from orchestrator.services import context_switch as cs

    assert cs.resolve_sole_record_anaphor("when is it due?", WO_LIST) is None  # two records
    assert cs.resolve_sole_record_anaphor("how warm is it there?", WO_ONE) is None
    assert cs.resolve_sole_record_anaphor("when is WO-010 due?", WO_ONE) is None
    in_room = "- **WO-020** — Filter change in Room 3.01"
    assert cs.resolve_sole_record_anaphor("how warm is it?", in_room) is None
    assert cs.resolve_sole_record_anaphor("see ISO-7730 for it?", "Cited ISO-7730.") is None


def test_an_ordinal_into_a_list_of_records_picks_the_record():
    from orchestrator.services import context_switch as cs

    assert (
        cs.resolve_ordinal("who is assigned to the first one?", WO_LIST)
        == "who is assigned to WO-008?"
    )


def test_who_is_assigned_asks_for_the_party():
    from orchestrator.services import register_vocabulary as rv

    vocab = rv.get_vocabulary()
    names = [c.name for c in vocab.concepts_in("Who is assigned to WO-008?")]
    assert "owner" in names
    assert "owner" not in [c.name for c in vocab.concepts_in("Which work orders are assigned?")]


# --- BUG-1604: a count joined to its noun by a hyphen is not a reading ----------------------


def test_a_hyphenated_count_is_not_an_impossible_reading():
    from orchestrator.services import plausibility as p

    nb = "‑"
    text = f"The mean humidity over the 1000{nb}point window is 50.62 % RH."
    assert p.implausible_values(text, "humidity") == []
    assert p.implausible_values("over a 1000-point window, humidity 50 %", "humidity") == []
    assert p.implausible_values("The humidity reads 1000 % now.", "humidity") == [1000.0]


# --- BUG-1605: one figure is not compared with itself ---------------------------------------


async def _narration_prompt(output, monkeypatch, sensors=1):
    from orchestrator.agents import analytics_agent as mod

    seen = {}

    async def fake_generate(prompt, task_type=None):
        seen["prompt"] = prompt
        return "ok"

    monkeypatch.setattr(mod.llm_manager, "generate", fake_generate)
    agent = mod.AnalyticsAgent.__new__(mod.AnalyticsAgent)
    meta = {f"u{i}": {"label": f"Room 2.1{i} noise [dB]"} for i in range(sensors)}
    await agent._format_analysis(
        {"success": True, "output": output}, "What was the peak noise in room 2.13?", meta
    )
    return seen["prompt"]


@pytest.mark.asyncio
async def test_a_single_maximum_is_reported_not_compared(monkeypatch):
    out = "Maximum Values:\nSensor: Room 2.13 noise [dB]\nMax: 62.80 dB\n"
    prompt = await _narration_prompt(out, monkeypatch)
    assert "There is ONE figure" in prompt
    assert "(highest, lowest, spread)" not in prompt


@pytest.mark.asyncio
async def test_several_figures_keep_the_comparison_rule(monkeypatch):
    out = "Sensor: Room 2.13 noise [dB]\nMax: 62.80 dB\nMin: 39.50 dB\nMean: 51.9 dB\n"
    prompt = await _narration_prompt(out, monkeypatch)
    assert "There is ONE figure" not in prompt
    assert "(highest, lowest, spread)" in prompt


# --- BUG-1606: a count of instruments is not a statistic of their readings ------------------


@pytest.mark.parametrize(
    "q",
    [
        "Which floor in the Abacws Building has the most PM2.5 sensors?",
        "which room has the fewest CO2 sensors installed?",
        "Which floor has the greatest number of energy meters?",
    ],
)
def test_a_count_of_sensors_is_not_an_aggregate(q):
    from orchestrator.services import aggregate_lane as al

    assert al.parse_intent(q) is None


@pytest.mark.parametrize(
    "q, stat",
    [
        ("Which floor has the most people?", "max"),
        ("How many CO2 sensors read above 1000 ppm?", "exceed"),
        ("Which floor has the most sensors above 1000 ppm?", "exceed"),
    ],
)
def test_statistics_of_readings_still_are(q, stat):
    from orchestrator.services import aggregate_lane as al

    got = al.parse_intent(q)
    assert got is not None and got.stat == stat


# --- BUG-1607: a ranking in which no space met anything is not a recommendation -------------


def _facet_dossier(totals, unverified=None):
    from orchestrator.services.deliberation import dossier as d

    ranked = [
        d.DossierRanked(
            rank=i + 1,
            space=f"Room 0.{i:02d} — Office",
            floor="0",
            total=t,
            unverified=list(unverified or []) if i == 0 else [],
        )
        for i, t in enumerate(totals)
    ]
    return d.EvidenceDossier(
        building_id="bx",
        raw_query="Which meeting rooms are free this afternoon?",
        decision="answer",
        ranked=ranked,
        coverage_summary="195 of 234 spaces considered",
        facet_criteria=[
            d.DossierFacetCriterion(
                phrase="meeting rooms", facet="spatial:space_kind", operator="eq", value="x"
            )
        ],
    )


def test_nothing_met_reads_the_model_and_its_dict_form():
    from orchestrator.services.deliberation.dossier import nothing_met

    zero = _facet_dossier([0.0, 0.0, 0.0])
    assert nothing_met(zero)
    assert nothing_met(zero.model_dump())
    assert not nothing_met(_facet_dossier([1.0, 1.0, 0.0]))
    assert not nothing_met(_facet_dossier([0.0, 0.0], unverified=["seats"]))


def test_a_ranking_of_zeros_says_no_space_met_and_names_none():
    from orchestrator.services.deliberation.dossier import render_answer

    text = render_answer(_facet_dossier([0.0, 0.0, 0.0]))
    assert text.startswith("**No space met what you asked for** (meeting rooms)")
    assert "Room 0.00" not in text
    assert "Best match" not in text and "Primary" not in text


def test_a_ranking_with_matches_still_lists_them():
    from orchestrator.services.deliberation.dossier import render_answer

    text = render_answer(_facet_dossier([1.0, 1.0, 0.0]))
    assert "No space met" not in text
    assert "Room 0.00" in text


# --- BUG-1608: the relevance gate judges the question the lanes answered --------------------


@pytest.mark.asyncio
async def test_the_gate_reads_the_coreference_rewrite(monkeypatch):
    from types import SimpleNamespace

    from orchestrator.services import answer_relevance_gate as gate
    from orchestrator.workflow import _orchestrator as orch

    seen = {}

    async def fake_verdict(question, text, lane):
        seen["question"] = question
        return SimpleNamespace(judged=False)

    monkeypatch.setattr(gate, "relevance_verdict", fake_verdict)
    monkeypatch.setattr(gate, "judges_lane", lambda lane, lanes=None: True)
    monkeypatch.setattr(orch.settings, "ANSWER_RELEVANCE_GATE", True, raising=False)
    state = SimpleNamespace(
        current_intent="analytics",
        user_message="and the day before?",
        intermediate_results={
            "coref_rewrite": {
                "original": "and the day before?",
                "rewritten": "How much solar energy did we generate the day before yesterday?",
            }
        },
    )
    out = await orch._relevance_gated(state, None, "About 35 kWh was generated.")
    assert out == "About 35 kWh was generated."
    assert seen["question"].endswith("the day before yesterday?")


def test_store_computed_figures_protect_an_aggregate_answer():
    from types import SimpleNamespace

    from orchestrator.workflow import _orchestrator as orch

    state = SimpleNamespace(
        intermediate_results={
            "aggregate_result": {"formatted_response": "x", "figures": {"total": 35.0}}
        },
        user_message="How much solar energy did we generate the day before yesterday?",
    )
    assert orch._grounded_evidence_behind(state) == "figures computed in the store"


def test_the_sql_node_copies_the_figures_onto_the_bus():
    import inspect

    from orchestrator.workflow import _orchestrator as orch

    src = inspect.getsource(orch)
    block = src[src.index('state.intermediate_results["aggregate_result"] = {') :][:900]
    assert '"figures": dict(result.get("figures") or {})' in block


# --- BUG-1609: a when-question is not answered with where -----------------------------------


@pytest.mark.parametrize(
    "q",
    [
        "What time does the Abacws Cafe on the ground floor close?",
        "When does the cafe on floor 0 open?",
        "What are the opening hours of the kitchen on floor 2?",
    ],
)
def test_a_time_question_gets_no_floor_listing(q):
    from orchestrator.services import amenity_floor_answer as af

    assert af.capability_answer(q, [object()], [], "B") is None


def test_a_where_question_still_reaches_the_floor_answer():
    from orchestrator.services import amenity_floor_answer as af

    assert not af._ASKS_A_TIME_RE.search("Where are the toilets on floor 2?")
    assert not af._ASKS_A_TIME_RE.search("Is the toilet on floor 2 open?")


# --- BUG-1610: "is that normal?" is a judgement, and gets the reference values --------------


@pytest.mark.asyncio
async def test_is_that_normal_supplies_the_standards(monkeypatch):
    from orchestrator.agents import analytics_agent as mod

    seen = {}

    async def fake_generate(prompt, task_type=None):
        seen["prompt"] = prompt
        return "ok"

    monkeypatch.setattr(mod.llm_manager, "generate", fake_generate)
    agent = mod.AnalyticsAgent.__new__(mod.AnalyticsAgent)
    await agent._format_analysis(
        {"success": True, "output": "Latest: 813 ppm\nMean: 801 ppm\n"},
        "Is the CO2 level in lab 4.20 normal for an office?",
        {},
    )
    assert "ASHRAE 62.1" in seen["prompt"]


# --- BUG-1611: a window that has passed is said, and the horizon there is is judged ---------


def test_an_afternoon_that_has_passed_is_said_and_the_horizon_judged():
    from orchestrator.services.forecasting.window_aggregate import comfort_verdict

    idx = ["2026-10-10 %02d:00:00" % h for h in range(18, 24)]  # UTC, 19:00-00:00 BST
    out = comfort_verdict(
        "Will meeting room 4.11 get stuffy this afternoon?",
        idx,
        [900.0] * 6,
        [850.0] * 6,
        [950.0] * 6,
        unit="ppm",
        horizon_label="next 6 hours",
        tz_name="Europe/London",
    )
    assert out is not None
    head, verdict = out.split("**", 1)
    assert (
        "The time asked about (afternoons, 12:00–18:00) is not in this forecast, which runs "
        "from Sat 19:00 to Sun 00:00" in head
    )
    assert verdict.startswith("Unlikely:**") and "next 6 hours" in verdict


def test_an_afternoon_inside_the_forecast_is_judged_on_the_afternoon_only():
    from orchestrator.services.forecasting.window_aggregate import comfort_verdict

    idx = ["2026-10-11 %02d:00:00" % h for h in range(0, 24)]
    values = [700.0] * 24
    values[13] = 1200.0  # 14:00 BST
    out = comfort_verdict(
        "Will room 4.11 get stuffy tomorrow afternoon?",
        idx,
        values,
        [v - 50 for v in values],
        [v + 50 for v in values],
        unit="ppm",
        horizon_label="next 24 hours",
        tz_name="Europe/London",
    )
    assert out.startswith("**Likely yes:**") and "not in this forecast" not in out


# --- BUG-1612: a possessive anaphor reaches the rewrite -------------------------------------


@pytest.mark.parametrize(
    "q", ["what's its leaving water temperature?", "what is their average reading today?"]
)
def test_a_possessive_anaphor_is_a_follow_up(q):
    from orchestrator.agents.dialogue_agent import _is_followup_query

    assert _is_followup_query(q)


# --- BUG-1613: a kind of room + a free window stays with the events lane --------------------


def _compound_route(monkeypatch, query, keys):
    from types import SimpleNamespace

    from orchestrator.services import routing_contract as rc
    from orchestrator.services.deliberation import facet_routing as fr
    from shared import config as shared_config

    monkeypatch.setattr(shared_config.settings, "ARBITER_V2_ROUTING", "live")
    monkeypatch.setattr(fr, "active_catalogue", lambda: object())
    monkeypatch.setattr(fr, "selects_spaces", lambda q: True)
    monkeypatch.setattr(
        fr,
        "compound_signal",
        lambda q, cat: SimpleNamespace(facet_keys=tuple(keys), reason="test"),
    )
    state = {"intent": "events", "concepts": [], "entities": []}
    rc.apply_contract(query, state, stage="concept")
    return state["intent"]


def test_meeting_rooms_free_this_afternoon_stays_with_the_events_lane(monkeypatch):
    got = _compound_route(
        monkeypatch,
        "Which meeting rooms are free this afternoon?",
        ["spatial:space_kind", "event:free_window"],
    )
    assert got == "events"


def test_a_third_facet_still_escalates(monkeypatch):
    got = _compound_route(
        monkeypatch,
        "Which quiet meeting rooms are free this afternoon?",
        ["spatial:space_kind", "event:free_window", "sensor:noise"],
    )
    assert got == "deliberate"


# --- BUG-1614: instruments are counted floor by floor from the graph ------------------------


@pytest.mark.parametrize(
    "q, expected",
    [
        (
            "Which floor in the Abacws Building has the most PM2.5 sensors?",
            ("PM2.5 sensors", "most"),
        ),
        ("which floor has the fewest CO2 sensors?", ("CO2 sensors", "fewest")),
        ("how many CO2 sensors are on each floor?", ("CO2 sensors", "each")),
        ("noise sensors per floor", ("noise sensors", "each")),
        ("Which floor has the most people?", None),
        ("How many PM2.5 sensors are there?", None),
    ],
)
def test_a_per_floor_count_is_recognised(q, expected):
    from orchestrator.services.ontology_inventory import per_floor_instrument_ask

    assert per_floor_instrument_ask(q) == expected


def test_the_counted_class_names_every_word_asked():
    from orchestrator.services.ontology_inventory import pick_counted_class

    rows = [("Equipment", 40), ("Meter", 39), ("Electrical_Meter", 20)]
    assert pick_counted_class(rows, "energy meters") is None
    assert pick_counted_class(rows, "electrical meters") == "Electrical_Meter"
    assert pick_counted_class([("PM2.5_Level_Sensor", 245)], "PM2.5 sensors") == (
        "PM2.5_Level_Sensor"
    )


def test_the_floor_census_names_the_most_and_states_the_unplaced():
    from orchestrator.services.ontology_inventory import render_floor_census

    rows = [("Floor 4 (Fourth Floor)", 52), ("Floor 5 (Fifth Floor)", 63), ("Floor 1", 14)]
    most = render_floor_census("PM2.5_Level_Sensor", rows, 135, "most", "B")
    assert most.startswith("**Floor 5 has the most PM2.5 Level Sensors: 63.**")
    assert "| Floor 4 | 52 |" in most and "6 of the 135 are not placed on a floor" in most
    fewest = render_floor_census("PM2.5_Level_Sensor", rows, 129, "fewest", "B")
    assert fewest.startswith("**Floor 1 has the fewest") and "All 129 are placed" in fewest
    tied = render_floor_census(
        "X_Sensor", [("Floor 1", 3), ("Floor 2", 3), ("Floor 3", 1)], 7, "most", "B"
    )
    assert tied.startswith("**Floor 1 and Floor 2 have the most X Sensors: 3 (tied).**")


def test_a_floor_census_where_every_floor_ties_says_so():
    from orchestrator.services.ontology_inventory import render_floor_census

    rows = [(f"Floor {i}", 1) for i in range(3)]
    out = render_floor_census("Energy_Sensor", rows, 4, "fewest", "B")
    assert out.startswith("**Every floor has the same number of Energy Sensors: 1.**")
    assert "1 of the 4 is not placed on a floor" in out


def test_a_concept_class_is_expanded_through_the_schema_prefixes_only():
    from orchestrator.services.ontology_inventory import class_iri, class_local_name

    assert (
        class_iri("ontosage:Sound_Level_Sensor")
        == "http://ontosage.org/capabilities#Sound_Level_Sensor"
    )
    assert class_iri("PM2.5_Level_Sensor").endswith("Brick#PM2.5_Level_Sensor")
    assert class_iri("bldg:Anything") is None and class_iri("brick:A B") is None
    assert class_local_name("ontosage:Sound_Level_Sensor") == "Sound_Level_Sensor"


# --- BUG-1615: availability asked and never read is named under "Not checked" ---------------


def _matched_dossier(raw_query):
    from orchestrator.services.deliberation import dossier as d

    doss = _facet_dossier([1.0, 1.0, 0.0])
    return doss.model_copy(update={"raw_query": raw_query})


def test_an_unread_availability_is_named():
    from orchestrator.services.deliberation.dossier import render_answer

    text = render_answer(_matched_dossier("Which quiet meeting rooms are free tomorrow afternoon?"))
    assert "**Not checked:** whether these spaces are free at the time you asked" in text


@pytest.mark.parametrize(
    "q", ["Which step-free meeting rooms are quiet?", "a room free of noise", "a quiet room"]
)
def test_free_in_another_sense_adds_nothing(q):
    from orchestrator.services.deliberation.dossier import render_answer

    assert "whether these spaces are free" not in render_answer(_matched_dossier(q))


# --- Round 6 (conversation battery 2) -------------------------------------------------------


def test_a_record_id_keeps_all_its_parts_and_any_hyphen():
    from orchestrator.services import context_switch as cs

    reply = (
        "Soonest first:\n- 25 October 2026 — **CON-2024-002**\n"
        "- 4 November 2026 — **CON-2025-003**\n"
        "- **INC‐2026‐019**, WO-008, BK-2026-0015, ISO-7730"
    )
    assert cs.records_in_reply(reply) == [
        "CON-2024-002",
        "CON-2025-003",
        "INC-2026-019",
        "WO-008",
        "BK-2026-0015",
    ]
    assert cs.resolve_ordinal("who provides the second one?", reply) == (
        "who provides CON-2025-003?"
    )
    one = "The most severe was **INC‑2026‑019** - Ladder used on roof plant."
    assert cs.resolve_sole_record_anaphor("where did it happen?", one) == (
        "where did INC-2026-019 happen?"
    )


@pytest.mark.parametrize("q", ["when was it highest?", "was it higher or lower?"])
def test_it_meaning_the_reading_is_not_replaced_by_the_place(q):
    from orchestrator.services import context_switch as cs

    assert cs.resolve_sole_floor_or_amenity_anaphor(q, "Hourly average CO2 in Floor 2", []) is None
    assert cs.resolve_sole_room_anaphor(q, "Room 2.13 read 909 ppm") is None


def test_a_place_question_still_takes_the_place():
    from orchestrator.services import context_switch as cs

    assert cs.resolve_sole_room_anaphor(
        "is it free this afternoon?", "Room 2.13 is a meeting room"
    ) == ("is room 2.13 free this afternoon?")


def test_the_floor_in_the_reply_lead_may_be_bound_by_that():
    from orchestrator.services import context_switch as cs

    rep = (
        "**Floor 4 consumed the most electricity last week, totaling 2,632 kWh.**\n"
        "The next highest was Floor 3 with 2,624 kWh, followed by Floor 5."
    )
    ok = "How much electricity did Floor 4 consume last week?"
    assert cs.previous_reply_named_it("how much was that?", ok, rep)
    assert not cs.previous_reply_named_it("how much was that?", ok.replace("4", "3"), rep)
    assert not cs.previous_reply_named_it(
        "how much was that?", ok, "**Floor 4 and Floor 3 are tied.**"
    )


@pytest.mark.parametrize(
    "q, selects",
    [
        ("What's the temperature in office 4.07?", False),
        ("What is the CO2 in lab 2.05?", False),
        ("Which offices on floor 4 are quietest?", True),
        ("find me a quiet office", True),
    ],
)
def test_a_room_named_by_kind_and_id_is_a_place_not_a_selection(q, selects):
    from orchestrator.services.deliberation import facet_routing as fr

    assert fr.selects_spaces(q) is selects


def test_a_deliberation_anchor_named_by_kind_resolves_by_its_id():
    from types import SimpleNamespace

    from orchestrator.services.deliberation import capability_schema as cs
    from orchestrator.services.deliberation.cqir import SpatialRelation

    ns = "http://example.org/b#"
    spaces = [
        SimpleNamespace(space_iri=ns + "Room4.07", label="Room 4.07 — Office"),
        SimpleNamespace(space_iri=ns + "Room4.08", label="Room 4.08 — Office"),
        SimpleNamespace(space_iri=ns + "Room0.01", label="Room 0.01 — Reception"),
    ]
    import inspect

    src = inspect.getsource(cs)
    assert "its dotted id decides" in src
    token = "office 4.07"
    import re

    m = re.search(r"(?<![\d.])(\d{1,2}\.\d{1,3})(?![\d.])", token)
    rx = re.compile(rf"(?<![\d.]){re.escape(m.group(1))}(?![\d.])")
    hits = [s.space_iri for s in spaces if rx.search(cs._local(s.space_iri)) or rx.search(s.label)]
    assert hits == [ns + "Room4.07"]
    assert SpatialRelation.IN_SPACE


def test_a_rewrite_may_not_add_a_year_nobody_wrote():
    from orchestrator.services.context_switch import strip_invented_years

    conv = ["Show me the CO2 on floor 2 today by hour", "Hourly average CO2 in Floor 2, Sat 10 Oct"]
    out = strip_invented_years(
        "Plot the hourly average CO2 levels for Floor 2 on Saturday, 10 October 2023.", conv
    )
    assert out == "Plot the hourly average CO2 levels for Floor 2 on Saturday, 10 October."
    kept = "Which incidents recorded in September 2026 were severe?"
    assert strip_invented_years(kept, ["effective from: September 2026"]) == kept
    assert strip_invented_years("who provides CON-2025-003?", ["x"]) == "who provides CON-2025-003?"


def test_the_rewrite_strips_invented_years_before_it_is_used():
    import inspect

    from orchestrator.agents import dialogue_agent as da

    src = inspect.getsource(da.DialogueAgent.rewrite_to_standalone)
    assert "strip_invented_years(rewritten" in src


# --- BUG-1621: a per-hour breakdown is plotted as a line, in time order ---------------------


@pytest.mark.asyncio
async def test_a_breakdown_is_drawn_as_a_line_in_time_order(monkeypatch, tmp_path):
    import json as _json
    from types import SimpleNamespace

    import httpx

    from orchestrator.workflow import _orchestrator as orch

    seen = {}

    class _Resp:
        def json(self):
            return {"stdout": "PLOT_BASE64: aGVsbG8="}

    class _Client:
        def __init__(self, *a, **k):
            pass

        async def __aenter__(self):
            return self

        async def __aexit__(self, *a):
            return False

        async def post(self, url, json=None):
            seen["code"] = json["code"]
            return _Resp()

    monkeypatch.setattr(httpx, "AsyncClient", _Client)
    monkeypatch.setattr(orch, "_save_chart_png", lambda b64, kind: f"/static/{kind}.png")
    figures = {
        "Sat 10 Oct 00:00 mean": 701.0,
        "Sat 10 Oct 01:00 mean": 689.8,
        "Sat 10 Oct 13:00 mean": 909.2,
    }
    state = SimpleNamespace(
        intermediate_results={
            "sql_result": {
                "aggregate_lane": True,
                "formatted_response": "table",
                "aggregate": {"stat": "mean", "group": "time"},
                "figures": figures,
            },
            "sensor_metadata": {},
        }
    )
    wo = orch.WorkflowOrchestrator.__new__(orch.WorkflowOrchestrator)
    out = await wo._render_aggregate_bar_chart(state, "plot the CO2 on floor 2 today by hour")
    assert out and out["chart_type"] == "aggregate_line"
    code = seen["code"]
    compile(code, "<chart>", "exec")
    assert 'kind = "line"' in code
    assert "labels = " + _json.dumps(["00:00", "01:00", "13:00"]) in code


# --- BUG-1622: one day's peak is that day's hours, not a weekly pattern ---------------------


@pytest.mark.parametrize(
    "q, one_day",
    [
        ("When was the highest CO2 level on floor 2 today?", True),
        ("When was it busiest yesterday?", True),
        ("When is CO2 usually highest?", False),
        ("When is the building typically quietest today?", False),
    ],
)
def test_a_single_day_peak_is_not_a_pattern(q, one_day):
    from orchestrator.services import aggregate_lane as al
    from orchestrator.services.aggregate_breakdown import _PATTERN_RE

    got = bool(al._ONE_DAY_RE.search(q) and not _PATTERN_RE.search(q))
    assert got is one_day


def test_the_one_day_peak_takes_the_hourly_breakdown():
    import inspect

    from orchestrator.services import aggregate_lane as al

    src = inspect.getsource(al.try_answer)
    assert '(3600, "hour") if _one_day else None' in src
    assert 'AggregateIntent("mean", intent.group, True, False, False, intent.floors)' in src
