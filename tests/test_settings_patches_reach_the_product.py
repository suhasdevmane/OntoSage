"""A settings patch must reach the object the product reads (CAVEAT-1060, lesson #159).

``tests/test_strict_secrets.py`` calls ``importlib.reload(shared.config)`` — correctly; it
is testing boot-time validation. The reload rebuilds the module's ``settings`` attribute,
but ``from shared.config import settings`` bound the OLD object into every module that ran
that line earlier, and those modules keep it forever. So after the reload there are two
Settings objects alive, and a patch applied to the wrong one changes nothing.

Three tests were found failing that way and were the LUCKY ones: a detached patch usually
leaves the test running against the REAL setting, which often still satisfies the
assertion. Measured on the eight files that held the 25 unaudited sites: with every
settings patch turned into a no-op, **15 of the 25 still passed** — five of them because
the patched value was the value the setting already had.

The rule this file pins:

* the product binds ``settings`` at module level  -> patch ``product_module.settings``
* the product imports it inside the function      -> patch the LIVE object, i.e. look it
  up at call time (``import shared.config as cfg`` then ``cfg.settings``, or an import
  inside the test body)

The form that is never provably right is a MODULE-level ``from shared.config import
settings`` in a test plus ``monkeypatch.setattr(settings, ...)``: that object is stale by
construction after a reload, and it works only while the product happens to hold the same
stale object. The scan below finds that form by parsing, not by matching text, so a
reformat cannot move it (lesson #151).

WHAT THIS DOES NOT CATCH, said plainly so nobody trusts it further than it goes. The other
mismatch — an import inside the TEST body (which resolves the live object) against a
product module that bound at import time (which does not) — is the one that broke the three
tests in lesson #159, and a parser cannot decide it: whether that form is right depends on
how the product module imports, which is only knowable by importing it. The instrument that
does decide it is a plugin that reloads ``shared.config`` after collection and reports, per
patch, whether the object equals ``shared.config.settings`` or is held by the module under
test; it is written up on CAVEAT-1110 and takes about ten minutes to rebuild. Run it when a
settings patch is suspected, not on every build.
"""

from __future__ import annotations

import ast
import importlib
import sys
from pathlib import Path
from typing import List, Tuple

import pytest

pytestmark = pytest.mark.unit

TESTS_DIR = Path(__file__).resolve().parent


# ── the mechanism, demonstrated rather than asserted ──────────────────────────


def _write_module(tmp_path: Path, name: str, body: str) -> None:
    (tmp_path / f"{name}.py").write_text(body, encoding="utf-8")


def test_a_reload_detaches_every_module_level_importer(tmp_path, monkeypatch):
    """`from X import y` binds the OBJECT; reloading X rebinds only X's own attribute.

    Shown on a throwaway pair of modules so the demonstration costs no session state —
    reloading `shared.config` here would hand every later test a different Settings.
    """
    _write_module(tmp_path, "cfg_probe", "class Cfg:\n    flag = 1\n\n\nsettings = Cfg()\n")
    _write_module(
        tmp_path,
        "consumer_probe",
        "from cfg_probe import settings\n\n\ndef read():\n    return settings.flag\n",
    )
    monkeypatch.syspath_prepend(str(tmp_path))
    for name in ("cfg_probe", "consumer_probe"):
        sys.modules.pop(name, None)

    import cfg_probe  # noqa: E402
    import consumer_probe  # noqa: E402

    assert consumer_probe.settings is cfg_probe.settings

    importlib.reload(cfg_probe)

    assert consumer_probe.settings is not cfg_probe.settings, (
        "if this ever passes, the premise of CAVEAT-1060 has changed and the scan below "
        "can be retired"
    )

    # And the consequence that makes a test vacuous: patching the RELOADED object leaves
    # the consumer reading the old one.
    cfg_probe.settings.flag = 99
    assert consumer_probe.read() == 1, "the patch reached nothing, silently"

    for name in ("cfg_probe", "consumer_probe"):
        sys.modules.pop(name, None)


# ── the scan ──────────────────────────────────────────────────────────────────


def _module_level_settings_aliases(tree: ast.Module) -> set:
    """Names bound to a `shared.config` settings object at MODULE scope.

    Only module scope matters: a binding made inside a test body is created while the test
    runs, so it is whatever `shared.config` currently exposes — which is the right object
    for a product module that also imports lazily.
    """
    names = set()
    config_modules = set()
    for node in tree.body:
        if isinstance(node, ast.Import):
            for alias in node.names:
                if alias.name == "shared.config":
                    config_modules.add(alias.asname or alias.name)
        elif isinstance(node, ast.ImportFrom) and node.module == "shared.config":
            for alias in node.names:
                if alias.name == "settings":
                    names.add(alias.asname or alias.name)
        elif isinstance(node, ast.Assign):
            # `s = cfg.settings` at module scope captures the object exactly as
            # `from shared.config import settings` does. The module alias is read from the
            # file's own imports — guessing it from the spelling missed `cfg`, which is
            # what the self-check below exists to catch.
            value = node.value
            if isinstance(value, ast.Attribute) and value.attr == "settings":
                if ast.unparse(value.value) in config_modules:
                    for target in node.targets:
                        if isinstance(target, ast.Name):
                            names.add(target.id)
    return names


def _bare_monkeypatch_setattr_targets(tree: ast.Module) -> List[Tuple[str, int]]:
    """Every `monkeypatch.setattr(<bare name>, ...)` with its line number."""
    hits: List[Tuple[str, int]] = []
    for node in ast.walk(tree):
        if not isinstance(node, ast.Call):
            continue
        fn = node.func
        if not (isinstance(fn, ast.Attribute) and fn.attr == "setattr"):
            continue
        if not (isinstance(fn.value, ast.Name) and fn.value.id == "monkeypatch"):
            continue
        if node.args and isinstance(node.args[0], ast.Name):
            hits.append((node.args[0].id, node.lineno))
    return hits


def _detachable_sites():
    found = []
    for path in sorted(TESTS_DIR.rglob("test_*.py")):
        try:
            tree = ast.parse(path.read_text(encoding="utf-8"))
        except SyntaxError:  # a file that cannot parse is another test's problem
            continue
        aliases = _module_level_settings_aliases(tree)
        if not aliases:
            continue
        for name, lineno in _bare_monkeypatch_setattr_targets(tree):
            if name in aliases:
                found.append(f"{path.name}:{lineno}")
    return found


def test_the_scan_can_actually_see_the_pattern_it_looks_for():
    """A scan that finds nothing because it looks for nothing is the worst outcome here.

    lessons #20-22: a guard that fails open must not be indistinguishable from a guard that
    found nothing. This feeds the scan's two halves a synthetic file containing exactly the
    defect and requires both to fire.
    """
    source = (
        "from shared.config import settings\n"
        "\n"
        "\n"
        "def test_x(monkeypatch):\n"
        "    monkeypatch.setattr(settings, 'FLAG', True)\n"
    )
    tree = ast.parse(source)
    assert _module_level_settings_aliases(tree) == {"settings"}
    assert _bare_monkeypatch_setattr_targets(tree) == [("settings", 5)]

    aliased = ast.parse(
        "import shared.config as cfg\n"
        "\n"
        "s = cfg.settings\n"
        "\n"
        "\n"
        "def test_y(monkeypatch):\n"
        "    monkeypatch.setattr(s, 'FLAG', True)\n"
    )
    assert "s" in _module_level_settings_aliases(aliased)

    clean = ast.parse(
        "from orchestrator.services import ontology_manager as om\n"
        "\n"
        "\n"
        "def test_z(monkeypatch):\n"
        "    monkeypatch.setattr(om.settings, 'FLAG', True)\n"
    )
    assert _module_level_settings_aliases(clean) == set()
    assert _bare_monkeypatch_setattr_targets(clean) == []


def test_no_test_patches_a_settings_object_a_reload_would_detach():
    """CAVEAT-1060: the 25 sites this was written for are fixed; keep it that way."""
    sites = _detachable_sites()
    assert sites == [], (
        "these patch a module-level `settings` that a `shared.config` reload detaches, so "
        "they change nothing once tests/test_strict_secrets.py has run and the assertion "
        "then measures the REAL setting: "
        + ", ".join(sites)
        + " — patch `<module_under_test>.settings` when that module imports settings at "
        "import time, or look the live object up at call time when it imports lazily"
    )
