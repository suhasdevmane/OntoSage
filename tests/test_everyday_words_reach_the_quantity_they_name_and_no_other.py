"""Everyday words reach the measured quantity they name, and the quantities the building does not
measure keep their honest decline.

Two findings from docs/REACH_2026-09-19.md, both checked against the real vocabulary:

1. Its top "lay terms reaching no concept" ('air quality', 'co2', 'co2 level', 'fire', 'water
   usage') already had concepts. The offline loader read `?c a hbco:Concept` with rdflib, which
   does not infer `hbco:CompositeConcept rdfs:subClassOf hbco:Concept` (ontosage_schema.ttl), so the
   13 composite concepts -- the ones with the commonest words -- were invisible to the MEASUREMENT.
   GraphDB infers it, so the live system was fine. The loader now does the same.
2. The words that genuinely reached nothing split into quantities the building MEASURES (mapped
   here, each with two real example questions) and words that name a record, an amenity, a
   quantity it does not measure, or nothing at all (NOT mapped: 'security', 'safety', 'safe',
   'quality', 'maintenance', 'access', 'sustainability', 'stairwells', 'voltage', 'ozone',
   'standby', 'backup', 'unusual', 'data', 'power'). Mapping 'voltage' would turn "voltage is not
   measured here" into a reading of some other sensor; 'unusual' would send every anomaly question
   to the temperature and CO2 sensors.
"""

import asyncio
import importlib.util
import sys
from pathlib import Path
from typing import Dict, List

import pytest
import rdflib
from rdflib.namespace import RDFS

from orchestrator.services.concept_resolver import ConceptResolver
from orchestrator.services.grounding_guard import has_measurand_concept

pytestmark = pytest.mark.unit

REPO = Path(__file__).resolve().parents[1]
HBCO = "http://ontosage.org/hbco#"


def _real_map() -> Dict[str, dict]:
    graph = rdflib.Graph()
    graph.parse(str(REPO / "ontology" / "hbco_mappings.ttl"), format="turtle")
    by: Dict[str, dict] = {}
    for s, term in graph.subject_objects(rdflib.URIRef(HBCO + "layTerm")):
        by.setdefault(
            str(s), {"concept_id": str(s).split("#")[-1], "lay_terms": [], "brick_classes": []}
        )["lay_terms"].append(str(term).lower())
    for s, cls in graph.subject_objects(rdflib.URIRef(HBCO + "mapsToBrickClass")):
        by[str(s)]["brick_classes"].append("brick:" + str(cls).split("#")[-1])
    return by


@pytest.fixture(scope="module")
def resolve():
    concept_map = _real_map()
    resolver = ConceptResolver()

    async def _load() -> Dict[str, dict]:
        return concept_map

    resolver._load_concept_map = _load  # type: ignore[method-assign]

    def _go(text: str):
        return asyncio.run(resolver.resolve(text))

    return _go


# ── the composite concepts are concepts ─────────────────────────────────────────────────────


def test_a_composite_concept_is_a_concept_in_the_schema():
    schema = rdflib.Graph()
    schema.parse(str(REPO / "ontology" / "ontosage_schema.ttl"), format="turtle")
    composite, concept = rdflib.URIRef(HBCO + "CompositeConcept"), rdflib.URIRef(HBCO + "Concept")
    assert (composite, RDFS.subClassOf, concept) in schema


def _load_reach_report():
    spec = importlib.util.spec_from_file_location(
        "_reach_report_k", REPO / "scripts" / "reach_report.py"
    )
    module = importlib.util.module_from_spec(spec)
    sys.modules["_reach_report_k"] = module
    spec.loader.exec_module(module)
    return module


def test_the_offline_loader_sees_the_composite_concepts_graphdb_infers():
    concept_map = _load_reach_report().load_concept_map()
    ids = {e["concept_id"] for e in concept_map.values()}
    for composite in (
        "iaq_composite",
        "co2_level",
        "temperature_reading",
        "busyness",
        "fire_safety",
    ):
        assert composite in ids, f"{composite} is missing from the offline concept map"
    assert len(ids) == len(_real_map()), "every concept in the TTL must load"


@pytest.mark.parametrize(
    "question,concept",
    [
        ("How is the air quality here?", "iaq_composite"),
        ("What is the CO2 level in here?", "co2_level"),
        ("are there CO2 detectors in all common rooms?", "co2_level"),
        ("to meet fire safety regulations, what checks must the building pass", "fire_safety"),
        ("are water usage and pressure stable in all part of the building?", "water_usage"),
    ],
)
def test_the_commonest_words_in_the_reach_reports_gap_list_already_reach_a_concept(
    resolve, question, concept
):
    assert concept in [m.concept_id for m in resolve(question)]


# ── the quantities this building measures, by the words people use ──────────────────────────

MAPPED = [
    # (question, concept it must reach) -- two real questions per addition
    ("Is there any indoor air pollution detected at this moment?", "iaq_composite"),
    ("are air purifiers adjusted automatically based on pollutant levels?", "iaq_composite"),
    ("how does the building respond to sudden increases in indoor pollutants?", "iaq_composite"),
    ("how accurate is the people count sensor in a large crowd?", "busyness"),
    ("what is the room utilisation on floor 3 this week?", "busyness"),
    ("Is there motion detected?", "motion_detected"),
    ("Is there any movement detected in restricted areas?", "motion_detected"),
    ("does the window sensor have an alert?", "unexpected_open_window"),
    ("Is it possible to temporarily disable a door sensor?", "unexpected_open_window"),
    ("What are the current lux levels on the lights in the rooms?", "lighting_comfort"),
    ("how much does the lux level near the windows let us dim the lights?", "lighting_comfort"),
    ("what is the current water flow rate?", "water_usage"),
    ("Does a high water flow in the pipes during closing hours mean a leak?", "water_usage"),
    ("What is the power usage?", "energy_consumption"),
    ("Which devices use the most energy?", "energy_consumption"),
    ("which floors consume the most energy?", "energy_consumption"),
    ("is the lighting energy efficient across the whole building", "energy_saving_tip"),
    ("are there energy efficient alternatives for the building", "energy_saving_tip"),
    ("are heating and cooling being used unnecessarily in any area?", "hvac_performance"),
    ("Heating status?", "hvac_performance"),
    ("Show gas detection alarm history for the solvent store.", "gas_level"),
    ("I want to avoid high particle levels today.", "pm25_level"),
    ("what is aqi", "iaq_composite"),
    ("which rooms have the worst aqi scores over the past month?", "iaq_composite"),
    ("Is the ambient light sufficient?", "lighting_comfort"),
    ("What is the Ambient Light level near the windows?", "lighting_comfort"),
    ("is the parking area full right now ?", "parking_availability"),
    ("parking full?", "parking_availability"),
]


@pytest.mark.parametrize("question,concept", MAPPED)
def test_a_measured_quantity_is_reached_by_the_words_people_use_for_it(resolve, question, concept):
    got = [m.concept_id for m in resolve(question)]
    assert concept in got, f"{question!r} reached {got}"


def test_noise_pollution_is_a_noise_question_not_an_air_quality_one(resolve):
    got = resolve("what do you do to reduce noise pollution to those who need quiet?")
    assert got[0].concept_id == "noisy", [m.concept_id for m in got]


def test_every_new_measurand_concept_names_a_class_the_building_measures():
    new = _real_map()[HBCO + "motion_detected"]
    assert new["brick_classes"] == ["brick:Motion_Sensor"]


# ── what must NOT be mapped: the honest declines stay honest ─────────────────────────────────


@pytest.mark.parametrize(
    "question",
    [
        # a quantity this building does not measure: mapping it would answer from another sensor
        "what is the current voltage level?",
        "is ozone level safe",
        "Are radiation levels safe?",
        "It's been cloudy for a few days; how is your battery level?",
        "Is there any unusual gas usage?",
        # words that name a record, an amenity or nothing: they must not become a measurand
        "How does the building security system work?",
        "which safety checks are due this month?",
        "is it safe for humans",
        "What is the most defensible event timeline, with clock quality and uncertainty shown?",
        "how does the building prioritize maintenance",
        "Are there sensors in stairwells?",
        "Does the battery backup power the whole building?",
        "How do you monitor sustainability goals?",
        "are there alerts for unusual patterns?",
    ],
)
def test_a_word_that_is_not_a_measured_quantity_reaches_no_measurand(resolve, question):
    got = resolve(question)
    assert not has_measurand_concept([m.to_dict() for m in got]), [m.concept_id for m in got]


def test_no_new_term_is_a_bare_word_that_names_a_record_or_an_unmeasured_quantity():
    banned = {
        "security",
        "safety",
        "safe",
        "quality",
        "maintenance",
        "access",
        "sustainability",
        "stairwell",
        "voltage",
        "ozone",
        "standby",
        "backup",
        "unusual",
        "data",
        "power",
        "service",
    }
    terms = {t for e in _real_map().values() for t in e["lay_terms"]}
    assert not (banned & terms), sorted(banned & terms)


# ── the referent gate, over the REAL vocabulary ─────────────────────────────────────────────


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "question,status",
    [
        ("are air purifiers adjusted automatically based on pollutant levels?", "resolved"),
        ("Can the building monitor sound decibel level?", "resolved"),
        ("Is the brightness level comfortable for reading?", "resolved"),
        ("what is the current voltage level?", "not_found"),
        ("Is ozone level normal?", "not_found"),
        ("Are radiation levels safe?", "not_found"),
    ],
)
async def test_the_gate_defers_only_to_quantities_the_real_vocabulary_explains(question, status):
    from orchestrator.services import referent_resolver as rr

    async def _nothing_exists(_query):
        return {"results": {"bindings": []}}

    rr.register_concept_terms(t for e in _real_map().values() for t in e["lay_terms"])
    try:
        res = await rr.ReferentResolver(_nothing_exists).resolve(question, [], "http://x#", "B")
    finally:
        rr.register_concept_terms([])
    assert res.status == status, (question, res)
