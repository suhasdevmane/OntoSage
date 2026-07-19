#!/usr/bin/env python3
"""Data-coverage audit — declared sensors vs. populated time-series, per modality/floor.

Quantifies the gap between what the building ONTOLOGY declares (sensors with a
``ref:hasTimeseriesId`` + ``ref:storedAt`` target) and what the DATABASES actually hold
(rows keyed by those UUIDs). This is the honest answer to "what can this building really
answer?" — a sensor with no rows is invisible to any query.

Config-driven / portable: reads the ACTIVE building's TTL files (resolved via
``shared.building_paths``) and its ``ref:storedAt`` targets. No building-specific literals,
so a new building is audited unchanged.

Usage
-----
    python scripts/data_coverage_audit.py                # declared side (offline, exact)
    python scripts/data_coverage_audit.py --live         # also probe MySQL for populated rows

The declared side always works offline. ``--live`` additionally connects to MySQL (narrow
per-modality tables + the wide ``sensor_data`` table) and reports populated UUID counts;
it degrades gracefully to "DB unreachable" instead of failing.
"""

from __future__ import annotations

import argparse
import re
import sys
from collections import defaultdict
from pathlib import Path
from typing import Dict, List, Optional, Tuple

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

REF = "https://brickschema.org/schema/Brick/ref#"
_FLOOR_RE = re.compile(r"(?:floor[_\s]?|_)(\d)\b|_(\d)\.\d{1,2}\b|\b(\d)\.\d{1,2}\b", re.IGNORECASE)


def _declared_from_ttl(building_id: str) -> Tuple[Dict[str, int], Dict[str, Dict[str, int]]]:
    """Return (per-target sensor counts, per-target→per-floor counts) from the TTLs.

    Uses rdflib so it reads the real RDF (blank-node ``ref:TimeseriesReference`` and all),
    not a line grep. Groups by the ``ref:storedAt`` object's local name (= the modality /
    database key), which is exactly how the adapter registry routes at query time.
    """
    from rdflib import Graph, URIRef

    from shared.building_paths import resolve_building_dir

    ttl_dir = resolve_building_dir(building_id, "") or Path("input")
    ttl_files = sorted(Path("input").glob("*.ttl")) + sorted(Path(ttl_dir).glob("*.ttl"))
    ttl_files = list(dict.fromkeys(ttl_files))  # de-dupe, preserve order

    g = Graph()
    for f in ttl_files:
        try:
            g.parse(str(f), format="turtle")
        except Exception as e:  # a malformed optional file must not abort the audit
            print(f"  (skipped {f.name}: {e})", file=sys.stderr)

    q = """
    PREFIX ref: <https://brickschema.org/schema/Brick/ref#>
    SELECT ?sensor ?db WHERE {
        ?sensor ref:hasExternalReference ?r .
        ?r ref:hasTimeseriesId ?uuid .
        OPTIONAL { ?r ref:storedAt ?db }
    }
    """
    per_target: Dict[str, int] = defaultdict(int)
    per_target_floor: Dict[str, Dict[str, int]] = defaultdict(lambda: defaultdict(int))
    for row in g.query(q):
        sensor = str(row[0])
        db = str(row[1]) if row[1] is not None else "(unspecified)"
        key = db.rsplit("#", 1)[-1].rsplit("/", 1)[-1] if isinstance(row[1], URIRef) else db
        per_target[key] += 1
        floor = _floor_of(sensor)
        per_target_floor[key][floor] += 1
    return dict(per_target), {k: dict(v) for k, v in per_target_floor.items()}


def _floor_of(uri: str) -> str:
    local = uri.rsplit("#", 1)[-1].rsplit("/", 1)[-1]
    m = _FLOOR_RE.search(local)
    if not m:
        return "?"
    return next((g for g in m.groups() if g), "?")


def _populated_counts(targets: List[str]) -> Optional[Dict[str, Tuple[int, int]]]:
    """Best-effort live probe: {target: (distinct_uuids, total_rows)} or None if DB down.

    Reads the database registry so the modality→table mapping is config-driven.
    """
    try:
        import pymysql  # aiomysql's sync sibling; simplest for a one-shot script

        from shared.config import settings
    except Exception as e:
        print(f"  (live probe unavailable: {e})", file=sys.stderr)
        return None

    reg = _load_registry()
    out: Dict[str, Tuple[int, int]] = {}
    try:
        conn = pymysql.connect(
            host=settings.MYSQL_HOST,
            port=int(settings.MYSQL_PORT),
            user=settings.MYSQL_USER,
            password=settings.MYSQL_PASSWORD,
            database=settings.MYSQL_DATABASE,
            connect_timeout=5,
        )
    except Exception as e:
        print(f"  (MySQL unreachable — declared side only: {e})", file=sys.stderr)
        return None

    try:
        with conn.cursor() as cur:
            for target in targets:
                table = reg.get(target, {}).get("table")
                if not table or not re.match(r"^[A-Za-z0-9_]+$", table):
                    continue
                try:
                    cur.execute(f"SELECT COUNT(DISTINCT uuid), COUNT(*) FROM `{table}`")
                    d, t = cur.fetchone()
                    out[target] = (int(d or 0), int(t or 0))
                except Exception as e:
                    print(f"  ({target}/{table}: {e})", file=sys.stderr)
    finally:
        conn.close()
    return out


def _load_registry() -> Dict[str, dict]:
    try:
        import yaml

        p = Path("input/database_registry.yaml")
        if p.exists():
            return yaml.safe_load(p.read_text(encoding="utf-8")) or {}
    except Exception:
        pass
    return {}


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--building", default=None, help="building id (default: settings.BUILDING_ID)")
    ap.add_argument("--live", action="store_true", help="also probe MySQL for populated rows")
    args = ap.parse_args()

    try:
        from shared.config import settings

        building_id = args.building or settings.BUILDING_ID
    except Exception:
        building_id = args.building or "bldg1"

    print(f"\n=== Data-coverage audit - building '{building_id}' ===\n")

    per_target, per_target_floor = _declared_from_ttl(building_id)
    if not per_target:
        print("No time-series sensors declared in the ontology (no ref:hasTimeseriesId found).")
        return 1

    populated = _populated_counts(list(per_target)) if args.live else None

    total_declared = sum(per_target.values())
    print(f"Declared time-series sensors: {total_declared}\n")
    header = f"{'storedAt target':<22}{'declared':>9}"
    if populated is not None:
        header += f"{'uuids w/ rows':>15}{'rows':>12}{'coverage':>10}"
    print(header)
    print("-" * len(header))
    for target in sorted(per_target, key=lambda k: -per_target[k]):
        decl = per_target[target]
        line = f"{target:<22}{decl:>9}"
        if populated is not None:
            d, t = populated.get(target, (0, 0))
            cov = f"{(100 * d / decl):.0f}%" if decl else "-"
            line += f"{d:>15}{t:>12}{cov:>10}"
        print(line)

    print("\nDeclared sensors by floor (from sensor URI/label):")
    for target in sorted(per_target, key=lambda k: -per_target[k]):
        floors = per_target_floor.get(target, {})
        floor_str = ", ".join(f"F{f}:{n}" for f, n in sorted(floors.items()))
        print(f"  {target:<22} {floor_str}")

    if populated is None and args.live:
        print("\n[!] Live probe could not reach MySQL — showing declared side only.")
    elif populated is None:
        print("\nRun with --live to probe populated rows (needs MySQL reachable).")
    print()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
