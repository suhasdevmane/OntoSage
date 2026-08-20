#!/usr/bin/env python3
"""Measure capability routing: flag OFF (legacy Qdrant KB) vs ON (TTL-first graph+docs).

Runs a curated capability question set through /chat and classifies the ANSWER SOURCE for
each, so we can compare CAPABILITIES_TTL_FIRST off vs on and confirm no regression before
removing capability.yaml (ROADMAP-009 WS-4 / TODO-011).

Usage:
  python scripts/measure_capability_routing.py --label off      # writes cap_route_off.json
  python scripts/measure_capability_routing.py --label on       # after flipping the flag + recreate
  python scripts/measure_capability_routing.py --compare        # prints off-vs-on table
"""

from __future__ import annotations

import argparse
import json
import sys
import time
from pathlib import Path

import httpx

BASE = "http://127.0.0.1:8000"
OUT = Path(__file__).resolve().parent / "outputs"

# (expected_kind, question). expected_kind: amenity | prose | guard (must NOT be capability)
QUESTIONS = [
    ("amenity", "Is there a prayer room in the building?"),
    ("amenity", "Where is the nearest lift?"),
    ("amenity", "Where are the toilets?"),
    ("amenity", "Where can I get a coffee?"),
    ("amenity", "Where is the makerspace?"),
    ("amenity", "What are the reception opening hours?"),
    ("amenity", "Is the building wheelchair accessible?"),
    ("amenity", "Where can I park my bike?"),
    ("prose", "What are the fire evacuation procedures?"),
    ("prose", "What is the data privacy and GDPR policy?"),
    ("prose", "How do I connect to the wifi?"),
    ("prose", "What are the parking and transport options to get here?"),
    ("prose", "How do I make a complaint about the building?"),
    ("guard", "How many sensors are there in the building?"),
    ("guard", "What is the temperature in zone 5.28?"),
    ("guard", "Show me the floor 3 layout."),
]


def _classify(ans: str) -> str:
    a = (ans or "").lower()
    # Capability answers carry distinctive phrases; data/floor answers only mention
    # "Building Ontology" in a source footer, so match the SPECIFIC capability markers.
    if "floor-plans/" in a or "floor plan (pdf)" in a:
        return "floor_plan"
    if "ontology (triples)" in a:  # CapabilityGraphResolver's exact phrase
        return "triples"
    if "live building figures" in a or "instrumented points" in a:
        return "metrics"
    if "documentation:" in a or "policy documents" in a or "**from:" in a:
        return "documents"
    if "information i have on record" in a or "capability profile" in a:
        return "kb"
    if "°c" in a or " ppm" in a or "degrees celsius" in a:
        return "data"
    if "don't have that" in a or "couldn't find" in a or "contact facility" in a:
        return "no_info"
    return "other"


def _token() -> str:
    u = f"meas_{int(time.time())}"
    p = "VerifyPass123456"
    httpx.post(
        f"{BASE}/auth/register",
        json={"username": u, "password": p, "email": f"{u}@e.com"},
        timeout=10,
    )
    r = httpx.post(f"{BASE}/auth/login", json={"username": u, "password": p}, timeout=10)
    return r.json()["data"]["session_token"]


def run(label: str) -> int:
    OUT.mkdir(parents=True, exist_ok=True)
    tok = _token()
    rows = []
    for i, (kind, q) in enumerate(QUESTIONS):
        try:
            # Unique session per question — isolate routing (no conversation-memory /
            # co-reference contamination between questions).
            r = httpx.post(
                f"{BASE}/chat",
                headers={"Authorization": tok},
                json={"message": q, "session_id": f"meas_{label}_{i}"},
                timeout=120,
            )
            d = r.json()
            ans = d.get("response") or d.get("data", {}).get("response") or ""
        except Exception as e:
            ans = f"ERROR: {e}"
        src = _classify(ans)
        rows.append({"kind": kind, "q": q, "source": src, "answer": ans[:200]})
        print(f"  [{label}] {kind:7} {src:10} {q[:52]}")
    (OUT / f"cap_route_{label}.json").write_text(json.dumps(rows, indent=2), encoding="utf-8")
    print(f"\nWrote {OUT / f'cap_route_{label}.json'}")
    return 0


def compare() -> int:
    off = json.loads((OUT / "cap_route_off.json").read_text(encoding="utf-8"))
    on = json.loads((OUT / "cap_route_on.json").read_text(encoding="utf-8"))
    print(f"\n{'kind':7} {'OFF':10} {'ON':10} question")
    print("-" * 78)
    regressions = 0
    for o, n in zip(off, on):
        flag = ""
        # A regression: a capability question that was answered (kb/triples/documents) OFF
        # but became no_info/other/floor_plan ON; or a guard that became capability ON.
        answered = {"triples", "documents", "kb"}
        if o["kind"] in ("amenity", "prose"):
            if o["source"] in answered and n["source"] not in answered:
                flag = "  <-- REGRESSION"
                regressions += 1
        if o["kind"] == "guard":
            if n["source"] in {"triples", "documents", "kb"}:
                flag = "  <-- guard leaked to capability"
                regressions += 1
        print(f"{o['kind']:7} {o['source']:10} {n['source']:10} {o['q'][:44]}{flag}")
    print(f"\nRegressions: {regressions}")
    return 1 if regressions else 0


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--label", choices=["off", "on"])
    ap.add_argument("--compare", action="store_true")
    args = ap.parse_args()
    if args.compare:
        return compare()
    if args.label:
        return run(args.label)
    ap.print_help()
    return 1


if __name__ == "__main__":
    raise SystemExit(main())
