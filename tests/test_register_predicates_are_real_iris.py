# -*- coding: utf-8 -*-
"""A predicate that is not an IRI is a property nobody queries.

`to_turtle` wrote every predicate as `<{predicate}>`. Eleven mappings declare
`predicate: rdfs:label` and several declare `predicate: rdfs:comment`, so those emitted
`<rdfs:label>` — a RELATIVE IRI. GraphDB accepted it, stored it, and reported the expected
triple count.

MEASURED LIVE on bldg1 before the fix:

    rdfs:label    (junk, relative)  206
    rdfs:comment  (junk, relative)   63
    rdfs:comment  (proper RDFS IRI)   0

The labels survived only because the lifter separately emits a proper label from
`label_column`, so there the damage was a duplicate. The comments had no second path: every
register's `note` column was unreachable by any query asking for a comment, and `note` is
where the caveat text lives — "collections are contracted; missed collections escalate same
day" is exactly the sentence an answer should carry.

Nothing errored at any point. That is the property this test exists to keep: the upload
succeeded, the counts looked right, and the property was simply not the one anybody queries.
"""

import pathlib
import sys

import pytest

pytestmark = pytest.mark.unit

REPO = pathlib.Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO))

from orchestrator.services.record_documents import (  # noqa: E402
    expand_predicate,
    lift_document,
    to_turtle,
)

RDFS = "http://www.w3.org/2000/01/rdf-schema#"
ONTO = "http://ontosage.org/capabilities#"
NS = "http://example.org/building#"
MAPPINGS = REPO / "ontology" / "record_documents"


def test_a_prefixed_name_expands():
    assert expand_predicate("rdfs:label") == f"{RDFS}label"
    assert expand_predicate("rdfs:comment") == f"{RDFS}comment"
    assert expand_predicate("ontosage:recordId") == f"{ONTO}recordId"


def test_a_full_iri_is_left_alone():
    assert expand_predicate(f"{RDFS}label") == f"{RDFS}label"
    assert expand_predicate("https://brickschema.org/schema/Brick#Room").startswith("https://")


def test_an_unknown_prefix_is_not_silently_rewritten():
    """Passing it through makes it fail as a bad IRI rather than become a wrong property."""
    assert expand_predicate("nosuch:thing") == "nosuch:thing"


def _any_register():
    for doc in sorted(REPO.glob("*/documents/*.md")):
        result = lift_document(doc, NS, MAPPINGS)
        if getattr(result, "ok", False) and result.instances:
            return doc, result
    pytest.skip("no building in this checkout holds a liftable register")


def test_serialised_turtle_contains_no_relative_iri_predicate():
    """The end-to-end property: every predicate written out is absolute."""
    doc, result = _any_register()
    for line in to_turtle(result).splitlines():
        if not line.startswith("<"):
            continue
        predicate = line.split("> <", 1)[1].split(">", 1)[0]
        assert predicate.startswith("http"), (
            f"{doc.name} serialises the relative predicate <{predicate}>. GraphDB will store "
            f"it verbatim and no query for that property will ever match it."
        )


def test_a_note_column_reaches_the_real_comment_property():
    """The column that was actually lost. Guarded by name, because it is load-bearing."""
    for doc in sorted(REPO.glob("*/documents/*.md")):
        result = lift_document(doc, NS, MAPPINGS)
        if not getattr(result, "ok", False):
            continue
        preds = {p for _, p, _ in result.triples}
        if any(p.endswith("comment") for p in preds):
            assert f"{RDFS}comment" in preds, (
                f"{doc.name} emits a comment predicate that is not the RDFS one: "
                f"{sorted(p for p in preds if p.endswith('comment'))}"
            )
            return
    pytest.skip("no register in this checkout declares a comment column")
