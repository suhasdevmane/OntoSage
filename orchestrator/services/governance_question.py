# -*- coding: utf-8 -*-
"""Questions ABOUT the assurance of the building's data, not about the building.

Live, tail H (2026-09-20). Each of these was answered from the wrong thing:

* "What asset and space information may be shown to this user role for this purpose without
  exposing restricted or personal detail?"  -> a census of the building's classes ("Room 234,
  Equipment 147 ...").
* "Which BMS points are physically verified against the assets and sensors they claim to
  represent?"                               -> the same census.
* "Can every reported value be traced back to the exact raw records, mappings, coefficients,
  parameters and code that produced it?"    -> "Found 3543 sensors (out of 3543 total)".
* "Do current layouts and aggregate demand indicate that a competent assessment of occupancy
  control, circulation or egress capacity is now required?" -> "Yes - the latest snapshot ...".
* "Before confirming the booking, which room features are currently verified against the
  requirements the person has chosen to state?" -> "0 room(s) with bookings right now".

None asks for a count, a list of what exists, or a reading. They ask about provenance, verification,
permission or a professional judgement. The honest answer comes from the documents, or is a plain
"I don't hold that": never a listing that happens to share a noun with the question.

Pure and building-agnostic: English only.
"""

from __future__ import annotations

import re

_GOVERNANCE_RE = re.compile(
    r"\btrace[ds]?\s+back\b|\btraceab\w+|\bprovenance\b|\blineage\b|\baudit\s+trail\b"
    r"|\bphysically\s+verified\b|\bverified\s+against\b|\bvalidated\s+against\b"
    r"|\bclaim(?:s|ed)?\s+to\s+(?:represent|measure|be)\b"
    r"|\bmay\s+be\s+shown\b|\bshown\s+to\s+(?:this|the|a)\s+(?:user|role)\b|\buser\s+role\b"
    r"|\bfor\s+this\s+purpose\b|\bwithout\s+exposing\b|\brestricted\s+or\s+personal\b"
    r"|\bcoefficients?\b|\braw\s+records\b"
    r"|\bcompetent\s+(?:assessment|person)\b"
    r"|\b(?:assessment|review|approval|sign-?off)\b[^?.!]{0,80}\b(?:is|are)\s+(?:now\s+)?"
    r"(?:required|needed|necessary|mandatory)\b",
    re.IGNORECASE,
)


def is_governance_question(question: str) -> bool:
    """True when the question is about provenance, verification, permission or a judgement."""
    return bool(_GOVERNANCE_RE.search(question or ""))
