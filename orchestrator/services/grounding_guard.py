"""Grounding guard (BUG-103) — refuse to present unrelated content as an answer.

Problem this solves
-------------------
Two independent paths could answer a question about something the building does not
have, using real-but-unrelated content, phrased as if it were the answer:

* **Document path** — a semantic search over uploaded manuals returns its best chunk
  above a cosine floor. That floor was tuned for one embedding model; under another
  (e.g. ``bge-large-en-v1.5``) generic building prose scores high against *any*
  building question, so "what is the pH of the water tank?" surfaced an HVAC CO2
  table under "Here is what I found…". Real text, wrong question.
* **Data path** — see :mod:`referent_resolver`, which gates *named referents*.

The fix here is deliberately **embedding-model-agnostic and building-agnostic**: a
retrieved passage may only be presented if it actually *mentions* what was asked
about. No thresholds to re-tune per model, no building literals, nothing to keep in
sync with a particular corpus.

Second responsibility: when we honestly decline, tell the user **how to make the
question answerable** — the connect-data → get-answers contract. A refusal that ends
the conversation is a dead end; a refusal that names the missing source is onboarding.
"""

from __future__ import annotations

import re
from typing import Iterable, List, Optional, Sequence, Set

from shared.utils import get_logger

logger = get_logger(__name__)

# Words that carry no topical signal — matching on these would let any passage
# "answer" any question. Deliberately generic English + building-domain filler.
_STOPWORDS: Set[str] = {
    "a",
    "about",
    "all",
    "am",
    "an",
    "and",
    "any",
    "anything",
    "are",
    "as",
    "at",
    "available",
    "be",
    "been",
    "being",
    "between",
    "both",
    "building",
    "but",
    "by",
    "can",
    "could",
    "current",
    "currently",
    "data",
    "day",
    "days",
    "did",
    "do",
    "does",
    "doing",
    "done",
    "each",
    "every",
    "explain",
    "find",
    "for",
    "from",
    "get",
    "give",
    "go",
    "had",
    "has",
    "have",
    "having",
    "he",
    "her",
    "here",
    "hers",
    "him",
    "his",
    "how",
    "i",
    "if",
    "in",
    "info",
    "information",
    "into",
    "is",
    "it",
    "its",
    "just",
    "know",
    "last",
    "latest",
    "level",
    "levels",
    "like",
    "list",
    "long",
    "look",
    "many",
    "may",
    "me",
    "measure",
    "measured",
    "might",
    "mine",
    "month",
    "months",
    "more",
    "most",
    "much",
    "must",
    "my",
    "need",
    "no",
    "not",
    "now",
    "number",
    "of",
    "off",
    "on",
    "one",
    "only",
    "or",
    "other",
    "our",
    "out",
    "over",
    "please",
    "reading",
    "readings",
    "recent",
    "report",
    "right",
    "said",
    "same",
    "say",
    "says",
    "see",
    "she",
    "should",
    "show",
    "since",
    "so",
    "some",
    "status",
    "such",
    "system",
    "systems",
    "tell",
    "than",
    "that",
    "the",
    "their",
    "theirs",
    "them",
    "then",
    "there",
    "these",
    "they",
    "this",
    "those",
    "through",
    "time",
    "times",
    "to",
    "today",
    "too",
    "under",
    "up",
    "us",
    "use",
    "used",
    "using",
    "value",
    "values",
    "very",
    "want",
    "was",
    "we",
    "week",
    "weeks",
    "were",
    "what",
    "when",
    "where",
    "which",
    "while",
    "who",
    "why",
    "will",
    "with",
    "would",
    "year",
    "years",
    "yesterday",
    "you",
    "your",
    "yours",
}

_WORD_RE = re.compile(r"[a-z0-9][a-z0-9.\-]*", re.IGNORECASE)


def _singular(word: str) -> str:
    """Crude, dependency-free stemmer — enough to match 'sensors'↔'sensor'.

    Also folds the common verb endings, because a question and the document that
    answers it rarely inflect the same way: "when was it last SERVICED" against a
    log that says "SERVICING activity … SERVICE dates" shared no term at all, so
    the passage was judged off-topic and the answer became "I don't have that
    information" while the document sat there saying it. Endings are stripped only
    while a 4-character stem survives, so short words are left alone rather than
    collapsed into each other.
    """
    if len(word) > 3 and word.endswith("ies"):
        return word[:-3] + "y"
    if len(word) > 3 and word.endswith("ses"):
        return word[:-2]
    if len(word) > 3 and word.endswith("s") and not word.endswith("ss"):
        word = word[:-1]
    if len(word) > 6 and word.endswith("ing"):
        word = word[:-3]
    elif len(word) > 5 and word.endswith("ed"):
        word = word[:-2]
    # "service" / "servic(ed)" / "servic(ing)" only agree once the silent -e goes.
    if len(word) > 4 and word.endswith("e"):
        word = word[:-1]
    return word


def content_terms(text: str, *, min_len: int = 3) -> Set[str]:
    """Topic-bearing terms of ``text``: lowercased, stopword-free, crudely singularised."""
    terms: Set[str] = set()
    for raw in _WORD_RE.findall((text or "").lower()):
        word = raw.strip(".-")
        if len(word) < min_len or word in _STOPWORDS:
            continue
        terms.add(_singular(word))
    return terms


# Vocabulary shared by nearly every building question and every building document.
# Overlap on these proves nothing: "average temperature in the WEST WING" and an HVAC
# table both say "temperature", yet the table cannot answer about a wing that does not
# exist. The distinctive remainder — "west wing" — is what a passage must actually
# mention. Generic English domain words only; no building's own vocabulary.
GENERIC_TERMS: Set[str] = {
    "air",
    "area",
    "average",
    "building",
    "concentration",
    "consumption",
    "current",
    "electricity",
    "energy",
    "equipment",
    "floor",
    "humidity",
    "light",
    "lighting",
    "maximum",
    "meter",
    "minimum",
    "occupancy",
    "power",
    "quality",
    "range",
    "rate",
    "reading",
    "room",
    "sensor",
    "space",
    "speed",
    "temperature",
    "total",
    "unit",
    "usage",
    "water",
    "zone",
}


def distinctive_terms(text: str) -> Set[str]:
    """Topic terms minus the vocabulary every building question shares."""
    return content_terms(text) - GENERIC_TERMS


def is_on_topic(query: str, passage: str, *, extra_vocab: Optional[Iterable[str]] = None) -> bool:
    """True if ``passage`` actually mentions something the ``query`` asked about.

    A passage retrieved by pure vector similarity may be topically unrelated — this is
    the lexical cross-check. ``extra_vocab`` lets a caller add known synonyms (e.g. the
    concept resolver's lay-term → Brick-class expansion), so legitimate paraphrases
    ("stuffy" → CO2) are not rejected.

    Fails OPEN: a query with no topical terms at all (e.g. "tell me more") returns
    True, leaving prior behaviour unchanged rather than blocking a valid follow-up.
    """
    q_terms = content_terms(query)
    if not q_terms:
        return True
    synonyms = {_singular(str(v).lower()) for v in (extra_vocab or []) if v}
    q_terms |= synonyms
    p_terms = content_terms(passage)
    if not p_terms:
        return False

    # When the question names something specific, the passage must mention THAT —
    # sharing only generic vocabulary ("temperature", "floor") is not an answer.
    q_distinctive = (q_terms - GENERIC_TERMS) | (synonyms - GENERIC_TERMS)
    if q_distinctive:
        return bool(q_distinctive & p_terms)
    # Wholly generic question ("what is the temperature?") — any overlap will do.
    return bool(q_terms & p_terms)


#: How well a retrieved passage matches the question. Three values, because the useful
#: distinction is not on/off: a passage sharing a word the whole corpus uses is genuinely
#: weaker evidence than one sharing a word that appears nowhere else, and pretending those are
#: the same is what BUG-218 was.
MATCH_DISTINCTIVE = "distinctive"  # shares a term that narrows this corpus
MATCH_COMMON = "common"  # shares only vocabulary most documents use
MATCH_NONE = "none"  # shares nothing


def match_strength(
    query: str,
    passage: str,
    *,
    extra_vocab: Optional[Iterable[str]] = None,
    corpus_df: Optional[dict] = None,
    n_docs: int = 0,
) -> str:
    """How strongly this passage matches, given what is common in this building's corpus.

    Used to decide how an answer is FRAMED, not whether it is shown. That is the deliberate
    choice: measured over the golden baseline, using this signal to suppress would drop about
    one legitimate answer for every off-topic one it removed, whereas using it to hedge costs
    nothing in recall and removes the thing that actually misleads -- a passage presented under
    a heading that asserts it answers the question.

    With no corpus table (a building with fewer than a few documents, or none loaded) every
    shared term counts as distinctive and this reduces to :func:`is_on_topic`.
    """
    if not is_on_topic(query, passage, extra_vocab=extra_vocab):
        return MATCH_NONE

    q_terms = content_terms(query)
    synonyms = {_singular(str(v).lower()) for v in (extra_vocab or []) if v}
    q_terms |= synonyms
    overlap = (q_terms - GENERIC_TERMS) & content_terms(passage)
    if not overlap:
        # Cleared is_on_topic on wholly generic vocabulary ("what is the temperature?").
        return MATCH_COMMON

    if not corpus_df or n_docs <= 0:
        return MATCH_DISTINCTIVE

    from orchestrator.services.corpus_stats import distinctive_terms

    return MATCH_DISTINCTIVE if distinctive_terms(overlap, corpus_df, n_docs) else MATCH_COMMON


def filter_on_topic(
    query: str,
    hits: Sequence[dict],
    *,
    text_key: str = "text",
    name_key: str = "doc_name",
    extra_vocab: Optional[Iterable[str]] = None,
) -> List[dict]:
    """Keep retrieved hits that are on-topic by passage text **or** document name.

    The document's NAME is itself a topical label, and a correct answer does not always
    repeat the question's vocabulary — "what is the fire evacuation procedure?" is
    rightly answered by "assemble at the north car park" from ``fire_safety.md``. Judging
    on text alone would reject that, so a name match is sufficient on its own. What no
    longer survives is the actual defect: a passage AND a document that both have nothing
    to do with what was asked.
    """
    kept = []
    for h in hits:
        text_ok = is_on_topic(query, str(h.get(text_key, "")), extra_vocab=extra_vocab)
        name_ok = is_on_topic(
            query, str(h.get(name_key, "")).replace("_", " "), extra_vocab=extra_vocab
        )
        if text_ok or name_ok:
            kept.append(h)
    if hits and not kept:
        logger.info(
            f"[grounding_guard] dropped {len(hits)} off-topic passage(s) — neither the text "
            "nor the document name mentioned what was asked about"
        )
    return kept


# ── Enablement guidance ──────────────────────────────────────────────────────────
# A refusal should teach the user how to make the question answerable. Wording is
# building-agnostic: it names the mechanism (TTL + registered time-series, amenity
# triple, uploaded document), never a specific building, path, or sensor.

# ─────────────────────────────────────────────────────────────────────────────
# Building scope (BUG-123)
# ─────────────────────────────────────────────────────────────────────────────
# A question about *this* building must be answered from this building's data. If
# it reaches the open-domain answerer instead, that answerer has no data and no
# way to know it lacks any — so it supplies plausible specifics. Observed live:
# "Is it stuffy in RM157?" was answered "humidity around 45% and CO2 near 800 ppm"
# for a room with neither sensor.
#
# Detection keys on question SHAPE plus the resolved lay-term concept, never on a
# building's own vocabulary — the same test must hold for every building.

# Locators for a place inside a building. Shape only: a word for a kind of space
# followed by an identifier, which is how every building refers to its own.
_PLACE_RE = re.compile(
    r"\b(?:room|rm|zone|floor|storey|level|space|area|wing|lab|office|suite|unit)"
    r"[_\s\-]?[a-z]?\d+[a-z]?(?:\.\d+)?\b",
    re.IGNORECASE,
)

# "…in this building", "…in here" — the user pointing at where they are.
_DEIXIS_RE = re.compile(
    r"\b(?:in|at|inside|around|throughout)\s+(?:this|the|our|my)\s+"
    r"(?:building|office|room|floor|space|site|premises|facility)\b"
    r"|\bin\s+here\b|\bright\s+here\b|\bthis\s+building\b",
    re.IGNORECASE,
)

# "is it …", "how is it …", "does it feel …" — a question about the present state
# of the space the user occupies. Carries an implicit "here".
_PRESENT_STATE_RE = re.compile(
    r"\b(?:is|are|does|do|how)\s+(?:it|the\s+air|things|we|the\s+temperature|"
    r"the\s+humidity)\b|\bfeel(?:s|ing)?\b|\btoo\s+(?:warm|hot|cold|humid|dry|stuffy|noisy)\b",
    re.IGNORECASE,
)


def has_measurand_concept(concepts: Optional[Sequence]) -> bool:
    """True when a resolved lay-term concept maps to a measurable building point.

    ``concepts`` are HBCO matches (dicts or objects exposing ``brick_classes``).
    A concept that maps to a Brick sensor class means the user named something
    this building measures — "stuffy" is a CO2 question, not a vocabulary one.
    """
    for c in concepts or []:
        classes = (
            c.get("brick_classes", []) if isinstance(c, dict) else getattr(c, "brick_classes", [])
        )
        for bc in classes or []:
            s = str(bc)
            if s.endswith("_Sensor") or s.endswith("_Setpoint") or "Sensor" in s:
                return True
    return False


def is_building_specific(query: str, concepts: Optional[Sequence] = None) -> bool:
    """True when the question asks about THIS building rather than the world.

    Requires BOTH a measurable subject and a reference to this building, so a
    definitional question keeps going to the open-domain answerer: "what is
    stuffiness?" names a measurand but no place and stays general, while "is it
    stuffy in RM157?" names both and belongs to the data path.
    """
    q = query or ""
    if not q.strip():
        return False
    if not has_measurand_concept(concepts):
        return False
    return bool(_PLACE_RE.search(q) or _DEIXIS_RE.search(q) or _PRESENT_STATE_RE.search(q))


# ─────────────────────────────────────────────────────────────────────────────
# Does the passage contain the KIND of fact that was asked for? (CAVEAT-108)
# ─────────────────────────────────────────────────────────────────────────────
# is_on_topic proves a passage is ABOUT the subject. It cannot prove the passage
# ANSWERS the question. "When was chiller 7 last serviced?" returns HVAC prose that
# genuinely discusses chillers and contains no date at all — presented plainly, that
# reads as the answer. Naming what is missing turns a misleading reply into an honest
# partial one, and tells the user what to go and add.

_ASKS_DATE_RE = re.compile(
    r"\b(?:when|what date|which date|how long ago|how old)\b"
    r"|\blast\s+(?:serviced|inspected|maintained|repaired|replaced|checked|cleaned)\b",
    re.IGNORECASE,
)
_ASKS_QUANTITY_RE = re.compile(
    r"\bhow (?:many|much)\b|\bwhat (?:is|was) the (?:number|count|total|average|level|reading)\b",
    re.IGNORECASE,
)
# A date in any of the shapes a building document actually uses.
_HAS_DATE_RE = re.compile(
    r"\b\d{4}-\d{2}-\d{2}\b|\b\d{1,2}[/-]\d{1,2}[/-]\d{2,4}\b"
    r"|\b(?:jan|feb|mar|apr|may|jun|jul|aug|sep|oct|nov|dec)[a-z]*\s+\d{1,2}\b"
    r"|\b\d{1,2}\s+(?:jan|feb|mar|apr|may|jun|jul|aug|sep|oct|nov|dec)[a-z]*\b"
    r"|\b(?:jan|feb|mar|apr|may|jun|jul|aug|sep|oct|nov|dec)[a-z]*\s+\d{4}\b",
    re.IGNORECASE,
)
_HAS_NUMBER_RE = re.compile(r"\d")


def missing_fact_caveat(query: str, passage: str) -> Optional[str]:
    """Return a caveat when the passage lacks the KIND of fact the question wants.

    ``None`` when the question asks for no particular kind, or the passage does
    contain one — silence is correct then, and a caveat on every answer would be
    noise that teaches users to ignore it.
    """
    q, p = query or "", passage or ""
    if not q.strip() or not p.strip():
        return None
    if _ASKS_DATE_RE.search(q) and not _HAS_DATE_RE.search(p):
        return (
            "I don't hold a specific date for this — what follows is the related "
            "information I do have."
        )
    if _ASKS_QUANTITY_RE.search(q) and not _HAS_NUMBER_RE.search(p):
        return (
            "I don't hold a specific figure for this — what follows is the related "
            "information I do have."
        )
    return None


SUBJECT_SENSOR = "sensor"  # a measurable quantity / live reading
SUBJECT_SPACE = "space"  # a room, floor, wing, zone, amenity
SUBJECT_EQUIPMENT = "equipment"  # a plant/asset (chiller, lift, charger)
SUBJECT_DOCUMENT = "document"  # policy / manual / procedural knowledge


def enablement_hint(subject_kind: str, subject: str = "") -> str:
    """Return a short, actionable 'how to make this answerable' block.

    Mirrors the two-halves rule: a question is answerable when the thing is a triple
    in the ontology AND (for live values) its readings are rows in a registered
    database. Onboarding a source is config + data — never a code change.
    """
    name = f"**{subject}**" if subject else "this"
    common = (
        "\n\nYou can add it — no code changes needed:\n"
        "1. **Describe it in the ontology** — upload a TTL naming the entity and its "
        "relationships (Admin portal → *Ontology* → upload, or drop the `.ttl` into the "
        "active building's input folder and restart).\n"
    )
    if subject_kind == SUBJECT_SENSOR:
        return (
            f"{common}"
            "2. **Point it at its readings** — give each sensor a "
            "`ref:hasExternalReference` → `ref:hasTimeseriesId` (the column/uuid) plus "
            "`ref:storedAt` (a key from `database_registry.yaml`).\n"
            "3. **Register the database** holding those rows (Admin portal → *Databases*).\n"
            f"Once both halves exist, questions about {name} are answered live — "
            "the pipeline needs nothing else."
        )
    if subject_kind == SUBJECT_EQUIPMENT:
        return (
            f"{common}"
            "2. **Link its points** — relate the asset to its sensors/commands "
            "(`brick:hasPoint`), and give any measured point a timeseries reference + "
            "`ref:storedAt` so live values resolve.\n"
            f"Once {name} exists in the model, I can answer about it and its readings."
        )
    if subject_kind == SUBJECT_SPACE:
        return (
            f"{common}"
            "2. **Place it in the hierarchy** — relate it to its floor/building "
            "(`brick:hasPart` / `brick:isPartOf`) and link any sensors located there.\n"
            "3. For a non-instrumented amenity, an `ontosage:Amenity` triple is enough "
            "(Admin portal → *Capabilities*) — include lay terms people actually say.\n"
            f"Then questions about {name} resolve to real, located entities."
        )
    if subject_kind == SUBJECT_DOCUMENT:
        return (
            "\n\nYou can add it — no code changes needed: upload the manual, policy or "
            "procedure to the active building's `documents/` folder (Admin portal → "
            "*Documents*). It is indexed automatically and quoted with its source, so "
            f"questions about {name} are answered from your own document."
        )
    return common

# ─────────────────────────────────────────────────────────────────────────────
# Meta-answers: prose ABOUT the pipeline, delivered instead of an answer
# ─────────────────────────────────────────────────────────────────────────────
#
# Measured live 2026-09-06, "Which rooms are stuffy right now?":
#
#     "I don't have the live CO2 or temperature readings that would let me tell you which
#      rooms are currently 'stuffy.' What I can share is a quick snapshot of how many
#      sensors are installed in each space...
#      Floor 0 - 11 sensors, Floor 1 - 8 sensors, ...
#      If you'd like to pull the current CO2 or temperature data for any of these spaces,
#      just let me know."
#
# The building has 589 air-quality sensors and a populated co2_data table. The generated
# SPARQL had returned COUNTS per space rather than readings, and the model narrated the
# shortfall -- offering, at the end, to do the very thing it had just been asked to do.
#
# THIS IS NOT AN HONEST DECLINE, AND THE DIFFERENCE IS THE WHOLE POINT.
#
# An honest decline is a statement about the BUILDING: "this building has no lifts recorded
# in its model", followed by what would make it answerable. It is produced deterministically
# by a lane that looked and found nothing, and it is one of this system's best behaviours.
#
# A meta-answer is a statement about the PIPELINE: what the model was handed, what it would
# need, what the reader should go and do. The reader cannot act on it, cannot tell whether
# the building has the data, and is being asked to operate machinery they cannot see. Worse,
# it usually arrives WITH a table of something else, which reads as a partial answer.
#
# So the markers below are deliberately narrow: each one names the conversation, the query
# or the reader's obligation to fetch data. None of them can appear in a true statement
# about a building.

#: Phrases that describe the exchange rather than the building.
_META_ANSWER_RES = (
    # The data as an object handed over in conversation.
    re.compile(
        r"\bthe (?:data|results?|information|context|snippets?|records?) "
        r"(?:you(?:'ve| have)? |that (?:you|were) )?(?:provided|gave|supplied|shared|sent"
        r"|pasted|listed|above)\b",
        re.IGNORECASE,
    ),
    re.compile(
        r"\bbased on the (?:data|information|context|results?) (?:provided|given|supplied"
        r"|you (?:provided|gave))\b",
        re.IGNORECASE,
    ),
    # Asking the reader to run the system.
    re.compile(
        r"\b(?:if you can|you (?:can|could|may want to|might want to|would need to|"
        r"should)|please)\s+(?:run|execute|issue|write|perform)\s+(?:a |an |the )?"
        r"(?:query|sparql|sql|search)\b",
        re.IGNORECASE,
    ),
    re.compile(
        r"\b(?:please|kindly)\s+(?:provide|supply|share|paste|upload)\s+"
        r"(?:the |more |additional |further )?(?:data|readings?|values?|information)\b",
        re.IGNORECASE,
    ),
    # Narrating the shortfall of its own inputs.
    re.compile(
        r"\b(?:i (?:do not|don't) have access to|i was not (?:given|provided)|"
        r"no (?:data|readings?|values?) (?:were|was) (?:provided|given|supplied|included))"
        r"\b",
        re.IGNORECASE,
    ),
    re.compile(
        r"\bonly tells? (?:us|me|you) how many\b|\bdoes not (?:contain|include) "
        r"(?:any )?(?:actual |live )?(?:readings?|measurements?|values?)\b",
        re.IGNORECASE,
    ),
    # THE PIVOT, which is what the live failure actually was.
    #
    # A bare "I don't have X" cannot be the marker: this system says it legitimately and
    # deterministically -- "I don't have a floor plan for Floor 7", "I don't have that
    # specific information on record" -- and each is a true statement followed by what
    # would change it. Catching those would suppress the honesty this project is built on.
    #
    # What made the stuffy-rooms answer a meta-answer is the SECOND move: having said it
    # lacks the readings, it offers a substitute it has just labelled as not the thing
    # asked for, and then hands the task back to the reader. Those two sentences together
    # describe the pipeline's state, not the building's.
    re.compile(
        # `give you` was missing, and that is what the live answer said: "What I can give
        # you is a quick snapshot of the rooms that are equipped with sensors". Three
        # synonyms is not a vocabulary; the verb is anything that hands over a substitute.
        r"\b(?:what i can (?:share|tell you|offer|give you|provide|show you) (?:instead )?is"
        r"|instead,? (?:here is|i can (?:show|share|offer))"
        r"|however,? i can (?:show|share|offer|tell))\b",
        re.IGNORECASE,
    ),
    re.compile(
        r"\bif you(?:'d| would)? like (?:me )?to (?:pull|fetch|check|look up|get|query)\b"
        r".{0,80}?\b(?:just )?let me know\b",
        re.IGNORECASE | re.DOTALL,
    ),
)

#: An honest decline says what the BUILDING lacks and how to change that. These phrases
#: are the system's own decline vocabulary and must never be treated as meta-narration:
#: catching them would suppress the behaviour this whole project is built around.
_HONEST_DECLINE_RES = (
    re.compile(
        r"\bthis building (?:has no|does not have|is not|has not)\b", re.IGNORECASE
    ),
    re.compile(r"\bnot (?:recorded|described|declared) in (?:this|the) building\b", re.IGNORECASE),
    re.compile(r"\bno (?:such )?(?:room|space|floor|zone|sensor|asset) (?:called|named)\b", re.IGNORECASE),
    re.compile(r"\byou can add it\b|\bno code changes? needed\b", re.IGNORECASE),
)


#: Typographic characters a language model produces where the patterns above write ASCII.
#:
#: THE GUARD MISSED THE ANSWER IT WAS WRITTEN FOR because of this. Live, 2026-09-07:
#:
#:     "If you’d like to check the current CO₂ levels ... just let me know."
#:
#: The pattern says `you(?:'d| would)?` with a STRAIGHT apostrophe. The model wrote a
#: RIGHT SINGLE QUOTATION MARK, so nothing matched, and the exact prose this guard exists
#: to suppress reached the user with the guard sitting in front of it.
#:
#: It is a class, not an instance: a model writes curly quotes, en and em dashes and
#: ellipsis characters wherever prose calls for them, so every pattern matching a
#: contraction or a dash in MODEL OUTPUT has the same hole. Normalising once here fixes
#: all of them, and is why this is a translation table rather than another alternative
#: added to one regex.
_TYPOGRAPHY = str.maketrans(
    {
        "\u2019": "'",  # right single quote -> apostrophe
        "\u2018": "'",
        "\u201c": '"',
        "\u201d": '"',
        "\u2013": "-",  # en dash
        "\u2014": "-",  # em dash
        "\u00a0": " ",  # non-breaking space
        "\u2011": "-",  # non-breaking hyphen
    }
)


def normalise_typography(text: str) -> str:
    """Model prose, in the characters the patterns are written in."""
    return (text or "").translate(_TYPOGRAPHY)


def meta_answer_reason(text: str) -> Optional[str]:
    """The phrase that makes this prose ABOUT the pipeline, or None.

    Returns the matched text so a caller can log WHICH marker fired. A guard that reports
    only "blocked" cannot be tuned, and an untunable guard is one that gets disabled the
    first time it is wrong.
    """
    body = normalise_typography(text)
    if not body.strip():
        return None
    for ok in _HONEST_DECLINE_RES:
        if ok.search(body):
            return None
    for bad in _META_ANSWER_RES:
        m = bad.search(body)
        if m:
            return m.group(0).strip()
    return None


def is_meta_answer(text: str) -> bool:
    """True when the prose describes the pipeline rather than the building."""
    return meta_answer_reason(text) is not None

