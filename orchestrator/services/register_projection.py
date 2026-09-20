# -*- coding: utf-8 -*-
"""Typed composition for the register lane: the answer is projected from the rows (2D-06).

The register lane fetches the right records and then asks a language model to narrate them. In
the 2026-09-18 hand reads that narration was the largest single source of weird answers, and
the failures were one shape: the rows were right and a word in the question was not matched to
the field that answers it. "Which refuge points are defective, and who owns them?" was answered
"the register does not contain an ownership field" over a register whose owner column reads
"Building Fire Warden Coordinator" (BUG-835); "Is the building up to date with its fire safety
inspections?" concluded "up to date" from one register while another shows an overdue dry riser
(BUG-829); "Is there a quiet room?" called 26 rooms quiet because each has a *quietest period*
field (BUG-813); "Which maintenance tasks are overdue?" said the building holds no maintenance
information (BUG-811).

A prompt asking the model to do better was tried six times and moved nothing measurable, so the
operations are done here, on the rows, and the model is handed the result or bypassed:

* ``resolve`` matches every content word of the question to a status, a recorded value, a
  field (through ``register_vocabulary``, so "owns" finds ``recordOwner``) or the text of a
  record, and returns the records that satisfy ALL of them;
* ``facts_lines`` hands those records to the narration as locked facts;
* ``deterministic_answer`` IS the answer for a simple who / when / which / how-many question
  whose every word was resolved, so the model is not asked;
* ``guard_narration`` replaces a paragraph that denies a field the rows hold with the values;
* ``cross_register_answer`` refuses to let ONE register stand for a whole subject: "is the
  building up to date with X" is answered from every register that covers X.

Nothing here knows a building, a register or a class: registers are read as rows, columns by
the words in their names, and the vocabulary comes from ``config/register_vocabulary.yaml``.
"""

from __future__ import annotations

import os
import re
from collections import Counter
from dataclasses import dataclass, field, replace
from functools import lru_cache
from pathlib import Path
from datetime import date, timedelta
from typing import Any, Awaitable, Callable, Dict, List, Optional, Sequence, Set, Tuple

import yaml

from orchestrator.services import register_facts as rf
from orchestrator.services.register_vocabulary import (
    Concept,
    StatusGroup,
    Vocabulary,
    column_words,
    get_vocabulary,
    normalise_value,
    stem,
    words_of,
)
from shared.utils import get_logger

logger = get_logger(__name__)

STATUS = rf.STATUS

#: Rows a deterministic answer will list. Past this the question is a survey, not a lookup, and
#: the narration (with the locked facts) is better placed to summarise it.
MAX_ANSWER_ROWS = 40
MAX_LISTED = 30
#: Past this many records the narration is handed the list as one line, not one bullet each.
COMPACT_AT = 10
#: Rows sharing one value are folded ("Estates: EV-001, EV-002 ...") past this many.
FOLD_AT = 6

#: Recorded statuses that mean a record is finished with. A date passed on such a record is
#: history, not a lapse.
_CLOSED = frozenset(rf._CLOSED_STATUSES) | frozenset(
    {"done", "resolved", "complete", "finished", "fixed", "passed", "superseded"}
)

_DATE_RE = re.compile(r"^\d{4}-\d{2}-\d{2}")

#: A question that asks for judgement, a comparison or an explanation. A lookup cannot answer it,
#: so it is never composed deterministically (the locked facts still reach the narration).
_NOT_SIMPLE_RE = re.compile(
    r"\b(?:why|should|compare|versus|vs|average|best|worst|most|least|highest|lowest|longest|"
    r"shortest|rank\w*|trend\w*|because|whether|difference|recommend\w*|suitable|suitability|"
    r"enough|adequate|impact|effect|cause\w*|reason\w*|between|"
    r"(?:is|are)\s+(?:it|they|this|that|we|the\s+\w+)\s+safe|how\s+(?:safe|risky)|"
    r"\brisk\s+of\s+(?!noise)|"
    r"how\s+(?!many\b|much\b)\w+)\b",
    re.IGNORECASE,
)
_COUNT_RE = re.compile(r"\bhow\s+many\b|\bnumber\s+of\b|\bhow\s+much\b|\bcount\b", re.IGNORECASE)
_LIST_RE = re.compile(r"\b(?:which|what|who|whom|when|where|list|show|name|give)\b", re.IGNORECASE)

#: A yes/no question about a whole subject's state. Answered from EVERY register on the subject.
_STATE_WORDS = r"(?:up\s+to\s+date|compliant|in\s+date|overdue|lapsed|outstanding|out\s+of\s+date)"
_WHOLE_SUBJECT_RE = re.compile(
    r"^\W*(?:is|are|do|does|have|has|were|was)\b.*\b" + _STATE_WORDS + r"\b"
    r"|^\W*(?:is|are)\s+(?:there\s+)?any\b.*\b(?:overdue|lapsed|outstanding|defective|faulty)\b",
    re.IGNORECASE | re.DOTALL,
)


def answers_enabled() -> bool:
    """Deterministic answers are ON unless REGISTER_PROJECTION_ANSWER is set to false."""
    return os.environ.get("REGISTER_PROJECTION_ANSWER", "true").strip().lower() != "false"


# --------------------------------------------------------------------------------------
# small row helpers
# --------------------------------------------------------------------------------------


def _value(row: Dict, col: str) -> str:
    return rf._value(row, col)


def _ident(row: Dict) -> str:
    """A record's identifier: its id, its label, or the tail of its IRI."""
    ident = rf._ident(row)
    if ident != "?":
        return ident
    iri = _value(row, "record")
    return iri.rsplit("/", 1)[-1].rsplit("#", 1)[-1] or "?"


def _as_date(raw: str) -> Optional[date]:
    if not raw or not _DATE_RE.match(raw):
        return None
    try:
        return date.fromisoformat(raw[:10])
    except ValueError:
        return None


def _fmt_date(d: date) -> str:
    return f"{d.day} {d.strftime('%B %Y')}"


def _show(value: str) -> str:
    """A recorded value for a reader: ISO dates as "3 June 2026", everything else as recorded."""
    d = _as_date(value)
    return _fmt_date(d) if d else value


_LABELS = {"recordOwner": "owner", STATUS: "status", "label": "name", "comment": "note"}


def _label(col: str) -> str:
    """A column in ordinary words: recordOwner -> "owner", locationText -> "location"."""
    if col in _LABELS:
        return _LABELS[col]
    words = rf._plain(col).split()
    if len(words) > 1 and words[-1] == "text":
        words = words[:-1]
    return " ".join(words) or col


def _all_columns(rows: Sequence[Dict]) -> List[str]:
    return sorted({k for r in rows for k in r})


def _is_closed(row: Dict, columns: Sequence[str]) -> bool:
    """Finished with: a closed status, or a recorded completion date."""
    status = normalise_value(_value(row, STATUS))
    if status and status.split(" ")[0] in _CLOSED:
        return True
    return any(
        _value(row, c) for c in columns if any(w.startswith("complet") for w in column_words(c))
    )


def _join(items: Sequence[str], conj: str = "and") -> str:
    items = [str(i) for i in items]
    if len(items) <= 1:
        return "".join(items)
    return ", ".join(items[:-1]) + f" {conj} " + items[-1]


def _sentence_case(text: str) -> str:
    return text[:1].upper() + text[1:]


# --------------------------------------------------------------------------------------
# what is overdue
# --------------------------------------------------------------------------------------


@dataclass
class OverdueInfo:
    """Which records are overdue, and on what evidence."""

    #: due | interval | recorded | none
    basis: str
    columns: List[str] = field(default_factory=list)
    recorded: List[int] = field(default_factory=list)
    computed: List[int] = field(default_factory=list)
    due: Dict[int, date] = field(default_factory=dict)


def overdue_info(rows: List[Dict], columns: Sequence[str], today: Optional[date]) -> OverdueInfo:
    """Records past their date, or recorded as overdue, from what the register holds.

    A register that records a due date is read against today; one that records a last-seen date
    and an interval is computed the same way (``last + interval``); one that records only a
    status is read as recorded; and one that records none of these says so, because a due date
    is not something to guess.
    """
    recorded = [i for i, r in enumerate(rows) if "overdue" in normalise_value(_value(r, STATUS))]
    due_cols = [
        c
        for c in columns
        if any(w in ("due", "deadline") for w in column_words(c))
        and any(_as_date(_value(r, c)) for r in rows)
    ]
    info = OverdueInfo(basis="none", recorded=recorded)
    if today is not None and due_cols:
        info.basis, info.columns = "due", due_cols
        for i, r in enumerate(rows):
            dates = [d for d in (_as_date(_value(r, c)) for c in due_cols) if d]
            if dates:
                info.due[i] = min(dates)
            if i in recorded or _is_closed(r, columns):
                continue
            if dates and min(dates) < today:
                info.computed.append(i)
        return info
    last_cols = [c for c in columns if rf._LAST_COLUMN_RE.search(c)]
    interval_cols = [c for c in columns if rf._INTERVAL_COLUMN_RE.search(c)]
    if today is not None and last_cols and interval_cols:
        info.basis, info.columns = "interval", [last_cols[0], interval_cols[0]]
        for i, r in enumerate(rows):
            when = _as_date(_value(r, last_cols[0]))
            days = rf._as_number(_value(r, interval_cols[0]))
            if when is None or days is None:
                continue
            info.due[i] = when + timedelta(days=int(days))
            if i not in recorded and not _is_closed(r, columns) and info.due[i] < today:
                info.computed.append(i)
        return info
    if recorded:
        info.basis = "recorded"
    return info


# --------------------------------------------------------------------------------------
# resolving the question against the rows
# --------------------------------------------------------------------------------------


# --------------------------------------------------------------------------------------
# the question a person typed, and the question inside it
# --------------------------------------------------------------------------------------

_LEAD_CLAUSE_RE = re.compile(r"^\s*([^:?!.\n]{1,60}):\s+")
_FOR_CLAUSE_RE = re.compile(r"^\s*for\s+(?:the|my)\s+[\w ]{1,24}?\s*,\s*", re.IGNORECASE)
_POLITE_RE = re.compile(
    r"\b(?:can|could|would|will)\s+you\s+(?:please\s+)?(tell|show|give|list|let)\s+me"
    r"(?:\s+know)?\b[:,]?\s*",
    re.IGNORECASE,
)
_ADDRESS_RE = re.compile(r"\b(?:tell|show|give|let)\s+me(?:\s+know)?\b[:,]?\s*", re.IGNORECASE)
_PERIOD_RE = re.compile(
    r"\b(?:today|tonight|this\s+(?:week|month|term|year|morning|afternoon)|"
    r"next\s+(?:week|month|term)|last\s+(?:week|month|term)|tomorrow|yesterday)\b",
    re.IGNORECASE,
)
_DURATION_RE = re.compile(
    r"\bfor\s+(?:about\s+|around\s+|at least\s+)?(?:\d+(?:\.\d+)?|a|an|one|two|three|four|five|six|"
    r"seven|eight|half an?)\s+(?:hours?|hrs?|minutes?|mins?)\b",
    re.IGNORECASE,
)
#: "where can I work", "a room I can use": the asker is only the subject of a search for places
_OPEN_ASK_RE = re.compile(
    r"^\W*(?:where|which|what)\b[^?]*\b(?:can|could|should|might|may)\s+i\b"
    r"|\b(?:room|space|place|desk|seat|area|option|spot)s?\s+(?:that\s+)?i\s+(?:can|could|might)\b",
    re.IGNORECASE,
)
_OWNERSHIP_PERSON_RE = re.compile(r"\b(?:my|mine|our|ours|we|we're|us|me)\b", re.IGNORECASE)
_EVERY_ONE_RE = re.compile(r"\bevery one of\b\s*", re.IGNORECASE)
_TRAILING_ASK_RE = re.compile(
    r"[,.]?\s*(?:giving each reference|and give the ids|with (?:their|each) (?:references|ids))"
    r"\s*[.?!]?\s*$",
    re.IGNORECASE,
)
_SPEAKER_SENTENCE_RE = re.compile(r"^(?:i|i'm|i am|i've|we|we're|our|my)\b", re.IGNORECASE)
_QUESTION_START_RE = re.compile(
    r"^(?:which|what|who|whom|when|where|how|list|show|name|give|are|is|do|does)\b", re.IGNORECASE
)


@dataclass
class Prepared:
    """A question with the politeness taken off it."""

    core: str
    #: the wording asked for a list ("could you list the ...", "just the references")
    list_hint: bool = False
    #: the question is about the reader ("my shift", "can I use")
    reader: bool = False
    #: phrases the register cannot filter on and that were set aside ("for three hours")
    dropped: List[str] = field(default_factory=list)


def prepare(question: str) -> Prepared:
    """The question inside the sentence: "For the audit record: List every one of the permits
    that are closed, giving each reference" asks "which permits are closed".

    Only wrappers are removed — a lead clause up to a colon, "for my notes,", a sentence about the
    speaker, "can you tell me", a trailing "just the references, please". Every word that says what
    is being asked is left exactly as it was written.
    """
    text = (question or "").strip()
    sentences = [s.strip() for s in re.split(r"(?<=[.?!])\s+", text) if s.strip()]
    kept: List[str] = []
    hint = False
    for i, sentence in enumerate(sentences):
        later_asks = any("?" in t or _QUESTION_START_RE.match(t) for t in sentences[i + 1 :])
        if _SPEAKER_SENTENCE_RE.match(sentence) and not sentence.endswith("?") and later_asks:
            continue  # "I'm writing a report on this building."
        if re.match(r"^(?:just|please)\b", sentence, re.IGNORECASE) and kept:
            hint = hint or bool(re.search(r"references|ids|list", sentence, re.IGNORECASE))
            continue  # "Just the references, please."
        kept.append(sentence)
    core = " ".join(kept) or text
    lead = _LEAD_CLAUSE_RE.match(core)
    if lead and len(core[lead.end() :].split()) >= 3 and "?" not in lead.group(1):
        core = core[lead.end() :]
    core = _FOR_CLAUSE_RE.sub("", core, count=1)
    polite = _POLITE_RE.search(core)
    if polite:
        hint = hint or polite.group(1).lower() in ("list", "show", "give")
        core = _POLITE_RE.sub("", core, count=1)
    core = _EVERY_ONE_RE.sub("", core)
    if _TRAILING_ASK_RE.search(core):
        hint = True
        core = _TRAILING_ASK_RE.sub("", core)
    core = _ADDRESS_RE.sub("", core).strip() or text
    dropped = [m.group(0) for m in _DURATION_RE.finditer(core)]
    core = _DURATION_RE.sub(" ", core)
    reader = bool(rf._FIRST_PERSON_RE.search(core))
    if reader and _OPEN_ASK_RE.search(core) and not _OWNERSHIP_PERSON_RE.search(core):
        reader = False  # "where can I work with ..." asks which PLACES qualify
    return Prepared(core=core, list_hint=hint, reader=reader, dropped=dropped)


# --------------------------------------------------------------------------------------
# records named in the question, and facets ("cost centre ABW-MECH", "on floor 4")
# --------------------------------------------------------------------------------------


def _blank_span(text: str, span: Tuple[int, int]) -> str:
    return text[: span[0]] + " " + text[span[1] :]


_MAPPING_DIRS = (
    Path("/app/ontology/record_documents"),
    Path(__file__).resolve().parents[2] / "ontology" / "record_documents",
)


@lru_cache(maxsize=64)
def _header_words(record_type: str) -> Dict[str, Tuple[str, ...]]:
    """The document's own column headers, by the predicate each became: warranty ``asset`` ->
    ``coveredScope``, work order ``trade`` -> ``responsibleRole``.

    A person reads the register DOCUMENT and asks in its words; the graph keeps the predicate's
    name. The mapping that lifted the document says which is which, and ships with the ontology.
    """
    if not record_type:
        return {}
    for base in _MAPPING_DIRS:
        path = base / f"{record_type}.yaml"
        try:
            if path.is_file():
                raw = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
                out: Dict[str, Tuple[str, ...]] = {}
                for header, spec in (raw.get("columns") or {}).items():
                    predicate = str((spec or {}).get("predicate", "")).rsplit(":", 1)[-1]
                    if predicate:
                        out[predicate] = out.get(predicate, ()) + tuple(
                            w for w in words_of(str(header).replace("_", " ")) if len(w) >= 3
                        )
                return out
        except (OSError, yaml.YAMLError, AttributeError, TypeError):
            return {}
    return {}


def _headers_for(rows: Sequence[Dict]) -> Dict[str, Tuple[str, ...]]:
    return _header_words(_value(rows[0], "liftedByMapping")) if rows else {}


def _col_words(col: str, header: Dict[str, Tuple[str, ...]]) -> List[str]:
    """A column's own words, plus the words its header had in the document it came from."""
    return column_words(col) + [w for w in header.get(col, ()) if w not in column_words(col)]


def _numbers_in(text: str) -> Set[str]:
    return set(re.findall(r"\d+(?:\.\d+)?", text))


def _ids_named(rows: List[Dict], text: str) -> Tuple[Set[int], List[str], str]:
    """Records the question names by their identifier ("When is EV-009 due for review?")."""
    found: Set[int] = set()
    named: List[str] = []
    for i, row in enumerate(rows):
        rid = _value(row, "recordId")
        if len(rid) < 3:
            continue
        match = re.search(r"(?<![\w-])" + re.escape(rid) + r"(?![\w-])", text, re.IGNORECASE)
        if match:
            found.add(i)
            named.append(rid)
            text = _blank_span(text, match.span())
    return found, named, text


def _flex_label(label: str) -> "re.Pattern":
    """A record's name as a pattern that survives dash, slash and spacing variants."""
    words = re.findall(r"[\w.]+", label)
    return re.compile(
        r"(?<![\w])" + r"[\s\-–—/&]+".join(re.escape(w) for w in words) + r"(?![\w])",
        re.IGNORECASE,
    )


def _labels_named(rows: List[Dict], text: str) -> Tuple[Set[int], List[str], str]:
    """Records the question names by their (unique, distinctive) name.

    "When is the Laboratory chemicals - COSHH due for review?" names one record. A name shared by
    several records ("Annual service") is a kind, not a reference, and so is a single plain word
    ("Occupant"): neither is used.
    """
    found: Set[int] = set()
    named: List[str] = []
    counts = Counter(_value(r, "label").lower() for r in rows)
    ranked = sorted(
        (i for i, r in enumerate(rows) if len(_value(r, "label")) >= 8),
        key=lambda i: -len(_value(rows[i], "label")),
    )
    for i in ranked:
        label = _value(rows[i], "label")
        if counts[label.lower()] != 1 or label == _value(rows[i], "recordId"):
            continue
        if not (re.search(r"\s", label) or re.search(r"\d", label)):
            continue
        match = _flex_label(label).search(text)
        if match:
            found.add(i)
            named.append(_ident(rows[i]))
            text = _blank_span(text, match.span())
    return found, named, text


def _members(cell: str) -> List[str]:
    """A cell as the values it holds: the whole, and its comma-joined parts (a record with its
    own authority as well as the register's holds two)."""
    parts = [p.strip() for p in cell.split(", ") if p.strip()]
    return [cell] + parts if len(parts) > 1 else [cell]


def _facets(
    rows: List[Dict],
    columns: Sequence[str],
    text: str,
    aliases: Dict[str, Tuple[str, ...]],
    header: Dict[str, Tuple[str, ...]],
) -> Tuple[List[Tuple[str, List[str], Set[int]]], str]:
    """Facet phrases: a column's own word followed by one of its values.

    "with weekday Friday", "cost centre ABW-MECH", "circuit C2-PUBLIC", "on floor 4", "grade C":
    exactly how a person (or a table header) states a facet, and the only way a value like ``C``
    or ``C2-PUBLIC`` — too short, or not made of words — can be recognised at all.
    """
    prov = rf.provenance_fields(rows)
    out: List[Tuple[str, List[str], Set[int]]] = []
    for col in columns:
        if col in (STATUS, "record", "label", "comment", "recordId"):
            continue
        if col in prov and not rf.carries_per_record_content(rows, col):
            continue
        values = sorted(
            {m for r in rows for m in _members(_value(r, col)) if m}, key=len, reverse=True
        )
        if not values or len(values) > 400:
            continue
        words = _col_words(col, header)
        names = [r"\s+".join(re.escape(w) for w in words)] if words else []
        if header.get(col):  # the document's own header, whole: "document kind O&M manual"
            names.insert(0, r"\s+".join(re.escape(w) for w in header[col]))
        for w in words:
            if len(w) >= 4:
                names.append(re.escape(w))
            for alias in aliases.get(w, ()):
                names.append(re.escape(alias))
        if not names:
            continue
        lead = r"(?<![\w])(?:" + "|".join(names) + r")\s+(?:of\s+|is\s+|=\s*|the\s+)?[\"'‘“]?"
        matched: List[str] = []
        for value in values:
            rx = re.compile(lead + re.escape(value) + r"[\"'’”]?(?![\w-])", re.IGNORECASE)
            match = rx.search(text)
            if match:
                matched.append(value)
                text = _blank_span(text, match.span())
        if matched:
            idx = {i for i, r in enumerate(rows) if set(_members(_value(r, col))) & set(matched)}
            out.append((col, matched, idx))
    return out, text


def _criteria(
    rows: List[Dict],
    columns: Sequence[str],
    text: str,
    vocab: Vocabulary,
    header: Dict[str, Tuple[str, ...]],
) -> Tuple[List[Tuple[str, List[str], Set[int]]], str]:
    """ "With power, good Wi-Fi and a low risk of noise": each phrase is a condition on a column.

    The words a person uses for a level ("good", "low risk of") and the recorded values that
    satisfy them are declared in the vocabulary, and only values the register actually holds are
    used: a criterion whose column or values are absent here is not applied (and its words stay
    unplaced, so the question falls back to the narration).
    """
    out: List[Tuple[str, List[str], Set[int]]] = []
    content = rf._content_columns(rows, list(columns))
    for crit in vocab.criteria:
        want = stem(crit.column)
        col = next(
            (
                c
                for c in sorted(content)
                if any(
                    stem(w).startswith(want) or want.startswith(stem(w))
                    for w in _col_words(c, header)
                    if len(w) >= 3
                )
            ),
            None,
        )
        if col is None:
            continue
        present = sorted(
            {
                _value(r, col)
                for r in rows
                if _value(r, col) and normalise_value(_value(r, col)) in crit.accepts
            }
        )
        if not present:
            continue
        for pattern in crit.patterns:
            match = pattern.search(text)
            if match:
                text = _blank_span(text, match.span())
                idx = {i for i, r in enumerate(rows) if _value(r, col) in present}
                out.append((col, present, idx))
                break
    return out, text


_NEGATION_RE = re.compile(
    r"\b(?:(?:have|has|having|with)\s+no|without(?:\s+an?|\s+any)?|lacks?|lacking|missing)\b\s*",
    re.IGNORECASE,
)
_FIELD_TAIL_RE = re.compile(
    r"\s*(?:recorded|listed|given|specified|on record|on file|in the register)\s*\??\s*$",
    re.IGNORECASE,
)


def _blank_columns(
    field_text: str,
    rows: List[Dict],
    columns: Sequence[str],
    vocab: Vocabulary,
    header: Dict[str, Tuple[str, ...]],
) -> List[str]:
    """The column(s) a "no <field>" phrase names. Empty when it names none of them.

    The register-wide owner stamp is never one: every record carries it, so it can neither lack
    nor prove a record's own owner.
    """
    content = rf._content_columns(rows, list(columns))
    for concept in vocab.concepts_in(field_text):
        if concept.name == "owner":
            return vocab.columns_for(concept, content)
    words = [
        stem(w)
        for w in words_of(field_text)
        if len(w) >= 3 and stem(w) not in vocab.generic_nouns and w not in ("the", "any", "for")
    ]
    if not words:
        return []
    best: List[Tuple[int, str]] = []
    for col in content:
        col_words = [stem(w) for w in _col_words(col, header)]

        def _hit(word: str) -> bool:
            return any(
                cw.startswith(word) or word.startswith(cw) for cw in col_words if len(cw) >= 3
            )

        if all(_hit(w) for w in words):
            best.append((abs(len(col_words) - len(words)), col))
    if not best:
        return []
    top = min(d for d, _c in best)
    return sorted(c for d, c in best if d == top)[:2]


@dataclass
class Resolution:
    """Everything the question named, matched to the rows — and what it could not match."""

    rows: List[Dict]
    #: records satisfying every condition (status included)
    selected: List[int] = field(default_factory=list)
    #: records satisfying every condition EXCEPT the status one
    scope: List[int] = field(default_factory=list)
    filters: List[str] = field(default_factory=list)
    other_filters: List[str] = field(default_factory=list)
    fields: Dict[str, List[str]] = field(default_factory=dict)
    concepts: List[Concept] = field(default_factory=list)
    missing: List[Concept] = field(default_factory=list)
    status_groups: List[StatusGroup] = field(default_factory=list)
    status_values: List[str] = field(default_factory=list)
    overdue: Optional[OverdueInfo] = None
    unresolved: List[str] = field(default_factory=list)
    conflict: bool = False
    #: True when the question is pinned by a status, a recorded value or a field it asks for —
    #: not merely by a word found somewhere in the text of some records.
    structured: bool = False
    #: columns the question names outright ("for review"), shown beside each record
    named: List[str] = field(default_factory=list)
    #: the question asks for the ABSENCE of something ("no owner", "not defective")
    negated: bool = False
    #: the "mentioning ..." conditions among ``other_filters`` (words found only in record text)
    text_filters: List[str] = field(default_factory=list)
    #: stamp column -> the value every record carries (the register's own owner)
    shared: Dict[str, str] = field(default_factory=dict)
    #: status-group name -> the recorded status values it matched in this register
    group_hits: Dict[str, List[str]] = field(default_factory=dict)
    #: stems of asked status words that no recorded status matched (a meaning, not a filter)
    unplaced: Set[str] = field(default_factory=set)
    #: the question with its politeness taken off
    prep: Optional["Prepared"] = None
    #: columns a "which have no X" question looks for a blank in, and X in the asker's words
    blank_cols: List[str] = field(default_factory=list)
    blank_label: str = ""
    #: the two readings of "no X": the cell is empty, and the cell SAYS there is none
    blank_empty: List[int] = field(default_factory=list)
    blank_says_none: List[int] = field(default_factory=list)
    #: properties the question named that this register does not record, in the asker's words
    unanswered: List[str] = field(default_factory=list)
    #: words the register's own text uses that this could not place — a clause not understood
    unplaced_text: List[str] = field(default_factory=list)
    #: "what is the status of X": the recorded state is the field asked for
    asks_status: bool = False
    #: identifiers or names of the records the question points at
    record_ids: List[str] = field(default_factory=list)
    #: columns a "with A, B and C" question filtered on, shown beside each record
    criteria_cols: List[str] = field(default_factory=list)
    #: the column a "which rooms have …" question groups by, and the asker's word for it
    group_col: str = ""
    group_word: str = ""
    #: phrases the register was NOT narrowed by, stated in the answer ("this week")
    unfiltered: List[str] = field(default_factory=list)

    def chosen(self) -> List[Dict]:
        return [self.rows[i] for i in self.selected]

    def pinned(self) -> bool:
        """Was the answer's scope fixed by something the register RECORDS?

        A recorded state, a value of one of its columns, a record it names, a condition on a
        level, or a field the question asks to see. A word that merely appears in the text of
        some rows is not enough: in a question naming five properties, one incidental word hit
        would otherwise pick an arbitrary handful of records and present them as the answer.
        """
        structured_filters = [f for f in self.other_filters if f not in self.text_filters]
        return bool(
            structured_filters
            or self.status_values
            or self.status_groups
            or self.criteria_cols
            or self.record_ids
            or self.fields
            or self.group_col
            or self.blank_cols
        )

    def dropped_named(self) -> List[str]:
        """Columns the question named that no line of the answer would show.

        Beside a state question a named field is not displayed ("overdue for maintenance" names
        a maintenance-tag column nobody asked to see), so when it is NOT one the answer already
        uses ("cannot be evidenced" names an evidence column) part of the question is unanswered.
        """
        if not self.status_groups:
            return []
        used = set(self.overdue.columns if self.overdue else [])
        used |= {c for cols in self.fields.values() for c in cols}
        return [c for c in self.named if c not in used]


def _is_numeric_column(rows: List[Dict], col: str) -> bool:
    values = [_value(r, col) for r in rows if _value(r, col)]
    return bool(values) and all(re.fullmatch(r"-?\d+(?:\.\d+)?", v) for v in values)


def _boolean_column(rows: List[Dict], col: str) -> bool:
    values = {_value(r, col).lower() for r in rows if _value(r, col)}
    return bool(values) and values <= {"true", "false"}


def resolve(
    rows: List[Dict],
    question: str,
    register_label: str = "",
    today: Optional[date] = None,
    vocab: Optional[Vocabulary] = None,
    register_terms: Sequence[str] = (),
) -> Resolution:
    """Match every content word of ``question`` to something in ``rows``."""
    vocab = vocab or get_vocabulary()
    res = Resolution(rows=list(rows or []))
    if not res.rows:
        return res
    prep = prepare(question)
    res.prep = prep
    n = len(res.rows)
    columns = _all_columns(res.rows)
    content = rf._content_columns(res.rows, columns)
    header = _headers_for(res.rows)
    work = prep.core
    other_sets: List[Set[int]] = []
    blank_idx: Optional[Set[int]] = None

    # 0a. a record the question names by identifier ("EV-009")
    named_rows, named_ids, work = _ids_named(res.rows, work)

    # 0b. facet phrases ("cost centre ABW-MECH", "on floor 4", "grade C") come BEFORE names, so
    # "category Occupant" is a facet and not a reference to a record called Occupant
    facet_cols: Set[str] = set()
    facets, work = _facets(res.rows, columns, work, vocab.column_aliases, header)
    for col, matched, idx in facets:
        facet_cols.add(col)
        if len(idx) < n:
            other_sets.append(idx)
            res.other_filters.append(f"{_label(col)}: {_join(sorted(matched), 'or')}")
            res.structured = True

    # 0b''. conditions on a level: "power", "good Wi-Fi", "a low risk of noise"
    criteria, work = _criteria(res.rows, columns, work, vocab, header)
    for col, matched, idx in criteria:
        facet_cols.add(col)
        res.criteria_cols.append(col)
        other_sets.append(idx)
        res.other_filters.append(f"{_label(col)}: {_join(sorted(matched), 'or')}")
        res.structured = True

    # 0b'. or by name ("the Laboratory chemicals - COSHH")
    if not named_rows:
        named_rows, named_ids, work = _labels_named(res.rows, work)
    if named_rows:
        other_sets.append(named_rows)
        res.other_filters.append("record: " + _join(named_ids, "or"))
        res.record_ids = named_ids
        res.structured = True

    # 0c. "which have no X recorded": the subject is analysed, the field is a blank to find
    negated = False
    neg = _NEGATION_RE.search(work)
    if neg:
        field_text = _FIELD_TAIL_RE.sub("", work[neg.end() :]).strip(" ?.!")
        blank_cols = _blank_columns(field_text, res.rows, columns, vocab, header)
        if blank_cols:
            res.blank_cols = blank_cols
            res.blank_label = field_text
            # TWO READINGS OF "HAVE NO Y", and a register can answer either one.
            #
            # "Which departments have no out-of-hours route?" was answered "every one of them has
            # it": the column is filled on all 20 records — and eight of those values read "No
            # cover, next working day", which is the register saying there is no route. An empty
            # cell and a value that says none are both "no Y", so both are collected and the
            # answer says which it found.
            res.blank_empty = [
                i for i, r in enumerate(res.rows) if all(not _value(r, c) for c in blank_cols)
            ]
            res.blank_says_none = [
                i
                for i, r in enumerate(res.rows)
                if i not in res.blank_empty
                and any(vocab.value_says_none(_value(r, c)) for c in blank_cols)
            ]
            blank_idx = set(res.blank_empty) | set(res.blank_says_none)
            res.other_filters.append(f"no {field_text} recorded")
            res.structured = True
            work = work[: neg.start()]
        else:
            negated = True
    else:
        negated = bool(
            re.search(r"\b(?:not|non|no|without|except|excluding)\b|n't\b", work.lower())
        )
    res.negated = negated

    low = work.lower()
    qstems = vocab.question_stems(work)
    consumed: Set[str] = set()
    # "Which rooms have teaching sessions?" asks about the GROUPS, so the word naming them is
    # answered by the grouping below rather than searched for among the records.
    group_words = grouping_words(work, vocab)
    consumed |= {stem(w) for w in group_words}
    if group_words:
        # A distribution over the whole register is a different thing from one over a week,
        # and the answer says which it is rather than filtering on a date it cannot read.
        res.unfiltered = [m.group(0) for m in _PERIOD_RE.finditer(work)]
        consumed |= {stem(w) for phrase in res.unfiltered for w in words_of(phrase)}

    # 1. the recorded state the question asks for ("defective", "open", "overdue")
    recorded = sorted({_value(r, STATUS) for r in res.rows if _value(r, STATUS)})
    selected_values: Set[str] = set()
    group_stems: Set[str] = set()
    for group in vocab.status_groups_in(work):
        hits = [v for v in recorded if group.matches_recorded(v)]
        if hits:
            selected_values.update(hits)
            res.group_hits[group.name] = hits
            group_stems |= group.consumed_stems(low)
            res.status_groups.append(group)
        elif group.name == "overdue":
            group_stems |= group.consumed_stems(low)
            res.group_hits[group.name] = []
            res.status_groups.append(group)
        else:
            res.unplaced |= group.consumed_stems(low)
    consumed |= group_stems

    # 2. the fields the question asks for ("who owns" -> the owner column)
    concept_stems: Set[str] = set()
    party_asked = asks_for_a_party(work)
    for concept in vocab.concepts_in(work):
        if concept.triggers(low, qstems) <= group_stems:
            continue  # "expired" is a recorded STATE here, not a request for an expiry date
        if concept.shape == "who" and not party_asked:
            continue  # "owner-confirmed", "the responsible owner": the word, not the ask
        cols = vocab.columns_for(concept, content)
        cols += [c for c in concept.stamps if c in columns and c not in cols]
        concept_stems |= concept.consumed_stems(low)
        if cols:
            res.fields[concept.name] = cols
            res.concepts.append(concept)
        else:
            res.missing.append(concept)
    consumed |= concept_stems

    # 3. a status named outright: "void", "quarantined", "scheduled" ("due review" is not one
    # when "due" was the concept the question asked for)
    for value in recorded:
        parts = [w for w in words_of(value) if len(w) >= 3]
        if (
            value not in selected_values
            and parts
            and all(stem(w) in qstems and stem(w) not in concept_stems for w in parts)
        ):
            selected_values.add(value)
            consumed |= {stem(w) for w in parts}
    res.status_values = sorted(selected_values)
    status_idx: Optional[Set[int]] = None
    if res.status_groups or selected_values:
        consumed |= vocab.status_words  # "with the status X": the word for the column itself
        status_idx = {i for i, r in enumerate(res.rows) if _value(r, STATUS) in selected_values}
        computed_note = ""
        # Overdue is COMPUTED from dates only when the register records no state of that name
        # ("expired", "lapsed" are states it records; "overdue" is worked out).
        recorded_hits = [v for vs in res.group_hits.values() for v in vs]
        if any(g.name == "overdue" for g in res.status_groups) and (
            not res.group_hits.get("overdue")
            or any(normalise_value(v).startswith("overdue") for v in recorded_hits)
        ):
            res.overdue = overdue_info(res.rows, columns, today)
            status_idx |= set(res.overdue.recorded) | set(res.overdue.computed)
            computed_note = " or past its due date" if res.overdue.computed else ""
        names = [normalise_value(v) for v in res.status_values] or ["overdue"]
        res.filters.append("recorded status: " + _join(names, "or") + computed_note)
        res.structured = True

    if res.status_groups or any(c.shape == "when" for c in res.concepts):
        consumed |= vocab.topic_words  # "overdue for maintenance": why it is due, not a filter
    qterms = rf._question_terms(work, "")
    every = [
        t for t, parent in qterms if parent is None and stem(t.replace("-", "")) not in consumed
    ]
    hyphen_parts: Dict[str, List[str]] = {}
    for t, parent in qterms:
        if parent is not None:
            hyphen_parts.setdefault(parent, []).append(t)
    terms = list(every)
    asked_numbers = _numbers_in(work)

    # 4. a recorded VALUE the question names ("refuge points" -> kind = refuge point). The
    # register's own name is NOT stripped here: "evacuation chairs" is a kind of record in the
    # evacuation register, and only the whole value can say so.
    skip_cols = {c for cols in res.fields.values() for c in cols} | facet_cols
    for col in content:
        if col in skip_cols or _is_numeric_column(res.rows, col) or _boolean_column(res.rows, col):
            continue
        counts: Dict[str, int] = {}
        for r in res.rows:
            v = _value(r, col)
            if v:
                counts[v] = counts.get(v, 0) + 1
        if not 2 <= len(counts) <= rf.MAX_KIND_VALUES:
            continue
        available: Set[str] = set()
        for term in terms:
            available |= vocab.value_words_for(term)
            for part in hyphen_parts.get(term, []):  # "as-built" carries "built"
                available |= vocab.value_words_for(part)
        matched = []
        for value in counts:
            wanted = [stem(x) for x in words_of(value) if len(x) >= 3]
            # a value with a number in it ("Room 5.16") is named only when the number is
            if (
                wanted
                and all(w in available for w in wanted)
                and _numbers_in(value) <= asked_numbers
            ):
                matched.append(value)
        if not matched:
            continue
        matched_stems = {stem(x) for v in matched for x in words_of(v)}
        column_stems = {stem(w) for w in _col_words(col, header)}
        terms = [
            t
            for t in terms
            if not (vocab.value_words_for(t) & matched_stems)
            and not any(vocab.value_words_for(p) & matched_stems for p in hyphen_parts.get(t, []))
            and stem(t) not in column_stems  # "of category injury": the column's own word
        ]
        if sum(counts[v] for v in matched) == n:
            continue  # every record has it: named, but it distinguishes none of them
        other_sets.append({i for i, r in enumerate(res.rows) if _value(r, col) in matched})
        res.other_filters.append(f"{_label(col)}: {_join(sorted(matched), 'or')}")
        res.structured = True

    # 5. a yes/no column the question names ("bookable rooms" -> bookable = yes)
    for term in list(terms):
        for col in content:
            if _boolean_column(res.rows, col) and stem(term) in {
                stem(w) for w in _col_words(col, header)
            }:
                if negated:
                    break
                other_sets.append(
                    {i for i, r in enumerate(res.rows) if _value(r, col).lower() == "true"}
                )
                res.other_filters.append(f"{_label(col)}: yes")
                res.structured = True
                terms.remove(term)
                break

    # 6. words that name no particular record: the register's own name, "tasks", "items"
    label_words = [
        w for text in [register_label] + list(register_terms) for w in words_of(text) if len(w) >= 3
    ]
    terms = [
        t
        for t in terms
        if stem(t) not in vocab.generic_nouns
        and not any(
            w == t.replace("-", "")
            or stem(w) == stem(t.replace("-", ""))  # "cost lines" names the "cost line" register
            or (len(stem(t)) >= 4 and stem(w).endswith(stem(t)))  # "spaces" -> "workspace"
            or rf._shared_prefix(w, t.replace("-", "")) >= 5
            for w in label_words
        )
    ]

    # 6b. "what is the status of X": the recorded state is what is asked for
    for term in list(terms):
        if stem(term) in vocab.status_words:
            res.asks_status = True
            terms.remove(term)

    # 7. a word that names a FIELD ("for review" -> the review-due column, "rooms" -> the room
    # column): the question asks about that field, so it is shown rather than searched for.
    for term in list(terms):
        named = [
            c
            for c in content
            if c not in skip_cols
            and (
                stem(term) in {stem(w) for w in _col_words(c, header) if len(w) >= 3}
                or rf._term_matches_column(term, c)
            )
        ]
        if named:
            res.named += [c for c in named if c not in res.named]
            terms.remove(term)

    # 8. a word found in the recorded text of some records ("the lift" -> the rows that mention
    # one). Only columns that NAME a record are searched: a word inside a free-text state or
    # note ("tested and working") is not what a record IS, and a negation reads as its opposite.
    searchable = [c for c in content if vocab.names_what_a_record_is(c)] + (
        ["label"] if "label" in columns else []
    )
    text_sets: List[Set[int]] = []
    text_phrases: List[str] = []
    # A NUMBERED PLACE THE QUESTION NAMES ("bookings in Room 5.15"). It was silently dropped: the
    # location column's values read "Room 5.15 — Seminar / Conference Room", which the whole-value
    # match in step 4 cannot take (the description words are not in the question), and a number is
    # not a word term. "How many bookings in Room 5.15 are confirmed?" was answered 11 — every
    # confirmed booking in the register — where the room holds 3. A wrong count with no sign that
    # a condition had been ignored is the worst outcome available, so a dotted number the question
    # gives is now either a filter on the records that carry it or an unresolved word.
    already = " ".join(res.other_filters + res.filters)
    for number in sorted(n for n in asked_numbers if "." in n and n not in already):
        pattern = re.compile(r"(?<![\d.])" + re.escape(number) + r"(?![\d])")
        hit = {
            i
            for i, r in enumerate(res.rows)
            if any(pattern.search(_value(r, c)) for c in searchable)
        }
        if not hit:
            res.unresolved.append(number)
        elif len(hit) < n:
            other_sets.append(hit)
            res.other_filters.append(f"in {number}")
            res.structured = True
    for term in terms:
        found = _text_hits(res.rows, searchable, term) if stem(term) not in res.unplaced else set()
        if not found:
            res.unresolved.append(term)
        elif len(found) < n:
            text_sets.append(found)
            text_phrases.append(f'mentioning "{term}"')
        # a word found on every record distinguishes none of them and is not a finding

    if res.fields or res.named or res.asks_status:
        res.structured = True
    # A GROUPING ONLY WHEN NOTHING ELSE WAS ASKED OF THE RECORDS. "Which rooms have teaching
    # sessions?" asks which rooms appear at all; "Which rooms have good Wi-Fi and are quiet?"
    # names conditions on the records themselves and is answered by filtering them, not by
    # counting rooms. Anything that filtered — a criterion, a state, a recorded value — settles
    # which of the two it is.
    if group_words and not res.blank_cols and not (res.other_filters or res.status_groups):
        res.group_col = grouping_column(content, group_words, header) or ""
        if res.group_col:
            res.group_word = grouping_label(work)
            res.structured = True
    for concept in res.concepts:
        for col in concept.stamps:
            shared = _shared_member(res.rows, col)
            if shared:
                res.shared[col] = shared
    # WHAT THE QUESTION NAMED THAT THIS REGISTER DOES NOT RECORD (2D-06 wave 4). A stakeholder
    # question routinely names four or five properties at once, and the answer either took one of
    # them or declined the whole: "was each assurance activity performed by people with the
    # required competence, independence, authority and access?" was declined over a register that
    # records the responsible role and the dates. What is held is answered; what is not is named
    # once, in the asker's own words — the qualifiers among them ("required", "current") are
    # dropped, because no register records those.
    if not vocab.concepts:
        # With no vocabulary nothing can be classified, so nothing is claimed to be missing and
        # every unplaced word blocks: the lane behaves exactly as it did before the table existed.
        res.unplaced_text = list(res.unresolved)
    else:
        candidates = [
            w
            for w in res.unresolved
            if len(w) >= 4 and stem(w) not in vocab.qualifier_words and w not in group_words
        ]
        # A WORD THE REGISTER'S OWN TEXT USES IS NOT AN ABSENCE. "Which refuge points have a
        # WORKING communication unit?" — both words sit in the recorded state of every provision,
        # and naming them as unrecorded would be the false absence this whole row exists to stop.
        # They are a clause that was understood by nobody, so the question keeps its narration.
        res.unplaced_text = [w for w in candidates if rf._term_in_text(res.rows, columns, w)]
        res.unanswered = [c.plain for c in res.missing] + [
            w for w in candidates if w not in res.unplaced_text
        ]
    # A WORD FOUND IN SOME ROWS NARROWS NOTHING IN A QUESTION THE REGISTER ONLY HALF ANSWERS.
    # "…performed by people with the required competence, independence, authority and access"
    # happens to contain "required" and "access", and both appear in a few rows; letting them
    # filter would hand back an arbitrary handful as though they were the answer.
    if not (res.unanswered and res.pinned()):
        other_sets += text_sets
        res.other_filters += text_phrases
        res.text_filters += text_phrases
    scope = set.intersection(*other_sets) if other_sets else set(range(n))
    # An empty intersection is a fact when every condition was matched to values the register
    # holds; when one came from free text it is likelier that the word was read wrongly.
    res.conflict = bool(other_sets) and not scope and bool(res.text_filters)
    res.scope = sorted(scope)
    chosen = set(scope)
    if status_idx is not None:
        chosen &= status_idx
    if blank_idx is not None:
        chosen &= blank_idx  # an empty result is the finding: no record lacks it
    res.selected = sorted(chosen)
    res.filters = res.other_filters + res.filters
    return res


def _text_hits(rows: List[Dict], columns: Sequence[str], term: str) -> Set[int]:
    """Indexes of the records whose recorded text carries this word (singular or plural)."""
    base = term.replace("-", " ")
    prefix = base if " " in base else stem(base)
    pattern = re.compile(r"\b" + re.escape(prefix[:8]), re.IGNORECASE)
    return {i for i, r in enumerate(rows) if any(pattern.search(_value(r, c)) for c in columns)}


def _shared_member(rows: List[Dict], col: str) -> str:
    """The value a stamp column carries on EVERY record: the register's own, not the record's.

    The lifter stamps each record with the document's owner, and a register that also has an
    owner column of its own maps that onto the same predicate, so a record with its own owner
    holds two values ("Estates, Facilities" once joined). The value common to all records is the
    register's; what is left over on a record is that record's own.
    """
    members = [[m.strip() for m in _value(r, col).split(", ") if m.strip()] for r in rows]
    if not members or not all(members) or not any(len(m) > 1 for m in members):
        return ""
    common = set(members[0]).intersection(*map(set, members[1:]))
    return next(iter(common)) if len(common) == 1 else ""


def _cell(row: Dict, col: str, shared: Dict[str, str]) -> str:
    """A cell's value, with the register-wide member set aside when the record has its own."""
    value = _value(row, col)
    keep = shared.get(col)
    if keep and ", " in value:
        members = [m.strip() for m in value.split(", ") if m.strip()]
        rest = [m for m in members if m != keep]
        if keep in members and rest:
            return ", ".join(rest)
    return value


# --------------------------------------------------------------------------------------
# rendering
# --------------------------------------------------------------------------------------


def _field_columns(res: Resolution, skip: Sequence[str] = ()) -> List[str]:
    """The columns the question asks for: a concept's, then any it names outright."""
    cols: List[str] = []
    for concept in res.concepts:
        cols += [c for c in res.fields.get(concept.name, []) if c not in cols and c not in skip]
    if res.status_groups:
        return cols  # asked about a state: a word that merely names a field is not shown
    return cols + [c for c in res.named if c not in cols and c not in skip]


def _row_line(
    row: Dict,
    cols: Sequence[str],
    show_status: bool,
    extra: Sequence[str] = (),
    shared: Optional[Dict[str, str]] = None,
    describe: Sequence[str] = (),
) -> str:
    ident, name = _ident(row), _value(row, "label")
    head = f"**{ident}**" + (f" — {name}" if name and name != ident else "")
    bits = []
    if describe and (not name or name == ident):
        bits += [f"{_label(c)}: {_value(row, c)}" for c in describe if _value(row, c)]
    for col in cols:
        cell = _cell(row, col, shared or {})
        if cell:
            bits.append(f"{_label(col)}: {_show(cell)}")
    if show_status and _value(row, STATUS):
        bits.append(f"status: {normalise_value(_value(row, STATUS))}")
    bits += list(extra)
    return "- " + head + (" — " + "; ".join(bits) if bits else "")


def _folded_lines(rows: List[Dict], cols: Sequence[str], shared: Dict[str, str]) -> List[str]:
    """Rows grouped by the value(s) they share, when there are too many to list one by one.

    Empty when grouping would not shorten the list (every record has its own value): a fold of
    one-record groups is the same list, harder to read.
    """
    groups: Dict[str, List[str]] = {}
    for r in rows:
        parts = [(c, _cell(r, c, shared)) for c in cols]
        key = (
            "; ".join((f"{_label(c)}: {v}" if len(cols) > 1 else v) for c, v in parts if v)
            or "(not recorded)"
        )
        groups.setdefault(key, []).append(_ident(r))
    if len(groups) * 2 > len(rows):
        return []
    return [
        f"- **{key}** — {len(ids)}: {', '.join(sorted(ids)[:MAX_LISTED])}"
        for key, ids in sorted(groups.items(), key=lambda kv: (-len(kv[1]), kv[0]))
    ]


_DESCRIBE_FIRST = (
    "kind",
    "type",
    "name",
    "title",
    "location",
    "scope",
    "asset",
    "subject",
    "category",
)


def _descriptor_columns(res: Resolution, skip: Sequence[str]) -> List[str]:
    """Up to two short text columns that say what a record IS, for records with no name.

    A permit register's records are named by their reference, which tells a reader nothing; its
    kind and location do. Picked by the data (short, varied, not a date) and then by the words
    in the column's name.
    """
    picked = []
    for col in rf._content_columns(res.rows, _all_columns(res.rows)):
        values = [_value(r, col) for r in res.rows if _value(r, col)]
        if (
            col in skip
            or col == "comment"
            or len(set(values)) < 2
            or any(len(v) > 60 or _as_date(v) for v in values)
            or _is_numeric_column(res.rows, col)
            or _boolean_column(res.rows, col)
        ):
            continue
        words = column_words(col)
        rank = min((_DESCRIBE_FIRST.index(w) for w in words if w in _DESCRIBE_FIRST), default=99)
        picked.append((rank, col))
    return [c for _rank, c in sorted(picked)[:2]]


def _register_phrase(register_label: str) -> str:
    label = re.sub(r"\s+registers?$", "", (register_label or "").strip(), flags=re.IGNORECASE)
    return f"the {label} register" if label else "this register"


def _lead(res: Resolution, register_label: str, n: int, total: int, breakdown: str = "") -> str:
    where = _register_phrase(register_label)
    if not res.filters:
        return f"All {total} records in {where}:"
    phrase = "; ".join(res.filters) + breakdown
    if n == 0:
        return f"**None of the {total} records in {where} match** ({phrase})."
    verb = "matches" if n == 1 else "match"
    return f"**{n} of the {total} records in {where} {verb}** ({phrase}):"


def _overdue_lines(res: Resolution, register_label: str, today: Optional[date]) -> List[str]:
    """The overdue answer, in the terms the register can support."""
    info = res.overdue
    assert info is not None
    rows = res.rows
    scope = set(res.scope)
    register = _register_phrase(register_label)
    if res.other_filters:
        of = f"the {len(scope)} records in {register} that match ({'; '.join(res.other_filters)})"
    else:
        of = f"the {len(rows)} records in {register}"
    as_at = f" (as at {_fmt_date(today)})" if today else ""
    columns = _all_columns(rows)
    if info.basis == "none":
        # A word found only in record text ("maintenance") did not narrow what the register
        # records about due dates, so the statement is about the whole register.
        whole = not res.other_filters or len(res.text_filters) == len(res.other_filters)
        pool = range(len(rows)) if whole else sorted(scope)
        which = "which of its records are overdue" if whole else "which of those are overdue"
        lines = [
            f"**{_sentence_case(register)} records no due date and no 'overdue' status**, so "
            f"{which} cannot be worked out from it."
        ]
        open_rows = [rows[i] for i in pool if not _is_closed(rows[i], columns)]
        if open_rows and len(open_rows) < len(pool):
            lines.append(
                f"It does record {len(open_rows)} of {len(pool)} as not complete "
                f"({_join(sorted(_ident(r) for r in open_rows)[:MAX_LISTED])}); "
                "that is not the same thing as overdue."
            )
        return lines
    recorded = [i for i in sorted(info.recorded) if i in scope]
    computed = [i for i in sorted(info.computed) if i in scope]
    hits = recorded + computed
    interval = info.basis == "interval"
    what = "past their " + _label(info.columns[-1]).replace(" days", "") if interval else "overdue"
    if not hits:
        return [
            f"**None of {of} is {what.replace('their', 'its')}**{as_at}: none is recorded as "
            f"overdue and none is past its {'interval' if interval else 'due date'}."
        ]
    lines = [f"**{len(hits)} of {of} {'is' if len(hits) == 1 else 'are'} {what}**{as_at}:", ""]
    extra_cols = _field_columns(res, skip=info.columns)
    for i in hits:
        bits = []
        if i in info.due:
            bits.append(f"due {_fmt_date(info.due[i])}")
        if i in recorded:
            bits.append("recorded as overdue")
        elif not interval:
            bits.append("past its date, not recorded as overdue")
        lines.append(_row_line(rows[i], extra_cols, False, bits, res.shared))
    if interval:
        lines += [
            "",
            f"The due dates are worked out by the system as {_label(info.columns[0])} plus "
            f"{_label(info.columns[1]).replace(' days', '')} in days; the register records "
            "inspection visits, not a maintenance "
            "due date.",
        ]
    return lines


def _who(row: Dict) -> str:
    name = _value(row, "label")
    return f"**{_ident(row)}**" + (f" ({name})" if name not in ("", _ident(row)) else "")


def _status_note(row: Dict) -> str:
    status = normalise_value(_value(row, STATUS))
    return f", recorded as {status}" if status else ""


def _when_lines(res: Resolution, concept: Concept, today: Optional[date]) -> List[str]:
    """Dates for the chosen records: latest first for "last", soonest first for "next"."""
    cols = res.fields.get(concept.name, [])
    dated: List[Tuple[date, Dict, str]] = []
    for row in res.chosen():
        for col in cols:
            d = _as_date(_value(row, col))
            if d:
                dated.append((d, row, col))
    if res.record_ids and len(res.chosen()) == 1:
        row = res.chosen()[0]
        parts = []
        for col in cols:
            d = _as_date(_value(row, col))
            if d:
                passed = " (already passed)" if today and d < today else ""
                parts.append(f"{_label(col)}: **{_fmt_date(d)}**{passed}")
        if parts:
            return [f"{_who(row)} — " + "; ".join(parts) + _status_note(row) + "."]
        return [f"{_who(row)} has no recorded {concept.plain}."]
    if not dated:
        if not res.chosen():
            return [
                f"**No record matches** ({'; '.join(res.filters) or 'the question'}), so there "
                f"is no {concept.plain} to give."
            ]
        return [f"The {len(res.chosen())} matching records hold no {concept.plain}."]
    latest = concept.pick == "latest"
    key = lambda t: (t[0], _ident(t[1]))  # noqa: E731
    if latest:
        dated.sort(key=key, reverse=True)
    else:
        upcoming = [t for t in dated if not today or t[0] >= today]
        past = [t for t in dated if today and t[0] < today]
        dated = sorted(upcoming, key=key) + sorted(past, key=key)
    d0, r0, c0 = dated[0]
    if latest:
        lead = f"The most recent {_label(c0)} on record is **{_fmt_date(d0)}** — {_who(r0)}."
    elif today and d0 < today and len(dated) == 1:
        lead = (
            f"The {_label(c0)} for {_who(r0)} was **{_fmt_date(d0)}** and has already passed"
            f"{_status_note(r0)}."
        )
    elif today and d0 < today:
        lead = (
            f"All {len(dated)} recorded {_label(c0)} dates have already passed; the earliest was "
            f"**{_fmt_date(d0)}** — {_who(r0)}{_status_note(r0)}."
        )
    else:
        lead = (
            f"The soonest {_label(c0)} on record is **{_fmt_date(d0)}** — "
            f"{_who(r0)}{_status_note(r0)}."
        )
    lines = [lead]
    if len(dated) > 1:
        lines += ["", "Most recent first:" if latest else "Soonest first:"]
        for d, r, _c in dated[:8]:
            name = _value(r, "label")
            lines.append(
                f"- {_fmt_date(d)} — **{_ident(r)}**" + (f" {name}" if name != _ident(r) else "")
            )
    undated = [r for r in res.chosen() if not any(_as_date(_value(r, c)) for c in cols)]
    if undated:
        lines += [
            "",
            f"{len(undated)} of the selected records have no recorded {_label(cols[0])}: "
            + ", ".join(sorted(_ident(r) for r in undated)[:MAX_LISTED])
            + ".",
        ]
    return lines


def _detail_columns(res: Resolution, already: Sequence[str]) -> List[str]:
    """When a record is picked BY its state, what that state is: a column named state/condition."""
    out = []
    for col in rf._content_columns(res.rows, _all_columns(res.rows)):
        words = column_words(col)
        if col not in already and any(
            w in ("state", "condition", "defect", "finding") for w in words
        ):
            out.append(col)
    return out[:1]


def _blank_lines(res: Resolution, register_label: str) -> List[str]:
    """Records that LACK a field — an empty cell, or a value that says there is none.

    Which reading answered is always stated: "the cell is empty" and "the cell reads 'No cover,
    next working day'" are different facts about a register, and a reader acts on them
    differently.
    """
    rows, total = res.chosen(), len(res.rows)
    where = _register_phrase(register_label)
    scope = len(res.scope)
    of = f"the {total} records in {where}" if scope == total else f"the {scope} matching records"
    empty, says_none = len(res.blank_empty), len(res.blank_says_none)
    if not rows:
        return [
            f"**None of {of} has no {res.blank_label}** — every one records one, and none of "
            f"them records that there is none."
        ]
    if empty and says_none:
        how = f" — {empty} with nothing recorded and {says_none} recording that there is none"
    elif says_none:
        how = " — each recording, in the field itself, that there is none"
    else:
        how = " — the field is empty on each of them"
    lines = [f"**{len(rows)} of {of} have no {res.blank_label}**{how}:", ""]
    describe = _descriptor_columns(res, [])
    shown = res.blank_cols if says_none else []
    lines += [_row_line(r, shown, False, describe=describe) for r in rows[:MAX_LISTED]]
    if len(rows) > MAX_LISTED:
        lines.append(f"- … and {len(rows) - MAX_LISTED} more.")
    others = scope - len(rows)
    if others:
        lines += ["", f"The other {others} record one."]
    return lines


def _record_field_line(res: Resolution, row: Dict, cols: Sequence[str]) -> str:
    """One named record and the field(s) asked of it: "EV-009 (name) — review due: 14 Nov 2026"."""
    bits = []
    for col in cols:
        cell = _cell(row, col, res.shared)
        if cell:
            bits.append(f"{_label(col)}: {_show(cell)}")
    if res.asks_status and _value(row, STATUS):
        bits.append(f"status: {normalise_value(_value(row, STATUS))}")
    return f"{_who(row)} — " + "; ".join(bits) + "." if bits else _who(row)


def _compose(
    res: Resolution,
    register_label: str,
    today: Optional[date],
    shape: str,
    compact: bool = False,
) -> List[str]:
    """The answer lines for a resolved question (``compact``: one line for a long list)."""
    if res.blank_cols:
        return _blank_lines(res, register_label)
    if res.group_col:
        counts = Counter(_value(r, res.group_col) for r in res.chosen())
        return grouping_lines(
            list(counts.items()),
            register_label,
            res.group_word or _label(res.group_col),
            len(res.chosen()),
            list(res.unfiltered) + (list(res.prep.dropped) if res.prep else []),
        )
    if res.overdue is not None:
        others = [g for g in res.status_groups if g.name != "overdue"]
        if not others:
            return _overdue_lines(res, register_label, today)
        # "How many open work orders are there, and which are overdue?" asks two things: each
        # is answered, the count of the open ones first.
        values = {v for g in others for v in res.group_hits.get(g.name, [])}
        part = replace(
            res,
            selected=[i for i in res.scope if _value(res.rows[i], STATUS) in values],
            overdue=None,
            status_groups=others,
            status_values=sorted(values),
            filters=res.other_filters
            + ["recorded status: " + _join([normalise_value(v) for v in sorted(values)], "or")],
        )
        return (
            _compose(part, register_label, today, shape, compact)
            + [""]
            + _overdue_lines(res, register_label, today)
        )
    when = [c for c in res.concepts if c.shape == "when"]
    if when and shape not in ("count", "exists"):
        return _when_lines(res, when[0], today)
    rows = res.chosen()
    cols = _field_columns(res)
    if len(rows) == 1 and res.record_ids and (cols or res.asks_status) and shape != "exists":
        return [_record_field_line(res, rows[0], cols)]
    seen = Counter(normalise_value(_value(r, STATUS)) for r in rows)
    breakdown = (
        " — " + ", ".join(f"{n} {s}" for s, n in sorted(seen.items(), key=lambda kv: -kv[1]))
        if len(res.status_values) > 1 and len(seen) > 1
        else ""
    )
    where = _register_phrase(register_label)
    if shape == "exists":
        phrase = "; ".join(res.filters)
        if not rows:
            return [f"**No** — none of the {len(res.rows)} records in {where} match ({phrase})."]
        verb = "matches" if len(rows) == 1 else "match"
        lead = (
            f"**Yes** — {len(rows)} of the {len(res.rows)} records in {where} {verb} "
            f"({phrase}){breakdown}:"
        )
    elif shape == "count" and not res.filters:
        lead = f"**{len(res.rows)} records** are held in {where}:"
    else:
        lead = _lead(res, register_label, len(rows), len(res.rows), breakdown)
    lines = [lead]
    if not rows:
        return lines
    if shape == "count" and len(rows) > MAX_ANSWER_ROWS:
        return lines[:-1] + [lead.rstrip(":") + "."]  # a count of a big register, not a list
    lines.append("")
    who_cols = [c for k in res.concepts if k.shape == "who" for c in res.fields.get(k.name, [])]
    folded = _folded_lines(rows, who_cols, res.shared) if len(rows) > FOLD_AT else []
    if folded and who_cols and cols == who_cols:
        return lines + folded
    if compact and len(rows) > COMPACT_AT:
        # A list the prompt must carry whole is one line of `id name`, never a cut list.
        return lines[:-1] + ["; ".join(f"{_ident(r)} {_value(r, 'label')}".strip() for r in rows)]
    # A status is worth a word only when the listed records differ in it.
    show_status = len(seen) > 1 or res.asks_status
    detail = _detail_columns(res, cols) if res.status_values else []
    shown = cols + detail + [c for c in res.criteria_cols if c not in cols + detail]
    describe = _descriptor_columns(res, shown)
    floor_col = next(
        (
            c
            for c in rf._content_columns(res.rows, _all_columns(res.rows))
            if rf._is_floor_column(res.rows, c)
        ),
        None,
    )
    if floor_col and len(rows) > FOLD_AT and len(rows) <= MAX_LISTED + 10:
        # a long list of places is read by floor
        if lines and lines[-1] == "":
            lines.pop()
        groups: Dict[str, List[Dict]] = {}
        for row in rows:
            groups.setdefault(_value(row, floor_col), []).append(row)
        for floor_value in sorted(groups, key=lambda v: (len(v), v)):
            lines += ["", f"**Floor {floor_value}** — {len(groups[floor_value])}:"]
            for row in groups[floor_value]:
                lines.append(
                    _row_line(
                        row,
                        [c for c in shown if c != floor_col],
                        show_status,
                        shared=res.shared,
                        describe=describe,
                    )
                )
    else:
        for row in rows[:MAX_LISTED]:
            lines.append(_row_line(row, shown, show_status, shared=res.shared, describe=describe))
        if len(rows) > MAX_LISTED:
            lines.append(f"- … and {len(rows) - MAX_LISTED} more.")
    if res.prep is not None and res.prep.dropped:
        lines += [
            "",
            "The register records no session length, so "
            + _join([f'"{d}"' for d in res.prep.dropped])
            + " is not something it could be filtered on.",
        ]
    return lines + _unanswered_line(res)


def _unanswered_line(res: Resolution) -> List[str]:
    """One closing sentence naming the parts of the question this register does not record.

    The other half of answering a multi-clause question: the rows answer what they hold, and the
    reader is told, once and in their own words, what the register was silent about — instead of
    the whole question being declined because one clause of five was beyond it.
    """
    if not res.unanswered:
        return []
    return [
        "",
        "This register does not record "
        + _join(sorted(set(res.unanswered))[:5])
        + ", so that part of the question is not answered here.",
    ]


# --------------------------------------------------------------------------------------
# what may stand alone as the answer
# --------------------------------------------------------------------------------------

_EXISTS_RE = re.compile(r"^\W*(?:are|is|do|does|did|was|were)\s+(?:there\s+)?any\b", re.IGNORECASE)

# --------------------------------------------------------------------------------------
# "WHICH ROOMS HAVE TEACHING SESSIONS?" — a question about the GROUPS, not about the records.
#
# Measured live 2026-09-19: the question reached this lane, the timetable register holds 675
# sessions with a room on every one, and the answer was "the building's records do not contain
# any information about teaching sessions … the data only lists how many sensors are installed
# in each space". The register is past the hand-over limit and the question names no room to
# scope by, so the lane declined and a generated query answered about something else.
#
# The answer is one line per distinct value with a count, which is an aggregation — so it is
# computed, here or by the graph, and never left to a narration that was handed no rows.
# --------------------------------------------------------------------------------------

_GROUPING_RE = re.compile(
    r"\b(?:which|what)\s+(?:of\s+the\s+)?([a-z]+s)\b[^?]{0,60}?"
    r"\b(?:have|has|hold|holds|contain|contains|are\s+there|is\s+there|with)\b",
    re.IGNORECASE,
)


def grouping_words(question: str, vocab: Optional[Vocabulary] = None) -> Tuple[str, ...]:
    """The words naming the column a "which X have …" question groups by, or ().

    "Which rooms have teaching sessions this week?" -> ("room", "location"): the word the asker
    used, and the column words the vocabulary says it stands for.
    """
    vocab = vocab or get_vocabulary()
    match = _GROUPING_RE.search(prepare(question).core)
    if not match:
        return ()
    word = stem(match.group(1))
    if word in vocab.generic_nouns:
        return ()
    names = {word} | {
        col for col, aliases in vocab.column_aliases.items() if word in {stem(a) for a in aliases}
    }
    return tuple(sorted(names))


def grouping_label(question: str) -> str:
    """The asker's own word for the groups, singular: "Which workspaces have …" -> "workspace"."""
    match = _GROUPING_RE.search(prepare(question).core)
    if not match:
        return ""
    word = match.group(1).lower()
    return word[:-1] if word.endswith("s") and not word.endswith("ss") else word


def unfiltered_periods(question: str) -> List[str]:
    """The period a question names that a register grouping was NOT narrowed by ("this week")."""
    return [m.group(0) for m in _PERIOD_RE.finditer(prepare(question).core)]


def grouping_column(columns: Sequence[str], words: Sequence[str], header=None) -> Optional[str]:
    """The ONE column whose name carries one of these words, or None when it is not exactly one.

    Two candidates is a question this cannot settle — grouping by the wrong column would put
    every record under a heading it does not belong to, which is the failure this replaces.
    """
    header = header or {}
    hits = [
        c
        for c in columns
        if any(stem(w) in {stem(x) for x in _col_words(c, header) if len(x) >= 3} for w in words)
    ]
    return hits[0] if len(hits) == 1 else None


def grouping_lines(
    pairs: Sequence[Tuple[str, int]],
    register_label: str,
    column_label: str,
    total: int,
    unfiltered: Sequence[str] = (),
) -> List[str]:
    """One line per distinct value with its count, largest first — counted, never narrated."""
    named = [(v, n) for v, n in pairs if str(v).strip()]
    where = _register_phrase(register_label)
    if not named:
        return [f"**No {column_label} is recorded** on any of the {total} records in {where}."]
    plural = "" if len(named) == 1 else "s"
    lines = [
        f"**{len(named)} {column_label}{plural}** appear on the {total} records in {where}:",
        "",
    ]
    for value, count in sorted(named, key=lambda pair: (-pair[1], str(pair[0])))[:MAX_LISTED]:
        lines.append(f"- **{value}** — {count}")
    if len(named) > MAX_LISTED:
        lines.append(f"- … and {len(named) - MAX_LISTED} more.")
    if unfiltered:
        lines += [
            "",
            "This counts every record the register holds: "
            + _join([f'"{u}"' for u in unfiltered])
            + " is not something it was narrowed by.",
        ]
    return lines


# --------------------------------------------------------------------------------------
# WHEN IS A QUESTION ASKING FOR AN OWNER? (2D-06 wave 8)
#
# Measured over the recorded runs: of 12 answers that BEGIN "The register records the owner:",
# nine answered a question that never asked for one — "What owner-confirmed changes since the
# last signed handover alter this shift's posts?", "Which reporting periods are not directly
# comparable because contracts, streams … changed?", "Can People Count data be used to redirect
# cleaning crews …?". The vocabulary treats "owner", "ownership", "responsible" as the owner
# concept wherever they appear, so a QUALIFIER ("owner-confirmed", "the responsible owner",
# "producer-responsibility") or a subject noun asked for a party, and the composed answer was the
# register's owner list — a confident, unrelated answer to a different question.
#
# A party is asked for by who / whose / in charge of / responsible or accountable FOR / owner OF /
# owned BY / "their owners". Anything else names the word without asking.
# --------------------------------------------------------------------------------------

_PARTY_ASK_RE = re.compile(
    r"\bwho(?:m|se)?\b|\bin charge\b|\b(?:responsible|accountable)\s+for\b"
    r"|\bown(?:er|ers|ership)\s+of\b|\bowned\s+by\b"
    r"|\b(?:their|its|each|every|the\s+recorded)\s+owners?\b(?!-)"
    r"|\bwhich\s+(?:role|team|person|people|department|party|parties)\b"
    r"|\b(?:people|persons?|staff|personnel)\s+(?:assigned|responsible|named|accountable)\b"
    r"|\bassigned\s+to\b"
    r"|\b(?:performed|carried\s+out|done|completed|signed\s+off|approved|assigned)\s+by\b"
    r"|\b(?:have|has|with|without)\s+(?:an?\s+)?(?:recorded\s+)?owners?\b"
    r"|\b(?:list|show|give|name)\b[^?.]{0,20}\bowners?\b",
    re.IGNORECASE,
)


def asks_for_a_party(question: str) -> bool:
    """Does the question ASK who owns or is responsible, rather than merely contain the word?"""
    return bool(_PARTY_ASK_RE.search(question or ""))


def question_shape(question: str, list_hint: bool = False) -> str:
    """count | exists | list | "" — the questions a lookup can answer outright."""
    prep = prepare(question)
    core = prep.core
    if _NOT_SIMPLE_RE.search(core):
        return ""
    if _COUNT_RE.search(core):
        return "count"
    if _EXISTS_RE.search(core):
        return "exists"
    if _LIST_RE.search(core) or list_hint or prep.list_hint:
        return "list"
    return ""


def _ineligible(res: Resolution, question: str, partial: bool) -> str:
    """Why this question must go to the narration instead, or "" when it may stand alone."""
    prep = res.prep or prepare(question)
    if partial:
        return "the rows are not the whole of one register"
    if prep.reader:
        return "the question is about the reader"
    shape = question_shape(prep.core, prep.list_hint)
    if not shape:
        return "not a who / when / which / how-many lookup"
    if res.negated:
        return "asks for the absence of something, which a lookup does not answer"
    named_numbers = [w for w in res.unresolved if any(ch.isdigit() for ch in w)]
    if named_numbers:
        # "how many bookings in Room 9.99 are confirmed?" must not be answered with every
        # confirmed booking: a place or reference the question names and no record carries is a
        # finding about THAT reference, which the referent gate and the narration say honestly.
        return "a number the question names is in no record: " + ", ".join(named_numbers[:4])
    if res.unplaced_text:
        return "words the register's own records use but this could not place: " + ", ".join(
            res.unplaced_text[:6]
        )
    if res.missing and not (
        res.fields or res.named or res.status_groups or res.blank_cols or res.group_col
    ):
        # Every property the question ASKED FOR is one this register has no field for. Listing
        # its records instead would be padding, not an answer: "who is the contact for the refuge
        # points?" is answered by saying there is no contact field, which the narration does.
        return "the register holds no field for what the question asks: " + ", ".join(
            c.plain for c in res.missing
        )
    if res.unanswered and not res.pinned():
        # Part of the question is beyond this register, and nothing the register HOLDS was
        # singled out — so there is no half to answer, only words that happen to appear in some
        # rows. That is the case to leave alone; when something was pinned, the composition
        # answers what is held and names the rest.
        return "the register holds none of what the question singles out: " + ", ".join(
            res.unanswered[:6]
        )
    if res.conflict:
        return "the conditions named select no record together"
    if not res.structured and shape != "count":
        return "nothing but free-text words to go on"
    if shape != "count" and not res.group_col and len(res.selected) > MAX_ANSWER_ROWS:
        return "too many records to list"
    return _unfit(res, shape)


def _unfit(res: Resolution, shape: str = "") -> str:
    """Why a resolved question is not safe to state as the answer, or "" when it is."""
    if res.group_col:
        return ""  # the answer is the groups, and every record has a place in them
    if not res.filters and shape != "count":
        # "Who owns the building data?" reduces to 'owns': with no record singled out the
        # answer would be a column dumped over the whole register.
        return "no record, kind or state singled out"
    if res.dropped_named():
        return "names a field alongside a state that the answer would not show"
    chosen = res.chosen()
    for concept in res.concepts:
        cols = res.fields.get(concept.name, [])
        if chosen and not any(_value(r, c) for r in chosen for c in cols):
            return f"none of the selected records holds a {concept.plain}"
    return ""


def deterministic_answer(
    rows: List[Dict],
    question: str,
    register_label: str = "",
    today: Optional[date] = None,
    partial: bool = False,
    register_terms: Sequence[str] = (),
) -> str:
    """The answer text itself for a simple lookup, or "" when the narration must write it.

    Refuses on any doubt: a word of the question that matched nothing, a field the register does
    not hold, two registers in play, a question about the reader. A deterministic reply that is
    wrong is worse than a narration that is merely stiff, so every refusal falls back.
    """
    if not answers_enabled() or not rows:
        return ""
    try:
        res = resolve(rows, question, register_label, today, register_terms=register_terms)
        why = _ineligible(res, question, partial)
        if why:
            logger.info(f"[register_projection] not composed deterministically: {why}")
            return ""
        prep = res.prep or prepare(question)
        lines = _compose(res, register_label, today, question_shape(prep.core, prep.list_hint))
    except Exception as exc:  # pragma: no cover - the narration still answers
        logger.warning(f"[register_projection] composition skipped: {type(exc).__name__}: {exc}")
        return ""
    text = "\n".join(lines).strip()
    logger.info(f"[register_projection] composed {len(text)} chars; filters={res.filters}")
    return text


# --------------------------------------------------------------------------------------
# for the narration, when it is the one writing
# --------------------------------------------------------------------------------------


def facts_lines(
    rows: List[Dict],
    question: str,
    register_label: str = "",
    today: Optional[date] = None,
    register_terms: Sequence[str] = (),
) -> List[str]:
    """Locked lines for the narration prompt: the records and values the question resolves to."""
    if not rows:
        return []
    try:
        res = resolve(rows, question, register_label, today, register_terms=register_terms)
        prep = res.prep or prepare(question)
        shape = question_shape(prep.core, prep.list_hint) or "list"
        # WHAT THE ROWS SETTLE, EVEN WHEN THEY DO NOT SETTLE ALL OF IT (wave 4). These lines used
        # to be withheld unless every word of the question was placed, on the grounds that a
        # partial lock reads as the whole answer — and the effect was that a question naming five
        # properties, of which the register holds three, reached the model with nothing at all and
        # was declined whole. The lines now say which part they cover, and the closing sentence
        # names the rest, so the model is never left to decide whether the register holds a field.
        if res.conflict or res.negated or not res.pinned():
            return []
        if any(ch.isdigit() for w in res.unresolved for ch in w):
            return []  # a place or reference the question names is in no record: lock nothing
        body = _compose(res, register_label, today, shape, True)
    except Exception as exc:  # pragma: no cover
        logger.warning(f"[register_projection] facts skipped: {type(exc).__name__}: {exc}")
        return []
    out = [
        "- THE ANSWER TO THIS QUESTION, WORKED OUT BY THE SYSTEM FROM THE ROWS (locked). State "
        "exactly these records and values, and never say the register lacks a field that a line "
        "below prints:"
    ]
    if res.unanswered:
        out.append(
            "  - THIS COVERS PART OF THE QUESTION. Give the part below as the answer, then say in "
            "ONE closing sentence that the register does not record "
            + _join(sorted(set(res.unanswered))[:5])
            + ". Never decline the whole question because of that part, and never call the part "
            "below unrecorded."
        )
    return out + ["  " + line for line in body if line.strip()]


def _paragraph_denies(paragraph: str, concept: Concept, cols: Sequence[str]) -> bool:
    """Does this paragraph deny the field a concept names?"""
    low = re.sub(r"[*_`]+", "", paragraph.lower())
    if not rf._ABSENCE_SENTENCE_RE.search(low):
        return False
    words = {stem(w) for w in words_of(low)}
    if words & concept.stems:
        return True
    return any(stem(w) in words for c in cols for w in column_words(c) if len(w) > 3)


def _rows_named(narration: str, rows: List[Dict]) -> List[Dict]:
    text = narration.translate({0x2011: "-", 0x2010: "-", 0x2013: "-", 0x2212: "-"})
    return [r for r in rows if _ident(r) != "?" and _ident(r) in text]


def _replacement(
    concept: Concept, cols: Sequence[str], subject: List[Dict], shared: Dict[str, str]
) -> str:
    lines = [f"The register records the {concept.plain}:", ""]
    folded = (
        _folded_lines(subject, cols, shared)
        if concept.shape == "who" and len(subject) > FOLD_AT
        else []
    )
    lines += folded or [_row_line(r, cols, False, shared=shared) for r in subject[:MAX_LISTED]]
    return "\n".join(lines)


def _denied_concepts(
    narration: str, res: Resolution, rows: List[Dict]
) -> "Dict[Concept, List[str]]":
    """Fields the NARRATION denies and the rows hold — whether or not the question named them.

    The question's own words were not enough. Measured live 2026-09-19 on the approval register:
    one answer grouped its accountable roles and owners correctly, and another said "because those
    fields are missing, the responsibilities … are currently unrecorded" — the same register
    contradicting itself between two questions. The second asked about competence, which names no
    column, so nothing the question said pointed at the columns the answer then denied.

    What the answer DENIES is the better evidence, so the denial's own words are read too. A
    concept is only ever admitted when the register really holds a column for it, which is what
    keeps a denial about something absent ("no carbon figure") from being overwritten.
    """
    vocab = get_vocabulary()
    content = rf._content_columns(rows, _all_columns(rows))
    out: "Dict[Concept, List[str]]" = {}
    for concept in res.concepts:
        cols = res.fields.get(concept.name, [])
        if cols:
            out[concept] = cols
    denials = " ".join(
        p for p in re.split(r"\n\s*\n", narration) if rf._ABSENCE_SENTENCE_RE.search(p.lower())
    )
    for concept in vocab.concepts_in(denials):
        if concept in out or concept.shape != "who":
            # Only the WHO concepts: a date or a place named inside a denial is as often the
            # thing that is genuinely missing as the thing the register holds, and replacing
            # those would argue with honest answers.
            continue
        cols = vocab.columns_for(concept, content)
        if cols:
            out[concept] = cols
    return out


def guard_narration(
    narration: str,
    rows: List[Dict],
    question: str,
    register_label: str = "",
    today: Optional[date] = None,
) -> str:
    """The finished narration, with any denial of a field the rows hold REPLACED by its values.

    W19's guard appended a value-less note beside the denial. This replaces the denial: a
    paragraph that says the register has no owner is removed and the owners are printed in its
    place. Only when nothing was replaced does the older note-appending check still run.
    """
    if narration and rf._QUERY_IRI_RE.search(narration):
        narration = rf.strip_query_instructions(narration) or (
            f"I could not read that from the {register_label or 'register'} records just now."
        )
    if not narration or not rows:
        return narration
    try:
        res: Optional[Resolution] = resolve(rows, question, register_label, today)
    except Exception as exc:  # pragma: no cover
        logger.warning(f"[register_projection] guard skipped: {type(exc).__name__}: {exc}")
        res = None
    if res is not None and not res.conflict:
        paragraphs = [p for p in re.split(r"\n\s*\n", narration) if p.strip()]
        named = res.chosen() if res.filters else _rows_named(narration, rows)
        replaced: Set[str] = set()
        party_asked = asks_for_a_party(question)
        for concept, cols in _denied_concepts(narration, res, rows).items():
            if concept.shape == "who" and not party_asked:
                continue  # a denial of an owner the reader never asked for is not ours to fill
            # WHOSE records to print. When the answer named none and nothing filtered, the denial
            # was about the register as a whole, so the whole register answers it — and for a
            # who-question that is a short list of roles with their counts, whatever its size.
            subject = named or (list(rows) if concept.shape == "who" or len(rows) <= 15 else [])
            if not subject or not cols:
                continue
            for i, paragraph in enumerate(paragraphs):
                if not paragraph.startswith("- ") and _paragraph_denies(paragraph, concept, cols):
                    paragraphs[i] = _replacement(concept, cols, subject, res.shared)
                    replaced.add(concept.name)
        if replaced:
            logger.warning(
                f"[register_projection] narration denied {sorted(replaced)}, which the rows "
                "hold — the denial was replaced by the values"
            )
            out: List[str] = []
            for p in paragraphs:
                if not out or p != out[-1]:
                    out.append(p)
            return "\n\n".join(out)
    if res is not None and _contradicts_the_rows(narration, res, question):
        try:
            prep = res.prep or prepare(question)
            shape = question_shape(prep.core, prep.list_hint) or "list"
            composed = "\n".join(_compose(res, register_label, today, shape))
        except (
            Exception
        ) as exc:  # pragma: no cover - keep the narration rather than lose the answer
            logger.warning(
                f"[register_projection] contradiction fix skipped: {type(exc).__name__}: {exc}"
            )
            composed = ""
        if composed.strip():
            logger.warning(
                "[register_projection] narration claims there is no match, and the rows hold "
                f"{len(res.selected)} — replaced by the computed answer"
            )
            return composed
    return narration + rf.false_absence_corrections(
        narration, rows, _all_columns(rows), question, register_label
    )


#: An opening that says nothing matched ("None of these workspaces combine all three ...", "The
#: records do not contain any workspace that ...").
_NONE_CLAIM_RE = re.compile(
    r"\b(?:none of (?:these|the|them|those)\b|no (?:\w+ ){0,3}(?:record|workspace|space|room|item|asset|"
    r"entry|result)s?\b[^.\n]{0,80}\b(?:match|meet|combine|satisfy|offer|have|has|contain)\w*|"
    r"(?:does|do) not contain any\b|there (?:is|are) no\b)",
    re.IGNORECASE,
)


def _contradicts_the_rows(narration: str, res: Resolution, question: str) -> bool:
    """The narration opens by saying nothing matches, and the computed selection is not empty.

    Only when EVERY word of the question was placed (so the selection is the whole answer), only
    in the opening, and only when the denying sentence is about what was ASKED: a passing "none of
    the others are overdue", or "no information about carbon emissions", is not a contradiction.
    """
    if not res.selected or res.unresolved or res.missing or res.conflict or res.negated:
        return False
    if res.blank_cols or not (res.filters or res.criteria_cols):
        return False
    opening = narration[:400]
    match = _NONE_CLAIM_RE.search(opening)
    if not match:
        return False
    start = max(opening.rfind(".", 0, match.start()), opening.rfind("\n", 0, match.start())) + 1
    ends = [i for i in (opening.find(".", match.end()), opening.find("\n", match.end())) if i >= 0]
    sentence = opening[start : min(ends) if ends else len(opening)]
    asked = {stem(t) for t, _p in rf._question_terms(question, "")}
    said = {stem(w) for w in words_of(sentence) if len(w) >= 4}
    return len(asked & said) >= 2


# --------------------------------------------------------------------------------------
# a whole subject is not one register (BUG-829)
# --------------------------------------------------------------------------------------


def related_classes(
    question: str, classes: Sequence[Any], primary_name: str, limit: int = 2
) -> List[Any]:
    """Other registers whose own name shares a two-word subject phrase with the question.

    "fire safety inspections" names the fire safety asset register by "fire safety", not by any
    word the compliance register answers to. The phrase is the evidence: two adjacent content
    words, stem-compared, found adjacent in a register's declared terms.
    """
    stop = {stem(w) for w in rf._STOPWORDS}
    words = [w for w in words_of(question)]
    pairs = {
        (stem(a), stem(b))
        for a, b in zip(words, words[1:])
        if len(a) >= 3 and len(b) >= 3 and stem(a) not in stop and stem(b) not in stop
    }
    out: List[Any] = []
    for cls in classes:
        if not pairs or getattr(cls, "local_name", "") == primary_name:
            continue
        for term in list(getattr(cls, "terms", ())) + [getattr(cls, "label", "")]:
            tw = [stem(w) for w in words_of(term)]
            if any(pair == (tw[i], tw[i + 1]) for pair in pairs for i in range(len(tw) - 1)):
                out.append(cls)
                break
    return out[:limit]


@dataclass
class RegisterFinding:
    """What one register says about the subject's state."""

    label: str
    total: int
    info: OverdueInfo
    rows: List[Dict]

    def hits(self) -> List[int]:
        return sorted(set(self.info.recorded) | set(self.info.computed))


#: The question is about the subject in general, not about one named thing. "Is the fire alarm
#: weekly test overdue?" asks about one record and is not answered by listing a register's lapses.
_GENERAL_SUBJECT_RE = re.compile(
    r"\b(?:building|all|any|anything|everything|every|our|we|nothing|none)\b", re.IGNORECASE
)


def wants_whole_subject(question: str) -> bool:
    """A yes/no question about a whole subject's state ("up to date", "any overdue")."""
    return bool(
        _WHOLE_SUBJECT_RE.search(question or "") and _GENERAL_SUBJECT_RE.search(question or "")
    )


def _describe(f: RegisterFinding, i: int) -> str:
    row = f.rows[i]
    ident, name = _ident(row), _value(row, "label")
    head = ident if not name or name == ident else f"{ident} ({name})"
    due = f.info.due.get(i)
    return head + (f", due {_fmt_date(due)}" if due else "")


def _finding_line(f: RegisterFinding) -> str:
    where = f"{f.label} register"
    if f.info.basis == "none":
        return (
            f"- **{_sentence_case(where)}** ({f.total} records): records no due date and no "
            "overdue status, so it cannot show this."
        )
    hits = f.hits()
    if not hits:
        return f"- **{_sentence_case(where)}** ({f.total} records): none overdue."
    shown = "; ".join(_describe(f, i) for i in hits[:8])
    more = f"; and {len(hits) - 8} more" if len(hits) > 8 else ""
    return (
        f"- **{_sentence_case(where)}** ({f.total} records): {len(hits)} overdue — {shown}{more}."
    )


def cross_register_lines(
    findings: Sequence[RegisterFinding], today: Optional[date], unread: Sequence[str] = ()
) -> str:
    """The answer to a whole-subject state question, register by register."""
    as_at = f" as at {_fmt_date(today)}" if today else ""
    total_hits = sum(len(f.hits()) for f in findings)
    names = _join([f"the {f.label} register" for f in findings])
    if total_hits:
        noun = "record is" if total_hits == 1 else "records are"
        lead = f"**No — not everything is up to date{as_at}.** {total_hits} {noun} overdue:"
    else:
        lead = (
            f"**Nothing is recorded as overdue{as_at}** in {names}. That is what those "
            "registers say, not a statement about anything they do not cover."
        )
    lines = [lead, ""] + [_finding_line(f) for f in findings]
    if unread:
        lines += ["", "Not read: " + ", ".join(unread) + "."]
    return "\n".join(lines)


async def cross_register_answer(
    question: str,
    primary_rows: List[Dict],
    primary_label: str,
    primary_name: str,
    classes: Sequence[Any],
    fetch_rows: Callable[[Any], Awaitable[List[Dict]]],
    today: Optional[date] = None,
) -> str:
    """A whole-subject yes/no answered from EVERY register on the subject, or "" if not one.

    "Is the building up to date with its fire safety inspections?" was answered "yes, none are
    overdue" from the compliance register alone, beside a fire safety asset register that holds
    an overdue dry riser. The conclusion belongs to the subject, not to whichever register was
    ranked first, so the related registers are read too and every one is reported.
    """
    if not answers_enabled() or not wants_whole_subject(question) or not primary_rows:
        return ""
    try:
        registers = [(primary_label, primary_rows)]
        unread: List[str] = []
        for cls in related_classes(question, classes, primary_name):
            label = getattr(cls, "label", "") or getattr(cls, "local_name", "")
            try:
                rows = await fetch_rows(cls)
            except Exception as exc:
                logger.warning(f"[register_projection] {label} unreadable: {type(exc).__name__}")
                unread.append(f"the {label} register")
                continue
            if rows:
                registers.append((label, rows))
        findings = [
            RegisterFinding(label, len(rows), overdue_info(rows, _all_columns(rows), today), rows)
            for label, rows in registers
        ]
        if not any(f.info.basis != "none" for f in findings):
            return ""
        return cross_register_lines(findings, today, unread)
    except Exception as exc:  # pragma: no cover - the narration still answers
        logger.warning(f"[register_projection] cross-register skipped: {type(exc).__name__}: {exc}")
        return ""


async def answer_before_narration(
    question: str,
    rows: List[Dict],
    register_label: str,
    register_name: str,
    classes: Sequence[Any],
    fetch_rows: Callable[[Any], Awaitable[List[Dict]]],
    today: Optional[date] = None,
    partial: bool = False,
    register_terms: Sequence[str] = (),
) -> str:
    """The answer the rows settle on their own, or "" when the narration must write it.

    A whole-subject state question is answered across every register on the subject; a simple
    who / when / which / how-many question is answered from the resolved records. Either way the
    model is not asked, so it cannot deny a field the rows hold or conclude beyond them.
    """
    if (
        partial
    ):  # two registers merged, or a scoped part of one: a count of it is not the register's
        return ""
    cross = await cross_register_answer(
        question, rows, register_label, register_name, classes, fetch_rows, today
    )
    return (
        cross
        or deterministic_answer(
            rows, question, register_label, today, register_terms=register_terms
        )
        or out_of_scope_decline(rows, question, register_label, today)
    )


_CROSS_SOURCE_RE = re.compile(
    r"\b(?:conflicts?|conflicting|disagree\w*|inconsisten\w*|reconcil\w*|mismatch\w*|"
    r"discrepanc\w*|contradict\w*)\b",
    re.IGNORECASE,
)


def out_of_scope_decline(
    rows: List[Dict],
    question: str,
    register_label: str = "",
    today: Optional[date] = None,
) -> str:
    """One sentence naming the register searched and what it records, for a question it cannot answer.

    Measured over the recorded runs, 9 of 12 answers that opened with the register's owner list
    answered a question that never asked for one, and the same family ended in "The register does
    not record …" followed by an unrelated count. A register asked something it holds none of
    should say exactly that — which register, what it does hold — rather than compose whatever it
    can. It also spares the model a long prompt: one such question took 175 s to end in a decline.

    Conservative on purpose: it speaks only when nothing the question says selects any record and
    three or more words are beyond the register, or when the question asks the register to
    reconcile itself against sources it does not hold. Anything the rows can pin is left alone.
    """
    try:
        if not rows:
            return ""
        res = resolve(rows, question, register_label, today)
        prep = res.prep or prepare(question)
        beyond = sorted(set(res.unanswered))
        # "not directly comparable" is a negation in the question's WORDS; with six or more words
        # beyond the register it is not a request for the records that lack something
        if prep.reader or res.conflict or (res.negated and len(beyond) < 6):
            return ""
        # a concept word like "last" in "the last signed handover" can pin a field by accident:
        # with five or more words beyond the register, one such word is not an answer
        pinned_fields = bool(res.fields) and len(beyond) < 5
        cross = bool(_CROSS_SOURCE_RE.search(question)) and bool(
            re.search(r"\bbetween\b", question, re.IGNORECASE)
        )
        structured = [f for f in res.other_filters if f not in res.text_filters]
        nothing_pinned = not (
            structured or res.status_values or res.blank_cols or res.group_col or res.overdue
        )
        speaks = (cross and len(beyond) >= 2) or (
            nothing_pinned and not pinned_fields and len(beyond) >= 3
        )
        if not speaks:
            return ""
        vocab = get_vocabulary()
        content = rf._content_columns(rows, _all_columns(rows))
        held = [
            _label(c)
            for c in content
            if not c.startswith(("record", "label"))
            and vocab.names_what_a_record_is(c)
            or c in ("label",)
        ]
        held = list(dict.fromkeys(held))[:8] or [_label(c) for c in content[:8]]
        return (
            f"{_register_phrase(register_label).capitalize()} ({len(rows)} records) cannot "
            f"answer this: it records {_join(held)}, and nothing about {_join(beyond[:4])}."
        )
    except Exception as exc:  # pragma: no cover - the narration still answers
        logger.warning(f"[register_projection] decline skipped: {type(exc).__name__}: {exc}")
        return ""
