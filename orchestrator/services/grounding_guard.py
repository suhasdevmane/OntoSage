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
    """Crude, dependency-free singulariser — enough to match 'sensors'↔'sensor'."""
    if len(word) > 3 and word.endswith("ies"):
        return word[:-3] + "y"
    if len(word) > 3 and word.endswith("ses"):
        return word[:-2]
    if len(word) > 3 and word.endswith("s") and not word.endswith("ss"):
        return word[:-1]
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
