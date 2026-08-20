#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Clear stale type assertions that live in the DEFAULT graph (BUG-203).

Each TTL is published with ``PUT ?context=urn:ontosage:ttl:<file>``, which
REPLACES that named graph and by construction cannot touch anything outside it.
A triple that reached the default graph by some earlier route is therefore immune
to every later correction: the file gets fixed, ``ttl_uploader`` reports
``uploaded=N``, and the graph keeps answering from the old copy. That is how
``retype_legacy_brick_classes.py`` can rewrite every TTL correctly and the
undeclared-type audit still report the same count afterwards.

This is the other half of that repair, and it is deliberately NOT a blanket
delete. For each stale type it first checks whether the subject already carries
the correct one:

  * it does  -> the stale triple is pure residue and is removed;
  * it does not -> the correct type is INSERTED first, because the stale triple
    is that subject's only type and deleting it would leave an untyped ghost
    that no query can reach and no file can restore. Two of bldg1's noise
    sensors were exactly this case.

Scope is "everything a TTL re-upload cannot reach", which is wider than the
default graph alone: sensor registration writes ``urn:ontosage:ds:<key>`` graphs
that no file owns either, and bldg1 had two noise sensors stale in exactly one of
those. Graphs named ``urn:ontosage:ttl:*`` ARE left alone — those come from files,
so fixing the file is the right repair and rewriting the graph would be undone on
the next upload. The mapping is imported from the retype tool so the two cannot
drift.

Usage:
    python scripts/cleanup_default_graph_types.py --dry-run
    python scripts/cleanup_default_graph_types.py
"""

from __future__ import annotations

import argparse
import json
import sys
import urllib.request
from pathlib import Path
from typing import Dict, List, Tuple

REPO = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO))

from scripts.retype_legacy_brick_classes import RETYPE  # noqa: E402

PREFIXES = {
    "brick": "https://brickschema.org/schema/Brick#",
    "ontosage": "http://ontosage.org/capabilities#",
}


def _env() -> Dict[str, str]:
    env: Dict[str, str] = {}
    p = REPO / ".env"
    if p.exists():
        for line in p.read_text(encoding="utf-8").splitlines():
            s = line.strip()
            if s and not s.startswith("#") and "=" in s:
                k, v = s.split("=", 1)
                env[k.strip()] = v.split("#", 1)[0].strip().strip('"').strip("'")
    return env


def _iri(term: str) -> str:
    pfx, local = term.split(":", 1)
    return PREFIXES[pfx] + local


def _endpoint() -> Tuple[str, str]:
    env = _env()
    base = (env.get("GRAPHDB_URL") or "http://localhost:7200").replace("graphdb:", "localhost:")
    return base.rstrip("/"), env.get("GRAPHDB_REPOSITORY", "bldg")


def _select(query: str) -> List[dict]:
    base, repo = _endpoint()
    req = urllib.request.Request(
        f"{base}/repositories/{repo}",
        data=query.encode(),
        headers={
            "Content-Type": "application/sparql-query",
            "Accept": "application/sparql-results+json",
        },
    )
    with urllib.request.urlopen(req, timeout=120) as resp:
        return json.load(resp).get("results", {}).get("bindings", [])


def _update(query: str) -> None:
    base, repo = _endpoint()
    req = urllib.request.Request(
        f"{base}/repositories/{repo}/statements",
        data=query.encode(),
        headers={"Content-Type": "application/sparql-update"},
    )
    with urllib.request.urlopen(req, timeout=300):
        pass


def main(argv: List[str]) -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--dry-run", action="store_true", help="report without changing the graph")
    args = ap.parse_args(argv)

    total_rescued = total_removed = 0
    for stale, correct in RETYPE.items():
        s_iri, c_iri = _iri(stale), _iri(correct)

        rows = _select(
            f"SELECT (COUNT(DISTINCT ?s) AS ?n) WHERE {{ "
            f"  ?s a <{s_iri}> . "
            f"  FILTER NOT EXISTS {{ GRAPH ?tg {{ ?s a <{s_iri}> . "
            f'    FILTER(STRSTARTS(STR(?tg), "urn:ontosage:ttl:")) }} }} '
            f"}}"
        )
        stale_n = int(rows[0]["n"]["value"]) if rows else 0
        if not stale_n:
            continue

        rows = _select(
            f"SELECT (COUNT(DISTINCT ?s) AS ?n) WHERE {{ "
            f"  ?s a <{s_iri}> . "
            f"  FILTER NOT EXISTS {{ ?s a <{c_iri}> }} "
            f"  FILTER NOT EXISTS {{ GRAPH ?tg {{ ?s a <{s_iri}> . "
            f'    FILTER(STRSTARTS(STR(?tg), "urn:ontosage:ttl:")) }} }} '
            f"}}"
        )
        orphan_n = int(rows[0]["n"]["value"]) if rows else 0

        print(f"  {stale} -> {correct}: {stale_n} stale, {orphan_n} would be left untyped")
        if args.dry_run:
            total_rescued += orphan_n
            total_removed += stale_n
            continue

        if orphan_n:
            # Give them the correct type BEFORE removing their only one.
            _update(
                f"INSERT {{ ?s a <{c_iri}> }} WHERE {{ "
                f"  ?s a <{s_iri}> . "
                f"  FILTER NOT EXISTS {{ ?s a <{c_iri}> }} "
                f"}}"
            )
            total_rescued += orphan_n

        # Remove from the default graph AND from any non-ttl named graph
        # (datasource graphs are generated, so no file can correct them).
        _update(
            f"DELETE {{ ?s a <{s_iri}> }} WHERE {{ "
            f"  ?s a <{s_iri}> . "
            f"  FILTER NOT EXISTS {{ GRAPH ?tg {{ ?s a <{s_iri}> . "
            f'    FILTER(STRSTARTS(STR(?tg), "urn:ontosage:ttl:")) }} }} '
            f"}}"
        )
        _update(
            f"DELETE {{ GRAPH ?g {{ ?s a <{s_iri}> }} }} WHERE {{ "
            f"  GRAPH ?g {{ ?s a <{s_iri}> }} "
            f'  FILTER(!STRSTARTS(STR(?g), "urn:ontosage:ttl:")) '
            f"}}"
        )
        total_removed += stale_n

    verb = "would rescue/remove" if args.dry_run else "rescued/removed"
    print(f"\n{verb}: {total_rescued} retyped in place, {total_removed} stale assertions cleared")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
