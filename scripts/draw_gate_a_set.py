#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Draw the SEALED Gate A evaluation set (V12-29). Prints counts and a hash — never questions.

WHY IT PRINTS NOTHING
---------------------
V12-29's acceptance: the set "is NOT consulted while fixing anything". A question that has been
read while changing the system stops being held out, because whoever reads it will fix towards
it. So this script writes the set and reports only how many questions came from where and the
SHA-256 of the file. The set is opened once — by the run, on the frozen build.

THE DRAW (deterministic; re-running writes a byte-identical file)
-----------------------------------------------------------------
Sources, both already in the repository:
  * docs/smart_building_questions.csv — stakeholder catalogues (rows with a Source_Doc) and the
    category bank;
  * the survey complexity master table — reasoning levels L1..L6.

Excluded before drawing, so nothing sealed has ever been used to develop or rehearse:
  * every question in docs/demo_question_bank.jsonl, docs/demo_script_questions.txt,
    scripts/regression_cases.json, and every quoted string in tests/*.py;
  * every question asked in scripts/outputs/*.jsonl (stakeholder runs, re-asks, rehearsals).

Per stakeholder role: 2 questions. Per catalogue category: 1. Per survey level: 3 (answerable
first). Ordered by sha256(SALT + id) — a salt fixed here, so the order is not file order and
not the order the bank used.

    python scripts/draw_gate_a_set.py               # writes tasks/gate_a/sealed_set.jsonl
"""

from __future__ import annotations

import csv
import hashlib
import json
import re
import sys
from collections import defaultdict
from pathlib import Path
from typing import Dict, List, Set

REPO = Path(__file__).resolve().parent.parent
CATALOGUE = REPO / "docs" / "smart_building_questions.csv"
SURVEY = (
    REPO / "paper" / "Survey analysis and results" / "outputs" / "master table analysis"
    / "complexity_master_table.csv"
)
OUT_DIR = REPO / "tasks" / "gate_a"
OUT = OUT_DIR / "sealed_set.jsonl"
SALT = "gate-a-v12-29-sealed-2026-09-15"

PER_ROLE = 2
PER_CATEGORY = 1
PER_LEVEL = 3


def norm(q: str) -> str:
    """The comparison form: lowercase, alphanumerics only, single spaces."""
    return " ".join(re.sub(r"[^a-z0-9]+", " ", (q or "").lower()).split())


def _order(key: str) -> str:
    return hashlib.sha256((SALT + key).encode("utf-8")).hexdigest()


def used_questions() -> Set[str]:
    """Every question text this project has already used, in comparison form."""
    used: Set[str] = set()
    bank = REPO / "docs" / "demo_question_bank.jsonl"
    if bank.is_file():
        for line in bank.read_text(encoding="utf-8").splitlines():
            if line.strip():
                used.add(norm(json.loads(line)["question"]))
    script = REPO / "docs" / "demo_script_questions.txt"
    if script.is_file():
        for line in script.read_text(encoding="utf-8").splitlines():
            if line.strip() and not line.startswith("#"):
                used.add(norm(line))
    cases = REPO / "scripts" / "regression_cases.json"
    if cases.is_file():
        data = json.loads(cases.read_text(encoding="utf-8"))
        for c in data.get("cases", data) if isinstance(data, dict) else data:
            if isinstance(c, dict) and c.get("question"):
                used.add(norm(c["question"]))
    for path in (REPO / "scripts" / "outputs").glob("*.jsonl"):
        for line in path.read_text(encoding="utf-8", errors="replace").splitlines():
            try:
                used.add(norm(json.loads(line).get("q", "")))
            except Exception:
                continue
    for path in (REPO / "tests").glob("*.py"):
        for s in re.findall(r"[\"']([^\"'\n]{20,})[\"']", path.read_text(encoding="utf-8", errors="replace")):
            used.add(norm(s))
    used.discard("")
    return used


def draw() -> List[Dict[str, str]]:
    used = used_questions()
    rows = list(csv.DictReader(CATALOGUE.open(encoding="utf-8-sig", newline="")))
    sealed: List[Dict[str, str]] = []
    seen: Set[str] = set()

    def take(q: str, **meta) -> bool:
        k = norm(q)
        if not k or k in used or k in seen:
            return False
        seen.add(k)
        sealed.append({"question": q.strip(), **meta})
        return True

    by_role: Dict[str, List[Dict[str, str]]] = defaultdict(list)
    by_cat: Dict[str, List[Dict[str, str]]] = defaultdict(list)
    for r in rows:
        if (r.get("Source_Doc") or "").strip() and (r.get("Stakeholder_Role") or "").strip():
            by_role[r["Stakeholder_Role"].strip()].append(r)
        if (r.get("Category") or "").strip():
            by_cat[r["Category"].strip()].append(r)
    for role in sorted(by_role):
        n = 0
        for r in sorted(by_role[role], key=lambda x: _order(x.get("ID") or x["Question"])):
            if n >= PER_ROLE:
                break
            n += take(r["Question"], source=r.get("Source", ""), id=r.get("ID", ""),
                      stakeholder=role, category=r.get("Category", ""),
                      boundary=(r.get("Answer_Boundary") or "")[:400])
    for cat in sorted(by_cat):
        n = 0
        for r in sorted(by_cat[cat], key=lambda x: _order(x.get("ID") or x["Question"])):
            if n >= PER_CATEGORY:
                break
            n += take(r["Question"], source=r.get("Source", ""), id=r.get("ID", ""),
                      stakeholder=r.get("Stakeholder_Role", ""), category=cat, boundary="")
    if SURVEY.is_file():
        by_level: Dict[str, List[Dict[str, str]]] = defaultdict(list)
        for r in csv.DictReader(SURVEY.open(encoding="utf-8-sig", newline="")):
            by_level[r.get("level_name", "")].append(r)
        for level in sorted(by_level):
            n = 0
            pool = sorted(by_level[level],
                          key=lambda r: (r.get("answerability") != "full", _order(r.get("qid", ""))))
            for r in pool:
                if n >= PER_LEVEL:
                    break
                n += take(r["question"], source="survey", id=r.get("qid", ""),
                          stakeholder=r.get("roles", ""), category=level, boundary="")
    return sealed


def main() -> int:
    sealed = draw()
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    body = "\n".join(json.dumps(s, ensure_ascii=False, sort_keys=True) for s in sealed) + "\n"
    OUT.write_text(body, encoding="utf-8")
    digest = hashlib.sha256(body.encode("utf-8")).hexdigest()
    (OUT_DIR / "SEALED.sha256").write_text(f"{digest}  sealed_set.jsonl\n", encoding="utf-8")
    by_source: Dict[str, int] = defaultdict(int)
    for s in sealed:
        by_source[s["source"] or "(no source recorded)"] += 1
    print(f"sealed {len(sealed)} questions -> {OUT.relative_to(REPO)}")
    print("by source:", dict(sorted(by_source.items())))
    print(f"sha256 {digest}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
