# -*- coding: utf-8 -*-
"""Developer tracker ids never reach the model's prompt, and never reach a reader.

Measured live 2026-09-18, unscripted: *"How busy is the building right now?"* was answered, in
full, with ``**BUG-606**``. The analytics narration prompt ends its rule 9 "...say which property
they do carry and stop (BUG-606)". The parenthetical is a developer's pointer to the fix that
introduced the rule. A model that meets a rule saying "and stop" followed by a token took the token
as the thing to say, and the reader received an internal ticket number as the answer.

The hazard is not one prompt. ~35 call sites build prompts as f-strings, source comments and
docstrings routinely cite the defect that motivated a rule, and a citation copied into a string
literal is invisible in review. So the remedy is at the two boundaries every string crosses:

* ``strip_tracker_ids`` at the model boundary (``LLMManager.generate`` and its siblings), so a
  provenance note in the source stays useful to the next developer and the model never sees it;
* ``strip_tracker_ids`` again in the final answer polish, so a tag that arrives by any other
  route — a document, a register field, a model recalling one — still cannot reach a reader.

Pure, dependency-free, and conservative on what it matches: only the tracker's own prefixes.
"""

from __future__ import annotations

import re

#: The prefixes ``tasks/FIX_TRACKER.csv`` uses. Record ids a building holds (AEP-001, REG-007,
#: CL-2026-006, WS-06, RTE-010, ACT-0042-2 ...) do not start with these, and the test that pins
#: this file walks every register id in the shipped TTL to prove it.
_ID = r"(?:BUG|CAVEAT|TODO|KNOWN|FIX)-\d{1,4}[A-Z]?"

#: "(BUG-606)", "(BUG-606, CAVEAT-12)", "(see BUG-606)" — a parenthesised citation, whole.
_PAREN = re.compile(
    r"[ \t]*\((?:[^()\n]{0,40}?\b)?" + _ID + r"(?:\s*[,;/&]\s*(?:" + _ID + r"))*[^()\n]{0,40}?\)"
)
#: A bare id, with the colon or comma a citation usually carries.
_BARE = re.compile(r"\b" + _ID + r"\b[:,]?")
_TAG_PRESENT = re.compile(r"\b" + _ID + r"\b")
_SPACES = re.compile(r"[ \t]{2,}")
_SPACE_BEFORE_PUNCT = re.compile(r"[ \t]+([.,;:!?])")
#: Emphasis left empty once its only content was a tag: "****", "** **", "__ __".
_EMPTY_EMPHASIS = re.compile(r"(\*\*|__)[ \t]*\1")
#: Where an answer's body ends and its footers ("You might also ask", "Sources") begin.
_FOOTER_SEPARATOR = re.compile(r"\n[ \t]*---[ \t]*(?:\n|$)")

#: What a reader gets when nothing but a tag would remain.
EMPTY_FALLBACK = (
    "I couldn't put a reliable answer together for that. Try naming a room, a floor or a "
    "period, and I'll answer from the building's own data."
)


def contains_tracker_id(text: object) -> bool:
    """True when ``text`` names a developer tracker id."""
    return bool(text) and bool(_TAG_PRESENT.search(str(text)))


def strip_tracker_ids(text: object) -> object:
    """Remove tracker ids and the citation punctuation around them.

    Non-strings and text with no id are returned unchanged (the same object), so this is safe on
    the hot path of every prompt. Never raises.
    """
    if not isinstance(text, str) or not _TAG_PRESENT.search(text):
        return text
    try:
        out = _PAREN.sub("", text)
        out = _BARE.sub("", out)
        out = _EMPTY_EMPHASIS.sub("", out)
        out = _SPACE_BEFORE_PUNCT.sub(r"\1", out)
        return _SPACES.sub(" ", out)
    except Exception:  # pragma: no cover - hygiene must never cost the call
        return text


def _body(text: str) -> str:
    """The answer proper: everything above the first footer separator."""
    return _FOOTER_SEPARATOR.split(text, maxsplit=1)[0]


def scrub_answer(text: str) -> str:
    """The reader-side pass: strip ids, and never hand back an answer that was only a tag.

    An answer whose body was nothing but ``**BUG-606**`` becomes the honest fallback, and its
    footers go with it: "You might also ask" and source chips under an answer that does not exist
    would present a ticket number as though it had been answered from the building's data.
    """
    if not contains_tracker_id(text):
        return text
    cleaned = str(strip_tracker_ids(text))
    # Markdown scaffolding is not an answer: judge the body, not the footers beneath it.
    if not re.sub(r"[^A-Za-z0-9]", "", _body(cleaned)):
        return EMPTY_FALLBACK
    return cleaned.strip()
