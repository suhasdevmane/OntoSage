# -*- coding: utf-8 -*-
"""Attribute every captured answer to the part of the system that produced it -- WITHOUT reading it.

    python scripts/attribute_answers.py --set eval/compound/T-REAL.jsonl --version v2

tasks/V2_COMPOUND_PLAN.md section 5 ("What else changes between v1 and v2") pre-registers this:
a v2 answer counts toward the compound ARCHITECTURE when the deliberation lane answered it with a
facet plan (an operation, or facet criteria); any other answer came from a v1 lane, and a change
in it is credited to the incidental fixes. The rule reads only the capture record's routing and
plan fields -- the lane, the evidence record's operation, the plan trace -- never the answer text,
so it can run on the sealed held-out captures before the blinded read without exposing them.

It also marks provider-failed turns by the plan's pre-registered rule, which does read the text,
but only to test it for five fixed fallback wordings; nothing of the answer is printed or stored.

Writes eval/compound/results/<version>/<set>.attribution.json: per item, ids and labels only.
"""

from __future__ import annotations

import argparse
import json
import sys
from collections import Counter
from pathlib import Path
from typing import Any, Dict, List

REPO = Path(__file__).resolve().parent.parent

#: The five wordings the code emits only from the `except` around an LLM call (plan section 5).
PROVIDER_FALLBACKS = (
    "couldn't summarise them against your question just now",
    "able to generate an answer just now",
    "The readings could not be summarised.",
    "language model this assistant uses is not responding",
    "language model that writes the summary is not responding",
)

#: The v2 routing rule; the route record names it as "contract:<rule>" when it escalated a turn.
ESCALATION_RULE = "compound_facets_to_deliberate"

#: Evidence-record operations only a v2 facet plan produces. v1's deliberation lane records
#: "recommendation" for its ranking of spaces.
V2_OPERATIONS = frozenset(
    {"aggregate_rank", "compare_facets", "period_compare", "relate", "aggregate", "comparison"}
)


def provider_failed(row: Dict[str, Any]) -> bool:
    """The plan's pre-registered test: a fallback wording, or a non-timeout degradation."""
    answer = (row.get("answer") or "").replace("’", "'")
    if any(f in answer for f in PROVIDER_FALLBACKS):
        return True
    degraded = row.get("ontosage_llm_degraded") or {}
    causes = degraded.get("causes") if isinstance(degraded, dict) else None
    return bool(causes and any(c != "pipeline_timeout" for c in causes))


def _steps(row: Dict[str, Any]) -> List[str]:
    trace = row.get("ontosage_plan_trace") or {}
    out = []
    for step in trace.get("steps") or []:
        out.append(str(step.get("stage") if isinstance(step, dict) else step))
    return out


def attribute(row: Dict[str, Any]) -> str:
    """'architecture' | 'deliberate-v1' | 'lane:<intent>' | 'error'."""
    if row.get("error"):
        return "error"
    lane = row.get("ontosage_intent") or (row.get("ontosage_route") or {}).get("final_node") or "?"
    if lane != "deliberate":
        return f"lane:{lane}"
    route = row.get("ontosage_route") or {}
    if f"contract:{ESCALATION_RULE}" in (route.get("overrides_applied") or []):
        return "architecture"  # routed here by the v2 rule, whatever the lane then did
    evidence = row.get("ontosage_evidence_record") or {}
    operation = str(evidence.get("operation") or "")
    steps = " ".join(_steps(row))
    facet_plan = operation in V2_OPERATIONS or "facet" in steps or "operation" in steps
    return "architecture" if facet_plan else "deliberate-v1"


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--set", required=True)
    ap.add_argument("--version", required=True)
    args = ap.parse_args()
    stem = Path(args.set).stem
    src = REPO / "eval" / "compound" / "results" / args.version / f"{stem}.jsonl"
    if not src.is_file():
        print(f"no capture at {src}", file=sys.stderr)
        return 2
    rows = [json.loads(x) for x in src.read_text(encoding="utf-8").splitlines() if x.strip()]
    per_item = {
        r["id"]: {"attribution": attribute(r), "provider_failed": provider_failed(r)} for r in rows
    }
    counts = Counter(v["attribution"] for v in per_item.values())
    failed = sorted(i for i, v in per_item.items() if v["provider_failed"])
    out = src.with_suffix(".attribution.json")
    out.write_text(
        json.dumps(
            {"set": stem, "version": args.version, "counts": dict(counts),
             "provider_failed": failed, "items": per_item},
            indent=1,
        ),
        encoding="utf-8",
    )
    print(f"{stem} {args.version}: {dict(counts)}; provider-failed {len(failed)} {failed}")
    print(f"wrote {out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
