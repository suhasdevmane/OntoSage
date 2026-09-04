# -*- coding: utf-8 -*-
"""Tiered corpus loading (V6-T46) and amenity service status / potability (V6-T45).

**T46.** The two corpora stratify on different axes on purpose. R1 coverage measures
OntoSage; R2 measures the estate's integration backlog; R3 measures governance. Rolling
them into one number would let a good R1 score mask an empty R2 -- and that is exactly the
scoring inflation that already cost this project three false results.

**T45.** Two gaps that cause a WRONG answer rather than a missing one: an out-of-service
amenity is still recommended, and potability sits one short inference from a flow reading.
"""

from pathlib import Path

import pytest

pytestmark = pytest.mark.unit

REPO = Path(__file__).resolve().parent.parent
BANK = REPO / "tasks" / "smart_building_questions.csv"
SCHEMA = REPO / "ontology" / "ontosage_schema.ttl"


# ── T46: tiered corpus ───────────────────────────────────────────────────────


@pytest.fixture(scope="module")
def rows():
    from scripts.corpus_replay import _load_strata_source

    return _load_strata_source(BANK)


def test_all_three_corpora_load(rows):
    """1,100 v5 synthetic + 2,960 from the 37 stakeholder catalogues (the six earliest
    of which were once labelled separately as `supervisor_catalogue_2026-08`)
    catalogues that had never been extracted (2026-08-29)."""
    assert len(rows) == 4060


def test_no_question_falls_into_unknown(rows):
    """A catalogue row has no Category; falling through would bucket 480 questions as junk.

    It happened again at four times the scale: the 2,480 rows from the 31 stakeholder
    catalogues mostly carry NEITHER Category nor Readiness, and on the old rules 1,840 of
    them landed in "unknown" — the meaningless bucket this test was written to prevent.
    They stratify by stakeholder instead.
    """
    unknown = [r for r in rows if r["l7_stratum"] == "unknown"]
    assert not unknown, f"{len(unknown)} rows have no stratum"


def test_the_first_six_catalogues_still_carry_their_readiness_strata(rows):
    """These 480 were labelled `supervisor_catalogue_2026-08` because they arrived from the
    supervisor before the other 31 were generated. That was a DELIVERY BATCH, not a separate
    corpus: all 37 are the same Talking Abacws catalogues, 80 questions each, and the six
    files proved byte-identical to their copies in the 37-catalogue folder. Merged under one
    source 2026-09-04.

    They are now selected by ROLE rather than by source, and the readiness strata they were
    tagged with must survive that — losing them would silently drop the only readiness axis
    the corpus has.
    """
    from collections import Counter

    SIX = {
        "Undergraduate students",
        "Taught postgraduate students",
        "PhD students",
        "Research staff",
        "Lecturers and tutors",
        "Academic office occupants",
    }
    cat = [r for r in rows if r.get("stakeholder_role") in SIX]
    assert len(cat) == 480, f"expected the six occupant catalogues to hold 480, got {len(cat)}"

    # The STRATIFICATION AXIS changed with the merge and that is the merge working: these
    # rows now stratify by stakeholder role, 80 each, exactly like the other 31 catalogues.
    assert set(Counter(r["l7_stratum"] for r in cat).values()) == {80}
    assert {r["l7_stratum"] for r in cat} == SIX

    # The READINESS TAGS THEMSELVES are untouched, which is the thing that would actually
    # have been a loss. Verified against the corpus rather than the strata view.
    import csv as _csv

    with BANK.open(encoding="utf-8-sig", newline="") as fh:
        bank_six = [r for r in _csv.DictReader(fh) if r["Stakeholder_Role"] in SIX]
    assert dict(Counter(r["Readiness_R"] for r in bank_six)) == {"R1": 27, "R2": 303, "R3": 150}


def test_v5_rows_still_stratify_by_category(rows):
    """The existing corpus must keep its existing axis - this is an addition, not a change.

    Selected by its OWN source name. "not supervisor" used to mean "v5", and the moment a
    third corpus arrived that read 3,580 rows as v5 — a definition by exclusion that was
    correct only while there were two banks.
    """
    v5 = [r for r in rows if r["bank_source"] == "v5_synthetic_bank"]
    assert len(v5) == 1100
    assert len({r["l7_stratum"] for r in v5}) == 24


def test_the_37_catalogues_stratify_by_stakeholder(rows):
    """One axis per corpus. Only 38% of these rows carry a readiness tag, so a fallback
    chain would split single catalogues across two axes."""
    from collections import Counter

    cat37 = [r for r in rows if r["bank_source"] == "stakeholder_catalogue_37"]
    # 2,960 since the merge, not 2,480: the six occupant catalogues rejoined the source they
    # always belonged to. 37 catalogues x 80 questions.
    assert len(cat37) == 2960
    sizes = Counter(r["l7_stratum"] for r in cat37)
    assert set(sizes.values()) <= {80, 27, 303, 150}, (
        "each catalogue contributes exactly 80 questions; the six earliest are stratified by "
        "readiness instead and keep their R1/R2/R3 sizes"
    )


def test_every_catalogue_row_carries_its_complexity(rows):
    cat = [r for r in rows if r["bank_source"] == "stakeholder_catalogue_37" and r["complexity_l"]]
    assert all(r["complexity_l"].startswith("L") for r in cat)


def test_tier_columns_reach_the_output_csv():
    """Carried through to the report, or per-tier reporting is impossible."""
    from scripts.corpus_replay import _CSV_FIELDNAMES

    for col in ("readiness_r", "complexity_l", "bank_source"):
        assert col in _CSV_FIELDNAMES


def test_loader_documents_why_the_axes_stay_separate():
    from scripts import corpus_replay

    doc = corpus_replay._load_strata_source.__doc__ or ""
    assert "R1 coverage measures" in doc
    assert "mask an empty R2" in doc


# ── T45: amenity status and potability ───────────────────────────────────────


@pytest.fixture(scope="module")
def g():
    rdflib = pytest.importorskip("rdflib")
    graph = rdflib.Graph()
    graph.parse(str(SCHEMA), format="turtle")
    return graph


def _t(name):
    from rdflib import URIRef

    return URIRef("http://ontosage.org/capabilities#" + name)


@pytest.mark.parametrize(
    "term",
    [
        "amenityStatus",
        "PotabilityStatement",
        "potabilityValue",
        "potabilityAuthority",
        "potabilityIssuedOn",
        "appliesToOutlet",
    ],
)
def test_amenity_status_term_is_defined(g, term):
    assert (_t(term), None, None) in g


def test_out_of_service_amenities_must_be_excluded_not_caveated(g):
    """Somebody who walks to a broken fountain has been given a wrong answer, however hedged."""
    from rdflib import RDFS

    comment = str(list(g.objects(_t("amenityStatus"), RDFS.comment))[0]).lower()
    assert "excluded" in comment
    assert "caveat" in comment


def test_potability_defaults_to_unknown(g):
    """'Nobody has published a statement' is honest; assuming either value is a health claim."""
    from rdflib import RDFS

    comment = str(list(g.objects(_t("potabilityValue"), RDFS.comment))[0]).lower()
    assert "unknown" in comment
    assert "default" in comment


def test_potability_requires_a_named_authority(g):
    """A drinkability claim with no owner is the unattributable assertion this all guards against."""
    from rdflib import RDFS

    comment = str(list(g.objects(_t("potabilityAuthority"), RDFS.comment))[0]).lower()
    assert "required" in comment


def test_module_forbids_inferring_potability_from_a_sensor():
    """The non-substitution rule applied to its most dangerous case."""
    text = SCHEMA.read_text(encoding="utf-8")
    assert "Module P" in text
    assert "never" in text.lower()
    assert "health" in text.lower()
