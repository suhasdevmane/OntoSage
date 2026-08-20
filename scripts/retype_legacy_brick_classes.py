#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Retype instances that carry a brick: class the pinned Brick version never defined.

Why this exists (TODO-181). An earlier minting path wrote types straight into
Brick's namespace without checking that Brick declares them. `brick:` is not a
free-form prefix — putting a term there asserts that Brick defines it, and a
reasoner or a validating consumer is entitled to treat an undefined one as an
error. Three shapes were left behind:

  * ``brick:Sound_Level_Sensor`` — Brick 1.4 defines NO acoustic sensor class at
    all, so this invented a term. OntoSage declares its own
    (``ontosage:Sound_Level_Sensor``, in ontology/ontosage_schema.ttl) precisely
    because the quantity is one of the most-asked-about in the survey corpus.
  * ``brick:Electric_Meter`` / ``brick:Building_Electric_Meter`` — near-misses
    for classes Brick really does define, spelled *Electrical*.
  * ``brick:Database`` — a storage concept Brick does not model.

Queries were unaffected because matching is on the LOCAL name, which is exactly
what made this survive: nothing failed, so nothing complained.

The mapping below is about the ONTOLOGY, not about any building, so this script
works on whatever TTL files it is pointed at — active (``input/``) or parked
(``bldg1/``, ``bldg3/``). It rewrites the source TTL rather than issuing a SPARQL
UPDATE, because the TTL is the source of truth: a graph-only fix is silently
reverted the next time the file is uploaded.

Usage:
    python scripts/retype_legacy_brick_classes.py --dry-run
    python scripts/retype_legacy_brick_classes.py input bldg1 bldg3
"""

from __future__ import annotations

import argparse
import re
import sys
from pathlib import Path
from typing import Dict, List, Tuple

REPO = Path(__file__).resolve().parent.parent

#: Undefined brick: term -> the term that IS defined. Ontology-level, not
#: building-level, so it is safe to apply to every building's TTL.
RETYPE: Dict[str, str] = {
    "brick:Sound_Level_Sensor": "ontosage:Sound_Level_Sensor",
    "brick:Noise_Level_Sensor": "ontosage:Noise_Level_Sensor",
    "brick:Electric_Meter": "brick:Electrical_Meter",
    "brick:Building_Electric_Meter": "brick:Building_Electrical_Meter",
    "brick:Database": "ontosage:Database",
    # Surfaced by the audit when bldg1 was booted. Two are near-misses for
    # classes Brick really defines; the rest are concepts Brick does not model
    # at all and are declared in ontology/ontosage_schema.ttl.
    "brick:Electrical_Power_Sensor": "brick:Electric_Power_Sensor",
    "brick:Vibration_Sensor": "brick:Vibration_Sensor_Equipment",
    "brick:Emergency_Generator": "ontosage:Emergency_Generator",
    "brick:Heat_Pump": "ontosage:Heat_Pump",
    "brick:Renewable_Energy_System": "ontosage:Renewable_Energy_System",
    "brick:Alarm_Group": "ontosage:Alarm_Group",
    "brick:Lighting_Command": "ontosage:Lighting_Command",
    # Surfaced by the audit when bldg3 was booted. All four are real Brick
    # classes the model had mis-spelled or over-specified; nothing new needed
    # declaring. The first two are pure word order — Brick writes the position
    # (Supply/Return) BEFORE the medium.
    "brick:Chilled_Water_Supply_Temperature_Setpoint": (
        "brick:Supply_Chilled_Water_Temperature_Setpoint"
    ),
    "brick:Chilled_Water_Return_Temperature_Setpoint": (
        "brick:Return_Chilled_Water_Temperature_Setpoint"
    ),
    # Brick carries the "outside air" specificity on the EQUIPMENT
    # (brick:Outside_Damper) rather than on the command point, so the general
    # command class is the faithful type — inventing a compound would assert a
    # term Brick does not define, which is the whole defect being repaired.
    "brick:Outside_Air_Damper_Command": "brick:Damper_Command",
    # AHU operating-mode points, 5 of 6 carrying readings, so they are read
    # (status) rather than written (command).
    "brick:Mode": "brick:Mode_Status",
}

#: Vocabulary files this tool must NEVER rewrite. Brick_v1.4.ttl states, among
#: other things, which terms are DEPRECATED and what replaces them — rewriting
#: a term inside those statements would corrupt the very definitions the retype
#: is validated against. Matched on the filename, so a building's own TTL is
#: unaffected however it is named.
_VOCABULARY_FILES = {
    "brick_v1.4.ttl",
    "brick+extensions.ttl",
    "ontosage_schema.ttl",
    "ontosage_capabilities.ttl",
    "hbco_core.ttl",
    "hbco_mappings.ttl",
}

ONTOSAGE_NS = "http://ontosage.org/capabilities#"
_PREFIX_LINE = f"@prefix ontosage: <{ONTOSAGE_NS}> .\n"


def _needs_ontosage(text: str) -> bool:
    return "ontosage:" in text and not re.search(r"^@prefix\s+ontosage:", text, re.MULTILINE)


def _insert_prefix(text: str) -> str:
    """Add the ontosage prefix to the file's HEADER prefix block.

    Not "after the last @prefix line": these TTLs are concatenations, so a second
    prefix block can appear thousands of lines in, and appending there puts the
    declaration AFTER the usage it is meant to bind — which Turtle rejects. The
    end of the first contiguous run of @prefix / comment / blank lines is the
    only position that is always valid.
    """
    lines = text.splitlines(keepends=True)
    insert_at = None
    for i, ln in enumerate(lines):
        s = ln.strip()
        if s.startswith("@prefix") or s.startswith("@base"):
            insert_at = i + 1
        elif s and not s.startswith("#") and insert_at is not None:
            break  # header block ended
    if insert_at is None:
        insert_at = 0  # no prefixes at all: put it first
    lines.insert(insert_at, _PREFIX_LINE)
    return "".join(lines)


def retype_text(text: str) -> Tuple[str, Dict[str, int]]:
    """Apply the mapping to one TTL body. Returns (new_text, counts)."""
    counts: Dict[str, int] = {}
    for old, new in RETYPE.items():
        # Word-boundary on the right so brick:Electric_Meter does not also match
        # brick:Electric_Meter_Something, and a leading boundary so a longer
        # prefixed name is never partially rewritten.
        pattern = re.compile(rf"(?<![\w:]){re.escape(old)}(?![\w-])")
        text, n = pattern.subn(new, text)
        if n:
            counts[old] = n
    if counts and _needs_ontosage(text):
        text = _insert_prefix(text)
        counts["+@prefix ontosage:"] = 1
    return text, counts


def main(argv: List[str]) -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument(
        "dirs",
        nargs="*",
        default=["input", "bldg1", "bldg2", "bldg3"],
        help="Directories holding building TTLs (missing ones are skipped).",
    )
    ap.add_argument("--dry-run", action="store_true", help="Report without writing.")
    args = ap.parse_args(argv)

    total = 0
    touched = 0
    for d in args.dirs:
        root = REPO / d
        if not root.is_dir():
            continue
        for path in sorted(root.glob("*.ttl")):
            if path.name.lower() in _VOCABULARY_FILES:
                continue  # never rewrite a vocabulary's own definitions
            original = path.read_text(encoding="utf-8")
            updated, counts = retype_text(original)
            if not counts:
                continue
            touched += 1
            n = sum(v for k, v in counts.items() if not k.startswith("+"))
            total += n
            detail = ", ".join(f"{k} x{v}" for k, v in counts.items())
            print(f"  {path.relative_to(REPO)}: {detail}")
            if not args.dry_run:
                path.write_text(updated, encoding="utf-8")

    verb = "would retype" if args.dry_run else "retyped"
    print(f"\n{verb} {total} instance(s) across {touched} file(s)")
    if not args.dry_run and touched:
        print("Re-upload the affected building's TTLs (restart orchestrator) to apply.")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
