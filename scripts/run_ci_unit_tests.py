# -*- coding: utf-8 -*-
"""Run exactly the tests GitHub Actions runs in its "Run unit tests" step.

    python scripts/run_ci_unit_tests.py

WHY THIS EXISTS. The commit gate is ``pytest -m unit`` (CLAUDE.md, Workflow rule 8), and that
selects only tests carrying the ``unit`` marker. CI runs a hand-listed set of files with no marker
filter. The two overlap but neither contains the other, so a test CI runs can be deselected by the
commit gate: on 2026-10-08 three tests in CI's list had been failing since August (one asserted
behaviour removed on 2026-08-20), CI sat red for days, and the commit gate stayed green throughout
because it never ran them.

The file list is read from ``.github/workflows/ci.yml`` at run time rather than copied here, so
this script cannot drift from CI. Run it in the PARKED state (no ``input/``, ``.env`` or
``docker-compose.yml``) -- that is what the CI runner checks out.
"""
from __future__ import annotations

import importlib.util
import os
import shlex
import subprocess
import sys
from pathlib import Path
from typing import List, Tuple

import yaml

REPO = Path(__file__).resolve().parent.parent
STEP_NAME = "Run unit tests"


def ci_unit_step() -> Tuple[List[str], dict]:
    """The test files and the environment of CI's unit-test step, read from ci.yml."""
    workflow = yaml.safe_load(
        (REPO / ".github" / "workflows" / "ci.yml").read_text(encoding="utf-8")
    )
    for job in (workflow.get("jobs") or {}).values():
        for step in job.get("steps") or []:
            if step.get("name") == STEP_NAME:
                tokens = shlex.split((step.get("run") or "").replace("\\\n", " "))
                files = [t for t in tokens if t.startswith("tests/") and t.endswith(".py")]
                return files, dict(step.get("env") or {})
    raise SystemExit(f"no step named {STEP_NAME!r} in .github/workflows/ci.yml")


def main() -> int:
    files, step_env = ci_unit_step()
    if not files:
        raise SystemExit("CI's unit-test step lists no test files -- refusing to report success")
    env = dict(os.environ)
    for key, value in step_env.items():
        env[key] = str(value).replace("${{ github.workspace }}", str(REPO))
    cmd = [
        sys.executable,
        "-m",
        "pytest",
        *files,
        "-q",
        "-p",
        "no:warnings",
        "-p",
        "no:cacheprovider",
    ]
    if importlib.util.find_spec(
        "pytest_timeout"
    ):  # CI passes --timeout=120; not every dev env has it
        cmd.append("--timeout=120")
    print(f"CI unit-test step: {len(files)} files", flush=True)
    return subprocess.call(cmd, cwd=REPO, env=env)


if __name__ == "__main__":
    raise SystemExit(main())
