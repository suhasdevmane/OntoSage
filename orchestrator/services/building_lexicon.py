# -*- coding: utf-8 -*-
r"""The words and identifier shapes THIS building actually uses (V10 W2-1).

WHY THIS EXISTS
---------------
`scripts/check_building_literals.py` passes. That is not the same as being
building-agnostic, and the gap is the whole point of this module.

The routing layer carries several hand-written vocabularies -- measurand words, space
nouns, and regexes for room and zone identifiers. None of them is a building LITERAL, so no
grep finds them, and every one of them was tuned against one building:

    _ROOM_ID_RE   = r"\\b(room|rm)[_\\s]?\\d+(\\.\\d+)?\\b"
    _ZONE_ID_RE   = r"\\bzone[_\\s][\\d]+\\.[\\d]+\\b"
    _SENSOR_ID_RE = r"\\b([A-Za-z][A-Za-z0-9]*_)+Sensor_[\\d.]+\\b"

A building numbering rooms `RM-204` matches none of them -- the hyphen alone defeats the
first. A building naming rooms `Atrium` and `Long Gallery` is invisible to all three. The
symptom is not an error: the question simply fails a bypass check, takes a different lane,
and comes back plausibly wrong.

WHAT THIS IS NOT
----------------
**Not a replacement for the generic lists.** "temperature", "average", "last week" and
"room" are domain English, not one building's vocabulary, and deleting them in favour of
graph-derived terms would make routing WORSE for every building -- a building whose graph is
still loading would lose the ability to recognise a trend question. The lexicon AUGMENTS:
the constants are the floor, and this adds what the building itself says.

**Not a referent check.** Knowing the shape of this building's room identifiers is not
knowing which rooms exist; `referent_resolver` answers that and runs regardless.

HOW THE IDENTIFIER SHAPE IS LEARNED
-----------------------------------
From the identifiers themselves, never from a rule. Each space's local name and label is
stripped of a leading type word ("Room 5.01" -> "5.01", "RM-204" -> "RM-204"), and the
remainder is generalised character-class by character-class. `5.01` and `12.7` both yield
`\\d+\\.\\d+`; `RM-204` yields `[A-Za-z]+-\\d+`; `Atrium` yields a literal alternative.
Identical shapes collapse, so a 234-room building produces two or three alternatives rather
than 234.

Cached per `building_id` for the process lifetime. Room names do not change between
requests, and routing runs on every turn.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Callable, Dict, FrozenSet, List, Optional, Sequence, Set

from shared.utils import get_logger

logger = get_logger(__name__)

#: Type words that precede an identifier and are not part of it. Domain English.
_TYPE_WORDS = (
    "room",
    "rm",
    "space",
    "zone",
    "office",
    "lab",
    "laboratory",
    "floor",
    "level",
    "storey",
    "suite",
    "unit",
)

_LEADING_TYPE_RE = re.compile(
    r"^(?:" + "|".join(_TYPE_WORDS) + r")[\s_\-]*", re.IGNORECASE
)

#: How many distinct identifier shapes are worth carrying. A building with more than this
#: is not using a naming convention, and a regex built from it would match almost anything.
_MAX_SHAPES = 6


@dataclass(frozen=True)
class BuildingLexicon:
    """What this building calls things. Every field may be empty."""

    building_id: str = ""
    #: Words naming a measurable quantity, from the ontology's measurands and lay terms.
    measurands: FrozenSet[str] = frozenset()
    #: Lower-case nouns for a place, from the Brick space classes that HAVE instances.
    space_nouns: FrozenSet[str] = frozenset()
    #: The identifier shapes this building's spaces actually use.
    identifier_shapes: tuple = ()
    #: Every space identifier, exactly. Bounded; empty when the building is very large.
    identifiers: FrozenSet[str] = frozenset()

    @property
    def usable(self) -> bool:
        return bool(self.measurands or self.space_nouns or self.identifier_shapes)

    def identifier_pattern(self) -> Optional[re.Pattern]:
        """A regex matching an identifier of any shape this building uses, or None."""
        if not self.identifier_shapes:
            return None
        body = "|".join(f"(?:{s})" for s in self.identifier_shapes)
        return re.compile(rf"\b(?:{'|'.join(_TYPE_WORDS)})?[\s_\-]*(?:{body})\b", re.IGNORECASE)

    def mentions_identifier(self, text: str) -> bool:
        pat = self.identifier_pattern()
        return bool(pat and pat.search(text or ""))

    def mentions_measurand(self, text: str) -> bool:
        low = (text or "").lower()
        return any(w in low for w in self.measurands)


# ── shape learning ───────────────────────────────────────────────────────────


#: A label's descriptive tail is not part of the identifier. Anything from the first
#: em dash, en dash, hyphen-with-spaces, colon, slash or bracket onward is description.
_LABEL_TAIL_RE = re.compile(r"\s*(?:[\u2014\u2013:(/]|\s-\s).*$")


def strip_type_word(name: str) -> str:
    r"""The IDENTIFIER inside a space's name.

    `Room 5.01`                     -> `5.01`
    `3.15 - Meeting Room`           -> `3.15`
    `HVAC Zone 5.21`                -> `5.21`
    `RM-204`                        -> `RM-204`
    `Server_Room_F5`                -> `Server_Room_F5`
    `Atrium`                        -> `Atrium`

    THE TAIL IS THE POINT. Feeding whole labels to the shape learner produced twenty
    distinct shapes for one building -- `\d+\.\d+`, then `\d+\.\d+ - [A-Za-z]+ [A-Za-z]+`,
    then the same with three words, then with a bracket -- because the DESCRIPTION varies
    even where the identifier convention does not. Twenty shapes reads as "no convention",
    which is exactly the wrong conclusion about a building that numbers every room `N.NN`.

    `RM-204` keeps its prefix: `rm` is a type word, but removing it leaves `204`, and a
    bare number matches far too much free text to be a useful identifier.
    """
    text = str(name or "").strip()
    # Drop the descriptive tail first, so a type word buried in it cannot mislead.
    head = _LABEL_TAIL_RE.sub("", text).strip()
    stripped = _LEADING_TYPE_RE.sub("", head).strip()

    if stripped and re.search(r"\d", stripped) and not (
        len(stripped) <= 3 and stripped.isdigit()
    ):
        # A residual phrase ("Zone 5.21" after "HVAC ") keeps only its identifier token:
        # the LAST whitespace-separated token containing a digit.
        tokens = [tok for tok in stripped.split() if re.search(r"\d", tok)]
        if tokens and len(stripped.split()) > 1:
            return tokens[-1].strip(".,;")
        return stripped

    if not head:
        return text
    # No digit anywhere: a word-named space. Returned whole, and never shape-learned --
    # matching bare words as identifiers would make every mention of "atrium" in free
    # text look like a room reference.
    return head


def shape_of(identifier: str) -> str:
    """A regex source describing this identifier's SHAPE.

    Character classes rather than the characters: `5.01` and `12.7` collapse to one shape,
    which is what makes a 234-room building produce two alternatives instead of 234.
    """
    text = str(identifier or "").strip()
    if not text:
        return ""
    out: List[str] = []
    i = 0
    while i < len(text):
        ch = text[i]
        if ch.isdigit():
            j = i
            while j < len(text) and text[j].isdigit():
                j += 1
            out.append(r"\d+")
            i = j
        elif ch.isalpha():
            j = i
            while j < len(text) and text[j].isalpha():
                j += 1
            out.append(r"[A-Za-z]+")
            i = j
        else:
            out.append(re.escape(ch))
            i += 1
    return "".join(out)


def learn_shapes(identifiers: Sequence[str], max_shapes: int = _MAX_SHAPES) -> tuple:
    """The distinct shapes these identifiers use, commonest first.

    Returns () when the identifiers agree on nothing -- a building with more than
    `max_shapes` conventions is not using one, and a regex built from it would match
    almost any word. Saying nothing is better than matching everything.
    """
    counts: Dict[str, int] = {}
    for ident in identifiers:
        ident = str(ident or "").strip()
        # A TYPE WORD FOLLOWED BY A BARE NUMBER is not an identifier shape.
        #
        # "Floor 4" survives strip_type_word intact -- correctly, because "4" alone is
        # useless as an identifier -- and then generalises to `[A-Za-z]+ \d+`, which
        # matches "last 7", "Windows 10" and "COVID 19" in ordinary free text. One
        # building's six floors would have made every sentence containing a word and a
        # number look like a room reference.
        #
        # Excluded from SHAPE learning only. The name stays in `identifiers`, so an exact
        # lookup still finds it.
        # Only when the type word stood as its OWN WORD. `Floor 4` is a type word and a
        # number; `RM-204` is a glued prefix that happens to contain one, and its `204`
        # would be stripped by the same rule -- which silently cost the whole `RM-\d+`
        # grammar its shape, the exact building this module exists to support.
        without_tail = _LABEL_TAIL_RE.sub("", ident).strip()
        first, _, rest = without_tail.partition(" ")
        if rest and first.lower() in _TYPE_WORDS and rest.strip().isdigit():
            continue
        s = shape_of(strip_type_word(ident))
        # A shape with no digit in it is a WORD, and matching bare words as identifiers
        # would make every mention of "atrium" look like a room reference in free text.
        # Word-named spaces are matched exactly, through `identifiers`, not by shape.
        if not s or r"\d+" not in s:
            continue
        counts[s] = counts.get(s, 0) + 1
    ordered = sorted(counts, key=lambda s: (-counts[s], s))
    return tuple(ordered[:max_shapes]) if len(ordered) <= max_shapes else ()


# ── building the lexicon ─────────────────────────────────────────────────────

_SPACES_QUERY = """
PREFIX brick: <https://brickschema.org/schema/Brick#>
PREFIX rdfs:  <http://www.w3.org/2000/01/rdf-schema#>
SELECT ?s (SAMPLE(?lab) AS ?label) (GROUP_CONCAT(DISTINCT ?c; separator=" ") AS ?classes)
WHERE {
  ?s a ?c . ?c rdfs:subClassOf* brick:Location .
  FILTER NOT EXISTS { ?s a brick:Building }
  OPTIONAL { ?s rdfs:label ?lab }
  FILTER(STRSTARTS(STR(?s), "%(ns)s"))
} GROUP BY ?s LIMIT 5000
"""

_MEASURAND_QUERY = """
PREFIX o:    <http://ontosage.org/capabilities#>
PREFIX hbco: <http://ontosage.org/hbco#>
PREFIX rdfs: <http://www.w3.org/2000/01/rdf-schema#>
SELECT DISTINCT ?word WHERE {
  {
    # Quantities the ontology declares, and that this building has an instrument for.
    ?cls o:measuresQuantityKind ?kind .
    ?sensor a ?cls .
    ?kind rdfs:label ?word .
  } UNION {
    # Lay terms for a concept, which is how people actually ask.
    ?concept a hbco:Concept ; hbco:layTerm ?word .
  }
}
"""

_CACHE: Dict[str, BuildingLexicon] = {}


def _local(iri: str) -> str:
    return str(iri).rsplit("#", 1)[-1].rsplit("/", 1)[-1]


async def lexicon_for(
    building_id: str, namespace: str, sparql_exec: Callable
) -> BuildingLexicon:
    """This building's vocabulary, read once from its graph and cached.

    Never raises. A building whose graph cannot be read gets an EMPTY lexicon, and every
    caller then falls back to its generic list -- which is how routing behaved before this
    module existed, so an unreachable graph costs nothing that was previously working.
    """
    key = f"{building_id}|{namespace}"
    hit = _CACHE.get(key)
    if hit is not None:
        return hit

    identifiers: Set[str] = set()
    nouns: Set[str] = set()
    measurands: Set[str] = set()

    try:
        res = await sparql_exec(_SPACES_QUERY % {"ns": namespace})
        for b in (res or {}).get("results", {}).get("bindings", []):
            local = _local(b.get("s", {}).get("value", ""))
            label = (b.get("label") or {}).get("value", "")
            for candidate in (local, label):
                ident = strip_type_word(candidate)
                if ident:
                    identifiers.add(ident)
            for cls in str((b.get("classes") or {}).get("value", "")).split():
                noun = _local(cls).replace("_", " ").strip().lower()
                # Multi-word Brick names ("Conference Room") contribute their head noun
                # too, because that is the word a person uses.
                if noun:
                    nouns.add(noun)
                    tail = noun.rsplit(" ", 1)[-1]
                    if len(tail) > 2:
                        nouns.add(tail)
    except Exception as exc:
        logger.warning(f"[building_lexicon] spaces unavailable: {exc}")

    try:
        res = await sparql_exec(_MEASURAND_QUERY)
        for b in (res or {}).get("results", {}).get("bindings", []):
            word = str(b.get("word", {}).get("value", "")).strip().lower()
            if 2 < len(word) <= 40:
                measurands.add(word)
    except Exception as exc:
        logger.warning(f"[building_lexicon] measurands unavailable: {exc}")

    shapes = learn_shapes(sorted(identifiers))
    lex = BuildingLexicon(
        building_id=building_id,
        measurands=frozenset(measurands),
        space_nouns=frozenset(nouns),
        identifier_shapes=shapes,
        # Bounded: the exact set is a convenience for callers that want to check a
        # specific string, not a referent check, and a very large building does not need
        # to carry one through every routing decision.
        identifiers=frozenset(identifiers) if len(identifiers) <= 5000 else frozenset(),
    )
    _CACHE[key] = lex
    logger.info(
        f"[building_lexicon] {building_id or '?'}: {len(measurands)} measurand word(s), "
        f"{len(nouns)} space noun(s), {len(shapes)} identifier shape(s) "
        f"{list(shapes)[:4]}"
    )
    return lex


def clear_cache(building_id: Optional[str] = None) -> None:
    """Drop the cache — after a swap, or a re-ingest that renamed spaces."""
    if building_id is None:
        _CACHE.clear()
        return
    for k in [k for k in _CACHE if k.startswith(f"{building_id}|")]:
        _CACHE.pop(k, None)


def cached_for(building_id: str, namespace: str = "") -> Optional[BuildingLexicon]:
    """The cached lexicon, without a round trip. None when it has not been built yet.

    For SYNCHRONOUS callers -- the routing contract's rules are sync by design, and making
    them async to consult a cache would be the wrong trade. A rule that finds no lexicon
    uses its generic list, which is what it did before.
    """
    if namespace:
        return _CACHE.get(f"{building_id}|{namespace}")
    for k, v in _CACHE.items():
        if k.startswith(f"{building_id}|"):
            return v
    return None
