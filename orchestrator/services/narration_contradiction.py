# -*- coding: utf-8 -*-
"""Detect (never edit) two shapes of an answer contradicting itself (G4/G6, 2026-10-04).

Both shapes were found live and hand-read, not guessed:

* **G6** — "Thus, the last time Room 5.08 met all listed comfort and air-quality standards
  was at 2026-10-02 11:45:13" sat in the SAME answer as "❌ non-compliant with WELL v2 and
  BREEAM Hea 02" for a standard measured at that exact timestamp. The compliance lane is
  LLM-narrated (there is no template generating "non-compliant" in this codebase), so the
  fix cannot be a deterministic rewrite without a live model to iterate against -- this
  module only COUNTS the shape, the way `scripts/count_gate_deletions.py` counts BUG-1252's
  gate deletions, so a week of real answers can be read before anything is enforced.
* **G4** — BUG-1405's shape: a headline average/range sitting outside the min/max of the
  answer's own printed per-group table ("averaging 27.6 degC, ranging from 7.2 to 71.0 degC"
  above a table reading 23.0-23.9 degC). `narration_validators._average_decision` already
  catches the narrower "X per <group>" phrasing; this module's `range_contradiction`
  additionally flags the bare "averaging N, ranging from A to B" shape that phrasing does
  not require a "per <group>" clause to use, WITHOUT touching `narration_validators.py`'s
  active-editing pipeline -- every guard added to that pipeline has destroyed a correct
  answer at least once (lesson #135), and this module never edits a single character.

Every function here is pure, returns None on "nothing to report", and is called from the
response path inside a bare `except: pass` -- a detector that could cost an answer would be
strictly worse than the defect it watches for.
"""
from __future__ import annotations

import re
from typing import List, Optional

#: A sentence asserting FULL compliance / comfort, over some span of standards or time.
_FULL_COMPLIANCE_CLAIM_RE = re.compile(
    r"\b(?:met|meets|meeting)\s+all\b[^.?!]{0,60}\b(?:standard|requirement|threshold|band)s?\b"
    r"|\b(?:is|was|remains?)\s+(?:fully\s+)?compliant\s+with\s+(?:every|all)\b"
    r"|\bthe\s+last\s+time\b[^.?!]{0,60}\bmet\s+all\b"
    # 2026-10-07, G6 widened: the original three alternatives all require the word
    # "standard"/"compliant" -- a plain "was comfortable" or "all comfort standards were
    # met" claim slipped past them. Measured against ~5,000 real stored answers: 2 new
    # hits, both a NEGATED claim ("you can't say whether it is comfortable") with no
    # nearby timestamp, so reconcile_compliance_claim's own timestamp-match gate (below)
    # would not edit either -- only compliance_contradiction's passive counter sees them.
    r"|\b(?:was|is|remains?)\s+(?:last\s+)?comfortable\b"
    r"|\ball\s+(?:comfort|air[\s-]?quality)\s+standards?\s+(?:were|was)\s+met\b",
    re.IGNORECASE,
)

#: An explicit NON-compliance marker the same answer's own prose or table carries.
_NON_COMPLIANCE_MARKER_RE = re.compile(
    r"❌|\bnon[\s-]?compliant\b|\bfails?\s+(?:to\s+meet|compliance)\b|\bnot\s+compliant\b",
    re.IGNORECASE,
)


def compliance_contradiction(text: str) -> Optional[str]:
    """The claim sentence, when the SAME text also carries an explicit non-compliance
    marker -- G6's shape. None when there is nothing to report (including on any input
    that is not a string, or empty)."""
    if not text or not isinstance(text, str):
        return None
    if not _NON_COMPLIANCE_MARKER_RE.search(text):
        return None
    m = _FULL_COMPLIANCE_CLAIM_RE.search(text)
    if not m:
        return None
    # The sentence containing the match, trimmed to one line for a readable log.
    start = text.rfind(".", 0, m.start()) + 1
    end = text.find(".", m.end())
    end = end + 1 if end != -1 else len(text)
    return text[start:end].strip()


def reconcile_compliance_claim(text: str, verdict: Optional[dict]) -> str:
    """Replace the claim sentence ONLY when it asserts the newest reading met all standards
    and that reading's own verdict (``standards_engine.newest_reading_verdict``) fails one.

    BUG-1428 / trial G6: "the last time it met all listed standards was 11:45:13" was printed
    beside a non-compliance mark for that same 11:45:13 reading. The replacement states the
    verdict the same check produced and says no earlier reading was searched, so it asserts
    nothing that was not computed. Returns ``text`` unchanged for any other input, including a
    claim about an EARLIER time, which the newest reading cannot contradict.
    """
    if not isinstance(text, str) or not text or not isinstance(verdict, dict):
        return text
    failing = verdict.get("failing") or []
    at = str(verdict.get("at") or "").strip()
    if not failing or not at:
        return text
    m = _FULL_COMPLIANCE_CLAIM_RE.search(text)
    if not m:
        return text
    start = text.rfind(".", 0, m.start()) + 1
    end = text.find(".", m.end())
    end = end + 1 if end != -1 else len(text)
    time_of_day = at[-8:] if len(at) >= 8 else at
    if time_of_day not in text[start:end]:
        return text
    names = "; ".join(
        f"{f.get('standard', '')}: {', '.join(f.get('parameters') or []) or 'see checks'}"
        for f in failing
    )
    replacement = (
        f" At the newest reading ({at}) the building does not fully meet all listed standards. "
        f"Not compliant: {names}. No earlier reading was searched, so no earlier time is claimed."
    )
    return text[:start] + replacement + text[end:]


#: "averaging N <unit>, ranging from A to B <unit>" -- the bare headline shape, no "per
#: <group>" required. Deliberately narrower than a generic number-pair scan: both the verb
#: ("averaging") and the range phrase ("ranging from ... to ...") must be present together,
#: which is specific enough that it should not fire on an ordinary sentence with two numbers.
_HEADLINE_AVG_RANGE_RE = re.compile(
    r"averag\w+\s+(?P<avg>-?\d[\d,]*\.?\d*)\s*[A-Za-z%°µ/³*\s]{0,15}?"
    r",?\s*rang\w+\s+from\s+(?P<lo>-?\d[\d,]*\.?\d*)\s*[A-Za-z%°µ/³*\s]{0,10}?"
    r"\s+to\s+(?P<hi>-?\d[\d,]*\.?\d*)",
    re.IGNORECASE,
)

#: A table ROW's label cell: "Floor 3", "Room 2.01", "Zone 3", with or without a leading
#: markdown pipe. Matched once per LINE so every numeric cell on that line can be read --
#: the first measured run found the naive "first number only" version false-flagging the
#: exact BUG-1405 fix: its own table carries Mean/Lowest/Highest/Sensors columns, and a
#: Rooftop row's Lowest=7.2/Highest=71.0 legitimately substantiates a building-wide headline
#: that a Mean-only read would call unsupported.
_LABEL_CELL_RE = re.compile(r"^\s*\**\s*(?:Floor|Level|Room|Zone)s?\b", re.IGNORECASE)
_NUMERIC_CELL_RE = re.compile(r"^\**\s*(-?\d[\d,]*\.?\d*)\s*\**\s*$")
#: Fallback for a non-tabular row, e.g. "Room 2.01: 23.3" with no pipes at all.
_COLON_ROW_RE = re.compile(
    r"(?:Floor|Level|Room|Zone)s?\s*\w[\w.]*\s*[:–—-]+\s*\**\s*(-?\d[\d,]*\.?\d*)(?!\s*[.:]\d)",
    re.IGNORECASE,
)


def _to_float(s: str) -> float:
    return float(s.replace(",", ""))


def _table_values(text: str) -> List[float]:
    """Every numeric cell from every row whose first cell is a Floor/Level/Room/Zone label.
    Returns [] unless at least 3 such rows are found, matching a table a reader could
    actually check a headline against."""
    values: List[float] = []
    row_count = 0
    for line in text.splitlines():
        if "|" not in line:
            continue
        cells = [c.strip() for c in line.split("|") if c.strip() != ""]
        if not cells or not _LABEL_CELL_RE.match(cells[0]):
            continue
        row_count += 1
        for cell in cells[1:]:
            m = _NUMERIC_CELL_RE.match(cell)
            if m:
                values.append(_to_float(m.group(1)))
    if row_count < 3:
        colon_values = [_to_float(v) for v in _COLON_ROW_RE.findall(text)]
        return colon_values if len(colon_values) >= 3 else []
    return values


def range_contradiction(text: str) -> Optional[str]:
    """The headline sentence, when its OWN stated min/max lies outside every numeric cell of
    the table printed in the same answer -- BUG-1405's shape, the bare 'averaging N, ranging
    from A to B' phrasing. None when there is no such headline, no table with at least 3 rows
    to compare against, or the headline's range is consistent with the table."""
    if not text or not isinstance(text, str):
        return None
    m = _HEADLINE_AVG_RANGE_RE.search(text)
    if not m:
        return None
    rows = _table_values(text)
    if len(rows) < 3:
        return None
    table_lo, table_hi = min(rows), max(rows)
    lo, hi = _to_float(m.group("lo")), _to_float(m.group("hi"))
    # A small tolerance for rounding between the headline and the table's own figures.
    tol = max(0.5, 0.02 * max(abs(table_hi), abs(table_lo), 1.0))
    if lo < table_lo - tol or hi > table_hi + tol:
        start = text.rfind(".", 0, m.start()) + 1
        end = text.find(".", m.end())
        end = end + 1 if end != -1 else len(text)
        return text[start:end].strip()
    return None


def log_contradictions(logger, text: str) -> None:
    """Call from the response path. Logs at most one line per shape found; never raises,
    never touches ``text``."""
    try:
        c = compliance_contradiction(text)
        if c:
            logger.info(f"[narration-contradiction] compliance claim vs marker: {c[:200]!r}")
    except Exception:
        pass
    try:
        r = range_contradiction(text)
        if r:
            logger.info(f"[narration-contradiction] headline range vs table: {r[:200]!r}")
    except Exception:
        pass
