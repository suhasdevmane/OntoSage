# -*- coding: utf-8 -*-
"""Waste, recycling and institutional targets (V6-T43).

The largest wholly-missing domain the category sweep found, and one the project had already
noticed -- `scripts/ttl_gap_audit.py` records the same gap as backlog item P4.

The less obvious half is the target. "Are we on track for our diversion target" is
unanswerable without one, and the tempting failure is not refusing it but **inventing a
plausible target and reporting progress against it**. So a target is authored, dated,
attributed, and never inferred from the data it exists to judge.
"""

from pathlib import Path

import pytest
import yaml

pytestmark = pytest.mark.unit

REPO = Path(__file__).resolve().parent.parent
SCHEMA = REPO / "ontology" / "ontosage_schema.ttl"
MODALITIES = REPO / "config" / "saturation_modalities.yaml"


@pytest.fixture(scope="module")
def g():
    rdflib = pytest.importorskip("rdflib")
    graph = rdflib.Graph()
    graph.parse(str(SCHEMA), format="turtle")
    return graph


def _t(name):
    from rdflib import URIRef

    return URIRef("http://ontosage.org/capabilities#" + name)


# ── modalities ───────────────────────────────────────────────────────────────


@pytest.fixture(scope="module")
def modalities():
    return yaml.safe_load(MODALITIES.read_text(encoding="utf-8"))["modalities"]


def test_both_waste_modalities_are_declared(modalities):
    assert "waste_fill" in modalities
    assert "waste_weight" in modalities


def test_fill_and_weight_are_separate_modalities(modalities):
    """They answer different questions and fail differently.

    Fill level says "is this bin full now" -- operational, live. Weight says "how much did we
    throw away" -- reporting, needs history. One modality would force one to stand in for the
    other.
    """
    assert modalities["waste_fill"]["sat"]["table"] != modalities["waste_weight"]["sat"]["table"]
    assert modalities["waste_fill"]["sat"]["unit"] == "percent"
    assert modalities["waste_weight"]["sat"]["unit"] == "kg"


def test_waste_modalities_are_label_filtered(modalities):
    """Level_Sensor is generic; without the filter every level sensor becomes a bin."""
    for name in ("waste_fill", "waste_weight"):
        assert modalities[name]["label_contains"]


def test_provisioning_needs_no_code_change(modalities):
    """The config-is-the-extension-point contract: a modality entry plus a table."""
    for name in ("waste_fill", "waste_weight"):
        sat = modalities[name]["sat"]
        assert sat["brick_class"] and sat["table"] and sat["unit"]


# ── vocabulary ───────────────────────────────────────────────────────────────


@pytest.mark.parametrize(
    "term",
    [
        "WastePoint",
        "wasteStream",
        "streamCapacityLitres",
        "SustainabilityTarget",
        "targetMetric",
        "targetValue",
        "targetUnit",
        "targetDate",
        "targetBaselinePeriod",
        "targetAuthority",
    ],
)
def test_waste_term_is_defined(g, term):
    assert (_t(term), None, None) in g


def test_waste_point_is_an_amenity_so_it_is_findable(g):
    """'Where are the recycling bins' should need authoring, not engineering."""
    from rdflib import RDFS

    parents = {str(o) for o in g.objects(_t("WastePoint"), RDFS.subClassOf)}
    assert any("Amenity" in p for p in parents)


def test_capacity_is_modelled_because_a_percentage_alone_is_not_actionable(g):
    """80% of a 25 L office bin and 80% of a 1100 L euro-bin are different problems."""
    from rdflib import RDFS

    comment = str(list(g.objects(_t("streamCapacityLitres"), RDFS.comment))[0])
    assert "1100" in comment or "euro-bin" in comment


# ── targets ──────────────────────────────────────────────────────────────────


def test_a_target_must_be_attributed(g):
    """An unattributed commitment cannot be relied on, and cannot be challenged."""
    from rdflib import RDFS

    comment = str(list(g.objects(_t("targetAuthority"), RDFS.comment))[0]).lower()
    assert "required" in comment


def test_a_target_must_be_dated(g):
    """'On track' is a statement about a rate, so an undated target cannot be judged."""
    from rdflib import RDFS

    comment = str(list(g.objects(_t("targetDate"), RDFS.comment))[0]).lower()
    assert "rate" in comment or "cannot be judged" in comment


def test_a_target_records_its_baseline_period(g):
    """Choosing a baseline after the fact is the oldest way to make a number say anything."""
    from rdflib import RDFS

    comment = str(list(g.objects(_t("targetBaselinePeriod"), RDFS.comment))[0]).lower()
    assert "baseline" in comment


def test_targets_are_documented_as_never_inferred(g):
    """A target derived from the data it judges makes every trend a success by construction."""
    from rdflib import RDFS

    comment = str(list(g.objects(_t("SustainabilityTarget"), RDFS.comment))[0]).lower()
    assert "never inferred" in comment


def test_module_states_that_contamination_is_a_ratio_not_an_estimate():
    text = SCHEMA.read_text(encoding="utf-8")
    assert "Module Q" in text
    assert "not measurable" in text.lower()
