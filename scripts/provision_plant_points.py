# -*- coding: utf-8 -*-
"""Provision BMS/plant points onto the equipment that already serves spaces (V6-T26).

Master Package D's instruction is **integrate the BMS, don't duplicate it**: a supply-air
temperature the control system already reads must not be re-instrumented with a second IoT
sensor that then disagrees with the first. This script models that integration — it attaches
plant points to equipment the graph ALREADY declares, and never invents equipment.

Building-agnostic by construction:

* Equipment is **discovered from the graph** (anything typed AHU or VAV that `brick:feeds`
  something), never listed. A building with different plant gets different points from the
  same code, which is the litmus test in design contract #3.
* Modalities and their Brick classes come from `config/saturation_modalities.yaml` — the
  six entries carrying `scope: equipment`. Adding a seventh is a config edit.
* The namespace, building id and database key are resolved from the active building.

Two decisions worth keeping when this is re-read:

**Points go on EVERY feeder, not a hand-picked canonical one.** bldg1 carries three parallel
AHU naming schemes (`AHU_F5`, `AHU_Floor5`, `AHU-F5`) and twelve individuals for six physical
units. Selecting the "real" one would mean pattern-matching a building literal into
building-agnostic code — precisely the hardcoding the contract forbids. The duplication is a
defect in the DATA, and it is reported as one rather than silently resolved here.

**The series seed comes from the LABEL, not the IRI.** Two individuals describing one physical
AHU therefore produce the SAME series, so the duplication surfaces as redundancy rather than
as a fabricated disagreement between two readings of one duct. Seeding from the IRI would have
manufactured a conflict that does not physically exist.

Usage::

    python scripts/provision_plant_points.py --dry-run     # report, write nothing
    python scripts/provision_plant_points.py               # TTL + rows
    python scripts/provision_plant_points.py --days 30
"""

from __future__ import annotations

import argparse
import asyncio
import math
import os
import random
import re
import sys
import uuid
from collections import defaultdict
from datetime import datetime, timedelta
from pathlib import Path
from typing import Dict, List, Optional, Tuple

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from orchestrator.services.evidence.plant_state import plant_modalities  # noqa: E402
from orchestrator.services.ontology_manager import run_sparql_select  # noqa: E402
from shared.config import settings  # noqa: E402
from shared.db_clock import UTC_SESSION_INIT

_PREFIXES = (
    "PREFIX rdf:  <http://www.w3.org/1999/02/22-rdf-syntax-ns#>\n"
    "PREFIX rdfs: <http://www.w3.org/2000/01/rdf-schema#>\n"
    "PREFIX brick:<https://brickschema.org/schema/Brick#>\n"
)

#: modality -> (Brick class, unit, which equipment kinds carry it)
#:
#: A damper belongs to the terminal unit, a filter and a supply fan to the air handler. Putting
#: every modality on every equipment kind would produce points no real building has, and the
#: coverage matrix would then report a saturation this estate does not possess.
PLACEMENT: Dict[str, Tuple[str, str, Tuple[str, ...]]] = {
    "supply_air_temperature": ("Supply_Air_Temperature_Sensor", "degC", ("AHU",)),
    "return_air_temperature": ("Return_Air_Temperature_Sensor", "degC", ("AHU",)),
    "fan_state": ("Fan_Status", "binary", ("AHU",)),
    "filter_differential_pressure": ("Filter_Differential_Pressure_Sensor", "Pa", ("AHU",)),
    "supply_air_flow": ("Air_Flow_Sensor", "L/s", ("AHU", "VAV")),
    "damper_position": ("Damper_Position_Sensor", "percent", ("VAV",)),
}

#: The unit as a QUDT IRI. This building declares units with `qudt:hasUnit` and a QUDT IRI
#: (875 triples) -- `brick:hasUnit` with a bare string was a THIRD convention invented here, and
#: it cost a real wrong answer: the filter differential pressure came back as "about 152.5 psi"
#: when the point is in Pascals. psi and Pa differ by a factor of 6,895, and the model invented
#: the unit only because the one in the graph was in a shape nothing downstream reads. Same
#: mistake as writing brick:isPartOf where the pipeline walks brick:hasLocation: a triple that
#: is present, correct, and invisible.
QUDT: Dict[str, str] = {
    "degC": "http://qudt.org/vocab/unit/DEG_C",
    "Pa": "http://qudt.org/vocab/unit/PA",
    "L/s": "http://qudt.org/vocab/unit/L-PER-SEC",
    "percent": "http://qudt.org/vocab/unit/PERCENT",
    "binary": "http://qudt.org/vocab/unit/UNITLESS",
}

_CAMEL = {
    "supply_air_temperature": "Supply_Air_Temperature",
    "return_air_temperature": "Return_Air_Temperature",
    "fan_state": "Fan_Status",
    "filter_differential_pressure": "Filter_DP",
    "supply_air_flow": "Supply_Air_Flow",
    "damper_position": "Damper_Position",
}


def stable_uuid(iri: str) -> str:
    """Deterministic from the point IRI, matching scripts/link_unlinked_sensors.py."""
    return str(uuid.uuid5(uuid.NAMESPACE_URL, iri))


def normalized_unit(label: str, iri: str) -> str:
    """A key identifying the PHYSICAL unit, so duplicate individuals share a series.

    `AHU_F5`, `AHU_Floor5` and `Air Handling Unit — Floor 5` all reduce to `ahu5`. This is
    used ONLY to seed the generator — never to merge anything in the graph, which would be
    the proximity-inference mistake in a different costume.
    """
    text = (label or iri.rsplit("#", 1)[-1]).lower()
    text = re.sub(r"[^a-z0-9]+", "", text)
    text = text.replace("airhandlingunit", "ahu").replace("variableairvolume", "vav")
    text = text.replace("floor", "").replace("f", "", 1) if text.startswith("ahu") else text
    return text


def local(iri: str) -> str:
    return str(iri).rsplit("#", 1)[-1].rsplit("/", 1)[-1]


async def discover_equipment(namespace: str) -> List[Dict[str, str]]:
    """Every AHU/VAV that feeds something, with its label and kind."""
    # The floor comes back with the equipment so each POINT can carry it too. Without that the
    # points are reachable only through their equipment, and the pipeline's floor-scoped
    # template -- the one that answers "on floor 5" for every ordinary room sensor -- returns
    # zero rows for plant. Measured: the right points were resolved and then discarded by a
    # template that could not locate them.
    q = (
        _PREFIXES + "SELECT DISTINCT ?e ?label ?kind ?floor WHERE {\n"
        "  { ?e a brick:AHU BIND('AHU' AS ?kind) } UNION { ?e a brick:VAV BIND('VAV' AS ?kind) }\n"
        "  ?e brick:feeds ?t .\n"
        "  OPTIONAL { ?e rdfs:label ?label }\n"
        "  OPTIONAL { { ?e brick:isPartOf ?floor } UNION { ?e brick:hasLocation ?floor }\n"
        "             ?floor a brick:Floor }\n"
        f'  FILTER(STRSTARTS(STR(?e), "{namespace}"))\n'
        "}"
    )
    res = await run_sparql_select(q, limit=2000)
    if not res.get("ok"):
        raise SystemExit(f"equipment discovery failed: {res.get('error')}")
    out = []
    for row in res.get("rows") or []:
        out.append(
            {
                "iri": str(row.get("e")),
                "label": str(row.get("label") or ""),
                "kind": str(row.get("kind") or ""),
                "floor": str(row.get("floor") or ""),
            }
        )
    return sorted(out, key=lambda r: r["iri"])


def series(modality: str, seed_key: str, start: datetime, days: int, step_min: int):
    """A plausible plant series. Deterministic in (modality, physical unit)."""
    rnd = random.Random(f"{modality}|{seed_key}")
    n = int(days * 24 * 60 / step_min)
    out: List[Tuple[datetime, float]] = []
    drift_start = rnd.uniform(40, 70)
    for i in range(n):
        ts = start + timedelta(minutes=i * step_min)
        hour = ts.hour + ts.minute / 60.0
        occupied = ts.weekday() < 5 and 7.0 <= hour < 19.0
        if modality == "fan_state":
            v = 1.0 if occupied else 0.0
        elif modality == "supply_air_temperature":
            v = (
                round(rnd.gauss(15.5, 0.6), 2) if occupied else round(rnd.gauss(20.5, 0.8), 2)
            )  # off-hours the duct drifts to room temperature
        elif modality == "return_air_temperature":
            v = round(rnd.gauss(22.5, 0.7) + (1.2 if occupied else 0.0), 2)
        elif modality == "filter_differential_pressure":
            # monotonic loading over the window: this is the point of a filter dP series --
            # it is how "the filter needs changing" becomes answerable at all.
            v = round(drift_start + (i / max(n - 1, 1)) * 110 + rnd.gauss(0, 2.0), 1)
        elif modality == "supply_air_flow":
            base = 900 if occupied else 120
            v = round(base * (1 + 0.12 * math.sin(i / 9.0)) + rnd.gauss(0, 25), 1)
        elif modality == "damper_position":
            base = 55 if occupied else 8
            v = round(min(100.0, max(0.0, base + 18 * math.sin(i / 11.0) + rnd.gauss(0, 4))), 1)
        else:
            v = round(rnd.gauss(0, 1), 3)
        out.append((ts, v))
    return out


def build_ttl(namespace: str, points: List[Dict], db_key: str) -> str:
    """TTL for the plant points. Same shape as every other connected point."""
    ns = namespace if namespace.endswith("#") else namespace + "#"
    lines = [
        "# BMS / plant telemetry points (V6-T26).",
        "#",
        "# GENERATED by scripts/provision_plant_points.py from equipment ALREADY in the graph.",
        "# Nothing here invents plant: every point hangs off an AHU or VAV that already",
        "# brick:feeds a zone or space. Master Package D asks for the BMS to be integrated",
        "# rather than duplicated, so these are declared as ordinary Brick points and routed",
        "# by ref:storedAt like any other series -- no new adapter, no new query path.",
        "",
        f"@prefix bldg: <{ns}> .",
        "@prefix rdf:  <http://www.w3.org/1999/02/22-rdf-syntax-ns#> .",
        "@prefix rdfs: <http://www.w3.org/2000/01/rdf-schema#> .",
        "@prefix brick:<https://brickschema.org/schema/Brick#> .",
        "@prefix ref:  <https://brickschema.org/schema/Brick/ref#> .",
        "@prefix xsd:  <http://www.w3.org/2001/XMLSchema#> .",
        "@prefix ontosage: <http://ontosage.org/capabilities#> .",
        "@prefix qudt: <http://qudt.org/schema/qudt/> .",
        "",
    ]
    for p in points:
        pl = local(p["iri"])
        lines += [
            f"bldg:{pl} a brick:{p['brick_class']} ;",
            f'    rdfs:label "{p["label"]}" ;',
            f"    brick:isPointOf bldg:{local(p['equipment'])} ;",
        ]
        if p.get("floor"):
            # brick:hasLocation is THE relation this pipeline's floor-scoped template walks
            # (`?sensor brick:hasLocation ?loc . ?loc (brick:isPartOf|^brick:hasPart)* ?floor`),
            # and it is what every ordinary sensor in this building already uses. Emitting
            # brick:isPartOf instead -- the first attempt -- was a SECOND convention for the
            # same fact: the triple was present, read correctly by anything looking for it, and
            # invisible to the query that actually answers "on floor 5". The point resolved and
            # was then dropped by a template that could not locate it.
            lines.append(f"    brick:hasLocation bldg:{local(p['floor'])} ;")
        lines += [
            f'    brick:hasUnit "{p["unit"]}" ;',
            # These readings are GENERATED. Every other synthetic sensor in this building
            # declares it, and the first version of this file did not — so a conformance check
            # for "no provisioned record lacks isSimulated" would have failed on exactly the
            # points added to demonstrate honest sourcing. The registry marking the STORE
            # synthetic is not a substitute: an answer cites the point, not the table.
            '    ontosage:isSimulated "true"^^xsd:boolean ;',
            f"    qudt:hasUnit <{QUDT.get(p['unit'], '')}> ;" if QUDT.get(p["unit"]) else "",
            "    ref:hasExternalReference [",
            "        a ref:TimeseriesReference ;",
            f'        ref:hasTimeseriesId "{p["uuid"]}" ;',
            f"        ref:storedAt bldg:{db_key}",
            "    ] .",
            "",
        ]
    return "\n".join(lines)


def duplicate_report(equipment: List[Dict]) -> str:
    """Equipment individuals that look like one physical unit recorded more than once.

    REPORTED, never merged. Two individuals sharing a normalised name are *probably* one
    air handler, and probably is not a basis for deleting a triple or for telling somebody
    their building has six AHUs when the graph says twelve.
    """
    groups: Dict[str, List[str]] = defaultdict(list)
    for e in equipment:
        groups[normalized_unit(e["label"], e["iri"])].append(local(e["iri"]))
    dupes = {k: sorted(v) for k, v in groups.items() if len(v) > 1}
    if not dupes:
        return ""
    lines = ["", "DUPLICATE EQUIPMENT IDENTITIES (reported, not merged):"]
    for k, v in sorted(dupes.items()):
        lines.append(f"  {k:<12} -> {', '.join(v)}")
    lines.append(
        "  These are separate individuals in the graph. Any answer naming the equipment that\n"
        "  serves a space will list all of them, because that is what the graph asserts. Fix\n"
        "  the TTL to resolve it -- this script will not guess which one is real."
    )
    return "\n".join(lines)


async def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--days", type=int, default=14)
    ap.add_argument("--step-min", type=int, default=15)
    ap.add_argument("--dry-run", action="store_true")
    ap.add_argument("--db-key", default="plant_data")
    args = ap.parse_args()

    building = settings.BUILDING_ID
    namespace = settings.BUILDING_NAMESPACE
    modalities = set(plant_modalities(building))
    if not modalities:
        raise SystemExit(
            "no equipment-scoped modalities in config/saturation_modalities.yaml -- nothing to "
            "provision. This is the failure mode where an empty result looks like success."
        )

    equipment = await discover_equipment(namespace)
    print(f"building={building} namespace={namespace}")
    print(f"equipment discovered: {len(equipment)}")
    print(f"equipment-scoped modalities: {sorted(modalities)}")

    points: List[Dict] = []
    for e in equipment:
        for mod in sorted(modalities):
            if mod not in PLACEMENT:
                print(f"  ! {mod} has no placement rule; skipped (add one to PLACEMENT)")
                continue
            brick_class, unit, kinds = PLACEMENT[mod]
            if e["kind"] not in kinds:
                continue
            iri = f"{namespace.rstrip('#')}#{local(e['iri'])}_{_CAMEL[mod]}"
            points.append(
                {
                    "iri": iri,
                    "equipment": e["iri"],
                    "brick_class": brick_class,
                    "unit": unit,
                    "modality": mod,
                    "label": f"{e['label'] or local(e['iri'])} {mod.replace('_', ' ')}",
                    "uuid": stable_uuid(iri),
                    "seed": normalized_unit(e["label"], e["iri"]),
                    "floor": e.get("floor", ""),
                }
            )

    by_mod: Dict[str, int] = defaultdict(int)
    for p in points:
        by_mod[p["modality"]] += 1
    print(f"points to provision: {len(points)}")
    for m, c in sorted(by_mod.items()):
        print(f"   {m:<32} {c}")
    print(duplicate_report(equipment))

    ttl = build_ttl(namespace, points, args.db_key)
    out = Path("input") / f"{building}_plant_points.ttl"
    rows = args.days * 24 * 60 // args.step_min * len(points)
    if args.dry_run:
        print(f"\nDRY RUN — would write {out} ({len(points)} points) and ~{rows:,} rows")
        return 0

    out.write_text(ttl, encoding="utf-8")
    print(f"\nwrote {out} ({len(ttl.splitlines())} lines)")

    import pymysql

    conn = pymysql.connect(
        host=os.getenv("MYSQL_HOST", "host.docker.internal"),
        port=int(os.getenv("MYSQL_PORT", "3306")),
        user=os.getenv("MYSQL_USER", "root"),
        password=os.getenv("MYSQL_PASSWORD", "mysql"),
        database=os.getenv("MYSQL_DATABASE", "sensordb"),
        # Same clock the rows are stamped in (BUG-403).
        init_command=UTC_SESSION_INIT,
    )
    start = datetime.utcnow().replace(second=0, microsecond=0) - timedelta(days=args.days)
    written = 0
    with conn.cursor() as cur:
        cur.execute(
            "CREATE TABLE IF NOT EXISTS plant_data ("
            "uuid CHAR(36) NOT NULL, datetime DATETIME NOT NULL, value DOUBLE,"
            "PRIMARY KEY (uuid, datetime), INDEX idx_plant_uuid (uuid),"
            "INDEX idx_plant_datetime (datetime)) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4"
        )
        for p in points:
            batch = [
                (p["uuid"], ts, v)
                for ts, v in series(p["modality"], p["seed"], start, args.days, args.step_min)
            ]
            cur.executemany(
                "INSERT IGNORE INTO plant_data (uuid, datetime, value) VALUES (%s,%s,%s)", batch
            )
            written += len(batch)
    conn.commit()
    conn.close()
    print(f"inserted {written:,} rows into plant_data")
    print("\nNEXT: restart the orchestrator so ttl_uploader ingests the new TTL.")
    return 0


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
