#!/usr/bin/env python3
"""
backfill_db_sensor_ttls.py — persist pre-migration DB sensor graphs to ``input/``.

Before sensors were made TTL-first, the admin "Register Sensors" flow wrote Brick triples straight
into a GraphDB named graph ``urn:ontosage:db:<key>`` with no backing file. Those triples vanish on
a GraphDB volume reset and are NOT reloaded on restart. This one-shot script finds every such
legacy graph, dumps it to ``input/db_<key>_sensors.ttl`` (the new source of truth), and syncs that
file's own graph — so nothing already registered is ever lost.

Run it ONCE against a live stack, ideally inside the orchestrator container so ``GRAPHDB_URL`` and
the ``input/`` mount resolve the same way the app sees them:

    docker exec ontosage-orchestrator python scripts/backfill_db_sensor_ttls.py --dry-run
    docker exec ontosage-orchestrator python scripts/backfill_db_sensor_ttls.py
    docker exec ontosage-orchestrator python scripts/backfill_db_sensor_ttls.py --drop-old

Idempotent: re-running merges (never drops) and skips graphs that yield no triples.
"""

from __future__ import annotations

import argparse
import asyncio
import sys
from pathlib import Path
from typing import List, Optional

# Allow `python scripts/backfill_db_sensor_ttls.py` from the repo root.
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import httpx  # noqa: E402

from orchestrator.services import db_ontology  # noqa: E402
from orchestrator.services.input_ttl_store import persist_ttl_file  # noqa: E402
from orchestrator.services.ontology_manager import (  # noqa: E402
    drop_named_graph,
    list_named_graphs,
)
from shared.config import settings  # noqa: E402
from shared.utils import get_logger  # noqa: E402

logger = get_logger(__name__)

_LEGACY_PREFIX = "urn:ontosage:db:"


def _auth() -> Optional[tuple]:
    if settings.GRAPHDB_USER and settings.GRAPHDB_PASSWORD:
        return (settings.GRAPHDB_USER, settings.GRAPHDB_PASSWORD)
    return None


async def _construct_graph_ttl(graph_uri: str, client: httpx.AsyncClient) -> str:
    """CONSTRUCT every triple in ``graph_uri`` and return it serialized as Turtle."""
    query = f"CONSTRUCT {{ ?s ?p ?o }} WHERE {{ GRAPH <{graph_uri}> {{ ?s ?p ?o }} }}"
    endpoint = f"{settings.GRAPHDB_URL.rstrip('/')}/repositories/{settings.GRAPHDB_REPOSITORY}"
    resp = await client.post(
        endpoint,
        content=query.encode("utf-8"),
        headers={"Content-Type": "application/sparql-query", "Accept": "text/turtle"},
        auth=_auth(),
    )
    resp.raise_for_status()
    return resp.text


async def backfill(*, dry_run: bool = False, drop_old: bool = False) -> int:
    """Dump every legacy ``urn:ontosage:db:*`` graph to input/. Returns exit code (0 = ok)."""
    graphs = await list_named_graphs()
    legacy = {g: n for g, n in graphs.items() if g.startswith(_LEGACY_PREFIX)}
    if not legacy:
        logger.info("[backfill] no legacy urn:ontosage:db:* graphs found — nothing to do")
        return 0

    logger.info(f"[backfill] found {len(legacy)} legacy DB graph(s): {sorted(legacy)}")
    failures: List[str] = []

    async with httpx.AsyncClient(timeout=120.0) as client:
        for graph_uri, triple_count in sorted(legacy.items()):
            db_key = graph_uri[len(_LEGACY_PREFIX) :]
            filename = db_ontology.sensors_filename(db_key)
            try:
                ttl = await _construct_graph_ttl(graph_uri, client)
            except Exception as e:
                logger.error(f"[backfill] CONSTRUCT <{graph_uri}> failed: {e}")
                failures.append(graph_uri)
                continue

            if not ttl.strip():
                logger.warning(f"[backfill] <{graph_uri}> returned no triples — skipping")
                continue

            if dry_run:
                logger.info(
                    f"[backfill] DRY-RUN would write input/{filename} "
                    f"({triple_count} triples from <{graph_uri}>)"
                    + (" and drop the legacy graph" if drop_old else "")
                )
                continue

            res = await persist_ttl_file(filename, ttl, merge=True, client=client)
            if not res.get("ok"):
                logger.error(f"[backfill] persist input/{filename} failed: {res}")
                failures.append(graph_uri)
                continue
            logger.info(f"[backfill] wrote input/{filename} + synced {res.get('graph')}")

            if drop_old:
                dropped = await drop_named_graph(graph_uri, client=client)
                logger.info(
                    f"[backfill] legacy <{graph_uri}> {'dropped' if dropped else 'DROP FAILED'}"
                )
                if not dropped:
                    failures.append(graph_uri)

    if failures:
        logger.error(f"[backfill] completed with {len(failures)} failure(s): {failures}")
        return 1
    logger.info("[backfill] done — all legacy DB graphs persisted to input/")
    return 0


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--dry-run", action="store_true", help="print what would be written; make no changes"
    )
    parser.add_argument(
        "--drop-old",
        action="store_true",
        help="after a successful write, drop the legacy urn:ontosage:db:<key> graph",
    )
    args = parser.parse_args()
    rc = asyncio.run(backfill(dry_run=args.dry_run, drop_old=args.drop_old))
    sys.exit(rc)


if __name__ == "__main__":
    main()
