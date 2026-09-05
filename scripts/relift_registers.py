#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Re-lift every record register into GraphDB, ignoring the graph-presence skip.

WHY THIS EXISTS
---------------
`DocumentIndexer` skips a register whose named graph already holds triples. That is the
right default — re-uploading every register on every boot is wasteful — but it means a fix
to the LIFTER cannot reach a building that has already been lifted once. BUG-422 was
exactly that: every register's `note` column had been written under the relative IRI
`<rdfs:comment>`, and correcting the serialiser changed nothing on disk because the graphs
were already populated.

This forces the rewrite. It is a maintenance action, not part of boot.

    python scripts/relift_registers.py                 # report only
    python scripts/relift_registers.py --apply         # rewrite the graphs
"""

from __future__ import annotations

import argparse
import asyncio
import sys
from pathlib import Path
from typing import List

REPO = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO))


async def _run(apply: bool) -> int:
    from orchestrator.services.building_context import resolve_building_context
    from orchestrator.services.ontology_manager import upload_ttl
    from orchestrator.services.record_documents import lift_document, to_turtle
    from shared.config import settings

    namespace = resolve_building_context(settings.BUILDING_ID).namespace
    if not namespace:
        print("no active building namespace; activate a building first")
        return 2

    docs = sorted((REPO / "input" / "documents").glob("*.md"))
    mappings = REPO / "ontology" / "record_documents"
    total = 0
    failures: List[str] = []
    for doc in docs:
        result = lift_document(doc, namespace, mappings)
        if not getattr(result, "ok", False) or not result.instances:
            continue
        comments = sum(1 for _, p, _ in result.triples if p.endswith("rdf-schema#comment"))
        print(f"  {doc.name:38s} {result.instances:3d} records  {comments:3d} comments")
        total += result.instances
        if not apply:
            continue
        outcome = await upload_ttl(to_turtle(result), result.graph_iri, replace=True)
        if not outcome.get("ok"):
            failures.append(f"{doc.name}: {outcome.get('error')}")

    print(f"\n{total} records across {len(docs)} documents")
    if failures:
        print("FAILED:")
        for f in failures:
            print("  ", f)
        return 1
    if apply:
        print("all registers rewritten")
    else:
        print("(report only — pass --apply to rewrite)")
    return 0


def main(argv: List[str]) -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--apply", action="store_true", help="rewrite the named graphs")
    args = ap.parse_args(argv)
    return asyncio.run(_run(args.apply))


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
