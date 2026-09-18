#!/usr/bin/env python3
"""Provision the three declared modalities that had no points at all (BUG-649).

WHY THIS EXISTS
---------------
``config/saturation_modalities.yaml`` declared ``damper_position`` (V6-T26) and
``waste_fill`` / ``waste_weight`` (V6-T43), and the provisioning half never followed. Each
resolved to ZERO points in the live graph, so the modality looked handled while the building
could not answer a single question about it. Declaring a modality is not covering a domain.

WHAT IT WRITES
--------------
* ``<building>_damper_points.ttl``  — one outside-air damper per air handling unit, with a
  ``brick:Damper_Position_Sensor`` point on it. Every class used is verified present in the
  loaded Brick TBox before anything is written: ``brick:Elevator_Status`` was declared in
  this very config file and does not exist in Brick at all (BUG-648), so "the config names
  it" is not evidence that a term is real.
* ``<building>_waste_points.ttl``   — a general-waste and a mixed-recycling bin per floor,
  each with a fill-level and a weight point, located in the most plausible room that floor
  actually has.

Both files are DISCOVERED, not hardcoded: the AHUs come from the graph, and each floor's bin
location is chosen from that floor's own rooms by a stated preference order. Re-running is a
no-op — ids are ``uuid5`` of the point IRI.

EVERY POINT DECLARES ``ontosage:isSimulated true``
--------------------------------------------------
These readings are generated, and the graph says so. That declaration is INTERNAL
provenance — it is what lets an answer know its own basis and what the scorecard's
real/synthetic share is computed from — and it is deliberately NOT the same thing as the
words a reader sees: the user-visible source chips name the sensing system ("Temperature
Sensing System"), never the fixture (BUG-665). Declared generation is not fabrication; an
undeclared generated reading is.

``tests/test_provenance_honesty.py`` fails closed on a provisioner that omits it, which is
how this omission was caught here — before these points had answered a single question.

WHAT IT DOES NOT DO
-------------------
It does not publish. Fill level and weight are correlated and fill is a SAWTOOTH (a bin
fills and is emptied; it does not random-walk), and a damper follows its own air handler's
fan. That behaviour lives in the publisher, which writes them as groups — the same reason
plant points are published per equipment (BUG-638/BUG-664).
"""
from __future__ import annotations

import argparse
import json
import os
import sys
import uuid
from pathlib import Path
from typing import Dict, List, Optional, Tuple

import requests

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO))

DEFAULT_ENDPOINT = os.environ.get("GRAPHDB_QUERY", "http://localhost:7200/repositories/bldg")

#: Rooms a bin plausibly stands in, best first. A floor with none of these gets its
#: lowest-numbered room rather than no bin at all — a building with waste on five floors and
#: none on the sixth is a stranger claim than a bin in an ordinary room.
ROOM_PREFERENCE = ("kitchen", "break", "common", "atrium", "reception", "lobby", "corridor")

STREAMS = (
    ("General", "general waste"),
    ("Recycling", "mixed recycling"),
)


def sparql(query: str, endpoint: str) -> List[Dict[str, Dict[str, str]]]:
    resp = requests.post(
        endpoint,
        data=query.encode("utf-8"),
        headers={
            "Content-Type": "application/sparql-query",
            "Accept": "application/sparql-results+json",
        },
        timeout=120,
    )
    resp.raise_for_status()
    return resp.json()["results"]["bindings"]


def local(iri: str) -> str:
    s = str(iri)
    for sep in ("#", "/"):
        if sep in s:
            s = s.rsplit(sep, 1)[-1]
    return s


def point_uuid(ns: str, name: str) -> str:
    return str(uuid.uuid5(uuid.NAMESPACE_URL, ns + name))


def verify_classes(endpoint: str, classes: List[str]) -> None:
    """Refuse to write a term the ontology does not define (BUG-179, BUG-648)."""
    values = " ".join(classes)
    rows = sparql(
        "PREFIX owl: <http://www.w3.org/2002/07/owl#>\n"
        "PREFIX brick: <https://brickschema.org/schema/Brick#>\n"
        "PREFIX ontosage: <http://ontosage.org/capabilities#>\n"
        f"SELECT ?c WHERE {{ VALUES ?c {{ {values} }} ?c a owl:Class }}",
        endpoint,
    )
    found = {local(r["c"]["value"]) for r in rows}
    missing = [c for c in classes if local(c.split(":")[-1]) not in found and c.split(":")[-1] not in found]
    if missing:
        raise SystemExit(
            "ABORTING WITHOUT WRITING — these classes are not declared in the loaded "
            f"ontology: {missing}. Minting them would put invented terms in a real "
            "namespace, which is how 56 mistyped instances arrived once already."
        )


def discover_ahus(endpoint: str) -> List[Tuple[str, str]]:
    rows = sparql(
        "PREFIX rdf: <http://www.w3.org/1999/02/22-rdf-syntax-ns#>\n"
        "PREFIX rdfs: <http://www.w3.org/2000/01/rdf-schema#>\n"
        "PREFIX brick: <https://brickschema.org/schema/Brick#>\n"
        "SELECT DISTINCT ?ahu ?label WHERE { ?ahu rdf:type brick:Air_Handling_Unit . "
        "OPTIONAL { ?ahu rdfs:label ?label } } ORDER BY ?ahu",
        endpoint,
    )
    return [(local(r["ahu"]["value"]), r.get("label", {}).get("value", "")) for r in rows]


def discover_bin_rooms(endpoint: str) -> Dict[str, Tuple[str, str]]:
    """floor local name -> (room local name, room label), one per floor."""
    rows = sparql(
        "PREFIX rdf: <http://www.w3.org/1999/02/22-rdf-syntax-ns#>\n"
        "PREFIX rdfs: <http://www.w3.org/2000/01/rdf-schema#>\n"
        "PREFIX brick: <https://brickschema.org/schema/Brick#>\n"
        "SELECT DISTINCT ?floor ?room ?label WHERE {\n"
        "  ?room rdf:type/rdfs:subClassOf* brick:Room .\n"
        "  { ?floor brick:hasPart ?room } UNION { ?room brick:isPartOf ?floor }\n"
        "  ?floor rdf:type brick:Floor .\n"
        "  OPTIONAL { ?room rdfs:label ?label }\n"
        "} ORDER BY ?floor ?room",
        endpoint,
    )
    by_floor: Dict[str, List[Tuple[str, str]]] = {}
    for r in rows:
        floor = local(r["floor"]["value"])
        by_floor.setdefault(floor, []).append(
            (local(r["room"]["value"]), r.get("label", {}).get("value", ""))
        )

    chosen: Dict[str, Tuple[str, str]] = {}
    for floor, rooms in by_floor.items():
        pick = None
        for want in ROOM_PREFERENCE:
            for room, label in sorted(set(rooms)):
                if want in label.lower():
                    pick = (room, label)
                    break
            if pick:
                break
        if pick is None and rooms:
            pick = sorted(set(rooms))[0]
        if pick:
            chosen[floor] = pick
    return chosen


def _header(title: str, why: str) -> str:
    return (
        f"# {title}\n#\n"
        + "\n".join(f"# {line}" for line in why.strip().splitlines())
        + "\n#\n# GENERATED by scripts/provision_damper_and_waste_points.py — re-runnable;\n"
        "# ids are uuid5 of the point IRI, so running it twice changes nothing.\n\n"
        "@prefix rdf:      <http://www.w3.org/1999/02/22-rdf-syntax-ns#> .\n"
        "@prefix rdfs:     <http://www.w3.org/2000/01/rdf-schema#> .\n"
        "@prefix owl:      <http://www.w3.org/2002/07/owl#> .\n"
        "@prefix brick:    <https://brickschema.org/schema/Brick#> .\n"
        "@prefix ref:      <https://brickschema.org/schema/Brick/ref#> .\n"
        "@prefix ontosage: <http://ontosage.org/capabilities#> .\n"
    )


def build_damper_ttl(ns: str, prefix: str, ahus: List[Tuple[str, str]]) -> Tuple[str, List[Dict]]:
    lines = [
        _header(
            "Outside-air dampers and their position points",
            "config/saturation_modalities.yaml declared the damper_position modality and no\n"
            "point of it existed, so every question about damper or economiser position was\n"
            "answered as 'not measured' by a building whose air handlers obviously have them.\n"
            "\n"
            "One OUTSIDE-AIR damper per air handling unit, which is the one an economiser\n"
            "modulates and the one a question about fresh air is usually about. A return-air\n"
            "damper is deliberately NOT invented alongside it: two dampers per unit implies a\n"
            "mixing arrangement this building has not told us it has.",
        ),
        f"@prefix bldg:     <{ns}> .\n",
    ]
    points: List[Dict] = []
    for ahu, ahu_label in ahus:
        damper = f"{ahu}_Outside_Air_Damper"
        sensor = f"{damper}_Position"
        uid = point_uuid(ns, sensor)
        floor_hint = ahu_label or ahu
        lines.append(
            f"{prefix}:{damper} a brick:Outside_Damper ;\n"
            f'    rdfs:label "{floor_hint} — outside air damper"@en ;\n'
            f"    brick:isPartOf {prefix}:{ahu} .\n"
        )
        lines.append(
            f"{prefix}:{sensor} a brick:Damper_Position_Sensor ;\n"
            f'    rdfs:label "{floor_hint} — outside air damper position" ;\n'
            f"    brick:isPointOf {prefix}:{damper} ;\n"
            f"    ontosage:isSimulated true ;\n"
            f"    ref:hasExternalReference [\n"
            f"        a ref:TimeseriesReference ;\n"
            f'        ref:hasTimeseriesId "{uid}" ;\n'
            f"        ref:storedAt {prefix}:plant_data\n"
            f"    ] .\n"
        )
        points.append({"point": sensor, "uuid": uid, "ahu": ahu, "table": "plant_data"})
    return "\n".join(lines), points


def build_waste_ttl(
    ns: str, prefix: str, rooms: Dict[str, Tuple[str, str]]
) -> Tuple[str, List[Dict]]:
    lines = [
        _header(
            "Waste and recycling bins, with fill level and weight",
            "waste_fill and waste_weight were declared by V6-T43 as 'the largest wholly-missing\n"
            "domain the category sweep found' and then never provisioned, so both resolved to\n"
            "zero points.\n"
            "\n"
            "Two streams per floor — general waste and mixed recycling — because the questions\n"
            "that need this ('how much did we divert from landfill?') cannot be answered from a\n"
            "single undifferentiated total. Each bin carries BOTH a fill level and a weight:\n"
            "fill answers 'does this need emptying now', weight answers 'how much did we throw\n"
            "away', and one cannot stand in for the other.\n"
            "\n"
            "The room on each floor is whichever of that floor's OWN rooms best matches a\n"
            "kitchen, break room, common area, atrium, reception, lobby or corridor.",
        ),
        f"@prefix bldg:     <{ns}> .\n",
    ]
    points: List[Dict] = []
    for floor, (room, room_label) in sorted(rooms.items()):
        for stream, stream_words in STREAMS:
            bin_name = f"{floor}_{stream}_Waste_Bin"
            place = room_label or room
            for kind, cls, table, unit in (
                ("Fill", "ontosage:Waste_Fill_Sensor", "wastefill_data", "percent full"),
                ("Weight", "ontosage:Waste_Weight_Sensor", "wasteweight_data", "kg"),
            ):
                sensor = f"{bin_name}_{kind}"
                uid = point_uuid(ns, sensor)
                lines.append(
                    f"{prefix}:{sensor} a {cls} ;\n"
                    f'    rdfs:label "{place} — {stream_words} bin {kind.lower()} ({unit})" ;\n'
                    f"    brick:hasLocation {prefix}:{room} ;\n"
                    f"    ontosage:isSimulated true ;\n"
                    f"    ref:hasExternalReference [\n"
                    f"        a ref:TimeseriesReference ;\n"
                    f'        ref:hasTimeseriesId "{uid}" ;\n'
                    f"        ref:storedAt {prefix}:{table}\n"
                    f"    ] .\n"
                )
                points.append(
                    {
                        "point": sensor,
                        "uuid": uid,
                        "bin": bin_name,
                        "stream": stream,
                        "role": kind.lower(),
                        "room": room,
                        "floor": floor,
                        "table": table,
                    }
                )
    return "\n".join(lines), points


def main(argv: Optional[List[str]] = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--endpoint", default=DEFAULT_ENDPOINT)
    ap.add_argument("--building-id", default=os.environ.get("BUILDING_ID", "bldg1"))
    ap.add_argument("--namespace", default="")
    ap.add_argument("--prefix", default="bldg")
    ap.add_argument("--input-dir", default=str(REPO / "input"))
    ap.add_argument("--dry-run", action="store_true")
    args = ap.parse_args(argv)

    ns = args.namespace
    if not ns:
        rows = sparql(
            "PREFIX rdf: <http://www.w3.org/1999/02/22-rdf-syntax-ns#>\n"
            "PREFIX brick: <https://brickschema.org/schema/Brick#>\n"
            "SELECT ?b WHERE { ?b rdf:type brick:Building } LIMIT 1",
            args.endpoint,
        )
        if not rows:
            raise SystemExit("no brick:Building in the graph — cannot infer the namespace")
        iri = rows[0]["b"]["value"]
        ns = iri[: iri.rindex("#") + 1] if "#" in iri else iri.rsplit("/", 1)[0] + "/"
    print(f"namespace: {ns}")

    verify_classes(
        args.endpoint,
        [
            "brick:Outside_Damper",
            "brick:Damper_Position_Sensor",
            "ontosage:Waste_Fill_Sensor",
            "ontosage:Waste_Weight_Sensor",
        ],
    )
    print("classes verified present in the loaded ontology")

    ahus = discover_ahus(args.endpoint)
    rooms = discover_bin_rooms(args.endpoint)
    print(f"air handling units: {len(ahus)}")
    for floor, (room, label) in sorted(rooms.items()):
        print(f"  bins on {floor:<8} -> {room} ({label})")

    damper_ttl, damper_points = build_damper_ttl(ns, args.prefix, ahus)
    waste_ttl, waste_points = build_waste_ttl(ns, args.prefix, rooms)
    print(f"damper points: {len(damper_points)}   waste points: {len(waste_points)}")

    if args.dry_run:
        print("--dry-run: nothing written")
        return 0

    out = Path(args.input_dir)
    for name, text in (
        (f"{args.building_id}_damper_points.ttl", damper_ttl),
        (f"{args.building_id}_waste_points.ttl", waste_ttl),
    ):
        path = out / name
        tmp = path.with_suffix(path.suffix + ".tmp")
        tmp.write_text(text, encoding="utf-8")
        os.replace(tmp, path)
        print(f"written: {path}")

    manifest = out / f"{args.building_id}_waste_publish_map.json"
    bins: Dict[str, Dict] = {}
    for p in waste_points:
        entry = bins.setdefault(
            p["bin"], {"bin": p["bin"], "stream": p["stream"], "room": p["room"], "roles": {}}
        )
        entry["roles"][p["role"]] = {"uuid": p["uuid"], "point": p["point"]}
    doc = {
        "fill_table": "wastefill_data",
        "weight_table": "wasteweight_data",
        # Capacity in kg at 100% full, by stream. General waste is denser than mixed dry
        # recycling, which is mostly air by volume -- so weight is NOT a fixed multiple of
        # fill across streams, and a single constant would make the recycling weight wrong.
        "capacity_kg": {"General": 55.0, "Recycling": 28.0},
        "bins": sorted(bins.values(), key=lambda b: b["bin"]),
    }
    tmp = manifest.with_suffix(manifest.suffix + ".tmp")
    tmp.write_text(json.dumps(doc, indent=2), encoding="utf-8")
    os.replace(tmp, manifest)
    print(f"written: {manifest}  ({len(doc['bins'])} bins)")

    print(
        "\nNEXT: create the two narrow tables, seed history, rebuild the plant map so the "
        "dampers join their AHU groups, then rebuild the publisher image."
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
