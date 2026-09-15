"""A sealed Gate A question must never appear in anything used to build or tune the system (V12-29).

The set is held out only while no fixture, prompt, probe case or demo file contains its text.
Once one does, the run measures a question somebody fixed towards.

On failure this names the FILE and a short hash of the question, never the text. Printing the
question would unseal it to whoever reads the test output.

Skipped when the set has not been drawn (a fresh clone: the set is gitignored until its run).
"""

import hashlib
import json
import re
from pathlib import Path

import pytest

pytestmark = pytest.mark.unit

REPO = Path(__file__).resolve().parent.parent
SEALED = REPO / "tasks" / "gate_a" / "sealed_set.jsonl"
MIN_CHARS = 20  # shorter normalised questions collide with ordinary prose


def _norm(text: str) -> str:
    return " ".join(re.sub(r"[^a-z0-9]+", " ", (text or "").lower()).split())


def _surfaces():
    yield from (REPO / "tests").glob("*.py")
    for tree in ("orchestrator", "shared"):
        yield from (REPO / tree).rglob("*.py")
        yield from (REPO / tree).rglob("*.yaml")
    for rel in (
        "scripts/regression_cases.json",
        "docs/demo_question_bank.jsonl",
        "docs/demo_script_questions.txt",
    ):
        if (REPO / rel).is_file():
            yield REPO / rel


def test_no_sealed_question_appears_in_a_fixture_prompt_or_probe():
    if not SEALED.is_file():
        pytest.skip("sealed Gate A set not drawn here")
    sealed = [
        _norm(json.loads(line)["question"])
        for line in SEALED.read_text(encoding="utf-8").splitlines()
        if line.strip()
    ]
    sealed = [q for q in sealed if len(q) >= MIN_CHARS]
    here = Path(__file__).resolve()
    leaks = []
    for path in _surfaces():
        if path.resolve() == here:
            continue
        body = _norm(path.read_text(encoding="utf-8", errors="replace"))
        for q in sealed:
            if q in body:
                tag = hashlib.sha256(q.encode()).hexdigest()[:10]
                leaks.append(f"{path.relative_to(REPO)} contains sealed question {tag}")
    assert not leaks, "\n".join(leaks)
