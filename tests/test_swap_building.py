"""Phase 15B-2 — swap_building.py CLI integration tests.

These tests shell-execute the actual `scripts/swap_building.py` against a
synthetic input directory under tmp_path.  We exercise:

  * Valid swap (dry-run mode) → exit 0, validation messages present
  * TTL/namespace mismatch → exit 2, mismatch reason on stderr
  * Missing building dir → exit 2
  * Already-active building (no-op) → exit 0
  * --no-cache-flush respected (no docker invocation attempted)
"""

from __future__ import annotations

import subprocess
import sys
from pathlib import Path

import pytest


REPO_ROOT = Path(__file__).parent.parent
SCRIPT = REPO_ROOT / "scripts" / "swap_building.py"


GOOD_TTL = """\
@prefix rdf:   <http://www.w3.org/1999/02/22-rdf-syntax-ns#> .
@prefix brick: <https://brickschema.org/schema/Brick#> .
@prefix bldg:  <http://swap-test.example/test-bldg#> .

bldg:Sensor_A a brick:Temperature_Sensor .
"""

MISMATCH_TTL = """\
@prefix rdf:   <http://www.w3.org/1999/02/22-rdf-syntax-ns#> .
@prefix brick: <https://brickschema.org/schema/Brick#> .
@prefix bldg:  <http://WRONG.example/different#> .

bldg:Sensor_A a brick:Temperature_Sensor .
"""

GOOD_BUILDING_YAML = """\
building_id: test_bldg
building_name: Test Building
ontology_namespace: http://swap-test.example/test-bldg#
building_prefix: bldg
"""


def _stage_building(input_root: Path, building_id: str, ttl_content: str) -> Path:
    bldg = input_root / building_id
    bldg.mkdir(parents=True)
    (bldg / "building.yaml").write_text(GOOD_BUILDING_YAML, encoding="utf-8")
    (bldg / "instance.ttl").write_text(ttl_content, encoding="utf-8")
    return bldg


def _run_swap(*args: str, env_file: Path, input_root: Path) -> subprocess.CompletedProcess:
    """Invoke the swap CLI with --no-cache-flush so tests don't touch docker."""
    cmd = [
        sys.executable, str(SCRIPT),
        "--env", str(env_file),
        "--input-root", str(input_root),
        "--no-cache-flush",
        *args,
    ]
    return subprocess.run(
        cmd, capture_output=True, text=True, timeout=60, cwd=str(REPO_ROOT)
    )


@pytest.fixture
def env_file(tmp_path: Path) -> Path:
    p = tmp_path / ".env"
    p.write_text("BUILDING_ID=bldg_old\nMODEL_PROVIDER=openai\n", encoding="utf-8")
    return p


# ─────────────────────────────────────────────────────────────────────────────
# Happy path
# ─────────────────────────────────────────────────────────────────────────────


def test_valid_swap_dry_run_exits_clean(tmp_path: Path, env_file: Path):
    """A valid building with matching TTL/namespace passes validation and
    reports what it would do without touching anything."""
    input_root = tmp_path / "input"
    input_root.mkdir()
    _stage_building(input_root, "test_bldg", GOOD_TTL)

    result = _run_swap("--to", "test_bldg", "--dry-run",
                       env_file=env_file, input_root=input_root)

    assert result.returncode == 0, (
        f"Expected exit 0; got {result.returncode}.  stdout=\n{result.stdout}\n"
        f"stderr=\n{result.stderr}"
    )
    assert "test_bldg" in result.stdout
    assert "[OK]" in result.stdout
    assert "DRY-RUN" in result.stdout

    # .env must NOT have been modified
    env_after = env_file.read_text(encoding="utf-8")
    assert "BUILDING_ID=bldg_old" in env_after, (
        f"Dry-run unexpectedly wrote to .env: {env_after}"
    )


def test_valid_swap_applies_env_update(tmp_path: Path, env_file: Path):
    """Live (non-dry-run) swap writes the new BUILDING_ID to .env."""
    input_root = tmp_path / "input"
    input_root.mkdir()
    _stage_building(input_root, "test_bldg", GOOD_TTL)

    result = _run_swap("--to", "test_bldg",
                       env_file=env_file, input_root=input_root)

    assert result.returncode == 0, result.stderr or result.stdout

    env_after = env_file.read_text(encoding="utf-8")
    assert "BUILDING_ID=test_bldg" in env_after
    assert "BUILDING_ID=bldg_old" not in env_after


# ─────────────────────────────────────────────────────────────────────────────
# Failure paths — each must exit 2 with a clear reason
# ─────────────────────────────────────────────────────────────────────────────


def test_namespace_mismatch_rejects(tmp_path: Path, env_file: Path):
    """TTL declares wrong @prefix bldg: → swap aborts before touching .env."""
    input_root = tmp_path / "input"
    input_root.mkdir()
    _stage_building(input_root, "test_bldg", MISMATCH_TTL)

    result = _run_swap("--to", "test_bldg", "--dry-run",
                       env_file=env_file, input_root=input_root)

    assert result.returncode == 2, (
        f"Expected exit 2 for namespace mismatch; got {result.returncode}.\n"
        f"stdout={result.stdout}\nstderr={result.stderr}"
    )
    # The user-facing failure must mention "mismatch" and both namespaces.
    combined = result.stdout + result.stderr
    assert "mismatch" in combined.lower()
    assert "WRONG" in combined or "wrong" in combined.lower()


def test_missing_building_dir_rejects(tmp_path: Path, env_file: Path):
    """input/<new>/ doesn't exist → swap aborts."""
    input_root = tmp_path / "input"
    input_root.mkdir()
    # Don't stage anything.

    result = _run_swap("--to", "ghost_bldg", "--dry-run",
                       env_file=env_file, input_root=input_root)

    assert result.returncode == 2
    combined = result.stdout + result.stderr
    assert "does NOT exist" in combined or "does not exist" in combined.lower()


def test_building_yaml_id_mismatch_rejects(tmp_path: Path, env_file: Path):
    """building.yaml declares building_id != directory name → reject."""
    input_root = tmp_path / "input"
    input_root.mkdir()
    bldg = input_root / "test_bldg"
    bldg.mkdir()
    # building_id intentionally doesn't match the directory.
    (bldg / "building.yaml").write_text(
        "building_id: different_name\n"
        "building_name: Test\n"
        "ontology_namespace: http://test/\n",
        encoding="utf-8",
    )

    result = _run_swap("--to", "test_bldg", "--dry-run",
                       env_file=env_file, input_root=input_root)

    assert result.returncode == 2
    combined = result.stdout + result.stderr
    assert "different_name" in combined or "must match" in combined.lower()


# ─────────────────────────────────────────────────────────────────────────────
# No-op paths
# ─────────────────────────────────────────────────────────────────────────────


def test_same_building_no_op(tmp_path: Path, env_file: Path):
    """If BUILDING_ID is already the target, exit 0 immediately."""
    env_file.write_text("BUILDING_ID=test_bldg\n", encoding="utf-8")
    input_root = tmp_path / "input"
    input_root.mkdir()
    _stage_building(input_root, "test_bldg", GOOD_TTL)

    result = _run_swap("--to", "test_bldg", "--dry-run",
                       env_file=env_file, input_root=input_root)

    assert result.returncode == 0
    combined = result.stdout + result.stderr
    assert (
        "already" in combined.lower()
        or "nothing to do" in combined.lower()
    ), f"Expected no-op message; got: {combined}"
