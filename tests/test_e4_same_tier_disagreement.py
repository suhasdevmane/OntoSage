# -*- coding: utf-8 -*-
"""E4 (QA-trial plan, 2026-10-04): precedence.resolve() can represent a same-tier tie.

Before this change, `resolve()` sorted claims by tier and took `ranked[0]` unconditionally.
Two systems of record disagreeing on the SAME question therefore produced one confident
value with `disagreement=False` — not a missing disclosure but an actively wrong one, since
nothing about the verdict said a second authoritative claim existed at all. The live instance
this absorbs (E6's own evidence): design occupancy is declared twice and disagrees for three
rooms (1.04: 50 vs 25; 4.01: 25 vs 20; 5.01: 25 vs 20), with `capacityBasis` — which would say
which wins — carrying zero triples today.

What these tests pin:

* two same-tier claims agreeing is NOT a disagreement (the ordinary case);
* two same-tier claims differing, with NO supersedes/effective_from evidence, produce
  `same_tier_disagreement=True`, `tiebreak="unresolved"`, and a sentence naming both — this is
  the state the bug used to erase entirely;
* an explicit `supersedes` link settles it without being called a disagreement needing a
  sentence pointed at the reader as unresolved — it IS resolved, by evidence;
* a later `effective_from` settles it the same way, only when EVERY tied claim states one;
* the winner is never chosen by arrival order — reversing the input order of an unresolved
  tie does not change which tiebreak path fires, only (possibly) which of the equally-unranked
  claims is reported, and both reversals still mark `tiebreak == "unresolved"`;
* the existing lower-tier `disagreement` contract (test_authority_contract.py) is unchanged —
  this is a SEPARATE field, not a replacement.
"""

from __future__ import annotations

import pytest

from orchestrator.services.evidence.precedence import SourceClaim, resolve

pytestmark = pytest.mark.unit


def test_two_same_tier_claims_that_agree_are_not_a_disagreement():
    v = resolve(
        [
            SourceClaim("reg-1", "authoritative", value=25.0, label="Register A"),
            SourceClaim("reg-2", "authoritative", value=25.0, label="Register B"),
        ]
    )
    assert v.same_tier_disagreement is False
    assert v.tiebreak == ""
    assert v.describe() == ""


def test_two_same_tier_claims_that_differ_with_no_evidence_are_unresolved_not_silent():
    v = resolve(
        [
            SourceClaim("reg-1.04-a", "authoritative", value=50.0, label="Room register"),
            SourceClaim("reg-1.04-b", "authoritative", value=25.0, label="Fire-safety plan"),
        ]
    )
    assert v.same_tier_disagreement is True
    assert v.tiebreak == "unresolved"
    assert len(v.tied_with) == 1
    assert v.winner is not None
    sentence = v.describe()
    assert "disagree" in sentence.lower()
    assert v.winner.describe() in sentence
    assert v.tied_with[0].describe() in sentence


def test_a_supersedes_link_resolves_the_tie_without_calling_it_unresolved():
    older = SourceClaim("reg-old", "authoritative", value=25.0, label="2024 fire-safety plan")
    newer = SourceClaim(
        "reg-new",
        "authoritative",
        value=50.0,
        label="2026 room register",
        supersedes="reg-old",
    )
    v = resolve([older, newer])
    assert v.winner is newer
    assert v.same_tier_disagreement is True
    assert v.tiebreak == "supersedes"
    assert "superseded" in v.describe().lower()
    assert "unresolved" not in v.describe().lower()


def test_a_later_effective_from_wins_when_every_tied_claim_states_one():
    old = SourceClaim(
        "reg-2024", "authoritative", value=25.0, label="2024 figure", effective_from="2024-01-01"
    )
    new = SourceClaim(
        "reg-2026", "authoritative", value=50.0, label="2026 figure", effective_from="2026-06-01"
    )
    v = resolve([old, new])
    assert v.winner is new
    assert v.tiebreak == "effective_from"
    assert v.same_tier_disagreement is True


def test_effective_from_is_not_used_unless_every_tied_claim_states_one():
    """One claim with no effective_from must not be silently out-ranked by one that has
    one -- that would let a single source's self-declared date decide, which is exactly
    the arrival-order risk this row exists to close under a different name."""
    dated = SourceClaim(
        "reg-a", "authoritative", value=50.0, effective_from="2026-01-01", label="Dated"
    )
    undated = SourceClaim("reg-b", "authoritative", value=25.0, label="Undated")
    v = resolve([dated, undated])
    assert v.tiebreak == "unresolved"


def test_the_winner_is_not_chosen_by_arrival_order():
    a = SourceClaim("reg-a", "authoritative", value=50.0, label="A")
    b = SourceClaim("reg-b", "authoritative", value=25.0, label="B")
    v1 = resolve([a, b])
    v2 = resolve([b, a])
    assert v1.tiebreak == v2.tiebreak == "unresolved"
    assert v1.same_tier_disagreement and v2.same_tier_disagreement


def test_same_tier_disagreement_is_reported_even_with_no_lower_tier_present():
    v = resolve(
        [
            SourceClaim("reg-a", "authoritative", value=50.0),
            SourceClaim("reg-b", "authoritative", value=25.0),
        ]
    )
    assert "same-tier" in v.reason
    assert v.disagreement is False  # the LOWER-tier field; nothing lower exists here


def test_same_tier_disagreement_coexists_with_lower_tier_disagreement():
    """A sensor disagreeing with the authoritative winner, AND two authoritative sources
    disagreeing with each other, are two distinct facts and must both survive the verdict."""
    v = resolve(
        [
            SourceClaim("reg-a", "authoritative", value=50.0, label="Register A"),
            SourceClaim("reg-b", "authoritative", value=25.0, label="Register B"),
            SourceClaim("occ-1", "measurement", value=12.0, label="Occupancy sensor"),
        ]
    )
    assert v.same_tier_disagreement is True
    assert v.disagreement is True
    assert len(v.overridden) == 1
    assert v.overridden[0].source_id == "occ-1"


def test_single_claim_at_the_top_tier_is_never_a_same_tier_disagreement():
    v = resolve(
        [
            SourceClaim("reg-a", "authoritative", value=50.0),
            SourceClaim("occ-1", "measurement", value=12.0),
        ]
    )
    assert v.same_tier_disagreement is False
    assert v.tiebreak == ""
