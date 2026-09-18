# -*- coding: utf-8 -*-
"""Pull the per-turn SPARQL captures that belong to a recorded bank run.

Runs INSIDE the orchestrator container (docker cp'd in). Reads
/app/outputs/query_results/*.json, keeps only captures whose ``user_query``
matches one of the questions handed in on stdin, and writes one compact JSONL
line per question to /tmp/bank_evidence.jsonl.

Selection rule: the capture with the LARGEST timestamp that is <= the run's
cut-off. A question asked many times over the day would otherwise bind against
whichever copy the filesystem listed first.
"""
from __future__ import annotations

import json
import os
import sys

CAPDIR = "/app/outputs/query_results"
CUTOFF = os.environ.get("CUTOFF", "2026-09-17T16:27:30")
FLOOR = os.environ.get("FLOOR", "2026-09-17T15:20:00")
OUT = os.environ.get("OUT", "/tmp/bank_evidence.jsonl")


def norm(s):
    return " ".join((s or "").split()).strip().lower()


def main():
    wanted = {}
    for line in sys.stdin:
        line = line.strip()
        if not line:
            continue
        rec = json.loads(line)
        wanted[norm(rec["q"])] = rec["q"]

    best = {}
    scanned = 0
    for name in os.listdir(CAPDIR):
        if not name.endswith(".json"):
            continue
        path = os.path.join(CAPDIR, name)
        try:
            with open(path, "r", encoding="utf-8") as fh:
                d = json.load(fh)
        except Exception:
            continue
        scanned += 1
        k = norm(d.get("user_query"))
        if k not in wanted:
            continue
        ts = str(d.get("timestamp") or "")
        if not (FLOOR <= ts <= CUTOFF):
            continue
        prev = best.get(k)
        if prev is None or ts > prev[0]:
            best[k] = (ts, d)

    with open(OUT, "w", encoding="utf-8") as fh:
        for k, (ts, d) in best.items():
            fh.write(
                json.dumps(
                    {
                        "q": wanted[k],
                        "timestamp": ts,
                        "sparql_query": d.get("sparql_query"),
                        "sparql_results": d.get("sparql_results"),
                        "formatted_response": d.get("formatted_response"),
                        "metadata": d.get("metadata"),
                        "analytics": d.get("analytics"),
                    },
                    ensure_ascii=False,
                )
                + "\n"
            )
    sys.stderr.write("scanned=%d wanted=%d matched=%d\n" % (scanned, len(wanted), len(best)))


if __name__ == "__main__":
    main()
