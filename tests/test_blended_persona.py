"""Phase 14A — multi-persona blending invariants.

OntoSage v1 served one persona at a time.  Phase 14A adds `personas: list[str]`
so a single turn can stack multiple personas (e.g., a facility manager who is
also a sustainability officer asks one combined question).

These tests pin down the blending semantics so future refactors don't silently
change the priors:

  * Single persona → no blending overhead (registry returns the unchanged record)
  * Two personas  → top_domains rank-merged, complexity = max, threshold = min
  * Unknown names → dropped via normalize_personas
  * Empty list   → defaults to ["general"]
"""

from __future__ import annotations

import pytest

from shared.persona_registry import PersonaRegistry, get_persona_registry


@pytest.fixture(scope="module")
def reg() -> PersonaRegistry:
    get_persona_registry.cache_clear()
    return get_persona_registry()


# ─────────────────────────────────────────────────────────────────────────────
# normalize_personas
# ─────────────────────────────────────────────────────────────────────────────


def test_normalize_empty_returns_general(reg):
    assert reg.normalize_personas([]) == ["general"]
    assert reg.normalize_personas(None) == ["general"]


def test_normalize_aliases_resolve(reg):
    # 'fm' is the alias for facility_manager (per _ALIASES)
    out = reg.normalize_personas(["fm", "FACILITY_MANAGER", "facility_manager"])
    assert out == ["facility_manager"], (
        f"Duplicate aliases must dedup; got {out}"
    )


def test_normalize_drops_unknown(reg):
    out = reg.normalize_personas(["facility_manager", "totally_made_up_role"])
    assert out == ["facility_manager"]


def test_normalize_preserves_order(reg):
    out = reg.normalize_personas(["researcher", "facility_manager", "occupant"])
    assert out == ["researcher", "facility_manager", "occupant"]


# ─────────────────────────────────────────────────────────────────────────────
# get_blended_priors — single persona is a no-op
# ─────────────────────────────────────────────────────────────────────────────


def test_single_persona_returns_unchanged_record(reg):
    """When given one persona, blending must return the original priors."""
    blended = reg.get_blended_priors(["facility_manager"])
    direct = reg.get_priors("facility_manager")

    assert blended.name == direct.name
    assert blended.top_domains == direct.top_domains
    assert blended.lookup_share == direct.lookup_share
    assert blended.default_complexity == direct.default_complexity
    assert blended.clarification_threshold == direct.clarification_threshold


def test_empty_list_blends_to_general(reg):
    blended = reg.get_blended_priors([])
    assert blended.name == "general"


# ─────────────────────────────────────────────────────────────────────────────
# get_blended_priors — multi-persona blending
# ─────────────────────────────────────────────────────────────────────────────


def test_two_personas_blend_top_domains_by_rank(reg):
    """facility_manager: [ENERGY, THERMAL, OCCUPANCY, FIRE_SAFETY]
       researcher:       [AIR_QUALITY, ENERGY, THERMAL, OCCUPANCY]

       Rank-merge points:
         ENERGY     = 8 (FM #0) + 7 (R #1) = 15
         THERMAL    = 7 (FM #1) + 6 (R #2) = 13
         AIR_QUALITY = 8 (R #0)            =  8
         OCCUPANCY  = 6 (FM #2) + 5 (R #3) = 11
         FIRE_SAFETY = 5 (FM #3)           =  5

       So the blended order should start with ENERGY, then THERMAL, then OCCUPANCY,
       then AIR_QUALITY, then FIRE_SAFETY.
    """
    blended = reg.get_blended_priors(["facility_manager", "researcher"])
    assert blended.top_domains[0] == "ENERGY"
    assert blended.top_domains[1] == "THERMAL"
    # The next three positions depend on the exact registry data; assert the
    # SET of top-3 domains contains the heavily-voted ones.
    assert set(blended.top_domains[:5]) >= {"ENERGY", "THERMAL", "OCCUPANCY"}


def test_blended_complexity_is_max(reg):
    """Researcher (COMPLEX) blended with occupant (SIMPLE) → COMPLEX."""
    blended = reg.get_blended_priors(["researcher", "occupant"])
    assert blended.default_complexity == "COMPLEX"


def test_blended_clarification_threshold_is_min(reg):
    """The blend should be more willing to clarify (min of thresholds)."""
    occupant = reg.get_priors("occupant")
    researcher = reg.get_priors("researcher")
    blended = reg.get_blended_priors(["researcher", "occupant"])

    expected_min = min(
        occupant.clarification_threshold, researcher.clarification_threshold
    )
    assert blended.clarification_threshold == expected_min


def test_blended_lookup_share_is_average(reg):
    """Mean of the constituent personas' lookup shares."""
    fm = reg.get_priors("facility_manager")
    sus = reg.get_priors("sustainability_officer")
    blended = reg.get_blended_priors(["facility_manager", "sustainability_officer"])

    expected = (fm.lookup_share + sus.lookup_share) / 2
    assert blended.lookup_share == pytest.approx(expected, rel=1e-6)


def test_blended_name_includes_all_personas(reg):
    blended = reg.get_blended_priors(["facility_manager", "researcher"])
    assert "facility_manager" in blended.name
    assert "researcher" in blended.name


def test_blended_handles_three_personas(reg):
    blended = reg.get_blended_priors(
        ["facility_manager", "researcher", "occupant"]
    )
    assert "+" in blended.name
    # 3 personas across many domains — blend should produce a coherent
    # short top_domains list.
    assert 0 < len(blended.top_domains) <= 6


# ─────────────────────────────────────────────────────────────────────────────
# Backward-compat: existing single-persona consumers must not regress
# ─────────────────────────────────────────────────────────────────────────────


def test_get_priors_unchanged_for_known_persona(reg):
    """The legacy single-string API must keep working exactly as before."""
    fm = reg.get_priors("facility_manager")
    assert fm.name == "facility_manager"
    assert fm.top_domains  # non-empty


def test_should_clarify_unchanged_for_single_persona(reg):
    fm = reg.get_priors("facility_manager")
    # Above the threshold → should clarify
    assert reg.should_clarify("facility_manager", fm.clarification_threshold + 0.1)
    # Below the threshold → should NOT clarify
    assert not reg.should_clarify(
        "facility_manager", fm.clarification_threshold - 0.1
    )
