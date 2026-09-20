# -*- coding: utf-8 -*-
"""W03: the outcome decomposition reproduces the published numbers, offline.

Six waves were judged on a collapsed metric that refusing more improves. These tests pin the two
halves separately, so a seventh wave cannot report progress on the collapsed one.
"""

from __future__ import annotations

import ast
import importlib.util
import sys
from pathlib import Path

import pytest

pytestmark = pytest.mark.unit

REPO = Path(__file__).resolve().parent.parent
SCRIPT = REPO / "scripts" / "decompose_outcomes.py"


def _load():
    spec = importlib.util.spec_from_file_location("decompose_outcomes", SCRIPT)
    mod = importlib.util.module_from_spec(spec)
    sys.modules["decompose_outcomes"] = mod
    spec.loader.exec_module(mod)
    return mod


do = _load()
_HAVE_READS = (do.PHASE0 / "phase0_read.jsonl").is_file() and (
    do.PHASE0 / "phase0_run6_read.jsonl"
).is_file()


def test_exact_mcnemar_matches_known_values():
    # 9 vs 11 discordant: not distinguishable from a coin. 21 vs 8: clearly not.
    assert do.mcnemar_exact(9, 11) == pytest.approx(0.8238, abs=1e-3)
    assert do.mcnemar_exact(21, 8) == pytest.approx(0.0241, abs=1e-3)
    assert do.mcnemar_exact(28, 17) == pytest.approx(0.1349, abs=1e-3)
    assert do.mcnemar_exact(0, 0) == 1.0
    assert do.mcnemar_exact(5, 5) == 1.0  # capped, never above 1


@pytest.mark.skipif(not _HAVE_READS, reason="hand-read artifacts not present")
def test_the_six_waves_improved_declining_and_not_answering():
    result = do.decompose()
    ans = result["first_to_last"]["answer"]
    dec = result["first_to_last"]["decline"]
    both = result["first_to_last"]["either"]
    assert (ans["gained"], ans["lost"]) == (9, 11)
    assert ans["p"] > 0.5, "correct answering did not move — that is the finding"
    assert (dec["gained"], dec["lost"]) == (21, 8)
    assert dec["p"] < 0.05, "correct declining did move"
    assert (both["gained"], both["lost"]) == (28, 17)
    assert both["p"] > 0.05, "the collapsed metric hides which half moved"


@pytest.mark.skipif(not _HAVE_READS, reason="hand-read artifacts not present")
def test_per_run_counts_are_the_published_ones():
    per_run = do.decompose()["per_run"]
    assert [r["answer"] for r in per_run] == [19, 10, 14, 16, 19, 17]
    assert [r["decline"] for r in per_run] == [21, 24, 37, 36, 38, 34]
    assert [r["weird"] for r in per_run] == [107, 113, 96, 95, 90, 96]
    assert all(sum(r.values()) == 147 for r in per_run)


def test_flip_rate_is_seeded_and_bounded():
    a = {str(i): "WEIRD" for i in range(100)}
    b = dict(a)
    for i in range(20):
        b[str(i)] = "GOOD_ANSWER"
    first = do.flip_rate(a, b)
    again = do.flip_rate(a, b)
    assert first == again, "a bootstrap interval must be reproducible"
    assert first["flips"] == 20 and first["rate"] == pytest.approx(0.2)
    assert first["lo"] <= first["rate"] <= first["hi"]
    identical = do.flip_rate(a, dict(a))
    assert identical["rate"] == 0.0 and identical["hi"] == 0.0


def test_the_tool_cannot_reach_the_network():
    """Not a runtime guard: the module imports nothing that can open a socket."""
    tree = ast.parse(SCRIPT.read_text(encoding="utf-8"))
    imported = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            imported.update(a.name.split(".")[0] for a in node.names)
        elif isinstance(node, ast.ImportFrom) and node.module:
            imported.add(node.module.split(".")[0])
    forbidden = {"socket", "urllib", "http", "requests", "httpx", "aiohttp", "redis", "asyncio"}
    assert not (imported & forbidden), imported & forbidden
