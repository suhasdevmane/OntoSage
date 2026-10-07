# -*- coding: utf-8 -*-
"""BUG-941 — answer a question about the CONVERSATION from the conversation (W5-03/W5-04).

WHAT WENT WRONG
---------------
Measured live 2026-09-29, eight turns on ``/v1/chat/completions``, one chat id. Turn 1 was
*"I am looking into air quality in room 5.01 specifically."* Turn 8 was *"Remind me which
room I said I was looking into, and why."* The answer was:

    the building's records do not record the room you were interested in or why you were
    looking into it

with ``Sources: Building model``. The session summary had been injected on that very turn
(``[/v1/chat/completions] session summary injected (453 chars)``), and it named room 5.01.

The decline is honest about the building's records and answers the wrong question. The user
did not ask what the BUILDING holds; they asked what THEY said. No intent covered that, the
room-shaped and records-shaped vocabulary classified it as a data question, and the lane it
reached reads the graph and never looks at the bus key that had the answer on it.

This is `agent-patterns.md` step 3 one level down: there, a lane computes an answer nobody
collects; here, a datum is put on the bus and nobody reads it.

WHAT THIS DOES
--------------
Two pure functions and no I/O:

* :func:`is_recall_question` decides whether a question is about the conversation.
* :func:`answer` renders one from :class:`session_summary.TurnNote` rows.

THREE RULES THAT ARE STRUCTURAL, NOT ADVISORY
---------------------------------------------
**1. It quotes; it does not interpret.** Every noun in the answer is a word the USER typed.
Nothing is extracted, classified or inferred — the lane reads back the user's own earlier
questions, with the turn number, oldest first. That is the strongest possible honesty
guarantee for a recall answer and it is also the cheapest: an extractor that decides which
room the user "meant" is a second place a wrong referent can be invented, and BUG-940 is
what that costs.

**2. It recalls SUBJECTS and never VALUES, and it says so.** W5-01 keeps figures out of the
session record by construction: :class:`TurnNote` has no field for the answer, and the only
thing an answer contributes is one token from a closed three-word vocabulary. A remembered
number restated as current is a fabrication (design contract #4, lessons #148), and a
remembered answer is the one place a fabrication would be least visible — there is no live
value to contradict it. So the caveat in :data:`VALUES_CAVEAT` is appended to every
non-empty answer, rather than the absence of figures being left for the reader to notice.

**3. An empty record produces an honest decline, not a shrug.** When the user asks which
room they mentioned and they mentioned none, the answer says exactly that and then shows
what they DID ask about — because "I have no record of that" is more useful with the record
attached.

Building-agnostic (design contract #3): no namespace, no Brick class, no sensor vocabulary,
no place vocabulary. The only nouns this module can emit are the user's own. It would run
unchanged for bldg2.
"""

from __future__ import annotations

import re
from typing import Any, List, Optional, Sequence, Tuple

from orchestrator.services.session_summary import OUTCOMES, TurnNote
from shared.utils import get_logger

logger = get_logger(__name__)

#: The bus key `main._inject_session_summary` writes the structured turns to. The PROSE
#: block lives under "session_summary" and is what the prompts read; this lane needs the
#: turns, because the block compresses everything past its detail window into one line that
#: keeps subjects and drops the sentences the user actually typed.
NOTES_KEY = "session_summary_notes"

#: How many earlier questions the answer may quote back. The session record is bounded at
#: 500 rows; a wall of them is not a recall.
MAX_QUOTED = 8

#: How many of the user's own words the decline may name back to them.
MAX_FOCUS_NAMED = 3

#: Appended to every non-empty answer. See rule 2 in the module docstring — this is the
#: statement that the lane recalls subjects and not values, and it is not optional.
VALUES_CAVEAT = (
    "I can recall what was **asked**, not what was answered: this session record keeps no "
    "measured values on purpose, so nothing above is a reading. Ask again for any figure "
    "and I will re-query the data."
)

# ─────────────────────────────────────────────────────────────────────────────
# Detection
# ─────────────────────────────────────────────────────────────────────────────

#: A first-person reference to something ALREADY SAID. Past and perfect forms only, plus the
#: interrogative inversion.
#:
#: Present-tense and modal forms are deliberately absent, and each exclusion is a measured
#: false positive rather than a matter of taste:
#:
#: * ``"can I ask ..."`` / ``"let me ask ..."`` / ``"I want to ask ..."`` are forward-looking
#:   requests. They contain "I ask" and are not recall, so bare ``ask`` matches only after
#:   ``did`` / ``have`` / ``was``.
#: * ``"I am looking into air quality in room 5.01"`` — turn 1 of the very probe this module
#:   exists for — contains "I ... looking into". A pattern including it would classify the
#:   DECLARATION as a question about itself. ``looking into`` and ``interested in`` are
#:   therefore not speech verbs here.
#: * ``wanted`` is absent for the same reason: "I wanted to know the temperature" is a data
#:   question wearing a past tense.
_RETROSPECTIVE = re.compile(
    # "I said", "we already discussed", "I have just mentioned"
    r"\b(?:i|we)\s+"
    r"(?:(?:have|had|has|'ve|'d)\s+)?"
    r"(?:just\s+|already\s+|previously\s+|earlier\s+|first\s+)?"
    r"(?:said|asked|mentioned|told|discussed|talked|raised|covered)\b"
    # "I was asking", "we were discussing"
    r"|\b(?:i|we)\s+(?:was|were)\s+(?:just\s+|already\s+)?"
    r"(?:asking|saying|telling|discussing|talking)\b"
    # "did I say", "have we discussed", "was I asking"
    r"|\b(?:did|have|has|had|was|were)\s+(?:i|we)\s+"
    r"(?:\w+\s+){0,2}?"
    r"(?:say|said|ask|asked|asking|mention|mentioned|tell|told|discuss|discussed|"
    r"talk|talked|talking|raise|raised|cover|covered)\b",
    re.IGNORECASE,
)

#: A question about what the ASSISTANT said -- its previous answer, the evidence behind it, how
#: it arrived at it (BUG-1397). "What is the evidence behind your answer about the coolest room?"
#: asked with no prior turn routed to the diagnosis lane, which ran and produced nothing, on two
#: asks of three. This conversation's own record is the one lane that can say whether there WAS
#: an answer and quote the question it answered.
_ABOUT_MY_ANSWER = re.compile(
    r"\b(?:your|that|the\s+(?:previous|last|earlier))\s+(?:previous\s+|last\s+|earlier\s+)?"
    r"(?:answer|response|reply|conclusion)s?\b"
    r"|\bwhat\s+you\s+(?:just\s+)?(?:said|told\s+me|answered|replied)\b"
    r"|\bhow\s+did\s+you\s+(?:get|arrive\s+at|come\s+up\s+with|work\s+out|calculate)\b"
    r"|\bevidence\s+(?:behind|for)\s+(?:your|that|the\s+last)\b",
    re.IGNORECASE,
)

#: The question must be a REQUEST TO RECALL, not a statement containing one. Without this,
#: "I told you about room 5.01." — a declaration — would route here.
_RECALL_REQUEST = re.compile(
    r"^\s*(?:what|which|who|when|where|why|how|did|do|does|have|has|had|was|were|can|could)\b"
    r"|\bremind\s+me\b|\btell\s+me\b|\brecap\b|\bsummar(?:ise|ize)\b"
    r"|\bgo\s+over\b|\brefresh\s+my\s+memory\b",
    re.IGNORECASE,
)

#: A head that asks for a VALUE. When one of these opens the question and the retrospective
#: clause is a relative clause hanging off a later noun, the question is about the building
#: and not about the conversation: "What is the CO2 in the room I mentioned earlier?" needs
#: the co-reference rewrite and the data lane, not this one.
_VALUE_HEAD = re.compile(
    r"\bwhat(?:'s|s| is| are| was| were)\s+the\b"
    r"|\bhow\s+(?:much|many|hot|cold|warm|humid|bright|noisy)\b"
    r"|\bshow\s+me\s+the\b|\bgive\s+me\s+the\b",
    re.IGNORECASE,
)

#: How many words may sit between a value head and the retrospective clause before the
#: question is read as a data question. See :func:`_value_head_owns`.
_VALUE_HEAD_GAP_WORDS = 2

#: Determiners that mark the retrospective clause as a RELATIVE clause hanging off a thing
#: the question is really about: *the ticket I raised*, *that room I mentioned*. The
#: interrogative determiners — which, what, whose — are deliberately absent, because
#: *which floor I said* is the recall question itself.
#:
#: This guard exists because of ONE sentence, and it is a real one rather than an invented
#: test case: *"What happened to the ticket I raised about the draught last week?"* is in
#: ``docs/smart_building_questions.csv`` and was the single false positive in 4,287
#: questions before it was added. It costs a phrasing — ``"What was the room I mentioned?"``
#: no longer routes here, because it is grammatically the same sentence — and that trade is
#: taken deliberately: over-capture is the worse direction (a working data question answered
#: from the conversation), while under-capture only leaves BUG-941's existing behaviour in
#: place for one wording. Both are pinned by tests so neither is later "fixed" by accident.
_RELATIVE_DETERMINERS = frozenset(
    {
        "a",
        "an",
        "her",
        "his",
        "its",
        "my",
        "our",
        "that",
        "the",
        "their",
        "these",
        "this",
        "those",
        "your",
    }
)

#: Words the recall question itself is made of. Stripped before deciding what the user wants
#: recalled, so "which ROOM did I say" leaves {"room"} and not {"which", "room", "did", …}.
_RECALL_VOCAB = frozenset(
    {
        "about",
        "again",
        "already",
        "and",
        "ask",
        "asked",
        "asking",
        "been",
        "before",
        "bring",
        "brought",
        "can",
        "conversation",
        "could",
        "cover",
        "covered",
        "did",
        "discuss",
        "discussed",
        "discussing",
        "do",
        "does",
        "earlier",
        "far",
        "first",
        "for",
        "from",
        "go",
        "had",
        "has",
        "have",
        "how",
        "i",
        "in",
        "into",
        "just",
        "looking",
        "me",
        "memory",
        "mention",
        "mentioned",
        "my",
        "of",
        "on",
        "over",
        "previously",
        "raise",
        "raised",
        "recap",
        "refresh",
        "remind",
        "said",
        "say",
        "saying",
        "session",
        "so",
        "summarise",
        "summarize",
        "talk",
        "talked",
        "talking",
        "tell",
        "telling",
        "that",
        "the",
        "them",
        "there",
        "these",
        "this",
        "those",
        "to",
        "told",
        "up",
        "was",
        "we",
        "were",
        "what",
        "when",
        "where",
        "which",
        "while",
        "who",
        "why",
        "with",
        "you",
        "your",
    }
)

#: A word, or a dotted/hyphenated identifier. Same shape as `session_summary._TOKEN`; kept
#: separate so neither module's tokenisation is constrained by the other's.
_TOKEN = re.compile(r"[a-z0-9]+(?:[.\-'][a-z0-9]+)*")

#: The question asks for a REASON as well as a subject, so the answer says what it has and
#: has not inferred about one.
_ASKS_WHY = re.compile(r"\bwhy\b|\breasons?\b|\bwhat\s+for\b", re.IGNORECASE)


def _value_head_owns(text: str, retro_start: int) -> bool:
    """True when a value-seeking head governs the question rather than a recall clause.

    The discriminator is the DISTANCE from the head to the retrospective clause, not any
    vocabulary — which is what keeps this building-agnostic:

    * ``"What was the room I mentioned?"`` — one word between them, so the retrospective
      clause is the head's own complement and the question is about the conversation.
    * ``"What is the CO2 in the room I mentioned earlier?"`` — four words between them, so
      the retrospective clause is a relative clause on a later noun and the question is
      about the building.

    The boundary is a judgement, stated here rather than buried: at
    :data:`_VALUE_HEAD_GAP_WORDS` it is deliberately tight, because over-capture is the
    worse direction (a working data question answered from the conversation) and
    under-capture only leaves BUG-941's existing behaviour in place for a phrasing.
    """
    match = _VALUE_HEAD.search(text)
    if not match or match.start() >= retro_start:
        return False
    gap = text[match.end() : retro_start]
    return len(gap.split()) > _VALUE_HEAD_GAP_WORDS


def _is_relative_clause(text: str, retro_start: int) -> bool:
    """True when the retrospective clause modifies a thing rather than being the question.

    *"the ticket I raised"* is a relative clause on a ticket; *"which floor I said"* is the
    question. The difference is the determiner, and only the determiner — see
    :data:`_RELATIVE_DETERMINERS` for the sentence that put this here.
    """
    before = _TOKEN.findall(text[:retro_start].lower())
    return len(before) >= 2 and before[-2] in _RELATIVE_DETERMINERS


def is_recall_question(query: str) -> bool:
    """True when the user is asking what was said earlier in THIS conversation.

    Four conditions, all required: a first-person reference to something already said, a
    request to recall it, no value-seeking head governing the sentence, and the
    retrospective clause not being a relative clause on some other thing.
    """
    text = (query or "").strip()
    if not text:
        return False
    if _ABOUT_MY_ANSWER.search(text) and _RECALL_REQUEST.search(text):
        return True
    retro = _RETROSPECTIVE.search(text)
    if not retro:
        return False
    if not _RECALL_REQUEST.search(text):
        return False
    if _value_head_owns(text, retro.start()):
        return False
    return not _is_relative_clause(text, retro.start())


# ─────────────────────────────────────────────────────────────────────────────
# Rendering
# ─────────────────────────────────────────────────────────────────────────────


def focus_terms(query: str) -> List[str]:
    """The user's own words naming WHAT they want recalled, in order, deduplicated.

    "Remind me which room I said I was looking into, and why." -> ``["room"]``. Everything
    the recall question is itself made of is stripped, so what is left is the subject — and
    it is the user's vocabulary, never this module's.
    """
    seen: List[str] = []
    known = set()
    for token in _TOKEN.findall((query or "").lower()):
        if len(token) < 3 or token in _RECALL_VOCAB or token in known:
            continue
        known.add(token)
        seen.append(token)
    return seen


def _matches(note: TurnNote, terms: Sequence[str]) -> int:
    """How many of ``terms`` the user's own words in this turn contain."""
    haystack = note.question.lower()
    return sum(1 for term in terms if term in haystack)


def _quote(note: TurnNote) -> str:
    """One earlier turn, as the user typed it."""
    suffix = "" if note.outcome == OUTCOMES[2] else f" ({note.outcome})"
    return f'- Turn {note.turn_index} — "{note.question}"{suffix}'


def _named(terms: Sequence[str]) -> str:
    """The user's focus words, quoted back at them: ``"room" or "floor"``."""
    shown = [f'"{t}"' for t in terms[:MAX_FOCUS_NAMED]]
    if len(shown) == 1:
        return shown[0]
    return ", ".join(shown[:-1]) + " or " + shown[-1]


def _select(notes: Sequence[TurnNote], terms: Sequence[str]) -> Tuple[List[TurnNote], bool, int]:
    """The turns to quote, whether the user's focus chose them, and how many were cut.

    Ordered oldest-first among the matches, then capped — the opposite end from the one a
    recency cut would keep, because a declared subject is normally stated EARLY and that is
    the end the raw message window has already lost.

    The third return value is how many turns the CAP removed, which is a different fact
    from how many the FOCUS removed and is reported differently. Conflating them read as
    *"…and 6 more turn(s) not shown"* under a single matching quote, which tells the reader
    their record was truncated when it was filtered.
    """
    pool = list(notes)
    by_focus = False
    if terms:
        scored = [n for n in notes if _matches(n, terms)]
        if scored:
            pool, by_focus = scored, True
    return pool[:MAX_QUOTED], by_focus, max(0, len(pool) - MAX_QUOTED)


def answer(query: str, notes: Sequence[TurnNote]) -> str:
    """Render a recall answer from this session's own record of the user's questions.

    ``notes`` must be ordered oldest-first. Never raises and never returns an empty string:
    with nothing to recall it returns the decline that says so.
    """
    usable = [n for n in (notes or []) if n.question.strip()]
    if not usable:
        return (
            "**Nothing has been asked in this conversation yet**, so there is nothing for "
            "me to recall. This is a record of what you have asked me in this session — it "
            "is not the building's records, and it does not reach back to other sessions."
        )

    terms = focus_terms(query)
    chosen, by_focus, capped = _select(usable, terms)

    lines: List[str] = []
    if terms and not by_focus:
        # The honest decline the tracker row asks for: say what is NOT there before showing
        # what is, and name the user's own word back rather than a guess at what they meant.
        lines.append(
            f"**I have no record of you mentioning {_named(terms)} in this conversation.**"
        )
        lines.append("")
        lines.append("What you have asked about so far, in your own words:")
    else:
        lines.append("**From this conversation, in your own words:**")
    lines.append("")
    lines.extend(_quote(n) for n in chosen)

    if capped:
        lines.append(f"- …and {capped} more matching turn(s) not shown.")
    if by_focus:
        others = len(usable) - len(chosen) - capped
        if others > 0:
            lines.append(
                f"- ({others} other turn(s) in this conversation did not mention "
                f"{_named(terms)}.)"
            )

    lines.append("")
    if by_focus:
        lines.append("That is what you said; I have not added anything to it.")
        if _ASKS_WHY.search(query or ""):
            lines.append("Any reason you gave is in those words — I have not inferred one for you.")
        lines.append("")
    lines.append(VALUES_CAVEAT)
    return "\n".join(lines)


#: BUG-1427. BUG-1397 correctly routes "what is the evidence behind your answer?", "how did
#: you arrive at that?", "what was your previous answer based on?" HERE — this is the one
#: lane that can say whether there was an answer — but until now the lane could only quote
#: the past QUESTION back (`answer()` above), never the previous answer's own recorded
#: evidence. Asking for a BASIS then produced "I have no record of you mentioning 'based'",
#: a confusing non-answer when a basis really was recorded one turn back. Said when a
#: previous turn exists but carried no usable evidence record at all (the key was never
#: set — an old cached turn, or a lane that raised before assembly ran); the much more
#: common case of a turn that ran and recorded "no lane produced evidence for this answer"
#: is itself a valid, honest render (see `render`'s NOT_ASSESSABLE handling) and is shown
#: rather than this.
_NO_EVIDENCE_RECORD = (
    "**Your last answer in this conversation carries no recorded evidence basis.** That "
    "happens when the turn is too old to carry one, or ended before a record could be "
    "assembled. Ask a question the building answers from its own records or live "
    "readings, then ask how I know, and I will read that record back to you."
)


async def _render_previous_answer_evidence(state: Any, query: str) -> Optional[str]:
    """The previous turn's evidence record read back in prose, or None to fall through.

    None (never a decline here) when the question is not about the previous ANSWER's basis,
    or there simply is no previous turn — the caller's quote-based `answer()` already covers
    both honestly. A decline is only returned from here when there WAS a previous turn with
    no evidence record to read, which `answer()` cannot say (it only sees the user's own
    past questions, never the evidence bus key).
    """
    if not _ABOUT_MY_ANSWER.search(query or ""):
        return None
    from orchestrator.services.answer_provenance import (
        load_previous_turn_record,
        render,
    )

    record = await load_previous_turn_record(getattr(state, "conversation_id", None))
    is_admin = False
    try:
        from orchestrator.services.grounding_guard import reader_is_admin_in

        is_admin = reader_is_admin_in(state)
    except Exception:  # pragma: no cover - the plain read-back is the safe side
        pass
    rendered = render(record, query, for_admin=is_admin) if record else None
    if rendered:
        return rendered
    if record is None:
        return _NO_EVIDENCE_RECORD
    return None  # render() returned nothing for a non-empty record; let answer() speak


# ─────────────────────────────────────────────────────────────────────────────
# The lane
# ─────────────────────────────────────────────────────────────────────────────


async def session_recall_node(state: Any) -> Any:
    """Answer a question about THIS CONVERSATION from the session's own record.

    The whole node lives here rather than in ``workflow/_orchestrator.py`` so the logic and
    its tests sit beside each other, the way ``scope_policy.scope_boundary_node`` already
    does. The orchestrator's method is a four-line delegate.

    Writes to ``dialogue_response``, which is the key ``_response_node`` already collects
    for standalone lanes that route straight to ``response`` — checked, not assumed, because
    `agent-patterns.md` step 3 is where a lane computes the right answer and the user reads
    *"I processed your request, but couldn't generate a response."* Three lanes reach the
    reader through that key today (``self_description``, ``general_knowledge``,
    ``locked_capability``); nothing else runs alongside this one, so nothing outranks it.

    BUG-1427: a question about the PREVIOUS ANSWER's own evidence (not about what the user
    themselves said) is read from that turn's recorded evidence, with the same vocabulary
    `answer_provenance.render()` uses everywhere else — never a raw dump of UUIDs, never a
    second API call. Only attempted when there IS a previous turn to ask about; with none,
    the existing quote-based decline below already says so honestly.
    """
    query = state.user_message or ""
    notes = state.intermediate_results.get(NOTES_KEY) or []
    if notes:
        try:
            evidenced = await _render_previous_answer_evidence(state, query)
        except Exception as exc:  # an evidence read must never cost the turn its recall
            logger.debug(f"[session_recall] evidence read-back skipped: {exc}")
            evidenced = None
        if evidenced:
            state.intermediate_results["dialogue_response"] = evidenced
            state.current_intent = "session_recall"
            logger.info("[session_recall] answered a provenance question from the evidence record")
            return state
    state.intermediate_results["dialogue_response"] = answer(query, notes)
    state.current_intent = "session_recall"
    logger.info(f"[session_recall] answered from {len(notes)} stored turn(s)")
    return state
