#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Turn a capture into a ranked list of what to build next.

WHAT THIS IS FOR
----------------
A capture says what happened; it does not say what to do. This joins three things that
already exist and have never been read together:

* the captured ANSWER for each question (scripts/outputs/baseline/baseline_*.csv);
* the SOURCE SYSTEMS each question needs (docs/V7_question_demand.csv);
* the READINESS of each of those systems (scripts/source_system_readiness.py --json).

and reports, per system, how many questions would move if it were filled. That ranking is
the point: without it, "improve coverage" is a preference, and with it, it is an ordered
list with a measured size against each row.

GRADING IS REUSED, NOT REINVENTED
---------------------------------
`corpus_replay._heuristic_grade` and the COMPUTED / QUOTED / HONEST vocabulary in
`build_v7_scorecard` are what every previous measurement in this project used. A second
grader here would make this run incomparable with all of them, which is the whole failure
mode of BUG-359 and CAVEAT-393 in a new place.

A QUOTED PASSAGE IS NOT A COMPUTED ANSWER (BUG-370) and an HONEST DECLINE IS NOT A FAILURE
— for a question the building genuinely cannot answer, a decline naming what is missing is
the correct outcome. Those are three separate columns here and are never summed.

    python scripts/analyse_stakeholder_capture.py
    python scripts/analyse_stakeholder_capture.py --capture <path> --top 25
"""

from __future__ import annotations

import argparse
import csv
import importlib.util
import json
import subprocess  # nosec B404 - fixed local command
import sys
from collections import Counter, defaultdict
from pathlib import Path
from typing import Dict, List

REPO = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO))

COMPUTED = {"answered-with-data", "answered-with-proof"}
QUOTED = {"document-quoted"}
HONEST = {"honest-capability-answer", "clarified-appropriately"}


def _load_module(name: str, rel: str):
    spec = importlib.util.spec_from_file_location(name, REPO / rel)
    mod = importlib.util.module_from_spec(spec)
    sys.modules[name] = mod
    spec.loader.exec_module(mod)
    return mod


def _readiness() -> Dict[str, str]:
    """Live readiness per source system, or {} when it cannot be measured."""
    try:
        res = subprocess.run(  # nosec B603 B607
            [sys.executable, str(REPO / "scripts" / "source_system_readiness.py"), "--json"],
            capture_output=True,
            text=True,
            timeout=900,
            cwd=str(REPO),
        )
        # The payload is pretty-printed across many lines, so parse the WHOLE stdout from
        # its first bracket rather than line by line. A line-wise parse found nothing and
        # every system reported '?', which reads like an answer instead of a failure.
        body = res.stdout or ""
        starts = [i for i in (body.find("["), body.find("{")) if i >= 0]
        if starts:
            data = json.loads(body[min(starts) :])
            rows_j = (
                data
                if isinstance(data, list)
                else (data.get("systems") or data.get("results") or [])
            )
            return {r["source_system"]: r["readiness"] for r in rows_j}
    except Exception as exc:
        print(f"[warn] readiness unavailable ({type(exc).__name__}); systems will show '?'")
    return {}


def _pct(part: int, whole: int) -> float:
    return 100.0 * part / whole if whole else 0.0


def main(argv: List[str]) -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--capture", default="")
    ap.add_argument("--demand", default=str(REPO / "docs" / "V7_question_demand.csv"))
    ap.add_argument("--top", type=int, default=20)
    ap.add_argument("--out", default=str(REPO / "docs" / "V7_GAP_PLAN.md"))
    args = ap.parse_args(argv)

    capture = Path(args.capture) if args.capture else None
    if capture is None:
        found = sorted((REPO / "scripts" / "outputs" / "baseline").glob("baseline_*.csv"))
        if not found:
            raise SystemExit("no capture found")
        capture = found[-1]

    replay = _load_module("_replay", "scripts/corpus_replay.py")
    grade_of = replay._heuristic_grade

    with capture.open(encoding="utf-8-sig", newline="") as fh:
        rows = list(csv.DictReader(fh))
    demand = {}
    with Path(args.demand).open(encoding="utf-8-sig", newline="") as fh:
        for r in csv.DictReader(fh):
            demand[r["ID"]] = [s for s in (r.get("source_systems") or "").split("|") if s]

    ready = _readiness()

    graded: List[Dict[str, str]] = []
    for r in rows:
        if r.get("status") != "OK":
            grade = "unmeasured"
        else:
            try:
                grade = grade_of(r.get("question", ""), r.get("answer", "") or "")
            except Exception:
                grade = "wrong"
        graded.append({**r, "grade": grade})

    n = len(graded)
    counts = Counter(g["grade"] for g in graded)
    computed = sum(c for k, c in counts.items() if k in COMPUTED)
    quoted = sum(c for k, c in counts.items() if k in QUOTED)
    honest = sum(c for k, c in counts.items() if k in HONEST)
    unmeasured = counts.get("unmeasured", 0)
    failed = n - computed - quoted - honest - unmeasured

    out: List[str] = []
    out.append(f"# Gap plan — {capture.name}\n")
    out.append(
        f"Questions: **{n}**  ·  models: "
        + ", ".join(
            f"{m}×{c}" for m, c in Counter(g.get("model") or "?" for g in graded).most_common()
        )
        + "\n"
    )
    out.append("| outcome | n | share |")
    out.append("|---|---:|---:|")
    for label, v in (
        ("**Computed** (figures from the building)", computed),
        ("Quoted (a passage, not a calculation)", quoted),
        ("Honest decline (correct when data is absent)", honest),
        ("Failed / wrong", failed),
        ("Unmeasured (timeout — retry these)", unmeasured),
    ):
        out.append(f"| {label} | {v} | {_pct(v, n):.1f}% |")

    # ── the ranking that decides what to build ─────────────────────────────────────────
    unmet: Dict[str, int] = defaultdict(int)
    unmet_ids: Dict[str, List[str]] = defaultdict(list)
    for g in graded:
        if g["grade"] in COMPUTED:
            continue  # already answered with data; nothing to unlock
        for system in demand.get(g.get("qid", ""), []):
            unmet[system] += 1
            if len(unmet_ids[system]) < 4:
                unmet_ids[system].append(g.get("qid", ""))

    # A question whose systems are ALL ready but which did not compute is not waiting for
    # data -- it is waiting for the lane to use what is already there. V7's own finding was
    # exactly this ("99 of 111 have every source as DATA and only 33% compute"), and mixing
    # the two makes the ranking useless: sensor_telemetry tops any list of "systems named by
    # non-computed questions" while being the best-populated store in the building.
    data_gap = routing_gap = 0
    routing_examples: List[str] = []
    for g in graded:
        if g["grade"] in COMPUTED or g["grade"] == "unmeasured":
            continue
        systems = demand.get(g.get("qid", ""), [])
        if systems and all(ready.get(s) == "DATA" for s in systems):
            routing_gap += 1
            if len(routing_examples) < 6:
                routing_examples.append(g.get("qid", "") + " [" + (g.get("intent") or "") + "]")
        else:
            data_gap += 1
    out.append("")
    out.append("## Is the gap data, or is it routing?")
    out.append("")
    out.append("| the question did not compute because | n |")
    out.append("|---|---:|")
    out.append(
        "| every system it needs is READY - the lane did not use them | **%d** |" % routing_gap
    )
    out.append("| at least one system it needs is not ready | %d |" % data_gap)
    if routing_examples:
        out.append("")
        out.append("Examples of the first kind: " + ", ".join(routing_examples))
    out.append("\n## What to build, ranked by questions it would move\n")
    out.append("| source system | readiness | non-computed questions naming it | examples |")
    out.append("|---|---|---:|---|")
    for system, count in sorted(unmet.items(), key=lambda kv: -kv[1])[: args.top]:
        out.append(
            f"| `{system}` | {ready.get(system, '?')} | {count} | "
            f"{', '.join(unmet_ids[system])} |"
        )

    # ── per role, so a stakeholder can be told what they get ───────────────────────────
    by_role: Dict[str, List[Dict[str, str]]] = defaultdict(list)
    for g in graded:
        by_role[g.get("stakeholder_role", "?")].append(g)
    out.append("\n## Per stakeholder role\n")
    out.append("| role | n | computed | quoted | honest | failed | unmeasured |")
    out.append("|---|---:|---:|---:|---:|---:|---:|")
    for role, subset in sorted(
        by_role.items(),
        key=lambda kv: -_pct(sum(1 for g in kv[1] if g["grade"] in COMPUTED), len(kv[1])),
    ):
        m = len(subset)
        c = sum(1 for g in subset if g["grade"] in COMPUTED)
        q = sum(1 for g in subset if g["grade"] in QUOTED)
        h = sum(1 for g in subset if g["grade"] in HONEST)
        u = sum(1 for g in subset if g["grade"] == "unmeasured")
        out.append(
            f"| {role[:46]} | {m} | **{_pct(c, m):.0f}%** | {_pct(q, m):.0f}% | "
            f"{_pct(h, m):.0f}% | {_pct(m - c - q - h - u, m):.0f}% | {u} |"
        )

    # ── per intent, so a routing gap is separable from a data gap ──────────────────────
    by_intent: Dict[str, List[Dict[str, str]]] = defaultdict(list)
    for g in graded:
        by_intent[g.get("intent") or "(none)"].append(g)
    out.append("\n## Per lane\n")
    out.append("| intent | n | computed | quoted | honest | failed |")
    out.append("|---|---:|---:|---:|---:|---:|")
    for intent, subset in sorted(by_intent.items(), key=lambda kv: -len(kv[1]))[:14]:
        m = len(subset)
        c = sum(1 for g in subset if g["grade"] in COMPUTED)
        q = sum(1 for g in subset if g["grade"] in QUOTED)
        h = sum(1 for g in subset if g["grade"] in HONEST)
        out.append(
            f"| {intent} | {m} | {_pct(c, m):.0f}% | {_pct(q, m):.0f}% | "
            f"{_pct(h, m):.0f}% | {_pct(m - c - q - h, m):.0f}% |"
        )

    text = "\n".join(out) + "\n"
    Path(args.out).write_text(text, encoding="utf-8")
    csv_out = Path(args.out).with_suffix(".csv")
    with csv_out.open("w", encoding="utf-8", newline="") as fh:
        w = csv.writer(fh)
        w.writerow(["qid", "role", "intent", "grade", "systems", "question"])
        for g in graded:
            w.writerow(
                [
                    g.get("qid", ""),
                    g.get("stakeholder_role", ""),
                    g.get("intent", ""),
                    g["grade"],
                    "|".join(demand.get(g.get("qid", ""), [])),
                    g.get("question", ""),
                ]
            )
    print(text[: text.index("## Per stakeholder role")])
    print(f"[written] {args.out}\n[written] {csv_out}")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
