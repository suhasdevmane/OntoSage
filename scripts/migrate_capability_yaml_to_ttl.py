#!/usr/bin/env python3
"""
migrate_capability_yaml_to_ttl.py — one-shot, building-agnostic migration of a
legacy ``capability.yaml`` into ontosage capability TRIPLES (TODO-012).

Every ``capability.yaml`` entry already carries exactly what a triple needs:

    id       -> local name           (bldg:Cap_<id>)
    keywords -> ontosage:layTerms     (deterministic lay-term matching)
    content  -> ontosage:answerText   (the answer prose)
    category -> ontosage:capabilityCategory
    source   -> ontosage:note

so the conversion is loss-free and reproducible. Physical facilities
(AMENITIES / ACCESSIBILITY) dual-type ``ontosage:Amenity``; everything else
dual-types ``ontosage:KnowledgeTopic`` (information / procedure). The result is a
single ``<building_id>_capabilities.ttl`` — the SAME triple shape the admin
Capabilities GUI writes (``capability_admin.build_amenity_ttl``) — that the
CapabilityGraphResolver answers directly. capability.yaml is then redundant.

Building-agnostic: reads the active building's namespace from building.yaml; no
building literals in this script. Idempotent: re-running regenerates the file.

Usage:
    python scripts/migrate_capability_yaml_to_ttl.py --building-dir bldg1
    python scripts/migrate_capability_yaml_to_ttl.py --building-dir bldg1 --dry-run
"""

from __future__ import annotations

import argparse
import re
import sys
from pathlib import Path
from typing import Dict, List, Optional

import yaml

_ONTO_NS = "http://ontosage.org/capabilities#"
_LOCALNAME_RE = re.compile(r"^[A-Za-z][A-Za-z0-9_.\-]{0,63}$")

# category -> (ontosage class, dual-type). Physical facilities are Amenity; the rest are
# knowledge topics. The resolver matches on layTerms regardless of subclass, so the class
# is primarily for schema fidelity / GUI editability.
_AMENITY_CATEGORIES = {"AMENITIES", "ACCESSIBILITY"}
_PROCEDURE_HINTS = ("report", "complaint", "booking", "evacuat", "lost", "how")


def _esc(s: str) -> str:
    """Escape a literal for Turtle (backslash, quote, newline)."""
    return (
        (s or "")
        .replace("\\", "\\\\")
        .replace('"', '\\"')
        .replace("\r\n", "\n")
        .replace("\n", "\\n")
        .strip()
    )


def _localname(entry_id: str) -> str:
    ln = "Cap_" + re.sub(r"[^A-Za-z0-9_.\-]", "_", entry_id.strip())
    return ln if _LOCALNAME_RE.match(ln) else "Cap_" + re.sub(r"\W", "_", entry_id)[:56]


def _label(entry_id: str) -> str:
    return entry_id.replace("_", " ").strip().title()


def _classify(entry: Dict) -> tuple:
    """Return (cls, second_type, capability_category)."""
    cat = (entry.get("category") or "").upper()
    eid = (entry.get("id") or "").lower()
    if cat in _AMENITY_CATEGORIES:
        return "Amenity", "ontosage:Amenity", cat.title()
    if any(h in eid for h in _PROCEDURE_HINTS):
        return "Procedure", "ontosage:KnowledgeTopic", "PROCEDURE"
    return "InformationTopic", "ontosage:KnowledgeTopic", "INFORMATION"


def _entry_ttl(ns: str, entry: Dict) -> Optional[str]:
    eid = entry.get("id")
    if not eid:
        return None
    cls, second_type, cap_cat = _classify(entry)
    local = _localname(eid)
    label = _label(eid)
    lay = ", ".join(entry.get("keywords") or [])
    answer = entry.get("content") or ""
    note = entry.get("source") or ""

    lines = [
        f"bldg:{local} a ontosage:{cls}, {second_type} ;",
        f'    rdfs:label "{_esc(label)}"@en ;',
    ]
    for prop, val in (
        ("capabilityCategory", cap_cat),
        ("layTerms", lay),
        ("answerText", answer),
        ("note", note),
    ):
        if (val or "").strip():
            lines.append(f'    ontosage:{prop} "{_esc(val)}" ;')
    lines[-1] = lines[-1].rstrip().rstrip(";").rstrip() + " ."
    return "\n".join(lines)


def _namespace(building_dir: Path, building_id: str) -> str:
    """Resolve the building's ontology namespace from building.yaml (building-agnostic)."""
    by = building_dir / "building.yaml"
    if by.exists():
        data = yaml.safe_load(by.read_text(encoding="utf-8")) or {}
        ns = data.get("ontology_namespace") or data.get("namespace")
        if ns:
            return ns if ns.endswith(("#", "/")) else ns + "#"
    raise SystemExit(
        f"[migrate] cannot resolve ontology namespace: no building.yaml with "
        f"ontology_namespace in {building_dir}"
    )


def migrate(building_dir: Path, building_id: str, dry_run: bool = False) -> int:
    cap_yaml = building_dir / "capability.yaml"
    if not cap_yaml.exists():
        print(f"[migrate] no capability.yaml in {building_dir} — nothing to do")
        return 0
    data = yaml.safe_load(cap_yaml.read_text(encoding="utf-8")) or {}
    entries: List[Dict] = data.get("capabilities") or []
    if not entries:
        print(f"[migrate] capability.yaml has no 'capabilities' entries")
        return 0

    ns = _namespace(building_dir, building_id)
    header = (
        f"# {building_id} capabilities — GENERATED from capability.yaml by\n"
        f"# scripts/migrate_capability_yaml_to_ttl.py (TODO-012). Do not hand-edit; either\n"
        f"# re-run the migration or author via the admin Capabilities GUI / OCBV TBox.\n"
        f"# Each entry is a dual-typed ontosage:Amenity / ontosage:KnowledgeTopic instance,\n"
        f"# answered live by the CapabilityGraphResolver (lay-term match on ontosage:layTerms).\n\n"
        f"@prefix bldg:     <{ns}> .\n"
        f"@prefix ontosage: <{_ONTO_NS}> .\n"
        f"@prefix rdfs:     <http://www.w3.org/2000/01/rdf-schema#> .\n\n"
    )
    blocks = [b for e in entries if (b := _entry_ttl(ns, e))]
    body = "\n\n".join(blocks) + "\n"
    out = building_dir / f"{building_id}_capabilities.ttl"

    n_amenity = sum(1 for e in entries if (e.get("category") or "").upper() in _AMENITY_CATEGORIES)
    print(
        f"[migrate] {building_id}: {len(blocks)} triples "
        f"({n_amenity} Amenity, {len(blocks) - n_amenity} KnowledgeTopic) -> {out.name}"
    )
    if dry_run:
        print("---- DRY RUN (first 2 blocks) ----")
        print("\n\n".join(blocks[:2]))
        return len(blocks)
    out.write_text(header + body, encoding="utf-8", newline="\n")
    print(f"[migrate] wrote {out}")
    return len(blocks)


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument(
        "--building-dir", required=True, help="building dir holding capability.yaml + building.yaml"
    )
    ap.add_argument("--building-id", default=None, help="defaults to the dir name")
    ap.add_argument("--dry-run", action="store_true")
    args = ap.parse_args()
    bdir = Path(args.building_dir).resolve()
    bid = args.building_id or bdir.name
    return 0 if migrate(bdir, bid, dry_run=args.dry_run) >= 0 else 1


if __name__ == "__main__":
    sys.exit(main())
