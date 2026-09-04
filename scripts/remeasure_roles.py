#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Re-ask one or more stakeholder roles and report the change, per role.

Built to close the loop on work chosen from a measurement: four registers were added
because four roles measured worst on the 2,480-question capture, so the only honest way to
say whether they helped is to ask the same questions again and grade them the same way.

GRADING IS THE SAME FUNCTION the baseline used (`corpus_replay._heuristic_grade`) and the
same COMPUTED / QUOTED / HONEST vocabulary. A second grader would make the two runs
incomparable, which is BUG-359 and CAVEAT-393 in a new place.

The model is stamped per row, because a comparison across two different models is not a
comparison of the change (CAVEAT-411).

    python scripts/remeasure_roles.py --roles "Cleaning and caretaking,Visitors and event"
    python scripts/remeasure_roles.py --baseline scripts/outputs/baseline/baseline_X.csv
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
    ap.add_argument("--roles", required=True, help="comma-separated role prefixes")
    ap.add_argument("--bank", default=str(REPO / "tasks" / "smart_building_questions.csv"))
    ap.add_argument("--baseline", default="")
    ap.add_argument("--base-url", default="http://127.0.0.1:8000")
    ap.add_argument("--out", default=str(REPO / "docs" / "V8_REMEASURE.md"))
    args = ap.parse_args(argv)

    cap = _load("_cap", "scripts/capture_golden_baseline.py")
    replay = _load("_replay", "scripts/corpus_replay.py")
    grade_of = replay._heuristic_grade

    prefixes = [p.strip() for p in args.roles.split(",") if p.strip()]
    with open(args.bank, encoding="utf-8-sig", newline="") as fh:
        bank = [
            r
            for r in csv.DictReader(fh)
            if r.get("Source") == "stakeholder_catalogue_37"
            and any((r.get("Stakeholder_Role") or "").startswith(p) for p in prefixes)
        ]
    if not bank:
        raise SystemExit("no questions matched those roles")

    before: Dict[str, str] = {}
    baseline = args.baseline
    if not baseline:
        found = sorted((REPO / "scripts" / "outputs" / "baseline").glob("baseline_*.csv"))
        baseline = str(found[-1]) if found else ""
    if baseline:
        with open(baseline, encoding="utf-8-sig", newline="") as fh:
            for r in csv.DictReader(fh):
                if r.get("status") != "OK":
                    before[r["qid"]] = "failed"
                    continue
                before[r["qid"]] = _bucket(grade_of(r.get("question", ""), r.get("answer") or ""))

    token = cap._login(args.base_url)
    provider, model = cap._active_model(args.base_url, token)
    print(f"re-asking {len(bank)} questions with {provider}/{model}")

    after: Dict[str, str] = {}
    rows_out: List[Dict[str, str]] = []
    t0 = time.time()
    for i, q in enumerate(bank, 1):
        res = cap._ask(q["Question"], args.base_url, "", token)
        grade = (
            "failed"
            if res["status"] != "OK"
            else _bucket(grade_of(q["Question"], str(res["answer"] or "")))
        )
        after[q["ID"]] = grade
        rows_out.append(
            {
                "qid": q["ID"],
                "role": q.get("Stakeholder_Role", ""),
                "question": q["Question"],
                "before": before.get(q["ID"], "?"),
                "after": grade,
                "intent": str(res["intent"]),
                "answer": str(res["answer"] or "")[:4000],
            }
        )
        if i % 20 == 0 or i == len(bank):
            rate = (time.time() - t0) / i
            print(
                f"  {i}/{len(bank)}  {rate:.1f}s/q  ETA {int(rate * (len(bank) - i) / 60)} min",
                flush=True,
            )

    by_role: Dict[str, List[Dict[str, str]]] = defaultdict(list)
    for r in rows_out:
        by_role[r["role"]].append(r)

    out = ["# Re-measurement after the register work\n"]
    out.append(f"Model: `{provider}/{model}`  ·  questions: {len(rows_out)}\n")
    out.append("| role | n | computed before | computed after | change |")
    out.append("|---|---:|---:|---:|---:|")
    for role, subset in sorted(by_role.items()):
        n = len(subset)
        b = sum(1 for r in subset if r["before"] == "computed")
        a = sum(1 for r in subset if r["after"] == "computed")
        out.append(
            f"| {role[:44]} | {n} | {100*b/n:.0f}% | **{100*a/n:.0f}%** | "
            f"{'+' if a >= b else ''}{100*(a-b)/n:.0f} pts |"
        )
    nb = sum(1 for r in rows_out if r["before"] == "computed")
    na = sum(1 for r in rows_out if r["after"] == "computed")
    out.append(
        f"| **all four** | {len(rows_out)} | {100*nb/len(rows_out):.0f}% | "
        f"**{100*na/len(rows_out):.0f}%** | {'+' if na >= nb else ''}"
        f"{100*(na-nb)/len(rows_out):.0f} pts |"
    )

    moved = [r for r in rows_out if r["before"] != r["after"]]
    gained = [r for r in moved if r["after"] == "computed"]
    lost = [r for r in moved if r["before"] == "computed" and r["after"] != "computed"]
    out.append(f"\nQuestions that began computing: **{len(gained)}**")
    out.append(f"Questions that stopped computing: **{len(lost)}** — these are regressions\n")
    for r in lost[:10]:
        out.append(f"- REGRESSION `{r['qid']}` [{r['intent']}] {r['question'][:90]}")
    out.append("\n## Newly computed, by role\n")
    for role, subset in sorted(by_role.items()):
        g = [r for r in subset if r["before"] != "computed" and r["after"] == "computed"]
        out.append(f"\n### {role} — {len(g)} newly computed\n")
        for r in g[:8]:
            out.append(f"- `{r['qid']}` {r['question'][:96]}")

    Path(args.out).write_text("\n".join(out) + "\n", encoding="utf-8")
    with Path(args.out).with_suffix(".csv").open("w", encoding="utf-8", newline="") as fh:
        w = csv.DictWriter(fh, fieldnames=list(rows_out[0]))
        w.writeheader()
        w.writerows(rows_out)
    print("\n".join(out[:12]))
    print(f"\n[written] {args.out}")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
