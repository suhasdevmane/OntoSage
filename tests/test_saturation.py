"""
V4-T08 tests — SATURATE provisioner (gap matrix -> simulated-sensor TTL).

Offline: plans and TTL are built from synthetic SpaceCoverage fixtures; validity
is checked by parsing the emitted Turtle with rdflib.
"""

from __future__ import annotations

import pytest
import rdflib

from orchestrator.services.deliberation.coverage_audit import (
    STATUS_MISSING,
    STATUS_PRESENT,
    STATUS_UNBACKED,
    ModalitySpec,
    SpaceCoverage,
)
from orchestrator.services.deliberation.saturation import (
    build_saturation_ttl,
    build_zoneid_ttl,
    plan_saturation,
    zone_id_for,
)

pytestmark = pytest.mark.unit

NS = "http://example.org/testbldg#"
BID = "anybldg"

ONTOSAGE = rdflib.Namespace("http://ontosage.org/capabilities#")
BRICK = rdflib.Namespace("https://brickschema.org/schema/Brick#")
REF = rdflib.Namespace("https://brickschema.org/schema/Brick/ref#")


def _modalities():
    return [
        ModalitySpec(
            "occupancy",
            ["Occupancy_Count_Sensor"],
            sat={
                "brick_class": "Occupancy_Count_Sensor",
                "table": "occupancy_data",
                "unit": "persons",
            },
        ),
        ModalitySpec(
            "co2",
            ["CO2_Level_Sensor"],
            sat={"brick_class": "CO2_Level_Sensor", "table": "co2_data", "unit": "ppm"},
        ),
        ModalitySpec("nosat", ["Some_Sensor"]),  # no sat config -> skipped
    ]


def _space(iri_local, label="", occ=STATUS_MISSING, co2=STATUS_MISSING):
    sc = SpaceCoverage(space_iri=f"{NS}{iri_local}", label=label or iri_local)
    sc.modalities = {
        "occupancy": {"status": occ, "sensor": "", "uuid": "", "stored_at": ""},
        "co2": {"status": co2, "sensor": "", "uuid": "", "stored_at": ""},
        "nosat": {"status": STATUS_MISSING, "sensor": "", "uuid": "", "stored_at": ""},
    }
    return sc


# ── planning ──────────────────────────────────────────────────────────────────


def test_plan_provisions_missing_and_unbacked_not_present():
    spaces = [
        _space("RoomA", occ=STATUS_MISSING, co2=STATUS_PRESENT),
        _space("RoomB", occ=STATUS_UNBACKED, co2=STATUS_MISSING),
    ]
    plan = plan_saturation(BID, NS, spaces, _modalities())
    assert sorted(plan.keys()) == ["co2", "occupancy"]
    assert len(plan["occupancy"]) == 2  # missing + unbacked both provisioned
    assert len(plan["co2"]) == 1  # RoomA co2 is present -> untouched
    assert "nosat" not in plan  # no sat config -> skipped


def test_plan_uuids_deterministic_and_distinct():
    spaces = [_space("RoomA"), _space("RoomB")]
    plan1 = plan_saturation(BID, NS, spaces, _modalities())
    plan2 = plan_saturation(BID, NS, list(reversed(spaces)), _modalities())
    u1 = {i.sensor_iri: i.uuid for m in plan1.values() for i in m}
    u2 = {i.sensor_iri: i.uuid for m in plan2.values() for i in m}
    assert u1 == u2  # order-independent, regeneration-stable
    assert len(set(u1.values())) == len(u1)  # no UUID collisions


# ── TTL emission ──────────────────────────────────────────────────────────────


def test_saturation_ttl_parses_and_carries_the_contract():
    spaces = [_space("RoomA", label="Room A")]
    plan = plan_saturation(BID, NS, spaces, _modalities())
    ttl = build_saturation_ttl(NS, "occupancy", plan["occupancy"])

    g = rdflib.Graph()
    g.parse(data=ttl, format="turtle")  # must be valid Turtle

    sensor = rdflib.URIRef(f"{NS}RoomA_sat_occupancy")
    assert (sensor, rdflib.RDF.type, BRICK.Occupancy_Count_Sensor) in g
    # location idiom must be hasLocation (NOT isPartOf) so discovery finds it
    assert (sensor, BRICK.hasLocation, rdflib.URIRef(f"{NS}RoomA")) in g
    assert not list(g.triples((sensor, BRICK.isPartOf, None)))
    # epistemic label — the honesty non-negotiable
    assert (sensor, ONTOSAGE.isSimulated, rdflib.Literal(True)) in g
    # contract #8 second half: timeseries ref with uuid + storedAt
    refs = list(g.objects(sensor, REF.hasExternalReference))
    assert len(refs) == 1
    uuids = list(g.objects(refs[0], REF.hasTimeseriesId))
    assert len(uuids) == 1 and str(uuids[0]) == plan["occupancy"][0].uuid
    stored = list(g.objects(refs[0], REF.storedAt))
    assert stored == [rdflib.URIRef(f"{NS}occupancy_data")]


def test_saturation_ttl_idempotent():
    spaces = [_space("RoomA"), _space("RoomB")]
    m = _modalities()
    ttl1 = build_saturation_ttl(NS, "occupancy", plan_saturation(BID, NS, spaces, m)["occupancy"])
    ttl2 = build_saturation_ttl(NS, "occupancy", plan_saturation(BID, NS, spaces, m)["occupancy"])
    assert ttl1 == ttl2  # byte-identical re-runs


def test_dotted_space_locals_survive_via_full_iris():
    """'Room_5.28'-style locals must not break Turtle (full-IRI emission)."""
    spaces = [_space("Room_5.28", label="HVAC Zone 5.28")]
    plan = plan_saturation(BID, NS, spaces, _modalities())
    ttl = build_saturation_ttl(NS, "occupancy", plan["occupancy"])
    g = rdflib.Graph()
    g.parse(data=ttl, format="turtle")
    assert (
        rdflib.URIRef(f"{NS}Room_5.28_sat_occupancy"),
        BRICK.hasLocation,
        rdflib.URIRef(f"{NS}Room_5.28"),
    ) in g


# ── zoneId join key ───────────────────────────────────────────────────────────


def test_zone_id_heuristics():
    assert zone_id_for(f"{NS}Zone_5.28", "HVAC Zone 5.28") == "5.28"
    assert zone_id_for(f"{NS}Room_301A", "Office 3.01A") == "3.01A"
    assert zone_id_for(f"{NS}RM001A_room", "RM001A_room") == "RM001A_room"  # local fallback


def test_zoneid_ttl_parses_and_covers_all_spaces():
    spaces = [_space("RoomA", label="Room A"), _space("Zone_5.28", label="HVAC Zone 5.28")]
    ttl = build_zoneid_ttl(NS, spaces)
    g = rdflib.Graph()
    g.parse(data=ttl, format="turtle")
    assert (rdflib.URIRef(f"{NS}Zone_5.28"), ONTOSAGE.zoneId, rdflib.Literal("5.28")) in g
    assert len(list(g.triples((None, ONTOSAGE.zoneId, None)))) == 2
