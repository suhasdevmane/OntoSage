# -*- coding: utf-8 -*-
"""
audit_coverage.py — run the SATURATE coverage audit against the ACTIVE building (V4-T06).

Emits the space × modality gap matrix as CSV plus a per-modality summary table.
Building-agnostic: namespace, building id and modality set all come from the
active building's config — no literals here.

RUN (stack up):
  python scripts/audit_coverage.py                       # active building, default output
  python scripts/audit_coverage.py --out my_gaps.csv     # explicit output path
"""

from __future__ import annotations

import argparse
import asyncio
import csv
import sys
from datetime import datetime
from pathlib import Path
from typing import Any, Dict

_SCRIPT_DIR = Path(__file__).resolve().parent
_REPO_ROOT = _SCRIPT_DIR.parent
sys.path.insert(0, str(_REPO_ROOT))

from orchestrator.services.deliberation.coverage_audit import (  # noqa: E402
    STATUS_MISSING,
    STATUS_PRESENT,
    STATUS_UNBACKED,
    CoverageAuditor,
    load_modalities,
)
from orchestrator.services.deliberation.live import active_identity, sparql_exec  # noqa: E402

_OUTPUT_DIR = _SCRIPT_DIR / "outputs" / "coverage"

_sparql_exec = sparql_exec
_active_identity = active_identity


async def _run(out_path: Path) -> int:
    identity = _active_identity()
    building_id = identity["BUILDING_ID"]
    namespace = identity["BUILDING_NAMESPACE"]
    print(f"[audit] building={building_id} namespace={namespace}")

    modalities = load_modalities(building_id)
    auditor = CoverageAuditor(_sparql_exec, modalities)
    spaces = await auditor.audit(namespace)
    if not spaces:
        print("[audit] ERROR: no spaces discovered — is the ontology loaded?")
        return 1

    rows = CoverageAuditor.to_rows(building_id, spaces)
    out_path.parent.mkdir(parents=True, exist_ok=True)
    with open(out_path, "w", encoding="utf-8", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=list(rows[0].keys()), lineterminator="\n")
        writer.writeheader()
        writer.writerows(rows)

    summary = CoverageAuditor.summary(spaces)
    print(f"\n[audit] {len(spaces)} spaces x {len(modalities)} modalities -> {out_path}")
    print(f"{'modality':<16} {'present':>8} {'unbacked':>9} {'missing':>8} {'coverage':>9}")
    for modality, agg in sorted(summary.items()):
        pct = 100 * agg[STATUS_PRESENT] / agg["total"] if agg["total"] else 0
        print(
            f"{modality:<16} {agg[STATUS_PRESENT]:>8} {agg[STATUS_UNBACKED]:>9} "
            f"{agg[STATUS_MISSING]:>8} {pct:>8.1f}%"
        )
    return 0


def main() -> int:
    parser = argparse.ArgumentParser(description="SATURATE coverage audit (V4-T06)")
    parser.add_argument("--out", default=None, help="Output CSV path")
    args = parser.parse_args()
    ts = datetime.now().strftime("%Y%m%d_%H%M%S")
    bid = _active_identity()["BUILDING_ID"]
    out = Path(args.out) if args.out else _OUTPUT_DIR / f"coverage_{bid}_{ts}.csv"
    return asyncio.run(_run(out))


if __name__ == "__main__":
    sys.exit(main())
