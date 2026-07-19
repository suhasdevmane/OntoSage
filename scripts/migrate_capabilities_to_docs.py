#!/usr/bin/env python3
"""Migrate PROSE capability entries from capability.yaml into the document KB (ROADMAP-009).

Structural capability facts (amenities, locations) belong in the ontology as triples
(input/<bldg>_capabilities.ttl). Long-form PROSE/policy (fire procedures, GDPR, IT support,
contacts) belongs in the document knowledge base, not forced into triples. This script emits
the prose entries verbatim into ``input/documents/building_reference.md`` so the document
indexer (Qdrant ``documents_<bldg>``) serves them — building the replacement for capability.yaml
while it is kept as a fallback (nothing is deleted here).

Idempotent: overwrites the generated file. Verbatim copy — no paraphrasing, no lossy triple-ification.

Usage:  python scripts/migrate_capabilities_to_docs.py [--building bldg1]
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

# Entries already migrated to ontology triples (input/<bldg>_capabilities.ttl) — skip.
_MIGRATED_TO_TRIPLES = {
    "wellbeing_facilities",  # prayer/nursing room
    "catering_amenities",  # café
    "quiet_study",  # study areas
    "lift_accessibility_detail",  # lift
    "bicycle_parking_detail",  # bike storage
    "shower_facilities_detail",  # showers
    "toilet_facilities_by_floor",  # toilets
}
# Prose already covered by hand-written docs in input/documents/ — skip to avoid duplication.
_ALREADY_IN_DOCS = {
    "fire_safety",
    "emergency_evacuation",
    "hvac_zoning",
    "smart_controls",
    "bookings_reservations",
}
_SKIP = _MIGRATED_TO_TRIPLES | _ALREADY_IN_DOCS

_OUTPUT_NAME = "building_reference.md"


def _title(entry_id: str) -> str:
    return entry_id.replace("_", " ").title()


def migrate(building_id: str) -> int:
    import yaml

    from shared.building_paths import resolve_building_file

    cap_path = resolve_building_file(building_id, "capability.yaml", Path("input"))
    if not cap_path or not Path(cap_path).exists():
        print(f"capability.yaml not found for {building_id}", file=sys.stderr)
        return 1
    data = yaml.safe_load(Path(cap_path).read_text(encoding="utf-8")) or {}

    info = data.get("building_info", {})
    entries = data.get("capabilities", []) or []

    docs_dir = Path(cap_path).parent / "documents"
    docs_dir.mkdir(parents=True, exist_ok=True)
    bname = info.get("name", building_id)

    # One focused doc PER topic — mixed-topic chunks dilute per-topic similarity below the
    # retrieval threshold (measured: a consolidated file regressed wifi/GDPR/parking). Each
    # topic as its own small doc is a clean retrieval target for the document KB.
    old_consolidated = docs_dir / "building_reference.md"
    if old_consolidated.exists():
        old_consolidated.unlink()  # superseded by per-topic files
    for stale in docs_dir.glob("cap_*.md"):
        stale.unlink()  # idempotent: clear previously generated per-topic docs

    moved, skipped = [], []
    for e in entries:
        eid = e.get("id", "")
        content = (e.get("content") or "").strip()
        if not eid or not content:
            continue
        if eid in _SKIP:
            skipped.append(eid)
            continue
        # Embed the entry's lay-term keywords into the doc so semantic retrieval matches
        # colloquial questions ("how do I connect to the wifi") — the keywords ARE the
        # lay phrasings, and dropping them was starving retrieval (esp. local MiniLM).
        kws = [str(k) for k in (e.get("keywords") or [])]
        kw_line = f"\n\nRelated: {', '.join(kws)}.\n" if kws else ""
        body = f"# {bname} — {_title(eid)}\n\n{content}\n{kw_line}"
        (docs_dir / f"cap_{eid}.md").write_text(body, encoding="utf-8")
        moved.append(eid)

    print(f"Wrote {len(moved)} per-topic capability docs (cap_*.md) to {docs_dir}")
    print(f"  moved:   {', '.join(sorted(moved))}")
    print(f"  skipped: {', '.join(sorted(skipped))} (triples or existing docs)")
    return 0


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--building", default=None, help="building id (default: settings.BUILDING_ID)")
    args = ap.parse_args()
    try:
        from shared.config import settings

        building_id = args.building or settings.BUILDING_ID
    except Exception:
        building_id = args.building or "bldg1"
    return migrate(building_id)


if __name__ == "__main__":
    raise SystemExit(main())
