#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Turn a golden-baseline capture into a readable progress report (V6-T54 companion).

GENERATED, not hand-written, so it can be regenerated whenever the capture changes and can
never drift from the data it describes.

WHAT THIS REPORT IS, AND IS NOT
It is a **capture** of how the system answers today, taken before any V6 change lands. It is
NOT a graded evaluation: no answer here has been judged correct or incorrect. That
distinction is load-bearing. Reporting "the system answered 1,529 of 1,580 questions" as
though it were an accuracy figure would be exactly the kind of number this project has
already published three times by accident and had to retract (CAVEAT-173, BUG-176, BUG-177).

So the report states what can be counted honestly -- how many questions produced an answer,
how those answers were routed, what SHAPE they took, and where the known defects are -- and
labels everything else as not yet measured.

    python scripts/build_baseline_report.py
    python scripts/build_baseline_report.py --capture scripts/outputs/baseline/baseline_X.csv
"""

from __future__ import annotations

import argparse
import csv
import json
import re
import sys
from collections import Counter
from datetime import datetime
from pathlib import Path
from typing import List, Optional

REPO = Path(__file__).resolve().parent.parent
BASELINE_DIR = REPO / "scripts" / "outputs" / "baseline"

#: An answer that declines. Detected by SHAPE rather than by grading -- these are the
#: system's own standard refusal phrasings, so the match is exact rather than a judgement.
_DECLINE = re.compile(
    r"don't have that specific information|no information on record|not on record"
    r"|I don't have|cannot answer|not assessable|I can.t report|won.t substitute",
    re.IGNORECASE,
)
#: An answer built from a retrieved document.
_DOC = re.compile(r"found in \*\*.+?\*\* documentation", re.IGNORECASE)


def _latest_capture() -> Optional[Path]:
    files = sorted(BASELINE_DIR.glob("baseline_*.csv"), key=lambda p: p.stat().st_mtime)
    return files[-1] if files else None


def _pct(n: int, d: int) -> str:
    return f"{n / d * 100:.1f}%" if d else "—"


def build(capture: Path) -> str:
    rows = list(csv.DictReader(capture.read_text(encoding="utf-8-sig").splitlines()))
    meta_path = capture.with_suffix("").with_suffix(".meta.json")
    meta = json.loads(meta_path.read_text(encoding="utf-8")) if meta_path.exists() else {}

    ok = [r for r in rows if r["status"] == "OK"]
    bad = [r for r in rows if r["status"] != "OK"]
    cat = [r for r in ok if r["source"].startswith("supervisor")]
    v5 = [r for r in ok if not r["source"].startswith("supervisor")]

    declines = [r for r in ok if _DECLINE.search(r["answer"])]
    docs = [r for r in ok if _DOC.search(r["answer"])]
    substantive = [r for r in ok if not _DECLINE.search(r["answer"])]

    L: List[str] = []
    A = L.append
    A("# OntoSage — Baseline Capture Report")
    A("")
    A(f"**Capture:** `{capture.name}`  ")
    A(f"**Taken:** {meta.get('captured_at', 'unknown')}  ")
    A("**Building:** bldg1 (Abacws) · **Model:** local `gpt-oss:20b`  ")
    A(
        f"**Generated:** {datetime.now().strftime('%Y-%m-%d %H:%M')} by `scripts/build_baseline_report.py`"
    )
    A("")
    A("---")
    A("")

    # ── what this is ────────────────────────────────────────────────────────
    A("## 1. What this is — and what it is not")
    A("")
    A("This is a **capture of how the system answers today**, taken deliberately *before* any")
    A("V6 change landed. Its purpose is to make later change measurable: every V6 task is")
    A("checked against it so an intended tightening can be told apart from a regression.")
    A("")
    A("**It is not a graded evaluation.** No answer here has been judged correct or incorrect.")
    A("The counts below describe what the system *did*, not how well it did it. Reading them as")
    A("accuracy would repeat a mistake this project has already made and retracted three times.")
    A("")

    # ── coverage of the run ─────────────────────────────────────────────────
    A("## 2. The run")
    A("")
    A("| | Count | Share |")
    A("|---|---:|---:|")
    A(f"| Questions asked | {len(rows)} | 100% |")
    A(f"| Produced an answer | {len(ok)} | {_pct(len(ok), len(rows))} |")
    A(f"| Quarantined (not scored) | {len(bad)} | {_pct(len(bad), len(rows))} |")
    A("")
    if bad:
        reasons = Counter(r["status"].split(":")[0] for r in bad)
        A("Quarantined rows are recorded **with their reason** and excluded from every")
        A("comparison, because a baseline that treated an outage as an answer would mark every")
        A("later healthy answer as a change:")
        A("")
        for reason, n in reasons.most_common():
            A(f"- **{reason}** — {n}")
        A("")

    # ── the two corpora ─────────────────────────────────────────────────────
    A("## 3. The two question sets")
    A("")
    A("| Source | Answered | Purpose |")
    A("|---|---:|---|")
    A(
        f"| Supervisor stakeholder catalogues | {len(cat)} | The 480 questions from the six 2026-08 catalogues |"
    )
    A(
        f"| Existing synthetic bank | {len(v5)} | The 1,100-question corpus built for the previous phase |"
    )
    A("")
    if cat:
        A("### Supervisor questions by readiness tier")
        A("")
        A("Tiers are the supervisors' own classification, not ours.")
        A("")
        tiers = Counter(r["readiness_r"] for r in cat)
        labels = {
            "R1": "Answerable with core sensing",
            "R2": "Needs an integration (timetable, booking, BMS, access…)",
            "R3": "Needs governance or research-grade validation",
        }
        A("| Tier | Meaning | Asked |")
        A("|---|---|---:|")
        for t in ("R1", "R2", "R3"):
            A(f"| **{t}** | {labels[t]} | {tiers.get(t, 0)} |")
        A("")
        roles = Counter(r["stakeholder_role"] for r in cat if r["stakeholder_role"])
        if roles:
            A("### By stakeholder")
            A("")
            A("| Stakeholder | Questions |")
            A("|---|---:|")
            for role, n in sorted(roles.items()):
                A(f"| {role} | {n} |")
            A("")

    # ── what the answers looked like ────────────────────────────────────────
    A("## 4. What the answers looked like")
    A("")
    A("Classified by **shape**, using the system's own standard phrasings — not by judging")
    A("whether any answer was right.")
    A("")
    A("| Shape | Count | Share of answered |")
    A("|---|---:|---:|")
    A(f"| Substantive answer | {len(substantive)} | {_pct(len(substantive), len(ok))} |")
    A(
        f'| Explicit decline ("I don\'t have that on record") | {len(declines)} | {_pct(len(declines), len(ok))} |'
    )
    A(f"| …of which drew on an uploaded document | {len(docs)} | {_pct(len(docs), len(ok))} |")
    A("")
    A("### Which lane answered")
    A("")
    A("| Lane | Count | Share |")
    A("|---|---:|---:|")
    for lane, n in Counter(r["intent"] or "(unrouted)" for r in ok).most_common(10):
        A(f"| {lane} | {n} | {_pct(n, len(ok))} |")
    A("")

    # ── honest findings ─────────────────────────────────────────────────────
    A("## 5. What the capture revealed")
    A("")
    A("Reading the individual rows — rather than only the totals — surfaced a defect that no")
    A("test had caught.")
    A("")
    A("**BUG-218 (P1, open).** A question can be answered with an unrelated document when the")
    A('two share a single common word. *"Which carpets are due deep cleaning this month?"* was')
    A("answered with the building's HVAC CO₂ threshold table, because that document contains")
    A('the phrase *"Heat recovery wheel: inspected quarterly, cleaned annually"* — the word')
    A("*cleaned* was enough. The salient term, *carpet*, appears nowhere in it.")
    A("")
    A("The content returned is real, so no anti-fabrication guard fires; but an unrelated")
    A('document presented under *"Here is what I found in the documentation"* reads as an')
    A(
        f"answer. **{len(docs)} of {len(ok)} answers ({_pct(len(docs), len(ok))}) draw on a document**, so the"
    )
    A("exposed surface is material. The share that is genuinely off-topic is **not yet")
    A("measured** — the fix and its measurement are scheduled together.")
    A("")
    A("This is the intended use of a baseline: it makes existing behaviour legible enough to")
    A("audit, before anything changes on top of it.")
    A("")

    # ── limitations ─────────────────────────────────────────────────────────
    A("## 6. Limitations of this report")
    A("")
    A('- **Nothing here is graded.** "Substantive" means an answer was produced, not that it')
    A("  was correct. Correctness grading is a separate, later step.")
    A("- **One building, one model.** bldg1 on local `gpt-oss:20b`. Portability across the")
    A("  other two buildings, and across hosted models, is measured later in the plan.")
    A(f"- **{len(bad)} questions produced no usable answer** and are excluded rather than counted")
    A("  as failures; most were provider timeouts or empty completions, not refusals.")
    A("- **Shape classification is heuristic.** Declines are matched on the system's own")
    A("  standard phrasings; an unusual refusal wording would be counted as substantive.")
    A("")
    A("---")
    A("")
    A(
        f"Full per-question data, including every answer in full: `{capture.relative_to(REPO).as_posix()}`"
    )
    return "\n".join(L) + "\n"


def main(argv: List[str]) -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--capture", default="", help="baseline CSV (default: newest)")
    ap.add_argument("--out", default="", help="output path (default: alongside the capture)")
    args = ap.parse_args(argv)

    capture = Path(args.capture) if args.capture else _latest_capture()
    if not capture or not capture.is_file():
        print("no baseline capture found")
        return 1

    text = build(capture)
    out = Path(args.out) if args.out else capture.with_name(capture.stem + "_REPORT.md")
    out.write_text(text, encoding="utf-8")
    print(f"wrote {out.relative_to(REPO).as_posix()}  ({len(text.splitlines())} lines)")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
