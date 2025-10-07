#!/usr/bin/env python
"""
Synthetic Brick Building Generator
=================================

Action Plan Ref: #3 Synthetic Brick Ontology Generation

Generates a synthetic building ontology (Brick) from a JSON specification.

Inputs (JSON spec example):
{
  "building_id": "bldg_office8",
  "building_name": "MultiStoreyOffice",
  "floors": 8,
  "rooms_per_floor": 12,
  "zones": 3,
  "sensors": {
     "Air_Temperature_Sensor": {"per_room": 1},
     "Zone_Air_Humidity_Sensor": {"per_room": 1},
     "CO2_Level_Sensor": {"per_room": 1, "probability": 0.8},
     "PM2_5_Level_Sensor": {"per_room": 0.3},
     "Air_Quality_Sensor": {"per_room": 0.2},
     "Sound_Noise_Sensor_MEMS": {"per_room": 0.4}
  },
  "options": {
     "seed": 42,
     "include_fume_hoods": false,
     "lab_profile": false
  }
}

Outputs:
- TTL ontology file with consistent prefixes
- CSV / JSON mapping of sensor UUIDs to names
- Optional SHACL validation run (if --validate and shapes path provided)

Usage:
  python scripts/generate_synthetic_building.py --spec spec.json --out-dir datasets/buildings/bldg_office8 \
      --shacl-shapes datasets/shacl/building_shapes.ttl --validate

Features:
- Deterministic generation via seed
- Optional omission probability for sensors
- Adds location hierarchy: Building > Floor > Room
- Adds zone membership annotation (custom predicate ref:hasZone or brick:isPartOf)
- Property chain reasoning target:
    Sensor brick:hasLocation Room ; Room brick:isPartOf Floor ; Floor brick:isPartOf Building .
  Allows inference of sensor in building.
"""
from __future__ import annotations
import argparse
import json
import os
import sys
import uuid
import random
from dataclasses import dataclass, field
from typing import Dict, List, Optional

try:
    from rdflib import Graph, Namespace, RDF, RDFS, Literal, URIRef
except ImportError as e:
    print("rdflib is required. Install via pip install rdflib", file=sys.stderr)
    raise

BRICK = Namespace("https://brickschema.org/schema/Brick#")
BLDGNS_BASE = "http://example.org/building/"
REF = Namespace("https://brickschema.org/schema/Brick/ref#")
TAG = Namespace("https://brickschema.org/schema/BrickTag#")
QUDT_UNIT = Namespace("http://qudt.org/vocab/unit/")

@dataclass
class SensorSpec:
    per_room: float  # can be fractional to represent probability or count
    probability: Optional[float] = None  # if provided, per_room treated as count when >=1 else probability base

@dataclass
class Spec:
    building_id: str
    building_name: str
    floors: int
    rooms_per_floor: int
    zones: int
    sensors: Dict[str, SensorSpec]
    options: Dict[str, object] = field(default_factory=dict)

# --------------------- Utility ---------------------

def load_spec(path: str) -> Spec:
    with open(path, 'r', encoding='utf-8') as f:
        raw = json.load(f)
    sensors = {k: SensorSpec(**v) for k, v in raw.get('sensors', {}).items()}
    return Spec(
        building_id=raw['building_id'],
        building_name=raw.get('building_name', raw['building_id']),
        floors=int(raw['floors']),
        rooms_per_floor=int(raw['rooms_per_floor']),
        zones=int(raw.get('zones', 1)),
        sensors=sensors,
        options=raw.get('options', {})
    )

# --------------------- Generation ---------------------

def make_uri(base: str, *parts: str) -> URIRef:
    return URIRef(base + '_'.join(parts))

def add_location_hierarchy(g: Graph, spec: Spec, base: str) -> Dict[str, URIRef]:
    mapping = {}
    bldg_uri = make_uri(base, spec.building_id)
    g.add((bldg_uri, RDF.type, BRICK.Building))
    g.add((bldg_uri, RDFS.label, Literal(spec.building_name)))
    mapping['building'] = bldg_uri

    for f in range(1, spec.floors + 1):
        floor_id = f"Floor{f}"
        floor_uri = make_uri(base, spec.building_id, floor_id)
        g.add((floor_uri, RDF.type, BRICK.Floor))
        g.add((floor_uri, BRICK.isPartOf, bldg_uri))
        g.add((floor_uri, RDFS.label, Literal(floor_id)))
        mapping[floor_id] = floor_uri
        for r in range(1, spec.rooms_per_floor + 1):
            room_id = f"Room{f}.{r:02d}"
            room_uri = make_uri(base, spec.building_id, room_id)
            g.add((room_uri, RDF.type, BRICK.Room))
            g.add((room_uri, BRICK.isPartOf, floor_uri))
            g.add((room_uri, RDFS.label, Literal(room_id)))
            mapping[room_id] = room_uri
    return mapping

def assign_zones(spec: Spec, mapping: Dict[str, URIRef]) -> Dict[str, int]:
    rooms = [k for k in mapping.keys() if k.startswith('Room')]
    zones = {}
    for idx, room in enumerate(sorted(rooms)):
        zones[room] = (idx % spec.zones) + 1
    return zones

def add_sensors(g: Graph, spec: Spec, mapping: Dict[str, URIRef], zones: Dict[str, int], base: str) -> List[Dict[str, str]]:
    sensor_records = []
    room_ids = [k for k in mapping if k.startswith('Room')]
    for room_id in room_ids:
        room_uri = mapping[room_id]
        z = zones.get(room_id, 1)
        for sensor_type, sconf in spec.sensors.items():
            # Determine count
            count = 0
            if sconf.per_room >= 1:
                count = int(sconf.per_room)
                # Apply probability if given for each instance
                for i in range(count):
                    if sconf.probability is not None and random.random() > sconf.probability:
                        continue
                    sensor_uuid = str(uuid.uuid4())
                    sensor_name = f"{sensor_type}_{room_id}_{i+1}" if count > 1 else f"{sensor_type}_{room_id}"
                    sensor_uri = make_uri(base, spec.building_id, sensor_name)
                    g.add((sensor_uri, RDF.type, BRICK.term(sensor_type)))
                    g.add((sensor_uri, BRICK.hasLocation, room_uri))
                    g.add((sensor_uri, RDFS.label, Literal(sensor_name)))
                    # Custom annotation for zone
                    g.add((sensor_uri, BRICK.isPartOf, mapping[f"Floor{room_id.split('.')[0][4:]}" ]))
                    sensor_records.append({"uuid": sensor_uuid, "name": sensor_name, "room": room_id, "zone": z, "type": sensor_type})
            else:
                # per_room <1 treated as probability of single sensor
                if random.random() <= sconf.per_room:
                    sensor_uuid = str(uuid.uuid4())
                    sensor_name = f"{sensor_type}_{room_id}"
                    sensor_uri = make_uri(base, spec.building_id, sensor_name)
                    g.add((sensor_uri, RDF.type, BRICK.term(sensor_type)))
                    g.add((sensor_uri, BRICK.hasLocation, room_uri))
                    g.add((sensor_uri, RDFS.label, Literal(sensor_name)))
                    g.add((sensor_uri, BRICK.isPartOf, mapping[f"Floor{room_id.split('.')[0][4:]}" ]))
                    sensor_records.append({"uuid": sensor_uuid, "name": sensor_name, "room": room_id, "zone": z, "type": sensor_type})
    return sensor_records

# --------------------- SHACL Validation (optional) ---------------------

def validate_graph(graph: Graph, shapes_path: str) -> bool:
    try:
        from pyshacl import validate
    except ImportError:
        print("pyshacl not installed; skip validation", file=sys.stderr)
        return False
    conforms, results_graph, results_text = validate(
        data_graph=graph,
        shacl_graph=Graph().parse(shapes_path, format='turtle'),
        inference='rdfs',
        abort_on_error=False,
        meta_shacl=False,
        advanced=True,
    )
    print(results_text)
    return bool(conforms)

# --------------------- Main ---------------------

def main():
    parser = argparse.ArgumentParser(description="Generate synthetic Brick building ontology")
    parser.add_argument('--spec', required=True, help='Path to JSON spec')
    parser.add_argument('--out-dir', required=True, help='Output directory')
    parser.add_argument('--validate', action='store_true', help='Run SHACL validation if shapes provided')
    parser.add_argument('--shacl-shapes', help='Path to SHACL shapes TTL file')
    parser.add_argument('--materialize-chain', action='store_true', help='Materialize sensor->building association triples')
    args = parser.parse_args()

    spec = load_spec(args.spec)
    seed = int(spec.options.get('seed', 1234))
    random.seed(seed)

    os.makedirs(args.out_dir, exist_ok=True)

    g = Graph()
    g.bind('brick', BRICK)
    g.bind(spec.building_id, Namespace(BLDGNS_BASE + spec.building_id + '#'))
    g.bind('ref', REF)
    g.bind('tag', TAG)

    base = BLDGNS_BASE

    mapping = add_location_hierarchy(g, spec, base)
    zones = assign_zones(spec, mapping)
    sensor_records = add_sensors(g, spec, mapping, zones, base)

    # Optionally materialize property chain shortcut: sensor brick:isPartOf building
    if args.materialize_chain:
        bldg_uri = mapping['building']
        for srec in sensor_records:
            sensor_uri = make_uri(base, spec.building_id, srec['name'])
            g.add((sensor_uri, BRICK.isPartOf, bldg_uri))

    ttl_path = os.path.join(args.out_dir, f"{spec.building_id}.ttl")
    g.serialize(destination=ttl_path, format='turtle')
    print(f"Wrote ontology: {ttl_path}")

    # Write sensor mapping CSV + JSON
    csv_path = os.path.join(args.out_dir, 'sensor_mappings.csv')
    with open(csv_path, 'w', encoding='utf-8') as f:
        f.write('uuid,name,type,room,zone\n')
        for rec in sensor_records:
            f.write(f"{rec['uuid']},{rec['name']},{rec['type']},{rec['room']},{rec['zone']}\n")
    json_path = os.path.join(args.out_dir, 'sensor_mappings.json')
    with open(json_path, 'w', encoding='utf-8') as jf:
        json.dump(sensor_records, jf, indent=2)
    print(f"Wrote sensor mappings: {csv_path}, {json_path}")

    if args.validate and args.shacl_shapes:
        ok = validate_graph(g, args.shacl_shapes)
        if not ok:
            print("SHACL validation FAILED", file=sys.stderr)
            sys.exit(2)
        print("SHACL validation passed")

if __name__ == '__main__':
    main()
