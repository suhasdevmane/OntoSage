#!/usr/bin/env python3
"""Run entity enrichment (Part D) standalone — typically inside the orchestrator
container where GraphDB (host 'graphdb') resolves:

    docker cp scripts/enrich_entities.py ontosage-orchestrator:/tmp/
    docker exec ontosage-orchestrator python /tmp/enrich_entities.py --dry-run
    docker exec ontosage-orchestrator python /tmp/enrich_entities.py

--dry-run reports what WOULD be enriched (and any unmapped points to add to
config/entity_enrichment.yaml) without writing the overlay graph.
"""

import asyncio
import sys


async def _main() -> int:
    from orchestrator.services.entity_enricher import (
        EntityEnricher,
        run_entity_enrichment,
    )

    if "--dry-run" in sys.argv:
        report = await EntityEnricher().enrich(dry_run=True)
        print("DRY-RUN:", report.summary())
        for ln in report.unmapped[:30]:
            print("  unmapped (no class):", ln)
    else:
        report = await run_entity_enrichment()
        print(report.summary())
    return 0


if __name__ == "__main__":
    raise SystemExit(asyncio.run(_main()))
