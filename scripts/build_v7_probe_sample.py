# -*- coding: utf-8 -*-
"""Draw a stakeholder-stratified probe set from the 37 catalogues.

Answerability has to be MEASURED on the live building, not predicted from which source
systems a question names — a question can name only sensors the building has and still
fail on routing, on the referent, or on a timeout. This builds the sample that
``corpus_replay.py --strata-source`` then replays.

Stratified by stakeholder role, evenly, because that is the axis the catalogues are
organised on and the axis on which failures differ: a security officer's questions and
an undergraduate's fail for different reasons and are fixed by different work. Drawing
proportionally would bury the 31 smaller roles under nothing, since every role holds
exactly 80 questions anyway.

    python scripts/build_v7_probe_sample.py --per-role 3
    python scripts/corpus_replay.py --strata-source docs/V7_probe_sample.csv
"""

from __future__ import annotations

import argparse
import csv
import random
import sys
from collections import defaultdict
from pathlib import Path
from typing import Dict, List

REPO = Path(__file__).resolve().parents[1]
BANK = REPO / "tasks" / "smart_building_questions.csv"
OUT = REPO / "docs" / "V7_probe_sample.csv"
# The six occupant catalogues were labelled `supervisor_catalogue_2026-08` because they
# arrived from the supervisor before the other 31 were generated. That was a delivery
# batch, not a different corpus: all 37 are the same Talking Abacws catalogues, 80
# questions each. Merged under one source 2026-09-04 (2,960 questions, 37 roles), so
# a filter on the old label now matches NOTHING rather than 480 rows.
CATALOGUE_SOURCES = ("stakeholder_catalogue_37",)


def main(argv: List[str]) -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--per-role", type=int, default=3, help="questions per stakeholder role")
    ap.add_argument("--seed", type=int, default=20260831)
    ap.add_argument("--out", default=str(OUT))
    args = ap.parse_args(argv)

    csv.field_size_limit(10**7)
    with BANK.open(encoding="utf-8-sig") as fh:
        rows = [r for r in csv.DictReader(fh) if r.get("Source") in CATALOGUE_SOURCES]

    by_role: Dict[str, List[Dict[str, str]]] = defaultdict(list)
    for row in rows:
        by_role[row.get("Stakeholder_Role", "").strip() or "unknown"].append(row)

    rng = random.Random(args.seed)
    picked: List[Dict[str, str]] = []
    for role in sorted(by_role):
        pool = sorted(by_role[role], key=lambda r: r["ID"])
        picked.extend(rng.sample(pool, min(args.per_role, len(pool))))

    out = Path(args.out)
    with out.open("w", newline="", encoding="utf-8") as fh:
        writer = csv.writer(fh)
        # corpus_replay reads ID/qid + Question/question + l7_stratum + expected_behavior
        writer.writerow(["ID", "Question", "l7_stratum", "expected_behavior", "Stakeholder_Role"])
        for row in picked:
            writer.writerow(
                [
                    row["ID"],
                    row["Question"],
                    row.get("Stakeholder_Role", ""),
                    # The catalogue's own boundary is the expectation to grade against.
                    (row.get("Answer_Boundary", "") or "")[:400],
                    row.get("Stakeholder_Role", ""),
                ]
            )

    print(f"{len(picked)} questions across {len(by_role)} roles -> {out.relative_to(REPO)}")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
