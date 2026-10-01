# -*- coding: utf-8 -*-
"""W5-01 — a rolling session summary that COMPRESSES old turns instead of dropping them.

WHAT WENT WRONG
---------------
The long-term memory window was a cliff, not a slope. ``get_older_context`` ran
``ORDER BY turn_index DESC OFFSET 20 LIMIT 30``: at turn 60 it returned turns 40 down to
11, and turns 1-10 were simply gone. The tracker's acceptance for this row —
*"a 60-turn conversation still answers a question about turn 3"* — could not be met by
construction, and nothing said so: the block that came back looked healthy.

The second thing that was wrong is subtler and worse. Those older lines carried
``result_summary[:150]``, which for an analytics turn is the ANSWER text verbatim —
measurements included. So a figure produced twenty turns ago was fed back into the prompt
with no time basis and no statement that it was stale, one paraphrase away from being
restated as a current reading. Design contract #4: a remembered number restated as current
is a fabrication, and it is the kind that reads perfectly.

WHAT THIS DOES
--------------
Two rules, both structural rather than advisory:

* **Nothing derived from an ANSWER reaches the summary except one word.** The outcome of a
  past turn is a token from :data:`OUTCOMES` and nothing else. There is no code path by
  which an answer's text, or a number inside it, can appear here — which is a stronger
  guarantee than redacting the answer would be, because a redactor can have a hole and an
  absent field cannot.
* **The user's own question is kept, with measurement-shaped figures redacted**
  (:func:`publication_gate.redact_quantities`, the project's one definition of "this is a
  measurement"). ``room 5.01`` and ``floor 3`` survive because they are identifiers;
  ``1,200 ppm`` does not. Belt and braces: the question is the user's text, not a reading,
  but a threshold a user typed still looks exactly like a reading once it is out of context.

Compression instead of truncation: turns older than the detail window collapse into one
bounded line naming what they were ABOUT, ordered by FIRST APPEARANCE. That ordering is the
whole point — the detail window already covers the recent end, so the compressed head's job
is the old end, which is the end that used to vanish. When there are more subjects than fit,
the line says how many were left out rather than pretending it is complete.

BOUNDS
------
Every field is truncated, the number of detail lines is capped, and the block is cut at
:data:`SUMMARY_MAX_CHARS`. Those are enforced here and not by the caller, because the caller
is four entry points (W5-02) and a bound maintained in four places is a bound in none. The
structural maximum is ~2,060 characters against a 2,200 cap, so the final cut is a
backstop that should never fire; ``tests/test_a_remembered_turn_carries_no_figure.py``
asserts the cap holds anyway, against rows built to break it.

Pure functions over rows: no database, no LLM, no clock, no building vocabulary.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Any, List, Mapping, Optional, Sequence, Tuple

from orchestrator.services.publication_gate import (
    REDACTED_QUANTITY,
    is_decline,
    redact_quantities,
)

#: The closed vocabulary an ANSWER may contribute to the summary. Nothing else from an
#: answer is carried, which is what makes "the summary states no measurement" structural.
OUTCOMES: Tuple[str, str, str] = ("answered", "declined", "no answer recorded")

#: How many recently completed turns the summary SKIPS, because the raw history still shows
#: them. Three, not twenty.
#:
#: The reader used ``skip_recent=CONVERSATION_MAX_MESSAGES`` (20), and that number counts
#: MESSAGES in Redis, not turns — while the raw history that actually reaches a prompt is
#: ``format_conversation_history(msgs, max_messages=6)``: six messages, which is three turns.
#: So turns 4 through 20 were in NEITHER the raw window nor the summary: a seventeen-turn
#: hole in the middle of the conversation, invisible because both halves looked healthy.
#: Three user messages plus three assistant replies is exactly the six the window shows, so
#: this leaves no gap and no duplication.
RECENT_TURNS_KEPT_RAW = 3

#: How many of the most recent older turns keep a line of their own.
DETAIL_TURNS = 10

#: Per-field truncation. A row arriving from a client can be as long as the message limit
#: allows, so the ceiling is applied here rather than trusted from the store.
QUESTION_MAX_CHARS = 90
INTENT_MAX_CHARS = 24

#: The compressed era: how many distinct subjects it may name, and how long each may be.
MAX_TOPICS = 12
TOPIC_MAX_CHARS = 28

#: Hard ceiling on the whole block. See BOUNDS above.
SUMMARY_MAX_CHARS = 2200

#: The first line, and the marker by which a previously injected block is recognised and
#: replaced rather than stacked (W5-02 injects on every turn, on every entry point).
HEADER = (
    "Earlier in this session (questions already asked; no measurements are kept here, "
    "so re-query the data before stating any value):"
)

#: Generic English function words. Deliberately no building vocabulary of any kind — this
#: list would be identical for bldg2 (design contract #3). Period words ("today",
#: "yesterday", "last", "week", "hour") are deliberately NOT here: W5-01 asks the summary to
#: record which place, quantity and PERIOD were in play, and dropping them would lose a
#: third of that.
_STOPWORDS = frozenset(
    {
        "a",
        "about",
        "again",
        "all",
        "also",
        "am",
        "an",
        "and",
        "any",
        "are",
        "as",
        "at",
        "be",
        "been",
        "but",
        "by",
        "can",
        "could",
        "did",
        "do",
        "does",
        "for",
        "from",
        "get",
        "give",
        "had",
        "has",
        "have",
        "how",
        "i",
        "if",
        "in",
        "into",
        "is",
        "it",
        "its",
        "just",
        "know",
        "like",
        "many",
        "me",
        "much",
        "my",
        "no",
        "not",
        "now",
        "of",
        "on",
        "one",
        "or",
        "our",
        "please",
        "really",
        "right",
        "show",
        "so",
        "some",
        "tell",
        "than",
        "that",
        "the",
        "their",
        "them",
        "then",
        "there",
        "these",
        "they",
        "this",
        "those",
        "to",
        "up",
        "us",
        "very",
        "was",
        "we",
        "were",
        "what",
        "when",
        "where",
        "which",
        "who",
        "why",
        "will",
        "with",
        "would",
        "you",
        "your",
    }
)

#: A word, or a dotted/hyphenated identifier such as ``5.04`` or ``ahu-1``.
_TOKEN = re.compile(r"[a-z0-9]+(?:[.\-'][a-z0-9]+)*")

#: A token that is only a number — ``3``, ``5.04``. Merged onto the word before it so
#: "floor 3" stays "floor 3" instead of collapsing to "floor".
_NUMERIC_TOKEN = re.compile(r"^[0-9]+(?:[.\-][0-9]+)*$")


def _text(value: Any) -> str:
    """A stripped string from anything a row may hold, including None."""
    return str(value).strip() if value is not None else ""


def _clip(value: str, limit: int) -> str:
    """Truncate to ``limit`` characters, marking the cut so nothing reads as complete."""
    value = " ".join(value.split())
    if len(value) <= limit:
        return value
    return value[: max(1, limit - 1)].rstrip() + "…"


def outcome_of(result_summary: Optional[str]) -> str:
    """Which of :data:`OUTCOMES` a stored turn ended in.

    Reuses ``publication_gate.is_decline`` rather than adding a fifth decline classifier to
    this repository — CLAUDE.md records the gate's own classifier being wrong three times in
    one day, and a copy is how that happens.
    """
    text = _text(result_summary)
    if not text:
        return OUTCOMES[2]
    return OUTCOMES[1] if is_decline(text) else OUTCOMES[0]


@dataclass(frozen=True)
class TurnNote:
    """One past turn, reduced to what may be remembered about it.

    ``question`` is the user's words with measurement-shaped figures redacted; ``outcome``
    is a member of :data:`OUTCOMES`. There is no field for the answer, on purpose.
    """

    turn_index: int
    question: str
    intent: str
    outcome: str


def _field(row: Any, key: str) -> Any:
    """One column of a row, whether it is a dict or an ``asyncpg.Record``.

    ``Record`` grew ``.get()`` only in asyncpg 0.18 and indexes by key like a mapping, so
    subscript-with-fallback works on both and on every version.
    """
    try:
        return row[key]
    except (KeyError, IndexError, TypeError):
        return None


def note_from_row(row: Any) -> TurnNote:
    """Build a :class:`TurnNote` from a ``turn_memory`` row.

    The row's ``result_summary`` is read HERE and discarded here: only the outcome token
    leaves this function, so the answer text has no route into the summary.
    """
    try:
        turn_index = int(_field(row, "turn_index"))
    except (TypeError, ValueError):
        turn_index = 0
    question = _clip(redact_quantities(_text(_field(row, "user_query"))), QUESTION_MAX_CHARS)
    intent = _clip(_text(_field(row, "intent")) or "general", INTENT_MAX_CHARS)
    return TurnNote(
        turn_index=turn_index,
        question=question,
        intent=intent,
        outcome=outcome_of(_field(row, "result_summary")),
    )


def _topics(notes: Sequence[TurnNote]) -> List[str]:
    """Distinct subjects the given turns were about, in order of FIRST appearance.

    First-appearance order, not frequency: the detail window already carries the recent
    turns, so the compressed head is the only record of the oldest ones and must not let a
    later repeated subject push turn 3's subject out.
    """
    seen: List[str] = []
    known = set()
    for note in notes:
        text = note.question.replace(REDACTED_QUANTITY, " ").lower()
        phrases: List[str] = []
        for token in _TOKEN.findall(text):
            if token in _STOPWORDS:
                continue
            if _NUMERIC_TOKEN.match(token):
                # "floor 3" / "room 5.04" — attach to the word it qualifies, and drop a
                # bare number that qualifies nothing.
                if phrases and not _NUMERIC_TOKEN.match(phrases[-1].split()[-1]):
                    phrases[-1] = f"{phrases[-1]} {token}"
                continue
            if len(token) < 3:
                continue
            phrases.append(token)
        for phrase in phrases:
            phrase = _clip(phrase, TOPIC_MAX_CHARS)
            if phrase and phrase not in known:
                known.add(phrase)
                seen.append(phrase)
    return seen


def _era_line(notes: Sequence[TurnNote]) -> str:
    """One bounded line standing in for every turn older than the detail window."""
    topics = _topics(notes)
    shown = topics[:MAX_TOPICS]
    more = len(topics) - len(shown)
    subjects = "; ".join(shown) if shown else "no recorded subject"
    if more > 0:
        subjects += f"; and {more} more"
    answered = sum(1 for n in notes if n.outcome == OUTCOMES[0])
    declined = sum(1 for n in notes if n.outcome == OUTCOMES[1])
    lo = min(n.turn_index for n in notes)
    hi = max(n.turn_index for n in notes)
    span = f"Turn {lo}" if lo == hi else f"Turns {lo}-{hi}"
    return f"{span} covered: {subjects} ({answered} answered, {declined} declined)."


def _detail_line(note: TurnNote) -> str:
    return f"Turn {note.turn_index} [{note.intent}] asked: {note.question} -> {note.outcome}"


def build(notes: Sequence[TurnNote], detail_turns: int = DETAIL_TURNS) -> str:
    """Render the rolling summary. Empty string when there is nothing to remember.

    ``notes`` must be ordered oldest-first. The newest ``detail_turns`` keep a line each;
    everything older collapses into one :func:`_era_line`.
    """
    notes = [n for n in notes if n.question.strip()]
    if not notes:
        return ""
    detail_turns = max(0, int(detail_turns))
    split = max(0, len(notes) - detail_turns)
    compressed, detail = notes[:split], notes[split:]

    lines = [HEADER]
    if compressed:
        lines.append(_era_line(compressed))
    lines.extend(_detail_line(n) for n in detail)

    block = "\n".join(lines)
    if len(block) <= SUMMARY_MAX_CHARS:
        return block
    # Backstop only: every field above is already clipped and every count capped, so
    # reaching here means a constant was widened without re-checking the arithmetic.
    kept = [HEADER]
    budget = SUMMARY_MAX_CHARS - len(HEADER)
    for line in lines[1:]:
        if len(line) + 1 > budget:
            break
        kept.append(line)
        budget -= len(line) + 1
    return "\n".join(kept)


def strip_previous(messages: Sequence[Any]) -> List[Any]:
    """Drop an earlier injected summary from a message list.

    The summary is rebuilt and re-injected every turn on every entry point. On the routes
    that restore their history from Redis (``/chat``, ``/chat/stream``, ``/stream``) that
    would stack one system block per turn — a memory feature that grows the prompt it exists
    to bound. Identified by :data:`HEADER`, which is why the header is a constant.
    """
    kept: List[Any] = []
    for message in messages or []:
        role = message.get("role") if isinstance(message, Mapping) else getattr(message, "role", "")
        content = (
            message.get("content")
            if isinstance(message, Mapping)
            else getattr(message, "content", "")
        )
        if str(role) == "system" and str(content or "").startswith(HEADER):
            continue
        kept.append(message)
    return kept
