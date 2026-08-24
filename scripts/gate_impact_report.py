#!/usr/bin/env python3
"""What would each evidence gate change if it were switched to enforcing? (V6-T55)

Every gate runs advisory first: it records the verdict it WOULD reach and changes nothing.
That is only useful if somebody reads the record, and this is the thing that makes it
readable — one row per question a gate would have acted on, with the reason it gives.

**This report is a decision aid, not a decision.** Switching a gate to enforcing changes what
the building tells people, so it is the operator's call, made against this list. The script
therefore prints impact and never edits `evidence_policy.yaml`.

Why it reads a capture rather than probing live: enforcement is a question about the whole
question bank, not about the handful of examples anyone would think to try. The capture
already asked 316 of them and recorded each answer's evidence record, so the impact is a
read over data that exists — no LLM calls, no cost, and reproducible.

    python scripts/gate_impact_report.py --capture scripts/outputs/baseline/<stamp>.csv

Caveat worth stating up front: a gate's advisory verdicts are only as good as the inputs it
was given. Three of the four gates currently judge fields nothing populates and are recorded
as not-evaluated rather than run (BUG-237), so this report describes freshness and the two
document suppressors, and says so rather than implying the others passed.
"""

from __future__ import annotations

import argparse
import csv
import sys
from collections import Counter, defaultdict
from pathlib import Path
from typing import Dict, List

csv.field_size_limit(10**8)
REPO = Path(__file__).resolve().parent.parent

#: What switching each gate to enforcing would DO to an answer. Used only for the advisory
#: section: for gates already in force the question does not arise, they have done it.
_SUPPRESSORS = {
    "retrieval_floor": "the document answer disappears; the question gets an honest 'no relevant passage'",
    "grounding_guard": "the retrieved passage is withheld as off-topic; same honest decline",
    "freshness": "the answer stops being presented as current status and is downgraded",
    "completeness": "the aggregate is refused with the gap named",
    "spatial_adequacy": "a room-level claim drops to proxy-labelled context",
    "calibration": "a standards verdict is withheld; the raw reading still stands",
    "permission": (
        "an entitlement claim (availability / access / privacy / permission) is replaced by "
        "the route to the system of record that can actually answer it"
    ),
    "source_precedence": (
        "the authoritative value leads and the lower-tier disagreement is reported rather "
        "than resolved"
    ),
    "conflict": "disagreeing sensors are both reported; no average is offered",
    "trend_integrity": "a trend spanning a configuration change is segmented or refused",
}


def _rows(path: Path) -> List[Dict[str, str]]:
    return [
        r
        for r in csv.DictReader(path.open(encoding="utf-8-sig", newline=""))
        if r.get("status") == "OK"
    ]


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--capture", required=True, help="a capture CSV with the gates column")
    ap.add_argument("--md", default="", help="write the report here")
    args = ap.parse_args(argv)

    path = Path(args.capture)
    if not path.is_absolute():
        path = REPO / path
    rows = _rows(path)
    if not rows:
        print(f"no OK rows in {path}")
        return 2

    # The column was empty on every row of every capture taken before BUG-238 was fixed, and an
    # empty column reads exactly like "no gate would change anything" — the most reassuring
    # possible output and completely false. Refuse rather than reassure.
    if not any(r.get("gates") for r in rows) and not any(r.get("answer_status") for r in rows):
        print(
            f"REFUSING: {path.name} records no gates and no answer_status on any of its "
            f"{len(rows)} OK rows.\nThat is the signature of a capture taken before BUG-238 was "
            "fixed, when the harness read the evidence DOSSIER instead of the evidence RECORD. "
            "Reporting from it would say 'no gate would change anything', which is the most "
            "reassuring output available and entirely an artefact. Re-capture first."
        )
        return 2

    # TWO DIFFERENT QUESTIONS, and conflating them was this script's own first bug. A gate in
    # `gates_applied` has ALREADY suppressed something and the captured answer reflects it --
    # there is no enforcement decision left to take. A gate in `gates_advisory` failed and
    # changed nothing, and is the only kind that answers "what would enforcing cost?".
    applied_by_gate: Dict[str, List[Dict[str, str]]] = defaultdict(list)
    advisory_by_gate: Dict[str, List[Dict[str, str]]] = defaultdict(list)
    for r in rows:
        for g in (r.get("gates") or "").split(","):
            g = g.strip()
            if g:
                applied_by_gate[g].append(r)
        for entry in (r.get("gates_advisory") or "").split(" | "):
            entry = entry.strip()
            if entry:
                advisory_by_gate[entry.split(":", 1)[0].strip()].append(r)

    out: List[str] = []

    def w(line: str = "") -> None:
        out.append(line)

    w("# Gate impact report")
    w()
    w(f"**Capture:** `{path.name}`  ")
    w(f"**Questions considered:** {len(rows)} answered rows  ")
    w()
    w(
        "Two sections, and the distinction is the point. **Would change if enforced** lists "
        "advisory verdicts — recorded, changed nothing, and the only thing an enforcement "
        "decision can be made from. **Already in force** lists suppressions that have acted; "
        "the captured answers reflect them and there is nothing left to decide. Reading the "
        "second as the first would present costs already paid as costs still to come."
    )
    w()
    w("Switching a gate to enforcing is an operator decision; this script never edits policy.")
    w()

    w("## Would change if enforced")
    w()
    if not advisory_by_gate:
        w(
            "No gate recorded an advisory failure in this capture. Either nothing would change, "
            "or the gates that would are among the three still awaiting inputs (see the note at "
            "the end) — the two are not distinguishable from here."
        )
    else:
        w("**This is the enforcement decision.** Each answer below is unchanged today.")
        w()
        w("| Gate | Answers it would change | Share | What enforcing would do |")
        w("|---|---:|---:|---|")
        for g, rs in sorted(advisory_by_gate.items(), key=lambda kv: -len(kv[1])):
            w(
                f"| `{g}` | {len(rs)} | {len(rs)/len(rows):.1%} | "
                f"{_SUPPRESSORS.get(g, 'unclassified — check the gate definition')} |"
            )
        w()
        for g, rs in sorted(advisory_by_gate.items(), key=lambda kv: -len(kv[1])):
            w(f"### `{g}` would change {len(rs)} answer(s)")
            w()
            lanes = Counter(r.get("intent") or "?" for r in rs)
            w(f"Lanes: {', '.join(f'{k} {v}' for k, v in lanes.most_common())}")
            w()
            for r in rs:
                reason = ""
                for entry in (r.get("gates_advisory") or "").split(" | "):
                    if entry.strip().startswith(g):
                        reason = entry.split(":", 1)[-1].strip()
                        break
                w(f"- **{r['qid']}** — {r['question'][:130]}")
                if reason:
                    w(f"  - {reason}")
            w()

    w("## Already in force")
    w()
    if not applied_by_gate:
        w("No suppression was recorded on any answer in this capture.")
    else:
        w(
            "These have ALREADY acted — the captured answers reflect them, and there is no "
            "enforcement decision left to take. Listed for review: is each one suppressing the "
            "right things?"
        )
        w()
        w("| Gate | Answers suppressed | Share |")
        w("|---|---:|---:|")
        for g, rs in sorted(applied_by_gate.items(), key=lambda kv: -len(kv[1])):
            w(f"| `{g}` | {len(rs)} | {len(rs)/len(rows):.1%} |")
        w()
        for g, rs in sorted(applied_by_gate.items(), key=lambda kv: -len(kv[1])):
            w(f"### `{g}` suppressed {len(rs)} answer(s)")
            w()
            lanes = Counter(r.get("intent") or "?" for r in rs)
            w(f"Lanes: {', '.join(f'{k} {v}' for k, v in lanes.most_common())}")
            w()
            for r in rs:
                w(f"- **{r['qid']}** — {r['question'][:150]}")
            w()

    # An answer already carrying a non-observed status is one the pipeline itself downgraded,
    # which is worth separating from gate impact so the two are not read as the same thing.
    statuses = Counter(r.get("answer_status") or "(none)" for r in rows)
    w("## Answer status across the capture")
    w()
    w("| Status | Count |")
    w("|---|---:|")
    for s, n in statuses.most_common():
        w(f"| {s} | {n} |")
    w()
    w(
        "Three of the four evidence gates judge inputs nothing populates yet and are recorded "
        "as *not evaluated* rather than run (BUG-237), so their absence here is a gap in the "
        "measurement, not evidence that they would change nothing."
    )

    text = "\n".join(out)
    print(text)
    if args.md:
        dest = Path(args.md)
        if not dest.is_absolute():
            dest = REPO / dest
        dest.write_text(text, encoding="utf-8")
        print(f"\nwrote {dest}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
