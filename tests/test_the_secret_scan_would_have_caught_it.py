# -*- coding: utf-8 -*-
"""The pre-commit secret scan catches what it exists to catch (BUG-507).

WHAT WENT WRONG
---------------
The live ``ADMIN_PASSWORD`` was committed in ``3756e8a`` (2026-07-08) inside a runnable
login example in ``tasks/REVIEW_AND_EXTEND_PROMPT.md``, and pushed. Untracking ``tasks/`` a
month later hid it from every present-tense check without removing the blob.

WHY A TEST AND NOT JUST THE SCRIPT
----------------------------------
``check_building_literals.py`` once scanned two directories and reported "clean" while
fifteen real literals sat outside its scope. A guard whose coverage nobody asserts will
quietly stop covering things, and the failure mode is silence -- exactly what you cannot
notice. So this pins the four behaviours the guard is FOR, not that it imports.

The negative cases matter as much as the positive one. The first run of this scanner
produced eight findings of which zero were real: a shell variable reference that was the
FIX, and a seeded test login that exists to be committed. A guard that cries wolf gets
``--no-verify``, and a bypassed guard protects nothing.
"""

from __future__ import annotations

import importlib.util
from pathlib import Path

import pytest

pytestmark = pytest.mark.unit

REPO = Path(__file__).resolve().parent.parent
SCRIPT = REPO / "scripts" / "check_staged_secrets.py"


def _guard():
    spec = importlib.util.spec_from_file_location("_secret_guard", SCRIPT)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


@pytest.fixture(scope="module")
def guard():
    assert SCRIPT.is_file(), f"the guard itself is missing: {SCRIPT}"
    return _guard()


def test_the_hook_is_tracked_and_git_is_pointed_at_it(guard):
    """A hook in .git/hooks protects one machine. This project needs it in the clone."""
    hook = REPO / ".githooks" / "pre-commit"
    assert hook.is_file(), ".githooks/pre-commit is missing; a clone would have no scan"
    body = hook.read_text(encoding="utf-8")
    assert "check_staged_secrets.py" in body
    assert "core.hooksPath" in body, "the hook must say how to enable itself"


def test_a_pasted_credential_is_an_error_not_a_warning(guard):
    """The exact failure of BUG-507: a real password inside a runnable example."""
    secret = "S0me-Real-Passw0rd-Value!"
    guard._env_secrets = lambda: {".env:ADMIN_PASSWORD": secret}  # type: ignore[attr-defined]
    errors, _ = guard.scan(["note.md"], lambda _p: f'curl -d \'{{"password":"{secret}"}}\'\n')
    assert errors, "a live credential in staged content must block the commit"
    assert any("LIVE CREDENTIAL" in e for e in errors)
    assert secret not in "".join(errors), "the guard must not print the secret it caught"


def test_a_credential_filename_is_refused_whatever_it_contains(guard):
    for name in (".env", ".env1", "user_credentials_bldg1.csv", "certs/server.pem"):
        errors, _ = guard.scan([name], lambda _p: "nothing sensitive here\n")
        assert errors, f"{name} must never be committable"


def test_a_template_is_not_a_credential_file(guard):
    """`.env2.example` is the file that documents what to fill in. Blocking it is absurd."""
    for name in (".env.example", ".env2.example", ".env3.example"):
        errors, _ = guard.scan([name], lambda _p: "MYSQL_PASSWORD=change-me\n")
        assert not errors, f"{name} is a template and must stay committable"


def test_a_shell_variable_reference_is_not_flagged(guard):
    """`"$ADMIN_PASSWORD"` is the REMEDY. Flagging it punishes the fix."""
    guard._env_secrets = lambda: {}  # type: ignore[attr-defined]
    _, infos = guard.scan(["ok.sh"], lambda _p: 'curl -d \'{"password":"$ADMIN_PASSWORD"}\'\n')
    assert not infos, "a variable reference must not be reported"


def test_an_unchanged_default_is_hygiene_not_disclosure(guard):
    """STRICT_SECRETS owns defaults, at boot. Reporting them here would train --no-verify."""
    default = "Admin@GraphDB2024"
    guard._env_secrets = lambda: {".env:GRAPHDB_PASSWORD": default}  # type: ignore[attr-defined]
    guard._benign_values = lambda: {default}  # type: ignore[attr-defined]
    errors, _ = guard.scan(["compose.yml"], lambda _p: f"GRAPHDB_PASSWORD={default}\n")
    assert not errors, "an unchanged default is not a disclosure"


def test_it_refuses_rather_than_reporting_clean_from_a_starved_input(guard):
    """A guard that returns 0 because it could not run is worse than no guard."""
    body = SCRIPT.read_text(encoding="utf-8")
    assert "return 2" in body, "there must be a distinct could-not-run exit code"
    assert "refusing to report clean" in body
