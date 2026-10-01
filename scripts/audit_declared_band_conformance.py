# -*- coding: utf-8 -*-
"""Audit stored readings against the band the building DECLARES for each point.

WHY THIS EXISTS
---------------
Found while diagnosing BUG-1042. Every point in `input/<bldg>_narrow_publish_map.json`
carries a `lo`/`hi` band taken from the ontology's own typicalMin/typicalMax, and the
current generator clamps every value it writes into that band. History does not: the
occupancy counters hold 283,792 rows above their declared maximum of 30, up to 194
people in a single academic office, all written in August 2026 under an older generator.

A row outside the declared band is not automatically wrong -- a real building does exceed
a typical range, which is what makes a reading interesting. What it IS, is a reading no
downstream consumer can interpret with the band it was given. The plausibility guard
flags one value at a time; nothing has ever counted them, so nobody could say whether a
month of a modality was usable.

WHAT IT REPORTS, AND WHAT IT DOES NOT
-------------------------------------
Per narrow table and per point family: rows, rows outside [lo, hi], the extremes, and
WHEN the violations were written -- because the era matters more than the count. A block
of violations that stops on a date is history under a retired generator; violations that
continue to today are a live defect. This script does not decide which; it prints the
last violating timestamp so a reader can.

It reads only. It never writes to any store.

CLOCKS: every store is UTC. The session is pinned to '+00:00' before any query, because a
default (BST) session makes a TIMESTAMP look local and that artefact has produced three
wrong "fixes" and a withdrawn P1 in this project (CLAUDE.md CLOCKS, lessons #103).

USAGE
-----
    docker cp scripts/audit_declared_band_conformance.py ontosage-orchestrator:/app/
    MSYS_NO_PATHCONV=1 docker exec ontosage-orchestrator \
        python /app/audit_declared_band_conformance.py [--table occupancy_data] [--by-month]
"""

from __future__ import annotations

import argparse
import glob
import json
import os
import sys
from collections import defaultdict
from typing import Dict, List, Optional, Tuple

try:
    import pymysql
except ImportError:  # pragma: no cover - the container always has it
    print("pymysql not available; run this INSIDE the orchestrator container")
    raise

from shared.db_clock import UTC_SESSION_INIT


def _map_paths() -> List[str]:
    """Every publish map the active building ships. Discovered, never hardcoded."""
    found = sorted(glob.glob("/app/input/*_publish_map.json"))
    return found or sorted(glob.glob("input/*_publish_map.json"))


def load_points() -> Dict[str, Dict[str, object]]:
    """uuid -> {table, lo, hi, sensor, label, band_from}, per point that declares a band.

    ``band_from`` is the day the band took effect, stamped by
    ``orchestrator/services/publisher_map.py`` when it writes or changes one. It matters
    because a violation BEFORE that date is a schema change with no migration and a
    violation AFTER it is a writer producing values it declares impossible — the same count,
    two different findings (CAVEAT-1131). A band written before anything dated bands carries
    the WORDS "unknown", not a plausible date.
    """
    points: Dict[str, Dict[str, object]] = {}
    for path in _map_paths():
        try:
            with open(path, "r", encoding="utf-8") as fh:
                doc = json.load(fh)
        except Exception as exc:
            print("  ! could not read %s: %s" % (path, exc))
            continue
        if not isinstance(doc, dict):
            continue
        for uuid, entry in doc.items():
            if not isinstance(entry, dict):
                continue
            lo, hi, table = entry.get("lo"), entry.get("hi"), entry.get("table")
            if lo is None or hi is None or not table:
                continue
            points[uuid] = {
                "table": str(table),
                "lo": float(lo),
                "hi": float(hi),
                "sensor": entry.get("sensor") or "",
                "label": entry.get("label") or "",
                "band_from": entry.get("band_from") or "",
            }
    return points


def _valid_from(points: Dict[str, Dict[str, object]]) -> Optional[str]:
    """The one date every stamped band in this group took effect, or None if they differ.

    A group is one (lo, hi, family), so its points ordinarily share a stamp. Where they do
    not, the split is not attributable to a single schema change and the audit says so
    rather than picking one.
    """
    stamps = {str(p.get("band_from") or "") for p in points.values()}
    stamps.discard("")
    dated = {s for s in stamps if s[:4].isdigit()}
    return dated.pop() if len(dated) == 1 and len(stamps) == 1 else None


def connect():
    conn = pymysql.connect(
        host=os.environ.get("MYSQL_HOST", "host.docker.internal"),
        port=int(os.environ.get("MYSQL_PORT", "3306")),
        user=os.environ.get("MYSQL_USER", "ontosage"),
        password=os.environ.get("MYSQL_PASSWORD", ""),
        database=os.environ.get("MYSQL_DATABASE", "sensordb"),
        charset="utf8mb4",
        # `init_command`, NOT a `SET time_zone` after connecting. Both pin this session, but
        # only `init_command` survives a reconnect, and pymysql reconnects silently — so the
        # hand-rolled form is correct exactly until the first dropped connection, which is the
        # worst way for a clock convention to fail. `UTC_SESSION_INIT` is the one spelling the
        # build checks for (tests/test_db_sessions_pin_utc.py), and a convention enforced at
        # one call site and assumed at the rest is not a convention.
        init_command=UTC_SESSION_INIT,
    )
    with conn.cursor() as cur:
        cur.execute("SELECT @@session.time_zone, NOW()")
        tz, now = cur.fetchone()
        print("session time_zone=%s  now=%s (UTC)" % (tz, now))
    return conn


def _family(sensor: str) -> str:
    """Group points that share a band, so a report names a family not 2,756 uuids."""
    name = sensor or "?"
    if "_sat_" in name:
        return name.split("_sat_", 1)[1]
    return name


def audit_table(
    cur, table: str, pts: Dict[str, Dict[str, object]], by_month: bool
) -> Tuple[int, int, int]:
    """Count rows outside the declared band for one table.

    Returns (rows, violations, violations_since_the_band_took_effect). The third figure is
    the one a defect decision turns on: a violation written BEFORE its band's valid-from was
    produced under a different constraint and is a migration question, while one written
    after it is a writer emitting a value the building says is impossible.
    """
    by_band: Dict[Tuple[float, float, str], List[str]] = defaultdict(list)
    for uuid, p in pts.items():
        by_band[(p["lo"], p["hi"], _family(str(p["sensor"])))].append(uuid)

    total = viol = since = 0
    lines: List[str] = []
    for (lo, hi, fam), uuids in sorted(by_band.items(), key=lambda kv: -len(kv[1])):
        ph = ",".join(["%s"] * len(uuids))
        valid_from = _valid_from({u: pts[u] for u in uuids})
        cur.execute(
            "SELECT COUNT(*), SUM(`value` < %%s OR `value` > %%s), MIN(`value`), MAX(`value`), "
            "       MAX(CASE WHEN `value` < %%s OR `value` > %%s THEN `datetime` END), "
            "       SUM((`value` < %%s OR `value` > %%s) AND `datetime` >= %%s) "
            "FROM `%s` WHERE uuid IN (%s)" % (table, ph),
            [lo, hi, lo, hi, lo, hi, valid_from or "9999-01-01"] + uuids,
        )
        n, bad, mn, mx, last_bad, bad_since = cur.fetchone()
        n = int(n or 0)
        bad = int(bad or 0)
        total += n
        viol += bad
        if valid_from:
            since += int(bad_since or 0)
        if bad:
            lines.append(
                "    %-28s n=%-9d band=[%g,%g] outside=%-8d (%.2f%%) range=%s..%s last=%s"
                % (fam[:28], n, lo, hi, bad, 100.0 * bad / max(1, n), mn, mx, last_bad)
            )
            if valid_from:
                lines.append(
                    "        band valid from %s: %d of those %d were written UNDER it%s"
                    % (
                        valid_from,
                        int(bad_since or 0),
                        bad,
                        "" if bad_since else "  <- all of it predates the band",
                    )
                )
            else:
                lines.append(
                    "        band valid from: UNKNOWN — this band predates the stamp, so "
                    "nothing here separates a schema change from a writer defect"
                )
            if by_month:
                cur.execute(
                    "SELECT YEAR(`datetime`), MONTH(`datetime`), COUNT(*), MAX(`value`) "
                    "FROM `%s` WHERE uuid IN (%s) AND (`value` < %%s OR `value` > %%s) "
                    "GROUP BY 1,2 ORDER BY 1,2" % (table, ph),
                    uuids + [lo, hi],
                )
                for y, mo, cnt, mx2 in cur.fetchall():
                    lines.append("        %04d-%02d  %-9d  max=%s" % (y, mo, cnt, mx2))
    if viol:
        print(
            "  %s: %d rows, %d outside the declared band (%.2f%%)"
            % (table, total, viol, 100.0 * viol / max(1, total))
        )
        for ln in lines:
            print(ln)
    else:
        print("  %s: %d rows, all inside the declared band" % (table, total))
    return total, viol, since


def main(argv: Optional[List[str]] = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--table", action="append", help="restrict to this table (repeatable)")
    ap.add_argument(
        "--by-month",
        action="store_true",
        help="break violations down by month, which separates history from a live defect",
    )
    args = ap.parse_args(argv)

    points = load_points()
    if not points:
        print("no publish map declared a band; nothing to audit")
        return 1
    tables = sorted({str(p["table"]) for p in points.values()})
    if args.table:
        tables = [t for t in tables if t in set(args.table)]
    print("%d points declare a band across %d table(s)\n" % (len(points), len(tables)))

    undated = sum(1 for p in points.values() if not str(p.get("band_from") or "")[:4].isdigit())
    if undated:
        print(
            "%d of those bands carry no valid-from date. A band with no date cannot be told "
            "apart\nfrom one the readings were taken under, so for those points this audit "
            "counts a schema\nchange and a writer defect as the same number (CAVEAT-1131).\n"
            % undated
        )

    conn = connect()
    grand_n = grand_v = grand_s = 0
    try:
        with conn.cursor() as cur:
            for table in tables:
                pts = {u: p for u, p in points.items() if p["table"] == table}
                try:
                    n, v, s = audit_table(cur, table, pts, args.by_month)
                except Exception as exc:
                    print("  %s: SKIPPED (%s)" % (table, exc))
                    continue
                grand_n += n
                grand_v += v
                grand_s += s
    finally:
        conn.close()

    print(
        "\nTOTAL %d rows, %d outside their declared band (%.3f%%)"
        % (grand_n, grand_v, 100.0 * grand_v / max(1, grand_n))
    )
    print(
        "Of those, %d were written UNDER a band carrying a valid-from date — i.e. by a writer "
        "that\nhad already been told the value was impossible. The rest predate their band, or "
        "their band\nis undated and the question cannot be answered from this run alone." % grand_s
    )
    print("A violation is not automatically an error. Read the `last=` timestamp: a block that")
    print("stops on a date is history under a retired generator; one reaching today is live.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
