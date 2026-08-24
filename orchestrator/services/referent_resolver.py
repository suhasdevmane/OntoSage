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
from typing import Awaitable, Callable, List, Optional

from shared.utils import get_logger

logger = get_logger(__name__)

# An injected async callable: SPARQL string -> standard SPARQL-results JSON dict.
SparqlExec = Callable[[str], Awaitable[dict]]

# A dotted numeric location id (e.g. 5.28, 3.01, 99.99). Common Brick zone/room id shape.
_DOTTED_ID_RE = re.compile(r"\d{1,2}\.\d{1,2}")
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
_SPACE_RE = re.compile(
    r"\b(?:the\s+)?([a-z][a-z-]{2,19})\s+(" + "|".join(_SPACE_HEADS) + r")\b", re.IGNORECASE
)
# The same heads standing alone behind a determiner: "in the gym", "on the rooftop".
# Without this a bare space noun was invisible to the gate, so "how many sensors are
# on the helipad?" was answered with the whole building's figures. A determiner is
# required so an incidental mention ("pool of data") cannot trip it, and the heads
# are generic English building words — no building's own vocabulary appears here.
_BARE_SPACE_RE = re.compile(r"\b(?:the|a|an)\s+(" + "|".join(_SPACE_HEADS) + r")\b", re.IGNORECASE)
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
        if m and _SAFE_TOKEN_RE.match(m.group(1)):
            return m.group(1)

    # 2) Raw query — require an explicit location word before the id so we never trip on a
    #    threshold/value (e.g. "above 26.5 degrees" has no location word → ignored).
    m = _WORDED_REF_RE.search(query or "")
    if m and _SAFE_TOKEN_RE.match(m.group(1)):
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
    m = _OTHER_BUILDING_RE.search(q)
    if m:
        head, ident = m.group(1).lower(), m.group(2)
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

    m = _MEASURAND_RE.search(q)
    if m:
        quantity = m.group(1).lower()
        if quantity not in _STOP_QUANTITIES and _SAFE_TOKEN_RE.match(quantity):
            return TypedReferent(
                kind=KIND_MEASURAND, token=quantity, phrase=quantity, head=quantity
            )

    return None


# Words that precede "level/concentration" without naming a measured quantity.
_STOP_QUANTITIES = frozenset(
    {"the", "a", "an", "this", "that", "high", "low", "current", "same", "acceptable", "normal"}
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
    ) -> ReferentResolution:
        """Resolve the query's spatial referent (if any) against ``namespace``.

        Never raises: on any SPARQL error returns ``SKIPPED`` so the caller proceeds
        exactly as it did before this gate existed (fail open).
        """
        token = detect_referent(query, entities)
        if not token:
            # No dotted/worded location — try the typed referents (BUG-103): a floor,
            # a named space, a piece of equipment, or a measured quantity.
            typed = detect_typed_referent(query)
            if typed:
                return await self._resolve_typed(typed, namespace, building_name)
            return ReferentResolution(status=NO_REFERENT)

        try:
            exists = await self._exists(token, namespace)
        except Exception as e:  # GraphDB down / timeout / malformed — fail OPEN.
            logger.warning(f"[referent_resolver] existence check failed, proceeding: {e}")
            return ReferentResolution(status=SKIPPED, referent=token)

        if exists:
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
        self, typed: TypedReferent, namespace: str, building_name: str
    ) -> ReferentResolution:
        """Validate a floor / space / equipment / measurand against the live graph."""
        if typed.head in self._BUILDING_FAMILY:
            return self._resolve_other_building(typed, namespace, building_name)
        terms = typed.token.split("|")
        try:
            exists = await self._exists_terms(terms, namespace)
            # A compound referent ("west wing", "chiller 7") may fail only on the
            # modifier. If even the HEAD noun is unknown to this building, the answer
            # is a confident "we have nothing like that"; otherwise we can suggest the
            # real ones of that kind.
            head_exists = exists or await self._exists_terms([typed.head], namespace)
        except Exception as e:  # fail OPEN — never block on a degraded GraphDB
            logger.warning(f"[referent_resolver] typed existence check failed, proceeding: {e}")
            return ReferentResolution(status=SKIPPED, referent=typed.phrase)

        if exists:
            return ReferentResolution(status=RESOLVED, referent=typed.phrase)

        suggestions: List[str] = []
        if head_exists:
            try:
                suggestions = await self._suggest_terms([typed.head], namespace)
            except Exception as e:
                logger.warning(f"[referent_resolver] typed suggestion lookup failed: {e}")

        return ReferentResolution(
            status=NOT_FOUND,
            referent=typed.phrase,
            suggestions=suggestions,
            message=self._typed_clarification(typed, suggestions, building_name),
        )

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
        cleaned = [t.lower().strip() for t in terms if t and t.strip()]
        if not cleaned:
            return True

        def _field_holds_all(field: str) -> str:
            return "(" + " && ".join(f'CONTAINS({field}, "{t}")' for t in cleaned) + ")"

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

    async def _suggest_terms(self, terms: List[str], namespace: str) -> List[str]:
        """Up to 5 real entity names of the same kind (e.g. the floors that DO exist)."""
        t = (terms[0] if terms else "").lower()
        if not t:
            return []
        q = (
            "PREFIX rdfs: <http://www.w3.org/2000/01/rdf-schema#>\n"
            "SELECT DISTINCT ?s WHERE {\n"
            "  ?s a ?cls .\n"  # anchor on typed entities — fast, same reason as _exists_terms
            "  OPTIONAL { ?s rdfs:label ?l }\n"
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
        typed: TypedReferent, suggestions: List[str], building_name: str
    ) -> str:
        """Honest refusal + how to make the question answerable (connect-data contract)."""
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

        return head + enablement_hint(subject_kind, typed.phrase)

    # ------------------------------------------------------------------ helpers

    async def _exists(self, token: str, namespace: str) -> bool:
        """True if any subject in ``namespace`` has ``token`` in its URI or rdfs:label."""
        t = token.lower()
        q = (
            "PREFIX rdfs: <http://www.w3.org/2000/01/rdf-schema#>\n"
            "SELECT ?s WHERE {\n"
            "  ?s ?p ?o .\n"
            f'  FILTER(STRSTARTS(STR(?s), "{namespace}"))\n'
            f'  FILTER( CONTAINS(LCASE(STR(?s)), "{t}")\n'
            f'          || EXISTS {{ ?s rdfs:label ?l . FILTER(CONTAINS(LCASE(STR(?l)), "{t}")) }} )\n'
            "} LIMIT 1"
        )
        data = await self._exec(q)
        return len(_bindings(data)) > 0

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
