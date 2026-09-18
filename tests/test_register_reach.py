# -*- coding: utf-8 -*-
"""Register and amenity vocabulary: pinned by a guard set, read from the class, never guessed.

What these pin, and why each one exists
---------------------------------------
* The GUARD SET (docs/phase0/guard_set.jsonl) — every regression-probe question, every demo
  script question and the traps the code's own docstrings name, with the register / absent
  class / amenity kind each selected when the file was derived BEFORE the 2026-09-17
  vocabulary pass. A lay-term edit that moves any of them fails here, however much recall it
  buys (lessons.md #38: a lay term is a corpus-wide change).
* CLASS-LEVEL AMENITY TERMS ARE READ. Before 2026-09-17 CapabilityGraphResolver asked only for
  an instance's own ontosage:layTerms, so a synonym declared on ontosage:PrayerRoom did nothing
  and a building typing its prayer room with no instance terms could not be asked about it.
  These run the resolver's real queries against the real TBox through rdflib.
* KINDS THAT MUST CARRY NO TERMS carry none: report-intake classes (a term would pull "the
  toilet is leaking" into a lookup), meta classes, and sensor / equipment classes (their
  vocabulary is HBCO's).
* The over-broad register terms that were narrowed stay narrowed, by behaviour: "does the
  evidence support a diagnosis?" is not an approval-record question.
"""

from __future__ import annotations

import importlib.util
import json
import sys
from pathlib import Path

import pytest

pytestmark = pytest.mark.unit

REPO = Path(__file__).resolve().parents[1]
SCHEMA = REPO / "ontology" / "ontosage_schema.ttl"
GUARD = REPO / "docs" / "phase0" / "guard_set.jsonl"
ONTO = "http://ontosage.org/capabilities#"


def _harness():
    name = "_test_register_reach_harness"
    if name in sys.modules:
        return sys.modules[name]
    spec = importlib.util.spec_from_file_location(name, REPO / "scripts" / "register_reach.py")
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    spec.loader.exec_module(module)
    return module


@pytest.fixture(scope="module")
def harness():
    return _harness()


@pytest.fixture(scope="module")
def schema(harness):
    return harness.load_schema(SCHEMA)


@pytest.fixture(scope="module")
def guard(harness):
    return harness.read_guard(GUARD)


@pytest.fixture(scope="module")
def bldg_reach(harness, schema, guard):
    """The router's view of the building the guard set was derived on, from the file alone."""
    meta, _rows = guard
    return harness.Reach(schema, meta["snapshot"])


# ── the file parses and the guard set is what it claims to be ──────────────────────────


def test_the_schema_still_parses(schema):
    assert len(schema) > 1000


def test_the_guard_set_covers_every_source_question(harness, guard):
    """Derived mechanically: every probe case, every demo line and every documented trap."""
    _meta, rows = guard
    questions = [r["question"] for r in rows]
    probe = [c["question"] for c in json.loads(harness.PROBE.read_text(encoding="utf-8"))]
    demo = [
        line.strip()
        for line in harness.DEMO.read_text(encoding="utf-8").splitlines()
        if line.strip() and not line.strip().startswith("#")
    ]
    for q in probe + demo + [t["question"] for t in harness.TRAPS]:
        assert q in questions, f"guard set is missing a source question: {q!r}"


def test_no_guard_question_changes_lane(harness, bldg_reach, guard):
    """The whole point: a vocabulary edit may not move a question that passes today."""
    _meta, rows = guard
    violations = [
        v for v in harness.guard_violations(bldg_reach, rows) if v["status"] == "VIOLATION"
    ]
    assert not violations, json.dumps(violations, indent=1)


def test_a_violation_is_detected_when_a_guard_question_moves(harness, bldg_reach, guard):
    """The guard is not vacuous: a row whose recorded lane differs from today's is reported."""
    _meta, rows = guard
    row = next(r for r in rows if r["expect"]["held"] == "Permit")
    tampered = dict(row, expect=dict(row["expect"], held="Warranty"))
    found = harness.guard_violations(bldg_reach, [tampered])
    assert found and found[0]["status"] == "VIOLATION"


# ── kinds that must never carry lay terms ───────────────────────────────────────────────

REPORT_INTAKE = (
    "Complaint",
    "FaultReport",
    "Feedback",
    "MaintenanceIssue",
    "SafetyReport",
    "Suggestion",
    "Report",
)
META = (
    "Capability",
    "Amenity",
    "KnowledgeTopic",
    "InformationTopic",
    "Policy",
    "Procedure",
    "PotabilityStatement",
    "Facility",
    "Service",
    "Database",
    "SourceType",
    "QuestionIntent",
    "StakeholderRole",
    "IntervalRecord",
    "ForecastSkill",
    "ConfigurationPeriod",
    "BuildingDescription",
    "AccessPolicy",
)


@pytest.mark.parametrize("name", REPORT_INTAKE + META)
def test_report_intake_and_meta_classes_carry_no_lay_terms(schema, name):
    from rdflib import URIRef

    terms = list(schema.objects(URIRef(ONTO + name), URIRef(ONTO + "layTerms")))
    assert not terms, f"ontosage:{name} must not declare lay terms: {terms}"


def test_sensor_and_equipment_classes_carry_no_lay_terms(schema):
    """Measurement vocabulary belongs to HBCO concepts, equipment names to Brick labels."""
    from rdflib import RDFS, URIRef

    brick = "https://brickschema.org/schema/Brick#"
    roots = {
        URIRef(brick + "Sensor"),
        URIRef(brick + "Equipment"),
        URIRef(brick + "Point"),
        URIRef(brick + "System"),
        URIRef(brick + "Location"),
        URIRef(brick + "Collection"),
        URIRef(brick + "Command"),
    }

    def ancestors(cls, seen=None):
        seen = seen if seen is not None else set()
        for parent in schema.objects(cls, RDFS.subClassOf):
            if parent not in seen:
                seen.add(parent)
                ancestors(parent, seen)
        return seen

    offenders = sorted(
        str(c).rsplit("#", 1)[-1]
        for c in set(schema.subjects(URIRef(ONTO + "layTerms"), None))
        if ancestors(c) & roots
    )
    assert not offenders, offenders


# ── class-level amenity terms reach the resolver ────────────────────────────────────────


def _exec_on(graph):
    """A sparql_exec for CapabilityGraphResolver that runs the real query through rdflib."""

    async def _exec(query: str) -> dict:
        result = graph.query(query)
        names = [str(v) for v in result.vars]
        return {
            "results": {
                "bindings": [
                    {n: {"value": str(row[n])} for n in names if row[n] is not None}
                    for row in result
                ]
            }
        }

    return _exec


def _building(schema, *instances):
    """The TBox plus amenity instances typed the dual way the convention requires."""
    from rdflib import RDF, RDFS, Graph, Literal, URIRef

    g = Graph()
    for triple in schema:
        g.add(triple)
    for local, kind, label, lay in instances:
        iri = URIRef("urn:test:" + local)
        g.add((iri, RDF.type, URIRef(ONTO + "Amenity")))
        g.add((iri, RDF.type, URIRef(ONTO + kind)))
        g.add((iri, RDFS.label, Literal(label)))
        if lay:
            g.add((iri, URIRef(ONTO + "layTerms"), Literal(lay)))
    return g


@pytest.fixture(scope="module")
def bare_building(schema):
    """A building whose amenities declare NO lay terms of their own — only their kind."""
    return _building(
        schema,
        ("prayer", "PrayerRoom", "Room G.12", ""),
        ("cafe", "Cafe", "Ground floor outlet", ""),
        ("bikes", "BikeStorage", "Rear yard", ""),
        ("lockers", "Locker", "Level 1 bank", ""),
        ("aed", "FirstAidPoint", "Reception", ""),
        ("lift", "Lift", "Core A", ""),
        ("fountain", "DrinkingWater", "Level 2 landing", ""),
        ("study", "StudyArea", "Level 3 open area", ""),
    )


async def _labels(graph, question):
    from orchestrator.services.capability_graph_resolver import CapabilityGraphResolver

    facts = await CapabilityGraphResolver(sparql_exec=_exec_on(graph)).resolve(question)
    return [f.label for f in facts]


@pytest.mark.parametrize(
    "question, label",
    [
        ("Is there a multi-faith room in the building?", "Room G.12"),
        ("where is the cafeteria?", "Ground floor outlet"),
        ("Is there a canteen?", "Ground floor outlet"),
        ("Where is the bike storage?", "Rear yard"),
        ("are there any lockers I can use", "Level 1 bank"),
        ("where is the nearest defibrillator?", "Reception"),
        ("Where is the nearest lift?", "Core A"),
        ("is there a water fountain on this floor", "Level 2 landing"),
    ],
)
async def test_a_kind_synonym_finds_an_amenity_that_declares_none(bare_building, question, label):
    assert label in await _labels(bare_building, question)


@pytest.mark.parametrize(
    "question",
    [
        # A status question: bare "lift" is an hbco:lift_status term, not a lift's location.
        "Is lift B out of service?",
        # Water use is a meter question, not a drinking-water point.
        "How much water did the building use last week?",
        # "study space" belongs to the WorkspaceProfile register, not to StudyArea.
        "What is the study space like on floor 2?",
        # "drinking water" is an hbco:water_quality term.
        "Is the drinking water quality within limits?",
    ],
)
async def test_a_kind_does_not_claim_what_its_terms_deliberately_left_out(bare_building, question):
    assert await _labels(bare_building, question) == []


async def test_before_the_class_terms_the_same_building_answered_nothing(schema):
    """The defect, restated: with the TBox's amenity-kind terms stripped, nothing matches."""
    from rdflib import URIRef

    stripped = _building(schema, ("prayer", "PrayerRoom", "Room G.12", ""))
    lay = URIRef(ONTO + "layTerms")
    for cls in list(stripped.subjects(lay, None)):
        if str(cls).startswith(ONTO) and not str(cls).startswith("urn:"):
            stripped.remove((cls, lay, None))
    assert await _labels(stripped, "Is there a multi-faith room?") == []


async def test_instance_terms_still_count_alongside_the_kind(schema):
    g = _building(schema, ("prayer", "PrayerRoom", "Room G.12", "chapel, quiet corner"))
    assert await _labels(g, "where is the chapel?") == ["Room G.12"]
    assert await _labels(g, "where is the prayer room?") == ["Room G.12"]


async def test_a_record_type_on_an_amenity_lends_it_no_vocabulary(schema):
    """Only Capability subclasses contribute: a register's words must not leak into amenities."""
    from rdflib import RDF, URIRef

    g = _building(schema, ("bins", "WastePoint", "Bin store", ""))
    g.add((URIRef("urn:test:bins"), RDF.type, URIRef(ONTO + "WasteCollectionPoint")))
    # "fill level" is a WasteCollectionPoint register term and no WastePoint term.
    assert await _labels(g, "what is the fill level?") == []


async def test_a_failing_kind_query_keeps_the_instance_terms():
    from orchestrator.services.capability_graph_resolver import CapabilityGraphResolver

    calls = {"n": 0}

    async def _exec(query: str) -> dict:
        calls["n"] += 1
        if "klays" in query:
            raise RuntimeError("kind query unsupported")
        return {
            "results": {
                "bindings": [
                    {
                        "a": {"value": "urn:x"},
                        "label": {"value": "Chapel"},
                        "lay": {"value": "chapel"},
                    }
                ]
            }
        }

    facts = await CapabilityGraphResolver(sparql_exec=_exec).resolve("where is the chapel")
    assert [f.label for f in facts] == ["Chapel"] and calls["n"] == 2


# ── narrowed register vocabulary, pinned by behaviour ───────────────────────────────────


@pytest.fixture(scope="module")
def all_held(harness, schema):
    """Every record class held once, so the scorer alone decides — no building's counts."""
    names = harness.schema_record_classes(schema)
    return harness.Reach(schema, {"record_counts": {n: 1 for n in names}, "amenities": {}})


@pytest.mark.parametrize(
    "question, cls",
    [
        ("Who signed off the asbestos management plan?", "ApprovalRecord"),
        ("What is the approval status of the Level 2 laboratory use?", "ApprovalRecord"),
        ("Which waste streams have the highest contamination?", "WasteCollectionPoint"),
        ("When is the next bin collection?", "WasteCollectionPoint"),
        ("Is there a public lecture this evening?", "PublicEvent"),
        ("Which step-free routes reach Level 3?", "AccessibleRoute"),
        ("Who is the emergency coordinator for tonight?", "CoordinationFunction"),
        ("What are the condition grades of the roof plant?", "ConditionSurvey"),
        ("Which door controllers are offline?", "DoorHardware"),
        ("How many incidents were reported last month?", "IncidentRecord"),
    ],
)
def test_the_phrases_a_record_is_called_by_still_reach_it(all_held, question, cls):
    assert all_held.register(question)["held"] == cls


@pytest.mark.parametrize(
    "question, not_cls",
    [
        (
            "My office is unusually hot. Does the evidence support a persistent local "
            "service problem?",
            "ApprovalRecord",
        ),
        (
            "Which services are confirmed, probable or unknown within this ceiling?",
            "ApprovalRecord",
        ),
        ("One sensor stream is drifting away from nearby measurements.", "WasteCollectionPoint"),
        (
            "A central teaching platform is unavailable. Which room functions remain usable?",
            "ContinuityProvision",
        ),
        ("Which access switches lack PoE headroom?", "AccessPermission"),
        ("Which emergency stops are reported missing or defeated?", "CoordinationFunction"),
        ("Is the AHU heat-recovery section delivering useful recovery?", "WorkspaceProfile"),
        ("What UPS runtime is defensible at the present battery condition?", "ConditionSurvey"),
    ],
)
def test_a_word_about_knowledge_or_another_thing_does_not_name_a_register(
    all_held, question, not_cls
):
    assert all_held.register(question)["held"] != not_cls


def test_an_anomaly_question_is_no_longer_answered_from_public_events(bldg_reach):
    """Documented in record_registry.load_lay_terms; bare "events" was the cause."""
    got = bldg_reach.register("Show me the anomaly events")
    assert got["held"] != "PublicEvent" and got["absent"] == "AnomalyEvent"


# ── false absence: a register the building holds must be reachable (BUG-749) ────────────
#
# Each question below is a VERBATIM row from the 147-question live read of 2026-09-17
# (docs/phase0/phase0_rerun.md.jsonl), and each was answered with an absence the building
# does not have: "Abacws Building's documents do not answer this" over 30 cleaning tasks,
# "I don't have that specific information on record" over 16 accessible routes. The
# selection is decided here, offline, before any lane runs — which is where the defect was.

FALSE_ABSENCE_ROWS = [
    (
        "row 20",
        "Which washroom should I service next, considering required frequency, time since "
        "the last confirmed service and current demand evidence?",
        "CleaningTask",
    ),
    (
        "row 111",
        "Is the building pushchair-friendly from the car park?",
        "AccessibleRoute",
    ),
    (
        "row 53",
        "If my assigned room is withdrawn, which currently eligible alternative should I "
        "ask the room team to consider?",
        "WorkspaceProfile",
    ),
    (
        "row 78",
        "Which room and time categories show repeated no-shows strongly enough to justify "
        "an owner-led review of release rules?",
        "Booking",
    ),
]


@pytest.mark.parametrize(
    "row, question, cls", FALSE_ABSENCE_ROWS, ids=[r[0] for r in FALSE_ABSENCE_ROWS]
)
def test_a_register_the_building_holds_is_reached(bldg_reach, row, question, cls):
    assert bldg_reach.register(question)["held"] == cls


def test_a_security_records_question_claims_no_register_at_all(bldg_reach):
    """Row 86, and the reason it is NOT fixed by vocabulary.

    "Which current Security records are incomplete, stale, duplicated or conflicting?"
    spans PatrolCheckpoint, AccessPermission, IncidentRecord and DoorHardware at once.
    Giving any ONE of them the phrase "security records" would answer a question about all
    four from a quarter of the evidence and present it as complete — the C8 defect, which
    is what declined this row with Continuity Provision's statistics in the first place.
    Selecting nothing is the honest outcome; what the decline then SAYS is the fix, and it
    lives in capability_agent (see test_a_decline_names_only_what_it_searched.py).
    """
    got = bldg_reach.register(
        "Which current Security records are incomplete, stale, duplicated or conflicting, "
        "and which operational decisions do those defects block?"
    )
    assert got["held"] is None and got["absent"] is None


@pytest.mark.parametrize(
    "question, not_cls",
    [
        # Rejected: bare "which washroom" — locating one is the toilet amenity's question.
        ("Which washroom is closest to Room 3.02?", "CleaningTask"),
        ("Where is the nearest washroom?", "CleaningTask"),
        # Rejected: bare "should i service" / "service next" — plant is not cleaned.
        ("Which chiller should I service next?", "CleaningTask"),
        # Rejected: "service this shift", which would have recovered CT-025.
        ("Which plant items are due for service this shift?", "CleaningTask"),
        # Rejected: the PLURAL "eligible alternatives", which outscored "bookings" here.
        (
            "A lift is officially unavailable. Which bookings no longer have a verified "
            "route for stated functional requirements, and what eligible alternatives exist?",
            "WorkspaceProfile",
        ),
    ],
)
def test_the_terms_rejected_for_over_capture_stay_rejected(bldg_reach, question, not_cls):
    """Each of these moved an UNRELATED question and was dropped for it, one at a time."""
    assert bldg_reach.register(question)["held"] != not_cls
