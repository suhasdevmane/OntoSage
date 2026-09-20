# -*- coding: utf-8 -*-
"""Is this text an ANSWER at all? The last line of defence before a reader sees it (2D-16 wave 3).

A hand read of 62 unscripted stakeholder questions on the final build found five answers that were
not answers. They came from five different lanes and share one shape -- something internal, or the
question's own words, emitted where an answer belongs:

* *"Has this reported spill already been attended...?"* -> **"Not met"**, in full. A verdict with no
  subject: not met by what, and attended or not?
* *"Where do declared assets accumulate behind a common fire, water, power ... dependency?"* ->
  **"continuity_provision_register"**. The register's FILE NAME, offered as the answer.
* *"are there any safety concern i should be aweare of"* -> *"A sensor that measures the difference
  of a quantity between any two points in the system"*. An ontology class comment.
* *"What are the top reasons for energy spikes? Suggest remedies."* -> *"No -- top reasons for
  energy is not measured in this building."* A why-question read as the name of a measurand.
* *"...Which official private-space or support option can staff confirm?"* -> *"'privacy to manage
  medication or another personal need', 'privacy to manage medication...' isn't something this
  building senses"* -- the question's own phrase, twice, as a sensor name.

Every rule below is PRECISION-FIRST and refuses to fire on anything that reads like prose about the
building: a rule that suppressed real answers would cost far more than these five. Each returns a
short reason, so a caller can log WHICH rule fired and a failing test can name it. Nothing here
knows any building's vocabulary.
"""

from __future__ import annotations

import re
from typing import List, Optional

from orchestrator.services.grounding_guard import content_terms, plain_prose

# What a reader sees, without the trailing sources / follow-up furniture every lane appends.
_FOOTER = re.compile(
    r"\n\s*(?:---|\*\*You might also ask|\*Sources?:|_Sources?:|\*Answered live|"
    r"\*From\b|\*These figures)",
    re.IGNORECASE,
)
_MEDIA = re.compile(r"!\[[^\]]*\]\([^)]*\)")
_LEADING_NOTE = re.compile(r"^_[^_\n]{20,400}_\s*", re.MULTILINE)


def body_of(text: str) -> str:
    """The part of an answer that is supposed to BE the answer."""
    body = _MEDIA.sub(" ", text or "")
    m = _FOOTER.search(body)
    if m:
        body = body[: m.start()]
    body = _LEADING_NOTE.sub("", body)
    return plain_prose(body).strip()


def _words(text: str) -> List[str]:
    return re.findall(r"[A-Za-z0-9][A-Za-z0-9'’\-]*", text or "")


# ── 1. a file, class or identifier name offered as the answer ────────────────────────────────

_IDENTIFIER = re.compile(
    r"^[A-Za-z][A-Za-z0-9]*(?:_[A-Za-z0-9]+)+$"  # snake_case_name
    r"|^[a-z][a-z0-9]*(?:[A-Z][a-z0-9]*)+$"  # camelCaseName
    r"|^[\w\-]+\.(?:md|ttl|csv|json|ya?ml|txt|pdf|sql|py)$"  # a file name
    r"|^[A-Za-z_][\w-]*:[A-Za-z_][\w-]*$"  # a prefixed IRI term
)


def is_bare_identifier(text: str) -> bool:
    """True when the whole answer is one machine name, like ``continuity_provision_register``."""
    body = body_of(text).strip().strip("`*_'\".,;: \n")
    if not body or "\n" in body:
        return False
    return bool(_IDENTIFIER.match(body))


# ── 2. a verdict with no subject ─────────────────────────────────────────────────────────────

#: Words that state a VERDICT rather than a fact. A whole answer made only of these says nothing
#: about what was judged.
_VERDICT = frozenset(
    {
        "met",
        "unmet",
        "compliant",
        "noncompliant",
        "pass",
        "passed",
        "fail",
        "failed",
        "ok",
        "okay",
        "yes",
        "no",
        "none",
        "open",
        "closed",
        "overdue",
        "due",
        "current",
        "unknown",
        "true",
        "false",
        "not",
        "n/a",
        "na",
        "nil",
    }
)
_MAX_VERDICT_WORDS = 3


def is_bare_verdict(text: str, question: str = "") -> bool:
    """True for an answer of at most three words, all verdict words, saying nothing of the subject.

    The question is consulted so that a short answer which at least NAMES what it is about is kept:
    "Not met" against "has the spill been attended?" shares nothing, and that is the defect.
    """
    body = body_of(text).strip(" .—-")
    words = _words(body)
    if not words or len(words) > _MAX_VERDICT_WORDS:
        return False
    if any(ch.isdigit() for ch in body):
        return False  # a figure is a fact, however short
    if not all(w.lower() in _VERDICT for w in words):
        return False
    return not (content_terms(body) & content_terms(question))


# ── 3. an ontology class comment offered as the answer ───────────────────────────────────────

#: How a Brick/ontology comment opens. A definition of a KIND of thing, not a statement about this
#: building: "A sensor that measures the difference of a quantity between any two points".
_CLASS_COMMENT = re.compile(
    r"^(?:an?|the)\s+(?:\w+\s+){0,3}?"
    r"(?:sensor|point|device|equipment|meter|actuator|setpoint|command|status|alarm|parameter|"
    r"location|space|zone|system|entity|collection|class|asset|element)\b"
    r"[^.]{0,120}?\b(?:that|which|used\s+to|representing|denoting|indicating|measuring)\b",
    re.IGNORECASE,
)
_MAX_CLASS_COMMENT_SENTENCES = 2


def is_class_definition(text: str, question: str = "") -> bool:
    """True when the answer defines a KIND of thing and says nothing the question asked about."""
    body = body_of(text)
    if not body or len(re.findall(r"[.!?]", body)) > _MAX_CLASS_COMMENT_SENTENCES:
        return False
    if not _CLASS_COMMENT.match(body.strip().lstrip("*_`")):
        return False
    shared = content_terms(body) & content_terms(question)
    return not shared


# ── 4. the question's own phrase, returned as the name of a measurand ────────────────────────

#: The lane saying a named quantity is not sensed here.
_NOT_SENSED = re.compile(
    r"\b(?:is\s?n[o']t|is\s+not|are\s+not|aren'?t|no)\s+(?:something|a\s+quantity)?\s*"
    r"(?:this\s+building|the\s+building|we)?\s*"
    r"(?:senses|sense|measured|measures|monitored|monitors|recorded|records|tracked)\b"
    r"|\bis\s+not\s+measured\s+in\s+this\s+building\b"
    r"|\bno\s+sensor\s+of\s+that\s+kind\b",
    re.IGNORECASE,
)

#: A question shape that asks for reasons, options or advice. None of these names a measurand, so
#: answering one with "that is not measured here" is answering a question nobody asked.
_NOT_A_MEASURAND_QUESTION = re.compile(
    r"\b(?:top\s+)?reasons?\b|\bwhy\b|\bcauses?\b|\bremed(?:y|ies)\b|\bsuggest\b|\brecommend\w*\b"
    r"|\bwhich\s+(?:official\s+)?(?:option|options|support|provision|arrangement|service)\w*\b"
    r"|\bwhat\s+(?:should|can|could)\s+(?:i|we|staff)\b|\bhow\s+(?:do|should|can)\s+(?:i|we)\b"
    r"|\bshould\s+i\s+be\s+aw\w*\b",
    re.IGNORECASE,
)

_MIN_ECHO_WORDS = 3


def _quoted_phrases(text: str) -> List[str]:
    """Phrases the answer puts in quotes, which is how a lane names the thing it looked for."""
    return [m.group(1).strip() for m in re.finditer(r"['‘“\"]([^'’”\"]{3,90})['’”\"]", text or "")]


def echoes_the_question_as_a_measurand(text: str, question: str) -> bool:
    """True when the answer hands back the question's own words as a quantity it does not sense."""
    body = body_of(text)
    if not body or not _NOT_SENSED.search(body):
        return False
    q_words = [w.lower() for w in _words(question)]
    if not q_words:
        return False
    # Either the lane quoted a phrase lifted from the question ...
    for phrase in _quoted_phrases(body):
        p_words = [w.lower() for w in _words(phrase)]
        if len(p_words) >= _MIN_ECHO_WORDS and " ".join(p_words) in " ".join(q_words):
            return True
    # ... or the question is one that names no measurand at all, and was answered as though it did.
    return bool(_NOT_A_MEASURAND_QUESTION.search(question))


# ── 5. the same phrase printed twice ─────────────────────────────────────────────────────────

#: A QUOTED phrase printed twice running, separated by nothing but punctuation:
#: *"'privacy to manage medication or another personal need', 'privacy to manage medication or
#: another personal need' isn't something this building senses"*.
#:
#: DELIBERATELY THIS NARROW. The first version compared word n-grams anywhere in the answer and
#: flagged four answers the hand read called GOOD: a floor-plan listing, a space table and two
#: register summaries all legitimately repeat a phrase across their rows. A rule that suppresses a
#: good answer costs more than the defect it removes, so it now matches only the rendering slip.
_REPEATED_QUOTE = re.compile(
    r"(['‘“\"])([^'’”\"]{6,90})['’”\"]\s*[,;:]?\s*" r"['‘“\"]\2['’”\"]",
    re.IGNORECASE,
)


def repeats_a_phrase(text: str) -> bool:
    """True when the answer prints the same QUOTED phrase twice running."""
    return bool(_REPEATED_QUOTE.search(body_of(text)))


# ── 6. record identifiers (and a status word) with nothing said about them ───────────────────
#
# Wave 5. Tail F: "GEN-01 / AEP-012" was the ENTIRE answer to "Which feeders or boards show
# sustained loading...?", and "RES-EV-2026-0909, Confirmed, RES-EV-2026-0909" the entire answer to
# "What incident identifier, command status and authoritative information source are confirmed?".
# Both are rows of a register with the sentence around them removed: a reader is handed a code and
# must guess what it is a code OF.

#: A record identifier: GEN-01, AEP-012, RES-EV-2026-0909, DR-001, CHK101. Upper-case letters, then
#: digits or further upper-case/digit groups; the non-breaking hyphen models emit is accepted.
_ID_TOKEN = re.compile(r"^(?:[A-Z]{1,6}(?:[-‑‐][A-Z0-9]{1,12}){1,4}|[A-Z]{2,6}\d{2,6})$")

#: A status word a register cell carries. Nothing else may appear beside the identifiers.
_STATE_WORDS = frozenset(
    {
        "confirmed",
        "unconfirmed",
        "active",
        "inactive",
        "open",
        "closed",
        "pending",
        "current",
        "overdue",
        "due",
        "defective",
        "unknown",
        "provisional",
        "cancelled",
        "approved",
        "withdrawn",
        "degraded",
        "met",
        "not",
        "yes",
        "no",
        "true",
        "false",
    }
)
_MAX_ID_LIST_WORDS = 15


def is_identifier_list(text: str) -> bool:
    """True when the whole answer is record identifiers, plus at most status words, and no sentence.

    Precision: every token must be an identifier or a status word; there must be at least two
    tokens and at least two identifiers OR an identifier and a status word. A single code is left
    alone, because "which door?" -> "DR-004" can be a complete (if terse) answer.
    """
    body = body_of(text)
    if not body:
        return False
    body = re.sub(r"[*_`|#>]", " ", body)
    body = re.sub(r"(?m)^\s*(?:[-•+]|\d+[.)])\s+", " ", body)
    tokens = [t for t in re.split(r"[\s,;]+", body) if t.strip(" .:")]
    tokens = [t.strip(" .:()[]") for t in tokens if t.strip(" .:()[]")]
    if not 2 <= len(tokens) <= _MAX_ID_LIST_WORDS:
        return False
    ids = [t for t in tokens if _ID_TOKEN.match(t)]
    states = [t for t in tokens if t.lower() in _STATE_WORDS]
    if len(ids) + len(states) != len(tokens) or not ids:
        return False
    return len(ids) >= 2 or bool(states)


# ── 7. ontology vocabulary offered as the answer ─────────────────────────────────────────────
#
# Tail F: an answer built from PROPERTY DEFINITIONS ("- Current Service Status - Property:
# `serviceStatus` (link to an `AssetStatus` record) - Definition: 'The reported operational state
# of a lift...'"), another that listed ontology CLASS NAMES as what the building offers ("Entrance
# - the building has a class for the main entrance; ContinuityProvision - a con..."), and a third
# that listed a register's FIELD DESCRIPTIONS ("Each entry lists: Location (e.g. ...), Note (a
# numeric value, e.g. 12, 24, 36) ..."). Each describes the SCHEMA the building's records are
# written in, not the records. None of them answers a question about the building.

#: The reader asked what a term MEANS, or about the schema itself; then a definition IS the answer.
_ASKS_ABOUT_SCHEMA = re.compile(
    r"\b(?:defin\w+|meaning\s+of|what\s+does\s+[^?]{1,60}\s+mean|propert(?:y|ies)|fields?|columns?|"
    r"attributes?|schema|ontology|vocabulary|glossary|structure|what\s+kinds?\s+of\s+(?:records?|data)"
    r"|what\s+(?:records?|data)\s+(?:do|does)\s+(?:you|it|the\s+building)\s+(?:hold|keep|have))\b",
    re.IGNORECASE,
)

_PROPERTY_LABEL = re.compile(r"(?im)^\W*(?:\*\*)?Property(?:\*\*)?\s*:")
_DEFINITION_LABEL = re.compile(r"(?im)^\W*(?:\*\*)?Definition(?:\*\*)?\s*:")
_LINK_TO_RECORD = re.compile(r"\(\s*link\s+to\s+an?\s+`?[A-Za-z]+`?\s+record\s*\)", re.IGNORECASE)
#: `serviceStatus`, `AssetStatus`: a back-ticked lowerCamel or PascalCase ontology term.
_BACKTICKED_TERM = re.compile(
    r"`(?:[a-z][a-z0-9]*(?:[A-Z][a-z0-9]+)+|[A-Z][a-z0-9]+(?:[A-Z][a-z0-9]+)+)`"
)
#: "Entrance – the building has a class for ...": a PascalCase class name, a dash, a gloss.
_CLASS_NAME_GLOSS = re.compile(r"\b[A-Z][a-z0-9]+(?:[A-Z][a-z0-9]+)+\s+[–—-]\s+\w")
_HAS_A_CLASS = re.compile(r"\b(?:has|have)\s+a\s+class\s+for\b|\ba\s+class\s+(?:for|that)\b", re.I)
_EACH_ENTRY_LISTS = re.compile(
    r"\bEach\s+(?:entry|record|row|item|line)\s+(?:lists|has|contains|carries|includes|records|"
    r"provides|gives)\b",
    re.IGNORECASE,
)
_EXAMPLE_MARK = re.compile(r"\be\.g\.\s*,?", re.IGNORECASE)


def describes_the_schema(text: str, question: str = "") -> Optional[str]:
    """Why ``text`` is a description of the record SCHEMA rather than an answer, or None."""
    body = body_of(text)
    if not body or _ASKS_ABOUT_SCHEMA.search(question or ""):
        return None
    props = len(_PROPERTY_LABEL.findall(body))
    defs = len(_DEFINITION_LABEL.findall(body))
    if props >= 1 and defs >= 1:
        return "a list of ontology property definitions"
    if len(_BACKTICKED_TERM.findall(body)) >= 2 or _LINK_TO_RECORD.search(body):
        return "ontology terms offered as the answer"
    if len(_CLASS_NAME_GLOSS.findall(body)) >= 2 or (
        _HAS_A_CLASS.search(body) and _CLASS_NAME_GLOSS.search(body)
    ):
        return "ontology class names offered as what the building holds"
    if _EACH_ENTRY_LISTS.search(body) and len(_EXAMPLE_MARK.findall(body)) >= 2:
        return "a list of field descriptions, not the records"
    if _DEFINES_A_CLASS.search(body):
        return "an ontology class definition offered as the answer"
    return None


#: "the building's records define the *Entrance* class as 'the location and space of a building...'"
#: -- the model's own account of what the ontology says a class IS, offered to a safety question.
_DEFINES_A_CLASS = re.compile(
    r"\b(?:[Dd]efines?|[Dd]efined)\s+(?:the\s+)?\W{0,3}[A-Z][A-Za-z]+\W{0,3}\s+class\b"
    r"|\bthe\s+\W{0,3}[A-Z][A-Za-z]+\W{0,3}\s+class\s+as\b"
)

#: The SQL lane's own empty-result string, as a whole answer.
_BARE_NO_DATA = re.compile(
    r"^\W*no\s+(?:data|results?|records?|rows?)\s+(?:were\s+)?(?:found|returned|available)"
    r"(?:\s+for\s+(?:your|this|the)\s+(?:query|request|question|search))?\W*$",
    re.IGNORECASE,
)


def is_bare_no_data(text: str) -> bool:
    """True when the whole answer is "No data found for your query.": it names nothing that was asked."""
    return bool(_BARE_NO_DATA.match(body_of(text).strip()))


# ── 8. the system's own suppression messages, which a reader cannot act on ───────────────────

#: Wording numeric_guard and the deliberation lane used before wave 5. Both now say plainly which
#: figure could not be checked; this stays as the backstop for any lane still emitting the old text.
_LEGACY_SUPPRESSION = re.compile(
    r"narration\s+failed\s+the\s+evidence\s+check|structured\s+result\s+is\s+still\s+available",
    re.IGNORECASE,
)


# ── the verdict ──────────────────────────────────────────────────────────────────────────────

#: An answer at least this long is prose, and none of the rules above is trusted against it: every
#: measured defect was a fragment. Counted on the body, after the footer is removed.
_PROSE_WORDS = 60


def non_answer_reason(text: str, question: str = "") -> Optional[str]:
    """Why this text is not an answer, or None. Precision-first; prose is always left alone."""
    body = body_of(text)
    if not body.strip():
        return None
    if is_bare_identifier(text):
        return "only a file or class name"
    if is_identifier_list(text):
        return "only record identifiers, with nothing said about them"
    if is_bare_verdict(text, question):
        return "only a verdict, with no subject"
    if is_bare_no_data(text):
        return "an empty-result message that names nothing the reader asked about"
    if is_class_definition(text, question):
        return "a definition of a kind of thing, not an answer about this building"
    if repeats_a_phrase(text):
        return "the same phrase printed twice"
    # These three are STRUCTURAL markers (a `Property:` label, back-ticked ontology terms, "Each
    # entry lists ... e.g. ... e.g."), so unlike the fragment rules they are checked on long text
    # too: the schema descriptions they catch run to a paragraph or more.
    if _LEGACY_SUPPRESSION.search(body):
        return "an internal suppression message a reader cannot act on"
    schema = describes_the_schema(text, question)
    if schema:
        return schema
    if len(_words(body)) > _PROSE_WORDS:
        return None
    if echoes_the_question_as_a_measurand(text, question):
        return "the question's own words treated as a measurand"
    return None


def narrates_the_retrieval_only(text: str) -> bool:
    """True when the answer says nothing BUT what the retrieval returned and that nothing was found.

    The backstop for `absence_wording`'s strip pass: by the time text reaches the response node's
    shape guard the narration has normally been removed or replaced, so this fires only on a lane
    that emitted it AFTER that pass. Kept out of `non_answer_reason` on purpose: an answer with
    substance and a narrated aside is trimmed, not discarded, and only the absence-only case is
    a non-answer.
    """
    from orchestrator.services.absence_wording import (
        describes_retrieval,
        says_only_that_there_is_none,
    )

    body = body_of(text)
    return bool(body) and describes_retrieval(body) and says_only_that_there_is_none(body)


def is_non_answer(text: str, question: str = "") -> bool:
    """True when ``text`` is one of the shapes a reader cannot use."""
    return non_answer_reason(text, question) is not None
