#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Remove the duplicated blank-node timeseries references in the default graph (CAVEAT-039).

WHAT IS WRONG
-------------
Before commit b4c7381 the TTL uploader POSTed each file to ``/statements`` with no
``?context=``. A context-less POST *appends*, and that is idempotent for triples made only of
IRIs -- but Brick models timeseries linkage as a blank node::

    ?sensor ref:hasExternalReference [ a ref:TimeseriesReference ;
                                       ref:hasTimeseriesId ... ; ref:storedAt ... ]

Every parse mints fresh blank-node identifiers, so every boot stacked another copy. The damage
landed precisely on the sensor-to-timeseries link. b4c7381 switched to a scoped ``PUT``, which
stopped the accumulation but by construction cannot reach what is already outside a named
graph.

WHY IT IS NOT COSMETIC
----------------------
No live read path scopes its query with a ``GRAPH`` clause, so every sensor lookup reads the
union -- including the default graph. The class-listing query the SPARQL agent emits has no
``DISTINCT`` and a ``LIMIT 50``, so the fan-out exhausts the limit on a single subject.
Measured on this repository: ``brick:CO2_Sensor`` returns 50 rows containing **one** distinct
sensor against a true population of **280**. Any "how many / list / which floors have X"
answered through that path is silently, confidently wrong -- which is a fabrication in the
sense design contract 4 forbids, produced without anything in the code being untruthful.

WHY THIS SCRIPT IS SAFE, AND HOW IT PROVES IT EACH TIME
-------------------------------------------------------
1. **Dry run by default.** ``--apply`` is required to change anything.
2. **Rescue gate first.** It counts sensors whose *only* reference lives in the default graph.
   If that is anything but zero, the deletion would strand a sensor and the script REFUSES to
   run -- it is not a warning. (Measured 0 on 2026-08-21; re-asserted at run time because a
   number measured yesterday is not a fact about today.)
3. **Backup before deletion**, as CAVEAT-216's cleanup established.
4. **The delete is doubly bounded**: to blank nodes, and to subjects that still hold a
   named-graph reference, so a sensor's default-graph copies go only while its real one stays.
5. **Re-verified afterwards** against fan-out and the query shape that was actually broken.

    python scripts/cleanup_orphan_timeseries_refs.py             # dry run, changes nothing
    python scripts/cleanup_orphan_timeseries_refs.py --apply     # after reading the dry run
"""

from __future__ import annotations

import argparse
import json
import sys
import urllib.error
import urllib.parse
import urllib.request
from datetime import datetime
from pathlib import Path
from typing import Dict, List, Optional

REPO_ROOT = Path(__file__).resolve().parent.parent
BACKUP_DIR = REPO_ROOT / "volumes" / "backups"

PREFIXES = """PREFIX ref: <https://brickschema.org/schema/Brick/ref#>
PREFIX brick: <https://brickschema.org/schema/Brick#>
"""

#: RDF4J's name for the default graph. Explicit rather than implied: an unscoped DELETE would
#: reach the named graphs too, and the named graphs are the copy being kept.
NULL_CONTEXT = "<http://www.openrdf.org/schema/sesame#nil>"


def _endpoint(base: str, repo: str) -> str:
    return f"{base.rstrip('/')}/repositories/{repo}"


def _select(base: str, repo: str, query: str, timeout: int = 300) -> List[Dict]:
    req = urllib.request.Request(
        _endpoint(base, repo),
        data=(PREFIXES + query).encode("utf-8"),
        headers={
            "Content-Type": "application/sparql-query",
            "Accept": "application/sparql-results+json",
        },
        method="POST",
    )
    with urllib.request.urlopen(req, timeout=timeout) as resp:
        return json.loads(resp.read().decode("utf-8"))["results"]["bindings"]


def _one(base: str, repo: str, query: str) -> str:
    rows = _select(base, repo, query)
    if not rows:
        return "0"
    return next(iter(rows[0].values()))["value"]


def _update(base: str, repo: str, query: str, timeout: int = 900) -> None:
    req = urllib.request.Request(
        f"{_endpoint(base, repo)}/statements",
        data=urllib.parse.urlencode({"update": PREFIXES + query}).encode("utf-8"),
        headers={"Content-Type": "application/x-www-form-urlencoded"},
        method="POST",
    )
    with urllib.request.urlopen(req, timeout=timeout) as resp:
        resp.read()


# -- the measurements ---------------------------------------------------------


def rescue_gate(base: str, repo: str) -> int:
    """Sensors that would lose their ONLY reference. Must be zero, or nothing runs."""
    return int(
        _one(
            base,
            repo,
            """SELECT (COUNT(DISTINCT ?s) AS ?n) WHERE {
                 ?s ref:hasExternalReference ?r .
                 FILTER NOT EXISTS { GRAPH ?g { ?s ref:hasExternalReference ?r2 } }
               }""",
        )
    )


def fanout(base: str, repo: str) -> Dict[str, float]:
    row = _select(
        base,
        repo,
        """SELECT (COUNT(?r) AS ?refs) (COUNT(DISTINCT ?s) AS ?sensors) WHERE {
             ?s ref:hasExternalReference ?r
           }""",
    )[0]
    refs, sensors = int(row["refs"]["value"]), int(row["sensors"]["value"])
    return {"refs": refs, "sensors": sensors, "mean": refs / sensors if sensors else 0.0}


def starvation_probe(base: str, repo: str, cls: str = "brick:CO2_Sensor") -> Dict[str, int]:
    """The failure a user would actually meet, not a proxy for it.

    Re-runs the agent's own query shape -- no DISTINCT, LIMIT 50 -- and reports how many
    distinct subjects survive it against the true population.
    """
    rows = _select(
        base,
        repo,
        f"""SELECT ?sensor ?uuid WHERE {{
              ?sensor a {cls} .
              OPTIONAL {{ ?sensor ref:hasExternalReference ?r . ?r ref:hasTimeseriesId ?uuid }}
            }} LIMIT 50""",
    )
    true_n = int(_one(base, repo, f"SELECT (COUNT(DISTINCT ?s) AS ?n) WHERE {{ ?s a {cls} }}"))
    return {
        "rows": len(rows),
        "distinct": len({r["sensor"]["value"] for r in rows}),
        "true_population": true_n,
    }


def scope(base: str, repo: str) -> int:
    """How many triples the deletion would remove."""
    return int(
        _one(
            base,
            repo,
            f"""SELECT (COUNT(*) AS ?n) WHERE {{
                  GRAPH {NULL_CONTEXT} {{ ?s ref:hasExternalReference ?r . ?r ?p ?o }}
                  FILTER(isBlank(?r))
                  FILTER EXISTS {{ GRAPH ?g {{ ?s ref:hasExternalReference ?r2 }} }}
                }}""",
        )
    )


# -- the change ---------------------------------------------------------------


def backup(base: str, repo: str) -> Path:
    """Serialise exactly what is about to be deleted, before deleting it."""
    rows = _select(
        base,
        repo,
        f"""SELECT ?s ?r ?p ?o WHERE {{
              GRAPH {NULL_CONTEXT} {{ ?s ref:hasExternalReference ?r . ?r ?p ?o }}
              FILTER(isBlank(?r))
              FILTER EXISTS {{ GRAPH ?g {{ ?s ref:hasExternalReference ?r2 }} }}
            }}""",
        timeout=900,
    )
    BACKUP_DIR.mkdir(parents=True, exist_ok=True)
    path = BACKUP_DIR / f"orphan_ts_refs_{datetime.now().strftime('%Y%m%d_%H%M%S')}.json"
    path.write_text(json.dumps(rows, indent=1), encoding="utf-8")
    return path


def delete(base: str, repo: str) -> None:
    """Remove the default-graph copies, and only those.

    Two filters carry the safety. ``isBlank`` keeps the deletion to generated nodes, never an
    authored IRI. ``FILTER EXISTS`` keeps it to sensors that still hold a named-graph
    reference, so the surviving copy is guaranteed to exist BEFORE its duplicate is removed --
    the property the rescue gate asserts globally, re-asserted here per subject.
    """
    _update(
        base,
        repo,
        f"""DELETE {{ GRAPH {NULL_CONTEXT} {{ ?s ref:hasExternalReference ?r . ?r ?p ?o }} }}
            WHERE  {{ GRAPH {NULL_CONTEXT} {{ ?s ref:hasExternalReference ?r . ?r ?p ?o }}
                      FILTER(isBlank(?r))
                      FILTER EXISTS {{ GRAPH ?g {{ ?s ref:hasExternalReference ?r2 }} }} }}""",
    )


def main(argv: List[str]) -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--base", default="http://localhost:7200")
    ap.add_argument("--repo", default="bldg")
    ap.add_argument("--apply", action="store_true", help="actually delete (default: dry run)")
    args = ap.parse_args(argv)

    print(f"repository: {_endpoint(args.base, args.repo)}\n")

    try:
        before_fan = fanout(args.base, args.repo)
        before_probe = starvation_probe(args.base, args.repo)
        n_scope = scope(args.base, args.repo)
        orphans = rescue_gate(args.base, args.repo)
    except (urllib.error.URLError, OSError) as exc:
        print(f"cannot reach GraphDB: {exc}")
        return 2

    print("BEFORE")
    print(
        f"  references {before_fan['refs']} over {before_fan['sensors']} sensors "
        f"(mean fan-out {before_fan['mean']:.1f}, expected 1-2)"
    )
    print(
        f"  agent query shape: {before_probe['rows']} rows -> "
        f"{before_probe['distinct']} distinct sensor(s) of a true "
        f"{before_probe['true_population']}"
    )
    print(f"  triples in scope for deletion: {n_scope}")
    print(f"  rescue gate (sensors that would be stranded): {orphans}")

    if orphans != 0:
        # Not a warning. A non-zero gate means the deletion would remove a sensor's only
        # link to its readings, and a sensor with no reference answers nothing at all.
        print("\nREFUSING: some sensors have no named-graph reference. Fix that first.")
        return 1

    if not args.apply:
        print("\nDRY RUN — nothing changed. Re-run with --apply to delete.")
        return 0

    saved = backup(args.base, args.repo)
    print(f"\nbacked up {n_scope} triples to {saved.relative_to(REPO_ROOT).as_posix()}")
    delete(args.base, args.repo)

    after_fan = fanout(args.base, args.repo)
    after_probe = starvation_probe(args.base, args.repo)
    print("\nAFTER")
    print(
        f"  references {after_fan['refs']} over {after_fan['sensors']} sensors "
        f"(mean fan-out {after_fan['mean']:.1f})"
    )
    print(
        f"  agent query shape: {after_probe['rows']} rows -> "
        f"{after_probe['distinct']} distinct sensor(s) of a true "
        f"{after_probe['true_population']}"
    )
    # Deliberately NOT asserting "50 distinct": with one reference each, a 50-row limit over
    # a 280-sensor population returns at most 50 distinct, and the honest success criterion is
    # that fan-out approaches 1, not that a truncated query became complete. The LIMIT itself
    # is a separate defect and a separate fix.
    if after_fan["mean"] > 4:
        print("\nWARNING: fan-out is still high; re-read the scope query before re-running.")
        return 1
    print("\nDone. Sensor count answers should now reflect the real population.")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
