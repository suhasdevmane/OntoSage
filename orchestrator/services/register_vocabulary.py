# -*- coding: utf-8 -*-
"""Which question words name which register columns and recorded values (BUG-835).

"Which refuge points are defective, and who owns them?" was answered "the register does not
contain an ownership field" over a register with an owner column, because the census compared
the question's word with the column's word letter by letter: "owns" and "owner" share three.
A person's word for a thing and the column named for it are joined here, from a table in
``config/register_vocabulary.yaml`` -- ordinary English only, no building and no register named.

This module only READS that table and answers four questions about it. What to do with the
answers (filter rows, project fields, compose a reply) lives in ``register_projection``.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from functools import lru_cache
from pathlib import Path
from typing import Dict, FrozenSet, List, Optional, Sequence, Tuple

import yaml

from shared.utils import get_logger

logger = get_logger(__name__)

#: /app is where the container mounts config/; the relative path serves a checkout and tests.
_PATHS = (Path("/app/config/register_vocabulary.yaml"), Path("config/register_vocabulary.yaml"))
_REPO_PATH = Path(__file__).resolve().parents[2] / "config" / "register_vocabulary.yaml"

_SUFFIXES = ("ership", "ers", "er", "ing", "ed", "es", "s")


def stem(word: str) -> str:
    """A crude stem, good only for asking whether two words are the same word.

    owns, owner, owners, owned and ownership all come out as "own"; points as "point";
    serviced and services as "servic". It is compared for equality and never displayed, so
    what matters is that the same English word always maps to the same stem.
    """
    w = (word or "").lower().strip()
    for suffix in _SUFFIXES:
        # "es" is a plural only after s, x, z, ch or sh (boxes, classes): "lines" is "line" + "s"
        if suffix == "es" and not re.search(r"(?:s|x|z|ch|sh)es$", w):
            continue
        if suffix == "s" and w.endswith("ss"):
            continue  # "class", "access" are not plurals
        if w.endswith(suffix) and len(w) - len(suffix) >= 3:
            w = w[: -len(suffix)]
            break
    if w.endswith("e") and len(w) > 4:
        w = w[:-1]
    return w


def words_of(text: str) -> List[str]:
    """Lower-case letter runs, hyphens split."""
    return re.findall(r"[a-z]+", (text or "").lower())


def column_words(col: str) -> List[str]:
    """``nextTestDue`` -> [next, test, due]."""
    return [w.lower() for w in re.findall(r"[A-Z]?[a-z]+", col or "")]


def normalise_value(value: str) -> str:
    """A recorded value as words: ``in_progress`` -> "in progress"."""
    return " ".join(words_of(value))


@dataclass(frozen=True)
class Concept:
    """One idea a question asks for in several ways, and the columns that record it."""

    name: str
    plain: str
    shape: str
    stems: FrozenSet[str]
    phrases: Tuple[str, ...]
    columns: Tuple[str, ...]
    exclude: Tuple[str, ...] = ()
    stamps: Tuple[str, ...] = ()
    pick: str = ""
    words: Tuple[str, ...] = ()
    _phrase_res: Tuple["re.Pattern", ...] = field(default=(), compare=False, repr=False)

    def asked_in(self, low: str, question_stems: FrozenSet[str]) -> bool:
        """Does the (lower-cased) question ask for this concept?"""
        if question_stems & self.stems:
            return True
        return any(p.search(low) for p in self._phrase_res)

    def consumed_stems(self, low: str) -> FrozenSet[str]:
        """Stems of the question words this concept accounts for, phrase words included."""
        out = set(self.stems)
        for pattern in self._phrase_res:
            found = pattern.search(low)
            if found:
                out.update(stem(w) for w in words_of(found.group(0)))
        return frozenset(out)

    def triggers(self, low: str, question_stems: FrozenSet[str]) -> FrozenSet[str]:
        """The stems of the question's words that asked for this concept."""
        out = set(question_stems & self.stems)
        for pattern in self._phrase_res:
            found = pattern.search(low)
            if found:
                out.update(stem(w) for w in words_of(found.group(0)))
        return frozenset(out)

    def names_column(self, col: str) -> bool:
        """Does this column's NAME carry one of the concept's words?"""
        words = column_words(col)
        if any(w in self.exclude for w in words):
            return False
        return any(w.startswith(t) for w in words for t in self.columns)


@dataclass(frozen=True)
class StatusGroup:
    """Question words for a recorded state, and the recorded values they can stand for."""

    name: str
    stems: FrozenSet[str]
    phrases: Tuple[str, ...]
    values: Tuple[str, ...]
    _phrase_res: Tuple["re.Pattern", ...] = field(default=(), compare=False, repr=False)

    def asked_in(self, low: str, question_stems: FrozenSet[str]) -> bool:
        if question_stems & self.stems:
            return True
        return any(p.search(low) for p in self._phrase_res)

    def consumed_stems(self, low: str) -> FrozenSet[str]:
        out = set(self.stems)
        for pattern in self._phrase_res:
            found = pattern.search(low)
            if found:
                out.update(stem(w) for w in words_of(found.group(0)))
        return frozenset(out)

    def matches_recorded(self, recorded: str) -> bool:
        """Is this recorded status value one the group's words can mean?"""
        norm = normalise_value(recorded)
        return any(norm.startswith(v) for v in self.values)


def _phrase_regexes(phrases: Sequence[str]) -> Tuple["re.Pattern", ...]:
    """A phrase is a literal ("last serviced") unless written ``re:<pattern>``."""
    return tuple(
        (
            re.compile(p[3:], re.IGNORECASE)
            if p.startswith("re:")
            else re.compile(r"(?<![a-z])" + re.escape(p.lower()) + r"(?![a-z])")
        )
        for p in phrases
    )


@dataclass(frozen=True)
class Criterion:
    """A condition a person states about a column ("good Wi-Fi") and the recorded values that meet it."""

    patterns: Tuple["re.Pattern", ...]
    column: str
    accepts: Tuple[str, ...]


def _flex_pattern(phrase: str) -> "re.Pattern":
    """ "wi-fi" also matches "wifi" and "wi fi"; words are separated by any whitespace."""
    tokens = []
    for token in phrase.lower().split():
        pieces = [re.escape(p) for p in token.split("-") if p]
        tokens.append(r"[\s\-]*".join(pieces))
    return re.compile(r"(?<![\w])" + r"\s+".join(tokens) + r"(?![\w])", re.IGNORECASE)


@dataclass(frozen=True)
class Vocabulary:
    """The whole table, parsed."""

    concepts: Dict[str, Concept]
    statuses: Tuple[StatusGroup, ...]
    value_synonyms: Dict[str, Tuple[str, ...]]
    generic_nouns: FrozenSet[str] = frozenset()
    topic_words: FrozenSet[str] = frozenset()
    naming_words: FrozenSet[str] = frozenset()
    status_words: FrozenSet[str] = frozenset()
    criteria: Tuple[Criterion, ...] = ()
    column_aliases: Dict[str, Tuple[str, ...]] = field(default_factory=dict)
    absent_values: Tuple["re.Pattern", ...] = ()
    qualifier_words: FrozenSet[str] = frozenset()
    generic_verbs: FrozenSet[str] = frozenset()

    def question_stems(self, question: str) -> FrozenSet[str]:
        return frozenset(stem(w) for w in words_of(question))

    def concepts_in(self, question: str) -> List[Concept]:
        """The concepts the question asks for, in table order."""
        low = (question or "").lower()
        stems = self.question_stems(question)
        return [c for c in self.concepts.values() if c.asked_in(low, stems)]

    def status_groups_in(self, question: str) -> List[StatusGroup]:
        low = (question or "").lower()
        stems = self.question_stems(question)
        return [g for g in self.statuses if g.asked_in(low, stems)]

    def columns_for(self, concept: Concept, columns: Sequence[str]) -> List[str]:
        """The columns whose NAME records the concept (stamps handled by the caller)."""
        return [c for c in columns if concept.names_column(c)]

    def concept_of_term(self, term: str) -> Optional[Concept]:
        s = stem(term.replace("-", ""))
        for concept in self.concepts.values():
            if s in concept.stems:
                return concept
        return None

    def forms_of(self, term: str) -> FrozenSet[str]:
        """Every question word that says what ``term`` says ("owns" -> owner, ownership ...)."""
        concept = self.concept_of_term(term)
        return frozenset(concept.words) if concept else frozenset()

    def term_names_column(self, term: str, col: str) -> bool:
        """Does this question word, through the table, name this column?"""
        concept = self.concept_of_term(term)
        return bool(concept and concept.names_column(col))

    def readable_stamps(self, term: str, columns: Sequence[str]) -> List[str]:
        """Provenance columns the term's concept is allowed to read ("owns" -> recordOwner)."""
        concept = self.concept_of_term(term)
        if not concept:
            return []
        return [c for c in columns if c in concept.stamps]

    def value_says_none(self, value: str) -> bool:
        """Does this recorded value SAY there is none of the thing?

        "No cover, next working day" does; "Normal hours" does not. A cell holding only a dash
        does, because that is how a table writes "nothing here".
        """
        text = (value or "").strip()
        if not text:
            return False  # an empty cell is the OTHER reading, and the caller keeps them apart
        if re.fullmatch(r"[-–—]{1,2}", text):
            return True
        return any(p.match(text) for p in self.absent_values)

    def names_what_a_record_is(self, col: str) -> bool:
        """Is this a column whose values NAME the record ("location", "kind", "asset")?"""
        return any(w in self.naming_words for w in column_words(col))

    def value_words_for(self, term: str) -> FrozenSet[str]:
        """Stems of the recorded VALUES a question word may stand for (quiet -> silent too)."""
        s = stem(term.replace("-", ""))
        out = {s}
        for word in self.value_synonyms.get(term.lower(), ()) + self.value_synonyms.get(s, ()):
            out.add(stem(word))
        return frozenset(out)


def _build(raw: Dict) -> Vocabulary:
    concepts: Dict[str, Concept] = {}
    for name, spec in (raw.get("concepts") or {}).items():
        question = [str(w).lower() for w in spec.get("question") or []]
        phrases = tuple(str(p).lower() for p in spec.get("phrases") or [])
        concepts[name] = Concept(
            name=name,
            plain=str(spec.get("plain") or name),
            shape=str(spec.get("shape") or ""),
            stems=frozenset(stem(w) for w in question),
            phrases=phrases,
            columns=tuple(str(c).lower() for c in spec.get("columns") or []),
            exclude=tuple(str(c).lower() for c in spec.get("exclude") or []),
            stamps=tuple(str(c) for c in spec.get("stamps") or []),
            pick=str(spec.get("pick") or ""),
            words=tuple(question),
            _phrase_res=_phrase_regexes(phrases),
        )
    groups = []
    for spec in raw.get("statuses") or []:
        words = [str(w).lower() for w in spec.get("words") or []]
        phrases = tuple(str(p).lower() for p in spec.get("phrases") or [])
        values = tuple(normalise_value(str(v)) for v in spec.get("values") or [])
        groups.append(
            StatusGroup(
                name=values[0] if values else "",
                stems=frozenset(stem(w) for w in words),
                phrases=phrases,
                values=values,
                _phrase_res=_phrase_regexes(phrases),
            )
        )
    synonyms = {
        str(k).lower(): tuple(str(v).lower() for v in vs or [])
        for k, vs in (raw.get("value_synonyms") or {}).items()
    }
    return Vocabulary(
        concepts=concepts,
        statuses=tuple(groups),
        value_synonyms=synonyms,
        generic_nouns=frozenset(stem(str(w)) for w in raw.get("generic_nouns") or []),
        topic_words=frozenset(stem(str(w)) for w in raw.get("topic_words") or []),
        naming_words=frozenset(str(w).lower() for w in raw.get("naming_columns") or []),
        status_words=frozenset(stem(str(w)) for w in raw.get("status_words") or []),
        qualifier_words=frozenset(stem(str(w)) for w in raw.get("qualifier_words") or []),
        generic_verbs=frozenset(str(w).lower() for w in raw.get("generic_verbs") or []),
        absent_values=tuple(
            re.compile(r"\s*" + re.escape(str(p).strip().lower()) + r"\b", re.IGNORECASE)
            for p in raw.get("absent_values") or []
        ),
        criteria=tuple(
            Criterion(
                patterns=tuple(
                    _flex_pattern(str(p))
                    for p in sorted(spec.get("phrases") or [], key=lambda x: -len(str(x)))
                ),
                column=str(spec.get("column") or "").lower(),
                accepts=tuple(normalise_value(str(a)) for a in spec.get("accepts") or []),
            )
            for spec in raw.get("criteria") or []
        ),
        column_aliases={
            str(k).lower(): tuple(str(a).lower() for a in vs or [])
            for k, vs in (raw.get("column_aliases") or {}).items()
        },
    )


@lru_cache(maxsize=1)
def get_vocabulary() -> Vocabulary:
    """The vocabulary, read once. A missing or broken file yields an EMPTY table, never an error:
    the register lane then behaves as it did before the table existed."""
    for path in (*_PATHS, _REPO_PATH):
        try:
            if path.is_file():
                raw = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
                return _build(raw)
        except (OSError, yaml.YAMLError, AttributeError, TypeError) as exc:
            logger.warning(f"[register_vocabulary] {path} unreadable: {type(exc).__name__}: {exc}")
    logger.warning("[register_vocabulary] no vocabulary file found — synonyms are off")
    return Vocabulary(concepts={}, statuses=(), value_synonyms={})
