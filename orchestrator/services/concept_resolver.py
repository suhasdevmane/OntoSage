"""
concept_resolver.py — HBCO lay-term resolution for the dialogue/SPARQL pipeline.

Translates lay-language terms in a user query into structured concept metadata
(brick classes + recipe IDs) from the Human-Building Conversation Ontology (HBCO).

Integration points:
  - dialogue_agent: calls resolve() after LLM entity extraction; stores results
    in state.intermediate_results["concepts"] (NEW reserved key).
  - sparql_agent._infer_class: checks concepts FIRST, falls back to static map.
  - analytics node: if concepts carry a recipe_id, fetches recipe thresholds to
    enrich the analytics prompt with numeric context.

Caching: concept map loaded from GraphDB once and cached in Redis (key
  cache:concept:hbco_all, 24h TTL). Cache is shared across requests.

Routing-precedence safety: this module ONLY affects class inference and recipe
  selection.  It does NOT affect intent routing — routing-precedence rules in
  CLAUDE.md (report-intake > capability, actuation → control-decline, etc.)
  must continue to run unchanged in dialogue_agent and _route_from_dialogue.
"""

from __future__ import annotations

import hashlib
import json
import re
from dataclasses import dataclass, field
from functools import lru_cache
from typing import AbstractSet, Any, Dict, FrozenSet, List, Optional, Pattern, Tuple

from shared.config import settings
from shared.utils import get_logger

logger = get_logger(__name__)

_HBCO = "http://ontosage.org/hbco#"
_CONCEPT_CACHE_KEY = "cache:concept:hbco_all"
_CONCEPT_CACHE_TTL = 86400  # 24 hours
#: A resolution the model reasoned out is stable for a building, so it is cached for a day:
#: the second person to use a new phrasing pays nothing for it.
_SEMANTIC_CACHE_TTL = 86400

_SPARQL_LOAD_CONCEPTS = """\
PREFIX hbco: <http://ontosage.org/hbco#>
PREFIX xsd:  <http://www.w3.org/2001/XMLSchema#>
SELECT ?concept ?layTerm ?brickClass ?recipe ?confidence WHERE {
  ?concept a hbco:Concept ;
           hbco:layTerm ?layTerm .
  OPTIONAL { ?concept hbco:mapsToBrickClass ?brickClass }
  OPTIONAL { ?concept hbco:requiresRecipe   ?recipe }
  OPTIONAL { ?concept hbco:confidence       ?confidence }
}"""


@dataclass
class ConceptMatch:
    concept_id: str
    lay_term: str
    brick_classes: List[str] = field(default_factory=list)
    recipe_id: Optional[str] = None
    confidence: str = ""
    #: True when the model chose this concept because no lay term matched. Carried so a reader can
    #: tell a word the ontology knows from one it was reasoned about, and so the two can be counted
    #: separately when the vocabulary is reviewed.
    semantic: bool = False

    def to_dict(self) -> Dict[str, Any]:
        return {
            "concept_id": self.concept_id,
            "lay_term": self.lay_term,
            "brick_classes": self.brick_classes,
            "recipe_id": self.recipe_id,
            "confidence": self.confidence,
            "semantic": self.semantic,
        }


def _concept_id_from_uri(uri: str) -> str:
    """e.g. 'http://ontosage.org/hbco#stuffiness' -> 'stuffiness'"""
    return uri.split("#")[-1].split("/")[-1]


async def _cache_get(key: str) -> Optional[str]:
    """Read a cached semantic resolution. Absent Redis is a miss, never an error."""
    try:
        from orchestrator.redis_manager import redis_manager

        return await redis_manager.get_cache(key)
    except Exception:
        return None


async def _cache_set(key: str, value: str) -> None:
    try:
        from orchestrator.redis_manager import redis_manager

        await redis_manager.set_cache(key, value, ttl=_SEMANTIC_CACHE_TTL)
    except Exception:
        pass


#: IRI stem -> CURIE prefix, for every vocabulary a concept may map a class from.
#: A concept can legitimately name a class Brick does not have — the OCBV layer exists
#: for exactly that — and those IRIs must come back as CURIEs like everything else.
_CLASS_PREFIXES = (
    ("https://brickschema.org/schema/Brick#", "brick:"),
    ("http://ontosage.org/capabilities#", "ontosage:"),
    ("http://ontosage.org/hbco#", "hbco:"),
)


def _brick_local(uri: str) -> str:
    """Shorten a class IRI to a CURIE.

    Only Brick was handled here, so an OCBV class came back as a BARE FULL IRI. Two
    things broke on that, both silently: the caller's most-specific-class check looks
    for an ``ontosage:`` prefix and never matched, so a concept naming both a class and
    its Brick parent always resolved to the PARENT — "how many parking spaces are
    free?" answered 294, the building's space count, from a 40-instance generic class
    instead of the one parking sensor. And had it been chosen, a bare IRI embedded in
    generated SPARQL is a syntax error, because an IRI needs angle brackets where a
    CURIE does not.
    """
    for stem, prefix in _CLASS_PREFIXES:
        if stem in uri:
            return prefix + uri.split("#")[-1]
    return uri


def _parse_bindings(bindings: list) -> Dict[str, ConceptMatch]:
    """Group SPARQL result rows by concept URI -> ConceptMatch."""
    by_concept: Dict[str, Dict[str, Any]] = {}
    for row in bindings:
        curi = row.get("concept", {}).get("value", "")
        if not curi:
            continue
        if curi not in by_concept:
            by_concept[curi] = {
                "concept_id": _concept_id_from_uri(curi),
                "lay_terms": set(),
                "brick_classes": set(),
                "recipe_id": None,
                "confidence": "",
            }
        entry = by_concept[curi]
        lt = row.get("layTerm", {}).get("value", "")
        if lt:
            entry["lay_terms"].add(lt.lower())
        bc = row.get("brickClass", {}).get("value", "")
        if bc:
            entry["brick_classes"].add(_brick_local(bc))
        recipe = row.get("recipe", {}).get("value", "")
        if recipe and not entry["recipe_id"]:
            entry["recipe_id"] = recipe
        conf = row.get("confidence", {}).get("value", "")
        if conf:
            entry["confidence"] = conf

    # Convert to list-of-dicts for JSON serialisation
    result: Dict[str, Dict[str, Any]] = {}
    for curi, entry in by_concept.items():
        result[curi] = {
            "concept_id": entry["concept_id"],
            "lay_terms": sorted(entry["lay_terms"]),
            "brick_classes": sorted(entry["brick_classes"]),
            "recipe_id": entry["recipe_id"],
            "confidence": entry["confidence"],
        }
    return result


# ── surface forms: plurals and one-letter slips ─────────────────────────────────────────────
#
# A lay term was matched as an EXACT whole word, so the vocabulary reached only the form the
# mapping happened to list: "temperatures", "light levels", "the lifts" and "VOCs" reached no
# concept while their singulars did, and a one-letter slip ("ennergy use") reached nothing. Both
# repairs below act on the QUESTION's surface form and look ONLY at the concept vocabulary, never
# at arbitrary text: a word is repaired only into a word some lay term already contains.


@lru_cache(maxsize=8192)
def _term_regex(term: str) -> Pattern[str]:
    """Whole-word pattern for a lay term whose LAST word may also appear plural (s, es, y->ies)."""
    body, tail = re.escape(term), ""
    last = term[-1:]
    if last.isalpha() and last != "s":
        if last == "y" and len(term) >= 7 and term[-2] not in "aeiou":
            body, tail = re.escape(term[:-1]), "(?:y|ies)"
        else:
            tail = "(?:e?s)?"
    return re.compile(r"(?<![a-z])" + body + tail + r"(?![a-z])")


#: The word that FOLLOWS a hyphen, when a lay term opens a compound.
_COMPOUND_HEAD_RE = re.compile(r"-([a-z]+)")


def term_names_the_subject(term: str, text: str, vocabulary: AbstractSet[str]) -> bool:
    """True when ``term`` appears in ``text`` as a word about the thing, not as a modifier.

    A HYPHENATED COMPOUND'S HEAD IS ITS LAST ELEMENT (measured live 2026-09-19). "Will clock drift,
    time-zone settings or a DAYLIGHT-SAVING transition change any access window?" matched the lay
    term "daylight" — the boundary check treats a hyphen as a word edge — so the question resolved
    to an illuminance measurand and was refused as covering 269 illuminance sensors. It names no
    quantity at all: "daylight-saving" is about time.

    The head decides, and the vocabulary is the only judge of it. "temperature-humidity combination"
    keeps its temperature concept because "humidity" is itself a concept word, so the compound is a
    coordinate pair and the question does name the quantity; "privacy-safe", "emergency-access" and
    "evacuation-assistance" lose theirs, because "safe", "access" and "assistance" are not
    quantities and the first element is describing them. Same rule the record registry applies to
    register terms (`_only_modifies`), in the other vocabulary.

    A term that CLOSES a compound ("sub-meter") is the head and always matches.

    ``vocabulary`` must be the set of WHOLE lay terms, not the words inside them: "saving", "safe"
    and "efficient" all appear inside some multi-word term ("energy saving"), and taking the words
    would have let "daylight-saving", "privacy-safe" and "energy-efficient" through.
    """
    pattern = _term_regex(term)
    for match in pattern.finditer(text or ""):
        tail = (text or "")[match.end() :]
        head = _COMPOUND_HEAD_RE.match(tail)
        if head is None:
            return True  # not opening a compound at all
        word = head.group(1)
        if word in vocabulary or word.rstrip("s") in vocabulary:
            return True  # a coordinate pair: both elements name something measured
    return False


#: Shortest word a slip is repaired in. Below it one edit reaches too many real words.
_SLIP_MIN_LEN = 6
#: Shortest vocabulary word in which a dropped or extra letter that is NOT a doubled one is
#: repaired. Short words are one letter from too many other real words ("contract"/"contact",
#: "portable"/"potable"); the long domain words a person actually misspells are not.
_SLIP_INNER_EDIT_MIN_LEN = 8

#: Real words one edit from a vocabulary word, which a repair must never touch. Each was found by
#: running the repair over the question banks and reading what it changed; the test that pins this
#: set re-derives the neighbours from the tracked bank, so a new one cannot slip in silently.
_REAL_WORDS_NEAR_VOCABULARY: FrozenSet[str] = frozenset(
    {
        "binding",  # not "blinding"
        "lightning",  # not "lighting"
        "dipping",  # not "dripping"
    }
)


def _one_slip_apart(a: str, b: str) -> bool:
    """``a`` is ``b`` with ONE slip: adjacent letters swapped, a letter doubled or un-doubled, or
    (in a long word) one letter dropped or added inside it. Never a changed letter, and never a
    different ENDING: "measured" for "measure" is an inflection, not a slip, and a substitution
    ("seating" for "heating") is the commonest way one real word becomes another."""
    if a == b or abs(len(a) - len(b)) > 1 or a[:1] != b[:1]:
        return False
    if len(a) == len(b):
        diffs = [i for i, (x, y) in enumerate(zip(a, b)) if x != y]
        if len(diffs) == 2 and diffs[1] == diffs[0] + 1:
            i, j = diffs
            return a[i] == b[j] and a[j] == b[i]
        return False
    short, long_ = (a, b) if len(a) < len(b) else (b, a)
    for i in range(len(long_)):
        if long_[:i] + long_[i + 1 :] != short:
            continue
        if (i > 0 and long_[i] == long_[i - 1]) or (
            i + 1 < len(long_) and long_[i] == long_[i + 1]
        ):
            return True  # a doubled letter: "ennergy", "controll"
        # Any other extra letter counts only inside a long word, and never at or just before an
        # inflection ending: "measured" is not a slip of "measure", "consumers" not of "consumes".
        if i == len(long_) - 1 or (i == len(long_) - 2 and long_[-1] in "sd"):
            return False
        return len(b) >= _SLIP_INNER_EDIT_MIN_LEN
    return False


@lru_cache(maxsize=16384)
def _slip_target(word: str, vocabulary: FrozenSet[str]) -> Optional[str]:
    """The ONE vocabulary word ``word`` is a slip of, or ``None`` (none, or more than one)."""
    if word in vocabulary or word in _REAL_WORDS_NEAR_VOCABULARY:
        return None
    for suffix in ("es", "s"):  # a plural of a vocabulary word is the term pattern's job
        if word.endswith(suffix) and word[: -len(suffix)] in vocabulary:
            return None
    near = [v for v in vocabulary if _one_slip_apart(word, v)]
    return near[0] if len(near) == 1 else None


def whole_lay_terms(concept_map: Dict[str, Dict[str, Any]]) -> FrozenSet[str]:
    """Every lay term, whole — the judge of a hyphen compound's head (see term_names_the_subject)."""
    return frozenset(
        (term or "").lower()
        for entry in concept_map.values()
        for term in entry.get("lay_terms", [])
        if term
    )


def _vocabulary_words(concept_map: Dict[str, Dict[str, Any]]) -> FrozenSet[str]:
    """Every word of ``_SLIP_MIN_LEN`` letters or more that some lay term contains."""
    words = set()
    for entry in concept_map.values():
        for term in entry.get("lay_terms", []):
            words.update(
                w for w in re.findall(r"[a-z]+", (term or "").lower()) if len(w) >= _SLIP_MIN_LEN
            )
    return frozenset(words)


def repair_slips(text: str, vocabulary: FrozenSet[str]) -> str:
    """``text`` with each word that is one slip from a vocabulary word replaced by that word."""
    if not vocabulary:
        return text

    def _fix(match: "re.Match[str]") -> str:
        word = match.group(0)
        return _slip_target(word, vocabulary) or word

    return re.sub(r"(?<![a-z])[a-z]{%d,}(?![a-z])" % _SLIP_MIN_LEN, _fix, text)


class ConceptResolver:
    """Resolve lay-language terms in a query to HBCO concept metadata."""

    def __init__(self) -> None:
        self._vocabulary_key: Tuple[int, int] = (0, -1)
        self._vocabulary: FrozenSet[str] = frozenset()

    def _vocabulary_of(self, concept_map: Dict[str, Dict[str, Any]]) -> FrozenSet[str]:
        """The slip-repair vocabulary of ``concept_map``, rebuilt only when the map changes."""
        # id() alone can repeat once a map is freed, so the term count rides along in the key.
        key = (id(concept_map), sum(len(e.get("lay_terms", ())) for e in concept_map.values()))
        if key != self._vocabulary_key:
            self._vocabulary, self._vocabulary_key = _vocabulary_words(concept_map), key
            # The referent gate must not decline a quantity the lay vocabulary explains.
            try:
                from orchestrator.services.referent_resolver import register_concept_terms
            except (ImportError, KeyError):  # the offline reach loader has no package to import from
                return self._vocabulary
            register_concept_terms(t for e in concept_map.values() for t in e.get("lay_terms", []))
        return self._vocabulary

    async def _load_concept_map(self) -> Dict[str, Dict[str, Any]]:
        """Fetch full concept map from Redis cache or GraphDB. Returns {concept_uri: entry}."""
        try:
            from orchestrator.redis_manager import redis_manager

            cached = await redis_manager.get_cache(_CONCEPT_CACHE_KEY)
            if cached and isinstance(cached, dict):
                return cached
        except Exception as e:
            logger.debug(f"[concept_resolver] Redis unavailable: {e}")

        data = await self._fetch_from_graphdb()
        if data:
            try:
                from orchestrator.redis_manager import redis_manager

                await redis_manager.set_cache(_CONCEPT_CACHE_KEY, data, ttl=_CONCEPT_CACHE_TTL)
            except Exception as e:
                logger.debug(f"[concept_resolver] Redis cache write skipped: {e}")
        return data

    async def _fetch_from_graphdb(self) -> Dict[str, Dict[str, Any]]:
        """Run SPARQL against GraphDB to load all HBCO concepts + lay terms."""
        endpoint = (
            f"http://{settings.GRAPHDB_HOST}:{settings.GRAPHDB_PORT}"
            f"/repositories/{settings.GRAPHDB_REPOSITORY}"
        )
        try:
            import httpx

            async with httpx.AsyncClient(timeout=15.0) as client:
                resp = await client.post(
                    endpoint,
                    content=_SPARQL_LOAD_CONCEPTS.encode(),
                    headers={
                        "Content-Type": "application/sparql-query",
                        "Accept": "application/sparql-results+json",
                    },
                )
                if resp.status_code != 200:
                    logger.warning(f"[concept_resolver] GraphDB returned {resp.status_code}")
                    return {}
                data = resp.json()
                bindings = data.get("results", {}).get("bindings", [])
        except Exception as e:
            logger.warning(f"[concept_resolver] failed to fetch concepts from GraphDB: {e}")
            return {}

        result = _parse_bindings(bindings)
        logger.info(f"[concept_resolver] loaded {len(result)} concept(s) from GraphDB")
        return result

    async def resolve(self, text: str) -> List[ConceptMatch]:
        """Find all HBCO concepts whose lay terms appear in the query text.

        Returns a list of ConceptMatch objects ordered by lay_term length
        (longer, more specific matches first).
        """
        if not text:
            return []

        normalized = text.lower()
        concept_map = await self._load_concept_map()
        if not concept_map:
            return []
        normalized = repair_slips(normalized, self._vocabulary_of(concept_map))
        vocabulary = whole_lay_terms(concept_map)

        matches: List[ConceptMatch] = []
        for entry in concept_map.values():
            # THE LONGEST MATCHING TERM represents the concept, not the first one found.
            # This used to `break` on the first hit in whatever order the terms came back
            # from the graph (effectively alphabetical), so "how full is the recycling bin"
            # was recorded as matching "bin" and then lost the cross-concept sort below —
            # which ranks by the length of that recorded term — to a concept matching the
            # longer word "full". The sort's whole premise, longer is more specific, only
            # holds if each concept is represented by its most specific evidence.
            best: Optional[str] = None
            for lay_term in entry.get("lay_terms", []):
                if not lay_term:
                    continue
                # Whole-word boundary check to avoid 'hot' matching 'shot'; a plural still matches,
                # and a term that merely OPENS a hyphen compound ("daylight-saving") names nothing.
                if term_names_the_subject(lay_term, normalized, vocabulary) and (
                    best is None or len(lay_term) > len(best)
                ):
                    best = lay_term
            if best is not None:
                matches.append(
                    ConceptMatch(
                        concept_id=entry["concept_id"],
                        lay_term=best,
                        brick_classes=list(entry.get("brick_classes", [])),
                        recipe_id=entry.get("recipe_id"),
                        confidence=entry.get("confidence", ""),
                    )
                )

        # Sort: longer lay term first (more specific), then by confidence
        _conf_order = {"high": 0, "medium": 1, "low": 2, "": 3}
        matches.sort(key=lambda m: (-len(m.lay_term), _conf_order.get(m.confidence, 3)))
        if matches:
            return matches

        # NOTHING MATCHED LITERALLY, so ask the model which of THIS building's concepts is meant.
        # The list above only knows the words somebody wrote down: it held "warmest", "hottest" and
        # "coldest" but not "coolest", so "where's the coolest place to work right now?" resolved to
        # no measurand, nothing contradicted the classifier's guess that a question mentioning "place
        # to work" belonged to the workspace register, and a temperature question was answered from a
        # register holding no temperature. Adding the missing word fixes one phrasing and leaves the
        # next; this fixes the shape.
        #
        # It runs only here, on a miss, so a building whose vocabulary already covers the words is
        # unaffected. It can only CHOOSE from the concepts just loaded, never invent one.
        return await self._semantic_fallback(text, concept_map)

    async def _semantic_fallback(
        self, text: str, concept_map: Dict[str, Dict[str, Any]]
    ) -> List[ConceptMatch]:
        """One model call that picks a concept from this building's own list, or nothing."""
        try:
            from orchestrator.services import semantic_concept_match as scm
        except Exception:
            return []
        if not scm.enabled():
            return []
        try:
            got = await scm.match(
                text,
                concept_map,
                cache_get=_cache_get,
                cache_set=_cache_set,
            )
        except Exception as exc:  # a fallback must never cost the deterministic answer
            logger.debug(f"[concept_resolver] semantic fallback skipped: {exc}")
            return []
        if not got.matched:
            return []
        # The map is keyed by IRI, so find the entry whose short concept_id was chosen.
        entry = next(
            (e for e in concept_map.values() if str(e.get("concept_id")) == got.concept_id), {}
        )
        logger.info(
            "[concept_resolver] semantic match %r -> %s (%s)",
            " ".join(str(text).split())[:60], got.concept_id, got.reason[:60],
        )
        return [
            ConceptMatch(
                concept_id=got.concept_id,
                # The word the person actually used is unknown, so the concept id stands in as the
                # evidence. It is never empty, which the cross-concept sort above relies on.
                lay_term=got.concept_id,
                brick_classes=list(entry.get("brick_classes") or got.brick_classes),
                recipe_id=entry.get("recipe_id"),
                confidence=entry.get("confidence", ""),
                semantic=True,
            )
        ]

    async def invalidate_cache(self) -> None:
        """Clear the Redis concept map cache (call after HBCO TTL is re-uploaded)."""
        try:
            from orchestrator.redis_manager import redis_manager

            await redis_manager.delete_cache(_CONCEPT_CACHE_KEY)
            logger.info("[concept_resolver] concept cache cleared")
        except Exception as e:
            logger.debug(f"[concept_resolver] cache clear skipped: {e}")


# Module-level singleton
concept_resolver = ConceptResolver()
