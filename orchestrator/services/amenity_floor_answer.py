# -*- coding: utf-8 -*-
"""A floor named in an amenity question is answered FOR THAT FLOOR, or the gap is stated (BUG-827).

WHAT WENT WRONG
---------------
    "Where are the toilets on floor 2?"
      -> the toilets on floors 0, 1 and 3, and not one word about floor 2.

The building DOES record a toilet on floor 2. Its live status says it is out of service, and the
resolver excludes an out-of-service amenity (walking to a broken fountain is a wrong answer, however
well hedged) -- correctly for the LIST, but silently. The reader was left to conclude that the
catalogue has no toilet on that floor, which is a different fact from "the one there is not working",
and a different fact again from "none is recorded, the nearest are one floor away". Three situations,
one answer: the list.

The ranking that put the asked floor first could not help: an amenity that was excluded is not in
the list to be ranked, and an amenity of another floor is not an answer to a question about this one.

WHAT THIS DOES
--------------
Given the amenities the resolver matched, the ones it withheld for being out of service, and a floor
number read from the question, it says one of three things, and only these:

* the amenities recorded on THAT floor (and which of that floor's are out of service);
* "the one on that floor is out of service", then the nearest ones that work;
* "none is recorded on that floor", then the nearest that are recorded.

It never invents a floor: an amenity whose floor is not recorded is left out of every one of these
lists rather than guessed at, and a question naming no floor returns None so the caller's ordinary
answer stands.

BUILDING-AGNOSTIC
-----------------
Nothing here names a room, a floor count or a kind of amenity. The kind is read back from the
labels the building gave its own amenities, and floors are compared as numbers.
"""

from __future__ import annotations

import re
from typing import Any, Dict, List, Optional, Sequence, Tuple

from orchestrator.services.amenity_proximity import wants_accessible
from orchestrator.services.capability_graph_resolver import _is_out_of_service
from shared.utils import get_logger

logger = get_logger(__name__)

_FLOOR_DIGITS_RE = re.compile(r"\b(?:floor|level|storey|story)\s*(-?\d+)\b", re.IGNORECASE)

#: "the second floor". British numbering, the one the building's own floor labels use
#: ("Floor 1 (First Floor)"); a building that numbers otherwise names its floors with digits.
_ORDINALS = {
    "ground": 0,
    "first": 1,
    "second": 2,
    "third": 3,
    "fourth": 4,
    "fifth": 5,
    "sixth": 6,
    "seventh": 7,
    "eighth": 8,
}
_FLOOR_ORDINAL_RE = re.compile(
    r"\b(" + "|".join(_ORDINALS) + r")\s+(?:floor|level|storey|story)\b", re.IGNORECASE
)
_ORDINAL_SUFFIX_RE = re.compile(r"\b(\d+)(?:st|nd|rd|th)\s+(?:floor|level|storey|story)\b", re.I)

#: The trailing number of a declared floor: "Floor3", "3", "Level 3". A declaration with no
#: digits (Rooftop, Basement) yields None instead of matching everything.
_DECLARED_FLOOR_RE = re.compile(r"(-?\d+)\s*$")

#: How many "nearest" amenities are named. Every one at the minimum distance, up to this many.
_NEAREST_SHOWN = 3


def floor_in_question(question: str) -> Optional[int]:
    """The floor a question names ("floor 2", "level 3", "the second floor"); None when none."""
    q = question or ""
    for rx in (_FLOOR_DIGITS_RE, _ORDINAL_SUFFIX_RE):
        m = rx.search(q)
        if m:
            return int(m.group(1))
    m = _FLOOR_ORDINAL_RE.search(q)
    return _ORDINALS[m.group(1).lower()] if m else None


def declared_floor(value: str) -> Optional[int]:
    """The floor number in an amenity's own floor declaration, or None."""
    m = _DECLARED_FLOOR_RE.search(str(value or "").strip())
    return int(m.group(1)) if m else None


def _plain(text: str) -> str:
    """A label for prose: the graph's own words, stripped of stray whitespace."""
    return re.sub(r"\s+", " ", str(text or "")).strip()


def kind_stem(label: str) -> str:
    """The kind an amenity's label opens with: 'Toilet facility — Room 2.02 …' -> 'toilet facility'."""
    head = re.split(r"\s[—–-]\s", _plain(label), maxsplit=1)[0]
    return head.strip().lower()


def _kind_phrase(question: str, pool: Sequence[Any]) -> str:
    """What to call the thing asked about: the question's own word when the building declared it."""
    low = f" {(question or '').lower()} "
    best = ""
    for fact in pool:
        for phrase in str(getattr(fact, "lay_terms", "") or "").split(","):
            p = phrase.strip().lower()
            if len(p) > len(best) and len(p) >= 4 and re.search(rf"\b{re.escape(p)}\b", low):
                best = p
    if best:
        return best
    for fact in pool:
        stem = kind_stem(getattr(fact, "label", ""))
        if stem:
            return stem
    return "match"


def _is_placeholder(fact: Any) -> bool:
    return bool(getattr(fact, "placeholder", False))


def _located(facts: Sequence[Any]) -> List[Tuple[int, Any]]:
    out: List[Tuple[int, Any]] = []
    for f in facts or []:
        n = declared_floor(getattr(f, "on_floor", ""))
        if n is not None:
            out.append((n, f))
    return out


def _prefer_surveyed(
    live: List[Tuple[int, Any]], down: List[Tuple[int, Any]]
) -> Tuple[List[Tuple[int, Any]], List[Tuple[int, Any]]]:
    """On a floor that has a record built from the building's own rooms, drop the placeholders.

    A placeholder is a position somebody filled in so the catalogue would be complete; a record
    derived from a room the building itself names is better evidence for the same floor, and the
    two side by side read as a contradiction (a toilet in a research laboratory beside a restroom).
    The out-of-service list is judged against the SAME floors, so a placeholder that is broken is
    not reported on a floor whose real restrooms work.
    """
    real_floors = {n for n, f in live + down if not _is_placeholder(f)}

    def keep(items: List[Tuple[int, Any]]) -> List[Tuple[int, Any]]:
        return [(n, f) for n, f in items if not _is_placeholder(f) or n not in real_floors]

    return keep(live), keep(down)


def _floors_phrase(numbers: Sequence[int]) -> str:
    uniq = sorted(set(numbers))
    return ", ".join(str(n) for n in uniq)


def _nearest(asked: int, items: List[Tuple[int, Any]]) -> List[Tuple[int, Any]]:
    """Every item at the smallest floor distance from the asked floor, lowest floor first."""
    if not items:
        return []
    best = min(abs(n - asked) for n, _f in items)
    near = sorted(((n, f) for n, f in items if abs(n - asked) == best), key=lambda x: x[0])
    return near[:_NEAREST_SHOWN]


def _labels(items: Sequence[Tuple[int, Any]]) -> str:
    seen: List[str] = []
    for _n, f in items:
        lab = _plain(getattr(f, "label", ""))
        if lab and lab not in seen:
            seen.append(lab)
    return "; ".join(seen)


def _nearest_line(asked: int, near: Sequence[Tuple[int, Any]], qualifier: str) -> str:
    parts = []
    for n, f in near:
        gap = abs(n - asked)
        way = "up" if n > asked else "down"
        parts.append(f"floor {n} ({gap} floor{'s' if gap != 1 else ''} {way}) — {_plain(f.label)}")
    return f"{qualifier}: " + "; ".join(parts) + "."


def floor_scoped_answer(
    question: str,
    facts: Sequence[Any],
    withheld: Sequence[Any] = (),
    asked_floor: Optional[int] = None,
) -> Optional[str]:
    """Answer an amenity question for the floor it names, or None when it names no floor.

    `facts` are the amenities the resolver matched and kept; `withheld` are the ones it matched
    and left out because they are out of service. Both need `label`, `on_floor` and `lay_terms`;
    `placeholder` is optional.
    """
    asked = asked_floor if asked_floor is not None else floor_in_question(question)
    if asked is None:
        return None
    # ACCESSIBILITY IS A DECLARED, VERIFIED FACT, and this list is built from lay terms. Every
    # ordinary toilet here carries "accessible toilet" among them so that people typing those
    # words find a toilet; answering "the accessible toilet on floor 1" with that list would tell a
    # wheelchair user an ordinary toilet is accessible. Those questions keep the lanes that read
    # the verified records (amenity_proximity, the accessible-route register).
    if wants_accessible(question):
        return None
    # A safety-critical amenity is kept in the resolver's list, flagged; here it is out of service
    # all the same, and is reported as such rather than offered as the one that works.
    broken = [f for f in facts or [] if _is_out_of_service(getattr(f, "service_status", ""))]
    live = _located([f for f in facts or [] if f not in broken])
    down = _located(list(withheld or []) + broken)
    if not live and not down:
        # Nothing here says which floor anything is on (a topic, or a catalogue without floors).
        return None
    live, down = _prefer_surveyed(live, down)
    pool = [f for _n, f in live + down]
    kind = _kind_phrase(question, pool)

    here = [(n, f) for n, f in live if n == asked]
    here_down = [(n, f) for n, f in down if n == asked]
    lines: List[str] = []

    if here:
        lines.append(f"**On floor {asked}:**")
        for _n, f in here:
            lines.append(f"- {_plain(f.label)}")
        if here_down:
            lines.append(f"\nCurrently out of service on floor {asked}: {_labels(here_down)}.")
        elsewhere = [n for n, _f in live if n != asked]
        if elsewhere:
            lines.append(f"\nAlso recorded on floor {_floors_phrase(elsewhere)}.")
        return "\n".join(lines)

    others = [(n, f) for n, f in live if n != asked]
    if here_down:
        # Worded so it reads the same whether one amenity or several is recorded there.
        lines.append(f"**Nothing recorded on floor {asked} is currently in service.**")
        lines.append(f"\nOut of service: {_labels(here_down)}.")
        if others:
            lines.append("\n" + _nearest_line(asked, _nearest(asked, others), "Nearest in service"))
        else:
            lines.append("\nNo other is recorded as in service.")
        return "\n".join(lines)

    lines.append(f"**The building records no {kind} on floor {asked}.**")
    if others:
        lines.append("\n" + _nearest_line(asked, _nearest(asked, others), "Nearest recorded"))
    else:
        lines.append("\nNone is recorded with a floor, so I cannot say which floor is nearest.")
    return "\n".join(lines)


def split_by_floor(facts: Sequence[Any]) -> Dict[int, List[Any]]:
    """Facts grouped by the floor they declare; unlocated facts are omitted."""
    out: Dict[int, List[Any]] = {}
    for n, f in _located(facts):
        out.setdefault(n, []).append(f)
    return out


def capability_answer(
    question: str,
    facts: Sequence[Any],
    withheld: Sequence[Any],
    building_name: str,
) -> Optional[Dict[str, Any]]:
    """The capability lane's result for a floor-scoped answer; None when the question names no floor."""
    text = floor_scoped_answer(question, facts, withheld)
    if not text:
        return None
    return {
        "success": True,
        "response": text + "\n\n*Answered live from the building's own records.*",
        "provenance": "capability_graph",
        "building_name": building_name,
    }
