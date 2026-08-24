#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Classify every changed answer against the golden baseline (V6-T54).

Every V6 task is gated on this: each changed answer must classify as **unchanged**,
**improved**, **intended tightening** (naming the gate that fired), or **REGRESSION** -- and
regressions must be zero.

WHY BYTE-IDENTITY IS REPORTED BUT NOT THE PASS CONDITION
-------------------------------------------------------
The obvious gate is "the text must match". It does not survive contact with this system, for
two reasons that have nothing to do with correctness:

* the building is LIVE. "What is the CO2 in 2.15" returns a different number every hour, and
  it should;
* the provider is not deterministic even at temperature 0. This project measured that
  directly while root-causing BUG-184: six identical prompts through the host Ollama at temp 0
  produced different text, and the CQ-IR parser absorbed most but not all of it.

So a byte-comparison over 1,580 questions would report near-total change and gate nothing. The
identity rate is still computed and printed, because it is a genuine signal about determinism
and because T55's acceptance criterion asks for it -- but the PASS condition is behavioural:
did the question route the same way, and did the answer keep the same standing?

WHAT COUNTS AS A REGRESSION
---------------------------
An answer that got worse with **no gate firing**. If a gate fired, the change is a tightening
and is attributable; if none did, something changed the answer for a reason nobody declared,
and that is exactly the class of silent drift the baseline exists to catch.

The direction matters as much as the change. An honest decline that became a confident answer
is reported as LOOSENED and listed for review even though it looks like an improvement --
that is the fabrication direction, and BUG-189 and BUG-218 both arrived looking like progress.

    python scripts/baseline_regression_gate.py --current <capture.csv>
    python scripts/baseline_regression_gate.py --current <c.csv> --baseline <b.csv> --md out.md
"""

from __future__ import annotations

import argparse
import csv
import re
import sys
from collections import Counter
from pathlib import Path
from typing import Dict, List, Optional, Tuple

REPO = Path(__file__).resolve().parent.parent
BASELINE_DIR = REPO / "scripts" / "outputs" / "baseline"

csv.field_size_limit(10_000_000)

#: The system's own standard refusal phrasings. Matched rather than judged: these are strings
#: the codebase emits, so recognising one is a fact about the output, not an opinion about it.
_DECLINE = re.compile(
    r"don't have that specific information|no information on record|not on record"
    r"|I don't have|cannot answer|not assessable|I can.t report|won.t substitute"
    r"|no data (?:is |was )?(?:available|recorded)|not been recorded",
    re.IGNORECASE,
)

#: Answer standing, coarse on purpose. A finer scale would invite arguing about degrees when
#: the only question the gate must settle is whether the system still stands behind an answer.
ANSWERED, DECLINED, EMPTY = "answered", "declined", "empty"

# Verdicts.
UNCHANGED = "unchanged"
LIVE_DRIFT = "live-drift"  # same standing, same lane, different text: a live building
REWORDED = "reworded"
ROUTE_CHANGED = "route-changed"
TIGHTENED = "tightened"  # answered -> declined, WITH a gate named
LOOSENED = "loosened"  # declined -> answered: review, this is the fabrication direction
IMPROVED = "improved"  # was empty, now says something
REGRESSION = "regression"  # got worse, no gate fired
DROPPED = "dropped"  # in the baseline, absent from the current run
ADDED = "added"

#: Verdicts that block. Deliberately short: a gate that fails on everything gets bypassed.
BLOCKING = {REGRESSION, DROPPED}


def standing(answer: str) -> str:
    if not (answer or "").strip():
        return EMPTY
    return DECLINED if _DECLINE.search(answer) else ANSWERED


def _read(path: Path) -> Dict[str, Dict[str, str]]:
    rows = list(csv.DictReader(path.read_text(encoding="utf-8-sig").splitlines()))
    return {r["qid"]: r for r in rows if r.get("qid")}


def classify(base: Dict[str, str], cur: Dict[str, str]) -> Tuple[str, str]:
    """One question's verdict, and the reason to print beside it."""
    b_ans, c_ans = base.get("answer", ""), cur.get("answer", "")
    b_stand, c_stand = standing(b_ans), standing(c_ans)
    b_intent, c_intent = base.get("intent", ""), cur.get("intent", "")
    gates = (cur.get("gates") or "").strip()

    if base.get("answer_sha") and base["answer_sha"] == cur.get("answer_sha"):
        return UNCHANGED, "byte-identical"

    if b_stand == c_stand:
        if b_intent != c_intent:
            # Same standing, different lane. Not a regression by itself -- but a question
            # quietly changing lane is one of the more informative things that can happen,
            # and it is invisible in the prose.
            return ROUTE_CHANGED, f"lane {b_intent or '?'} -> {c_intent or '?'}"
        if _numbers(b_ans) != _numbers(c_ans) and _skeleton(b_ans) == _skeleton(c_ans):
            return LIVE_DRIFT, "same wording, different readings"
        return REWORDED, "same standing and lane, different wording"

    if b_stand == ANSWERED and c_stand in (DECLINED, EMPTY):
        if gates:
            return TIGHTENED, f"declined by gate(s): {gates}"
        # The core rule. Something made the answer worse and nothing owns it.
        return REGRESSION, "answer became a decline with NO gate firing"

    if b_stand in (DECLINED, EMPTY) and c_stand == ANSWERED:
        # Looks like progress, and might be. Also the exact direction in which BUG-189 and
        # BUG-218 arrived, so it is surfaced for review rather than counted as a win.
        return (IMPROVED if b_stand == EMPTY else LOOSENED), (
            "was a decline, now answers -- confirm the evidence is real"
        )

    return REGRESSION, f"{b_stand} -> {c_stand}"


def _numbers(text: str) -> List[str]:
    return re.findall(r"-?\d+(?:\.\d+)?", text or "")


def _skeleton(text: str) -> str:
    """The sentence with its numbers removed.

    Two answers with the same skeleton and different numbers are the same answer about a
    building that moved, which is the single most common difference between any two runs here
    and must not be mistaken for a change in behaviour.
    """
    return re.sub(r"-?\d+(?:\.\d+)?", "#", text or "").strip()


def compare(baseline: Path, current: Path, *, partial: bool = False) -> Dict[str, object]:
    base, cur = _read(baseline), _read(current)

    # Quarantined rows are excluded from BOTH sides. Comparing against an outage would report
    # every later healthy answer as a change -- the failure BUG-176/177 produced twice.
    b_ok = {k: v for k, v in base.items() if v.get("status") == "OK"}
    c_ok = {k: v for k, v in cur.items() if v.get("status") == "OK"}
    comparable = sorted(set(b_ok) & set(c_ok))

    results: List[Dict[str, str]] = []
    for qid in comparable:
        verdict, reason = classify(b_ok[qid], c_ok[qid])
        results.append(
            {
                "qid": qid,
                "verdict": verdict,
                "reason": reason,
                "question": b_ok[qid].get("question", ""),
                "baseline_intent": b_ok[qid].get("intent", ""),
                "current_intent": c_ok[qid].get("intent", ""),
                "gates": c_ok[qid].get("gates", ""),
            }
        )

    # A question the baseline answered that the current run could not even ask is a hole in
    # the comparison, not a pass. Counted as blocking so a shrinking run cannot look clean.
    #
    # `partial` is the operator DECLARING that the subset was deliberate. It cannot be
    # inferred: a capture records only what it asked, so a question that was skipped and a
    # question that failed before writing a row look identical from the file. Making the
    # operator say so keeps the default honest -- a run that quietly shrank still fails.
    for qid in sorted(set(b_ok) - set(c_ok)):
        if partial:
            continue
        results.append(
            {
                "qid": qid,
                "verdict": DROPPED,
                "reason": "answered in the baseline, not usable in this run",
                "question": b_ok[qid].get("question", ""),
                "baseline_intent": b_ok[qid].get("intent", ""),
                "current_intent": "",
                "gates": "",
            }
        )
    for qid in sorted(set(c_ok) - set(b_ok)):
        results.append(
            {
                "qid": qid,
                "verdict": ADDED,
                "reason": "not comparable: absent from the baseline",
                "question": c_ok[qid].get("question", ""),
                "baseline_intent": "",
                "current_intent": c_ok[qid].get("intent", ""),
                "gates": c_ok[qid].get("gates", ""),
            }
        )

    counts = Counter(r["verdict"] for r in results)
    identical = counts.get(UNCHANGED, 0)
    blocking = [r for r in results if r["verdict"] in BLOCKING]
    return {
        "results": results,
        "counts": counts,
        "comparable": len(comparable),
        "identity_rate": (identical / len(comparable)) if comparable else 0.0,
        "blocking": blocking,
        "passed": not blocking,
        "partial": partial,
    }


def render(outcome: Dict[str, object], baseline: Path, current: Path) -> str:
    counts: Counter = outcome["counts"]  # type: ignore[assignment]
    results: List[Dict[str, str]] = outcome["results"]  # type: ignore[assignment]
    blocking: List[Dict[str, str]] = outcome["blocking"]  # type: ignore[assignment]
    n = outcome["comparable"]

    L = [
        "# Regression gate — current run vs golden baseline",
        "",
        f"**Baseline:** `{baseline.name}`  ",
        f"**Current:** `{current.name}`  ",
        f"**Comparable questions:** {n} (quarantined rows excluded from both sides)",
        (
            "**Partial run** — the current capture covered a declared subset, so questions "
            "absent from it are not counted as dropped. A pass here is evidence about the "
            "subset only."
            if outcome.get("partial")
            else ""
        ),
        "",
        "## Verdict",
        "",
        f"**{'PASS' if outcome['passed'] else 'FAIL'}** — {len(blocking)} blocking finding(s).",
        "",
        "| Verdict | Count | Blocks? |",
        "|---|---:|---|",
    ]
    for verdict, count in counts.most_common():
        L.append(f"| {verdict} | {count} | {'**yes**' if verdict in BLOCKING else 'no'} |")
    L += [
        "",
        f"Byte-identical: **{outcome['identity_rate']:.1%}** of comparable answers.",
        "",
        "That figure is reported, not gated. The building is live and the provider is not "
        "deterministic even at temperature 0 (measured while root-causing BUG-184), so text "
        "differing between runs is expected and says nothing about correctness. The pass "
        "condition is behavioural: same lane, same standing, and every tightening attributable "
        "to a gate that fired.",
        "",
    ]

    if blocking:
        L += ["## Blocking findings", ""]
        for r in blocking[:60]:
            L.append(f"- **{r['qid']}** — {r['reason']}")
            L.append(f"  - {r['question'][:150]}")
        if len(blocking) > 60:
            L.append(f"- …and {len(blocking) - 60} more (see the CSV).")
        L.append("")

    loosened = [r for r in results if r["verdict"] == LOOSENED]
    if loosened:
        L += [
            "## Declines that became answers — review these",
            "",
            "Not blocking, and not automatically good. This is the direction BUG-189 and "
            "BUG-218 both arrived from: an answer appearing where the system used to admit it "
            "could not say. Each one needs its evidence checked before it counts as progress.",
            "",
        ]
        for r in loosened[:30]:
            L.append(f"- **{r['qid']}** — {r['question'][:140]}")
        if len(loosened) > 30:
            L.append(f"- …and {len(loosened) - 30} more.")
        L.append("")

    tightened = [r for r in results if r["verdict"] == TIGHTENED]
    if tightened:
        by_gate = Counter(r["gates"] for r in tightened)
        L += [
            "## Tightenings, by the gate responsible",
            "",
            "| Gate(s) | Questions |",
            "|---|---:|",
        ]
        for gate, count in by_gate.most_common():
            L.append(f"| {gate or '(unnamed)'} | {count} |")
        L.append("")

    routed = [r for r in results if r["verdict"] == ROUTE_CHANGED]
    if routed:
        by_move = Counter(f"{r['baseline_intent']} -> {r['current_intent']}" for r in routed)
        L += ["## Lane changes", "", "| Move | Questions |", "|---|---:|"]
        for move, count in by_move.most_common(15):
            L.append(f"| {move} | {count} |")
        L.append("")

    return "\n".join(L) + "\n"


def _latest(pattern: str) -> Optional[Path]:
    files = sorted(BASELINE_DIR.glob(pattern), key=lambda p: p.stat().st_mtime)
    return files[-1] if files else None


def main(argv: List[str]) -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--current", required=True, help="capture to test")
    ap.add_argument("--baseline", default="", help="golden baseline (default: oldest capture)")
    ap.add_argument(
        "--partial",
        action="store_true",
        help="the current run deliberately covered a subset; do not treat absent questions "
        "as dropped",
    )
    ap.add_argument("--md", default="", help="write the report here")
    ap.add_argument("--csv", default="", help="write per-question verdicts here")
    args = ap.parse_args(argv)

    current = Path(args.current)
    baseline = Path(args.baseline) if args.baseline else _latest("baseline_*.csv")
    if not current.is_file() or not baseline or not baseline.is_file():
        print("need both a baseline and a current capture")
        return 2
    if current.resolve() == baseline.resolve():
        print("REFUSING: comparing a capture with itself proves nothing")
        return 2

    outcome = compare(baseline, current, partial=args.partial)
    if args.partial:
        print("PARTIAL run declared: absent questions are not counted as dropped.")
    report = render(outcome, baseline, current)

    out_md = Path(args.md) if args.md else current.with_name(current.stem + "_GATE.md")
    out_md.write_text(report, encoding="utf-8")
    if args.csv:
        rows: List[Dict[str, str]] = outcome["results"]  # type: ignore[assignment]
        with Path(args.csv).open("w", encoding="utf-8-sig", newline="") as fh:
            w = csv.DictWriter(fh, fieldnames=list(rows[0]) if rows else ["qid"])
            w.writeheader()
            w.writerows(rows)

    counts: Counter = outcome["counts"]  # type: ignore[assignment]
    print(f"comparable: {outcome['comparable']}  identical: {outcome['identity_rate']:.1%}")
    for verdict, count in counts.most_common():
        print(f"  {verdict:15} {count}")
    print(f"\n{'PASS' if outcome['passed'] else 'FAIL'} — wrote {out_md.name}")
    # Non-zero on failure so this can gate a task without anyone reading the output.
    return 0 if outcome["passed"] else 1


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
