# -*- coding: utf-8 -*-
"""
pii_redaction.py — deterministic PII redaction for stored free text (V5-T40).

Fault reports and complaints are typed by PEOPLE and end up in the
``user_reports`` table, readable by admins and joinable to anomaly episodes
(T19). Occupants routinely type their own or colleagues' emails, phone
numbers and names into a fault description — none of which the ticket needs.
This module strips the identifying carriers BEFORE the row is written, so the
database never holds them (redaction at write time, not display time).

Deterministic regex only — no LLM, no network. Redaction markers keep the
text readable ("contact [email redacted] about the leak"). The reporter's
ACCOUNT id is kept on the row (that is authentication, not incidental PII).

Building-agnostic: patterns are generic carriers (email/phone/self-intro),
never names of real people or places.
"""

from __future__ import annotations

import re
from typing import Dict, Tuple

_EMAIL_RE = re.compile(r"[a-zA-Z0-9._%+-]+@[a-zA-Z0-9.-]+\.[a-zA-Z]{2,}")

# international-ish phone carriers: +44 7911 123456 / 029 2087 4000 / 07911-123456
_PHONE_RE = re.compile(
    r"(?<![\w./-])(?:\+?\d{1,3}[\s-]?)?(?:\(?\d{2,5}\)?[\s-]?)\d{3,4}[\s-]?\d{3,4}(?![\w-])"
)

# self-introductions and third-party naming: "my name is X", "call me X",
# "this is John Smith", "ask for Priya"
_NAME_INTRO_RE = re.compile(
    # intro words match case-insensitively ("I'm", "My name is"); the NAME
    # itself stays strictly Capitalized so ordinary words never redact
    r"\b(?i:my name(?:'s| is)|i am|i'm|this is|call me|ask for|contact|reach)\s+"
    r"((?:[A-Z][a-z]{1,20})(?:\s+[A-Z][a-z]{1,20}){0,2})\b"
)

#: words the name-intro pattern must never treat as a name (sentence starters)
_NAME_STOPWORDS = {
    "the",
    "a",
    "an",
    "not",
    "very",
    "so",
    "here",
    "there",
    "on",
    "in",
    "at",
    "room",
    "office",
    "floor",
    "building",
    "facilities",
    "maintenance",
    "it",
    "urgent",
    "broken",
    "again",
    "still",
    "cold",
    "hot",
    "monday",
    "tuesday",
    "wednesday",
    "thursday",
    "friday",
    "saturday",
    "sunday",
}


def redact_pii(text: str) -> Tuple[str, Dict[str, int]]:
    """Redact identifying carriers; returns (clean_text, counts)."""
    if not text:
        return text, {}
    counts: Dict[str, int] = {}

    def _sub(pattern: re.Pattern, marker: str, label: str, s: str) -> str:
        n = len(pattern.findall(s))
        if n:
            counts[label] = counts.get(label, 0) + n
            s = pattern.sub(marker, s)
        return s

    out = _sub(_EMAIL_RE, "[email redacted]", "emails", text)

    # phones — but never eat room/zone ids like "3.01" or "RM125" (the phone
    # pattern needs >=7 digits total, room ids never have that many)
    def _phone_sub(m: re.Match) -> str:
        digits = re.sub(r"\D", "", m.group(0))
        if len(digits) < 7:
            return m.group(0)
        counts["phones"] = counts.get("phones", 0) + 1
        return "[phone redacted]"

    out = _PHONE_RE.sub(_phone_sub, out)

    def _name_sub(m: re.Match) -> str:
        candidate = m.group(1)
        if candidate.split()[0].lower() in _NAME_STOPWORDS:
            return m.group(0)
        counts["names"] = counts.get("names", 0) + 1
        return m.group(0).replace(candidate, "[name redacted]")

    out = _NAME_INTRO_RE.sub(_name_sub, out)
    return out, counts
