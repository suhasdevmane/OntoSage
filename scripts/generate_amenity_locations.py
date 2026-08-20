# -*- coding: utf-8 -*-
"""
generate_amenity_locations.py — emit structured amenity individuals (V4-T12).

Writes input/<id>_amenity_locations.ttl: per-floor DrinkingWater / ToiletFacility /
StudyArea individuals located in real spaces from the active building's graph.
Auto-uploads on the next orchestrator restart (ttl_uploader discovery).

RUN (stack up):
  python scripts/generate_amenity_locations.py --dry-run
  python scripts/generate_amenity_locations.py
"""

from __future__ import annotations

import argparse
import asyncio
import sys
from pathlib import Path

_SCRIPT_DIR = Path(__file__).resolve().parent
_REPO_ROOT = _SCRIPT_DIR.parent
sys.path.insert(0, str(_REPO_ROOT))

from orchestrator.services.deliberation.amenities import (
    build_amenity_ttl,
    plan_amenities,
)  # noqa: E402
from orchestrator.services.deliberation.coverage_audit import (  # noqa: E402
    CoverageAuditor,
    load_modalities,
)
from orchestrator.services.deliberation.live import active_identity, sparql_exec  # noqa: E402


async def _run(dry_run: bool) -> int:
    identity = active_identity()
    building_id, namespace = identity["BUILDING_ID"], identity["BUILDING_NAMESPACE"]
    input_dir = _REPO_ROOT / "input"
    if not input_dir.exists():
        print("[amenities] ERROR: no active building (input/ absent)")
        return 1
    print(f"[amenities] building={building_id}")

    auditor = CoverageAuditor(sparql_exec, load_modalities(building_id))
    spaces = await auditor.discover_spaces(namespace)
    if not spaces:
        print("[amenities] ERROR: no spaces discovered")
        return 1

    plan = plan_amenities(spaces)
    for kind, placements in sorted(plan.items()):
        for p in placements:
            print(f"  {kind:<16} floor {p['floor']:<8} -> {p['space_label']}")
    if dry_run:
        print("[amenities] --dry-run: nothing written")
        return 0

    path = input_dir / f"{building_id}_amenity_locations.ttl"
    path.write_text(build_amenity_ttl(namespace, plan), encoding="utf-8")
    print(f"[amenities] wrote {path.name} — restart the orchestrator to upload")
    return 0


def main() -> int:
    parser = argparse.ArgumentParser(description="Amenity ABox generator (V4-T12)")
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args()
    return asyncio.run(_run(args.dry_run))


if __name__ == "__main__":
    sys.exit(main())
