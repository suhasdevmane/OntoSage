#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Extract the supervisors' stakeholder-catalogue questions from the QuestionBank PDFs.

Parsed, not summarised. The catalogue records are highly regular:

    UG-001
    CORE
    L3 - prediction and recommendation
    R2 - integration-dependent
    Student question: <text, possibly wrapped over several lines>
    Sensors and telemetry
    ...

so the question text can be lifted verbatim. That matters: these 480 questions become an
acceptance corpus, and a paraphrased question is a different question — it would quietly
change what the system is being tested on. An LLM extraction pass was rejected for exactly
that reason.

Emits one row per catalogue record, with the supervisors' own priority tag, operation
complexity (L1-L4) and readiness tier (R1-R3) preserved as given.

Usage:
    python scripts/extract_catalogue_questions.py --out tasks/v6/catalogue_questions.csv
"""

from __future__ import annotations

import argparse
import csv
import re
import sys
from pathlib import Path
from typing import Dict, List, Optional

REPO = Path(__file__).resolve().parent.parent
PDF_DIR = REPO / "QuestionBank"

#: Catalogue id prefix -> the stakeholder role that catalogue is written for.
ROLE_BY_PREFIX = {
    "UG": "Undergraduate Student",
    "PGT": "Taught Postgraduate Student",
    "PHD": "PhD Student",
    "RS": "Research Staff",
    "LT": "Lecturer or Tutor",
    "AO": "Academic Office Occupant",
}

_ID_RE = re.compile(r"^(UG|PGT|PHD|RS|LT|AO)-(\d{3})$")
_L_RE = re.compile(r"^(L[1-4])\s*[-–]\s*(.+)$")
_R_RE = re.compile(r"^(R[1-3])\s*[-–]\s*(.+)$")
#: "Student question:", "Lecturer question:", "Researcher question:" - the label varies per
#: catalogue, so match the shape rather than enumerating the wordings.
_Q_RE = re.compile(r"^([A-Z][A-Za-z /]{2,40})\s+question:\s*(.*)$")
_SECTION_RE = re.compile(r"^(\d+)\.\s+(.{3,80})$")

#: Headings that end the question text. Everything after the first of these belongs to the
#: record's evidence annexes, not to what the user would say out loud.
_END_HEADINGS = (
    "Sensors and telemetry",
    "Supporting building data",
    "Analysis required",
    "Answer boundary",
    "Why this is useful",
)

#: Field headings whose bodies we keep, mapped to the output column they populate.
_ANNEX = {
    "Sensors and telemetry": "sensors_required",
    "Supporting building data": "authoritative_sources",
    "Analysis required": "analysis_required",
    "Answer boundary": "answer_boundary",
}


_QRANGE_RE = re.compile(r"^Questions?\s+[A-Z]+-\d+")
_TITLE_RE = re.compile(r"^TALKING ABACWS|^[A-Z][A-Z ,/&-]{8,}$")


def _lines(pdf: Path) -> tuple[List[str], List[str]]:
    """Return (content lines, section-in-force for each line).

    The catalogue repeats its section heading as a running header on EVERY page,
    which is what makes the section recoverable at all — but those headers sit
    between records, where the previous record's annex scan would otherwise eat
    them and leave the section stale. Resolving the section here, once, and
    stripping the furniture out of the content stream avoids that entirely:
    PGT-051 belongs to section 6, and a parser that reported section 1 would be
    quietly mislabelling a third of the corpus.
    """
    from pypdf import PdfReader

    out: List[str] = []
    sects: List[str] = []
    section = ""
    for page in PdfReader(str(pdf)).pages:
        for raw in (page.extract_text() or "").splitlines():
            s = raw.strip()
            if not s:
                continue
            sm = _SECTION_RE.match(s)
            if sm and not _ID_RE.match(s):
                section = f"{sm.group(1)}. {sm.group(2)}"
                continue  # furniture, not content
            if _QRANGE_RE.match(s) or _TITLE_RE.match(s):
                continue
            out.append(s)
            sects.append(section)
    return out, sects


def _collect(lines: List[str], i: int) -> tuple[str, int]:
    """Join wrapped lines from i until the next known heading."""
    buf: List[str] = []
    while i < len(lines):
        s = lines[i]
        if s in _END_HEADINGS or _ID_RE.match(s):
            break
        buf.append(s)
        i += 1
    return " ".join(buf).strip(), i


def parse(pdf: Path) -> List[Dict[str, str]]:
    lines, sects = _lines(pdf)
    rows: List[Dict[str, str]] = []
    i = 0
    while i < len(lines):
        m = _ID_RE.match(lines[i])
        if not m:
            i += 1
            continue

        qid = lines[i]
        prefix = m.group(1)
        rec: Dict[str, str] = {
            "ID": qid,
            "Stakeholder_Role": ROLE_BY_PREFIX[prefix],
            "Section": sects[i],
            "Priority": "",
            "Complexity_L": "",
            "Operation": "",
            "Readiness_R": "",
            "Readiness_Label": "",
            "Question": "",
            "sensors_required": "",
            "authoritative_sources": "",
            "analysis_required": "",
            "answer_boundary": "",
            "Source_Doc": pdf.name,
        }
        i += 1

        # Header block: priority tag, L-level, R-tier - order is stable but be tolerant.
        while i < len(lines) and not _Q_RE.match(lines[i]) and not _ID_RE.match(lines[i]):
            s = lines[i]
            lm, rm = _L_RE.match(s), _R_RE.match(s)
            if lm:
                rec["Complexity_L"], rec["Operation"] = lm.group(1), lm.group(2).strip()
            elif rm:
                rec["Readiness_R"], rec["Readiness_Label"] = rm.group(1), rm.group(2).strip()
            elif s.isupper() and 3 <= len(s) <= 30 and not rec["Priority"]:
                rec["Priority"] = s
            i += 1

        if i < len(lines):
            qm = _Q_RE.match(lines[i])
            if qm:
                head = qm.group(2).strip()
                i += 1
                rest, i = _collect(lines, i)
                rec["Question"] = (head + " " + rest).strip()

        # Annex bodies
        while i < len(lines) and not _ID_RE.match(lines[i]):
            s = lines[i]
            if s in _ANNEX:
                i += 1
                body, i = _collect(lines, i)
                rec[_ANNEX[s]] = body
            elif s == "Why this is useful":
                i += 1
                _, i = _collect(lines, i)
            else:
                i += 1

        if rec["Question"]:
            rows.append(rec)
    return rows


def main(argv: List[str]) -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--out", default="tasks/v6/catalogue_questions.csv")
    args = ap.parse_args(argv)

    all_rows: List[Dict[str, str]] = []
    for pdf in sorted(PDF_DIR.glob("Talking_Abacws_Stakeholder_*.pdf")):
        rows = parse(pdf)
        tiers: Dict[str, int] = {}
        for r in rows:
            tiers[r["Readiness_R"] or "?"] = tiers.get(r["Readiness_R"] or "?", 0) + 1
        print(f"  {pdf.name[:52]:<54} {len(rows):>3} questions  tiers={tiers}")
        all_rows.extend(rows)

    out = REPO / args.out
    out.parent.mkdir(parents=True, exist_ok=True)
    with out.open("w", encoding="utf-8-sig", newline="") as fh:
        w = csv.DictWriter(fh, fieldnames=list(all_rows[0].keys()))
        w.writeheader()
        w.writerows(all_rows)
    print(f"\n  wrote {len(all_rows)} questions -> {out}")
    return 0 if len(all_rows) == 480 else 1


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
