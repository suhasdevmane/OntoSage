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
from typing import Dict, List, Optional, Set, Tuple

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


#: Longest first, so "authoritative supporting data" is never read as
#: "authoritative sources" plus stray words.
_SECTIONS_BY_LEN = sorted(_SECTIONS, key=len, reverse=True)


def _is_section(line: str) -> bool:
    low = line.strip().lower().rstrip(":")
    return any(low == s or low.startswith(s) for s in _SECTIONS)


def _split_headings(line: str) -> Tuple[List[str], str]:
    """Split a line into the run of section headings it opens with, plus the remainder.

    Most catalogues put one heading on a line and its body on the next, so this
    returns a single heading and an empty remainder. Two catalogues lay each
    question card out as side-by-side boxes whose headings share one PDF block —
    ``"SENSORS AND TELEMETRY ANALYSIS REQUIRED"`` — and this is what separates
    them. A few blocks carry a heading and its body together
    (``"WHY THIS IS USEFUL Enables the team to ..."``); that body comes back as
    the remainder and belongs to the last heading found.
    """
    rest = line.strip().rstrip(":")
    heads: List[str] = []
    while rest:
        low = rest.lower()
        match = next((s for s in _SECTIONS_BY_LEN if low.startswith(s)), None)
        if match is None:
            break
        heads.append(match)
        rest = rest[len(match) :].strip().lstrip(":").strip()
    return heads, rest


def _sections_of(block: List[str], opens: Set[int]) -> Dict[str, str]:
    """Map each section heading in one question block to its body text.

    ``opens`` holds the indices (relative to ``block``) at which a PDF block
    begins. They matter only when several headings arrive together: the bodies
    that follow are then separate PDF blocks and are handed out one apiece, in
    order. With a single heading pending, the body runs to the next heading as
    before, so a body split across several PDF blocks is still joined whole.
    """
    found: Dict[str, str] = {}
    pending: List[str] = []
    i = 0
    while i < len(block):
        line = block[i].strip()
        if not line or _NOISE.match(line):
            i += 1
            continue

        heads, remainder = _split_headings(line)
        if heads:
            pending.extend(heads)
            if remainder:  # heading and body shared a line
                found.setdefault(pending.pop(), remainder)
            i += 1
            continue

        if not pending:
            i += 1
            continue

        # A body. One PDF block each while several headings wait their turn;
        # otherwise everything up to the next heading.
        one_block_only = len(pending) > 1
        parts: List[str] = []
        while i < len(block):
            cur = block[i].strip()
            if cur and (_is_section(cur) or _NOISE.match(cur)):
                break
            if cur:
                parts.append(cur)
            i += 1
            if one_block_only and i in opens:
                break
        found.setdefault(pending.pop(0), _clean(" ".join(parts)))
    return found


def page_lines(pdf: Path) -> Tuple[List[str], Set[int]]:
    """All lines of the PDF in reading order, plus the indices that OPEN a PDF block.

    Reading order is correct in every one of the 37 catalogues and is left alone.
    What the plain text loses is where one laid-out box ends and the next begins,
    and two catalogues need exactly that. Room-booking and University estates set
    each question card as two side-by-side boxes, so a single block carries BOTH
    headings and the two bodies follow as separate blocks:

        "SENSORS AND TELEMETRY ANALYSIS REQUIRED"   <- one block, two headings
        "No sensor evidence is needed ..."          <- block, body of the first
        "Operation - authorised lookup ..."         <- block, body of the second

    Reading that as flat text put the sensors body under "Analysis Required" and
    shifted every later section one slot along, on 160 rows. Block starts let the
    splitter hand one body to each heading. Nothing else uses them, so the other
    35 catalogues parse exactly as before.
    """
    import fitz

    lines: List[str] = []
    starts: Set[int] = set()
    with fitz.open(pdf) as doc:
        for page in doc:
            blocks = [b for b in page.get_text("blocks") if b[6] == 0 and b[4].strip()]
            for block in _page_order(blocks):
                starts.add(len(lines))
                lines.extend(_merge_wrapped(block[4].splitlines()))
    return lines, starts


def _is_anchor(block) -> bool:
    """True when this PDF block opens a question — its first line is bare an ID."""
    first = next((ln.strip() for ln in block[4].splitlines() if ln.strip()), "")
    return bool(_ID_LINE.match(first))


def _bands(xs: List[float], gap: float = 40.0) -> List[float]:
    """Left edges of the layout columns on a page, clustered from block x-positions."""
    out: List[float] = []
    for x in sorted(xs):
        if not out or x - out[-1] > gap:
            out.append(x)
    return out


def _page_order(blocks: List) -> List:
    """Reading order for a page, re-grouped per question where the cards are columnar.

    Reading order is right for 36 of the 37 catalogues and is returned untouched.
    University estates lays each question out as a THREE-column card — sensors
    left, sources centre, analysis/boundary/why right — and stacks two of those
    per page. Flat reading order then emits both left-and-centre columns, then
    both right columns, so the right column of question *n* arrives after the ID
    of question *n+1*: the first question lost its analysis, boundary and why,
    and the second was handed the first's. 40 rows carried another question's
    reasoning, which is worse than carrying none.

    So on a page that holds several questions in three or more columns, each
    block is bound to the question it sits under and read column by column. The
    ID and the question text are pinned to the front of their card, because a
    question caption is typeset beside the ID rather than under it and must not
    land between a section heading and its body.
    """
    anchors = [b for b in blocks if _is_anchor(b)]
    if len(anchors) < 2:
        return blocks

    tops = sorted(b[1] for b in anchors)

    def card_of(block) -> float:
        # A caption set beside the ID can sit a few points above it.
        below = [t for t in tops if t <= block[1] + 20.0]
        return below[-1] if below else -1.0

    # Only reorder a page whose reading order actually INTERLEAVES the questions.
    # Layout shape is the wrong test: several catalogues set genuinely columnar
    # cards that still emit in the right order, and re-ordering those emptied two
    # of them outright. What is unambiguous is a block belonging to an earlier
    # question arriving after a later question's ID — that, and only that, is the
    # case flat reading order cannot express.
    seq = [card_of(b) for b in blocks]
    if all(a <= b for a, b in zip(seq, seq[1:])):
        return blocks

    bands = _bands([b[0] for b in blocks])

    ordered: List = []
    for card in [-1.0] + tops:
        group = [b for b in blocks if card_of(b) == card]
        if card < 0:
            ordered.extend(group)
            continue
        # The ID, the question marker and the question text are typeset across
        # the head of the card, so they are kept in reading order ahead of the
        # sections; only from the first heading on does the card read in columns.
        first_head = next(
            (
                i
                for i, b in enumerate(group)
                if any(_is_section(ln.strip()) for ln in b[4].splitlines())
            ),
            len(group),
        )
        head, body = group[:first_head], group[first_head:]
        ordered.extend(head)
        ordered.extend(
            sorted(body, key=lambda b: (max(i for i, x in enumerate(bands) if x <= b[0]), b[1]))
        )
    return ordered


def _merge_wrapped(block_lines: List[str]) -> List[str]:
    """Rejoin a section heading that the layout wrapped over two lines.

    One catalogue sets "AUTHORITATIVE SUPPORTING DATA" narrow enough that "DATA"
    falls to the next line. The splitter saw neither a heading nor a body and
    dropped the sources section on all 80 of its questions. Only a line that is
    a genuine prefix of a known heading is merged, so ordinary prose is untouched.
    """
    out: List[str] = []
    i = 0
    while i < len(block_lines):
        cur = block_lines[i].strip().rstrip(":")
        low = cur.lower()
        if (
            cur
            and i + 1 < len(block_lines)
            and not _is_section(cur)
            and any(s.startswith(low) and s != low for s in _SECTIONS)
            and _is_section(f"{cur} {block_lines[i + 1].strip()}")
        ):
            out.append(f"{cur} {block_lines[i + 1].strip()}")
            i += 2
            continue
        out.append(block_lines[i])
        i += 1
    return out


def page_text(pdf: Path) -> str:
    """Full text of the PDF in reading order."""
    return "\n".join(page_lines(pdf)[0])


def _clean(text: str) -> str:
    return " ".join(text.split()).strip()


#: A running page header reads as a question marker followed by text —
#: "TALKING ABACWS - STAKEHOLDER QUESTION CATALOGUE 12 ROOM-BOOKING TEAM" — and a
#: question's block runs to the next ID, so it swallows the NEXT page's header.
#: Scanning a whole block for a marker therefore found the header before the
#: question's own marker and stored page furniture as the question, on every
#: second question of four catalogues. Furniture is skipped as a candidate.
_HEADER_FURNITURE = re.compile(
    r"^(TALKING ABACWS|CATALOGUE \d|STAKEHOLDER QUESTION CATALOGUE"
    r"|Talking Abacws|Stakeholder Question Catalogue)",
    re.IGNORECASE,
)

#: An ALL-CAPS line is a sidebar or section caption, never part of a question.
_CAPS_LINE = re.compile(r"^[A-Z0-9][A-Z0-9 ,/&'.()–-]{6,}$")


def _skip(line: str) -> bool:
    """True when a line is page furniture and must never be read as question text."""
    return bool(_NOISE.match(line) or _HEADER_FURNITURE.match(line))


def _continue_question(block: List[str], start: int, seed: str = "") -> str:
    """Collect a question's text from ``start``, stopping where the question ends.

    A question wraps over as many lines as the layout needs, so collection runs on
    until something that cannot be part of it: a blank, a section heading, page
    furniture, or an ALL-CAPS sidebar caption. It also stops as soon as the text
    ends in a question mark — without that, one catalogue ran every question on
    into the "USE ONLY AFTER DEPLOYMENT..." panel set beside it, appending a
    sidebar to all 80.
    """
    parts: List[str] = [seed.strip()] if seed.strip() else []
    if parts and parts[-1].endswith("?"):
        return _clean(" ".join(parts))
    for cont in block[start:]:
        c = cont.strip()
        if _is_section(c):
            break
        if not c or _skip(c) or _CAPS_LINE.match(c):
            # Before the question has begun these are captions standing between
            # the marker and the text ("STAKEHOLDER QUESTION" / "CATEGORY 1" /
            # the question); once it has begun they are what ends it.
            if parts:
                break
            continue
        parts.append(c)
        if c.endswith("?"):
            break
    return _clean(" ".join(parts))


def parse(pdf: Path) -> List[Dict[str, str]]:
    """One dict per question found in this catalogue."""
    lines, opens = page_lines(pdf)

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
        # The marker patterns scan the whole block, and a block runs to the next
        # ID — so it also contains the following page's running header. Furniture
        # is skipped as a candidate everywhere below, or the header wins.

        # (a) inline "<role> question: <text>"
        for j, raw in enumerate(block):
            line = raw.strip()
            if _skip(line):
                continue
            m = _INLINE_Q.match(line)
            if m:
                question = _continue_question(block, j + 1, seed=m.group(2))
                break

        # (b) marker and question on ONE line: "TIMETABLING TEAM QUESTION Is weekly ..."
        if not question:
            for j, raw in enumerate(block):
                line = raw.strip()
                if _skip(line):
                    continue
                m = _MARKER_INLINE.match(line)
                if m:
                    question = _continue_question(block, j + 1, seed=m.group(1))
                    break

        # (c) a marker on its own line, text on the following lines
        if not question:
            for j, raw in enumerate(block):
                line = raw.strip()
                if not _skip(line) and _MARKER_Q.match(line):
                    question = _continue_question(block, j + 1)
                    break

        # (d) the marker sits BEFORE the id line, so the question opens the block
        #     ("BMS/HVAC OPERATORS QUESTION" / "BM-001" / "Which HVAC zones ..."), and
        # (e) some catalogues carry no marker at all — the question simply follows the
        #     id (Cleaning and caretaking teams). Both are read the same way, and both
        #     are guarded by _LOOKS_LIKE_Q so a section title is never taken for a
        #     question.
        if not question:
            marker_before = bool(idx and _MARKER_Q.match(lines[idx - 1].strip()))
            first = next(
                (
                    k
                    for k, c in enumerate(block)
                    if c.strip() and not _skip(c.strip()) and not _is_section(c.strip())
                ),
                None,
            )
            if first is not None and (marker_before or _LOOKS_LIKE_Q.search(block[first].strip())):
                candidate = _continue_question(block, first)
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

        sections = _sections_of(block, {k - (idx + 1) for k in opens})

        def _section_of(name: str) -> str:
            return sections.get(name, "")

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


#: Re-extracted from the PDF and always preferred when non-empty. These carry the
#: catalogue's own evidence specification and are what the V7 gap analysis reads.
_REFRESHED = (
    "Question",
    "Sensors_Required",
    "Authoritative_Sources",
    "Analysis_Required",
    "Answer_Boundary",
    "Notes",
)

#: Kept whenever the bank already holds a value. The bank's Section names and
#: CORE/SITUATIONAL priorities were curated by hand for the first six catalogues
#: and the extractor does not recover them from those files; overwriting would
#: blank a real Section and churn "CORE" to "Core" for no gain.
_CURATED_FIRST = ("Complexity_L", "Readiness_R", "Readiness_Label", "Priority", "Section")


def _refresh_row(row: Dict[str, str], parsed_row: Dict[str, str]) -> None:
    """Fold a freshly parsed question into a bank row already holding it.

    Only ever replaces a field with a non-empty new value, so a parse that misses
    a section leaves what the bank already had rather than erasing it.
    """
    for field in _REFRESHED:
        value = (parsed_row.get(field) or "").strip()
        if value:
            row[field] = value
    for field in _CURATED_FIRST:
        if not (row.get(field) or "").strip():
            row[field] = (parsed_row.get(field) or "").strip()


def main(argv: List[str]) -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--validate", action="store_true", help="compare against the CSV's 480")
    ap.add_argument("--dry-run", action="store_true")
    ap.add_argument(
        "--refresh",
        action="store_true",
        help="also re-extract the fields of rows already in the bank (see _refresh_row)",
    )
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
            if args.refresh:
                _refresh_row(row, r)

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
