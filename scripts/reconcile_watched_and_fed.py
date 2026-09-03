#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Does every point the system WATCHES actually receive readings? (CAVEAT-402)

THE QUESTION THIS ASKS, AND THE ONE IT DELIBERATELY DOES NOT
------------------------------------------------------------
The anomaly scanner watches every point the capability schema attaches to a space. Whether a
point is *fed* was, until this script, answered by reading publisher map files — and there
are three of them, none aware of the others, so the answer depended on which file you opened.
That is how CAVEAT-402 came to be recorded as a data gap when in fact every watched point was
being written: a reconciliation across map files found 605 "unfed" points, of which 509 were
fed by a second map and 96 were columns in a wide table that the first two maps do not
describe at all.

So this asks the question that has one answer: **when did this point last produce a
reading?** Read per-uuid from the adapters, independent of which map claims it, and correct
in production where no publisher map exists at all.

WHY PER-UUID AND NOT PER-STORE
------------------------------
A narrow table's sensors are ROWS. ``MAX(datetime)`` over ``noise_data`` reported today while
235 of its 236 points had been silent for a week (CAVEAT-361). A store-level check would have
called that healthy. Wide tables are the opposite — every column is written by the same
INSERT — so a table-level timestamp is the honest answer there, and the adapter says which
kind it is rather than this script assuming.

EXIT CODE
---------
Non-zero when a watched point has produced nothing inside the staleness window, so this can
stand as a check rather than a report nobody reruns.

BUILDING-AGNOSTIC
-----------------
No building id, store, modality or count appears here. Watched points come from the running
building's schema, freshness from its own adapters.

    python scripts/reconcile_watched_and_fed.py
    python scripts/reconcile_watched_and_fed.py --stale-minutes 60
"""

from __future__ import annotations

import argparse
import json
import os
import subprocess  # nosec B404 - fixed local docker commands
import sys
from collections import Counter
from pathlib import Path
from typing import List

REPO = Path(__file__).resolve().parent.parent
CONTAINER = os.environ.get("ONTOSAGE_ORCH_CONTAINER", "ontosage-orchestrator")

#: Runs inside the orchestrator, which is the only place with both the graph and the
#: adapters. Emits one JSON object so the host side does no parsing of its own.
#:
#: The space-attachment filter mirrors ``AnomalyScanner._fetch`` exactly. A point the scanner
#: skips must not be counted as watched, or this reports the wrong gap — which is the whole
#: failure mode being repaired.
PROBE = r"""
import asyncio, json, sys
from datetime import datetime, timedelta

from orchestrator.services.adapters.registry import adapter_registry
from orchestrator.services.deliberation.capability_schema import build_schema
from orchestrator.services.deliberation.coverage_audit import load_modalities
from orchestrator.services.deliberation.live import sparql_exec
from shared.config import settings

STALE_MINUTES = float(sys.argv[1]) if len(sys.argv) > 1 else 30.0


async def main():
    await adapter_registry.initialize()
    schema = await build_schema(
        settings.BUILDING_ID,
        settings.BUILDING_NAMESPACE,
        sparql_exec,
        load_modalities(settings.BUILDING_ID),
    )

    by_store = {}
    for sc in schema.spaces:
        for modality, h in (sc.modalities or {}).items():
            h = h or {}
            uuid = str(h.get("uuid") or "")
            store = str(h.get("stored_at") or "")
            if not uuid or not store or str(h.get("status", "")) != "present":
                continue
            by_store.setdefault(store, {})[uuid] = modality

    now = datetime.utcnow()
    cutoff = now - timedelta(minutes=STALE_MINUTES)
    out = {"stores": {}, "fresh": 0, "stale": 0, "silent": 0, "unknown": 0, "watched": 0}
    for store, points in sorted(by_store.items()):
        adapter = adapter_registry.get(store)
        row = {"points": len(points), "fresh": 0, "stale": 0, "silent": 0, "unknown": 0,
               "granularity": "none", "latest": None}
        out["watched"] += len(points)
        if adapter is None:
            row["unknown"] = len(points)
            out["unknown"] += len(points)
            out["stores"][store] = row
            continue

        latest = {}
        if hasattr(adapter, "latest_by_uuid"):
            # A narrow store: sensors are rows, so ask per sensor.
            row["granularity"] = "per-uuid"
            try:
                latest = await adapter.latest_by_uuid(list(points))
            except Exception as exc:
                row["error"] = str(exc)[:200]
        else:
            # A wide store: every column is written by the same INSERT, so the table's own
            # newest timestamp IS each column's. Reported as such rather than implied.
            row["granularity"] = "per-store"
            try:
                table_latest = await adapter.latest_timestamp(store)
            except Exception as exc:
                table_latest, row["error"] = None, str(exc)[:200]
            latest = {u: table_latest for u in points}

        newest = None
        for uuid in points:
            when = latest.get(uuid, "missing")
            if when == "missing" or when is None:
                # A key absent means the query could not say; a key present holding None
                # means the store proved there is nothing. Only the second is silence.
                bucket = "unknown" if when == "missing" else "silent"
            else:
                bucket = "fresh" if when >= cutoff else "stale"
                if newest is None or when > newest:
                    newest = when
            row[bucket] += 1
            out[bucket] += 1
        row["latest"] = newest.isoformat() if newest else None
        out["stores"][store] = row

    print("RECONCILE:" + json.dumps(out))


asyncio.run(main())
"""


def main(argv: List[str]) -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument(
        "--stale-minutes",
        type=float,
        default=30.0,
        help="a watched point with nothing newer than this is reported as stale",
    )
    ap.add_argument(
        "--allow-stale",
        action="store_true",
        help="report stale points without failing; silent points still fail",
    )
    args = ap.parse_args(argv)

    tmp = REPO / "scripts" / "outputs" / "_reconcile_probe.py"
    tmp.parent.mkdir(parents=True, exist_ok=True)
    tmp.write_text(PROBE, encoding="utf-8")
    env = os.environ.copy()
    env["MSYS_NO_PATHCONV"] = "1"
    subprocess.run(  # nosec B603 B607
        ["docker", "cp", str(tmp), f"{CONTAINER}:/tmp/_reconcile_probe.py"],
        check=True,
        capture_output=True,
        timeout=60,
        env=env,
    )
    res = subprocess.run(  # nosec B603 B607
        [
            "docker",
            "exec",
            CONTAINER,
            "python",
            "/tmp/_reconcile_probe.py",
            str(args.stale_minutes),
        ],
        capture_output=True,
        text=True,
        timeout=1800,
        env=env,
    )
    line = next((ln for ln in (res.stdout or "").splitlines() if ln.startswith("RECONCILE:")), "")
    if not line:
        raise SystemExit(
            "the probe produced nothing — is the stack up and the graph loaded?\n"
            + (res.stderr or res.stdout or "")[-1200:]
        )
    data = json.loads(line[len("RECONCILE:") :])

    watched = data["watched"]
    print(f"watched points (attached to a space, status=present): {watched}")
    print(f"  fresh   (a reading inside {args.stale_minutes:g} min)  {data['fresh']:>6}")
    print(f"  stale   (a reading, but older)                {data['stale']:>6}")
    print(f"  SILENT  (the store proved there is nothing)   {data['silent']:>6}")
    print(f"  unknown (the store could not say)             {data['unknown']:>6}")
    print(f"\n{'store':28} {'pts':>5} {'fresh':>6} {'stale':>6} {'silent':>6} {'how':>9}  latest")
    print("-" * 100)
    for store, row in sorted(data["stores"].items(), key=lambda kv: -kv[1]["points"]):
        print(
            f"{store[:28]:28} {row['points']:>5} {row['fresh']:>6} {row['stale']:>6} "
            f"{row['silent']:>6} {row['granularity']:>9}  {row['latest'] or '-'}"
        )
        if row.get("error"):
            print(f"{'':28} error: {row['error']}")

    out = REPO / "scripts" / "outputs" / "watched_vs_fed.json"
    out.write_text(json.dumps(data, indent=1), encoding="utf-8")
    print(f"\n[written] {out}")

    failed = data["silent"] + (0 if args.allow_stale else data["stale"])
    if failed:
        stores = Counter()
        for store, row in data["stores"].items():
            n = row["silent"] + (0 if args.allow_stale else row["stale"])
            if n:
                stores[store] = n
        print(
            f"\nFAIL: {failed} watched point(s) are not receiving readings. Every detector "
            f"sees these as dead, and a question about the space they sit in cannot be "
            f"answered from them.\n  " + ", ".join(f"{s} ({n})" for s, n in stores.most_common())
        )
        return 1
    print("\nOK: every watched point is receiving readings.")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
