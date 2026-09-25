#!/usr/bin/env python3
"""
clean_duplicate_questions.py
============================

Smart de-duplicator for the survey question corpus. Reads
``inputs/questions_by_user.csv`` and writes a copy that keeps only ONE row per
unique question, so a downstream LLM run (J_complexity_master_table.py) does not
pay to classify the same question twice.

WHY A SEPARATE FILE (not in place)?
    ``questions_by_user.csv`` is the canonical raw corpus. The paper's stats
    (5,127/5,916 questions, the S1-S4 stage counts, persona analysis) and the other
    analysis scripts (B/C/D/...) depend on the FULL set. So by default this writes
    a NEW file and leaves the original untouched. Point the classifier at it:

        $J = "paper/Survey analysis and results/scripts/J_complexity_master_table.py"
        $U = "paper/Survey analysis and results/inputs/questions_by_user_unique.csv"
        python $J --provider openai --model gpt-5.5 --input $U --turns 1

    (You usually do NOT also need --dedup then -- the file is already unique. Using
    it anyway is harmless.)

WHAT "SMART" MEANS HERE (deterministic, safe -- never merges distinct questions):
    Two rows are duplicates if their questions match after canonicalisation:
      - Unicode NFKC normalise (folds curly quotes / odd whitespace)
      - lowercase
      - strip surrounding quotes/brackets and outer whitespace
      - collapse internal whitespace to a single space
      - strip trailing punctuation (?!.,;: and spaces)
    This catches case / spacing / punctuation / trailing-"?" variants that a plain
    exact match misses, WITHOUT fuzzy/semantic merging (which could wrongly fuse two
    genuinely different questions). The FIRST occurrence is kept (earliest
    user/timestamp); later duplicates are dropped.

USAGE (PowerShell, from the repo ROOT -- quote the spaced path):
    $C = "paper/Survey analysis and results/scripts/clean_duplicate_questions.py"
    python $C                       # -> inputs/questions_by_user_unique.csv (+ summary)
    python $C --report              # also write a *_duplicates_report.csv to audit
    python $C --in-place            # overwrite the original (makes a .bak first)  [NOT advised]

Exit code 0 on success.
"""

from __future__ import annotations

import argparse
import csv
import re
import sys
import unicodedata
from pathlib import Path
from typing import Dict, List, Optional, Tuple

HERE = Path(__file__).resolve().parent
SURVEY_ROOT = HERE.parent
DEFAULT_INPUT = (
    SURVEY_ROOT / "corpus" / "classified_corpus.csv"
    if (SURVEY_ROOT / "corpus" / "classified_corpus.csv").exists()
    else SURVEY_ROOT / "inputs" / "questions_by_user.csv"
)
DEFAULT_OUTPUT = SURVEY_ROOT / "inputs" / "questions_by_user_unique.csv"

QUESTION_COL = "Question"
_TRAILING_PUNCT = re.compile(r"[\s?!.,;:]+$")
_LEADING_WRAP = re.compile(r'^[\s"\'`(\[]+')
_TRAILING_WRAP = re.compile(r'[\s"\'`)\]]+$')


def canonical(question: str) -> str:
    """Canonical form used to decide duplicates (see module docstring)."""
    q = unicodedata.normalize("NFKC", question or "")
    q = q.strip().lower()
    q = _LEADING_WRAP.sub("", q)
    q = _TRAILING_WRAP.sub("", q)
    q = re.sub(r"\s+", " ", q)
    q = _TRAILING_PUNCT.sub("", q).strip()
    return q


def dedupe(
    input_path: Path,
) -> Tuple[List[dict], List[str], Dict[str, List[dict]], int]:
    """Return (unique_rows, fieldnames, duplicate_groups, blank_count).

    ``duplicate_groups`` maps a canonical key -> all rows sharing it (only for
    keys that appeared more than once), preserving input order; the first row in
    each group is the one kept.
    """
    with input_path.open("r", encoding="utf-8-sig", newline="") as f:
        reader = csv.DictReader(f)
        fieldnames = list(reader.fieldnames or [])
        if QUESTION_COL not in fieldnames:
            raise SystemExit(
                f"ERROR: input has no '{QUESTION_COL}' column. Found: {fieldnames}"
            )
        unique: List[dict] = []
        seen: Dict[str, int] = {}            # canonical -> index in `unique`
        groups: Dict[str, List[dict]] = {}   # canonical -> [rows] (dupes only)
        blank = 0
        for row in reader:
            q = (row.get(QUESTION_COL) or "").strip()
            if not q:
                blank += 1
                continue
            key = canonical(q)
            if not key:
                blank += 1
                continue
            if key in seen:
                groups.setdefault(key, [unique[seen[key]]]).append(row)
            else:
                seen[key] = len(unique)
                unique.append(row)
    return unique, fieldnames, groups, blank


def write_rows(path: Path, fieldnames: List[str], rows: List[dict]) -> None:
    with path.open("w", encoding="utf-8", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=fieldnames)
        writer.writeheader()
        for r in rows:
            writer.writerow({k: r.get(k, "") for k in fieldnames})


def write_report(path: Path, groups: Dict[str, List[dict]]) -> None:
    """Audit file: one row per dropped duplicate, with the kept question alongside."""
    with path.open("w", encoding="utf-8", newline="") as f:
        w = csv.writer(f)
        w.writerow(["canonical_key", "occurrences", "kept_question", "dropped_question",
                    "dropped_username", "dropped_qnum"])
        for key, rows in sorted(groups.items(), key=lambda kv: -len(kv[1])):
            kept = rows[0].get(QUESTION_COL, "")
            for dropped in rows[1:]:
                w.writerow([
                    key, len(rows), kept,
                    dropped.get(QUESTION_COL, ""),
                    dropped.get("Username") or dropped.get("PID") or "",
                    dropped.get("QuestionNumber", ""),
                ])


def main() -> int:
    p = argparse.ArgumentParser(
        description="Remove duplicate questions from the survey corpus (keep first copy).",
        formatter_class=argparse.ArgumentDefaultsHelpFormatter,
    )
    p.add_argument("--input", type=Path, default=DEFAULT_INPUT)
    p.add_argument("--output", type=Path, default=DEFAULT_OUTPUT,
                   help="Where to write the unique CSV (ignored with --in-place).")
    p.add_argument("--in-place", action="store_true",
                   help="Overwrite the input file (a .bak backup is made first). NOT advised.")
    p.add_argument("--report", action="store_true",
                   help="Also write <output>_duplicates_report.csv listing what was dropped.")
    args = p.parse_args()

    if not args.input.exists():
        sys.stderr.write(f"ERROR: input not found: {args.input}\n")
        return 2

    unique, fieldnames, groups, blank = dedupe(args.input)
    total_kept = len(unique)
    removed = sum(len(rows) - 1 for rows in groups.values())
    total_rows = total_kept + removed + blank

    if args.in_place:
        backup = args.input.with_suffix(args.input.suffix + ".bak")
        if not backup.exists():
            backup.write_bytes(args.input.read_bytes())
        out_path = args.input
        backup_note = f"  backup : {backup}\n"
    else:
        out_path = args.output
        backup_note = ""

    out_path.parent.mkdir(parents=True, exist_ok=True)
    write_rows(out_path, fieldnames, unique)

    report_note = ""
    if args.report and groups:
        rep = out_path.with_name(out_path.stem + "_duplicates_report.csv")
        write_report(rep, groups)
        report_note = f"  report : {rep}  ({len(groups)} duplicate groups)\n"

    pct = (100.0 * removed / total_rows) if total_rows else 0.0
    sys.stdout.write(
        "Smart de-duplication complete.\n"
        f"  input  : {args.input}\n"
        f"  output : {out_path}\n"
        f"{backup_note}{report_note}"
        f"  rows in     : {total_rows}\n"
        f"  blank/skip  : {blank}\n"
        f"  duplicates  : {removed} removed ({pct:.1f}% of rows)\n"
        f"  unique kept : {total_kept}\n"
    )
    if not args.in_place:
        sys.stdout.write(
            "\nNext: run the classifier against the unique file --\n"
            f'  --input "{out_path}"\n'
        )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
