# -*- coding: utf-8 -*-
"""
saturate_building.py — provision simulated sensors for every coverage gap (V4-T08).

Runs the coverage audit against the ACTIVE building, then writes one TTL per
modality with gaps (input/<id>_saturation_<modality>.ttl) plus the zoneId join-key
file (input/<id>_saturation_zoneids.ttl). Files auto-upload on the next
orchestrator restart via ttl_uploader's <BUILDING_ID>_*.ttl discovery, each into
its own named graph — which doubles as the per-modality on/off switch.

Building-agnostic: identity, namespace, modality set and storage keys all come
from the active building's config. Deterministic: re-runs are byte-identical.

RUN (stack up):
  python scripts/saturate_building.py --dry-run     # show the plan, write nothing
  python scripts/saturate_building.py               # write TTLs into input/
"""

from __future__ import annotations

import argparse
import asyncio
import sys
from pathlib import Path

_SCRIPT_DIR = Path(__file__).resolve().parent
_REPO_ROOT = _SCRIPT_DIR.parent
sys.path.insert(0, str(_REPO_ROOT))

from orchestrator.services.deliberation.coverage_audit import (  # noqa: E402
    CoverageAuditor,
    load_modalities,
)
from orchestrator.services.deliberation.live import (  # noqa: E402
    active_identity,
    sparql_exec,
)
from orchestrator.services.deliberation.saturation import (  # noqa: E402
    build_saturation_ttl,
    build_zoneid_ttl,
    plan_saturation,
)


async def _run(dry_run: bool, only: list = None) -> int:
    identity = active_identity()
    building_id = identity["BUILDING_ID"]
    namespace = identity["BUILDING_NAMESPACE"]
    input_dir = _REPO_ROOT / "input"
    if not input_dir.exists():
        print("[saturate] ERROR: no active building (input/ absent) — activate one first")
        return 1
    print(f"[saturate] building={building_id} namespace={namespace}")

    modalities = load_modalities(building_id)
    if only:
        wanted = {m.strip().lower() for m in only}
        known = {m.name.lower() for m in modalities}
        missing = wanted - known
        if missing:
            print(f"[saturate] ERROR: unknown modality: {', '.join(sorted(missing))}")
            return 1
        modalities = [m for m in modalities if m.name.lower() in wanted]
        print(
            f"[saturate] restricted to {len(modalities)} modality(ies): "
            f"{', '.join(m.name for m in modalities)}"
        )
    auditor = CoverageAuditor(sparql_exec, modalities)
    spaces = await auditor.audit(namespace)
    if not spaces:
        print("[saturate] ERROR: no spaces discovered — is the ontology loaded?")
        return 1

    # V5-T09: building-scoped modalities anchor to the building entity
    building_iri = None
    try:
        res = await sparql_exec(
            "PREFIX brick: <https://brickschema.org/schema/Brick#> "
            "SELECT ?b WHERE { ?b a brick:Building . "
            f'FILTER(STRSTARTS(STR(?b), "{namespace}")) }} LIMIT 1'
        )
        binds = res.get("results", {}).get("bindings", [])
        if binds:
            building_iri = binds[0]["b"]["value"]
    except Exception as exc:
        print(f"[saturate] building-entity lookup failed ({exc}) — using namespace fallback")

    plan = plan_saturation(building_id, namespace, spaces, modalities, building_iri=building_iri)
    total = sum(len(v) for v in plan.values())
    print(
        f"[saturate] {len(spaces)} spaces -> {total} simulated sensors across {len(plan)} modalities"
    )
    for modality, items in sorted(plan.items()):
        print(f"  {modality:<16} {len(items):>4} sensors -> table {items[0].table}")

    if dry_run:
        print("[saturate] --dry-run: nothing written")
        return 0

    written = []
    for modality, items in sorted(plan.items()):
        path = input_dir / f"{building_id}_saturation_{modality}.ttl"
        path.write_text(build_saturation_ttl(namespace, modality, items), encoding="utf-8")
        written.append(path.name)
    zone_path = input_dir / f"{building_id}_saturation_zoneids.ttl"
    zone_path.write_text(build_zoneid_ttl(namespace, spaces), encoding="utf-8")
    written.append(zone_path.name)

    print(f"[saturate] wrote {len(written)} files into input/:")
    for name in written:
        print(f"  {name}")
    print("[saturate] restart the orchestrator to auto-upload (ttl_uploader SHA discovery)")
    return 0


def main() -> int:
    parser = argparse.ArgumentParser(description="SATURATE provisioner (V4-T08)")
    parser.add_argument("--dry-run", action="store_true", help="Plan only; write nothing")
    parser.add_argument(
        "--only",
        default="",
        help="Comma-separated modality names to provision (default: all with gaps). "
        "Provisioning is additive per modality — each writes its own TTL and its own "
        "named graph — so filling one gap never has to mean generating the other twenty.",
    )
    args = parser.parse_args()
    return asyncio.run(_run(args.dry_run, [x for x in args.only.split(",") if x.strip()]))


if __name__ == "__main__":
    sys.exit(main())
