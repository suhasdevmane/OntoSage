# -*- coding: utf-8 -*-
"""A potability statement carries the owner who stands behind it (BUG-323, 2026-08-27).

Module P of the OCBV schema models drinkability as a PUBLISHED STATEMENT rather
than something derived from a reading, and says why in the schema itself: the lay
mapping already sends "drinking water" at ``brick:Water_Quality_Sensor``, a flow
reading sits one short step away, and *a sensor reading does not support a health
statement*. Being wrong about drinkability harms someone.

``PotabilityStatement`` is a ``KnowledgeTopic`` subclass precisely so the existing
resolver finds it with no new code — and that worked. What did not work is that
the resolver surfaced the topic's ``answerText`` alone. ``potabilityValue``,
``potabilityAuthority`` and ``potabilityIssuedOn`` had zero readers anywhere in
the codebase, so a drinkability claim would have been presented with no owner and
no date: exactly the confident unattributable assertion the module was written to
prevent, and the schema's stated reason for requiring both.

**No potability statement is authored for bldg1 here, deliberately.** bldg1 is a
real building. Provisioning a synthetic "the water is safe to drink, published by
Facilities" claim about a real building is the harm this module guards against,
whatever provenance flag rides along with it. The vocabulary is now readable; the
claim is the building owner's to publish.
"""

import pytest

from orchestrator.services.capability_graph_resolver import CapabilityFact

pytestmark = pytest.mark.unit


def _fact(**kw) -> str:
    base = dict(label="Drinking water on level 5", location="Level 5 kitchen")
    base.update(kw)
    return CapabilityFact(**base).render()


# ── a published claim names its owner and its date ───────────────────────────
def test_a_potable_statement_names_the_authority_and_the_date():
    out = _fact(
        potability="potable",
        potability_authority="Cardiff University Estates",
        potability_issued_on="2026-05-14",
    )
    assert "safe to drink" in out
    assert "Cardiff University Estates" in out
    assert "2026-05-14" in out


def test_a_not_potable_statement_is_unambiguous():
    """'Not potable' must not read like a hedge on 'potable'."""
    out = _fact(
        potability="not_potable",
        potability_authority="Estates",
        potability_issued_on="2026-01-02",
    )
    assert "NOT for drinking" in out
    assert "safe to drink" not in out


# ── and an incomplete one is reported as incomplete ──────────────────────────
def test_a_statement_with_no_authority_is_reported_as_unverified():
    """The schema requires an authority because a drinkability claim with no owner
    is the unattributable assertion the evidence discipline exists to prevent.
    Surfacing the value alone would reproduce that defect."""
    out = _fact(potability="potable", potability_issued_on="2026-05-14")
    assert "unverified" in out
    assert "names no issuing authority" in out


def test_a_statement_with_no_date_says_so():
    """A statement issued years ago describes a plumbing system that may since have
    been altered, so a missing date is worth stating rather than omitting."""
    out = _fact(potability="potable", potability_authority="Estates")
    assert "Estates" in out
    assert "no issue date recorded" in out


@pytest.mark.parametrize("value", ["unknown", ""])
def test_no_published_statement_is_distinguished_from_unsafe(value):
    """'Nobody has assessed this' and 'this is unsafe' are different answers, and
    the schema names UNKNOWN as a legitimate one."""
    out = _fact(potability=value or "unknown")
    assert "no statement has been published" in out
    assert "not the same as unsafe" in out


# ── the rendering path actually reaches it ───────────────────────────────────
def test_a_statement_with_no_other_topic_fields_still_renders_its_claim():
    """The knowledge-topic branch was entered only when answerText or a contact was
    present. A statement carrying nothing but potability fields would have fallen
    through to the physical-amenity rendering, which drops all of this."""
    out = _fact(potability="potable", potability_authority="Estates")
    assert "Drinkability" in out


def test_a_plain_amenity_is_unchanged():
    """Nothing here may alter the output for the amenities that carry no statement."""
    out = _fact(note="Refill point beside the lifts.")
    assert "Drinkability" not in out
    assert out == "**Drinking water on level 5** — Level 5 kitchen. Refill point beside the lifts."


# ── the query asks for what the render needs ─────────────────────────────────
def test_the_resolver_query_binds_all_three_terms():
    """Reading two of the three would produce a claim missing exactly the part the
    schema calls required."""
    import inspect

    from orchestrator.services import capability_graph_resolver as cgr

    src = inspect.getsource(cgr.CapabilityGraphResolver._amenities)
    for term in ("potabilityValue", "potabilityAuthority", "potabilityIssuedOn"):
        assert term in src, term


def test_the_fields_survive_the_hop_from_amenity_to_fact():
    """Five capabilities in this codebase were correct up to the last hop and had
    no invoker. Querying a term and dropping it before rendering is that same
    failure, one step later."""
    import inspect

    from orchestrator.services import capability_graph_resolver as cgr

    src = inspect.getsource(cgr.CapabilityGraphResolver.resolve)
    for term in ("potability=", "potability_authority=", "potability_issued_on="):
        assert term in src, term
