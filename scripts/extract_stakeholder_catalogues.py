# -*- coding: utf-8 -*-
"""Extract every question from the Talking Abacws stakeholder catalogues.

37 catalogues, 80 questions each, 2,960 in total. Six were already in
``tasks/smart_building_questions.csv`` (480 rows, IDs UG-/PGT-/PHD-/RS-/LT-/AO-); the
other 31 are new.

**Three layouts, one anchor.** The catalogues were authored at different times and their
question blocks differ:

    OLD      UG-003 / CORE / L4 - itinerary optimisation / R2 - integration-dependent
             "Student question: <text>"
    NEW-A    FM-003  CRITICAL STATUS GAPS / L2 calculation | R3 restricted
             "FACILITIES MANAGERS QUESTION" then the text on the next line
    NEW-B    SO-005 / SECTION / RECOMMENDATION / EXCEPTIONS
             "STAKEHOLDER QUESTION" then the text on the next line

What every layout shares is that a block begins with a line that is exactly an ID, and
the question follows a marker that either ends in "QUESTION" or reads "<something>
question:". So the extractor anchors on those two facts and treats the rest as optional.

**It is validated against the 480 questions already extracted by hand.** If this script
cannot reproduce those, it cannot be trusted on the other 2,480 — `--validate` does that
comparison and reports any question whose text differs.

    python scripts/extract_stakeholder_catalogues.py --validate
    python scripts/extract_stakeholder_catalogues.py --dry-run
    python scripts/extract_stakeholder_catalogues.py            # merge into the CSV
"""

from __future__ import annotations

import argparse
import csv
import re
import sys
from pathlib import Path
from typing import Dict, List, Optional, Tuple

REPO = Path(__file__).resolve().parents[1]
CATALOGUES = REPO / "QuestionBank" / "Talking_Abacws_37_Stakeholder_Catalogues"
BANK = REPO / "tasks" / "smart_building_questions.csv"

#: A block starts with a line that is exactly an ID, optionally followed by a title.
_ID_LINE = re.compile(r"^([A-Z]{2,6}-\d{3})(?:\s{2,}(.*))?$")

#: "Student question: ..." / "Manager question: ..." — the old layout, inline.
_INLINE_Q = re.compile(r"^([A-Z][A-Za-z /,'-]{2,60})\s+question:\s*(.+)$", re.IGNORECASE)

#: "STAKEHOLDER QUESTION" / "FACILITIES MANAGERS QUESTION" — the newer layouts, on its
#: own line with the text following.
_MARKER_Q = re.compile(r"^[A-Z][A-Z ,/&'.-]{2,120}\bQUESTION\b\s*$")

#: "TIMETABLING TEAM QUESTION Is weekly delivery or ..." — marker and question sharing
#: one line (Timetabling team).
_MARKER_INLINE = re.compile(r"^[A-Z][A-Z ,/&'.-]{2,120}\bQUESTION\b\s+(\S.*)$")

#: A block whose question carries no marker at all (Cleaning and caretaking teams): the
#: question is simply the first line after the ID. Guarded, because without a marker the
#: first line could equally be a section title — it must actually read as a question.
_LOOKS_LIKE_Q = re.compile(
    r"\?\s*$|^(?:which|what|where|when|why|how|who|is|are|do|does|did|can|could|should"
    r"|will|would|has|have|am)\b",
    re.IGNORECASE,
)

#: Section headings, in every casing the catalogues use. A question ends where one starts.
#:
#: MEASURED, not guessed. A first pass listed "operation", "safe failure" and "evidence
#: and provenance" as headings — they are not, they are how the analysis PARAGRAPH opens
#: ("Operation: calculation. Interval: current shift..."), so treating them as boundaries
#: truncated Analysis_Required to empty on 81% of questions. It also missed
#: "authoritative supporting data", which is the heading 2,671 of the 2,960 blocks
#: actually use. Counting the headings across all 37 files settled both.
_SECTIONS = [
    "sensors and telemetry",
    "authoritative supporting data",
    "supporting building data",
    "authoritative sources",
    "authoritative building data",
    "analysis required",
    "answer boundary",
    "why this is useful",
]

_COMPLEXITY = re.compile(r"\b(L[1-4])\b\s*[-–—]?\s*([a-z][a-z ,/-]{2,60})?", re.IGNORECASE)
_READINESS = re.compile(r"\b(R[1-4])\b\s*[-–—]?\s*([a-z][a-z ,/-]{2,60})?", re.IGNORECASE)
_PRIORITY = re.compile(r"^(CORE|SITUATIONAL|CRITICAL|ESSENTIAL|ADVANCED|OPTIONAL)\b")

#: Page furniture that appears mid-block and must never be mistaken for content.
_NOISE = re.compile(
    r"^(TALKING ABACWS|/\s|STAKEHOLDER \d+|\d+$|Talking Abacws design companion"
    r"|Evidence-aware|Proposed capability)",
    re.IGNORECASE,
)


def _is_section(line: str) -> bool:
    low = line.strip().lower().rstrip(":")
    return any(low == s or low.startswith(s) for s in _SECTIONS)


def page_text(pdf: Path) -> str:
    import fitz

    doc = fitz.open(pdf)
    return "\n".join(doc[i].get_text() for i in range(doc.page_count))


def _clean(text: str) -> str:
    return " ".join(text.split()).strip()


def parse(pdf: Path) -> List[Dict[str, str]]:
    """One dict per question found in this catalogue."""
    lines = page_text(pdf).splitlines()

    # locate every block start
    starts: List[Tuple[int, str, str]] = []
    for i, raw in enumerate(lines):
        m = _ID_LINE.match(raw.strip())
        if m:
            starts.append((i, m.group(1), (m.group(2) or "").strip()))

    out: List[Dict[str, str]] = []
    seen = set()
    for n, (idx, qid, title) in enumerate(starts):
        if qid in seen:
            continue  # an ID repeated in a running header, not a second question
        end = starts[n + 1][0] if n + 1 < len(starts) else len(lines)
        block = lines[idx + 1 : end]

        question = ""
        # (a) inline "<role> question: <text>"
        for j, raw in enumerate(block):
            m = _INLINE_Q.match(raw.strip())
            if m:
                parts = [m.group(2).strip()]
                for cont in block[j + 1 :]:
                    c = cont.strip()
                    if not c or _is_section(c) or _NOISE.match(c):
                        break
                    parts.append(c)
                question = _clean(" ".join(parts))
                break
        # (b) marker and question on ONE line: "TIMETABLING TEAM QUESTION Is weekly ..."
        if not question:
            for j, raw in enumerate(block):
                m = _MARKER_INLINE.match(raw.strip())
                if m:
                    parts = [m.group(1).strip()]
                    for cont in block[j + 1 :]:
                        c = cont.strip()
                        if not c or _is_section(c) or _NOISE.match(c):
                            break
                        parts.append(c)
                    question = _clean(" ".join(parts))
                    break

        # (c) a marker on its own line, text on the following lines
        if not question:
            for j, raw in enumerate(block):
                if _MARKER_Q.match(raw.strip()):
                    parts: List[str] = []
                    for cont in block[j + 1 :]:
                        c = cont.strip()
                        if not c:
                            if parts:
                                break
                            continue
                        if _is_section(c) or _NOISE.match(c):
                            break
                        parts.append(c)
                    question = _clean(" ".join(parts))
                    break

        # (d) the marker sits BEFORE the id line, so the question opens the block
        #     ("BMS/HVAC OPERATORS QUESTION" / "BM-001" / "Which HVAC zones ..."), and
        # (e) some catalogues carry no marker at all — the question simply follows the
        #     id (Cleaning and caretaking teams). Both are read the same way, and both
        #     are guarded by _LOOKS_LIKE_Q so a section title is never taken for a
        #     question.
        if not question:
            marker_before = bool(idx and _MARKER_Q.match(lines[idx - 1].strip()))
            parts: List[str] = []
            for cont in block:
                c = cont.strip()
                if not c:
                    if parts:
                        break
                    continue
                if _is_section(c) or _NOISE.match(c):
                    break
                if not parts and not (marker_before or _LOOKS_LIKE_Q.search(c)):
                    break  # a title, not a question
                parts.append(c)
            candidate = _clean(" ".join(parts))
            if candidate and (marker_before or _LOOKS_LIKE_Q.search(candidate)):
                question = candidate

        if not question:
            continue  # nothing that looks like a question — reported by the caller

        head = " ".join(block[:6])
        cm = _COMPLEXITY.search(head)
        rm = _READINESS.search(head)
        pm = next(
            (_PRIORITY.match(b.strip()) for b in block[:6] if _PRIORITY.match(b.strip())), None
        )

        def _section_of(name: str) -> str:
            for j, raw in enumerate(block):
                if raw.strip().lower().rstrip(":").startswith(name):
                    parts = []
                    for cont in block[j + 1 :]:
                        c = cont.strip()
                        if not c or _is_section(c) or _NOISE.match(c):
                            break
                        parts.append(c)
                    return _clean(" ".join(parts))
            return ""

        seen.add(qid)
        out.append(
            {
                "ID": qid,
                "Question": question,
                "Priority": pm.group(1).title() if pm else "",
                "Complexity_L": cm.group(1).upper() if cm else "",
                "Readiness_R": rm.group(1).upper() if rm else "",
                "Readiness_Label": _clean(rm.group(2) or "") if rm else "",
                "Sensors_Required": _section_of("sensors and telemetry"),
                "Authoritative_Sources": (
                    _section_of("authoritative supporting data")
                    or _section_of("authoritative sources")
                    or _section_of("supporting building data")
                    or _section_of("authoritative building data")
                ),
                "Analysis_Required": _section_of("analysis required"),
                "Answer_Boundary": _section_of("answer boundary"),
                "Notes": _section_of("why this is useful"),
                "Section": title,
                "Source_Doc": pdf.name,
            }
        )
    return out


def role_for(pdf: Path) -> str:
    """The stakeholder role, from the catalogue's own name."""
    stem = pdf.stem
    # the six older files carry a numbered prefix
    m = re.match(r"Talking_Abacws_Stakeholder_\d+_(.+)$", stem)
    if m:
        stem = m.group(1).replace("_", " ")
    return stem.strip()


def main(argv: List[str]) -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--validate", action="store_true", help="compare against the CSV's 480")
    ap.add_argument("--dry-run", action="store_true")
    ap.add_argument("--out", default=str(BANK))
    args = ap.parse_args(argv)

    if not CATALOGUES.is_dir():
        print(f"catalogue folder not found: {CATALOGUES}")
        return 1

    parsed: Dict[str, Dict[str, str]] = {}
    per_file: List[Tuple[str, int]] = []
    for pdf in sorted(CATALOGUES.glob("*.pdf")):
        rows = parse(pdf)
        role = role_for(pdf)
        for r in rows:
            r["Stakeholder_Role"] = role
            parsed[r["ID"]] = r
        per_file.append((pdf.name, len(rows)))

    short = [(n, c) for n, c in per_file if c != 80]
    print(f"parsed {len(parsed)} questions from {len(per_file)} catalogues")
    if short:
        print(f"  !! {len(short)} file(s) did not yield 80 questions:")
        for n, c in short:
            print(f"     {c:3d}  {n}")

    existing = list(csv.DictReader(BANK.open(encoding="utf-8-sig")))
    fields = list(existing[0].keys())
    by_id = {r["ID"]: r for r in existing}

    if args.validate:
        known = [
            r
            for r in existing
            if r["ID"] in parsed and (r.get("Source") or "") != "v5_synthetic_bank"
        ]
        same = diff = 0
        examples = []
        for r in known:
            a = _clean(r["Question"])
            b = _clean(parsed[r["ID"]]["Question"])
            if a == b:
                same += 1
            else:
                diff += 1
                if len(examples) < 5:
                    examples.append((r["ID"], a, b))
        print(f"\nVALIDATION against the {len(known)} hand-extracted rows:")
        print(f"  identical: {same}   different: {diff}")
        for qid, a, b in examples:
            print(f"\n  {qid}\n    csv: {a[:150]}\n    pdf: {b[:150]}")
        return 0 if diff == 0 else 2

    new_ids = [q for q in parsed if q not in by_id]
    print(f"\nnew questions to add: {len(new_ids)}")
    print(
        f"existing rows to enrich with a role: "
        f"{sum(1 for q in parsed if q in by_id and not (by_id[q].get('Stakeholder_Role') or '').strip())}"
    )

    if args.dry_run:
        print("\nDRY RUN — nothing written")
        return 0

    # enrich existing rows, then append the new ones
    for qid, r in parsed.items():
        if qid in by_id:
            row = by_id[qid]
            if not (row.get("Stakeholder_Role") or "").strip():
                row["Stakeholder_Role"] = r["Stakeholder_Role"]
            if not (row.get("Source_Doc") or "").strip():
                row["Source_Doc"] = r["Source_Doc"]

    added = []
    for qid in sorted(new_ids):
        r = parsed[qid]
        row = {k: "" for k in fields}
        for k, v in r.items():
            if k in row:
                row[k] = v
        row["Source"] = "stakeholder_catalogue_37"
        added.append(row)

    out = Path(args.out)
    with out.open("w", newline="", encoding="utf-8-sig") as fh:
        w = csv.DictWriter(fh, fieldnames=fields)
        w.writeheader()
        w.writerows(existing)
        w.writerows(added)
    print(
        f"\nwrote {out}: {len(existing)} existing + {len(added)} new = {len(existing) + len(added)} rows"
    )
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
