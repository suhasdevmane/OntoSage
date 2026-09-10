# -*- coding: utf-8 -*-
"""V5-T32 — onboarding validator CLI: what does THIS building unlock, and why not?

Run inside the orchestrator container (it needs GraphDB + adapters):

  docker exec ontosage-orchestrator python /app/scripts/check_onboarding.py

The host is NOT a supported place to run it: the registry's hostnames are
container-internal, so from the host every store lookup returns nothing and the
report would describe an empty building. It refuses there rather than pretend.

Writes ``scripts/outputs/onboarding_<building>_<ts>.md`` and prints the table.

Exit 0 when a report was produced — this is a REPORT, not a gate; the swap/boot
path uses it to tell an operator what is missing, never to refuse a building.

Exit 2 when the adapters cannot be reached, because then the report would be
about this PROCESS rather than about the building, and a table of zeros reads
exactly like a building that is missing everything.
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

    # AN UNMEASURABLE BUILDING IS NOT AN EMPTY ONE.
    #
    # This was `except Exception: pass`, on the reasoning that the registry is already
    # initialised inside the app process. True there — and on the HOST, where the
    # registry's hostnames are container-internal, initialisation fails, every store
    # lookup returns nothing, and the report is emitted anyway. Measured on a healthy
    # bldg1, from the host:
    #
    #     history: 0.0 days · events rows: 0 · adjacency edges: 0 · 4/11 unlocked
    #
    # against the same building, from inside the container, the same minute:
    #
    #     history: 8.0 days · events rows: 98,139 · adjacency edges: 270 · 10/11 unlocked
    #
    # The first was written to disk with exit code 0 and reads as authoritative. Someone
    # would open defects against a building that answers those questions perfectly well.
    # `certify_building.py` already states the rule this needs: a run that cannot be
    # trusted is better not started than explained away afterwards.
    adapters_ok = True
    init_error = ""
    try:
        await adapter_registry.initialize()
    except Exception as exc:
        adapters_ok = False
        init_error = f"{type(exc).__name__}: {exc}"
    if adapters_ok and not getattr(adapter_registry, "is_available", False):
        # No exception, no adapters: the same blindness by a quieter route.
        adapters_ok = False
        init_error = "no time-series adapters registered"
    if not adapters_ok:
        print(
            "REFUSING TO REPORT — the time-series adapters are not reachable from here\n"
            f"  {init_error}\n\n"
            "Every store lookup would return nothing and this report would say the "
            "building is far less capable than it is: on a healthy building that is the "
            "difference between 4/11 and 10/11 capabilities.\n\n"
            "Run it where the adapters live:\n"
            "  docker exec ontosage-orchestrator python /app/scripts/check_onboarding.py"
        )
        return 2

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
