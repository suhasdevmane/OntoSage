#!/usr/bin/env python3
"""Comprehensive capability A/B for the capability.yaml removal gate (TODO-012).

Runs a broad capability question set through /chat with CAPABILITIES_TTL_FIRST=on and
classifies each answer's SOURCE. The removal-readiness verdict hinges on one thing:

  Does every PROSE question answer from the DOCUMENT KB, or does any fall back to the
  capability.yaml KB safety net? A KB-safety-net hit means that topic would return
  "no info" once capability.yaml is deleted — a blocker.

Also checks amenities -> triples, general-knowledge NEGATIVES do not leak to capability,
and routing GUARDS (data/floor/metrics) stay out of capability.

Usage: python scripts/measure_capability_corpus.py            # run + verdict
"""

from __future__ import annotations

import json
import sys
import time
from pathlib import Path

import httpx

BASE = "http://127.0.0.1:8000"
OUT = Path(__file__).resolve().parent / "outputs"

# (kind, question). kind: amenity | prose | negative | guard
QUESTIONS = [
    # ── amenities (expect: triples) ──
    ("amenity", "Is there a prayer room in the building?"),
    ("amenity", "Where can I pray or find a quiet reflection space?"),
    ("amenity", "Where is the nearest lift?"),
    ("amenity", "Is there an elevator to all floors?"),
    ("amenity", "Where are the toilets?"),
    ("amenity", "Are there accessible or gender-neutral toilets?"),
    ("amenity", "Where can I get a coffee?"),
    ("amenity", "Is there a cafe or somewhere to eat?"),
    ("amenity", "Where is the makerspace?"),
    ("amenity", "Is there a simulated trading room?"),
    ("amenity", "Where is the cybersecurity lab?"),
    ("amenity", "What are the reception opening hours?"),
    ("amenity", "Is the building wheelchair accessible?"),
    ("amenity", "Where can I park my bike?"),
    ("amenity", "Where are the showers?"),
    ("amenity", "Is there a nursing or baby feeding room?"),
    ("amenity", "Where can I study or find a quiet workspace?"),
    # ── prose / policy (expect: documents) ──
    ("prose", "What are the fire evacuation procedures?"),
    ("prose", "What is the data privacy and GDPR policy?"),
    ("prose", "How do I connect to the wifi?"),
    ("prose", "What are the parking and transport options to get here?"),
    ("prose", "How do I make a complaint about the building?"),
    ("prose", "What happens during a power outage?"),
    ("prose", "How does building access control work?"),
    ("prose", "Is there CCTV surveillance in the building?"),
    ("prose", "How does the lighting system work?"),
    ("prose", "What sustainability measures does the building have?"),
    ("prose", "Who do I contact in an emergency?"),
    ("prose", "What are the building working hours?"),
    ("prose", "What are the room occupancy limits?"),
    ("prose", "How do I print or scan documents?"),
    ("prose", "What is the visitor and guest policy?"),
    ("prose", "What is the smoking policy?"),
    ("prose", "Where is lost property handled?"),
    ("prose", "What schools and departments are in the building?"),
    ("prose", "How do I report that a room is too warm or too cold?"),
    # ── general-knowledge negatives (must NOT route to capability) ──
    ("negative", "What is the capital of France?"),
    ("negative", "Who is the current CEO of OpenAI?"),
    ("negative", "Briefly, what is entropy?"),
    # ── routing guards (must NOT leak to capability) ──
    ("guard", "What is the current temperature in zone 5.28?"),
    ("guard", "Show me the floor 3 layout."),
    ("guard", "How many sensors are there in the building?"),
]


def _classify(ans: str) -> str:
    a = (ans or "").lower()
    if "floor-plans/" in a or "floor plan (pdf)" in a:
        return "floor_plan"
    if "ontology (triples)" in a:
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
    return "other"  # generic LLM / general-knowledge answer


_CAP_SOURCES = {"triples", "documents", "kb"}


def _token() -> str:
    u = f"corpus_{int(time.time())}"
    p = "VerifyPass123456"
    httpx.post(f"{BASE}/auth/register", json={"username": u, "password": p, "email": f"{u}@e.com"},
               timeout=10)
    r = httpx.post(f"{BASE}/auth/login", json={"username": u, "password": p}, timeout=10)
    return r.json()["data"]["session_token"]


def main() -> int:
    OUT.mkdir(parents=True, exist_ok=True)
    tok = _token()
    rows = []
    for i, (kind, q) in enumerate(QUESTIONS):
        try:
            r = httpx.post(f"{BASE}/chat", headers={"Authorization": tok},
                           json={"message": q, "session_id": f"corpus_{i}"}, timeout=150)
            d = r.json()
            ans = d.get("response") or d.get("data", {}).get("response") or ""
        except Exception as e:
            ans = f"ERROR: {e}"
        src = _classify(ans)
        rows.append({"kind": kind, "q": q, "source": src, "answer": ans[:160]})
        print(f"  {kind:8} {src:11} {q[:52]}")
    (OUT / "cap_corpus.json").write_text(json.dumps(rows, indent=2), encoding="utf-8")

    # ── verdict ──
    def by(kind):
        return [r for r in rows if r["kind"] == kind]

    amen_bad = [r for r in by("amenity") if r["source"] != "triples"]
    prose_docs = [r for r in by("prose") if r["source"] == "documents"]
    prose_kb = [r for r in by("prose") if r["source"] == "kb"]  # safety-net = removal blocker
    prose_fail = [r for r in by("prose") if r["source"] in ("no_info", "other")]
    neg_leak = [r for r in by("negative") if r["source"] in _CAP_SOURCES]
    guard_leak = [r for r in by("guard") if r["source"] in _CAP_SOURCES]

    print("\n" + "=" * 60)
    print("REMOVAL-READINESS VERDICT (capability.yaml deletion)")
    print("=" * 60)
    print(f"amenities -> triples : {len(by('amenity')) - len(amen_bad)}/{len(by('amenity'))}"
          + (f"   MISS: {[r['q'][:30] for r in amen_bad]}" if amen_bad else ""))
    print(f"prose -> documents   : {len(prose_docs)}/{len(by('prose'))}")
    if prose_kb:
        print(f"  *** KB SAFETY-NET (blocks removal): {[r['q'][:34] for r in prose_kb]}")
    if prose_fail:
        print(f"  *** FAIL (no_info/generic):         {[r['q'][:34] for r in prose_fail]}")
    print(f"negatives NOT capability: {len(by('negative')) - len(neg_leak)}/{len(by('negative'))}"
          + (f"   LEAK: {[r['q'][:30] for r in neg_leak]}" if neg_leak else ""))
    print(f"guards NOT capability   : {len(by('guard')) - len(guard_leak)}/{len(by('guard'))}"
          + (f"   LEAK: {[r['q'][:30] for r in guard_leak]}" if guard_leak else ""))

    blockers = len(prose_kb) + len(prose_fail) + len(neg_leak) + len(guard_leak) + len(amen_bad)
    print("\n" + ("REMOVAL SAFE — no blockers." if blockers == 0
                  else f"NOT SAFE — {blockers} blocker(s); fix before deleting capability.yaml."))
    print(f"\nFull rows: {OUT / 'cap_corpus.json'}")
    return 0 if blockers == 0 else 1


if __name__ == "__main__":
    raise SystemExit(main())
