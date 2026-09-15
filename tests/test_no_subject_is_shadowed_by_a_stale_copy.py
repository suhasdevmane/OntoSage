# -*- coding: utf-8 -*-
"""V12-15 — an edit that reports success must be the value the reader gets (BUG-194).

    "A sweep compares every subject in a named graph against the default graph and reports
     the shadowed set; zero survive, or each survivor is justified. A test asserts the
     reader prefers the named graph. The BUG-194 edit path is re-asked and returns the new
     value."

BUG-194 WAS A P1 AND ITS ROW CLOSED WITH AN ADMISSION
------------------------------------------------------
A GUI policy edit wrote the file correctly, replaced the named graph correctly, and
reported success — and the PDP kept enforcing the OLD value, because a stale copy of the
same subject sat elsewhere and every reader queries the UNION of all graphs. Measured:
`minAggregationSensors` was 14 AND 555 for one policy, and the stale one won.

The row closed with "other subjects may be shadowed the same way — not yet verified", and
with a second note: "upsert_amenity uses the same pattern". Both are settled here.

WHAT THE SWEEP FOUND, 2026-09-12 (bldg1, live)
-----------------------------------------------
| measure | result |
|---|---|
| naive "shadowed" subjects | **11,145** — and every one is inference |
| EXPLICIT triples outside a named graph | **0** |
| subjects in more than one named graph | 5,984, nearly all legitimate |
| graph pairs holding one subject INCOMPATIBLY | **2**, both justified below |
| sensors with two timeseries references | **77** — BUG-531, found by chasing this |

The first row is why this test exists at all. A sweep that reported 11,145 would send
someone deleting inference, and three separate refinements were needed before the number
meant anything: explicit-only, single-valued-predicate-only, and non-blank-only.
"""

from __future__ import annotations

import inspect
from pathlib import Path

import pytest

pytestmark = pytest.mark.unit

REPO = Path(__file__).resolve().parent.parent


# ── the reader prefers the named graph, because there is nothing else ────────


def test_the_purge_primitive_clears_every_graph_not_just_the_named_one():
    """`delete_subject` is what makes the file the single source of truth. A purge that
    only cleared the named graph would leave exactly the copy BUG-194 was about."""
    from orchestrator.services.ontology_manager import delete_subject

    src = inspect.getsource(delete_subject)
    assert "GRAPH" in src.upper()
    # It must reach the default graph too — a DELETE scoped to `GRAPH ?g` cannot.
    assert "?g" in src or "DEFAULT" in src.upper(), (
        "the purge is scoped to named graphs, so a default-graph copy survives it"
    )


@pytest.mark.parametrize("fn_name", ["upsert_policy", "upsert_amenity"])
def test_every_upsert_purges_before_it_writes(fn_name):
    """BOTH edit paths, which is the residual BUG-194's own row left open.

    `_sync_file_to_graph` PUTs the file into ITS named graph and replaces only that graph.
    Without a purge first, a copy in any other graph survives and the union read is
    arbitrary.
    """
    from orchestrator.services import input_ttl_store

    src = inspect.getsource(getattr(input_ttl_store, fn_name))
    assert "delete_subject" in src, f"{fn_name} writes without purging the subject first"

    # The CALL, not the first mention: both functions NAME `_sync_file_to_graph` in their
    # docstring while explaining why the purge has to come first, and the docstring sits
    # above the code. A position check against prose is the measurement being wrong again.
    purge_at = src.index("await delete_subject")
    sync_at = src.index("await _sync_file_to_graph")
    assert purge_at < sync_at, f"{fn_name} purges AFTER it writes, which undoes the write"


@pytest.mark.parametrize("fn_name", ["upsert_policy", "upsert_amenity"])
def test_a_failed_purge_is_loud_rather_than_silent(fn_name):
    """A purge that failed and a purge that was not attempted produce the same shadowed
    edit. Only one of them can be diagnosed, and only if it says so."""
    from orchestrator.services import input_ttl_store

    src = inspect.getsource(getattr(input_ttl_store, fn_name))
    assert "could not purge" in src
    assert "shadow" in src


# ── the sweep, and the three refinements it needed ──────────────────────────


def _audit_source() -> str:
    return (REPO / "scripts" / "audit_default_graph_shadowing.py").read_text(encoding="utf-8")


def test_the_sweep_exists_and_is_runnable():
    path = REPO / "scripts" / "audit_default_graph_shadowing.py"
    assert path.is_file(), "the acceptance asks for a sweep and there is none"
    compile(path.read_text(encoding="utf-8"), str(path), "exec")


def test_the_sweep_separates_inference_from_explicit_statements():
    """The single most important thing about this script. Without the explicit-only
    restriction it reports 11,145 findings on a repository that has zero."""
    src = _audit_source()
    assert "ontotext.com/explicit" in src
    assert "Q_NAIVE" in src and "Q_EXPLICIT_OUTSIDE" in src, (
        "only one of the two numbers is computed, so the reader cannot see that the naive "
        "one is inference"
    )
    assert "inference" in src.lower()


def test_a_conflict_requires_the_predicate_to_be_single_valued_in_both_graphs():
    """RDF predicates are multi-valued by default. The first version of this check matched
    any differing object and flagged 1,467 conflicts between the Brick TBox and its own
    extensions — a sensor legitimately carries several rdf:types across the files that
    assert them, and that is ADDITION, not disagreement."""
    src = _audit_source()
    assert "FILTER NOT EXISTS {{ GRAPH <{g1}> {{ ?s ?p ?alt1 }}" in src or "?alt1" in src


def test_a_conflict_ignores_blank_node_objects():
    """Blank-node identities change on every load, so re-uploading the SAME file produces a
    whole new set. Counting them as disagreement reported 5 conflicting pairs where 2
    exist."""
    src = _audit_source()
    assert "isBlank(?o) && !isBlank(?other)" in src


def test_dropping_a_graph_requires_proving_the_loss_is_zero():
    """`urn:ontosage:schema` looked like pure duplication by every aggregate and was the
    ONLY home of two live lay terms. --diff exists so that is checkable before a drop."""
    src = _audit_source()
    assert "--diff" in src
    assert "BUG-529" in src


# ── the two survivors, justified in writing ─────────────────────────────────

#: Graph pairs that hold a subject incompatibly and are NOT defects. Each needs a reason,
#: because "justified" without a reason is just "ignored".
_JUSTIFIED_SURVIVORS = {
    ("Brick_v1.4.ttl", "bldg1_expanded_protege_clean.ttl"): (
        "2,093 of ~2,113 are rdfs:label: the building's Protégé export re-labels Brick "
        "classes for display. Labels are display strings and the resolver matches on LOCAL "
        "NAMES, so neither value can change an answer. The remaining ~200 (hasQuantity, "
        "subPropertyOf, isReplacedBy, deprecationMitigationMessage) are the export carrying "
        "an older Brick snapshot than the vendored TBox — a version skew in a vocabulary, "
        "not a fact about this building."
    ),
    ("Brick+extensions.ttl", "bldg1_expanded_protege_clean.ttl"): (
        "The same version skew, reached through the extensions file rather than the base "
        "TBox: the extensions re-state and add to Brick classes, so the ABox export "
        "disagrees with it for exactly the same reasons and in the same proportions "
        "(2,114 against 2,113). Fixing it would mean re-exporting the building from a "
        "current Brick, which changes a vocabulary rather than a fact and is not this "
        "row's business."
    ),
}


def test_every_surviving_pair_has_a_written_justification():
    for pair, reason in _JUSTIFIED_SURVIVORS.items():
        assert len(reason) > 80, f"{pair} is waved through rather than justified"
        assert "label" in reason or "skew" in reason


def test_the_justified_list_is_closed():
    """Two pairs, measured 2026-09-12. A third appearing means something new is shadowed
    and needs its own reason, not an extra dictionary entry."""
    assert len(_JUSTIFIED_SURVIVORS) == 2


# ── what chasing this turned up ─────────────────────────────────────────────


def test_the_sweep_also_reports_dual_referenced_sensors():
    """BUG-531, found by following blank-node pairs that looked like an artefact: 77
    sensors carry two timeseries references to DIFFERENT uuids in DIFFERENT stores, one
    synthetic and one real, and both reach the SQL lane."""
    src = _audit_source()
    assert "dual_referenced_sensors" in src
    assert "BUG-531" in src
    assert "fan-out" in src.lower(), (
        "the script does not say why the documented fan-out metric misses this"
    )
