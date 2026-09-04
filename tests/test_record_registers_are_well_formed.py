# -*- coding: utf-8 -*-
"""Every record-document mapping must agree with the ontology and its own document.

A register is three files that have to line up — a mapping in `ontology/record_documents/`,
a class in Module R of `ontology/ontosage_schema.ttl`, and a document in `input/documents/`
whose table header matches the mapping's columns. Nothing at runtime checks that they do:
lifting is silent about a column the document lacks and about a predicate the TBox never
declares, so a register can ship and answer nothing.

These are generic. They walk whatever mappings exist rather than naming today's ten, so a
building that adds its own register gets the same checks for free.

Added alongside `cleaning_task` and `public_event`, the first two registers built from a
measured gap: the 2,480-question stakeholder capture put cleaning and caretaking at 19%
computed and visitors at 16%, against 62% for estates.
"""

from pathlib import Path

import pytest
import yaml

pytestmark = pytest.mark.unit

REPO = Path(__file__).resolve().parent.parent
MAPPINGS = sorted((REPO / "ontology" / "record_documents").glob("*.yaml"))
SCHEMA = (REPO / "ontology" / "ontosage_schema.ttl").read_text(encoding="utf-8")


def _mapping(path: Path) -> dict:
    return yaml.safe_load(path.read_text(encoding="utf-8")) or {}


def test_there_are_mappings_to_check():
    assert MAPPINGS, "no record-document mappings found — has the layout changed?"


@pytest.mark.parametrize("path", MAPPINGS, ids=lambda p: p.stem)
def test_a_mapping_declares_the_minimum_a_lift_needs(path):
    m = _mapping(path)
    for key in ("record_type", "class", "iri_template", "columns"):
        assert m.get(key), f"{path.name} has no {key}"
    assert m["record_type"] == path.stem, (
        f"{path.name} declares record_type={m['record_type']!r}; the document's front-matter "
        f"is matched on the FILE name, so these must agree"
    )


@pytest.mark.parametrize("path", MAPPINGS, ids=lambda p: p.stem)
def test_the_class_exists_in_the_tbox(path):
    cls = _mapping(path)["class"]
    local = cls.split(":", 1)[-1]
    assert f"ontosage:{local} " in SCHEMA or f"ontosage:{local}\n" in SCHEMA, (
        f"{path.name} lifts into {cls}, which Module R never declares — the triples would "
        f"carry a type nothing describes"
    )


@pytest.mark.parametrize("path", MAPPINGS, ids=lambda p: p.stem)
def test_the_class_carries_lay_terms(path):
    """R.4's own rule: a class name is not the word a person uses."""
    local = _mapping(path)["class"].split(":", 1)[-1]
    assert f"ontosage:{local} ontosage:layTerms" in SCHEMA, (
        f"{local} has no layTerms, so no question can route to it — the exact failure "
        f"Module R.4 exists to prevent"
    )


@pytest.mark.parametrize("path", MAPPINGS, ids=lambda p: p.stem)
def test_every_predicate_is_declared(path):
    m = _mapping(path)
    missing = []
    for column, spec in (m.get("columns") or {}).items():
        pred = (spec or {}).get("predicate", "")
        if not pred.startswith("ontosage:"):
            continue  # rdfs:label / rdfs:comment are core vocabulary
        local = pred.split(":", 1)[1]
        if f"ontosage:{local} " not in SCHEMA:
            missing.append(f"{column} -> {pred}")
    assert not missing, f"{path.name} maps to undeclared predicates: {missing}"


@pytest.mark.parametrize("path", MAPPINGS, ids=lambda p: p.stem)
def test_the_iri_template_uses_a_column_that_exists(path):
    m = _mapping(path)
    import re

    for field in re.findall(r"\{(\w+)\}", m["iri_template"]):
        assert field in (m.get("columns") or {}), (
            f"{path.name} builds its IRI from {{{field}}}, which is not a column — every "
            f"record would collide on the same IRI"
        )


@pytest.mark.parametrize("path", MAPPINGS, ids=lambda p: p.stem)
def test_the_label_column_exists(path):
    m = _mapping(path)
    label = m.get("label_column")
    if label:
        assert label in (
            m.get("columns") or {}
        ), f"{path.name}: label_column {label!r} is not a column"


@pytest.mark.parametrize("path", MAPPINGS, ids=lambda p: p.stem)
def test_a_status_lookup_is_a_declared_list_not_a_judgement(path):
    """The one interpretation a mapping is allowed, and it must be exhaustive by
    declaration — a cell matching nothing is an error, never a guess."""
    for column, spec in (_mapping(path).get("columns") or {}).items():
        values = (spec or {}).get("values")
        if values is None:
            continue
        assert isinstance(values, dict) and values, f"{path.name}:{column} has an empty lookup"
        for canonical, surface in values.items():
            assert (
                isinstance(surface, list) and surface
            ), f"{path.name}:{column}:{canonical} lists no surface forms"


# ── the document side ──────────────────────────────────────────────────────────────────


def _documents():
    folder = REPO / "input" / "documents"
    return sorted(folder.glob("*.md")) if folder.is_dir() else []


@pytest.mark.parametrize("path", MAPPINGS, ids=lambda p: p.stem)
def test_a_register_that_has_a_document_matches_its_header(path):
    """A document is optional here (input/ is per-building and may be parked), but one that
    exists must carry every required column or the lift drops rows in silence."""
    m = _mapping(path)
    docs = [
        d
        for d in _documents()
        if f"record_type: {m['record_type']}"
        in d.read_text(encoding="utf-8", errors="ignore")[:600]
    ]
    if not docs:
        pytest.skip(f"no document declares record_type {m['record_type']}")
    text = docs[0].read_text(encoding="utf-8")
    headers = [ln for ln in text.splitlines() if ln.strip().startswith("|")]
    assert headers, f"{docs[0].name} declares a record_type but has no table"
    columns = {c.strip() for ln in headers for c in ln.strip("|").split("|")}
    required = [c for c, s in (m.get("columns") or {}).items() if (s or {}).get("required")]
    missing = [c for c in required if c not in columns]
    assert not missing, f"{docs[0].name} is missing required column(s) {missing}"


@pytest.mark.parametrize("path", MAPPINGS, ids=lambda p: p.stem)
def test_every_status_cell_matches_a_declared_surface_form(path):
    """A cell matching nothing is an error, and the lift is all-or-nothing (V7-T18) — so one
    bad cell silently costs the whole register.

    This caught exactly that on `cleaning_task`: the document had been written with the
    mapping's CANONICAL keys (`handed_over`) where the lift matches only the surface forms
    the mapping lists (`Handed over`). Nothing lifted, and the only sign was one warning
    line in a container log.
    """
    m = _mapping(path)
    docs = [
        d
        for d in _documents()
        if f"record_type: {m['record_type']}"
        in d.read_text(encoding="utf-8", errors="ignore")[:600]
    ]
    if not docs:
        pytest.skip(f"no document declares record_type {m['record_type']}")
    lines = [
        ln.strip()
        for ln in docs[0].read_text(encoding="utf-8").splitlines()
        if ln.strip().startswith("|")
    ]
    header = None
    bad = []
    for ln in lines:
        cells = [c.strip() for c in ln.strip("|").split("|")]
        if header is None:
            if any(c in (m.get("columns") or {}) for c in cells):
                header = cells
            continue
        if set(cells) <= {"", "---", ":---", "---:"}:
            continue
        for column, spec in (m.get("columns") or {}).items():
            values = (spec or {}).get("values")
            if not values or column not in header:
                continue
            idx = header.index(column)
            if idx >= len(cells):
                continue
            cell = cells[idx]
            if not cell:
                continue
            # Use the LIFTER'S OWN matcher rather than restating its rule. It is a PREFIX
            # match, deliberately -- "Closed, fire watch completed" is closed because the
            # mapping lists "Closed", not because anything judged it. A test that restated
            # the rule as equality would reject the permit register, which is correct, and
            # would drift the moment the rule changed.
            from orchestrator.services.record_documents import ColumnSpec, _coerce

            spec_obj = ColumnSpec(
                predicate=(spec or {}).get("predicate", ""),
                datatype=(spec or {}).get("datatype", "xsd:string"),
                values={k: list(v) for k, v in values.items()},
            )
            _canonical, why = _coerce(cell, spec_obj.datatype, spec_obj)
            if why:
                bad.append(f"{cells[0]}:{column}={cell!r}")
    assert not bad, (
        f"{docs[0].name} has status cells matching no declared surface form: {bad[:5]}. "
        f"The lift is all-or-nothing, so the whole register would fail to load."
    )
