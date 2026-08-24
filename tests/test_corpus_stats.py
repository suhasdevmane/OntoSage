# -*- coding: utf-8 -*-
"""Corpus-frequency signal behind BUG-218's framing decision.

BUG-218: a retrieved passage sharing one incidental word with the question was presented under
a heading asserting it answered. Measured over the golden baseline, **148 of 377**
document-citing answers (39.3%) cited an unrelated document.

**What was measured, and what was rejected.** Candidate rules were swept against a hand-labelled
set of all 377 (148 off-topic / 42 arguable / 187 on-topic):

| rule | off-topic flagged | on-topic flagged | precision |
|---|---|---|---|
| DF limit <= 2 (shipped) | 26% | 6% | **70.4%** |
| DF limit <= 1 | 45% | 30% | 48.5% |
| DF limit <= 3 | 7% | 2% | 66.7% |
| "question names a term absent from the corpus" | 97% | 99% | 38.8% |
| overlap >= 2 terms | 82% | 48% | 52.4% |
| proportional (k=3, cap=2) | 70% | 44% | 51.0% |

against a 39.3% base rate. The last three are near chance, which is why this signal drives
FRAMING and not filtering: at 6% false-positives, hedging costs a slightly softer heading on
about eleven correct answers, whereas dropping would cost those answers outright.

**Honest coverage: this addresses about a quarter of the defect.** The remaining ~74% share a
genuinely rare term with the passage and no lexical rule separates them -- they are semantic
failures (homonymy: "monitor" the verb vs the screen; "book" the verb vs the noun). Those need
the retrieval floor re-derived for the current embedding model, which is a separate task.
"""

from pathlib import Path

import pytest

from orchestrator.services.corpus_stats import (
    COMMON_TERM_FRACTION,
    MIN_DOCS_FOR_SIGNAL,
    clear_cache,
    common_term_threshold,
    distinctive_terms,
    document_frequencies,
)
from orchestrator.services.grounding_guard import (
    MATCH_COMMON,
    MATCH_DISTINCTIVE,
    MATCH_NONE,
    match_strength,
)

pytestmark = pytest.mark.unit


@pytest.fixture
def corpus(tmp_path):
    """Five documents, with "clean" spread across four of them and "carpet" in none."""
    d = tmp_path / "bldg9" / "documents"
    d.mkdir(parents=True)
    (d / "hvac.md").write_text(
        "Heat recovery wheel inspected quarterly, cleaned annually.", encoding="utf-8"
    )
    (d / "fire.md").write_text("Escape routes kept clean and clear of storage.", encoding="utf-8")
    (d / "governance.md").write_text(
        "Records are cleaned of identifiers before retention.", encoding="utf-8"
    )
    (d / "bookings.md").write_text(
        "Pods are cleaned between bookings each morning.", encoding="utf-8"
    )
    (d / "plant.md").write_text(
        "Chiller staging and delta-T across the heating circuit.", encoding="utf-8"
    )
    clear_cache()
    yield tmp_path
    clear_cache()


# -- the table ---------------------------------------------------------------


def test_frequencies_count_documents_not_occurrences(corpus):
    """A word repeated forty times in one manual is one document's worth of evidence.

    Counting occurrences would let a single verbose file decide what the corpus finds common.
    """
    df, n = document_frequencies("bldg9", input_root=corpus)
    assert n == 5
    assert df["clean"] == 4
    assert df.get("carpet", 0) == 0
    assert df["chiller"] == 1


def test_the_threshold_is_a_fraction_of_the_corpus(corpus):
    """A count would make a 20-document building accidentally strict."""
    _df, n = document_frequencies("bldg9", input_root=corpus)
    assert common_term_threshold(n) == int(n * COMMON_TERM_FRACTION)
    assert common_term_threshold(20) == 8
    assert common_term_threshold(3) == 1


def test_a_term_the_corpus_never_uses_counts_as_distinctive(corpus):
    """Absent is the strongest evidence a passage containing it is unusual, and it is the
    safe direction -- an unknown term must never become a reason to reject."""
    df, n = document_frequencies("bldg9", input_root=corpus)
    assert "carpet" in distinctive_terms({"carpet"}, df, n)


def test_a_corpus_common_term_is_not_distinctive(corpus):
    df, n = document_frequencies("bldg9", input_root=corpus)
    assert distinctive_terms({"clean"}, df, n) == []


# -- degenerate corpora must degrade to a no-op ------------------------------


def test_a_tiny_corpus_yields_no_signal(tmp_path):
    """With two documents a term is in half the corpus or all of it; neither means anything.

    Inventing a signal there would be worse than having none.
    """
    d = tmp_path / "bldg8" / "documents"
    d.mkdir(parents=True)
    (d / "a.md").write_text("cleaned annually", encoding="utf-8")
    (d / "b.md").write_text("cleaned monthly", encoding="utf-8")
    clear_cache()
    df, n = document_frequencies("bldg8", input_root=tmp_path)
    assert (df, n) == ({}, 0)
    assert distinctive_terms({"clean"}, df, n) == ["clean"]  # falls open
    clear_cache()


def test_a_missing_corpus_is_not_an_error(tmp_path):
    clear_cache()
    assert document_frequencies("nosuch", input_root=tmp_path) == ({}, 0)


def test_min_docs_is_stated_not_implied():
    assert MIN_DOCS_FOR_SIGNAL >= 3


def test_the_cache_notices_a_new_document(corpus):
    """Uploading a manual must change the table; nothing else should recompute it."""
    df1, n1 = document_frequencies("bldg9", input_root=corpus)
    (corpus / "bldg9" / "documents" / "new.md").write_text(
        "Carpet cleaning schedule for the atrium.", encoding="utf-8"
    )
    df2, n2 = document_frequencies("bldg9", input_root=corpus)
    assert n2 == n1 + 1
    assert df2.get("carpet", 0) == 1


# -- the signal in use -------------------------------------------------------


def test_the_motivating_case_is_graded_as_a_weak_match(corpus):
    """The exact BUG-218 pair: a carpets question answered from the HVAC table."""
    df, n = document_frequencies("bldg9", input_root=corpus)
    got = match_strength(
        "Which carpets are due deep cleaning this month?",
        "Heat recovery wheel: inspected quarterly, cleaned annually.",
        corpus_df=df,
        n_docs=n,
    )
    assert got == MATCH_COMMON


def test_a_genuine_match_keeps_its_standing(corpus):
    """The cost of the signal is borne by correct answers, so this must hold."""
    df, n = document_frequencies("bldg9", input_root=corpus)
    got = match_strength(
        "Is the chiller staging correctly?",
        "Chiller staging and delta-T across the heating circuit.",
        corpus_df=df,
        n_docs=n,
    )
    assert got == MATCH_DISTINCTIVE


def test_an_unrelated_passage_is_still_none(corpus):
    df, n = document_frequencies("bldg9", input_root=corpus)
    got = match_strength("what colour is the roof", "Chiller staging.", corpus_df=df, n_docs=n)
    assert got == MATCH_NONE


def test_without_a_corpus_table_behaviour_is_unchanged():
    """Fails open. A building with no documents indexed must behave exactly as before."""
    got = match_strength(
        "Which carpets are due deep cleaning this month?",
        "Heat recovery wheel: cleaned annually.",
    )
    assert got == MATCH_DISTINCTIVE


def test_the_signal_never_promotes_an_unrelated_passage(corpus):
    """It may only weaken a verdict, never strengthen one past the guard."""
    df, n = document_frequencies("bldg9", input_root=corpus)
    for q, p in [
        ("what colour is the roof", "Chiller staging."),
        ("who is the vice chancellor", "Escape routes kept clean."),
    ]:
        assert match_strength(q, p, corpus_df=df, n_docs=n) == MATCH_NONE


# -- building agnosticism ----------------------------------------------------


def test_no_building_literal_and_no_domain_word_list():
    """The alternative to a per-corpus table is a fixed list of distrusted words -- which is
    exactly the hardcoded domain vocabulary design contract 3 forbids."""
    from scripts.check_building_literals import _prose_lines

    path = Path(__file__).resolve().parent.parent / "orchestrator" / "services" / "corpus_stats.py"
    src = path.read_text(encoding="utf-8")
    prose = _prose_lines(src)
    code = "\n".join(l for n, l in enumerate(src.splitlines(), 1) if n not in prose).lower()
    for literal in ("abacws", "bldg1", "bldg2", "bldg3", "cardiff", "hvac", "carpet"):
        assert literal not in code
