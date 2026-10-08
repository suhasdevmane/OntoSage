# -*- coding: utf-8 -*-
"""facet_routing.py -- does this question need several facets of the building at once? (v2, P6)

WHY THIS EXISTS
---------------
Every v1 lane but one answers ONE facet: a reading, a register, a booking store. A question that
combines them -- "a quiet room for twelve with a projector, free this afternoon" -- reached
whichever lane its loudest word pointed at and was answered in part: the register lane found the
workspace register for one criterion and declined the rest. The plan (tasks/V2_COMPOUND_PLAN.md
4.6) is to ESCALATE such a question to the deliberation lane, decided after facet retrieval,
not by keywords, and first in shadow mode.

This module makes that decision from the active building's facet catalogue (``facets.py``) and
nothing else: no building's words, classes or counts. The routing contract owns WHEN it is asked
(``routing_contract._r_compound_facets_to_deliberate``); this module owns WHAT it answers.

WHAT COUNTS AS A COMPOUND QUESTION -- the rule, and the measurement behind each part
------------------------------------------------------------------------------------
A question escalates when, after its time window and place references are set aside:

  1. it SELECTS SPACES -- "which ... room", "find me a ... space", "where can I ...", "is there
     a ... area" (``SPACE_SELECTION_RE``); and
  2. at least TWO CRITERIA survive, where a criterion is a set of question words that reach
     suitable space facets, and facets reached through the same word are ONE criterion ("quiet"
     reaching both the noise sensor and a register's noise profile is one thing asked twice);
  3. the criteria come from at least two distinct SOURCES -- two source kinds (a sensor and a
     register), or two registers. Two columns of one register are one source: the register lane
     answers them in one read, by design.

MEASURED, offline, before it was trusted: the first parked building's catalogue (386 facets)
and the second's (77), over the development split (2,477 stakeholder questions), the
73-question supervisor evidence pack (51 of them the regression gate) and the 4,060-question
bank minus its 42 held-out rows. Moves, first building, DEV / gate / bank:

  * the literal first cut -- >= 2 suitable facets from >= 2 source kinds, or >= 2 facets and a
    selection word -- 1,546 / 21 / 2,278. Retrieval is built to RANK candidates for a compiler
    prompt and credits every word that touches a facet: "the next 24 hours" reached a
    work-order "hours" column at 7.79, above CO2 at 4.86, and "What is the CO2 level in room
    5.01?" became compound. A score threshold alone (5.0) still moved 7 gate cases and cut the
    projector first;
  * space facets only, scope set aside, the evidence-quality rules below: 753 / 4 / 959;
  * a register's single word counting only when the register is named: 299 / 2 / 379 -- and a
    hand read of 30 found 5 to 7 right: several facets named inside an audit, a scenario or a
    judgement do not make a selection;
  * requiring the question to SELECT SPACES (part 1): 81 / 1 / 103, about 1 in 6 wrong;
  * this module as shipped: 56 / 2 / 70 (second building 24 / 2 / 29). A seeded hand read of 15
    DEV and 10 bank moves found 23 right; the two gate cases are already answered by the
    deliberation lane, so no gate route changes.

EVIDENCE QUALITY -- each a property of how a term was made, never a word list about a building
---------------------------------------------------------------------------------------------
  * class vocabulary never counts: it says which register, not which field;
  * a one-word term made from a longer phrase counts only when the whole phrase is in the
    question: "in use" became the term "use" (324 spurious criteria in one measurement), "after
    hours" became "hours", "Common room" became "common";
  * an enum value counts only WHOLE ("Projector"), not one word inside a longer value;
  * a unit counts only as a quantity ("twelve PEOPLE"), and a time unit only as the length of a
    route ("within five MINUTES") -- otherwise it is the question's time window;
  * a register's single-word evidence counts only when the question names that register, and a
    word every facet of a register carries ("route" on every route fact) is the register's name;
  * a criterion whose every word is generic time, schedule, degree or status vocabulary
    (``_GENERIC_WORDS``) is dropped: "late" reaches a quietest-period value, "strongest option"
    a network rating -- neither is a facet the asker named.
"""

from __future__ import annotations

import asyncio
import bisect
import re
import weakref
from dataclasses import dataclass
from typing import Dict, FrozenSet, List, Optional, Sequence, Set, Tuple

from orchestrator.services.deliberation.facets import (
    TARGET_NOUNS,
    Facet,
    FacetCatalogue,
    TermMatch,
    build_facet_catalogue,
    cached_catalogue,
    content_words,
    facet_vocabulary,
    plain_words,
)
from shared.utils import describe_exception, get_logger

logger = get_logger(__name__)

#: The three rollout stages of ARBITER_V2_ROUTING.
MODES: Tuple[str, ...] = ("off", "shadow", "live")

#: Facets reached at or below this share of the catalogue's ``unique_word_weight`` are not
#: criteria. RELATIVE, not a fixed score, because retrieval scores are inverse document
#: frequencies and grow with the catalogue: a word only one facet carries weighs 5.27 on the
#: first parked building (386 facets), 3.68 on the second (77) and about 2 on a dozen-facet test
#: catalogue -- a fixed bar of 1.5 that suited the first building silently disabled the rule on
#: the test one, where a projector record scored about 1.3.
#:
#: CHOSEN BY MEASUREMENT over both parked buildings, the development split and the bank (see the
#: module docstring): the moved sets do not change anywhere from 0 to 0.35 on the first building
#: or from 0 to 0.8 on the second. Above that every lost move was a right one -- first a space
#: type plus one condition ("which study areas have the lowest PM2.5", 0.397 of the unique-word
#: weight, an enum value being weighted at half), then the projector, display and capacity
#: criteria. 0.2 is the middle of the plateau the two buildings share: evidence counts when it
#: weighs more than a fifth of a word only one facet carries.
MIN_RELATIVE_SCORE: float = 0.2

#: The facet types a deliberation answer ranks: spaces. A fact about the building as a whole or
#: about a record's own route is not a criterion a space can be filtered on.
_TARGET_ENTITY = "space"

#: Facets that SCOPE a question rather than filter it: "on floor 3" narrows where to look and the
#: deliberation lane already reads it as a spatial qualifier.
_SCOPE_FACETS: FrozenSet[str] = frozenset({"spatial:floor"})

_NUMBER = (
    r"(?:\d+(?:\.\d+)?|a|an|one|two|three|four|five|six|seven|eight|nine|ten|eleven|twelve|"
    r"fifteen|twenty|thirty|forty|forty-eight|half\s+an?|couple\s+of|few)"
)
_TIME_UNIT = r"(?:hours?|hrs?|minutes?|mins?|days?|weeks?|months?|years?)"

#: A time window: the question's WHEN, which the plan's time spec owns, never a facet.
TIME_WINDOW_RE = re.compile(
    r"\b(?:over|during|in|for|across|within)?\s*(?:the\s+)?"
    r"(?:next|last|past|previous|coming|following|recent)\s+(?:"
    + _NUMBER
    + r"\s+)?"
    + _TIME_UNIT
    + r"\b"
    r"|\b(?:hourly|daily|weekly|monthly|annually|yearly)\b"
    r"|\b" + _NUMBER + r"[-\s]" + _TIME_UNIT + r"\s+(?:ago|window|period|average|mean|rolling)\b",
    re.IGNORECASE,
)

#: A named place: "room 5.01", "floor 3", "floors 1 and 3", "each floor". The question's WHERE.
PLACE_REF_RE = re.compile(
    r"\b(?:floor|level|storey|room|rm|zone)\s*\d+(?:\.\d+)?\b"
    r"|\b(?:floors?|levels?|storeys?)\s+\d+\s*(?:and|or|to|vs\.?|versus|against|-)\s*\d+\b"
    r"|\b[a-z]{0,6}\d{1,2}\.\d{1,3}\b"
    r"|\b(?:ground|first|second|third|fourth|fifth|top|basement)\s+floor\b"
    r"|\b(?:each|every|per|by)\s+floor\b",
    re.IGNORECASE,
)

#: The nouns a selection over SPACES is phrased with -- generic English. Seats, zones and
#: locations are left out on measurement: "which verified seats should we offer" chooses seats
#: in a room, and "which zones / reported locations show ..." were analysis questions every time.
_SPACE_NOUN = (
    r"(?:rooms?|spaces?|places?|areas?|spots?|desks?|offices?|labs?|workspaces?|"
    r"workstations?|venues?|studios?|pods?)(?![\w-])"
)
#: A verb between "which/what" and the noun makes it a question ABOUT something else: "what do
#: current room measurements show" is not a choice of room.
_AUXILIARY = (
    r"(?:is|are|was|were|do|does|did|can|could|should|would|will|has|have|had|must|may|might)\b"
)

#: One modifier before the space noun, a comma allowed after it: "a quiet, well-lit room".
_MODIFIER = r"[\w'-]+,?\s+"
#: "what is the area OF room 3.50" is a measure, not a place to choose.
_NOT_A_MEASURE = r"(?!\s+of\b)"

#: The question CHOOSES spaces: the operation the deliberation lane exists for.
SPACE_SELECTION_RE = re.compile(
    r"\b(?:which|what)\s+(?:(?!" + _AUXILIARY + r")" + _MODIFIER + r"){0,4}?" + _SPACE_NOUN
    # "what is the quietest study area I can reach" -- the superlative form of the same choice
    + r"|\bwhat(?:'s|\s+is|\s+are)\s+the\s+(?:"
    + _MODIFIER
    + r"){0,4}?"
    + _SPACE_NOUN
    + _NOT_A_MEASURE
    + r"|\b(?:find|recommend|suggest|book|reserve|need|want|choose|pick|looking\s+for)\s+"
    r"(?:me\s+|us\s+)?(?:a|an|the|some|any|one)\s+(?:"
    + _MODIFIER
    + r"){0,4}?"
    + _SPACE_NOUN
    + r"|\bwhere\s+(?:can|should|could|would|might|do)\s+(?:i|we)\s+\w+"
    r"|\b(?:is\s+there|are\s+there)\s+(?:a|an|any)\s+(?:"
    + _MODIFIER
    + r"){0,3}?"
    + _SPACE_NOUN
    + r"|\bany\s+(?:"
    + _MODIFIER
    + r"){0,3}?"
    + _SPACE_NOUN
    + r"|\b(?:best|ideal|most\s+suitable)\s+(?:"
    + _MODIFIER
    + r"){0,2}?"
    + _SPACE_NOUN,
    re.IGNORECASE,
)

#: Words that never name a criterion ON THEIR OWN: time and schedule, degree and rating levels,
#: and the status words registers record. A criterion keeps them when another word carries it
#: ("low noise", "stable temperature"); one made of nothing else is dropped. Generic English, in
#: the canonical (singular) form retrieval compares; each measured as a spurious criterion. Time
#: UNITS are not here: `_counts` already admits one only as a route's length ("within five
#: minutes"), and listing them here as well discarded exactly that criterion.
_GENERIC_WORDS: FrozenSet[str] = frozenset(
    content_words(
        """early earlier earliest late latest last past previous recent first
        final start end due shift period time timing scheduled
        high low medium moderate strong strongest weak poor fair excellent adequate acceptable
        reasonable normal typical usual stable steady
        open closed active inactive current verified confirmed approved required complete
        completed pending planned valid expired"""
    )
)

#: Time units, in the canonical form; a time unit names a criterion only as a route's length.
_TIME_UNITS: FrozenSet[str] = frozenset(
    content_words("hour hours minute minutes min mins second seconds day days week weeks")
)

#: "X-free" means WITHOUT X: "step-free" is no step, not a free room. Retrieval reads the tokens
#: "step" and "free" apart, so where the building has no step-free facet to take both words
#: together, "free" alone reached occupancy and availability as a criterion. Measured on the
#: second parked building, which has no route records: 3 of its development-split moves rested
#: on that "free" and nothing else as their second criterion.
_FREE_SUFFIX_RE = re.compile(r"(?<=[a-z0-9])-free\b", re.IGNORECASE)
_STANDALONE_FREE_RE = re.compile(r"(?<![\w-])free\b", re.IGNORECASE)

#: A LIMIT on a journey's length -- "within five minutes", "under 10 mins". Without one, a time
#: quantity is how long something lasts ("rehearse for 90 minutes"), not how far a space is.
_ROUTE_LIMIT_RE = re.compile(
    r"\b(?:within|under|less\s+than|no\s+more\s+than|at\s+most)\s+" + _NUMBER + r"[-\s]"
    r"(?:minutes?|mins?)\b",
    re.IGNORECASE,
)


@dataclass(frozen=True)
class Criterion:
    """Question words that reach the same suitable space facets: one thing the asker wants."""

    words: Tuple[str, ...]
    #: The facets those words reach, best retrieval score first.
    keys: Tuple[str, ...]
    kinds: FrozenSet[str]
    #: (source kind, record class or facet key): two columns of one register are one source.
    sources: FrozenSet[Tuple[str, str]]
    score: float


@dataclass(frozen=True)
class CompoundSignal:
    """Why a question needs several facets at once."""

    criteria: Tuple[Criterion, ...]
    kinds: FrozenSet[str]
    #: "kinds" when the criteria span two source kinds, "sources" when two registers (or two
    #: modalities) of one kind.
    reason: str

    @property
    def facet_keys(self) -> List[str]:
        """The best facet of each criterion, in question order -- what the shadow log names."""
        return [c.keys[0] for c in self.criteria]


def scope_text(question: str) -> str:
    """The question without its time window and named places, which are scope, not criteria."""
    return PLACE_REF_RE.sub(" ", TIME_WINDOW_RE.sub(" ", question or ""))


def selects_spaces(question: str) -> bool:
    """True when the question CHOOSES spaces, read after its named places are set aside."""
    return bool(SPACE_SELECTION_RE.search(scope_text(question)))


#: {(source kind, record class): the words every facet of that register carries}.
_RegisterWords = Dict[Tuple[str, str], FrozenSet[str]]

#: Per catalogue, held WEAKLY and keyed by the catalogue itself: an id() key outlives a rebuilt
#: catalogue, and the next object to reuse that address would read another catalogue's words.
_CLASS_WORDS: "weakref.WeakKeyDictionary[FacetCatalogue, _RegisterWords]" = (
    weakref.WeakKeyDictionary()
)


def _register_words(catalogue: FacetCatalogue) -> _RegisterWords:
    """Single-word own terms shared by EVERY facet of a register: its name, not a field's."""
    cached = _CLASS_WORDS.get(catalogue)
    if cached is not None:
        return cached
    groups: Dict[Tuple[str, str], List[Set[str]]] = {}
    for facet in catalogue:
        if not facet.record_class:
            continue
        words: Set[str] = set()
        for tier, text in facet_vocabulary(facet):
            terms = content_words(text)
            if tier == "own" and len(terms) == 1:
                words.add(terms[0])
        groups.setdefault((facet.source_kind, facet.record_class), []).append(words)
    out = {
        group: frozenset(set.intersection(*sets))
        for group, sets in groups.items()
        if len(sets) >= 2
    }
    _CLASS_WORDS[catalogue] = out
    return out


def _reduced_and_absent(match: TermMatch, question_text: str) -> bool:
    """A one-word term cut down from phrases whose dropped words carried meaning, none present.

    Dropping a phrase's function words is right for RANKING ("step free" from "is step free"),
    and wrong for deciding what was NAMED: "use" is not "in use", "hours" is not "after hours",
    "zone" is not a cleaner's "my zone". A phrase that lost only the noun naming the space itself
    keeps its meaning -- a "desk space" is a desk, a "quiet room" is a quiet one -- so it still
    counts; measured, requiring those verbatim cost 11 right development-split moves for 3 wrong.
    """
    if len(match.words) != 1 or not match.phrases:
        return False
    for phrase in match.phrases:
        words = phrase.split()
        if len(words) == 1:
            return False  # a genuine one-word term
        dropped = [w for w in words if not content_words(w)]
        if all(w in TARGET_NOUNS for w in dropped):
            return False  # only the space's own noun was dropped
        if f" {phrase} " in question_text:
            return False
    return True


def _counts(
    match: TermMatch,
    facet: Facet,
    question_text: str,
    named: Set[str],
    register_words: Dict[Tuple[str, str], FrozenSet[str]],
    route_limit: bool,
) -> bool:
    """Whether one term match is evidence of a CRITERION (see the module docstring)."""
    if match.tier in ("class", "value_word"):
        return False
    single = len(match.words) == 1
    if match.tier == "unit":
        if not match.quantity:
            return False
        if match.words[0] in _TIME_UNITS and not (facet.source_kind == "spatial" and route_limit):
            return False
    elif single and match.words[0] in _TIME_UNITS:
        return False
    if _reduced_and_absent(match, question_text):
        return False  # a one-word term cut down from a phrase: only the phrase names the facet
    if single and facet.record_class:
        if match.tier == "own" and match.words[0] in register_words.get(
            (facet.source_kind, facet.record_class), frozenset()
        ):
            return False
        if facet.source_kind == "record" and facet.record_class not in named:
            return False
    return True


def compound_signal(
    question: str,
    catalogue: Optional[FacetCatalogue],
    *,
    min_relative_score: float = MIN_RELATIVE_SCORE,
) -> Optional[CompoundSignal]:
    """Why ``question`` needs several facets of the building at once -- or None.

    Pure and deterministic: the same question and catalogue always give the same answer, and
    no store is read. A question that does not select spaces returns None before retrieval.
    """
    if catalogue is None or not question or not question.strip():
        return None
    scoped = scope_text(question)
    if not SPACE_SELECTION_RE.search(scoped):
        return None
    min_score = min_relative_score * catalogue.unique_word_weight
    retrieved = {
        facet.key: score
        for score, facet in catalogue.retrieve(
            scoped, k=len(catalogue), min_score=min_score, min_status="suitable"
        )
        if facet.entity_type == _TARGET_ENTITY and facet.key not in _SCOPE_FACETS
    }
    if len(retrieved) < 2:
        return None
    matches = catalogue.term_matches(scoped)
    question_text = " " + " ".join(plain_words(scoped)) + " "
    # The registers the question NAMES through their class vocabulary -- by a whole phrase: "my
    # zone" is a cleaning-register phrase that reduces to "zone", and "which desk ZONE" named the
    # cleaning register through it until this rule applied to naming as well as to fields.
    named: Set[str] = set()
    for m in matches:
        facet = catalogue.get(m.key)
        if m.tier == "class" and facet is not None and facet.record_class:
            if not _reduced_and_absent(m, question_text):
                named.add(facet.record_class)
    register_words = _register_words(catalogue)
    route_limit = bool(_ROUTE_LIMIT_RE.search(scoped))
    where: Dict[str, Set[int]] = {}
    said: Dict[str, Set[str]] = {}
    for m in matches:
        facet = catalogue.get(m.key)
        if m.key not in retrieved or facet is None:
            continue
        if not _counts(m, facet, question_text, named, register_words, route_limit):
            continue
        where.setdefault(m.key, set()).update(m.positions)
        said.setdefault(m.key, set()).update(m.words)
    generic = _GENERIC_WORDS
    if _FREE_SUFFIX_RE.search(scoped) and not _STANDALONE_FREE_RE.search(scoped):
        generic = generic | frozenset(content_words("free"))  # only "X-free": not availability
    criteria = _criteria(catalogue, retrieved, where, said, generic)
    if len(criteria) < 2:
        return None
    kinds = frozenset().union(*(c.kinds for c in criteria))
    sources = frozenset().union(*(c.sources for c in criteria))
    if len(sources) < 2:
        return None  # two columns of one register: the register lane answers them in one read
    return CompoundSignal(
        criteria=tuple(criteria),
        kinds=kinds,
        reason="kinds" if len(kinds) >= 2 else "sources",
    )


def _criteria(
    catalogue: FacetCatalogue,
    retrieved: Dict[str, float],
    where: Dict[str, Set[int]],
    said: Dict[str, Set[str]],
    generic: FrozenSet[str],
) -> List[Criterion]:
    """Group facets reached through shared question words; drop the all-generic groups."""
    keys = sorted(where)
    parent = {k: k for k in keys}

    def root(k: str) -> str:
        while parent[k] != k:
            parent[k] = parent[parent[k]]
            k = parent[k]
        return k

    for i, a in enumerate(keys):
        for b in keys[i + 1 :]:
            if where[a] & where[b]:
                parent[root(a)] = root(b)
    groups: Dict[str, List[str]] = {}
    for k in keys:
        groups.setdefault(root(k), []).append(k)
    out: List[Tuple[int, Criterion]] = []
    for members in groups.values():
        words = sorted(set().union(*(said[k] for k in members)))
        if all(w in generic for w in words):
            continue
        ranked = sorted(members, key=lambda k: (-retrieved[k], k))
        facets = [catalogue.get(k) for k in ranked]
        out.append(
            (
                min(min(where[k]) for k in members),
                Criterion(
                    words=tuple(words),
                    keys=tuple(ranked),
                    kinds=frozenset(f.source_kind for f in facets),
                    sources=frozenset((f.source_kind, f.record_class or f.key) for f in facets),
                    score=retrieved[ranked[0]],
                ),
            )
        )
    return [criterion for _, criterion in sorted(out, key=lambda pair: pair[0])]


# ── operations v1 has no lane for: group -> aggregate -> rank (C3), measured vs declared (C2) ──
#
# WHY A SECOND SIGNAL. `compound_signal` escalates a question that CHOOSES spaces on several
# facets (C1). A ranking of FLOORS or of KINDS of room chooses no space, and a comparison of what
# a room holds with what it is declared to hold is not a selection either -- so neither reached
# the operations the deliberation lane gained in P4 (`operations.py`). Measured live on the v1
# build, 2026-10-08, the lanes they did reach were wrong in four distinct ways:
#
#   * "Which floor has the most people in it right now?" -- the compare lane ranked floors by the
#     MEAN reading per sensor and named Floor 0 (1.8 a sensor, 18 sensors) over Floor 5 (1.6, 54
#     sensors): the opposite of their totals. People add up; the lane averaged them.
#   * "Which kind of room is the warmest on average today?" -- ranked individual rooms.
#   * "Which floor has the most meeting rooms?" -- pasted a booking policy document.
#   * "Are any meeting rooms over their seating capacity right now?", "How does the number of
#     people on each floor compare with its capacity?" -- declined: "no current occupancy", "no
#     measured series", while 233 spaces carry an occupancy series.
#
# What it deliberately leaves alone, because v1 answers it well (same probe): a LEVEL ranked across
# floors ("which floor is warmest" -- a mean per floor is the right figure), and two named periods
# ("this week against last week" -- the compare lane reads both whole and says so). And in the
# contract, "how evenly / how uniform" questions stay with v1's own `uniformity_is_a_comparison`
# rule (a shape owner `_compound_shape_owned_elsewhere` defers to): measured live, its per-floor
# table with the building's range answers them acceptably, so a dispersion reaches this lane only
# in forms that rule does not own ("the largest gap between its warmest and coolest room"). So C3 escalates
# only for an amount that adds up, a grouping by kind of room, a question about how evenly
# something is spread, or a count of spaces of a kind; C2 only when a measured figure is set
# against a declared one.

#: The question ranks or totals GROUPS of spaces by floor. Generic English.
_FLOOR_GROUP_RE = re.compile(
    r"\b(?:which|what)\s+(?:floor|level|storey)s?\b"
    r"|\b(?:per|each|every|by)\s+(?:floor|level|storey)\b"
    r"|\bacross\s+(?:the\s+|all\s+(?:the\s+)?|its\s+)?(?:floors|levels|storeys)\b"
    r"|\bfloor[\s-]by[\s-]floor\b|\bbetween\s+(?:the\s+)?floors\b",
    re.IGNORECASE,
)
#: ...or by KIND of room.
_KIND_GROUP_RE = re.compile(
    r"\b(?:which|what)\s+(?:kinds?|types?|sorts?)\s+of\s+(?:rooms?|spaces?|areas?)\b"
    r"|\b(?:per|each|every|by)\s+(?:kind|type)\s+of\s+(?:rooms?|spaces?)\b"
    r"|\b(?:per|each|every|by)\s+(?:room|space)\s+(?:types?|kinds?)\b"
    r"|\b(?:room|space)\s+(?:types|kinds)\b",
    re.IGNORECASE,
)
#: The answer is a figure per group, compared: an extreme, a count, a total, or how even it is.
#: "-iest" covers the superlatives of every "-y" adjective at once (busiest, noisiest, stuffiest).
_AGGREGATE_CUE_RE = re.compile(
    r"\b(?:most|fewest|least|highest|lowest|largest|smallest|biggest|quietest|warmest|coolest|"
    r"coldest|hottest|loudest|brightest|darkest|fullest|best|worst|more|fewer|less|total|overall|"
    r"rank(?:ed|ing)?|compare[sd]?|comparison|average)\b|\b[a-z]+iest\b"
    r"|\bhow\s+(?:many|much|evenly)\b|\bnumber\s+of\b",
    re.IGNORECASE,
)
#: How evenly a figure is spread: a dispersion, which no v1 lane computes.
_DISPERSION_RE = re.compile(
    r"\bhow\s+(?:evenly|uniformly|consistently|equally)\b"
    r"|\b(?:spread|variation|variability|disparity|imbalance|unevenly|uneven|uniform|uniformly)\b"
    r"|\b(?:vary|varies|differ|differs)\s+(?:between|across|from)\b"
    r"|\b(?:even|consistent)\s+across\b"
    r"|\bgap\s+between\s+(?:its|their|the)\s+\w+est\b",
    re.IGNORECASE,
)
#: A dispersion may be asked over the building's spaces as one group: "across the building",
#: "across areas". Only for a dispersion -- "the temperature across the building" alone is a
#: level the v1 lanes already give.
_ACROSS_SPACES_RE = re.compile(
    r"\b(?:across|throughout|over)\s+(?:the\s+|all\s+(?:the\s+)?|its\s+)?"
    r"(?:building|areas|rooms|spaces|zones|wings)\b",
    re.IGNORECASE,
)
#: A count of SPACES of some kind per group: "the most meeting rooms", "how many study rooms".
_COUNTED_SPACES_RE = re.compile(
    r"\b(?:most|fewest|least|more|fewer|how\s+many|number\s+of)\s+(?:[\w-]+\s+){0,2}?"
    r"(?:rooms|spaces|labs|laboratories|offices|study\s+areas|seminar\s+rooms)\b",
    re.IGNORECASE,
)
#: A measured figure set AGAINST a declared one: "over their seating capacity", "versus capacity".
_DECLARED_WORDS = (
    r"(?:capacity|capacities|limit|limits|setpoints?|set\s+points?|targets?|budgets?|design|"
    r"rated|stated|maximum|max|allowance)"
)
_VERSUS_RE = re.compile(
    r"\b(?:versus|vs\.?|against|relative\s+to|compared?\s+(?:with|to)|in\s+relation\s+to)\b"
    r"|\b(?:over|above|below|under|exceeds?|exceeding|exceeded|within|beyond|more\s+than|"
    r"less\s+than|fewer\s+than)\s+(?:(?:its|their|the|a|an)\s+)?(?:[\w-]+\s+){0,2}?"
    + _DECLARED_WORDS
    + r"\b"
    # "more PEOPLE than their capacity": the counted noun sits between the two halves
    r"|\b(?:more|fewer|less)\s+(?:[\w-]+\s+){1,2}than\s+(?:(?:its|their|the|a|an)\s+)?"
    r"(?:[\w-]+\s+){0,2}?" + _DECLARED_WORDS + r"\b",
    re.IGNORECASE,
)
#: A future figure is the forecast lane's; two named periods are the compare lane's (it reads
#: both whole). Neither is taken.
_FUTURE_RE = re.compile(
    r"\b(?:tomorrow|next\s+(?:week|month|hour|day)|will\s+(?:be|have)|forecast|predict\w*|"
    r"expected\s+to|going\s+to)\b",
    re.IGNORECASE,
)
_TWO_PERIODS_RE = re.compile(
    r"\b(?:this|last|previous)\s+(?:week|month|year)\b.*\b(?:than|versus|vs\.?|against|"
    r"compared\s+(?:with|to))\b.*\b(?:this|last|previous)\s+(?:week|month|year)\b"
    r"|\btoday\b.*\byesterday\b|\byesterday\b.*\btoday\b"
    r"|\bweekdays?\b.*\bweekends?\b|\bweekends?\b.*\bweekdays?\b",
    re.IGNORECASE | re.DOTALL,
)


@dataclass(frozen=True)
class OperationSignal:
    """Why a question needs a v2 operation that no v1 lane computes."""

    #: "C3" (group -> aggregate -> rank), "C2" (a measured figure against a declared one) or "C5"
    #: (a measured series related to recorded events or to a second series).
    shape: str
    #: additive | room_kind | dispersion | counted_spaces | measured_vs_declared | events | state |
    #: series
    reason: str
    facet_keys: Tuple[str, ...]


# ── a measured series related to recorded events or to a second series (C5) ─────────────────
#
# WHY A THIRD SIGNAL. "Is CO2 higher during timetabled sessions?", "does noise rise after access
# events?", "when occupancy goes up, does CO2 follow?" relate one measured series to something
# else in the same spaces. No v1 lane computes that (tasks/V2_COMPOUND_PLAN.md section 2: C5 ->
# none -> decline), and a selection or a ranking it is not, so neither signal above can see it.
#
# THE RULE, each part a property of the question and the building's catalogue, never a building's
# words:
#   1. a RELATION cue -- "during", "while", "after", "following", "whenever" (an event cue), or
#      "correlat*", "relationship", "related to", "associated with", "move together", "rises
#      with", "when X goes up" (a co-movement cue) -- and no forecast, no two named periods (those
#      are C4's, and v1's compare lane reads them whole), no question asking for a MOMENT ("when
#      is ...", "what time ...");
#   2. a SENSOR facet the question names, by the evidence rules the C1 signal uses; and
#   3. what it is related to, each INTRODUCED by its cue (within ``RELATION_REACH`` content words)
#      and named apart from the measured series: an EVENT SOURCE the catalogue holds (a whole term
#      of the source's own vocabulary), or a yes/no SENSOR ("while the window is open"), or a
#      measured sensor the clause predicates ("when it IS busy"); or, with a co-movement cue, a
#      SECOND sensor anywhere.
#
# MEASURED, offline, before it was trusted: the catalogue ``build_facet_catalogue`` derives from
# the parked first building's own files (rdflib, no reasoning; 391 facets, 5 of them event
# sources -- 675 timetabled sessions in 44 rooms, 16 bookings in 6, 17 public events in 5, access
# and alarm events placed in 2 rooms and 1) -- NOT the live GraphDB catalogue; re-measure there.
# Fires, by set:
#   * the 73-question supervisor pack: 1 -- #25, "rooms where the CO2 rises while occupancy stays
#     flat", the plan's own C5 example and the pack case v1 declined;
#   * the development split (2,477): 6, every one hand-read: 4 relations (a reading while a space
#     is empty or unoccupied, twice; CO2 after a seminar; what happens while windows are open), 1
#     relation asked as a forecast (noise when the lecture begins), 1 route question, which the
#     route rule owns and the escalation stands down for. The windows question is stood down too,
#     by the actuation rule's "open windows" -- a v1 rule this signal does not override;
#   * the labelled development sample: of its 8 C5 items 1 fires (the windows question). The other
#     7 ask for an ADJUSTED comparison (net of weather, season, timetable or concurrent changes),
#     or relate records that are not on the clock, or name no held series -- none of which a
#     two-variable co-occurrence answers, so the signal leaves them; none of its 8 NC:SINGLE
#     controls fires;
#   * the 4,060-question bank minus its 42 held-out rows: 7 (counts only, never read), 2 of them
#     stood down by an owning rule.
#   In all four sets 0 questions with a C2 or C3 signal now get a C5 one, and 0 carry the C1
#   signal (which the routing rule checks first).
# Two wider cuts were measured on the development split and REJECTED:
#   * a cue anywhere and any facet named anywhere: 40 fires, 26 through a yes/no state -- "keeping
#     an authorised workspace AVAILABLE", "STEP-FREE breaks while ..." reached the occupancy facets
#     through availability words. Hence RELATION_REACH, _AVAILABILITY_WORDS and the X-free rule;
#   * any MEASURED reading a cue introduces, read as a state: +4 fires, 2 wrong and 2 routes ("while
#     still meeting reasonable ventilation, temperature ...", "when are CO2 or temperature most
#     likely to worsen"). Hence _PREDICATED_STATE_RE.
# A known gap: "when the room is OCCUPIED" does not fire on that building, because none of its
# vocabulary carries the bare word (only "currently occupied", "is the room occupied"). That is a
# lay term the ontology could declare, not a word this module should invent.
_EVENT_CUE_RE = re.compile(
    r"\b(?:during|while|whilst|throughout|after|afterwards|following|whenever|when)\b",
    re.IGNORECASE,
)
_MOVEMENT = (
    r"(?:ris(?:e|es|ing)|rose|increas(?:e|es|ed|ing)|go(?:es)?\s+up|went\s+up|climb(?:s|ed|ing)?|"
    r"fall(?:s|ing)?|fell|drop(?:s|ped|ping)?|decreas(?:e|es|ed|ing)|go(?:es)?\s+down|went\s+down|"
    r"spik(?:e|es|ed|ing)|peak(?:s|ed|ing)?|stay(?:s|ed)?\s+(?:flat|level|steady|the\s+same)|"
    r"chang(?:e|es|ed|ing))"
)
_SERIES_CUE_RE = re.compile(
    r"\bcorrelat\w*|\brelationship\b|\brelated\s+to\b|\brelat(?:e|es|ing)\s+(?:to|with)\b"
    r"|\bassociat\w*\s+with\b|\bco-?var\w*|\bco-?mov\w*|\bmove\s+together\b|\bin\s+step\s+with\b"
    r"|\b(?:when|whenever|as|while|whilst|if)\s+(?:the\s+)?(?:[\w-]+\s+){1,4}?" + _MOVEMENT + r"\b"
    r"|\b" + _MOVEMENT + r"\s+(?:when|whenever|as|while|whilst|with|along\s+with)\b"
    r"|\b(?:affect|affects|affected|impact|impacts|influence|influences|influenced)\b"
    r"|\beffect\s+(?:of|on)\b",
    re.IGNORECASE,
)
#: "While the window is open", "when the room is occupied": a yes/no reading's ON state.
_STATE_CUE_RE = re.compile(r"\b(?:while|whilst|when|whenever|during)\b", re.IGNORECASE)
#: The question asks for a MOMENT, not a relation: "when is CO2 highest", "what time does it peak".
_ASKS_A_MOMENT_RE = re.compile(
    r"^\s*(?:when\s+(?:is|are|am|was|were|does|do|did|will)\b|what\s+time\b|at\s+what\s+time\b"
    r"|which\s+(?:day|days|hour|hours|time|times)\b)",
    re.IGNORECASE,
)
#: How many content words after its cue the event or the state may start: "during LECTURES",
#: "while the WINDOW is open", "while this office is estimated to be EMPTY". Further away, the cue
#: belongs to another clause ("available during our shift", "when was the alarm last tested").
RELATION_REACH = 3
#: Words that name whether a space can be USED, never a measured quantity: a series named only by
#: one of them is not a series the question asks about ("keeping a workspace available").
_AVAILABILITY_WORDS: FrozenSet[str] = frozenset(content_words("available unavailable availability"))
#: A MEASURED reading stands in for a state only when the clause PREDICATES it: "when it IS busy",
#: "while they ARE crowded". Without the verb a list of quantities after "while" is read as a state
#: ("while still meeting reasonable ventilation, temperature ..." -- measured, not relational), and
#: with no subject before it the clause asks for a moment ("when are CO2 levels highest").
_PREDICATED_STATE_RE = re.compile(
    r"\b(?:while|whilst|when|whenever)\s+(?:[\w'-]+\s+){1,3}?"
    r"(?:is|are|was|were|gets?|got|becomes?|became|feels?|seems?|stays?)\s+"
    r"(?:(?:very|too|so|quite|really|still|getting|more|less|most|least)\s+)?(?P<state>[\w'-]+)",
    re.IGNORECASE,
)


def _cue_starts(text: str, pattern: "re.Pattern") -> List[int]:
    """For each cue, the position (among the question's CONTENT words, as ``TermMatch.positions``
    counts them) of the first content word after it."""
    from orchestrator.services.deliberation.facets import _TOKEN_RE, _is_content

    content_starts = [
        m.start()
        for m in _TOKEN_RE.finditer((text or "").lower())
        if _is_content(m.group(0).replace(".", ""))
    ]
    return [bisect.bisect_left(content_starts, cue.end()) for cue in pattern.finditer(text or "")]


def _named_space_matches(
    scoped: str, catalogue: FacetCatalogue
) -> Dict[str, Tuple[Facet, List[TermMatch]]]:
    """``_named_space_facets`` with the evidence itemised: every counted match, per facet."""
    keys = {f.key for f in _named_space_facets(scoped, catalogue)}
    if not keys:
        return {}
    question_text = " " + " ".join(plain_words(scoped)) + " "
    named: Set[str] = set()
    matches = catalogue.term_matches(scoped)
    for m in matches:
        facet = catalogue.get(m.key)
        if m.tier == "class" and facet is not None and facet.record_class:
            if not _reduced_and_absent(m, question_text):
                named.add(facet.record_class)
    register_words = _register_words(catalogue)
    route_limit = bool(_ROUTE_LIMIT_RE.search(scoped))
    out: Dict[str, Tuple[Facet, List[TermMatch]]] = {}
    for m in matches:
        facet = catalogue.get(m.key)
        if facet is None or m.key not in keys:
            continue
        if not _counts(m, facet, question_text, named, register_words, route_limit):
            continue
        if all(w in _GENERIC_WORDS for w in m.words):
            continue
        out.setdefault(m.key, (facet, []))[1].append(m)
    return out


def _measured(
    named: Dict[str, Tuple[Facet, List[TermMatch]]], outside: FrozenSet[int] = frozenset()
) -> List[Facet]:
    """Numeric sensor facets named OUTSIDE the given positions, by more than availability words."""
    out = []
    for key in sorted(named):
        facet, matches = named[key]
        if facet.source_kind != "sensor" or facet.value_type not in ("number", "integer"):
            continue
        if any(
            not (set(m.positions) & outside) and not all(w in _AVAILABILITY_WORDS for w in m.words)
            for m in matches
        ):
            out.append(facet)
    return out


def relation_signal(
    question: str, catalogue: Optional[FacetCatalogue]
) -> Optional[OperationSignal]:
    """Why ``question`` relates a measured series to recorded events or to another series (C5).

    Pure and deterministic, like the other signals; the cheap word tests run first. An event or a
    yes/no state counts only as what a cue INTRODUCES (``RELATION_REACH``), and the measured series
    must be named outside it -- "CO2 during lectures", not "lectures, available during the day".
    """
    if catalogue is None or not question or not question.strip():
        return None
    scoped = scope_text(question)
    if _FREE_SUFFIX_RE.search(scoped) and not _STANDALONE_FREE_RE.search(scoped):
        scoped = _FREE_SUFFIX_RE.sub("", scoped)  # "step-free" is no step: never availability
    event_cue = bool(_EVENT_CUE_RE.search(scoped))
    series_cue = bool(_SERIES_CUE_RE.search(scoped))
    if not (event_cue or series_cue):
        return None
    if _FUTURE_RE.search(question) or _TWO_PERIODS_RE.search(question):
        return None
    if _ASKS_A_MOMENT_RE.search(question) and not series_cue:
        return None
    named = _named_space_matches(scoped, catalogue)
    if not named:
        return None
    event_starts = _cue_starts(scoped, _EVENT_CUE_RE)
    state_starts = _cue_starts(scoped, _STATE_CUE_RE)

    def introduced(positions: Sequence[int], starts: Sequence[int]) -> bool:
        return any(0 <= p - k < RELATION_REACH for p in positions[:1] for k in starts)

    for m in catalogue.event_source_matches(scoped):
        if introduced(m.positions, event_starts):
            measured = _measured(named, frozenset(m.positions))
            if measured:
                return OperationSignal("C5", "events", (measured[0].key, m.key))
    # A reading a state cue introduces: a yes/no one ("while the window is open") is a state; a
    # measured one PREDICATED by the clause ("when it is busy") is a second series.
    predicated = {
        word
        for match in _PREDICATED_STATE_RE.finditer(scoped)
        for word in content_words(match.group("state"))
    }
    for key in sorted(named, key=lambda k: (named[k][0].value_type != "boolean", k)):
        facet, matches = named[key]
        if facet.source_kind != "sensor":
            continue
        yes_no = facet.value_type == "boolean"
        # "when is it available" asks when a space can be used, not about a sensed state
        clause = [
            m
            for m in matches
            if introduced(m.positions, state_starts)
            and not all(w in _AVAILABILITY_WORDS for w in m.words)
            and (yes_no or m.words[0] in predicated)
        ]
        if not clause:
            continue
        outside = frozenset(p for m in clause for p in m.positions)
        measured = [f for f in _measured(named, outside) if f.key != key]
        if measured:
            reason = "state" if facet.value_type == "boolean" else "series"
            return OperationSignal("C5", reason, (measured[0].key, key))
    if series_cue:
        measured = _measured(named)
        states = [
            f for f, _ in named.values() if f.source_kind == "sensor" and f.value_type == "boolean"
        ]
        if len(measured) >= 2:
            return OperationSignal("C5", "series", (measured[0].key, measured[1].key))
        if measured and states:
            return OperationSignal("C5", "series", (measured[0].key, states[0].key))
    return None


def _named_space_facets(scoped: str, catalogue: FacetCatalogue) -> List[Facet]:
    """The SPACE facets the question names, by the evidence rules `compound_signal` uses.

    Only the evidence half: no space-selection precondition and no grouping into criteria. A
    facet counts when a term reaching it passes `_counts` (not class vocabulary, not a fragment of
    a phrase the question does not contain, not a unit used as a time window, ...).
    """
    min_score = MIN_RELATIVE_SCORE * catalogue.unique_word_weight
    retrieved = {
        facet.key
        for _score, facet in catalogue.retrieve(
            scoped, k=len(catalogue), min_score=min_score, min_status="suitable"
        )
        if facet.entity_type == _TARGET_ENTITY and facet.key not in _SCOPE_FACETS
    }
    if not retrieved:
        return []
    matches = catalogue.term_matches(scoped)
    question_text = " " + " ".join(plain_words(scoped)) + " "
    named: Set[str] = set()
    for m in matches:
        facet = catalogue.get(m.key)
        if m.tier == "class" and facet is not None and facet.record_class:
            if not _reduced_and_absent(m, question_text):
                named.add(facet.record_class)
    register_words = _register_words(catalogue)
    route_limit = bool(_ROUTE_LIMIT_RE.search(scoped))
    out: Dict[str, Facet] = {}
    for m in matches:
        facet = catalogue.get(m.key)
        if m.key not in retrieved or facet is None:
            continue
        if not _counts(m, facet, question_text, named, register_words, route_limit):
            continue
        if all(w in _GENERIC_WORDS for w in m.words):
            continue
        out[facet.key] = facet
    return [out[k] for k in sorted(out)]


def operation_signal(
    question: str, catalogue: Optional[FacetCatalogue]
) -> Optional[OperationSignal]:
    """Why ``question`` needs a C3 or C2 operation that no v1 lane computes -- or None.

    Pure and deterministic, like `compound_signal`: decided from the question's words and the
    active building's catalogue, never from a building's own vocabulary.
    """
    if catalogue is None or not question or not question.strip():
        return None
    # C5 first: the codebook's own order puts a relation before C4, C2 and C3, and its word tests
    # are as cheap as theirs.
    relation = relation_signal(question, catalogue)
    if relation is not None:
        return relation
    # The cheap tests first: most questions compare nothing and group nothing.
    versus = bool(_VERSUS_RE.search(question))
    grouped = bool(
        _FLOOR_GROUP_RE.search(question)
        or _KIND_GROUP_RE.search(question)
        or (_DISPERSION_RE.search(question) and _ACROSS_SPACES_RE.search(question))
    )
    if not (versus or grouped):
        return None
    if _FUTURE_RE.search(question) or _TWO_PERIODS_RE.search(question):
        return None
    from orchestrator.services.deliberation.operations import additive, is_count

    scoped = scope_text(question)
    numeric = [
        f
        for f in _named_space_facets(scoped, catalogue)
        if f.value_type in ("number", "integer") and f.source_kind in ("sensor", "record", "ttl")
    ]
    measured = [f for f in numeric if f.source_kind == "sensor"]
    declared = [f for f in numeric if f.source_kind in ("record", "ttl")]

    # C2 -- a measured figure set against a declared one about the same spaces. When the question
    # names only the declared side ("over their seating capacity"), its measured partner is the
    # sensed facet that counts the same thing: both counts, or both in one unit -- never a guess
    # across quantities (operations.compare_fit refuses those again at compile time).
    if _VERSUS_RE.search(question) and declared:

        def _pairs(sensor: Facet) -> bool:
            return any(
                (is_count(d) and is_count(sensor))
                or (getattr(d, "unit", None) and getattr(d, "unit", None) == sensor.unit)
                for d in declared
            )

        partners = measured or [
            f
            for f in catalogue
            if f.source_kind == "sensor"
            and f.entity_type == _TARGET_ENTITY
            and f.status == "suitable"
            and _pairs(f)
        ]
        if partners:
            keys = tuple(dict.fromkeys([partners[0].key] + [d.key for d in declared]))
            return OperationSignal("C2", "measured_vs_declared", keys)

    # C3 -- a figure per GROUP of spaces, where v1's figure is wrong or missing.
    if not _AGGREGATE_CUE_RE.search(question) and not _DISPERSION_RE.search(question):
        return None
    by_kind = bool(_KIND_GROUP_RE.search(question))
    by_floor = bool(_FLOOR_GROUP_RE.search(question))
    if (
        _DISPERSION_RE.search(question)
        and measured
        and (by_kind or by_floor or _ACROSS_SPACES_RE.search(question))
    ):
        return OperationSignal("C3", "dispersion", tuple(f.key for f in measured))
    if not (by_kind or by_floor) or not _AGGREGATE_CUE_RE.search(question):
        return None
    keys = tuple(f.key for f in numeric)
    if by_kind and numeric:
        return OperationSignal("C3", "room_kind", keys)
    adds_up = [f for f in numeric if additive(f)[0]]
    if adds_up:
        return OperationSignal("C3", "additive", tuple(f.key for f in adds_up))
    if _COUNTED_SPACES_RE.search(question):
        return OperationSignal("C3", "counted_spaces", keys)
    return None


# ── the mode switch, the catalogue the router reads, and its warm-up ────────────────────


def routing_mode() -> str:
    """ARBITER_V2_ROUTING, read at call time: "off", "shadow" or "live". Anything else is off.

    Read from the settings object the config module holds NOW, not one imported at load time:
    a reloaded config replaces the object, and a module holding the old one would keep reading
    a setting nobody can change any more.
    """
    from shared import config as _config

    mode = str(getattr(_config.settings, "ARBITER_V2_ROUTING", "off") or "off").strip().lower()
    return mode if mode in MODES else "off"


def active_catalogue() -> Optional[FacetCatalogue]:
    """The active building's cached facet catalogue, or None. Never builds one.

    The identity is the deliberation lane's own (``live.active_identity``), so the router reads
    exactly the catalogue the warm-up built for the building the lane serves.
    """
    from orchestrator.services.deliberation.live import active_identity

    identity = active_identity()
    return cached_catalogue(identity["BUILDING_ID"], identity["BUILDING_NAMESPACE"])


#: Seconds before the first build (the graph is still loading at boot), then between retries.
WARM_FIRST_DELAY_S: float = 90.0
WARM_RETRY_DELAYS_S: Tuple[float, ...] = (60.0, 120.0, 240.0, 480.0)


async def warm_facet_catalogue(
    first_delay_s: float = WARM_FIRST_DELAY_S,
    retry_delays_s: Sequence[float] = WARM_RETRY_DELAYS_S,
) -> Optional[FacetCatalogue]:
    """Build and cache the active building's facet catalogue in the background, at boot.

    The router never builds one (a build reads the whole graph); until this finishes the rule is
    inert, which is the honest default. A partial build is not cached by
    ``build_facet_catalogue``, so this retries until a complete one is, and says so either way.
    """
    from orchestrator.services.deliberation.coverage_audit import load_modalities
    from orchestrator.services.deliberation.live import active_identity, sparql_exec

    await asyncio.sleep(first_delay_s)
    delays = (0.0, *retry_delays_s)
    for attempt, delay in enumerate(delays, start=1):
        if delay:
            await asyncio.sleep(delay)
        identity = active_identity()
        building_id = identity["BUILDING_ID"]
        try:
            catalogue = await build_facet_catalogue(
                sparql_exec,
                building_id,
                identity["BUILDING_NAMESPACE"],
                load_modalities(building_id),
                refresh=True,
            )
        except Exception as exc:
            logger.warning(
                f"[facet-routing] catalogue build {attempt}/{len(delays)} failed: "
                f"{describe_exception(exc)}"
            )
            continue
        if not catalogue.errors:
            logger.info(
                f"[facet-routing] {building_id}: {len(catalogue)} facets cached for compound "
                f"routing (mode={routing_mode()})"
            )
            return catalogue
        logger.warning(
            f"[facet-routing] catalogue build {attempt}/{len(delays)} partial "
            f"({'; '.join(catalogue.errors)}); retrying"
        )
    logger.warning(
        "[facet-routing] no complete facet catalogue after every retry -- compound routing "
        "stays inert until the next restart"
    )
    return None


__all__ = [
    "CompoundSignal",
    "Criterion",
    "MIN_RELATIVE_SCORE",
    "MODES",
    "OperationSignal",
    "SPACE_SELECTION_RE",
    "active_catalogue",
    "compound_signal",
    "operation_signal",
    "relation_signal",
    "routing_mode",
    "scope_text",
    "selects_spaces",
    "warm_facet_catalogue",
]
