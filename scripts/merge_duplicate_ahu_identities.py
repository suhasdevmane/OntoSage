#!/usr/bin/env python
"""Merge bldg1's three AHU naming schemes onto one (BUG-249).

The building has SIX air handlers. The graph carried three names for them:

``AHU_F0``-``AHU_F5``
    The real ones. Declared in ``bldg1_abacws_metadata.ttl`` as
    ``brick:Air_Handling_Unit``, ``isPartOf`` their floor, ``feeds`` their zones,
    and measured by the per-floor HVAC electrical sub-meter. This is the scheme
    that survives.

``AHU_Floor0``-``AHU_Floor5``
    **Never declared anywhere.** ``provision_plant_points.py`` wrote thirty points
    with ``brick:isPointOf bldg:AHU_FloorN`` against a subject that does not exist,
    and a reasoner typed the dangling reference as equipment from the property's
    range — which is why ``brick:AHU`` counted fourteen instances for six units.
    Those thirty points duplicate the ``AHU_FN_*`` points one-for-one: same five
    classes, same floors, same units, different UUIDs.

``AHU-F5`` / ``AHU-F3``
    Declared in ``equipment_linkage.ttl`` as ``brick:Air_Handler_Unit`` with a
    label, a location and a useful comment — but no ``feeds``. They are where the
    feed framework attached the AHU runtime sensor, so that sensor was unreachable
    from any space by the equipment -> zone -> room path.

What this does
--------------
* Deletes the thirty phantom ``AHU_FloorN_*`` points and their
  ``ConfigurationPeriod`` records.
* Re-points ``feed_ahu_runtime_floor5`` at ``AHU_F5``, so the runtime series is
  reachable from floor 5's spaces.
* Carries the ``AHU-F3`` / ``AHU-F5`` comments onto ``AHU_F3`` / ``AHU_F5`` — that
  text ("Rated 8,000 m3/h", "serving open-plan offices and study spaces") is
  information the building has, and dropping it to tidy up would lose it.
* Deletes the now-empty ``AHU-F3`` / ``AHU-F5`` individuals.

What it does NOT do
-------------------
* **No database rows are deleted.** The thirty removed points had UUIDs with rows
  in ``plant_data``. Rows with no triple are merely unreachable, which is
  harmless; deleting live data to tidy a naming scheme is not a trade this script
  is entitled to make.
* **``building.yaml`` is not touched.** Its ``points_writable`` list contains
  ``urn:bldg1:AHU-F5-SP``, an opaque actuation URN rather than a graph IRI.
  Editing the allowlist would change what this system is permitted to actuate,
  which is not a side effect a data migration gets to have.

Every edited file is backed up beside itself first. Re-running finds nothing.

Run:
  python scripts/merge_duplicate_ahu_identities.py --dry-run
  python scripts/merge_duplicate_ahu_identities.py --apply
"""

from __future__ import annotations

import argparse
import re
import shutil
import sys
from pathlib import Path
from typing import List, Tuple

REPO = Path(__file__).resolve().parents[1]
BLDG = REPO / "bldg1"

PLANT = BLDG / "bldg1_plant_points.ttl"
CONFIG_HISTORY = BLDG / "bldg1_configuration_history.ttl"
LINKAGE = BLDG / "equipment_linkage.ttl"
METADATA = BLDG / "bldg1_abacws_metadata.ttl"

#: A whole `bldg:Subject ... .` statement, from the subject to the closing dot at
#: the start of a line. Turtle blocks in these files are written one per subject.
_BLOCK = r"^bldg:{name}\b.*?(?:^|\n)\s*\]?\s*\.\s*\n"


def _blocks_for(text: str, name_re: str) -> List[Tuple[int, int, str]]:
    """(start, end, subject) for every top-level block whose subject matches."""
    out: List[Tuple[int, int, str]] = []
    pattern = re.compile(rf"^bldg:({name_re})\s", re.M)
    for m in pattern.finditer(text):
        start = m.start()
        # The block ends at the first line that is exactly " ." or ends in " ." at
        # depth zero. These files always close a subject with a line ending in "." ,
        # and nested blank nodes close with "] ." on their own line first.
        end = text.find("\n\n", start)
        end = len(text) if end == -1 else end + 2
        out.append((start, end, m.group(1)))
    return out


def _drop_blocks(text: str, name_re: str) -> Tuple[str, List[str]]:
    blocks = _blocks_for(text, name_re)
    dropped = [s for _a, _b, s in blocks]
    for start, end, _s in reversed(blocks):
        text = text[:start] + text[end:]
    return text, dropped


def _backup(path: Path, apply: bool) -> None:
    if apply:
        shutil.copy2(path, path.with_suffix(path.suffix + ".pre-ahu-merge.bak"))


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    g = ap.add_mutually_exclusive_group(required=True)
    g.add_argument("--dry-run", action="store_true")
    g.add_argument("--apply", action="store_true")
    args = ap.parse_args()
    apply = bool(args.apply)
    changed: List[str] = []

    # ── 1. the thirty phantom points ─────────────────────────────────────────
    plant = PLANT.read_text(encoding="utf-8")
    plant2, dropped_points = _drop_blocks(plant, r"AHU_Floor\d+_\w+")
    print(f"{PLANT.name}: dropping {len(dropped_points)} phantom points")
    for s in dropped_points[:3]:
        print(f"    e.g. bldg:{s}")
    if dropped_points and "AHU_Floor" in plant2:
        print("    WARNING: AHU_Floor references remain", file=sys.stderr)

    # ── 2. their configuration-period records ────────────────────────────────
    cfg = CONFIG_HISTORY.read_text(encoding="utf-8")
    cfg2, dropped_cfg = _drop_blocks(cfg, r"AHU_Floor\d+_\w+_cfg\d+")
    print(f"{CONFIG_HISTORY.name}: dropping {len(dropped_cfg)} configuration periods")

    # ── 3. the runtime sensor, re-pointed at the real AHU ────────────────────
    link = LINKAGE.read_text(encoding="utf-8")
    n_repoint = link.count("brick:isPointOf bldg:AHU-F5")
    link2 = link.replace("brick:isPointOf bldg:AHU-F5", "brick:isPointOf bldg:AHU_F5")
    print(f"{LINKAGE.name}: re-pointing {n_repoint} point(s) from AHU-F5 to AHU_F5")

    # ── 4. carry the comments across before deleting the strays ──────────────
    carried = {}
    for stray, real in (("AHU-F3", "AHU_F3"), ("AHU-F5", "AHU_F5")):
        m = re.search(rf"^bldg:{re.escape(stray)}\s.*?rdfs:comment\s+(\".*?\")", link2, re.S | re.M)
        if m:
            carried[real] = m.group(1)
    link2, dropped_ahu = _drop_blocks(link2, r"AHU-F\d+")
    print(f"{LINKAGE.name}: dropping {len(dropped_ahu)} stray AHU individuals: {dropped_ahu}")

    meta = METADATA.read_text(encoding="utf-8")
    meta2 = meta
    for real, comment in sorted(carried.items()):
        anchor = f"bldg:{real}\n    rdf:type owl:NamedIndividual , brick:Air_Handling_Unit ;\n"
        if anchor not in meta2:
            print(f"    SKIP comment for {real}: declaration not found in {METADATA.name}")
            continue
        if "rdfs:comment" in meta2[meta2.index(anchor) : meta2.index(anchor) + 800]:
            print(f"    SKIP comment for {real}: it already has one")
            continue
        meta2 = meta2.replace(anchor, anchor + f"    rdfs:comment {comment} ;\n", 1)
        print(f"    carried comment onto bldg:{real}")

    edits = [
        (PLANT, plant, plant2),
        (CONFIG_HISTORY, cfg, cfg2),
        (LINKAGE, link, link2),
        (METADATA, meta, meta2),
    ]
    for path, before, after in edits:
        if before == after:
            continue
        changed.append(path.name)
        if apply:
            _backup(path, apply)
            path.write_text(after, encoding="utf-8")

    print()
    if not apply:
        print("DRY RUN — nothing written. Re-run with --apply.")
        return 0
    print(f"Applied to: {', '.join(changed) or '(nothing)'}")

    try:
        import rdflib

        for path, _b, _a in edits:
            g_ = rdflib.Graph()
            g_.parse(str(path), format="turtle")
            print(f"  {path.name}: {len(g_)} triples parse OK")
    except ImportError:  # pragma: no cover
        print("  (rdflib not installed — skipped the reparse check)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
