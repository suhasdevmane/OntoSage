# -*- coding: utf-8 -*-
"""
generate_compliance_register.py — V5-T05 (shape S3): register template -> TTL.

Renders config/compliance_register_template.yaml into per-building
ComplianceCheck triples (<id>_compliance.ttl). Dates live in the graph, so
due/overdue/history questions are SPARQL queries (TTL-first).

Dev-mode semantics (synthetic-but-declared): each item gets `history_cycles`
completed past checks (completedDate = dueDate +/- deterministic jitter) and
one CURRENT check — open and due in the future, except the template's
`dev_overdue_items`, which are forced overdue so the register always contains
true positives. Every instance carries ontosage:isSimulated true.

RUN:
  python -X utf8 scripts/generate_compliance_register.py                 # active input/
  python -X utf8 scripts/generate_compliance_register.py --all           # + parked folders
  python -X utf8 scripts/generate_compliance_register.py --now 2026-08-15T12:00:00
"""

from __future__ import annotations

import argparse
import hashlib
import sys
from datetime import datetime, timedelta
from pathlib import Path
from typing import Dict, List

import yaml

_REPO = Path(__file__).resolve().parents[1]
_TEMPLATE = _REPO / "config" / "compliance_register_template.yaml"
_FMT = "%Y-%m-%dT%H:%M:%S"


def _load_building(building_dir: Path) -> Dict[str, str]:
    cfg = yaml.safe_load((building_dir / "building.yaml").read_text(encoding="utf-8"))
    return {
        "id": cfg["building_id"],
        "namespace": cfg["ontology_namespace"],
        "prefix": cfg.get("ontology_prefix", "bldg"),
    }


def _jitter_hours(seed: str, span: int = 48) -> int:
    """Deterministic jitter in [-span/2, +span/2) hours from a string seed."""
    h = int(hashlib.sha256(seed.encode()).hexdigest()[:8], 16)
    return (h % span) - span // 2


def render(building: Dict[str, str], template: Dict, now: datetime) -> str:
    prefix, ns, bid = building["prefix"], building["namespace"], building["id"]
    overdue_forced = set(template.get("dev_overdue_items") or [])
    default_cycles = int((template.get("defaults") or {}).get("history_cycles", 6))

    lines: List[str] = [
        f"# {bid}_compliance.ttl — ComplianceCheck register (V5-T05, S3: dates as triples)",
        f"# GENERATED {now.strftime(_FMT)} by scripts/generate_compliance_register.py.",
        "# Synthetic-but-declared (isSimulated true). Real buildings upload their actual",
        "# register in this same shape via the admin portal.",
        f"@prefix {prefix}: <{ns}> .",
        "@prefix ontosage: <http://ontosage.org/capabilities#> .",
        "@prefix rdfs: <http://www.w3.org/2000/01/rdf-schema#> .",
        "@prefix xsd: <http://www.w3.org/2001/XMLSchema#> .",
        "",
    ]

    n_open = n_overdue = n_done = 0
    for item in template.get("items", []):
        iid = item["id"]
        freq = timedelta(days=int(item["frequency_days"]))
        cycles = int(item.get("history_cycles", default_cycles))
        role = str(item.get("responsible_role", "facility_manager"))
        label = str(item["label"]).replace('"', "'")

        # anchor the cycle deterministically per building+item
        anchor_shift = timedelta(hours=_jitter_hours(f"{bid}:{iid}:anchor", 96))
        current_due = now + (freq / 2) + anchor_shift
        if iid in overdue_forced:
            current_due = now - (freq / 4) - abs(anchor_shift) - timedelta(days=1)

        # completed history, newest first walking back from the current due date
        for k in range(1, cycles + 1):
            due_k = current_due - k * freq
            done_k = due_k + timedelta(hours=_jitter_hours(f"{bid}:{iid}:{k}", 72))
            local = f"compliance_{iid}_{k:02d}"
            lines += [
                f"{prefix}:{local} a ontosage:ComplianceCheck ;",
                f'    rdfs:label "{label} (cycle -{k})"@en ;',
                f'    ontosage:dueDate "{due_k.strftime(_FMT)}"^^xsd:dateTime ;',
                f'    ontosage:completedDate "{done_k.strftime(_FMT)}"^^xsd:dateTime ;',
                '    ontosage:recordStatus "done" ;',
                f'    ontosage:responsibleRole "{role}" ;',
                "    ontosage:isSimulated true .",
                "",
            ]
            n_done += 1

        status = "open"
        local = f"compliance_{iid}_current"
        lines += [
            f"{prefix}:{local} a ontosage:ComplianceCheck ;",
            f'    rdfs:label "{label}"@en ;',
            f'    ontosage:dueDate "{current_due.strftime(_FMT)}"^^xsd:dateTime ;',
            f'    ontosage:recordStatus "{status}" ;',
            f'    ontosage:responsibleRole "{role}" ;',
            "    ontosage:isSimulated true .",
            "",
        ]
        if current_due < now:
            n_overdue += 1
        else:
            n_open += 1

    lines.insert(4, f"# state at generation: done={n_done} open={n_open} OVERDUE={n_overdue}")
    return "\n".join(lines) + "\n"


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--building-dir", default="input")
    ap.add_argument("--all", action="store_true")
    ap.add_argument("--now", default=None, help="freeze the clock (ISO) — used by tests")
    args = ap.parse_args()

    now = datetime.strptime(args.now, _FMT) if args.now else datetime.utcnow()
    template = yaml.safe_load(_TEMPLATE.read_text(encoding="utf-8"))

    dirs = []
    if args.all:
        for d in [_REPO / "input"] + sorted(_REPO.glob("bldg*")):
            if d.is_dir() and (d / "building.yaml").is_file():
                dirs.append(d)
    else:
        dirs.append(_REPO / args.building_dir)

    for d in dirs:
        b = _load_building(d)
        ttl = render(b, template, now)
        out = d / f"{b['id']}_compliance.ttl"
        out.write_text(ttl, encoding="utf-8")
        print(f"[compliance] {out} — {ttl.count('a ontosage:ComplianceCheck')} checks")
    print("[compliance] restart the orchestrator to upload (ttl_uploader SHA discovery)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
