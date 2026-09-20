# -*- coding: utf-8 -*-
"""Nothing from general knowledge goes out unlabelled (2D-16 wave 2).

Wave-1 development read, "What kind of vechicles park?" (lane general_knowledge): a paragraph about
cars, vans, motorcycles and "dedicated charging stalls", written from the model's own knowledge with
nothing to say it was not about THIS building -- whose graph holds a transport-and-parking topic
(motorcycles, scooters, EV charging, cycle parking). Two rules, both enforced on the way out:

1. **The building's own records go first.** When the question's subject matches an amenity or topic
   the building declares (typo-tolerant: "vechicles" is "vehicles"), the answer is that record, said
   as the building's.
2. **Anything else from the model is labelled**, at the top, as general knowledge, so a reader can
   never take it for something the building said. The label is added by code, not requested of the
   model, and is never added twice.

Building-agnostic: the vocabulary is whatever amenities the active building declares.
"""

from __future__ import annotations

import difflib
import re
from types import SimpleNamespace
from typing import Any, Iterable, List, Optional, Sequence, Set, Tuple

from orchestrator.services.fallback_wording import _close
from orchestrator.services.passage_relevance import question_topic_terms
from shared.utils import get_logger

logger = get_logger(__name__)

LABEL = "General knowledge (not from this building's records):"
_LABELLED = re.compile(r"^\s*(?:\*\*)?general (?:guidance|knowledge)\b", re.IGNORECASE)

_WORD = re.compile(r"[a-z][a-z\-]+")
_MIN_TYPO_LEN = 5
_TYPO_CUTOFF = 0.82


def labelled(text: str) -> str:
    """``text`` with the general-knowledge label on top; unchanged when already labelled or empty."""
    body = (text or "").strip()
    if not body or _LABELLED.match(body):
        return body
    return f"{LABEL} {body}"


def is_labelled(text: str) -> bool:
    """True when the text already carries a general-guidance or general-knowledge label."""
    return bool(_LABELLED.match(text or ""))


def vocabulary_of(amenities: Iterable[Any]) -> Set[str]:
    """Every word the building's amenities and topics are known by (label and lay terms)."""
    vocab: Set[str] = set()
    for am in amenities or ():
        parts = [str(getattr(am, "label", "") or "")]
        parts.extend(str(p) for p in (getattr(am, "lay_phrases", None) or ()))
        for text in parts:
            vocab.update(w for w in _WORD.findall(text.lower()) if len(w) >= 3)
    return vocab


def correct_typos(question: str, vocabulary: Set[str]) -> str:
    """The question with words that are one slip away from a declared word put right.

    Only words of five letters or more that the building does not already know, and only to a
    word it does: "vechicles" becomes "vehicles" (matched on the stem), an unrelated word is left
    exactly as typed. Conservative, because a wrong correction would answer a different question.
    """
    if not vocabulary:
        return question
    known = set(vocabulary) | {v.rstrip("s") for v in vocabulary}
    pool = sorted(known)

    def fix(match: "re.Match[str]") -> str:
        word = match.group(0)
        low = word.lower()
        if len(low) < _MIN_TYPO_LEN or low in known or low.rstrip("s") in known:
            return word
        best = difflib.get_close_matches(low.rstrip("s"), pool, n=1, cutoff=_TYPO_CUTOFF)
        if not best:
            return word
        return best[0] + ("s" if low.endswith("s") and not best[0].endswith("s") else "")

    return re.sub(r"[A-Za-z][A-Za-z\-]+", fix, question)


def _words_of(am: Any) -> Set[str]:
    return vocabulary_of([am])


def score(topic: Set[str], am: Any) -> int:
    """How many of the question's subject terms this amenity's own words cover."""
    words = _words_of(am)
    return sum(1 for t in topic if any(_close(t, w) or _close(w, t) for w in words))


def match_amenities(question: str, amenities: Sequence[Any], limit: int = 2) -> List[Any]:
    """The amenities that ARE the subject of ``question``, best first (typo-tolerant).

    An amenity qualifies when it covers at least two of the question's subject terms, or the one
    it has; and a short question must be fully covered (a longer one may leave one term over), so a
    question that merely mentions a parking word ("can I park a helicopter on the roof?") is not
    answered with the parking topic.
    """
    fixed = correct_typos(question, vocabulary_of(amenities))
    topic = question_topic_terms(fixed)
    if not topic:
        return []
    ranked: List[Tuple[int, int, Any]] = []
    for am in amenities:
        s = score(topic, am)
        if s == 0:
            continue
        if s >= 2 or len(topic) == 1:
            label_words = vocabulary_of(
                [SimpleNamespace(label=getattr(am, "label", ""), lay_phrases=())]
            )
            in_label = sum(
                1 for t in topic if any(_close(t, w) or _close(w, t) for w in label_words)
            )
            ranked.append((s, in_label, am))
    ranked.sort(key=lambda p: (-p[0], -p[1]))
    # A short question must be COVERED: a subject word left over ("helicopter" in "can I park a
    # helicopter on the roof?") means the topic mentions the question, it is not the question.
    allowed_leftover = 0 if len(topic) <= 3 else 1
    kept: List[Any] = []
    for _s, _l, am in ranked:
        words = _words_of(am)
        leftover = [t for t in topic if not any(_close(t, w) or _close(w, t) for w in words)]
        if len(leftover) <= allowed_leftover:
            kept.append(am)
    return kept[:limit]


async def records_answer(question: str, building: str = "this building") -> Optional[str]:
    """The building's own answer to a question the model was about to answer, or None.

    Reads the amenity and topic triples through the capability resolver; never raises, because
    the caller's alternative is the labelled model answer.
    """
    try:
        from orchestrator.services.capability_graph_resolver import (
            _to_fact,
            get_capability_graph_resolver,
        )

        amenities = await get_capability_graph_resolver()._amenities()
        matched = match_amenities(question, list(amenities))
        if not matched:
            return None
        parts = [f"Here is what I found for **{building}**:\n"]
        parts.extend(_to_fact(am).render() for am in matched)
        parts.append("\n*Answered live from the building's own records.*")
        return "\n\n".join(parts)
    except Exception as exc:
        logger.debug(f"[general_knowledge] building records unavailable: {exc}")
        return None
