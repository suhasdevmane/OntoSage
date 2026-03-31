# OntoSage Test Ontology Fixtures — Phase 5.2
# =============================================
# Minimal in-memory TTL/graph fixtures for use in unit and integration tests.
# No files on disk required — each fixture returns a populated rdflib Graph.
#
# Usage:
#   from tests.fixtures.ontology_fixtures import (
#       brick_fixture, rec_fixture, s223_fixture, mock_building_graph
#   )

"""
Test ontology fixtures for OntoSage (Phase 5.2).

Provides three schema variants (Brick, REC, ASHRAE 223P) plus a combined
mock building graph with 10 sensors across 3 zones on 2 floors.
"""

from __future__ import annotations
from typing import List, Dict

# ─────────────────────────────────────────────────────────────────────────────
# Raw TTL fixtures (schema-minimal)
# ─────────────────────────────────────────────────────────────────────────────

MOCK_BRICK_TTL = """\
@prefix brick: <https://brickschema.org/schema/Brick#> .
@prefix ref:   <https://brickschema.org/schema/Brick/ref#> .
@prefix bldg:  <http://test.building.local/mock#> .
@prefix rdf:   <http://www.w3.org/1999/02/22-rdf-syntax-ns#> .
@prefix rdfs:  <http://www.w3.org/2000/01/rdf-schema#> .
@prefix xsd:   <http://www.w3.org/2001/XMLSchema#> .

# Building
bldg:MockBuilding a brick:Building ;
    rdfs:label "Mock Test Building" .

# Floors
bldg:Floor_1 a brick:Floor ;
    rdfs:label "Floor 1" ;
    brick:isPartOf bldg:MockBuilding .
bldg:Floor_2 a brick:Floor ;
    rdfs:label "Floor 2" ;
    brick:isPartOf bldg:MockBuilding .

# Zones
bldg:Zone_1_01 a brick:HVAC_Zone ;
    rdfs:label "Zone 1.01" ;
    brick:isPartOf bldg:Floor_1 .
bldg:Zone_1_02 a brick:HVAC_Zone ;
    rdfs:label "Zone 1.02" ;
    brick:isPartOf bldg:Floor_1 .
bldg:Zone_2_01 a brick:HVAC_Zone ;
    rdfs:label "Zone 2.01" ;
    brick:isPartOf bldg:Floor_2 .

# Temperature Sensors
bldg:Air_Temperature_Sensor_1_01 a brick:Air_Temperature_Sensor ;
    rdfs:label "Air Temperature Sensor 1.01" ;
    brick:isPointOf bldg:Zone_1_01 ;
    ref:hasExternalReference [
        ref:hasTimeseriesId "uuid-temp-101" ;
        ref:storedAt "mysql://abacws"
    ] .
bldg:Air_Temperature_Sensor_1_02 a brick:Air_Temperature_Sensor ;
    rdfs:label "Air Temperature Sensor 1.02" ;
    brick:isPointOf bldg:Zone_1_02 ;
    ref:hasExternalReference [
        ref:hasTimeseriesId "uuid-temp-102" ;
        ref:storedAt "mysql://abacws"
    ] .
bldg:Air_Temperature_Sensor_2_01 a brick:Air_Temperature_Sensor ;
    rdfs:label "Air Temperature Sensor 2.01" ;
    brick:isPointOf bldg:Zone_2_01 ;
    ref:hasExternalReference [
        ref:hasTimeseriesId "uuid-temp-201" ;
        ref:storedAt "mysql://abacws"
    ] .

# Humidity Sensors
bldg:Relative_Humidity_Sensor_1_01 a brick:Relative_Humidity_Sensor ;
    rdfs:label "Relative Humidity Sensor 1.01" ;
    brick:isPointOf bldg:Zone_1_01 ;
    ref:hasExternalReference [
        ref:hasTimeseriesId "uuid-hum-101" ;
        ref:storedAt "mysql://abacws"
    ] .
bldg:Relative_Humidity_Sensor_2_01 a brick:Relative_Humidity_Sensor ;
    rdfs:label "Relative Humidity Sensor 2.01" ;
    brick:isPointOf bldg:Zone_2_01 ;
    ref:hasExternalReference [
        ref:hasTimeseriesId "uuid-hum-201" ;
        ref:storedAt "mysql://abacws"
    ] .

# CO2 Sensors
bldg:CO2_Sensor_1_01 a brick:CO2_Sensor ;
    rdfs:label "CO2 Sensor 1.01" ;
    brick:isPointOf bldg:Zone_1_01 ;
    ref:hasExternalReference [
        ref:hasTimeseriesId "uuid-co2-101" ;
        ref:storedAt "mysql://abacws"
    ] .
bldg:CO2_Sensor_1_02 a brick:CO2_Sensor ;
    rdfs:label "CO2 Sensor 1.02" ;
    brick:isPointOf bldg:Zone_1_02 ;
    ref:hasExternalReference [
        ref:hasTimeseriesId "uuid-co2-102" ;
        ref:storedAt "mysql://abacws"
    ] .

# Occupancy
bldg:Occupancy_Sensor_1_01 a brick:Occupancy_Sensor ;
    rdfs:label "Occupancy Sensor 1.01" ;
    brick:isPointOf bldg:Zone_1_01 ;
    ref:hasExternalReference [
        ref:hasTimeseriesId "uuid-occ-101" ;
        ref:storedAt "mysql://abacws"
    ] .

# VAV (equipment)
bldg:VAV_1_01 a brick:Variable_Air_Volume_Box ;
    rdfs:label "VAV 1.01" ;
    brick:isPartOf bldg:Zone_1_01 .
bldg:VAV_1_02 a brick:Variable_Air_Volume_Box ;
    rdfs:label "VAV 1.02" ;
    brick:isPartOf bldg:Zone_1_02 .
"""

MOCK_REC_TTL = """\
@prefix rec:   <https://w3id.org/rec#> .
@prefix rdf:   <http://www.w3.org/1999/02/22-rdf-syntax-ns#> .
@prefix rdfs:  <http://www.w3.org/2000/01/rdf-schema#> .
@prefix bldg:  <http://test.building.local/mock#> .

bldg:RecBuilding a rec:Building ;
    rdfs:label "Mock REC Building" .

bldg:RecFloor1 a rec:Floor ;
    rdfs:label "Floor 1" ;
    rec:isPartOf bldg:RecBuilding .

bldg:RecRoom101 a rec:Room ;
    rdfs:label "Room 101" ;
    rec:isPartOf bldg:RecFloor1 .

bldg:RecTempSensor a rec:TemperatureSensor ;
    rdfs:label "Temp Sensor REC 101" ;
    rec:isLocatedIn bldg:RecRoom101 ;
    rec:timeseriesId "uuid-rec-temp-101" .

bldg:RecCO2Sensor a rec:CO2Sensor ;
    rdfs:label "CO2 Sensor REC 101" ;
    rec:isLocatedIn bldg:RecRoom101 ;
    rec:timeseriesId "uuid-rec-co2-101" .
"""

MOCK_S223_TTL = """\
@prefix s223: <http://data.ashrae.org/standard223#> .
@prefix rdf:  <http://www.w3.org/1999/02/22-rdf-syntax-ns#> .
@prefix rdfs: <http://www.w3.org/2000/01/rdf-schema#> .
@prefix bldg: <http://test.building.local/mock#> .

bldg:S223System a s223:System ;
    rdfs:label "Mock 223P System" .

bldg:S223Zone a s223:DomainSpace ;
    rdfs:label "HVAC Zone A" ;
    s223:contains bldg:S223System .

bldg:S223TempSensor a s223:TemperatureSensor ;
    rdfs:label "Temperature Sensor 223P" ;
    s223:cnx bldg:S223Zone .

bldg:S223HumSensor a s223:HumiditySensor ;
    rdfs:label "Humidity Sensor 223P" ;
    s223:cnx bldg:S223Zone .
"""


# ─────────────────────────────────────────────────────────────────────────────
# Fixture factories
# ─────────────────────────────────────────────────────────────────────────────

def brick_fixture():
    """Return a parsed rdflib Graph with mock Brick v1.3 building."""
    try:
        from rdflib import Graph
        g = Graph()
        g.parse(data=MOCK_BRICK_TTL, format="turtle")
        return g
    except ImportError:
        return None


def rec_fixture():
    """Return a parsed rdflib Graph with mock REC 3.3 building."""
    try:
        from rdflib import Graph
        g = Graph()
        g.parse(data=MOCK_REC_TTL, format="turtle")
        return g
    except ImportError:
        return None


def s223_fixture():
    """Return a parsed rdflib Graph with mock ASHRAE 223P system."""
    try:
        from rdflib import Graph
        g = Graph()
        g.parse(data=MOCK_S223_TTL, format="turtle")
        return g
    except ImportError:
        return None


def mock_building_graph():
    """Return a combined Brick graph (most complete) suitable for query testing."""
    return brick_fixture()


# ─────────────────────────────────────────────────────────────────────────────
# Mock sensor data (time-series rows)
# ─────────────────────────────────────────────────────────────────────────────

def mock_sensor_readings(uuid: str = "uuid-temp-101", n: int = 50) -> List[Dict]:
    """Generate synthetic sensor readings for testing."""
    import math
    import datetime
    base = datetime.datetime(2024, 3, 1, 8, 0, 0)
    rows = []
    for i in range(n):
        ts = base + datetime.timedelta(minutes=i * 10)
        # Sine wave + noise
        val = 21.0 + 3.0 * math.sin(i * 0.3) + (hash(f"{uuid}{i}") % 100) / 500.0
        rows.append({
            "Datetime": ts.isoformat(),
            "uuid": uuid,
            "value": round(val, 2),
        })
    return rows


def mock_anomalous_readings(n: int = 20) -> List[Dict]:
    """Generate readings with intentional anomalies for anomaly agent testing."""
    import datetime
    base = datetime.datetime(2024, 3, 1, 8, 0, 0)
    rows = []
    for i in range(n):
        ts = base + datetime.timedelta(minutes=i * 10)
        # Inject anomaly at index 5 (spike) and 10 (out-of-range)
        if i == 5:
            val = 35.0   # spike — very high temp
        elif i == 10:
            val = 8.0    # out-of-range — very cold
        else:
            val = 22.0 + (i % 3) * 0.5
        rows.append({
            "Datetime": ts.isoformat(),
            "uuid": "uuid-temp-101",
            "temperature": val,
        })
    return rows


def mock_sql_result(uuid: str = "uuid-temp-101", n: int = 30) -> Dict:
    """Simulate what SQLAgent.fetch_data_for_uuids returns."""
    return {
        "success": True,
        "data": mock_sensor_readings(uuid, n),
        "formatted_response": f"Retrieved {n} readings for {uuid}.",
        "query_info": {"uuid": uuid, "backend": "mysql"},
    }


def mock_sparql_result(sensor_name: str = "Air_Temperature_Sensor_1_01") -> Dict:
    """Simulate what SPARQLAgent.generate_query returns."""
    return {
        "success": True,
        "query": "SELECT * WHERE { ?s a brick:Air_Temperature_Sensor }",
        "results": {
            "results": {
                "bindings": [
                    {
                        "sensor": {"value": f"http://test.building.local/mock#{sensor_name}"},
                        "uuid": {"value": "uuid-temp-101"},
                        "label": {"value": sensor_name.replace("_", " ")},
                        "storage": {"value": "mysql://abacws"},
                    }
                ]
            }
        },
        "formatted_response": f"Found {sensor_name} with UUID uuid-temp-101.",
        "standardized": {
            "results": [
                {"uuid": "uuid-temp-101", "label": sensor_name, "storage": "mysql://abacws"}
            ]
        },
    }
