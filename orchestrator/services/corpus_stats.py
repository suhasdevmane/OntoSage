# -*- coding: utf-8 -*-
"""How common each word is in THIS building's own documents (BUG-218).

The grounding guard keeps a retrieved passage when it shares any distinctive word with the
question. Measured over the golden baseline, that let **148 of 377** document-citing answers
(39.3%) come from an unrelated document. The failing cases are not near-misses -- they share
exactly one incidental word:

    "Which carpets are due deep cleaning this month?"
    -> the HVAC threshold table, because it says "Heat recovery wheel: ... cleaned annually"

The discriminating fact is not *how many* words matched but *which*. "cleaned" appears in most
of the corpus; "carpet" appears in none of it. A count-based rule cannot tell those apart, and
sweeping thresholds over the real corpus confirmed it: every proportional variant dropped
roughly one legitimate answer for each off-topic one it removed.

**Why document frequency, and why per building.** A word that appears in most of a building's
documents carries no evidence that a passage is about the question. That is a property of THIS
corpus, not of English, and it has to be: the alternative -- a fixed list of words the guard
distrusts -- is exactly the hardcoded domain vocabulary design contract 3 forbids. A table
derived from whatever the building itself uploaded contains no literals at all, and a building
onboarded tomorrow gets its own.

**Cheap and honest about staleness.** The table is computed from the files on disk and cached
against a signature of that directory (names, sizes, mtimes), so uploading a document
recomputes it and nothing else does. No Qdrant call, no request-path I/O.

**Degenerate corpora degrade to a no-op, not to silence.** With one or two documents every
term is "rare", so the signal says nothing and the guard behaves exactly as before. That is
correct: a building that has uploaded a single manual has given no evidence about what is
common, and inventing some would be worse than having none.
"""

from __future__ import annotations

from pathlib import Path
from typing import Dict, List, Optional, Tuple

from shared.building_paths import resolve_building_dir
from shared.utils import get_logger

logger = get_logger(__name__)

#: Share of the corpus above which a term stops counting as topical evidence.
#:
#: Expressed as a FRACTION, not a count, so a 20-document building is not accidentally strict
#: and a 3-document one not accidentally permissive.
#:
#: 0.4 was MEASURED, not chosen. Swept against a hand-labelled set of all 377 document-citing
#: answers in the golden baseline (148 off-topic / 42 arguable / 187 on-topic, base rate
#: 39.3%). On this 5-document corpus 0.4 gives a limit of 2:
#:
#:   limit <= 1   45% of off-topic flagged, 30% of on-topic   48.5% precision
#:   limit <= 2   26% of off-topic flagged,  6% of on-topic   70.4% precision  <- shipped
#:   limit <= 3    7% of off-topic flagged,  2% of on-topic   66.7% precision
#:
#: Rules rejected on the same data, all near the 39.3% base rate: "the question names a term
#: absent from the corpus" (97% of off-topic BUT 99% of on-topic -- useless), overlap >= 2
#: terms (52.4%), and the proportional rule originally proposed for this fix (51.0%).
#:
#: ALSO MEASURED AND REJECTED: specificity rules of the form "the question has >= 3 distinctive
#: terms but the passage matched only one". These DO catch the motivating example (a carpets
#: question answered from the HVAC table, which this shipped rule misses) and they catch 80% of
#: all off-topic answers -- but they hedge 47% of the CORRECT ones, for 52.4% precision.
#:
#: That trade was rejected deliberately, and the reasoning matters more than the number. The
#: hedge says "I could not find a passage that directly addresses this". On an answer that DID
#: address it, that sentence is simply false -- the system disclaiming work it got right. At a
#: 47% false-positive rate it would say so on nearly half of all document answers, which is a
#: fresh honesty defect rather than a fix for one, and it would train readers to skip the
#: qualifier exactly when it is true. A softer universal qualifier fails the same way: a
#: caveat printed on half the answers is noise, and noise is what makes the one that matters
#: easy to miss.
#:
#: Coverage is honest at about a quarter of the defect. The rest share a genuinely rare term
#: with the passage and are semantic rather than lexical failures ("monitor" the verb vs the
#: screen, "book" the verb vs the noun); no word-overlap rule separates those, and the next
#: lever is the retrieval floor, which is calibrated for a different embedding model.
COMMON_TERM_FRACTION = 0.4

#: Below this many documents the signal is not computed at all. With two documents a term is
#: either in half the corpus or all of it, and neither number means anything.
MIN_DOCS_FOR_SIGNAL = 3

_CACHE: Dict[str, Tuple[Tuple, Dict[str, int], int]] = {}


def _signature(docs_dir: Path) -> Tuple:
    """A cheap fingerprint of the directory, so an upload invalidates the cache and nothing
    else does."""
    try:
        return tuple(
            sorted(
                (p.name, p.stat().st_size, int(p.stat().st_mtime))
                for p in docs_dir.iterdir()
                if p.is_file()
            )
        )
    except OSError:
        return ()


def document_frequencies(
    building_id: str, input_root: Optional[Path] = None
) -> Tuple[Dict[str, int], int]:
    """``(term -> number of documents containing it, document count)`` for one building.

    Returns ``({}, 0)`` when the corpus is missing or too small to say anything. Callers must
    treat that as "no signal" and fall through to their prior behaviour -- never as "nothing
    is distinctive", which would block every answer.
    """
    docs_dir = resolve_building_dir(building_id, "documents", input_root)
    if not docs_dir or not Path(docs_dir).is_dir():
        return {}, 0
    docs_dir = Path(docs_dir)

    sig = _signature(docs_dir)
    cached = _CACHE.get(building_id)
    if cached and cached[0] == sig:
        return cached[1], cached[2]

    # Imported here rather than at module scope: grounding_guard imports nothing from this
    # module, and keeping the dependency one-way stops an import cycle from ever forming.
    from orchestrator.services.grounding_guard import content_terms

    freqs: Dict[str, int] = {}
    n_docs = 0
    for path in sorted(docs_dir.iterdir()):
        if not path.is_file():
            continue
        try:
            text = path.read_text(encoding="utf-8", errors="ignore")
        except OSError as exc:
            logger.debug(f"[corpus_stats] could not read {path.name}: {exc}")
            continue
        n_docs += 1
        # Per DOCUMENT, not per occurrence: a word repeated forty times in one manual is one
        # document's worth of evidence, and counting occurrences would let a single verbose
        # file decide what the whole corpus considers common.
        for term in set(content_terms(text)) | set(content_terms(path.stem.replace("_", " "))):
            freqs[term] = freqs.get(term, 0) + 1

    if n_docs < MIN_DOCS_FOR_SIGNAL:
        freqs, n_docs = {}, 0

    _CACHE[building_id] = (sig, freqs, n_docs)
    return freqs, n_docs


def common_term_threshold(n_docs: int) -> int:
    """Documents a term may appear in before it stops counting as evidence."""
    if n_docs < MIN_DOCS_FOR_SIGNAL:
        return 0
    return max(1, int(n_docs * COMMON_TERM_FRACTION))


def distinctive_terms(terms, corpus_df: Dict[str, int], n_docs: int) -> List[str]:
    """The subset of `terms` that actually narrows anything in this corpus.

    A term absent from the table is treated as distinctive: it appears in none of the
    documents, which is the strongest possible evidence that a passage containing it is
    unusual -- and it is also the safe direction, since an unknown term must never silently
    become a reason to reject.
    """
    if not corpus_df or n_docs < MIN_DOCS_FOR_SIGNAL:
        return list(terms)
    limit = common_term_threshold(n_docs)
    return [t for t in terms if corpus_df.get(t, 0) <= limit]


def clear_cache() -> None:
    """For tests, and for a caller that has just rewritten the corpus behind our back."""
    _CACHE.clear()
