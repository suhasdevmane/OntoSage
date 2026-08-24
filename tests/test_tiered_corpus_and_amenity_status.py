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


def test_both_corpora_load(rows):
    assert len(rows) == 1580


def test_no_question_falls_into_unknown(rows):
    """A catalogue row has no Category; falling through would bucket 480 questions as junk."""
    unknown = [r for r in rows if r["l7_stratum"] == "unknown"]
    assert not unknown, f"{len(unknown)} rows have no stratum"


def test_catalogue_rows_stratify_by_readiness(rows):
    cat = [r for r in rows if r["bank_source"].startswith("supervisor")]
    assert len(cat) == 480
    from collections import Counter

    assert dict(Counter(r["l7_stratum"] for r in cat)) == {"R1": 27, "R2": 303, "R3": 150}


def test_v5_rows_still_stratify_by_category(rows):
    """The existing corpus must keep its existing axis - this is an addition, not a change."""
    v5 = [r for r in rows if not r["bank_source"].startswith("supervisor")]
    assert len(v5) == 1100
    assert len({r["l7_stratum"] for r in v5}) == 24


def test_every_catalogue_row_carries_its_complexity(rows):
    cat = [r for r in rows if r["bank_source"].startswith("supervisor")]
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
