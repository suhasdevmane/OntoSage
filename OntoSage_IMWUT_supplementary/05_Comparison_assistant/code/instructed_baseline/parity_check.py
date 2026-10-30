#!/usr/bin/env python3
"""Parity check for the instructed assistant (spec §7, tracker E4): did its TOOLS retrieve each fact a
development form needs, in at least 2 of 3 runs, whatever its final answer said?

The facts are read from the task bank's development-form keys (task_bank_instances.json), so the
check cannot be tuned after the fact. Pass/fail is about retrieval capability only: whether the answer
used the facts correctly is what the comparison itself measures.

    python scripts/instructed_baseline/parity_check.py outputs/instructed_baseline/parity_dev.jsonl
"""

from __future__ import annotations

import argparse
import json
import sys
from collections import defaultdict
from pathlib import Path
from typing import Any, Dict, List

REPO = Path(__file__).resolve().parents[2]
TASKS = (
    REPO
    / "paper"
    / "phd plan"
    / "[anonymised]"
    / "11_Study_Materials"
    / "C_Task_Bank_and_Keys"
    / "task_bank_instances.json"
)


def readings(rec: Dict[str, Any]) -> List[Dict[str, Any]]:
    out = []
    for s in rec.get("steps", []):
        if s.get("action") == "get_readings":
            out += [r for r in (s.get("result") or {}).get("readings", []) if r.get("n")]
    return out


def text_of(rec: Dict[str, Any], action: str) -> str:
    return " ".join(
        json.dumps(s.get("result"), ensure_ascii=False)
        for s in rec.get("steps", [])
        if s.get("action") == action
    )


def facts_for(form: str, key: Dict[str, Any], params: Dict[str, Any]) -> Dict[str, Any]:
    """{fact name: predicate(record) -> bool} for one development form."""
    if form == "S1-D":
        target = float(key["answer_ppm"])
        return {
            "CO2 readings for the room and window (max matches the key)": lambda r: any(
                abs(float(x.get("max", -1)) - target) <= 0.5 for x in readings(r)
            )
        }
    if form == "S2-D":
        n_key = int(key.get("n", 0))
        return {
            "temperature readings covering the whole held part of March": lambda r: any(
                x.get("n", 0) >= 0.95 * n_key and not x.get("row_limit_hit") for x in readings(r)
            )
        }
    if form == "S3-D":
        return {
            "the absence of any radon point": lambda r: '"points": []' in text_of(r, "find_points")
            or '"matches": []' in text_of(r, "resolve_terms")
        }
    if form == "S4-D":
        means = key["mean_c"]
        rooms = list(means)
        fs = {
            f"temperature readings for Room {room} (mean matches the key)": (
                lambda r, m=float(means[room]): any(
                    abs(float(x.get("mean", -99)) - m) <= 0.05 for x in readings(r)
                )
            )
            for room in rooms
        }
        warmer = max(means, key=lambda k: means[k])
        fs[f"the recorded capacity of the warmer room ({warmer})"] = (
            lambda r, w=warmer: f"Room{w}" in text_of(r, "find_spaces")
            and "roomCapacity" in text_of(r, "find_spaces")
        )
        return fs
    return {}


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("runs")
    ap.add_argument("--out", default="")
    args = ap.parse_args()
    forms = {
        f["form"]: f
        for f in json.loads(TASKS.read_text(encoding="utf-8"))["forms"]
        if f["use"] == "development"
    }
    recs = [
        json.loads(x) for x in Path(args.runs).read_text(encoding="utf-8").splitlines() if x.strip()
    ]
    by_form: Dict[str, List[Dict[str, Any]]] = defaultdict(list)
    for r in recs:
        by_form[r["qid"]].append(r)
    lines = [
        "# Parity check — instructed assistant on the development forms",
        "",
        f"Runs file: `{Path(args.runs).name}` · code_sha {recs[0].get('code_sha') if recs else '?'} · "
        f"prompt {recs[0].get('prompt_version') if recs else '?'} ({recs[0].get('prompt_sha') if recs else '?'}) · "
        f"mode {recs[0].get('mode') if recs else '?'}",
        "",
        "| Form | Needed fact | Runs retrieving it | Pass (≥ 2 of 3) |",
        "|---|---|---|---|",
    ]
    all_pass = True
    for form in sorted(forms):
        f = forms[form]
        runs = by_form.get(form, [])
        for name, pred in facts_for(form, f["key"], f["params"]).items():
            hits = sum(1 for r in runs if pred(r))
            ok = hits >= 2 and len(runs) >= 3
            all_pass &= ok
            lines.append(
                f"| {form} | {name} | {hits} of {len(runs)} | {'PASS' if ok else 'FAIL'} |"
            )
    pf = sum(1 for r in recs if r.get("provider_failure"))
    lines += [
        "",
        f"Provider failures: {pf} of {len(recs)} runs. Verdict: **{'PASS' if all_pass else 'FAIL'}**.",
    ]
    report = "\n".join(lines) + "\n"
    print(report)
    if args.out:
        Path(args.out).write_text(report, encoding="utf-8")
    return 0 if all_pass else 1


if __name__ == "__main__":
    sys.exit(main())
