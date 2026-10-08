"""The commit gate and CI must be able to run the same tests (scripts/run_ci_unit_tests.py).

``pytest -m unit`` and CI's hand-listed files overlap without either containing the other, which
let three CI tests fail for weeks behind a green commit gate (2026-10-08). The runner reads the file
list out of ci.yml, so these tests only have to prove the list is non-empty and still names files
that exist.
"""

import importlib.util
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parent.parent


def _runner():
    spec = importlib.util.spec_from_file_location(
        "run_ci_unit_tests", REPO / "scripts" / "run_ci_unit_tests.py"
    )
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


@pytest.mark.unit
def test_ci_names_a_unit_test_step_with_files():
    files, _ = _runner().ci_unit_step()
    assert len(files) >= 10, f"CI's unit-test step lists suspiciously few files: {files}"


@pytest.mark.unit
def test_every_file_ci_lists_exists():
    files, _ = _runner().ci_unit_step()
    missing = [f for f in files if not (REPO / f).is_file()]
    assert not missing, f"ci.yml's unit-test step lists files that do not exist: {missing}"
