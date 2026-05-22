"""
Unit tests for orchestrator.services.semantic_router.SemanticRouter.

Covers §16.1.3 of the capability semantic routing spec.

Sixteen tests:
   1. high_score_returns_capability_intent
   2. medium_score_returns_no_intent_but_matches_populated
   3. low_score_returns_no_intent_and_empty_matches
   4. matches_grouped_by_entry_id
   5. max_pool_score_per_entry
   6. disabled_returns_source_disabled
   7. qdrant_down_returns_source_fallback
   8. collection_missing_returns_source_fallback
   9. per_building_threshold_honored
  10. top_k_respected
  11. register_intent_extension_hook
  12. embedding_failure_returns_fallback
  13. empty_query_returns_no_intent
  14. query_with_only_punctuation
  15. unicode_query_works
  16. concurrent_classify_safe
"""

from __future__ import annotations

import asyncio
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock

import pytest

from orchestrator.services.semantic_router import (
    CapabilityMatch,
    SemanticRouter,
    SemanticRouteResult,
)


# ── Fixtures ────────────────────────────────────────────────────────────────────


_CAP_YAML = """
building_info:
  id: testbldg
  name: Test Building
capabilities:
  - id: lift_details
    category: ACCESSIBILITY
    keywords: [lift dimensions, lift weight]
    content: Lift is 106x220cm, 1000kg weight limit.
    source: test
  - id: fire_safety
    category: FIRE_SAFETY
    keywords: [fire, evacuation]
    content: Fire alarms and sprinklers throughout.
    source: test
"""


def _write_kb(tmp_path: Path, building_id: str, content: str = _CAP_YAML) -> Path:
    bdir = tmp_path / building_id
    bdir.mkdir(parents=True, exist_ok=True)
    (bdir / "capability.yaml").write_text(content, encoding="utf-8")
    return bdir / "capability.yaml"


def _write_building_yaml(tmp_path: Path, building_id: str, block: str = "") -> Path:
    bdir = tmp_path / building_id
    bdir.mkdir(parents=True, exist_ok=True)
    path = bdir / "building.yaml"
    path.write_text(block, encoding="utf-8")
    return path


class _FakeEmbedder:
    def __init__(self, dim=4, fail=False):
        self.dimension = dim
        self._fail = fail

    async def embed(self, text):
        if self._fail:
            raise RuntimeError("embedding api down")
        return [0.1] * self.dimension


def _make_point(entry_id, score, vector_source="keyword", text="kw text"):
    p = MagicMock()
    p.payload = {
        "entry_id": entry_id,
        "vector_source": vector_source,
        "text": text,
    }
    p.score = score
    return p


def _make_qdrant_returning(points):
    """Build a Qdrant client whose query_points returns these points."""
    client = MagicMock()
    result = MagicMock()
    result.points = points
    client.query_points = AsyncMock(return_value=result)
    return client


def _make_router(tmp_path, embedder=None, qdrant=None, points=None):
    """Build a SemanticRouter wired to tmp_path with capability intent registered."""
    if qdrant is None:
        qdrant = _make_qdrant_returning(points or [])
    if embedder is None:
        embedder = _FakeEmbedder()
    router = SemanticRouter(
        qdrant_client=qdrant, embedding_service=embedder, input_root=str(tmp_path)
    )
    router.register_intent("capability", "capability_")
    return router


# ── Tests ───────────────────────────────────────────────────────────────────────


async def test_high_score_returns_capability_intent(tmp_path):
    """Test 1: score >= override_min → intent='capability', skip-LLM signal."""
    _write_kb(tmp_path, "testbldg")
    points = [_make_point("lift_details", 0.92), _make_point("fire_safety", 0.40)]
    router = _make_router(tmp_path, points=points)

    result = await router.classify("how big is the lift?", "testbldg")

    assert result.intent == "capability"
    assert result.score == pytest.approx(0.92)
    assert result.source == "semantic"
    assert len(result.matches) >= 1
    assert result.matches[0].entry_id == "lift_details"


async def test_medium_score_returns_no_intent_but_matches_populated(tmp_path):
    """Test 2: threshold <= score < override_min → intent=None, matches included."""
    _write_kb(tmp_path, "testbldg")
    # Default threshold=0.65, override_min=0.85 → 0.70 is medium band
    points = [_make_point("lift_details", 0.70)]
    router = _make_router(tmp_path, points=points)

    result = await router.classify("lifts and stuff", "testbldg")

    assert result.intent is None, "Medium score must leave intent decision to caller"
    assert result.score == pytest.approx(0.70)
    assert len(result.matches) == 1, "Caller needs matches to evaluate soft override"


async def test_low_score_returns_no_intent_and_empty_matches(tmp_path):
    """Test 3: score < threshold → intent=None, matches=[]."""
    _write_kb(tmp_path, "testbldg")
    points = [_make_point("lift_details", 0.20)]
    router = _make_router(tmp_path, points=points)

    result = await router.classify("totally unrelated query", "testbldg")

    assert result.intent is None
    assert result.matches == []
    assert result.score == pytest.approx(0.20)


async def test_matches_grouped_by_entry_id(tmp_path):
    """Test 4: multiple raw points for same entry collapse to one match."""
    _write_kb(tmp_path, "testbldg")
    # Three raw hits, two for lift_details, one for fire_safety
    points = [
        _make_point("lift_details", 0.91),
        _make_point("lift_details", 0.85),
        _make_point("fire_safety", 0.30),
    ]
    router = _make_router(tmp_path, points=points)

    result = await router.classify("lift", "testbldg")

    # Distinct entry_ids only
    entry_ids = [m.entry_id for m in result.matches]
    assert entry_ids.count("lift_details") == 1, "Group-by must collapse duplicate entry_ids"


async def test_max_pool_score_per_entry(tmp_path):
    """Test 5: when an entry has hits [0.7, 0.8, 0.9], grouped score is 0.9 (max)."""
    _write_kb(tmp_path, "testbldg")
    points = [
        _make_point("lift_details", 0.70),
        _make_point("lift_details", 0.80),
        _make_point("lift_details", 0.90),  # this should win
    ]
    router = _make_router(tmp_path, points=points)

    result = await router.classify("lift", "testbldg")

    assert result.score == pytest.approx(0.90)
    assert result.matches[0].score == pytest.approx(0.90)


async def test_disabled_returns_source_disabled(tmp_path):
    """Test 6: capability_routing.enabled=false → source='disabled'."""
    _write_kb(tmp_path, "testbldg")
    _write_building_yaml(
        tmp_path,
        "testbldg",
        block="capability_routing:\n  enabled: false\n",
    )
    router = _make_router(tmp_path, points=[_make_point("lift_details", 0.99)])

    result = await router.classify("lift dimensions?", "testbldg")

    assert result.source == "disabled"
    assert result.intent is None
    assert result.score == 0.0


async def test_qdrant_down_returns_source_fallback(tmp_path):
    """Test 7: Qdrant exception → source='fallback', no exception escapes."""
    _write_kb(tmp_path, "testbldg")
    client = MagicMock()
    client.query_points = AsyncMock(side_effect=RuntimeError("connection refused"))
    router = _make_router(tmp_path, qdrant=client)

    result = await router.classify("lift?", "testbldg")

    assert result.source == "fallback"
    assert result.intent is None


async def test_collection_missing_returns_source_fallback(tmp_path):
    """Test 8: collection doesn't exist → Qdrant raises → fallback."""
    _write_kb(tmp_path, "testbldg")
    client = MagicMock()
    client.query_points = AsyncMock(
        side_effect=RuntimeError("Collection 'capability_bldg99' not found")
    )
    router = _make_router(tmp_path, qdrant=client)

    result = await router.classify("anything", "bldg99")

    assert result.source == "fallback"


async def test_per_building_threshold_honored(tmp_path):
    """Test 9: same query, different building thresholds → different decisions."""
    # bldg_strict: override_min=0.95, threshold=0.90 — score 0.92 is medium
    # bldg_lax:    override_min=0.80, threshold=0.60 — score 0.92 is high
    _write_kb(tmp_path, "bldg_strict")
    _write_kb(tmp_path, "bldg_lax")
    _write_building_yaml(
        tmp_path,
        "bldg_strict",
        block="capability_routing:\n  threshold: 0.90\n  override_min: 0.95\n",
    )
    _write_building_yaml(
        tmp_path,
        "bldg_lax",
        block="capability_routing:\n  threshold: 0.60\n  override_min: 0.80\n",
    )

    points = [_make_point("lift_details", 0.92)]

    router_strict = _make_router(tmp_path, points=points)
    r_strict = await router_strict.classify("lift?", "bldg_strict")
    assert r_strict.intent is None, "0.92 should NOT override at strict building"
    assert r_strict.score == pytest.approx(0.92)

    router_lax = _make_router(tmp_path, points=points)
    r_lax = await router_lax.classify("lift?", "bldg_lax")
    assert r_lax.intent == "capability", "0.92 SHOULD override at lax building"


async def test_top_k_respected(tmp_path):
    """Test 10: top_k=2 → at most 2 distinct entries in matches."""
    _write_kb(tmp_path, "testbldg")
    _write_building_yaml(
        tmp_path,
        "testbldg",
        block="capability_routing:\n  top_k: 2\n",
    )
    points = [
        _make_point("lift_details", 0.91),
        _make_point("fire_safety", 0.86),
        _make_point("hvac_zoning", 0.80),  # would be 3rd if top_k allowed
    ]
    router = _make_router(tmp_path, points=points)

    result = await router.classify("anything", "testbldg")

    assert len(result.matches) <= 2


async def test_register_intent_extension_hook(tmp_path):
    """Test 11: register_intent stores the binding for future extension."""
    router = SemanticRouter(
        qdrant_client=_make_qdrant_returning([]),
        embedding_service=_FakeEmbedder(),
        input_root=str(tmp_path),
    )
    router.register_intent("floor_plan", "spatial_")
    router.register_intent("spatial_query", "spatial_query_")

    assert "floor_plan" in router._intents
    assert router._intents["floor_plan"].collection_prefix == "spatial_"
    assert "spatial_query" in router._intents


async def test_embedding_failure_returns_fallback(tmp_path):
    """Test 12: EmbeddingService raises → source='fallback'."""
    _write_kb(tmp_path, "testbldg")
    embedder = _FakeEmbedder(fail=True)
    router = _make_router(tmp_path, embedder=embedder)

    result = await router.classify("lift?", "testbldg")

    assert result.source == "fallback"


async def test_empty_query_returns_no_intent(tmp_path):
    """Test 13: empty / whitespace input → no embedding attempted, no crash."""
    _write_kb(tmp_path, "testbldg")
    embedder = _FakeEmbedder()
    embedder_spy = MagicMock(wraps=embedder)
    embedder_spy.embed = AsyncMock(side_effect=embedder.embed)
    embedder_spy.dimension = embedder.dimension
    router = _make_router(tmp_path, embedder=embedder_spy)

    r1 = await router.classify("", "testbldg")
    r2 = await router.classify("   ", "testbldg")

    assert r1.intent is None
    assert r1.score == 0.0
    assert r2.intent is None
    assert r2.score == 0.0
    # Embed must NOT be called for empty input
    embedder_spy.embed.assert_not_called()


async def test_query_with_only_punctuation(tmp_path):
    """Test 14: '???' produces no crash; treated as empty content."""
    _write_kb(tmp_path, "testbldg")
    points = [_make_point("lift_details", 0.10)]
    router = _make_router(tmp_path, points=points)

    result = await router.classify("???", "testbldg")
    # Treated as a real query — gets embedded, but low score keeps it out
    assert result.intent is None
    assert result.matches == []


async def test_unicode_query_works(tmp_path):
    """Test 15: non-ASCII query doesn't crash; routes via score normally."""
    _write_kb(tmp_path, "testbldg")
    points = [_make_point("lift_details", 0.92)]
    router = _make_router(tmp_path, points=points)

    result = await router.classify("室温 lift dimension はどうですか?", "testbldg")
    assert result.intent == "capability"
    assert result.score == pytest.approx(0.92)


async def test_concurrent_classify_safe(tmp_path):
    """Test 16: 50 concurrent classify() calls all succeed with correct routing."""
    _write_kb(tmp_path, "testbldg")
    points = [_make_point("lift_details", 0.92)]
    router = _make_router(tmp_path, points=points)

    queries = [f"query number {i}" for i in range(50)]
    results = await asyncio.gather(
        *[router.classify(q, "testbldg") for q in queries]
    )

    assert len(results) == 50
    for r in results:
        assert r.intent == "capability"
        assert r.score == pytest.approx(0.92)


# ── Multi-intent extension (2026-05-22) ────────────────────────────────────────


async def test_multi_intent_no_extra_intents_registered_returns_capability_only(tmp_path):
    """Default (no intent_routing block): only capability intent is registered;
    classify() behaves exactly as before the multi-intent refactor."""
    _write_kb(tmp_path, "testbldg")
    points = [_make_point("lift_details", 0.92)]
    router = _make_router(tmp_path, points=points)

    # Only capability is registered → behavior matches the existing tests
    result = await router.classify("how big is the lift?", "testbldg")
    assert result.intent == "capability"


async def test_multi_intent_disabled_floor_plan_skipped(tmp_path):
    """When intent_routing.floor_plan.enabled=false, the router should not search
    that collection. Only capability should win."""
    _write_kb(tmp_path, "testbldg")
    _write_building_yaml(
        tmp_path, "testbldg",
        block=(
            "capability_routing:\n"
            "  enabled: true\n"
            "intent_routing:\n"
            "  floor_plan:\n"
            "    enabled: false\n"
            "    descriptors: ['show me the floor plan']\n"
        ),
    )
    points = [_make_point("lift_details", 0.92)]
    router = _make_router(tmp_path, points=points)
    router.register_intent("floor_plan", "intent_floor_plan_")

    result = await router.classify("how big is the lift?", "testbldg")
    # Capability still wins; floor_plan disabled → skipped without Qdrant query
    assert result.intent == "capability"


async def test_multi_intent_highest_score_wins(tmp_path):
    """When both capability and floor_plan return matches, the higher-scoring
    intent wins — regardless of registration order."""
    _write_kb(tmp_path, "testbldg")
    _write_building_yaml(
        tmp_path, "testbldg",
        block=(
            "capability_routing:\n"
            "  enabled: true\n"
            "  threshold: 0.50\n"
            "  override_min: 0.60\n"
            "intent_routing:\n"
            "  floor_plan:\n"
            "    enabled: true\n"
            "    descriptors: ['show me the floor plan', 'building layout']\n"
            "    threshold: 0.50\n"
            "    override_min: 0.60\n"
        ),
    )

    # Build a Qdrant mock that returns DIFFERENT points depending on which
    # collection is queried.
    cap_points = [_make_point("lift_details", 0.65)]  # capability score 0.65
    fp_points = [_make_point("0", 0.85, text="show me the floor plan")]  # floor_plan 0.85

    client = MagicMock()

    async def _query_points(collection_name, **kwargs):
        result = MagicMock()
        if "capability" in collection_name:
            result.points = cap_points
        elif "floor_plan" in collection_name:
            result.points = fp_points
        else:
            result.points = []
        return result

    client.query_points = AsyncMock(side_effect=_query_points)

    router = _make_router(tmp_path, qdrant=client)
    router.register_intent("floor_plan", "intent_floor_plan_")

    result = await router.classify("show me the floor plan", "testbldg")

    # floor_plan (0.85) > capability (0.65) → floor_plan wins
    assert result.intent == "floor_plan"
    assert result.score == pytest.approx(0.85)
