# -*- coding: utf-8 -*-
"""Which retrieved passages may answer a question, and which document text is not an answer at all.

Two defects in the document lane, both measured on the 2026-09-18 held-out reads, share this
module because they are the same fault seen from either end: *text that is not about the
question is presented as the answer*.

1. **Authoring commentary is indexed.** Every register document opens with a section written for
   the person who BUILT the register ("Three duty columns, not one ...", "Why every row carries a
   survey date"). It is developer commentary about design, not a fact about the building, yet it
   is embedded beside the table and retrieved for questions like "what design choices were
   made?". :func:`strip_authoring_commentary` removes those sections before indexing, and
   :func:`drop_commentary_hits` removes them from an index built before that existed, so the fix
   does not wait for a re-embed.

2. **One shared word is enough.** ``grounding_guard.is_on_topic`` keeps a passage that shares a
   single distinctive term with the question, so a cost-line quote answered a question about how
   readings are aggregated. :func:`assess` asks for more: the passage must cover a fair share of
   the question's content terms, or name the document the question is about, or clear the
   retrieval floor by a margin. A passage that does none of these is not an answer, and the lane
   declines instead of quoting it.

Building-agnostic: nothing here names a building, a register or a sensor. Headings are matched by
the SHAPE of what they say about themselves ("why this register ...", "what this register
records ..."), and terms come from the question and the passage.
"""

from __future__ import annotations

import os
import re
from dataclasses import dataclass, field
from functools import lru_cache
from pathlib import Path
from typing import Any, Dict, Iterable, List, Optional, Sequence, Set, Tuple

from orchestrator.services.grounding_guard import GENERIC_TERMS, content_terms
from shared.utils import get_logger

logger = get_logger(__name__)

# ── authoring commentary ─────────────────────────────────────────────────────────────────────

#: Headings that talk about the register/document ITSELF rather than about the building. Matched
#: on the heading text alone: the sections they open are prose written for the person who built
#: the register, and a "design rationale" is never the answer to a stakeholder's question.
#:
#: Deliberately NOT matched: legends and definitions ("Grades", "How to read the fail state",
#: "How cost is computed", "What a visitor needs to know") -- those explain the building's own
#: data to a reader, and a question about them has a right to be answered from them.
_AUTHORING_HEADING_RES: Tuple["re.Pattern[str]", ...] = tuple(
    re.compile(p, re.IGNORECASE)
    for p in (
        r"^why\b",
        r"^what (?:this|the|these) (?:register|registers|records?|document|documents)\b",
        r"^what this (?:is|makes|decides|does)\b",
        r"^what an? [\w \-]{2,40} is for\b",
        r"^what changed\b",
        r"^how (?:a|the|this) [\w \-]{0,30}(?:register|shift|balance|target|record)\b[\w ,\-]*"
        r"\b(?:is read|reads?|is used|works)\b",
        r"^how to read (?:this|the) (?:register|table|document)\b",
        r"\bdesign (?:choices?|decisions?|rationale|notes?)\b",
        r"^notes? for (?:authors|maintainers|editors)\b",
        r"\bare (?:two|three|four|five) different (?:answers|things|facts)\b",
    )
)

_HEADING_RE = re.compile(r"^(#{1,6})[ \t]+(.+?)[ \t]*#*[ \t]*$")
_FRONT_MATTER_RE = re.compile(r"\A﻿?---[ \t]*\r?\n.*?\r?\n---[ \t]*(?:\r?\n|\Z)", re.DOTALL)

#: The same front matter after the indexer flattened the file into single-spaced words.
_FLAT_FRONT_MATTER_RE = re.compile(r"\A\s*---\s+(?:[\w\-]+:.*?)\s---(?:\s|\Z)", re.DOTALL)


def is_authoring_heading(heading: str) -> bool:
    """True when a heading opens a section about the document itself, not about the building."""
    text = re.sub(r"[*_`]", "", str(heading or "")).strip()
    return any(rx.search(text) for rx in _AUTHORING_HEADING_RES)


@dataclass
class Section:
    """One heading-delimited part of a markdown document."""

    level: int
    heading: str
    body: str
    start: int  # line index of the heading
    end: int  # line index one past the last body line


def split_sections(text: str) -> List[Section]:
    """Heading-delimited sections; a section runs until the next heading of its level or higher."""
    lines = (text or "").splitlines()
    heads: List[Tuple[int, int, str]] = []
    fenced = False
    for i, line in enumerate(lines):
        if line.lstrip().startswith("```"):
            fenced = not fenced
            continue
        if fenced:
            continue
        m = _HEADING_RE.match(line)
        if m:
            heads.append((i, len(m.group(1)), m.group(2).strip()))
    sections: List[Section] = []
    for idx, (line_no, level, heading) in enumerate(heads):
        end = len(lines)
        for nxt_line, nxt_level, _ in heads[idx + 1 :]:
            if nxt_level <= level:
                end = nxt_line
                break
        sections.append(Section(level, heading, "\n".join(lines[line_no + 1 : end]), line_no, end))
    return sections


def authoring_sections(text: str) -> List[Section]:
    """The sections of ``text`` that are authoring commentary, outermost first."""
    found: List[Section] = []
    covered_until = -1
    for sec in split_sections(strip_front_matter(text)):
        if sec.start < covered_until:
            continue  # inside a commentary section already found
        if is_authoring_heading(sec.heading):
            found.append(sec)
            covered_until = sec.end
    return found


def strip_front_matter(text: str) -> str:
    """The document without its YAML front matter (which is lifted into triples separately)."""
    return _FRONT_MATTER_RE.sub("", text or "", count=1)


def strip_authoring_commentary(text: str) -> Tuple[str, List[str]]:
    """``(text without authoring sections, their headings)``. Unchanged when there are none."""
    body = strip_front_matter(text)
    sections = authoring_sections(body)
    if not sections:
        return text, []
    lines = body.splitlines()
    drop: Set[int] = set()
    for sec in sections:
        drop.update(range(sec.start, sec.end))
    kept = [ln for i, ln in enumerate(lines) if i not in drop]
    return "\n".join(kept).strip() + "\n", [s.heading for s in sections]


def indexable_text(text: str) -> str:
    """What the document index should embed: no front matter, no authoring commentary."""
    stripped, _ = strip_authoring_commentary(text)
    return strip_front_matter(stripped)


def strip_flat_front_matter(text: str) -> str:
    """Remove a leading ``--- key: value ... ---`` block from an already-flattened chunk."""
    return _FLAT_FRONT_MATTER_RE.sub("", text or "", count=1).lstrip()


# ── fingerprints of commentary, for an index built before the sections were excluded ─────────

_SHINGLE = 6
_WORD = re.compile(r"[a-z0-9]+")
_FP_CACHE: Dict[Tuple[str, Tuple[Tuple[str, int, int], ...]], Set[str]] = {}


def _shingles(text: str, width: int = _SHINGLE) -> Set[str]:
    words = _WORD.findall((text or "").lower())
    if len(words) < width:
        return set()
    return {" ".join(words[i : i + width]) for i in range(len(words) - width + 1)}


def _documents_dir(building_id: str) -> Optional[Path]:
    try:
        from shared.building_paths import resolve_building_dir

        return resolve_building_dir(building_id, "documents")
    except Exception as exc:  # a missing helper must never break retrieval
        logger.debug(f"[passage_relevance] documents dir unavailable: {exc}")
        return None


def commentary_shingles(building_id: str, docs_dir: Optional[Path] = None) -> Set[str]:
    """Word 6-grams of every authoring section in the building's documents, cached by mtime."""
    root = docs_dir or _documents_dir(building_id)
    if root is None or not Path(root).is_dir():
        return set()
    files = sorted(p for p in Path(root).iterdir() if p.is_file() and p.suffix.lower() == ".md")
    sig = tuple((p.name, int(p.stat().st_size), int(p.stat().st_mtime_ns)) for p in files)
    key = (str(root), sig)
    hit = _FP_CACHE.get(key)
    if hit is not None:
        return hit
    prints: Set[str] = set()
    for path in files:
        try:
            raw = path.read_text(encoding="utf-8", errors="replace")
        except OSError:
            continue
        for sec in authoring_sections(raw):
            prints |= _shingles(sec.body)
    _FP_CACHE.clear()  # one building's signature at a time; a changed directory replaces it
    _FP_CACHE[key] = prints
    return prints


def commentary_fraction(text: str, prints: Set[str]) -> float:
    """Share of ``text``'s 6-grams that come from authoring commentary (0.0 when none)."""
    grams = _shingles(text)
    if not grams or not prints:
        return 0.0
    return len(grams & prints) / len(grams)


#: A passage this much made of commentary is the commentary, not a table that quotes it.
COMMENTARY_DROP_FRACTION = 0.5


def drop_commentary_hits(
    hits: Sequence[Dict[str, Any]], building_id: str, *, docs_dir: Optional[Path] = None
) -> List[Dict[str, Any]]:
    """Retrieved passages without the ones that are authoring commentary; front matter removed.

    The hits are returned as copies with flattened front matter stripped, so "simulated: true"
    and ``maps_to:`` never reach a composer or a reader.
    """
    prints = commentary_shingles(building_id, docs_dir)
    kept: List[Dict[str, Any]] = []
    dropped = 0
    for hit in hits:
        text = str(hit.get("text", ""))
        if commentary_fraction(text, prints) >= COMMENTARY_DROP_FRACTION:
            dropped += 1
            continue
        clean = strip_flat_front_matter(text)
        kept.append({**hit, "text": clean} if clean != text else hit)
    if dropped:
        logger.info(f"[passage_relevance] dropped {dropped} authoring-commentary passage(s)")
    return kept


# ── relevance ────────────────────────────────────────────────────────────────────────────────

#: Words that frame a question without naming its subject. Kept small and generic English.
_FRAMING = {
    "provide",
    "describe",
    "possible",
    "able",
    "way",
    "ways",
    "thing",
    "things",
    "kind",
    "kinds",
    "type",
    "types",
    "actually",
    "exactly",
    "really",
    "mean",
    "means",
    "work",
    "works",
    "happen",
    "happens",
    "part",
    "parts",
    "cover",
    "covers",
    "include",
    "includes",
    "regarding",
    "concerning",
    "related",
    "specific",
    "general",
    "generally",
    "typically",
    "usually",
    "different",
    "difference",
    "differ",
    "differs",
    "tell",
    "let",
    "make",
    "makes",
    "made",
    "take",
    "takes",
    "want",
    "wants",
    "ask",
    "asks",
    "put",
}
_FRAMING_STEMS: Set[str] = content_terms(" ".join(sorted(_FRAMING)), min_len=2) | set(_FRAMING)

#: Margin above the retrieval floor at which a passage is trusted without lexical overlap.
#:
#: MEASURED, and the measurement is that it decides nothing (wave 4). Replayed over the recorded
#: runs -- 19 questions whose live answer either cited a document or declined, against all 206
#: document chunks -- this path was reached **0 times**: every passage was settled by window
#: coverage or by the document's name first. Two consequences worth stating rather than hiding:
#:
#: * it cannot be calibrated from the recorded evidence, because the runs record no retrieval
#:   scores at all, so there is nothing to fit a threshold to. Saying "0.10 is tuned" would be a
#:   number with no measurement behind it, which is the failure `CLAUDE.md` logs most often;
#: * it is kept as a safety valve for the case the lexical rules cannot see -- a retriever that is
#:   very confident where question and passage share no word -- and it costs nothing while unused.
#:
#: Override with ``DOCUMENT_RELEVANCE_MARGIN`` to exercise it deliberately.
DEFAULT_SCORE_MARGIN = 0.10


def score_margin() -> float:
    """The margin over the retrieval floor, from the environment when set."""
    try:
        return float(os.environ.get("DOCUMENT_RELEVANCE_MARGIN", DEFAULT_SCORE_MARGIN))
    except ValueError:
        return DEFAULT_SCORE_MARGIN


def needed_terms(n_topic: int) -> int:
    """Subject terms a passage must share: one for a short question, two, then three for a long one.

    Two, not "half": a long analytical question has many subject terms and a correct passage often
    shares only the few that name its object (measured: the one consistently correct document
    answer on the 147-question bank shares 2 of 8). One shared word is the failure this gate
    exists to remove -- an incidental "ventilation" in a cost table.
    """
    if n_topic <= 2:
        return 1
    return 2 if n_topic <= 8 else 3


def _fold(term: str) -> str:
    """A six-letter stem for comparing inflections the crude singulariser leaves apart."""
    return term[:6] if len(term) >= 7 else term


def _shares(topic: Set[str], other: Set[str]) -> bool:
    """True when any topic term equals, or shares a folded stem with, a term of ``other``."""
    folded = {_fold(t) for t in other}
    return any(t in other or _fold(t) in folded for t in topic)


#: Ordinary English words for the same thing. NOT a building's vocabulary and not a lay-term table
#: (that is the concept resolver's job, and it reaches this module as ``extra_vocab``): these are
#: dictionary synonyms an English speaker would use interchangeably, and without them a question
#: and the sentence that answers it can share no word at all.
#:
#: Measured: "is there a muster point outside the building?" was answered with generic fire prose
#: while three chunks said "Proceed to the assembly point on Senghennydd Road". Every one was
#: REJECTED by this gate, because the question says muster and the building says assembly, so they
#: shared only "point" -- one term of three, below the bar. The junk chunk that passed shared
#: "outside" by accident.
_SYNONYMS: Tuple[Tuple[str, ...], ...] = (
    ("muster", "assembly", "rallying", "marshalling"),
    ("lift", "elevator"),
    ("loo", "lavatory", "toilet", "washroom", "restroom", "wc"),
    ("bin", "waste", "rubbish", "refuse", "trash"),
    ("car park", "parking", "carpark"),
    ("canteen", "cafeteria", "cafe", "refectory"),
    ("janitor", "caretaker", "custodian"),
    # The named schemes are industry vocabulary, like ASHRAE in the project's standards data, not
    # any one building's: a question asking for "certifications" is answered by a sentence naming
    # the scheme, and nothing else connects the two words.
    (
        "certification",
        "certificate",
        "accreditation",
        "rating",
        "award",
        "breeam",
        "leed",
        "passivhaus",
        "epc",
        "wellstandard",
    ),
    ("tip", "advice", "guidance", "suggestion", "recommendation"),
    ("store", "storeroom", "stores", "stockroom", "supply"),
    ("fault", "defect", "broken", "failure"),
    ("staff", "employee", "personnel", "colleague"),
    ("exit", "egress", "way out"),
)


@lru_cache(maxsize=1)
def _synonym_groups() -> Dict[str, Set[str]]:
    """term -> every folded term it may be matched by, built once from :data:`_SYNONYMS`."""
    groups: Dict[str, Set[str]] = {}
    for row in _SYNONYMS:
        folded = {_fold(t) for word in row for t in content_terms(word)}
        for word in row:
            for term in content_terms(word):
                groups.setdefault(term, set()).update(folded)
                groups.setdefault(_fold(term), set()).update(folded)
    return groups


def question_topic_terms(question: str) -> Set[str]:
    """The terms of a question that name its SUBJECT: no stop-words, generic or framing words."""
    return {
        t for t in content_terms(question) if t not in GENERIC_TERMS and t not in _FRAMING_STEMS
    }


@dataclass
class Verdict:
    """Whether one passage may answer the question, and on what evidence."""

    relevant: bool
    via: str  # coverage | name | score | no_topic_terms | none
    coverage: float = 0.0
    shared: Tuple[str, ...] = field(default_factory=tuple)
    needed: int = 0
    #: How many of the question's terms appear TOGETHER in one window. The ranking signal: a
    #: passage that says them in one place answers, one that scatters them merely mentions.
    window: int = 0

    @property
    def rank(self) -> Tuple[int, int]:
        """Sort key, best first: terms said together, then terms shared anywhere."""
        return (self.window, len(self.shared))


def assess(
    question: str,
    text: str,
    *,
    doc_name: str = "",
    score: Optional[float] = None,
    floor: Optional[float] = None,
    margin: Optional[float] = None,
    extra_vocab: Iterable[str] = (),
) -> Verdict:
    """Decide whether a passage is about the question.

    Relevant when ANY of: the question has no subject terms (fail open, as ``is_on_topic`` does);
    the passage shares :func:`needed_terms` of the question's subject terms; the document's own
    name carries a subject term; or the retrieval score clears the floor by ``margin``. ``extra_vocab`` (the concept resolver's lay-term expansion) credits one extra
    term when the passage says it, so "stuffy" is not failed against a passage about CO2.
    """
    topic = question_topic_terms(question)
    if not topic:
        return Verdict(True, "no_topic_terms")
    # THE BEST WINDOW INSIDE THE PASSAGE, not the passage as a whole (wave 4). A long passage that
    # contains the answering sentence must not be rejected because the rest of it is about
    # something else, and a passage whose shared terms are scattered across two unrelated rows is
    # weaker evidence than one that says them together.
    shared, window_shared = _shared_terms(topic, text)
    credit = 0
    for vocab in extra_vocab or ():
        stems = content_terms(str(vocab))
        if stems and _shares(stems, content_terms(text)):
            credit = 1
            break
    covered = min(len(topic), len(shared) + credit)
    needed = needed_terms(len(topic))
    coverage = covered / float(len(topic))
    if covered >= needed:
        return Verdict(True, "coverage", coverage, shared, needed, window=len(window_shared))
    if doc_name and _shares(topic, content_terms(str(doc_name).replace("_", " "))):
        return Verdict(True, "name", coverage, shared, needed, window=len(window_shared))
    if score is not None and floor is not None:
        if float(score) >= float(floor) + (score_margin() if margin is None else margin):
            return Verdict(True, "score", coverage, shared, needed, window=len(window_shared))
    return Verdict(False, "none", coverage, shared, needed, window=len(window_shared))


#: Words of the tightest span a passage is scored over. A sentence, give or take.
WINDOW_WORDS = 40


def _shared_terms(topic: Set[str], text: str) -> Tuple[Tuple[str, ...], Tuple[str, ...]]:
    """``(terms shared anywhere, terms shared inside the best window)``.

    Matching is by exact term, by folded stem ("isolate"/"isolation") and by ordinary English
    synonym ("muster"/"assembly"), so a question and the sentence that answers it are not kept
    apart by the word each happens to use.
    """
    words = re.findall(r"[a-z0-9][a-z0-9.\-]*", (text or "").lower())
    if not words:
        return (), ()
    groups = _synonym_groups()

    def _hit(term: str, bag: Set[str]) -> bool:
        folded = {_fold(t) for t in bag}
        if term in bag or _fold(term) in folded:
            return True
        alts = groups.get(term) or groups.get(_fold(term))
        return bool(alts and (alts & folded))

    whole = content_terms(text)
    shared = tuple(sorted(t for t in topic if _hit(t, whole)))
    best: Tuple[str, ...] = ()
    step = max(1, WINDOW_WORDS // 2)
    for start in range(0, max(1, len(words) - 1), step):
        bag = content_terms(" ".join(words[start : start + WINDOW_WORDS]))
        if not bag:
            continue
        here = tuple(sorted(t for t in topic if _hit(t, bag)))
        if len(here) > len(best):
            best = here
        if len(best) == len(topic):
            break
    return shared, best


def document_is_named(question: str, hits: Sequence[Dict[str, Any]]) -> bool:
    """True when some hit's DOCUMENT NAME carries a subject term of the question.

    A document called ``wifi_policy`` is about the wifi policy even when the retrieved chunk
    spells the network "Guest-WiFi"; the name is a topical label the lexical test cannot see.
    """
    topic = question_topic_terms(question)
    return bool(topic) and any(
        _shares(topic, content_terms(str(h.get("doc_name", "")).replace("_", " "))) for h in hits
    )


def relevant_hits(
    question: str,
    hits: Sequence[Dict[str, Any]],
    *,
    floor: Optional[float] = None,
    extra_vocab: Iterable[str] = (),
) -> Tuple[List[Dict[str, Any]], List[Dict[str, Any]]]:
    """Split retrieved passages into ``(kept, dropped)``, best first, by :func:`assess`.

    RANKED, not merely filtered (wave 4). Retrieval hands back its own order, and for "is there a
    muster point outside the building?" that order put a spill row that happened to say "outside"
    ahead of the sentence naming the assembly point. A passage that says the question's terms
    TOGETHER answers it; one that scatters them across unrelated rows only mentions them. The
    retrieval score breaks ties, so an equally-covered pair keeps the retriever's judgement.
    """
    vocab = list(extra_vocab or ())
    kept: List[Tuple[Tuple[int, int, float], Dict[str, Any]]] = []
    dropped: List[Dict[str, Any]] = []
    for hit in hits:
        verdict = assess(
            question,
            str(hit.get("text", "")),
            doc_name=str(hit.get("doc_name", "")),
            score=hit.get("score"),
            floor=floor,
            extra_vocab=vocab,
        )
        if verdict.relevant:
            try:
                tie = float(hit.get("score") or 0.0)
            except (TypeError, ValueError):
                tie = 0.0
            kept.append(((verdict.window, len(verdict.shared), tie), hit))
        else:
            dropped.append(hit)
    kept.sort(key=lambda pair: pair[0], reverse=True)
    ordered = [hit for _key, hit in kept]
    if dropped:
        logger.info(
            f"[passage_relevance] {len(dropped)} of {len(hits)} passage(s) failed the relevance "
            f"gate for {sorted(question_topic_terms(question))}"
        )
    return ordered, dropped
