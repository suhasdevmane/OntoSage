# -*- coding: utf-8 -*-
"""Per-stakeholder scorecard for a V7 replay (V7-T42).

One coverage number hides the thing that matters. Measured before any V7 work: Architects
and Waste-management teams were 100% blocked by systems that do not exist, while
Prospective students were 86% blocked almost entirely at PROSE — the same headline
percentage, and completely different work to fix. A single figure would have ranked the
wrong task first.

Three separations this report insists on:

* **computed vs quoted.** A document quote is a truthful, sourced response and it is not
  a calculation over the building's data. Summing them reported 55.4% coverage where the
  computed rate was 17.8% (BUG-370).
* **graded vs quarantined.** A row captured while the model was degraded or the transport
  failed teaches nothing about behaviour and is excluded, never scored (BUG-176/177).
* **predicted vs measured.** The readiness ceiling is a prediction. Where measurement
  BEATS it the prediction is wrong and worth knowing — that is how the pasted-passage
  defect surfaced.

    python scripts/build_v7_scorecard.py --capture scripts/outputs/replay/v7probe3.csv
"""

from __future__ import annotations

import argparse
import csv
import json
import sys
from collections import Counter, defaultdict
from pathlib import Path
from typing import Dict, List, Optional

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO / "scripts"))

#: Statuses that mean the run learned nothing about the system. Never scored.
QUARANTINE_PREFIXES = ("ERROR", "LLM-DEGRADED")

COMPUTED = {"answered-with-data", "answered-with-proof"}
QUOTED = {"document-quoted"}
HONEST = {"honest-capability-answer", "clarified-appropriately"}


def load(path: Path) -> List[Dict[str, str]]:
    with path.open(encoding="utf-8") as fh:
        return list(csv.DictReader(fh))


def readiness_ceiling(demand: Path, readiness: Optional[Path]) -> Dict[str, str]:
    """qid -> the worst-readiness system it names, when both inputs are available."""
    if not (demand.is_file() and readiness and readiness.is_file()):
        return {}
    ready = {r["source_system"]: r["readiness"] for r in json.loads(readiness.read_text())}
    # WIRED sits BELOW prose deliberately (CAVEAT-412): a document you can quote answers more
    # questions than a feed that is switched on and has produced nothing. The default for an
    # unknown state stays the worst rank, so a state added upstream degrades the ceiling
    # rather than silently flattering it.
    rank = {"DATA": 0, "PROSE": 1, "WIRED": 2, "ABSENT": 3}
    out: Dict[str, str] = {}
    with demand.open(encoding="utf-8") as fh:
        for row in csv.DictReader(fh):
            systems = [s for s in (row.get("source_systems") or "").split("|") if s]
            if not systems:
                out[row["ID"]] = "NONE"
                continue
            worst = max(systems, key=lambda s: rank.get(ready.get(s, "ABSENT"), max(rank.values())))
            out[row["ID"]] = ready.get(worst, "ABSENT")
    return out


def main(argv: List[str]) -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--capture", required=True)
    ap.add_argument("--demand", default=str(REPO / "docs" / "V7_question_demand.csv"))
    ap.add_argument("--readiness", default="")
    ap.add_argument("--out", default=str(REPO / "docs" / "V7_SCORECARD.md"))
    args = ap.parse_args(argv)

    rows = load(Path(args.capture))
    quarantined = [r for r in rows if str(r.get("status", "")).startswith(QUARANTINE_PREFIXES)]
    graded = [r for r in rows if r not in quarantined]
    if not graded:
        print("no gradeable rows — nothing to score")
        return 2

    ceiling = readiness_ceiling(Path(args.demand), Path(args.readiness) if args.readiness else None)

    def share(subset: List[Dict[str, str]], grades: set) -> float:
        return 100 * sum(1 for r in subset if r.get("grade") in grades) / len(subset)

    lines = [
        "# V7 scorecard — per stakeholder",
        "",
        f"**Capture:** `{Path(args.capture).name}` · "
        f"**graded {len(graded)}**, quarantined {len(quarantined)}",
        "",
        "> Quarantined rows are excluded, never scored: a row captured while the model was",
        "> degraded or the transport failed teaches nothing about behaviour. Two incidents",
        "> in this project published numbers from such rows before the harness learned to",
        "> hold them back.",
        "",
        "## Overall",
        "",
        "| outcome | n | share |",
        "|---|---:|---:|",
    ]
    counts = Counter(r.get("grade", "") for r in graded)
    for label, grades in (
        ("**Computed answer**", COMPUTED),
        ("Document quote", QUOTED),
        ("Honest decline", HONEST),
        ("Deflected", {"deflected"}),
        ("Wrong", {"wrong", "fabricated"}),
        ("No response", {"invalid-no-response"}),
    ):
        n = sum(counts.get(g, 0) for g in grades)
        lines.append(f"| {label} | {n} | {100 * n / len(graded):.1f}% |")
    lines += [
        "",
        "> **Coverage is the computed row alone.** A quote is truthful and sourced, and it",
        "> computed nothing; adding the two together once turned 17.8% into a reported",
        "> 55.4% (BUG-370).",
        "",
        "## Per stakeholder role",
        "",
        "| role | n | computed | quoted | honest | fail |",
        "|---|---:|---:|---:|---:|---:|",
    ]
    by_role: Dict[str, List[Dict[str, str]]] = defaultdict(list)
    for row in graded:
        by_role[row.get("stakeholder_role") or row.get("l7_stratum") or "unknown"].append(row)
    for role, subset in sorted(by_role.items(), key=lambda kv: -share(kv[1], COMPUTED)):
        fail = 100 - share(subset, COMPUTED | QUOTED | HONEST)
        lines.append(
            f"| {role[:52]} | {len(subset)} | **{share(subset, COMPUTED):.0f}%** | "
            f"{share(subset, QUOTED):.0f}% | {share(subset, HONEST):.0f}% | {fail:.0f}% |"
        )

    if ceiling:
        lines += [
            "",
            "## Predicted ceiling against measured outcome",
            "",
            "| predicted ceiling | n | computed |",
            "|---|---:|---:|",
        ]
        by_ceiling: Dict[str, List[Dict[str, str]]] = defaultdict(list)
        for row in graded:
            by_ceiling[ceiling.get(row.get("qid", ""), "?")].append(row)
        for state in ("DATA", "PROSE", "WIRED", "ABSENT", "NONE", "?"):
            subset = by_ceiling.get(state)
            if subset:
                lines.append(f"| {state} | {len(subset)} | {share(subset, COMPUTED):.0f}% |")
        lines += [
            "",
            "> A ceiling should behave like one: DATA highest, ABSENT lowest. Where measured",
            "> BEATS predicted, the prediction is wrong and worth investigating — that is how",
            "> the pasted-passage defect was found, when ABSENT-capped questions appeared to",
            "> answer as often as DATA ones.",
        ]

    out = Path(args.out)
    out.write_text("\n".join(lines) + "\n", encoding="utf-8")
    print("\n".join(lines[:22]))
    try:
        shown = out.relative_to(REPO)
    except ValueError:
        shown = out  # a scratch path outside the repo is a legitimate place to write one
    print(f"\nwrote {shown}")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
