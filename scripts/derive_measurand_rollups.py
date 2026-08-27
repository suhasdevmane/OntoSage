#!/usr/bin/env python
"""Derive which class counts sweep in a different measurand (CAVEAT-286).

``ontology/measurand_kinds.ttl`` says what each confusable sensor class measures.
Brick's own hierarchy says which classes are subclasses of which. Cross the two and
you get the fact an answer needs: *counting this class also counts these, and they
measure something else.*

Derived rather than hand-written, and committed rather than computed at answer
time. Both halves matter:

* **Derived** — a hand-maintained list drifts from the ontology it describes, which
  is the failure this codebase keeps paying for. Re-running this after a Brick
  upgrade is how the map stays true.
* **Committed** — the alternative is parsing a 54,000-triple TBox inside a request.

Run:
  python scripts/derive_measurand_rollups.py
  python scripts/derive_measurand_rollups.py --check   # exit 1 if the file is stale
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Dict, List, Set

REPO = Path(__file__).resolve().parents[1]
OUT = REPO / "config" / "measurand_rollups.json"

# Running a file in scripts/ puts scripts/ on sys.path, not the repo root, so the
# one parser for measurand_kinds.ttl would be unimportable and this script would
# grow a second copy of it -- the drift this whole exercise exists to avoid.
if str(REPO) not in sys.path:
    sys.path.insert(0, str(REPO))

#: Where a vendored Brick TBox may be found. Any building's copy will do -- they are
#: the same file -- so this does not require a particular building to be active.
_BRICK_CANDIDATES = (
    "input/Brick_v1.4.ttl",
    "bldg1/Brick_v1.4.ttl",
    "bldg2/Brick_v1.4.ttl",
    "bldg3/Brick_v1.4.ttl",
)


def _brick_path() -> Path:
    for rel in _BRICK_CANDIDATES:
        p = REPO / rel
        if p.is_file():
            return p
    raise SystemExit("No vendored Brick TBox found. Looked in: " + ", ".join(_BRICK_CANDIDATES))


def _descendants(subclass_of: Dict[str, Set[str]], root: str) -> Set[str]:
    seen: Set[str] = set()
    stack = [root]
    while stack:
        cur = stack.pop()
        for kid in subclass_of.get(cur, ()):
            if kid not in seen:
                seen.add(kid)
                stack.append(kid)
    return seen


def build() -> dict:
    import rdflib

    from orchestrator.services.measurand_kinds import _kinds

    brick_ns = "https://brickschema.org/schema/Brick#"
    kinds = _kinds()
    if not kinds:
        raise SystemExit("ontology/measurand_kinds.ttl declares nothing; nothing to derive.")

    g = rdflib.Graph()
    g.parse(str(_brick_path()), format="turtle")
    children: Dict[str, Set[str]] = {}
    for s, _p, o in g.triples((None, rdflib.RDFS.subClassOf, None)):
        if str(s).startswith(brick_ns) and str(o).startswith(brick_ns):
            children.setdefault(str(o)[len(brick_ns) :], set()).add(str(s)[len(brick_ns) :])

    rollups: Dict[str, List[str]] = {}
    for cls, kind in sorted(kinds.items()):
        foreign = sorted(
            d for d in _descendants(children, cls) if kinds.get(d) and kinds[d] != kind
        )
        if foreign:
            rollups[cls] = foreign
    return {
        "_comment": (
            "DERIVED by scripts/derive_measurand_rollups.py from Brick's asserted "
            "hierarchy crossed with ontology/measurand_kinds.ttl. Do not hand-edit: "
            "re-run the script after a Brick upgrade. Each entry says that counting "
            "the key class also counts the listed classes, which measure something else."
        ),
        "brick_source": str(_brick_path().relative_to(REPO)).replace("\\", "/"),
        "declared_classes": len(kinds),
        "rollups": rollups,
    }


def main() -> int:
    ap = argparse.ArgumentParser(description="Derive measurand roll-up disclosures.")
    ap.add_argument("--check", action="store_true", help="fail if the committed file is stale")
    args = ap.parse_args()

    fresh = build()
    body = json.dumps(fresh, indent=2, sort_keys=True) + "\n"

    if args.check:
        if not OUT.is_file():
            print(f"{OUT.relative_to(REPO)} is missing. Run without --check to create it.")
            return 1
        if OUT.read_text(encoding="utf-8") != body:
            print(f"{OUT.relative_to(REPO)} is STALE. Re-run without --check.")
            return 1
        print(f"{OUT.relative_to(REPO)} is up to date.")
        return 0

    OUT.parent.mkdir(parents=True, exist_ok=True)
    OUT.write_text(body, encoding="utf-8")
    print(f"wrote {OUT.relative_to(REPO)} from {fresh['brick_source']}")
    if not fresh["rollups"]:
        print("  no class rolls up a foreign measurand - nothing to disclose")
    for cls, foreign in sorted(fresh["rollups"].items()):
        print(f"  {cls} also counts: {', '.join(foreign)}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
