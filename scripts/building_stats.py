#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Print the building-characteristics figures the paper's Table 4 reports.

Why this exists (TODO-205). Those numbers were written by hand and drift the
moment sensors are added — SATURATE alone roughly doubled every fixture, so a
table stating the original counts stopped matching what a reader finds in the
artifact. Recounting by hand is error-prone: the first attempt at it reported
"roughly 306 and 300 sensors" when the true figures were 751 and 1527, because
grep counts OCCURRENCES and one sensor can carry several triples.

Run this instead, and paste the row it prints.

What is counted, and why:

  Sensors  instances carrying ``ref:hasExternalReference`` -> ``hasTimeseriesId``.
           That is the property that makes a sensor ANSWERABLE — a sensor with
           no timeseries id is a modelling artefact no question can reach — so
           it is the honest number for a table about deployments. Reported split
           into the base building model and the SATURATE-provisioned additions,
           because the two mean different things and quoting only the total
           invites "where did all these sensors come from?".

  Spaces   instances whose type is a subclass of ``brick:Room``.
  Zones    instances of ``brick:HVAC_Zone``.
  (A sensor-TYPES count is deliberately NOT reported: buildings whose TTL
  embeds the Brick vocabulary also assert every superclass on each instance,
  so any file-based count of "kinds of sensor" is inflated in a way that
  cannot be unpicked reliably. Derive it from the live graph if needed.)

Reads the TTL files directly, so it works for PARKED buildings without booting
anything. The live graph can report slightly MORE than the files do, because
sensors registered through the admin console land in their own named graph
rather than in a file; use ``--live`` against the active building to see that.

Usage:
    python scripts/building_stats.py                 # every building on disk
    python scripts/building_stats.py input bldg3     # just these
    python scripts/building_stats.py --live          # the ACTIVE building's graph
"""

from __future__ import annotations

import argparse
import glob
import json
import sys
import urllib.request
from pathlib import Path
from typing import Dict, List, Optional, Tuple

REPO = Path(__file__).resolve().parent.parent

BRICK = "https://brickschema.org/schema/Brick#"
REF = "https://brickschema.org/schema/Brick/ref#"
#: Vocabulary files: definitions, not building content.
_VOCAB = {"brick_v1.4.ttl", "brick+extensions.ttl"}


def _building_dirs(explicit: List[str]) -> List[Path]:
    if explicit:
        return [REPO / d for d in explicit if (REPO / d).is_dir()]
    out = []
    for name in ("input", "bldg1", "bldg2", "bldg3"):
        p = REPO / name
        if p.is_dir() and any(p.glob("*.ttl")):
            out.append(p)
    return out


def _measure(folder: Path) -> Optional[Dict[str, object]]:
    import rdflib
    from rdflib import RDF, RDFS, Namespace

    files = [
        f for f in sorted(glob.glob(str(folder / "*.ttl"))) if Path(f).name.lower() not in _VOCAB
    ]
    if not files:
        return None
    base_files = [f for f in files if "saturation" not in Path(f).name.lower()]

    def load(paths: List[str]) -> "rdflib.Graph":
        g = rdflib.Graph()
        for p in paths:
            try:
                g.parse(p, format="turtle")
            except Exception:
                pass  # a building may ship a partial file; count what parses
        return g

    ref = Namespace(REF)
    brick = Namespace(BRICK)

    def sensors(g) -> int:
        return len({s for s, _, _ in g.triples((None, ref.hasExternalReference, None))})

    g_all, g_base = load(files), load(base_files)
    total, base = sensors(g_all), sensors(g_base)

    rooms = {brick.Room}
    changed = True
    while changed:
        changed = False
        for s, _, o in g_all.triples((None, RDFS.subClassOf, None)):
            if o in rooms and s not in rooms:
                rooms.add(s)
                changed = True
    spaces = {s for s, _, o in g_all.triples((None, RDF.type, None)) if o in rooms}
    zones = {s for s, _, _ in g_all.triples((None, RDF.type, brick.HVAC_Zone))}
    building_id = folder.name
    yaml_path = folder / "building.yaml"
    name = ""
    if yaml_path.is_file():
        for line in yaml_path.read_text(encoding="utf-8").splitlines():
            if line.startswith("building_id:"):
                building_id = line.split(":", 1)[1].strip()
            elif line.startswith("building_name:"):
                name = line.split(":", 1)[1].strip()
    return {
        "dir": folder.name,
        "building_id": building_id,
        "name": name,
        "sensors_total": total,
        "sensors_base": base,
        "sensors_saturated": total - base,
        "spaces": len(spaces),
        "zones": len(zones),
    }


def _live() -> Optional[Dict[str, object]]:
    env = {}
    p = REPO / ".env"
    if not p.is_file():
        print("no active building (.env absent) — omit --live or activate one first")
        return None
    for line in p.read_text(encoding="utf-8").splitlines():
        s = line.strip()
        if s and not s.startswith("#") and "=" in s:
            k, v = s.split("=", 1)
            env[k.strip()] = v.split("#", 1)[0].strip().strip('"').strip("'")
    base = (env.get("GRAPHDB_URL") or "http://localhost:7200").replace("graphdb:", "localhost:")
    ns = env.get("BUILDING_NAMESPACE", "")

    def ask(q: str) -> Dict[str, str]:
        req = urllib.request.Request(
            f"{base.rstrip('/')}/repositories/{env.get('GRAPHDB_REPOSITORY', 'bldg')}",
            data=q.encode(),
            headers={
                "Content-Type": "application/sparql-query",
                "Accept": "application/sparql-results+json",
            },
        )
        with urllib.request.urlopen(req, timeout=120) as r:
            rows = json.load(r).get("results", {}).get("bindings", [])
        return {k: v["value"] for k, v in (rows[0].items() if rows else [])}

    sens = ask(
        f"PREFIX ref:<{REF}> SELECT (COUNT(DISTINCT ?s) AS ?n) WHERE {{ "
        f"?s ref:hasExternalReference ?r . ?r ref:hasTimeseriesId ?u . "
        f'FILTER(STRSTARTS(STR(?s),"{ns}")) }}'
    ).get("n", "?")
    sp = ask(
        f"PREFIX brick:<{BRICK}> PREFIX rdfs:<http://www.w3.org/2000/01/rdf-schema#> "
        f"SELECT (COUNT(DISTINCT ?sp) AS ?n) WHERE {{ ?sp a ?c . ?c rdfs:subClassOf* brick:Room . "
        f'FILTER(STRSTARTS(STR(?sp),"{ns}")) }}'
    ).get("n", "?")
    zn = ask(
        f"PREFIX brick:<{BRICK}> SELECT (COUNT(DISTINCT ?z) AS ?n) WHERE {{ ?z a brick:HVAC_Zone . "
        f'FILTER(STRSTARTS(STR(?z),"{ns}")) }}'
    ).get("n", "?")
    return {
        "dir": "(live)",
        "building_id": env.get("BUILDING_ID", "?"),
        "name": env.get("BUILDING_NAME", ""),
        "sensors_total": sens,
        "sensors_base": "-",
        "sensors_saturated": "-",
        "spaces": sp,
        "zones": zn,
    }


def main(argv: List[str]) -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("dirs", nargs="*", help="building folders (default: every one found)")
    ap.add_argument("--live", action="store_true", help="query the ACTIVE building's graph instead")
    args = ap.parse_args(argv)

    stats = [_live()] if args.live else [_measure(d) for d in _building_dirs(args.dirs)]
    stats = [s for s in stats if s]
    if not stats:
        print("no buildings found")
        return 1

    hdr = f"{'building':<22}{'sensors':>9}{'base':>8}{'+sat':>7}{'spaces':>8}{'zones':>7}"
    print(hdr)
    print("-" * len(hdr))
    for s in stats:
        label = f"{s['building_id']} ({s['dir']})" if s["dir"] != "(live)" else s["building_id"]
        print(
            f"{label:<22}{str(s['sensors_total']):>9}{str(s['sensors_base']):>8}"
            f"{str(s['sensors_saturated']):>7}{str(s['spaces']):>8}"
            f"{str(s['zones']):>7}"
        )
    print(
        "\nsensors = instances with ref:hasExternalReference -> hasTimeseriesId "
        "(what a question can actually reach)"
        "\nbase    = the building model as authored;  +sat = added by SATURATE provisioning"
    )
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
