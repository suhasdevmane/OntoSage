# -*- coding: utf-8 -*-
"""Answer a "which source is right?" question from the cross-source conflict scanner (E2,
QA-trial plan, 2026-10-04).

``scripts/fact_conflicts.py`` is a complete, standing-tested capability -- it extracts
(subject, attribute, value) facts from a building's own ``documents/*.md`` and authored TTL
(hours, contacts, levels, counts, places, providers -- see that module's own RULES table) and
lists every one stated with more than one value -- with no caller anywhere in the
orchestrator. A tester asking "the reception hours differ depending on who I ask -- which is
right?" reached nothing, while the scanner that answers it already runs in CI.

Deliberately does not resolve the disagreement. A document is a statement ABOUT a system of
record, not the record itself (the same principle :mod:`evidence.precedence` encodes for a
live claim) -- so this names every value and where it was found, and leaves which one is
current to the record's own owner, exactly as ``scripts/fact_conflicts.py: ACCEPTED`` already
does for the one disagreement that module's own author could not resolve from the data alone.

Building-agnostic by construction: the scanner discovers predicates from whatever the active
building's own files say, and this lane only asks it which (subject, attribute) pair the
question's words land closest to -- it never names a building's own facts.
"""

from __future__ import annotations

import asyncio
import re
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

from shared.building_paths import resolve_building_dir
from shared.utils import get_logger

logger = get_logger(__name__)

#: Question-shape words that carry no content about WHICH fact is in dispute -- stripped
#: before matching a question's words against a (subject, attribute) pair's own words, so
#: "which is right" does not itself count as evidence for any subject.
_STOPWORDS = frozenset(
    "which one record source answer figure number value reading is are was were right "
    "correct accurate true wins depend depends depending differ differs who you "
    "should rely trust believe ask about the a an of for to in on at and or".split()
)

_WORD_RE = re.compile(r"[a-z][a-z']+")


def _scan_root(building_id: str) -> Optional[Path]:
    """The directory ``scripts.fact_conflicts.scan`` should walk for this building.

    Reuses the same resolver every other per-building loader uses (``documents/``'s own
    parent is the flat-or-nested input root); falls back to a directory that carries TTL
    directly, since a building with no ``documents/`` folder at all still has facts in its
    TTL to check.
    """
    docs_dir = resolve_building_dir(building_id, "documents")
    if docs_dir is not None:
        return docs_dir.parent
    for root in (Path("/app/input"), Path("input")):
        for candidate in (root / building_id, root):
            if candidate.is_dir() and any(candidate.glob("*.ttl")):
                return candidate
    return None


def _keywords(question: str) -> List[str]:
    words = _WORD_RE.findall((question or "").lower())
    return [w for w in words if len(w) >= 4 and w not in _STOPWORDS]


def _best_match(found: Dict[Tuple[str, str], Any], kws: List[str]) -> Optional[Tuple[str, str]]:
    """The (subject, attribute) key whose own words overlap the question's content words
    most -- the simplest correct thing: never guesses when overlap is zero."""
    best: Optional[Tuple[str, str]] = None
    best_score = 0
    for key in found:
        label = f"{key[0]} {key[1]}".replace("_", " ").lower()
        label_words = set(_WORD_RE.findall(label))
        score = sum(1 for w in kws if w in label_words)
        if score > best_score:
            best_score = score
            best = key
    return best


def _format_match(subject: str, attribute: str, values: Dict[str, List[Any]]) -> str:
    lines = []
    for value, facts_for_value in sorted(values.items()):
        where = "; ".join(sorted({f"{f.source}:{f.line}" for f in facts_for_value})[:4])
        lines.append(f"- **{value}** ({where})")
    body = "\n".join(lines)
    subject_words = subject.replace("_", " ")
    attribute_words = attribute.replace("_", " ")
    return (
        f"This building's own documents and registers state {subject_words} "
        f"{attribute_words} differently in different places, and nothing I hold says which "
        f"one supersedes the other:\n\n{body}\n\n"
        "The disagreement is reported rather than resolved -- a document is a statement "
        "about a record, not the record itself, so I cannot pick for you."
    )


async def answer_precedence_question(question: str, building_id: str) -> Dict[str, Any]:
    """The lane a "which source is right?" question routes to.

    Returns a dict with ``success`` and ``formatted_response`` (the standalone-lane
    convention every node in ``_orchestrator.py`` already returns) plus
    ``fact_conflict_matches`` -- 0 when nothing in the scanner's findings overlaps the
    question's words, never fabricated.
    """
    root = _scan_root(building_id)
    if root is None:
        return {
            "success": False,
            "formatted_response": (
                "I could not find this building's own documents or registers to check for a "
                "stated disagreement."
            ),
            "fact_conflict_matches": 0,
        }

    try:
        from scripts.fact_conflicts import conflicts as _conflicts
        from scripts.fact_conflicts import scan as _scan
        from scripts.fact_conflicts import split_accepted as _split_accepted

        loop = asyncio.get_event_loop()
        facts = await loop.run_in_executor(None, _scan, root)
    except Exception as exc:  # pragma: no cover - defensive; scan() itself has no known raise
        logger.warning(f"[fact_conflict] scan failed for {building_id}: {exc}")
        return {
            "success": False,
            "formatted_response": "",
            "fact_conflict_matches": 0,
        }

    found = _conflicts(facts)
    open_conflicts, accepted = _split_accepted(found)

    kws = _keywords(question)
    match = _best_match(open_conflicts, kws) or _best_match(accepted, kws)

    if match is None:
        if not open_conflicts:
            return {
                "success": True,
                "formatted_response": (
                    "I checked this building's own documents and registers and did not find "
                    "this fact stated more than once with a different value. This reflects "
                    "what is recorded -- it is not a guarantee that no disagreement exists "
                    "anywhere else."
                ),
                "fact_conflict_matches": 0,
            }
        names = sorted({f"{s}.{a}" for (s, a) in open_conflicts})[:5]
        return {
            "success": True,
            "formatted_response": (
                "I did not find that specific fact stated twice in what I hold. I do have "
                f"{len(open_conflicts)} other fact(s) stated with more than one value: "
                f"{', '.join(names)}."
            ),
            "fact_conflict_matches": 0,
        }

    subject, attribute = match
    values = (open_conflicts.get(match) or accepted.get(match)) or {}
    return {
        "success": True,
        "formatted_response": _format_match(subject, attribute, values),
        "fact_conflict_matches": len(values),
        "fact_conflict_subject": subject,
        "fact_conflict_attribute": attribute,
    }
