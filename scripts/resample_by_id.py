#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Re-ask a named list of question ids and report what changed, per role.

WHY THIS EXISTS
---------------
A capture is a photograph of one configuration. Eleven registers, a scored class matcher and
a grader fix landed after the last one, so planning from it would target gaps that may
already be closed — and a full 2,960 re-capture costs seven hours to find that out.

This re-asks a named subset. Given a stratified sample of the questions that did NOT compute,
it answers the only question a plan needs: **how many of them are already fixed?**

Grading is `corpus_replay._heuristic_grade`, the same function every measurement in this
project uses. The model is stamped per row, because a comparison across two models is not a
comparison of the change (CAVEAT-411).

    python scripts/resample_by_id.py --ids scripts/outputs/_resample_ids.txt
"""

from __future__ import annotations

import argparse
import csv
import importlib.util
import sys
import time
from collections import defaultdict
from pathlib import Path
from typing import Dict, List

REPO = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO))

COMPUTED = {"answered-with-data", "answered-with-proof"}
QUOTED = {"document-quoted"}
HONEST = {"honest-capability-answer", "clarified-appropriately"}


def _load(name: str, rel: str):
    spec = importlib.util.spec_from_file_location(name, REPO / rel)
    mod = importlib.util.module_from_spec(spec)
    sys.modules[name] = mod
    spec.loader.exec_module(mod)
    return mod


def _bucket(grade: str) -> str:
    if grade in COMPUTED:
        return "computed"
    if grade in QUOTED:
        return "quoted"
    if grade in HONEST:
        return "honest"
    return "failed"


def main(argv: List[str]) -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--ids", required=True, help="file of question ids, one per line")
    ap.add_argument("--bank", default=str(REPO / "tasks" / "smart_building_questions.csv"))
    ap.add_argument("--previous", default=str(REPO / "tasks" / "V8_QA_RESULTS.csv"))
    ap.add_argument("--base-url", default="http://127.0.0.1:8000")
    ap.add_argument("--out", default=str(REPO / "docs" / "V9_RESAMPLE.md"))
    args = ap.parse_args(argv)

    cap = _load("_cap", "scripts/capture_golden_baseline.py")
    replay = _load("_replay", "scripts/corpus_replay.py")
    grade_of = replay._heuristic_grade

    wanted = [
        line.strip()
        for line in Path(args.ids).read_text(encoding="utf-8").splitlines()
        if line.strip()
    ]
    with open(args.bank, encoding="utf-8-sig", newline="") as fh:
        bank = {r["ID"]: r for r in csv.DictReader(fh)}
    with open(args.previous, encoding="utf-8-sig", newline="") as fh:
        prev = {r["qid"]: r for r in csv.DictReader(fh)}

    token = cap._login(args.base_url)
    provider, model = cap._active_model(args.base_url, token)
    print(f"re-asking {len(wanted)} questions with {provider}/{model}", flush=True)

    out_rows: List[Dict[str, str]] = []
    t0 = time.time()
    for i, qid in enumerate(wanted, 1):
        q = bank.get(qid)
        if not q:
            continue
        res = cap._ask(q["Question"], args.base_url, "", token)
        after = (
            "failed"
            if res["status"] != "OK"
            else _bucket(grade_of(q["Question"], str(res["answer"] or "")))
        )
        out_rows.append(
            {
                "qid": qid,
                "role": q.get("Stakeholder_Role", ""),
                "question": q["Question"],
                "before": (prev.get(qid) or {}).get("outcome", "?"),
                "after": after,
                "intent": str(res["intent"]),
                "answer": str(res["answer"] or "")[:6000],
            }
        )
        if i % 20 == 0 or i == len(wanted):
            rate = (time.time() - t0) / i
            print(
                f"  {i}/{len(wanted)}  {rate:.1f}s/q  ETA {int(rate*(len(wanted)-i)/60)} min",
                flush=True,
            )

    fixed = [r for r in out_rows if r["after"] == "computed"]
    lines = ["# Re-sample of questions that did not compute\n"]
    lines.append(f"Model: `{provider}/{model}` · {len(out_rows)} questions, 5 per role\n")
    lines.append(
        f"**Already fixed by work landed since the capture: {len(fixed)} of {len(out_rows)} "
        f"({100*len(fixed)/max(len(out_rows),1):.0f}%)**\n"
    )
    lines.append("| outcome now | n |")
    lines.append("|---|---:|")
    counts: Dict[str, int] = defaultdict(int)
    for r in out_rows:
        counts[r["after"]] += 1
    for k in ("computed", "quoted", "honest", "failed"):
        lines.append(f"| {k} | {counts[k]} |")

    lines.append("\n## Still not computing, by lane\n")
    lines.append("| intent | n |")
    lines.append("|---|---:|")
    still: Dict[str, int] = defaultdict(int)
    for r in out_rows:
        if r["after"] != "computed":
            still[r["intent"] or "(none)"] += 1
    for k, v in sorted(still.items(), key=lambda kv: -kv[1]):
        lines.append(f"| {k} | {v} |")

    lines.append("\n## Per role\n")
    lines.append("| role | n | now computing |")
    lines.append("|---|---:|---:|")
    by_role: Dict[str, List[Dict[str, str]]] = defaultdict(list)
    for r in out_rows:
        by_role[r["role"]].append(r)
    for role, rs in sorted(
        by_role.items(), key=lambda kv: -sum(1 for r in kv[1] if r["after"] == "computed")
    ):
        c = sum(1 for r in rs if r["after"] == "computed")
        lines.append(f"| {role[:44]} | {len(rs)} | {c} |")

    Path(args.out).write_text("\n".join(lines) + "\n", encoding="utf-8")
    with Path(args.out).with_suffix(".csv").open("w", encoding="utf-8", newline="") as fh:
        w = csv.DictWriter(fh, fieldnames=list(out_rows[0]))
        w.writeheader()
        w.writerows(out_rows)
    print("\n".join(lines[:12]))
    print(f"\n[written] {args.out}")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
