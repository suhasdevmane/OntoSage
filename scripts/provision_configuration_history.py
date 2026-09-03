# -*- coding: utf-8 -*-
"""Declare when each point's current configuration took effect (V6-T07).

Acceptance scenario 3 needs the graph to model sensor location as an INTERVAL rather than a
current value, so a reading from March is interpreted against the room the sensor was in during
March. `orchestrator/services/evidence/history.py` has done that arithmetic since 2026-08-21 and
had nothing to read: no building declared a single `ontosage:ConfigurationPeriod`.

**The effective date is measured, never invented.** A commissioning date nobody recorded cannot
be recovered, and writing a plausible one would defeat the entire point — a fabricated boundary
misattributes readings exactly the way a missing one does, while looking authoritative. What IS
knowable is the **earliest observation in the store**, so that is what this writes, with
`ontosage:changeKind "first_observed"` saying so in the data.

The consequence is deliberate and correct: `location_as_of` returns **None** for any instant
before a point's first reading. "We do not know where it was" and "it was where it is now" are
different claims, and only the first one is true.

Where a real relocation IS known, an operator adds a period with `changeKind "relocation"` and a
proper `effectiveFrom`; this script never overwrites a period it did not write, which is what
`ontosage:periodSource` marks.

Usage::

    python scripts/provision_configuration_history.py --dry-run
    python scripts/provision_configuration_history.py
"""

from __future__ import annotations

import argparse
import asyncio
import os
import sys
from collections import defaultdict
from datetime import datetime
from pathlib import Path
from typing import Dict, List, Optional, Tuple

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from orchestrator.services.ontology_manager import run_sparql_select  # noqa: E402
from shared.config import settings  # noqa: E402
from shared.db_clock import UTC_SESSION_INIT

ONTOSAGE = "http://ontosage.org/capabilities#"

_PREFIXES = (
    "PREFIX rdfs: <http://www.w3.org/2000/01/rdf-schema#>\n"
    "PREFIX brick:<https://brickschema.org/schema/Brick#>\n"
    "PREFIX ref:  <https://brickschema.org/schema/Brick/ref#>\n"
    f"PREFIX ontosage: <{ONTOSAGE}>\n"
)


def local(iri: str) -> str:
    return str(iri).rsplit("#", 1)[-1].rsplit("/", 1)[-1]


async def connected_points(namespace: str) -> List[Dict]:
    """Points that have BOTH a location and a timeseries reference.

    Both halves are required: a period on a point with no location says nothing, and a period
    on a point with no readings can never be matched to an answer.
    """
    query = (
        _PREFIXES + "SELECT DISTINCT ?p ?uuid ?store ?loc WHERE {\n"
        "  ?p ref:hasExternalReference ?r .\n"
        "  ?r ref:hasTimeseriesId ?uuid .\n"
        "  OPTIONAL { ?r ref:storedAt ?store }\n"
        "  { ?p brick:hasLocation ?loc } UNION { ?p brick:isPartOf ?loc }\n"
        "  ?loc a ?lcls . ?lcls rdfs:subClassOf* brick:Location .\n"
        "  FILTER NOT EXISTS { ?existing ontosage:configurationOf ?p }\n"
        f'  FILTER(STRSTARTS(STR(?p), "{namespace}"))\n'
        "}"
    )
    res = await run_sparql_select(query, limit=20000)
    if not res.get("ok"):
        raise SystemExit(f"point discovery failed: {res.get('error')}")
    out: Dict[str, Dict] = {}
    for row in res.get("rows") or []:
        iri = str(row.get("p") or "")
        if not iri:
            continue
        cur = out.setdefault(iri, {"iri": iri, "uuid": "", "store": "", "loc": ""})
        cur["uuid"] = cur["uuid"] or str(row.get("uuid") or "")
        cur["store"] = cur["store"] or local(str(row.get("store") or ""))
        # Keep the FIRST location seen and never merge two. A point the graph places in two
        # rooms is a data defect; silently choosing one would hide it behind a confident period.
        cur["loc"] = cur["loc"] or str(row.get("loc") or "")
    return sorted(out.values(), key=lambda d: d["iri"])


def earliest_observations(points: List[Dict]) -> Dict[str, datetime]:
    """{uuid: earliest datetime} — one grouped query per store, never one per sensor.

    A per-sensor MIN() over a few thousand points would take longer than the rest of this
    script put together, and the wide store cannot be queried that way at all.
    """
    import pymysql

    by_store: Dict[str, List[str]] = defaultdict(list)
    for p in points:
        if p["uuid"] and p["store"]:
            by_store[p["store"]].append(p["uuid"])

    conn = pymysql.connect(
        host=os.getenv("MYSQL_HOST", "host.docker.internal"),
        port=int(os.getenv("MYSQL_PORT", "3306")),
        user=os.getenv("MYSQL_USER"),
        password=os.getenv("MYSQL_PASSWORD"),
        database=os.getenv("MYSQL_DATABASE", "sensordb"),
        # Same clock the rows are stamped in (BUG-403).
        init_command=UTC_SESSION_INIT,
    )
    found: Dict[str, datetime] = {}
    try:
        with conn.cursor() as cur:
            cur.execute("SHOW TABLES")
            tables = {r[0] for r in cur.fetchall()}
            for store, uuids in sorted(by_store.items()):
                if store in tables:
                    # Narrow shape: one grouped MIN over the uuid column.
                    marks = ",".join(f"'{u}'" for u in uuids)
                    try:
                        cur.execute(
                            f"SELECT uuid, MIN(datetime) FROM `{store}` "
                            f"WHERE uuid IN ({marks}) GROUP BY uuid"
                        )
                        for uuid, first in cur.fetchall():
                            if first:
                                found[str(uuid)] = first
                        continue
                    except Exception:
                        pass
                # Wide shape: each uuid is a COLUMN, so a per-uuid MIN() is a full table
                # scan EACH. Measured: ~700 columns over a 661k-row table did not finish in
                # ten minutes. One scan computing many conditional aggregates does the same
                # work once, batched so no single statement grows unreasonably long.
                cur.execute(
                    "SELECT table_name, column_name FROM information_schema.columns "
                    "WHERE table_schema=%s",
                    (os.getenv("MYSQL_DATABASE", "sensordb"),),
                )
                cols: Dict[str, str] = {}
                for tname, cname in cur.fetchall():
                    cols.setdefault(str(cname), str(tname))

                by_table: Dict[str, List[str]] = defaultdict(list)
                for uuid in uuids:
                    table = cols.get(uuid)
                    if table:
                        by_table[table].append(uuid)
                for table, table_uuids in by_table.items():
                    for i in range(0, len(table_uuids), 40):
                        batch = table_uuids[i : i + 40]
                        selects = ", ".join(
                            f"MIN(CASE WHEN `{u}` IS NOT NULL THEN `datetime` END)" for u in batch
                        )
                        try:
                            cur.execute(f"SELECT {selects} FROM `{table}`")
                            row = cur.fetchone() or ()
                            for uuid, first in zip(batch, row):
                                if first:
                                    found[uuid] = first
                        except Exception as exc:
                            print(f"   ! batch failed on {table}: {str(exc)[:90]}")
    finally:
        conn.close()
    return found


def build_ttl(namespace: str, decided: List[Dict]) -> str:
    ns = namespace if namespace.endswith("#") else namespace + "#"
    lines = [
        "# Configuration history — when each point's current location took effect (V6-T07).",
        "#",
        "# GENERATED by scripts/provision_configuration_history.py.",
        "#",
        "# effectiveFrom is the point's EARLIEST OBSERVATION in the timeseries store, which is a",
        "# measured fact. It is NOT a commissioning date: nobody recorded one, and inventing a",
        "# plausible date would misattribute readings exactly the way a missing date does, while",
        "# looking authoritative. changeKind says 'first_observed' so the data admits this.",
        "#",
        "# Consequence, deliberate: location_as_of returns None before a point's first reading.",
        "# 'We do not know where it was' and 'it was where it is now' are different claims.",
        "#",
        "# A real relocation is added by an operator with changeKind 'relocation' and a proper",
        "# effectiveFrom; this script only writes periods for points that have NONE, so an",
        "# operator's history is never overwritten.",
        "",
        f"@prefix bldg: <{ns}> .",
        "@prefix xsd:  <http://www.w3.org/2001/XMLSchema#> .",
        f"@prefix ontosage: <{ONTOSAGE}> .",
        "",
    ]
    for d in decided:
        pid = local(d["iri"])
        lines += [
            f"bldg:{pid}_cfg1 a ontosage:ConfigurationPeriod ;",
            f"    ontosage:configurationOf bldg:{pid} ;",
            f'    ontosage:effectiveFrom "{d["from"]:%Y-%m-%dT%H:%M:%S}"^^xsd:dateTime ;',
            f"    ontosage:configLocation bldg:{local(d['loc'])} ;",
            '    ontosage:changeKind "first_observed" ;',
            '    ontosage:periodSource "measured-earliest-observation" .',
            "",
        ]
    return "\n".join(lines)


async def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--dry-run", action="store_true")
    ap.add_argument("--limit", type=int, default=0, help="cap the number of points (smoke test)")
    args = ap.parse_args()

    building, namespace = settings.BUILDING_ID, settings.BUILDING_NAMESPACE
    points = await connected_points(namespace)
    if args.limit:
        points = points[: args.limit]
    print(f"building={building}")
    print(f"located points with a timeseries reference and no period yet: {len(points)}")

    firsts = earliest_observations(points)
    decided: List[Dict] = []
    no_reading: List[str] = []
    for p in points:
        first = firsts.get(p["uuid"])
        if first is None:
            no_reading.append(local(p["iri"]))
            continue
        decided.append({"iri": p["iri"], "loc": p["loc"], "from": first})

    print(f"periods to write: {len(decided)}")
    print(f"NO OBSERVATION FOUND (no period written, history stays unknown): {len(no_reading)}")
    for name in no_reading[:8]:
        print(f"   {name}")
    if len(no_reading) > 8:
        print(f"   ... and {len(no_reading) - 8} more")
    if decided:
        span = sorted(d["from"] for d in decided)
        print(f"earliest observation across the estate: {span[0]}  latest first-seen: {span[-1]}")

    out = Path("input") / f"{building}_configuration_history.ttl"
    if args.dry_run:
        print(f"\nDRY RUN — would write {out} ({len(decided)} periods)")
        return 0
    out.write_text(build_ttl(namespace, decided), encoding="utf-8")
    print(f"\nwrote {out}")
    print("NEXT: restart the orchestrator so ttl_uploader ingests it.")
    return 0


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
