#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Make every sensor-to-timeseries link reachable by the predicate the code queries.

WHAT WENT WRONG
---------------
The link from a sensor to its timeseries reference is written three different ways in this
project's graphs, and the code follows one of them 43 times and another 9 times:

    s223:hasExternalReference   2,763 sensors   2,839 uuids     <- the superset
    ref:hasExternalReference    2,727 sensors   2,733 uuids     <- what the code queries
    brick:hasExternalReference      2 sensors       2 uuids

So 106 uuids -- an entire synthetic modality set, with rows landing in MySQL right now --
are invisible to every lane that follows `ref:`. Measured 2026-09-06 while regenerating the
publisher's value-range map: a query joining sensors to their references returned 522 where
the building has 628, and the missing 106 looked at first like orphan references with no
sensor at all.

This is design contract 8 broken in the subtlest available way. Both halves are present --
the sensor is in the graph AND its rows are in a registered database -- and the join between
them is expressed in a vocabulary the reader does not speak. Nothing errors. The sensors
simply do not exist as far as most of the system is concerned.

WHY ASSERT RATHER THAN REWRITE THE READERS
------------------------------------------
Both vocabularies are legitimate: `ref:` is Brick's and `s223:` is ASHRAE 223P's, and a
building modelled against either is modelled correctly. Asserting both is what the other
2,727 references already do, so this makes the exception match the rule rather than making
the rule match the exception. Rewriting 43 query sites to spell an alternation would leave
the 44th, written next month, wrong again.

WHY A SPARQL INSERT AND NOT A TTL FILE
--------------------------------------
The affected references are BLANK NODES. A blank node cannot be named from outside the store,
so no TTL file can add a triple pointing at one. The insert binds them inside the graph.

Idempotent: the FILTER NOT EXISTS means a second run inserts nothing. Building-agnostic:
no namespace, class or identifier appears here.

    python scripts/normalise_timeseries_links.py --dry-run
    python scripts/normalise_timeseries_links.py
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path
from typing import List

REPO = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO))

import requests  # noqa: E402

GRAPHDB = "http://localhost:7200/repositories/bldg"

_REF = "https://brickschema.org/schema/Brick/ref#hasExternalReference"

#: Every vocabulary that expresses the same link. Add one here if a building arrives
#: modelled in a fourth; do NOT add an alternation to a query.
_ALIASES = (
    "http://data.ashrae.org/standard223#hasExternalReference",
    "https://brickschema.org/schema/Brick#hasExternalReference",
)

#: The canonical link is asserted into its OWN named graph. The source TTL files are left
#: untouched -- a building's own files should say what its author wrote -- and dropping this
#: one graph undoes the whole normalisation.
_GRAPH = "urn:ontosage:derived:timeseries_link_normalisation"


def _post(query: str, endpoint: str, accept: str = "text/csv") -> str:
    r = requests.post(
        endpoint,
        data=query.encode("utf-8"),
        headers={"Content-Type": "application/sparql-query", "Accept": accept},
        timeout=180,
    )
    r.raise_for_status()
    return r.text


def _update(query: str, endpoint: str) -> None:
    r = requests.post(
        endpoint.rstrip("/") + "/statements",
        data={"update": query},
        timeout=300,
    )
    r.raise_for_status()


def _count_missing(endpoint: str) -> int:
    alt = " ".join(f"<{a}>" for a in _ALIASES)
    q = (
        f"SELECT (COUNT(*) AS ?n) WHERE {{\n"
        f"  VALUES ?p {{ {alt} }}\n"
        f"  ?s ?p ?r .\n"
        f"  FILTER NOT EXISTS {{ ?s <{_REF}> ?r }}\n"
        f"}}"
    )
    body = _post(q, endpoint)
    lines = [l for l in body.strip().splitlines() if l.strip()]
    return int(lines[-1]) if len(lines) > 1 else 0


def main(argv: List[str]) -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--endpoint", default=GRAPHDB)
    ap.add_argument("--dry-run", action="store_true")
    args = ap.parse_args(argv)

    try:
        missing = _count_missing(args.endpoint)
    except Exception as exc:
        print(f"could not query the graph: {exc}")
        return 1

    if missing == 0:
        print("every sensor-to-timeseries link is already reachable by the canonical predicate")
        return 0

    print(
        f"{missing} link(s) are expressed ONLY in an alias vocabulary, so every lane that "
        f"follows the canonical predicate cannot see them."
    )
    if args.dry_run:
        print(f"  [dry-run] would assert {missing} canonical link(s) into <{_GRAPH}>")
        return 0

    alt = " ".join(f"<{a}>" for a in _ALIASES)
    update = (
        f"INSERT {{ GRAPH <{_GRAPH}> {{ ?s <{_REF}> ?r }} }}\n"
        f"WHERE {{\n"
        f"  VALUES ?p {{ {alt} }}\n"
        f"  ?s ?p ?r .\n"
        f"  FILTER NOT EXISTS {{ ?s <{_REF}> ?r }}\n"
        f"}}"
    )
    try:
        _update(update, args.endpoint)
    except Exception as exc:
        print(f"insert failed: {exc}")
        return 1

    remaining = _count_missing(args.endpoint)
    print(f"  asserted; {missing} -> {remaining} unreachable link(s)")
    if remaining:
        print("  WARNING: some links were not normalised; the insert did not do what it says")
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
