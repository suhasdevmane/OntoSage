# -*- coding: utf-8 -*-
"""Answer the measured part, and say which qualifier the records could not honour.

The failure this prevents (live hand read, 2026-09-19). *"Which commissioned CO2-monitored zones
show sustained elevated CO2 during an approved occupied period?"* was refused outright — "that
covers all 280 CO2 sensors at once". The refusal is about breadth, but the real trouble is narrower
and more interesting: the question carries three GOVERNANCE qualifiers — *commissioned*, *approved*,
*during an approved period* — and no series carries any of them. A reading knows its value and its
time; it does not know whether the zone was commissioned or the period sanctioned.

Two wrong answers were available and both were taken at some point: refuse everything (the reader
learns nothing, though the exceedance is computable), or answer as though the qualifier had been
applied (a governance claim nothing supports — the worse of the two). The third way is to answer
the measured part and say, in one sentence, which words were not honoured.

What counts as a governance qualifier: a word about AUTHORISATION or STATUS that no measurement
carries. "Occupied" is deliberately absent — occupancy is measured here, so a lane can honour it —
and so is every word naming a quantity, a place or a time.

Pure and building-agnostic: English only, no building, register or field names.
"""

from __future__ import annotations

import re
from typing import List, Sequence

#: Each entry: a pattern, and how to say what is missing. The phrasing names the RECORD that would
#: have to exist ("which zones are commissioned"), never a field name.
_QUALIFIERS: Sequence[tuple] = (
    (re.compile(r"\bcommissioned?\b|\bcommissioning\b", re.I), "which of them are commissioned"),
    (
        re.compile(r"\bapproved\b|\bauthoris(?:ed|ation)\b|\bauthoriz(?:ed|ation)\b|\bsanctioned\b",
                   re.I),
        "which periods or zones were approved",
    ),
    (re.compile(r"\bcertified\b|\baccredited\b", re.I), "which of them are certified"),
    (re.compile(r"\bverified\b|\bvalidated\b", re.I), "which readings have been verified"),
    (re.compile(r"\bin\s+scope\b|\bin-scope\b", re.I), "which of them are in scope"),
    (re.compile(r"\bpermitted\b|\blicen[sc]ed\b", re.I), "which of them are permitted"),
    (re.compile(r"\bagreed\b|\bcontracted\b", re.I), "what was agreed"),
    (re.compile(r"\bdesignated\b|\bnominated\b", re.I), "which of them are designated"),
)

#: A question that ASKS ABOUT the governance itself is not a measurement with a qualifier on it:
#: "which changes lack an approved record?" wants the approvals, and a register answers it.
_ABOUT_THE_GOVERNANCE_RE = re.compile(
    r"\blacks?\b|\bmissing\b|\bwithout\s+(?:an?\s+)?(?:approval|approved|authoris|certificat)"
    r"|\bwho\s+(?:approved|authoris|signed)\b|\bapproval\s+(?:record|evidence|status)\b"
    r"|\bevidence\s+of\s+(?:approval|commissioning)\b",
    re.IGNORECASE,
)


def unhonoured(question: str) -> List[str]:
    """The governance qualifiers a measurement lane cannot honour, as phrases for a sentence.

    Empty when the question carries none, and empty when the question is ABOUT the governance
    rather than about a measurement — that one belongs to a register, not to a caveat.
    """
    q = question or ""
    if not q.strip() or _ABOUT_THE_GOVERNANCE_RE.search(q):
        return []
    found: List[str] = []
    for pattern, phrase in _QUALIFIERS:
        if pattern.search(q) and phrase not in found:
            found.append(phrase)
    return found


def _join(items: Sequence[str]) -> str:
    items = list(items)
    if len(items) <= 1:
        return "".join(items)
    return ", ".join(items[:-1]) + " or " + items[-1]


def caveat(question: str, what_was_done: str = "") -> str:
    """One sentence naming the qualifiers not honoured, or "" when there are none.

    ``what_was_done`` is the lane's own description of the answer it DID give ("every zone with
    readings in the window"). Stating it matters: a caveat that says only what is missing leaves
    the reader unsure what the figures above them cover.
    """
    missing = unhonoured(question)
    if not missing:
        return ""
    tail = f" so this covers {what_was_done}." if what_was_done else "."
    return f"_The records do not say {_join(missing)},{tail}_"
