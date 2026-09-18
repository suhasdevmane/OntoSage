"""Every measured quantity is reachable by the words people use for it — and only by them.

HBCO concepts map lay terms to sensor CLASSES (Brick, or OCBV ``ontosage:`` where Brick has
none). Measured on 2026-09-17 against the live bldg1 graph, 26 point classes carrying 1,507
points had no concept on the class or on any ancestor — and the concepts that looked like they
covered sound, energy, power, faults, leaks, doors and windows pointed at classes that do not
exist:

* ``noisy``, ``quiet_zone``, ``quiet_space``, ``acoustic_comfort`` and ``focus_environment``
  mapped to ``brick:Noise_Level_Sensor`` / ``brick:Sound_Level_Sensor``. Brick 1.4 defines
  neither; the 233 sound sensors are ``ontosage:Sound_Level_Sensor`` (BUG-179 is why).
* nine energy concepts mapped to ``brick:Electrical_Energy_Sensor`` and three to
  ``brick:Electrical_Power_Sensor`` — the Brick names are ``Energy_Sensor`` and
  ``Electric_Power_Sensor``.
* ``Fault_Sensor``, ``Leak_Detector``, ``Door_Position_Sensor``, ``Window_Position_Sensor``,
  ``Daylight_Sensor``, ``People_Counter_Sensor`` and ``Water_Quality_Sensor``: none exist.

A concept naming a class that does not exist resolves, logs a class, and matches nothing. Worse,
the SPARQL agent takes the concept's class INSTEAD of its keyword map, so the dead class also
suppressed the working fallback. Nothing failed loudly; the words simply led nowhere.

These tests read committed files only — the CSV, the generated TTL, the OCBV schema and the
Brick 1.4 TTL every parked building folder carries — so they run with no building active.
"""

import asyncio
import csv
import importlib.util
import sys
from pathlib import Path
from typing import Dict, List, Set

import pytest
import rdflib
import yaml
from rdflib.namespace import OWL, RDF, RDFS

from orchestrator.services.concept_resolver import ConceptResolver, _parse_bindings

pytestmark = pytest.mark.unit

REPO = Path(__file__).resolve().parents[1]
CSV_PATH = REPO / "ontology" / "mining" / "concept_terms_raw.csv"
TTL_PATH = REPO / "ontology" / "hbco_mappings.ttl"
GENERATOR = REPO / "ontology" / "mining" / "csv_to_hbco.py"
SCHEMA_PATH = REPO / "ontology" / "ontosage_schema.ttl"
MODALITIES_PATH = REPO / "config" / "saturation_modalities.yaml"

BRICK = "https://brickschema.org/schema/Brick#"
ONTO = "http://ontosage.org/capabilities#"
HBCO = "http://ontosage.org/hbco#"

#: Ancestors too generic to count as "reachable": a concept on brick:Sensor would claim every
#: sensor in the building for one word.
_GENERIC = {BRICK + n for n in ("Point", "Sensor", "Command", "Status", "Setpoint", "Entity")}


def _curie_to_iri(curie: str) -> str:
    prefix, local = curie.split(":", 1)
    return {"brick": BRICK, "ontosage": ONTO}[prefix] + local


def _brick_ttl() -> Path:
    candidates = [REPO / "input" / "Brick_v1.4.ttl"] + sorted(REPO.glob("bldg*/Brick_v1.4.ttl"))
    for c in candidates:
        if c.exists():
            return c
    pytest.fail(
        "Brick_v1.4.ttl is committed in every bldg*/ folder; none was found, so the declared-"
        "class check has nothing to check against. Point _brick_ttl() at its new location."
    )


@pytest.fixture(scope="module")
def rows() -> List[Dict[str, str]]:
    with open(CSV_PATH, encoding="utf-8", newline="") as fh:
        return list(csv.DictReader(fh))


def _split(s: str) -> List[str]:
    return [t.strip() for t in (s or "").split("|") if t.strip()]


@pytest.fixture(scope="module")
def vocab() -> rdflib.Graph:
    g = rdflib.Graph()
    g.parse(str(_brick_ttl()), format="turtle")
    g.parse(str(SCHEMA_PATH), format="turtle")
    return g


def _declared(g: rdflib.Graph, iri: str) -> bool:
    return (rdflib.URIRef(iri), RDF.type, OWL.Class) in g


def _ancestors(g: rdflib.Graph, iri: str) -> Set[str]:
    seen: Set[str] = set()
    todo = [rdflib.URIRef(iri)]
    while todo:
        node = todo.pop()
        for sup in g.objects(node, RDFS.subClassOf):
            if isinstance(sup, rdflib.URIRef) and str(sup) not in seen:
                seen.add(str(sup))
                todo.append(sup)
    return seen


def _concept_class_iris(rows: List[Dict[str, str]]) -> Set[str]:
    return {_curie_to_iri(c) for r in rows for c in _split(r["brick_classes"])}


def _reachable(g: rdflib.Graph, iri: str, mapped: Set[str]) -> bool:
    return iri in mapped or bool((_ancestors(g, iri) - _GENERIC) & mapped)


# ── the file the system loads is the file the CSV says ───────────────────────────────────────


def test_the_ttl_is_generated_from_the_csv_and_not_edited_by_hand(rows):
    spec = importlib.util.spec_from_file_location("_csv_to_hbco", GENERATOR)
    mod = importlib.util.module_from_spec(spec)
    sys.modules["_csv_to_hbco"] = mod
    spec.loader.exec_module(mod)
    expected = mod.build_ttl(rows).replace("\r\n", "\n")
    actual = TTL_PATH.read_text(encoding="utf-8").replace("\r\n", "\n")
    assert actual == expected, (
        "ontology/hbco_mappings.ttl differs from what csv_to_hbco.py builds from the CSV — "
        "edit the CSV and run `python ontology/mining/csv_to_hbco.py`"
    )


# ── every class a concept names exists ──────────────────────────────────────────────────────


def test_every_concept_class_is_a_declared_class(rows, vocab):
    missing = [
        f"{r['concept_id']} -> {c}"
        for r in rows
        for c in _split(r["brick_classes"])
        if not _declared(vocab, _curie_to_iri(c))
    ]
    assert not missing, (
        "concepts map to classes neither Brick 1.4 nor ontosage_schema.ttl declares; such a "
        f"concept resolves and then matches nothing: {missing}"
    )


def test_no_concept_maps_to_a_deprecated_or_alias_brick_class(rows, vocab):
    alias_of = rdflib.URIRef(BRICK + "aliasOf")
    bad = []
    for r in rows:
        for c in _split(r["brick_classes"]):
            node = rdflib.URIRef(_curie_to_iri(c))
            if (node, OWL.deprecated, None) in vocab or (node, alias_of, None) in vocab:
                bad.append(f"{r['concept_id']} -> {c}")
    assert not bad, f"map to the current Brick class, not a deprecated or alias one: {bad}"


def test_the_existence_check_is_not_vacuous(vocab):
    # The two shapes of dead class found on 2026-09-17 must be caught by the check above.
    assert not _declared(vocab, BRICK + "Noise_Level_Sensor")
    assert not _declared(vocab, BRICK + "Electrical_Energy_Sensor")
    assert _declared(vocab, ONTO + "Sound_Level_Sensor")
    assert _declared(vocab, BRICK + "Energy_Sensor")


# ── one word, one concept ────────────────────────────────────────────────────────────────────


def test_no_lay_term_belongs_to_two_concepts(rows):
    # The resolver lower-cases every term, so the check does too. A shared term puts two
    # concepts on one word and the winner becomes whatever order the store returns.
    owner: Dict[str, str] = {}
    clashes = []
    for r in rows:
        terms = [t.lower() for t in _split(r["lay_terms"])]
        dup_here = sorted({t for t in terms if terms.count(t) > 1})
        if dup_here:
            clashes.append(f"{r['concept_id']} repeats {dup_here}")
        for t in set(terms):
            if t in owner and owner[t] != r["concept_id"]:
                clashes.append(f"{t!r}: {owner[t]} and {r['concept_id']}")
            owner.setdefault(t, r["concept_id"])
    assert not clashes, clashes


# ── measured classes are reachable ───────────────────────────────────────────────────────────


def test_every_ocbv_point_class_is_reachable_by_a_concept(rows, vocab):
    # OCBV declares a point class exactly because a building measures something Brick cannot
    # name. A class declared without a concept is a quantity nobody can ask about by name.
    mapped = _concept_class_iris(rows)
    point = BRICK + "Point"
    unreachable = []
    for cls in set(vocab.subjects(RDF.type, OWL.Class)):
        iri = str(cls)
        if not iri.startswith(ONTO) or point not in _ancestors(vocab, iri):
            continue
        if not _reachable(vocab, iri, mapped):
            unreachable.append(iri[len(ONTO) :])
    assert (
        not unreachable
    ), f"OCBV point classes with no concept on them or an ancestor: {unreachable}"


#: Provisioned classes a concept deliberately does NOT carry, each with its reason.
_NOT_A_CONCEPT_CLASS = {
    # An Electrical_Meter is EQUIPMENT; the energy concepts carry brick:Energy_Sensor. Adding
    # the meter would make it the class the SPARQL agent picks (alphabetically first), and a
    # building whose readings sit on Energy_Sensor points would lose every energy answer.
    "Electrical_Meter": "equipment, not a reading class",
    # Position_Sensor is the parent of Damper_ and Valve_Position_Sensor: under inference a
    # "door position" concept on it would pull every damper and valve into a door question.
    "Position_Sensor": "too broad under inference",
}


def test_every_provisioned_modality_class_is_reachable_by_a_concept(rows, vocab):
    raw = yaml.safe_load(MODALITIES_PATH.read_text(encoding="utf-8"))["modalities"]
    mapped = _concept_class_iris(rows)
    unreachable = []
    for name, spec in raw.items():
        cls = str(((spec or {}).get("sat") or {}).get("brick_class") or "")
        if not cls or cls.split(":")[-1] in _NOT_A_CONCEPT_CLASS:
            continue
        iri = _curie_to_iri(cls if ":" in cls else f"brick:{cls}")
        if not _reachable(vocab, iri, mapped):
            unreachable.append(f"{name}: {cls}")
    assert not unreachable, f"provisioned modalities no lay term can reach: {unreachable}"


# ── the words people use resolve to the quantity they mean ───────────────────────────────────


@pytest.fixture(scope="module")
def resolver() -> ConceptResolver:
    """The real resolver, fed the concept map the GraphDB load would produce from the TTL."""
    g = rdflib.Graph()
    g.parse(str(TTL_PATH), format="turtle")
    H = rdflib.Namespace(HBCO)
    bindings = []
    concepts = set(g.subjects(RDF.type, H.Concept)) | set(g.subjects(RDF.type, H.CompositeConcept))
    for c in sorted(concepts):
        classes = sorted(g.objects(c, H.mapsToBrickClass)) or [None]
        recipe = next(iter(g.objects(c, H.requiresRecipe)), None)
        conf = next(iter(g.objects(c, H.confidence)), None)
        for term in sorted(g.objects(c, H.layTerm)):
            for bc in classes:
                row = {"concept": {"value": str(c)}, "layTerm": {"value": str(term)}}
                if bc is not None:
                    row["brickClass"] = {"value": str(bc)}
                if recipe is not None:
                    row["recipe"] = {"value": str(recipe)}
                if conf is not None:
                    row["confidence"] = {"value": str(conf)}
                bindings.append(row)
    concept_map = _parse_bindings(bindings)

    r = ConceptResolver()

    async def _load():
        return concept_map

    r._load_concept_map = _load  # type: ignore[method-assign]
    return r


def _resolve(resolver: ConceptResolver, text: str):
    return asyncio.run(resolver.resolve(text))


@pytest.mark.parametrize(
    "question,concept,cls",
    [
        # sound — the concepts existed, the class did not
        ("How loud is room 3.10?", "noisy", "ontosage:Sound_Level_Sensor"),
        ("Which room is the noisiest right now?", "noisy", "ontosage:Sound_Level_Sensor"),
        ("What are the sound levels on floor 2?", "noisy", "ontosage:Sound_Level_Sensor"),
        ("Which room in the building is the quietest right now?", "quiet_space", None),
        ("Is there anywhere quiet I can work?", "quiet_zone", "ontosage:Sound_Level_Sensor"),
        # the extreme form of a comfort word (BUG-640 fixed the ranking compiler, not this)
        ("Which rooms in the building are the stuffiest right now?", "stuffiness", None),
        ("Which floor is the warmest right now?", "too_warm", "brick:Temperature_Sensor"),
        ("Which is the coldest room right now?", "too_cold", None),
        ("Which floor is the busiest?", "busy", "brick:Occupancy_Count_Sensor"),
        # outdoor and green roof
        ("Is it raining?", "rainfall", "ontosage:Rainfall_Sensor"),
        ("Does the green roof need watering?", "soil_moisture", "ontosage:Soil_Moisture_Sensor"),
        ("How dry is the soil on the roof?", "soil_moisture", None),
        ("What is the solar irradiance right now?", "solar_irradiance", None),
        ("What is the outside humidity?", "outdoor_humidity", "brick:Outside_Air_Humidity_Sensor"),
        # air quality constituents, each by its own name
        ("Are CO levels safe in the basement?", "carbon_monoxide", "brick:CO_Level_Sensor"),
        ("What is the NO2 level on floor 2?", "nitrogen_dioxide", None),
        ("What is the formaldehyde level on floor 3?", "formaldehyde", None),
        ("What is the PM10 on floor 4?", "pm10_level", "brick:PM10_Level_Sensor"),
        ("What is the PM1 level on floor 0?", "pm1_level", None),
        ("What are the gas levels on floor 5?", "gas_level", "brick:Gas_Sensor"),
        # energy and power — the class names were wrong
        (
            "Compare this week's electricity use with last week.",
            "energy_consumption",
            "brick:Energy_Sensor",
        ),
        (
            "What is the power draw on floor 3 right now?",
            "electric_power",
            "brick:Electric_Power_Sensor",
        ),
        # occupancy, doors, windows, lighting
        ("How many people are on floor 2?", "busy", "brick:Occupancy_Count_Sensor"),
        ("Is room 3.10 occupied right now?", "occupancy_status", "brick:Occupancy_Status"),
        ("Are any windows open on floor 2?", "unexpected_open_window", "brick:Contact_Sensor"),
        (
            "What is the colour temperature of the lights on floor 2?",
            "light_colour_temperature",
            None,
        ),
        ("Are the lights on in room 2.05?", "lighting_state", "ontosage:Lighting_Command"),
        # plant
        ("What is the supply air temperature on floor 5?", "supply_air_temperature", None),
        ("What is the filter differential pressure on AHU_F5?", "filter_pressure", None),
        ("Is the supply fan running on floor 5?", "fan_status", "brick:Fan_Status"),
        ("What's the delta-T across the heating circuit?", "water_temperature", None),
        ("How many running hours has the AHU done this month?", "run_time", None),
        ("What is the humidity setpoint on floor 3?", "humidity_setpoint", None),
        ("What is the water level in the floor 5 tank?", "water_level", None),
        # things that already worked and must keep working
        (
            "How many parking spaces are free?",
            "parking_availability",
            "ontosage:Parking_Occupancy_Sensor",
        ),
        ("How full is the recycling bin on floor 3?", "waste_fill", "ontosage:Waste_Fill_Sensor"),
        ("What is the CO2 level in room 5.01 right now?", "co2_level", None),
    ],
)
def test_a_lay_phrasing_resolves_to_its_quantity(resolver, question, concept, cls):
    matches = _resolve(resolver, question)
    assert matches, f"{question!r} resolved to no concept"
    first = matches[0]
    assert first.concept_id == concept, (
        f"{question!r} resolved first to {first.concept_id} via {first.lay_term!r}; "
        f"all: {[(m.concept_id, m.lay_term) for m in matches]}"
    )
    assert first.brick_classes, f"{concept} carries no class, so it reaches no sensor"
    if cls:
        assert cls in first.brick_classes


def _measurement_concepts(matches) -> List[str]:
    return [m.concept_id for m in matches if m.brick_classes]


@pytest.mark.parametrize(
    "question",
    [
        "Where is the accessible toilet?",
        "Who approved the permit?",
        "Where is the train station?",
        # actuation is declined elsewhere; it must not read as a question about light state
        "Turn the lights on in room 2.05.",
    ],
)
def test_a_non_measurement_question_reaches_no_sensor_class(resolver, question):
    assert _measurement_concepts(_resolve(resolver, question)) == []


@pytest.mark.parametrize(
    "question,forbidden",
    [
        # "how full" was a waste-bin term; an occupancy question sent it to the bins
        ("How full is the meeting room?", "waste_fill"),
        # and bare "full" was an occupancy term; a bin, a list and a report are not crowds
        ("How full is the recycling bin on floor 3?", "crowded"),
        ("Give me the full list of sensors on floor 2.", "crowded"),
        # "co" must not be read inside "co2", nor in "co-working"
        ("What is the CO2 level in room 5.01?", "carbon_monoxide"),
        ("Is the co-working space free?", "carbon_monoxide"),
        # "pm1" matches inside "pm10" by the resolver's letter-only boundary; the longer term
        # must win, and PM2.5 must not touch PM1 at all
        ("What is the PM2.5 on floor 2?", "pm1_level"),
        # a building's opening hours are not equipment run hours
        ("What are the building's operating hours?", "run_time"),
        # kWh is energy, not the kW power concept
        ("How many kWh did floor 3 use?", "electric_power"),
        # a gas leak is an emergency procedure, not a reading request
        ("Who do I call about a gas leak?", "gas_level"),
        # "db" is a database as often as a decibel
        ("Which db stores the readings?", "noisy"),
        ("Open the windows on floor 3.", "unexpected_open_window"),
    ],
)
def test_a_neighbouring_phrasing_does_not_reach_the_wrong_quantity(resolver, question, forbidden):
    matches = _resolve(resolver, question)
    assert forbidden not in [
        m.concept_id for m in matches
    ], f"{question!r} resolved to {forbidden}: {[(m.concept_id, m.lay_term) for m in matches]}"


def test_pm10_outranks_pm1_when_both_match(resolver):
    ids = [m.concept_id for m in _resolve(resolver, "what is the pm10 on floor 4")]
    assert ids.index("pm10_level") < ids.index("pm1_level")


def test_drinking_water_is_never_answered_from_a_sensor(resolver):
    # ontosage_schema.ttl Module P: potability is a published statement with an owner, never
    # something inferred from a reading. The concept may match; it must carry no class.
    matches = _resolve(resolver, "Is the drinking water safe to drink?")
    assert "water_quality" in [m.concept_id for m in matches]
    assert _measurement_concepts(matches) == []
