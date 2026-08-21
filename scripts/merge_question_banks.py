#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Extend the V5 synthetic question bank with the supervisors' 480 catalogue questions.

Two corpora, one file, and deliberately NOT one taxonomy. The V5 bank classifies its
1,100 questions into 24 categories and three registers; the supervisors' catalogues
classify their 480 into 8 sections per stakeholder role, with their own priority tag, an
operation-complexity ladder (L1-L4) and a readiness tier (R1-R3). Those are different
axes measuring different things.

Forcing the catalogue questions into the 24 V5 categories was rejected: it would invent a
classification the supervisors did not make, and any per-category number computed
afterwards would be reporting that invention back as a finding. Instead every row carries
`Source`, the union of both schemas is kept, and each corpus is reported on its own axis —
V5 rows by Category, catalogue rows by Readiness_R. A blank cell here means "this corpus
does not classify on that axis", not "unknown".

Usage:
    python scripts/merge_question_banks.py
"""

from __future__ import annotations

import csv
import shutil
import sys
from pathlib import Path
from typing import Dict, List

REPO = Path(__file__).resolve().parent.parent
V5_BANK = REPO / "tasks" / "smart_building_questions.csv"
CATALOGUE = REPO / "tasks" / "v6" / "catalogue_questions.csv"
BACKUP = REPO / "tasks" / "v6" / "smart_building_questions_v5_original.csv"

SRC_V5 = "v5_synthetic_bank"
SRC_CAT = "supervisor_catalogue_2026-08"

#: V5 columns first (so existing tooling that reads by name keeps working), then the
#: catalogue's own fields.
NEW_COLS = [
    "Source",
    "Section",
    "Priority",
    "Complexity_L",
    "Readiness_R",
    "Readiness_Label",
    "Sensors_Required",
    "Authoritative_Sources",
    "Analysis_Required",
    "Answer_Boundary",
    "Source_Doc",
]


def main() -> int:
    if not V5_BANK.is_file():
        print(f"missing {V5_BANK}")
        return 1
    if not CATALOGUE.is_file():
        print(f"missing {CATALOGUE} - run scripts/extract_catalogue_questions.py first")
        return 1

    v5 = list(csv.DictReader(V5_BANK.read_text(encoding="utf-8-sig").splitlines()))
    cat = list(csv.DictReader(CATALOGUE.read_text(encoding="utf-8-sig").splitlines()))
    v5_cols = list(v5[0].keys())
    cols = v5_cols + [c for c in NEW_COLS if c not in v5_cols]

    if not BACKUP.exists():
        BACKUP.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(V5_BANK, BACKUP)
        print(f"  backed up the original V5 bank -> {BACKUP.relative_to(REPO)}")

    out: List[Dict[str, str]] = []
    for r in v5:
        row = {c: r.get(c, "") for c in cols}
        row["Source"] = SRC_V5
        out.append(row)

    seen = {r["ID"] for r in out}
    clashes = []
    for r in cat:
        if r["ID"] in seen:
            clashes.append(r["ID"])
            continue
        row = {c: "" for c in cols}
        row.update(
            {
                "ID": r["ID"],
                "Question": r["Question"],
                # Category/Register/Surface_*/Latent_*/Required_Data_Sources stay blank:
                # the catalogue does not classify on the V5 axes. See module docstring.
                "Stakeholder_Role": r["Stakeholder_Role"],
                "Answer_Type": r["Operation"],
                "Notes": f"{r['Priority']} - {r['Source_Doc']}".strip(" -"),
                "Source": SRC_CAT,
                "Section": r["Section"],
                "Priority": r["Priority"],
                "Complexity_L": r["Complexity_L"],
                "Readiness_R": r["Readiness_R"],
                "Readiness_Label": r["Readiness_Label"],
                "Sensors_Required": r["sensors_required"],
                "Authoritative_Sources": r["authoritative_sources"],
                "Analysis_Required": r["analysis_required"],
                "Answer_Boundary": r["answer_boundary"],
                "Source_Doc": r["Source_Doc"],
            }
        )
        out.append(row)
        seen.add(r["ID"])

    with V5_BANK.open("w", encoding="utf-8-sig", newline="") as fh:
        w = csv.DictWriter(fh, fieldnames=cols)
        w.writeheader()
        w.writerows(out)

    from collections import Counter

    src = Counter(r["Source"] for r in out)
    print(f"  wrote {len(out)} questions -> {V5_BANK.relative_to(REPO)}")
    print(f"    {SRC_V5}: {src[SRC_V5]}")
    print(f"    {SRC_CAT}: {src[SRC_CAT]}")
    if clashes:
        print(f"    SKIPPED {len(clashes)} id clashes: {clashes[:5]}")
    tiers = Counter(r["Readiness_R"] for r in out if r["Source"] == SRC_CAT)
    print(f"    catalogue readiness: {dict(sorted(tiers.items()))}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
