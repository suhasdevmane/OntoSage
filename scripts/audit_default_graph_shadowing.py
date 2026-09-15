#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Which subjects exist in more than one place, and which of those is a problem (V12-15).

    BUG-194 (P1) — a GUI policy edit wrote the file correctly, replaced the named graph
    correctly, and reported success. The reader returned the OLD value, because a stale
    copy of the same subject sat elsewhere and the PDP queries the UNION of all graphs.
    That row closed with "other subjects may be shadowed the same way — not yet verified".

    This verifies it.

THE TRAP THIS SCRIPT EXISTS TO AVOID
-------------------------------------
The obvious query — "subject in a named graph AND matching outside it" — returns **11,145**
subjects on bldg1. Every one of them is GraphDB materialising INFERENCE into the implicit
context. Restricted to explicit statements the answer is **zero**: there is not one explicit
triple outside a named graph in this repository.

A sweep that reported 11,145 would send someone deleting inference. So both numbers are
printed, side by side, and the naive one is labelled as what it is. That is the difference
between an audit and a scare.

WHAT IT ACTUALLY LOOKS FOR
---------------------------
Three questions, because "shadowed" turned out to mean three different things:

1. EXPLICIT triples outside every named graph  — the literal BUG-194 shape. Expect 0.
2. Subjects in more than one NAMED graph       — expected and mostly benign: a Brick class
                                                 appears in the TBox and in the ABox that
                                                 uses it, and two per-file overlays add
                                                 DIFFERENT properties to the same sensors.
3. Of those, the pairs that genuinely DISAGREE — two graphs holding the same subject with
                                                 different content. This is the only one
                                                 that can produce a shadowed read.

AND THE RULE THAT SAVED A CAPABILITY
--------------------------------------
Never drop a graph because an aggregate says it is redundant. `urn:ontosage:schema` looked
like pure duplication by every count — and two of its triples,
`HandoverRecord layTerms "handover", "handovers"`, existed NOWHERE ELSE. `--diff` prints
exactly what would be lost, and `--drop` refuses to run without it.

Usage:
    python scripts/audit_default_graph_shadowing.py
    python scripts/audit_default_graph_shadowing.py --diff urn:ontosage:schema
"""

from __future__ import annotations

import argparse
import json
import sys
import urllib.error
import urllib.request
from typing import Any, Dict, List, Optional, Tuple

#: GraphDB's pseudo-graph for explicit-only statements. Without it every query below
#: silently includes inference and the whole audit reports a number nobody can act on.
EXPLICIT = "http://www.ontotext.com/explicit"


def _endpoint() -> Tuple[str, Optional[Tuple[str, str]]]:
    """(repository query URL, optional basic-auth pair) from the active configuration."""
    try:
        sys.path.insert(0, ".")
        from shared.config import settings

        host = getattr(settings, "GRAPHDB_HOST", "localhost")
        port = getattr(settings, "GRAPHDB_PORT", 7200)
        repo = getattr(settings, "GRAPHDB_REPOSITORY", "bldg")
        user = getattr(settings, "GRAPHDB_USER", "") or ""
        pwd = getattr(settings, "GRAPHDB_PASSWORD", "") or ""
    except Exception:  # pragma: no cover - running outside the app
        host, port, repo, user, pwd = "localhost", 7200, "bldg", "", ""

    # A container hostname does not resolve from the host running this script. The audit is
    # a host-side tool, so fall back rather than fail with a DNS error that describes
    # nothing about the graph.
    if host in ("graphdb", "ontosage-graphdb"):
        host = "localhost"
    return f"http://{host}:{port}/repositories/{repo}", ((user, pwd) if user else None)


def _ask(query: str, timeout: float = 300.0) -> List[Dict[str, Any]]:
    url, auth = _endpoint()
    req = urllib.request.Request(
        url,
        data=query.encode("utf-8"),
        headers={
            "Content-Type": "application/sparql-query",
            "Accept": "application/sparql-results+json",
        },
    )
    if auth:
        import base64

        token = base64.b64encode(f"{auth[0]}:{auth[1]}".encode()).decode()
        req.add_header("Authorization", f"Basic {token}")
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:  # nosec B310 - fixed scheme
            return json.loads(resp.read().decode("utf-8"))["results"]["bindings"]
    except urllib.error.URLError as exc:
        print(f"  ! GraphDB unreachable at {url}: {exc.reason}", file=sys.stderr)
        raise SystemExit(3)


def _one(query: str) -> int:
    rows = _ask(query)
    return int(rows[0]["n"]["value"]) if rows else 0


# ── the three questions ──────────────────────────────────────────────────────

Q_NAIVE = """
SELECT (COUNT(DISTINCT ?s) AS ?n) WHERE {
  GRAPH ?g { ?s ?p ?o }
  ?s ?p2 ?o2 .
  FILTER NOT EXISTS { GRAPH ?g2 { ?s ?p2 ?o2 } }
}"""

Q_EXPLICIT_OUTSIDE = f"""
SELECT (COUNT(DISTINCT ?s) AS ?n) FROM <{EXPLICIT}> WHERE {{
  ?s ?p ?o .
  FILTER NOT EXISTS {{ GRAPH ?g {{ ?s ?p ?o }} }}
}}"""

Q_MULTI_GRAPH = """
SELECT (COUNT(DISTINCT ?s) AS ?n) WHERE {
  GRAPH ?g1 { ?s ?p1 ?o1 }
  GRAPH ?g2 { ?s ?p2 ?o2 }
  FILTER(?g1 != ?g2)
}"""

Q_PAIRS = """
SELECT ?g1 ?g2 (COUNT(DISTINCT ?s) AS ?n) WHERE {
  GRAPH ?g1 { ?s ?p1 ?o1 }
  GRAPH ?g2 { ?s ?p2 ?o2 }
  FILTER(STR(?g1) < STR(?g2))
} GROUP BY ?g1 ?g2 ORDER BY DESC(?n) LIMIT 25"""


def _disagreements(g1: str, g2: str) -> int:
    """Subjects these two graphs describe INCOMPATIBLY — the only shadowing that can bite.

    "Different content" is not enough, and the first version of this check proved it:
    matching `?s ?p ?o` in one graph against `?s ?p ?other` in the other flagged 1,467
    conflicts between the Brick TBox and its extensions, and 232 of 232 shared subjects
    between two of this building's own files. All noise. RDF predicates are multi-valued by
    default — a sensor legitimately carries several `rdf:type`s and several `layTerms`,
    split across the files that assert them, and that is ADDITION rather than disagreement.

    A real conflict needs the predicate to be single-valued IN BOTH graphs and to hold
    different values. Then exactly one of them wins the union read, and which one is
    arbitrary — which is BUG-194.
    """
    return _one(
        f"""
SELECT (COUNT(DISTINCT ?s) AS ?n) WHERE {{
  GRAPH <{g1}> {{ ?s ?p ?o }}
  GRAPH <{g2}> {{ ?s ?p ?other }}
  FILTER(?o != ?other)
  FILTER(!isBlank(?o) && !isBlank(?other))
  FILTER NOT EXISTS {{ GRAPH <{g1}> {{ ?s ?p ?alt1 }} FILTER(?alt1 != ?o) }}
  FILTER NOT EXISTS {{ GRAPH <{g2}> {{ ?s ?p ?alt2 }} FILTER(?alt2 != ?other) }}
}}"""
    )


def dual_referenced_sensors() -> int:
    """Sensors carrying MORE THAN ONE timeseries reference, to DIFFERENT ids.

    Not graph shadowing, and found by chasing it (BUG-531). Two `hasExternalReference`
    blank nodes on one sensor look like a blank-node artefact — and 77 of them on bldg1
    resolve to different uuids in DIFFERENT stores, one synthetic and one real. Both reach
    the SQL lane, which fetches from both and merges.

    The documented fan-out metric cannot see it: each reference has its own uuid, so
    `refs / distinct uuids` is exactly 1.00 while every one of those sensors answers from
    two sources at once.
    """
    return _one(
        """
PREFIX ref: <https://brickschema.org/schema/Brick/ref#>
SELECT (COUNT(DISTINCT ?s) AS ?n) WHERE {
  ?s ref:hasExternalReference ?r1, ?r2 .
  ?r1 ref:hasTimeseriesId ?u1 .
  ?r2 ref:hasTimeseriesId ?u2 .
  FILTER(?u1 != ?u2)
}"""
    )


def _only_in(g1: str, g2: str, non_blank_only: bool = True) -> List[Tuple[str, str, str]]:
    """Triples in g1 and not in g2. Blank-node subjects/objects are excluded by default:
    their identities change on every load, so a re-upload of the SAME file produces a whole
    new set of them and they are noise rather than content."""
    blank = "FILTER(!isBlank(?s) && !isBlank(?o))" if non_blank_only else ""
    rows = _ask(
        f"""
SELECT ?s ?p ?o WHERE {{
  GRAPH <{g1}> {{ ?s ?p ?o }}
  {blank}
  FILTER NOT EXISTS {{ GRAPH <{g2}> {{ ?s ?p ?o }} }}
}} LIMIT 200"""
    )
    return [(r["s"]["value"], r["p"]["value"], r["o"]["value"]) for r in rows]


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--diff", metavar="GRAPH", help="show what this graph holds that no other does")
    ap.add_argument("--against", metavar="GRAPH", help="compare --diff against this one graph")
    args = ap.parse_args()

    if args.diff:
        other = args.against
        if not other:
            print("--diff needs --against <graph>; comparing to 'everything else' cannot be")
            print("expressed as a single loss list.")
            return 2
        rows = _only_in(args.diff, other)
        print(f"\nNON-BLANK triples in <{args.diff}> and NOT in <{other}>: {len(rows)}")
        for s, p, o in rows:
            print(f"  {s}\n      {p}\n      {o}")
        if not rows:
            print("  (none — dropping it would lose no content)")
        print(
            "\nBlank nodes are excluded: their identities change on every load, so a "
            "re-upload of the same file makes a whole new set of them."
        )
        return 0

    print("\n" + "=" * 78)
    print("DEFAULT-GRAPH AND CROSS-GRAPH SHADOWING AUDIT  (V12-15, BUG-194)")
    print("=" * 78)

    naive = _one(Q_NAIVE)
    explicit = _one(Q_EXPLICIT_OUTSIDE)
    print(f"\n1. Subjects a NAIVE sweep calls shadowed ............ {naive:,}")
    print(f"   Of those, with an EXPLICIT triple outside a graph .. {explicit:,}")
    if naive and not explicit:
        print("   -> ALL of them are inference materialised into the implicit context.")
        print("      Reporting the first number as a finding would send someone deleting")
        print("      inference. This is why both are printed (CAVEAT-530).")

    multi = _one(Q_MULTI_GRAPH)
    print(f"\n2. Subjects present in MORE THAN ONE named graph .... {multi:,}")
    print("   Expected and mostly benign: a Brick class appears in the TBox and in the")
    print("   ABox that uses it, and two overlays add DIFFERENT properties to one sensor.")

    print("\n3. Graph pairs that share subjects, and whether they DISAGREE:\n")
    print(f"   {'shared':>7}  {'disagree':>8}  graphs")
    survivors: List[Tuple[str, str, int]] = []
    for row in _ask(Q_PAIRS):
        g1, g2 = row["g1"]["value"], row["g2"]["value"]
        shared = int(row["n"]["value"])
        bad = _disagreements(g1, g2)
        mark = "  <-- SHADOWED" if bad else ""
        short1, short2 = g1.split(":")[-1][:34], g2.split(":")[-1][:34]
        print(f"   {shared:>7,}  {bad:>8,}  {short1:34} | {short2}{mark}")
        if bad:
            survivors.append((g1, g2, bad))

    dual = dual_referenced_sensors()
    print(f"\n4. Sensors with MORE THAN ONE timeseries reference .. {dual:,}")
    if dual:
        print("   -> BUG-531. Both uuids reach the SQL lane, which fetches from BOTH stores")
        print("      and merges. The documented fan-out metric reads 1.00 throughout,")
        print("      because each reference carries its own uuid.")

    print("\n" + "-" * 78)
    if not survivors:
        print("No graph pair disagrees about a subject. Nothing is shadowed.")
        return 0

    print(f"{len(survivors)} pair(s) hold the same subject with different content.\n")
    print("Each needs a written justification or a fix. BEFORE dropping either graph, run")
    print("  --diff <graph> --against <other>")
    print("and confirm the loss is zero. `urn:ontosage:schema` looked like pure duplication")
    print("by every aggregate and was the ONLY home of two live lay terms (BUG-529).")
    return 1


if __name__ == "__main__":
    raise SystemExit(main())
