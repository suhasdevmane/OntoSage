# -*- coding: utf-8 -*-
"""Last-pass wording fixes applied to every answer before it reaches the reader.

Two deterministic rewrites, both pure (no I/O) so they are pinned by unit tests:

**BUG-679 — the building's data is not the user's.** The answering model is handed retrieved
records inside its prompt and narrates them as though the reader had supplied them: "The ontology
data you provided does not contain …", "The handover records you provided do **not** contain …",
"The records you have show that …". The user provided nothing; the building did. A prompt line
already forbids this and the phrasing still reached 7+ recorded answers, so it is fixed at the
output as well — a rule an LLM may ignore is a rule that needs a backstop.

**BUG-699 — no provenance flags in user-visible text.** Standing owner rule: an answer never says
``simulated: true``. The readings are placeholders to be replaced by real data, and a flag lifted
from a record's front-matter ("Environment: simulated: true") tells the reader nothing they can
act on. Only the TEXT is cleaned; the ``ontosage:isSimulated`` triples and the code that reads
them are untouched (tests/test_provenance_honesty.py relies on them).

Neither rewrite touches fenced or inline code. Neither contains a building literal.

**BUG-832 / CAVEAT-833 — the prose around a correct figure.** After both rewrites,
``narration_validators`` removes advice nobody asked for, norms with no source, a count that
contradicts its own list, a max-minus-min presented as a delta, and advice that moves a value the
wrong way. Same contract: pure, never raises, leaves every other byte of the answer alone.
"""

from __future__ import annotations

import re
from typing import Callable, List, Match, Optional, Pattern, Tuple

__all__ = ["attribute_to_building", "strip_provenance_flags", "polish_answer"]

# ── BUG-679 ──────────────────────────────────────────────────────────────────

_WORD = r"[^\W\d_][\w\-‐‑]*"
# NOT "information": no measured occurrence used it, and "the information you provided has been
# logged" is a true sentence in a report confirmation.
_NOUN = r"data|records|results|readings"
# "that were provided" appeared in run 4 — the same misattribution in the passive, which the
# "you ..." form did not cover.
_SUPPLIED = r"(?:you(?:'ve|’ve|\s+have)?|that\s+(?:were|was))\s+(?:provided|supplied|shared)"

#: "the [building] [ontology] <noun> you provided" — the determiner is required, so the rewrite
#: can put "the building's" in its place without producing "nine the building's records".
_THE_SUPPLIED_RE = re.compile(
    rf"\b(?P<the>the)\s+(?P<mod>(?:{_WORD}\s+){{0,2}}?)(?P<noun>{_NOUN})\s+{_SUPPLIED}\b",
    re.IGNORECASE,
)
#: "the records you have show …" — only with a reporting verb after it, so an ordinary "the
#: records you have access to" is not read as the same phrase.
#: Measured in run 3: "The records you have do not contain any information about …" — the same
#: misattribution with a NEGATED verb, which the reporting-verb list did not cover. Verbs are
#: still required (an ordinary "the records you have access to" must not match), and the
#: optional negation is what run 3 added.
_THE_YOU_HAVE_RE = re.compile(
    rf"\b(?P<the>the)\s+(?P<mod>(?:{_WORD}\s+){{0,2}}?)(?P<noun>records|data)\s+you\s+have\s+"
    r"(?=(?:do\s+not\s+|does\s+not\s+|don't\s+|doesn't\s+)?"
    r"(?:show|shows|indicate|indicates|list|lists|contain|contains|describe|describes)\b)",
    re.IGNORECASE,
)

#: THE READER DOES NOT KNOW WHAT AN ONTOLOGY IS (BUG-763). Six answers in run 3 said things
#: like "No records of scheduled inspections are present in the ontology" and "The ontology
#: only defines:". It is the project's word for the building's model of itself, and to a
#: facility manager it reads as a system component that failed. The phrase is replaced, never
#: deleted: what follows it is usually true and worth keeping.
#: Run 4 leaked three shapes the first pattern missed: "the building's ontology data", "the
#: current ontology" and "the building's ontology". A determiner is still required, so
#: "we model the building with an ontology" — a sentence genuinely about the modelling — stands.
_ONTOLOGY_NOUN_RE = re.compile(
    r"\b(?P<det>the|this|our|its)\s+(?:building[’']s\s+)?(?:current\s+)?(?:building\s+)?"
    r"ontology(?:\s+data)?\b",
    re.IGNORECASE,
)
#: No determiner ("all nine handover records you provided"): drop the clause, keep the rest.
_BARE_SUPPLIED_RE = re.compile(rf"\b(?P<noun>{_NOUN})\s+{_SUPPLIED}\b", re.IGNORECASE)

#: Singular verb -> plural, for "the ontology data … does" becoming "the building's records do".
_PLURAL_VERB = {
    "does": "do",
    "doesn't": "don't",
    "doesn’t": "don’t",
    "has": "have",
    "hasn't": "haven't",
    "is": "are",
    "isn't": "aren't",
    "was": "were",
    "wasn't": "weren't",
    "contains": "contain",
    "includes": "include",
    "shows": "show",
    "lists": "list",
    "describes": "describe",
    "mentions": "mention",
    "holds": "hold",
    "covers": "cover",
    "indicates": "indicate",
}
_VERB_AFTER_RE = re.compile(
    r"^(?P<sp>\s+)(?P<adv>(?:only|also|still|not)\s+)?(?P<verb>"
    + "|".join(re.escape(v) for v in sorted(_PLURAL_VERB, key=len, reverse=True))
    + r")\b",
    re.IGNORECASE,
)


def _cased(word: str, like: str) -> str:
    """``word`` with the capitalisation of ``like``'s first letter."""
    return word[:1].upper() + word[1:] if like[:1].isupper() else word


def _building_phrase(m: Match[str]) -> Tuple[str, bool]:
    """The replacement for a matched phrase, and whether it turned singular data plural."""
    mod = re.sub(r"(?i)^building\s+", "", m.group("mod") or "")
    noun = m.group("noun")
    became_plural = False
    # "the [building] ontology data you provided" -> "the building's records": "ontology" is how
    # the facts are stored, not what a reader would call them.
    if re.fullmatch(r"(?i)ontology\s+", mod) and noun.lower() == "data":
        mod, noun, became_plural = "", "records", True
    return f"{_cased('the', m.group('the'))} building's {mod}{noun}", became_plural


def _rewrite_prose(text: str) -> str:
    """Apply the BUG-679 rewrites to prose that holds no code."""

    def _sub(pattern: Pattern[str], s: str) -> str:
        out: List[str] = []
        pos = 0
        for m in pattern.finditer(s):
            out.append(s[pos : m.start()])
            phrase, plural = _building_phrase(m)
            out.append(phrase)
            pos = m.end()
            if pattern is _THE_YOU_HAVE_RE:
                out.append(" ")  # the match consumed the space before the verb
            if plural:
                vm = _VERB_AFTER_RE.match(s[pos:])
                if vm:
                    verb = vm.group("verb")
                    plural_verb = _PLURAL_VERB[verb.lower()]
                    out.append(vm.group("sp") + (vm.group("adv") or "") + _cased(plural_verb, verb))
                    pos += vm.end()
        out.append(s[pos:])
        return "".join(out)

    text = _sub(_THE_SUPPLIED_RE, text)
    text = _sub(_THE_YOU_HAVE_RE, text)
    text = _BARE_SUPPLIED_RE.sub(lambda m: m.group("noun"), text)
    # "the building model" and not "the building's records": it is SINGULAR, so the verb that
    # follows still agrees ("the ontology only defines" -> "the building model only defines"),
    # and it does not produce "no records ... in the building's records".
    text = _ONTOLOGY_NOUN_RE.sub(lambda m: f"{_cased('the', m.group('det'))} building model", text)
    # Measured live: "The building's records (the ontology data you provided) contain …" became
    # "The building's records (the building's records) contain …". A parenthetical that only
    # repeats the building attribution adds nothing once the rewrite has run.
    return _REDUNDANT_ATTRIBUTION_RE.sub(r"\g<head>", text)


#: "<… building's …> (the building's …)" — the bracket restates what precedes it.
_REDUNDANT_ATTRIBUTION_RE = re.compile(
    r"(?P<head>\bbuilding[’']s\s+[^\s()]+(?:\s+[^\s()]+){0,2})\s*\(\s*the\s+building[’']s\s+[^()]{0,60}\)",
    re.IGNORECASE,
)


# ── BUG-699 ──────────────────────────────────────────────────────────────────

_FLAG = r"\**`?(?:is[_ ]?simulated|simulated)`?\**\s*(?:[:=]|\bis\b)\s*\**`?(?:true|false)`?\**"
#: A whole line whose content is a flag, optionally behind a bullet and a short label
#: ("- Environment: simulated: true").
_FLAG_LINE_RE = re.compile(
    rf"^\s*(?:[-*•+]\s+|\d+[.)]\s+)?(?:\**[\w .\-]{{1,40}}\**\s*:\s*)?{_FLAG}\s*[.;,]?\s*$",
    re.IGNORECASE,
)
#: The same flag inline, in brackets: "(simulated: true)".
_FLAG_INLINE_RE = re.compile(rf"\s*[(\[]\s*{_FLAG}\s*[)\]]", re.IGNORECASE)
_FLAG_HEADER_RE = re.compile(r"^\**`?(?:is[_ ]?simulated|simulated)`?\**$", re.IGNORECASE)
_TABLE_CELL_SPLIT = re.compile(r"(?<!\\)\|")


def _cells(line: str) -> List[str]:
    body = line.strip()
    if body.startswith("|"):
        body = body[1:]
    if body.endswith("|") and not body.endswith("\\|"):
        body = body[:-1]
    return _TABLE_CELL_SPLIT.split(body)


def _strip_table(rows: List[str]) -> List[str]:
    """Drop an isSimulated/simulated column, and any key/value row that is only the flag."""
    header = _cells(rows[0])
    drop = {i for i, c in enumerate(header) if _FLAG_HEADER_RE.match(c.strip())}
    out: List[str] = []
    for row in rows:
        cells = _cells(row)
        if len(cells) == 2 and _FLAG_HEADER_RE.match(cells[0].strip()):
            if re.fullmatch(r"(?i)\**`?(?:true|false)`?\**", cells[1].strip()):
                continue
        if drop:
            kept = [c for i, c in enumerate(cells) if i not in drop]
            if not kept:
                continue
            indent = row[: len(row) - len(row.lstrip())]
            row = indent + "|" + "|".join(kept) + "|"
        out.append(row)
    return out


def _strip_flags_prose(text: str) -> str:
    """Apply the BUG-699 removals to text that holds no fenced code."""
    lines = text.split("\n")
    out: List[str] = []
    i = 0
    while i < len(lines):
        line = lines[i]
        if line.lstrip().startswith("|"):
            j = i
            while j < len(lines) and lines[j].lstrip().startswith("|"):
                j += 1
            out.extend(_strip_table(lines[i:j]))
            i = j
            continue
        if _FLAG_LINE_RE.match(line):
            i += 1
            continue
        out.append(_FLAG_INLINE_RE.sub("", line))
        i += 1
    return "\n".join(out)


# ── code-aware application ───────────────────────────────────────────────────

_FENCE_RE = re.compile(r"(^[ \t]*(?:```|~~~)[^\n]*\n.*?^[ \t]*(?:```|~~~)[ \t]*$)", re.M | re.S)
_INLINE_CODE_RE = re.compile(r"(`[^`\n]+`)")


def _outside_code(text: str, fn: Callable[[str], str], inline: bool) -> str:
    """Run ``fn`` over the parts of ``text`` that are not code."""
    parts = _FENCE_RE.split(text)
    for k in range(0, len(parts), 2):  # even indices are outside fences
        if inline:
            bits = _INLINE_CODE_RE.split(parts[k])
            for b in range(0, len(bits), 2):
                bits[b] = fn(bits[b])
            parts[k] = "".join(bits)
        else:
            parts[k] = fn(parts[k])
    return "".join(parts)


def _user_pasted_data(user_message: Optional[str]) -> bool:
    """True when the user really did supply data — a table, a code block or several lines."""
    msg = user_message or ""
    if "```" in msg or re.search(r"^\s*\|.*\|\s*$", msg, re.M):
        return True
    return len([ln for ln in msg.splitlines() if ln.strip()]) >= 3


def attribute_to_building(text: str, user_message: Optional[str] = None) -> str:
    """Rewrite "the <records> you provided" to the building's own records (BUG-679).

    Left alone when the user's own message carries pasted data, where "the data you provided"
    is true.
    """
    if not text or _user_pasted_data(user_message):
        return text or ""
    return _outside_code(text, _rewrite_prose, inline=True)


def strip_provenance_flags(text: str) -> str:
    """Remove ``simulated: true|false`` lines, bracketed flags and table columns (BUG-699)."""
    if not text:
        return text or ""
    # Inline code is not split out here: a flag line is commonly written `simulated: true`, and
    # the line match already requires the WHOLE line to be the flag.
    return _outside_code(text, _strip_flags_prose, inline=False)


#: A claim about where the DATA came from, in the words the owner's standing rule keeps out of every
#: answer: "All alarms were simulated." (tail G, 2026-09-20, a metadata-lane narration of a register
#: whose records carry isSimulated). `strip_provenance_flags` removes the `simulated: true` FIELD
#: form; a narration can restate the same flag as a sentence, which no field pattern can see.
_ORIGIN_CLAIM_RE = re.compile(r"\b(?:synthetic(?:ally)?|simulated|fake|dummy|mock(?:ed)?)\b", re.IGNORECASE)
_SENTENCE_SPLIT_RE = re.compile(r"(?<=[.!?])\s+")


def _drop_origin_sentences(text: str) -> str:
    kept: List[str] = []
    for line in text.split("\n"):
        if not _ORIGIN_CLAIM_RE.search(line):
            kept.append(line)
            continue
        if line.lstrip().startswith("|"):
            continue  # a table row that says it: the row is the claim
        sentences = [s for s in _SENTENCE_SPLIT_RE.split(line) if not _ORIGIN_CLAIM_RE.search(s)]
        rest = " ".join(sentences).strip()
        if rest.strip("*_ `"):
            kept.append(rest)
    return "\n".join(kept)


def strip_origin_claims(text: str, user_message: Optional[str] = None) -> str:
    """Remove sentences that call the building's data synthetic, simulated, fake, dummy or mock.

    The owner's standing rule: readings are placeholders to be replaced by real data, and no answer
    may say otherwise. A question that itself uses one of these words is left alone, so a person who
    asks about it is not answered with a silent gap. Never raises.
    """
    try:
        if not text or not _ORIGIN_CLAIM_RE.search(text):
            return text or ""
        if user_message and _ORIGIN_CLAIM_RE.search(user_message):
            return text
        return _outside_code(text, _drop_origin_sentences, inline=False)
    except Exception:  # pragma: no cover - a wording pass must never cost the answer
        return text


#: Lanes where the USER supplies the content — a fault report, feedback, a preference, a booking.
#: "the details you provided have been logged" is true there, and rewriting it to "the
#: building's details" would misattribute the user's own words to the building.
_USER_SUPPLIED_INTENTS = frozenset(
    {
        "maintenance",
        "complaint",
        "feedback",
        "safety_report",
        "suggestion",
        "preference_management",
        "lab_booking",
    }
)


def polish_answer(
    text: str, user_message: Optional[str] = None, intent: Optional[str] = None
) -> str:
    """Both rewrites, in the order the response node applies them. Never raises.

    The provenance-flag strip always runs; the attribution rewrite does not run on a lane whose
    content the user supplied (`_USER_SUPPLIED_INTENTS`).
    """
    try:
        # A developer tracker id must never reach a reader, whichever lane produced it.
        # `**BUG-606**` was once the whole of an answer to "How busy is the building?".
        from orchestrator.services.prompt_hygiene import scrub_answer

        text = scrub_answer(text)
        stripped = strip_provenance_flags(text)
        if str(intent or "").strip().lower() in _USER_SUPPLIED_INTENTS:
            return stripped
        stripped = strip_origin_claims(stripped, user_message)
        return _narration_hygiene(
            attribute_to_building(stripped, user_message), user_message, intent
        )
    except Exception:  # pragma: no cover - a wording pass must never cost the answer
        return text


def _narration_hygiene(text: str, question: Optional[str], intent: Optional[str]) -> str:
    """Unasked advice, uncited norms and miscounts removed (BUG-832, CAVEAT-833); never raises."""
    try:
        from orchestrator.services.narration_validators import apply_validators

        return apply_validators(question, text, intent)
    except Exception:  # pragma: no cover - a hygiene pass must never cost the answer
        return text
