# -*- coding: utf-8 -*-
"""
generate_l7_bank.py — instantiate deliberative benchmark questions from the
ACTIVE building's own graph (V4-T27).

The hand-authored seed bank (tests/fixtures/l7_bank/seed_questions.csv) spans
every stakeholder category but is thin on deliberative strata; this generator
adds volume by filling templates with REAL entities (floors, rooms, amenity
kinds) pulled live — so the bank ports to any building with zero shared
literals, and the deterministic parameters make every question's ground truth
computable by the grader.

RUN (stack up):
  python scripts/generate_l7_bank.py            # -> tests/fixtures/l7_bank/generated_<id>.csv
"""

from __future__ import annotations

import asyncio
import csv
import random
import sys
from pathlib import Path

_SCRIPT_DIR = Path(__file__).resolve().parent
_REPO_ROOT = _SCRIPT_DIR.parent
sys.path.insert(0, str(_REPO_ROOT))

from orchestrator.services.deliberation.capability_schema import build_schema  # noqa: E402
from orchestrator.services.deliberation.coverage_audit import _local, load_modalities  # noqa: E402
from orchestrator.services.deliberation.live import active_identity, sparql_exec  # noqa: E402

# (stratum, expected_behavior, answer_type, template) — {floor}/{room}/{amenity}
# placeholders fill from the live graph
_TEMPLATES = [
    ("superlative", "answer", "single_choice", "Which room on {floor} is the quietest right now?"),
    ("superlative", "answer", "single_choice", "Show me the zone with minimum occupancy."),
    (
        "superlative",
        "answer",
        "single_choice",
        "Which room on {floor} has the lowest CO2 right now?",
    ),
    (
        "superlative",
        "answer",
        "single_choice",
        "Which room is the warmest in the whole building right now?",
    ),
    ("superlative", "answer", "ranked_list", "Rank the rooms on {floor} by noise level."),
    (
        "constraint_ranking",
        "answer",
        "single_choice",
        "Where can I sit that's quiet, with good air, near {amenity}?",
    ),
    (
        "constraint_ranking",
        "answer",
        "single_choice",
        "Find me a room on {floor} that is cool and not stuffy.",
    ),
    (
        "constraint_ranking",
        "answer",
        "ranked_list",
        "Which rooms are both quiet and well-lit right now?",
    ),
    (
        "forecast",
        "answer",
        "single_choice",
        "Where should I sit tomorrow morning for a quiet environment?",
    ),
    (
        "forecast",
        "answer",
        "single_choice",
        "Which room on {floor} will have the best air tomorrow?",
    ),
    ("spatial_anchored", "answer", "ranked_list", "Which quiet rooms are nearest a {amenity}?"),
    (
        "ambiguous",
        "clarify",
        "clarify_question",
        "Where should I sit - somewhere quiet on floor 99?",
    ),
    (
        "ambiguous",
        "clarify",
        "clarify_question",
        "Where can I sit that's quiet, near the aquarium?",
    ),
    (
        "unanswerable",
        "decline_hint",
        "honest_decline",
        "Which room has the lowest radiation right now?",
    ),
    (
        "unanswerable",
        "decline_hint",
        "honest_decline",
        "Rank the rooms on {floor} by wifi signal strength.",
    ),
    # mixed mappable+unmappable: drop-and-declare policy answers on 'quiet'
    # and DECLARES that 'air ionisation' isn't sensed (assumption in the dossier)
    (
        "constraint_ranking",
        "answer",
        "single_choice",
        "Where can I sit that's quiet with the best air ionisation?",
    ),
]

_PER_TEMPLATE = 2  # instantiations per parameterised template (seeded)


async def _run() -> int:
    identity = active_identity()
    building_id, namespace = identity["BUILDING_ID"], identity["BUILDING_NAMESPACE"]
    schema = await build_schema(building_id, namespace, sparql_exec, load_modalities(building_id))
    floors = schema.floors
    amenities = schema.amenity_kinds
    if not floors:
        print("[l7-bank] ERROR: no floors discovered")
        return 1
    rng = random.Random(f"{building_id}:l7bank")  # deterministic per building

    rows = []
    counter = 0
    for stratum, behavior, answer_type, template in _TEMPLATES:
        needs_floor = "{floor}" in template
        needs_amenity = "{amenity}" in template
        variants = _PER_TEMPLATE if (needs_floor or needs_amenity) else 1
        for _ in range(variants):
            q = template
            if needs_floor:
                q = q.replace("{floor}", rng.choice(floors))
            if needs_amenity:
                q = q.replace(
                    "{amenity}", _spell(rng.choice(amenities)) if amenities else "drinking water"
                )
            counter += 1
            rows.append(
                {
                    "ID": f"G{counter:03d}",
                    "Question": q,
                    "Category": "generated-deliberative",
                    "Register": "Generated",
                    "expected_behavior": behavior,
                    "l7_stratum": stratum,
                    "required_data_sources": "graph, timeseries, geometry, amenities",
                    "answer_type": answer_type,
                    "latent_complexity": 7,
                    "rationale": f"template-instantiated from the {building_id} graph",
                }
            )

    # dedupe identical instantiations (same floor drawn twice)
    seen, unique = set(), []
    for r in rows:
        if r["Question"] not in seen:
            seen.add(r["Question"])
            unique.append(r)

    out = _REPO_ROOT / "tests" / "fixtures" / "l7_bank" / f"generated_{building_id}.csv"
    out.parent.mkdir(parents=True, exist_ok=True)
    with open(out, "w", encoding="utf-8", newline="") as f:
        w = csv.DictWriter(f, fieldnames=list(unique[0].keys()), lineterminator="\n")
        w.writeheader()
        w.writerows(unique)
    print(f"[l7-bank] {len(unique)} generated questions -> {out}")
    print(f"[l7-bank] floors={floors} amenities={amenities}")
    return 0


def _spell(kind: str) -> str:
    """DrinkingWater -> 'drinking water' (lay phrasing for the question text)."""
    out = []
    for ch in kind:
        if ch.isupper() and out:
            out.append(" ")
        out.append(ch.lower())
    return "".join(out)


if __name__ == "__main__":
    sys.exit(asyncio.run(_run()))
