# -*- coding: utf-8 -*-
"""Offline measurement of the claim binder over a recorded answer bank (A2).

**NO LIVE ASKS.** Everything here reads files that a previous run already wrote, so the number
it produces can be regenerated at any time, on any machine, without the GPU:

* ``docs/phase0/phase0_rerun.md.jsonl``       — the answers as the readers received them
* ``docs/phase0/phase0_rerun_read.jsonl``     — the hand read (0-indexed ``row``, class, verdict)
* ``docs/phase0/phase0_rerun_evidence.jsonl`` — the per-turn graph evidence those same runs
  recorded, matched back to each question

**The caveat is in the output, not in a footnote.** The recorded captures hold the GRAPH
evidence for a turn. A turn that went on to read a time-series store has evidence this
measurement cannot see, and its figures would look unbound when they are not. Those turns are
detected from the projection the lane asked for (a timeseries id or a store reference means a
store read followed) and reported separately as PARTIAL. **The headline rate is over turns
whose recorded evidence is complete**, and the other two buckets are printed beside it so
nobody can quote the flattering one alone.

Regenerating the evidence file (only needed after a new bank run)::

    docker cp scripts/_extract_bank_evidence.py <orchestrator>:/tmp/x.py
    docker exec <orchestrator> python /tmp/x.py < docs/phase0/phase0_rerun.md.jsonl

**The enforcement replay (CAVEAT-769).** ``--replay-enforcement`` answers the only question
that matters before the flag is switched on again: *with the lanes now recording what they
compute, and enforcement conditional on the record being complete, how many recorded answers
would enforcement have CHANGED -- and how many of those changes would have removed a CORRECT
figure?* It measures two variants over the same corpora, side by side:

``A`` (reverted)
    ``require_complete_evidence=False`` and no computed figures. This is exactly what ran
    live for 25 minutes on 2026-09-18, reproduced rather than remembered.

``B`` (proposed)
    Computed figures recorded, enforcement withheld unless the turn's record is complete.

Correctness is judged against ground truth that was written down before this module existed:
the regression probe's own ``expect`` markers for the counts lane (reconstructed from its
real figures in ``docs/phase0/counts_lane_fixture.json``), and the hand-read verdicts for the
recorded bank. A change that removes a probe marker, or that touches an answer a human read
as GOOD, is a correct figure removed.

Usage::

    python scripts/measure_claim_binding.py [--out docs/phase0/claim_binding_measurement.json]
    python scripts/measure_claim_binding.py --replay-enforcement
"""
from __future__ import annotations

import argparse
import json
import re
import sys
from collections import Counter
from pathlib import Path
from typing import Any, Dict, List

REPO = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO))

from orchestrator.services.claim_binder import analyse  # noqa: E402

PHASE0 = REPO / "docs" / "phase0"
ANSWERS = PHASE0 / "phase0_rerun.md.jsonl"
READ = PHASE0 / "phase0_rerun_read.jsonl"
EVID = PHASE0 / "phase0_rerun_evidence.jsonl"
BANK = PHASE0 / "phase0_bank.jsonl"
DEFAULT_OUT = PHASE0 / "claim_binding_measurement.json"

#: A projection carrying one of these went on to read a store this measurement cannot see.
_STORE_VARS = ("uuid", "uuidvalue", "storage", "storageref")


def norm(s: Any) -> str:
    return " ".join(str(s or "").split()).strip().lower()


def load(path: Path) -> List[Dict[str, Any]]:
    with open(path, encoding="utf-8") as fh:
        return [json.loads(line) for line in fh if line.strip()]


def sparql_rows(caps: Any) -> List[Dict[str, Any]]:
    """The captured bindings as plain rows, whichever shape the capture used."""
    if isinstance(caps, list):
        return [r for r in caps if isinstance(r, dict)]
    if not isinstance(caps, dict):
        return []
    res = caps.get("results") or {}
    if isinstance(res, list):
        return [r for r in res if isinstance(r, dict)]
    out = []
    for binding in res.get("bindings") or []:
        out.append(
            {k: (v.get("value") if isinstance(v, dict) else v) for k, v in (binding or {}).items()}
        )
    return out


def evidence_is_complete(caps: Any) -> bool:
    """Does the capture hold everything this answer rested on?"""
    if isinstance(caps, dict):
        names = [str(v).lower() for v in ((caps.get("head") or {}).get("vars") or [])]
    else:
        names = []
    if not names:
        rows = sparql_rows(caps)
        names = [str(k).lower() for k in (rows[0].keys() if rows else [])]
    return bool(names) and not any(n in _STORE_VARS for n in names)


def aggregate(rows: List[Dict[str, Any]], label: str) -> Dict[str, Any]:
    totals: Counter = Counter()
    for row in rows:
        totals.update(row["counts"])
    assessed = totals["bound"] + totals["derived"] + totals["unbound"]
    return {
        "label": label,
        "answers": len(rows),
        "claims": totals["total"],
        "assessed": assessed,
        "bound": totals["bound"],
        "derived": totals["derived"],
        "unbound": totals["unbound"],
        "skipped": totals["skipped"],
        "unbound_numeric": totals["unbound_numeric"],
        "unbound_universal": totals["unbound_universal"],
        "unbound_inference": totals["unbound_inference"],
        "unbound_rate": round(totals["unbound"] / assessed, 4) if assessed else None,
        "answers_with_an_unbound_claim": sum(1 for r in rows if r["counts"]["unbound"]),
    }


# ── the enforcement replay (CAVEAT-769) ──────────────────────────────────────

#: The recorded runs this replays. Each is a jsonl of ``{"q": ..., "answer": ...}`` written by
#: a bank run; a run still being written is read as far as it goes.
RUN_FILES = (
    ("rerun", PHASE0 / "phase0_rerun.md.jsonl", PHASE0 / "phase0_rerun_read.jsonl"),
    ("run3", PHASE0 / "phase0_run3.md.jsonl", PHASE0 / "phase0_run3_read.jsonl"),
    ("run4", PHASE0 / "phase0_run4.md.jsonl", None),
)

#: The counts lanes' real figures and the answers they render, pulled once with read-only
#: SELECTs. Absent = the probe-lane half of the replay is reported as NOT MEASURED rather
#: than silently skipped.
FIXTURE = PHASE0 / "counts_lane_fixture.json"
PROBE_CASES = REPO / "scripts" / "regression_cases.json"
REPLAY_OUT = PHASE0 / "claim_enforcement_replay.json"

#: Hand-read verdicts whose answers a human judged right. Changing one of these is the error
#: this whole exercise exists to make impossible.
GOOD_VERDICTS = ("GOOD_ANSWER", "GOOD_DECLINE")


def load_jsonl(path: Path) -> List[Dict[str, Any]]:
    """Every complete line. A run still being written ends mid-line; that line is dropped."""
    out: List[Dict[str, Any]] = []
    if not path.exists():
        return out
    with open(path, encoding="utf-8") as fh:
        for line in fh:
            line = line.strip()
            if not line:
                continue
            try:
                out.append(json.loads(line))
            except json.JSONDecodeError:
                break
    return out


def _variants(answer: str, results: Dict[str, Any], question: str = "") -> Dict[str, Any]:
    """Enforce the same answer both ways and report what each did."""
    from orchestrator.services.claim_binder import analyse as _analyse

    # The question goes to BOTH variants. It is not part of what changed between them, and
    # giving it only to the one being argued for would flatter it.
    reverted = _analyse(
        answer, results, mode="enforce", question=question, require_complete_evidence=False
    )
    proposed = _analyse(answer, results, mode="enforce", question=question)
    return {
        "a_changed": reverted.answer != answer,
        "a_notes": list(reverted.notes)[:6],
        "b_changed": proposed.answer != answer,
        "b_notes": list(proposed.notes)[:6],
        "b_enforced": proposed.enforced,
        "completeness": (proposed.completeness.as_dict() if proposed.completeness else {}),
        "counts": proposed.counts(),
        "a_answer": reverted.answer,
        "b_answer": proposed.answer,
    }


def _present(text: str, marker: str) -> bool:
    """Is this marker stated in the text, as a token rather than as loose digits?

    A plain substring test would find "8" inside "3,248" and report every figure as surviving
    whatever was deleted, which is the flattering answer and the wrong one.
    """
    m = str(marker).strip()
    if not m:
        return False
    if any(ch.isdigit() for ch in m):
        return re.search(r"(?<![\d,.])" + re.escape(m) + r"(?![\d,.])", text) is not None
    return m.lower() in text.lower()


def _markers_lost(before: str, after: str, markers: List[str]) -> List[str]:
    return [m for m in markers if _present(before, m) and not _present(after, m)]


def _figure_markers(answer: str, figures: Dict[str, Any]) -> List[str]:
    """Every figure the lane COMPUTED that the answer actually states, as written.

    This is the strongest ground truth available offline for these lanes: the number came
    from a COUNT the graph answered, so if enforcement removes it, it has removed a figure
    that was right. Stated both bare and thousands-separated, because the renderer uses both.
    """
    out: List[str] = []
    for value in sorted({float(v) for v in figures.values()}, reverse=True):
        for token in (
            (f"{int(value):,}", str(int(value)))
            if value == int(value)
            else (
                f"{value:,.1f}",
                str(value),
            )
        ):
            if _present(answer, token) and token not in out:
                out.append(token)
                break
    return out


def replay_probe_lane() -> Dict[str, Any]:
    """The probe's own counting questions, rendered from their real figures.

    This is the half of the replay with hard ground truth: the probe asserts a FACT per case
    ("280"), so an enforcement pass that removes it has removed a correct figure, full stop.
    """
    if not FIXTURE.exists():
        return {"measured": False, "why": f"{FIXTURE.name} not present — run the fetch first"}
    fixture = json.loads(FIXTURE.read_text(encoding="utf-8"))
    expect_by_q = {
        norm(c.get("question")): [str(m) for m in (c.get("expect") or [])]
        for c in json.loads(PROBE_CASES.read_text(encoding="utf-8"))
    }
    rows: List[Dict[str, Any]] = []
    for case in fixture.get("cases") or []:
        answer = case.get("answer") or ""
        computed = case.get("figures") or {}
        markers = list(expect_by_q.get(norm(case.get("question")), []))
        for token in _figure_markers(answer, computed):
            if token not in markers:
                markers.append(token)
        figures = {"sources": {case.get("source", "computed"): computed}}
        # A: the lane runs, puts its usual (figure-free) payload on the bus and records
        # nothing it computed -- which is what broke. The payload has to be non-empty or the
        # index reports itself unavailable and every claim is SKIPPED, which would make the
        # reverted variant look harmless for the wrong reason.
        without = {
            case.get("lane")
            or "capability_result": {
                "success": True,
                "provenance": case.get("source") or "",
                "building_name": fixture.get("building_name") or "",
            }
        }
        # B: the same turn with the figures the lane now files.
        with_figs = dict(without)
        with_figs["computed_figures"] = figures
        a = _variants(answer, without, case.get("question") or "")
        b = _variants(answer, with_figs, case.get("question") or "")
        rows.append(
            {
                "question": case.get("question"),
                "source": case.get("source"),
                "expect": markers,
                "a_changed": a["a_changed"],
                "a_markers_lost": _markers_lost(answer, a["a_answer"], markers),
                "b_changed": b["b_changed"],
                "b_enforced": b["b_enforced"],
                "b_completeness": b["completeness"],
                "b_markers_lost": _markers_lost(answer, b["b_answer"], markers),
                "counts_with_figures": b["counts"],
            }
        )
    return {
        "measured": True,
        "cases": rows,
        "a_changed": sum(1 for r in rows if r["a_changed"]),
        "a_correct_figures_removed": sum(1 for r in rows if r["a_markers_lost"]),
        "b_changed": sum(1 for r in rows if r["b_changed"]),
        "b_correct_figures_removed": sum(1 for r in rows if r["b_markers_lost"]),
    }


def replay_runs() -> Dict[str, Any]:
    """The recorded 147-question bank runs, with whatever evidence each turn recorded."""
    evidence = {norm(e["q"]): e for e in load(EVID)} if EVID.exists() else {}
    per_run: Dict[str, Any] = {}
    all_rows: List[Dict[str, Any]] = []
    for label, answers_path, read_path in RUN_FILES:
        answers = load_jsonl(answers_path)
        if not answers:
            per_run[label] = {"answers": 0, "why": f"{answers_path.name} not present"}
            continue
        reads = {r["row"]: r for r in load_jsonl(read_path)} if read_path else {}
        rows: List[Dict[str, Any]] = []
        for i, ans in enumerate(answers):
            answer = ans.get("answer") or ""
            cap = evidence.get(norm(ans.get("q")))
            results: Dict[str, Any] = {}
            bucket = "none"
            if cap:
                srows = sparql_rows(cap.get("sparql_results"))
                results = {"sparql_result": {"success": True, "results": {"data": srows}}}
                bucket = (
                    "complete" if evidence_is_complete(cap.get("sparql_results")) else "partial"
                )
            v = _variants(answer, results, ans.get("q") or "")
            hand = reads.get(i) or {}
            verdict = str(hand.get("verdict") or "")
            rows.append(
                {
                    "run": label,
                    "row": i,
                    "id": hand.get("id") or "",
                    "question": ans.get("q"),
                    "capture": bucket,
                    "hand_verdict": verdict,
                    "a_changed": v["a_changed"],
                    "b_changed": v["b_changed"],
                    "b_enforced": v["b_enforced"],
                    "completeness": v["completeness"].get("status"),
                    "why_withheld": (
                        "" if v["b_enforced"] else v["completeness"].get("reason", "")
                    ),
                    "counts": v["counts"],
                    "a_notes": v["a_notes"],
                    "b_notes": v["b_notes"],
                }
            )
        per_run[label] = {
            "answers": len(rows),
            "a_changed": sum(1 for r in rows if r["a_changed"]),
            "b_changed": sum(1 for r in rows if r["b_changed"]),
            "a_changed_on_a_good_answer": sum(
                1 for r in rows if r["a_changed"] and r["hand_verdict"] in GOOD_VERDICTS
            ),
            "b_changed_on_a_good_answer": sum(
                1 for r in rows if r["b_changed"] and r["hand_verdict"] in GOOD_VERDICTS
            ),
            "b_enforced": sum(1 for r in rows if r["b_enforced"]),
        }
        all_rows.extend(rows)
    withheld: Counter = Counter(r["completeness"] for r in all_rows if not r["b_enforced"])

    def _deleted(row: Dict[str, Any], variant: str) -> bool:
        """Did this variant REMOVE a figure, as opposed to appending a caveat?

        The distinction is the whole point: a removal destroys an answer, a caveat only
        qualifies one. Folding them into one "changed" number hides which kind happened.
        """
        return any(n.startswith("removed") for n in row[f"{variant}_notes"])

    return {
        "per_run": per_run,
        "totals": {
            "answers": len(all_rows),
            "a_changed": sum(1 for r in all_rows if r["a_changed"]),
            "b_changed": sum(1 for r in all_rows if r["b_changed"]),
            "a_changed_on_a_good_answer": sum(
                1 for r in all_rows if r["a_changed"] and r["hand_verdict"] in GOOD_VERDICTS
            ),
            "b_changed_on_a_good_answer": sum(
                1 for r in all_rows if r["b_changed"] and r["hand_verdict"] in GOOD_VERDICTS
            ),
            "b_enforced": sum(1 for r in all_rows if r["b_enforced"]),
            "withheld_by_status": dict(withheld),
            "a_figures_removed": sum(1 for r in all_rows if _deleted(r, "a")),
            "b_figures_removed": sum(1 for r in all_rows if _deleted(r, "b")),
            "a_figures_removed_from_a_good_answer": sum(
                1 for r in all_rows if _deleted(r, "a") and r["hand_verdict"] in GOOD_VERDICTS
            ),
            "b_figures_removed_from_a_good_answer": sum(
                1 for r in all_rows if _deleted(r, "b") and r["hand_verdict"] in GOOD_VERDICTS
            ),
            "b_caveat_only": sum(1 for r in all_rows if r["b_changed"] and not _deleted(r, "b")),
        },
        "changed_rows": [r for r in all_rows if r["b_changed"]][:40],
        "rows": all_rows,
    }


def replay(out_path: Path) -> int:
    probe = replay_probe_lane()
    runs = replay_runs()
    payload = {
        "what_this_answers": (
            "With the counts lanes recording what they compute, and enforcement conditional "
            "on the turn's record being complete: how many recorded answers would "
            "enforcement CHANGE, and how many of those changes would remove a CORRECT "
            "figure? Variant A reproduces the reverted 2026-09-18 behaviour for comparison."
        ),
        "probe_lane": probe,
        "recorded_runs": runs,
    }
    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text(json.dumps(payload, indent=1, ensure_ascii=False), encoding="utf-8")

    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    print("PROBE'S OWN COUNTING QUESTIONS (ground truth = the probe's expect markers)")
    if not probe.get("measured"):
        print(f"  NOT MEASURED: {probe.get('why')}")
    else:
        print(
            f"  A (reverted):  changed={probe['a_changed']}/{len(probe['cases'])}  "
            f"correct figures removed={probe['a_correct_figures_removed']}"
        )
        print(
            f"  B (proposed):  changed={probe['b_changed']}/{len(probe['cases'])}  "
            f"correct figures removed={probe['b_correct_figures_removed']}"
        )
        for c in probe["cases"]:
            print(
                f"    {c['question'][:52]:<52} A:{'CHANGED' if c['a_changed'] else 'kept':<8}"
                f" lost={c['a_markers_lost']}  B:{'CHANGED' if c['b_changed'] else 'kept':<8}"
                f" lost={c['b_markers_lost']} ({c['b_completeness'].get('status')})"
            )
    t = runs["totals"]
    print("\nRECORDED BANK RUNS (ground truth = the hand read)")
    print(
        f"  answers={t['answers']}  A changed={t['a_changed']} "
        f"(on a hand-read GOOD answer: {t['a_changed_on_a_good_answer']})"
    )
    print(
        f"  answers={t['answers']}  B changed={t['b_changed']} "
        f"(on a hand-read GOOD answer: {t['b_changed_on_a_good_answer']})"
    )
    print(
        f"  figures REMOVED (as opposed to caveated): A={t['a_figures_removed']} "
        f"B={t['b_figures_removed']}; from a hand-read GOOD answer: "
        f"A={t['a_figures_removed_from_a_good_answer']} "
        f"B={t['b_figures_removed_from_a_good_answer']}"
    )
    print(f"  B enforced on {t['b_enforced']} turns; withheld: {t['withheld_by_status']}")
    for label, r in runs["per_run"].items():
        if r.get("answers"):
            print(
                f"    {label:<6} answers={r['answers']:>3} A={r['a_changed']:>3} "
                f"B={r['b_changed']:>3} enforced={r['b_enforced']:>3}"
            )
    print(f"\nwritten {out_path}")
    return 0


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--out", default=str(DEFAULT_OUT))
    ap.add_argument(
        "--replay-enforcement",
        action="store_true",
        help="measure what enforcement would change over the recorded runs, and what it "
        "would have removed that was correct",
    )
    ap.add_argument("--replay-out", default=str(REPLAY_OUT))
    args = ap.parse_args()

    if args.replay_enforcement:
        return replay(Path(args.replay_out))

    answers = load(ANSWERS)
    reads = {r["row"]: r for r in load(READ)}
    bank = {norm(b["question"]): b for b in load(BANK)} if BANK.exists() else {}
    evidence = {norm(e["q"]): e for e in load(EVID)} if EVID.exists() else {}

    rows: List[Dict[str, Any]] = []
    # phase0_rerun_read.jsonl numbers its rows from ZERO. Reading it as 1-based shifted every
    # hand-read label onto its neighbour — the measurement apparatus being the bug again, so
    # the alignment is asserted rather than assumed (lessons.md #20-22).
    for i, ans in enumerate(answers):
        hand = reads.get(i) or {}
        if hand and norm(hand.get("question")) != norm(ans["q"]):
            raise SystemExit(f"row {i}: hand-read labels are not aligned with the answers")
        cap = evidence.get(norm(ans["q"]))
        results: Dict[str, Any] = {}
        complete = False
        fetched = 0
        if cap:
            srows = sparql_rows(cap.get("sparql_results"))
            fetched = len(srows)
            complete = evidence_is_complete(cap.get("sparql_results"))
            results = {"sparql_result": {"success": True, "results": {"data": srows}}}
        report = analyse(ans.get("answer") or "", results, mode="record")
        rows.append(
            {
                "row": i,
                "id": hand.get("id") or "",
                "question": ans["q"],
                "category": (bank.get(norm(ans["q"])) or {}).get("category") or "uncategorised",
                "hand_read_class": hand.get("class") or "",
                "hand_read_verdict": hand.get("verdict") or "",
                "evidence": "complete" if complete else ("partial" if cap else "none"),
                "rows_fetched": fetched,
                "counts": report.counts(),
                "unbound_rate": report.unbound_rate(),
                "unbound": [
                    {
                        "kind": c.kind,
                        "raw": c.raw,
                        "subject": c.subject,
                        "why": c.reason,
                        "sentence": c.sentence[:200],
                    }
                    for c in report.claims
                    if c.binding == "unbound"
                ],
                "derived": [
                    {"raw": c.raw, "operation": c.operation, "why": c.reason}
                    for c in report.claims
                    if c.binding == "derived"
                ][:6],
            }
        )

    complete_rows = [r for r in rows if r["evidence"] == "complete"]
    overall = [
        aggregate(complete_rows, "HEADLINE - complete recorded evidence"),
        aggregate(
            [r for r in rows if r["evidence"] == "partial"], "PARTIAL - store read not captured"
        ),
        aggregate([r for r in rows if r["evidence"] == "none"], "NO EVIDENCE RECORDED"),
        aggregate(rows, "ALL"),
    ]
    per_category = {
        cat: aggregate([r for r in complete_rows if r["category"] == cat], cat)
        for cat in sorted({r["category"] for r in complete_rows})
    }
    # The nearest thing to a per-lane split this offline corpus can honestly give: the recorded
    # runs did not store which lane answered, so the question's own class stands in for it.
    per_class = {
        cls: aggregate([r for r in complete_rows if r["hand_read_class"] == cls], cls)
        for cls in sorted({r["hand_read_class"] for r in complete_rows if r["hand_read_class"]})
    }
    c7 = [r for r in rows if r["hand_read_class"] == "C7"]
    payload = {
        "generated_from": {
            "answers": str(ANSWERS.relative_to(REPO)),
            "hand_read": str(READ.relative_to(REPO)),
            "evidence": str(EVID.relative_to(REPO)),
        },
        "caveat": (
            "Recorded captures hold graph evidence only. Turns that went on to read a "
            "time-series store are reported as PARTIAL and excluded from the headline."
        ),
        "overall": overall,
        "per_category_complete_only": per_category,
        "per_hand_read_class_complete_only": per_class,
        "c7_rows": [
            {
                "row": r["row"],
                "id": r["id"],
                "evidence": r["evidence"],
                "counts": r["counts"],
                "unbound": r["unbound"][:6],
            }
            for r in c7
        ],
        "c7_flagged": sum(1 for r in c7 if r["counts"]["unbound"]),
        "c7_total": len(c7),
        "worst": sorted(complete_rows, key=lambda r: (-r["counts"]["unbound"], r["row"]))[:12],
        "rows": rows,
    }
    out = Path(args.out)
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(payload, indent=1, ensure_ascii=False), encoding="utf-8")

    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    for o in overall:
        print(
            f"{o['label']:<40} answers={o['answers']:>3} claims={o['claims']:>5} "
            f"assessed={o['assessed']:>5} bound={o['bound']:>4} derived={o['derived']:>3} "
            f"unbound={o['unbound']:>4} rate={o['unbound_rate']} "
            f"answers_hit={o['answers_with_an_unbound_claim']}"
        )
    print("\nby hand-read class (complete evidence only):")
    for cls, o in sorted(per_class.items(), key=lambda kv: -(kv[1]["unbound_rate"] or 0)):
        print(
            f"  {cls:<6} answers={o['answers']:>3} assessed={o['assessed']:>4} "
            f"unbound={o['unbound']:>3} rate={o['unbound_rate']}"
        )
    print(
        f"\nC7 (hand-read invented-verdict rows) flagged: "
        f"{payload['c7_flagged']}/{payload['c7_total']}"
    )
    print("\nworst offenders (complete evidence only):")
    for r in payload["worst"][:8]:
        print(
            f"  row {r['row']:>3} {r['id']:<8} unbound={r['counts']['unbound']:>2} "
            f"rows_fetched={r['rows_fetched']}"
        )
        for ex in r["unbound"][:2]:
            print(f"      {ex['kind']:<9} {ex['raw'][:66]!r}")
            print(f"        why: {ex['why'][:96]}")
    print(f"\nwritten {out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
