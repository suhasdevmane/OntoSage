# -*- coding: utf-8 -*-
"""Answering "what does this building contain?" from Brick classes (BUG-122).

Capability triples describe what a building OFFERS. What it CONTAINS is already in
Brick, and nothing read that half — so "what equipment is installed in this
building?" declined with "I don't have that information on record" while the graph
held 149 equipment instances. A well-populated ontology reporting itself as empty is
worse than a slow answer.

The lookup matches the question's nouns against Brick CLASS names, which come from
the shared TBox rather than any building's vocabulary — that is what makes it
portable across buildings that name their individual units differently.
"""

import pytest

from orchestrator.services.ontology_inventory import (
    _query_terms,
    is_inventory_question,
    render_census,
)

pytestmark = pytest.mark.unit


@pytest.mark.parametrize(
    "query",
    [
        "What equipment is installed in this building?",
        "List all equipment in the building",
        "What types of equipment does this building have?",
        "which devices do we have?",
        "show me the meters",
        "what sensors are there?",
        "how many valves do you have?",
    ],
)
def test_inventory_questions_are_recognised(query):
    assert is_inventory_question(query) is True


@pytest.mark.parametrize(
    "query",
    [
        "What is the supply air temperature of AHU01N?",
        "Is it too warm in RM157?",
        "Show me floor 1",
        "What is a VAV box?",  # a definition, not an inventory
        "Hello",
        "",
    ],
)
def test_non_inventory_questions_are_left_alone(query):
    assert is_inventory_question(query) is False


def test_a_bare_noun_without_an_asking_shape_does_not_trigger():
    """ "the chiller is leaking" is a report, not a request for a census."""
    assert is_inventory_question("the chiller is leaking") is False


def test_query_terms_drop_filler_and_keep_the_subject():
    terms = _query_terms("What equipment is installed in this building?")
    assert "equipment" in terms
    for filler in ("building", "installed", "this", "what"):
        assert filler not in terms


def test_query_terms_singularise_so_a_plural_matches_the_class_name():
    assert "sensor" in _query_terms("what sensors are there?")
    assert "meter" in _query_terms("show me the meters")


def test_render_lists_every_class_with_its_live_count():
    out = render_census(
        [("HVAC_Equipment", 149), ("Variable_Air_Volume_Box", 132)], "Test Building"
    )
    assert "Test Building" in out
    assert "HVAC Equipment" in out and "149" in out
    assert "Variable Air Volume Box" in out and "132" in out
    assert "ontology" in out.lower(), "the answer must say where the figures came from"


def test_nothing_found_renders_nothing_rather_than_an_empty_claim():
    assert render_census([], "Test Building") is None


def test_no_building_literals_in_the_module():
    import inspect

    import orchestrator.services.ontology_inventory as mod

    src = inspect.getsource(mod).lower()
    for literal in ("bldg1", "bldg2", "bldg3", "abacws", "buildsys"):
        assert literal not in src, f"inventory lookup must not name a building: {literal}"


@pytest.mark.parametrize(
    "query",
    [
        "What is a VAV box?",
        "what is an air handling unit?",
        "explain what a chiller does",
        "define setpoint",
        "how does a heat pump work?",
        "what does a meter measure?",
    ],
)
def test_a_definition_is_not_answered_with_a_count(query):
    """These name an inventory noun and open like a question. Without the
    definitional guard they trigger a census, answering "what IS a VAV box"
    with "132 Variable Air Volume Box"."""
    assert is_inventory_question(query) is False


@pytest.mark.parametrize(
    "query", ["what are the meters?", "which sensors do we have?", "list the chillers"]
)
def test_plural_definite_questions_are_still_inventory(query):
    assert is_inventory_question(query) is True


def test_classes_naming_the_same_population_are_collapsed():
    """Brick types one set of boxes as VAV, Variable_Air_Volume_Box and
    Terminal_Unit at once. Listing all three reads like three different things,
    so the most descriptive name stands for the population."""
    from orchestrator.services.ontology_inventory import collapse_synonyms

    # Same span of instance URIs => the same population under different names.
    eq = ("bldg:VAV_001", "bldg:VAV_132")
    ahu = ("bldg:AHU_01", "bldg:AHU_16")
    got = collapse_synonyms(
        [
            ("Equipment", 149, "bldg:AHU_01", "bldg:VAV_132"),
            ("HVAC_Equipment", 149, "bldg:AHU_01", "bldg:VAV_132"),
            ("Terminal_Unit", 132, *eq),
            ("Variable_Air_Volume_Box", 132, *eq),
            ("VAV", 132, *eq),
            ("Air_Handling_Unit", 16, *ahu),
            ("AHU", 16, *ahu),
            ("Chiller", 1, "bldg:CH_1", "bldg:CH_1"),
        ]
    )
    assert got == [
        ("HVAC_Equipment", 149),
        ("Variable_Air_Volume_Box", 132),
        ("Air_Handling_Unit", 16),
        ("Chiller", 1),
    ]


def test_equal_counts_over_different_instances_are_both_kept():
    """The dangerous case: this building has 139 supply-air and 139 discharge-air
    temperature sensors that ARE the same dual-typed instances, but also 140
    zone-air sensors sharing none of them. Collapsing on count alone would be a
    guess; two same-sized but disjoint populations must both survive."""
    from orchestrator.services.ontology_inventory import collapse_synonyms

    got = collapse_synonyms(
        [
            ("Supply_Air_Temperature_Sensor", 139, "bldg:S_001", "bldg:S_139"),
            ("Discharge_Air_Temperature_Sensor", 139, "bldg:S_001", "bldg:S_139"),
            ("Exhaust_Air_Temperature_Sensor", 139, "bldg:E_001", "bldg:E_139"),
        ]
    )
    names = {n for n, _ in got}
    assert "Exhaust_Air_Temperature_Sensor" in names, "a disjoint population must not be dropped"
    assert len(got) == 2, "the two dual-typed names collapse; the disjoint one stands"


def test_distinct_populations_are_all_kept():
    from orchestrator.services.ontology_inventory import collapse_synonyms

    got = collapse_synonyms(
        [
            ("Fan", 4, "bldg:F1", "bldg:F4"),
            ("Pump", 3, "bldg:P1", "bldg:P3"),
            ("Boiler", 2, "bldg:B1", "bldg:B2"),
        ]
    )
    assert got == [("Fan", 4), ("Pump", 3), ("Boiler", 2)]


# ── one pipeline for "what does this building have" ──────────────────────────


def test_discovery_and_capability_share_the_same_census():
    """Both question families must group by the ontology, not by two different
    mechanisms that can drift apart or disagree with each other."""
    import inspect

    from orchestrator.agents import capability_agent
    from orchestrator.workflow import _orchestrator

    cap = inspect.getsource(capability_agent)
    orch = inspect.getsource(_orchestrator.WorkflowOrchestrator._ontology_census)
    assert "class_census" in cap, "capability path must use the shared census"
    assert "class_census" in orch, "discovery path must use the same shared census"


def test_label_grouping_is_documented_as_a_fallback_only():
    """Grouping by label only works for buildings that encode the type in the
    label — the defect that reported 600 sensors as 600 types of one each."""
    import inspect

    from orchestrator.workflow._orchestrator import WorkflowOrchestrator

    doc = inspect.getdoc(WorkflowOrchestrator._count_sensor_types) or ""
    assert "fallback" in doc.lower()
    assert "label" in doc.lower()


def test_census_grouping_wins_over_label_grouping_when_available():
    """A census must be used when present; the label parser is the last resort."""
    import inspect

    from orchestrator.workflow._orchestrator import WorkflowOrchestrator

    body = inspect.getsource(WorkflowOrchestrator._handle_sensor_discovery)
    census_at = body.index("if census:")
    fallback_at = body.index("_count_sensor_types(filtered)")
    assert census_at < fallback_at, "the ontology census must be consulted first"


# ── compound nouns must not be matched by their most generic word ────────────


async def test_compound_terms_are_tried_together_first(monkeypatch):
    """ "air handling unit" must match a class containing all three words. Matching
    any single word lets the most generic one win — "air" alone pulls in every
    air-temperature sensor, which answered a question about air handling units
    with the sensor census."""
    import orchestrator.services.ontology_inventory as mod

    seen = []

    async def _fake(terms, ns, ep, limit, *, require_all):
        seen.append(require_all)
        return [("Air_Handling_Unit", 16)] if require_all else [("Air_Temperature_Sensor", 294)]

    monkeypatch.setattr(mod, "_census_query", _fake)
    got = await mod.class_census("how many air handling units are there?", "ns:", "http://x")

    assert seen[0] is True, "the compound must be tried before any-word"
    assert got == [("Air_Handling_Unit", 16)]


async def test_any_word_is_tried_when_the_compound_finds_nothing(monkeypatch):
    import orchestrator.services.ontology_inventory as mod

    seen = []

    async def _fake(terms, ns, ep, limit, *, require_all):
        seen.append(require_all)
        return [] if require_all else [("Chiller", 1)]

    monkeypatch.setattr(mod, "_census_query", _fake)
    got = await mod.class_census("what chilled water plant do we have?", "ns:", "http://x")

    assert seen == [True, False]
    assert got == [("Chiller", 1)]
