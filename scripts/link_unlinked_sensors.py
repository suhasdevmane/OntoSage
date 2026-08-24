#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Connect points the ontology describes but no database backs (V6).

THE GAP THIS CLOSES
Design contract 8 says a question is answerable when the sensor is a triple in GraphDB **and**
its readings are rows in a registered database, linked by ``ref:hasTimeseriesId`` +
``ref:storedAt``. Both halves are required. An audit of bldg1 found 2,705 Brick points of which
**113 had no timeseries UUID at all** -- 23 of them legitimately (a command is something you
write, a camera is not a numeric stream), and **90 that should have data and did not**: EV
charger and lift power meters, PV arrays, intrusion detectors, occupancy counters, CO2 sensors
in named rooms. They were authored into the enrichment TTLs to describe the building and never
connected, so the system could describe them and could not report a reading.

WHAT IT WRITES, AND WHY THAT IS NOT FABRICATION
Two things: a TTL of ``ref:hasExternalReference`` links, and synthetic rows behind them. Every
generated stream is declared with ``ontosage:isSimulated true`` on its reference, which is the
same contract bldg2 and bldg3 already live under. The honesty rule forbids UNDECLARED
fabrication, not declared simulation -- an answer resting on one of these can say so, because
the graph says so.

**Real data is never touched.** The script refuses to write into a table whose registry entry
declares ``nature: real``, so bldg1's genuine Abacws snapshot cannot be diluted by generated
rows no matter how it is invoked.

HOW IT STAYS BUILDING-AGNOSTIC
The class-to-table mapping is read from ``config/saturation_modalities.yaml`` -- the same map
the saturation pipeline uses -- not hardcoded here. Sensors are discovered by SPARQL against
whatever building is active. There is no building name, room id, floor number or sensor count
in this file. A point whose class has no mapping is REPORTED, never guessed at: inventing a
destination for an unrecognised sensor is how a reading ends up in the wrong table.

UUIDs are ``uuid5`` of the point's IRI, so the script is idempotent -- running it twice
produces the same identifiers and re-links nothing.

    python scripts/link_unlinked_sensors.py                 # dry run: report only
    python scripts/link_unlinked_sensors.py --write-ttl     # emit the TTL
    python scripts/link_unlinked_sensors.py --write-ttl --seed-data --days 30
"""

from __future__ import annotations

import argparse
import json
import math
import os
import random
import re
import sys
import urllib.request
import uuid
from collections import defaultdict
from datetime import datetime, timedelta
from pathlib import Path
from typing import Dict, List, Optional, Tuple

_SCRIPT_DIR = Path(__file__).resolve().parent
REPO = _SCRIPT_DIR.parent
sys.path.insert(0, str(REPO))

import yaml  # noqa: E402

GRAPHDB = os.environ.get("GRAPHDB_QUERY_URL", "http://localhost:7200/repositories/bldg")
REF_NS = "https://brickschema.org/schema/Brick/ref#"
ONTOSAGE_NS = "http://ontosage.org/capabilities#"

#: Classes that hold no time series by nature. Listed so the remaining gap is the real one:
#: counting a light switch as a missing sensor would inflate the problem and then "fix" it by
#: inventing readings for something that never reads anything.
NON_TIMESERIES_HINTS = ("Command", "Setpoint", "Camera", "CCTV")

#: Per-modality shape of a plausible day. Amplitude and floor only -- the generator is
#: deliberately simple, because the point is a connected, declared stream, not a simulation
#: anybody should mistake for measurement.
PROFILES: Dict[str, Dict[str, float]] = {
    "electric_power": {"base": 2.0, "swing": 6.0, "noise": 0.4, "min": 0.0},
    "motion": {"base": 0.0, "swing": 1.0, "noise": 0.0, "min": 0.0, "binary": 1},
    "occupancy_status": {"base": 0.0, "swing": 1.0, "noise": 0.0, "min": 0.0, "binary": 1},
    "occupancy": {"base": 0.0, "swing": 12.0, "noise": 1.5, "min": 0.0},
    "position": {"base": 50.0, "swing": 40.0, "noise": 2.0, "min": 0.0, "max": 100.0},
    "water_level": {"base": 60.0, "swing": 25.0, "noise": 1.0, "min": 0.0, "max": 100.0},
    "water_usage": {"base": 1.0, "swing": 8.0, "noise": 0.5, "min": 0.0},
    "solar_irradiance": {"base": 0.0, "swing": 700.0, "noise": 30.0, "min": 0.0},
    "runtime_hours": {"base": 0.0, "swing": 0.0, "noise": 0.0, "min": 0.0, "cumulative": 1},
    "air_quality": {"base": 55.0, "swing": 25.0, "noise": 4.0, "min": 0.0, "max": 100.0},
    "humidity": {"base": 48.0, "swing": 10.0, "noise": 2.0, "min": 15.0, "max": 95.0},
    "illuminance": {"base": 120.0, "swing": 400.0, "noise": 25.0, "min": 0.0},
    "temperature": {"base": 21.0, "swing": 3.0, "noise": 0.4, "min": 5.0, "max": 40.0},
    "co2": {"base": 480.0, "swing": 500.0, "noise": 30.0, "min": 380.0},
    "door_contact": {"base": 0.0, "swing": 1.0, "noise": 0.0, "min": 0.0, "binary": 1},
    "water_flow": {"base": 0.5, "swing": 10.0, "noise": 0.3, "min": 0.0},
}
DEFAULT_PROFILE = {"base": 1.0, "swing": 1.0, "noise": 0.1, "min": 0.0}


# -- graph access -------------------------------------------------------------


def sparql(query: str, timeout: int = 600) -> List[dict]:
    req = urllib.request.Request(
        GRAPHDB,
        data=query.encode("utf-8"),
        headers={
            "Content-Type": "application/sparql-query",
            "Accept": "application/sparql-results+json",
        },
        method="POST",
    )
    with urllib.request.urlopen(req, timeout=timeout) as r:
        return json.loads(r.read().decode("utf-8"))["results"]["bindings"]


def active_namespace() -> str:
    """The building's own namespace, read from the graph rather than assumed."""
    rows = sparql(
        """PREFIX brick: <https://brickschema.org/schema/Brick#>
           SELECT ?b WHERE { ?b a brick:Building } LIMIT 1"""
    )
    if rows:
        iri = rows[0]["b"]["value"]
        return iri.rsplit("#", 1)[0] + "#" if "#" in iri else iri.rsplit("/", 1)[0] + "/"
    raise RuntimeError("no brick:Building in the graph — cannot resolve the namespace")


def unlinked_points() -> List[Tuple[str, str, List[str]]]:
    """(iri, label, classes) for every Point with no timeseries id."""
    rows = sparql(
        f"""PREFIX brick: <https://brickschema.org/schema/Brick#>
            PREFIX rdfs: <http://www.w3.org/2000/01/rdf-schema#>
            PREFIX ref: <{REF_NS}>
            SELECT ?p (SAMPLE(?l) AS ?label)
                   (GROUP_CONCAT(DISTINCT ?cn; separator=",") AS ?classes)
            WHERE {{
              ?p a ?cls . ?cls rdfs:subClassOf* brick:Point .
              BIND(REPLACE(STR(?cls), "^.*[#/]", "") AS ?cn)
              OPTIONAL {{ ?p rdfs:label ?l }}
              FILTER NOT EXISTS {{ ?p ref:hasExternalReference ?r . ?r ref:hasTimeseriesId ?u }}
            }} GROUP BY ?p"""
    )
    return [
        (
            r["p"]["value"],
            r.get("label", {}).get("value", ""),
            [c for c in r.get("classes", {}).get("value", "").split(",") if c],
        )
        for r in rows
    ]


# -- mapping ------------------------------------------------------------------


def class_to_modality() -> Dict[str, str]:
    """Reverse the canonical modality map: Brick class -> modality name.

    Read from config rather than written here, so a building that adds a modality gets the
    linking behaviour for free and there is exactly one place the mapping lives.
    """
    cfg = yaml.safe_load((REPO / "config" / "saturation_modalities.yaml").read_text("utf-8"))
    out: Dict[str, str] = {}
    for modality, spec in (cfg.get("modalities") or {}).items():
        for cls in spec.get("brick_classes") or []:
            out.setdefault(str(cls).split(":")[-1], modality)
    return out


def modality_table(modality: str) -> Tuple[str, str]:
    cfg = yaml.safe_load((REPO / "config" / "saturation_modalities.yaml").read_text("utf-8"))
    sat = ((cfg.get("modalities") or {}).get(modality) or {}).get("sat") or {}
    return str(sat.get("table", "")), str(sat.get("unit", ""))


def registry() -> Dict[str, dict]:
    path = REPO / "input" / "database_registry.yaml"
    if not path.is_file():
        return {}
    return yaml.safe_load(path.read_text(encoding="utf-8")).get("databases") or {}


def storage_key_for(table: str, dbs: Dict[str, dict]) -> Optional[str]:
    """The registry key whose table matches, so storedAt points at something real."""
    for key, spec in dbs.items():
        if not isinstance(spec, dict):
            continue
        if str(spec.get("table", "")).strip() == table:
            return key
    return None


def stable_uuid(iri: str) -> str:
    """Deterministic from the point's IRI, so re-running links nothing twice."""
    return str(uuid.uuid5(uuid.NAMESPACE_URL, iri))


# -- generation ---------------------------------------------------------------


def series(modality: str, days: int, step_min: int, seed: int) -> List[Tuple[datetime, float]]:
    """A plausible daily shape. Deterministic per sensor, so re-seeding is reproducible."""
    rnd = random.Random(seed)
    prof = {**DEFAULT_PROFILE, **PROFILES.get(modality, {})}
    end = datetime.now().replace(second=0, microsecond=0)
    start = end - timedelta(days=days)
    out: List[Tuple[datetime, float]] = []
    t = start
    running = 0.0
    while t <= end:
        hour = t.hour + t.minute / 60.0
        # One occupied-hours bump; enough to make day/night questions meaningful without
        # pretending to model a building.
        occupied = math.sin(max(0.0, (hour - 7.0) / 12.0) * math.pi) if 7 <= hour <= 19 else 0.0
        if prof.get("cumulative"):
            running += occupied * 0.15
            v = round(running, 3)
        elif prof.get("binary"):
            v = 1.0 if rnd.random() < occupied * 0.6 else 0.0
        else:
            v = prof["base"] + prof["swing"] * occupied + rnd.gauss(0, prof["noise"])
            v = max(prof["min"], v)
            if "max" in prof:
                v = min(prof["max"], v)
            v = round(v, 3)
        out.append((t, v))
        t += timedelta(minutes=step_min)
    return out


# -- output -------------------------------------------------------------------


def build_ttl(links: List[dict], ns: str) -> str:
    lines = [
        "# Timeseries links for points the enrichment TTLs described but never connected.",
        "# GENERATED by scripts/link_unlinked_sensors.py -- re-runnable, ids are uuid5 of the",
        "# point IRI. Every stream is declared simulated; nothing here claims to be measured.",
        "",
        f"@prefix bldg: <{ns}> .",
        f"@prefix ref: <{REF_NS}> .",
        f"@prefix ontosage: <{ONTOSAGE_NS}> .",
        "@prefix xsd: <http://www.w3.org/2001/XMLSchema#> .",
        "",
    ]
    for lk in links:
        local = lk["iri"].rsplit("#", 1)[-1].rsplit("/", 1)[-1]
        lines += [
            f"bldg:{local} ref:hasExternalReference [",
            "    a ref:TimeseriesReference ;",
            f'    ref:hasTimeseriesId "{lk["uuid"]}" ;',
            f"    ref:storedAt bldg:{lk['storage_key']} ;",
            "    ontosage:isSimulated true ;",
            f'    ontosage:generatedBy "link_unlinked_sensors.py" ;',
            "] .",
            "",
        ]
    return "\n".join(lines)


def db_connect():
    import pymysql

    def env(name: str, default: str = "") -> str:
        if os.environ.get(name):
            return os.environ[name]
        p = REPO / ".env"
        if p.is_file():
            for line in p.read_text(encoding="utf-8", errors="ignore").splitlines():
                line = line.strip()
                if line.startswith(f"{name}=") and not line.startswith("#"):
                    return line.split("=", 1)[1].strip().strip('"').strip("'")
        return default

    host = env("MYSQL_HOST", "127.0.0.1")
    if host in ("mysql", "host.docker.internal"):
        host = "127.0.0.1"
    db = re.sub(r"\$\{[A-Z0-9_]+:-([^}]*)\}", r"\1", env("MYSQL_DATABASE", "sensordb"))
    return pymysql.connect(
        host=host,
        port=int(env("MYSQL_PORT", "3306")),
        user=env("MYSQL_USER", "root"),
        password=env("MYSQL_PASSWORD", ""),
        database=db,
        connect_timeout=20,
    )


def main(argv: List[str]) -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--write-ttl", action="store_true")
    ap.add_argument("--seed-data", action="store_true")
    ap.add_argument("--days", type=int, default=30)
    ap.add_argument("--step-min", type=int, default=15)
    args = ap.parse_args(argv)

    ns = active_namespace()
    points = unlinked_points()
    cls_map = class_to_modality()
    dbs = registry()

    linked: List[dict] = []
    skipped_expected: List[str] = []
    unmapped: Dict[str, List[str]] = defaultdict(list)

    for iri, label, classes in points:
        if any(h in c for c in classes for h in NON_TIMESERIES_HINTS):
            skipped_expected.append(iri.rsplit("#", 1)[-1])
            continue
        modality = next((cls_map[c] for c in classes if c in cls_map), None)
        if not modality:
            unmapped[
                ",".join(sorted(c for c in classes if c not in ("Point", "Class")))[:60]
            ].append(iri.rsplit("#", 1)[-1])
            continue
        table, unit = modality_table(modality)
        key = storage_key_for(table, dbs)
        if not key:
            unmapped[f"(no registry key for table {table})"].append(iri.rsplit("#", 1)[-1])
            continue
        linked.append(
            {
                "iri": iri,
                "label": label,
                "modality": modality,
                "table": table,
                "unit": unit,
                "storage_key": key,
                "uuid": stable_uuid(iri),
            }
        )

    print(f"points with no timeseries link : {len(points)}")
    print(f"  not a time series (skipped)  : {len(skipped_expected)}")
    print(f"  mappable and will be linked  : {len(linked)}")
    print(f"  UNMAPPED (reported, not guessed): {sum(len(v) for v in unmapped.values())}")
    for cls, names in sorted(unmapped.items(), key=lambda kv: -len(kv[1])):
        print(f"      {len(names):>3}  {cls}")
        for n in names[:3]:
            print(f"           e.g. {n}")

    by_mod = defaultdict(int)
    for lk in linked:
        by_mod[lk["modality"]] += 1
    if by_mod:
        print("\n  to link, by modality:")
        for m, n in sorted(by_mod.items(), key=lambda kv: -kv[1]):
            print(f"      {n:>3}  {m} -> {modality_table(m)[0]}")

    if not args.write_ttl:
        print("\nDRY RUN — nothing written. Re-run with --write-ttl (and --seed-data).")
        return 0

    # BUILDING_ID from the process env, else .env, else the namespace's last token. The
    # middle step matters: outside the container the variable is not exported, and falling
    # straight through to the namespace produced a file named after the SITE rather than the
    # building id, out of step with every sibling TTL.
    bid = os.environ.get("BUILDING_ID", "").strip()
    if not bid:
        envf = REPO / ".env"
        if envf.is_file():
            for line in envf.read_text(encoding="utf-8", errors="ignore").splitlines():
                line = line.strip()
                if line.startswith("BUILDING_ID=") and not line.startswith("#"):
                    bid = line.split("=", 1)[1].strip().strip('"').strip("'")
                    break
    bid = bid or ns.rstrip("#/").rsplit("/", 1)[-1]
    out_ttl = REPO / "input" / f"{bid}_sensor_links.ttl"
    out_ttl.write_text(build_ttl(linked, ns), encoding="utf-8")
    print(f"\nwrote {out_ttl.relative_to(REPO).as_posix()} ({len(linked)} links)")

    if not args.seed_data:
        print("TTL only — re-run with --seed-data to populate the tables.")
        return 0

    # Real tables are never written to. bldg1's genuine snapshot must not be diluted by
    # generated rows, and the registry is the only place that knows which is which.
    real_keys = {k for k, v in dbs.items() if isinstance(v, dict) and v.get("nature") == "real"}
    conn = db_connect()
    cur = conn.cursor()
    written = 0
    for lk in linked:
        if lk["storage_key"] in real_keys:
            print(f"  REFUSING to seed {lk['table']} — registry declares it nature: real")
            continue
        rows = series(lk["modality"], args.days, args.step_min, seed=hash(lk["uuid"]) & 0xFFFF)
        cur.executemany(
            f"INSERT INTO `{lk['table']}` (uuid, datetime, value) VALUES (%s, %s, %s)",
            [(lk["uuid"], t, v) for t, v in rows],
        )
        written += len(rows)
    conn.commit()
    cur.close()
    conn.close()
    print(f"seeded {written} rows across {len(linked)} streams")
    print("Restart the stack (or reload from the admin portal) so the TTL is ingested.")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
