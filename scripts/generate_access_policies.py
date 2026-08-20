# -*- coding: utf-8 -*-
"""
generate_access_policies.py — V5-T37 (Pillar C PROTECT): policy template -> TTL.

Renders config/access_policy_template.yaml into per-building AccessPolicy triples
(<id>_policies.ttl) that ttl_uploader auto-loads. Building-agnostic: identity and
namespace come from each building folder's building.yaml.

Profiles:
  standard   the tiered template as written (k-floors, resolution tiers, rates)
  demo_open  every role gets full READ (demo: anyone asks anything). Inference-
             class denials (individual_presence / individual_pattern /
             private_content) REMAIN ACTIVE in both profiles — user decision
             2026-08-15: the system explains the building, never tracks people.
             DB writes are impossible from chat regardless of profile.

RUN (host-side, per building folder):
  python -X utf8 scripts/generate_access_policies.py                       # active input/, standard
  python -X utf8 scripts/generate_access_policies.py --profile demo_open
  python -X utf8 scripts/generate_access_policies.py --building-dir <parked-folder>
  python -X utf8 scripts/generate_access_policies.py --all                 # active + all parked
"""

from __future__ import annotations

import argparse
import sys
from datetime import datetime
from pathlib import Path
from typing import Dict, List

import yaml

_REPO = Path(__file__).resolve().parents[1]
_TEMPLATE = _REPO / "config" / "access_policy_template.yaml"


def _load_building(building_dir: Path) -> Dict[str, str]:
    by = building_dir / "building.yaml"
    if not by.is_file():
        raise SystemExit(f"[policies] no building.yaml in {building_dir}")
    cfg = yaml.safe_load(by.read_text(encoding="utf-8"))
    return {
        "id": cfg["building_id"],
        "namespace": cfg["ontology_namespace"],
        "prefix": cfg.get("ontology_prefix", "bldg"),
    }


def _tiers_str(tiers: List[Dict]) -> str:
    return ",".join(f"{t['recency_minutes']}:{t['max_resolution_seconds']}" for t in tiers)


def _policy_block(local: str, role: str, scope: str, spec: Dict, prefix: str) -> List[str]:
    lines = [
        f"{prefix}:{local} a ontosage:AccessPolicy ;",
        f'    ontosage:appliesToRole "{role}" ;',
        f'    ontosage:scopeSpaces "{scope}" ;',
        f"    ontosage:minAggregationSensors {int(spec.get('min_aggregation_sensors', 1))} ;",
        f"    ontosage:minAggregationSpaces {int(spec.get('min_aggregation_spaces', 1))} ;",
        f'    ontosage:resolutionTier "{_tiers_str(spec.get("resolution_tiers", [{"recency_minutes": 0, "max_resolution_seconds": 1}]))}" ;',
    ]
    rate = spec.get("rate_limit") or {"max_queries": 0, "per_minutes": 0}
    lines.append(
        f'    ontosage:rateLimit "{int(rate.get("max_queries", 0))}:{int(rate.get("per_minutes", 0))}" ;'
    )
    comment = str(spec.get("comment", "")).strip().replace('"', "'").replace("\n", " ")
    lines.append(f'    rdfs:comment "{comment}"@en .')
    return lines


def _render(building: Dict[str, str], template: Dict, profile: str) -> str:
    ns, prefix, bid = building["namespace"], building["prefix"], building["id"]
    now = datetime.utcnow().strftime("%Y-%m-%d %H:%M UTC")
    out: List[str] = [
        f"# {bid}_policies.ttl — AccessPolicy instances (V5-T37, profile={profile})",
        f"# GENERATED {now} by scripts/generate_access_policies.py — edit the template,",
        "# not this file. Inference-class denials are active in EVERY profile.",
        f"@prefix {prefix}: <{ns}> .",
        "@prefix ontosage: <http://ontosage.org/capabilities#> .",
        "@prefix rdfs: <http://www.w3.org/2000/01/rdf-schema#> .",
        "",
    ]

    # inference-class rules: one policy instance per rule, role "*"
    for cls, verdict in (template.get("inference_classes") or {}).items():
        out += [
            f"{prefix}:policy_inference_{cls} a ontosage:AccessPolicy ;",
            '    ontosage:appliesToRole "*" ;',
            f'    ontosage:inferenceClass "{cls}:{verdict}" ;',
            '    rdfs:comment "The system explains the building; it never tracks '
            'individuals. Denied for every role; aggregate alternatives are offered."@en .',
            "",
        ]

    open_spec = {
        "min_aggregation_sensors": 1,
        "min_aggregation_spaces": 1,
        "resolution_tiers": [{"recency_minutes": 0, "max_resolution_seconds": 1}],
        "rate_limit": {"max_queries": 0, "per_minutes": 0},
        "comment": "demo_open profile: unrestricted READ for demonstrations. "
        "Database writes remain impossible from the conversational pipeline.",
    }

    for role, spec in (template.get("policies") or {}).items():
        if profile == "demo_open":
            out += _policy_block(f"policy_{role}_demo_open", role, "any", open_spec, prefix)
            out.append("")
            continue
        # standard: a role entry is either a flat spec or named sub-scopes
        if "resolution_tiers" in spec or "scope_spaces" in spec:
            scope = spec.get("scope_spaces", "any")
            out += _policy_block(f"policy_{role}_{scope}", role, scope, spec, prefix)
            out.append("")
        else:
            rate = spec.get("rate_limit")
            for sub_name, sub in spec.items():
                if not isinstance(sub, dict) or sub_name == "rate_limit":
                    continue
                merged = dict(sub)
                if rate and "rate_limit" not in merged:
                    merged["rate_limit"] = rate
                scope = merged.get("scope_spaces", "any")
                out += _policy_block(f"policy_{role}_{sub_name}", role, scope, merged, prefix)
                out.append("")
    return "\n".join(out) + "\n"


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--profile", choices=["standard", "demo_open"], default="standard")
    ap.add_argument(
        "--building-dir", default="input", help="building folder (default: active input/)"
    )
    ap.add_argument(
        "--all", action="store_true", help="generate for input/ + every parked bldg*/ folder"
    )
    args = ap.parse_args()

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
        ttl = _render(b, template, args.profile)
        out_path = d / f"{b['id']}_policies.ttl"
        out_path.write_text(ttl, encoding="utf-8")
        n_policies = ttl.count("a ontosage:AccessPolicy")
        print(f"[policies] {out_path} — {n_policies} policy instances (profile={args.profile})")
    print("[policies] restart the orchestrator to upload (ttl_uploader SHA discovery)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
