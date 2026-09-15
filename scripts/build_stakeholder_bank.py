#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Draw a reproducible stakeholder question bank for demo readiness (RUN-04).

Two sources, both already in this repository, and nothing invented:

* ``docs/smart_building_questions.csv`` — 4,060 questions: 37 stakeholder catalogues of 80
  each (with a written ANSWER BOUNDARY — what the service must refuse), plus a 1,100-question
  bank spread over 20 answer categories.
* the survey master table (``paper/Survey analysis and results/.../complexity_master_table.csv``)
  — 5,604 questions from 96 participants, classified by reasoning level.

WHY A DRAWN SAMPLE AND NOT A HAND-PICKED ONE
--------------------------------------------
A demo script chosen by the person who built the system measures what that person expects
to work. Drawing by stakeholder and category — deterministically, so a re-run draws the same
questions — is what makes "every stakeholder" a claim that can be checked. The selection
prefers rows marked Core/CORE where a catalogue marks priority, and otherwise orders by a
stable hash of the question ID, never by file order.

The bank records each catalogue's answer boundary next to its question, because for a
question like "can you open the plant room for me?" the CORRECT answer is a refusal, and
a triage that scored it as a failure would teach the system to overstep.

    python scripts/build_stakeholder_bank.py                  # 1 per role + 1 per category
    python scripts/build_stakeholder_bank.py --per-role 2 --survey-per-level 2
"""

from __future__ import annotations

import argparse
import csv
import hashlib
import json
from collections import defaultdict
from pathlib import Path
from typing import Dict, List

REPO = Path(__file__).resolve().parent.parent
CATALOGUE = REPO / "docs" / "smart_building_questions.csv"
SURVEY = (
    REPO / "paper" / "Survey analysis and results" / "outputs" / "master table analysis"
    / "complexity_master_table.csv"
)

_PRIORITY_RANK = {"critical": 0, "core": 1, "high": 2, "situational": 3, "useful": 4}


def _stable(key: str) -> str:
    return hashlib.sha256(key.encode("utf-8")).hexdigest()


def _rank(row: Dict[str, str]) -> tuple:
    pr = _PRIORITY_RANK.get((row.get("Priority") or "").strip().lower(), 9)
    return (pr, _stable(row.get("ID") or row.get("Question") or ""))


def _read(path: Path) -> List[Dict[str, str]]:
    with path.open(encoding="utf-8-sig", newline="") as fh:
        return list(csv.DictReader(fh))


def build(per_role: int, per_category: int, survey_per_level: int) -> List[Dict[str, str]]:
    rows = _read(CATALOGUE)
    bank: List[Dict[str, str]] = []
    seen = set()

    def add(q: str, **meta):
        key = " ".join(q.lower().split())
        if not q.strip() or key in seen:
            return
        seen.add(key)
        bank.append({"question": q.strip(), **meta})

    # 1. every stakeholder catalogue (the rows carrying a source document)
    by_role: Dict[str, List[Dict[str, str]]] = defaultdict(list)
    for r in rows:
        if (r.get("Source_Doc") or "").strip() and (r.get("Stakeholder_Role") or "").strip():
            by_role[r["Stakeholder_Role"].strip()].append(r)
    for role in sorted(by_role):
        for r in sorted(by_role[role], key=_rank)[:per_role]:
            add(r["Question"], source=r.get("Source", ""), id=r.get("ID", ""), stakeholder=role,
                category=r.get("Category", ""), boundary=(r.get("Answer_Boundary") or "")[:300])

    # 2. every answer category of the synthetic bank
    by_cat: Dict[str, List[Dict[str, str]]] = defaultdict(list)
    for r in rows:
        if (r.get("Category") or "").strip():
            by_cat[r["Category"].strip()].append(r)
    for cat in sorted(by_cat):
        for r in sorted(by_cat[cat], key=_rank)[:per_category]:
            add(r["Question"], source=r.get("Source", ""), id=r.get("ID", ""),
                stakeholder=r.get("Stakeholder_Role", ""), category=cat,
                register=r.get("Register", ""), boundary="")

    # 3. the survey, one draw per reasoning level (answerable ones first)
    if survey_per_level and SURVEY.is_file():
        by_level: Dict[str, List[Dict[str, str]]] = defaultdict(list)
        for r in _read(SURVEY):
            by_level[r.get("level_name", "")].append(r)
        for level in sorted(by_level):
            pool = sorted(
                by_level[level],
                key=lambda r: (r.get("answerability") != "full", _stable(r.get("qid", ""))),
            )
            for r in pool[:survey_per_level]:
                add(r["question"], source="survey", id=r.get("qid", ""),
                    stakeholder=r.get("roles", ""), category=level,
                    answerability=r.get("answerability", ""), boundary="")
    return bank


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--per-role", type=int, default=1)
    ap.add_argument("--per-category", type=int, default=1)
    ap.add_argument("--survey-per-level", type=int, default=1)
    ap.add_argument("--jsonl", default=str(REPO / "docs" / "demo_question_bank.jsonl"))
    ap.add_argument("--md", default=str(REPO / "docs" / "DEMO_QUESTION_BANK.md"))
    args = ap.parse_args()

    bank = build(args.per_role, args.per_category, args.survey_per_level)
    Path(args.jsonl).write_text(
        "\n".join(json.dumps(b, ensure_ascii=False) for b in bank) + "\n", encoding="utf-8"
    )
    lines = [
        "# Demo question bank",
        "",
        f"{len(bank)} questions, drawn deterministically by `scripts/build_stakeholder_bank.py` "
        "from `docs/smart_building_questions.csv` (every stakeholder catalogue and every answer "
        "category) and the survey master table (every reasoning level). These are EXAMPLES of what "
        "each stakeholder asks — the system is expected to answer questions beyond them.",
        "",
        "Where a catalogue states an answer boundary, a refusal inside that boundary is the CORRECT "
        "answer.",
        "",
        "| # | source | stakeholder | category | question |",
        "|---|---|---|---|---|",
    ]
    for i, b in enumerate(bank, 1):
        lines.append(
            f"| {i} | {b['source']} | {b.get('stakeholder','')[:40]} | {b.get('category','')[:32]} | "
            f"{b['question'].replace('|', '/')} |"
        )
    Path(args.md).write_text("\n".join(lines) + "\n", encoding="utf-8")
    print(f"{len(bank)} questions -> {args.jsonl}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
