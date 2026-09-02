#!/usr/bin/env python3
"""
Phase 5 — Export production traffic as a G1 six-tuple corpus.

Reads agent memory (Qdrant user_memory collection) and emits one row per
interaction in the Phase-B taxonomy format, so production traffic can be
re-scored against the pre-design survey corpus.

Output CSV columns (matching Phase-B analysis scripts):
  user_id, session_date, persona, domain_l1, query_type_l2, intent,
  temporal, spatial, complexity, grounded, memory_type, query_snippet

Usage:
    python scripts/export_production_corpus.py \
        --qdrant-url http://localhost:6333 \
        --output outputs/production_corpus_<date>.csv
"""

import argparse
import csv
import json
import sys
from datetime import datetime
from pathlib import Path

sys.path.append(str(Path(__file__).resolve().parents[1]))

try:
    from qdrant_client import QdrantClient
    from qdrant_client.models import FieldCondition, Filter, MatchAny

    _QDRANT_OK = True
except ImportError:
    _QDRANT_OK = False

COLLECTION = "user_memory"
BATCH_SIZE = 100


def scroll_all(client: "QdrantClient", collection: str):
    """Yield all payloads from a Qdrant collection."""
    offset = None
    while True:
        result, offset = client.scroll(
            collection_name=collection,
            offset=offset,
            limit=BATCH_SIZE,
            with_payload=True,
            with_vectors=False,
        )
        for point in result:
            yield point.payload
        if offset is None:
            break


def payload_to_row(payload: dict) -> dict:
    """Map a Qdrant payload to the G1 six-tuple export row."""
    g1 = payload.get("g1_taxonomy") or {}
    return {
        "user_id": payload.get("user_id", ""),
        "session_date": payload.get("timestamp", ""),
        "persona": payload.get("persona", "general"),
        "domain_l1": g1.get("domain_l1", "OTHER"),
        "query_type_l2": g1.get("query_type_l2", "LOOKUP"),
        "intent": payload.get("intent", g1.get("intent", "general")),
        "temporal": str(g1.get("temporal", False)).lower(),
        "spatial": str(g1.get("spatial", False)).lower(),
        "complexity": g1.get("complexity", "SIMPLE"),
        "grounded": payload.get("grounded", "unknown"),
        "memory_type": payload.get("memory_type", "qa_pair"),
        "query_snippet": (payload.get("query") or "")[:120],
    }


FIELDNAMES = [
    "user_id",
    "session_date",
    "persona",
    "domain_l1",
    "query_type_l2",
    "intent",
    "temporal",
    "spatial",
    "complexity",
    "grounded",
    "memory_type",
    "query_snippet",
]


def main():
    parser = argparse.ArgumentParser(description="Export production corpus in G1 format")
    parser.add_argument("--qdrant-url", default="http://localhost:6333", help="Qdrant URL")
    parser.add_argument(
        "--output",
        default=f"outputs/production_corpus_{datetime.now():%Y%m%d_%H%M}.csv",
        help="Output CSV path",
    )
    args = parser.parse_args()

    if not _QDRANT_OK:
        print("ERROR: qdrant-client not installed. Run: pip install qdrant-client")
        sys.exit(1)

    client = QdrantClient(url=args.qdrant_url)
    out_path = Path(args.output)
    out_path.parent.mkdir(parents=True, exist_ok=True)

    rows = 0
    with open(out_path, "w", newline="", encoding="utf-8") as fh:
        writer = csv.DictWriter(fh, fieldnames=FIELDNAMES)
        writer.writeheader()
        for payload in scroll_all(client, COLLECTION):
            writer.writerow(payload_to_row(payload))
            rows += 1

    print(f"Exported {rows} interactions → {out_path}")


if __name__ == "__main__":
    main()
