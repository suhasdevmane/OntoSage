# -*- coding: utf-8 -*-
"""facets.py — the facet catalogue: what can be known about which kind of entity (v2, P2).

WHY THIS EXISTS
---------------
ARBITER's vocabulary was the sensed-modality list, so its only facets were readings and its only
target was a space. A question that combined a reading with anything the building holds as a
RECORD or a TTL PROPERTY -- "a quiet room for twelve with a projector" -- compiled the seat count
and the projector to unmapped terms and was clarified away. The building knows those things; the
compiler was never told they exist.

A FACET is one thing that can be known about one kind of entity: its entity type, a stable key, the
kind of source it comes from, its value type and unit, how a value reaches the entity (the join),
the words people use for it, a few values actually present, and how available it is. This module
derives every facet from the active building's own graph and configuration. It names no building,
no class of any building's and no count: point it at another building's graph and it describes
that building.

WHERE EACH SOURCE KIND COMES FROM -- reused, never re-implemented
-----------------------------------------------------------------
  sensor   one facet per room-scoped modality, from ``coverage_audit.CoverageAuditor`` -- the
           same space x modality matrix the admission gate reads. Lay terms from the modality
           config's ``lay_terms``, the compiler's ``_LAY_HINTS`` and the graph's HBCO concepts.
  record   every datatype predicate on the instances of every held record class
           (``record_registry.read_record_classes`` + ``predicate_profile_query``, the query
           ``schema_hint`` reads). The entity type comes from the P1 link the instances carry.
  ttl      datatype predicates on the building's spaces; capacity ONLY through
           ``design_occupancy`` and its authority order, never as a raw read.
  event    the executor's two availability checks (``cqir.EventCriterion``), backed by the
           booking records in the graph and the building's registered events store; and the
           EVENT SOURCES a series can be related to (C5): every held record class whose records
           are placed in a space AND on the clock (``event_sources``), value type ``interval``.
  spatial  floor membership, and the numeric facts of route records joined to the space a route
           reaches (``routeToSpace``).

THE AVAILABILITY LADDER -- computed, never guessed
--------------------------------------------------
  declared   the class or predicate exists (configured, declared in the TBox or a mapping, or used)
  linked     at least one instance joins to an entity of the facet's type
  populated  at least one value exists
  suitable   the value type is known (one datatype family in the data) and coverage >= 1 --
             at least one ENTITY has a value through the join

Each rung needs the one before it. ``coverage`` counts entities, never records: twenty-two AV
components in seven rooms give an AV facet a coverage of seven.

RETRIEVAL
---------
``FacetCatalogue.retrieve`` ranks facets for a question by lexical evidence alone, so the
compiler's prompt can carry the twenty-five most relevant facets however large the building is.
Event sources (``interval``) are NOT in that index: an event stream is not a criterion a space is
filtered or ranked on, only the operand of a relation, so it never competes with criteria for a
prompt slot or a routing decision -- and adding a building's event sources leaves every existing
facet's retrieval score unchanged. ``match_event_sources`` reads them with the same whole-term
matcher, over their own vocabulary only.
Evidence comes in tiers -- the facet's own words (label, lay terms, the predicate's local name),
then the values an enum actually holds and the unit, then the register's class vocabulary -- and
each word is weighted by how few facets share it, so "status" (on nearly every register) counts
for little and "projector" for a lot. A multi-word term found whole in the question scores its
words twice, so it outranks the same words found apart.
"""

from __future__ import annotations

import math
import re
from collections import defaultdict
from dataclasses import dataclass
from pathlib import Path
from typing import (
    Any,
    Awaitable,
    Callable,
    Dict,
    FrozenSet,
    Iterable,
    Iterator,
    List,
    Mapping,
    Optional,
    Sequence,
    Set,
    Tuple,
)

from orchestrator.services import design_occupancy, record_registry
from orchestrator.services.deliberation import event_sources
from orchestrator.services.deliberation.capability_schema import _FLOOR_WORDS
from orchestrator.services.deliberation.compiler import _LAY_HINTS, _base_form
from orchestrator.services.deliberation.coverage_audit import (
    STATUS_PRESENT,
    STATUS_UNBACKED,
    CoverageAuditor,
    ModalitySpec,
    SpaceCoverage,
    SparqlExec,
    _bindings,
    _local,
    _val,
    load_modality_raw,
)
from orchestrator.services.record_documents import (
    ColumnSpec,
    expand_predicate,
    load_mapping,
)
from orchestrator.services.record_entity_links import (
    FLOOR_PREDICATE,
    LINK_PREDICATE_IRIS,
    LINK_PREDICATES,
    LOCATED_IN,
    PLACES_QUERY,
    ROUTE_FROM,
    ROUTE_TO,
    SERVES,
)
from orchestrator.services.register_facts import provenance_fields
from shared.utils import describe_exception, get_logger

logger = get_logger(__name__)

# ── vocabulary of the catalogue itself ─────────────────────────────────────────────────

ENTITY_TYPES: Tuple[str, ...] = ("space", "floor", "route", "asset", "building")
SOURCE_KINDS: Tuple[str, ...] = ("sensor", "record", "ttl", "event", "spatial")
#: The value type of an event source: per space, a set of time intervals (C5).
INTERVAL = "interval"
VALUE_TYPES: Tuple[str, ...] = (
    "number",
    "integer",
    "boolean",
    "enum",
    "text",
    "datetime",
    INTERVAL,
)
#: The availability ladder, lowest rung first.
LADDER: Tuple[str, ...] = ("declared", "linked", "populated", "suitable")

#: A string predicate with at most this many distinct values, some of them repeated, is an enum.
ENUM_MAX_VALUES = 12
#: ...and only when every one of those values is a LABEL, not a sentence. A register's note
#: column can repeat five long notes across forty rows; that is prose, and treating it as a value
#: set would hand every word of it to retrieval as evidence.
ENUM_MAX_CHARS = 60
MAX_EXAMPLES = 5
#: An example longer than this is shown as an excerpt: examples illustrate, they do not quote.
_EXAMPLE_CHARS = 80

_ONTOSAGE = record_registry.ONTOSAGE
_RDF_TYPE = "http://www.w3.org/1999/02/22-rdf-syntax-ns#type"
_BRICK_HAS_LOCATION = "https://brickschema.org/schema/Brick#hasLocation"
_BRICK_IS_PART_OF = "https://brickschema.org/schema/Brick#isPartOf"
#: The start of a record's period (TBox Module J: "Start of the period. Inclusive."). A booking
#: whose start is recorded is a booking an availability check can place in time.
_PERIOD_START = _ONTOSAGE + "effectiveFrom"

_MAPPINGS_DIR = Path(__file__).resolve().parents[3] / "ontology" / "record_documents"

_PREFIXES = (
    "PREFIX rdf: <http://www.w3.org/1999/02/22-rdf-syntax-ns#>\n"
    "PREFIX rdfs: <http://www.w3.org/2000/01/rdf-schema#>\n"
    "PREFIX owl: <http://www.w3.org/2002/07/owl#>\n"
    "PREFIX brick: <https://brickschema.org/schema/Brick#>\n"
    "PREFIX o: <http://ontosage.org/capabilities#>\n"
    "PREFIX hbco: <http://ontosage.org/hbco#>\n"
)

# ── the facet ──────────────────────────────────────────────────────────────────────────


@dataclass(frozen=True)
class Facet:
    """One thing that can be known about one kind of entity, and how available it is."""

    #: Stable id: ``<source>:<name>`` -- "sensor:co2", "record:<Class>.<predicate>",
    #: "ttl:<predicate>", "ttl:capacity", "event:free_window", "spatial:floor".
    key: str
    entity_type: str
    source_kind: str
    label: str
    value_type: str
    unit: Optional[str] = None
    #: The facet's own words beyond its label and predicate name: hints, aliases, column names.
    lay_terms: Tuple[str, ...] = ()
    record_class: Optional[str] = None
    predicate: Optional[str] = None
    modality: Optional[str] = None
    #: How a value reaches its entity. None when the value sits on the entity itself, or when
    #: the entity is the whole building.
    join_predicate: Optional[str] = None
    #: Up to MAX_EXAMPLES distinct values actually present; an enum's whole value set.
    examples: Tuple[str, ...] = ()
    status: str = "declared"
    #: How many ENTITIES of ``entity_type`` have a value through the join.
    coverage: int = 0
    #: The register's own vocabulary (its class label and lay terms). Weaker evidence than
    #: ``lay_terms``: it says which register a question is about, not which of its fields.
    class_terms: Tuple[str, ...] = ()
    #: Where a value must be read through, when a raw read would be wrong.
    resolver: Optional[str] = None
    #: Other ways the same value reaches an entity: (entity type, join predicate, coverage).
    other_joins: Tuple[Tuple[str, str, int], ...] = ()
    #: Computed caveats: a datatype the mapping and the data disagree on, a store that cannot
    #: be verified from the graph.
    notes: Tuple[str, ...] = ()
    #: An event source's (role, predicate) pairs: how its records are placed on the clock
    #: (``event_sources.time_roles``). Empty for every other facet.
    roles: Tuple[Tuple[str, str], ...] = ()

    @property
    def rank(self) -> int:
        """The facet's rung on the availability ladder, 0 (declared) to 3 (suitable)."""
        return LADDER.index(self.status)

    def at_least(self, status: str) -> bool:
        """True when the facet has reached ``status`` on the ladder."""
        return self.rank >= LADDER.index(status)


def ladder_status(linked: bool, populated: bool, typed: bool, coverage: int) -> str:
    """The highest rung a DECLARED facet reaches; each rung requires the one before it."""
    if not linked:
        return "declared"
    if not populated:
        return "linked"
    if typed and coverage >= 1:
        return "suitable"
    return "populated"


# ── words ──────────────────────────────────────────────────────────────────────────────

_TOKEN_RE = re.compile(r"[a-z0-9]+(?:\.[a-z0-9]+)*")
_CAMEL_RE = re.compile(r"(?<=[a-z0-9])(?=[A-Z])|(?<=[A-Z])(?=[A-Z][a-z])")
_NUMERIC_RE = re.compile(r"\d+(?:st|nd|rd|th|am|pm|h|hr|hrs|min|mins|m|s|k)?")

#: Irregular plurals a question uses for a unit or a lay term ("twelve people" for persons).
_IRREGULAR = {"people": "person"}

#: Words that never NAME a facet. Grammar (the register scorer's own function-word list), the
#: frame of a request, time references (the IR's time spec owns those), quantities (they are
#: values, not facets) and the nouns that name the TARGET of a question rather than a fact
#: about it. Generic English only. A target noun still takes part in a multi-word term ("room
#: capacity"), it just cannot be evidence on its own, because nearly every question has one.
_FRAME_WORDS = frozenset(
    """what which where who whom whose why how is are was were be been being am do does did done
    can could would should will shall may must have has had having i me my mine we us our ours
    you your yours he him his she they them their theirs one ones please find show give tell
    list want wants need needs looking look get got let know see make like also just only very
    really there here something anything somewhere anywhere""".split()
)
_TIME_WORDS = frozenset(
    """today tomorrow tonight yesterday morning mornings afternoon afternoons evening evenings
    night nights currently current right later soon upcoming next week weeks weekend weekday
    weekdays month months year years day days moment""".split()
)
_NUMBER_WORDS = frozenset(
    """zero one two three four five six seven eight nine ten eleven twelve thirteen fourteen
    fifteen sixteen seventeen eighteen nineteen twenty thirty forty fifty sixty seventy eighty
    ninety hundred thousand dozen couple few several half""".split()
)
_TARGET_NOUNS = frozenset(
    """room rooms space spaces place places area areas spot spots location locations building
    buildings site""".split()
)
#: The nouns that name the TARGET of a question, public for callers that must tell a phrase
#: shortened by dropping its target noun ("desk space" -> "desk") from one shortened by dropping
#: a word that carried its meaning ("in use" -> "use").
TARGET_NOUNS: FrozenSet[str] = _TARGET_NOUNS
#: Degree, comparison and summary words. They say WHICH WAY or HOW MUCH ("the least crowded",
#: "the most seats", "on average") -- the IR's direction and operation -- never which facet.
_DEGREE_WORDS = frozenset(
    """most least more less higher lower highest lowest best worst better worse good bad top
    bottom many much lot lots fewer fewest max maximum min minimum average mean total overall
    too than compare compared comparing comparison versus vs""".split()
)
_NON_CONTENT = (
    record_registry._FUNCTION_WORDS
    | _FRAME_WORDS
    | _TIME_WORDS
    | _NUMBER_WORDS
    | _TARGET_NOUNS
    | _DEGREE_WORDS
)

#: A local name ENDING in a unit word states its unit: allowMinutes, routeDistanceMetres.
_UNIT_SUFFIXES = frozenset(
    """minutes mins hours seconds days weeks months years metres meters litres liters percent
    kg kwh lux ppm""".split()
)

#: Extra words for a few unit symbols, so "22 degrees" reaches a temperature in degC.
_UNIT_WORDS: Dict[str, Tuple[str, ...]] = {
    "degc": ("degrees", "celsius"),
    "db": ("decibels",),
    "percent": ("percentage",),
}


def split_camel(name: str) -> str:
    """A predicate or class local name as words: seatCount -> "seat count"."""
    return _CAMEL_RE.sub(" ", str(name or "")).replace("_", " ").strip().lower()


def _tokens(text: str) -> List[str]:
    """Lowercase word tokens; a dot inside a token is dropped, so "PM2.5" is "pm25"."""
    return [t.replace(".", "") for t in _TOKEN_RE.findall(str(text or "").lower())]


def _is_number(token: str) -> bool:
    return token in _NUMBER_WORDS or bool(_NUMERIC_RE.fullmatch(token))


def _is_content(token: str) -> bool:
    return len(token) >= 2 and token not in _NON_CONTENT and not _is_number(token)


def _singular(word: str) -> str:
    """English singular, enough for a lay term: rooms -> room, facilities -> facility."""
    w = _IRREGULAR.get(word, word)
    if len(w) > 4 and w.endswith("ies"):
        return w[:-3] + "y"
    if len(w) > 4 and w.endswith(("sses", "shes", "ches", "xes")):
        return w[:-2]
    if len(w) > 3 and w.endswith("s") and not w.endswith(("ss", "us", "is")):
        return w[:-1]
    return w


def _vocab_forms(canon: str) -> FrozenSet[str]:
    """Every spelling a question may use for one vocabulary word (already singular)."""
    forms = {canon, record_registry.plural_of(canon)}
    forms |= {plural for plural, single in _IRREGULAR.items() if single == canon}
    return frozenset(forms)


def _question_forms(word: str) -> FrozenSet[str]:
    """A question word in every form a vocabulary word could match.

    The comparative and superlative reduce through the compiler's own ``_base_form``
    ("quietest" -> "quiet"); plurals both ways. Base forms are taken of the QUESTION only: a
    vocabulary noun ending in -er ("water", "meter") must not be cut to a stem that some other
    question word then matches.
    """
    w = _IRREGULAR.get(word, word)
    base = _base_form(w)
    forms = {w, _singular(w), record_registry.plural_of(w), base, _singular(base)}
    return frozenset(f for f in forms if f)


def _canon(word: str) -> str:
    return _singular(_IRREGULAR.get(word, word))


# ── the catalogue ──────────────────────────────────────────────────────────────────────

#: Evidence tiers and their weights. A facet's own words are the strongest evidence; the values
#: an enum holds and the unit say what a question is about less directly; the register's class
#: vocabulary says which register, not which field.
_TIER_WEIGHTS: Dict[str, float] = {"own": 1.0, "value": 0.5, "unit": 0.5, "class": 0.15}
#: A unit word right after a number ("twelve PEOPLE", "5 MINUTES") is a quantity stated in that
#: unit, which is as strong as naming the facet.
_QUANTITY_FACTOR = 2.0


@dataclass(frozen=True)
class _Term:
    """One piece of a facet's vocabulary: its content words, canonical and in order."""

    tier: str
    content: Tuple[str, ...]


@dataclass(frozen=True)
class TermMatch:
    """One piece of a facet's vocabulary found WHOLE in a question -- what retrieval scores.

    ``retrieve`` sums these into one number per facet. A caller that must judge the evidence
    rather than rank by it -- the compound-question router has to tell "a word that names this
    facet" from "a word this facet happens to carry" -- reads them itemised here.

    ``positions`` index the question's CONTENT words (the words retrieval reads), so two matches
    sharing a position were found on the same word. ``weight`` is the term's inverse document
    frequency (doubled for a multi-word term found together), before any tier weight.
    ``phrases`` are the vocabulary texts the term was made from, as lowercase words, function
    words included: "in use" made the one-word term "use", and only the phrase says so.
    A ``value`` match is a WHOLE enum value; ``value_word`` is one word found inside a longer
    value, the description match retrieval also credits ("seminar" in "Lecture / seminar room").
    """

    key: str
    tier: str
    words: Tuple[str, ...]
    positions: Tuple[int, ...]
    weight: float
    quantity: bool = False
    phrases: Tuple[str, ...] = ()


def content_words(text: str) -> Tuple[str, ...]:
    """The canonical content words retrieval matches ``text`` by (what a term is made of)."""
    return tuple(_canon(t) for t in _tokens(text) if _is_content(t))


def plain_words(text: str) -> List[str]:
    """Every lowercase word of ``text``, function words included, as ``TermMatch.phrases`` are."""
    return _tokens(text)


def _make_term(tier: str, text: str) -> Optional[_Term]:
    content = content_words(text)
    return _Term(tier, content) if content else None


def facet_vocabulary(facet: Facet) -> List[Tuple[str, str]]:
    """(tier, text) for every piece of vocabulary a facet is retrieved by, tier by tier."""
    own = [facet.label, *facet.lay_terms]
    if facet.predicate:
        own.append(split_camel(_local(facet.predicate)))
    if facet.modality:
        own.append(facet.modality.replace("_", " "))
    texts: List[Tuple[str, str]] = [("own", t) for t in own]
    if facet.value_type == "enum":
        texts += [("value", v) for v in facet.examples]
    if facet.unit and facet.value_type != "boolean":
        texts.append(("unit", facet.unit))
        texts += [("unit", w) for w in _UNIT_WORDS.get(facet.unit.lower(), ())]
    texts += [("class", t) for t in facet.class_terms]
    return texts


def _facet_term_phrases(facet: Facet) -> List[Tuple[_Term, Tuple[str, ...]]]:
    """Each distinct term of a facet, in vocabulary order, with every phrase that made it."""
    order: List[_Term] = []
    phrases: Dict[_Term, List[str]] = {}
    for tier, text in facet_vocabulary(facet):
        term = _make_term(tier, text)
        if term is None:
            continue
        if term not in phrases:
            order.append(term)
            phrases[term] = []
        phrase = " ".join(_tokens(text))
        if phrase not in phrases[term]:
            phrases[term].append(phrase)
    return [(term, tuple(phrases[term])) for term in order]


def _facet_terms(facet: Facet) -> List[_Term]:
    """The vocabulary a facet is retrieved by, tier by tier."""
    return [term for term, _ in _facet_term_phrases(facet)]


class FacetCatalogue:
    """Every facet the active building supports, and deterministic retrieval over them."""

    def __init__(
        self,
        facets: Iterable[Facet],
        *,
        building_id: str = "",
        namespace: str = "",
        entity_counts: Optional[Mapping[str, int]] = None,
        errors: Sequence[str] = (),
    ) -> None:
        self.facets: Tuple[Facet, ...] = tuple(sorted(facets, key=lambda f: f.key))
        self.building_id = building_id
        self.namespace = namespace
        #: How many spaces and floors the building has, for reading coverage against.
        self.entity_counts: Dict[str, int] = dict(entity_counts or {})
        #: Sources that could not be read. Non-empty means the catalogue is PARTIAL: a facet
        #: missing from it is "not known", never "not held".
        self.errors: Tuple[str, ...] = tuple(errors)
        self._by_key = {f.key: f for f in self.facets}
        #: The facets criterion retrieval ranks: every facet but an event source (see RETRIEVAL).
        self._retrievable: Tuple[Facet, ...] = tuple(
            f for f in self.facets if f.value_type != INTERVAL
        )
        self._event_index: Optional["FacetCatalogue"] = None
        self._index()

    # ── lookups ──────────────────────────────────────────────────────────────────────

    def __len__(self) -> int:
        return len(self.facets)

    def __iter__(self) -> Iterator[Facet]:
        return iter(self.facets)

    def get(self, key: str) -> Optional[Facet]:
        """The facet with this key, or None."""
        return self._by_key.get(key)

    def for_entity(self, entity_type: str) -> List[Facet]:
        """Every facet about one entity type, in key order."""
        return [f for f in self.facets if f.entity_type == entity_type]

    def counts(self) -> Dict[str, Dict[str, int]]:
        """{source_kind: {entity_type: number of facets}}."""
        out: Dict[str, Dict[str, int]] = {}
        for f in self.facets:
            row = out.setdefault(f.source_kind, {})
            row[f.entity_type] = row.get(f.entity_type, 0) + 1
        return out

    def status_counts(self) -> Dict[str, int]:
        """{rung: number of facets on it}, every rung present."""
        out = {rung: 0 for rung in LADDER}
        for f in self.facets:
            out[f.status] += 1
        return out

    # ── event sources (C5) ──────────────────────────────────────────────────────────

    def event_sources(self, min_status: str = "suitable") -> List[Facet]:
        """The building's event sources at or above ``min_status``, most widely placed first."""
        return sorted(
            (f for f in self.facets if f.value_type == INTERVAL and f.at_least(min_status)),
            key=lambda f: (-f.coverage, f.key),
        )

    def event_source_matches(self, question: str) -> List[TermMatch]:
        """Every whole term of a suitable event source's own vocabulary ``question`` contains.

        The same matcher retrieval uses, over the event sources' words only (their label and the
        class's declared lay terms), itemised with the question positions they were found at. A
        one-word term cut down from a longer phrase ("entrance" from "which entrance") counts only
        when the question holds the whole phrase -- the rule the compound router applies for the
        same reason.
        """
        sources = self.event_sources()
        if not sources or not (question or "").strip():
            return []
        if self._event_index is None:
            from dataclasses import replace

            self._event_index = FacetCatalogue(
                replace(f, value_type="text", examples=(), class_terms=()) for f in sources
            )
        plain = " " + " ".join(plain_words(question)) + " "
        out: List[TermMatch] = []
        for match in self._event_index.term_matches(question):
            if match.tier != "own":
                continue
            if len(match.words) == 1 and match.phrases:
                whole = [p for p in match.phrases if len(p.split()) == 1 or f" {p} " in plain]
                if not whole:
                    continue
            out.append(match)
        return out

    def match_event_sources(self, question: str) -> List[Facet]:
        """The suitable event sources ``question`` names by a WHOLE term of their own vocabulary,
        best evidence first (``event_source_matches``, summed per source)."""
        named: Dict[str, float] = {}
        for match in self.event_source_matches(question):
            named[match.key] = named.get(match.key, 0.0) + match.weight
        ranked = sorted(named, key=lambda k: (-named[k], k))
        return [self._by_key[k] for k in ranked if k in self._by_key]

    # ── retrieval ────────────────────────────────────────────────────────────────────
    #
    # A TERM MATCHES WHOLE OR NOT AT ALL. Its content words must appear in the question in the
    # same order with nothing but non-content words between them ("step-free within 10 minutes"
    # carries "step free minutes"). Credit for one word of a longer term was measured to be
    # mostly noise: "suitable for study" lent "study" to a CO2 facet, and "quiet in terms of
    # people" lent "quiet" to occupancy. The one exception is an ENUM VALUE, which is a
    # description rather than a name: "Lecture / seminar room" is evidence for "seminar".

    def _index(self) -> None:
        """Build the terms, the first-word index, the value postings and the word weights."""
        self._terms: List[Tuple[int, _Term]] = []
        #: The vocabulary phrases each term (by its index in ``_terms``) was made from.
        self._phrases: List[Tuple[str, ...]] = []
        self._by_first: Dict[str, List[int]] = defaultdict(list)
        self._value_words: Dict[str, Set[int]] = defaultdict(set)
        document_frequency: Dict[str, Set[int]] = defaultdict(set)
        vocabulary: Set[str] = set()
        for idx, facet in enumerate(self._retrievable):
            for term, phrases in _facet_term_phrases(facet):
                self._by_first[term.content[0]].append(len(self._terms))
                self._terms.append((idx, term))
                self._phrases.append(phrases)
                vocabulary.update(term.content)
                if term.tier == "value":
                    for token in term.content:
                        self._value_words[token].add(idx)
                if term.tier != "class":
                    for token in term.content:
                        document_frequency[token].add(idx)
        n = max(1, len(self._retrievable))
        #: Inverse document frequency over the facets' OWN vocabulary: a word on many facets
        #: tells them apart poorly. A word only class vocabulary carries is as rare as can be.
        self._idf: Dict[str, float] = {
            token: math.log(1.0 + n / (1.0 + len(document_frequency.get(token, ()))))
            for token in vocabulary
        }
        #: The weight of a word exactly one facet carries: the strongest single-word evidence this
        #: catalogue can give. It grows with the catalogue (5.27 at 386 facets, 3.68 at 77), so a
        #: caller judging a score across buildings divides by it rather than fixing a number.
        self.unique_word_weight: float = math.log(1.0 + n / 2.0)
        self._forms: Dict[str, Set[str]] = defaultdict(set)
        for token in vocabulary:
            for form in _vocab_forms(token):
                self._forms[form].add(token)

    def _matches(self, word: str) -> Set[str]:
        """The vocabulary words one question word matches."""
        found: Set[str] = set()
        for form in _question_forms(word):
            found |= self._forms.get(form, set())
        return found

    def _evidence(
        self, question: str, collect: Optional[List[TermMatch]] = None
    ) -> Tuple[Dict[int, float], Set[int], List[Tuple[int, str]]]:
        """({facet index: score}, content positions some facet used, the content words).

        With ``collect``, every match that contributes is also appended to it, itemised (see
        ``TermMatch``). Collecting changes no score.
        """
        words = _tokens(question)
        content = [(pos, w) for pos, w in enumerate(words) if _is_content(w)]
        matched = [self._matches(w) for _, w in content]
        used: Set[int] = set()
        totals: Dict[int, float] = defaultdict(float)
        value_best: Dict[int, Dict[int, float]] = defaultdict(dict)
        hit: Set[int] = set()
        for i in range(len(content)):
            for token in sorted(matched[i]):
                for term_id in self._by_first.get(token, ()):
                    if term_id in hit:
                        continue  # a term counts once, however often the question repeats it
                    idx, term = self._terms[term_id]
                    width = len(term.content)
                    if i + width > len(content) or not all(
                        term.content[j] in matched[i + j] for j in range(width)
                    ):
                        continue
                    hit.add(term_id)
                    used.update(range(i, i + width))
                    weight = sum(self._idf.get(t, 0.0) for t in term.content)
                    if width > 1:
                        weight *= 2.0  # the words found together, as the term has them
                    pos = content[i][0]
                    quantity = term.tier == "unit" and pos > 0 and _is_number(words[pos - 1])
                    if collect is not None:
                        collect.append(
                            TermMatch(
                                key=self._retrievable[idx].key,
                                tier=term.tier,
                                words=term.content,
                                positions=tuple(range(i, i + width)),
                                weight=weight,
                                quantity=quantity,
                                phrases=self._phrases[term_id],
                            )
                        )
                    if term.tier == "value":
                        if width > 1:
                            totals[idx] += _TIER_WEIGHTS["value"] * weight / 2.0
                        continue
                    if quantity:
                        weight *= _QUANTITY_FACTOR
                    totals[idx] += _TIER_WEIGHTS[term.tier] * weight
            # An enum value's words count one by one, once per question word.
            for token in sorted(matched[i]):
                for idx in self._value_words.get(token, ()):
                    weight = self._idf.get(token, 0.0)
                    if collect is not None:
                        collect.append(
                            TermMatch(
                                key=self._retrievable[idx].key,
                                tier="value_word",
                                words=(token,),
                                positions=(i,),
                                weight=weight,
                            )
                        )
                    if weight > value_best[idx].get(i, 0.0):
                        value_best[idx][i] = weight
                        used.add(i)
        for idx, by_position in value_best.items():
            totals[idx] += _TIER_WEIGHTS["value"] * sum(by_position[i] for i in sorted(by_position))
        return dict(totals), used, content

    def term_matches(self, question: str) -> List[TermMatch]:
        """Every vocabulary term ``question`` contains, itemised: the evidence ``retrieve`` sums.

        In question order, deterministic. A term found twice is reported once, as retrieval
        counts it once.
        """
        matches: List[TermMatch] = []
        self._evidence(question, matches)
        return matches

    def scores(self, question: str) -> Dict[str, float]:
        """{facet key: score} for every facet with any evidence in the question."""
        totals, _, _ = self._evidence(question)
        return {
            self._retrievable[idx].key: round(score, 6)
            for idx, score in sorted(totals.items())
            if score > 0
        }

    def retrieve(
        self,
        question: str,
        k: int = 25,
        min_score: float = 0.0,
        min_status: Optional[str] = None,
    ) -> List[Tuple[float, Facet]]:
        """The ``k`` facets with the strongest lexical evidence in ``question``, best first.

        Only facets scoring above ``min_score`` are returned: a question naming nothing the
        building holds retrieves nothing, rather than the facets nearest to nothing. Ties
        break on the key, so the same question retrieves the same list every time.
        ``min_status`` keeps only facets at or above that rung of the ladder; by default a
        merely declared facet is returned too, so a compiler can say it is not assessable.
        """
        ranked = sorted(
            ((score, self._by_key[key]) for key, score in self.scores(question).items()),
            key=lambda pair: (-pair[0], pair[1].key),
        )
        return [
            (score, facet)
            for score, facet in ranked
            if score > min_score and (min_status is None or facet.at_least(min_status))
        ][: max(0, k)]

    def unmatched_terms(self, question: str) -> List[str]:
        """Content words of ``question`` that no facet's evidence used, in question order.

        The compiler's input for ambiguity signals: a word here named nothing the building
        holds, so the honest move is to say so, never to map it to the nearest facet.
        """
        _, used, content = self._evidence(question)
        out: List[str] = []
        for i, (_, word) in enumerate(content):
            if i not in used and word not in out:
                out.append(word)
        return out


# ── building the catalogue ─────────────────────────────────────────────────────────────

_CACHE: Dict[Tuple[str, str], FacetCatalogue] = {}


def clear_cache() -> None:
    """Forget every built catalogue (tests, and after the graph changes)."""
    _CACHE.clear()


def cached_catalogue(building_id: str, namespace: str) -> Optional[FacetCatalogue]:
    """The COMPLETE catalogue already built for this building, or None. Never builds one.

    For callers on a request path -- the router -- that must not pay for a build: a build reads
    the whole graph, and a turn that waited for one would be a turn the reader waited for. Only
    a complete catalogue is ever cached (``build_facet_catalogue`` leaves a partial one out), so
    what this returns can be read as "the building's facets", never as a fragment of them.
    """
    return _CACHE.get((str(building_id or ""), str(namespace or "")))


async def build_facet_catalogue(
    sparql_exec: SparqlExec,
    building_id: str,
    namespace: str,
    modalities: Sequence[ModalitySpec],
    *,
    mappings_dir: Optional[Path] = None,
    modality_config: Optional[Mapping[str, Mapping[str, Any]]] = None,
    events_store: Optional[bool] = None,
    refresh: bool = False,
) -> FacetCatalogue:
    """The facet catalogue of one building, from its own graph and configuration.

    ``sparql_exec`` is the async SPARQL-JSON callable ARBITER uses (``live.sparql_exec``).
    ``modalities`` is the modality set the coverage audit reads (``load_modalities``).
    ``modality_config`` is the merged raw modality config, read for its ``lay_terms``
    (``load_modality_raw(building_id)`` when omitted). ``events_store`` says whether the building
    registers an events store; None asks the live adapter registry.

    Cached per (building_id, namespace). A build in which any source could not be read is
    returned with ``errors`` set and is NOT cached, so the next call tries again.
    """
    key = (str(building_id or ""), str(namespace or ""))
    if not refresh and key in _CACHE:
        return _CACHE[key]
    builder = _Builder(
        sparql_exec,
        building_id,
        namespace,
        list(modalities),
        mappings_dir or _MAPPINGS_DIR,
        modality_config,
        events_store,
    )
    catalogue = await builder.build()
    if catalogue.errors:
        logger.warning(
            f"[facets] {building_id}: partial catalogue ({len(catalogue)} facets), "
            f"not cached: {'; '.join(catalogue.errors)}"
        )
    else:
        _CACHE[key] = catalogue
    logger.info(
        f"[facets] {building_id}: {len(catalogue)} facets "
        f"{catalogue.counts()} ladder {catalogue.status_counts()}"
    )
    return catalogue


# ── query texts ────────────────────────────────────────────────────────────────────────

#: The words HBCO concepts give to the Brick classes a sensor modality is made of.
_HBCO_QUERY = (
    _PREFIXES
    + """SELECT DISTINCT ?cls ?term WHERE {
  ?concept a hbco:Concept ; hbco:layTerm ?term ; hbco:mapsToBrickClass ?cls .
} LIMIT 20000"""
)

#: Held classes that have a held SUBclass. Under RDFS reasoning every instance of a subclass is
#: also an instance of its parent, so a parent would profile every child's predicates again.
#:
#: ONE VALUES block per query, here and below, on purpose: an engine that joins two VALUES
#: blocks first and the triple patterns after evaluates the patterns with nothing bound -- a
#: property path over the whole class hierarchy -- and only then joins. Measured offline: this
#: query did not finish in five minutes written with two VALUES blocks.
_PARENTS_QUERY = (
    _PREFIXES
    + """SELECT DISTINCT ?sup WHERE {
  VALUES ?sub { %(values)s }
  ?sub rdfs:subClassOf+ ?sup .
  FILTER(?sup != ?sub && ?sup IN (%(listed)s))
} LIMIT 2000"""
)

#: For every (class, link, predicate): how many linked instances carry the predicate and how many
#: distinct entities they reach. The rdf:type row of each (class, link) is the class's linked
#: total, since every instance carries its type. The (class, link) pairs arrive as ONE VALUES
#: block, so the link predicate is bound before its triples are read.
_LINK_QUERY = (
    _PREFIXES
    + """SELECT ?cls ?link ?p (COUNT(DISTINCT ?i) AS ?inst) (COUNT(DISTINCT ?e) AS ?ents) WHERE {
  VALUES (?cls ?link) { %(pairs)s }
  ?i a ?cls .
  ?i ?link ?e .
  ?i ?p ?v .%(scope)s
} GROUP BY ?cls ?link ?p LIMIT 50000"""
)

#: Datatype predicates the TBox declares for a class (rdfs:domain), with or without values.
_DOMAIN_QUERY = (
    _PREFIXES
    + """SELECT DISTINCT ?cls ?p WHERE {
  VALUES ?cls { %(values)s }
  ?p rdfs:domain ?cls .
  ?p a owl:DatatypeProperty .
} LIMIT 5000"""
)

#: The TBox's English label and declared range for each predicate the catalogue describes.
_LABEL_QUERY = (
    _PREFIXES
    + """SELECT ?p (SAMPLE(?l) AS ?label) (SAMPLE(?r) AS ?range) WHERE {
  VALUES ?p { %(values)s }
  OPTIONAL { ?p rdfs:label ?l . FILTER(LANG(?l) = "" || LANGMATCHES(LANG(?l), "en")) }
  OPTIONAL { ?p rdfs:range ?r }
} GROUP BY ?p LIMIT 5000"""
)

#: Literal-valued predicates on the building's spaces (brick:Space and its subclasses), profiled
#: as the record predicates are. A space carries several types under reasoning (Room, Space,
#: Location ...), so every count is DISTINCT, and the number of values is the number of distinct
#: (space, value) PAIRS -- a plain count would multiply each value by the space's types and make
#: a column of unique values look like a repeating enum.
_SPACE_PROFILE_QUERY = (
    _PREFIXES
    + """SELECT ?p (COUNT(DISTINCT ?s) AS ?carriers)
       (COUNT(DISTINCT CONCAT(STR(?s), " ", STR(?v))) AS ?values)
       (COUNT(DISTINCT ?v) AS ?distinct)
       (GROUP_CONCAT(DISTINCT STR(DATATYPE(?v)); SEPARATOR=" ") AS ?datatypes)
       (SUBSTR(GROUP_CONCAT(DISTINCT STR(?v); SEPARATOR="\\t"), 1, %(budget)d) AS ?sample)
WHERE {
  ?s a ?c . ?c rdfs:subClassOf* brick:Space .
  FILTER(STRSTARTS(STR(?s), "%(ns)s"))
  ?s ?p ?v .
  FILTER(isLiteral(?v))
} GROUP BY ?p LIMIT 2000"""
)

#: Design-occupancy predicates the TBox declares, matched the way design_occupancy matches them.
_CAPACITY_TBOX_QUERY = (
    _PREFIXES
    + """SELECT DISTINCT ?p WHERE {
  ?p a owl:DatatypeProperty .
  BIND(REPLACE(LCASE(REPLACE(STR(?p), "^.*[#/]", "")), "[^a-z0-9]", "") AS ?norm)
  FILTER(?norm IN (%(terms)s))
} LIMIT 200"""
)

# ── the executor's event kinds ─────────────────────────────────────────────────────────

#: The event-store kind the executor's availability check reads (plan_executor:
#: ``_event_availability`` overlaps "booking" rows). Joined to the held record classes BY NAME
#: through ``record_registry.event_store_record_classes``, the join BUG-670 established.
_BOOKING_EVENT_KIND = "booking"

#: The two checks ``cqir.EventCriterion`` names, as facets: (label, value type, unit, words).
#: The words are the event-kind analogue of the compiler's ``_LAY_HINTS``: generic English.
_EVENT_FACETS: Tuple[Tuple[str, str, str, Optional[str], Tuple[str, ...]], ...] = (
    (
        "free_window",
        "free for a time window (no booking overlaps it)",
        "boolean",
        None,
        (
            "free",
            "available",
            "availability",
            "vacant",
            "unbooked",
            "not booked",
            "free slot",
        ),
    ),
    (
        "booking_pressure",
        "share of the next 7 days that is booked",
        "number",
        "percent",
        ("booking pressure", "rarely booked", "least booked", "often booked", "how often booked"),
    ),
)

#: The capacity facet's words beyond the TBox labels of the predicates it reads.
_CAPACITY_WORDS: Tuple[str, ...] = ("capacity", "design occupancy")

# ── value types ────────────────────────────────────────────────────────────────────────

_XSD_FAMILIES: Dict[str, str] = {
    **{
        t: "integer"
        for t in (
            "integer int long short byte nonNegativeInteger positiveInteger negativeInteger "
            "nonPositiveInteger unsignedInt unsignedLong unsignedShort unsignedByte"
        ).split()
    },
    **{t: "number" for t in ("decimal", "double", "float")},
    **{t: "datetime" for t in ("date", "dateTime", "dateTimeStamp", "time", "gYear")},
    "boolean": "boolean",
}


def _family(datatype: str) -> Optional[str]:
    """The value type a datatype IRI (or ``xsd:`` name) belongs to; None for a non-literal."""
    text = str(datatype or "").strip()
    if not text or text == "iri":
        return None
    return _XSD_FAMILIES.get(text.rsplit("#", 1)[-1].rsplit(":", 1)[-1], "text")


def _value_type(
    datatypes: Iterable[str],
    declared: Optional[str],
    declared_values: bool,
    distinct: int,
    values: int,
    sample: Sequence[str] = (),
) -> Tuple[str, bool, List[str]]:
    """(value type, whether it is known, notes), from the data first and the declaration second.

    The data's own datatypes decide when they agree with each other. Integers mixed with
    decimals are numbers. Any other mixture means the value type is NOT known, and the facet
    cannot reach "suitable" -- the declaration is reported as the intended type, never
    assumed to be what the data holds. A string predicate whose mapping declares its values is
    an enum; so is one with a small set of short values that repeat (``sample`` holds them).
    """
    families = {f for f in (_family(d) for d in datatypes) if f}
    if families == {"integer", "number"}:
        families = {"number"}
    declared_family = _family(declared) if declared else None
    notes: List[str] = []
    if len(families) == 1:
        value_type, typed = next(iter(families)), True
        if declared_family == "number" and value_type == "integer":
            value_type = "number"
        elif declared_family and declared_family != value_type:
            notes.append(f"declared {declared}, but the data holds {value_type} values")
    elif not families:
        value_type, typed = declared_family or "text", declared_family is not None
    else:
        value_type, typed = declared_family or "text", False
        notes.append("mixed datatypes in the data: " + ", ".join(sorted(families)))
    labels = all(len(str(v).strip()) <= ENUM_MAX_CHARS for v in sample)
    if value_type == "text" and (
        declared_values or (1 <= distinct <= ENUM_MAX_VALUES and values > distinct and labels)
    ):
        value_type = "enum"
    return value_type, typed, notes


def _sort_key(value: str) -> Tuple[int, Any]:
    try:
        return (0, float(value))
    except ValueError:
        return (1, value.lower())


def _excerpt(value: str) -> str:
    text = " ".join(str(value).split())
    return text if len(text) <= _EXAMPLE_CHARS else text[: _EXAMPLE_CHARS - 1].rstrip() + "…"


def _examples(values: Iterable[str], value_type: str) -> Tuple[str, ...]:
    """Distinct values present: an enum's whole set, a spread for an ordered type, else the first."""
    distinct = sorted({str(v).strip() for v in values if str(v).strip()}, key=_sort_key)
    if value_type == "enum":
        return tuple(_excerpt(v) for v in distinct[:ENUM_MAX_VALUES])
    if value_type in ("number", "integer", "datetime") and len(distinct) > MAX_EXAMPLES:
        last = len(distinct) - 1
        picks = sorted({round(i * last / (MAX_EXAMPLES - 1)) for i in range(MAX_EXAMPLES)})
        return tuple(distinct[i] for i in picks)
    return tuple(_excerpt(v) for v in distinct[:MAX_EXAMPLES])


def _unit_from_name(local: str, value_type: str) -> Optional[str]:
    """The unit a NUMERIC predicate's name ends in: routeDistanceMetres -> "metres".

    Only for numbers: "openingHours" holds a schedule ("Mon-Fri 08:00-18:00"), not a count of
    hours, and a unit on it would be a claim about the data that the data does not make.
    """
    words = split_camel(local).split()
    if value_type not in ("number", "integer") or len(words) < 2:
        return None
    return words[-1] if words[-1] in _UNIT_SUFFIXES else None


#: Identity is not a facet: a label, a comment or an identifier names an entity, it does not
#: describe it.
_IDENTITY_LOCALS = frozenset({"label", "prefLabel", "altLabel", "comment", "identifier", "type"})
_ID_SUFFIX_RE = re.compile(r"(?<=[a-z0-9])(?:Id|ID)$")


def _is_identity(local: str) -> bool:
    return local in _IDENTITY_LOCALS or bool(_ID_SUFFIX_RE.search(local))


# ── raw rows ───────────────────────────────────────────────────────────────────────────


def _rows(payload: Any) -> List[Dict[str, str]]:
    """SPARQL-JSON bindings as plain {variable: value} rows."""
    out = []
    for binding in _bindings(payload if isinstance(payload, dict) else {}):
        out.append({var: _val(binding, var) for var in binding})
    return out


def _int(value: Any) -> int:
    try:
        return int(float(str(value or "0")))
    except ValueError:
        return 0


def _sample(text: str, budget: int) -> Tuple[str, ...]:
    parts = str(text or "").split("\t")
    if len(text or "") >= budget and len(parts) > 1:
        parts = parts[:-1]  # the last value may have been cut by the budget
    return tuple(p for p in parts if p.strip())


@dataclass
class _Profile:
    """What one predicate's values look like, read in one aggregate row."""

    carriers: int = 0
    values: int = 0
    distinct: int = 0
    literals: int = 0
    datatypes: FrozenSet[str] = frozenset()
    sample: Tuple[str, ...] = ()

    @classmethod
    def from_row(cls, row: Mapping[str, str], budget: int) -> "_Profile":
        values = _int(row.get("values"))
        return cls(
            carriers=_int(row.get("carriers")),
            values=values,
            distinct=_int(row.get("distinct")),
            # The space profile filters to literals in the query and returns no column for it.
            literals=_int(row.get("literals")) if "literals" in row else values,
            datatypes=frozenset(str(row.get("datatypes") or "").split()),
            sample=_sample(str(row.get("sample") or ""), budget),
        )


def _as_run_select(sparql_exec: SparqlExec) -> Callable[..., Awaitable[Dict[str, Any]]]:
    """``sparql_exec`` in the shape record_registry reads: (query, limit) -> {ok, rows}."""

    async def run_select(query: str, limit: int = 100) -> Dict[str, Any]:
        if not re.search(r"\bLIMIT\s+\d+", query, re.IGNORECASE):
            query = f"{query.rstrip()}\nLIMIT {limit}"
        try:
            payload = await sparql_exec(query)
        except Exception as exc:
            return {"ok": False, "rows": [], "error": describe_exception(exc)}
        return {"ok": True, "rows": _rows(payload)}

    return run_select


def _escape(text: str) -> str:
    return str(text or "").replace("\\", "\\\\").replace('"', '\\"')


def _iri_values(iris: Iterable[str]) -> str:
    return " ".join(f"<{iri}>" for iri in sorted(set(iris)))


# ── the builder ────────────────────────────────────────────────────────────────────────

#: Which entity type each link makes a record about, in precedence order: a record that names a
#: route's ends is about the route; one placed in a space is about the space, else the space it
#: serves; one placed only on a floor is about the floor.
_LINK_ENTITY: Tuple[Tuple[str, str], ...] = (
    (LINK_PREDICATES[ROUTE_TO], "route"),
    (LINK_PREDICATES[ROUTE_FROM], "route"),
    (LINK_PREDICATES[LOCATED_IN], "space"),
    (LINK_PREDICATES[SERVES], "space"),
    (FLOOR_PREDICATE, "floor"),
)


class _Builder:
    """One catalogue build: a fixed sequence of SELECTs, each source fenced off from the rest."""

    def __init__(
        self,
        sparql_exec: SparqlExec,
        building_id: str,
        namespace: str,
        modalities: List[ModalitySpec],
        mappings_dir: Path,
        modality_config: Optional[Mapping[str, Mapping[str, Any]]],
        events_store: Optional[bool],
    ) -> None:
        self.exec = sparql_exec
        self.building_id = building_id
        self.namespace = namespace
        self.modalities = modalities
        self.mappings_dir = mappings_dir
        self.modality_config = modality_config
        self.events_store = events_store
        self.facets: List[Facet] = []
        self.errors: List[str] = []
        self.space_iris: Set[str] = set()
        self.floor_labels: Dict[str, str] = {}
        self.audited: List[SpaceCoverage] = []
        self.labels: Dict[str, str] = {}
        self.ranges: Dict[str, str] = {}

    async def _select(self, query: str) -> List[Dict[str, str]]:
        return _rows(await self.exec(query))

    async def build(self) -> FacetCatalogue:
        await self._fenced("places", self._places)
        await self._fenced("sensor", self._sensors)
        records = await self._fenced("record", self._read_records)
        space_profile = await self._fenced("ttl", self._read_space_profile)
        capacity = await self._fenced("capacity", self._read_capacity)
        predicates: Set[str] = set()
        if records:
            predicates |= {p for (_, p) in records["profile"]} | {
                p for preds in records["declared"].values() for p in preds
            }
        if space_profile:
            predicates |= set(space_profile)
        if capacity:
            predicates |= set(capacity["predicates"])
        await self._fenced("labels", lambda: self._read_labels(predicates))
        if records:
            await self._fenced("record", lambda: self._record_facets(records))
            await self._fenced("events", lambda: self._event_source_facets(records))
        if space_profile is not None:
            await self._fenced("ttl", lambda: self._ttl_facets(space_profile))
        if capacity:
            await self._fenced("capacity", lambda: self._capacity_facet(capacity))
        await self._fenced("spatial", self._floor_facet)
        await self._fenced("spatial", self._space_kind_facet)
        return FacetCatalogue(
            self.facets,
            building_id=self.building_id,
            namespace=self.namespace,
            entity_counts={
                "space": len(self.space_iris),
                "floor": len(self.floor_labels),
                "room": len(self.audited),
            },
            errors=self.errors,
        )

    async def _fenced(self, source: str, step: Callable[[], Awaitable[Any]]) -> Any:
        """Run one step; a failure costs that source's facets and is recorded, never raised."""
        try:
            return await step()
        except Exception as exc:
            reason = describe_exception(exc)
            logger.warning(f"[facets] {self.building_id}: {source} unavailable: {reason}")
            self.errors.append(f"{source}: {reason}")
            return None

    # ── places ───────────────────────────────────────────────────────────────────────

    async def _places(self) -> None:
        """The building's spaces and floors, by the same query the P1 linker resolves against."""
        rows = await self._select(PLACES_QUERY % {"ns": _escape(self.namespace), "limit": 50000})
        floor_labels: Dict[str, Set[str]] = defaultdict(set)
        for row in rows:
            iri, kind = row.get("place", ""), row.get("kind", "")
            if kind == "space":
                self.space_iris.add(iri)
            elif kind == "floor":
                floor_labels[iri].add(row.get("label", ""))
        # A floor with several labels is named by the first in sort order, whatever order the
        # graph returned them in; a floor with none by its local name.
        self.floor_labels = {
            iri: min((lbl for lbl in labels if lbl), default=_local(iri))
            for iri, labels in floor_labels.items()
        }

    # ── sensors ──────────────────────────────────────────────────────────────────────

    async def _sensors(self) -> None:
        """One facet per room-scoped modality, from the coverage audit's space x modality matrix."""
        self.audited = await CoverageAuditor(self.exec, self.modalities).audit(self.namespace)
        hbco = await self._hbco_terms()
        config = self.modality_config
        if config is None:
            config = load_modality_raw(self.building_id)
        for spec in self.modalities:
            if str((spec.sat or {}).get("scope", "room")).lower() != "room":
                continue  # the audit's room matrix excludes them; so does the catalogue
            statuses = [s.modalities.get(spec.name, {}).get("status") for s in self.audited]
            present = sum(1 for s in statuses if s == STATUS_PRESENT)
            located = sum(1 for s in statuses if s in (STATUS_PRESENT, STATUS_UNBACKED))
            unit = (spec.sat or {}).get("unit") or None
            value_type = "boolean" if unit == "binary" else "number"
            words: Set[str] = {spec.name.replace("_", " ")}
            words |= {
                str(t).strip().lower()
                for t in ((config.get(spec.name) or {}).get("lay_terms") or [])
                if str(t).strip()
            }
            words |= {
                phrase.strip().lower()
                for phrase in _LAY_HINTS.get(spec.name, "").split(",")
                if phrase.strip()
            }
            for cls in spec.brick_classes:
                words |= hbco.get(cls.lower(), set())
            self.facets.append(
                Facet(
                    key=f"sensor:{spec.name}",
                    entity_type="space",
                    source_kind="sensor",
                    label=spec.name.replace("_", " "),
                    value_type=value_type,
                    unit=None if unit == "binary" else unit,
                    lay_terms=tuple(sorted(words)),
                    modality=spec.name,
                    join_predicate=_BRICK_HAS_LOCATION,
                    status=ladder_status(located > 0, present > 0, True, present),
                    coverage=present,
                    notes=(
                        "readings live in the time-series store; the graph says which spaces "
                        "have a sensor with a timeseries reference",
                    ),
                )
            )

    async def _hbco_terms(self) -> Dict[str, Set[str]]:
        """{brick class local name, lowercased: lay terms HBCO concepts map to it}."""
        out: Dict[str, Set[str]] = defaultdict(set)
        try:
            rows = await self._select(_HBCO_QUERY)
        except Exception as exc:  # the vocabulary is optional; the facets are not
            logger.info(f"[facets] HBCO lay terms unavailable: {describe_exception(exc)}")
            return out
        for row in rows:
            term = row.get("term", "").strip().lower()
            if term:
                out[_local(row.get("cls", "")).lower()].add(term)
        return out

    # ── records ──────────────────────────────────────────────────────────────────────

    async def _read_records(self) -> Optional[Dict[str, Any]]:
        """Held classes, their predicate profile, their links and their declared fields."""
        held = await record_registry.read_record_classes(_as_run_select(self.exec))
        if not held:
            return None
        names = sorted(r.local_name for r in held)
        parents_query = _PARENTS_QUERY % {
            "values": " ".join(f"o:{n}" for n in names),
            "listed": ", ".join(f"o:{n}" for n in names),
        }
        parents = {_local(row.get("sup", "")) for row in await self._select(parents_query)}
        leaves = [r for r in held if r.local_name not in parents]
        leaf_values = " ".join(f"o:{r.local_name}" for r in leaves)
        budget = record_registry.PROFILE_SAMPLE_BUDGET
        profile: Dict[Tuple[str, str], _Profile] = {}
        query = record_registry.predicate_profile_query(
            [r.local_name for r in leaves], self.namespace, detailed=True
        )
        for row in await self._select(query + "LIMIT 20000"):
            profile[(_local(row.get("cls", "")), row.get("p", ""))] = _Profile.from_row(row, budget)
        scope = f'\n  FILTER(STRSTARTS(STR(?i), "{_escape(self.namespace)}"))'
        links: Dict[Tuple[str, str, str], Tuple[int, int]] = {}
        pairs = " ".join(
            f"(o:{r.local_name} <{link}>)" for r in leaves for link in sorted(LINK_PREDICATE_IRIS)
        )
        link_query = _LINK_QUERY % {"pairs": pairs, "scope": scope}
        for row in await self._select(link_query):
            key = (_local(row.get("cls", "")), row.get("link", ""), row.get("p", ""))
            links[key] = (_int(row.get("inst")), _int(row.get("ents")))
        declared: Dict[str, Set[str]] = defaultdict(set)
        for row in await self._select(_DOMAIN_QUERY % {"values": leaf_values}):
            declared[_local(row.get("cls", ""))].add(row.get("p", ""))
        mapped, locations = self._mapped_columns({r.local_name for r in leaves})
        for name, columns in mapped.items():
            declared[name] |= set(columns)
        return {
            "classes": leaves,
            "profile": profile,
            "links": links,
            "declared": declared,
            "mapped": mapped,
            "locations": locations,
        }

    def _mapped_columns(
        self, class_names: Set[str]
    ) -> Tuple[Dict[str, Dict[str, Tuple[str, ColumnSpec]]], Set[str]]:
        """{class: {predicate: (column, spec)}} from the mappings, and the location-text predicates.

        A column a mapping declares with ``link:`` holds a place in WORDS, beside the link the
        lifter writes for it. Its predicate restates a location, so it is no facet of anything:
        the link is the join, and the place's own facets are what a question asks about.
        """
        mapped: Dict[str, Dict[str, Tuple[str, ColumnSpec]]] = defaultdict(dict)
        locations: Set[str] = set()
        for path in sorted(self.mappings_dir.glob("*.yaml")):
            mapping = load_mapping(path.stem, self.mappings_dir)
            if mapping is None:
                continue
            for column, spec in mapping.columns.items():
                if spec.link:
                    locations.add(expand_predicate(spec.predicate))
            cls = mapping.class_iri
            if not cls.startswith(_ONTOSAGE) or cls[len(_ONTOSAGE) :] not in class_names:
                continue
            for column, spec in mapping.columns.items():
                if spec.predicate:
                    mapped[cls[len(_ONTOSAGE) :]].setdefault(
                        expand_predicate(spec.predicate), (column, spec)
                    )
        return mapped, locations

    async def _read_labels(self, predicates: Set[str]) -> None:
        wanted = sorted(p for p in predicates if p.startswith("http"))
        if not wanted:
            return
        for row in await self._select(_LABEL_QUERY % {"values": _iri_values(wanted)}):
            predicate = row.get("p", "")
            if row.get("label"):
                self.labels[predicate] = row["label"].strip()
            if row.get("range"):
                self.ranges[predicate] = row["range"]

    def _label(self, predicate: str) -> str:
        return (self.labels.get(predicate) or split_camel(_local(predicate))).strip().lower()

    async def _record_facets(self, records: Dict[str, Any]) -> None:
        profile: Dict[Tuple[str, str], _Profile] = records["profile"]
        links: Dict[Tuple[str, str, str], Tuple[int, int]] = records["links"]
        mapped = records["mapped"]
        excluded = set(LINK_PREDICATE_IRIS) | records["locations"] | {_RDF_TYPE}
        for record in records["classes"]:
            name = record.local_name
            own = {p: prof for (c, p), prof in profile.items() if c == name}
            instances = own.get(_RDF_TYPE, _Profile()).carriers
            joins = [
                (link, entity)
                for link, entity in _LINK_ENTITY
                if links.get((name, link, _RDF_TYPE), (0, 0))[0] > 0
            ]
            entity, join = (joins[0][1], joins[0][0]) if joins else ("building", None)
            stamps = provenance_fields(
                [
                    {_local(p): prof.sample[i] for p, prof in own.items() if len(prof.sample) > i}
                    for i in range(2)
                ]
            )
            candidates = {p for p, prof in own.items() if prof.literals > 0}
            candidates |= set(mapped.get(name, {})) | records["declared"].get(name, set())
            for predicate in sorted(candidates):
                local = _local(predicate)
                if predicate in excluded or local in stamps or _is_identity(local):
                    continue
                self._add_record_facet(
                    record,
                    predicate,
                    own.get(predicate, _Profile()),
                    instances,
                    entity,
                    join,
                    joins,
                    links,
                    mapped.get(name, {}).get(predicate),
                )
            if entity == "route" and join == LINK_PREDICATES[ROUTE_TO]:
                self._route_facets(record, own, links, candidates - excluded, stamps, mapped)
        self._event_facets(records)

    def _add_record_facet(
        self,
        record: record_registry.RecordClass,
        predicate: str,
        prof: _Profile,
        instances: int,
        entity: str,
        join: Optional[str],
        joins: List[Tuple[str, str]],
        links: Dict[Tuple[str, str, str], Tuple[int, int]],
        column: Optional[Tuple[str, ColumnSpec]],
    ) -> None:
        name = record.local_name
        spec = column[1] if column else None
        declared_type = spec.datatype if spec else self.ranges.get(predicate)
        value_type, typed, notes = _value_type(
            prof.datatypes,
            declared_type,
            bool(spec and spec.values),
            prof.distinct,
            prof.values,
            prof.sample,
        )

        def coverage_via(link: Optional[str], kind: str) -> int:
            if link is None:
                return 1 if prof.carriers > 0 else 0
            inst, ents = links.get((name, link, predicate), (0, 0))
            return inst if kind == "route" else ents

        linked = instances > 0 if join is None else True
        coverage = coverage_via(join, entity)
        words = {split_camel(_local(predicate))}
        if column:
            words.add(column[0].replace("_", " ").lower())
        words.discard(self._label(predicate))
        self.facets.append(
            Facet(
                key=f"record:{name}.{_local(predicate)}",
                entity_type=entity,
                source_kind="record",
                label=self._label(predicate),
                value_type=value_type,
                unit=_unit_from_name(_local(predicate), value_type),
                lay_terms=tuple(sorted(w for w in words if w)),
                record_class=name,
                predicate=predicate,
                join_predicate=join,
                examples=_examples(prof.sample, value_type),
                status=ladder_status(linked, prof.carriers > 0, typed, coverage),
                coverage=coverage,
                class_terms=tuple(record.terms),
                other_joins=tuple(
                    (kind, link, coverage_via(link, kind)) for link, kind in joins if link != join
                ),
                notes=tuple(notes),
            )
        )

    def _route_facets(
        self,
        record: record_registry.RecordClass,
        own: Dict[str, _Profile],
        links: Dict[Tuple[str, str, str], Tuple[int, int]],
        candidates: Set[str],
        stamps: FrozenSet[str],
        mapped: Mapping[str, Mapping[str, Tuple[str, ColumnSpec]]],
    ) -> None:
        """A route record's numeric and yes/no facts, as facts about the space it reaches.

        "A room step-free from reception, within five minutes" filters SPACES by a route's
        facts. The route record names its destination with routeToSpace; that link is the join,
        and the starting point (routeFromSpace) is the parameter the executor fixes.
        """
        name = record.local_name
        to_link, from_link = LINK_PREDICATES[ROUTE_TO], LINK_PREDICATES[ROUTE_FROM]
        origins = links.get((name, from_link, _RDF_TYPE), (0, 0))
        for predicate in sorted(candidates):
            local = _local(predicate)
            if local in stamps or _is_identity(local):
                continue
            prof = own.get(predicate, _Profile())
            column = mapped.get(name, {}).get(predicate)
            spec = column[1] if column else None
            value_type, typed, notes = _value_type(
                prof.datatypes,
                spec.datatype if spec else self.ranges.get(predicate),
                bool(spec and spec.values),
                prof.distinct,
                prof.values,
                prof.sample,
            )
            if value_type not in ("number", "integer", "boolean"):
                continue
            coverage = links.get((name, to_link, predicate), (0, 0))[1]
            self.facets.append(
                Facet(
                    key=f"spatial:{name}.{local}",
                    entity_type="space",
                    source_kind="spatial",
                    label=f"{self._label(predicate)} (route to the space)",
                    value_type=value_type,
                    unit=_unit_from_name(local, value_type),
                    lay_terms=tuple(sorted({split_camel(local), "route", "journey"})),
                    record_class=name,
                    predicate=predicate,
                    join_predicate=to_link,
                    examples=_examples(prof.sample, value_type),
                    status=ladder_status(True, prof.carriers > 0, typed, coverage),
                    coverage=coverage,
                    class_terms=tuple(record.terms),
                    notes=tuple(notes)
                    + (
                        f"the route's start is its routeFromSpace link, which {origins[0]} route "
                        f"record(s) carry, reaching {origins[1]} space(s)",
                    ),
                )
            )

    def _event_facets(self, records: Dict[str, Any]) -> None:
        """The executor's availability checks, backed by booking records and the events store."""
        names = [r.local_name for r in records["classes"]]
        booking = sorted(record_registry.event_store_record_classes(names, [_BOOKING_EVENT_KIND]))
        store = self.events_store
        if store is None:
            try:
                store = record_registry.events_store_registered()
            except Exception as exc:  # pragma: no cover - an unreadable registry is "no store"
                logger.info(f"[facets] events store unknown: {describe_exception(exc)}")
                store = False
        if not booking and not store:
            return
        located = LINK_PREDICATES[LOCATED_IN]
        links = records["links"]
        profile = records["profile"]
        linked = sum(links.get((b, located, _RDF_TYPE), (0, 0))[0] for b in booking)
        started = sum(profile.get((b, _PERIOD_START), _Profile()).carriers for b in booking)
        # Distinct spaces cannot be summed across classes; with more than one booking class the
        # largest is a lower bound, and the note says so.
        coverage = max(
            (links.get((b, located, _PERIOD_START), (0, 0))[1] for b in booking), default=0
        )
        notes = [
            (
                "registered events store: the executor reads its booking rows when the plan runs; "
                "the graph cannot show whether it holds any"
                if store
                else "no events store is registered: availability rests on the booking records "
                "in the graph"
            )
        ]
        if len(booking) > 1:
            notes.append("coverage is the largest single booking class's, a lower bound")
        class_terms = tuple(
            sorted({t for r in records["classes"] if r.local_name in booking for t in r.terms})
        )
        for kind, label, value_type, unit, words in _EVENT_FACETS:
            self.facets.append(
                Facet(
                    key=f"event:{kind}",
                    entity_type="space",
                    source_kind="event",
                    label=label,
                    value_type=value_type,
                    unit=unit,
                    lay_terms=words,
                    record_class=booking[0] if booking else None,
                    join_predicate=located if booking else None,
                    status=ladder_status(bool(store or linked), started > 0, True, coverage),
                    coverage=coverage,
                    class_terms=class_terms,
                    resolver="plan_executor._event_availability" if store else None,
                    notes=tuple(notes),
                )
            )

    async def _event_source_facets(self, records: Dict[str, Any]) -> None:
        """The record classes whose records are placed in a space AND on the clock (C5).

        Discovered from the graph by ``event_sources``: one read of every held class's placed
        records and their time values, the qualification decided in code from the data and the
        TBox's interval vocabulary. A class that does not qualify (no time on the clock, or placed
        only on floors, equipment or the building) gets no facet -- the compiler then has nothing to
        relate a series to, and says what the building does record with a time and a place.
        """
        classes = list(records["classes"])
        if not classes or not self.space_iris:
            return
        rows = await self._select(
            event_sources.discovery_query([r.local_name for r in classes], self.namespace)
        )
        if len(rows) >= event_sources.MAX_DISCOVERY_ROWS:
            raise RuntimeError(
                f"the event-source read reached its {event_sources.MAX_DISCOVERY_ROWS}-row limit; "
                "a cut read cannot say which registers are events"
            )
        profiles = event_sources.profiles_from_rows(rows, self.space_iris)
        by_name = {r.local_name: r for r in classes}
        for name in sorted(profiles):
            profile = profiles[name]
            roles = event_sources.time_roles(profile)
            if not roles:
                continue
            record = by_name.get(name)
            label = ((record.label if record else "") or split_camel(name)).strip().lower()
            words = {
                str(t).strip().lower() for t in (record.terms if record else ()) if str(t).strip()
            }
            words.discard(label)
            kinds = dict(roles)
            start = profile.predicates.get(
                kinds.get(event_sources.ROLE_START) or kinds.get(event_sources.ROLE_DAY) or ""
            )
            timed = start.records if start is not None else 0
            first, last = event_sources.span_of(profile, roles)
            self.facets.append(
                Facet(
                    key=f"event:{name}",
                    entity_type="space",
                    source_kind="event",
                    label=label,
                    value_type=INTERVAL,
                    lay_terms=tuple(sorted(words)),
                    record_class=name,
                    join_predicate=event_sources.PLACE_LINKS[0],
                    examples=(first, last) if first else (),
                    status=ladder_status(True, timed > 0, True, profile.spaces),
                    coverage=profile.spaces,
                    resolver="event_sources.events_query",
                    roles=roles,
                    notes=(
                        event_sources.time_note(roles),
                        f"{profile.records} record(s) placed in {profile.spaces} space(s), "
                        f"{timed} of them on the clock",
                    ),
                )
            )

    # ── TTL properties of spaces ─────────────────────────────────────────────────────

    async def _read_space_profile(self) -> Dict[str, _Profile]:
        budget = record_registry.PROFILE_SAMPLE_BUDGET
        rows = await self._select(
            _SPACE_PROFILE_QUERY % {"ns": _escape(self.namespace), "budget": budget}
        )
        return {row.get("p", ""): _Profile.from_row(row, budget) for row in rows if row.get("p")}

    async def _ttl_facets(self, space_profile: Dict[str, _Profile]) -> None:
        """Literal predicates on spaces -- except capacity, which has its own authority order."""
        taken: Set[str] = set()
        for predicate in sorted(space_profile):
            local = _local(predicate)
            if _is_identity(local) or design_occupancy.is_design_occupancy_predicate(predicate):
                continue
            if predicate in LINK_PREDICATE_IRIS:
                continue
            prof = space_profile[predicate]
            value_type, typed, notes = _value_type(
                prof.datatypes,
                self.ranges.get(predicate),
                False,
                prof.distinct,
                prof.values,
                prof.sample,
            )
            key = f"ttl:{local}"
            if key in taken:  # two vocabularies naming a property alike: keep both apart
                key = f"ttl:{local}~{len([k for k in taken if k.startswith(key)])}"
            taken.add(key)
            self.facets.append(
                Facet(
                    key=key,
                    entity_type="space",
                    source_kind="ttl",
                    label=self._label(predicate),
                    value_type=value_type,
                    unit=_unit_from_name(local, value_type),
                    lay_terms=tuple(sorted({split_camel(local)} - {self._label(predicate)})),
                    predicate=predicate,
                    examples=_examples(prof.sample, value_type),
                    status=ladder_status(True, prof.carriers > 0, typed, prof.carriers),
                    coverage=prof.carriers,
                    notes=tuple(notes),
                )
            )

    async def _read_capacity(self) -> Dict[str, Any]:
        """Design occupancy per space, through design_occupancy, and the predicates declaring it."""
        declared = {
            row.get("p", "")
            for row in await self._select(
                _CAPACITY_TBOX_QUERY % {"terms": design_occupancy._terms_for_sparql()}
            )
        }
        occupancy = await design_occupancy.declared_design_occupancy(self.exec)
        used = {
            key
            for entry in occupancy.values()
            for key in entry.declarations
            if design_occupancy.is_design_occupancy_predicate(key)
        }
        return {"predicates": sorted((declared | used) - {""}), "occupancy": occupancy}

    async def _capacity_facet(self, capacity: Dict[str, Any]) -> None:
        """ONE capacity facet per building, read through design_occupancy's authority order.

        The building may state capacity under several properties, on the space or on a retained
        record, and from the model or a drawing; ``design_occupancy`` already settles which one
        answers (the TTL figure, else the drawing, else none -- never an average). Reading the
        raw properties here as well would put a second, unsettled figure beside the settled one.
        """
        predicates: List[str] = capacity["predicates"]
        occupancy = capacity["occupancy"]
        if not predicates and not occupancy:
            return
        in_spaces = {iri: e for iri, e in occupancy.items() if iri in self.space_iris}
        settled = [e.value for e in in_spaces.values() if e.value is not None]
        conflicted = sum(1 for e in in_spaces.values() if e.conflicted)
        drawn = sum(
            1
            for e in in_spaces.values()
            if e.value is not None and e.source == design_occupancy.CAPACITY_SOURCE_DRAWING
        )
        words = set(_CAPACITY_WORDS)
        for predicate in predicates:
            words |= {self._label(predicate), split_camel(_local(predicate))}
        notes = [f"reads {', '.join(_local(p) for p in predicates)} through the authority order"]
        if conflicted:
            notes.append(f"{conflicted} space(s) state disagreeing figures: reported, never picked")
        if drawn:
            notes.append(f"{drawn} figure(s) come from the drawing, the second source")
        self.facets.append(
            Facet(
                key="ttl:capacity",
                entity_type="space",
                source_kind="ttl",
                label="room capacity (design occupancy)",
                value_type="integer",
                unit="persons",
                lay_terms=tuple(sorted(w for w in words if w)),
                predicate=predicates[0] if len(predicates) == 1 else None,
                examples=_examples([str(v) for v in settled], "integer"),
                status=ladder_status(bool(in_spaces), bool(in_spaces), True, len(settled)),
                coverage=len(settled),
                resolver=(
                    "design_occupancy.authoritative_capacity: the TTL figure, else the drawing, "
                    "else none; a disagreement is reported, never averaged"
                ),
                notes=tuple(notes),
            )
        )

    # ── floors ───────────────────────────────────────────────────────────────────────

    async def _floor_facet(self) -> None:
        """Which floor a space is on, from the spaces the coverage audit reads."""
        if not self.floor_labels and not any(s.floor for s in self.audited):
            return
        by_local = {_local(iri): label for iri, label in self.floor_labels.items()}
        on_floor = [s for s in self.audited if s.floor]
        floors = sorted({by_local.get(s.floor, s.floor) for s in on_floor}, key=_sort_key)
        self.facets.append(
            Facet(
                key="spatial:floor",
                entity_type="space",
                source_kind="spatial",
                label="floor the space is on",
                value_type="enum",
                lay_terms=tuple(sorted({w for w in _FLOOR_WORDS if len(w) > 2})),
                join_predicate=_BRICK_IS_PART_OF,
                examples=tuple(_excerpt(f) for f in floors[:ENUM_MAX_VALUES]),
                status=ladder_status(bool(on_floor), bool(on_floor), True, len(on_floor)),
                coverage=len(on_floor),
            )
        )

    # ── kinds of space ───────────────────────────────────────────────────────────────

    async def _space_kind_facet(self) -> None:
        """What KIND of space each is: its label's descriptor and its Brick room classes.

        Every space carries this, so a filter on it never leaves a space "not verified" the way
        the register-held kinds did (space_kinds.py has the measurement). Every kind the building
        uses is in the retrieval vocabulary -- a question names "seminar rooms" whatever their
        count -- while the examples shown to the compiler are the commonest, as for any enum.
        """
        from orchestrator.services.deliberation.space_kinds import SPACE_KIND_FACET, space_kinds

        counts: Dict[str, int] = defaultdict(int)
        typed = 0
        for space in self.audited:
            kinds = space_kinds(space.label, space.kinds)
            if kinds:
                typed += 1
            for kind in kinds:
                counts[kind] += 1
        if not typed:
            return
        ranked = sorted(counts, key=lambda k: (-counts[k], k))
        self.facets.append(
            Facet(
                key=SPACE_KIND_FACET,
                entity_type="space",
                source_kind="spatial",
                label="kind of space (its own label and room type)",
                value_type="enum",
                lay_terms=tuple(
                    sorted({"kind of room", "type of room", "room type", "kind of space", *ranked})
                ),
                examples=tuple(_excerpt(k) for k in ranked[:ENUM_MAX_VALUES]),
                status=ladder_status(True, True, True, typed),
                coverage=typed,
                resolver=(
                    "space_kinds.kind_matches over each space's label descriptor and Brick room "
                    "classes; every word of the requested kind must be a word of one of them"
                ),
            )
        )


__all__ = [
    "ENTITY_TYPES",
    "Facet",
    "FacetCatalogue",
    "LADDER",
    "SOURCE_KINDS",
    "TARGET_NOUNS",
    "TermMatch",
    "VALUE_TYPES",
    "build_facet_catalogue",
    "cached_catalogue",
    "clear_cache",
    "content_words",
    "facet_vocabulary",
    "ladder_status",
    "plain_words",
    "split_camel",
]
