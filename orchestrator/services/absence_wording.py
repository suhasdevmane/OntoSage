# -*- coding: utf-8 -*-
"""One honest sentence when the building's records do not hold what a question names (2D-16 wave 2).

Wave-1 development read, "Which rooms are swimming pools?" (metadata lane, semantic fallback):

    *I'm sorry, but the building model does not record which rooms are swimming pools. The 100 query
    results you received only list spaces (floors and rooms) ... you would need a field that
    explicitly marks a space as a pool ... Once that field is available, I can help you filter.*

while "Is there a swimming pool?" got the one-sentence referent decline. The reader asked the same
thing twice and was told two different things, one of which narrated the pipeline ("the results you
received") and told a non-administrator to add a field to a model they cannot edit.

This module supplies the ONE sentence both paths should say, and recognises the internal-prose
shape so the semantic fallback's text can be replaced by it. It decides nothing about whether the
subject exists: the referent gate and the absence router own that. It only words the decline, and it
words it as what was FOUND ("I found no swimming pool in this building's records"), never as a claim
about what the model lacks.
"""

from __future__ import annotations

import re
from typing import Any, List, Optional, Sequence

#: Prose that tells the reader what the SYSTEM received. Measured across the recorded runs in five
#: spellings -- "the 100 query results you received", "the ontology data you provided", "the sensor
#: data you provided", "the data you received", "the rows returned" -- so the noun phrase is matched
#: loosely (any two words before the noun) and the verb list carries both directions. The reader
#: never asked what the retrieval returned; saying so describes the pipeline, not the building.
_RESULTS_YOU_RECEIVED = re.compile(
    r"\b(?:the|this|these|those|our|its)?\s*(?:\d[\d,]*\s+)?"
    r"(?:[a-z]+\s+){0,2}?(?:results?|rows?|records?|items?|hits?|matches|data(?:set|base)?|entries|"
    r"bindings|triples?|snippets?|passages?|context|output)\s+"
    r"(?:that\s+)?(?:you(?:'ve|\s+have|\s+were)?\s+)?"
    r"(?:received|were\s+returned|returned|provided|gave|shared|supplied|retrieved|"
    r"were\s+retrieved|were\s+provided|fetched|pulled|listed\s+above|above)\b",
    re.IGNORECASE,
)

#: The query as the SUBJECT of the sentence ("the query returned 34 items", "the SPARQL query found
#: nothing about liens"). Measured 2026-09-20 (tail K): "do you have any liens or problems with the
#: city or town" was answered "34 items returned by the query are all related to building systems
#: (cooling capacity, sensor...)" on one run and a clean decline on the next — the same retrieval,
#: narrated once and not the other. A reader never asked what a query returned. The single-record
#: form is NOT here: `strip_store_addressing` rewrites "The query returned a single record" in place
#: so the record it introduces survives.
_THE_QUERY_RETURNED = re.compile(
    r"\bthe\s+(?:\w+\s+){0,2}?quer(?:y|ies)\s+(?:only\s+)?(?:returned|retrieved|yielded|produced|"
    r"found|gave|came\s+back)\b(?!\s+(?:a\s+single|one)\s+(?:record|row|result)\b)",
    re.IGNORECASE,
)

#: The WIDER phrases (wave 5, tail F): "the information returned only lists the building's
#: floors", "the records you queried", "the dataset only lists ...". They are real narration, but
#: the same words also open TRUE declines that the hand read called good ("The dataset only lists
#: sensors and their details" for a question about the building's age), so on their own they do
#: not change an answer. They act only when the building HOLDS a register that matches the
#: question (`false_absence_note`), which is what makes the absence false rather than true.
_INFORMATION_RETURNED = re.compile(
    r"\bthe\s+(?:\w+\s+){0,2}?information\s+(?:that\s+)?(?:you\s+)?"
    r"(?:returned|provided|received|retrieved|supplied|given|shown)\b",
    re.IGNORECASE,
)
_YOU_QUERIED = re.compile(
    r"\bthe\s+(?:\w+\s+){0,2}?(?:records?|data|results?|rows?|entries)\s+(?:that\s+)?"
    r"(?:you|we|i)(?:'ve|\s+have)?\s+(?:queried|searched|asked\s+for|requested|looked\s+at)\b",
    re.IGNORECASE,
)
#: The nouns are the retrieval's own words -- never "records", "rows" or "data", because "the
#: records only list two exceptions" is a fact about the building.
_ONLY_LISTS = re.compile(
    r"\b(?:the|this|that)\s+(?:\w+\s+){0,2}?(?:dataset|data\s*set|information|results?|"
    r"query\s+results?|output|context)\s+(?:returned\s+)?only\s+"
    r"(?:lists?|contains?|includes?|covers?|shows?|describes?|provides?|has)\b",
    re.IGNORECASE,
)

#: "in the query results", "in the returned data" -- the same fault as a prepositional tail. A bare
#: "in the dataset" is NOT here: report answers say "no anomalies were detected in the dataset"
#: and "across the entire data set" about the very readings they summarise, and the replay over the
#: recorded runs found three good answers those words would have altered.
_IN_THE_RETRIEVAL = re.compile(
    r"\b(?:in|from|within|among|across)\s+(?:this|the|these|those|our)\s+"
    r"(?:\d[\d,]*\s+)?(?:[a-z]+\s+){0,2}?"
    r"(?:query\s+results?|search\s+results?|results?\s+set|"
    r"retrieved\s+(?:rows?|records?|data|passages?)|returned\s+(?:rows?|records?|data)|"
    r"supplied\s+(?:data|records?)|provided\s+(?:data|records?|context))\b",
    re.IGNORECASE,
)

_WIDE_NARRATION = (_INFORMATION_RETURNED, _YOU_QUERIED, _ONLY_LISTS)


def describes_retrieval(text: str) -> bool:
    """True when the prose tells the reader what the system received, fetched or was given."""
    body = text or ""
    return bool(
        _RESULTS_YOU_RECEIVED.search(body)
        or _IN_THE_RETRIEVAL.search(body)
        or _THE_QUERY_RETURNED.search(body)
    )


def describes_retrieval_wide(text: str) -> bool:
    """`describes_retrieval`, plus the wider phrases that only a held register makes false."""
    body = text or ""
    return describes_retrieval(body) or any(rx.search(body) for rx in _WIDE_NARRATION)


#: An instruction to go and change or find data. Two families, both measured live: add a FIELD to
#: the model ("you would need a field that marks a space as a pool"), and go to ANOTHER SOURCE
#: ("you would need to look for a different data source that includes room type or function").
#: Neither is something the reader asked for, and neither is an action a non-administrator can take.
_ADD_A_FIELD = re.compile(
    r"\b(?:you\s+would\s+need|you'?d\s+need|would\s+need|need(?:s|ed)?|requires?|add(?:ing)?)\s+"
    r"(?:a|an|the)\s+(?:\w+\s+){0,4}?(?:field|attribute|property|column|flag|tag|classification)\b"
    r"|\bonce\s+that\s+(?:field|attribute|property)\b|\bI\s+can\s+help\s+you\s+filter\b"
    r"|\bthe\s+(?:field|attribute|column|property)\s+that\s+would\s+(?:hold|carry|record|store)\b"
    r"|\b(?:look|search|check|consult|refer|turn)\s+(?:for|in|to|at)\s+"
    r"(?:a|an|another|other|different|separate|external)\b[^.?!]{0,60}?"
    r"\b(?:source|dataset|data\s*set|system|database|records?|documentation|documents?)\b"
    r"|\b(?:a|an|another|other|different|separate|external)\s+data\s+source\b",
    re.IGNORECASE,
)

# ── stripping the narration, keeping the answer ──────────────────────────────────────────────

_SENTENCE_SPLIT = re.compile(r"(?<=[.!?])\s+(?=[A-Z0-9\"'(*_“])")
_BULLET = re.compile(r"^\s*(?:[-*•+]\s+|\d+[.)]\s+)")
_FOOTER = re.compile(r"\n\s*(?:---|\*\*You might also ask)", re.IGNORECASE)


def narrating_sentences(text: str) -> List[str]:
    """Every sentence or bullet of ``text`` that describes the retrieval or asks for a new field."""
    out: List[str] = []
    for line in (text or "").split("\n"):
        if not line.strip():
            continue
        parts = _SENTENCE_SPLIT.split(line) if not _BULLET.match(line) else [line]
        for part in parts:
            if part.strip() and (describes_retrieval(part) or _ADD_A_FIELD.search(part)):
                out.append(part)
    return out


def strip_retrieval_narration(text: str) -> str:
    """``text`` without the sentences that describe the retrieval; unchanged when there are none.

    Sentence-level, and line-level for a bullet, for the same reason ``strip_schema_remediation``
    is: the fault is a whole clause, and deleting its subject leaves prose that reads worse than
    the original. What is left may be an absence claim, which is a fact about the building and is
    the caller's business, not this function's.
    """
    body = text or ""
    if not describes_retrieval(body) and not _ADD_A_FIELD.search(body):
        return body
    kept_lines: List[str] = []
    for line in body.split("\n"):
        if _BULLET.match(line):
            if describes_retrieval(line) or _ADD_A_FIELD.search(line):
                continue
            kept_lines.append(line)
            continue
        parts = _SENTENCE_SPLIT.split(line)
        kept = [p for p in parts if not (describes_retrieval(p) or _ADD_A_FIELD.search(p))]
        if len(kept) != len(parts):
            line = " ".join(p for p in kept if p.strip())
            if not line.strip():
                continue
        kept_lines.append(line)
    return re.sub(r"\n{3,}", "\n\n", "\n".join(kept_lines)).strip("\n")


def _body_of(text: str) -> str:
    """The answer without its trailing suggestions / sources block."""
    m = _FOOTER.search(text or "")
    return (text or "")[: m.start()] if m else (text or "")


#: Below this many words, what is left after stripping is a fragment rather than an answer.
_MIN_REMAINING_WORDS = 8


#: The prose already says the building does not record something.
_SAYS_ABSENT = re.compile(
    r"\b(?:does\s+not|doesn'?t|do\s+not|don'?t|no)\s+(?:record|contain|include|hold|list|have|"
    r"store|indicate|classif)\w*",
    re.IGNORECASE,
)

#: A sentence whose whole content is "there is none". Wider than ``_SAYS_ABSENT`` because the
#: sentences left behind after the narration is stripped say it in the model's own ways -- "there
#: are no instances or properties that specify a filter size", "none of those records indicate".
_ABSENCE_SENTENCE = re.compile(
    r"(?:\bdoes\s+not|\bdoesn'?t|\bdo\s+not|\bdon'?t|\bis\s+not|\bare\s+not|\bisn'?t|\baren'?t|"
    r"\bthere\s+(?:is|are)\s+no\b|\bno\s+(?:instances?|properties|propert(?:y|ies)|records?|"
    r"information|data|entries|triples?|fields?|values?|such)\b|\bnone\s+of\b|\bnothing\b|"
    r"\bcannot\s+(?:confirm|say|tell|determine)\b|\bunable\s+to\b|\bi'?m\s+sorry\b|\bi\s+am\s+sorry\b)",
    re.IGNORECASE,
)

#: A heading or label carries no claim either way, so it never counts as substance.
_HEADING_ONLY = re.compile(r"^\s*(?:\*{0,2}|#{1,6}\s*)[\w ,'’-]{0,40}\*{0,2}\s*:?\s*$")


def _sentences(text: str) -> List[str]:
    """Sentences and non-empty lines of ``text``, for judging what it actually says."""
    out: List[str] = []
    for line in (text or "").split("\n"):
        if not line.strip():
            continue
        out.extend(p for p in _SENTENCE_SPLIT.split(line) if p.strip())
    return out


def says_only_that_there_is_none(text: str) -> bool:
    """True when every sentence of ``text`` is an absence claim, a heading or a bullet of neither.

    This is the test that decides whether an answer had any substance BESIDES the absence. One
    register listing eight waste streams and mentioning in passing that the rules are not recorded
    has substance; "the model does not record which rooms are swimming pools" has none.
    """
    sentences = _sentences(_body_of(text))
    if not sentences:
        return True
    for sentence in sentences:
        plain = re.sub(r"[*`_#]", "", sentence).strip()
        if not plain or _HEADING_ONLY.match(plain):
            continue
        if not _ABSENCE_SENTENCE.search(plain):
            return False
    return True


def is_internal_absence_prose(text: str) -> bool:
    """True for an absence narrated in the pipeline's terms or ending in an add-a-field instruction."""
    body = text or ""
    if not _SAYS_ABSENT.search(body):
        return False
    return describes_retrieval(body) or bool(_ADD_A_FIELD.search(body))


# ── the subject a question is asking about ───────────────────────────────────────────────────

_PLACE_WORD = r"(?:rooms?|spaces?|areas?|floors?|zones?|places?|parts?|locations?|spots?)"
_TAIL = r"(?P<s>[a-z][a-z' \-]{1,40}?)\s*[?.!]*\s*$"
_SUBJECT_PATTERNS = tuple(
    re.compile(p, re.IGNORECASE)
    for p in (
        rf"\bwhich\s+{_PLACE_WORD}\s+(?:are|is|have|has|contain|contains|include|includes)\s+"
        rf"(?:the\s+|a\s+|an\s+|any\s+)?{_TAIL}",
        rf"\bwhere\s+(?:are|is|can\s+i\s+find)\s+(?:the\s+|a\s+|an\s+|any\s+)?{_TAIL}",
        rf"\b(?:is|are)\s+there\s+(?:a|an|any)\s+{_TAIL}",
        rf"\bdoes\s+(?:the|this)\s+building\s+(?:have|contain|include)\s+(?:a|an|any)?\s*{_TAIL}",
        rf"\bhow\s+many\s+{_TAIL}",
        rf"\blist\s+(?:all\s+)?(?:the\s+)?{_TAIL}",
    )
)
_TRAILING_FRAME = re.compile(
    r"\s+(?:in|on|at|inside|within|of|for|here|there|now|today|tonight|currently|available|"
    r"this|last|next|right)\b.*$",
    re.IGNORECASE,
)


def _singular(phrase: str) -> str:
    words = phrase.split()
    if not words:
        return phrase
    last = words[-1]
    if len(last) > 3 and last.endswith("ies"):
        last = last[:-3] + "y"
    elif len(last) > 3 and last.endswith("s") and not last.endswith("ss"):
        last = last[:-1]
    return " ".join(words[:-1] + [last])


def subject_of(question: str) -> str:
    """The thing a question asks about ("swimming pool"), singular; '' when it cannot tell."""
    q = (question or "").strip()
    for pattern in _SUBJECT_PATTERNS:
        m = pattern.search(q)
        if not m:
            continue
        subject = _TRAILING_FRAME.sub("", m.group("s")).strip(" -'")
        if 1 <= len(subject.split()) <= 4:
            return _singular(subject.lower())
    return ""


def absence_sentence(subject: str, building: str = "this building") -> str:
    """The one sentence, worded exactly as the referent gate words it.

    "Is there a swimming pool?" and "Which rooms are swimming pools?" are the same question asked
    two ways, and a reader who asks both must not be told two different things. The referent gate
    already says *"'swimming pool' does not exist in this building, so there is nothing to report
    about it"* (`_orchestrator.apply_referent_gate`), and that is the sentence both paths now use.
    ``building`` is accepted so callers need not know that this wording does not spell it out.
    """
    if not subject:
        name = (building or "this building").strip()
        return f"I found nothing in {name}'s records that answers that."
    return f"'{subject}' does not exist in this building, so there is nothing to report about it."


#: How this system opens an honest decline. Matched on the FIRST sentence only: an answer that
#: mentions an absence in passing is not a decline.
_DECLINE_OPENER = re.compile(
    r"^\s*\**\s*(?:I\s+(?:could\s+not|couldn'?t|can'?t|cannot|don'?t|do\s+not)\b"
    r"|I\s+found\s+(?:no|nothing)\b|'[^']{2,60}'\s+does\s+not\s+exist\b"
    r"|[\w' ]{0,40}documents\s+do\s+not\s+answer\b|No\s*[—–-]+\s*[a-z]"
    # "You'll need to pull those from the facility-operations team." -- a decline that hands the
    # reader elsewhere (wave 9: the recommend lane then appended unrelated numbered advice).
    r"|You(?:'ll|\s+will|'d|\s+would)\s+need\s+to\b)",
    re.IGNORECASE,
)


#: "desk (120), focus room (8), collaboration area (5)" and markdown tables: a tally of kinds.
_COUNTED_ITEM = re.compile(r"[A-Za-z][\w \-]{1,30}\(\s*\d[\d,]*\s*\)")
_TABLE_ROW = re.compile(r"^\s*\|.*\|\s*$", re.MULTILINE)
_BULLET_COUNT = re.compile(r"^\s*[-*•]\s+.*?\b\d[\d,]*\b", re.MULTILINE)


def _is_count_listing(block: str) -> bool:
    """True when a block is a tally of kinds rather than a statement about the question."""
    body = block or ""
    return (
        len(_COUNTED_ITEM.findall(body)) >= 2
        or len(_TABLE_ROW.findall(body)) >= 2
        or len(_BULLET_COUNT.findall(body)) >= 3
    )


#: This system's OWN declines. They compose their pointer blocks deliberately ("The nearest things I
#: can answer are ...", "What IS measured there: ...", "Try, for example: ..."), so the stripper
#: below must leave them alone; replayed over the recorded runs it removed those blocks from 40
#: answers the hand read called good. It exists for a MODEL's decline followed by unrelated advice.
_SYSTEM_DECLINE = re.compile(
    r"^\s*\**\s*(?:I\s+did\s+not\s+find\b|I\s+couldn'?t\s+(?:answer|tie)\b|I\s+can'?t\s+answer\b|"
    r"I\s+found\s+nothing\b|I\s+don'?t\s+hold\b|No\b[^.\n]{0,60}\bnot\s+measured\b|"
    r"'[^']{2,60}'\s+does\s+not\s+exist\b|[\w' ]{0,40}documents\s+do\s+not\s+answer\b|"
    r"This\s+building\s+(?:doesn'?t|does\s+not)\s+keep\b)",
    re.IGNORECASE,
)


#: A block this system appends to a decline on purpose: what the building does keep, or how to ask.
_SYSTEM_POINTER = re.compile(
    r"\bdoes\s+keep\b[^\n]*\bwhich\s+I\s+can\s+read\b|nearest\s+things\s+I\s+can\s+answer|"
    r"\bTry,\s+for\s+example\b",
    re.IGNORECASE,
)


def opens_with_a_decline(text: str) -> bool:
    """True when the answer's first sentence is a decline."""
    first = next((s for s in _sentences(_body_of(text)) if s.strip()), "")
    return bool(_DECLINE_OPENER.match(first.replace("’", "'")))


def strip_unrelated_body_after_decline(text: str, question: str) -> str:
    """A decline is the whole answer: drop any block after it that is not about the question.

    Measured (wave 4): *"Can I get tips to improve sustainability in my workspace?"* declined and
    then listed workspace kinds and counts. A reader who has just been told there is no answer is
    then shown a table of something else, which reads as though it were the answer after all.

    Only blocks AFTER the opening decline are considered, and a block is kept whenever it shares
    any subject term with the question -- so a decline that goes on to name the nearest records, or
    to say what the building does hold, is untouched.
    """
    body = _body_of(text)
    if not opens_with_a_decline(body):
        return text
    first = next((s for s in _sentences(body) if s.strip()), "")
    if _SYSTEM_DECLINE.match(first.replace("’", "'")):
        return text
    from orchestrator.services.grounding_guard import content_terms
    from orchestrator.services.passage_relevance import question_topic_terms

    topic = question_topic_terms(question)
    if not topic:
        return text
    # A heading or numbered step starts a NEW block even without a blank line before it: the
    # recommend lane's "You'll need to pull those from ... ### 1. Use the CO2 sensor ..." is one
    # paragraph to a blank-line split, and the advice rode along with the decline.
    blocks = [
        b for b in re.split(r"\n\s*\n|\n(?=#{1,6}\s)|(?<=[.!?])\s+(?=#{2,6}\s)", body) if b.strip()
    ]
    if len(blocks) < 2:
        return text
    kept = [blocks[0]]
    dropped = 0
    for block in blocks[1:]:
        # A COUNT LISTING never continues a decline. "Can I get tips to improve sustainability in
        # my workspace?" was declined and then given "desk (120), focus room (8) ...": a tally of
        # entity kinds, which shares the word "workspace" with the question and answers none of
        # it. Term overlap alone keeps such a block, so the shape is tested as well.
        if _SYSTEM_POINTER.search(block):
            kept.append(block)  # a pointer this system composed on purpose
            continue
        if _is_count_listing(block) or not (topic & content_terms(block)):
            dropped += 1
            continue
        kept.append(block)
    if not dropped:
        return text
    tail = text[len(body) :]  # the sources / follow-up footer, kept as it was
    return ("\n\n".join(kept).strip() + tail).strip()


def _without_wide_narration(text: str) -> str:
    """``text`` minus every sentence that narrates the retrieval (wide phrases too) or asks for data.

    Typography is normalised first: a model writes "I'm sorry" with a RIGHT SINGLE QUOTATION MARK,
    and every pattern here is written with a straight apostrophe.
    """
    from orchestrator.services.grounding_guard import normalise_typography

    kept: List[str] = []
    for line in normalise_typography(_body_of(text)).splitlines():
        if not line.strip():
            continue
        parts = [line] if _BULLET.match(line) else _SENTENCE_SPLIT.split(line)
        for part in parts:
            if part.strip() and not (describes_retrieval_wide(part) or _ADD_A_FIELD.search(part)):
                kept.append(part)
    return "\n".join(kept)


def false_absence_note(
    text: str, question: str, records: Sequence[Any], building: str = "this building"
) -> Optional[str]:
    """A note that names the register the building HOLDS, in place of an absence about it.

    Wave 5, tail F: *"I'm sorry, but the information returned only lists the building's floors
    (e.g. 'Floor 0 ...'). It does not contain any records of authorised routes ..."* for a
    question whose answer sits in a circulation register the building keeps. Two things are wrong
    at once -- the sentence describes the retrieval, and its absence is FALSE -- and the second is
    the one that costs the reader: they are told the building holds nothing while it holds exactly
    that.

    Acts only when ALL of these hold, which is why it can be trusted with a good decline:

    * the prose narrates the retrieval (the wide phrases, which alone change nothing);
    * once the narration is removed, all that is left is an absence claim -- an answer with
      substance is never touched;
    * the building holds a register class the question matches (`held_record_class`).

    Returns None otherwise, so a TRUE decline ("The dataset only lists sensors and their details"
    for a question about the building's age, where no register matches) is left exactly as it was.
    """
    body = text or ""
    if not records or not describes_retrieval_wide(body):
        return None
    remaining = _without_wide_narration(body)
    if len(remaining.split()) >= _MIN_REMAINING_WORDS and not says_only_that_there_is_none(
        remaining
    ):
        return None
    try:
        from orchestrator.services.record_registry import held_record_class

        held = held_record_class(question or "", list(records))
    except Exception:  # a registry hiccup must never cost the reader the original answer
        return None
    name = (building or "this building").strip()
    if held is None or not getattr(held, "label", ""):
        # DELIBERATELY NO FUZZY FALLBACK. A first version named the one class whose LABEL shared a
        # word with the question when the registry named none, to reach "authorised route" (not a
        # lay term of the circulation register). Replayed over the recorded runs it altered a good
        # decline about sound separation, so a class is named only when the registry itself names
        # it; widening the registry's vocabulary is the fix for a missed match, not this function.
        return None
    label = str(held.label).strip().lower()
    return (
        f"**{name} keeps {label} records, and that is where this would be answered.** I could "
        f"not read the answer from them just now, so I would rather not say the building holds "
        f"nothing. Ask for the {label} records — naming a room, floor or date if you have one — "
        "and I will read them."
    )


#: How the STORE addresses a thing -- the reader never asked, and cannot use it. Measured live:
#: "the part after the last '#' in its URI", "a UUID that can be used to query its data", "The query
#: returned a single record", "Timeseries ID". A reader who asked about identifiers is exempt.
_STORE_ADDRESSING = re.compile(
    r"\bthe\s+(?:part|portion|text)\s+after\s+the\s+last\s+['\"`]?[#/]['\"`]?\s+in\s+"
    r"(?:its|the|their)\s+(?:URI|IRI|URL)\b"
    r"|\b(?:a|the|its|their)\s+(?:UUID|GUID)\b[^.?!\n]{0,60}?\b(?:query|look\s*up|fetch|retrieve|"
    r"read)\b"
    r"|\btime\s*-?series\s+(?:ID|identifier|reference)\b",
    re.IGNORECASE,
)
_QUERY_RETURNED_ONE = re.compile(
    r"\bthe\s+query\s+returned\s+(?:a\s+single|one)\s+(?:record|row|result)\b", re.IGNORECASE
)
_ASKS_ABOUT_IDENTIFIERS = re.compile(
    r"\b(?:uuids?|guids?|ids?|identifiers?|iris?|uris?|urls?|time\s*-?series|schema|"
    r"ontology|sparql|fields?|columns?|properties|attributes?|tables?)\b",
    re.IGNORECASE,
)

#: A snake_case FIELD name in bold or a code span: "(the **sensor_count** field)". The reader is
#: told what the answer holds in words; the store's column name is not one of them (wave 7).
_FIELD_NAME = r"[a-z][a-z0-9]*(?:_[a-z0-9]+)+"
_FIELD_PAREN = re.compile(
    rf"\s*\((?:the\s+)?[*`]{{1,2}}{_FIELD_NAME}[*`]{{1,2}}(?:\s+(?:field|column|property|attribute))?\)",
    re.IGNORECASE,
)
_FOOTNOTE_LINE = re.compile(r"^\s*[_*][^_*\s].*[_*]\s*$")
_FIELD_TOKEN = re.compile(rf"(?<![\w/])[*`]{{1,2}}({_FIELD_NAME})[*`]{{1,2}}(?![\w])")


def humanize_field_names(text: str) -> str:
    """``text`` with store field names in bold or code spans removed or spoken in words.

    "(the **sensor_count** field)" is deleted -- the sentence already says what it counts -- and a
    bare `sensor_count` becomes "sensor count". Table rows are left alone.
    """
    out: List[str] = []
    for line in (text or "").split("\n"):
        # A table row, and an italic footnote ("_Policy: `policy_inference_individual_presence`._"),
        # are labels the system attaches on purpose: they are not the narration's own prose.
        if line.lstrip().startswith("|") or _FOOTNOTE_LINE.match(line):
            out.append(line)
            continue
        line = _FIELD_PAREN.sub("", line)
        line = _FIELD_TOKEN.sub(lambda m: m.group(1).replace("_", " "), line)
        out.append(line)
    return "\n".join(out)


def strip_store_addressing(text: str, question: str = "") -> str:
    """``text`` without sentences that tell the reader how the store addresses its data.

    A sentence that carries a figure is never dropped (it may be the answer); "The query returned a
    single record" is reworded in place instead, so the record it introduces survives. A table row
    is left alone, and so is everything when the reader asked about identifiers.
    """
    body = text or ""
    if _ASKS_ABOUT_IDENTIFIERS.search(question or ""):
        return body
    body = humanize_field_names(body)
    if not (_STORE_ADDRESSING.search(body) or _QUERY_RETURNED_ONE.search(body)):
        return body
    body = _QUERY_RETURNED_ONE.sub("There is one record", body)
    lines: List[str] = []
    for line in body.split("\n"):
        if line.lstrip().startswith("|") or not _STORE_ADDRESSING.search(line):
            lines.append(line)
            continue
        if _BULLET.match(line):
            if re.search(r"\d", line):
                lines.append(line)
            continue
        parts = _SENTENCE_SPLIT.split(line)
        kept = [p for p in parts if not (_STORE_ADDRESSING.search(p) and not re.search(r"\d", p))]
        rebuilt = " ".join(p for p in kept if p.strip()) if len(kept) != len(parts) else line
        if rebuilt.strip():
            lines.append(rebuilt)
    out = re.sub(r"\n{3,}", "\n\n", "\n".join(lines)).strip("\n")
    return out if out.strip() else (text or "")


#: The store's own vocabulary, said to a reader as though it were the building's: "I did not find any
#: specific triple that states whether the shared meeting booth is currently available". A triple, a
#: SPARQL query and the knowledge graph are how this system holds facts; none is something the
#: reader can look for. Bare "graph" and "ontology" are NOT here -- a chart is a graph, and "the
#: ontology" is exactly what an administrator asks about.
_STORE_VOCABULARY = re.compile(
    r"\b(?:triples?|sparql|rdf|graphdb|turtle\s+file|knowledge\s+graph|"
    r"(?:in|from|within)\s+the\s+(?:building\s+)?(?:ontology|graph))\b",
    re.IGNORECASE,
)


#: A question about the assistant itself is answered in the system's own terms ("what can you do?").
_ASKS_ABOUT_THE_SYSTEM = re.compile(
    r"\b(?:you|your|yours|ontosage|the\s+system|this\s+system|assistant|capabilit\w+)\b",
    re.IGNORECASE,
)


def drop_store_vocabulary(text: str, question: str = "") -> str:
    """``text`` without sentences that speak in the store's terms; "" when nothing else was said.

    A sentence with a figure is kept (it may be the answer), and so is everything when the reader
    asked about the ontology, a field or an identifier.
    """
    body = text or ""
    if (
        _ASKS_ABOUT_IDENTIFIERS.search(question or "")
        or _ASKS_ABOUT_THE_SYSTEM.search(question or "")
        or not _STORE_VOCABULARY.search(body)
    ):
        return body
    lines: List[str] = []
    for line in body.split("\n"):
        if line.lstrip().startswith("|") or not _STORE_VOCABULARY.search(line):
            lines.append(line)
            continue
        parts = _sentences_of(line)
        kept = [p for p in parts if not (_STORE_VOCABULARY.search(p) and not re.search(r"\d", p))]
        rebuilt = " ".join(p for p in kept if p.strip())
        if rebuilt.strip():
            lines.append(rebuilt)
    return re.sub(r"\n{3,}", "\n\n", "\n".join(lines)).strip("\n")


# ── an answer never opens in the middle of a thought (wave 7) ────────────────────────────────

#: Openers that point back at a sentence the reader was never shown.
_ORPHAN_OPENER = re.compile(
    r"^[\s*_#>]*(?:they|these|those|it|all\s+of\s+(?:them|those|these)|"
    r"none\s+of\s+(?:them|those|these)|each\s+of\s+(?:them|those|these)|"
    r"both\s+of\s+(?:them|those|these))\b",
    re.IGNORECASE,
)
#: Openers no answer has any business starting with, removal or not.
_ALWAYS_ORPHAN = re.compile(
    r"^[\s*_#>]*(?:all\s+of\s+them|none\s+of\s+(?:those|them|these)|each\s+of\s+(?:them|those))\b",
    re.IGNORECASE,
)
_LOWERCASE_START = re.compile(r"^[\s*_#>]*[a-z]")
_STRUCTURAL_LINE = re.compile(r"^\s*(?:[-*•+]\s|\d+[.)]\s|\||#|>|---)")


_ABBREVIATION_END = re.compile(
    r"(?:\be\.g\.|\bi\.e\.|\betc\.|\bvs\.|\bapprox\.|\bno\.)$", re.IGNORECASE
)


def _sentences_of(line: str) -> List[str]:
    """Sentences of one line, without splitting after "e.g." or "i.e."."""
    out: List[str] = []
    for part in _SENTENCE_SPLIT.split(line):
        if out and _ABBREVIATION_END.search(out[-1].rstrip()):
            out[-1] = f"{out[-1]} {part}"
        else:
            out.append(part)
    return out


def _is_orphan(sentence: str, removed: bool) -> bool:
    if _ALWAYS_ORPHAN.match(sentence):
        return True
    return removed and bool(_ORPHAN_OPENER.match(sentence) or _LOWERCASE_START.match(sentence))


def mend_opening(
    text: str, original: str, question: str = "", building: str = "this building"
) -> str:
    """``text`` with any leading sentence that has lost its antecedent removed.

    THE ONE HELPER every hygiene pass that deletes prose calls at its end. A pass that removes a
    sentence can leave the next one first, and "They only record scheduled closure periods" or
    "None of those sensor entries contain information about ..." then opens an answer, pointing at
    something the reader was never shown. When ``text`` differs from ``original`` (something was
    removed), a first sentence that begins with a pronoun, a "None of those" / "All of them" /
    "Each of" phrase or a lower-case letter is dropped; if nothing of substance is left, the
    honest one-sentence decline stands in. A few openers ("None of those", "All of them") are
    orphans even when nothing was removed. Bullets, tables and headings are never touched.
    """
    body = text or ""
    removed = body != (original or "")
    footer_at = _FOOTER.search(body)
    head, foot = (body[: footer_at.start()], body[footer_at.start() :]) if footer_at else (body, "")
    lines = head.split("\n")
    changed = False
    while lines:
        line = lines[0]
        if not line.strip():
            if changed:
                lines.pop(0)
                continue
            break
        if _STRUCTURAL_LINE.match(line):
            break
        parts = _sentences_of(line)
        keep = 0
        while keep < len(parts) and _is_orphan(parts[keep], removed):
            keep += 1
        if keep == 0:
            break
        changed = True
        if keep < len(parts):
            lines[0] = " ".join(p for p in parts[keep:] if p.strip())
            break
        lines.pop(0)
    if not changed:
        return body
    rest = "\n".join(lines).strip()
    if len(rest.split()) < _MIN_REMAINING_WORDS:
        return absence_sentence(subject_of(question), building) + foot
    return rest + foot


def rewrite_semantic_absence(
    text: str, question: str, building: str = "this building"
) -> Optional[str]:
    """What to say instead of ``text``, or None when ``text`` narrates nothing.

    Two outcomes, and which one applies is decided by what SURVIVES the strip:

    * the answer was an absence NARRATED in the pipeline's terms -- nothing of substance is left
      once the narration goes -- so the whole thing becomes the one honest sentence;
    * the answer said something about the building AND narrated the retrieval in passing; then only
      the narration goes, because discarding a real answer over three words is the mistake BUG-550
      already paid for once.
    """
    original = text or ""
    # Sentences in the store's own terms ("no triple states ...") go first; when nothing else was
    # said, the whole answer becomes the one honest sentence.
    pruned = drop_store_vocabulary(original, question)
    if pruned != original:
        remaining = _body_of(pruned)
        if len(remaining.split()) < _MIN_REMAINING_WORDS or says_only_that_there_is_none(remaining):
            return absence_sentence(subject_of(question), building)
    text = strip_store_addressing(pruned, question)
    if not describes_retrieval(text) and not _ADD_A_FIELD.search(text or ""):
        text = mend_opening(text, original, question, building)
        return text if text != original else None
    stripped = strip_retrieval_narration(text)
    remaining = _body_of(stripped)
    if len(remaining.split()) >= _MIN_REMAINING_WORDS and not says_only_that_there_is_none(
        remaining
    ):
        stripped = mend_opening(stripped, original, question, building)
        return stripped if stripped != original else None
    return absence_sentence(subject_of(question), building)
