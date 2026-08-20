# -*- coding: utf-8 -*-
"""V5-T32 — onboarding validator CLI: what does THIS building unlock, and why not?

Run inside the orchestrator container (it needs GraphDB + adapters):

  docker exec ontosage-orchestrator python /app/scripts/check_onboarding.py

or on the host with the stack up and ports published. Writes
``scripts/outputs/onboarding_<building>_<ts>.md`` and prints the table.

Exit code 0 always — this is a REPORT, not a gate; the swap/boot path uses it
to tell an operator what is missing, never to refuse a building.
"""

from __future__ import annotations

import asyncio
import sys
from datetime import datetime
from pathlib import Path

_REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(_REPO))


async def main() -> int:
    from orchestrator.services.adapters.registry import adapter_registry
    from orchestrator.services.deliberation.live import sparql_exec
    from orchestrator.services.onboarding_report import (
        build_unlock_report,
        gather_facts,
        render_report,
    )
    from shared.config import settings

    try:
        await adapter_registry.initialize()
    except Exception:  # already initialised inside the app process
        pass

    building = settings.BUILDING_ID
    facts = await gather_facts(building, settings.BUILDING_NAMESPACE, sparql_exec)
    statuses = build_unlock_report(facts)
    text = render_report(building, facts, statuses)
    print(text)

    # scripts/ is mounted READ-ONLY in the container (V5-T32), so fall back to
    # the writable outputs mount — the report must always land somewhere
    name = f"onboarding_{building}_{datetime.now():%Y%m%d_%H%M%S}.md"
    for out_dir in (_REPO / "scripts" / "outputs", Path("/app/outputs"), _REPO / "outputs"):
        try:
            out_dir.mkdir(parents=True, exist_ok=True)
            path = out_dir / name
            path.write_text(text, encoding="utf-8")
            print(f"-> {path}")
            break
        except OSError:
            continue
    else:
        print("(report not written: no writable output directory)")
    return 0


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
