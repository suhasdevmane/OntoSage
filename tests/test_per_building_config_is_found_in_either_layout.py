# -*- coding: utf-8 -*-
"""Six loaders searched a layout the system never produces (CAVEAT-448, V10 W2-3).

WHAT WENT WRONG
---------------
`rules.yaml`, `channels.yaml`, `recipes.yaml`, `goals.yaml` and their siblings were each
loaded by a hand-written search that looked ONLY at `input/<building_id>/<file>`.

The canonical layout is FLAT. Under swap-by-rename the active building's files sit directly
in `input/`, and the nested form exists nowhere in this repository. So:

    input/rules.yaml      exists     — the ECA rules engine never loaded it
    input/channels.yaml   exists     — notification dispatch never loaded it

Both features had been dark for every building, and the log line was *"no rules.yaml for
building 'bldg1' — feed framework idle"*, which reads exactly like a building that chose not
to configure any.

`shared/building_paths.resolve_building_file` has existed for this since the flat layout
landed, and tries nested then flat. Ten files used it; the same logic was written five more
times, and every one of the copies was wrong.

WHAT THESE TESTS PIN
--------------------
1. The active building's files resolve, whichever layout they are in.
2. Each migrated loader delegates rather than carrying a sixth copy.
3. A file present in the FLAT layout is found -- the case that was broken.
"""

from __future__ import annotations

import inspect
from pathlib import Path

import pytest

pytestmark = pytest.mark.unit

REPO = Path(__file__).resolve().parent.parent


def test_the_flat_layout_resolves(tmp_path):
    """The broken case, in isolation."""
    from shared.building_paths import resolve_building_file

    (tmp_path / "rules.yaml").write_text("rules: []\n", encoding="utf-8")
    got = resolve_building_file("bldgX", "rules.yaml", input_root=tmp_path)
    assert got == tmp_path / "rules.yaml"


def test_the_nested_layout_still_wins_when_both_exist(tmp_path):
    """Precedence is part of the contract: an explicit per-building file outranks."""
    from shared.building_paths import resolve_building_file

    (tmp_path / "rules.yaml").write_text("rules: []\n", encoding="utf-8")
    nested = tmp_path / "bldgX"
    nested.mkdir()
    (nested / "rules.yaml").write_text("rules: []\n", encoding="utf-8")
    assert resolve_building_file("bldgX", "rules.yaml", input_root=tmp_path) == (
        nested / "rules.yaml"
    )


@pytest.mark.parametrize(
    "module_path, symbol, filename",
    [
        ("orchestrator.services.rules_engine", "RulesEngine._find_yaml", "rules.yaml"),
        (
            "orchestrator.services.notification_service",
            "NotificationService._find_yaml",
            "channels.yaml",
        ),
        ("orchestrator.services.goal_planner", "_find_building_overlay", "goals.yaml"),
        (
            "orchestrator.services.recipe_registry",
            "_resolve_building_overlay",
            "recipes.yaml",
        ),
    ],
)
def test_each_loader_delegates_to_the_one_resolver(module_path, symbol, filename):
    import importlib

    mod = importlib.import_module(module_path)
    obj = mod
    for part in symbol.split("."):
        obj = getattr(obj, part)
    src = inspect.getsource(obj)
    assert "resolve_building_file" in src, (
        f"{module_path}.{symbol} carries its own search again; that is the sixth copy, and "
        f"five of the previous five were wrong"
    )
    assert f'"{filename}"' in src


def test_the_active_buildings_rules_and_channels_are_reachable():
    """The live consequence, asserted against whatever the tree holds.

    Skips rather than fails when a file is absent -- a building need not declare rules --
    but when one IS present the loader must find it. That distinction is the whole defect:
    "absent" and "present but unreachable" looked identical in the log.
    """
    from shared.building_paths import resolve_building_file

    active = REPO / "input"
    if not (active / "building.yaml").exists():
        pytest.skip("no active building (parked state)")

    import yaml

    building_id = str(
        (yaml.safe_load((active / "building.yaml").read_text(encoding="utf-8")) or {}).get(
            "building_id"
        )
        or ""
    )
    assert building_id, "the active building.yaml declares no building_id"

    for name in ("rules.yaml", "channels.yaml", "feeds.yaml", "intents.yaml"):
        if not (active / name).exists():
            continue
        assert resolve_building_file(building_id, name) is not None, (
            f"{name} sits in input/ and the resolver cannot find it, so whatever reads it "
            f"is silently switched off"
        )
