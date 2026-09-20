"""Referent resolution gate — verify a named zone/room/sensor exists before answering.

Problem this solves
--------------------
A data query that names a *specific* location — "what is the temperature in Zone 99.99?"
— used to be answered with fabricated-looking data. The pipeline's fallback cascade
(class+location SPARQL → ``_fallback_pattern_search`` which drops the location filter →
semantic RAG → SQL ``fetch_data_for_uuids`` → SQL auto-expand) is designed to always
surface *some* class-matching sensor's readings, which the response LLM then narrates as
belonging to the nonexistent zone. There was no step that asked "does Zone 99.99 exist?".

This module adds that step. It is intentionally **precision-first**: it only fires when the
user names a *specific* spatial referent, and it **fails open** (proceeds as before) on any
SPARQL error, so it can never block a legitimate query or a query against a degraded GraphDB.

Portability
-----------
Building-agnostic. The referent is validated against the ACTIVE building's ontology
namespace (passed in by the caller from the per-request building context) using generic
SPARQL over subject URIs / ``rdfs:label`` — no building-specific literals. A new building
works unchanged: its zones come from its own TTL.
"""

from __future__ import annotations

import difflib
import re
from dataclasses import dataclass, field
from typing import Awaitable, Callable, FrozenSet, Iterable, List, Optional

from shared.utils import get_logger

logger = get_logger(__name__)

# An injected async callable: SPARQL string -> standard SPARQL-results JSON dict.
SparqlExec = Callable[[str], Awaitable[dict]]

# A dotted numeric location id (e.g. 5.28, 3.01, 99.99). Common Brick zone/room id shape.
_DOTTED_ID_RE = re.compile(r"\d{1,2}\.\d{1,2}")

#: English CLOSED-CLASS words: prepositions, conjunctions, pronouns, auxiliaries, wh-words and
#: quantifiers. None of them names a place or a measured quantity in any building, yet the
#: patterns below capture "whatever word follows" a cue: "this room IS warm", "a room FOR two",
#: "classes ON Levels 1 and 3", "at WHAT level of VOC". Measured over the 10,339-question pool,
#: about 3% of questions carried one of them as a bogus "place", and the gate spent two graph
#: lookups on each. Generic English only -- no building's vocabulary appears here.
_FUNCTION_WORDS = frozenset(
    "a an the this that these those it its you your we our they their i me my he she his her "
    "on at in of to from by with for into onto about over under near during without within "
    "than as and or but if so nor either neither whether while because since until unless "
    "what which who whom whose when where why how there here then too very not no per "
    "is are was were be been being am do does did done can could will would shall should may "
    "might must has have had having get gets got all any some each every both few fewer many "
    "much more most less least other another such various several multiple different certain "
    "specific given only just also even still yet again ever never".split()
)
# "zone|room|space|node|area <id>" — an explicitly location-qualified reference.
_WORDED_REF_RE = re.compile(
    r"\b(?:zone|room|space|node|area)\s+([A-Za-z0-9][A-Za-z0-9._-]{0,23})\b",
    re.IGNORECASE,
)
#: Does this token look like something a building would USE as an identifier?
#:
#: `_WORDED_REF_RE` captures the word after "room"/"zone"/"space", and English puts a verb
#: there as readily as an id: "this room FEELS stuffy", "which room HAS the most daylight".
#: A token carrying a digit ("5.01", "B12", "3") is an id in every building convention seen
#: here; a bare word may be a real named space ("Atrium") or may be a verb, and only the graph
#: can say which. So this is not used to reject a token -- it decides how a MISS is reported.
_IDENTIFIER_SHAPED_RE = re.compile(r"\d")


# Injection guard: only these characters may reach a SPARQL string literal.
_SAFE_TOKEN_RE = re.compile(r"^[A-Za-z0-9._-]{1,24}$")

# Data intents whose answer is scoped to a specific sensor/zone — worth gating.
# Broad intents (metadata, discovery, floor_plan, capability, …) are NOT gated: they
# legitimately answer without a specific referent.
GATED_INTENTS = frozenset(
    {
        "sensor_data",
        "analytics",
        "trend",
        "compare",
        "comparison",
        "anomaly",
        "compliance",
        "visualization",
        # BUG-103: counts and listings scoped to a named referent are equally fabricable
        # ("how many sensors are on floor 42?" → three real sensors from other floors).
        # A query with no named referent still returns NO_REFERENT and passes through.
        "metadata",
        "discovery",
        # BUG-156: advice is the MOST fabricable shape, not the least — it invites a
        # number in a sentence the user reads as a recommendation. "Should we charge
        # the battery now or wait?" fell through to generic analytics and quoted a
        # real reading from an unrelated series, presenting it in a battery context
        # this building does not model. Gate it like any other scoped data answer.
        "recommend",
    }
)

# Status values
RESOLVED = "resolved"
NOT_FOUND = "not_found"
NO_REFERENT = "no_referent"
SKIPPED = "skipped"  # existence check could not run (e.g. GraphDB down) — fail open
AMBIGUOUS = "ambiguous"  # the label matches several real ids and names none of them


# ── Typed referents (BUG-103) ────────────────────────────────────────────────────
# The original gate only knew dotted zone/room ids, so "floor 42", "the west wing",
# "the swimming pool", "EV chargers" and "methane concentration" walked straight past
# it into the SQL/analytics cascade and came back wearing another sensor's numbers.
# Each kind below is detected by ENGLISH STRUCTURE (never a building's vocabulary) and
# validated against the ACTIVE building's own graph — so a new building works unchanged.
KIND_LOCATION = "location"
KIND_FLOOR = "floor"
KIND_SPACE = "space"
KIND_EQUIPMENT = "equipment"
KIND_MEASURAND = "measurand"

# "floor 42" / "42nd floor" — the storey number is the referent.
_FLOOR_RE = re.compile(
    r"\bfloor\s+(\d{1,3})\b|\b(\d{1,3})\s*(?:st|nd|rd|th)\s+floor\b", re.IGNORECASE
)
# "<modifier> <space-head>" — e.g. west wing, rooftop garden, server room, swimming pool.
# The HEAD nouns are generic English building-space words, not any building's names.
_SPACE_HEADS = (
    "wing",
    "garden",
    "pool",
    "lobby",
    "atrium",
    "parking",
    "garage",
    "greenhouse",
    "courtyard",
    "terrace",
    "canteen",
    "cafeteria",
    "gym",
    "auditorium",
    "warehouse",
    "basement",
    "rooftop",
    "helipad",
    "cellar",
    "mezzanine",
    "boilerhouse",
    "plantroom",
    "loadingbay",
    # BUG-189: 'corridor' was missing, so "the public corridor on floor 1" was
    # invisible to the gate and a ROOM's reading was attributed to a corridor the
    # building does not have. These are generic English building-space words, in
    # keeping with the rest of this list — no building's own vocabulary.
    "corridor",
    "hallway",
    "stairwell",
    "foyer",
)
#: Words that can PRECEDE a space head without being part of its name. The
#: modifier group below accepted ANY word, so a quantifier or a deictic was
#: swallowed into the referent and the gate then refused a question about a
#: referent nobody had named: "how many parking bays are free?" produced the
#: space "many parking" and answered "I couldn't find many parking in this
#: building's model" -- a truthful sentence about a fabricated subject, which
#: is the exact failure this gate exists to prevent, committed by the gate
#: itself (measured live 2026-08-25). Function words only: a real modifier
#: like "main" in "main corridor" must still be kept.
_NON_MODIFIERS = frozenset(
    {
        "many",
        "much",
        "there",
        "any",
        "some",
        "every",
        "each",
        "which",
        "what",
        "this",
        "that",
        "these",
        "those",
        "more",
        "less",
        "fewer",
        "most",
        "all",
        "both",
        "few",
        "several",
        "another",
        "other",
        "such",
        "here",
        "and",
        "but",
        "for",
        "with",
        "from",
        "into",
        "onto",
        "about",
        "have",
        "has",
        "are",
        "was",
        "were",
        "does",
        "did",
        "the",
        "its",
        "our",
        "their",
        "your",
    }
)
#: Words that say what a place is LIKE right now, not what it is CALLED. "When is the least
#: disruptive window for cleaning a busy corridor" and "avoid the busiest corridor" describe a
#: corridor by its state, and the modifier group took "busy" for part of its name, so a building
#: with corridors was told it had no "busy corridor". A name that really is "Quiet Room" still
#: resolves as the bare head (the graph is asked for "room"), and a name is never lost by leaving
#: one of these out: the pattern then finds no modifier and names no space at all.
_STATE_MODIFIERS = frozenset(
    {
        "busy",
        "busier",
        "busiest",
        "quiet",
        "quieter",
        "quietest",
        "noisy",
        "noisier",
        "noisiest",
        "crowded",
        "empty",
        "emptiest",
        "free",
        "available",
        "vacant",
        "occupied",
        "nearest",
        "closest",
        "nearby",
        "best",
        "worst",
        "warmest",
        "coldest",
        "hottest",
        "coolest",
        "darkest",
        "brightest",
        "cleanest",
        "dirtiest",
        "safest",
        "largest",
        "biggest",
        "smallest",
        "longest",
        "shortest",
        "current",
        "usual",
        "next",
        "first",
        "last",
        "verified",
    }
)
# A SPACE HEAD CARRYING A HYPHEN IS AN ADJECTIVE, NOT A PLACE (BUG-740 / C20).
#
# "Is today's noise a brief CORRIDOR-RELATED peak or a sustained room-level problem?"
# was refused with "'brief corridor' does not exist in this building" — a truthful
# sentence about a subject nobody named, which is the failure this gate exists to
# prevent, committed by the gate itself (the same shape as the "many parking" note
# above). "corridor-related" is the first half of an attributive compound modifying
# "peak"; the head noun of the phrase is "peak", so no space is named at all. The
# trailing `(?!-)` is the structural tell and needs no vocabulary: a place name is
# not immediately followed by a hyphen and another word.
_HEAD_NOT_HYPHENATED = r"\b(?!-)"
_SPACE_RE = re.compile(
    r"\b(?:the\s+)?(?!(?:" + "|".join(sorted(_NON_MODIFIERS | _STATE_MODIFIERS)) + r")\b)"
    r"([a-z][a-z-]{2,19})\s+(" + "|".join(_SPACE_HEADS) + r")" + _HEAD_NOT_HYPHENATED,
    re.IGNORECASE,
)
# The same heads standing alone behind a determiner: "in the gym", "on the rooftop".
# Without this a bare space noun was invisible to the gate, so "how many sensors are
# on the helipad?" was answered with the whole building's figures. A determiner is
# required so an incidental mention ("pool of data") cannot trip it, and the heads
# are generic English building words — no building's own vocabulary appears here.
_BARE_SPACE_RE = re.compile(
    r"\b(?:the|a|an)\s+(" + "|".join(_SPACE_HEADS) + r")" + _HEAD_NOT_HYPHENATED,
    re.IGNORECASE,
)
# Plant / assets. Generic equipment nouns; an optional trailing number is kept.
_EQUIPMENT_HEADS = (
    "chiller",
    "boiler",
    "elevator",
    "escalator",
    "charger",
    "compressor",
    "generator",
    "turbine",
    "heat pump",
    "solar panel",
    "water tank",
)
_EQUIPMENT_RE = re.compile(
    r"\b(" + "|".join(_EQUIPMENT_HEADS) + r")s?\b(?:\s*#?\s*(\d{1,3}))?", re.IGNORECASE
)
# "<quantity> concentration|level(s)" — the measured quantity is the referent.
_MEASURAND_RE = re.compile(r"\b([a-z][a-z0-9]{1,19})\s+(?:concentration|levels?)\b", re.IGNORECASE)
# "Building 47" / "Block C" / "Tower 2" — a SPECIFICALLY NAMED other building. A
# question that names one is asking about a site this instance is not connected to,
# so it must be validated (and will not be found). Requires an identifier after the
# word, so "this building" / "the building" / "our building" — which mean the
# connected one — never match. Building-agnostic: it names no site, only the shape
# "<building-word> <id>".
_OTHER_BUILDING_RE = re.compile(
    r"\b(building|block|tower|annex|annexe)\s+([A-Za-z]?\d+[A-Za-z]?|[A-Z])\b",
    re.IGNORECASE,
)
# Multi-word referent phrases reaching a SPARQL literal — letters/digits/space/.-_ only.
_SAFE_PHRASE_RE = re.compile(r"^[A-Za-z0-9 ._-]{1,40}$")


#: The ontology's lay TERMS, published by the concept resolver whenever it loads the concept map.
#: Empty until then (and in any process that never resolves a concept), which leaves the gate
#: behaving exactly as it did without it. Whole terms, not their words: "solar radiation" is a
#: term, and it must not make "radiation levels" a quantity the building is taken to measure.
_CONCEPT_TERMS: FrozenSet[str] = frozenset()
_CONCEPT_SINGLE_WORDS: FrozenSet[str] = frozenset()


def register_concept_terms(terms: Iterable[str]) -> None:
    """Publish the lay vocabulary to the measured-quantity check."""
    global _CONCEPT_TERMS, _CONCEPT_SINGLE_WORDS
    _CONCEPT_TERMS = frozenset(t.lower() for t in terms if t)
    _CONCEPT_SINGLE_WORDS = frozenset(t for t in _CONCEPT_TERMS if t.isalpha() and len(t) >= 6)


def _explained_by_concepts(token: str) -> bool:
    """True if "<token> level(s)" is a lay term, or ``token`` is one (or one slip from one)."""
    if not _CONCEPT_TERMS:
        return False
    if token in _CONCEPT_TERMS or any(
        f"{token} {tail}" in _CONCEPT_TERMS for tail in ("level", "levels", "concentration")
    ):
        return True
    from orchestrator.services.concept_resolver import _slip_target

    return _slip_target(token, _CONCEPT_SINGLE_WORDS) is not None


def _names_a_building(ident: str, after: str) -> bool:
    """Is the identifier after "building"/"block"/... a NAME, not an article or a pronoun?

    A single letter is an identifier ("Block C", "Building B") -- except "a" and "I". The pattern
    is case-blind, so "how should we go about building a green roof" named a building called A
    and "the building I can keep on my phone" a building called I, and each was declined as a site
    this instance is not connected to. "A" needs its capital; "I" needs its capital AND nothing
    after it but the end of the sentence, because "Building I can see" is a pronoun.
    """
    if len(ident) != 1 or not ident.isalpha():
        return True
    if ident == "a":
        return False
    if ident == "A":
        return True
    if ident.lower() == "i":
        return ident == "I" and not after.strip(" \t").lstrip(",.;:!?)")[:1].isalnum()
    return True


@dataclass
class TypedReferent:
    """A named thing the question is *about*, plus what kind of thing it is."""

    kind: str
    token: str  # pipe-separated terms that must ALL appear on one entity
    phrase: str  # what to echo back to the user
    head: str  # the kind-defining term ("floor", "wing", "chiller") — drives suggestions


@dataclass
class ReferentResolution:
    """Outcome of resolving a named referent against the building ontology."""

    status: str
    referent: Optional[str] = None
    suggestions: List[str] = field(default_factory=list)
    message: str = ""
    #: What KIND of thing was looked for (a floor, a space, equipment, a measured quantity), so the
    #: refusal can be worded as what it is. Empty for the legacy id-shaped referents.
    kind: str = ""


def absence_reason(resolution: "ReferentResolution") -> str:
    """The one sentence a refused referent is reported with, worded for the KIND of thing it was.

    A measured QUANTITY is not a place. Measured 2026-09-20 (tail J): "can i efficiency level of the
    building" was answered "'efficiency' does not exist in this building" — a quantity word gated
    and worded as an absent room. "Does not exist" is right for a space, a floor or a piece of
    equipment; for a quantity the true statement is that the building does not measure it.
    """
    ref = getattr(resolution, "referent", "")
    if getattr(resolution, "kind", "") == KIND_MEASURAND:
        return f"'{ref}' is not something this building measures, so there is nothing to report about it"
    return f"'{ref}' does not exist in this building, so there is nothing to report about it"


def detect_referent(query: str, entities: Optional[List[str]] = None) -> Optional[str]:
    """Return the single explicit spatial referent token, or ``None``.

    Precision-first: only returns a token when the query/entities name a *specific*
    location (a location-qualified dotted id like "zone 5.28", or a bare dotted id that
    the dialogue agent already extracted as an entity). Broad queries ("all zones",
    "temperature", "26.5 degrees") return ``None`` and pass through the pipeline unchanged.
    """
    # 1) Entity list first — the dialogue agent already isolated building entities, so a
    #    dotted id here is a high-confidence zone/room reference (not a threshold value).
    for ent in entities or []:
        ent = str(ent)
        m = _DOTTED_ID_RE.search(ent)
        if m and _SAFE_TOKEN_RE.match(m.group(0)):
            return m.group(0)
        m = _WORDED_REF_RE.search(ent)
        if m and m.group(1).lower() not in _FUNCTION_WORDS and _SAFE_TOKEN_RE.match(m.group(1)):
            return m.group(1)

    # 2) Raw query — require an explicit location word before the id so we never trip on a
    #    threshold/value (e.g. "above 26.5 degrees" has no location word → ignored).
    #    A function word after the cue is not a name ("this room IS warm"): keep looking.
    for m in _WORDED_REF_RE.finditer(query or ""):
        if m.group(1).lower() in _FUNCTION_WORDS:
            continue
        if _SAFE_TOKEN_RE.match(m.group(1)):
            return m.group(1)

    return None


def detect_typed_referent(query: str) -> Optional[TypedReferent]:
    """Detect a floor / named space / equipment / measurand referent, or ``None``.

    Structural English patterns only — nothing here knows any building's vocabulary,
    so the same detection serves every building. Precision-first: an unmatched query
    returns ``None`` and flows through the pipeline exactly as before.
    """
    q = query or ""

    # A specifically-named OTHER building is checked first: "air quality in Building
    # 47" names both a measurand and a place, and the place is what makes it
    # unanswerable — this instance is connected to one building, not 47.
    for m in _OTHER_BUILDING_RE.finditer(q):
        head, ident = m.group(1).lower(), m.group(2)
        if not _names_a_building(ident, q[m.end() :]):
            continue
        phrase = f"{head} {ident}"
        if _SAFE_PHRASE_RE.match(phrase):
            return TypedReferent(
                kind=KIND_LOCATION, token=f"{head}|{ident}", phrase=phrase, head=head
            )

    # BUG-189: the MOST SPECIFIC referent governs. Floors used to be matched first,
    # so "<space> on floor N" resolved to the floor — and because the floor exists,
    # the gate passed and the space was never existence-checked. That is how a
    # non-existent corridor received a real room's temperature. A question that
    # names a space is about that space; the floor is only context.
    m = _SPACE_RE.search(q)
    if m:
        modifier, head = m.group(1).lower(), m.group(2).lower()
        # A determiner is not a modifier. "in the gym" matched here with
        # modifier="the", giving the token "the|gym" — which demands an entity
        # whose name contains BOTH words, so a gym the building really has would
        # be reported missing. Treat it as the bare space it is.
        if modifier in ("the", "a", "an"):
            if _SAFE_TOKEN_RE.match(head):
                return TypedReferent(kind=KIND_SPACE, token=head, phrase=head, head=head)
        else:
            phrase = f"{modifier} {head}"
            if _SAFE_PHRASE_RE.match(phrase):
                return TypedReferent(
                    kind=KIND_SPACE, token=f"{modifier}|{head}", phrase=phrase, head=head
                )

    m = _EQUIPMENT_RE.search(q)
    if m:
        head, num = m.group(1).lower(), m.group(2)
        phrase = f"{head} {num}" if num else head
        if _SAFE_PHRASE_RE.match(phrase):
            token = f"{head}|{num}" if num else head
            return TypedReferent(kind=KIND_EQUIPMENT, token=token, phrase=phrase, head=head)

    # Checked after the modified forms so "the swimming pool" is still reported as
    # "swimming pool" rather than the bare "pool".
    m = _BARE_SPACE_RE.search(q)
    if m:
        head = m.group(1).lower()
        if _SAFE_TOKEN_RE.match(head):
            return TypedReferent(kind=KIND_SPACE, token=head, phrase=head, head=head)

    # Only once no space is named does the floor become the referent.
    m = _FLOOR_RE.search(q)
    if m:
        num = m.group(1) or m.group(2)
        if num and _SAFE_TOKEN_RE.match(num):
            return TypedReferent(
                kind=KIND_FLOOR, token=f"floor|{num}", phrase=f"floor {num}", head="floor"
            )

    # Every "<word> level(s)" is looked at, not only the first: "classes ON Levels 1 and 3 ... and
    # the CO2 levels" names one quantity, and the word before the first "Levels" is a preposition.
    for m in _MEASURAND_RE.finditer(q):
        quantity = m.group(1).lower()
        if quantity not in _STOP_QUANTITIES and _SAFE_TOKEN_RE.match(quantity):
            return TypedReferent(
                kind=KIND_MEASURAND, token=quantity, phrase=quantity, head=quantity
            )

    return None


# Words that precede "level/concentration" without naming a measured quantity: every function
# word ("on Levels 1 and 3", "at what level of VOC") and the modifiers a person puts on a level
# ("the verified levels", "an appropriate level", "a sufficient level"). Adjectives that are
# ALSO the name of a measured quantity ("noise", "heat", "light") are deliberately not here.
_STOP_QUANTITIES = _FUNCTION_WORDS | frozenset(
    {
        "high",
        "low",
        "current",
        "same",
        "acceptable",
        "normal",
        "appropriate",
        "sufficient",
        "adequate",
        "required",
        "necessary",
        "relevant",
        "verified",
        "affected",
        "authorised",
        "authorized",
        "concerning",
        "practical",
        "healthy",
        "safe",
        "unsafe",
        "dangerous",
        "optimal",
        "ideal",
        "overall",
        "average",
        "maximum",
        "minimum",
        "peak",
        "next",
        "previous",
        "last",
        "first",
        "new",
        "old",
        "good",
        "bad",
        "better",
        "best",
        "worse",
        "worst",
        "right",
        "wrong",
        # size, position and period words: "wide levels", "upper levels", "daily levels"
        "wide",
        "broad",
        "narrow",
        "general",
        "whole",
        "entire",
        "full",
        "top",
        "bottom",
        "upper",
        "lower",
        "middle",
        "large",
        "small",
        "big",
        "huge",
        "extra",
        "extreme",
        "particular",
        "individual",
        "basic",
        "standard",
        "typical",
        "usual",
        "regular",
        "daily",
        "weekly",
        "monthly",
        "hourly",
        "yearly",
        "annual",
    }
)


# ── Unbound spatial deixis: ask which room, do not pick one ──────────────────
#
# "I've developed a headache in this room — what are the current conditions?" named
# no room, and three different lanes each did something worse than asking. One
# declined outright ("I don't have that specific information on record"), one bound
# "here" to whichever sensor a search returned first and then failed to build a
# series for it, and one read the deixis as the WHOLE BUILDING and refused the fetch
# as too large. Each answer is about a subject the asker never chose.
#
# A deictic reference is not a missing referent, it is an UNRESOLVED one: the asker
# knows exactly which room they mean. The only correct move is to ask, and the only
# thing that makes asking wrong is that the conversation already named a room — which
# the caller checks, because this module cannot see the conversation.
#
# Generic English throughout; no building's vocabulary appears here.

#: Room-type nouns a person uses deictically when they are standing in one.
_DEICTIC_SPACE_NOUNS = (
    "room",
    "space",
    "office",
    "lab",
    "laboratory",
    "studio",
    "zone",
    "area",
    "classroom",
    "workspace",
)

#: Generic room TYPES that a building normally has more than one of, so "the
#: <type> room" identifies nothing on its own. Deliberately short: a type a
#: building plausibly has exactly one of would make the question answerable and
#: the clarification an obstruction.
_AMBIGUOUS_ROOM_TYPES = ("meeting", "conference", "seminar", "break", "common")

#: A CONDITION INSIDE a space — the thing an instrument reads. Generic English, no
#: building's vocabulary: warmth, noise, light and air are conditions of a room in any
#: building, and the lay words for them are the words people actually use.
#:
#: This is what makes a bare "here" a room rather than a site. "Is there a café here?"
#: plausibly means the campus; "is it stuffy in here?" cannot mean anything but the room
#: the asker is standing in, and answering it about a different room is the failure the
#: clarification exists to prevent. Measured 2026-09-18: "is it stuffy in here?", "how
#: warm is it here?" and "what is the air quality here?" all fell straight through the
#: presence-verb branch below and were answered about whichever space a search returned.
_SENSED_CONDITION_RE = re.compile(
    r"\b(?:warm|warmer|warmth|hot|hotter|cold|colder|cool|cooler|chilly|freezing|"
    r"stuffy|stuffiness|airless|stale|muggy|humid|humidity|damp|dry|"
    r"noisy|noise|loud|louder|quiet|quieter|bright|brighter|dark|darker|dim|glare|"
    r"draught\w*|draft\w*|smell\w*|temperature|temp|co2|co₂|carbon\s+dioxide|"
    r"air\s+quality|aqi|iaq|illuminance|lux|light\s+level|decibels?|"
    r"occupancy|busy|crowded|comfortable|comfort|conditions?|ventilation)\b",
    re.IGNORECASE,
)

#: "here" in any of its ordinary spatial uses, with no verb required.
_BARE_HERE_RE = re.compile(r"\b(?:in\s+|right\s+|round\s+|around\s+)?here\b", re.IGNORECASE)

_DEICTIC_SPACE_RE = re.compile(
    # "in this room", "this space's usual levels", "the current room"
    r"\b(?:this|the\s+current)\s+(" + "|".join(_DEICTIC_SPACE_NOUNS) + r")\b"
    # "should I stay here", "while I'm sitting here" — a first-person presence verb binds
    # "here" to the room whatever the question then asks about.
    r"|\b(?:stay|staying|stayed|sit|sitting|sat|work|working|stand|standing|"
    r"remain|remaining|am\s+i|i\s*'?\s*m|i\s+am|move\s+from|leave)\b[^.?!]{0,20}?"
    r"\b(?:in\s+)?(?:right\s+)?here\b"
    # "what systems are specific for the meeting room?"
    r"|\bthe\s+(?:" + "|".join(_AMBIGUOUS_ROOM_TYPES) + r")\s+room\b",
    re.IGNORECASE,
)

#: "zone 5.28", "room 1.06", "floor 3" — an identifier the building could hold.
_NAMED_SPACE_RE = re.compile(
    r"\b(?:zone|room|space|node|area|floor|level)\s+([A-Za-z0-9][A-Za-z0-9._-]{0,23})\b",
    re.IGNORECASE,
)


def detect_space_deixis(query: str) -> Optional[str]:
    """The deictic space phrase the question is scoped to, or ``None``.

    Returns what the asker actually wrote ("this room", "here", "the meeting room")
    so the clarification can echo it back instead of asking a generic question.
    """
    m = _DEICTIC_SPACE_RE.search(query or "")
    if not m:
        # "Is it stuffy in here?" — no presence verb, and unmistakably about this room.
        q = query or ""
        if _BARE_HERE_RE.search(q) and _SENSED_CONDITION_RE.search(q):
            return "here"
        return None
    phrase = " ".join(m.group(0).split()).strip().lower()
    # The presence-verb branch matches the whole clause ("stay here"); the deictic
    # in it is the last word, and that is what the clarification should quote back.
    if phrase.endswith("here"):
        return "here"
    return phrase


def names_a_specific_space(query: str) -> bool:
    """True when the question itself identifies a space the building could hold.

    Precision-first in the opposite direction from the gate above: a false TRUE
    only means a deictic question is answered as it is today, while a false FALSE
    asks "which room?" of someone who already said.
    """
    q = query or ""
    if not q.strip():
        return False
    if _DOTTED_ID_RE.search(q):
        return True
    for m in _NAMED_SPACE_RE.finditer(q):
        # "this room FEELS stuffy" puts a verb where an id goes; only a token
        # carrying a digit is an identifier in every convention seen here.
        if _IDENTIFIER_SHAPED_RE.search(m.group(1)):
            return True
    if _FLOOR_RE.search(q):
        return True
    typed = detect_typed_referent(q)
    return bool(typed and typed.kind in (KIND_SPACE, KIND_LOCATION))


def ask_which_space(phrase: str) -> str:
    """The clarification for an unbound deictic — one question, no guessing.

    Worded to avoid the words the dialogue node treats as a *spurious* location
    clarification ("location", "city", "region", "where are you"): this one is
    genuine, and must not be converted into a reading of somewhere else.
    """
    phrase = (phrase or "this room").strip()
    if phrase.startswith("the ") and phrase.endswith(" room"):
        kind = phrase[len("the ") :]
        return (
            f"Which {kind} do you mean? There is more than one here, and I would rather "
            f"ask than answer about the wrong one — give me its number or its name and "
            f"I will tell you what it has."
        )
    return (
        f'Which room do you mean by "{phrase}"? I cannot tell which one you are in, and '
        "answering about a different one would look right and be wrong. Give me its "
        "number or name — or name the floor and I will narrow it down."
    )


class ReferentResolver:
    """Validate a named referent against a building's ontology namespace."""

    def __init__(self, sparql_exec: SparqlExec):
        self._exec = sparql_exec

    async def resolve(
        self,
        query: str,
        entities: Optional[List[str]],
        namespace: str,
        building_name: str = "this building",
        for_admin: bool = False,
    ) -> ReferentResolution:
        """Resolve the query's spatial referent (if any) against ``namespace``.

        Never raises: on any SPARQL error returns ``SKIPPED`` so the caller proceeds
        exactly as it did before this gate existed (fail open).

        ``for_admin`` — pass ``reader_is_admin_in(state)`` — adds to a NOT_FOUND message how
        to make the referent answerable. Every other reader gets the decline and what the
        building does have; the default is that plain form.
        """
        token = detect_referent(query, entities)
        if not token:
            # No dotted/worded location — try the typed referents (BUG-103): a floor,
            # a named space, a piece of equipment, or a measured quantity.
            typed = detect_typed_referent(query)
            if typed:
                return await self._resolve_typed(
                    typed, namespace, building_name, for_admin=for_admin
                )
            return ReferentResolution(status=NO_REFERENT)

        try:
            exists = await self._exists(token, namespace)
        except Exception as e:  # GraphDB down / timeout / malformed — fail OPEN.
            logger.warning(f"[referent_resolver] existence check failed, proceeding: {e}")
            return ReferentResolution(status=SKIPPED, referent=token)

        if exists:
            # EXISTS IS NOT THE SAME AS NAMES ONE THING (BUG-526). `_exists` runs two
            # LIMIT 1 lookups with CONTAINS, and ids share prefixes: "5.1" is contained in
            # Room5.10, Room5.11 and Room5.12, so the gate reported RESOLVED and a
            # downstream lane answered about whichever the store returned first — with the
            # user's own words in the answer, which is what makes it convincing.
            #
            # Only an IDENTIFIER-shaped token is checked. A word like "kitchen" matching
            # several rooms is ordinary language, and the lanes below already handle a set;
            # a dotted id that names none of the ids it matches is a typo or a half-typed
            # room, and saying so is the whole point of this gate.
            if _IDENTIFIER_SHAPED_RE.search(token):
                try:
                    matches = await self._matching_ids(token, namespace)
                except Exception as exc:  # never turn a resolved referent into a failure
                    logger.debug(f"[referent_resolver] ambiguity check skipped: {exc}")
                    matches = set()
                if len(matches) > 1 and token.lower() not in {m.lower() for m in matches}:
                    shown = sorted(matches)[:5]
                    logger.info(
                        f"[referent_resolver] {token!r} matches {len(matches)} ids "
                        f"({', '.join(shown)}) and names none of them"
                    )
                    return ReferentResolution(
                        status=AMBIGUOUS,
                        referent=token,
                        suggestions=shown,
                        message=(
                            f"'{token}' matches {len(matches)} places in this building and "
                            f"names none of them exactly. Which did you mean?"
                        ),
                    )
            return ReferentResolution(status=RESOLVED, referent=token)

        # BUG-232: a word-shaped token that the graph does not know was almost certainly
        # never a referent -- "room FEELS stuffy" is not a question about a place called
        # "feels". Declining on it by name is worse than not spotting it: the user gets a
        # confident error about a word they never used as a location, and the question they
        # DID ask goes unanswered. Fall through instead and let the rest of the pipeline try.
        #
        # An identifier-shaped token is different: "room 5.99" that does not exist is a real
        # mistake, and telling the user is the whole point of this gate.
        if not _IDENTIFIER_SHAPED_RE.search(token):
            logger.debug(
                f"[referent_resolver] {token!r} is word-shaped and unknown to the graph; "
                "treating it as not a referent rather than as a failed one"
            )
            return ReferentResolution(status=NO_REFERENT)

        # Not found — best-effort suggestions (never fatal).
        try:
            suggestions = await self._suggest(token, namespace)
        except Exception as e:
            logger.warning(f"[referent_resolver] suggestion lookup failed: {e}")
            suggestions = []

        return ReferentResolution(
            status=NOT_FOUND,
            referent=token,
            suggestions=suggestions,
            message=self._clarification(token, suggestions, building_name),
        )

    # ------------------------------------------------- typed referents (BUG-103)

    # Words that introduce a whole other BUILDING, not a space within this one.
    _BUILDING_FAMILY = frozenset({"building", "block", "tower", "annex", "annexe"})

    def _resolve_other_building(
        self, typed: TypedReferent, namespace: str, building_name: str
    ) -> ReferentResolution:
        """Resolve "Building 47" against THIS building's identity, not the graph.

        A substring scan cannot answer this: entities are routinely labelled with the
        building's own name ("<Site> Building — Room X"), so "building" matches almost
        everything and a numeric identifier matches some URL or id — a false "exists".
        The design contract is one building at a time, so a reference to a
        specifically-named OTHER building resolves only if its identifier is part of
        THIS building's own name or namespace id; otherwise it is a different site and
        the honest answer is "not here". Compared against whatever this building calls
        itself, so it stays building-agnostic.
        """
        ident = typed.token.split("|", 1)[-1].lower()
        haystack = f"{building_name} {namespace}".lower()
        # Whole-token match so "3" does not hit "2003"/"w3.org" and "c" does not hit
        # every word — the identifier must stand on its own.
        if re.search(rf"(?<![a-z0-9]){re.escape(ident)}(?![a-z0-9])", haystack):
            return ReferentResolution(status=RESOLVED, referent=typed.phrase)
        return ReferentResolution(
            status=NOT_FOUND,
            referent=typed.phrase,
            message=self._clarification(typed.phrase, [], building_name),
        )

    async def _resolve_typed(
        self,
        typed: TypedReferent,
        namespace: str,
        building_name: str,
        for_admin: bool = False,
    ) -> ReferentResolution:
        """Validate a floor / space / equipment / measurand against the live graph."""
        if typed.head in self._BUILDING_FAMILY:
            return self._resolve_other_building(typed, namespace, building_name)
        # A quantity the ontology's own lay vocabulary already explains ("brightness", "decibel",
        # "pollutant") is not a referent to look for by name in the graph: the concept resolver
        # maps it to the classes the building measures, and whether those hold data is answered
        # honestly downstream. Declining it here said "no sensor measures pollutant" of a building
        # with 835 air-quality sensors.
        if typed.kind == KIND_MEASURAND and _explained_by_concepts(typed.token):
            return ReferentResolution(status=RESOLVED, referent=typed.phrase)
        terms = typed.token.split("|")
        # A four-letter word is a substring of far too much ("on" in "carbon"): a measured
        # quantity that short must stand as a whole word to count as found.
        short_quantity = (
            typed.kind == KIND_MEASURAND and typed.token.isalpha() and len(terms[0]) <= 4
        )
        found = self._exists_whole_words if short_quantity else self._exists_terms
        try:
            exists = await found(terms, namespace)
            # A compound referent ("west wing", "chiller 7") may fail only on the
            # modifier. If even the HEAD noun is unknown to this building, the answer
            # is a confident "we have nothing like that"; otherwise we can suggest the
            # real ones of that kind.
            head_exists = exists or await found([typed.head], namespace)
        except Exception as e:  # fail OPEN — never block on a degraded GraphDB
            logger.warning(f"[referent_resolver] typed existence check failed, proceeding: {e}")
            return ReferentResolution(status=SKIPPED, referent=typed.phrase)

        if exists:
            return ReferentResolution(status=RESOLVED, referent=typed.phrase)

        suggestions: List[str] = []
        if head_exists:
            try:
                suggestions = await self._suggest_terms([typed.head], namespace, typed.kind)
            except Exception as e:
                logger.warning(f"[referent_resolver] typed suggestion lookup failed: {e}")

        # A COMPOUND WHOSE HEAD THE BUILDING HOLDS, WITH NOTHING SAME-KIND TO OFFER, IS NOT AN
        # ABSENCE. Measured 2026-09-20 (tail G): "car parking is eligible for that building" was
        # answered "'car parking' does not exist in this building, so there is nothing to report
        # about it" — while the graph holds a ParkingArea (Ground Level Parking, six EV chargers).
        # The compound failed only on its modifier ("car" is in no field beside "parking"), the
        # head was found, and the kind-filtered suggestion query returned nothing because the
        # amenity class sits outside the Brick roots it searches. "No suggestions" was then read as
        # "no such thing". The gate can establish that the COMPOUND is unmatched; it cannot
        # establish that the building lacks the KIND, so it steps aside and lets the lanes answer.
        # A referent whose head is ALSO unknown ("swimming pool", "escalator") is untouched, and a
        # head with same-kind suggestions still gets the "did you mean" clarification.
        # A NUMBERED referent is never stepped aside for ("floor 42", "room 9.99"): a number is an
        # identifier, so "the building holds floors" says nothing about whether THIS one exists —
        # that is exactly the fabrication this gate was built to stop (BUG-189).
        numbered = bool(re.search(r"\d", typed.phrase or ""))
        if head_exists and not suggestions and not numbered:
            return ReferentResolution(status=SKIPPED, referent=typed.phrase)

        # AND A HEAD THAT NAMES A KIND THE BUILDING OFFERS. "car parking" DID find same-kind
        # suggestions ("Ground Level Parking"), so it was refused with a "did you mean" instead of
        # answered. What separates it from "west wing" (where a clarification is right, because
        # "which wing?" is a real question) is that the building has typed something as an AMENITY
        # of that kind (`ontosage:ParkingArea`): the graph itself says it offers this thing, and
        # the modifier is a way of asking for it, not a different place.
        if head_exists and not exists and not numbered:
            try:
                if await self._holds_amenity_kind(typed.head, namespace):
                    return ReferentResolution(status=SKIPPED, referent=typed.phrase)
            except Exception as e:
                logger.warning(f"[referent_resolver] amenity-kind check failed, refusing: {e}")

        return ReferentResolution(
            status=NOT_FOUND,
            referent=typed.phrase,
            suggestions=suggestions,
            message=self._typed_clarification(
                typed, suggestions, building_name, for_admin=for_admin
            ),
            kind=typed.kind,
        )

    async def _holds_amenity_kind(self, head: str, namespace: str) -> bool:
        """True when some instance is typed with an ontosage class whose name says ``head``.

        The class is matched as a WHOLE WORD of its CamelCase name ("ParkingArea" holds "parking";
        "carpool" does not hold "pool"), and only ontosage classes count — the building-authored
        amenity and record classes, not Brick's sensor vocabulary, so "carbon" is not held by a
        carbon-monoxide sensor.
        """
        word = re.sub(r"[^a-z0-9]", "", (head or "").lower())
        if len(word) < 4:
            return False
        q = (
            "PREFIX rdfs: <http://www.w3.org/2000/01/rdf-schema#>\n"
            "PREFIX o: <http://ontosage.org/capabilities#>\n"
            "SELECT ?s WHERE {\n"
            "  ?s a ?cls .\n"
            f'  FILTER(STRSTARTS(STR(?s), "{namespace}"))\n'
            '  FILTER(STRSTARTS(STR(?cls), "http://ontosage.org/capabilities#"))\n'
            "  FILTER NOT EXISTS { VALUES ?root { o:Record o:IntervalRecord } "
            "?cls rdfs:subClassOf+ ?root }\n"
            '  FILTER(!REGEX(STR(?cls), "(Sensor|Meter|Detector|Point|Status)$"))\n'
            '  BIND(LCASE(REPLACE(REPLACE(STR(?cls), "^.*#", ""), "([a-z])([A-Z])", "$1 $2")) AS ?w)\n'
            f'  FILTER(REGEX(?w, "(^|[^a-z0-9]){word}s?([^a-z0-9]|$)"))\n'
            "} LIMIT 1"
        )
        return len(_bindings(await self._exec(q))) > 0

    async def _exists_terms(self, terms: List[str], namespace: str) -> bool:
        """True if ONE subject in ``namespace`` matches every term.

        A term may match the subject's local name, its ``rdfs:label``, or its class
        LOCAL name — so "chiller" resolves whether the building names the instance
        ``Chiller_01`` or types a generically-named instance as ``brick:Chiller``.

        Every term must co-occur in the SAME field. Scattering them was a bug: a
        multi-word referent could match because one field (e.g. an entity's label,
        which often carries the site's own name) held one term while an unrelated
        field (a schema type URI) held another — two fields, one false positive.
        Requiring a single field to hold all terms is what "this thing exists"
        actually means. Building-agnostic: only the active namespace and the user's
        own words are used, and both subject and type are reduced to their local
        names so the namespace host can never supply a term.
        """
        return await self._exists_terms_query(terms, namespace, whole_word=False)

    async def _exists_whole_words(self, terms: List[str], namespace: str) -> bool:
        """Like ``_exists_terms`` but each term must stand as a WHOLE word in the field.

        A short quantity word is a substring of far too much: "on" is in "carbon", "co" in "co2"
        and "colour", "no" in "noise". Used for measured quantities of four letters or fewer, where
        a substring hit says nothing about whether the building measures the thing named.
        """
        return await self._exists_terms_query(terms, namespace, whole_word=True)

    async def _exists_terms_query(self, terms: List[str], namespace: str, whole_word: bool) -> bool:
        """The one query behind both existence tests; ``whole_word`` swaps CONTAINS for a word match."""
        cleaned = [t.lower().strip() for t in terms if t and t.strip()]
        if not cleaned:
            return True

        def _holds(field: str, t: str) -> str:
            if whole_word and t.isalnum():
                return f'REGEX({field}, "(^|[^a-z0-9]){t}([^a-z0-9]|$)")'
            return f'CONTAINS({field}, "{t}")'

        def _field_holds_all(field: str) -> str:
            return "(" + " && ".join(_holds(field, t) for t in cleaned) + ")"

        # Anchor on ``?s a ?cls`` rather than ``?s ?p ?o``: every entity carries a
        # type, so this visits each entity ONCE instead of once per triple — the
        # difference between scanning ~155k triples and ~thousands of entities, which
        # is what made the check slow enough to time out under load (BUG-136). The
        # type is also had for free from the same pattern.
        q = (
            "PREFIX rdfs: <http://www.w3.org/2000/01/rdf-schema#>\n"
            "SELECT ?s WHERE {\n"
            "  ?s a ?cls .\n"
            "  OPTIONAL { ?s rdfs:label ?l }\n"
            f'  FILTER(STRSTARTS(STR(?s), "{namespace}"))\n'
            f"  BIND(LCASE(SUBSTR(STR(?s), {len(namespace) + 1})) AS ?local)\n"
            '  BIND(LCASE(REPLACE(STR(?cls), "^.*[#/]", "")) AS ?clslocal)\n'
            '  BIND(LCASE(COALESCE(STR(?l), "")) AS ?lbl)\n'
            f"  FILTER({_field_holds_all('?local')} "
            f"|| {_field_holds_all('?lbl')} "
            f"|| {_field_holds_all('?clslocal')})\n"
            "} LIMIT 1"
        )
        return len(_bindings(await self._exec(q))) > 0

    #: The Brick root a suggestion must sit beneath, per referent kind. A suggestion is
    #: offered as "what this building does have" INSTEAD of the thing asked about, so it
    #: has to be the same kind of thing.
    _SUGGEST_ROOT = {
        KIND_SPACE: "https://brickschema.org/schema/Brick#Location",
        KIND_FLOOR: "https://brickschema.org/schema/Brick#Location",
        KIND_EQUIPMENT: "https://brickschema.org/schema/Brick#Equipment",
    }

    async def _suggest_terms(self, terms: List[str], namespace: str, kind: str = "") -> List[str]:
        """Up to 5 real entity names of the same kind (e.g. the floors that DO exist).

        KIND-FILTERED. Without it this matched any entity whose name merely CONTAINS the
        term, and every suggestion it produced was the wrong kind of thing — measured live:

            "verified corridor" -> "CCTV Corridor F1, CCTV Corridor F2, ..."   (cameras)
            "lift lobby"        -> "CHK-301, CHK-302, CHK-303"                 (checkpoints)
            "room"              -> "Alcohol Vapor MQ3 Gas Sensor 5.01, ..."    (sensors)

        The sentence it feeds reads "What this building does have: ...", offered in place of
        the space that was asked for. Answering a question about a corridor with a list of
        cameras named after corridors is not a smaller answer, it is a different one — and
        it makes the decline look careless in exactly the moment the system is being honest.

        The kind is dropped when unknown, which keeps the old behaviour rather than
        returning nothing.
        """
        t = (terms[0] if terms else "").lower()
        if not t:
            return []
        root = self._SUGGEST_ROOT.get(kind, "")
        kind_clause = f"  ?cls rdfs:subClassOf* <{root}> .\n" if root else ""
        q = (
            "PREFIX rdfs: <http://www.w3.org/2000/01/rdf-schema#>\n"
            "SELECT DISTINCT ?s WHERE {\n"
            "  ?s a ?cls .\n"  # anchor on typed entities — fast, same reason as _exists_terms
            + kind_clause
            + "  OPTIONAL { ?s rdfs:label ?l }\n"
            f'  FILTER(STRSTARTS(STR(?s), "{namespace}"))\n'
            # Local name, not full URI — a term that lives in the namespace itself
            # would otherwise match every subject.
            f"  BIND(LCASE(SUBSTR(STR(?s), {len(namespace) + 1})) AS ?local)\n"
            f'  FILTER(CONTAINS(?local, "{t}") '
            f'|| CONTAINS(LCASE(COALESCE(STR(?l), "")), "{t}"))\n'
            "} LIMIT 60"
        )
        names: set[str] = set()
        for b in _bindings(await self._exec(q)):
            uri = b.get("s", {}).get("value", "")
            local = uri.split("#")[-1].split("/")[-1]
            if local:
                names.add(local.replace("_", " "))
        return sorted(names)[:5]

    @staticmethod
    def _typed_clarification(
        typed: TypedReferent,
        suggestions: List[str],
        building_name: str,
        for_admin: bool = False,
    ) -> str:
        """Honest refusal + what the building does have, for everyone; plus how to make the
        question answerable (connect-data contract) for an administrator only."""
        from orchestrator.services.grounding_guard import (
            SUBJECT_EQUIPMENT,
            SUBJECT_SENSOR,
            SUBJECT_SPACE,
            enablement_hint,
        )

        kind_word = {
            KIND_FLOOR: "floor",
            KIND_SPACE: "space",
            KIND_EQUIPMENT: "equipment",
            KIND_MEASURAND: "measurement",
        }.get(typed.kind, "referent")

        if typed.kind == KIND_MEASURAND:
            head = (
                f"**{building_name}** has no sensor measuring **{typed.phrase}**, "
                f"so I can’t report a {typed.phrase} value — I won’t substitute a "
                f"different measurement."
            )
            subject_kind = SUBJECT_SENSOR
        else:
            head = (
                f"I couldn’t find **{typed.phrase}** in **{building_name}**’s model, "
                f"so I can’t return data for it — the readings I have belong to other "
                f"{kind_word}s and attributing them to {typed.phrase} would be wrong."
            )
            subject_kind = {
                KIND_EQUIPMENT: SUBJECT_EQUIPMENT,
                KIND_SPACE: SUBJECT_SPACE,
                KIND_FLOOR: SUBJECT_SPACE,
            }.get(typed.kind, SUBJECT_SPACE)

        if suggestions:
            head += f"\n\nWhat this building does have: **{', '.join(suggestions)}**."

        return head + enablement_hint(subject_kind, typed.phrase, for_admin=for_admin)

    # ------------------------------------------------------------------ helpers

    async def _exists(self, token: str, namespace: str) -> bool:
        """True if any subject in ``namespace`` has ``token`` in its URI or rdfs:label."""
        t = token.lower()
        # Two narrow lookups, never one scan of every triple (BUG-544). The single query
        # this replaced walked `?s ?p ?o` with an EXISTS per subject: a word that IS in the
        # graph hit LIMIT 1 in under a second, but a word that is NOT ("room MOVES") scanned
        # the whole graph — 27.6 s measured on the active building — and under load crossed the 30 s client
        # timeout, so the turn declined with "the existence check didn't complete in time".
        # Labels answer most referents; typed subjects cover an IRI with no label. Measured
        # on 5.01 / atrium / kitchen / chiller: every hit the old query found, ~2.5 s a miss.
        prefix = "PREFIX rdfs: <http://www.w3.org/2000/01/rdf-schema#>\n"
        by_label = (
            prefix + "SELECT ?s WHERE {\n"
            "  ?s rdfs:label ?l .\n"
            f'  FILTER(STRSTARTS(STR(?s), "{namespace}") && CONTAINS(LCASE(STR(?l)), "{t}"))\n'
            "} LIMIT 1"
        )
        if _bindings(await self._exec(by_label)):
            return True
        by_iri = (
            prefix + "SELECT ?s WHERE {\n"
            "  ?s a ?type .\n"
            f'  FILTER(STRSTARTS(STR(?s), "{namespace}") && CONTAINS(LCASE(STR(?s)), "{t}"))\n'
            "} LIMIT 1"
        )
        return len(_bindings(await self._exec(by_iri))) > 0

    async def _matching_ids(self, token: str, namespace: str) -> set:
        """The DISTINCT dotted ids whose subjects contain ``token``.

        Distinct IDS, never a count of subjects: every sensor in Room5.01 has "5.01" in its
        URI, so counting subjects would call an unambiguous room ambiguous twenty times over.
        The set is what decides — "5.1" matching {5.10, 5.11, 5.12} is three places, and
        "5.01" matching {5.01} is one however many points sit in it.
        """
        t = token.lower()
        query = (
            "SELECT DISTINCT ?s WHERE {\n"
            "  ?s a ?type .\n"
            f'  FILTER(STRSTARTS(STR(?s), "{namespace}") && CONTAINS(LCASE(STR(?s)), "{t}"))\n'
            "} LIMIT 200"
        )
        ids: set = set()
        for b in _bindings(await self._exec(query)):
            uri = b.get("s", {}).get("value", "")
            # EVERY dotted id in the subject, and only those containing the token. Taking
            # the FIRST one offered "2.5" as a candidate for "5.1" — a subject can carry
            # more than one number, and the one that matched is the one worth suggesting.
            for m in _DOTTED_ID_RE.finditer(uri):
                if t in m.group(0).lower():
                    ids.add(m.group(0))
        return ids

    async def _suggest(self, token: str, namespace: str) -> List[str]:
        """Return up to 5 real dotted-id locations closest to ``token``."""
        q = (
            "SELECT DISTINCT ?s WHERE {\n"
            "  ?s ?p ?o .\n"
            f'  FILTER(STRSTARTS(STR(?s), "{namespace}"))\n'
            '  FILTER(REGEX(STR(?s), "[0-9]{1,2}[.][0-9]{1,2}"))\n'
            "} LIMIT 400"
        )
        data = await self._exec(q)
        ids: set[str] = set()
        for b in _bindings(data):
            uri = b.get("s", {}).get("value", "")
            m = _DOTTED_ID_RE.search(uri)
            if m:
                ids.add(m.group(0))
        if not ids:
            return []
        ids_sorted = sorted(ids)
        # Prefer typo-close matches (e.g. "5.2" → "5.28"); otherwise fall back to a
        # small sample of real zones so a wildly-wrong id ("99.99") still gets the
        # user a concrete, valid starting point instead of an empty hand.
        close = difflib.get_close_matches(token, ids_sorted, n=5, cutoff=0.3)
        return close or ids_sorted[:5]

    @staticmethod
    def _clarification(token: str, suggestions: List[str], building_name: str) -> str:
        head = (
            f'I couldn’t find "{token}" in {building_name}, '
            f"so I can’t return sensor data for it."
        )
        if suggestions:
            opts = ", ".join(suggestions)
            return (
                f"{head} Did you mean one of these zones: **{opts}**? "
                'You can also ask "list all zones" to see what exists.'
            )
        return (
            f"{head} Try asking “list all zones” (or “list zones on floor N”) "
            "to see the valid locations, then name an existing zone or sensor."
        )


def _bindings(data: dict) -> list:
    """Extract the bindings list from a standard SPARQL-results dict, defensively."""
    if not isinstance(data, dict):
        return []
    results = data.get("results", {})
    if isinstance(results, dict):
        b = results.get("bindings", [])
        return b if isinstance(b, list) else []
    return []
