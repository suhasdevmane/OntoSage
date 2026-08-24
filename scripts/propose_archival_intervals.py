#!/usr/bin/env python3
"""Measure each stream's real archival cadence and PROPOSE a declaration (V6-T17's missing input).

The completeness gate is written, tested, and cannot run, because it needs one fact nobody has
recorded: how often each stream is *supposed* to arrive. `ontosage:archivalIntervalS` is defined
in the OCBV TBox and has TBox tests — and **zero instances declare it**, in the files or in the
graph. So coverage is always unknown, so the gate would answer "the share of the window
observed could not be established" for every answer in the system, which is why it is recorded
as awaiting an input rather than wired (BUG-237).

WHY THIS PROPOSES RATHER THAN APPLIES. `completeness.py` is explicit that inferring the interval
from the data is circular: a window with a six-hour hole has a median gap that already reflects
the hole, so the series would score itself complete. That objection is about **the window being
assessed**. Measuring the modal interval across a stream's whole history is a different
operation — it is what commissioning a building does — but the distinction only holds if a
person accepts the number. A system that measures its own cadence and then grades itself
against it has marked its own homework by a longer route.

So this writes a TTL file and a report. It never POSTs, never touches the graph, and never
edits `input/`. Loading it is a separate, deliberate act.

WHY THE MODE, NOT THE MEAN OR MEDIAN. `(last - first) / (n - 1)` is the mean gap and a single
outage moves it arbitrarily far. The median survives small holes but not a stream that was down
for half its life. The **modal** inter-arrival gap is the interval the stream actually keeps
when it is working, and outages are outliers that do not move it at all — which is exactly the
property needed, since the declared cadence is the yardstick outages are measured against.

A stream whose modal gap accounts for less than ``--min-share`` of its intervals has no stable
cadence, and this proposes nothing for it. Declaring a number for such a stream would hand the
completeness gate a confident yardstick derived from a stream that has none.

    python scripts/propose_archival_intervals.py                 # measure and report
    python scripts/propose_archival_intervals.py --out cadence.ttl
"""

from __future__ import annotations

import argparse
import asyncio
import json
import sys
from collections import defaultdict
from pathlib import Path
from typing import Dict, List, Optional, Tuple

REPO = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO))

#: Below this many observed intervals a modal gap is not evidence of anything.
MIN_INTERVALS = 20


def _load_sensor_map() -> Dict[str, Dict]:
    """uuid -> {uuid, storage} for the ACTIVE building, from the map the SQL lane itself uses."""
    from shared.config import settings

    try:
        raw = json.loads(Path(settings.SENSOR_MAP_PATH).read_text(encoding="utf-8"))
    except Exception as exc:
        print(f"sensor map unavailable ({exc}); nothing to measure")
        return {}
    out: Dict[str, Dict] = {}
    for entry in raw.values():
        if isinstance(entry, dict) and entry.get("uuid") and entry.get("storage"):
            out[str(entry["uuid"])] = entry
    return out


async def _modal_gaps(adapter, table: str) -> Dict[str, Tuple[int, float, int]]:
    """``{uuid: (modal gap seconds, share of intervals at that gap, interval count)}``.

    One query per table rather than one per sensor: a building with 2,700 streams would
    otherwise issue 2,700 round trips to answer a question SQL can group in a single pass.
    """
    sql = (
        "SELECT uuid, gap, COUNT(*) AS c FROM ("
        "  SELECT `uuid`, TIMESTAMPDIFF(SECOND,"
        "    LAG(`datetime`) OVER (PARTITION BY `uuid` ORDER BY `datetime`), `datetime`) AS gap"
        f"  FROM `{table}`"
        ") g WHERE gap IS NOT NULL AND gap > 0 GROUP BY uuid, gap"
    )
    res = await adapter.execute_query(sql)
    if not res.success:
        return {}
    counts: Dict[str, Dict[int, int]] = defaultdict(dict)
    for row in res.data:
        try:
            counts[str(row["uuid"])][int(row["gap"])] = int(row["c"])
        except Exception:
            continue
    out: Dict[str, Tuple[int, float, int]] = {}
    for uid, dist in counts.items():
        total = sum(dist.values())
        if total < MIN_INTERVALS:
            continue
        gap, n = max(dist.items(), key=lambda kv: kv[1])
        out[uid] = (gap, n / total, total)
    return out


async def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--out", default="", help="write the proposed TTL here (never auto-loaded)")
    ap.add_argument(
        "--min-share",
        type=float,
        default=0.5,
        help="a modal gap must cover at least this share of intervals to count as a cadence",
    )
    args = ap.parse_args(argv)

    from orchestrator.services.adapters.registry import adapter_registry
    from shared.config import settings

    smap = _load_sensor_map()
    if not smap:
        return 2
    by_store: Dict[str, List[str]] = defaultdict(list)
    for uid, e in smap.items():
        by_store[str(e["storage"])].append(uid)
    print(f"{len(smap)} declared stream(s) across {len(by_store)} store(s)\n")

    await adapter_registry.initialize()

    proposals: Dict[str, Tuple[int, float, int]] = {}
    skipped: Dict[str, str] = {}
    for store, uids in sorted(by_store.items()):
        local = store.rsplit("#", 1)[-1].rsplit("/", 1)[-1]
        adapter = adapter_registry.get(store)
        if adapter is None or not hasattr(adapter, "execute_query"):
            print(f"  {local:<24} no adapter — skipped")
            continue
        # Public accessor: while this was `_table`, every narrow store looked wide.
        table = getattr(adapter, "table", None)
        if not table:
            # Wide table: each sensor is a COLUMN, so inter-arrival per sensor needs one pass
            # per column. Deliberately not attempted here — a wide store's cadence is a
            # property of the publisher writing the row, and guessing it per column from a
            # sampled scan would be a worse number than none.
            print(f"  {local:<24} wide shape — not measured (see the note in the report)")
            for u in uids:
                skipped[u] = "wide-table store; cadence is a property of the row writer"
            continue
        try:
            gaps = await _modal_gaps(adapter, table)
        except Exception as exc:
            print(f"  {local:<24} query failed: {type(exc).__name__} {exc}")
            continue
        kept = 0
        for u in uids:
            got = gaps.get(u)
            if not got:
                skipped[u] = "fewer than %d observed intervals" % MIN_INTERVALS
                continue
            gap, share, total = got
            if share < args.min_share:
                skipped[u] = f"no stable cadence (modal gap covers only {share:.0%} of intervals)"
                continue
            proposals[u] = (gap, share, total)
            kept += 1
        print(f"  {local:<24} {kept} of {len(uids)} stream(s) have a stable cadence")

    print(f"\nPROPOSED: {len(proposals)}   NOT PROPOSED: {len(skipped)}")
    if proposals:
        dist: Dict[int, int] = defaultdict(int)
        for gap, _s, _t in proposals.values():
            dist[gap] += 1
        print("\ncadence distribution (seconds -> streams):")
        for gap, n in sorted(dist.items(), key=lambda kv: -kv[1])[:10]:
            print(f"  {gap:>7}s  {n:>5}")

    reasons: Dict[str, int] = defaultdict(int)
    for why in skipped.values():
        reasons[why.split("(")[0].strip()] += 1
    if reasons:
        print("\nwhy the rest were not proposed:")
        for why, n in sorted(reasons.items(), key=lambda kv: -kv[1]):
            print(f"  {n:>5}  {why}")

    if args.out and proposals:
        ns = settings.BUILDING_NAMESPACE
        lines = [
            "# PROPOSED archival cadences — measured, NOT applied.",
            "#",
            "# Generated by scripts/propose_archival_intervals.py. Each value is the MODAL",
            "# inter-arrival gap over the stream's whole history: the interval it keeps when it",
            "# is working, which outages do not move. Streams with no stable modal gap are",
            "# deliberately absent rather than given a confident number.",
            "#",
            "# Review before loading. The completeness gate measures every window against these",
            "# values, so a wrong one here does not produce an error — it produces a coverage",
            "# figure that looks authoritative.",
            "",
            "@prefix ontosage: <http://ontosage.org/schema#> .",
            f"@prefix bldg: <{ns}> .",
            "@prefix ref: <https://brickschema.org/schema/Brick/ref#> .",
            "@prefix xsd: <http://www.w3.org/2001/XMLSchema#> .",
            "",
        ]
        for uid, (gap, share, total) in sorted(proposals.items()):
            lines.append(
                f"# {total} intervals observed; modal gap holds for {share:.0%} of them\n"
                f'[] ref:hasTimeseriesId "{uid}" ;\n'
                f"   ontosage:archivalIntervalS {gap} .\n"
            )
        dest = Path(args.out)
        if not dest.is_absolute():
            dest = REPO / dest
        dest.write_text("\n".join(lines), encoding="utf-8")
        print(f"\nwrote {dest}  — review it; nothing has been loaded")
    return 0


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
