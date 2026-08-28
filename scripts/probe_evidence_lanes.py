#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Live-probe every lane and assert it emits an evidence record (V6-T02 acceptance).

T02's verify step is one line: *"live probe one question per lane; assert record present and
status set."* This is that, run against whichever building is active.

WHY A LIVE PROBE AND NOT MORE UNIT TESTS
The unit tests could not have caught what was actually wrong. `assemble.py` took its lane keys
from CLAUDE.md's reserved-key list, which named `sparql_results` and `sql_data` -- strings the
pipeline never writes -- and `test_evidence_assembly.py` was written against the same wrong
names. Both agreed, both passed, and in production the two most important data lanes were
recorded as having produced no evidence at all. Only a real turn through a real pipeline puts
the writer and the reader of that key in the same room.

WHAT IT ASSERTS, PER LANE
* a record is present on the response at all;
* its ``status`` is set (never blank);
* it is **not** the fail-closed record -- reaching a lane and then reporting "no lane produced
  evidence" is the exact failure this probe exists to detect, and it is invisible from
  outside because the prose answer looks fine;
* the lane inferred matches the lane the question was aimed at, where the routing is
  deterministic enough to say.

The questions are deliberately generic. Naming a specific room or sensor would make the probe
a bldg1 test; these are phrased so any building with that lane wired answers something.

    python scripts/probe_evidence_lanes.py
    python scripts/probe_evidence_lanes.py --json out.json
"""

from __future__ import annotations

import argparse
import importlib.util
import json
import sys
import uuid
from pathlib import Path
from typing import Dict, List, Optional

REPO = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO))

import requests  # noqa: E402

BASE = "http://127.0.0.1:8000"

#: (lane key the record should infer, question). One per lane named in T02's objective.
#: Where routing legitimately sends a question elsewhere, `expect` is None and the probe only
#: asserts that SOME lane owned the answer -- a probe that fails on correct routing would be
#: retired within a week.
#: Question templates, filled from the ACTIVE building's own graph at run time.
#:
#: The first version of this probe used generic phrasings ("the latest temperature in this
#: building") and seven of the ten were swallowed by the capability lane, so it reported 10/10
#: while exercising four intents. `is_data_query()` only treats a question as a data question
#: when it names a ROOM or FLOOR, so {room} and {floor} are what actually route these to the
#: data lanes. Filled from the graph rather than hardcoded: naming a real room here would make
#: this a bldg1 test.
PROBE_TEMPLATES: List[Dict[str, str]] = [
    {"lane": "sparql_result", "q": "What sensor types does this building have?"},
    {"lane": "sql_result", "q": "What is the current temperature in {room}?"},
    {
        "lane": "analytics_result",
        "q": "What was the average temperature in {room} over the last week?",
    },
    {"lane": "forecast_result", "q": "Forecast the temperature in {room} for tomorrow."},
    # Phrased to match the deliberate lane's superlative shape; a generic "where should I
    # work" was claimed by capability.
    {
        "lane": "deliberate_result",
        "q": "Which room on floor {floor} is the quietest right now?",
    },
    {"lane": "events_result", "q": "Were there any anomalies on floor {floor} in the last week?"},
    # Verbatim from the register intent's own examples. An earlier attempt ("Register a
    # maintenance issue: the tap is dripping") was a pun on the word and landed in the
    # report-intake lane instead -- this lane is the COMPLIANCE register, not a place to file
    # a ticket.
    {"lane": "register_result", "q": "Which compliance checks are overdue?"},
    {"lane": "capability_result", "q": "Is there a bike storage in this building?"},
    # Area and adjacency are the geometry words that keep a count on spatial_query rather
    # than sending it to the graph.
    {
        "lane": "spatial_result",
        "q": "What is the area of the rooms on floor {floor}, and which are adjacent?",
    },
    {"lane": "floor_plan_result", "q": "Show me the floor plan of floor {floor}."},
]


def _sparql_select(query: str) -> List[dict]:
    r = requests.post(
        "http://localhost:7200/repositories/bldg",
        data=query.encode("utf-8"),
        headers={
            "Content-Type": "application/sparql-query",
            "Accept": "application/sparql-results+json",
        },
        timeout=120,
    )
    if r.status_code != 200:
        return []
    return r.json()["results"]["bindings"]


def resolve_referents() -> Dict[str, str]:
    """A real room and a real floor from whatever building is active."""
    out = {"room": "", "floor": ""}
    rows = _sparql_select(
        """PREFIX brick: <https://brickschema.org/schema/Brick#>
           PREFIX rdfs: <http://www.w3.org/2000/01/rdf-schema#>
           SELECT ?label WHERE {
             ?r a brick:Room . OPTIONAL { ?r rdfs:label ?l }
             BIND(COALESCE(?l, REPLACE(STR(?r), "^.*[#/]", "")) AS ?label)
           } ORDER BY ?label LIMIT 1"""
    )
    if rows:
        out["room"] = rows[0]["label"]["value"]
    rows = _sparql_select(
        """PREFIX brick: <https://brickschema.org/schema/Brick#>
           SELECT ?f WHERE { ?f a brick:Floor } ORDER BY ?f LIMIT 3"""
    )
    if rows:
        import re as _re

        m = _re.search(r"(\d+)", rows[-1]["f"]["value"].rsplit("#", 1)[-1])
        out["floor"] = m.group(1) if m else "1"
    return out


def build_probes() -> List[Dict[str, Optional[str]]]:
    refs = resolve_referents()
    if not refs["room"] or not refs["floor"]:
        print(
            f"WARNING: could not resolve a room/floor from the graph ({refs}); "
            "probes will be generic and may not reach their lanes"
        )
    out = []
    for t in PROBE_TEMPLATES:
        out.append({"lane": t["lane"], "q": t["q"].format(**refs)})
    return out


#: The record the chokepoint emits when NO lane claimed the answer. Matching this is the
#: failure mode the probe exists for: the prose reads fine and the record says nothing
#: supports it.
FAIL_CLOSED = "no lane produced evidence"


def login() -> str:
    spec = importlib.util.spec_from_file_location(
        "cap", str(REPO / "scripts" / "capture_golden_baseline.py")
    )
    cap = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(cap)
    return cap._login(BASE)


def ask(token: str, question: str, timeout: int = 240) -> Dict:
    r = requests.post(
        f"{BASE}/chat",
        headers={"Authorization": f"Bearer {token}", "Content-Type": "application/json"},
        json={"message": question, "session_id": f"lane-{uuid.uuid4().hex[:8]}"},
        timeout=timeout,
    )
    if r.status_code != 200:
        return {"_http": r.status_code}
    payload = r.json()
    return payload.get("data") or payload


def _pipeline_key() -> str:
    """The /v1 bearer key. A DIFFERENT credential from the session token used by /chat.

    Probing /v1 with a session token returns 401, which looks exactly like "the endpoint
    does not carry the record" -- so getting this wrong turns a working feature into a
    reported defect. Read from the environment, never printed.
    """
    import os

    if os.environ.get("PIPELINE_API_KEY"):
        return os.environ["PIPELINE_API_KEY"].split(",")[0].strip()
    envf = REPO / ".env"
    if envf.is_file():
        for line in envf.read_text(encoding="utf-8", errors="ignore").splitlines():
            line = line.strip()
            if line.startswith("PIPELINE_API_KEY=") and not line.startswith("#"):
                return line.split("=", 1)[1].strip().strip('"').strip("'").split(",")[0].strip()
    return ""


def ask_v1(question: str, timeout: int = 240) -> Dict:
    """The OpenAI-compatible endpoint, which is what most clients actually use."""
    key = _pipeline_key()
    if not key:
        return {"_http": "no PIPELINE_API_KEY configured"}
    r = requests.post(
        f"{BASE}/v1/chat/completions",
        headers={"Authorization": f"Bearer {key}", "Content-Type": "application/json"},
        json={"model": "ontobot-pipeline", "messages": [{"role": "user", "content": question}]},
        timeout=timeout,
    )
    if r.status_code != 200:
        return {"_http": r.status_code}
    return r.json()


def main(argv: List[str]) -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--json", default="", help="write the full result here")
    args = ap.parse_args(argv)

    try:
        token = login()
    except Exception as exc:
        print(f"cannot authenticate: {exc}")
        return 2

    probes = build_probes()
    rows: List[Dict] = []
    print(f"{'lane':22} {'record':7} {'status':16} {'inferred':22} verdict")
    print("-" * 92)
    for probe in probes:
        data = ask(token, probe["q"])
        rec = data.get("evidence_record") or {}
        status = str(rec.get("status") or "")
        reason = str(rec.get("not_assessable_reason") or "")
        intent = str(data.get("intent") or "")

        present = bool(rec)
        fail_closed = FAIL_CLOSED in reason
        # A turn answered while the provider was down is not evidence of anything, and the
        # fallback text reads enough like an answer to score as one. Measured 2026-08-28:
        # Ollama died mid-run on bldg1 and this probe reported 9/10 with the deliberate
        # lane "FAIL-CLOSED" — a dead model presented as a lane defect, and I started
        # diagnosing the lane. capture_golden_baseline, corpus_replay and leak_benchmark
        # all quarantine on this field already; this probe was the one that did not.
        degraded = bool(data.get("llm_degraded"))
        ok = present and bool(status) and not fail_closed and not degraded
        if degraded:
            verdict = "DEGRADED"
        elif ok:
            verdict = "PASS"
        elif fail_closed:
            verdict = "FAIL-CLOSED"
        else:
            verdict = "NO RECORD"

        rows.append(
            {
                "lane": probe["lane"],
                "question": probe["q"],
                "intent": intent,
                "present": present,
                "status": status,
                "operation": rec.get("operation"),
                "reason": reason[:120],
                "degraded": degraded,
                "ok": ok,
            }
        )
        print(
            f"{probe['lane']:22} {'yes' if present else 'NO':7} {status:16} "
            f"{str(rec.get('operation') or '-'):22} {verdict}"
        )

    # Acceptance criterion 3: the record must also reach the OpenAI-compatible endpoint.
    v1 = ask_v1(probes[0]["q"])
    v1_rec = v1.get("ontosage_evidence_record")
    v1_ok = bool(v1_rec) and bool((v1_rec or {}).get("status"))
    print("-" * 92)
    print(f"/v1/chat/completions carries the record: {'yes' if v1_ok else 'NO'}")

    passed = sum(1 for r in rows if r["ok"])
    quarantined = [r["lane"] for r in rows if r.get("degraded")]
    intents = sorted({r["intent"] for r in rows if r["intent"]})
    print(f"\nresponses carrying a usable record: {passed}/{len(rows)}")
    # The number that actually evidences the criterion. The first version of this probe
    # reported 10/10 while exercising four intents, because seven questions were claimed by
    # the capability lane -- "every response has a record" is not "all ten lanes emit one".
    print(f"distinct lanes exercised: {len(intents)}  {intents}")
    if quarantined:
        # Said loudly, and it makes the run INVALID rather than merely lower-scoring.
        # This project has thrown away two artifacts for exactly this: a container
        # recreated mid-run (CAVEAT-173/BUG-176) and an LLM outage whose fallback text
        # graded as a PASS (BUG-177). A score from a run with degraded turns is not a
        # score, so it must not be reported as one.
        print(
            f"INVALID RUN — {len(quarantined)} turn(s) answered while the LLM was "
            f"degraded: {', '.join(quarantined)}. Fix the provider and re-run; "
            f"do not publish this number."
        )
    if args.json:
        Path(args.json).write_text(
            json.dumps({"lanes": rows, "v1_ok": v1_ok}, indent=1), encoding="utf-8"
        )
    # 3 = invalid, distinct from 1 = failed. They call for different things: an invalid
    # run must be repeated once the provider is healthy, a failed one must be diagnosed.
    # Collapsing them is how a dead model gets investigated as a lane defect.
    if quarantined:
        return 3
    return 0 if (passed == len(rows) and v1_ok and len(intents) >= 6) else 1


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
