# -*- coding: utf-8 -*-
"""A code plus one word is not evidence of health.

Live, tail K (2026-09-20). *"Which approved emergency communication channels and fixed points have
current end-to-end health evidence?"* was answered "CF-12 ... (Ready), CF-14 ..." -- rows of a
readiness column. "Ready" says a channel is designated ready for use; it is not a test result, and
"end-to-end health evidence" asks for one. Presented plainly, the rows read as the evidence.

The rule is narrow and asymmetric: a document answer that is nothing but coded rows each ending in
a one-word status is declined ONLY when the question asks for evidence, verification or health. A
question that asks for the status itself ("which channels are ready?") is answered by those rows.

Pure and building-agnostic.
"""

from __future__ import annotations

import re
from typing import Optional

_CODED_ROW_RE = re.compile(
    r"^\W*[A-Za-z]{1,5}-\d{1,4}\b[^\n]{0,80}?\(?\b(?:ready|open|closed|active|inactive|yes|no|ok|"
    r"available|unavailable|pass|fail|current|planned)\b\)?\W*$",
    re.IGNORECASE | re.MULTILINE,
)

_ASKS_EVIDENCE_RE = re.compile(
    r"\b(?:evidence|evidenced|verif\w+|health|healthy|tested|test\s+result|proven|proof|assur\w+|"
    r"end-to-end|validated|commission\w*|certified)\b",
    re.IGNORECASE,
)

_ASKS_STATUS_RE = re.compile(r"\b(?:status|which\s+\w+\s+are\s+(?:ready|open|active))\b", re.IGNORECASE)


def _substance(text: str) -> str:
    """The answer body without headings, sources and rules."""
    lines = []
    for ln in (text or "").splitlines():
        s = ln.strip()
        if not s or s.startswith(("#", "*Source", "---", "**From")):
            continue
        lines.append(s)
    return "\n".join(lines)


def is_terse_status_overclaim(question: str, answer: str) -> bool:
    """True when coded status rows are being offered as the evidence a question asked for."""
    if not _ASKS_EVIDENCE_RE.search(question or "") or _ASKS_STATUS_RE.search(question or ""):
        return False
    body = _substance(answer)
    rows = _CODED_ROW_RE.findall(body)
    if len(rows) < 2:
        return False
    # nearly everything in the body is a coded row: there is no prose, no date, no test
    total = [ln for ln in body.splitlines() if len(ln) > 3]
    return len(rows) >= max(2, int(0.6 * len(total)))


def decline_text(building_name: str) -> str:
    """What to say instead of the rows."""
    return (
        f"**{building_name} records a status for these items, not evidence that they work.** What I "
        "hold is a readiness column (for example *Ready*), which says an item is designated for use; "
        "it is not a test result, and I have no end-to-end health or test record for them. Ask "
        "*which of them are marked ready?* for the status itself, or ask for the test or inspection "
        "records by name."
    )


def apply(question: str, answer: str, building_name: str = "this building") -> Optional[str]:
    """The replacement text, or None when the answer stands."""
    return decline_text(building_name) if is_terse_status_overclaim(question, answer) else None
