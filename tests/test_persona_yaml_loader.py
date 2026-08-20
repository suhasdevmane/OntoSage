"""Phase 5 — YAML-driven persona loader tests.

Verifies:
  1. With no YAML present the hardcoded defaults are unchanged.
  2. A YAML file in input/personas/ defines a new persona.
  3. Aliases declared in YAML resolve via PersonaRegistry.
  4. Per-building YAML overrides global YAML overrides hardcoded defaults.
  5. Malformed YAML is tolerated (logged, then skipped).
  6. The legacy 10 personas remain reachable.
"""

from __future__ import annotations

from pathlib import Path
from unittest.mock import patch

import pytest
import yaml

from shared import persona_loader, persona_registry


@pytest.fixture
def clear_singleton():
    """Reset the lru_cached singleton between tests."""
    persona_registry.get_persona_registry.cache_clear()
    yield
    persona_registry.get_persona_registry.cache_clear()


# ─────────────────────────────────────────────────────────────────────────────
# Loader behaviour
# ─────────────────────────────────────────────────────────────────────────────


def test_loader_returns_empty_when_no_dirs(tmp_path, clear_singleton):
    with patch.object(persona_loader, "_GLOBAL_PERSONA_DIRS", [tmp_path / "nope"]):
        data, aliases = persona_loader.load_persona_overlays(None)
    assert data == {}
    assert aliases == {}


def test_loader_reads_yaml_file(tmp_path, clear_singleton):
    p = tmp_path / "caretaker.yaml"
    p.write_text(
        yaml.dump(
            {
                "name": "caretaker",
                "description": "test caretaker",
                "aliases": ["janitor"],
                "top_domains": ["FIRE_SAFETY"],
                "lookup_share": 0.9,
                "default_complexity": "SIMPLE",
                "clarification_threshold": 0.3,
                "borda_topics": ["Maintenance"],
            }
        )
    )
    with patch.object(persona_loader, "_GLOBAL_PERSONA_DIRS", [tmp_path]):
        data, aliases = persona_loader.load_persona_overlays(None)
    assert "caretaker" in data
    assert data["caretaker"]["description"] == "test caretaker"
    assert aliases.get("janitor") == "caretaker"


def test_loader_skips_malformed_yaml(tmp_path, clear_singleton):
    (tmp_path / "broken.yaml").write_text("not valid YAML: {[}")
    (tmp_path / "good.yaml").write_text(
        yaml.dump(
            {
                "name": "good",
                "description": "fine",
                "top_domains": ["THERMAL"],
                "lookup_share": 0.5,
                "default_complexity": "MODERATE",
                "clarification_threshold": 0.5,
                "borda_topics": [],
            }
        )
    )
    with patch.object(persona_loader, "_GLOBAL_PERSONA_DIRS", [tmp_path]):
        data, _ = persona_loader.load_persona_overlays(None)
    assert "good" in data
    # broken file silently dropped
    assert "broken" not in data


def test_per_building_overrides_global(tmp_path, clear_singleton):
    global_dir = tmp_path / "global"
    bldg_dir = tmp_path / "bldg1" / "personas"
    global_dir.mkdir()
    bldg_dir.mkdir(parents=True)
    (global_dir / "occupant.yaml").write_text(
        yaml.dump(
            {
                "name": "occupant",
                "description": "GLOBAL",
                "top_domains": ["THERMAL"],
                "lookup_share": 0.7,
                "default_complexity": "SIMPLE",
                "clarification_threshold": 0.4,
                "borda_topics": [],
            }
        )
    )
    (bldg_dir / "occupant.yaml").write_text(
        yaml.dump(
            {
                "name": "occupant",
                "description": "PER-BUILDING",
                "top_domains": ["AIR_QUALITY"],
                "lookup_share": 0.9,
                "default_complexity": "SIMPLE",
                "clarification_threshold": 0.2,
                "borda_topics": [],
            }
        )
    )
    with (
        patch.object(persona_loader, "_GLOBAL_PERSONA_DIRS", [global_dir]),
        patch.object(
            persona_loader,
            "_per_building_persona_dirs",
            lambda bid: [bldg_dir] if bid == "bldg1" else [],
        ),
    ):
        data, _ = persona_loader.load_persona_overlays("bldg1")
    assert data["occupant"]["description"] == "PER-BUILDING"
    assert data["occupant"]["lookup_share"] == 0.9


# ─────────────────────────────────────────────────────────────────────────────
# Registry integration
# ─────────────────────────────────────────────────────────────────────────────


def test_legacy_personas_still_reachable(clear_singleton):
    """All 10 hardcoded personas remain available with no YAML."""
    with patch.object(persona_loader, "_GLOBAL_PERSONA_DIRS", []):
        reg = persona_registry.PersonaRegistry()
    legacy = {
        "occupant",
        "facility_manager",
        "researcher",
        "it_admin",
        "safety_officer",
        "student",
        "executive",
        "sustainability_officer",
        "visitor",
        "general",
    }
    assert legacy.issubset(set(reg.all_personas()))


def test_yaml_persona_resolves_via_registry(tmp_path, clear_singleton):
    yaml_dir = tmp_path / "personas"
    yaml_dir.mkdir()
    (yaml_dir / "caretaker.yaml").write_text(
        yaml.dump(
            {
                "name": "caretaker",
                "description": "test caretaker",
                "aliases": ["janitor", "cleaner"],
                "top_domains": ["FIRE_SAFETY"],
                "lookup_share": 0.9,
                "default_complexity": "SIMPLE",
                "clarification_threshold": 0.3,
                "borda_topics": ["Maintenance"],
            }
        )
    )
    with patch.object(persona_loader, "_GLOBAL_PERSONA_DIRS", [yaml_dir]):
        reg = persona_registry.PersonaRegistry()
    assert "caretaker" in reg.all_personas()
    assert reg.get_priors("caretaker").name == "caretaker"
    assert reg.get_priors("janitor").name == "caretaker"
    assert reg.get_priors("cleaner").name == "caretaker"
    assert reg.get_priors("unknown_persona_name").name == "general"


def test_yaml_can_override_hardcoded_persona(tmp_path, clear_singleton):
    """A YAML entry with the same name as a hardcoded persona overrides it."""
    yaml_dir = tmp_path / "personas"
    yaml_dir.mkdir()
    (yaml_dir / "executive.yaml").write_text(
        yaml.dump(
            {
                "name": "executive",
                "description": "OVERRIDDEN",
                "top_domains": ["INFORMATIONAL"],
                "lookup_share": 0.99,
                "default_complexity": "SIMPLE",
                "clarification_threshold": 0.1,
                "borda_topics": ["Whatever"],
            }
        )
    )
    with patch.object(persona_loader, "_GLOBAL_PERSONA_DIRS", [yaml_dir]):
        reg = persona_registry.PersonaRegistry()
    priors = reg.get_priors("executive")
    assert priors.description == "OVERRIDDEN"
    assert priors.lookup_share == 0.99


def test_registry_aliases_includes_yaml_aliases(tmp_path, clear_singleton):
    yaml_dir = tmp_path / "personas"
    yaml_dir.mkdir()
    (yaml_dir / "caretaker.yaml").write_text(
        yaml.dump(
            {
                "name": "caretaker",
                "description": "x",
                "aliases": ["JANITOR"],
                "top_domains": [],
                "lookup_share": 0.5,
                "default_complexity": "SIMPLE",
                "clarification_threshold": 0.3,
                "borda_topics": [],
            }
        )
    )
    with patch.object(persona_loader, "_GLOBAL_PERSONA_DIRS", [yaml_dir]):
        reg = persona_registry.PersonaRegistry()
    # aliases() returns the merged map; YAML alias is lower-cased on read
    assert reg.aliases().get("janitor") == "caretaker"
