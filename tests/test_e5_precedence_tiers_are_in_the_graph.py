# -*- coding: utf-8 -*-
"""E5 (QA-trial plan, 2026-10-04): "which kind of record wins?" had nothing in the graph
to answer from -- the rule lived only in config/evidence_policy.yaml and
precedence.py's RANK, neither queryable by SPARQL. scripts/generate_precedence_ttl.py
GENERATES the TTL from those two sources (the policy stays the single source of truth)
rather than hand-authoring a second copy that could drift from it.

Deliberately does NOT reuse ontosage:SourceType, which already means something
different in the schema (which LANE answered a question). Two new classes instead:
ontosage:PrecedenceTier (ranked) and ontosage:SourceKind (linked to its tier).
"""
import subprocess
import sys
from pathlib import Path

import pytest
import rdflib

pytestmark = pytest.mark.unit

REPO = Path(__file__).resolve().parents[1]
SCRIPT = REPO / "scripts" / "generate_precedence_ttl.py"


def _generate() -> str:
    result = subprocess.run(
        [sys.executable, str(SCRIPT), "--print"],
        cwd=REPO,
        capture_output=True,
        text=True,
        timeout=30,
    )
    assert result.returncode == 0, result.stderr
    return result.stdout


def test_the_generated_ttl_parses_as_turtle():
    ttl = _generate()
    g = rdflib.Graph()
    g.parse(data=ttl, format="turtle")
    assert len(g) > 0


def test_it_does_not_reuse_sourcetype():
    ttl = _generate()
    assert "ontosage:SourceType" not in ttl
    assert "ontosage:PrecedenceTier" in ttl
    assert "ontosage:SourceKind" in ttl


def test_every_tier_from_rank_is_rendered_with_its_own_integer():
    from orchestrator.services.evidence.precedence import RANK

    ttl = _generate()
    for tier, rank in RANK.items():
        assert f"ontosage:tierRank {rank} " in ttl, f"tier {tier!r} (rank {rank}) missing"


def test_a_known_kind_points_at_the_right_tier():
    ttl = _generate()
    g = rdflib.Graph()
    g.parse(data=ttl, format="turtle")
    ns = rdflib.Namespace("http://ontosage.org/capabilities#")
    booking_tier = g.value(ns.Kind_Booking, ns.hasPrecedenceTier)
    assert booking_tier == ns.Tier_Authoritative
    sensor_tier = g.value(ns.Kind_Sensor, ns.hasPrecedenceTier)
    assert sensor_tier == ns.Tier_Measurement


def test_the_output_is_derived_from_the_policy_not_hand_authored_twice():
    """Regenerating must reflect precedence.RANK's own values -- if someone changes a
    rank in precedence.py without touching this test, the generated number must move
    with it, proving this is a rendering and not an independent assertion."""
    from orchestrator.services.evidence.precedence import RANK

    ttl = _generate()
    assert f"ontosage:tierRank {RANK['authoritative']} " in ttl
    assert RANK["authoritative"] > RANK["measurement"] > RANK["inference"]
