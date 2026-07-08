#!/usr/bin/env python3
"""Generate the time-series EXTENSION TTL for bldg1's input/data sensors.

This is the standardization step (Workstream B1): every CSV under input/data/
that holds sensor readings becomes a first-class Brick point in the ontology —
a UUID + label + location(Floor) + unit + the standard timeseries reference
(``ref:hasExternalReference -> ref:TimeseriesReference{hasTimeseriesId, storedAt}``)
— matching the pattern the existing abacws temperature/CO2 sensors already use.

Outputs (both under input/, the canonical flat layout):
  * input/bldg1_timeseries_extension.ttl   — load into the SAME GraphDB `bldg` repo
  * input/bldg1_timeseries_extension_uuids.json — UUID/table/class map reused by the
        narrow-table loader and the dummy data publisher (single source of truth).

Deterministic UUIDs (uuid5 over the entity URI) -> re-running is idempotent and the
TTL, the MySQL tables, and the publisher all agree on the same UUID per sensor.

Readings live in NARROW per-modality MySQL tables `(uuid, datetime, value)` reached
via ``ref:storedAt bldg:<table>`` (e.g. bldg:energy_data). `input/` holds metadata
only — no raw CSV sensor files in the runtime path.
"""

from __future__ import annotations

import json
import uuid
from pathlib import Path
from typing import List, NamedTuple

BLDG_NS = "http://abacwsbuilding.cardiff.ac.uk/abacws#"
REPO_ROOT = Path(__file__).resolve().parents[1]
OUT_TTL = REPO_ROOT / "input" / "bldg1_timeseries_extension.ttl"
OUT_MAP = REPO_ROOT / "input" / "bldg1_timeseries_extension_uuids.json"


class Sensor(NamedTuple):
    csv: str  # input/data/<csv>.csv
    value_col: str  # the reading column in the CSV
    local: str  # entity local name -> bldg:<local>
    brick_class: str  # prefixed class (brick:… or bldg:… custom)
    unit: str  # prefixed QUDT unit
    table: str  # narrow MySQL table == storedAt key (bldg:<table>)
    location: str  # prefixed location entity (bldg:FloorN or bldg:Abacws)
    label: str


# Brick has native classes for all of these EXCEPT noise + vibration, which we
# define as custom subclasses of brick:Sensor below.
SENSORS: List[Sensor] = (
    [
        Sensor(
            f"energy_meter_floor{n}",
            "kwh",
            f"Energy_Meter_Floor{n}",
            "brick:Energy_Sensor",
            "unit:KiloW-HR",
            "energy_data",
            f"bldg:Floor{n}",
            f"Electrical Energy Meter — Floor {n}",
        )
        for n in range(6)
    ]
    + [
        Sensor(
            f"occupancy_floor{n}",
            "occupancy",
            f"Occupancy_Sensor_Floor{n}",
            "brick:Occupancy_Count_Sensor",
            "unit:NUM",
            "occupancy_data",
            f"bldg:Floor{n}",
            f"Occupancy Count Sensor — Floor {n}",
        )
        for n in range(6)
    ]
    + [
        Sensor(
            "water_main",
            "flow_lpm",
            "Water_Flow_Sensor_Main",
            "brick:Water_Flow_Sensor",
            "unit:L-PER-MIN",
            "water_data",
            "bldg:Abacws",
            "Water Main Flow Sensor",
        ),
        Sensor(
            "noise_floor5",
            "noise_db",
            "Noise_Sensor_Floor5",
            "bldg:Noise_Level_Sensor",
            "unit:DeciB",
            "noise_data",
            "bldg:Floor5",
            "Noise Level Sensor — Floor 5",
        ),
        Sensor(
            "iaq_pm25_floor3",
            "pm25",
            "PM25_Sensor_Floor3",
            "brick:PM2.5_Level_Sensor",
            "unit:MicroGM-PER-M3",
            "iaq_data",
            "bldg:Floor3",
            "PM2.5 Level Sensor — Floor 3",
        ),
        Sensor(
            "iaq_voc_floor3",
            "voc",
            "VOC_Sensor_Floor3",
            "brick:TVOC_Level_Sensor",
            "unit:PPB",
            "iaq_data",
            "bldg:Floor3",
            "TVOC Level Sensor — Floor 3",
        ),
        Sensor(
            "light_floor5",
            "lux",
            "Illuminance_Sensor_Floor5",
            "brick:Illuminance_Sensor",
            "unit:LUX",
            "light_data",
            "bldg:Floor5",
            "Illuminance Sensor — Floor 5",
        ),
        Sensor(
            "lift_vibration_floor0",
            "vib_mm_s",
            "Vibration_Sensor_Floor0",
            "bldg:Vibration_Sensor",
            "unit:MilliM-PER-SEC",
            "equipment_data",
            "bldg:Floor0",
            "Lift Vibration Sensor — Floor 0",
        ),
        Sensor(
            "ahu_runtime_floor5",
            "runtime_h",
            "AHU_Runtime_Sensor_Floor5",
            "brick:Run_Time_Sensor",
            "unit:HR",
            "equipment_data",
            "bldg:Floor5",
            "AHU Run Time Sensor — Floor 5",
        ),
    ]
)

PREFIXES = """\
@prefix bldg:   <http://abacwsbuilding.cardiff.ac.uk/abacws#> .
@prefix brick:  <https://brickschema.org/schema/Brick#> .
@prefix ref:    <https://brickschema.org/schema/Brick/ref#> .
@prefix ashrae: <http://data.ashrae.org/standard223#> .
@prefix unit:   <http://qudt.org/vocab/unit/> .
@prefix rdf:    <http://www.w3.org/1999/02/22-rdf-syntax-ns#> .
@prefix rdfs:   <http://www.w3.org/2000/01/rdf-schema#> .
@prefix owl:    <http://www.w3.org/2002/07/owl#> .
@prefix xsd:    <http://www.w3.org/2001/XMLSchema#> .

# ── Custom point classes (Brick 1.4 has no native noise/vibration point class) ──
bldg:Noise_Level_Sensor a owl:Class ;
    rdfs:subClassOf brick:Sensor ;
    rdfs:label "Noise Level Sensor"@en .

bldg:Vibration_Sensor a owl:Class ;
    rdfs:subClassOf brick:Sensor ;
    rdfs:label "Vibration Sensor"@en .
"""


# Extra (super)classes to type an instance with, so generic class queries the
# LLM/class-map already use (e.g. brick:TVOC_Sensor, brick:Occupancy_Sensor) still
# resolve these points — matching how the existing abacws sensors enumerate their
# full type hierarchy explicitly (GraphDB has no subclass reasoning enabled).
EXTRA_TYPES = {
    "brick:Occupancy_Count_Sensor": ["brick:Occupancy_Sensor"],
    "brick:PM2.5_Level_Sensor": ["brick:PM2.5_Sensor", "brick:Air_Quality_Sensor"],
    "brick:TVOC_Level_Sensor": ["brick:TVOC_Sensor", "brick:Air_Quality_Sensor"],
}


def _uuid_for(local: str) -> str:
    return str(uuid.uuid5(uuid.NAMESPACE_URL, BLDG_NS + local))


def _sensor_ttl(s: Sensor, ts_uuid: str) -> str:
    types = [s.brick_class] + EXTRA_TYPES.get(s.brick_class, []) + ["brick:Sensor", "brick:Point"]
    type_block = " ,\n        ".join(["owl:NamedIndividual"] + types)
    return f"""\
bldg:{s.local} a {type_block} ;
    rdfs:label "{s.label}"@en ;
    brick:hasUnit {s.unit} ;
    brick:hasLocation {s.location} ;
    ashrae:hasExternalReference [
        a ashrae:ExternalReference , ref:ExternalReference , ref:TimeseriesReference ;
        ref:hasTimeseriesId "{ts_uuid}" ;
        ref:storedAt bldg:{s.table}
    ] ;
    ref:hasExternalReference [
        a ashrae:ExternalReference , ref:ExternalReference , ref:TimeseriesReference ;
        ref:hasTimeseriesId "{ts_uuid}" ;
        ref:storedAt bldg:{s.table}
    ] .
"""


def main() -> None:
    ttl_parts = [PREFIXES, "\n# ── Time-series sensor points (migrated from input/data CSVs) ──\n"]
    uuid_map = {}
    for s in SENSORS:
        ts_uuid = _uuid_for(s.local)
        ttl_parts.append("\n" + _sensor_ttl(s, ts_uuid))
        uuid_map[s.local] = {
            "uuid": ts_uuid,
            "csv": s.csv,
            "value_col": s.value_col,
            "table": s.table,
            "brick_class": s.brick_class,
            "unit": s.unit,
            "location": s.location,
            "label": s.label,
        }

    OUT_TTL.write_text("".join(ttl_parts), encoding="utf-8")
    OUT_MAP.write_text(json.dumps(uuid_map, indent=2), encoding="utf-8")
    tables = sorted({s.table for s in SENSORS})
    print(f"Wrote {len(SENSORS)} sensor points -> {OUT_TTL}")
    print(f"Wrote UUID map -> {OUT_MAP}")
    print(f"Narrow tables (storedAt keys): {tables}")


if __name__ == "__main__":
    main()
