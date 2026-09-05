#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Ask the live system the questions we have already proved it can answer.

WHY THIS EXISTS
---------------
The unit suite protects the CODE. It cannot tell you that "who do I contact about a broken
door closer?" still returns DEP-01 and a 24-hour target, because that answer depends on the
graph, the registers, five routing components and the model — none of which a unit test
exercises together.

Every fix in this project's history that broke something else broke it exactly here: a
routing guard added for one question shape silently took another shape with it. BUG-431's
first fix is the clearest case — it corrected "how many CO2 sensors" and, in doing so,
started answering it with the building-wide total instead. A unit test would not have
noticed; this would.

WHAT IT CHECKS
--------------
Each case names a question and a `expect` marker that MUST appear in the answer — a figure,
a record id, a department code. Markers are facts the register holds, not phrasings, so a
reworded answer still passes and a wrong FIGURE fails. `forbid` catches known-wrong answers
that a regression would bring back.

    python scripts/regression_probe.py              # all cases
    python scripts/regression_probe.py --only registers
    python scripts/regression_probe.py --baseline   # write the current answers as the record
"""

from __future__ import annotations

import argparse
import importlib.util
import json
import sys
import time
from pathlib import Path
from typing import Any, Dict, List

REPO = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO))

CASES_PATH = REPO / "scripts" / "regression_cases.json"


def _load(name: str, rel: str):
    spec = importlib.util.spec_from_file_location(name, REPO / rel)
    mod = importlib.util.module_from_spec(spec)
    sys.modules[name] = mod
    spec.loader.exec_module(mod)
    return mod


def _matches(answer: str, marker: str) -> bool:
    """Case-insensitive, and tolerant of the separators a model renders numbers with.

    A model writes 2,728 or 2728 or 2 728 for the same figure, and an en-dash where the
    register has a hyphen. Failing a regression check on typography would train whoever
    runs this to ignore it, which is worse than not having it.
    """
    a = answer.lower().replace(",", "").replace("‑", "-").replace("–", "-")
    a = a.replace("’", "'").replace(" ", " ").replace("\xa0", " ")
    m = marker.lower().replace(",", "").replace("‑", "-").replace("–", "-")
    return m in a


def main(argv: List[str]) -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--base-url", default="http://127.0.0.1:8000")
    ap.add_argument("--only", default="", help="run only cases in this group")
    ap.add_argument("--out", default=str(REPO / "docs" / "REGRESSION_PROBE.md"))
    args = ap.parse_args(argv)

    cases: List[Dict[str, Any]] = json.loads(CASES_PATH.read_text(encoding="utf-8"))
    if args.only:
        cases = [c for c in cases if c.get("group") == args.only]
    if not cases:
        print("no cases selected")
        return 2

    cap = _load("_cap", "scripts/capture_golden_baseline.py")
    # RETRY THE LOGIN. The first request after a container restart routinely exceeds the
    # 30-second read timeout while the app finishes warming, and a probe that dies at the
    # door reports nothing about the system — which is indistinguishable, in a log, from a
    # probe that found nothing wrong.
    token = None
    for attempt in range(1, 6):
        try:
            token = cap._login(args.base_url)
            break
        except Exception as exc:
            if attempt == 5:
                print(f"could not authenticate after 5 attempts: {exc}")
                return 2
            print(f"  login attempt {attempt} failed ({type(exc).__name__}), retrying")
            time.sleep(20)
    provider, model = cap._active_model(args.base_url, token)
    print(f"regression probe: {len(cases)} cases against {provider}/{model}\n")

    rows, failed = [], 0
    t0 = time.time()
    for i, case in enumerate(cases, 1):
        res = cap._ask(case["question"], args.base_url, "", token)
        answer = str(res.get("answer") or "")
        missing = [m for m in case.get("expect", []) if not _matches(answer, m)]
        present = [f for f in case.get("forbid", []) if _matches(answer, f)]
        # `expect_any` is satisfied by ANY ONE of its markers.
        #
        # The same fact is rendered differently between runs at temperature: the overdue
        # fume cupboard comes back as "FC-301", as "HZ-003" and as "Level 3 fume cupboard",
        # all correct. A marker list requiring every spelling fails on style, and a probe
        # that cries wolf is one nobody reads — which costs more than having none, because
        # a real regression then arrives among the noise.
        alternatives = case.get("expect_any", [])
        any_missing = bool(alternatives) and not any(_matches(answer, m) for m in alternatives)
        ok = res["status"] == "OK" and not missing and not present and not any_missing
        if not ok:
            failed += 1
        why = ""
        if res["status"] != "OK":
            why = f"transport {res['status']}"
        elif missing:
            why = f"missing {missing}"
        elif any_missing:
            why = f"none of {alternatives}"
        elif present:
            why = f"forbidden present {present}"
        print(
            f"  {'PASS' if ok else 'FAIL'}  [{case.get('group','')}] "
            f"{case['question'][:62]}"
            + (f"\n         -> {why}" if why else "")
        )
        rows.append(
            {
                "group": case.get("group", ""),
                "question": case["question"],
                "ok": ok,
                "why": why,
                "intent": str(res.get("intent") or ""),
                "answer": answer[:1200],
            }
        )

    elapsed = time.time() - t0
    print(f"\n{len(rows) - failed}/{len(rows)} pass in {elapsed / 60:.1f} min")

    lines = [
        "# Regression probe — answers this system has already been proved to give\n",
        f"Model: `{provider}/{model}` · {len(rows)} cases · "
        f"**{len(rows) - failed} pass, {failed} fail**\n",
        "Each case asserts a FACT the registers hold — a figure, a record id, a department "
        "code — not a phrasing, so a reworded answer passes and a wrong figure fails.\n",
        "| result | group | question | why |",
        "|---|---|---|---|",
    ]
    for r in rows:
        lines.append(
            f"| {'PASS' if r['ok'] else '**FAIL**'} | {r['group']} | "
            f"{r['question'][:70]} | {r['why']} |"
        )
    # THE ANSWER, for every failure. A probe that reports "missing ['ws-']" and not what
    # came back instead cannot tell a broken system from a badly chosen marker, and the
    # first thing anyone does with it is re-ask the question by hand.
    fails = [r for r in rows if not r["ok"]]
    if fails:
        lines.append("")
        lines.append("## What came back instead")
        lines.append("")
        for r in fails:
            lines.append(f"### {r['question']}")
            lines.append("")
            lines.append(f"- **why:** {r['why']} · **intent:** `{r['intent']}`")
            lines.append("")
            lines.append("```")
            lines.append((r["answer"] or "")[:900])
            lines.append("```")
            lines.append("")
    Path(args.out).write_text("\n".join(lines) + "\n", encoding="utf-8")
    print(f"[written] {args.out}")
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
