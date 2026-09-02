"""
Calibrate per-building capability_routing thresholds against the active
embedding provider.

Use this whenever you change EMBEDDING_PROVIDER, EMBEDDING_MODEL_*, or add new
KB entries — score distributions differ between embedding models, so default
thresholds (0.65/0.85) may be wrong for your setup.

WHAT THIS DOES
==============
1. Embeds a fixed corpus of representative queries against the active provider.
2. Queries Qdrant for the top match against each query.
3. Computes the gap between the lowest "should-hit" score and the highest
   "should-not-hit" score.
4. Suggests safe `threshold` and `override_min` values that sit inside that gap.
5. (Optional) Writes the suggested values into input/<bldg>/building.yaml.

USAGE
=====
    # Dry-run: print suggested values, don't modify YAML
    python scripts/calibrate_intent_routing.py --building bldg1

    # Apply: update input/bldg1/building.yaml with suggested values
    python scripts/calibrate_intent_routing.py --building bldg1 --apply

REQUIREMENTS
============
- Orchestrator running and reachable at localhost
- Qdrant reachable at localhost:6333
- The capability_<bldg> collection exists (run the indexer first if missing)
- EMBEDDING_PROVIDER set correctly in .env

CALIBRATION CORPUS
==================
6 capability queries + 5 non-capability queries.  These were chosen during the
2026-05-21/22 migration to expose the typical score distribution.  Add more
queries here as you learn what queries are routed incorrectly in production.
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

import requests

ROOT = Path(__file__).resolve().parent.parent
QDRANT_URL = "http://localhost:6333"

# Calibration corpus — (label, query, should_hit_capability)
CORPUS = [
    # should HIT capability
    ("cap_lift", "What are the lift dimensions and weight limit?", True),
    ("cap_elevator", "How big is the elevator?", True),
    ("cap_shower", "Where can I shower in this building?", True),
    ("cap_baby", "Is there a changing table for infants?", True),
    ("cap_bike", "Do you have secure storage for my bicycle?", True),
    ("cap_fire", "What are the fire safety procedures?", True),
    # should NOT hit capability
    ("neg_off_domain", "What is the airspeed of an unladen swallow?", False),
    ("neg_sensor_co2", "What is the current CO2 level on floor 3?", False),
    ("neg_sensor_temp", "What is the temperature on floor 3?", False),
    ("neg_analytics", "Compare CO2 levels between floor 1 and floor 3", False),
    ("neg_floor_plan", "Show me floor 3", False),
]


def _embed(text: str) -> list:
    """Embed using the active provider (OpenAI or local sentence-transformers)."""
    # Mirror the provider detection from shared/config.py
    sys.path.insert(0, str(ROOT))
    from shared.config import settings

    if settings.EMBEDDING_PROVIDER == "openai":
        import openai

        client = openai.OpenAI()
        r = client.embeddings.create(model=settings.EMBEDDING_MODEL_OPENAI, input=text)
        return list(r.data[0].embedding)
    else:
        # Local sentence-transformers (cache after first call)
        global _LOCAL_MODEL
        try:
            _LOCAL_MODEL
        except NameError:
            from sentence_transformers import SentenceTransformer

            _LOCAL_MODEL = SentenceTransformer(settings.EMBEDDING_MODEL_LOCAL)
        return _LOCAL_MODEL.encode(text, convert_to_numpy=True).tolist()


def calibrate(building_id: str) -> dict:
    """Run the corpus, return suggested threshold values."""
    collection = f"capability_{building_id}"
    print(f"Calibrating against Qdrant collection: {collection}")
    print(
        f"Corpus: {len(CORPUS)} queries ({sum(1 for _,_,h in CORPUS if h)} positive, "
        f"{sum(1 for _,_,h in CORPUS if not h)} negative)\n"
    )

    results = []
    print(f"{'label':22s} {'should_hit':>11s} {'score':>7s}  entry")
    print("-" * 80)
    for label, query, should_hit in CORPUS:
        emb = _embed(query)
        r = requests.post(
            f"{QDRANT_URL}/collections/{collection}/points/query",
            json={"query": emb, "limit": 1, "with_payload": True},
            timeout=15,
        )
        if r.status_code != 200:
            print(f"  [skip] {label}: Qdrant error {r.status_code}")
            continue
        points = r.json().get("result", {}).get("points", [])
        if not points:
            print(f"  [skip] {label}: no matches")
            continue
        top = points[0]
        score = float(top["score"])
        entry = top["payload"].get("entry_id", "?")
        results.append({"label": label, "should_hit": should_hit, "score": score, "entry": entry})
        print(f"  {label:22s} {str(should_hit):>11s} {score:7.4f}  {entry}")
    print()

    pos = [r["score"] for r in results if r["should_hit"]]
    neg = [r["score"] for r in results if not r["should_hit"]]
    if not pos or not neg:
        print("ERROR: need both positive and negative samples to calibrate")
        sys.exit(1)

    min_pos = min(pos)
    max_neg = max(neg)
    gap = min_pos - max_neg

    print(f"Positive score range:  {min(pos):.4f} - {max(pos):.4f}")
    print(f"Negative score range:  {min(neg):.4f} - {max(neg):.4f}")
    print(f"Gap (min_pos - max_neg): {gap:.4f}")

    if gap <= 0:
        print("\nWARNING: NEGATIVE OVERLAP DETECTED.")
        print("  No safe threshold separates capability from non-capability.")
        print(
            "  Consider: re-tuning prompts, adding more descriptors, or accepting "
            "some false-positive rate."
        )
        suggested_threshold = (min_pos + max_neg) / 2
        suggested_override = min_pos
    else:
        # Place threshold just above max_neg; override_min midway in the gap
        suggested_threshold = round(max_neg + gap * 0.05, 2)
        suggested_override = round(max_neg + gap * 0.5, 2)
        # Clamp into sensible bounds
        suggested_threshold = max(0.10, min(0.95, suggested_threshold))
        suggested_override = max(suggested_threshold, min(0.95, suggested_override))

    print(f"\nSuggested values:")
    print(f"  threshold:    {suggested_threshold}")
    print(f"  override_min: {suggested_override}")

    return {
        "threshold": suggested_threshold,
        "override_min": suggested_override,
        "min_positive": min_pos,
        "max_negative": max_neg,
        "gap": gap,
        "samples": results,
    }


def apply(building_id: str, threshold: float, override_min: float) -> None:
    """Write suggested values into input/<bldg>/building.yaml."""
    import yaml

    path = ROOT / "input" / building_id / "building.yaml"
    if not path.exists():
        print(f"[apply] {path} not found — creating new file")
        path.parent.mkdir(parents=True, exist_ok=True)
        data = {}
    else:
        with open(path, "r", encoding="utf-8") as fh:
            data = yaml.safe_load(fh) or {}
    cfg = data.setdefault("capability_routing", {})
    cfg["threshold"] = threshold
    cfg["override_min"] = override_min
    with open(path, "w", encoding="utf-8") as fh:
        yaml.safe_dump(data, fh, sort_keys=False, default_flow_style=False)
    print(f"\n[apply] Updated {path}: threshold={threshold}, override_min={override_min}")
    print("[apply] Restart orchestrator for new thresholds to take effect")


def main():
    p = argparse.ArgumentParser()
    p.add_argument("--building", default="bldg1", help="Building ID to calibrate")
    p.add_argument(
        "--apply", action="store_true", help="Write suggested values to input/<bldg>/building.yaml"
    )
    args = p.parse_args()

    result = calibrate(args.building)
    if args.apply:
        apply(args.building, result["threshold"], result["override_min"])
    else:
        print("\n(dry-run; pass --apply to write to building.yaml)")


if __name__ == "__main__":
    main()
