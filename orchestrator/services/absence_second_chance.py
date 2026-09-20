# -*- coding: utf-8 -*-
"""A decline that says the building holds nothing gets one second look (row 2D-18).

Measured on the 2026-09-19 development reads, the largest remaining class of unacceptable answers
is a FALSE ABSENCE: the lane the classifier happened to pick retrieved something irrelevant and the
narration turned "my retrieval had no X" into "the building has no X". The building holds the
records — door hardware with a defective and an overdue door, service schedules, coordination
functions that name the wardens, 675 timetabled sessions, a lift whose own record states a weight
limit of 1000 kg — and nothing in the pipeline looked where they are.

What this does, in order, and all of it deterministic until the single lane call:

1. ``detect_absence_shape``: is the final answer an absence claim, and what does it say is missing?
2. ``skip_reason``: never touch a typed absence, a referent-gate refusal, an observability
   "not measured", a privacy or control refusal, or a lane that is not a retrieval lane.
3. ``probe``: score the question with scorers the failing lane did NOT use —
   ``record_registry.rank_record_classes`` (the router's own register selector, over the ontology's
   declared lay terms) confirmed against the chosen registers' actual rows by
   ``register_projection.resolve``, and the prose the building keeps on its own records — and
   require a clear margin, so a weak candidate never overrides.
4. A confirmed leader (tier A) is handed to that lane's answerer ONCE. A grounded, non-absence
   result replaces the decline; anything else leaves the decline standing.
5. A weaker candidate (tier B), or a failed reopen, rewrites only the false universal
   ("the register does not record X") into a scoped statement naming what was searched and what is
   closest. With no candidate the answer is untouched: an honest decline stays honest.

Nothing here names a building, a register or a sensor: registers, their fields and their values are
read as rows, the vocabulary comes from the ontology, and the prose from the building's own graph.
Every read and every lane call is injected, so each decision is testable offline with fakes.
"""

from __future__ import annotations

import asyncio
import math
import os
import re
from dataclasses import dataclass, field
from datetime import date
from typing import Any, Awaitable, Callable, Dict, List, Optional, Sequence, Set, Tuple

from orchestrator.services.grounding_guard import (
    _HONEST_DECLINE_RES,
    content_terms,
    meta_answer_reason,
    names_internal_vocabulary,
    plain_prose,
)
from orchestrator.services.passage_relevance import needed_terms, question_topic_terms
from shared.utils import describe_exception, get_logger

logger = get_logger(__name__)

ENV_FLAG = "ABSENCE_SECOND_CHANCE"

#: The whole second look — probe and at most one lane call — may take no longer than this.
BUDGET_SECONDS = 75.0

#: Registers whose rows are fetched for confirmation. A shortlist, because each one is a query.
MAX_SHORTLIST = 4

#: Rows fetched per shortlisted register. Past this the register is marked partial and its rows are
#: used for evidence only — a count taken from part of a register would be a wrong number.
MAX_PROBE_ROWS = 150

#: Lanes whose retrieval can miss what the building holds. Every other lane keeps its answer.
REOPENABLE_LANES = frozenset(
    {
        "metadata",
        "discovery",
        "analytics",
        "sensor_data",
        "compare",
        "trend",
        "recommend",
        "capability",
        "events",
        "register",
    }
)

#: A bus key that is set means some lane made a deliberate, typed decision; it is never reopened.
_TYPED_KEYS: Tuple[Tuple[str, str], ...] = (
    ("privacy_refusal_result", "privacy refusal"),
    ("referent_refusal_result", "referent gate"),
    ("observability_result", "observability"),
    ("control_result", "control lane"),
    ("disclosure_decision", "disclosure gate"),
    ("absence_correction", "already corrected by the absence guard"),
    ("unmodelled_correction", "unmodelled entity"),
    ("asset_state_result", "asset state"),
    ("readiness_result", "readiness"),
)

#: Questions about individuals or their data are refused on purpose; reaching for them is a leak.
_PRIVATE_ASK_RE = re.compile(
    r"\b(?:track|tracking|tracked|surveil\w*|spy|whereabouts|movements?)\b[^.?]{0,50}"
    r"\b(?:me|him|her|them|person|people|staff|student|students|employee|individual\w*)\b"
    r"|\b(?:data|information)\b[^.?]{0,40}\b(?:collected|sold|shared)\b[^.?]{0,25}"
    r"\b(?:on|about)\s+(?:me|us|people)\b"
    r"|\bwho\s+(?:is|was)\s+(?:in|at|inside)\b",
    re.IGNORECASE,
)

#: A deterministic "does not exist" that the referent gate or a typed lane wrote as text.
_NOT_EXIST_RE = re.compile(
    r"\bdoes\s+not\s+exist\b|\bno\s+such\s+(?:room|space|floor|zone|sensor|asset)\b"
    r"|\bnot\s+measured\b|\bnot\s+something\s+this\s+building\s+measures\b",
    re.IGNORECASE,
)


#: "Not measured" is the observability lane's own true statement about a quantity nobody senses.
_NOT_MEASURED_RE = re.compile(
    r"\bnot\s+measured\b|\bnot\s+something\s+this\s+building\s+measures\b", re.IGNORECASE
)


def enabled() -> bool:
    """On unless ABSENCE_SECOND_CHANCE is set to false."""
    return os.environ.get(ENV_FLAG, "true").strip().lower() != "false"


# ── 1. what an absence answer looks like ────────────────────────────────────────────────────────

_SUBJ = (
    r"(?:register|registers|records?|data|database|building model|model|ontology|documents?|"
    r"building|system|sources?|results?|entries|readings?|information)"
)
_VERB = (
    r"(?:record|contain|include|hold|have|list|state|specify|describe|cover|mention|track|show|"
    r"provide|store|keep|capture)"
)
# Every alternative here ends at a WORD BOUNDARY. Without one, "does not include official text-based
# check-in" lost its first two letters to the preposition "of" of `_PREP` below, and "datasets" lost
# "data" to this list: a prefix strip that treats a stop word as a word wherever it starts.
_THING = (
    r"(?:any\s+|an\s+|a\s+)?(?:(?:information|data|entries|entry|records?|details|evidence|fields?|"
    r"readings?|figures?|mentions?|values?)\b)?"
)
_PREP = r"(?:(?:about|on|for|of|regarding|that|to)\b)?"
_OBJ = r"(?P<obj>[^.\n]*)"

#: (kind, pattern, reword). ``reword`` is False where the sentence is ALREADY scoped to what was
#: searched — those may be reopened, but their wording is true and is not touched.
#: SPECIFIC SHAPES FIRST: the first match wins, so a sentence a reader would call one thing must
#: not be recorded as another merely because a broader pattern sits above it.
_SHAPES: Tuple[Tuple[str, "re.Pattern[str]", bool], ...] = (
    (
        "no_record_of_that",
        re.compile(
            r"\b(?:this|the)\s+building\s+(?:does\s*n[o']t|doesn't|does\s+not)\s+keep\s+"
            r"(?:a\s+)?record\b(?:\s+of\s+(?P<obj>[^.\n]*))?",
            re.IGNORECASE,
        ),
        True,
    ),
    (
        "not_recorded",
        re.compile(
            rf"\b{_SUBJ}\b[^.\n]{{0,40}}?\b(?:does|do)\s*(?:not|n't)\s+{_VERB}\b\s*{_THING}\s*"
            rf"{_PREP}\s*{_OBJ}",
            re.IGNORECASE,
        ),
        True,
    ),
    (
        "not_recorded",
        re.compile(
            r"\bnone\s+of\s+(?:them|these|those|the\s+\w+(?:\s+\w+)?)\s+"
            rf"(?:contains?|includes?|mentions?|records?|has|have)\s+{_THING}\s*{_OBJ}",
            re.IGNORECASE,
        ),
        True,
    ),
    (
        "no_information",
        re.compile(
            r"\bthere\s+(?:is|are|'s)\s+no\s+(?:\w+\s+){0,2}?"
            r"(?:record|records|information|data|entries|readings?|evidence|comparison|mention)\b"
            r"[^.\n]*?(?:of|for|about|on|that\s+describes?|describing|regarding)\s+" + _OBJ,
            re.IGNORECASE,
        ),
        True,
    ),
    (
        "no_information",
        re.compile(
            r"\bno\s+(?:information|data|record|records|evidence)\s+"
            r"(?:on|about|of|for|regarding)\s+" + _OBJ,
            re.IGNORECASE,
        ),
        True,
    ),
    (
        "unavailable",
        re.compile(
            r"\bno\s+(?P<obj>[a-z][\w\-/ ]{2,50}?)\s+(?:comparison|breakdown|data|information|"
            r"readings?|figures?)\s+(?:is|are)\s+(?:available|possible)\b",
            re.IGNORECASE,
        ),
        True,
    ),
    (
        "retrieval_only",
        re.compile(
            r"\b(?:the|this)\s+(?:data|results?|records?|information|building\s+model|model)\b"
            r"[^.\n]{0,40}?\b(?:you\s+)?(?:retrieved|provided|supplied|returned|received|given)\b"
            r"[^.\n]{0,30}?\b(?:only\s+(?:lists?|contains?|shows?|includes?)|lists?\s+only"
            r"|are\s+all|is\s+all)\b\s*" + _OBJ,
            re.IGNORECASE,
        ),
        True,
    ),
    (
        # "Therefore, I can't tell you whether any parking spots are currently free." — a decline
        # that names no absence in the building at all, and reads as one. Measured 2026-09-19.
        "cannot_tell",
        re.compile(
            r"\bi\s+(?:can'?t|cannot|could\s+not|couldn'?t)\s+(?:tell|say|determine|establish|"
            r"confirm|report)\s+(?:you\s+)?(?:whether|if|which|what|how)\s+" + _OBJ,
            re.IGNORECASE,
        ),
        True,
    ),
    (
        "none_on_record",
        re.compile(
            r"\bi\s+(?:do\s*n[o']t|don't|do\s+not)\s+have\s+(?:that\s+)?(?:specific\s+)?"
            r"(?:information|data|details)\b[^.\n]*?\bon\s+record\b",
            re.IGNORECASE,
        ),
        False,
    ),
    (
        "documents_silent",
        re.compile(
            r"\bdocuments?\s+do(?:es)?\s*(?:not|n't)\s+answer\b"
            r"|\bi\s+could\s*n[o']t\s+find\s+(?:this|that|it)\s+in\b",
            re.IGNORECASE,
        ),
        False,
    ),
)

#: A line that is only a heading or a banner — "**Answer**", "_Served at 5-second resolution…_".
#: It says nothing about the building, so a claim after it still OPENS the answer.
_BANNER_RE = re.compile(r"^\s*(?:#{1,6}\s|[*_]{1,3}[^*_]{0,60}[*_]{1,3}\s*$|_[^_]{0,160}_\s*$)")

#: How many content segments count as the opening of an answer.
LEAD_SEGMENTS = 2
_SENT_SPLIT = re.compile(r"(?<=[.!?])\s+(?=[A-Z*_`\[(])")
#: Where the missing thing ENDS. A clause that starts with "so", "which" or "because" is the
#: answer's own commentary on the absence, not part of what is absent: it was spliced into the
#: sentence "I did not find waste volumes, so it cannot contribute to the answer in ...".
_OBJ_STOP = re.compile(
    r"\s*(?:,\s*(?:nor|and\s+no|so|which|but|because|therefore|thus|hence|meaning|and\s+so)\b"
    r"|;|\s+-\s+|\s+nor\s+|\s+so\s+(?:it|they|this|that|we|i|there)\b"
    r"|\s+which\s+(?:means|is|are|cannot)\b)",
    re.IGNORECASE,
)
_INTERROG_HEAD = re.compile(r"^(?:whether|if|how|what|which|who|whom|when|where|why)\b", re.I)


@dataclass(frozen=True)
class AbsenceShape:
    """An absence claim found in an answer: which kind, the sentence, and what it says is missing."""

    kind: str
    segment: str
    object_text: str
    leads: bool  # among the answer's first statements: worth scoping
    reword: bool
    #: The FIRST thing the answer says. Only such a claim may have the whole answer replaced:
    #: measured on the replay, acting on a later one swapped three good answers for lookups that
    #: covered less, and one of those disagreed with the answer it replaced about a count.
    opens: bool = False


def _clean_object(text: str) -> str:
    """The thing the answer says is missing, trimmed to a phrase a reader can follow."""
    obj = plain_prose(text or "").strip(" \t-–—:;,.'\"")
    obj = _OBJ_STOP.split(obj, maxsplit=1)[0]
    obj = re.sub(r"^(?:about|regarding|on|of)\s+", "", obj, flags=re.IGNORECASE)
    obj = re.sub(r"^(?:any|the|a|an)\s+", "", obj, flags=re.IGNORECASE).strip(" ,.;")
    if len(obj) > 130:
        obj = obj[:130].rsplit(" ", 1)[0].rstrip(" ,;")
    obj = _without_a_leading_verb(obj)
    return balance_quotes(obj)


#: A finite verb the object phrase started with because the pattern's own verb was elsewhere:
#: "I did not find any contain information about existing signage".
_LEADING_VERB = re.compile(
    r"^(?:contains?|includes?|lists?|mentions?|records?|describes?|states?|specif(?:y|ies)|"
    r"has|have|shows?|holds?|covers?)\s+(?:(?:any|the|an?)\s+)?"
    r"(?:(?:information|data|details|records?|evidence|entries)\s+(?:about|on|of|for|regarding)\s+)?",
    re.IGNORECASE,
)


def _without_a_leading_verb(obj: str) -> str:
    """The thing that is missing, without a verb the pattern left at its front."""
    m = _LEADING_VERB.match(obj or "")
    if not m:
        return obj
    return obj[m.end() :].strip(" ,.;")


def balance_quotes(text: str) -> str:
    """``text`` with any quotation mark that has no partner removed.

    The object phrase is trimmed by stripping quote characters from both ends, which removed a
    closing quote and kept the opening one: 'I did not find any bookable room as "reliable in ...'.
    A pair is left alone; a lone mark is dropped rather than guessed at.
    """
    out = text or ""
    if out.count('"') % 2:
        out = out.replace('"', "")
    if out.count("“") != out.count("”"):
        out = out.replace("“", "").replace("”", "")
    return out


def _segments(text: str) -> List[str]:
    """Sentences and lines of an answer, each a verbatim substring so it can be replaced."""
    out: List[str] = []
    for line in (text or "").split("\n"):
        if not line.strip():
            continue
        out.extend(part for part in _SENT_SPLIT.split(line) if part.strip())
    return out


def opens_the_answer(segments: Sequence[str], index: int) -> bool:
    """True when the segment at ``index`` is one of the answer's first things said.

    Position, not character offset: an absence that OPENS an answer is the answer, and one that
    follows two substantive sentences is a caveat on an answer already given. Headings and banners
    do not count as things said.
    """
    content = [i for i, seg in enumerate(segments) if not _BANNER_RE.match(seg)]
    return index in content[:LEAD_SEGMENTS]


def detect_absence_shape(text: str) -> Optional[AbsenceShape]:
    """The first absence claim in ``text``, or None. Pure; precision first."""
    if not text or not text.strip():
        return None
    segments = _segments(text)
    for index, seg in enumerate(segments):
        plain = plain_prose(seg)
        for kind, pattern, reword in _SHAPES:
            m = pattern.search(plain)
            if not m:
                continue
            obj = _clean_object(m.groupdict().get("obj") or "")
            content = [i for i, part in enumerate(segments) if not _BANNER_RE.match(part)]
            return AbsenceShape(
                kind,
                seg,
                obj,
                opens_the_answer(segments, index),
                reword,
                bool(content) and index == content[0],
            )
    try:
        from orchestrator.services.absence_guard import detect_absence_claim

        modality = detect_absence_claim(text)
    except Exception:  # pragma: no cover - the detector must never cost an answer
        modality = None
    return AbsenceShape("modality", "", modality, True, False, True) if modality else None


def skip_reason(
    results: Dict[str, Any], lane: Optional[str], question: str, answer: str
) -> Optional[str]:
    """Why this answer must not be looked at again, or None when it may be."""
    if lane not in REOPENABLE_LANES:
        return f"lane {lane!r} is not a retrieval lane"
    for key, why in _TYPED_KEYS:
        if results.get(key):
            return why
    for key in ("sparql_result", "sql_result"):
        res = results.get(key)
        if isinstance(res, dict) and (
            res.get("method") == "typed_absence" or res.get("retrieval_outcome")
        ):
            return "typed absence"
    if _PRIVATE_ASK_RE.search(question or ""):
        return "question is about individuals or their data"
    body = plain_prose(answer or "")
    if _NOT_EXIST_RE.search(body):
        return "deterministic 'does not exist' / 'not measured' decline"
    if any(rx.search(body) for rx in _HONEST_DECLINE_RES):
        return "the system's own deterministic decline"
    return None


# ── 2. what to look for ─────────────────────────────────────────────────────────────────────────

#: Words that frame a question without naming what it is about, on top of the shared framing list.
_NOISE = frozenset(
    "record register held hold kept keep currently evidence evidenced documented recorded "
    "required need needed provide would could confirmed confirm current recent stated state "
    "still ready relevant".split()
)


def fold(term: str) -> str:
    """Six-letter stem, so 'defect' meets 'defective' and 'isolate' meets 'isolation'."""
    return term[:6] if len(term) >= 7 else term


def topic_terms(question: str) -> List[str]:
    """Subject terms of a question: compounds split, framing and generic words dropped."""
    out: List[str] = []
    for term in sorted(question_topic_terms(question)):
        parts = [p for p in re.split(r"[-/]", term) if len(p) >= 4]
        pieces = sorted(content_terms(" ".join(parts))) if len(parts) >= 2 else [term]
        for piece in pieces:
            if len(piece) >= 3 and piece not in _NOISE and piece not in out:
                out.append(piece)
    return out


# ── 3. what the probe may read ──────────────────────────────────────────────────────────────────


@dataclass
class RegisterTable:
    """One register the building holds: its identity and as many of its rows as were fetched."""

    local_name: str
    label: str
    instances: int
    rows: List[Dict[str, Any]] = field(default_factory=list)

    @property
    def partial(self) -> bool:
        """True when the rows in hand are not the whole register, so no count may be stated."""
        return bool(self.rows) and len(self.rows) < self.instances


@dataclass(frozen=True)
class TextHit:
    """A sentence the building's graph holds about one of its own things."""

    subject: str
    label: str
    predicate: str
    text: str


#: Prose predicates: what a building writes about a thing in its own words.
PROSE_PREDICATES: Tuple[str, ...] = (
    "http://www.w3.org/2000/01/rdf-schema#comment",
    "http://www.w3.org/2004/02/skos/core#definition",
    "http://ontosage.org/capabilities#answerText",
    "http://ontosage.org/capabilities#note",
)


class Reach:
    """What the probe may read. The live one queries the graph; tests pass fixtures."""

    async def classes(self) -> List[Any]:  # pragma: no cover - interface
        """The record classes this building holds (``record_registry.RecordClass`` objects)."""
        return []

    async def rows(
        self, names: Sequence[str]
    ) -> Dict[str, List[Dict[str, Any]]]:  # pragma: no cover
        """The rows of the shortlisted registers, one pivoted dict per record."""
        return {}

    async def text_hits(self, topic: Sequence[str]) -> List[TextHit]:  # pragma: no cover
        """Prose on the building's own records carrying at least two of the question's words."""
        return []

    async def topics(self, question: str) -> List[Any]:  # pragma: no cover
        """Amenity / knowledge-topic facts the capability resolver matches to the question."""
        return []

    async def holds(self, subject: str) -> Optional["Held"]:  # pragma: no cover
        """What the building holds that a sentence called missing, or None. Never a guess."""
        return None

    async def measurable(self, question: str, results: Dict[str, Any]) -> Any:  # pragma: no cover
        """``sensor_binder.Binding`` for this question, or None when nothing measurable is named.

        The binder is the module that owns "(quantity, place) -> the series to read", including
        the judgement that a place genuinely has none. Asking it rather than re-deriving any part
        of that is the whole design: a second opinion about which sensors answer a question is how
        two parts of this system come to give different answers to it.
        """
        return None


# ── 4. registers ────────────────────────────────────────────────────────────────────────────────


@dataclass(frozen=True)
class Candidate:
    """Somewhere the building may hold what the decline said it lacks."""

    kind: str  # register | text | sensor
    name: str
    label: str
    tier: str  # A: hand it to its lane. B: name it as the closest thing.
    score: float
    shared: Tuple[str, ...]
    coverage: float
    margin: float
    evidence: str
    payload: Any = None


@dataclass(frozen=True)
class Confirmation:
    """What the register lane's own resolver makes of the question against one register's rows."""

    structured: int  # status, kind, yes/no or named-field placements: words that PIN records
    unresolved: int  # question words placed nowhere in this register
    conflict: bool  # the conditions named select no record together
    selected: int  # records satisfying every condition


def confirm(table: RegisterTable, question: str, today: Optional[date]) -> Confirmation:
    """Run the register lane's own resolver over ``table``: it decides what a question word IS."""
    from orchestrator.services import register_projection as rp

    res = rp.resolve(table.rows, question, table.label, today)
    kinds = [f for f in res.other_filters if not f.startswith("mentioning")]
    states = len(res.status_groups) or (1 if res.status_values else 0)
    return Confirmation(
        states + len(kinds) + len(res.named),
        len(res.unresolved),
        res.conflict,
        len(res.selected),
    )


def _named_terms(record: Any, question: str) -> Tuple[str, ...]:
    """The class's own declared terms that this question uses, longest first."""
    low = f" {(question or '').lower()} "
    hits = [
        t for t in (getattr(record, "terms", ()) or ()) if re.search(rf"\b{re.escape(t)}\b", low)
    ]
    return tuple(sorted(set(hits), key=lambda t: (-len(t), t))[:4])


def rank_registers(
    question: str,
    ranked: Sequence[Tuple[float, Any]],
    tables: Dict[str, RegisterTable],
    topic: Sequence[str],
    object_terms: Set[str],
    used_score: float = 0.0,
    today: Optional[date] = None,
) -> List[Candidate]:
    """Score the shortlist, strongest first; tier A only for a confirmed, clear leader.

    ``ranked`` comes from ``record_registry.rank_record_classes`` — the scorer the register lane
    uses to CHOOSE a register, over the ontology's declared lay terms. That is the point of using
    it here rather than a private one: it reaches a register whose rows were never fetched (675
    timetabled sessions), and the lane that declined never consulted it at all. A second scorer
    would be a third answer to a question one module should own.
    """
    out: List[Candidate] = []
    for pos, (score, record) in enumerate(list(ranked)[:MAX_SHORTLIST]):
        table = tables.get(record.local_name)
        conf = (
            confirm(table, question, today)
            if table and table.rows
            else Confirmation(0, len(topic), False, 0)
        )
        names = _named_terms(record, question)
        rival = float(ranked[1][0]) if pos == 0 and len(ranked) > 1 else 0.0
        margin = (score / rival) if rival else float("inf")
        held = {fold(t) for w in names for t in content_terms(w)}
        holds_missing = not object_terms or any(fold(t) in held for t in object_terms)
        # A leader is reopened only when the ontology's own words NAME it, its rows PIN at least one
        # of the question's conditions, most of the question lands somewhere in it, and it clearly
        # beats both the runner-up and whatever the failing lane had already read.
        strong = (
            pos == 0
            and bool(names)
            and conf.structured >= 1
            and not conf.conflict
            and conf.unresolved <= 0.6 * max(len(topic), 1)
            and margin >= 1.3
            and (not used_score or score >= 1.5 * used_score)
            and holds_missing
        )
        out.append(
            Candidate(
                kind="register",
                name=record.local_name,
                label=record.label or record.local_name,
                tier="A" if strong else "B",
                score=round(float(score), 2),
                shared=names,
                coverage=round(min(len(names) / max(len(topic), 1), 1.0), 2),
                margin=round(min(margin, 99.0), 2),
                evidence=(
                    f"the building's {record.label} register is named by "
                    f"{', '.join(names) or 'no declared term'}"
                    + (
                        f"; {conf.structured} of the question's conditions match its rows, "
                        f"{conf.unresolved} words unplaced"
                        if table and table.rows
                        else "; its rows were not read"
                    )
                ),
                payload=table,
            )
        )
    return out


# ── 5. prose on the building's own records ──────────────────────────────────────────────────────

_SIMULATED_RE = re.compile(r"\b(?:synthetic|simulated|fake|dummy|placeholder)\b", re.IGNORECASE)
_ASKS_VALUE_RE = re.compile(
    r"^\W*(?:what(?:'s|\s+is|\s+are|\s+was)|how\s+(?:much|many|long|high|big|large|far|old|often"
    r"|wide|heavy|tall)|when\s+is)\b",
    re.IGNORECASE,
)


def _words(text: str) -> Set[str]:
    return {fold(t) for t in content_terms(text)}


def states_a_value(text: str, shared: Sequence[str]) -> bool:
    """True when a digit sits near one of the shared words: this prose gives a figure for it."""
    low = (text or "").lower()
    for word in shared:
        stem = fold(word)
        at = low.find(stem)
        while at != -1:
            if re.search(r"\d", low[max(0, at - 40) : at + len(stem) + 40]):
                return True
            at = low.find(stem, at + 1)
    return False


def text_query(namespace: str, topic: Sequence[str], limit: int = 40) -> str:
    """SPARQL for prose on the active building's things that carries at least two topic words."""
    words = sorted({fold(t) for t in topic if len(t) >= 4})[:12]
    if len(words) < 2:
        return ""
    tests = " + ".join(f'IF(CONTAINS(LCASE(STR(?text)), "{w}"), 1, 0)' for w in words)
    preds = " ".join(f"<{p}>" for p in PROSE_PREDICATES)
    return (
        "PREFIX rdfs: <http://www.w3.org/2000/01/rdf-schema#>\n"
        "SELECT ?s ?label ?p ?text ?hits WHERE {\n"
        f"  VALUES ?p {{ {preds} }}\n"
        "  ?s ?p ?text .\n"
        f'  FILTER(isLiteral(?text) && STRSTARTS(STR(?s), "{namespace}"))\n'
        "  OPTIONAL { ?s rdfs:label ?label }\n"
        f"  BIND(({tests}) AS ?hits)\n"
        "  FILTER(?hits >= 2)\n"
        f"}} ORDER BY DESC(?hits) LIMIT {int(limit)}"
    )


#: Share of a text's own vocabulary that must be the question's words. MEASURED on this building's
#: prose: a record's own comment about what the question asks ("A refuge point whose communication
#: unit does not work…", "Weight limit 1000 kg…") runs 0.18–0.33, while an authored topic page that
#: merely contains the words somewhere in 900 characters runs 0.03–0.08. Below this a hit is not
#: about the question, it is long.
MIN_TEXT_DENSITY = 0.05


def rank_text(
    topic: Sequence[str], hits: Sequence[TextHit], object_terms: Set[str], question: str = ""
) -> List[Candidate]:
    """The prose that says the most of what was asked, densest first.

    Ranked by ``shared / sqrt(the text's own terms)``, not by shared terms alone: a 900-character
    policy page shares more words with any question than a one-line record does, and is about the
    question far less often. The same measurement sets ``MIN_TEXT_DENSITY``.
    """
    live = [t for t in topic if len(t) >= 3]
    if len(live) < 2:
        return []
    ranked: List[Tuple[float, int, TextHit, List[str]]] = []
    for hit in hits:
        if _SIMULATED_RE.search(hit.text):
            continue  # the owner's standing rule: no user-visible text calls the data simulated
        own = content_terms(hit.text)
        have = {fold(t) for t in own} | _words(hit.label)
        shared = [t for t in live if fold(t) in have]
        n = len(shared)
        if n >= 2 and n / max(len(own), 1) >= MIN_TEXT_DENSITY:
            ranked.append((n / math.sqrt(max(len(own), 1)), n, hit, shared))
    ranked.sort(key=lambda r: (-r[0], r[2].subject))
    asks_value = bool(_ASKS_VALUE_RE.search(question or ""))
    out: List[Candidate] = []
    for pos, (density, n, hit, shared) in enumerate(ranked[:3]):
        coverage = n / float(len(live))
        rival = ranked[1][0] if pos == 0 and len(ranked) > 1 else 0.0
        margin = density / rival if rival else float("inf")
        held = {fold(s) for s in shared}
        holds_missing = not object_terms or any(fold(t) in held for t in object_terms)
        # PROSE IS REOPENED ONLY TO STATE A FIGURE IT HOLDS. "What is the weight limit on the
        # lifts?" is answered by the lift's own record ("Weight limit 1000 kg"); a policy page that
        # merely shares two words with the question is the closest thing, not the answer. Measured:
        # without this every long authored topic — the GDPR page above all — became a leader for
        # any question sharing two of its many words.
        strong = (
            pos == 0
            and asks_value
            and states_a_value(hit.text, shared)
            and n >= max(2, needed_terms(len(live)))
            and coverage >= 0.5
            and margin > 1.0
            and holds_missing
        )
        out.append(
            Candidate(
                kind="text",
                name=hit.subject,
                label=hit.label or hit.subject.rsplit("#", 1)[-1].rsplit("/", 1)[-1],
                tier="A" if strong else "B",
                score=round(density, 3),
                shared=tuple(shared),
                coverage=round(coverage, 2),
                margin=round(min(margin, 99.0), 2),
                evidence=f"{n} of {len(live)} question terms in the record's own text",
                payload=hit,
            )
        )
    return out


# ── 5b. quantities the building measures ────────────────────────────────────────────────────────
#
# The three false absences wave 3 could not touch were all of one shape: the question asks about
# something the building MEASURES, and a lane that reads records declined for it. "Are my windows
# leaking heat right now?" (window contact and temperature), "are there any devices left on in
# unoccupied rooms?" (occupancy status and electric power), "are there free parking spaces
# available now?" (a parking_free modality). No register holds those; a series does.
#
# The arm is deliberately thin. It asks `sensor_binder` — which already resolves the quantity
# through the concept resolver and the modality catalogue, resolves the place against the live
# graph, and returns a TYPED ABSENCE when the place genuinely has none — and it believes the
# answer in both directions:
#
#   bound   -> the building measures this, so the decline was false: hand the series to the lane
#              that owns readings.
#   absent  -> the decline was RIGHT. No candidate, nothing reworded, nothing said.
#
# Nothing here reads a value, and nothing here decides which sensors answer a question.


#: A question that asks for a present state or a figure, as opposed to a planning or decision one.
_DIRECT_ASK_RE = re.compile(
    r"^\W*(?:is|are|was|were|do|does|did|can|could|has|have|any|how\s+(?:much|many|busy|warm|hot|"
    r"cold|full|long|often)|what(?:'s|\s+is|\s+are))\b",
    re.IGNORECASE,
)


def _stem5(word: str) -> str:
    """Five-letter stem with a negating prefix removed: 'unoccupied' and 'occupancy' meet."""
    return re.sub(r"^(?:un|in|non)(?=[a-z]{5})", "", word.lower())[:5]


def binding_is_about_question(
    question: str, concepts: Sequence[Dict[str, Any]], binding: Any
) -> bool:
    """True when the QUESTION's own words name the quantity the binder bound.

    The binder can bind a quantity from a word that only borrows it ('available' resolves to the
    empty-space concept, which binds occupancy). Naming that in a reply — "this building does
    measure occupancy" — to "Are there any accessibility features available near me?" is noise, and
    so are the energy-submeter clauses under a project-option and an AV-readiness question (tail J).
    Two things must both hold: the question is a direct ask for a state or a figure, and one of its
    words shares a stem with the bound quantity, its classes, or the classes of a concept the
    QUESTION resolved to.
    """
    if not _DIRECT_ASK_RE.search(question or ""):
        return False
    pool_text = " ".join(
        [str(getattr(binding, "quantity_label", "") or "")]
        + [str(c).replace("_", " ") for c in (getattr(binding, "classes", ()) or ())]
        + [
            str(c).replace("_", " ").replace(":", " ")
            for concept in concepts or []
            for c in (concept.get("brick_classes") or [])
        ]
    )
    # Raw words, not `content_terms`: its stemmer turns "parking" into "park", which is four letters.
    pool = {_stem5(t) for t in re.findall(r"[a-z]{5,}", pool_text.lower())}
    stops = {"there", "these", "those", "which", "where", "right", "about", "available"}
    return any(
        _stem5(t) in pool
        for t in re.findall(r"[a-z]{5,}", (question or "").lower())
        if t not in stops
    )


def sensor_candidate(binding: Any, question: str) -> Optional[Candidate]:
    """A candidate for a bound quantity, or None when the binder bound nothing.

    ``STATUS_ABSENT`` deliberately yields None: the binder has established that this place does
    not measure this quantity, which makes the original decline true. A second look that argued
    with it would be the false-absence defect pointed the other way.
    """
    if binding is None or not getattr(binding, "is_bound", False):
        return None
    sensors = list(getattr(binding, "sensors", ()) or ())
    series = [s for s in sensors if getattr(s, "uuid", "")]
    if not series:
        return None  # declared but with nothing to read: not a rescue, and never presented as one
    quantity = str(getattr(binding, "quantity_label", "") or "that quantity")
    basis = str(getattr(binding, "basis", "") or "")
    # A building-wide bind has no place, and the binder's display name for one is "that place" —
    # which in an answer reads as a room it declines to name. Say what it is: across the building.
    if basis == "population" or not str(getattr(binding, "scope_label", "") or ""):
        where = "across the building"
    else:
        where = f"at {str(getattr(binding, 'display_scope', '') or '')}".strip()
    return Candidate(
        kind="sensor",
        name=quantity,
        label=f"{quantity} {where}".strip() if where else quantity,
        tier="A",
        score=float(len(series)),
        shared=tuple(sorted({str(getattr(s, "quantity", "") or quantity) for s in series})),
        coverage=1.0,
        margin=float("inf"),
        evidence=(
            f"the building measures {quantity}"
            + (f" {where}" if where else "")
            + f": {len(series)} series bound"
            + (f" (from {basis})" if basis else "")
        ),
        payload=binding,
    )


# ── 6. the probe ────────────────────────────────────────────────────────────────────────────────

_CLASS_REF_RE = re.compile(r"ontosage:([A-Z][A-Za-z0-9]+)")


def stored_sources(results: Dict[str, Any]) -> List[str]:
    """Source ids the turn recorded in ``_prov_stores``, whichever shape a lane wrote them in.

    ``provenance.py`` documents the bus entry as a RAW STORE KEY (a string); the register lane
    writes a dict with a ``source_id``. Both are on the bus, and reading only the dict shape raised
    ``'str' object has no attribute 'get'`` on every turn that followed a WorkspaceProfile answer —
    the second look silently inactive on exactly the path it exists for, caught only because it
    fails safe and logs.
    """
    out: List[str] = []
    entries = results.get("_prov_stores")
    for entry in entries if isinstance(entries, (list, tuple)) else []:
        if isinstance(entry, str):
            out.append(entry)
        elif isinstance(entry, dict):
            out.append(str(entry.get("source_id") or ""))
    return out


def used_classes(results: Dict[str, Any]) -> Set[str]:
    """Register classes the failing lane already read, so a second look goes somewhere else."""
    used: Set[str] = set()
    for source in stored_sources(results):
        if source.startswith("ontosage:"):
            used.add(source.split(":", 1)[1])
    sparql = results.get("sparql_result")
    if isinstance(sparql, dict):
        used |= set(_CLASS_REF_RE.findall(str(sparql.get("query") or "")))
    return used


async def probe(
    question: str,
    shape: AbsenceShape,
    results: Dict[str, Any],
    reach: Reach,
    lane: Optional[str] = None,
    today: Optional[date] = None,
) -> List[Candidate]:
    """Candidates for where the building holds what the answer said it lacks, best first."""
    topic = topic_terms(question)
    if len(topic) < 2:
        return []
    object_terms = {t for t in topic_terms(shape.object_text) if t in topic}
    used = used_classes(results)
    found: List[Candidate] = []
    try:
        from orchestrator.services.record_registry import rank_record_classes

        classes = await reach.classes()
        ranked_all = rank_record_classes(question or "", list(classes)) if classes else []
        ranked = [(s, r) for s, r in ranked_all if r.local_name not in used][:MAX_SHORTLIST]
        if ranked:
            # What the failing lane already had: a second look must beat it, not repeat it.
            used_score = max((s for s, r in ranked_all if r.local_name in used), default=0.0)
            fetched = await reach.rows([r.local_name for _s, r in ranked])
            tables = {
                r.local_name: RegisterTable(
                    r.local_name,
                    r.label or r.local_name,
                    int(getattr(r, "instances", 0) or 0),
                    list(fetched.get(r.local_name) or []),
                )
                for _s, r in ranked
            }
            found += rank_registers(
                question, ranked, tables, topic, object_terms, used_score, today
            )
    except Exception as exc:
        logger.debug(f"[second_chance] register probe skipped: {describe_exception(exc)}")
    try:
        found += rank_text(topic, await reach.text_hits(topic), object_terms, question)
    except Exception as exc:
        logger.debug(f"[second_chance] text probe skipped: {describe_exception(exc)}")
    try:
        sensor = sensor_candidate(await reach.measurable(question, results), question)
        if sensor is not None:
            found.append(sensor)
    except Exception as exc:
        logger.debug(f"[second_chance] sensor probe skipped: {describe_exception(exc)}")
    if lane != "capability":  # the capability lane has already asked this resolver
        try:
            topic = topic_candidate(await reach.topics(question), question)
            if topic is not None:
                found.append(topic)
        except Exception as exc:
            logger.debug(f"[second_chance] topic probe skipped: {describe_exception(exc)}")
    order = {"A": 0, "B": 1}
    # A BOUND SERIES OUTRANKS A REGISTER. The binder has resolved the question's own quantity and
    # its own place against the graph; a register is a lexical match on the question's words. Where
    # both fire, the measurement is the better evidence about what the building holds.
    kinds = {"sensor": 0, "register": 1, "topic": 2, "text": 3}
    return sorted(found, key=lambda c: (order[c.tier], kinds[c.kind], -c.score, c.name))


MAX_TOPIC_QUESTION_WORDS = 12


def topic_candidate(facts: Sequence[Any], question: str = "") -> Optional[Candidate]:
    """A candidate for what the building's amenity / knowledge-topic triples say about the question.

    TWO GATES BEYOND THE RESOLVER'S OWN, both added after the first replay: the capability resolver
    matches on any distinctive lay term, so a long catalogue question about "suppression systems"
    was matched to the catering topic and a recycling question to the sustainability page — nine good
    answers replaced. A topic is a candidate only when the question is a DIRECT ask and a word of the
    topic's own LABEL is in the question ("accessibility features" -> the Accessibility topic).

    The capability resolver is the scorer the capability lane uses, over each amenity's own
    declared lay terms, and returns only on a strong match. A lane that never consulted it — the
    metadata lane told "Are there any accessibility features available near me?" that the building
    records none, while it records accessible toilets, lifts, step-free routes and a hearing loop —
    is exactly what a second look is for. Answered by the resolver's own ``render``, never by prose
    written here.
    """
    if question and not _DIRECT_ASK_RE.search(question):
        return None
    # A SHORT ask only. A word of a topic's label turns up by chance in a long catalogue question
    # ("the study intends to interpret" -> Quiet Study; "free-cooling hours" -> Working Hours), and
    # a question that long is about something the topic pages do not answer.
    if question and len(question.split()) > MAX_TOPIC_QUESTION_WORDS:
        return None
    asked = {_stem5(w) for w in re.findall(r"[a-z]{5,}", (question or "").lower())}
    usable = [
        f
        for f in facts or []
        if getattr(f, "label", "")
        and (f.answer or f.note or f.location)
        and (
            not question
            or asked & {_stem5(w) for w in re.findall(r"[a-z]{5,}", str(f.label).lower())}
        )
    ]
    if not usable:
        return None
    first = usable[0]
    return Candidate(
        kind="topic",
        name=str(first.label),
        label=str(first.label),
        tier="A",
        score=float(len(usable)),
        shared=tuple(str(f.label) for f in usable[:3]),
        coverage=1.0,
        margin=float("inf"),
        evidence=f"the building's own record names {len(usable)} matching amenity/topic entries",
        payload=usable,
    )


def topic_answer(candidate: Candidate) -> str:
    """The capability resolver's own rendering of the matched facts (at most three)."""
    facts = candidate.payload if isinstance(candidate.payload, list) else []
    return "\n\n".join(f.render() for f in facts[:3])


# ── 7. wording ──────────────────────────────────────────────────────────────────────────────────

_FOOTER_RE = re.compile(
    r"\n+\s*---\s*\n+(?:\*\*You might also ask:\*\*[^\n]*|\*Sources:[^\n]*)(?:\n+\s*---\s*\n+"
    r"(?:\*\*You might also ask:\*\*[^\n]*|\*Sources:[^\n]*))*\s*$",
    re.IGNORECASE,
)


def split_footer(text: str) -> Tuple[str, str]:
    """The answer body and its trailing suggestions / sources block."""
    m = _FOOTER_RE.search(text or "")
    return (text[: m.start()], text[m.start() :]) if m else (text or "", "")


def _and_list(items: Sequence[str], limit: int = 2) -> str:
    kept = list(dict.fromkeys(str(x).strip() for x in items if str(x).strip()))[:limit]
    if len(kept) <= 1:
        return kept[0] if kept else ""
    return ", ".join(kept[:-1]) + f" and {kept[-1]}"


_HAS_DETERMINER = re.compile(
    r"^(?:any|an?|the|this|that|these|those|my|our|your|their|its|no|some|each|every|all|"
    r"another|other|either|both|\d)\b",
    re.IGNORECASE,
)


def _with_a_determiner(obj: str) -> str:
    """``obj`` ready to follow "did not find": "answer" -> "any answer".

    `_clean_object` strips a leading article so the phrase can be compared with the question, which
    left "I did not find answer in the records I searched" (four live answers). "any" is right after
    a negative for a singular, a plural or a mass noun alike. A proper name ("Room 5.01") and a
    phrase that already carries a determiner are left exactly as they were.
    """
    text = (obj or "").strip()
    if not text or _HAS_DETERMINER.match(text) or not text[0].islower():
        return text
    return f"any {text}"


def scoped_sentence(shape: AbsenceShape, searched: str, closest: Sequence[Candidate]) -> str:
    """'I did not find X in what I searched; closest: Y' in place of 'the building has no X'."""
    obj = _without_a_leading_verb(shape.object_text)
    if not obj:
        what = "that"
    elif _INTERROG_HEAD.match(obj):
        what = f"a record that settles {obj}"
    else:
        what = _with_a_determiner(obj)
    sentence = balance_quotes(f"I did not find {what} in {searched or 'the records I searched'}.")
    # A MEASURED QUANTITY IS SAID FIRST AND DIFFERENTLY. That the building measures something is a
    # fact the binder established against the graph, not a suggestion of where to look next, and it
    # is the half of the answer the reader of "the register does not record whether devices are
    # left on" most needed: the building does measure it.
    measured = [c for c in closest if c.kind == "sensor"]
    if measured:
        first = measured[0]
        series = int(first.score) or len(first.shared)
        # ONE plain clause (wave 7): this sentence appeared on nine of sixty-two answers, and the
        # longer form ("so the limitation is what I read, not what it senses ...") was the same
        # message said twice.
        sentence += f" This building **does** measure {first.label} ({series} series); ask for it."
        return sentence
    names = [
        (
            f"{c.label} records"
            if c.kind == "register"
            else (
                f"the building's {c.label} information"
                if c.kind == "topic"
                else f"the building's record of {c.label}"
            )
        )
        for c in closest
    ]
    near = _and_list(names)
    if near:
        sentence += f" The closest this building keeps is {near}, which I can read for you."
    return sentence


#: How much of the question a candidate must carry before the answer NAMES it as the closest
#: thing. A pointer is a promise that reading it would help, and a weak one spends the reader's
#: time: measured on the development reads, below this the named register is things like an
#: approvals register for a refuge-point question. The scoping half of the sentence — which is the
#: part that stops the false universal — is stated either way.
MIN_POINTER_COVERAGE = 0.3


#: A label that is an internal identifier rather than a name: `policy_facility_manager_any`,
#: `WCP-017`, a uuid. Naming one at a reader is the defect the recurrence table was just repaired
#: for — an identifier printed where a place or a record's name belongs.
_IDENTIFIER_LABEL_RE = re.compile(r"^[a-z0-9]+(?:[_-][a-z0-9]+)+$|^[0-9a-f-]{12,}$", re.IGNORECASE)


def useful_pointer(candidate: Candidate) -> bool:
    """True when naming this candidate tells the reader somewhere worth reading."""
    label = (candidate.label or "").strip()
    if not label or _IDENTIFIER_LABEL_RE.match(label):
        return False
    if candidate.kind == "sensor":
        return True  # the binder proved the series exist; this is a fact, not a suggestion
    return candidate.coverage >= MIN_POINTER_COVERAGE and (
        candidate.kind != "register" or "0 of the question's conditions" not in candidate.evidence
    )


def reword_absence(
    answer: str, shape: AbsenceShape, closest: Sequence[Candidate], searched: str = ""
) -> Optional[str]:
    """The answer with only its false universal rewritten into a scoped statement, or None."""
    if not shape.reword or not shape.segment or not closest:
        return None
    pointers = [c for c in closest if useful_pointer(c)]
    text = answer.replace(shape.segment, scoped_sentence(shape, searched, pointers), 1)
    if text == answer or names_internal_vocabulary(text):
        return None
    return text


# ── 8. one look ─────────────────────────────────────────────────────────────────────────────────

Answerer = Callable[[Candidate, str], Awaitable[Optional[str]]]


@dataclass
class Answerers:
    """The lane answerers a candidate may be handed to. At most ONE is called, once."""

    register: Optional[Answerer] = None
    text: Optional[Answerer] = None
    #: The lane that owns readings. This module never composes one: it hands over the bound series
    #: and publishes only what that lane returns.
    sensor: Optional[Answerer] = None
    topic: Optional[Answerer] = None

    def for_kind(self, kind: str) -> Optional[Answerer]:
        return {
            "register": self.register,
            "text": self.text,
            "sensor": self.sensor,
            "topic": self.topic,
        }.get(kind)


@dataclass
class Replacement:
    """What to show instead of the original answer, and why."""

    text: str
    reopened: bool
    kind: str
    candidate: Optional[Candidate]
    shape: AbsenceShape
    detail: Dict[str, Any] = field(default_factory=dict)

    def record(self) -> Dict[str, Any]:
        """The audit line kept on the state bus."""
        cand = self.candidate
        return {
            "outcome": "reopened" if self.reopened else "reworded",
            "absence_kind": self.shape.kind,
            "candidate": (
                {"kind": cand.kind, "name": cand.name, "label": cand.label} if cand else None
            ),
            "evidence": cand.evidence if cand else "",
            **self.detail,
        }


def acceptable(text: Optional[str]) -> bool:
    """A lane result may replace a decline only when it is a grounded, non-absence answer."""
    if not text or len(text.strip()) < 20:
        return False
    if meta_answer_reason(text) or names_internal_vocabulary(text):
        return False
    shape = detect_absence_shape(text)
    return shape is None or not shape.leads


async def absence_second_chance(
    question: str,
    answer: str,
    lane: Optional[str],
    state: Any,
    *,
    reach: Optional[Reach] = None,
    answerers: Optional[Answerers] = None,
    searched: str = "",
    today: Optional[date] = None,
) -> Optional[Replacement]:
    """A replacement for a false-absence answer, or None when the answer stands as written.

    Idempotent: the record it leaves on the bus stops a second pass over the same turn.
    """
    if not enabled():
        return None
    results = getattr(state, "intermediate_results", None)
    if not isinstance(results, dict) or results.get("second_chance"):
        return None
    shape = detect_absence_shape(answer)
    if shape is None:
        return None
    why = skip_reason(results, lane, question, answer)
    if why:
        results["second_chance"] = {"outcome": "skipped", "why": why}
        logger.info(f"[second_chance] not reopened: {why}")
        return None
    # THE CLAIM MUST BE THE ANSWER, NOT A CAVEAT INSIDE ONE.
    #
    # Measured on the replay: "Which postings need an owner check for coding?" answers the question
    # correctly, lists the three postings, and then says the register holds no project or activity
    # coding — which is true. Acting on that sentence replaced a good answer with a lookup that
    # covered less of the question. An absence that opens an answer IS the answer and is fair game;
    # one that qualifies an answer already given is not this module's business.
    if not shape.leads:
        results["second_chance"] = {"outcome": "skipped", "why": "the absence qualifies an answer"}
        return None
    if reach is None:
        return None
    try:
        found = await asyncio.wait_for(
            probe(question, shape, results, reach, lane, today), BUDGET_SECONDS
        )
    except Exception as exc:  # a look that cannot finish leaves the answer exactly as it was
        logger.warning(f"[second_chance] probe failed: {describe_exception(exc)} at {_where(exc)}")
        return None
    if not found:
        results["second_chance"] = {"outcome": "no_candidate"}
        return None
    best = found[0]
    detail: Dict[str, Any] = {"candidates": [f"{c.kind}:{c.name}:{c.tier}" for c in found[:3]]}
    if best.tier == "A" and shape.opens and answerers is not None:
        call = answerers.for_kind(best.kind)
        if call is not None:
            try:  # exactly one extra lane call, and never a second candidate
                text = await asyncio.wait_for(call(best, question), BUDGET_SECONDS)
            except Exception as exc:
                logger.debug(f"[second_chance] lane call failed: {describe_exception(exc)}")
                text = None
            if acceptable(text):
                logger.warning(
                    f"[second_chance] a false absence was reopened from {best.kind} "
                    f"{best.name!r}: {best.evidence}"
                )
                return Replacement(str(text).strip(), True, best.kind, best, shape, detail)
            detail["reopen"] = "the lane did not return a grounded answer"
    reworded = reword_absence(answer, shape, found[:2], searched)
    if reworded:
        logger.info(f"[second_chance] absence scoped to what was searched; closest {best.name!r}")
        return Replacement(reworded, False, "scoped", best, shape, detail)
    results["second_chance"] = {"outcome": "kept", **detail}
    return None


# ── 8b. false statements of NON-EXISTENCE ────────────────────────────────────────────────────────
#
# The worst class in the 2026-09-20 read (tail G) is not a decline but a FALSE ASSERTION, which a
# reader believes: "This building does not have occupancy sensors" (467 occupancy series exist),
# "'car parking' does not exist in this building" (a ParkingArea exists), "the building does not
# track embodied carbon" said from one irrelevant approval record. None of these has the SHAPE of a
# failed lookup, so `absence_second_chance` — which needs an absence-led answer — never looks.
#
# This check needs nothing of the answer's shape. ANY sentence that says the building lacks <X> is
# resolved: if <X> is something the building HOLDS — measured, offered as an amenity, or kept as a
# register — the sentence is rewritten to the scoped form. It rewrites and never replaces: the rest
# of the answer is the lane's, and a rescue that re-answered would need the lane's evidence.
#
# It is deliberately conservative in what counts as "held": every content word of <X> has to be
# accounted for by the thing found, so "embodied carbon" is not held by a carbon-monoxide sensor.

_LACK_VERB = (
    r"(?:have|has|track|tracks|record|records|measure|measures|monitor|monitors|hold|holds|keep|"
    r"keeps|contain|contains|include|includes|offer|offers|provide|provides)"
)
_LACKS: Tuple[Tuple[str, "re.Pattern[str]"], ...] = (
    (
        "does_not_have",
        re.compile(
            r"\b(?:this|the)\s+building\s+(?:does\s*n[o']t|doesn't|does\s+not|has\s+not|hasn't)\s+"
            rf"(?:currently\s+)?{_LACK_VERB}\s+(?:any\s+|an?\s+|the\s+|dedicated\s+)?"
            r"(?P<x>[^.\n,;:()]{3,70})",
            re.IGNORECASE,
        ),
    ),
    (
        "has_no",
        re.compile(
            r"\b(?:this|the)\s+building\s+(?:currently\s+)?has\s+no\s+(?:dedicated\s+)?"
            r"(?P<x>[^.\n,;:()]{3,70})",
            re.IGNORECASE,
        ),
    ),
    (
        "does_not_exist",
        re.compile(
            r"['\"‘’“”]?(?P<x>[^'\"‘’“”.\n]{3,50})['\"‘’“”]?\s+does\s+not\s+exist\s+in\s+this\s+"
            r"building",
            re.IGNORECASE,
        ),
    ),
)

#: Words that say a thing is a sensing device and not what it senses.
_DEVICE_WORDS = frozenset(
    "sensor sensors meter meters detector detectors monitor monitors device devices system "
    "systems equipment data reading readings point points".split()
)

#: A sentence that states a RESULT, or names a place by id, or a threshold: not a claim about kind.
_NOT_A_KIND_CLAIM_RE = re.compile(
    r"\d+\.\d+|\b(?:above|below|over|under|exceed\w*|currently|right\s+now|today|tonight|"
    r"booked|free|available|vacant|occupied|open)\b",
    re.IGNORECASE,
)


@dataclass(frozen=True)
class Held:
    """Something the building demonstrably holds that a sentence said it lacks."""

    kind: str  # sensor | amenity | register
    label: str
    count: int = 0


@dataclass(frozen=True)
class LackClaim:
    """One sentence asserting that the building lacks something."""

    kind: str
    segment: str
    subject: str


def find_lack_claims(answer: str) -> List[LackClaim]:
    """Sentences of the form 'this building does not have / has no / X does not exist'."""
    found: List[LackClaim] = []
    for seg in _segments(answer or ""):
        plain = plain_prose(seg)
        if _NOT_A_KIND_CLAIM_RE.search(plain):
            continue
        for kind, pattern in _LACKS:
            m = pattern.search(plain)
            if not m:
                continue
            subject = _clean_object(m.group("x"))
            words = [w for w in content_terms(subject) if w not in _DEVICE_WORDS]
            if words and len(subject.split()) <= 8:
                found.append(LackClaim(kind, seg, subject))
            break
    return found[:3]


def lack_terms(subject: str) -> List[str]:
    """The words of a claimed-missing thing that name WHAT it is, not what kind of device it is."""
    return sorted(t for t in content_terms(subject) if t not in _DEVICE_WORDS)


def scoped_lack(claim: LackClaim, held: Held) -> str:
    """The honest form of 'the building has no X' when the building holds something answering to X."""
    lead = balance_quotes(f"I did not find {claim.subject} in the records I searched.")
    if held.kind == "sensor":
        series = f" ({held.count} series)" if held.count else ""
        return f"{lead} This building **does** measure {held.label}{series}; ask for it."
    if held.kind == "amenity":
        return f"{lead} This building does keep {held.label}."
    return f"{lead} This building does keep {held.label} records, which I can read for you."


async def rewrite_false_existence(
    answer: str, reach: "Reach", question: str = ""
) -> Tuple[str, List[Dict[str, Any]]]:
    """``answer`` with every provably false 'the building lacks X' rewritten, and what changed."""
    claims = find_lack_claims(answer)
    text, changes = answer, []
    for claim in claims:
        try:
            held = await reach.holds(claim.subject)
        except Exception as exc:  # an unreadable graph leaves the sentence exactly as it was
            logger.debug(f"[second_chance] holds() failed: {describe_exception(exc)}")
            held = None
        if held is None:
            continue
        new = scoped_lack(claim, held)
        if names_internal_vocabulary(new):
            continue
        text = text.replace(claim.segment, new, 1)
        changes.append(
            {
                "claimed_missing": claim.subject,
                "held": held.label,
                "kind": held.kind,
                "how": claim.kind,
            }
        )
    return text, changes


# ── 9. the live reach and the live answerers ────────────────────────────────────────────────────


class GraphReach(Reach):
    """The probe's reads against the building's own graph: ≤ 6 bounded queries, all read-only."""

    def __init__(
        self,
        sparql_exec: Callable[[str], Awaitable[Dict[str, Any]]],
        namespace: str,
        building_id: Optional[str] = None,
    ):
        self._exec = sparql_exec
        self._namespace = namespace
        self._bid = building_id

    async def topics(self, question: str) -> List[Any]:
        """The capability resolver's own matches, read through this reach's graph executor."""
        from orchestrator.services.capability_graph_resolver import CapabilityGraphResolver

        return await CapabilityGraphResolver(self._exec).resolve(question)

    async def holds(self, subject: str) -> Optional[Held]:
        """Sensor, then amenity, then register: the first that accounts for the whole subject."""
        terms = lack_terms(subject)
        if not terms:
            return None
        return (
            await self._held_sensor(subject, terms)
            or await self._held_amenity(subject)
            or await self._held_register(subject, terms)
        )

    async def _held_sensor(self, subject: str, terms: List[str]) -> Optional[Held]:
        """A measured quantity, when the concept the subject resolves to covers EVERY content word.

        "occupancy sensors" resolves to occupancy and is covered; "embodied carbon" resolves to
        carbon monoxide and is not — `embodied` belongs to no concept — so a claim that the building
        does not track embodied carbon is left exactly as it was.
        """
        from orchestrator.services.concept_resolver import concept_resolver
        from orchestrator.services.sensor_binder import bind_sensors

        matches = await concept_resolver.resolve(subject) or []
        concepts = [m.to_dict() if hasattr(m, "to_dict") else m for m in matches]
        if not concepts:
            return None
        binding = await bind_sensors(
            subject, [], concepts, self._exec, self._namespace, self._bid, True
        )
        if not getattr(binding, "is_bound", False):
            return None
        covered = {
            fold(t)
            for c in concepts
            for t in content_terms(f"{c.get('lay_term', '')} {c.get('concept_id', '')}")
        } | {fold(t) for t in content_terms(str(getattr(binding, "quantity_label", "")))}
        if not all(fold(t) in covered for t in terms):
            return None
        sensors = [s for s in binding.sensors if getattr(s, "uuid", "")]
        if not sensors:
            return None
        return Held("sensor", str(binding.quantity_label), len(sensors))

    async def _held_amenity(self, subject: str) -> Optional[Held]:
        """A kind the building OFFERS: an instance typed with an ontosage class named by the head.

        The head is the subject's LAST word as written ("car parking" -> "parking"), not a stem: the
        stemmer turns "parking" into "park", which is not a word of "ParkingArea". Record classes
        are excluded — a work order is a record the register arm reports, not an amenity — so a
        claim about "work orders" is never answered with a record's label.
        """
        # The head is the last word that says WHAT, not what kind of device: "radiation sensors" is
        # about radiation, and matching "sensor" would name a soil-moisture sensor as the answer.
        words = [w for w in re.findall(r"[a-z0-9]+", subject.lower()) if w not in _DEVICE_WORDS]
        head = re.sub(r"s$", "", words[-1]) if words else ""
        if len(head) < 4:
            return None
        query = (
            "PREFIX rdfs: <http://www.w3.org/2000/01/rdf-schema#>\n"
            "PREFIX o: <http://ontosage.org/capabilities#>\n"
            "SELECT ?s ?l ?cls WHERE {\n"
            "  ?s a ?cls .\n"
            '  FILTER(STRSTARTS(STR(?cls), "http://ontosage.org/capabilities#"))\n'
            "  FILTER NOT EXISTS { VALUES ?root { o:Record o:IntervalRecord } "
            "?cls rdfs:subClassOf+ ?root }\n"
            # A sensor class is a MEASUREMENT, which the sensor arm owns; naming one as an amenity
            # said the building "keeps" a parking-occupancy point in place of the parking it has.
            '  FILTER(!REGEX(STR(?cls), "(Sensor|Meter|Detector|Point|Status)$"))\n'
            '  BIND(LCASE(REPLACE(REPLACE(STR(?cls), "^.*#", ""), "([a-z])([A-Z])", "$1 $2")) AS ?w)\n'
            f'  FILTER(REGEX(?w, "(^|[^a-z0-9]){head}s?([^a-z0-9]|$)"))\n'
            "  OPTIONAL { ?s rdfs:label ?l }\n"
            "} LIMIT 3"
        )
        rows = (await self._exec(query) or {}).get("results", {}).get("bindings", [])
        # EVERY content word must be accounted for by the amenity's own label and class name.
        # Measured on the replay: "'underground parking' does not exist" — a TRUE statement, the
        # building's parking is at ground level — was rewritten to "does keep Ground Level Parking"
        # because the head matched and the modifier was ignored. A modifier is not decoration: it
        # can be the very thing that is absent. (The "car parking" refusal that motivated this is
        # fixed where it is made, in the referent gate, which steps aside for an amenity kind.)
        needed = {fold(t) for t in lack_terms(subject)}
        for row in rows:
            cls_local = str((row.get("cls") or {}).get("value", "")).rsplit("#", 1)[-1]
            label = (row.get("l") or {}).get("value") or cls_local
            words = re.sub(r"(?<=[a-z])(?=[A-Z])", " ", cls_local) + " " + label
            if needed <= {fold(t) for t in content_terms(words)}:
                return Held("amenity", re.sub(r"\s+[—-]\s+.*$", "", label).strip(), len(rows))
        return None

    async def _held_register(self, subject: str, terms: List[str]) -> Optional[Held]:
        """A register the router's own selector names for the subject, covering every content word."""
        from orchestrator.services.record_registry import rank_record_classes

        classes = await self.classes()
        ranked = rank_record_classes(subject, list(classes)) if classes else []
        if not ranked:
            return None
        record = ranked[0][1]
        named = {fold(t) for w in _named_terms(record, subject) for t in content_terms(w)}
        if not all(fold(t) in named for t in terms):
            return None
        return Held("register", str(record.label or record.local_name), int(record.instances or 0))

    async def measurable(self, question: str, results: Dict[str, Any]) -> Any:
        """``sensor_binder.bind_sensors`` for this question, with the turn's own concepts.

        The concepts come off the bus when the concept resolver already ran this turn, and are
        resolved here only when it did not — the resolver owns the lay-term vocabulary Agent K
        widened, and asking it twice for one turn would be two answers to one question.
        """
        from orchestrator.services.sensor_binder import bind_sensors

        concepts = list(results.get("concepts") or [])
        if not concepts:
            try:
                from orchestrator.services.concept_resolver import concept_resolver

                matches = await concept_resolver.resolve(question) or []
                concepts = [m.to_dict() if hasattr(m, "to_dict") else m for m in matches]
            except Exception as exc:
                logger.debug(f"[second_chance] concepts unavailable: {describe_exception(exc)}")
                concepts = []
        entities = [e for e in (results.get("entities") or []) if isinstance(e, str)]
        binding = await bind_sensors(
            question,
            entities,
            concepts,
            self._exec,
            self._namespace,
            self._bid,
            # The building-wide population IS allowed here, and the binder owns the guard rails:
            # it uses one only for an ask that names no single place, never to widen a question
            # that named one, and it refuses a population too large to read. Without it the arm
            # missed exactly the questions it was built for — "are my windows leaking heat right
            # now?" names a quantity and no place, so the binder stepped aside and the false
            # absence stood.
            allow_population=True,
        )
        # A bound quantity the question's own words do not name is not evidence about the question.
        return binding if binding_is_about_question(question, concepts, binding) else None

    async def classes(self) -> List[Any]:
        """The record classes the active building holds — the registry's own cached read."""
        from orchestrator.services.record_registry import record_classes

        return await record_classes()

    async def rows(self, names: Sequence[str]) -> Dict[str, List[Dict[str, Any]]]:
        tables: Dict[str, List[Dict[str, Any]]] = {}
        for name in list(names)[:MAX_SHORTLIST]:
            query = (
                "PREFIX rdf: <http://www.w3.org/1999/02/22-rdf-syntax-ns#>\n"
                "PREFIX ontosage: <http://ontosage.org/capabilities#>\n"
                "SELECT ?record ?p ?v WHERE {\n"
                "  { SELECT DISTINCT ?record WHERE { ?record a ontosage:%s }\n"
                f"    ORDER BY ?record LIMIT {MAX_PROBE_ROWS} }}\n"
                "  ?record ?p ?v . FILTER(?p != rdf:type)\n"
                "} ORDER BY ?record" % name
            )
            try:
                result = await self._exec(query)
            except Exception as exc:
                logger.debug(
                    f"[second_chance] rows for {name} unavailable: {describe_exception(exc)}"
                )
                continue
            pivot: Dict[str, Dict[str, Any]] = {}
            for binding in (result or {}).get("results", {}).get("bindings", []):
                subject = (binding.get("record") or {}).get("value", "")
                predicate = (binding.get("p") or {}).get("value", "")
                if not subject or not predicate:
                    continue
                column = predicate.rsplit("#", 1)[-1].rsplit("/", 1)[-1]
                value = (binding.get("v") or {}).get("value", "")
                row = pivot.setdefault(subject, {"record": subject})
                row[column] = f"{row[column]}, {value}" if column in row else value
            if pivot:
                tables[name] = list(pivot.values())
        return tables

    async def text_hits(self, topic: Sequence[str]) -> List[TextHit]:
        query = text_query(self._namespace, topic)
        if not query:
            return []
        try:
            result = await self._exec(query)
        except Exception as exc:
            logger.debug(f"[second_chance] prose unavailable: {describe_exception(exc)}")
            return []
        hits: List[TextHit] = []
        for binding in (result or {}).get("results", {}).get("bindings", []):
            hits.append(
                TextHit(
                    (binding.get("s") or {}).get("value", ""),
                    (binding.get("label") or {}).get("value", ""),
                    (binding.get("p") or {}).get("value", ""),
                    (binding.get("text") or {}).get("value", ""),
                )
            )
        return hits


def register_answer(candidate: Candidate, question: str, today: Optional[date] = None) -> str:
    """The register lane's OWN answer for this candidate, composed from its rows, or "".

    ``register_projection.deterministic_answer`` is that lane's answerer: it projects the records
    the question resolves to and refuses (returns "") on any doubt — a word it could not place, a
    field the register does not hold, rows that are not the whole register. No model is asked,
    which is deliberate: a narration invited to rescue a decline is exactly where the invented
    conclusions in this defect class come from.
    """
    from orchestrator.services import register_projection as rp

    table = candidate.payload
    if not isinstance(table, RegisterTable) or not table.rows:
        return ""
    text = rp.deterministic_answer(table.rows, question, table.label, today, table.partial)
    if not text:
        return ""
    held = (
        f"{len(table.rows)} of the building's {table.instances} {table.label} records"
        if table.partial
        else f"all {table.instances or len(table.rows)} of the building's {table.label} records"
    )
    return f"{text}\n\n_Read from {held}._"


_SENTENCE_RE = re.compile(r"[^.!?\n]+[.!?]?")


def text_answer(candidate: Candidate, question: str) -> str:
    """The building's own sentence about this record, quoted with its source, or "".

    Quoted, never paraphrased: the value of an authored record is that somebody is accountable for
    its words, and a paraphrase of a fact is a new claim with no owner.
    """
    hit = candidate.payload
    if not isinstance(hit, TextHit) or not hit.text:
        return ""
    wanted = [fold(t) for t in candidate.shared]
    picked = [
        s.strip()
        for s in _SENTENCE_RE.findall(hit.text)
        if s.strip() and any(w in s.lower() for w in wanted)
    ][:2]
    if not picked:
        return ""
    label = candidate.label or "this record"
    return (
        f"From the building's record of **{label}**:\n\n"
        + " ".join(picked)
        + (f"\n\n_Recorded against {label} in the building's own model._")
    )


async def readings_answer(candidate: Candidate, question: str) -> str:
    """Hand the bound series to the lane that owns readings, and publish only what it says.

    ``aggregate_lane.try_answer`` computes in the store and writes its text in code, including the
    boundary line naming which sensors and which window — which is exactly why it is the handoff:
    nothing here reads, rounds, or narrates a value. It returns None for a question it cannot
    answer completely and honestly, and then this returns "" and the decline stands (reworded to
    say the building does measure the quantity, which the binder established).
    """
    binding = candidate.payload
    sensors = [s for s in (getattr(binding, "sensors", ()) or ()) if getattr(s, "uuid", "")]
    if not sensors:
        return ""
    try:
        from shared.config import settings

        from orchestrator.services import aggregate_lane
        from orchestrator.services.adapters.registry import adapter_registry
        from orchestrator.services.deliberation.live import sparql_exec

        result = await aggregate_lane.try_answer(
            question=question,
            uuids=[s.uuid for s in sensors],
            storage_map={s.uuid: s.storage for s in sensors if s.storage},
            metadata={
                s.uuid: {"label": s.label, "kind": s.quantity, "sensor_uri": s.iri} for s in sensors
            },
            start_date=None,
            end_date=None,
            # The budget is what refused these questions in the first place; the aggregate lane
            # exists for exactly that case and answers it in the store.
            budget_hit=True,
            tz_name=getattr(settings, "BUILDING_TIMEZONE", None),
            adapter_for=lambda uri: adapter_registry._adapters.get(
                adapter_registry._resolve_storage_key(uri or "")
            ),
            store_key=adapter_registry._resolve_storage_key,
            sparql_exec=sparql_exec,
        )
    except Exception as exc:  # the readings lane is the addition; it must not cost the answer
        logger.warning(f"[second_chance] readings lane skipped: {describe_exception(exc)}")
        return ""
    text = str((result or {}).get("formatted_response") or "") if isinstance(result, dict) else ""
    return text


def graph_answerers(today: Optional[date] = None) -> Answerers:
    """The three answerers the live hook passes: none of them calls a model."""

    async def _register(candidate: Candidate, question: str) -> Optional[str]:
        return register_answer(candidate, question, today) or None

    async def _text(candidate: Candidate, question: str) -> Optional[str]:
        return text_answer(candidate, question) or None

    async def _sensor(candidate: Candidate, question: str) -> Optional[str]:
        return await readings_answer(candidate, question) or None

    async def _topic(candidate: Candidate, question: str) -> Optional[str]:
        return topic_answer(candidate) or None

    return Answerers(register=_register, text=_text, sensor=_sensor, topic=_topic)


def _where(exc: BaseException) -> str:
    """The innermost frame of an exception as ``file:line in function`` — enough to diagnose a
    skipped second look from the log alone, which a bare exception message never was."""
    import traceback

    frames = traceback.extract_tb(exc.__traceback__)
    if not frames:
        return "unknown location"
    last = frames[-1]
    return f"{last.filename.rsplit('/', 1)[-1].rsplit(chr(92), 1)[-1]}:{last.lineno} in {last.name}"


def searched_phrase(results: Dict[str, Any]) -> str:
    """What the failing lane actually looked at, in the reader's words.

    Named from the evidence the turn left behind, never assumed: a scoped statement is only an
    improvement on a false universal if the scope it names is the true one.
    """
    labels = []
    for source in stored_sources(results):
        if source.startswith("ontosage:"):
            name = source.split(":", 1)[1]
            labels.append(re.sub(r"(?<!^)(?=[A-Z])", " ", name).lower())
    if labels:
        return "the building's " + _and_list(sorted(set(labels))) + " records"
    return ""


#: Lanes that make deliberate, typed decisions and are never rewritten, whatever their text says.
_NEVER_REWRITTEN_LANES = frozenset({"control", "privacy_refusal", "greeting", "clarification"})


async def correct_false_existence(
    state: Any, answer: str, lane: Optional[str], question: str, reach: "Reach"
) -> Tuple[str, List[Dict[str, Any]]]:
    """Rewrite provably false 'the building lacks X' sentences; leave every true absence alone.

    The referent gate's own refusal IS examined here (it is upstream, and its sentence is exactly
    what a reader must not be told falsely) — but only rewritten when the building demonstrably
    holds what the sentence calls missing. Privacy, control, disclosure and observability results
    are never touched, and a question about individuals is never reached for.
    """
    results = getattr(state, "intermediate_results", None)
    if not isinstance(results, dict) or lane in _NEVER_REWRITTEN_LANES:
        return answer, []
    for key, _why in _TYPED_KEYS:
        if key != "referent_refusal_result" and results.get(key):
            return answer, []
    if _PRIVATE_ASK_RE.search(question or "") or _NOT_MEASURED_RE.search(plain_prose(answer or "")):
        return answer, []
    if not find_lack_claims(answer):
        return answer, []
    return await rewrite_false_existence(answer, reach, question)


async def apply_to_answer(
    state: Any,
    answer: str,
    *,
    lane: Optional[str] = None,
    sparql_exec: Optional[Callable[[str], Awaitable[Dict[str, Any]]]] = None,
    namespace: str = "",
    today: Optional[date] = None,
) -> str:
    """The hook's whole job: the answer to publish, unchanged unless a second look found better.

    Everything that can go wrong is contained here: with the flag off, no executor, no absence
    claim or no candidate, the caller's text is returned untouched.
    """
    results = getattr(state, "intermediate_results", None)
    if not enabled() or not answer or sparql_exec is None or not isinstance(results, dict):
        return answer
    question = str(results.get("original_query") or getattr(state, "user_message", "") or "")
    if not question:
        return answer
    reach = GraphReach(sparql_exec, namespace, getattr(state, "building_id", None))
    # FALSE NON-EXISTENCE FIRST, and independent of the answer's shape: a reader believes "this
    # building does not have occupancy sensors" far more readily than a decline.
    try:
        answer, changes = await correct_false_existence(state, answer, lane, question, reach)
        if changes:
            results["false_existence"] = changes
    except Exception as exc:
        logger.warning(
            f"[second_chance] false-existence check skipped: {describe_exception(exc)} at {_where(exc)}"
        )
    try:
        replacement = await absence_second_chance(
            question,
            answer,
            lane,
            state,
            reach=reach,
            answerers=graph_answerers(today),
            searched=searched_phrase(results),
            today=today,
        )
    except Exception as exc:  # a second look must never cost the first answer
        logger.warning(f"[second_chance] skipped: {describe_exception(exc)} at {_where(exc)}")
        return answer
    if replacement is None:
        return answer
    results["second_chance"] = replacement.record()
    return replacement.text
